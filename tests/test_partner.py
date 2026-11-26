"""通过本地 HTTP 核对合作方报文和回执。"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from partner_lab import create_server


class PartnerTransportTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.source = self.root / "materials" / "partner.json"
        self.profile = json.loads(self.source.read_text(encoding="utf-8"))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "partner.sqlite3"
        self.opener = build_opener(ProxyHandler({}))
        self.start()

    def start(self):
        self.server = create_server("127.0.0.1", 0, self.source, self.db)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02})
        self.thread.start()
        self.addCleanup(self.stop, self.server, self.thread)

    @staticmethod
    def stop(server, thread):
        if thread.is_alive():
            server.shutdown()
            thread.join(timeout=2)
        server.server_close()

    def request(self, url, data=None):
        body = None if data is None else json.dumps(data).encode()
        request = Request(f"http://127.0.0.1:{self.server.server_port}{url}", data=body,
                          headers={"Content-Type": "application/json"})
        try:
            response = self.opener.open(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.code, json.load(response)

    def test_health_and_feed_pagination(self):
        self.assertEqual(self.request("/health"), (200, {"partner": self.profile["name"]}))
        for stream, events in self.profile["feeds"].items():
            with self.subTest(stream=stream):
                self.assertGreaterEqual(len(events), 2)
                phases = [event["visible_at"] for event in events]
                self.assertEqual(phases, sorted(phases))
                self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
                self.assertEqual(self.request(f"/feeds/{stream}?limit=1")[1]["items"][0]["sequence"], 1)
        self.assertEqual(self.request("/lab/advance", {"steps": 20}), (200, {"phase": 20}))
        for stream, events in self.profile["feeds"].items():
            cursor = 0
            received = []
            for incoming in events:
                code, page = self.request(f"/feeds/{stream}?limit=1&after={cursor}")
                self.assertEqual(code, 200)
                self.assertEqual(page["cursor"], incoming["sequence"])
                received.extend(page["items"])
                cursor = page["cursor"]
            self.assertFalse(page["has_more"])
            self.assertEqual(received, [{k: v for k, v in event.items() if k != "visible_at"} for event in events])

    def test_receipts_survive_restart(self):
        action, profile = next(iter(self.profile["actions"].items()))
        path = f"/operations/{action}/local-check"
        default = profile["default"]
        body = {"target": "transport-check", **dict.fromkeys(profile["fields"], "示例")}
        self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request(path, body)[1]["status"], default["status"])
        self.assertEqual(self.request(path, dict(body, target="other"))[0], 409)
        self.stop(self.server, self.thread)
        self.start()
        self.assertEqual(self.request(path)[1]["status"], default["status"])
        self.request("/lab/advance", {"steps": 20})
        self.assertEqual(self.request(path)[1]["status"], default["final_status"])
        self.assertEqual(self.request(path, body), self.request(path))

    def test_delayed_proof_is_queryable(self):
        overrides = [(name, profile, target, options) for name, profile in self.profile["actions"].items()
                     for target, options in profile.get("overrides", {}).items() if options.get("reveal")]
        self.assertTrue(overrides)
        for action, profile, target, options in overrides:
            with self.subTest(action=action, target=target):
                body = {"target": target, **dict.fromkeys(profile["fields"], "示例")}
                url = f"/operations/{action}/late-{target}"
                self.assertEqual(self.request(url, body)[0], 503)
                self.assertEqual(self.request(url)[0], 404)
                self.request("/lab/advance", {"steps": options["reveal"]})
                self.assertEqual(self.request(url)[1]["target"], target)


if __name__ == "__main__":
    unittest.main()
