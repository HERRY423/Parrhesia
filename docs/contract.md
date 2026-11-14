# Parrhesia 0.3.0 core contract (pilot; new cases v2, stored v1 compatibility)

`Engine(workspace).dispatch(action, payload) -> dict`. Only Python's standard library is required.
Expected errors raise `ContractError` with `.code`, `.message`, and `.as_dict()`; errors never advance the case.
The workspace must already be a directory. State is local in `.parrhesia/state.sqlite3` (`PRAGMA user_version = 2`, maintaining an append-only SHA-256 hash-chained `events` table with `prev_event_hash` and `event_hash`).
No action sends network requests, executes submitted code, invokes a model, or proves scientific validity.
JSON objects reject unknown fields, so misspelled safety-relevant fields do not silently disappear.

## Lifecycle

`draft -> frozen -> reviewed -> adjudicated -> export_pending -> exported`.
An optional review `review_status=needs_split` produces `review_blocked`; adjudication is then unavailable.
Start a narrower new case rather than silently omitting findings above the cap of three per role.

Evidence, hypotheses and the ledger may only be registered/edited in `draft`.
Freeze binds the draft, complete ledger, evidence hashes and hypothesis log to one revision digest,
and creates **both** reviewer packets atomically, before any review is accepted. Each review is final;
neither role can see the other through `review_packet`. The adjudicator gets both reviews only after
both arrive. To revise a frozen case, create a new case; records are never silently rewritten.
`get_case` is an author/operator audit endpoint, not a reviewer endpoint: it exposes context IDs and
submitted reviews. Host routing must restrict reviewers to their packet; this pilot is not a process
security sandbox against an agent deliberately accessing the database or other endpoints.

All timestamps are engine-recorded UTC. Reviewer `context_id` and `model`, evidence provenance,
scientific checks, confidence and adjudication are **self-reports**. Distinct context IDs are required,
but are not evidence of statistically independent reasoning or a completed independent validation.

## Claim schema v2: type × type-local evidence level + scope

New cases default to v2. Fields are **not** automatically translated from legacy `level`.
Existing stored v1 cases retain their original frozen input/digests; creating a new legacy case with `schema_version: 1` is rejected as `legacy_creation_disabled`; clients must use v2 for new cases. Reopening an old case does not upgrade, rewrite or re-freeze it. To migrate scientifically, create a new v2 case, register the actual evidence and reclassify explicitly; historical timestamps, review decisions and acceptance are not copied as new evidence. Legacy `level` is a historical category, not a v2 grade.

All v2 ledger claims replace `level` with `claim_type` and `evidence_level`, retaining required `scope`.
These three fields also apply to **decisions** (in addition to `boundary` for limitations).
Review findings replace `proposed_level` with `proposed_claim_type`, `proposed_evidence_level`, and `proposed_scope`.
V2 rejects legacy fields or mixtures; v1 rejects v2-only fields. Changing type or scope in adjudication requires an explicit rationale and revised text, evaluated only against the frozen evidence.

| claim_type | evidence_level (unordered, type-local descriptors) |
|---|---|
| `description` | `unassessed`, `recorded`, `measurement_checked`, `replicated` |
| `association` | `unassessed`, `unadjusted`, `adjusted`, `robust_association` |
| `prediction` | `unassessed`, `apparent`, `internally_validated`, `externally_validated`, `prospectively_evaluated` |
| `causal_effect` | `unassessed`, `unidentified`, `identified_under_assumptions`, `sensitivity_supported` |
| `mechanism` | `unassessed`, `compatible`, `component_tested`, `causal_chain_tested` |
| `necessity` | `unassessed`, `bounded_test`, `counterfactual_supported` |
| `sufficiency` | `unassessed`, `bounded_test`, `counterfactual_supported` |
| `synthesis` | `unassessed`, `mapped`, `critically_appraised`, `synthesized_with_uncertainty` |
| `theory` | `unassessed`, `conjectured`, `proved_under_assumptions`, `independently_checked` |
| `qualitative` | `unassessed`, `situated_description`, `interpretation_audited`, `triangulated` |
| `computational` | `unassessed`, `benchmark_measured`, `reproduced`, `externally_evaluated` |
| `engineering` | `unassessed`, `test_passed`, `host_accepted`, `user_impact` |

Scientific cases accept all types except `engineering`. General cases accept `description`, `computational`, `engineering`. V2 requires explicit coverage of all seven `checks` in both domains; only legacy v1 general cases retain the old not-applicable defaults.
There is no cross-type ranking, score, promotion or inference from an intervention flag.
`unassessed`, `unidentified`, `conjectured` cannot receive `supported` or `partially_supported`; they can remain explicit `insufficient_evidence` records. A claim that a conjecture exists is a different descriptive claim, not proof of the conjecture.

### V2 ledger records and shared assessment shape

Alongside the original `id`, `text`, `evidence_ids`, `effect`, `scope`, `origin`, `contribution`, alternatives/checks and optional hypothesis/research fields, v2 requires:

- `design_packages`: array of `{family, checks}`. Scientific cases require 1–9 different families; general cases may use an empty array. Choose applicable packages, not all nine.
- `statistical_report`: object with all eight keys below, each a shared assessment.
- `provenance_cards`: object containing all four card-kind arrays; empty arrays mean no cards registered, never work completed.
- `causal_basis`: required for `causal_effect`, `necessity`, `sufficiency` and `mechanism × causal_chain_tested`; optional otherwise. UNKNOWN records are allowed in a ledger so overclaims and missing evidence remain reviewable.
- `effect_records`: optional array of 0–50 structured endpoint records separating primary/benchmark effects from secondary/safety/exploratory/sensitivity records and enabling deterministic numeric anchoring, interval/p-value, GRIM/granularity, and direction polarity checks (see below).
- `prior_claim_links`: optional array of 0–20 append-only lineage links (`prior_case_id`, `prior_claim_id`, `relation` in `replicates | refines | narrows | extends | supersedes | reverses | refutes`, substantive `reason`, optional `triggered_reversal_id`) connecting this claim to frozen ancestor claims without mutating prior cases.
- `reversal_triggers`: optional array of 0–20 structured executable reversal conditions (`id`, `description`, `kind`, `target_verdict`, kind-specific predicate fields, optional `target_claim_type`, `target_evidence_level`, `target_scope`); also accepted on adjudication decisions.

A shared assessment is `{"status":"unknown", "reason":"Not supplied", "evidence_ids":[]}`.
Status: `pass | fail | unknown | not_applicable`; nonempty reason required. For design and statistical items, reason contains the actual reported details and location, or the explicit gap/inapplicability explanation, not just a success label. Evidence IDs must belong to this claim's registered `evidence_ids`, not merely another claim in the case. These are **registrant assessments**, not engine verdicts. No missing scientific field is silently filled with success.

| design_packages.family | Required keys in checks (each a shared assessment) |
|---|---|
| `observational` | `sampling_temporality`, `measurement`, `confounding_selection`, `missingness`, `robustness` |
| `quasi_experimental` | `assignment_rule`, `identification`, `diagnostics_placebos`, `local_scope`, `sensitivity` |
| `randomized` | `randomization_concealment`, `analysis_population`, `adherence_attrition`, `interference`, `harms` |
| `prediction` | `target_horizon`, `splits_leakage`, `calibration_discrimination`, `validation_shift`, `utility` |
| `ml` | `data_contamination`, `splits_tuning`, `baselines_budget`, `seeds_uncertainty`, `ablations_compute` |
| `mechanism` | `causal_model`, `specificity_controls`, `temporal_chain`, `rescue_orthogonal`, `rival_pathways` |
| `evidence_synthesis` | `protocol_search`, `eligibility_selection`, `bias_dependence`, `heterogeneity`, `certainty_missing_studies` |
| `theory` | `definitions_assumptions`, `proof`, `boundary_counterexamples`, `independent_check`, `empirical_bridge` |
| `qualitative` | `epistemic_position`, `sampling_context`, `reflexivity_ethics`, `analysis_audit`, `negative_cases_transfer` |

`statistical_report` requires: `units_sample_size`, `estimand_scale`, `estimate_uncertainty`, `model_assumptions`, `missingness_exclusions`, `multiplicity_selection`, `comparisons_baselines`, `robustness_limits`.
These cover units/N/denominators, estimand/scale, estimate and uncertainty, model assumptions, missingness/exclusions, multiplicity/selection, direct comparisons/baselines and robustness/limits. Theory and qualitative records use justified `not_applicable` assessments for genuinely inapplicable statistical items, not invented p-values.
See the [policy source](../policy/parrhesia-policy.md) for the scientific meaning and reporting boundaries of each package.

