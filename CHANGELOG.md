# 版本变更记录

## 0.4.0 — 2026-11-21

### 两阶段盲审先估后看、沙箱边界强化与三层语义队列去重 — 2026-11-21

- **真实两阶段 `estimate_first` 单包交付工作流**：`review_packet` 新增可选 `stage="full"|"evidence_only"`（`evidence_only` 剥离 `question`/`draft`/`hypotheses`/作者主张文/类型等级与 `claim_direction`，绑定阶段专属 `packet_nonce` 且禁止重放为 `submit_review`）；CLI `isolate-packet` 支持 `--stage`，`run-isolated` / `run-dual-review` 新增 `--two-stage-blind` 在第一阶段独立沙箱校验锁定 `stage1_locked_estimates` 并计算 `stage1_estimate_sha256` / `stage1_transcript_sha256` 后再在第二阶段揭示完整盲审包，全部受工作区 HMAC `runner_seal` 约束。
- **OS 子进程隔离硬化与诚实边界声明**：扩展 `_RESERVED_RUNNER_ENV_KEYS` 拦截 `LD_PRELOAD` / `DYLD_*` / `PYTHONPATH` / `PYTHONSTARTUP` / 配置目录与协议变量透传；重定向 `APPDATA`/`LOCALAPPDATA`/`XDG_*` 至沙箱临时目录；临时输入以只读权限挂载并在运行后强制重校验与清理（Windows `chmod` 恢复）；新增 `--offline-env`（回环代理与 `HF_HUB_OFFLINE` 等离线环境变量）、`--sandbox-mode standard|strict_os`（Linux `bwrap` / macOS `sandbox-exec`，不可用时明确报 `sandbox_unavailable` 而不静默降级）、`close_fds=True` / 新进程组，以及 `.parrhesia` SQLite/WAL/`runner.key` 运行前后快照篡改检测（`sandbox_boundary_violation`）；`isolation_grade` 显式输出 `two_stage_blind_verified`、`os_sandbox`、`workspace_untouched` 与 `boundaries`（`enforced` / `not_enforced`）。
- **三层语义队列去重护栏（`parrhesia/synthesis.py`、`parrhesia/effects.py`）**：`effect_records` 新增可选 `cohort_id`（`mcp_schemas.py` 引入 `sha256` `$defs` 复用并将五档 MCP Schema 线缆体积均压缩至阈值内）；综合引擎新增 Layer 1（追踪 `derived_from_evidence_ids` 祖先快照 SHA-256、规范 `cohort_id`、standardized `NCT`/`GSE`/`phs`/DOI 识别并支持同文献多队列以不同显式 `cohort_id` 合法并池）与 Layer 2 嫌疑筛查（同 `n≥20` 同效应克隆及 ≥10 非套话实词且 3-gram Jaccard ≥ 0.65），生成 `suspected_cohort_overlaps` 与 `verify_cohort_independence` 并将未复核组从 `replicated_consistent` 收紧为 `suspected_duplicate_cohort_review_needed`，同步渲染至离线 HTML 与 Markdown/HTML 审阅清单。

### 科研复评回归修复 — 2026-11-21

- 跨案合并按已关联的终点、估计目标和尺度分组，使用各输入声明的区间覆盖率与可用方法。区间内含无效值时保留证据未定状态。
- 多表 Excel 预填绑定选表，LaTeX 摘要覆盖实际读取的子文件。稿件核验识别相似终点误配与零 p 值，校准评分要求数值与结局标签一致。
- 占优判断须有独立观测和直接检验，虚假平衡检查保留有效的范围限定。修复决策曲线的部署措辞、探索预检文件副作用和试评材料绑定。

### 五大核心错位修复与壁垒 2–4（方法学副驾驶 / 活体跨案综合 / OS 子进程隔离） — 2026-11-21

