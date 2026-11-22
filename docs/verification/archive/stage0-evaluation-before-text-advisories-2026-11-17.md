# Stage 0 Evaluation Verification Report (`stage0-v2`)

- **Mode**: `mechanical` (local deterministic engine, structural/numeric gates, L1-Explore card, Card A/B/C dev consistency, Paired sensitivity, Derived Lineage & Chunked-Window, zero-leakage Held-out Generalization, and Metamorphic Invariance)
- **Control Arm Inputs (export availability, not live runs)**: `A_baseline`（A：无 Parrhesia 规则）、`B_compact`（B-精简：8665 B 精简块 + 26094 B `parrhesia-l2-reference` skill）、`B_full`（B-全文：46582 B 基础规则 + L2 参考 + 工具工作流）、`E_full_l2_workflow`（E：完整 L2 流程，49368 B skill + 基础规则 + L2 参考 + 工具工作流；layered-v1）
- **L2 Calibration Cases (`dev_phrase_consistency`)**: `40 / 40` across `10` families (`all_passed=True`)
- **L1-Explore Exploratory Cases**: `9 / 9` (`exploratory_all_valid=True`)
- **Card A Counterfactual Perturbation Runs (`dev_phrase_consistency`)**: `60 / 60` (`pre_card_a_rejection=0/60`, `hard_rejected=30/60`, `lexical_advisory_flagged=30/60`, `calibrated_flip_accepted=60/60`)
- **Card B Execution-Fork Multiplicity Runs (`dev_phrase_consistency`)**: `60 / 60` (`pre_card_b_adv_rejection=0/40`, `hard_rejected=20/40`, `lexical_advisory_flagged=20/40`, `positive_control_accepted=20/20`)
- **Card C Symmetry Audit Runs (Non-Blocking Advisory)**: `136 / 136` (`non_blocking_export_preserved_rate=1.0`, `calibrated_false_alarm_rate=0.0`, `all_five_hooks_verified=True`)
- **Paired Sensitivity Concordance**: `6 / 6` pairs (`strong_accepted=6/6`, `weak_hard_rejected=4`, `weak_advisory_flagged=2`, `concordance=1.0`)
- **Lineage & Chunked-Window Verification**: `4 / 4` specs (`synthetic_lineage_blocking_rate=1.0`, `chunked_window_head_tail_recall=1.0`, `tail_contradiction_mode=lexical_advisory`)
- **Held-out Generalization (`leakage_strict_passed=True`, `overlap=0`)**: Realistic controls `24 / 24` (`false_rejection_rate=0.0`); Adversarial paraphrases caught mechanically `6 / 12` (`mechanical_recall=0.5`, `uncaught_without_llm_or_p1=6/12`)
- **Metamorphic Invariance**: `12 / 12` (`invariance_rate=1.0`, `false_advisories=2`)
- **P1 Structured `effect_records` (`p1_effect_records`, Separate Column)**: `12 / 12` (positive control `1/1`, `FRR=0.0`, negative traps `11/11`, structured `HADV-07..12` counterparts `6/6`)
- **P2 Longitudinal Graph, Triggers & Calibration (`p2_longitudinal_calibration`, `PLONG-01..08`)**: `8 / 8` (`pass_rate=1.0`, `event_chain_verified=8/8`)
- **External Paid LLM Execution Status**: `not_run` (`requires_prior_user_approval=True`)

## Current inputs and ingestion extension

- Runtime: `0.4.0`; layout: `layered-v1`; MCP tools: `25`, compact UTF-8 JSON `69093 B`.
- Entry skill: `3058 B`; assembled E prompt above includes its references. Bytes are not model tokens or author effort.
- Ingestion: `10/10`; actual action coverage: `{"draft_manuscript": true, "extract_effects": true, "freeze": true, "import_artifact": true, "set_ledger": true, "submit_adjudication": true, "submit_review": true, "verify": true}`.
- Historical held-out fixtures are now exposed regression cases; unchanged lexical leakage checks do not establish fresh generalization.
- `all_passed` means expected mechanical behavior, including explicitly uncaught semantic cases; it does not mean complete detection or net benefit.
- Host workflow acceptance and real author benefit: `not_run`. See `docs/evaluation/author-impact-pilot.md` for the prepared comparison and burden measures.

## Split-Column Evaluation Summary (Zero-Leakage P0 + P1 Separation)