### Causal identification record and structural authorization

`causal_basis` has exactly these keys:

- `design_family`: one of the selected design-package families.
- `estimand`: nonempty text for `population`, `contrast`, `outcome`, `time_horizon`, `summary`, `intercurrent_events`. State population, treatment/comparator strategies, outcome, horizon, summary and handling of intercurrent events; distinguish estimand from estimator and estimate.
- `assumptions`: 1–30 objects with `name` plus a shared assessment, unique names.
- `falsification_sensitivity`: 1–30 objects with `name` plus a shared assessment, unique names. Record the relevant actual diagnostics and sensitivity range, not a claim that every design needs every possible test.
- `assessment`, `necessity_test`, `sufficiency_test`: shared assessments. The latter two are separate; record justified inapplicability unless the corresponding claim is made.

Positive empirical causal decisions must cite the **frozen** identification evidence. The selected family must be observational, quasi-experimental, randomized, mechanism or evidence synthesis. Assumptions, relevant falsification/sensitivity records and overall assessment must be `pass` with nonempty registered evidence references; the matching necessity/sufficiency assessment is additionally required for those types. The core estimand fields cannot be UNKNOWN/NA/NOT_IDENTIFIABLE. Required evidence must be cited in the decision. Randomization or intervention alone does not bypass these checks. New gated cases require intervention/quasi-experiment evidence kinds for `verdict="supported"`; purely observational evidence (`kind="observation"`) cannot receive `supported`, but can receive `partially_supported` (or a `partially_supported` reviewer stance) on `causal_effect × identified_under_assumptions` or `sensitivity_supported` when a substantive `condition` is supplied alongside a complete `causal_basis` (`design_family="observational"`) and an `observational` design package whose `sampling_temporality`, `confounding_selection` and `robustness` checks are all `pass` with cited `evidence_ids`. Unsupported/insufficient decisions preserve missing/failed records without pretending they pass; their assigned evidence level must still respect the check ceiling.

This is a **structural gate**. A `pass` means the submitter reports a justified assessment, not that untestable assumptions have been proved. The engine does not inspect causal language, validate scientific identification, establish statistical adequacy or certify source truth. Reviewers must check that all essential assumptions and appropriate diagnostics are actually represented. A logical necessity/sufficiency proof belongs to `theory`, with explicit assumptions; it does not certify an empirical causal claim.

### Four provenance card schemas

Each card is `{id, status, reason, evidence_ids, details}`. IDs must be unique across all four arrays within a claim. Status is `reported | checked | unknown | missing | failed | not_run | not_applicable`. A `checked` card requires a registered source but remains a caller-reported content check. All detail values are nonempty **strings**, preserving `0`, `NA`, `UNKNOWN` separately; do not convert missing values to zero.

| provenance_cards key | Required details keys |
|---|---|
| `citation` | `source`, `locator`, `claim_link`, `support_relation`, `read_extent` |
| `number` | `value`, `unit_denominator`, `population_time`, `derivation`, `uncertainty`, `locator` |
| `execution` | `command`, `code_version`, `inputs`, `environment`, `started_at`, `ended_at`, `exit_status`, `outputs`, `log_locator` (optional: `claim_id`, `run_group`, `fork_role`) |
| `search` | `database`, `query`, `searched_at`, `filters`, `coverage`, `results`, `selection`, `limitations` |

`citation` records the exact source-to-claim relationship and read extent. `number` records value, units/denominator, extraction/calculation basis and location. `execution` distinguishes actual invocation, completion, logs and outputs (optional `fork_role` in `primary | exploratory | exploratory_failed | auxiliary_failed | secondary_failed | sensitivity`, where a `checked` card cannot carry a failed `fork_role`, and optional `claim_id`/`run_group` for multi-claim fork scoping). `search` retains reproducible query, coverage, selection and limits; unknown result counts stay UNKNOWN. Cards cannot execute code, contact services or establish that a search/run happened. No passwords, tokens or unapproved patient identifiers belong in them.

All new fields are frozen, survive restart, are included in both review packets, and are displayed in Markdown and HTML reports. Reports label these as registrant records and preserve the original classification alongside the revised one.

### Structured effect records and computable checks (`effect_records`)

Claims may optionally carry `effect_records` (`0–50` items) so endpoint effects and safety/secondary outcomes are represented declaratively instead of relying on prose heuristics alone (`parrhesia/effects.py`):

- **Required keys (`REQUIRED_EFFECT_KEYS`)**: `id` (unique within the claim), `endpoint` (non-empty <= 500 chars), `endpoint_role` (`primary | secondary | safety | exploratory | sensitivity | benchmark`), `metric` (`HR | OR | RR | IRR | diff | mean_diff | risk_diff | proportion | rate | AUC | AUROC | RMSE | MAE | R2 | F1 | accuracy | logFC | beta | count | other`), `estimate` (finite JSON number), `direction` (`benefit | harm | null | non_inferior | equivalence | higher_better | lower_better | neutral`), and `evidence_id` (registered case evidence).
- **Optional keys (`OPTIONAL_EFFECT_KEYS`)**: `null_value` (defaults to `1.0` for ratio metrics `HR | OR | RR | IRR`, `0.0` for difference metrics `diff | mean_diff | risk_diff | logFC | beta`, else omitted), `ci_level` (`0 < ci_level < 1`, default `0.95` for Wald compatibility), `ci_low` and `ci_high` (must supply both or omit both, satisfying `ci_low <= estimate <= ci_high`), `p_value` (`0.0 <= p_value <= 1.0`), `n` (`int >= 1`), `events` (`int >= 0`, `events <= n` for binary proportions/accuracy), `decimals` (`int in [0, 8]`), `scale` (`unit | percentage`, default `unit`), `beneficial_if` (`below_null | above_null`), `quote_substring`, `notes`, `claim_direction` (same enum as `direction`, optional assertion of the proposition), `inference_method` (`wald | log_wald | student_t | other | unknown`), and `count_basis` (`unweighted_binary | other | unknown`).
- **Structural & computable checks (`validate_effect_records` & `verify_effect_computations`)**:
  - Bounds and internal math remain hard checks. CI-p consistency runs only for explicitly declared matching, unadjusted, two-sided `wald` or `log_wald` test/CI pairs; omitted/other methods return `unassessed`, not a pass. `student_t` is recorded but not numerically verified. GRIM and events/n checks apply only to `proportion | accuracy` with `count_basis="unweighted_binary"`, where n denotes the exact count denominator. Weighted estimates, incidence rates, ratios, AUC and F1 are not treated as binomial fractions. Declaring a method or denominator is a source-supported assertion, never a repair shortcut.
  - Anchoring & polarity on positive decisions (`supported`, `partially_supported`): `unanchored_effect_record` requires `estimate`, `[ci_low, ci_high]`, `p_value`, and optional `quote_substring` to match the cited `evidence_id`'s quote or snapshot text; `effect_direction_mismatch` validates `direction` against `estimate` vs `null_value` and `beneficial_if`.
  - `supported` means the proposition is supported, not that an effect is beneficial. Both benefit and harm may be supported. Optional `claim_direction` declares the direction asserted by the proposition; a conflicting observed direction is rejected. A supported directional primary/benchmark assertion (`benefit | harm | higher_better | lower_better`) whose interval crosses null is rejected. Without `claim_direction`, alignment is `unassessed`; a descriptive null result is not automatically rejected or interpreted as equivalence. Secondary/safety null effects do not veto another endpoint. Supporting primary sources must still be cited. Margin-based non-inferiority/equivalence and semantic support require review.
  - Non-blocking symmetry hook: if `verdict="unsupported"` conflicts with strictly beneficial, anchored `primary`/`benchmark` records, `symmetry_audit` emits `unsupported_despite_beneficial_primary_effect` without blocking export.

### Cross-time claim graph, executable reversal triggers, and calibration

Parrhesia extends single-case review into an immutable, append-only longitudinal DAG with deterministic reversal evaluation and post-adjudication calibration (`parrhesia/triggers.py`, `parrhesia/calibration.py`):

