# Parrhesia

**Let evidence determine claim strength, and adjudication end hollow neutrality.**

**Language / 语言**: **[简体中文](README.md)** · English

**Parrhesia** is a local evidence-calibration and dual-review adjudication plugin conforming to the [Agent Plugins 1.0.0](https://agent-plugins.org/) specification, with a single-source cross-platform `AGENTS.md` policy system. Its design separates cognitive roles for independent review and uses a **deterministic local state machine with zero third-party dependencies (Python 3.11+ standard library only)** to address overclaiming, excessive disclaimers, and hollow neutrality in scientific analysis, engineering evaluation, and technical decisions. The measured scope and limits of this design are stated in the evidence-boundary section below.

---

## Why Parrhesia?

When one model drafts, criticizes, identifies contributions, and decides within a single conversation, three forms of distortion can arise. Parrhesia separates these conflicting responsibilities:

| Distortion | Observable symptoms in everyday AI collaboration | Role separation | Invalid proxy metric |
| :--- | :--- | :--- | :--- |
| **1. Idealization and overclaiming**<br>*(Overclaim)* | Turning association into “drives/regulates/causes”; presenting synthetic tests or one successful run as clinical or production benefit; generalizing beyond tested conditions | **Overclaim reviewer (`overclaim`)** checks overstated language, unresolved confounding, and inference gaps: *What is the strongest claim the evidence permits?* | “Does the tone sound humble?” |
| **2. Excessive defensiveness and disclaimer inflation**<br>*(Underclaim)* | Erasing robust external validation or measured improvements with boilerplate about limited samples, missing multicenter trials, or “for reference only”; repeatedly weakening every paragraph | **Underclaim reviewer (`underclaim`)** identifies unjustifiably weakened contributions and uninformative disclaimers: *What does the evidence already establish?* | “How many disclaimers were removed?” |
| **3. Hollow neutrality** | Listing both sides and calling for more research without substantive comparison, returning responsibility for the decision to the user | **Single adjudicator (`adjudicator`)** does not vote or average positions; accepts, partially accepts, or rejects each finding and gives a verdict with **observable reversal conditions** | “Is the conclusion decisive or pleasing to the user?” |

### Calibration at a glance

The numbers below illustrate wording; they are not clinical results from this project.

- ❌ **Overclaim**: “Single-cell co-expression and significant regression (p=0.002) prove that transcription factor X activates pathway Y and causes resistance.”
- ❌ **Excessive disclaimer**: “Although the model achieved AUROC 0.84 (95% CI 0.77–0.90) in an independent external cohort (N=120), the limited sample, possible unknown biases, and absence of multicenter phase III randomized trials prevent any firm conclusion; for reference only.”
- ✅ **Calibrated wording**:
  > “In an independent external validation cohort (N=120), the model showed robust external discrimination for one-year recurrence (`prediction × externally_validated`, **supported**; AUROC 0.84, 95% CI 0.77–0.90), supporting its candidacy for risk stratification in populations from the same distribution. Net clinical decision benefit (`utility`) remains to be evaluated prospectively. If subsequent cross-center calibration slopes fall outside [0.8, 1.2], applicability will be narrowed to populations matching the original center.”

**Three non-negotiable boundaries** (see the [single policy source](policy/parrhesia-policy.md#唯一优先级)):

1. **Instruction priority and tradeoffs**: platform system instructions > platform developer instructions > user messages. Within that boundary: **data confidentiality and spending limits > evidence truthfulness > calibrated strength > full expression of supported contributions > efficiency**.
2. **Never fabricate certainty or treat missing evidence as counterevidence**: do not invent data, numbers, citations, execution, or searches. `insufficient_evidence` is a legitimate conclusion, distinct from both support and `unsupported`.
3. **User expectations are not evidence**: users choose scope, format, language, and workflow simplicity, but cannot dictate evidence grades or verdicts.

---

## Four progressive workflows with minimal overhead (`L0` / `L1` / `L1-Explore` / `L2`)

Parrhesia keeps routine tasks lightweight while applying checks to consequential conclusions. Agents select a tier by task and identify it on the first line; users need not memorize tool payloads.

| Tier | Typical tasks | Interaction and output | Database and dual review? |
| :--- | :--- | :--- | :--- |
| **`[L0]`** | Translation, formatting, a single verifiable fact, local code edits, pure numerical calculations | **Give the result directly**, with `[L0]` on the first line and no extra structure | No |
| **`[L1]`**<br>*(default)* | Explanations, comparisons, evidence judgments, interim conclusions | Natural prose covering **① verdict and `claim_type × evidence_level + scope` · ② traceable evidence and strongest rival explanation · ③ observable reversal conditions · ④ next action · ⑤ relevant failed/unknown checks** | No; lightweight internal checks |
| **`[L1-Explore]`** | Brainstorming, hypotheses, mechanism reasoning, experimental/statistical design | **2–3 exploratory hypothesis cards**, each containing **① strongest rival · ② discriminating experiment · ③ cost · ④ stopping rule · ⑤ falsification condition** | No; supports exploration |
| **`[L2]`** | Figure captions, abstracts, manuscripts, formal reports, submission materials, core-claim reviews, responses to challenges | Review **3–5 core claims at a time**, not the whole document: register → freeze packets → overclaim/underclaim reviews in two clean contexts → adjudicate → verify provenance and export atomically | **Yes**; SQLite persistence and mechanical gates |

> 💡 **Recommended daily workflow**: Use `L1-Explore` throughout exploration to narrow hypotheses and discriminating experiments; send only 3–5 core claims to `L2` during confirmation; use full dual review for captions, abstracts, manuscripts, or formal reports.

---

## Installation and host integration

The local MCP server and CLI require only **Python 3.11+**, with **zero third-party dependencies** and no external packages to install with `pip`.

### Option 1: Codex plugin marketplace (GUI / CLI)

#### 1. “Add plugin marketplace” in the GUI (recommended)

In the Codex desktop plugin management page, choose **Add plugin marketplace** (from a GitHub repository, Git URL, or local folder):

| Field | Value | Notes |
| :--- | :--- | :--- |
| **Source** | `HERRY423/Parrhesia`<br>*(or `https://github.com/HERRY423/Parrhesia.git`)* | For an offline package or local clone, select the repository root containing `.agents/plugins/marketplace.json`, such as `C:\Parrhesia` |
| **Git ref** | `main` | Gets the latest `0.3.0` updates; use a commit or tag to pin a version |
| **Sparse path** | **Leave blank** | The plugin manifest is at the root; do **not** copy the placeholder `plugins/codex` |

Click **Add marketplace**, then select **Parrhesia Marketplace** and install **Parrhesia**.

#### 2. Codex CLI installation

```powershell
# Add the GitHub marketplace and install the plugin
codex plugin marketplace add HERRY423/Parrhesia --ref main
codex plugin add parrhesia@parrhesia-marketplace

# Optional: add a local clone
codex plugin marketplace add C:\Parrhesia
```

#### 3. Sync Codex global compact rules and the L2 scientific reference skill

Codex uses a **resident compact policy block (`< 10 KiB`) + on-demand `parrhesia-l2-reference` skill + separate role packets**, avoiding a roughly `48 KiB` full policy in routine context:

```powershell
# Sync compact rules to ~/.codex/AGENTS.md and the L2 reference skill to ~/.codex/skills/parrhesia-l2-reference/SKILL.md
python scripts/install-codex.py

# Read-only consistency check against the repository policy source
python scripts/install-codex.py --check
```

---

### Option 2: Claude Code marketplace and Agent Plugins 1.0.0 clients

#### 1. Claude Code CLI installation

```bash
claude plugin marketplace add HERRY423/Parrhesia
claude plugin install parrhesia@parrhesia-marketplace
```

The Claude-specific `.claude-plugin/plugin.json` now declares the MCP server inline, using `${CLAUDE_PLUGIN_ROOT}` for the launcher and `${CLAUDE_PLUGIN_DATA}/workspace` for the default persistent ledger, independently of the generic `mcp.json` variables. Use a recent Claude Code version supporting `userConfig` and these variables. Set the plugin's `python` option in `/config` to a working Python **3.11+** interpreter (default: `python`; use `python3` on Linux/macOS when needed, or an absolute executable path). If set, `PARRHESIA_WORKSPACE` must be an existing absolute directory and overrides the default. Back up ledgers before uninstalling: Claude may delete plugin data on uninstall.

Users with the old manifest must update the plugin and restart the session, verify that the cached manifest contains `mcpServers`, and confirm Parrhesia is connected in `/mcp`; installation alone does not establish server availability. This repair passed Claude Code 2.1.325 strict manifest validation and independent MCP subprocess checks; **real Claude Code session workflow acceptance is still pending**, and the `host_accepted` scope below is unchanged. [Official Claude manifest and variable reference](https://code.claude.com/docs/en/plugins-reference)

#### 2. Standard Agent Plugins 1.0.0 clients

Compatible hosts can load `plugin.json`, `mcp.json`, and `skills/` at the repository root, discovering **22 local tools**, read-only resources, and role prompts through stdio MCP:

- **18 typed action tools (`parrhesia_<action>`)**: `create_case`, `register_evidence`, `register_hypothesis`, `scaffold_claim`, `set_ledger`, `freeze`, `review_packet`, `submit_review`, `adjudication_packet`, `submit_adjudication`, `verify`, `get_case`, `export`, `record_human_decision`, `claim_graph`, `evaluate_triggers`, `record_calibration_outcome`, and `calibration_report`, each with JSON Schema and permission annotations.
- **`parrhesia_validate`**: read-only preflight in a SQLite transaction with automatic `ROLLBACK`; failures return structured `repair_hint` guidance.
- **3 backward-compatible general tools**: `parrhesia_contract`, `parrhesia_select_workspace`, and `parrhesia_workflow`.
- **Read-only MCP resources and role prompts**: `parrhesia://contract`, `parrhesia://cases`, `parrhesia://claim-graph`, `parrhesia://calibration`; templates `parrhesia://cases/{case_id}`, `/ceilings`, `/triggers`, `/packet/{role}`; prompts `parrhesia_review_overclaim`, `parrhesia_review_underclaim`, and `parrhesia_adjudicate`.

---

### Option 3: Grok Build CLI project adapter

The idempotent installer syncs both `parrhesia-review` and `parrhesia-l2-reference`, backs up existing files, safely merges project `.mcp.json`, and maintains a compact `AGENTS.md` policy block by default (`--policy full` selects the full policy):

```powershell
# Install into a project (or run & .\scripts\install-grok.ps1 -Project C:\YourProject)
python scripts/install-grok.py --project C:\YourProject

# Read-only hash/configuration/skill/source checks, or safe uninstall
python scripts/install-grok.py --project C:\YourProject --check
python scripts/install-grok.py --project C:\YourProject --uninstall

# Inspect Grok configuration discovery in the project
grok --cwd C:\YourProject inspect
```

See the [Grok integration guide](docs/grok-integration.md).

---

### Option 4: Antigravity host adapter

For Google Antigravity (Antigravity IDE / Antigravity 2.0 / `agy` CLI), the self-contained adapter generates `.agents/plugins/parrhesia/` with an explicit allowlist: `plugin.json`, `mcp_config.json`, frontmatter-free compact `rules/parrhesia.md` (`< 24,000 B`), two skills, and a silent read-only `SessionStart` SQLite status hook. It does not modify `~/.gemini/config/config.json`.

```powershell
# Install into a project (or run & .\scripts\install-antigravity.ps1 -Project C:\YourProject)
python scripts/install-antigravity.py --project C:\YourProject

# Read-only limits/integrity check, safe uninstall, or installation into an explicitly isolated directory
python scripts/install-antigravity.py --project C:\YourProject --check
python scripts/install-antigravity.py --project C:\YourProject --uninstall
python scripts/install-antigravity.py --scope user --target C:\CustomAntigravityHome
```

See the [Antigravity integration guide](docs/antigravity-integration.md).

---

### Option 5: ChatGPT web / Custom GPT text-only protocol (no local dependencies)

Run the L2 dual-review protocol across separate web conversations without a local Python or MCP process:

1. Paste the [ChatGPT policy template](templates/AGENTS.parrhesia.chatgpt.md) into ChatGPT Project Instructions or Custom GPT Instructions.
2. Generate the standard handoff kit (output directory must not exist):
   ```powershell
   python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
   ```
3. Follow the [ChatGPT integration guide](docs/chatgpt-integration.md): freeze the ledger with `01-frozen-input.md` (or `01-frozen-input-blind.md`), paste `02-overclaim.md` and `03-underclaim.md` into two new separate conversations, adjudicate in the main conversation using `04-adjudication.md`, and archive with `05-handoff-record.md`.

---

## Core features and architecture: four pillars in `0.3.0`

### Pillar 1: Two-dimensional evidence coordinates — `claim_type × evidence_level + scope`

A single ladder from description to association, prediction, mechanism, and causation wrongly suggests that prediction is inferior or repeated associations become causal. Parrhesia uses **12 claim types, evidence levels within each type, and explicit scope**, with `claim_basis` distinguishing `empirical` observations, `synthetic` examples, and `formal` proofs.

| Claim type (`claim_type`) | Within-type levels (all include `unassessed`) | Wording and scope boundary |
| :--- | :--- | :--- |
| **Description** `description` | `recorded` · `measurement_checked` · `replicated` | Describe observed objects only; do not infer populations or mechanisms |
| **Association** `association` | `unadjusted` · `adjusted` · `robust_association` | Say “associated with”; adjustment or robustness does not eliminate unmeasured confounding |
| **Prediction** `prediction` | `apparent` · `internally_validated` · `externally_validated` · `prospectively_evaluated` | State target, time, and population; external discrimination is not clinical utility or causal mechanism |
| **Causal effect** `causal_effect` | `unidentified` · `identified_under_assumptions` · `sensitivity_supported` | Causal language applies only to the specified `estimand`, design, and identification assumptions |
| **Mechanism** `mechanism` | `compatible` · `component_tested` · `causal_chain_tested` | Co-expression/enrichment provides compatible clues; a full chain requires examining alternative pathways |
| **Necessity** `necessity` | `bounded_test` · `counterfactual_supported` | Whether Y can still occur after removing X in the specified context; **not sufficiency** |
| **Sufficiency** `sufficiency` | `bounded_test` · `counterfactual_supported` | Whether introducing X produces Y in the specified context; **not necessity** |
| **Synthesis** `synthesis` | `mapped` · `critically_appraised` · `synthesized_with_uncertainty` | Inherits study bias and dependence; pooling does not create causal identification |
| **Theory** `theory` | `conjectured` · `proved_under_assumptions` · `independently_checked` | Requires `claim_basis="formal"`; numerical examples do not replace proofs |
| **Qualitative** `qualitative` | `situated_description` · `interpretation_audited` · `triangulated` | Preserve context and negative cases; do not impose population frequencies or p-values |
| **Computational performance** `computational` | `benchmark_measured` · `reproduced` · `externally_evaluated` | Report datasets, budget-matched baselines, and seeds; leaderboard results are not deployment benefit |
| **Engineering** `engineering` | `test_passed` · `host_accepted` · `user_impact` | Unit tests do not replace real host acceptance; handshakes do not establish user benefit |

- **Proposition support is separate from effect direction**: `supported` means the stated proposition has evidence, not necessarily `benefit`. Harm or null-effect propositions may also be supported when evidence and `claim_direction` match; opposite directions are blocked.
- **Empirical causality and conditional observational support**: unconditional empirical causal support requires `intervention` or `quasi_experiment` evidence. Observational evidence may receive **`partially_supported`** when a complete, evidence-bound `causal_basis` specifies the estimand, identification assumptions, and passing falsification/sensitivity checks, core observational design checks pass, and `condition` states the untestable assumptions.

---

### Pillar 2: Structured scientific checks and computable effects (`effect_records`)

In an `L2` ledger, `scaffold_claim` generates an honest all-`unknown` / `not_run` claim skeleton. Attach records appropriate to the actual study design:

- **9 design packages (`design_packages`)**: `observational`, `quasi_experimental`, `randomized`, `prediction`, `ml`, `mechanism`, `evidence_synthesis`, `theory`, and `qualitative`. Core checks cannot be bypassed with `not_applicable`; adjacent within-type levels have progressively stronger requirements.
- **8 statistical-report dimensions (`statistical_report`) and 4 provenance-card kinds (`provenance_cards`)**: sample size/independent units, estimand/scale, effects/uncertainty, assumptions, missingness/exclusions, multiplicity, direct baseline comparisons, and robustness/limits; attach `citation`, `number`, `execution`, and `search` cards.
- **Computable effects (`effect_records`)** separate `primary` / `benchmark` from `secondary` / `safety` / `exploratory` / `sensitivity` endpoints and check only declared applicable conditions:
  - **Interval–p consistency**: records declaring matching two-sided unadjusted `inference_method="wald"` or `"log_wald"` are checked for mathematical compatibility of estimate, interval, and p-value. Other or undeclared methods remain `unassessed`.
  - **GRIM and integer-denominator granularity**: proportion/accuracy records declaring `count_basis="unweighted_binary"` are checked for integer feasibility of sample size n, event counts, and decimal precision.
  - **Primary null-crossing and secondary separation**: directional `primary` / `benchmark` claims whose intervals cross the null are blocked from positive verdicts (`primary_effect_crosses_null`); supported primary benefit can coexist with nonsignificant secondary or safety endpoints.

---

### Pillar 3: Mechanical gates against empty workflows and rubber stamping (`gate_version=1`)

```text
Draft + source snapshots (reject symlinks/path escape) + scaffold_claim + Ledger v2
                                      |
                                      v  freeze (SHA-256 revision digest; case-level blind=true)
                    +-----------------+-----------------+
                    v clean context 1                   v clean context 2
             Overclaim packet                    Underclaim packet
         [0–3 substantive findings,             [0–3 substantive findings,
          stance on every claim]                 stance on every claim]
                    +-----------------+-----------------+
                                      v  both reviews complete (>3 findings: needs_split)
                              Single adjudication
            [per-claim verdict; substantive revised_text_quote or explicit disagreement]
                                      |
                                      v  verify & export (gates + non-blocking symmetry_audit)
                  Read-only HTML / Markdown report / SQLite event hash chain
```

The kernel rejects submissions that use unsupported `pass` labels, placeholder reasons, unrelated header quotes, or nominal acceptance without actual revision. Rejection does not advance the state machine.

| Gate | Typical evasion | Deterministic check |
| :--- | :--- | :--- |
| **Evidence binding and placeholders** | `pass` without evidence IDs; reasons such as `"ok"`, `"通过"`, `"见上"`, or `"TBD"` | Passing checks require nonempty `evidence_ids` and substantive reasons; positive decisions must cite evidence supporting required checks (`uncited_check_evidence`) |
| **Evidence kinds and synthetic isolation** | Labeling observational data as `intervention`; using synthetic data for real empirical conclusions | Enforce `kind` compatibility with claim type/level; positive synthetic support is limited to `description × recorded` and `computational × benchmark_measured` |
| **Unique source anchors and claim linkage** | Fabricated quotes or unrelated headers/copyright text | Positive references require a uniquely matching `quote` of at least 6 CJK characters or 12 visible ASCII characters, sharing numbers, substantive terms, or provenance-card locators with the claim (`unlinked_evidence_quote`) |
| **Four-role windows and lineage** | ANSI logs rejected; contradictions at the end of files larger than 128 KiB hidden by truncation; derived tables laundering synthetic ancestors | Strip ANSI controls; unique quotes produce budgeted windows preserving head metadata, primary quote, anchors, and tail summary; `derived_from_evidence_ids` tracks ancestor hashes and synthetic provenance |
| **Substantive incorporation and symmetry audit** | Marking `incorporated` while retaining the criticized text; unjustified downgrades without counterevidence | `revised_text_quote` must occur uniquely in both proposed and revised text, be absent from the original, and substantively replace criticized terms; otherwise record `disagreement`. Non-blocking `symmetry_audit` flags excessive hedging and unsupported abstention |

---

### Pillar 4: Execution provenance, longitudinal claim graphs, and post-hoc calibration

1. **Command provenance without recording secret environment values, and event integrity (`record-exec` / `events`)**
   - `python -m parrhesia record-exec` captures the command, Git commit/dirty state, lockfile hashes, input/output SHA-256 through `--input-file` / `--output-file`, and environment presence markers rather than secret values.
   - **Failure receipts remain durable**: timeout (wrapper `124`), start failure (wrapper `127`), and nonzero child exits preserve logs, snapshots, and events without overwriting history. Claim/run-group gates detect hidden failed forks (`selective_execution_omission`) and unadjusted selection across forks (`unadjusted_execution_multiplicity`).
   - **SQLite event hash chain (`PRAGMA user_version = 2`)**: events carry `prev_event_hash` and `event_hash`; `verify` and `get_case` expose `event_chain_status`: `verified`, `legacy_unhashed`, `mixed_verified`, or `tampered`.
2. **Longitudinal claim graph (`claim_graph`) and executable reversal triggers (`reversal_triggers`)**
   - An append-only DAG connects studies through `prior_case_ids`, `supersedes_case_id`, and `prior_claim_links` (`replicates`, `refines`, `narrows`, `extends`, `supersedes`, `reverses`, `refutes`) without modifying frozen prior cases. Draft, frozen, or unadjudicated successor relations remain `pending`; `active_standing` changes only after a valid successor adjudication.
   - Five predicate kinds—`effect_metric`, `check_status`, `evidence_status`, `execution_outcome`, `replication_verdict`—make reversal conditions executable. Adjudication rejects `self_triggering_reversal_condition`; follow-up `evaluate_triggers` returns `fired`, `unfired`, or `pending_data`.
3. **Source-bound post-hoc probability calibration (`record_calibration_outcome` / `calibration_report`)**
   - Decisions may include explicit `[0.0, 1.0]` `forecast_probability`. Append-only outcomes must bind verified `external_evidence` or a valid adjudicated `follow_up_case`; missing or invalid sources remain pending and do not enter resolved scores.
   - `calibration_report` separates explicit-forecast proper scores (`explicit_brier_score`, `explicit_log_score`, five reliability bins, `ECE`/`MCE`) from qualitative-confidence `heuristic_scores`, and separates `known_truth` interval coverage from `replication_point_containment_rate` and assumption-qualified `z_difference`.

---

## Five-minute quick start and common commands

### 1. Run the offline end-to-end demo

No network or model configuration is needed. A built-in synthetic case runs registration → freezing → blind review packets → dual-review submission → adjudication → anchor verification → atomic export. The output directory must not already exist:

```powershell
python -m parrhesia demo --output .\artifacts\my-demo
```

The directory contains an interactive read-only `review.html`, a Markdown adjudication report, `workflow-transcript.json`, and `.parrhesia/state.sqlite3`.

### 2. Core CLI reference

```powershell
# Inspect the runtime version and full JSON contract
python -m parrhesia contract

# Scaffold an all-unknown/not_run v2 claim (optional include_effect_records and check_ceilings preview)
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input docs/examples/claim-v2-unknown.json

# Execute an analysis, capture Git/lockfile/input-output hashes and non-secret environment markers, and create an execution card
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --claim-id C1 --card-id exec-1 --input-file data/clean.csv --output-file results/metrics.json -- python your_analysis.py

# Start the local stdio MCP server for a host client
python -m parrhesia serve --workspace C:\YourWorkspace
```

<details>
<summary><b>🔧 Developer commands: policy generation, Stage 0 evaluations, and packaging</b></summary>

```powershell
# 1. Check or regenerate derived policy files (AGENTS.md, host templates, SKILL.md, ChatGPT templates)
python scripts/generate-policy.py --check
python scripts/generate-policy.py

# 2. Stage 0 modes currently supported by the published repository
python scripts/run-stage0-eval.py --mode mechanical --report-out docs/verification/stage0-evaluation.md
python scripts/run-stage0-eval.py --mode prompt-export --output-dir artifacts/stage0-prompts

# 3. Automated unit tests
python -m unittest discover -s tests -v

# 4. Deterministic distribution ZIP, checking manifest/runtime version consistency
python scripts/build-release.py --output dist/parrhesia-0.3.0.zip
```
</details>

The published Stage 0 script currently supports only `mechanical` and `prompt-export`. Local extended evaluation scripts, test changes, and raw evidence were not published with these READMEs; these commands do not reproduce every local acceptance check.

---

## Our own evidence boundaries (practicing what we preach)

Parrhesia reports its own `0.3.0` maturity using the same `engineering` and `computational` evidence levels:

**Latest CI (2026-11-14, `engineering × test_passed`)**: the [GitHub Actions run](https://github.com/HERRY423/Parrhesia/actions/runs/43608255809) for [commit `9581eae`](https://github.com/HERRY423/Parrhesia/commit/9581eae170525e5d9d61586c78774085b2edaead) completed on both Windows and Ubuntu (Python 3.11) with **117 tests passed, 0 failures, and 0 skips**; policy generation consistency checks also passed. Both platforms installed `jsonschema==4.26.0` and actually ran and passed `test_actual_official_schemas` (original schema byte hashes, identifiers, Draft 2020-12 validity, and `plugin.json` / `mcp.json` validation). This result covers only that commit's public CI test suite. It does not replace historical test totals, extend the `host_accepted` scope below, or change the remaining limitations; earlier failure and skip records are retained.

| Evaluation area | Current evidence and judgment | Supported scope and limits |
| :--- | :--- | :--- |
| **Windows Codex desktop integration and native file-symlink rejection**<br>(`engineering × host_accepted`, **supported** within scope) | On 2026-11-14, Windows 11 + Python 3.13.9 + Codex desktop loaded the frozen `0.3.0` package ([acceptance summary](docs/verification/release-0.3.0.md)). Harm-proposition review/adjudication/export, pending successor relations, calibration source verification/invalidation, CLI timeout/start-failure/nonzero-exit receipts read back by the host, and native file-symlink rejection after enabling Developer Mode were exercised. Original symlink test: 1 passed, 0 skipped; rejected registration changed neither evidence nor events | The local MCP workflow, state machine, event chain, and tested path boundary operated according to contract in this Windows Codex session with fixed synthetic material. **Limits**: reviewer content was a same-context fixed fixture, not independent scientific model review; this does not establish acceptance on other hosts, coverage of all reparse point types or concurrency races, or `user_impact` |
| **Local state machine, gates, computable effects, longitudinal calibration, and host adapters**<br>(`engineering × test_passed`, **supported**) | `0.3.0` separates proposition support from benefit direction, requires explicit `wald`/`log_wald` and `unweighted_binary` applicability, preserves pending draft successors, binds outcome sources, separates explicit forecasts from heuristics and truth coverage from replication containment, and retains failure receipts ([migration guide](docs/migration-0.3.md)). The pre-repair historical snapshot contains 184 unit tests and five Stage 0 evaluation columns ([Stage 0](docs/verification/stage0-evaluation.md), [0.2.0 verification](docs/verification/release-0.2.0.md)) | Supports the tested SQLite ACID transactions, `events` SHA-256 chain, 22 MCP tools including `parrhesia_validate` and `repair_hint`, anti-rubber-stamping gates ([hardening verification](docs/verification/gate-bypass-hardening-20261019.md)), and adapter structure/contracts for Codex, Claude, Grok, Antigravity, and ChatGPT. Historical totals are not post-repair rerun counts |
| **Net behavioral improvement on live LLMs**<br>(`computational × unassessed`, **insufficient_evidence** / `not_run`) | The [evaluation plan](docs/evaluation-plan.md) is frozen and leakage-audited four-arm blind prompt packets were exported (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`; `279` packets). External paid LLM blind evaluation remains `not_run` | Reductions in overclaim, excessive disclaimers, and hollow neutrality have **not been measured on a real blinded held-out evaluation**. The plan estimates 120–160 independent cases to detect an absolute improvement of 15–20 percentage points |
| **Deterministic cross-checks versus scientific truth**<br>*(architectural boundary)* | The engine checks source SHA-256, unique claim-linked quotes, progressively required design checks, evidence-bound `pass`, explicit design contradictions, and `input_manifest` | Deterministic checks are **not proof of scientific truth**. They can block empty form-filling, unsupported `pass`, adjacent-level misuse, and unbound outcomes, but cannot independently identify carefully fabricated source files without a reproducible execution chain or replace domain peer review |

---

Additional acceptance scope: failure receipts cover **installed CLI execution → native host readback**, not arbitrary command execution through MCP. File-symlink acceptance does not cover directory junctions or concurrent replacement races; ordinary-file registration passed as a positive control. Raw tool responses, tests, databases, and earlier failure/skip records remain local. The public acceptance summary is not a complete reproducibility bundle.

## Documentation

- **Core policy and contracts**
  - [Single policy source (`policy/parrhesia-policy.md`)](policy/parrhesia-policy.md) · [Product design (`docs/product-design.md`)](docs/product-design.md) · [Runtime contract (`docs/contract.md`)](docs/contract.md)
  - [0.3.0 migration (`docs/migration-0.3.md`)](docs/migration-0.3.md) · [0.2.0 migration (`docs/migration-0.2.md`)](docs/migration-0.2.md) · [Evaluation plan (`docs/evaluation-plan.md`)](docs/evaluation-plan.md)
- **Host integrations and skills**
  - [L2 review workflow (`skills/parrhesia-review/SKILL.md`)](skills/parrhesia-review/SKILL.md) · [L2 scientific reference (`skills/parrhesia-l2-reference/SKILL.md`)](skills/parrhesia-l2-reference/SKILL.md)
  - [Antigravity](docs/antigravity-integration.md) · [Grok](docs/grok-integration.md) · [ChatGPT](docs/chatgpt-integration.md)
  - [Repository `AGENTS.md`](AGENTS.md) · [Full policy template](templates/AGENTS.parrhesia.md) · [Codex compact template](templates/AGENTS.parrhesia.codex.md) · [ChatGPT template](templates/AGENTS.parrhesia.chatgpt.md)
- **Verification and audits**
  - [0.3.0 desktop acceptance (`docs/verification/release-0.3.0.md`)](docs/verification/release-0.3.0.md) · [0.2.0 verification (`docs/verification/release-0.2.0.md`)](docs/verification/release-0.2.0.md)
  - [Stage 0](docs/verification/stage0-evaluation.md) · [Anti-stall gates](docs/verification/anti-stall-gates.md) · [Gate-bypass hardening](docs/verification/gate-bypass-hardening-20261019.md)

---

## License and repository

- **License**: [Apache-2.0 License](LICENSE)
- **Repository**: [https://github.com/HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
