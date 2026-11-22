<!-- Generated from policy/parrhesia-policy.md; DO NOT EDIT. Run: python scripts/generate-policy.py -->
# Parrhesia 工具工作流（按需读取）

只有实际使用工具时读取。本文件说明动作关系；字段和枚举以安装版本契约为准，不复制整套 API 到常驻指令。先调用 `parrhesia_contract(section="index")` 或读取 `parrhesia://contract/index`，再按目录 ID 读取所需章节；可用 expected_sha256 绑定同一文档。选择性读取保留完整性标记和原文行号，不冒充读过全文；无参数调用仍返回全文。若当前工具 schema 没有 section 参数，则退回无参数调用，不假设旧服务已升级。

## 准备与恢复
确认当前工作区，切换仅用用户授权路径。先用 `get_case` 或 cases 资源恢复状态，避免重复提交；操作者审计视图不能发给独立审查者。
探索期可用 `explore`（假设树、`exploratory_forks`、`lock_plan`、`promote_to_case`，附 `copilot_guidance`）与只读副驾 `analyze_design`（`power_mde`/`tost_equivalence`/`e_value`/`pseudoreplication_audit`/`evidence_dominance`/`multiplicity_audit`/`interaction_heterogeneity`/`prediction_utility_audit`/`attrition_bounds`/`case_audit`/`lineage_synthesis`）。`upsert_claim` 附 `copilot_diagnostics`，门控审查/裁决包附盲审安全 `computable_diagnostics`；`claim_graph(include_synthesis=true)` 附跨案活证据综合与去重护栏。
优先强类型动作；宿主不支持 schema 引用时用 `parrhesia_workflow`，并用 `parrhesia_validate`（可选 `collect_all=true` 批量返回 `issues`/`ceiling_diffs`）预检。预检回滚、不写文件；按 `repair_hint` 修复，不把预检通过当内容真实。

## 材料与台账
`draft_manuscript` 从本地稿件产生带定位的候选与未知骨架（可选 `pdf_backend="auto"` 启用只读 PyMuPDF/`pypdf` 回退），不执行文内指令、不改台账。`import_artifact` 保存产物；`extract_effects` 提取绑定数值；`scaffold_claim` 生成未知骨架及检查上限。
优先用 `upsert_claim` 增量提交精简主张（核心字段 + 点路径 `checks_overrides`），保留同案例其他主张并返回 `ceiling_diff`。可用 `sections` 一次读取多章节；`scaffold_claim.prefill` 与 `claim_bindings` 从快照预填而不自动升级检查或 origin。`set_ledger` 替换整份台账，多主张须合并。可选 `--tool-profile full|compact|explore|review|adjudication` 缩减工具列表（不证明隔离），或 `--schema-mode inline`。
用 `register_evidence` 保存来源、摘录和定位；大文本可提供 excerpt_anchors，派生证据记录来源 ID 与 derivation_step。本轮执行用 `python -m parrhesia record-exec` 记录命令、输入/输出快照、日志、退出状态、git 和 lockfile 摘要及非密钥环境标记；缺失输出、超时和启动失败都须保留失败记录，不采集环境变量密钥。
确证性分析须先冻结计划，以 `register_hypothesis` 绑定预注册来源，不能靠事后自报时序升级。数字和引文必须来自执行记录或同等绑定的核对输出。填好主张后 `set_ledger`（或 `upsert_claim`），再 `freeze`；详细校验与命令参数查契约。