- **Longitudinal case & claim graph (`create_case`, `set_ledger`, `claim_graph`)**:
  - `create_case` accepts optional `prior_case_ids` (`0–20`), `supersedes_case_id`, and `case_relation` (`follow_up | replication | reanalysis | correction | extension | retraction`). Whenever `supersedes_case_id` is supplied, `_set_ledger` merges it with `prior_case_ids`, and every `prior_claim_links[].prior_case_id` must belong to the case's declared prior cases (`unlinked_prior_case`) and point to a real claim (`unknown_prior_claim`).
  - Prior frozen cases, digests, and exports remain untouched; acyclic lineage trajectories and `active_standing` (precedence `reversed > refuted > superseded > narrowed > refined > replicated`) are computed read-only by `claim_graph`. Replacement edges remain visible as `pending` until an effective adjudication (`adjudicated | export_pending | exported`, no active pause/challenge/defer or stored blocked verification). Claim edges require a supported/partially-supported successor decision; case-wide supersession requires all successor decisions positive and nonempty. Draft/frozen/held/negative successors do not change prior standing.
  - When a prior claim carried `reversal_triggers` and a follow-up link declares `triggered_reversal_id`, adjudication requires the named trigger ID to exist (`unknown_reversal_trigger`) and actually fire on the follow-up claim (`untriggered_reversal_link`); declaring `reverses` or `refutes` against a positively supported prior claim without changing its wording/scope/verdict fails with `contradictory_claim_lineage_transition`.
- **Executable reversal triggers (`reversal_triggers`, `evaluate_triggers`)**:
  - Five trigger kinds (`TRIGGER_KINDS`) are supported (`0–20` triggers per claim or decision):
    1. `effect_metric`: compares an `effect_records` field (`estimate | ci_low | ci_high | p_value | n | events`) using `operator` (`lt | le | gt | ge | eq | ne | crosses_null | excludes_null | outside_band | inside_band`), `metric`, optional `endpoint`, `endpoint_role`, `threshold`, `band_low`/`band_high`, `null_value`.
    2. `check_status`: fires when `target_check` resolves in `target_statuses` (`pass | fail | unknown | not_applicable`).
    3. `evidence_status`: fires when evidence (specific `evidence_id` or any cited item) enters `trigger_on` (`blocked | unverified | contradicts`).
    4. `execution_outcome`: fires on SQLite `record_exec` runs matching optional `fork_role` and `exit_operator` (`non_zero | eq | ne`, optional `exit_status`).
    5. `replication_verdict`: fires when graph-linked downstream claims matching `relations` (default `replicates | refutes | reverses | supersedes`) carry a verdict in `target_verdicts`.
  - At `submit_adjudication`, non-`replication_verdict` triggers are checked against the claim's own frozen evidence, effects, and checks; a claim cannot be finalized if its own reversal trigger already fires in conflict (`self_triggering_reversal_condition`).
  - `evaluate_triggers` evaluates all triggers read-only against `against_case_id`, inline `observations`, or live workspace state (`verify`, SQLite `record_exec`, graph descendants), classifying each trigger as `fired`, `unfired`, or `pending_data`.
- **Measurable calibration (`forecast_probability`, `record_calibration_outcome`, `calibration_report`)**:
  - Adjudication `decisions` accept optional `forecast_probability` in `[0.0, 1.0]` alongside `confidence` and `confidence_reason` (default mapping when omitted: `high=0.85`, `medium=0.60`, `low=0.30`).
  - `record_calibration_outcome` appends post-adjudication (`adjudicated | export_pending | exported`) outcomes (`replicated | partially_replicated | refuted | inconclusive`, optional `outcome_score` in `[0.0, 1.0]`, `resolution_source` in `follow_up_case | external_evidence | trigger_evaluation`, optional `follow_up_case_id`, `follow_up_claim_id`, `evidence_id`, `observed_estimate`, `observed_ci_low`, `observed_ci_high`, `metric`, substantive `reason`) without mutating frozen `input_digest`, `adjudication_digest`, or exported artifacts.
  - `calibration_report` separates explicit forecasts with source-verified binary outcomes (`proper_scores`, reliability bins, ECE/MCE) from descriptive `heuristic_scores` using confidence mappings or soft outcomes. The legacy `proper_scores.combined_*` fields are null. Confidence strata remain descriptive and labeled. Source verification establishes identity and binding, not truth, independent replication or prospective forecasting.

### Complete v2 input example

[claim-v2-unknown.json](examples/claim-v2-unknown.json) is a complete, schema-valid **blank claim** with no fabricated data: all unknowns are explicit, execution/search cards are `not_run`, and its classification is `description × unassessed`. It can be passed as the sole element of `set_ledger.claims` in a newly created scientific v2 case. Supply the generated `case_id` in the action payload. It cannot receive a positive verdict as written.

Replace only fields justified by actual materials, select the applicable design package and register evidence before adding its IDs. For a causal claim add the full `causal_basis` specified above; do not convert the example by simply changing its type or grade.

The legacy examples below retain v1 syntax **only for already stored schema_version=1 cases**. For v2 reviews/decisions replace the classification fields as specified above; all existing coverage, identity, freeze, reference, verdict, condition and disposition rules still apply.

## Payloads

### Current anti-stall gates: gate_version=1

New v2 cases always receive `gate_version: 1`; callers cannot set or disable it. All added inputs below are required for these cases. Saved v1 and v2 cases without this field keep their historical contract and digests. New v1 creation is disabled; stored legacy cases remain recoverable and their reports are labeled `LEGACY_UNGATED`; neither they nor historical v2 reports certify current gate acceptance. To adopt current gates, create a new v2 case and re-register/re-review evidence. No automatic scientific migration occurs.

`claim_basis` is required on ledger claims and decisions, and `proposed_claim_basis` on findings:
`empirical | synthetic | formal`. Formal is reserved for `theory` (and mandatory there). Synthetic permits only description/computational types; positive synthetic decisions are limited to `description × recorded` and `computational × benchmark_measured`. Any synthetic kind **or** provenance in a positive decision's references prohibits empirical/formal support, including mixed references. Changing basis for a positive decision requires both revised wording and a changed scope. Labels are caller declarations; the engine cannot detect fraudulent provenance or parse scientific semantics.

#### Type-local check ceilings

Both packets show `check_ceilings` with `allowed_levels`, `blocked_levels` (path/status) and `verdict_ceiling`. This is not a numeric or cross-type ladder. Ledger claims may retain high proposed levels for review. Every final decision must use an allowed level; negative verdicts do not legitimize a falsely high evidence grade. Both positive verdicts (`supported`, `partially_supported`) and positive reviewer stances must pass all applicable gates.

| Target type/level | Fixed essential seven-check keys |
|---|---|
| Any unassessed/unidentified/conjectured | None; no positive verdict permitted |
| description / recorded | None; literal anchored record only |
| description / measurement_checked | quality, unit |
| description / replicated | quality, unit, batch |
| association / unadjusted | quality, unit, assumptions |
| association / adjusted, robust_association | quality, unit, assumptions, batch, multiplicity, baseline |
| theory / proved_under_assumptions | assumptions, unit |
| theory / independently_checked | assumptions, unit, quality, baseline |
| qualitative / situated_description | quality, unit |
| qualitative / interpretation_audited | quality, unit, assumptions, batch |
| qualitative / triangulated | quality, unit, assumptions, batch, multiplicity, baseline |
| synthesis / mapped | quality, unit, assumptions |
| synthesis / critically_appraised, synthesized_with_uncertainty | quality, unit, assumptions, batch, multiplicity, baseline |
| mechanism / compatible | quality, unit, assumptions |
| mechanism / component_tested, causal_chain_tested | quality, unit, assumptions, batch, multiplicity, baseline |
| engineering / test_passed | quality, baseline |
| engineering / host_accepted | quality, baseline, unit |
| engineering / user_impact | quality, baseline, unit, assumptions |
| prediction or computational / all positive levels | quality, unit, assumptions, leakage, baseline, multiplicity |
| Remaining positive types/levels | quality, unit, assumptions, batch, multiplicity, baseline |