- **对称裁决与非空泛门控**：v2 默认 `symmetry_mode="enforced"`（保留 `"advisory"` 可选），在 `submit_adjudication` 截停缺依据免责（`unjustified_overhedging`）、虚假平衡（`false_balance_neutrality`）、无反证降级弃权（`unjustified_underclaim`/`unjustified_abstention`/`unjustified_downgrade`）与裸术语空泛改判；支持显式 `abstention_justification`、`actionable_stance` 与 `evidence_dominance`，并在 `symmetry_audit.py` 免除 McCrary/Egger/Schoenfeld 等诊断检验 `p >= 0.05` 的假阴性误报。
- **完整生命周期与极简接口**：MCP 扩展至 **28 个工具**（新增 `explore` 持久假设树与分叉追踪、`upsert_claim` 单主张编译并返回 `ceiling_diff`、`analyze_design` 只读可计算诊断）与 **5 种工具配置档**（`full`/`compact`/`explore`/`review`/`adjudication`），`parrhesia_validate` 支持 `collect_all=true`；`draft_manuscript` 新增可选只读 `pdf_backend="auto"`（默认严格保留 `"stdlib"`）。
- **主动型可计算方法学副驾驶（`parrhesia/methods.py`、`parrhesia/copilot.py`）**：`analyze_design` 扩展至 **11 种确定性纯标准库诊断模式**（含 `multiplicity_audit`、`interaction_heterogeneity` 含 Gelman-Stern 对照与 DerSimonian-Laird 元分析、`prediction_utility_audit` 含 EPV 收缩与 Vickers Net Benefit、`attrition_bounds` Manski 边界、全案 `case_audit` 及跨案 `lineage_synthesis`），并在 `upsert_claim`、`explore` 与盲审包自动挂载盲态安全诊断。
- **活体跨案综合与离线森林图报告（`parrhesia/synthesis.py`、`parrhesia/report.py`）**：只读汇总跨案例独立效应（SHA-256 数据集与 `reanalysis`/`correction` 去重卫兵）、累计 DerSimonian-Laird 轨迹检验与祖先 `reversal_triggers` 联级提醒，不篡改已冻结旧案；新增 `parrhesia synthesize` 生成包含静态 SVG 森林图的离线只读 HTML 报告（由 `Engine.read_workspace_cases_snapshot` 逐案核验冻结摘要与事件哈希链）。
- **OS 子进程物理隔离并发双审（`parrhesia/isolation.py`、`parrhesia/isolated_runner.py`）**：支持 `blind_mode="estimate_first"`（脱敏 `evidence_first_dossier` + `packet_nonce`）与 5 级 `isolation_grade`；新增 CLI `parrhesia run-isolated` 与并发编排 `parrhesia run-dual-review`，在剥离数据库与父环境变量密钥的独立临时沙箱中执行角色命令，以工作区内部 `.parrhesia/runner.key` 签发 HMAC `runner_seal` 并强验算规范 `packet_sha256`。
- **现实科研基准预演（`docs/evaluation/realistic-science-pilot-v1.json`）**：冻结 12 类现实陷阱与零开销 `dry-run` 预演；当前验证限于本地确定性测试、机械套件与零模型 `dry-run`，`0.4.0` 真实宿主 `host_accepted` 与外部付费大模型对照评测仍为 `not_run`。

### V0.4 发布阻塞修复 — 2026-11-17

- 统一两套 2×2 统计源在手动登记、改名文件及显式导入中的分类、synthetic 限制与公式绑定；历史完整快照重新核对内容类型，不改写冻结记录，不相容类别明确拒绝。
- SQLite 迁移、回填及完成标记在同一事务内提交；自动修复旧版空/残索引，保留案例、快照、事件和既有类别限制。未知数据库版本在写入前拒绝。新增 [0.3→0.4 迁移与恢复说明](docs/migration-0.4.md)。
- PDF 以 Catalog/Kids 页树和当前 Tf 字体读取，保留字体资源继承、页面及内容流边界；对无法确定的结构与编码明确拒绝。支持范围收窄为常规 xref、非增量 PDF，未读 XObjects 保留 partial。
- Fisher 用有界整数权重选尾；下溢/超限的 p 值省略并保留 issues，点估计单独处理溢出与下溢，不将非零值补成零。
- 新正反回归与原基线分开保存；原 PDF 测试中缺失字体/页树声明的 fixture 原件及失败归档，现行正例补齐合法结构，保留原功能断言。发布状态仍待修复后完整验收，不复用历史宿主或 CI 结论。

### 提示上下文修复与新案例验证 — 2026-11-17

