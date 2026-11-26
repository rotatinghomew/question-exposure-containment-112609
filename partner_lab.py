"""在本地提供合作方的合成报文、提交回执和可控制的送达次序。"""
import argparse
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def encode(body):
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Lab:
    def __init__(self, source, database):
        self.source = json.loads(source.read_text(encoding="utf-8"))
        self.database = database
        with closing(self.connect()) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY, phase INTEGER NOT NULL);
                INSERT OR IGNORE INTO clock VALUES (1, 0);
                CREATE TABLE IF NOT EXISTS operations (
                    action TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL,
                    visible_at INTEGER NOT NULL, status TEXT NOT NULL, final_status TEXT NOT NULL,
                    done_at INTEGER NOT NULL, PRIMARY KEY (action, request_id)
                );
            """)

    def connect(self):
        return sqlite3.connect(self.database, timeout=5, isolation_level="IMMEDIATE")

    @staticmethod
    def phase(conn):
        return conn.execute("SELECT phase FROM clock WHERE id=1").fetchone()[0]

    def advance(self, steps):
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE clock SET phase = phase + ? WHERE id=1", (steps,))
            return {"phase": self.phase(conn)}

    def feed(self, stream, after, size):
        if stream not in self.source["feeds"]:
            return 404, {"error": "未登记的来源"}
        with closing(self.connect()) as conn:
            phase = self.phase(conn)
        available = [
            {key: value for key, value in item.items() if key != "visible_at"}
            for item in self.source["feeds"][stream]
            if item["sequence"] > after and item["visible_at"] <= phase
        ]
        page = available[:size]
        cursor = page[-1]["sequence"] if page else after
        return 200, {"items": page, "cursor": cursor, "has_more": len(available) > size}

    @staticmethod
    def receipt(conn, action, request_id, phase):
        row = conn.execute(
            "SELECT payload, visible_at, status, final_status, done_at "
            "FROM operations WHERE action=? AND request_id=?", (action, request_id)
        ).fetchone()
        if row is None or phase < row[1]:
            return 404, {"error": "目前没有可出具的回执"}
        payload, _, status, final_status, done_at = row
        return 200, {"action": action, "request_id": request_id, "target": json.loads(payload)["target"],
                     "status": final_status if phase >= done_at else status}

    def lookup(self, action, request_id):
        if action not in self.source["actions"]:
            return 404, {"error": "未登记的操作"}
        with closing(self.connect()) as conn:
            return self.receipt(conn, action, request_id, self.phase(conn))

    def submit(self, action, request_id, body):
        profile = self.source["actions"].get(action)
        if profile is None:
            return 404, {"error": "未登记的操作"}
        if not isinstance(body.get("target"), str) or not body["target"]:
            return 400, {"error": "target 必须是非空字符串"}
        if sorted(body) != sorted(["target", *profile["fields"]]):
            return 400, {"error": "报文字段与操作约定不同"}
        serialized = encode(body)
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                phase = self.phase(conn)
                known = conn.execute(
                    "SELECT payload FROM operations WHERE action=? AND request_id=?", (action, request_id)
                ).fetchone()
                if known:
                    if known[0] != serialized:
                        return 409, {"error": "同一请求号不能改变报文"}
                    code, receipt = self.receipt(conn, action, request_id, phase)
                    return (503, {"error": "回执暂不可用"}) if code == 404 else (code, receipt)
                config = {**profile["default"], **profile.get("overrides", {}).get(body["target"], {})}
                if phase < config.get("available_at", 0):
                    return 503, {"error": "回执暂不可用"}
                conn.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                    (action, request_id, serialized, phase + config.get("reveal", 0), config["status"],
                     config["final_status"], phase + config.get("finish", 0)),
                )
                code, receipt = self.receipt(conn, action, request_id, phase)
                return (503, {"error": "回执暂不可用"}) if code == 404 else (code, receipt)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def emit(self, code, body):
        data = encode(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def parts(self):
        url = urlsplit(self.path)
        return [unquote(p) for p in url.path.split("/") if p], parse_qs(url.query)

    def do_GET(self):
        parts, query = self.parts()
        lab = self.server.lab
        if parts == ["health"]:
            self.emit(200, {"partner": lab.source["name"]})
        elif len(parts) == 2 and parts[0] == "feeds":
            try:
                after = int(query.get("after", ["0"])[0])
                size = int(query.get("limit", ["20"])[0])
                if after < 0 or not 1 <= size <= 100:
                    raise ValueError
            except ValueError:
                self.emit(400, {"error": "游标应非负，每页限 1 至 100 条"})
                return
            self.emit(*lab.feed(parts[1], after, size))
        elif len(parts) == 3 and parts[0] == "operations":
            self.emit(*lab.lookup(parts[1], parts[2]))
        else:
            self.emit(404, {"error": "路径不存在"})

    def do_POST(self):
        parts, _ = self.parts()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 65536:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            self.emit(400, {"error": "需要有效的 JSON 对象"})
            return
        if parts == ["lab", "advance"]:
            steps = body.get("steps")
            if type(steps) is not int or not 1 <= steps <= 100:
                self.emit(400, {"error": "推进量应为 1 至 100 的整数"})
            else:
                self.emit(200, self.server.lab.advance(steps))
        elif len(parts) == 3 and parts[0] == "operations":
            self.emit(*self.server.lab.submit(parts[1], parts[2], body))
        else:
            self.emit(404, {"error": "路径不存在"})


def create_server(host, port, source, database):
    server = ThreadingHTTPServer((host, port), Handler)
    server.lab = Lab(source, database)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("materials/partner.json"), help="合作方报文")
    parser.add_argument("--database", type=Path, default=Path("partner.sqlite3"), help="本地合作方状态")
    parser.add_argument("--port", type=int, default=8091, help="本地端口")
    args = parser.parse_args()
    with create_server("127.0.0.1", args.port, args.source, args.database) as server:
        print(f"合作方接入端点 http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