| Evaluation Column | Scope | Key Result | Honest Boundary / Gap |
|---|---|---|---|
| `dev_phrase_consistency` | Base `40/40` + Card A (`30` hard / `30` advisory) + Card B (`20` hard / `20` advisory) + Card C (`136/136`) + Paired (`6/6`) + Lineage (`4/4`) | Mechanical + non-blocking lexical-advisory P0-1 contract concordant | In-distribution only; lexical advisories are non-blocking diagnostics |
| `heldout_generalization` | Static leakage gate (`overlap=0`) + `24` realistic controls + `12` adversarial paraphrases | Controls `24/24` (`FRR=0.0`); Adversarial hard-caught `6/12` (`recall=0.5`) | `6/12` natural-language paraphrases (`HADV-07, HADV-08, HADV-09, HADV-10, HADV-11, HADV-12`) remain uncaught without LLM review or P1 `effect_records` |
| `metamorphic_invariance` | `12` invariance transforms (`clause_reorder`, `no significant difference in adverse events`, `OR = 1.08`, literature contrast) | `12/12` preserved acceptance & export (`invariance_rate=1.0`) | False lexical advisories across transforms: `2` |
| `p1_effect_records` | `12` structured `effect_records` probes (`PEFF-01` realistic primary benefit + null safety/secondary; `PEFF-02..06` computable checks; `PEFF-07..12` structured `HADV-07..12` counterparts) + SQLite `event_chain` | Positive control `1/1` (`FRR=0.0`); Negative traps caught `11/11` (`HADV-07..12` structured `6/6`, `event_chain=verified` `12/12`) | Requires populated structured `effect_records`; prose-only `HADV-07..12` in `heldout_generalization` still stays uncaught without LLM or structured input |
| `p2_longitudinal_calibration` | `8` longitudinal DAG, trigger & calibration probes (`PLONG-01..08`) + SQLite `event_chain` | `8/8` passed (`positive=4/4`, `traps=4/4`, `event_chain=verified` `8/8`) | Deterministic runtime contract checks on structured P2 lineage, triggers, and outcome resolution |

## Unified Stage 0 Metric Dimensions (`not_run` marked explicitly for Live LLM)

| Metric Dimension | Value | Status / Notes |
|---|---|---|
| `overstatement_rejection_rate` | `1.0` | Base overclaim/rubber-stamp traps (`20/20`) hard-rejected (`dev_phrase_consistency`) |
| `false_abstention_detection_rate` | `1.0` | Card C `U1_false_abstention` (`20/20`) |
| `unjustified_downgrade_detection_rate` | `1.0` | Card C `U1b_unjustified_downgrade` (`15/15`) |
| `known_valid_retention_rate` | `1.0` | Base accepted positives (`20/20`) + `PAIR-01..06` strong twins (`6/6`) retained & exported |
| `equal_coverage_accuracy` | `1.0` | Minimum per-family pass accuracy across all `10` families |
| `paired_evidence_sensitivity_concordance` | `1.0` | Joint strong+weak twin concordance (`6/6`: `4` hard-rejected, `2` lexical-advisory) |
| `synthetic_lineage_blocking_rate` | `1.0` | `LIN-01` synthetic ancestor blocked (`Engine` + CLI `record-exec --derived-from`); `LIN-02` hash-verified binary accepted & tampered ancestor blocked |
| `chunked_window_head_tail_recall` | `1.0` | `LIN-03` 4-role `<<<PARRHESIA_EXCERPT_WINDOW ...>>>` `<=128 KiB` preserving head/quote/anchor/tail + tail contradiction (`lexical_advisory`); `LIN-04` unanchored truncated blocked |
| `calibrated_false_alarm_rate` | `0.0` | Card C calibrated positives (`16`), `P1` null controls (`20`), check-gap controls (`20`) = `0/56` false alarms |
| `heldout_realistic_false_rejection_rate` | `0.0` | Held-out zero-leakage realistic controls (`0/24` false rejections, target `< 0.05`) |
| `heldout_adversarial_mechanical_recall` | `0.5` | Zero-leakage paraphrases hard-caught by numeric/SQLite/tail gates (`6/12`) |
| `heldout_adversarial_uncaught_rate` | `0.5` | Zero-leakage natural-language paraphrases uncaught without live LLM or P1 (`6/12`) |
| `metamorphic_invariance_rate` | `1.0` | Invariance across `12` non-contradictory transformations |
| `p1_effect_records_catch_rate` | `1.0` | Separate `p1_effect_records` suite (`11/11` computable catches incl. `6/6` `HADV-07..12` structured counterparts) |
| `p1_effect_records_false_rejection_rate` | `0.0` | Separate `p1_effect_records` positive control (`0/1` false rejections) |
| `p2_longitudinal_pass_rate` | `1.0` | `p2_longitudinal_calibration` suite (`PLONG-01..08`: `8/8`, `event_chain=verified` `8/8`) |
| `leakage_strict_passed` | `True` | Static AST + regex + 3-gram leakage check (`parrhesia/gates.py` vs `heldout_*`) |
| `live_llm_eval_status` | `not_run` | External paid LLM runs require prior explicit user approval |

## Equal Coverage by Family

| Family | Passed | Total | Accuracy |
|---|---|---|---|
| `observational` | `4` | `4` | `1.0` |
| `quasi_experimental` | `4` | `4` | `1.0` |
| `randomized` | `4` | `4` | `1.0` |
| `prediction` | `4` | `4` | `1.0` |
| `ml` | `4` | `4` | `1.0` |
| `mechanism` | `4` | `4` | `1.0` |
| `evidence_synthesis` | `4` | `4` | `1.0` |
| `theory` | `4` | `4` | `1.0` |
| `qualitative` | `4` | `4` | `1.0` |
| `general` | `4` | `4` | `1.0` |