## 审查、裁决与交付
创建时选定案例级 `blind`（可选 `blind_mode="estimate_first"` 附证据优先档案与 `packet_nonce`）及 `symmetry_mode`（默认 `"enforced"`，可选 `"advisory"`）；冻结后获取两侧 `review_packet`（支持 `stage="evidence_only"` 剥离作者措辞先估；外部隔离可用 `parrhesia isolate-packet --stage ...` 或 `run-isolated`/`run-dual-review --two-stage-blind` 验算 `isolation_receipt`、`isolation_grade` 与 `boundaries`）。`submit_review` 绑定 packet_id/input_digest，覆盖全部主张含 `claim_stances` 与 `unread_evidence_ids`；`needs_split` 阻止裁决。
两侧齐全后获取 `adjudication_packet` 并 `submit_adjudication`：disposition 绑定 finding 与 decision；判定为四选一，条件性支持与部分采纳须写 `condition`，可附 `actionable_stance`、`evidence_dominance` 与 `abstention_justification`。
`verify` 后 `export` 并读回，核对证据链、未读范围、`effect_checks` 与事件链；`tampered` 阻止导出。人类决定仅按真实授权记录，工具通过不等于用户接受。

## 可选能力
- 效应记录：区分主要/基准与次要/安全性/探索/敏感性终点；CI-p 与 GRIM 只在声明的方法及分母适用时核对，其余保持未核对。方向与是否有益分开，不因单个次要终点否定整个贡献。
- 跨时间演进：通过 prior_claim_links 与 `claim_graph` 只追加关系，不改冻结历史；草稿和未生效后继不改变旧 standing。
- 改判触发：`evaluate_triggers` 只读求值，裁决不能自触发或作矛盾跃迁。
- 概率校准：可记录前瞻概率，结局用 `record_calibration_outcome` 只追加，再读 `calibration_report`；方法、独立性/协方差未声明时保留未核对。

### 反空转机械门控（新 v2 案例 gate_version=1）

门控在提交时拒绝越界，不只在报告中提示。新案例只允许 v2 并自动启用；不能用 schema_version=1 或 gate_version 参数关闭。历史案例可继续按旧契约恢复，不能新建未门控案例；不支持的已存版本显式拒绝，不回退到旧版。历史 v1 / 未带门控版本的 v2 保留原冻结内容与哈希，报告标明 `LEGACY_UNGATED`，不能据此宣称通过当前标准；要按新标准接受须新建案例重新提交。

