# Parrhesia

**Proportion claim strength to evidence. End hollow neutrality through explicit adjudication.**

**Language / 语言**：**[简体中文](README.md)** · English

Parrhesia is a local, zero-dependency evidence-calibration and dual-review adjudication plugin conforming to the [Agent Plugins 1.0.0](https://agent-plugins.org/) specification, paired with a single-source-of-truth cross-platform `AGENTS.md` policy system. The current release is **`0.2.0` pilot** (new cases enforce `schema_version=2` and anti-rubber-stamping mechanical gates `gate_version=1`, while preserving read/recovery compatibility for stored legacy records).

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

To avoid bloating every conversation with a 41 KB policy file, Codex uses a **compact resident policy block (`~5.4 KB`) + on-demand `parrhesia-l2-reference` skill + isolated role packets**:

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

Any host supporting Agent Plugins 1.0.0 discovers `plugin.json`, `mcp.json`, and `skills/` at the repository root and exposes 3 local stdio MCP tools:
- `parrhesia_contract`: Read the active workspace and full runtime contract specification.
- `parrhesia_select_workspace`: Explicitly switch to an existing user-authorized workspace directory.
- `parrhesia_workflow`: Dispatch all 14 lifecycle actions (`create_case`, `register_evidence`, `log_hypothesis`, `scaffold_claim`, `set_ledger`, `freeze`, `review_packet`, `submit_review`, `adjudication_packet`, `submit_adjudication`, `human_decision`, `verify`, `export`, `get_case`).

---

### Method 3: Grok Build CLI Project Adapter

For Grok Build CLI (`grok 1.0.48+`), an idempotent installer backs up existing files and merges the project `.mcp.json` entry and `AGENTS.md` policy block:

```powershell
# Install into a target project (or run & .\scripts\install-grok.ps1 -Project C:\YourProject)
python scripts/install-grok.py --project C:\YourProject

# Verify tool discovery and MCP handshake
grok --cwd C:\YourProject inspect
grok --cwd C:\YourProject mcp doctor parrhesia --json
```
*See [Grok Integration Guide](docs/grok-integration.md).*

---

### Method 4: ChatGPT Web / Custom GPT Text Protocol (Zero Local Dependencies)

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
2. **Evidence-Bound Substantive `pass` & Decision Citation Verification (`effective_status` & `uncited_check_evidence`)**: Any `pass` in `design_packages`, `statistical_report`, or `causal_basis` must carry non-empty `evidence_ids` and a substantive `reason` (one-word rubber-stamp placeholders like `"ok"`, `"pass"`, `"yes"`, `"done"` are automatically downgraded to `unknown`, locking the ceiling). Positive decisions must cite the `evidence_ids` backing every required passing check (`uncited_check_evidence`).
3. **Evidence-Kind Compatibility & Source Contradiction Detection (`incompatible_evidence_kind` & `contradictory_evidence_kind`)**: Every cited reference must match the `COMPATIBILITY` matrix for `claim_type × evidence_level`; if the snapshot text explicitly describes a weaker contradicting study design (e.g., registering an explicitly non-randomized observational cohort as `kind="intervention"`, or internal cross-validation as `kind="prediction_external"`), positive support is rejected with `contradictory_evidence_kind`.
4. **Synthetic Evidence Isolation (`synthetic_empirical_support`)**: Any evidence with `kind="synthetic"` or `provenance="synthetic"` is blocked from supporting `empirical` or `formal` positive verdicts; synthetic positive scope is restricted to `description × recorded` and `computational × benchmark_measured`.
5. **Unique Quote Anchoring & Claim-Linkage Verification (`unanchored_positive_evidence` & `unlinked_evidence_quote`)**: Every positive reference requires a unique literal `quote` ($\ge 12$ visible non-whitespace characters) and concrete `location`, **and** the quote must share quantitative values, substantive domain terms, or checked-card locators with the claim (`unlinked_evidence_quote` blocks arbitrary unrelated substrings from the source file).
6. **Explicit Unread-Source Acknowledgment (`unread_ack_required`)**: Binary files (PDF/ZIP/PNG), truncated sources ($> 128\text{ KiB}$), or missing files cannot support positive verdicts and must be explicitly listed in `unread_evidence_ids`.
7. **Complete Original-Claim Stances (`incomplete_stances`)**: Reviewers must submit an explicit stance on every frozen claim even when reporting zero findings.
8. **Disposition Incorporation Anchors & Case-Wide Blind Freeze (`finding_not_incorporated` & `case_level_blind`)**: Incorporations must supply a unique $\ge 12$-character `revised_text_quote` present in both `proposed_text` and `revised_text` and absent from the original claim; unincurporated recommendations must record `resolution="disagreement"`. `blind=true` is frozen at case creation, and reports record `reviewer_input_manifests`.

---

## Quick Start & Common Commands

```powershell
# 1. Run the offline end-to-end synthetic demonstration (output directory must not exist yet)
python -m parrhesia demo --output .\artifacts\my-demo

# 2. Scaffold an honest all-unknown v2 claim template and inspect its check_ceilings
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input docs/examples/claim-v2-unknown.json

# 3. Execute a command, capture stdout/stderr + hashes as observed evidence, and emit an execution card
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --card-id exec-1 -- python your_analysis.py

# 4. Verify single-source policy generation, Stage 0 evaluation suite, and all 114 unit tests
python scripts/generate-policy.py --check
python scripts/run-stage0-eval.py --report-out docs/verification/stage0-evaluation.md
python -m unittest discover -s tests -v

# 5. Build the deterministic Agent Plugins 1.0.0 release archive
python scripts/build-release.py --output dist/parrhesia-0.2.0.zip
```

---

## Self-Applied Evidence Boundary (Practicing What We Preach)

| Dimension | Current Classification & Evidence | Supported Claim & Honest Boundary |
| :--- | :--- | :--- |
| **Local State Machine, Mechanical Gates & Release Consistency**<br>(`engineering × test_passed`, **supported**) | 114 automated tests (113 passed, 1 skipped; see [release-0.2.0.md](docs/verification/release-0.2.0.md)); 24 L2 Stage 0 cases + 6 `L1-Explore` cases passing ([stage0-evaluation.md](docs/verification/stage0-evaluation.md)) | Verifies SQLite ACID transactions, level-progressive ceilings, 9-family essential check enforcement, evidence-bound `pass` checks, claim-linked quotes, `kind` contradiction detection, `LEGACY_UNGATED` recovery, and standalone ZIP execution |
| **Multi-Host Sync & Historical Handshake**<br>(`engineering × test_passed`, **supported**; `0.2.0` live orchestration pending) | `install-codex.py --check`, marketplace schema checks, and [ChatGPT kit verification](docs/verification/chatgpt-adapter.md) pass; [Grok 1.0.48 native handshake](docs/verification/grok-native.json) is a historical `0.1.0` record | Proves package structure, manifest schemas, and stdio MCP handshake; does not misrepresent `0.1.0` handshake logs as `0.2.0` end-to-end multi-agent host validation |
| **Net Behavioral Improvement on Live LLMs**<br>(`computational × unassessed`, **insufficient_evidence** / `not_run`) | [Evaluation plan](docs/evaluation-plan.md) frozen and 4-arm prompt packets (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`) exported; external paid LLM status is `not_run` | Empirical reductions in overclaim, underclaim, and hollow-neutrality rates across live models have **not yet been measured** on a held-out blind benchmark |
| **Deterministic Cross-Reference Gates vs. Empirical Scientific Truth**<br>(Intrinsic Architectural Boundary) | Engine verifies SHA-256 hashes, claim-linked unique quotes, progressive design/stat checks, evidenced `pass` records, and explicit `kind` contradictions | **Deterministic cross-reference gates are not proof of empirical truth**: they block lazy and manipulative form-filling (unbacked `pass`, `"ok"` reasons, `N/A` bypasses, unlinked quotes, explicit design-kind contradictions), but cannot independently detect fabricated raw files without external execution provenance (`record-exec` / `reproducible-science`) or replace domain peer review |

---

## License & Repository

- **License**: [Apache-2.0 License](LICENSE)
- **Repository**: [https://github.com/HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