Fixed essential keys must be `pass` with a substantive `reason` (bilingual trivial placeholders such as `"ok"`, `"pass"`, `"yes"`, `"done"`, `"TBD"`, `"TODO"`, `"see above"`, `"未知"`, `"无"`, `"待定"`, `"见上"`, `"通过"`, `"合格"` or `<6`-unit strings are downgraded to `unknown` on both `pass` and `not_applicable` checks, while explicit `fail` stays `fail`); fail/unknown/not_applicable block. Whenever fixed checks apply, all selected design-package checks also apply across **all nine design families**: unknown/fail block, a selected design package cannot mark all of its checks `not_applicable` (`all_not_applicable`), and every `pass` item in `design_packages` or `statistical_report` must include non-empty `evidence_ids` and a substantive `reason` (and those `evidence_ids` must be cited in any positive decision, or `uncited_check_evidence` is raised). Even where `critical_paths` is empty (`description × recorded`) or no tier-essential statistical checks are required (`description`, `theory`, `qualitative`, `engineering` at base tiers), explicit `fail` items in `design_packages` or `statistical_report` and `provenance_cards` failures/contradictions still block the ceiling. Essential design and statistical checks scale progressively across adjacent `evidence_level` grades so adjacent levels cannot be relabeled interchangeably:
- `observational`: tier 1 (`unadjusted`, `measurement_checked`) requires `sampling_temporality`, `measurement`; tier 2 (`adjusted`, `identified_under_assumptions`, `replicated`) adds `confounding_selection`; tier 3 (`robust_association`, `sensitivity_supported`) adds `missingness`, `robustness`.
- `quasi_experimental`: tier 1/2 (`identified_under_assumptions`, `bounded_test`) requires `assignment_rule`, `identification`, `diagnostics_placebos`; tier 3 (`sensitivity_supported`, `counterfactual_supported`) adds `local_scope`, `sensitivity`.
- `randomized`: tier 1/2 requires `randomization_concealment`, `analysis_population`, `adherence_attrition`; tier 3 adds `interference`, `harms`.
- `prediction`: `apparent` (`target_horizon`, `calibration_discrimination`) < `internally_validated` (+ `splits_leakage`) < `externally_validated` (+ `validation_shift`) < `prospectively_evaluated` (+ `utility`).
- `ml`: `benchmark_measured` (`baselines_budget`, `splits_tuning`) < `reproduced` (+ `data_contamination`, `seeds_uncertainty`) < `externally_evaluated` (+ `ablations_compute`).
- `mechanism`: `compatible` (`causal_model`) < `component_tested`/`bounded_test` (+ `specificity_controls`, `temporal_chain`) < `causal_chain_tested`/`counterfactual_supported` (+ `rescue_orthogonal`, `rival_pathways`).
- `evidence_synthesis`: `mapped` (`protocol_search`, `eligibility_selection`) < `critically_appraised` (+ `bias_dependence`, `heterogeneity`) < `synthesized_with_uncertainty` (+ `certainty_missing_studies`).
- `theory`: `proved_under_assumptions` (`definitions_assumptions`, `proof`) < `independently_checked` (+ `boundary_counterexamples`, `independent_check`).
- `qualitative`: `situated_description` (`epistemic_position`, `sampling_context`) < `interpretation_audited` (+ `reflexivity_ethics`, `analysis_audit`) < `triangulated` (+ `negative_cases_transfer`).

Statistical report requirements likewise progress by tier (`units_sample_size`, `estimate_uncertainty` at tier 1; + `model_assumptions`, `comparisons_baselines` at tier 2; + `robustness_limits` at tier 3). Provenance cards with `status` in `failed | missing` (unless an `execution` card has `details.fork_role` in `exploratory_failed | auxiliary_failed | secondary_failed` with a substantive `reason` alongside at least one passing `exit_status=0` execution card, which then triggers multi-fork multiplicity enforcement instead of deadlocking the ceiling), or `citation` cards whose `support_relation` is contradicting (`is_contradicting_relation()` matches both exact labels like `unsupported`, `contradicts`, `refutes`, `不支持`, `反对` and natural-language rewrites such as `"does not support"`, `"fails to support"`, `"cannot support"`, `"contrary to"`, `"inconsistent with"`, `"无法支持"`, `"不能支持"`, `"不足以支持"`, `"与主张矛盾"`, `"相悖"`, `"证伪"`, `"推翻"`, while respecting double negations such as `"does not contradict"` / `"不矛盾"`), block positive verdicts and ceilings (even on `description × recorded`); any `checked` `number`, `execution` or `citation` card must have its `evidence_ids` cited in a positive decision. Nonessential seven-check items remain visible in the report. A literal record can be supported despite unverified measurement quality; that does not support the measurement's truth. Runtime reasons/statuses are reported assessments, not independently verified facts.

Causal type/level ceilings additionally include `causal_basis` assessment, assumptions, the corresponding necessity/sufficiency test, and core estimand completeness; `falsification_sensitivity` is required to `pass` with cited `evidence_ids` specifically for `sensitivity_supported`, `counterfactual_supported`, and `causal_chain_tested` (while an explicit `fail` on `falsification_sensitivity` blocks all positive causal levels). Missing basis, unknown/failing assessments or pass labels without evidence references cannot retain an identified causal evidence grade even in a negative verdict; use unassessed/unidentified as appropriate. Negative reviewer stances may still reject the overgraded original wording without modifying the ledger.

#### Evidence kind × claim type/level compatibility

Every cited reference in a positive judgment must match the table; an incompatible supplementary citation cannot be smuggled into the supporting reference list. Keep contextual material in the ledger and explain its non-supporting role. Unassessed/unidentified/conjectured levels have no compatible positive evidence. `unknown` never supports a positive verdict.

| claim_type / evidence_level | Allowed evidence kind |
|---|---|
| description / recorded | Any listed known kind, including synthetic (subject to claim_basis) |
| description / measurement_checked, replicated | Any listed known kind except synthetic |
| association / all positive levels | observation, intervention, quasi_experiment |
| prediction / apparent | prediction_fit, prediction_internal, prediction_external, prediction_prospective |
| prediction / internally_validated | prediction_internal, prediction_external, prediction_prospective |
| prediction / externally_validated | prediction_external, prediction_prospective |
| prediction / prospectively_evaluated | prediction_prospective |
| causal_effect / identified_under_assumptions, sensitivity_supported | intervention, quasi_experiment (or `observation` for `partially_supported` with explicit `condition`, `observational` design checks `pass`, and complete `causal_basis`) |
| necessity, sufficiency / all positive levels | intervention, quasi_experiment |
| mechanism / compatible | observation, mechanistic_assay, intervention, quasi_experiment |
| mechanism / component_tested | mechanistic_assay, intervention, quasi_experiment |
| mechanism / causal_chain_tested | intervention, quasi_experiment |
| synthesis / all positive levels | systematic_review |
| theory / all positive levels | theoretical_proof |
| qualitative / all positive levels | qualitative_material |
| computational / benchmark_measured | benchmark, benchmark_replication, benchmark_external, synthetic |
| computational / reproduced | benchmark_replication, benchmark_external |
| computational / externally_evaluated | benchmark_external |
| engineering / test_passed | test_log, host_acceptance, user_outcome |
| engineering / host_accepted | host_acceptance, user_outcome |
| engineering / user_impact | user_outcome |

`kind` accepts exactly the distinct values above plus `unknown`. `kind=synthetic` requires `provenance=synthetic`; synthetic provenance is also detected when kind is another category. Compatibility with the matrix above is enforced mechanically as a hard rejection (`incompatible_evidence_kind`). Positive decisions and stances also undergo mechanical numeric and structural checks: `unanchored_effect_estimate` checks signed effect/CI numbers and reduction polarity unconditionally across `claim_type`/`claim_basis` changes (prioritizing `quote`/local windows and `provenance_cards.number` over `Table N`/`Fig N`/`alpha=`/`p=` clutter); when `effect_records` are supplied, deterministic checks also enforce `unanchored_effect_record`, `effect_interval_inconsistent`, `invalid_ratio_effect`, `effect_pvalue_ci_mismatch`, `effect_granularity_mismatch`, `effect_grim_inconsistent`, `effect_direction_mismatch`, `primary_effect_crosses_null` (isolating `primary`/`benchmark` endpoints from benign null `secondary`/`safety`/`exploratory`/`sensitivity` records), and `uncited_primary_effect`; structural `provenance_cards` `support_relation` contradictions fail critical checks (`critical_check_ceiling`), and execution-fork multiplicity checks (`validate_execution_forks`) load SQLite `record_exec` events alongside logs, scope per `claim_id`/`run_group` when supplied so unrelated claims do not cross-contaminate, reject failed non-zero `exit_status`, `not_run` evasion of recorded runs (`unaccounted_ev_ids`), and `unlinked_events` with `selective_execution_omission`, and require a valid `multiplicity_selection` citation (`unadjusted_execution_multiplicity`) when structural multi-fork evidence (`fork_count > 1`) is present. By contrast, pure free-text lexical cues (such as weaker study-design caveats like `"no randomization"` / `"internal validation only"`, outcome-pending text, null/refuting prose phrases, or execution-omission/multiplicity prose without structural fork mismatches) do **not** raise hard rejections; instead they emit non-blocking `symmetry_audit["lexical_advisories"]` (`hook_code` in `possible_evidence_kind_mismatch`, `possible_outcome_pending_text`, `possible_contradictory_evidence_text`, `possible_execution_omission_text`, `possible_unadjusted_multiplicity_text`). Compatibility is necessary, not sufficient: actual replication, source relevance, design adequacy and semantic support still require review. Intervention labels alone never authorize causal wording.

