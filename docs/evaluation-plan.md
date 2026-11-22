# Parrhesia 评价方案

状态：**评价设计，尚未执行正式模型效果评估**。工程测试和合成演示另行记录，不能填入本方案的语义收益结果。使用真实研究材料、外部模型或付费调用之前，提交具体样本范围、数据去向、分析计划和费用上限，由用户批准。

2026-11-16 输入布局更新：规则改为按需参考后，静态 prompt 导出显式拼接适用材料。`B_full` 为通用入口 + L2 参考 + 工具工作流；`E_full_l2_workflow` 为主 skill + 精简入口 + L2 参考 + 工具工作流。导出标记 `policy_layout=layered-v1`，记录五个来源文件的字节数与 SHA-256，区别入口体积与实际拼接体积。新布局不可与历史单体规则运行合并统计；原有记录不改写，也不据此声称遵从度提高。正式比较须按新输入重新冻结计划。


2026-11-17 工程刷新：当前字节数来自本轮实际输入测量（详见 [核验记录](verification/evaluation-modernization-2026-11-17.md)），不是模型 token 数。历史报告已原样归档；`stage0-cases.json` 的种子、阈值与预期结果不改写。历史“heldout”已多次暴露，本轮只作为回归集；词法零重叠不能证明新的泛化能力。新 `ingestion-v1` 单独检验稿件 → 产物 → 效应 → 预填 → 冻结/审查/报告链路，不能替代纯文本语义召回。

本轮用户选择“先完成工程评测与试验准备”。[作者负担试评准备](evaluation/author-impact-pilot.md)采用 B / S / E-manual / E-prefill 四组，区分填表成本与额外审查收益；该设计尚未获得真实观测，不与旧 Stage 0 四组混合。可运行 `python -X utf8 scripts/prepare-impact-pilot.py prepare --output <新目录>`，无需模型调用。

2026-11-17 提示修复：原 Stage 0 JSON 和判定阈值保留；新 `text-advisory-regression-v1` 读数允许“原漏检 → 非阻断提示”，与原 `expectation_matched` / `heldout.all_passed` 并列，禁止把提示计入硬检出。新增 38 个修改前冻结的开发案例与 8 个语义边界诊断案例；它们均由已看过旧失败的开发者编写，不能称为独立盲测。旧词法零重叠检查只覆盖旧词表；新提示模块逐规则公开重叠和案例常量检查。当前回归还要求正对照及变形案例零误提示。

## 待检验的产品假说

核心假说是：在给定资料和预算内，分开的夸大/低估审查加上单一裁决，能提高“主张与证据匹配、对当前问题明确表态”的联合质量。它不假定多 Agent 必然优于一次模型调用，也不把措辞更强当成收益。

需要区分三个可能结果：

- 结构化台账本身已带来大部分收益，额外角色不值得其成本；
- 双向审查缓解了单向批评的系统性低估，但只有裁决才能形成可用结论；
- 完整流程增加开销或产生审查锚定，未比简化方案更好。

三种结果都保留。若简化方案表现相当且成本更低，应推荐简化方案，而不是维持插件复杂度。

## 对照组与公平比较

| 组别 | 提供给模型的能力 | 回答的问题 |
|---|---|---|
| A：原始宿主基线（`A_baseline`） | 同一模型、相同资料和任务；无 Parrhesia 规则 | 现状是什么 |
| B-精简：现用精简块（`B_compact`） | A + 精简规则块（`templates/AGENTS.parrhesia.codex.md`，本轮实测 `8,665 B`，含统一四档契约与 `L1-Explore` 轻量探索台账；L2 场景按需联用 `26,094 B` `parrhesia-l2-reference` skill）；无插件编排 | 精简常驻规则（及按需 L2 参考）是否足够且不劣于全文 |
| B-全文：全文规则（`B_full`） | A + 完整全文规则（`templates/AGENTS.parrhesia.md`，当前拼接 `46,582 B`；入口本身 `8,938 B`，原冻结套件中的 `41 KB` 仅保留为历史标签）；无插件编排 | 全文常驻规则与精简块的校准差异及上下文开销 |
| C：单向批评 | B + 台账 + 夸大审查 + 最终修订 | 只有找错是否产生过度保守 |
| D：双向审查，无独立裁决 | B + 台账 + 两份分别审查；原作者整合 | 独立裁决是否有额外价值 |
| E：完整 Parrhesia（`E_full_l2_workflow`） | B + `parrhesia-review` 入口（`3,058 B`；静态 E 提示词拼接后 `49,368 B`）+ L2 台账冻结 + 角色包隔离双向审查（记录 `input_manifest` 与可选 `isolation_attestation`，缺省记 `UNKNOWN`）+ 单一独立裁决 + 核对 | 完整 L2 双审裁决流程是否值得采用 |

