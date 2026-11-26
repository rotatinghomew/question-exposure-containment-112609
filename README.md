# 题库暴露处置与既有答卷的证据资格

校招考试组按岗位登记题包、语言版本和补测能力，发放网关提供实际取题记录。

`materials/registry.json` 是业务登记演练资料，`materials/partner.json` 是合作方的合成报文。字段和状态含义见 [交换资料](docs/exchange.md)。本地合作方接入端只处理来源报文与送达回执，便于业务服务联调。

使用 Python 3.11.2，依赖均为标准库。从项目根目录运行以下命令启动本地合作方。

```sh
python3 partner_lab.py --port 8091
```

在另一个终端可以访问 `http://127.0.0.1:8091/health` 检查是否已经启动。默认使用项目根目录的 `partner.sqlite3` 保存合作方状态。可传入 `--database` 选择单独的文件，或用 `--source` 载入另一组合成交换资料。

使用内置测试库检查合作方报文分页、迟到回执和本地重启。

```sh
python3 -m unittest discover -s tests -v
```