#### Anchors, unread sources, stances and findings

- Registration: required `kind`, optional boolean `unread_content_ack`. Unread binary sources require this flag to be true. UTF-8 text excludes PDF/archive/image/ELF signatures (`%PDF-`, `PK\x03\x04`, `\x89PNG`, `\xff\xd8\xff`, `\x1f\x8b`, `GIF8`, `\x7fELF`) and NUL-bearing or arbitrary control-character buffers, while automatically stripping ANSI terminal CSI/OSC escape sequences (`\x1b[...m`, etc.) and benign terminal formatting controls (`\b`, `\f`, `\v`, `\a`, BOM) so `record-exec` logs with color codes remain readable UTF-8 text.
- Any supplied `quote` must have at least **12 visible non-whitespace units (`MIN_QUOTE_CHARS = 12`, where CJK ideographs/syllables count as 2 units each so `MIN_CJK_QUOTE_CHARS = 6` CJK characters $\equiv$ 12 ASCII characters; control/format, combining-mark and private-use codepoints do not count)**, occur exactly once in the complete saved text (overlapping matches count), and match literally. Bad supplied quotes fail registration. A source may be registered without quote/location, but **every positive reference** must have both a valid quote, a concrete non-placeholder `location` (`is_placeholder()` rejects both English placeholders like `UNKNOWN/NA/N/A/NONE/NULL/NIL/TBD/TODO/PENDING/SEE ABOVE` and Chinese placeholders like `未知/无/暂无/待定/待填/未运行/不适用/见上/同上/如上/略` as well as punctuation-only strings), and a substantive lexical/numeric/card-locator link to the claim (`unlinked_evidence_quote` rejects unrelated boilerplate quotes).
- Packets cap per-source inline UTF-8 text at **128 KiB** (`PACKET_TEXT_BYTES`, bounding prompt context size). When a readable UTF-8 text source exceeds 128 KiB, the engine constructs sorted, merged **chunked excerpt windows** (`excerpt_windows`, with backward-compatible summary `excerpt_window` including `start_char`, `end_char`, `start_line`, `end_line`, `total_chars`, `total_lines`, `quote_anchored`, and `window_count`) strictly within `<= 128 KiB` UTF-8 bytes covering `head_metadata`, centered `quote_primary` (when quoted), centered `anchor_excerpt` for each item in optional `excerpt_anchors` (1–8 distinct verbatim anchors), and `tail_summary`. Window chunks are delimited with `<<<PARRHESIA_EXCERPT_WINDOW index=... role=... chars=... lines=... of total_chars=...>>>` markers, which mechanical number/polarity/lexical scanners (`gates.py:strip_window_markers`) strip before checking evidence so window headers never pollute numeric anchoring. When `quote` is uniquely anchored (`excerpt_window.quote_anchored = true`), large logs or manuscripts can support positive verdicts without manual file slicing once acknowledged in `unread_evidence_ids`. Unquoted $> 128\text{ KiB}$ sources (`quote_anchored = false`), binary files, and missing sources cannot directly support positive verdicts even with acknowledgment. Every review and adjudication requires `unread_evidence_ids` listing all sources where `source_text_status != "complete"`; submit `[]` when none.
- Derived evidence lineage (optional on gated v2 `register_evidence` and `record-exec`): pass `derived_from_evidence_ids` (known registered IDs in the case) alongside a meaningful `derivation_step` ($\le 2000$ chars; orphan `derivation_step` without nonempty parents is rejected). Mechanical validation (`validate_mechanical`) inspects transitive ancestors (`evidence_lineage`) and blocks empirical/formal positive decisions citing any evidence with a `synthetic` ancestor (`synthetic_empirical_support`), cycle (`invalid_lineage`), or unknown ancestor. `verify` computes transitive `lineage_status` (`not_derived | verified | hash_verified_unread_binary_ancestors | unverified | blocked`) and exposes `evidence_chains`. When a raw binary file (`unread_content_ack = true`) has intact snapshot and disk hashes (`hash_verified_unread_binary_ancestors`) and feeds a readable verified derived summary text file (`derived_from_evidence_ids`), citations to the verified derived summary can export positive decisions, while any missing, corrupted (`blocked`), or unacknowledged binary ancestor blocks or downgrades the derived leaf.
- Non-blocking anti-underclaim, false-abstention & lexical cue symmetry audit (`audit_underclaim_and_abstention` + `collect_lexical_advisories`): `submit_review`, `submit_adjudication`, `verify`, Markdown reports, and HTML reports attach a strictly **non-blocking** `symmetry_audit` payload (`non_blocking: true`, `severity: "advisory"`; it never raises `ContractError` and never blocks review, adjudication, or export). Underclaim/abstention `flags` emit `possible_false_abstention`, `possible_unjustified_downgrade`, `unsupported_without_counterevidence`, `unsupported_despite_beneficial_primary_effect` (when `verdict="unsupported"` conflicts with strictly beneficial anchored `primary`/`benchmark` `effect_records`), `possible_boilerplate_overhedging`, and `rejected_underclaim_finding_advisory` when nonpositive/downgraded verdicts conflict with mechanically admissible evidence/checks or lack counterevidence. Separately, `lexical_advisories` (`lexical_advisory_count`) surfaces pure free-text heuristic cues (`possible_evidence_kind_mismatch`, `possible_outcome_pending_text`, `possible_contradictory_evidence_text`, `possible_execution_omission_text`, `possible_unadjusted_multiplicity_text`) as review aids without blocking valid scientific prose.
- `submit_review.claim_stances`: exactly one `{claim_id, stance, rationale, evidence_ids}` per frozen claim, even with zero findings (operational cap: **0–3 findings per reviewer role** to focus each review pass on the highest-impact issues rather than nitpicking; if $>3$ substantive issues exist, set `review_status="needs_split"`). `stance` uses the four verdict enums. A `partially_supported` stance additionally requires a substantive `condition`; empty, invisible-only or bilingual placeholder conditions are rejected. The same placeholder checks apply to final decision, estimand, and partial adoption conditions.
- Optional `isolation_attestation` object (`{"history_inheritance": "...", "memory_access": "...", "host_surface": "..."}`, all optional caller-reported strings $\le 200$ chars) is accepted on both `submit_review` and `submit_adjudication`. Any omitted fields default to `"UNKNOWN"` in Markdown `input_manifest` / `adjudication_isolation_attestation` blocks and HTML `reviewer_input_manifests` / `adjudication_isolation_attestation` (never hardcoded as isolated; attestation fields remain caller self-reports).
- Each disposition adds `claim_id` and `resolution` (`incorporated | disagreement`). `incorporated` requires `revised_text_quote` ($\ge 12$ visible non-whitespace units: $\ge 6$ CJK or $\ge 12$ ASCII characters), unique in both `finding.proposed_text` and final `revised_text`, case-insensitively absent from `original.text`, and substantively incorporating the finding: `revised_text` cannot retain the unrevised `original.text` verbatim with an appended clause, cannot retain all substantive tokens that `proposed_text` removed or any criticized tokens from `finding.issue` that `proposed_text` removed, and must adopt the issue-linked replacement tokens (`salient_new`) from `proposed_text` (for `partial` adoption, `revised_text_quote` itself must anchor those issue-linked replacement tokens rather than a trailing filler clause). `accepted` incorporation additionally requires the whole `proposed_text` and exact proposed type/level/scope/basis in the decision. Partial incorporation requires `condition`. A rejected disposition cannot be incorporated.
- An unincorporated or divergent recommendation must use `resolution=disagreement` plus substantive `disagreement`, with no `revised_text_quote`. This is allowed even when the adjudicator accepts the underlying criticism; the report exposes the retained wording and disagreement instead of treating an accepted label as implementation. All dispositions bind the finding to the decision for the same claim.
- `create_case.blind` is boolean, defaults true, and is frozen case-wide. Both review packets omit draft and the author research-framing fields best_current_explanation/discriminating_test when true. Per-request blind overrides are rejected, even if equal to the case value. Set false explicitly at creation for a nonblind case. It is packet filtering, not a security sandbox; question/source/claim text can contain framing and must be curated by the operator.