## Stage 0 对照评估设计要点与日常工作流

Stage 0 对照评估聚焦 **A（无 Parrhesia 规则）**、**B-精简（现用 `8,665 B` + 按需 `26,094 B`）**、**B-全文（拼接 `46,582 B`）**、**E（拼接 `49,368 B`）** 四组；语料规格定义于 `docs/evaluation/stage0-cases.json`，严格按 **`dev_phrase_consistency`（开发期门控一致性）**、**`heldout_generalization`（零泄漏保留泛化）**、**`metamorphic_invariance`（不变性变换）**、**`p1_effect_records`（P1 结构化效应检验集，单独分栏）** 与 **`p2_longitudinal_calibration`（P2 跨时间主张图谱、触发器与校准检验集，单独分栏）** 分栏报告（配合 `python scripts/check-eval-leakage.py --strict` 静态/动态泄漏审计与 `python scripts/run-stage0-eval.py`）：

- **开发期一致性语料（`dev_phrase_consistency`）**：保留原核心案例并扩展至 **40 个基础 L2 案例**（覆盖 10 类科学/工程家族 × 4 场景）、**9 个 `L1-Explore` 案例**（`EXP-01..09`）、**Card A 60 次反事实证据敏感性运行**（20 正例 × 3 扰动：数字锚定/极性错位为硬阻断 `unanchored_effect_estimate`，纯文本否定/待出结局提示在 P0-1 记为非阻断 `lexical_advisories`）、**Card B 60 次执行分支与多重性门控运行**（20 正例 × 3 场景：`F1` SQLite 未交代/失败运行触发硬阻断 `selective_execution_omission`，`F2` 纯文本单次/未校正提示触发 `possible_unadjusted_multiplicity_text` 非阻断建议，`F3` 校准正对照零误报通过）、**6 组双生敏感性配对案例**（`PAIR-01..06`）、**4 组衍生血缘与 `>128 KiB` 分片窗口规格**（`LIN-01..04`），以及非阻断对称性审计 **Card C**（136 次运行，覆盖 5 项 hooks）。
- **零泄漏保留泛化集（`heldout_generalization`）**：新增 **24 个仿真现实措辞正对照**（`HRC-01..24`，含阴性次要终点、安全不良事件无差异对比、条件限制与学术讨论段落，检验 P0-1 低误拒率 `heldout_realistic_false_rejection_rate < 0.05`）与 **12 个对抗改写案例**（`HADV-01..12`，诚实区分 `6/12` 可被数字/SQLite/超窗尾段机制硬检出，与 `6/12` 仅靠纯自然语言语义伪装的案例显式记为 `uncaught_without_llm_or_p1`，等待已批准的外部 LLM 双审或填入结构化 `effect_records`）。
- **不变性变换集（`metamorphic_invariance`）**：新增 **12 组等价不变性变换**（`META-01..12`，从句重排、无显著不良反应对比、近零比值比修饰、文献对比），验证非矛盾学术措辞调整不破坏已校准通过率。
- **P1 结构化效应检验集（`p1_effect_records`，单独分栏，`--mode p1-effects`）**：新增 **12 个结构化 `effect_records` 检验案例**（`PEFF-01..12`：`PEFF-01` 验证主要终点显著获益并存 `null` 次要/安全终点时不误阻断且 `FRR = 0`；`PEFF-02..06` 验证 `primary_effect_crosses_null`、`unanchored_effect_record`、`effect_pvalue_ci_mismatch`、`effect_grim_inconsistent`、`effect_direction_mismatch` 及 SQLite 哈希事件链 `event_chain_status=verified`；`PEFF-07..12` 作为 `HADV-07..12` 的结构化 `effect_records` 对应体验证 `6/6` 可计算硬拦截，**与纯自然语言 `heldout_generalization` 严格分栏报告**，不替代也不篡改纯文本 `HADV-07..12` 的 `6/12` 机械召回率）。
- **P2 跨时间主张图谱、触发器与校准检验集（`p2_longitudinal_calibration`，单独分栏，`--mode p2-longitudinal`）**：新增 **8 个纵向演进与校准案例**（`PLONG-01..08`：`4` 个正对照覆盖多案例 `claim_graph` 轨迹与 `active_standing` 不篡改旧冻结记录、全部 5 类 `reversal_triggers` 确定性 `evaluate_triggers` 求值、导出后只追加 `record_calibration_outcome` 不改写冻结摘要/事件链，以及 `calibration_report` Brier/对数得分、ECE/MCE、主区间覆盖率/`z_drift` 与 `trigger_precision`；`4` 个负陷阱验证 `self_triggering_reversal_condition`、`contradictory_claim_lineage_transition`、`untriggered_reversal_link` 与 `unlinked_prior_case`，且全部保持 `event_chain_status=verified`）。**与 `heldout_generalization` 及 `p1_effect_records` 分别独立分栏报告**。
- **零泄漏检查与提示词导出（`--mode prompt-export` + `check-eval-leakage.py --strict`）**：导出内联规则包前自动校验 `parrhesia/gates.py` 启发式短语/正则集合对 `heldout_*` 与导出 `arms` 的词法及 3-gram 零泄漏，确保**标准答案、预期错误码、场景/扰动 ID 与内部 `evidence_kind` 标签不进入 `arms`**。

