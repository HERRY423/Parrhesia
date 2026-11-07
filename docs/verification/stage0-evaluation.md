# Stage 0 Evaluation Verification Report (`stage0-v2`)

- **Mode**: `mechanical` (local deterministic engine, gate & L1-Explore card verification)
- **Control Arms Exported**: `A_baseline`（A：无 Parrhesia 规则）、`B_compact`（B-精简：现用精简块 + `parrhesia-l2-reference` skill）、`B_full`（B-全文：41 KB `templates/AGENTS.parrhesia.md`）、`E_full_l2_workflow`（E：完整 L2 流程，含审查者隔离配方）
- **L2 Calibration Cases**: `24 / 24` (`all_passed=True`)
- **L1-Explore Exploratory Cases**: `6 / 6` (`exploratory_all_valid=True`)
- **External Paid LLM Execution Status**: `not_run` (`requires_prior_user_approval=True`)

## Stage 0 Design Key Points (Frozen Specification)

1. **统计单位**：统计单位是案例，重复运行不算独立样本。
2. **主终点与非劣效框架**：主终点：精简版相对全文版的校准通过率，用非劣效框架，界值运行前冻结。（`comparison=B_compact (B-精简) vs B_full (B-全文 41 KB)`, `framework=non_inferiority`, `non_inferiority_margin=-0.05`, `margin_frozen_before_run=True`）
3. **新增探索类案例（`L1-Explore`）的三个指标**：
   - `discriminating_experiments_before_first_fp`：在首次出现假阳性结论前，已完成的区分实验数
   - `steps_to_kill_false_hypothesis`：杀死错误假说所用步数
   - `total_consumption`：总消耗（tokens / USD / 墙钟时间）
4. **Stage 0 定位与样本量说明**：Stage 0 只估计方差和可执行性。上一份报告估算，要检出 15 到 20 个百分点的绝对提升，需要约 120 到 160 个案例，这是它的估算，不是我的测量。
5. **外部模型调用审批门槛**：外部模型调用需要你先批准，评价方案也这样要求。

## Case-by-Case Mechanical Gate Results (24 L2 Cases)

| Case | Family | Scenario | Classification (`claim_type × evidence_level`) | Verdict | Expected | Actual | Error Code | Pass |
|---|---|---|---|---|---|---|---|---|
| `OBS-01` | `observational` | `overclaim_trap` | `causal_effect × identified_under_assumptions` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `OBS-02` | `observational` | `underclaim_trap` | `association × robust_association` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `OBS-03` | `observational` | `rubber_stamp_trap` | `association × adjusted` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `OBS-04` | `observational` | `calibrated_valid` | `causal_effect × sensitivity_supported` | `partially_supported` | `accepted` | `accepted` | — | `PASS` |
| `QE-01` | `quasi_experimental` | `overclaim_trap` | `causal_effect × identified_under_assumptions` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `QE-02` | `quasi_experimental` | `underclaim_trap` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `QE-03` | `quasi_experimental` | `rubber_stamp_trap` | `causal_effect × identified_under_assumptions` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `QE-04` | `quasi_experimental` | `calibrated_valid` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `RCT-01` | `randomized` | `overclaim_trap` | `causal_effect × sensitivity_supported` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `RCT-02` | `randomized` | `underclaim_trap` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `RCT-03` | `randomized` | `rubber_stamp_trap` | `causal_effect × identified_under_assumptions` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `RCT-04` | `randomized` | `calibrated_valid` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `PRED-01` | `prediction` | `overclaim_trap` | `prediction × externally_validated` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `PRED-02` | `prediction` | `underclaim_trap` | `prediction × externally_validated` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `PRED-03` | `prediction` | `rubber_stamp_trap` | `prediction × externally_validated` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `PRED-04` | `prediction` | `calibrated_valid` | `prediction × externally_validated` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `ML-01` | `ml` | `overclaim_trap` | `computational × reproduced` | `supported` | `rejected` | `rejected` | `synthetic_empirical_support` | `PASS` |
| `ML-02` | `ml` | `underclaim_trap` | `computational × reproduced` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `ML-03` | `ml` | `rubber_stamp_trap` | `computational × reproduced` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `ML-04` | `ml` | `calibrated_valid` | `computational × externally_evaluated` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `MECH-01` | `mechanism` | `overclaim_trap` | `sufficiency × counterfactual_supported` | `supported` | `rejected` | `rejected` | `causal_identification_gap` | `PASS` |
| `MECH-02` | `mechanism` | `underclaim_trap` | `necessity × counterfactual_supported` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `MECH-03` | `mechanism` | `rubber_stamp_trap` | `mechanism × component_tested` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `MECH-04` | `mechanism` | `calibrated_valid` | `mechanism × component_tested` | `supported` | `accepted` | `accepted` | — | `PASS` |

## L1-Explore Lightweight Exploration Ledger Cases (6 Exploratory Cases)

| Case | Family | Origin | Classification | Cards | Required 5 Fields (`strongest_rival`, `discriminating_experiment`, `cost`, `stopping_rule`, `kill_condition`) | Live LLM Metrics |
|---|---|---|---|---|---|---|
| `EXP-01` | `observational` | `exploratory` | `mechanism × compatible` | `1` | `PASS` | `not_run` |
| `EXP-02` | `quasi_experimental` | `exploratory` | `theory × conjectured` | `1` | `PASS` | `not_run` |
| `EXP-03` | `prediction` | `exploratory` | `prediction × apparent` | `1` | `PASS` | `not_run` |
| `EXP-04` | `ml` | `exploratory` | `computational × benchmark_measured` | `1` | `PASS` | `not_run` |
| `EXP-05` | `mechanism` | `exploratory` | `mechanism × compatible` | `1` | `PASS` | `not_run` |
| `EXP-06` | `randomized` | `exploratory` | `causal_effect × unidentified` | `1` | `PASS` | `not_run` |

## Verification Scope & Honesty Boundary

1. **What this verifies (`engineering × test_passed`)**: All 24 L2 Stage 0 cases execute through `parrhesia.core.Engine` v2 (`gate_version=1`), and all 6 `L1-Explore` exploratory cases validate the 5-field lightweight exploration ledger card contract (`strongest_rival`, `discriminating_experiment`, `cost`, `stopping_rule`, `kill_condition`, marked `exploratory`). Prompt packets are exported across all 4 control arms (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`).
2. **What remains `NOT_RUN` (`UNKNOWN`)**: Live external GPT/Claude/Grok API runs across Arms `A`, `B-精简`, `B-全文`, and `E` require prior user approval per `docs/evaluation-plan.md` and are explicitly marked `external_llm_status: not_run`.
