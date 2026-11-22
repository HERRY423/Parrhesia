<!-- Generated from policy/parrhesia-policy.md; DO NOT EDIT. Run: python scripts/generate-policy.py -->
# 可选外部集成

这些是适配说明，不是核心规则的依赖。只有当前任务已选择对应能力时才读取相关段落；不自动安装、搜索市场或外发资料。当前安装的接口与用户预算优先，旧脚本名仅供识别，不当作已安装或已执行。

## reproducible-science
若已安装，可用 results / citations / repro 绑定输出与来源，prereg 或其预注册检查冻结计划。历史钩子包括 unbound_numbers.py、unverified_quotations.py、unfrozen_plan_before_run.py、frozen_file_before_edit.py；实际可用名称以当前插件契约为准。
未安装时可使用 Parrhesia `record-exec`、来源快照和运行前冻结的预注册记录完成同样的溯源要求。不降低绑定标准，不将钩子通过等同科学有效或引文语义得到验证。

## 外部服务与 AgentMuxer 历史记录
优先已有适用工具，纯本地工作不做外部搜索。若主动选择 AgentMuxer，可在确认检索本身免费后使用 search_offerings；这不是所有用户必做步骤。
兼容已有 `.agentmuxer/ledger.md`：只追加、不迁移、不覆盖、不清零，不因改用供应商或重开会话重置任务额度。未使用该集成的项目沿用其既有消费记录，不要求创建这个目录。
默认单次 ≤ $0.10、同一任务累计 ≤ $1.00；已结算、未释放预留与状态未知均计入额度，未知费用不记成零。付费前读取历史，无法恢复则暂停新付费并继续无费用工作；超过用户额度先询问。
每次追加日期、用途、provider/method/path、invocationId、idempotencyKey、报价、maxCostMicros、状态、实际费用、备注；无供应商字段时标不适用或未知。可执行限额取单次上限与剩余额度较小者；无供应商限额不能把本地记录称作强制控制。
pending 或结果未知时用原调用 ID/幂等键查询，不重复购买；认证、余额、预算拒绝不循环重试。无恢复接口保留未知，不自行充值、订阅或提高后台预算。付费授权不授权上传、发布、发消息或删除，审查者和子代理不得付费。