1. **统计单位**：统计单位是案例（case），同一模型的重复运行用于评估随机变异，**重复运行不算独立样本**。
2. **主终点与非劣效框架**：主终点为 **B-精简（现用）相对 B-全文（原冻结规范标为 `41 KB`，当前拼接输入为 `46,582 B`）的校准通过率**，采用非劣效框架（non-inferiority framework），非劣效界值在运行前冻结（预设 `Δ_NI = -0.05`，即精简版校准通过率不低于全文版超过 5 个百分点）。
3. **10 家族等覆盖、双向配对敏感性与 P0-1 阻断/建议边界**：
   - **全家族等覆盖（`equal_coverage_accuracy`）**：在原 6 类基础上补齐 `evidence_synthesis`（`SYNTH-01..04`）、`theory`（`THEORY-01..04`，显式 `claim_basis="formal"`）、`qualitative`（`QUAL-01..04`）与 `general`/`engineering`（`ENG-01..04`，显式 `domain="general"`），共 10 类家族 × 4 场景（`overclaim_trap`、`underclaim_trap`、`rubber_stamp_trap`、`calibrated_valid`）= 40 个基础 L2 案例；
   - **双向敏感性配对控制（`paired_evidence_sensitivity_concordance`）**：`paired_sensitivity_cases`（`PAIR-01..06`）为强正例（`strong_twin`）匹配同主题/近表层措辞的弱对照（`weak_twin`），要求同时“放行 `strong_twin` + 检出 `weak_twin`”；在 P0-1 边界下，数字锚定/`kind`/引证错位类弱对照触发硬阻断（`weak_twins_rejected`），纯文本缺失结局或否定从句类弱对照触发非阻断 `lexical_advisories`（`weak_twins_advisory_flagged`），二者区分报告；
   - **衍生血缘与分片长文本窗口检查（`synthetic_lineage_blocking_rate`、`chunked_window_head_tail_recall`）**：`lineage_window_specs`（`LIN-01..04`）验证 `synthetic` 祖先经 `derived_from_evidence_ids` 衍生伪装后仍被 `synthetic_empirical_support` 阻断，合法的 `hash_verified_unread_binary_ancestors` 可读衍生摘要允许通过并在 `verification` 中报告 `evidence_chains`，以及 `>128 KiB` 长文本经 `excerpt_anchors` 与 `<<<PARRHESIA_EXCERPT_WINDOW ...>>>` 保留 `head_metadata`、`quote_primary`、`anchor_excerpt`、`tail_summary` 槽位（`LIN-03` 尾部矛盾句触发非阻断 `possible_contradictory_evidence_text` 建议；`LIN-04` 未锚定截断阻断 `unread_positive_evidence`）；
   - **Card-C 非阻断对称性审计（`symmetry_audit`）**：接入内核 `audit_underclaim_and_abstention` 与 `collect_lexical_advisories`（`severity="advisory"`、`non_blocking=true`），分别输出 `flags`（`possible_false_abstention`、`possible_unjustified_downgrade`、`unsupported_without_counterevidence`、`possible_boilerplate_overhedging`、`rejected_underclaim_finding_advisory`）与纯文本 `lexical_advisories`，并检验精准边界正对照误报率为 0。