Rejection codes include `critical_check_ceiling`, `synthetic_empirical_support`, `incompatible_evidence_kind`, `unanchored_effect_estimate`, `unanchored_effect_record`, `primary_effect_crosses_null`, `effect_direction_mismatch`, `effect_interval_inconsistent`, `invalid_ratio_effect`, `effect_pvalue_ci_mismatch`, `effect_granularity_mismatch`, `effect_grim_inconsistent`, `uncited_primary_effect`, `selective_execution_omission`, `unadjusted_execution_multiplicity`, `unanchored_positive_evidence`, `unlinked_evidence_quote`, `uncited_check_evidence`, `invalid_quote`, `unread_ack_required`, `unread_positive_evidence`, `incomplete_stances`, `finding_decision_mismatch`, `finding_not_incorporated`, `missing_disagreement`, `contradictory_resolution`, `case_level_blind`, `legacy_creation_disabled`, `unsupported_contract_version`, `missing_stance_condition`, `invalid_condition`, `unlinked_prior_case`, `unknown_prior_claim`, `unknown_reversal_trigger`, `self_triggering_reversal_condition`, `contradictory_claim_lineage_transition`, `untriggered_reversal_link`, and `invalid_calibration_outcome`. Pure lexical cue mismatches (`possible_evidence_kind_mismatch`, `possible_outcome_pending_text`, `possible_contradictory_evidence_text`, `possible_execution_omission_text`, `possible_unadjusted_multiplicity_text`) and `unsupported_despite_beneficial_primary_effect` are emitted in non-blocking `symmetry_audit` rather than blocking rejection codes. Unknown stored schema/gate versions are rejected rather than interpreted as legacy. Rejected submissions do not advance or mutate stored workflow state.

Minimal current review extension (merge into the common payload below):

```json
{"claim_stances":[{"claim_id":"C1","stance":"insufficient_evidence","rationale":"Measurement checks remain unknown","evidence_ids":[]}],"unread_evidence_ids":[]}
```

Current incorporated disposition example:

```json
{"finding_id":"O1","claim_id":"C1","disposition":"accepted","reason":"The original scope exceeded the supplied record","resolution":"incorporated","revised_text_quote":"Exact proposed replacement wording"}
```

Add `unread_evidence_ids` at adjudication top level and `claim_basis` to every decision (and optional `isolation_attestation` on reviews/adjudications). Findings add `proposed_claim_basis`. The action examples explicitly labeled legacy below retain their legacy shapes for compatibility, not current acceptance.

Every action except `create_case` and `scaffold_claim` requires `case_id`. Generated IDs must be used exactly.

### scaffold_claim

```json
{"case_id":"optional-case-id", "claim_id":"C1", "claim_type":"causal_effect", "evidence_level":"unassessed", "design_families":["observational"], "include_causal_basis":true, "include_effect_records":false, "include_reversal_triggers":false, "include_prior_claim_links":false}
```

Read-only helper that generates a complete, schema-valid v2 claim skeleton with explicit `unknown` assessments and `not_run` execution/search cards (never pre-filled with fake `pass` values), plus optional empty `"effect_records": []`, `"reversal_triggers": []`, and `"prior_claim_links": []` scaffolds when enabled, and a `check_ceilings` preview showing exactly which checks are currently blocking each `evidence_level`. Does not mutate case state. In addition, the CLI provides `python -m parrhesia record-exec --workspace <dir> [--case-id <id>] [--claim-id <cid>] [--run-group <grp>] [--fork-role <role>] [--input-file <path> ...] [--output-file <path> ...] [--stdout-excerpt-chars <n>] [--code-version <str>] [--inputs <str>] [--outputs <str>] [--derived-from <ev_id> ... --derivation-step <text>] [-- <command...>]` to execute a local command, capture stdout/stderr and timestamps into a unique workspace log file (`artifacts/exec-logs/exec-<timestamp>.log` when `--log-path` is omitted, preventing consecutive-run overwrites), verify declared regular workspace `--input-file` SHA-256 digests pre-run and `--output-file` digests pre/post-run (missing declared outputs mark card `status="failed"`), capture `git` (`HEAD`/branch/dirty/streaming diff SHA-256), lockfiles (`pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`, `package-lock.json`, `Cargo.lock`, `Pipfile.lock`, `environment.yml`), non-secret runtime markers (never reading `os.environ` secret values), and sanitized `stdout_excerpt` (default `400`, capped at `2000`), optionally register the log as `observed` evidence (recording `--derived-from` lineage metadata and non-empty `provenance`) and record a scoped `record_exec` SQLite event, and emit a schema-valid `execution` provenance card JSON alongside `provenance`.

### create_case

```json
{"question":"The concrete question", "draft":"Full initial draft", "domain":"scientific", "schema_version":2, "blind":true, "writer_context_id":"writer-1", "prior_case_ids":["..."], "supersedes_case_id":"...", "case_relation":"replication"}
```

`domain` is optional (`scientific` default; `general` also supported). `writer_context_id` is optional;
when absent, separation from the writer remains explicitly unknown. `prior_case_ids`, `supersedes_case_id`, and `case_relation` (`follow_up | replication | reanalysis | correction | extension | retraction`) are optional longitudinal pointers validated against existing workspace cases without mutating those prior cases. `schema_version` defaults to integer `2`; explicit integer `1` is rejected for creation; v1 applies only to recovery of already stored cases. Other values (including booleans) are rejected. Returns `case_id`, `state`, `created_at`, `schema_version`, and supplied longitudinal fields.

### register_evidence

```json
{"case_id":"...", "path":"evidence/results.txt", "label":"Observed output", "kind":"observation", "provenance":"reported", "quote":"exact unique source text", "location":"line 2", "excerpt_anchors":["secondary unique anchor"], "derived_from_evidence_ids":["ev_parent"], "derivation_step":"Summarized raw artifact"}
```

`path` and `provenance` are required (`kind` is also required on gated v2 cases). `label`, `quote`, `location`, plus gated optional `unread_content_ack`, `excerpt_anchors` (1–8 distinct unique anchors $\ge 12$ non-whitespace units), `derived_from_evidence_ids`, and `derivation_step` (required and meaningful $\le 2000$ chars whenever `derived_from_evidence_ids` is nonempty) are supported; omitting optional fields leaves `_frozen_input` digests unchanged.
Provenance is `reported | observed | synthetic`; `observed` is the registrant's assertion, not an execution attestation.
The path must be a relative regular file within the workspace. Symlinks/reparse points, traversal,
absolute paths and the internal `.parrhesia` directory are rejected. Maximum source size is 16 MiB.
Raw bytes are copied into SQLite, hashed and retained through restarts. Optional quotes are exact UTF-8
substring anchors; location is descriptive metadata, not a parsed line/page check.
Legacy ungated registration does not reject unmatched quotes; verification reports a blocking mismatch. Current gates reject supplied short, nonunique or mismatched quotes at registration.
Returns `evidence_id`, `sha256`, `size`, `captured_at`, `provenance` and the other registered metadata.
Packets include source UTF-8 text up to 128 KiB with explicit truncation; binary sources require an
external reader and their scientific interpretation remains unknown to this engine.

### register_hypothesis

```json
{"case_id":"...", "statement":"Hypothesis", "timing_basis":"reported_prespecified", "source_evidence_id":"..."}
```

`statement` and `timing_basis` are required. Timing is `reported_prespecified | exploratory | unknown`.
`source_evidence_id` is optional except for `reported_prespecified`, which requires a registered source.
The engine records when the hypothesis entered this case; it cannot retrospectively establish when
the researcher first thought of it. Prespecification claims remain source-backed self-reports.
Returns `hypothesis_id` and engine `recorded_at` alongside the submitted metadata.

### set_ledger (legacy v1 payload only)