- 词法提示区分主张端点与附带安全结果、历史研究与当前结果；保留主要安全性、混合主张和真实反证。引文继承已核对来源的上下文，不独立重复触发已排除的附带句。
- 为明确待采集结局、模型生成虚拟数据增加非阻断提示；不新增硬拒绝、不改科学判定，不将曲线近似、临床选择或调参词汇直接当作反证。
- 冻结 38 个开发者编写的新正反案例，另存 8 个语义边界诊断案例；原 Stage 0 案例和期望不变。版本化回归读数与原期望匹配数并列，公开新规则重叠，禁止将已暴露案例称为独立保留集。

### Stage 0 摄入回归与作者负担试评准备 — 2026-11-17

- Stage 0 增加独立 `ingestion-v1` 分栏与 `--mode ingestion`：10 个合成场景覆盖稿件、产物、效应、预填、完整审查/报告链路，以及缺失、错绑、源变动、跨行拼接、失败执行等边界；实际调用统计进入全套机械验收。
- 统一提示词拼接与体积测量，记录运行时版本、输入指纹和运行期间是否变化；刷新过时报告，原报告原样归档，冻结案例、种子、阈值不改写。纯文本未检出与误提示继续独立显示。
- 新增四组作者负担试评准备和缺失保留的记录汇总工具，区分结构化辅助、预填与跨上下文流程价值；仅准备，不调用模型、不推定真实收益。
- CI 保存 Stage 0 报告、测量 JSON 与错误日志；本地结果及边界见 [本轮核验](docs/verification/evaluation-modernization-2026-11-17.md)。

### 分发完整性与已有案例 HTML 报告 — 2026-11-17

- Codex 同步覆盖两个完整技能目录及入口的三份 references，沿用精简全局块；源文件预检、目标完整性检查、原始字节备份、事务回滚与幂等更新统一进入共享适配器。Grok / Antigravity 使用同一技能必需文件清单。
- 新增跨平台 CI wheel 验收：仓库外构建、全新 venv 离线安装、安装元数据定位契约、CLI / stdio MCP 启动与已有案例报告；保留失败日志和产物。构建隔离与运行隔离分别记录。
- 新增 `parrhesia report`，从已有裁定案例的 SQLite 只读快照生成 HTML，核对冻结摘要与事件链，保留未知和历史核验状态，不改案例、登记接受或覆盖旧报告。
- 使用与证据边界见[分发与验收](docs/distribution.md)；本地结果见[本轮核验](docs/verification/distribution-2026-11-17.md)。

### 宿主兼容、角色工具列表与证据预填 — 2026-11-16

- 新增 `scaffold_claim.prefill` 与 `draft_manuscript.claim_bindings`，从已登记快照按显式记录选择组装完整台账载荷；稿件绑定同时核对哈希、原文和位置。保留未选行、解析问题及未知设计/假说状态，不自动写台账。
- `parrhesia_contract.sections` 支持批量读取相关章节，去掉父子章节重叠；无参数全文与单章节读取兼容。
- `--schema-mode inline` 提供无引用的等价输入契约；默认完整 25 工具不变，`--tool-profile review|adjudication` 各提供五个相关工具。精简列表不是权限或隔离机制。
- 对重复字段按实际字节收益共享，精简 `extract_effects` 输出描述，完整数值返回与输入校验保留。宿主验收范围和实测大小见 [第三轮核验](docs/verification/protocol-load-2026-11-16-round3.md)。

### 契约按需读取与共享枚举 — 2026-11-16

- `parrhesia_contract` 增加可选 `section` 与 `expected_sha256`：目录、完整章节及版本绑定；无参数全文调用保持原返回结构。新增 `parrhesia://contract/{section}` 资源模板，不增加工具数量。
- 目录与摘录标明非全文、原文行号和文档指纹，文档变更或未知章节显式拒绝，不默默返回其他内容。服务启动提示与生成规则改为先读目录、再读相关章节。
- 仅对同一 inputSchema 内重复出现的领域枚举与 ID 列表使用命名引用；其余 24 个工具的输入约束展开后与本轮基线完全一致。详情见 [第二轮核验](docs/verification/protocol-load-2026-11-16-round2.md)。

### 协议与适配器一致性 — 2026-11-16