4. **新增探索类案例（`L1-Explore`）的指标（`EXP-01..09`）**：
   - 在首次出现假阳性结论前，已完成的区分实验数（`discriminating_experiments_before_first_fp`）；
   - 杀死错误假说所用步数（`steps_to_kill_false_hypothesis`）；
   - 总消耗（`total_consumption`：tokens / USD / 墙钟时间）。
5. **Stage 0 范围与样本量声明**：**Stage 0 只估计方差、检验机械门控边界与零泄漏可行性**。上一份报告估算，要检出 15 到 20 个百分点的绝对提升，需要约 120 到 160 个案例——这是上一份报告的样本量估算，不是实测结果。
6. **外部模型调用审批边界**：**外部模型调用需要用户先批准**，本评价方案、`docs/evaluation/stage0-cases.json` 与 `scripts/run-stage0-eval.py` 均强制遵守该要求（未获批准前 `external_llm_status="not_run"` 且 `requires_prior_user_approval=true`，绝不伪造模型评测分数）。

**推荐的日常工作流（不新增工具）**：探索阶段全程 `L1-Explore`（对每个候选假说维护轻量探索台账卡：最强对手、区分实验、成本、停止规则、杀死条件，标 `exploratory`），不建 L2 持久台账、不双审。确证阶段把 3 到 5 条核心主张送入 `L2`。只有写入图注、摘要或正文时才走完整双审。

这些组比较的是可部署方案；并不能把所有差异纯粹归因为某一模块。若需精确归因台账、核对或裁决角色，再做有明确决策价值的消融，不在首次评估里无限扩展。

主比较使用相同模型版本、资料访问权限、最大总推理/输出预算、检索预算及时间上限。先决定采用 token 预算还是按实价的费用预算；不同模型不能同时被声称 token 与费用完全相等。基线可以在同一总预算内自检，不能人为限制到明显更短的答案。报告实际消耗，不强迫各组为花满预算而产生无用输出。

另设“日常自然配置”的次要比较，估计真实工作成本。不要把自然配置中的更多计算量解释为编排结构的独立收益。模型提供商、版本、温度、系统指令、可用工具、并发限制与日期全部冻结或如实报告变更。

## 任务样本与参考判断

样本覆盖三种主要错误和合法的不确定性：证据充分但原文弱化；效应只在有限条件成立；真正缺证；混杂未排除；支持与反证并存；异质性被误读；工程演示被外推成用户收益；需要作行动选择但科学因果尚不清楚。

必须包含容易诱发“看起来改善”的反例：小样本但有效的精度限制、阴性结果、确有必要的安全边界、无须批评的合格初稿，以及使用肯定措辞却证据不足的文本。合法限制被删、未知被强行判支持，均属于退步。