```json
{"case_id":"...", "claims":[{
  "id":"C1", "text":"A falsifiable claim", "level":"association",
  "evidence_ids":["..."],
  "effect":{"estimate":"r = 0.4", "uncertainty":"95% CI 0.2 to 0.6"},
  "scope":"Population, conditions and analysis unit",
  "origin":"unknown", "hypothesis_id":null,
  "best_current_explanation":"Current best explanation",
  "discriminating_test":"Observation that distinguishes competing hypotheses",
  "alternatives":[{"explanation":"Confounding", "status":"not_excluded", "reason":"No adjustment supplied"}],
  "checks":{
    "quality":{"status":"unknown", "reason":"Not supplied"},
    "batch":{"status":"unknown", "reason":"Not supplied"},
    "unit":{"status":"unknown", "reason":"Not supplied"},
    "assumptions":{"status":"unknown", "reason":"Not supplied"},
    "multiplicity":{"status":"unknown", "reason":"Not supplied"},
    "leakage":{"status":"unknown", "reason":"Not supplied"},
    "baseline":{"status":"unknown", "reason":"Not supplied"}
  },
  "contribution":"What this changes about the scientific question"
}]}
```

1–100 claims.
Legacy v1 levels by domain:
- `domain="scientific"`: `descriptive | association | predictive | mechanistic | causal`.
- `domain="general"`: `descriptive | test_passed | host_accepted | user_impact`.
Engineering levels are not an automatically inferred hierarchy.

Optional fields per claim:
- `hypothesis_id`: optional string.
- `best_current_explanation`: optional string (stake best current explanation for research advancement).
- `discriminating_test`: optional string (falsifiable test to separate competing explanations).

Alternatives and checks requirements:
- In `scientific` domain: `alternatives` (1–3, status `excluded | partially_excluded | not_excluded`, each with reason) and all 7 `checks` (status `pass | fail | unknown | not_applicable`, each with reason) are required.
- In `general` domain: `checks` is optional (omitted checks default each of the seven checks to `not_applicable` with reason "not applicable to general engineering claim"), and `alternatives` is optional (0–3 items, defaulting to `[]`).

`effect.estimate` and `.uncertainty` must be nonempty strings; explicitly write `UNKNOWN` if not established.
Origin: `prespecified | exploratory | unknown`. `prespecified` requires a registered hypothesis whose
timing is `reported_prespecified`, linked to its documentary source. Missing IDs are rejected.
Evidence IDs may be empty so explicit insufficient-evidence cases remain representable.
Returns `claim_count` and `state`.

### freeze / get_case / verify

```json
{"case_id":"..."}
```

`freeze` requires a ledger and returns `revision_id`, `input_digest`, and `packet_ids` keyed by role.
`get_case` returns the durable case document (no raw blobs) along with `event_chain` and `event_chain_status` (`verified | partial_legacy_verified | legacy_unhashed | tampered`). `verify` can run at any stage and returns
per-source `snapshot_status`, `file_status`, `anchor_status`, `lineage_status`, gated `excerpt_window_count`/`excerpt_windows`, plus top-level `evidence_chains`, `effect_checks` (computed `verify_effect_computations` summary when `effect_records` are present), `symmetry_audit` (when adjudicated, non-blocking, carrying `flags` alongside `lexical_advisories`/`lexical_advisory_count`), `event_chain` (`status`, `event_count`, `hashed_event_count`, `legacy_unhashed_count`, `broken_sequences`, `head_event_hash`), `event_chain_status`, and `status = pass | unverified | blocked` (`tampered` event chains force `status = blocked` and block `export`).
It compares retained bytes, their registered hash, current files and optional quote anchors.
`missing` and `unreadable` are unknown, distinct from `mismatch`. Any mismatch or `tampered` event chain is blocking.
The scope is content integrity/traceability only; `scientific_validity` is always `not_established_by_engine`.

### review_packet

```json
{"case_id":"...", "role":"overclaim"}
```

Role is `overclaim | underclaim`. Current cases use the frozen case-level blind setting above. Only legacy ungated cases permit an optional per-request `blind` (default false); when true, draft is null. This legacy override is not accepted for current gated cases.
Returns `packet_id`, `input_digest`, `revision_id`, `role`, `question`, `domain`, `draft`, `claims`, `evidence`, `hypotheses`, optional `blind`, and role-specific `instructions`.
Writer context, desired verdicts, full conversation and the other role's review are never included.
Both roles receive the same frozen substantive input, each in its own host context.

### submit_review (legacy payload example; current additions above)

```json
{"case_id":"...", "role":"overclaim", "packet_id":"...", "input_digest":"...",
 "reviewer":{"context_id":"fresh-overclaim", "model":"model/version"},
 "covered_claim_ids":["C1"],
 "findings":[{"id":"O1", "claim_id":"C1", "evidence_ids":["..."],
   "issue":"Concrete evidence/wording mismatch", "proposed_level":"descriptive",
   "proposed_text":"Exact replacement", "decision_impact":"How this changes the judgment"}]}
```

All shown fields required. Optional `review_status` is `complete` (default) or `needs_split`.
For v1, `proposed_level` must match the case domain. For v2, the proposed type/level/scope must satisfy the type-local contract above.
0–3 findings per role; empty findings are valid with exact claim coverage.
Each finding must reference registered evidence belonging to the claim; empty IDs allowed for a
missing-evidence criticism. Finding IDs must be unique across both reviews. Context ID must differ
from a known writer context and the other reviewer context. No model diversity is falsely required.
Returns the stored review and lifecycle state. Duplicate or stale submissions are rejected.

### adjudication_packet

```json
{"case_id":"..."}
```

Requires both reviews. Returns `adjudication_id`, `input_digest`, `revision_id`, frozen input and both
reviews. The digest binds both immutable reviews as well as the frozen input. Packet is persistent.

### submit_adjudication (legacy payload example; current additions above)

```json
{"case_id":"...", "adjudication_id":"...", "input_digest":"...",
 "adjudicator":{"context_id":"fresh-adjudicator", "model":"model/version"},
 "decisions":[{"claim_id":"C1", "verdict":"partially_supported", "level":"association",
   "revised_text":"Precise final claim", "rationale":"Specific reason",
   "evidence_ids":["..."], "confidence":"medium", "confidence_reason":"Why",
   "boundary":"Where this applies", "reversal_condition":"Evidence that would change judgment",
   "condition":"The condition under which the partially supported claim holds"}],
 "dispositions":[{"finding_id":"O1", "disposition":"accepted", "reason":"Why"}]}
```

All shown fields required except `condition`, which is required only for `partially_supported`.
Verdicts: `supported | partially_supported | unsupported | insufficient_evidence`.
For v1, `level` must match the case domain. For v2, use type/level/scope and the positive-verdict structural gates above.
Confidence: `high | medium | low`. Each claim gets exactly one decision; decisions may optionally carry numeric `forecast_probability` in `[0.0, 1.0]` for post-hoc calibration tracking and decision-level `reversal_triggers` (checked against `self_triggering_reversal_condition`, `contradictory_claim_lineage_transition`, and `untriggered_reversal_link`); each finding gets exactly
one disposition (`accepted | partial | rejected`) with a reason. `partial` dispositions additionally
require `condition`. Positive verdicts must cite at least one claim evidence ID; the adjudicator can
remove evidence but cannot silently add evidence outside the frozen claim. Adjudicator context must
differ from both reviewers; it may equal the writer, because writing and adjudication can share a host.
Confidence is a reasoned assessment, unless explicit `forecast_probability` is supplied. Final text is bounded to decisions;
the engine does not accept an untracked final essay.
The verdict evaluates `revised_text`, not the original draft claim. Reports show the original and
revised wording separately, so narrowing an overclaim is never presented as endorsing that overclaim.

### export

```json
{"case_id":"...", "path":"exports/case-report.md"}
```

Requires adjudication. Optional `path` defaults to `exports/<case_id>.md`. Must be a new relative path
within the workspace, outside `.parrhesia`; no overwrite. Runs verification immediately before export.
Any mismatch blocks export. Missing/unreadable source bytes are explicitly unverified; a positive
verdict citing any such source is blocked. Unsupported and insufficient-evidence judgments may
export with that uncertainty displayed. Empty evidence is permitted only for non-positive verdicts.
Successful export writes Markdown, returns its absolute `path`, `sha256`, `verification`, and `state`.
The immutable report bytes and intended path are first committed to SQLite (`export_pending`),
then materialized through exclusive atomic hard-link creation. Filesystems must support hard links
(the standard Windows NTFS workspace does). A failed write can be retried with the same case/path;
the exact prepared artifact is recovered, including after a restart. A matching file left by a crash
is accepted without overwriting it; a different file is rejected. Sources are rechecked before
materialization; changed statuses block retry until the recorded source state is restored.
The case retains the export path/digest; after completion a second export is rejected.
Reports contain all final decisions, original claim IDs, exact revised text, dispositions, source
hashes/statuses, effect uncertainty, scientific checks and evidence boundary; they never label a
scientific conclusion “verified.” A content-integrity pass is not proof of a code execution, a valid
inference, actual preregistration, independent review, human acceptance, or benefit versus Grok.