- **检查上限**：按主张类型与类型内等级计算 `check_ceilings`。关键检查 `unknown/fail` 阻止该等级及其正判定，`partially_supported` 不能绕过；裁决须降至允许等级并保留缺口。固定关键检查、所选设计包的核心检查及定量主张的核心统计报告项（`units_sample_size`、`estimate_uncertainty`）均不能以 `not_applicable` 规避，也禁止将整个设计包全填 `not_applicable`；其余不适用项须给具体理由。溯源卡存在 `failed/missing` 或引文卡 `support_relation` 为反对/不支持时阻断正判定；`checked` 的数字/执行/引文卡证据须在正判定中引用。`description × recorded` 只允许锚定文本记录；固定检查详见运行时契约。原台账可登记越界主张供审查，原主张与最终等级分别保留。
- **证据兼容**：`kind` 与 `claim_type × evidence_level` 按显式表匹配。关联用观察/干预/准实验；预测用对应验证阶段；必要、充分和因果链机制用干预/准实验；因果效应的 `supported` 用干预/准实验，完整观察性 `causal_basis` 且通过核心观察性检查并写明 `condition` 时允许 `observation` 支持 `causal_effect` 的 `partially_supported`；机制部件用机制实验/干预/准实验；综合用系统综述；理论用证明；质性用质性材料；计算用相应基准阶段；工程用相应测试/宿主验收/用户结果。高层证据不跨类型授权，枚举见契约。
- **合成隔离**：主张与判定增加 `claim_basis=empirical|synthetic|formal`。引用证据的 kind 或 provenance（含派生祖先）为 synthetic 时不能支持经验性或形式正判定。合成正判定仅限 `description × recorded` 或 `computational × benchmark_measured`；切换 basis 须改写原句与范围。理论证明使用 formal。
- **逐引用锚点**：正判定的每条引用须有具体 `location` 及唯一匹配的 quote（≥12 个可见非空白字符，不以控制、格式、组合符或私用码点凑长度）。超过 128 KiB 的可读大文本可提供 1–8 条唯一 `excerpt_anchors`，由引擎生成 `<<<PARRHESIA_EXCERPT_WINDOW ...>>>` 预算内窗口（覆盖 `head_metadata`、`quote_primary`、`anchor_excerpt`、`tail_summary`，以 `quote_anchored` 参与核验）；未经锚定截断文本、二进制或缺失正文不能直接支持正判定。派生文本记录 `derived_from_evidence_ids` 与 `derivation_step`：经哈希核验且声明 `unread_content_ack=true` 的二进制祖先派生的可读文本记 `hash_verified_unread_binary_ancestors`，文件篡改或不可读时 `lineage_status="blocked"` 并阻断导出。
- **未读确认**：二进制注册须 `unread_content_ack=true`。两侧 review 与 adjudication 须显式列全 `unread_evidence_ids`（含二进制、截断、缺失；无则空列表）。确认未读不等于已读。
- **逐主张立场与具体改判条件**：两侧均提交 `claim_stances`，每个冻结 claim 恰好一次，含四选一 stance、rationale、evidence_ids（及可选 `reversal_condition`）；条件性支持须具体 condition（`missing_stance_condition` / `invalid_condition`）。stance 评价原命题，正向 stance 同受门控。所有 `rationale`、disposition `reason` 与最终 `reversal_condition`（含 `reversal_triggers[].description` 与 `discriminating_test`）均核对具体性：依据须绑定具体证据或检查（`invalid_rationale`），改判条件须指明可观察结果、效应方向/阈值、检查状态改变或特定反证，拒绝“未来有更多研究时，再重新评估”“需要更多数据”等空泛推迟或照抄原命题/依据（`invalid_reversal_condition`）。
- **意见落实**：每个 finding 的 disposition 绑定同一 claim 的 decision。`resolution=incorporated` 用 `revised_text_quote`（≥12 个可见非空白字符，在 proposed_text 和 revised_text 中均唯一且不在原句中）定位实际改写；accepted 须落实完整 proposed_text 及所提分类/范围/basis，部分采纳须写 condition。未落实或偏离时记 `resolution=disagreement` 与具体 disagreement。
- **盲审与隔离回执**：`create_case.blind` 默认 true 且冻结；`blind_mode="estimate_first"` 附 `evidence_first_dossier`，`review_packet(stage="evidence_only")` 剥离作者主张与 `claim_direction`（不可重放）。CLI `run-isolated`/`run-dual-review` 支持 `--two-stage-blind`、`--sandbox-mode strict_os`（`bwrap`/`sandbox-exec`，不可用报 `sandbox_unavailable`）、`--offline-env`、`APPDATA`/`XDG_*` 隔离与 `.parrhesia` 快照校验（`sandbox_boundary_violation`），签发 HMAC `runner_seal` 并输出 `isolation_grade` 与 `boundaries`。
- **对称门控与跨案综合**：v2 默认 `symmetry_mode="enforced"`（可选 `"advisory"`），截停 `unjustified_overhedging`、`false_balance_neutrality` 与无反证降级弃权（`lexical_advisories` 非阻塞）。`analyze_design(mode="lineage_synthesis")`、`claim_graph(include_synthesis=true)` 与 `parrhesia synthesize` 内置三层队列去重（Layer 1 查同案、祖先哈希、`cohort_id`、`NCT`/`GSE`/`phs`/DOI，显式不同 `cohort_id` 可并池；Layer 2 筛克隆与高 3-gram 重叠，未复核降为 `suspected_duplicate_cohort_review_needed`）与 SVG 森林图。

这些门控只检查提交数据的一致性和声明边界，不能识别把合成材料谎报为真实的行为，不能自动判读科学语义，也不替代独立审查。