开发集用于改提示词和修契约；保留集用于一次冻结版本后的主评价。同一论文、证据包、改写版本和近似模板放入同一分组后划分，避免家族泄漏。模型自己编写的合成案例单独报告，不能代表真实文稿中的收益。

参考判断由至少两位合适背景的人独立标注，分歧交第三位裁定或保留为争议区。标注者先看资料与问题，不看系统名称、产品主张和其他人的意见。参考内容包括：可支持的主张级别/范围、必须保留的限制、重要贡献、合理判定集合、改判条件及严重错误。复杂问题可有多个合格答案，不把某一句参考文字当唯一正确答案。

## 主指标与失败指标

以 case 或独立证据包为统计单位。一个 case 中多个结论、同一模型的重复采样和多个评委都不是新的独立案例。

| 维度 | 观察内容 | 防止误计 |
|---|---|---|
| 主张校准 | 最终级别与适用范围是否落在参考允许范围 | 更保守并不自动更好；分别统计夸大与低估 |
| 判定完整性 | 每条核心主张是否有判定、依据和可观察改判条件 | 证据不足可得满分；强迫支持不能加分 |
| 贡献保留 | 正文是否准确呈现已支持的重要发现 | 无根据升格扣分；不按积极词数计分 |
| 限制的有效性 | 必要限制是否保留、范围是否正确、是否无信息重复 | 不能奖励删除真实的精度/外推限制 |
| 证据忠实度 | 引文、数字、反例、缺失与来源类型是否正确 | 一个严重捏造不能被更多轻微改进平均掩盖 |
| 实用成本 | 实际费用、总 token、墙钟时间、人工复核时间 | 并发降低延迟不等于降低费用 |
| 用户控制 | 是否能暂停、拒绝、补充、恢复且保留旧判定 | 输出“已采纳”不是研究者实际接受 |

主结果报告夸大、低估、空泛中立三种错误各自的变化，以及“无严重证据错误且判定完整”的联合通过率；在 `docs/evaluation/stage0-cases.json` 与 `scripts/run-stage0-eval.py` 中，必须按 **`dev_phrase_consistency`**、**`heldout_generalization`**、**`metamorphic_invariance`**、**`p1_effect_records`** 与 **`p2_longitudinal_calibration`** 五栏分别报告分维指标，除原有 9 项设计维度（`overstatement_rate`、`understatement_rate`、`false_abstention_rate`、`valid_abstention_accuracy`、`known_valid_retention_rate`、`equal_coverage_accuracy`、`paired_evidence_sensitivity_concordance`、`synthetic_lineage_blocking_rate`、`chunked_window_head_tail_recall`）外，Stage 0 机械报告显式增列 `overstatement_rejection_rate`、`false_abstention_detection_rate`、`unjustified_downgrade_detection_rate`、`calibrated_false_alarm_rate`、`heldout_realistic_false_rejection_rate`、`heldout_adversarial_mechanical_recall`、`heldout_adversarial_uncaught_rate`、`metamorphic_invariance_rate`、`p1_effect_records_catch_rate`、`p1_effect_records_false_rejection_rate`、`p2_longitudinal_calibration_rate`、`p2_longitudinal_positive_pass_rate`、`p2_longitudinal_trap_catch_rate`、`leakage_strict_passed` 与 `live_llm_eval_status="not_run"`，同时严格区分硬门控阻断（如 `unanchored_effect_estimate`、`selective_execution_omission`、`primary_effect_crosses_null`、`unanchored_effect_record`、`effect_pvalue_ci_mismatch`、`effect_grim_inconsistent`、`effect_direction_mismatch`、`self_triggering_reversal_condition`、`contradictory_claim_lineage_transition`、`untriggered_reversal_link`、`unlinked_prior_case`）与非阻断 `lexical_advisories`（及 `unsupported_despite_beneficial_primary_effect` 低估提示），不得只汇成一个掩盖双向权衡或混合开发/保留集的总分。置信度高/中/低先评价理由与证据一致性；仅当对裁决显式填写 `[0.0, 1.0]` `forecast_probability` 并通过只追加 `record_calibration_outcome` 记录可核验结局时，才由 `calibration_report` 计算 Brier/对数得分、分箱 ECE/MCE、主区间覆盖率/`z_drift` 与触发器精确率。