## Stage 0 Design Key Points (Frozen Specification)

1. **统计单位**：统计单位是案例，重复运行不算独立样本。
2. **主终点与非劣效框架**：主终点：精简版相对全文版的校准通过率，用非劣效框架，界值运行前冻结。（`comparison=B_compact (B-精简) vs B_full (B-全文 41 KB)`, `framework=non_inferiority`, `non_inferiority_margin=-0.05`, `margin_frozen_before_run=True`）
3. **新增探索类案例（`L1-Explore`）的三个指标**：
   - `discriminating_experiments_before_first_fp`：在首次出现假阳性结论前，已完成的区分实验数
   - `steps_to_kill_false_hypothesis`：杀死错误假说所用步数
   - `total_consumption`：总消耗（tokens / USD / 墙钟时间）
4. **Stage 0 定位与样本量说明**：Stage 0 只估计方差和可执行性。上一份报告估算，要检出 15 到 20 个百分点的绝对提升，需要约 120 到 160 个案例，这是它的估算，不是我的测量。
5. **外部模型调用审批门槛**：外部模型调用需要你先批准，评价方案也这样要求。

## Case-by-Case Mechanical Gate Results (40 L2 Cases)

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
| `SYNTH-01` | `evidence_synthesis` | `overclaim_trap` | `synthesis × synthesized_with_uncertainty` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `SYNTH-02` | `evidence_synthesis` | `underclaim_trap` | `synthesis × synthesized_with_uncertainty` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `SYNTH-03` | `evidence_synthesis` | `rubber_stamp_trap` | `synthesis × mapped` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `SYNTH-04` | `evidence_synthesis` | `calibrated_valid` | `synthesis × synthesized_with_uncertainty` | `partially_supported` | `accepted` | `accepted` | — | `PASS` |
| `THEORY-01` | `theory` | `overclaim_trap` | `theory × proved_under_assumptions` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `THEORY-02` | `theory` | `underclaim_trap` | `theory × proved_under_assumptions` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `THEORY-03` | `theory` | `rubber_stamp_trap` | `theory × independently_checked` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `THEORY-04` | `theory` | `calibrated_valid` | `theory × independently_checked` | `partially_supported` | `accepted` | `accepted` | — | `PASS` |
| `QUAL-01` | `qualitative` | `overclaim_trap` | `association × adjusted` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `QUAL-02` | `qualitative` | `underclaim_trap` | `qualitative × triangulated` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `QUAL-03` | `qualitative` | `rubber_stamp_trap` | `qualitative × interpretation_audited` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `QUAL-04` | `qualitative` | `calibrated_valid` | `qualitative × triangulated` | `partially_supported` | `accepted` | `accepted` | — | `PASS` |
| `ENG-01` | `general` | `overclaim_trap` | `engineering × user_impact` | `supported` | `rejected` | `rejected` | `incompatible_evidence_kind` | `PASS` |
| `ENG-02` | `general` | `underclaim_trap` | `engineering × host_accepted` | `supported` | `accepted` | `accepted` | — | `PASS` |
| `ENG-03` | `general` | `rubber_stamp_trap` | `engineering × user_impact` | `supported` | `rejected` | `rejected` | `critical_check_ceiling` | `PASS` |
| `ENG-04` | `general` | `calibrated_valid` | `engineering × user_impact` | `partially_supported` | `accepted` | `accepted` | — | `PASS` |

## L1-Explore Lightweight Exploration Ledger Cases (9 Exploratory Cases)

| Case | Family | Origin | Classification | Cards | Required 5 Fields (`strongest_rival`, `discriminating_experiment`, `cost`, `stopping_rule`, `kill_condition`) | Live LLM Metrics |
|---|---|---|---|---|---|---|
| `EXP-01` | `observational` | `exploratory` | `mechanism × compatible` | `1` | `PASS` | `not_run` |
| `EXP-02` | `quasi_experimental` | `exploratory` | `theory × conjectured` | `1` | `PASS` | `not_run` |
| `EXP-03` | `prediction` | `exploratory` | `prediction × apparent` | `1` | `PASS` | `not_run` |
| `EXP-04` | `ml` | `exploratory` | `computational × benchmark_measured` | `1` | `PASS` | `not_run` |
| `EXP-05` | `mechanism` | `exploratory` | `mechanism × compatible` | `1` | `PASS` | `not_run` |
| `EXP-06` | `randomized` | `exploratory` | `causal_effect × unidentified` | `1` | `PASS` | `not_run` |
| `EXP-07` | `evidence_synthesis` | `exploratory` | `synthesis × mapped` | `1` | `PASS` | `not_run` |
| `EXP-08` | `theory` | `exploratory` | `theory × conjectured` | `1` | `PASS` | `not_run` |
| `EXP-09` | `qualitative` | `exploratory` | `qualitative × situated_description` | `1` | `PASS` | `not_run` |

## Card A: Counterfactual Evidence-Sensitivity Suite (20 Positive Cases × 3 Perturbations = 60 Runs)

