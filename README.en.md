# Parrhesia

**Latest acceptance (2026-11-14):** The Windows Codex desktop host loaded 0.3.0. Harm-proposition review/export, pending successor standing, calibration source binding, CLI failure receipts read back by the host, and Windows native file-symlink rejection reached **engineering × host_accepted** within fixed synthetic scenarios. The original symlink test passed with zero skips; earlier permission failures remain preserved. This does not establish independent scientific review, acceptance on other hosts, user_impact, or coverage of all reparse points/races. [Scope, artifact identity and limitations](docs/verification/release-0.3.0.md).

Local repair status (2026-11-14): numerical checks now require explicit applicability, draft replacement edges remain pending, calibration separates verified sources, explicit forecasts and known-truth coverage from unresolved reports, heuristic mappings and replication containment. Timeout/start failures retain durable receipts. The 184-test and existing Stage 0 figures below are the pre-repair historical snapshot; see the [0.3 migration guide](docs/migration-0.3.md); detailed test and acceptance records remain local.

**Proportion claim strength to evidence. End hollow neutrality through explicit adjudication.**

**Language / 语言**：**[简体中文](README.md)** · English

Parrhesia is a local, zero-dependency evidence-calibration and dual-review adjudication plugin conforming to the [Agent Plugins 1.0.0](https://agent-plugins.org/) specification, paired with a single-source-of-truth cross-platform `AGENTS.md` policy system. The current version is **`0.3.0`** (new cases enforce `schema_version=2` and mechanical gates `gate_version=1`, while preserving legacy records; see the [migration guide](docs/migration-0.3.md)). Source and frozen acceptance artifacts have distinct identities; this documentation update does not rebuild the package or create a GitHub Release.

See [Changelog](CHANGELOG.md) · [0.1.0 → 0.2.0 Migration Guide](docs/migration-0.2.md) · [0.2.0 Release Verification](docs/verification/release-0.2.0.md) · [Stage 0 Evaluation Report](docs/verification/stage0-evaluation.md)

---

## Why Parrhesia?

When a single LLM is asked in one context to draft conclusions, critique over-interpretation, rescue buried findings, and issue a final verdict simultaneously, it predictably falls into three systematic failure modes. Parrhesia resolves this by **architecturally decoupling** these conflicting roles:

| Failure Mode | Observable Symptom in Daily AI Workflows | Parrhesia's Decoupled Mechanism | Forbidden Proxy Metric |
| :--- | :--- | :--- | :--- |
| **1. Idealization & Overclaiming**<br>*(Overclaim)* | Leaping from correlation to causal verbs ("drives / regulates / causes"); presenting synthetic runs or internal splits as real-world clinical/production gains; extrapolating local findings universally | **Overclaim Reviewer (`overclaim`)**<br>Audits only upward leaps beyond evidence, unaddressed confounding, and missing controls: *What is the highest level the frozen evidence actually supports?* | "Whether the tone sounds humble or cautious" |
| **2. Defensive Disclaimer Inflation**<br>*(Underclaim)* | Burying a robust externally validated result or reproducible benchmark gain under generic boilerplate ("given limited sample size and lack of a multicenter Phase III RCT, no conclusion can be drawn, for reference only") | **Underclaim Reviewer (`underclaim`)**<br>Audits only unsupported self-weakening and non-specific disclaimers: *What contribution has the evidence already solidly established?* | "How many disclaimers were deleted" |
| **3. Hollow Neutrality**<br>*(Fence-Sitting)* | "On one hand... on the other hand... more research is needed," pleasing both sides without weighing competing explanations or stating what would falsify either view | **Single Adjudicator (`adjudicator`)**<br>No voting or averaging; issues a single explicit verdict per claim (`supported`, `partially_supported`, `unsupported`, or `insufficient_evidence`) with an **observable reversal condition** | "Whether the conclusion sounds bold or matches user wishes" |

### Before vs. After Calibration at a Glance

- ❌ **Overclaim Anti-Pattern**: "Single-cell co-expression and significant regression ($p=0.002$) prove transcription factor X activates pathway Y and causes drug resistance."
- ❌ **Underclaim (Disclaimer Inflation) Anti-Pattern**: "Although the model achieved AUROC 0.84 (95% CI 0.77–0.90) in an independent external cohort ($N=120$), due to limited sample size, potential unknown bias, and lack of a Phase III randomized trial, no firm conclusion can be drawn; for reference only."
- ✅ **Parrhesia Calibrated Statement**:
  > "In the independent external validation cohort ($N=120$), the model demonstrates robust external discrimination for 1-year recurrence (`prediction × externally_validated`, **supported**; AUROC 0.84, 95% CI 0.77–0.90), supporting its use as a candidate risk-stratification tool in similarly distributed populations; net clinical decision utility (`utility`) awaits prospective interventional evaluation. If calibration slope falls outside $[0.8, 1.2]$ in subsequent multi-center cohorts, narrow applicability to the original center distribution."

**Three Non-Negotiable Baselines** (see [Single Policy Source](policy/parrhesia-policy.md)):
1. **Priority Hierarchy**: Platform system instructions > Platform developer instructions > User message. Within those bounds: **Data confidentiality & spend caps > Evidence truth > Proportional claim strength > Full expression of supported contributions > Efficiency**.
2. **Never fabricate certainty, and never treat absence of evidence as evidence of absence**: Fabricating data, numbers, citations, executions, or searches is strictly forbidden. When evidence is insufficient, record `insufficient_evidence` explicitly as a formal judgment—neither inflating it into support nor conflating it with `unsupported`.
3. **User preference is not evidence**: The user controls task scope, output format, language, and workflow tier, but never dictates evidence grades or verdicts.

---

## Installation & Multi-Host Integration

Running the local MCP server and CLI requires **Python 3.11+** using **only the Python standard library** (zero third-party dependencies; no `pip install` required).

### Method 1: Codex Plugin Marketplace (GUI / CLI)

#### 1. GUI "Add Plugin Marketplace" Dialog (Recommended)

In the Codex desktop app's Plugin Manager, click **Add Plugin Marketplace** (*Add from a GitHub repository, Git URL, or local folder*) and fill in the dialog fields as follows:

| Dialog Field | Value to Enter | Notes |
| :--- | :--- | :--- |
| **Source** (*来源*) | `HERRY423/Parrhesia`<br>*(or `https://github.com/HERRY423/Parrhesia.git`)* | For offline use or a local clone, you may also select the local repository root containing `.agents/plugins/marketplace.json` (e.g., `C:\Parrhesia`) |
| **Git Ref** (*Git 引用*) | `main` | Tracks the latest `0.2.0` branch; pin a specific tag or commit SHA if needed |
| **Sparse Path** (*稀疏路径*) | **Leave blank** | The marketplace manifest lives at the repository root. **Do not** type the gray placeholder `plugins/codex` |

Click **Add Marketplace**, then select **Parrhesia Marketplace** and install **Parrhesia**.

#### 2. Codex CLI Installation

```powershell
# Add the marketplace from GitHub and install the plugin
codex plugin marketplace add HERRY423/Parrhesia --ref main
codex plugin add parrhesia@parrhesia-marketplace

# (Optional) Add the marketplace from a local checkout
codex plugin marketplace add C:\Parrhesia
```

#### 3. Sync Compact Global Policy & On-Demand L2 Reference Skill for Codex

To avoid bloating every conversation with the `49,260 B` (~`48.1 KiB`) full policy file, Codex uses a **compact resident policy block (`9,101 B` / ~`8.9 KiB`, strictly `< 10 KiB`) + on-demand `parrhesia-l2-reference` skill (`19,764 B`) + isolated role packets**:

```powershell
# Sync the compact block into ~/.codex/AGENTS.md and install ~/.codex/skills/parrhesia-l2-reference/SKILL.md
python scripts/install-codex.py

# Read-only check verifying ~/.codex is in sync with policy/parrhesia-policy.md
python scripts/install-codex.py --check
```

---

### Method 2: Claude Code Marketplace & Standard Agent Plugins 1.0.0 Hosts

#### 1. Claude Code CLI

```bash
claude plugin marketplace add HERRY423/Parrhesia
claude plugin install parrhesia@parrhesia-marketplace
```

#### 2. Standard Agent Plugins 1.0.0 Clients

Any host supporting Agent Plugins 1.0.0 discovers `plugin.json`, `mcp.json`, and `skills/` at the repository root and exposes **22 local stdio MCP tools**, read-only resources, and role prompt templates:
- **18 per-action typed tools (`parrhesia_<action>`)**: Dedicated schemas and annotations for `create_case`, `register_evidence`, `register_hypothesis`, `scaffold_claim`, `set_ledger`, `freeze`, `review_packet`, `submit_review`, `adjudication_packet`, `submit_adjudication`, `verify`, `get_case`, `export`, `record_human_decision`, `claim_graph`, `evaluate_triggers`, `record_calibration_outcome`, and `calibration_report`.
- **`parrhesia_validate`**: Zero-side-effect SQLite `ROLLBACK` preflight validator returning a dry-run preview or a structured `repair_hint` on contract failure.
- **3 backward-compatible legacy tools**: `parrhesia_contract` (read workspace and contract), `parrhesia_select_workspace` (explicitly bind a user-authorized directory), and `parrhesia_workflow` (generic action dispatcher).
- **MCP Resources, Prompts & Actionable Errors**: Concrete resources `parrhesia://contract`, `parrhesia://cases`, `parrhesia://claim-graph`, `parrhesia://calibration`, URI templates `parrhesia://cases/{case_id}`, `/ceilings`, `/triggers`, `/packet/{role}`, prompts `parrhesia_review_overclaim`, `parrhesia_review_underclaim`, `parrhesia_adjudicate`, and structured `repair_hint` fields on JSON-RPC tool errors.

---

### Method 3: Grok Build CLI Project Adapter

For Grok Build CLI (verified on `grok 1.0.48` for manifest validation and project MCP discovery), an idempotent installer deploys both `parrhesia-review` and `parrhesia-l2-reference`, backs up existing files, merges `.mcp.json`, and maintains a compact `AGENTS.md` policy block by default (`9,101 B`; pass `--policy full` for the complete block):

```powershell
# Install into a target project (or run & .\scripts\install-grok.ps1 -Project C:\YourProject)
python scripts/install-grok.py --project C:\YourProject

# Read-only integrity/drift check or clean uninstall
python scripts/install-grok.py --project C:\YourProject --check
python scripts/install-grok.py --project C:\YourProject --uninstall

# Verify Grok configuration discovery
grok --cwd C:\YourProject inspect
```
*See [Grok Integration Guide](docs/grok-integration.md).*

---

### Method 4: Antigravity IDE / CLI Host Adapter

For Google Antigravity (Antigravity IDE / Antigravity 2.0 / `agy` CLI), a self-contained adapter writes a compliant `.agents/plugins/parrhesia/` bundle (allowlisted `plugin.json`, `mcp_config.json`, frontmatter-free `< 24,000 B` compact `rules/parrhesia.md`, both `parrhesia-review` and `parrhesia-l2-reference` skills, and a silent read-only `SessionStart` SQLite hook) without ever touching `~/.gemini/config/config.json`:

```powershell
# Install into a target project (or run & .\scripts\install-antigravity.ps1 -Project C:\YourProject)
python scripts/install-antigravity.py --project C:\YourProject

# Read-only check, clean uninstall, or isolated user-target install
python scripts/install-antigravity.py --project C:\YourProject --check
python scripts/install-antigravity.py --project C:\YourProject --uninstall
python scripts/install-antigravity.py --scope user --target C:\CustomAntigravityHome
```
*See [Antigravity Integration Guide](docs/antigravity-integration.md).*

---

### Method 5: ChatGPT Web / Custom GPT Text Protocol (Zero Local Dependencies)

Run the L2 dual-review workflow in ChatGPT Web across isolated chat sessions without local Python execution:
1. Paste [templates/AGENTS.parrhesia.chatgpt.md](templates/AGENTS.parrhesia.chatgpt.md) into your ChatGPT Project Instructions or Custom GPT Instructions.
2. Generate the handoff kit into a new directory:
   ```powershell
   python scripts/prepare-chatgpt.py --output artifacts/chatgpt-kit
   ```
3. Follow the [ChatGPT Integration Guide](docs/chatgpt-integration.md): freeze the ledger with `01-frozen-input.md` (or `01-frozen-input-blind.md`) → run `02-overclaim.md` and `03-underclaim.md` in two fresh chat sessions → adjudicate with `04-adjudication.md` → archive with `05-handoff-record.md`.

---

## Progressive Four-Tier Workflow (`L0` / `L1` / `L1-Explore` / `L2`)

Parrhesia avoids bureaucracy on trivial tasks while enforcing strict accountability on high-stakes conclusions. Every final response begins with the active tier tag on its own first line:

```text
Incoming Task Request
  │
  ├─► Translation / formatting / single verifiable fact / local code edit / raw calculation?
  │     └──► [L0] Execute directly with zero structural overhead
  │
  ├─► Brainstorming / hypothesis generation / mechanism sketching / study or identification design?
  │     └──► [L1-Explore] Lightweight Exploration Ledger (no L2 database or dual review)
  │            Maintain 2–3 candidate hypothesis cards (explicitly marked exploratory), each with 5 fields:
  │            ① Strongest Rival · ② Discriminating Experiment · ③ Cost · ④ Stopping Rule · ⑤ Kill Condition
  │
  ├─► Everyday explanation / comparison / recommendation / evidence judgment / EDA summary?
  │     └──► [L1] Default Calibration Contract
  │            ① Opening verdict + claim_type × evidence_level + scope
  │            ② Verifiable basis (name the strongest rival explanation on research questions)
  │            ③ Observable reversal condition · ④ Immediate next action · ⑤ Exception report on failed baseline checks
  │
  └─► Figure legends / abstracts / manuscript text / formal reports / re-evaluating challenged core claims?
        └──► [L2] Frozen Ledger + Blind Dual Review + Single Adjudication (3–5 core claims per case)
```

---

## Core Architecture: 2D Evidence Classification & Eight Anti-Rubber-Stamping Gates

### 1. Beyond a Single Linear Ladder: `claim_type × evidence_level + scope` (Claim Schema v2)

A single global ladder (`descriptive → association → predictive → mechanistic → causal`) falsely implies that prediction is "lower" than mechanism or that repeated correlations become causal. Parrhesia `0.2.0` classifies claims along **12 claim types × type-local evidence levels + explicit scope**, paired with `claim_basis` (`empirical` / `synthetic` / `formal`):

| Claim Type (`claim_type`) | Type-Local Evidence Levels (`evidence_level`, each starting at `unassessed`) | Wording & Authorization Boundary |
| :--- | :--- | :--- |
| `description` | `recorded` · `measurement_checked` · `replicated` | Describes observed objects only; no population generalization or mechanism |
| `association` | `unadjusted` · `adjusted` · `robust_association` | Use "associated with"; covariate adjustment does not eliminate unmeasured confounding |
| `prediction` | `apparent` · `internally_validated` · `externally_validated` · `prospectively_evaluated` | State target, horizon, and population; external discrimination $\neq$ clinical utility or mechanism |
| `causal_effect` | `unidentified` · `identified_under_assumptions` · `sensitivity_supported` | Causal verbs apply only to the specified `estimand`, design family, and identification assumptions |
| `mechanism` | `compatible` · `component_tested` · `causal_chain_tested` | Co-expression/enrichment is at most `compatible`; full chain requires orthogonal rescue & rival exclusion |
| `necessity` | `bounded_test` · `counterfactual_supported` | Whether removing $X$ prevents $Y$ in the specified context; **never implies sufficiency** |
| `sufficiency` | `bounded_test` · `counterfactual_supported` | Whether introducing $X$ produces $Y$ in the specified context; **never implies necessity** |
| `synthesis` | `mapped` · `critically_appraised` · `synthesized_with_uncertainty` | Inherits primary-study bias and dependence; pooling never manufactures causal identification |
| `theory` | `conjectured` · `proved_under_assumptions` · `independently_checked` | Requires `claim_basis="formal"`; numerical examples do not replace proof |
| `qualitative` | `situated_description` · `interpretation_audited` · `triangulated` | Preserves context and negative cases; do not impose population frequencies or $p$-values |
| `computational` | `benchmark_measured` · `reproduced` · `externally_evaluated` | Report datasets, budget-matched baselines, and seeds; leaderboard gain $\neq$ deployment impact |
| `engineering` | `test_passed` · `host_accepted` · `user_impact` | Passing unit tests $\neq$ live host acceptance; protocol handshake $\neq$ measured user benefit |

### 2. Eight Deterministic Anti-Rubber-Stamping Gates (`gate_version=1`)

To prevent an agent from gaming the ledger by filling every check with `pass` + `"ok"`, marking core checks `not_applicable`, quoting an unrelated 12-character header, or mislabeling observational data as `intervention`, `parrhesia/gates.py` enforces eight deterministic structural and cross-reference gates:

1. **Full 9-Family Essential Check Coverage & Level-Progressive Ceilings (`check_ceilings` & `FAMILY_TIER_CHECKS`)**:
   - **All 9 design families enforced**: Core design checks cannot be bypassed via `not_applicable` in *any* family—including `theory` (`definitions_assumptions`, `proof`), `qualitative` (`epistemic_position`, `sampling_context`, `analysis_audit`), and `evidence_synthesis` (`protocol_search`, `eligibility_selection`, `bias_dependence`), alongside `observational`, `quasi_experimental`, `randomized`, `prediction`, `ml`, and `mechanism`.
   - **Mechanical differentiation across adjacent `evidence_level`s**: Adjacent grades within the same `claim_type` require strictly expanding design, fixed, and statistical checks (e.g., `association`: `unadjusted < adjusted < robust_association`; `causal_effect`: `identified_under_assumptions` requires passing identification assumptions, whereas `sensitivity_supported` additionally requires passing `falsification_sensitivity` and tier-3 sensitivity/robustness checks; `theory`, `qualitative`, and `synthesis` likewise require progressive check tiers).
2. **Evidence-Bound Substantive `pass`, Bilingual Placeholder Blocking & Decision Citation Verification (`effective_status`, `is_placeholder` & `uncited_check_evidence`)**: Any `pass` in `design_packages`, `statistical_report`, or `causal_basis` must carry non-empty `evidence_ids` and a substantive `reason` (bilingual rubber-stamp placeholders such as `"ok"`, `"pass"`, `"yes"`, `"done"`, `"TBD"`, `"TODO"`, `"see above"`, `"未知"`, `"无"`, `"待定"`, `"见上"`, `"同上"`, `"略"`, `"通过"`, `"合格"` are rejected across reasons, conditions, locations, estimands, and disagreements). Positive decisions must cite the `evidence_ids` backing every required passing check (`uncited_check_evidence`). Citation contradiction detection (`is_contradicting_relation`) catches both exact labels and natural-language rewrites (`"does not support"`, `"fails to support"`, `"contrary to"`, `"无法支持"`, `"不足以支持"`, `"与主张矛盾"`, `"证伪"`, while respecting double negations like `"does not contradict"` / `"不矛盾"`).
3. **Evidence-Kind Compatibility & Source Contradiction Detection (`incompatible_evidence_kind` & `contradictory_evidence_kind`)**: Every cited reference must match the `COMPATIBILITY` matrix for `claim_type × evidence_level`; if the snapshot text explicitly describes a weaker contradicting study design (e.g., registering an explicitly non-randomized observational cohort as `kind="intervention"`, or internal cross-validation as `kind="prediction_external"`), positive support is rejected with `contradictory_evidence_kind`.
4. **Synthetic Evidence Isolation (`synthetic_empirical_support`)**: Any evidence with `kind="synthetic"` or `provenance="synthetic"` is blocked from supporting `empirical` or `formal` positive verdicts; synthetic positive scope is restricted to `description × recorded` and `computational × benchmark_measured`.
5. **Language-Aware Unique Quote Anchoring & Claim-Linkage Verification (`unanchored_positive_evidence` & `unlinked_evidence_quote`)**: Every positive reference requires a unique literal `quote` of at least **12 non-whitespace units (weighted by lexical density: 2 units per CJK character so $\ge 6$ CJK characters $\equiv \ge 12$ ASCII characters)** and a concrete non-placeholder `location`, **and** the quote must share quantitative values, substantive domain terms, or checked-card locators with the claim (`unlinked_evidence_quote` blocks arbitrary unrelated substrings from the source file).
6. **ANSI Terminal Log Normalization, $> 128\text{ KiB}$ 4-Role Windowing, Derived Lineage Propagation & Unread Acknowledgment (`text_content`, `excerpt_anchors` & `derived_from_evidence_ids`)**:
   - `text_content()` automatically strips ANSI CSI/OSC color and cursor escape sequences (`\x1b[...m`) and benign terminal controls from `record-exec` logs while still rejecting PDF/ZIP/PNG/ELF headers and NUL-bearing binary streams.
   - Review packets cap inline source text at **128 KiB** (an operational prompt-budget bound): when a $> 128\text{ KiB}$ UTF-8 text source has a unique registered `quote` (optionally paired with `excerpt_anchors`), the engine generates structured 4-role excerpt windows $\le 128\text{ KiB}$ (`<<<PARRHESIA_EXCERPT_WINDOW ...>>>` preserving `head_metadata`, `quote_primary`, `anchor_excerpt`, and `tail_summary` so late-file contradictions/failures are not hidden behind truncation; `excerpt_window.quote_anchored = true`), allowing positive verdicts once acknowledged in `unread_evidence_ids`; unquoted $> 128\text{ KiB}$ files and unread binary leaf sources remain blocked from positive support.
   - `register_evidence` and CLI `record-exec --derived-from --derivation-step` track derived-artifact lineage (`derived_from_evidence_ids`), mechanically blocking `synthetic` ancestor laundering (`synthetic_empirical_support`), preserving `hash_verified_unread_binary_ancestors` audit trails for SHA-256-verified read-only binary upstreams, and blocking tampered ancestor artifacts on disk.
7. **Complete Original-Claim Stances, 3-Finding Focus Budget & Non-Blocking Symmetry Audit (`incomplete_stances` & `symmetry_audit`)**: Reviewers must submit an explicit stance on every frozen claim even when reporting zero findings. Each reviewer role is capped at **0–3 findings** per pass to prioritize the highest-impact flaws (setting `review_status="needs_split"` when $>3$ substantive issues exist). Verification and exported reports also emit non-blocking advisory `symmetry_audit` flags across five anti-underclaim / false-abstention hooks (`possible_false_abstention`, `possible_unjustified_downgrade`, `unsupported_without_counterevidence`, `possible_boilerplate_overhedging`, `rejected_underclaim_finding_advisory`) without blocking calibrated exports.
8. **Substantive Disposition Incorporation, Blind Freeze, Honest Isolation Attestation & Fork Multiplicity (`finding_not_incorporated`, `case_level_blind`, `isolation_attestation` & execution-fork gates)**: Incorporations require a unique `revised_text_quote` ($\ge 6$ CJK or $\ge 12$ ASCII characters) present in both `proposed_text` and `revised_text` and case-insensitively absent from `original.text`, **and** enforce substantive adoption: `revised_text` cannot keep `original.text` verbatim with a tacked-on sentence, cannot retain criticized terms that `proposed_text` removed, and must adopt the issue-linked replacement terms from `proposed_text` (and in `partial` mode, `revised_text_quote` itself must anchor those issue-linked terms rather than a filler clause); unincorporated recommendations must record `resolution="disagreement"`. `blind=true` is frozen at case creation, and reports record `reviewer_input_manifests` plus optional caller-supplied `isolation_attestation` (`history_inheritance`, `memory_access`, `host_surface`—honestly defaulting to `"UNKNOWN"` when omitted rather than hardcoded strings). Execution forks recorded via `record-exec` are tracked per `claim_id` / `run_group` and cross-checked against SQLite events (`selective_execution_omission`, `unadjusted_execution_multiplicity`, while permitting explicitly disclosed non-primary failed forks alongside an accountable primary run).
9. **Computable `effect_records` Verification, Secret-Free Auto-Provenance & SQLite Event Hash Chain (`user_version=2`)**:
   - `scaffold_claim(include_effect_records=True)` initializes structured `effect_records` separating `primary`/`benchmark` endpoints from `secondary`/`safety`/`exploratory`/`sensitivity` outcomes. Deterministic checks enforce CI-vs-$p$-value compatibility (`effect_pvalue_ci_mismatch`), GRIM/granularity integer feasibility (`effect_grim_inconsistent`), primary-only null-crossing blocking (`primary_effect_crosses_null`, allowing calibrated `supported` verdicts when secondary or safety endpoints cross null), record anchor verification (`unanchored_effect_record`), polarity/direction consistency (`effect_direction_mismatch`), and non-blocking underclaim advisories (`unsupported_despite_beneficial_primary_effect`), reporting per-record `effect_checks` on `verify`.
   - `record-exec` adds `--input-file`, `--output-file`, and `--stdout-excerpt-chars` (default `400`, cap `2000`) alongside automatic git/lockfile SHA-256 capture and presence-only non-secret env markers; `PRAGMA user_version = 2` chains SQLite `events` with `prev_event_hash`/`event_hash` SHA-256 digests and surfaces `event_chain` / `event_chain_status` (`verified`, `legacy_unhashed`, `mixed_verified`, `tampered`) on `verify` and `get_case`.
10. **Cross-Time Claim Graph (`claim_graph`), Executable Reversal Triggers & Measurable Calibration**:
   - **Append-only longitudinal DAG**: `create_case` (`prior_case_ids`, `supersedes_case_id`, `case_relation`) and claim `prior_claim_links` (`replicates` / `refines` / `narrows` / `extends` / `supersedes` / `reverses` / `refutes`) connect follow-up cases without mutating frozen prior records or exports; `claim_graph` (and `parrhesia://claim-graph`) traces per-claim verdict/level trajectories and deterministic `active_standing`.
   - **5 executable trigger kinds (`reversal_triggers` & `evaluate_triggers`)**: Replaces vague "more research needed" text with verifiable predicates across `effect_metric`, `check_status`, `evidence_status`, `execution_outcome`, and `replication_verdict`. Adjudication blocks `self_triggering_reversal_condition`, `contradictory_claim_lineage_transition`, and `untriggered_reversal_link`; read-only `evaluate_triggers` (and `parrhesia://cases/{case_id}/triggers`) evaluates triggers against `against_case_id`, inline `observations`, or live workspace state as `fired`, `unfired`, or `pending_data`.
   - **Empirical post-hoc calibration (`forecast_probability`, `record_calibration_outcome` & `calibration_report`)**: Adjudication decisions accept optional `[0.0, 1.0]` `forecast_probability` values; after adjudication or export, append-only `record_calibration_outcome` logs replication/interval observations without rewriting `input_digest`, `adjudication_digest`, or event hash chains; and `calibration_report` (and `parrhesia://calibration`) computes Brier/log proper scores, 5 reliability bins (`ECE`/`MCE`), confidence strata, known-truth CI coverage separately from replication point containment and assumption-qualified `z_difference`, and `trigger_precision`.

---

## Quick Start & Common Commands

```powershell
# 1. Run the offline end-to-end synthetic demonstration (output directory must not exist yet)
python -m parrhesia demo --output .\artifacts\my-demo

# 2. Scaffold an honest all-unknown v2 claim template (optionally with include_effect_records) and inspect check_ceilings
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input docs/examples/claim-v2-unknown.json

# 3. Execute a command, auto-capture git/lockfile/input-output hashes & non-secret env markers into a unique log, and emit a claim-scoped execution card
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --claim-id C1 --card-id exec-1 --input-file data/clean.csv --output-file results/metrics.json -- python your_analysis.py

# 4. Verify single-source policy generation, strict zero-leakage Stage 0 evaluation suites (split columns + de-leaked prompt export), and all 184 unit tests
python scripts/generate-policy.py --check
python scripts/check-eval-leakage.py --strict
python scripts/run-stage0-eval.py --mode mechanical --report-out docs/verification/stage0-evaluation.md
python scripts/run-stage0-eval.py --mode counterfactual
python scripts/run-stage0-eval.py --mode fork-multiplicity
python scripts/run-stage0-eval.py --mode symmetry
python scripts/run-stage0-eval.py --mode lineage-window
python scripts/run-stage0-eval.py --mode heldout
python scripts/run-stage0-eval.py --mode metamorphic
python scripts/run-stage0-eval.py --mode p1-effects
python scripts/run-stage0-eval.py --mode p2-longitudinal
python scripts/run-stage0-eval.py --mode prompt-export --output-dir artifacts/stage0-prompts
python -m unittest discover -s tests -v

# 5. Build the deterministic Agent Plugins 1.0.0 release archive
python scripts/build-release.py --output dist/parrhesia-0.3.0.zip
```

---

## Self-Applied Evidence Boundary (Practicing What We Preach)

| Dimension | Current Classification & Evidence | Supported Claim & Honest Boundary |
| :--- | :--- | :--- |
| **Local State Machine, Mechanical & Computable Gates, Longitudinal Triggers & Calibration**<br>(`engineering × test_passed`, **supported**) | 184 automated tests (182 passed, 2 skipped: host symlink permissions and optional `jsonschema`; covering `tests/test_adapters.py`, `tests/test_effects.py`, `tests/test_longitudinal_calibration.py`, `tests/test_record_exec_provenance.py`, `tests/test_server.py`, and `tests/test_packaging.py`; earlier baseline in [release-0.2.0.md](docs/verification/release-0.2.0.md)); `check-eval-leakage.py --strict` (`overlap=0`) and all five Stage 0 split-column suites pass: `dev_phrase_consistency` (`40/40` L2 across 10 families, `9/9` `L1-Explore`, 60 Card A, 60 Card B, 136 Card C, `6/6` paired twins, `4/4` lineage/window specs), `heldout_generalization` (`24/24` realistic controls `FRR=0.0`, `6/12` adversarial paraphrases caught mechanically while `HADV-07..12` stay explicitly `uncaught_without_llm_or_p1`), `metamorphic_invariance` (`12/12`), separate `p1_effect_records` (`12/12`, `0` FRR on `PEFF-01`, `11/11` computable traps incl. `6/6` structured `HADV-07..12` counterparts, `12/12` `event_chain_status=verified`), and separate `p2_longitudinal_calibration` (`8/8`: `4/4` positive controls + `4/4` longitudinal/self-triggering/lineage traps, `8/8` `event_chain_status=verified`) ([stage0-evaluation.md](docs/verification/stage0-evaluation.md)) | Verifies SQLite ACID transactions (including `PRAGMA user_version = 2` SHA-256 `events` hash chain), 22 MCP tools (18 typed per-action tools, `parrhesia_validate` rollback preflight, 4 resources / 7 templates, prompts, and `repair_hint`), computable `effect_records` checks, append-only `claim_graph` DAG lineage & `active_standing`, 5 executable `reversal_triggers` kinds & `evaluate_triggers`, post-export `record_calibration_outcome` & `calibration_report` metrics, secret-free `record-exec` provenance, anti-rubber-stamping gates (see [gate-bypass-hardening-20261019.md](docs/verification/gate-bypass-hardening-20261019.md)), `LEGACY_UNGATED` recovery, and standalone ZIP execution; `p1_effect_records` and `p2_longitudinal_calibration` require structured records and do not replace prose-level dual review |
| **Multi-Host Sync, Engineering Adapters & Historical Handshake**<br>(`engineering × test_passed`, **supported**; `0.2.0` live orchestration pending) | Antigravity adapter (`.antigravity-plugin/plugin.json`, `install-antigravity.py`/`.ps1` `--check`/`--uninstall`, frontmatter-free `< 24,000 B` rules, dual skills, read-only `SessionStart` hook, isolated `--scope user`), Grok `0.2.0` adapter (dual skills, `compact|full`, `--check`/`--uninstall`, `grok 1.0.48` manifest validation & isolated project `.mcp.json` discovery), `install-codex.py`, marketplace schema checks, and [ChatGPT kit verification](docs/verification/chatgpt-adapter.md) pass; [Grok 1.0.48 native handshake](docs/verification/grok-native.json) is a historical `0.1.0` record | Proves package structure, manifest schemas, rule size limits, shell hook safety, file integrity checks, and stdio MCP handshakes; does not misrepresent local adapter tests or `0.1.0` logs as live Antigravity / Grok end-to-end multi-agent review validation |
| **Net Behavioral Improvement on Live LLMs**<br>(`computational × unassessed`, **insufficient_evidence** / `not_run`) | [Evaluation plan](docs/evaluation-plan.md) frozen and 4-arm de-leaked prompt packets (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`, `279` total packets across base L2, `L1-Explore`, Card A, Card B, Card C symmetry, paired sensitivity, held-out controls, held-out adversarial paraphrases, metamorphic invariance, `p1_effect_records`, and `p2_longitudinal_calibration`, verified by `--prompt-export` leakage audit + `scoring_rubric_metrics`) exported; external paid LLM status is `not_run` | Empirical reductions in overclaim, underclaim, and hollow-neutrality rates across live models have **not yet been measured** on a held-out blind benchmark |
| **Deterministic Cross-Reference Gates vs. Empirical Scientific Truth**<br>(Intrinsic Architectural Boundary) | Engine verifies SHA-256 hashes, claim-linked unique quotes, progressive design/stat checks, evidenced `pass` records, and explicit `kind` contradictions | **Deterministic cross-reference gates are not proof of empirical truth**: they block lazy and manipulative form-filling (unbacked `pass`, `"ok"` reasons, `N/A` bypasses, unlinked quotes, explicit design-kind contradictions), but cannot independently detect fabricated raw files without external execution provenance (`record-exec` / `reproducible-science`) or replace domain peer review |

---

## License & Repository

- **License**: [Apache-2.0 License](LICENSE)
- **Repository**: [https://github.com/HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