### record_human_decision

```json
{"case_id":"...", "decision":"challenge", "responsible_human":"Researcher name", "reason":"Specific disagreement"}
```

All fields required. `decision` is `accept | challenge | defer | pause`. Append-only at every stage;
does not edit any frozen claim, review, adjudication or exported file. The human name is caller-reported,
not authenticated. Holds accumulate after the most recent `accept`: `pause` blocks workflow mutations
until a subsequent explicit `accept`; recording `challenge` or `defer` does not resume paused work.
Reads, verification and further human events remain available. An existing adjudication packet can be
read during a pause, but creating its first packet is a blocked workflow mutation. `challenge` and
`defer` block final export until `accept` is recorded. Acceptance clears the preceding holds and resumes
workflow but does not assert scientific validity. Later holds remain effective until another `accept`.
No human acceptance is fabricated or required implicitly. Post-export events are available in
`get_case`; the immutable already-exported report is not retrospectively rewritten.

### claim_graph

```json
{"case_id":"optional-filter", "claim_id":"optional-filter"}
```

Read-only longitudinal DAG query across workspace cases. Returns `filter`, `case_nodes`, `case_edges`, `claim_nodes` (including chronological verdict/level `trajectory` and `active_standing`), `claim_edges`, `chains`, and `cycle_detected`.

### evaluate_triggers

```json
{"case_id":"...", "against_case_id":"optional-follow-up-case", "observations":{"effect_records":[], "checks":{}, "evidence_status":{}, "execution_runs":[], "replication_verdicts":[]}}
```

Read-only deterministic evaluation of a case's `reversal_triggers` (on both claims and decisions). When neither `against_case_id` nor `observations` is given, evaluates against live workspace state (`verify`, SQLite `record_exec` events, and graph descendants). Returns `evaluation_mode`, `total_triggers`, `fired_count`, `unfired_count`, `pending_data_count`, `fired_trigger_ids`, and `claim_evaluations`.

### record_calibration_outcome

```json
{"case_id":"...", "claim_id":"C1", "outcome":"replicated", "outcome_score":1.0, "resolution_source":"follow_up_case", "follow_up_case_id":"...", "follow_up_claim_id":"C1_rep", "reason":"Independent replication matched primary effect"}
```

Append-only outcome records are allowed after adjudication and never rewrite frozen digests or exports. Outcomes and resolution_source enums are unchanged. Explicit nonexistent evidence IDs are rejected. Missing, unread, changed or unbound sources remain `source_binding.status="pending"`; their reported outcome is retained but excluded from resolved scoring. External references must be registered in a workspace case (new evidence can be registered in a separate draft source case). Follow-up resolutions require a specific linked claim, effective adjudication and verified cited sources; trigger firing alone does not establish an outcome. Existing legacy records are reassessed read-only and remain unmodified.

Numeric observations require `metric` and `effect_record_id` binding to the original endpoint, with values anchored in the source. Optional fields: `comparison_kind` (`replication_estimate`, default; or `known_truth` for an explicitly declared external reference value), `observed_ci_low/high`, `observed_ci_level`, `observed_ci_method`, `comparison_assumption` (`independent | covariance_supplied | unknown`) and `estimate_covariance` (on the same, possibly log, analysis scale). Known truth must not be another estimated interval. Source truth and independence remain caller assertions subject to review.

### calibration_report

```json
{"case_id":"optional-filter", "domain":"scientific", "claim_type":"causal_effect"}
```

Read-only calibration analytics across effective adjudicated cases. `proper_scores` and `reliability_bins` use only explicit forecast probabilities and source-verified binary outcomes; `heuristic_scores` and labeled `confidence_strata` report descriptive mappings separately. `interval_calibration.evaluated_count/covered_count/empirical_coverage_rate/nominal_coverage_rate/coverage_error` apply only to declared known-truth references. Replication points have separate `replication_count` and `replication_point_containment_rate`, with no nominal CI coverage claim. `z_difference` and `mean_absolute_z_difference` use both studies' variances only when matching Wald methods and an explicit independence/covariance assumption are supplied; otherwise they are null/unassessed. `z_drift` and `mean_absolute_z_drift` are deprecated null fields. Follow-up graph labels remain graph-inferred, and a failed replication or a refinement/extension alone is not scored as refutation or confirmation.

Compatibility: `proper_scores.combined_brier_score` and `proper_scores.combined_log_score` remain present as deprecated null fields; their mixed descriptive counterparts are under `heuristic_scores`. Clients must use `proper_scores.explicit_brier_score` / `explicit_log_score` for eligible explicit-probability scoring. This eligibility checks traceability and binary labels, not whether the forecast was genuinely prospective or the outcome was independently established.

## MCP server interface (22 tools, resources, prompts, and dry-run validation)

`python -m parrhesia serve --workspace <dir>` (`parrhesia/server.py`, `parrhesia/mcp_schemas.py`) advertises MCP `capabilities: {"tools": {}, "resources": {}, "prompts": {}}`:

- **22 MCP tools** (each with `inputSchema`, `outputSchema`, and read-only/idempotency annotations):
  - **18 typed per-action tools**: `parrhesia_<action>` for every action in `ACTIONS` (`parrhesia_create_case`, `parrhesia_register_evidence`, `parrhesia_register_hypothesis`, `parrhesia_scaffold_claim`, `parrhesia_set_ledger`, `parrhesia_freeze`, `parrhesia_review_packet`, `parrhesia_submit_review`, `parrhesia_adjudication_packet`, `parrhesia_submit_adjudication`, `parrhesia_verify`, `parrhesia_get_case`, `parrhesia_export`, `parrhesia_record_human_decision`, `parrhesia_claim_graph`, `parrhesia_evaluate_triggers`, `parrhesia_record_calibration_outcome`, `parrhesia_calibration_report`).
  - **1 read-only preflight dry-run validator**: `parrhesia_validate` (`action`, `payload`) runs `Engine.validate_action` inside a rolled-back SQLite savepoint/connection without mutating state or disk, returning `{valid, action, dry_run: true, preview}` on valid payloads or `{valid: false, action, dry_run: true, error, message, repair_hint}` on contract failures.
  - **3 backward-compatible legacy tools**: `parrhesia_contract`, `parrhesia_select_workspace`, and `parrhesia_workflow(action, payload)`.
  - **Actionable error payloads**: tool failures return `isError: true` with JSON `{error, message, repair_hint}` mapped via `repair_hint_for`.
- **Read-only MCP resources (`resources/list`, `resources/templates/list`, `resources/read`)**:
  - Concrete resources (4): `parrhesia://contract` (markdown workflow contract), `parrhesia://cases` (JSON case list), `parrhesia://claim-graph` (longitudinal DAG), and `parrhesia://calibration` (calibration report).
  - Resource templates (7): `parrhesia://cases`, `parrhesia://claim-graph`, `parrhesia://calibration`, `parrhesia://cases/{case_id}` (durable case document + `event_chain`), `parrhesia://cases/{case_id}/ceilings` (type-local `check_ceilings` and `effect_record_counts` per claim), `parrhesia://cases/{case_id}/triggers` (read-only trigger evaluation against workspace state), and `parrhesia://cases/{case_id}/packet/{role}` (read-only isolated packet for `overclaim`, `underclaim`, or already-built `adjudication`).
- **Role prompts (`prompts/list`, `prompts/get`)**:
  - `parrhesia_review_overclaim`, `parrhesia_review_underclaim`, and `parrhesia_adjudicate` (accepting optional `case_id` to inject the live isolated packet alongside role instructions).

### Execution failure receipts (2026-11-14 repair)

`record-exec` reserves a new log before launching and rejects an existing explicit log path without executing the command. Timeout and process-start failure preserve timestamps, captured partial bytes, a failed execution card, registered evidence (when case-id is supplied), and a `record_exec` event. `termination_status` is `completed | timed_out | start_failed`; the child `exit_status` is null when unavailable, never an invented exit code. CLI wrapper exits 124 for timeout and 127 for start failure after printing the receipt; a normally completed nonzero child retains its actual exit_status and failed card (wrapper 0 denotes receipt creation). Input/argument validation failures before launch are not execution attempts.
