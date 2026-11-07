# 从 0.1.0 升级到 0.2.0

0.2.0 改变新案例的输入契约。软件版本 `0.2.0`、`schema_version=2`、`gate_version=1` 和 Agent Plugins 格式 `1.0.0` 分别管理软件、主张结构、机械门控与分发格式；不要一并替换。

## 文件与宿主

1. 停止旧 MCP 进程，保留旧安装目录、宿主配置以及项目的 `.parrhesia` 数据目录备份。将新版 ZIP 解压到新目录，不覆盖正在运行的副本。
2. 从新版目录执行 `python scripts/generate-policy.py --check` 与 `python -m parrhesia contract`。配置宿主使用新版入口；Grok 适配可从新版目录运行 `python scripts/install-grok.py --project C:\YourProject`，其备份/合并行为见 [接入说明](grok-integration.md)。不把本地 ZIP 构建等同已更新任何宿主安装。
3. 只替换目标项目已有的 Parrhesia 规则块，保留其他规则；规则源为 `policy/parrhesia-policy.md`，派生模板不要手改。ChatGPT 模式从新版运行 `scripts/prepare-chatgpt.py`，使用新目录保存套件，不覆盖旧交接记录。
4. 重启后核对 MCP `initialize` 的 `serverInfo.version` 为 `0.2.0`，读取 `parrhesia_contract` 和当前工作区，再读取已有 case 状态。仅版本/握手正确不证明宿主双审独立性。

## 新请求字段对照

| 旧请求习惯 | 0.2.0 新案例要求 |
|---|---|
| create_case 显式 schema_version=1 | 新建只允许 2；省略时默认为 2，门控自动启用，不能关闭 |
| claim / decision 的 level | claim_type、该类型支持的 evidence_level、scope；另有 claim_basis |
| finding 的 proposed_level | proposed_claim_type、proposed_evidence_level、proposed_scope、proposed_claim_basis |
| 只登记检查摘要 | 七项 checks；适用 design_packages；八项 statistical_report；四类 provenance_cards；适用 causal_basis |
| evidence_ids 有引用就可正判定 | 每条正向引用须有符合长度/唯一性条件的 quote 和具体 location；kind 与主张兼容；检查无关键缺口 |
| review findings=[] 即完成 | 两侧仍需逐 claim 的 claim_stances；全部未读 evidence IDs 显式确认；条件性 stance 填真实 condition |
| accepted 标签表示已改 | disposition 绑定同一 claim 的 decision；incorporated 定位实际新增改写，否则 explicit disagreement；partial 填 condition |
| 每次 review_packet 单独选择 blind | create_case 的 blind 默认 true，案例级冻结，不能单次覆盖 |
| 二进制登记即已读 | 注册时 unread_content_ack=true；两侧 review 与 adjudication 列全 unread_evidence_ids；不可直接用于正判定 |

表格是迁移导览，完整必填字段、枚举和错误码以 [当前契约](contract.md) 及运行时返回为准。不要用批量字符串替换把旧等级变成新等级：如旧 causal 必须重新区分因果效应、必要性、充分性，并检查实际设计与证据。无法确认时保留 UNKNOWN / 证据不足。

[v2 缺口示例](examples/claim-v2-unknown.json)展示未知状态如何登记，不是可获正判定的完整证据。`python -m parrhesia demo --output artifacts/demo-0.2.0` 可生成完整合成流程与调用序列（目录须不存在）；示例不构成真实科学证据。

## 已有记录

已有 v1 或未门控 v2 的冻结内容与摘要不改写，可按历史契约恢复，输出标 `LEGACY_UNGATED`。该标记意味着未经过当前门控，不能据此报告满足新版标准。要使用新版门控，应新建 v2 案例、重新登记实际证据并显式关联旧 case ID；不复制旧审查时间、判定或用户接受为新证据。

未知版本返回 `unsupported_contract_version` 时停止该记录的操作，先使用匹配版本读取；不要手改数据库版本号绕过检查。保留旧安装与备份便于恢复，但不能用旧版入口新建案例再声称通过新版门控。

## 交付边界

文字模板模式没有本地运行时的机械拒绝保障。新 ZIP 包含源码、规则、模板、文档与测试，不含工作区数据库、私有配置、凭据、测试临时输出或旧安装环境。当前验证范围见 [0.2.0 核验记录](verification/release-0.2.0.md)。