- **Discriminating Ablation & P0-1 Boundary (`counterfactual_gates=False` vs `True`)**: Pre-Card-A gates rejected `0 / 60` (`0.0%`); under P0-1, Card A hard-rejected `30 / 60` (`50.0%`, numeric effect anchoring) and emitted non-blocking `lexical_advisories` on `30 / 60` pure-text runs (combined detected `60 / 60`). Kill condition (`pre_card_a >= 95%`) triggered: `False`.
- **Calibrated Verdict-Flip Concordance**: `60 / 60` (`100.0%`) properly flipped non-positive adjudications (`unsupported` / `insufficient_evidence`) accepted and exported.

| Run ID | Base Case | Perturbation | Pre-Card-A (`gate=off`) | Card A Outcome | Detection Mode | Code / Advisory Hook | Calibrated Flip | Pass |
|---|---|---|---|---|---|---|---|---|
| `OBS-02-P1_null_flip` | `OBS-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `OBS-02-P2_outcome_stripped` | `OBS-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-02-P3_synthetic_swap` | `OBS-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-04-P1_null_flip` | `OBS-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `partially_supported -> unsupported` (`accepted`) | `PASS` |
| `OBS-04-P2_outcome_stripped` | `OBS-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-04-P3_synthetic_swap` | `OBS-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QE-02-P1_null_flip` | `QE-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `QE-02-P2_outcome_stripped` | `QE-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QE-02-P3_synthetic_swap` | `QE-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QE-04-P1_null_flip` | `QE-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `QE-04-P2_outcome_stripped` | `QE-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QE-04-P3_synthetic_swap` | `QE-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-02-P1_null_flip` | `RCT-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `RCT-02-P2_outcome_stripped` | `RCT-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-02-P3_synthetic_swap` | `RCT-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-04-P1_null_flip` | `RCT-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `RCT-04-P2_outcome_stripped` | `RCT-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-04-P3_synthetic_swap` | `RCT-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-02-P1_null_flip` | `PRED-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `PRED-02-P2_outcome_stripped` | `PRED-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-02-P3_synthetic_swap` | `PRED-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-04-P1_null_flip` | `PRED-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `PRED-04-P2_outcome_stripped` | `PRED-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-04-P3_synthetic_swap` | `PRED-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ML-02-P1_null_flip` | `ML-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `ML-02-P2_outcome_stripped` | `ML-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ML-02-P3_synthetic_swap` | `ML-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ML-04-P1_null_flip` | `ML-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `ML-04-P2_outcome_stripped` | `ML-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ML-04-P3_synthetic_swap` | `ML-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-02-P1_null_flip` | `MECH-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `MECH-02-P2_outcome_stripped` | `MECH-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-02-P3_synthetic_swap` | `MECH-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-04-P1_null_flip` | `MECH-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `MECH-04-P2_outcome_stripped` | `MECH-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-04-P3_synthetic_swap` | `MECH-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-02-P1_null_flip` | `SYNTH-02` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> unsupported` (`accepted`) | `PASS` |
| `SYNTH-02-P2_outcome_stripped` | `SYNTH-02` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-02-P3_synthetic_swap` | `SYNTH-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-04-P1_null_flip` | `SYNTH-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `partially_supported -> unsupported` (`accepted`) | `PASS` |
| `SYNTH-04-P2_outcome_stripped` | `SYNTH-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-04-P3_synthetic_swap` | `SYNTH-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-02-P1_null_flip` | `THEORY-02` | `P1_null_flip` | `accepted` | `accepted` | `lexical_advisory` | `possible_contradictory_evidence_text` | `supported -> unsupported` (`accepted`) | `PASS` |
| `THEORY-02-P2_outcome_stripped` | `THEORY-02` | `P2_outcome_stripped` | `accepted` | `accepted` | `lexical_advisory` | `possible_outcome_pending_text` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-02-P3_synthetic_swap` | `THEORY-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-04-P1_null_flip` | `THEORY-04` | `P1_null_flip` | `accepted` | `accepted` | `lexical_advisory` | `possible_contradictory_evidence_text` | `partially_supported -> unsupported` (`accepted`) | `PASS` |
| `THEORY-04-P2_outcome_stripped` | `THEORY-04` | `P2_outcome_stripped` | `accepted` | `accepted` | `lexical_advisory` | `possible_outcome_pending_text` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-04-P3_synthetic_swap` | `THEORY-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-02-P1_null_flip` | `QUAL-02` | `P1_null_flip` | `accepted` | `accepted` | `lexical_advisory` | `possible_contradictory_evidence_text` | `supported -> unsupported` (`accepted`) | `PASS` |
| `QUAL-02-P2_outcome_stripped` | `QUAL-02` | `P2_outcome_stripped` | `accepted` | `accepted` | `lexical_advisory` | `possible_outcome_pending_text` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-02-P3_synthetic_swap` | `QUAL-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-04-P1_null_flip` | `QUAL-04` | `P1_null_flip` | `accepted` | `accepted` | `lexical_advisory` | `possible_contradictory_evidence_text` | `partially_supported -> unsupported` (`accepted`) | `PASS` |
| `QUAL-04-P2_outcome_stripped` | `QUAL-04` | `P2_outcome_stripped` | `accepted` | `accepted` | `lexical_advisory` | `possible_outcome_pending_text` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-04-P3_synthetic_swap` | `QUAL-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-02-P1_null_flip` | `ENG-02` | `P1_null_flip` | `accepted` | `accepted` | `lexical_advisory` | `possible_contradictory_evidence_text` | `supported -> unsupported` (`accepted`) | `PASS` |
| `ENG-02-P2_outcome_stripped` | `ENG-02` | `P2_outcome_stripped` | `accepted` | `accepted` | `lexical_advisory` | `possible_outcome_pending_text` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-02-P3_synthetic_swap` | `ENG-02` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-04-P1_null_flip` | `ENG-04` | `P1_null_flip` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `partially_supported -> unsupported` (`accepted`) | `PASS` |
| `ENG-04-P2_outcome_stripped` | `ENG-04` | `P2_outcome_stripped` | `accepted` | `rejected` | `hard_rejected` | `unanchored_effect_estimate` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-04-P3_synthetic_swap` | `ENG-04` | `P3_synthetic_swap` | `accepted` | `accepted` | `lexical_advisory` | `possible_evidence_kind_mismatch` | `partially_supported -> insufficient_evidence` (`accepted`) | `PASS` |

