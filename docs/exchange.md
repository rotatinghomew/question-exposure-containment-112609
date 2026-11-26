# 题库暴露处置与既有答卷的证据资格的交换资料

校招考试组按岗位登记题包、语言版本和补测能力，发放网关提供实际取题记录。

family 是已登记的等价题组，investigation 的 items 是本次报告实际覆盖的题，reclassification 是对既有暴露范围的修订。允许等价范围以该条调查材料为准，不能仅凭语言简称推测。allowed_substitutes 记题包允许用于同能力的替代证据。
issue-pack 的 target 是场次，items 是发放的题版本号列表。prepared 只表示网关已接手，fetched 才表示题已经交付。issue-makeup 使用原场次或教务补测编号作 target，registered 是补测已登记。原场次答卷引用以 gateway 的 answers 为准。

已开通的来源流为 `gateway`、`investigation`。除 target 外，各操作的报文字段如下。

- `issue-pack` 的提交字段为 `pack_version`、`items`。
- `issue-makeup` 的提交字段为 `package`、`original_sitting`、`abilities`。

## 本地联调端

地址默认是 `http://127.0.0.1:8091`。交换格式为 UTF-8 JSON。来源编号的作用域由上面的业务约定定义。各来源的 `sequence` 只表示该来源的送达次序，从 1 开始，和业务时刻无关。

- `GET /feeds/{stream}?after=0&limit=20` 返回当前可见的 `items`、`cursor` 和是否还有可见页的 `has_more`。`after` 为上次已收到的序号，`limit` 可取 1 至 100。每一条有 `kind` 和 `data`。按同一位置重读可以看到原报文。
- `POST /operations/{action}/{request_id}` 提交该操作。JSON 中带 `target` 及该操作约定的字段。请求号在同一操作内唯一，重送相同随附值不会执行第二次，改变报文则返回 409。请求号和来源名采用 URL 单段，避免斜杠。
- `GET /operations/{action}/{request_id}` 查询回执，正面回执有 `action`、`request_id`、`target` 和 `status`。提交返回 503 时，外方可能已受理。查询暂时返回 404 只有“查不到证明”的含义，业务最终拒绝以相应明确回执为据。
- `POST /lab/advance` 接受包含正整数 `steps` 的对象。它只推进联调端送达阶段，不修改任何业务日期。阶段从 0 开始。清空联调应另用一个数据库文件，保留该文件重启可继续查询既有回执。

`materials/partner.json` 内的 `feeds` 记录可供演练的来源报文，`visible_at` 是联调的最早送达阶段。`actions` 记录提交字段与外方回执。各操作可以为特定 `target` 单独设定延迟等传输条件。目录内资料均为合成内容。
