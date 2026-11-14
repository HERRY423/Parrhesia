# 版本变更记录

## 0.3.0 — 2026-11-14（源码与限定宿主验收）

- 最新公开 CI：[提交 `9581eae`](https://github.com/HERRY423/Parrhesia/commit/9581eae170525e5d9d61586c78774085b2edaead) 的 [Windows / Ubuntu 运行](https://github.com/HERRY423/Parrhesia/actions/runs/43608255809)（Python 3.11）均为 **117 项全部通过、0 失败、0 跳过**，规则生成一致性检查通过。CI 固定安装 `jsonschema==4.26.0` 并检查可导入性，schema 快照禁止换行转换；两个平台均实际通过 `test_actual_official_schemas`，涵盖原始字节哈希、schema 标识与 Draft 2020-12 合法性、`plugin.json` / `mcp.json` 校验。
- 该结果为指定提交公开 CI 测试集的 `engineering × test_passed`，不替代历史测试计数、不扩大下述 `host_accepted` 范围或改变剩余限制。保留[原始失败运行](https://github.com/HERRY423/Parrhesia/actions/runs/43606318762)及[修复后仍跳过 1 项的运行](https://github.com/HERRY423/Parrhesia/actions/runs/43607137788)；本地原始记录不随文档提交。
- 将修复后的工作树与已安装的旧 0.2.0 明确区分；插件清单、Python 包、MCP 与报告版本统一为 0.3.0，具体字节身份以 RELEASE-MANIFEST.json 及 ZIP SHA-256 为准。验收绑定当时的冻结包；后续文档同步不重新打包或创建 GitHub Release。
- 包含 22 个 MCP 入口、结构化效应检查、纵向关系、结局校准及执行溯源实现；修复命题支持与获益方向混淆、统计检查适用范围、草稿提前生效、未绑定结局评分及复现覆盖率定义。
- 超时、启动失败和输出核验异常保留失败收据；不覆盖已有执行日志或历史证据。
- 启发式概率与显式概率分栏，复现点包含率与 known_truth 覆盖率分栏；废弃混合 proper_scores 与 z_drift 字段返回 null。未提供适用方法、计数定义或结局来源的旧记录保持 unassessed/pending，不自动迁移或补齐。
- 升级兼容性见 [0.3 迁移说明](docs/migration-0.3.md)。宿主验收必须绑定本构建并逐项记录，不能由安装成功或本地单元测试替代。

- 真实 Windows Codex 桌面 0.3.0 的四条工作流及原生文件符号链接拒绝已达到限定范围的 engineering × host_accepted。开发者模式开启后，符号链接原测试 1 通过、0 跳过；原生宿主拒绝链接且不改变证据/事件，普通文件正对照成功。
- 原始失败与权限跳过记录保留本地；测试、缓存、原始证据不随本次文档同步推送。范围不包含独立科学审查、其他宿主、全部 reparse point/竞态或 user_impact。详见 [0.3.0 宿主验收摘要](docs/verification/release-0.3.0.md)。

## 0.2.0 pilot — 2026-10-19

本版整理工作目录相对上一源码基线 `5da772b` 的累计更改。软件版本为 0.2.0；新案例使用 claim schema v2、gate_version=1；Agent Plugins 格式仍为 1.0.0。这些版本号表示不同契约，不能互换。

### 规则与科学内容

- 新增触发决策树与首行 `[L0]` / `[L1]` / `[L1-Explore]` / `[L2]` 标签，确立推荐日常工作流：探索阶段全程 `L1-Explore`（不建 L2 台账、不双审，维护轻量探索台账卡：最强对手、区分实验、成本、停止规则、杀死条件，标 `exploratory`）；确证阶段将 3–5 条核心主张送入 `L2`；写入图注、摘要或正文时执行完整双审。
- 仓库根 `AGENTS.md` 与 Codex 全局规则改为“精简块（compact block）+ 仓库开发规则”，不再常驻 41 KB 全文；将完整 L2 科学审查参考独立为 `skills/parrhesia-l2-reference/SKILL.md` 并纳入 `policy/parrhesia-policy.md` 的单源生成目标。
- 在 `parrhesia-review` 与 `parrhesia-l2-reference` skill 中明确溯源与预注册硬约束：数字和引文必须来自 `python -m parrhesia record-exec` 或 `reproducible-science`（`results` / `citations` / `repro`）钩子绑定的输出；确证性分析前须先用 `reproducible-science`（`prereg`）或预注册文件冻结分析计划，未事先冻结的一律标 `exploratory`。
- 明确审查者隔离配方：派子代理时只给对应角色的 `review_packet`（不继承起草历史）、尽量关闭持久记忆读取与历史检索，并在审查反馈及最终报告中记录审查者输入清单（`input_manifest`）。
- 统一平台指令优先级、不得编造数据/引文/执行/检索、证据不足不得包装成支持、用户期望不作为证据的底线。
- 以 `claim_type × evidence_level + scope` 替代统一五级阶梯，覆盖 12 种主张；拆分必要性与充分性。新增九个设计包、八项统计报告、引文/数字/执行/检索四类溯源卡及 `causal_basis`。
- 从唯一规则源生成仓库根 `AGENTS.md`、宿主模板、`parrhesia-review` 与 `parrhesia-l2-reference` Skill 及 ChatGPT 交接模板，持续检查生成文件漂移。

### 运行时与报告

- v2 台账、意见、裁决与报告同步采用新字段。加入 `claim_basis`，区分 empirical、synthetic 与 formal。
- 新增 `scaffold_claim` 工作流动作（生成全 `unknown` / `not_run` 的诚实主张骨架并返回门控上限）与 `python -m parrhesia record-exec` CLI 命令（执行本地命令、捕获日志并自动登记证据、生成 `execution` 溯源卡）。
- 新案例强制启用反空转与反橡皮图章门控：关键检查上限、设计包/统计报告禁止全填 `not_applicable`、反例引文卡拦截、已核对溯源卡必须被正向裁决引用、证据类型兼容、合成证据隔离、逐引用 quote/location、逐主张 stance、未读内容确认及案例级盲审。
- 经验因果无条件正判定（`supported`）限定为 intervention / quasi_experiment；观察性证据（`observation`）在具备完整 `causal_basis`、敏感度分析与显式不可检验假设条件（`condition`）时允许判为 `partially_supported`（条件性支持）。
- finding 与同一 claim 的 decision 绑定；落实采纳须有真实改写锚点，否则记录具体 disagreement。条件性立场和部分采纳要求实际条件，不能用 UNKNOWN 或不可见占位符替代。
- quote 至少 12 个可见非空白字符，须在完整可读文本中唯一；控制字符、组合附加符与私用字符不能凑长度。改写锚点须唯一且不在原句中。
- HTML/Markdown 展示原命题与修订命题、门控边界、逐主张立场、审查者输入清单（`input_manifest` / `reviewer_input_manifests`）、意见落实及未读状态。合成演示不再使用合成证据支持经验性正判定。

### 不兼容变更与历史恢复

- 停止通过生产接口新建 schema v1；返回 `legacy_creation_disabled`。新客户端须使用 v2，旧 `level` / `proposed_level` 不自动映射。
- 已保存的 v1 和未门控 v2 按历史契约恢复，保留原冻结内容与摘要，标记 `LEGACY_UNGATED`。不自动迁移、重新认证或复制旧接受状态。
- 未知 schema/gate 版本及布尔伪装版本被拒绝，不降级到历史路径；review_packet 不允许覆盖案例级 blind。
- 升级步骤与字段对照见 [0.2 升级说明](docs/migration-0.2.md)。

### 分发与验证

- 统一插件清单、Python 包与 MCP/HTML 报告版本；构建前校验三处版本一致，拒绝混版包。
- 新增 `python scripts/install-codex.py`（同步 Codex 全局精简块与 `parrhesia-l2-reference` skill，支持 `--check` 与自动备份）及 `python scripts/run-stage0-eval.py`（运行 Stage 0 24 个 L2 案例与 6 个 `L1-Explore` 探索案例机械评估，导出 `A` / `B-精简` / `B-全文` / `E` 四组对照提示词包）。
- 分发 ZIP 补入 LICENSE 和本变更记录；保留确定性构建、内容摘要、私有工作区排除和同名不同内容拒绝覆盖。
- 新增契约、门控绕过、历史恢复、Codex 同步、审查者输入清单及 Stage 0 对照套件回归测试（共 **111 项测试：110 通过、1 跳过、0 失败**）；当前执行结果见 [0.2.0 核验记录](docs/verification/release-0.2.0.md)与 [Stage 0 评估报告](docs/verification/stage0-evaluation.md)。

本版为本地 pilot 交付。工程测试、合成演示和 MCP 子进程启动不代表真实宿主上下文隔离、模型收益、科学有效性或用户接受。

## 0.1.0 pilot — 历史版本

提供 SQLite 案例状态机、证据快照、双向审查、裁决、人工介入、原子导出、宿主适配与单源规则生成的基础实现。历史执行与宿主记录见 [0.1.0 交付核验](docs/verification/release-readiness.md)，不作为 0.2.0 的重新验收记录。