## Card B: `record-exec` Execution-Fork Detection & Multiplicity Gate Suite (20 Positive Cases × 3 Scenarios = 60 Runs)

- **Adversarial Fork/Multiplicity Ablation & P0-1 Boundary (`fork_gates=False` vs `True`, 40 runs)**: Pre-Card-B gates rejected `0 / 40`; under P0-1, structural `F1_hidden_failed_forks` hard-rejected `20 / 40` (`selective_execution_omission`), while phrase-only `F2_unadjusted_multi_fork` emitted non-blocking `possible_unadjusted_multiplicity_text` advisories on `20 / 40` runs (combined detected `40 / 40`).
- **Positive-Control Specificity (`F3_calibrated_multiplicity_accounted`, 20 runs)**: `20 / 20` (`100.0%`, over-blocking rate `0.0%`) accepted and exported cleanly with zero advisories. Kill condition triggered: `False`.

| Run ID | Base Case | Scenario (`fork_count=5`) | Pre-Card-B | Card B Positive | Detection Mode | Code / Advisory | Calibrated Outcome | Pass |
|---|---|---|---|---|---|---|---|---|
| `OBS-02-F1_hidden_failed_forks` | `OBS-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-02-F2_unadjusted_multi_fork` | `OBS-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-02-F3_calibrated_multiplicity_accounted` | `OBS-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `OBS-04-F1_hidden_failed_forks` | `OBS-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-04-F2_unadjusted_multi_fork` | `OBS-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `OBS-04-F3_calibrated_multiplicity_accounted` | `OBS-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `QE-02-F1_hidden_failed_forks` | `QE-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QE-02-F2_unadjusted_multi_fork` | `QE-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QE-02-F3_calibrated_multiplicity_accounted` | `QE-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `QE-04-F1_hidden_failed_forks` | `QE-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QE-04-F2_unadjusted_multi_fork` | `QE-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QE-04-F3_calibrated_multiplicity_accounted` | `QE-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `RCT-02-F1_hidden_failed_forks` | `RCT-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-02-F2_unadjusted_multi_fork` | `RCT-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-02-F3_calibrated_multiplicity_accounted` | `RCT-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `RCT-04-F1_hidden_failed_forks` | `RCT-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-04-F2_unadjusted_multi_fork` | `RCT-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `RCT-04-F3_calibrated_multiplicity_accounted` | `RCT-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `PRED-02-F1_hidden_failed_forks` | `PRED-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-02-F2_unadjusted_multi_fork` | `PRED-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-02-F3_calibrated_multiplicity_accounted` | `PRED-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `PRED-04-F1_hidden_failed_forks` | `PRED-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-04-F2_unadjusted_multi_fork` | `PRED-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `PRED-04-F3_calibrated_multiplicity_accounted` | `PRED-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `ML-02-F1_hidden_failed_forks` | `ML-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ML-02-F2_unadjusted_multi_fork` | `ML-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ML-02-F3_calibrated_multiplicity_accounted` | `ML-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `ML-04-F1_hidden_failed_forks` | `ML-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ML-04-F2_unadjusted_multi_fork` | `ML-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ML-04-F3_calibrated_multiplicity_accounted` | `ML-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `MECH-02-F1_hidden_failed_forks` | `MECH-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-02-F2_unadjusted_multi_fork` | `MECH-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-02-F3_calibrated_multiplicity_accounted` | `MECH-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `MECH-04-F1_hidden_failed_forks` | `MECH-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-04-F2_unadjusted_multi_fork` | `MECH-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `MECH-04-F3_calibrated_multiplicity_accounted` | `MECH-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `SYNTH-02-F1_hidden_failed_forks` | `SYNTH-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-02-F2_unadjusted_multi_fork` | `SYNTH-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-02-F3_calibrated_multiplicity_accounted` | `SYNTH-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `SYNTH-04-F1_hidden_failed_forks` | `SYNTH-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-04-F2_unadjusted_multi_fork` | `SYNTH-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `SYNTH-04-F3_calibrated_multiplicity_accounted` | `SYNTH-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `THEORY-02-F1_hidden_failed_forks` | `THEORY-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-02-F2_unadjusted_multi_fork` | `THEORY-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-02-F3_calibrated_multiplicity_accounted` | `THEORY-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `THEORY-04-F1_hidden_failed_forks` | `THEORY-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-04-F2_unadjusted_multi_fork` | `THEORY-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `THEORY-04-F3_calibrated_multiplicity_accounted` | `THEORY-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `QUAL-02-F1_hidden_failed_forks` | `QUAL-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-02-F2_unadjusted_multi_fork` | `QUAL-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-02-F3_calibrated_multiplicity_accounted` | `QUAL-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `QUAL-04-F1_hidden_failed_forks` | `QUAL-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-04-F2_unadjusted_multi_fork` | `QUAL-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `QUAL-04-F3_calibrated_multiplicity_accounted` | `QUAL-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `ENG-02-F1_hidden_failed_forks` | `ENG-02` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-02-F2_unadjusted_multi_fork` | `ENG-02` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-02-F3_calibrated_multiplicity_accounted` | `ENG-02` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |
| `ENG-04-F1_hidden_failed_forks` | `ENG-04` | `F1_hidden_failed_forks` | `accepted` | `rejected` | `hard_rejected` | `selective_execution_omission` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-04-F2_unadjusted_multi_fork` | `ENG-04` | `F2_unadjusted_multi_fork` | `accepted` | `accepted` | `lexical_advisory` | `possible_unadjusted_multiplicity_text` | `insufficient_evidence` (`accepted`) | `PASS` |
| `ENG-04-F3_calibrated_multiplicity_accounted` | `ENG-04` | `F3_calibrated_multiplicity_accounted` | `accepted` | `accepted` | `clean_control` | — | `positive_preserved` (`accepted`) | `PASS` |