- 将清单、`pyproject.toml`、`parrhesia/__init__.py` 与运行时契约版本统一从已冻结的 `0.3.0` 推进至 `0.4.0`（保留历史 `0.3.0` 发布与宿主验收范围不变）；移除非 Grok 插件清单（`plugin.json`、`.codex-plugin/plugin.json`、`.claude-plugin/plugin.json`）中陈旧的 `"grok"` 关键词。
- 更新 Antigravity `SessionStart` 钩子（`scripts/antigravity_hook.py`）与安装器内置规则（`scripts/install-antigravity.py`）：按 SQLite `events` 序列号定位最近活跃案例而非仅按插入 `rowid`，并引导主机优先读取只读资源 `parrhesia://cases/{case_id}` 或强类型 MCP 工具（`parrhesia_get_case` / `parrhesia_verify`），仅在宿主不支持 `$defs`/`$ref` 时回退 `parrhesia_workflow`。
- 精确化 `parrhesia/provenance.py` 的 Git 脏污边界：对未跟踪的 `.agentmuxer/ledger.md` 与由本工作区 `.parrhesia/state.sqlite3` 记录且核对 SHA-256 一致的已导出 `.md` 报告不误判为源码脏仓库；未绑定或内容不符的文件及代码文件继续标脏。
- 补强 GitHub Actions CI（`.github/workflows/policy.yml`）：在现有规则生成检查与全量单测基础上，接入严格防泄露 CLI 检查（`check-eval-leakage.py --strict`）、Stage 0 机械套件（`run-stage0-eval.py --mode mechanical`）与确定性发布包/版本一致性校验（`build-release.py`）。

### 协议与规则减负 — 2026-11-16

- `set_ledger` 使用 schema 内部的 `$defs/$ref` 复用检查结构；展开后全部工具输入约束保持一致。`draft_manuscript` 的返回 schema 仅描述对象摘要，实际返回完整骨架，台账提交仍执行完整验证。
- 将常驻分档与底线、L2 科学参考、工具工作流、可选外部集成分层，继续由单一规则源生成；通用入口移除外部插件脚本名和计费路径，已有消费台账仍按可选集成说明保留。
- ChatGPT 套件随附按需 L2 参考，宿主适配器随 skill 目录携带参考文件；增加 schema 体积、引用解析、嵌套拒绝与安装引用检查。测量和验证范围见 [本地核验](docs/verification/protocol-load-2026-11-16.md)，不等同模型遵从度或宿主兼容性已实测提升。

### 稿件与产物导入及 P0 核心修复 — 2026-11-15

- 增加只读 `draft_manuscript`、草稿态 `import_artifact`、只读 `extract_effects`，共 25 个 MCP 入口；支持本地 Markdown/LaTeX/DOCX/Quarto 候选主张骨架与实际产物解析。范围和示例见 [使用说明](docs/artifact-ingestion.md)。
- 统计记录绑定源快照、表格行或混淆矩阵公式，核对 estimate、CI 和 p；缺失/错误行保留，不推定主终点、获益方向或科学有效性。
- `record-exec` 默认类别从 `benchmark` 改为保守推导的 `unknown`；新增 `--artifact` 与 `--metadata-file`。只有匹配成功运行的 changed output 才绑定实际产物，历史输出不冒充新执行。真实执行收据/绑定统计记录可作为补充来源，但正向研究类别仍须独立的相容来源支持。
- 本地修复 DOCX 标题与英文断句、统计 `Coef` 大小写与指标/CI 别名、`.tsv` 表结构嗅探、`effect_records` 保留 `notes` 与 GRIM 原文小数精度、非劣效边界与缺 CI 非显著拦截、`record_index` 解耦、`evidence_kind_restrictions` 索引与受限环境原子导出兜底。
- 本 `0.4.0` 发布未改写历史 `0.3.0` 发布或冻结证据；本地确定性测试与打包校验不代表 `0.4.0` 桌面宿主 `host_accepted` 实机验收、科研结论成立或外部大模型真实净收益已验证。

## 0.3.0 后续适配修复 — 2026-11-15

- Claude 专用清单内联声明 stdio MCP 服务，改用 `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA`，并提供 Python 3.11+ 解释器配置；通用 Agent Plugins 清单保持不变。
- Claude Code 2.1.325 严格清单校验及独立 MCP 子进程验证通过；真实 Claude 会话工作流仍待验收，不扩大原有 Windows Codex `host_accepted` 范围。已有冻结包身份与历史 CI 计数仍绑定原提交，不作为本次适配修改的验收。

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