严重错误包括捏造执行/引文/数字，把未知当已通过，错误的因果升级，删除影响结论的反证，以及用“明确结论”要求压过真实证据不足。合法不确定性或合适的安全约束本身不是产品缺陷。

## 统计与解读规则

在查看保留集结果前冻结主要比较、最小有意义收益、容许的严重错误增量和最大成本。建议先以小规模开发试评确认标注一致性和可执行性，再依据其变异制定样本量；不得用试评中的有利差异倒推出容易过关的门槛。样本数量、支付上限与正式分析尚待具体执行计划批准。

同一 case 各组配对比较，估计差值与不确定性；对证据包/任务家族聚类，报告合理的区间而非只看显著性。主要比较预先限定；多个主要终点或组间比较采用预设的多重比较策略。模型重复运行用于评估随机变异，不能把运行数当独立科学样本扩大 n。

按预设错误类别报告异质性。某类改善、另一类无效时，应把适用场景收窄；不能从“一类显著、另一类不显著”直接宣称组间差异。样本不足以比较时保留描述性结论。

对未完成调用和超过预算的运行同时报告：成功运行质量和按分配组计算的可交付率。不要静默删除失败，把插件的可靠性损失排除在产品结果之外。盲评可能受输出风格影响，应统一呈现格式并报告盲法的实际限制。

## 工程验收与真实宿主验收

工程验收应实际覆盖：同一冻结版本产生两份包；越阶段提交被拒；结论与审查意见完整覆盖；旧包不可嫁接到新版本；材料变化能被发现；未知检查不变成通过；重启后继续；导出内容读回与状态一致；路径越界与不可信资料不能扩大权限。

真实宿主验收另行记录：插件可发现、技能能读取运行时契约、用户选定工作区、模型实际得到独立输入、双方审查均返回、裁决逐条处理意见、暂停恢复有效、最后文件可打开。仅直接调用 Python、MCP `tools/list` 成功或模型声称“新上下文”，不能代替这些验收。

真实宿主验收通过仍不证明语义收益。人工填写的演示通过仍不证明 Grok 会持续遵循规则。对付费调用保存供应商、用途、模型版本、调用标识、上限、已确认支出和未结算状态；不能把未知费用记为零。

## 决策门槛与追加评价

以下是待执行前定量化的决策规则，不是已达标声明：

- 若 E 的夸大率未恶化，低估/空泛中立减少且联合通过率有有意义提升，成本可接受，则进入限定场景试用。
- 若 B 已达到相似结果，优先提供 AGENTS 模式；若 C 的低估增加而 E 改善，双向审查的必要性才得到相应支持。
- 若 D 与 E 相当且更便宜，裁决可作为复杂争议场景选项；若 E 的裁决遗漏或无依据折中减少，再支持默认独立裁决。
- 若收益只见于一个模型或任务类别，仅对该范围作主张；若严重证据错误增加，先修复具体失败，不能用平均评分提升抵消。

有决策价值的后续工作限定为：

| 具体疑点 | 什么结果会改变决策 | 成本类型 |
|---|---|---|
| 同模型共有偏差是否使双向审查失效 | 异模型在严重错误上有稳定净收益才加入可选适配 | 额外模型调用、数据外发审核、人工盲评 |
| 初稿锚定是否主导审查 | 隐去初稿只给主张/原始资料后更准确，才改变审查包设计 | 额外一组运行及标注 |
| 超过三条问题是否导致漏审 | 分批审查明显减少实质遗漏且开销可接受，才增加分批编排 | 长稿样本与运行时间 |

这些是可选增强评价，不阻塞本地工程交付。每次真正执行前都要重申疑点、可能结果对决策的影响及估计费用；没有决策影响的重复展示不开展。