## Card C: Non-Blocking Anti-Underclaim & False-Abstention Symmetry Audit (136 Runs)

- **Advisory Detection Across All 5 Hooks**: `possible_false_abstention` `20/20` (`1.0`), `possible_unjustified_downgrade` `15/15` (`1.0`), `unsupported_without_counterevidence` `20/20` (`1.0`), `possible_boilerplate_overhedging` `15/15` (`1.0`), `rejected_underclaim_finding_advisory` `10/10` (`1.0`).
- **Non-Blocking Export & Control Specificity**: Export preserved across `136/136` runs (`non_blocking_export_preserved_rate=1.0`); false alarms across calibrated positives, `P1` null counterevidence controls, and critical check-gap controls = `0/56` (`calibrated_false_alarm_rate=0.0`).

## Paired Evidence-Sensitivity Concordance (6 Pairs)

| Pair | Family | Claim Type × Target Level | Strong Twin Outcome | Weak Twin Outcome (Error / Advisory) | Pair Concordance |
|---|---|---|---|---|---|
| `PAIR-01` | `randomized` | `causal_effect × sensitivity_supported` | `accepted` (`exported`) | `rejected` (`unanchored_effect_estimate`) | `PASS` |
| `PAIR-02` | `observational` | `causal_effect × sensitivity_supported` | `accepted` (`exported`) | `rejected` (`incompatible_evidence_kind`) | `PASS` |
| `PAIR-03` | `prediction` | `prediction × externally_validated` | `accepted` (`exported`) | `accepted` (`possible_evidence_kind_mismatch`) | `PASS` |
| `PAIR-04` | `evidence_synthesis` | `synthesis × synthesized_with_uncertainty` | `accepted` (`exported`) | `accepted` (`possible_outcome_pending_text`) | `PASS` |
| `PAIR-05` | `theory` | `theory × proved_under_assumptions` | `accepted` (`exported`) | `rejected` (`incompatible_evidence_kind`) | `PASS` |
| `PAIR-06` | `general` | `engineering × user_impact` | `accepted` (`exported`) | `rejected` (`incompatible_evidence_kind`) | `PASS` |

## Derived Evidence Lineage & >128 KiB Chunked-Window Verification (4 Specs)

- **Lineage Checks**: `LIN-01` Engine + CLI `record-exec --derived-from --derivation-step` synthetic blocking = `True` / `True`; `LIN-02` `hash_verified_unread_binary_ancestors` leaf export = `True`; tampered disk ancestor blocked = `True`.
- **Chunked-Window Checks**: `LIN-03` 4-role `<<<PARRHESIA_EXCERPT_WINDOW ...>>>` (`<=128 KiB`) preserved & exported = `True`; tail contradiction beyond 128 KiB caught = `True` (`mode=lexical_advisory`); `LIN-04` unanchored truncated blocked = `True`.

