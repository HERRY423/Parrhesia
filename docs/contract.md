# Parrhesia 0.2.0 core contract (pilot; new cases v2, stored v1 compatibility)

`Engine(workspace).dispatch(action, payload) -> dict`. Only Python's standard library is required.
Expected errors raise `ContractError` with `.code`, `.message`, and `.as_dict()`; errors never advance the case.
The workspace must already be a directory. State is local in `.parrhesia/state.sqlite3`.
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
| `execution` | `command`, `code_version`, `inputs`, `environment`, `started_at`, `ended_at`, `exit_status`, `outputs`, `log_locator` |
| `search` | `database`, `query`, `searched_at`, `filters`, `coverage`, `results`, `selection`, `limitations` |

`citation` records the exact source-to-claim relationship and read extent. `number` records value, units/denominator, extraction/calculation basis and location. `execution` distinguishes actual invocation, completion, logs and outputs. `search` retains reproducible query, coverage, selection and limits; unknown result counts stay UNKNOWN. Cards cannot execute code, contact services or establish that a search/run happened. No passwords, tokens or unapproved patient identifiers belong in them.

All new fields are frozen, survive restart, are included in both review packets, and are displayed in Markdown and HTML reports. Reports label these as registrant records and preserve the original classification alongside the revised one.

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
| theory / proved or independently checked | assumptions |
| qualitative / all positive levels | quality, unit |
| engineering / all positive levels | quality, baseline |
| prediction or computational / all positive levels | quality, unit, assumptions, leakage, baseline, multiplicity |
| Remaining positive types/levels | quality, unit, assumptions, batch, multiplicity, baseline |

Fixed essential keys must be `pass`; fail/unknown/not_applicable block. Whenever fixed checks apply, all selected design-package checks also apply: unknown/fail block, and a selected design package cannot mark all of its checks `not_applicable` (`all_not_applicable`). Essential design-specific checks (`observational`: `sampling_temporality`, `confounding_selection`, `robustness`; `quasi_experimental`: `assignment_rule`, `identification`, `diagnostics_placebos`, `sensitivity`; `randomized`: `randomization_concealment`, `analysis_population`, `adherence_attrition`; `mechanism`: `causal_model`, `specificity_controls`, `temporal_chain`; `prediction`: `target_horizon`, `splits_leakage`, `calibration_discrimination`; `ml`: `data_contamination`, `splits_tuning`, `baselines_budget`) must be `pass` and cannot be bypassed via `not_applicable`. All eight statistical records also apply except to description/theory/qualitative/engineering; for those quantitative types, `units_sample_size` and `estimate_uncertainty` must be `pass` (`not_applicable` is rejected), while genuinely inapplicable remaining statistical items may use justified `not_applicable`. Provenance cards with `status` in `failed | missing`, or `citation` cards whose `support_relation` is contradicting (`unsupported`, `contradicts`, `refutes`, `不支持`, `反对`), block positive verdicts and ceilings; any `checked` `number`, `execution` or `citation` card must have its `evidence_ids` cited in a positive decision. Nonessential seven-check items remain visible in the report. A literal record can be supported despite unverified measurement quality; that does not support the measurement's truth. Runtime reasons/statuses are reported assessments, not independently verified facts.

Causal type/level ceilings additionally include causal_basis assessment, assumptions, falsification/sensitivity, the corresponding necessity/sufficiency test, and core estimand completeness. Missing basis, unknown/failing assessments or pass labels without evidence references cannot retain an identified causal evidence grade even in a negative verdict; use unassessed/unidentified as appropriate. Negative reviewer stances may still reject the overgraded original wording without modifying the ledger.

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

`kind` accepts exactly the distinct values above plus `unknown`. `kind=synthetic` requires `provenance=synthetic`; synthetic provenance is also detected when kind is another category. Compatibility is necessary, not sufficient: actual replication, source relevance, design adequacy and semantic support still require review. Intervention labels alone never authorize causal wording.

#### Anchors, unread sources, stances and findings

