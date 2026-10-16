# Parrhesia core contract (v0.1.0 pilot)

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

## Payloads

Every action except `create_case` requires `case_id`. Generated IDs must be used exactly.

### create_case

```json
{"question":"The concrete question", "draft":"Full initial draft", "domain":"scientific", "writer_context_id":"writer-1"}
```

`domain` is optional (`scientific` default; `general` also supported). `writer_context_id` is optional;
when absent, separation from the writer remains explicitly unknown. Returns `case_id`, `state`, `created_at`.

### register_evidence

```json
{"case_id":"...", "path":"evidence/results.txt", "label":"Observed output", "provenance":"reported", "quote":"exact text", "location":"line 2"}
```

`path` and `provenance` are required. `label`, `quote`, `location` are optional.
Provenance is `reported | observed | synthetic`; `observed` is the registrant's assertion, not an execution attestation.
The path must be a relative regular file within the workspace. Symlinks/reparse points, traversal,
absolute paths and the internal `.parrhesia` directory are rejected. Maximum source size is 16 MiB.
Raw bytes are copied into SQLite, hashed and retained through restarts. Optional quotes are exact UTF-8
substring anchors; location is descriptive metadata, not a parsed line/page check.
Registration does not reject an unmatched quote: verification reports it as a blocking mismatch.
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

### set_ledger

```json
{"case_id":"...", "claims":[{
  "id":"C1", "text":"A falsifiable claim", "level":"association",
  "evidence_ids":["..."],
  "effect":{"estimate":"r = 0.4", "uncertainty":"95% CI 0.2 to 0.6"},
  "scope":"Population, conditions and analysis unit",
  "origin":"unknown", "hypothesis_id":null,
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

1–100 claims. Every shown claim field is required except `hypothesis_id`.
Levels: `descriptive | association | predictive | mechanistic | causal` (not an automatically inferred hierarchy).
`effect.estimate` and `.uncertainty` must be nonempty strings; explicitly write `UNKNOWN` if not established.
Alternatives: 1–3, status `excluded | partially_excluded | not_excluded`, each with a reason.
All seven checks are required, status `pass | fail | unknown | not_applicable`, each with a reason.
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

Role is `overclaim | underclaim`. Returns `packet_id`, `input_digest`, `revision_id`, `role`,
`question`, `domain`, `draft`, `claims`, `evidence`, `hypotheses`, and role-specific `instructions`.
Writer context, desired verdicts, full conversation and the other role's review are never included.
Both roles receive the same frozen substantive input, each in its own host context.

### submit_review

```json
{"case_id":"...", "role":"overclaim", "packet_id":"...", "input_digest":"...",
 "reviewer":{"context_id":"fresh-overclaim", "model":"model/version"},
 "covered_claim_ids":["C1"],
 "findings":[{"id":"O1", "claim_id":"C1", "evidence_ids":["..."],
   "issue":"Concrete evidence/wording mismatch", "proposed_level":"descriptive",
   "proposed_text":"Exact replacement", "decision_impact":"How this changes the judgment"}]}
```

All shown fields required. Optional `review_status` is `complete` (default) or `needs_split`.
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

### submit_adjudication

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