| Spec | Scenario | Expected | Actual | Error Code | Pass |
|---|---|---|---|---|---|
| `LIN-01` | `derived_lineage_synthetic_laundering_blocked` | `rejected` | `rejected` | `synthetic_empirical_support` | `PASS` |
| `LIN-02` | `hash_verified_unread_binary_ancestor_allowed` | `accepted` | `accepted` | — | `PASS` |
| `LIN-03` | `chunked_large_text_window_head_tail_preserved` | `accepted` | `accepted` | — | `PASS` |
| `LIN-04` | `unanchored_large_text_tail_omitted_blocked` | `rejected` | `rejected` | `unread_positive_evidence` | `PASS` |

## Held-out Generalization: Realistic Controls (24 Zero-Leakage Cases)

- **Static Leakage Gate**: `leakage_strict_passed=True`, `heldout_lexical_overlap_count=0` (vs `parrhesia/gates.py` blacklists/heuristics).
- **False-Rejection Rate**: `0 / 24` (`0.0`, threshold `< 0.05`); false lexical advisories = `0 / 24`.

| Case | Family | Classification | Verdict | Actual | Export | Lexical Advisories | Pass |
|---|---|---|---|---|---|---|---|
| `HRC-01` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-02` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-03` | `randomized` | `causal_effect × identified_under_assumptions` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-04` | `prediction` | `prediction × externally_validated` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-05` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-06` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-07` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-08` | `quasi_experimental` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-09` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-10` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-11` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-12` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-13` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-14` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-15` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-16` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-17` | `prediction` | `prediction × externally_validated` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-18` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-19` | `prediction` | `prediction × externally_validated` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-20` | `mechanism` | `mechanism × component_tested` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-21` | `ml` | `computational × externally_evaluated` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-22` | `randomized` | `causal_effect × sensitivity_supported` | `supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-23` | `general` | `engineering × user_impact` | `partially_supported` | `accepted` | `exported` | `—` | `PASS` |
| `HRC-24` | `observational` | `causal_effect × sensitivity_supported` | `partially_supported` | `accepted` | `exported` | `—` | `PASS` |

## Held-out Generalization: Adversarial Paraphrases (12 Zero-Leakage Cases)

- **Honest P0 Boundary**: `6 / 12` (`50.0%`) caught by hard numeric/SQLite/tail gates (`HADV-01..06`); `6 / 12` (`50.0%`) uncaught natural-language paraphrases (`HADV-07, HADV-08, HADV-09, HADV-10, HADV-11, HADV-12`) pending live LLM review or P1 `effect_records`.

| Case | Category | Expected Mechanism | Observed Outcome | Error Code | Match |
|---|---|---|---|---|---|
| `HADV-01` | `null_effect_numeric_mismatch` | `caught_mechanically` | `caught_mechanically_hard` | `unanchored_effect_estimate` | `PASS` |
| `HADV-02` | `harm_sign_flip_numeric_mismatch` | `caught_mechanically` | `caught_mechanically_hard` | `unanchored_effect_estimate` | `PASS` |
| `HADV-03` | `stripped_outcome_numeric_fabrication` | `caught_mechanically` | `caught_mechanically_hard` | `unanchored_effect_estimate` | `PASS` |
| `HADV-04` | `sqlite_suppressed_failure_branches` | `caught_mechanically` | `caught_mechanically_hard` | `selective_execution_omission` | `PASS` |
| `HADV-05` | `sqlite_unadjusted_multiplicity_paraphrase` | `caught_mechanically` | `caught_mechanically_hard` | `unadjusted_execution_multiplicity` | `PASS` |
| `HADV-06` | `tail_window_numeric_contradiction` | `caught_mechanically` | `caught_mechanically_hard` | `unanchored_effect_estimate` | `PASS` |
| `HADV-07` | `pure_paraphrase_null_without_numbers` | `uncaught_without_llm_or_p1` | `uncaught_without_llm_or_p1` | — | `PASS` |
| `HADV-08` | `pure_paraphrase_stripped_outcome_without_numbers` | `uncaught_without_llm_or_p1` | `uncaught_without_llm_or_p1` | — | `PASS` |
| `HADV-09` | `pure_paraphrase_disguised_synthetic` | `uncaught_without_llm_or_p1` | `uncaught_without_llm_or_p1` | — | `PASS` |
| `HADV-10` | `pure_paraphrase_confounded_routine_care` | `uncaught_without_llm_or_p1` | `uncaught_without_llm_or_p1` | — | `PASS` |
| `HADV-11` | `pure_paraphrase_cherry_picked_sweep` | `uncaught_without_llm_or_p1` | `uncaught_without_llm_or_p1` | — | `PASS` |
| `HADV-12` | `pure_paraphrase_cjk_null_without_numbers` | `uncaught_without_llm_or_p1` | `uncaught_without_llm_or_p1` | — | `PASS` |

## Metamorphic Invariance Suite (12 Transforms)

- **Invariance Summary**: `12 / 12` preserved acceptance & export (`invariance_rate=1.0`, `false_advisories=2`).

| Transform | Base Case | Transform Type | Base -> Variant Outcome | Export | Advisories | Pass |
|---|---|---|---|---|---|---|
| `META-01` | `RCT-04` | `clause_reorder` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-02` | `RCT-04` | `append_adverse_event_null` | `accepted -> accepted` | `exported` | `possible_contradictory_evidence_text` | `PASS` |
| `META-03` | `RCT-04` | `replace_or_108` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-04` | `RCT-04` | `insert_literature_contrast` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-05` | `PRED-04` | `clause_reorder` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-06` | `PRED-04` | `append_adverse_event_null` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-07` | `PRED-04` | `replace_or_108` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-08` | `PRED-04` | `insert_literature_contrast` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-09` | `ML-04` | `clause_reorder` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-10` | `ML-04` | `append_adverse_event_null` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-11` | `ML-04` | `replace_or_108` | `accepted -> accepted` | `exported` | `—` | `PASS` |
| `META-12` | `ML-04` | `insert_literature_contrast` | `accepted -> accepted` | `exported` | `possible_contradictory_evidence_text` | `PASS` |