- Registration: required `kind`, optional boolean `unread_content_ack`. Unread binary sources require this flag to be true. UTF-8 text excludes PDF/archive/image signatures and control-bearing buffers; the engine does not extract binary content. Register a separate readable extract with its provenance and scope if needed.
- Any supplied `quote` must have at least **12 visible non-whitespace Unicode characters (control/format, combining-mark and private-use codepoints do not count toward the minimum)**, occur exactly once in the complete saved text (overlapping matches count), and match literally. Bad supplied quotes fail registration. A source may be registered without quote/location, but **every positive reference** must have both a valid quote and a concrete non-placeholder `location`. Location is a caller locator, not a parser-verified line/page. A unique quote proves anchoring, not semantic entailment.
- Packets retain the 128 KiB text cap. Binary, truncated or missing source text cannot support a positive verdict, even with acknowledgment. Every review and adjudication requires `unread_evidence_ids` listing exactly all such case sources (including uncited ones); submit `[]` when none. `verify` marks these sources unverified with explicit read status; hash equality is not reading.
- `submit_review.claim_stances`: exactly one `{claim_id, stance, rationale, evidence_ids}` per frozen claim, even with zero findings. `stance` uses the four verdict enums. A `partially_supported` stance additionally requires a substantive `condition`; empty, invisible-only or UNKNOWN/NA conditions are rejected. The same placeholder checks apply to final decision and partial adoption conditions. It evaluates the **original** claim. Positive stances require nonempty anchored compatible references and all applicable checks; negative stances can reject an overgraded original claim. No implied approval from empty findings.
- Each disposition adds `claim_id` and `resolution` (`incorporated | disagreement`). `incorporated` requires `revised_text_quote` (at least 12 visible non-whitespace characters), unique in both finding.proposed_text and final revised_text, and absent from the original text so it identifies an actual changed passage. Reusing an unchanged fragment plus an unrelated addition is rejected. `accepted` incorporation additionally requires the whole proposed_text and exact proposed type/level/scope/basis in the decision. Partial incorporation requires `condition`. A rejected disposition cannot be incorporated.
- An unincorporated or divergent recommendation must use `resolution=disagreement` plus substantive `disagreement`, with no `revised_text_quote`. This is allowed even when the adjudicator accepts the underlying criticism; the report exposes the retained wording and disagreement instead of treating an accepted label as implementation. All dispositions bind the finding to the decision for the same claim.
- `create_case.blind` is boolean, defaults true, and is frozen case-wide. Both review packets omit draft and the author research-framing fields best_current_explanation/discriminating_test when true. Per-request blind overrides are rejected, even if equal to the case value. Set false explicitly at creation for a nonblind case. It is packet filtering, not a security sandbox; question/source/claim text can contain framing and must be curated by the operator.

Rejection codes include `critical_check_ceiling`, `synthetic_empirical_support`, `incompatible_evidence_kind`, `unanchored_positive_evidence`, `invalid_quote`, `unread_ack_required`, `unread_positive_evidence`, `incomplete_stances`, `finding_decision_mismatch`, `finding_not_incorporated`, `missing_disagreement`, `contradictory_resolution`, `case_level_blind`, `legacy_creation_disabled`, `unsupported_contract_version`, `missing_stance_condition`, `invalid_condition`. Unknown stored schema/gate versions are rejected rather than interpreted as legacy. Rejected submissions do not advance or mutate stored workflow state.

Minimal current review extension (merge into the common payload below):

```json
{"claim_stances":[{"claim_id":"C1","stance":"insufficient_evidence","rationale":"Measurement checks remain unknown","evidence_ids":[]}],"unread_evidence_ids":[]}
```

Current incorporated disposition example:

```json
{"finding_id":"O1","claim_id":"C1","disposition":"accepted","reason":"The original scope exceeded the supplied record","resolution":"incorporated","revised_text_quote":"Exact proposed replacement wording"}
```

Add `unread_evidence_ids` at adjudication top level and `claim_basis` to every decision. Findings add `proposed_claim_basis`. The action examples explicitly labeled legacy below retain their legacy shapes for compatibility, not current acceptance.

Every action except `create_case` and `scaffold_claim` requires `case_id`. Generated IDs must be used exactly.

### scaffold_claim

```json
{"case_id":"optional-case-id", "claim_id":"C1", "claim_type":"causal_effect", "evidence_level":"unassessed", "design_families":["observational"], "include_causal_basis":true}
```

Read-only helper that generates a complete, schema-valid v2 claim skeleton with explicit `unknown` assessments and `not_run` execution/search cards (never pre-filled with fake `pass` values), plus a `check_ceilings` preview showing exactly which checks are currently blocking each `evidence_level`. Does not mutate case state. In addition, the CLI provides `python -m parrhesia record-exec --workspace <dir> [--case-id <id>] -- <command...>` to execute a local command, capture stdout/stderr and timestamps into a workspace log file, optionally register the log as `observed` evidence, and emit a schema-valid `execution` provenance card JSON.

### create_case

```json
{"question":"The concrete question", "draft":"Full initial draft", "domain":"scientific", "schema_version":2, "blind":true, "writer_context_id":"writer-1"}
```

`domain` is optional (`scientific` default; `general` also supported). `writer_context_id` is optional;
when absent, separation from the writer remains explicitly unknown. `schema_version` defaults to integer `2`; explicit integer `1` is rejected for creation; v1 applies only to recovery of already stored cases. Other values (including booleans) are rejected. Returns `case_id`, `state`, `created_at`, `schema_version`.

### register_evidence

```json
{"case_id":"...", "path":"evidence/results.txt", "label":"Observed output", "kind":"observation", "provenance":"reported", "quote":"exact unique source text", "location":"line 2"}
```

`path` and `provenance` are required. `label`, `quote`, `location` are optional.
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
`get_case` returns the durable case document (no raw blobs). `verify` can run at any stage and returns
per-source `snapshot_status`, `file_status`, `anchor_status` plus `status = pass | unverified | blocked`.
It compares retained bytes, their registered hash, current files and optional quote anchors.
`missing` and `unreadable` are unknown, distinct from `mismatch`. Any mismatch is blocking.
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
Confidence: `high | medium | low`. Each claim gets exactly one decision; each finding gets exactly
one disposition (`accepted | partial | rejected`) with a reason. `partial` dispositions additionally
require `condition`. Positive verdicts must cite at least one claim evidence ID; the adjudicator can
remove evidence but cannot silently add evidence outside the frozen claim. Adjudicator context must
differ from both reviewers; it may equal the writer, because writing and adjudication can share a host.
Confidence is a reasoned assessment, not a calibrated probability. Final text is bounded to decisions;
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