## P1 Structured `effect_records` Suite (12 Cases, Separate Column)

- **Computable Verification & Zero-FRR Summary**: `12 / 12` passed; Positive control `1/1` (`FRR=0.0`); Negative computable traps caught `11/11` (including `6/6` structured counterparts of `HADV-07..12`); SQLite SHA-256 `event_chain_status=verified` on `12/12`.

| Case | Counterpart | Family | Classification | Expected | Actual Error | Event Chain | Pass |
|---|---|---|---|---|---|---|---|
| `PEFF-01` | — | `randomized` | `causal_effect × sensitivity_supported` | `accepted` | — | `verified` | `PASS` |
| `PEFF-02` | — | `randomized` | `causal_effect × sensitivity_supported` | `primary_effect_crosses_null` | `primary_effect_crosses_null` | `verified` | `PASS` |
| `PEFF-03` | — | `randomized` | `causal_effect × sensitivity_supported` | `unanchored_effect_record` | `unanchored_effect_record` | `verified` | `PASS` |
| `PEFF-04` | — | `randomized` | `causal_effect × sensitivity_supported` | `effect_pvalue_ci_mismatch` | `effect_pvalue_ci_mismatch` | `verified` | `PASS` |
| `PEFF-05` | — | `randomized` | `causal_effect × identified_under_assumptions` | `effect_grim_inconsistent` | `effect_grim_inconsistent` | `verified` | `PASS` |
| `PEFF-06` | — | `randomized` | `causal_effect × sensitivity_supported` | `effect_direction_mismatch` | `effect_direction_mismatch` | `verified` | `PASS` |
| `PEFF-07` | `HADV-07` | `randomized` | `causal_effect × identified_under_assumptions` | `primary_effect_crosses_null` | `primary_effect_crosses_null` | `verified` | `PASS` |
| `PEFF-08` | `HADV-08` | `randomized` | `causal_effect × identified_under_assumptions` | `unanchored_effect_record` | `unanchored_effect_record` | `verified` | `PASS` |
| `PEFF-09` | `HADV-09` | `ml` | `computational × externally_evaluated` | `unanchored_effect_record` | `unanchored_effect_record` | `verified` | `PASS` |
| `PEFF-10` | `HADV-10` | `randomized` | `causal_effect × identified_under_assumptions` | `primary_effect_crosses_null` | `primary_effect_crosses_null` | `verified` | `PASS` |
| `PEFF-11` | `HADV-11` | `ml` | `computational × externally_evaluated` | `primary_effect_crosses_null` | `primary_effect_crosses_null` | `verified` | `PASS` |
| `PEFF-12` | `HADV-12` | `randomized` | `causal_effect × identified_under_assumptions` | `primary_effect_crosses_null` | `primary_effect_crosses_null` | `verified` | `PASS` |

## Verification Scope & Honesty Boundary

1. **What this verifies (`engineering × test_passed`)**: `dev_phrase_consistency` executes `40` L2 cases across `10` families, `9` `L1-Explore` cards, `60` Card A runs (`30` hard numeric rejections + `30` non-blocking lexical advisories + `60` calibrated flips), `60` Card B runs (`20` structural SQLite rejections + `20` non-blocking multiplicity advisories + `20` Holm-Bonferroni controls), `136` Card C symmetry audit runs (`calibrated_false_alarm_rate=0.0`), `6/6` paired twins, and `4/4` lineage/chunked-window specs. `heldout_generalization` passes zero-leakage check (`overlap=0`) with `0/24` realistic false rejections, catching `6/12` adversarial paraphrases mechanically while `6/12` natural-language paraphrases remain uncaught without live LLM review or P1 `effect_records`. `metamorphic_invariance` passes `12/12`. Separately, `p1_effect_records` verifies `12/12` structured P1 cases (`0` FRR on `PEFF-01`, `11/11` computable catches incl. `6/6` structured `HADV-07..12` counterparts, and `12/12` verified SQLite event chains). Prompt packets are exported across all 4 control arms (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`).
2. **What remains `NOT_RUN` (`UNKNOWN`)**: Live external GPT/Claude/Grok API runs across Arms `A`, `B-精简`, `B-全文`, and `E` require prior user approval per `docs/evaluation-plan.md` and are explicitly marked `external_llm_status: not_run`.
