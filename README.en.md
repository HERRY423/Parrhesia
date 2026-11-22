# Parrhesia

**Let evidence determine claim strength, and adjudication end hollow neutrality.**

**Language / 语言**: **[简体中文](README.md)** · English

**Release**: [v0.4.0](https://github.com/HERRY423/Parrhesia/releases/tag/v0.4.0) ([Changelog](CHANGELOG.md)) · **Runtime**: Python 3.11+ stdlib only (zero third-party deps) · **Surface**: 28 MCP tools / 5 wire-budget profiles · **CI**: [Windows & Ubuntu (v0.4.0)](https://github.com/HERRY423/Parrhesia/actions/runs/44977579853) · **License**: [Apache-2.0](LICENSE)

**Parrhesia** is a local evidence-calibration and dual-review adjudication plugin conforming to the [Agent Plugins 1.0.0](https://agent-plugins.org/) specification, with a single-source cross-platform `AGENTS.md` policy system. Its design separates cognitive roles for independent review and uses a **deterministic local state machine with zero third-party dependencies (Python 3.11+ standard library only)** to address overclaiming, excessive disclaimers, and hollow neutrality in scientific analysis, engineering evaluation, and technical decisions. Independent review requires host-isolated contexts or the built-in OS subprocess sandbox runner; deterministic gates verify traceability, statistical consistency, and dual-review closure rather than replacing domain peer review, and net behavioral gains on live LLMs remain to be measured under the [evaluation plan](docs/evaluation-plan.md).

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

## What Makes Parrhesia v0.4.0 Different

Prompt-only self-reflection still asks the same model inside the same context window to draft, praise, criticize, and conclude all at once. Generic linters and literature plugins cannot compute statistical self-consistency or catch recycled cohorts across papers. **Parrhesia `v0.4.0` turns blind review isolation, symmetric adjudication, computable methodology, and longitudinal synthesis into deterministic, zero-dependency engineering gates:**

1. **True Two-Stage `estimate_first` Blind Review + OS Subprocess Sandbox**
   - `review_packet(stage="evidence_only")` strips `question`, `draft`, `hypotheses`, author claim prose/classifications, and `claim_direction`, binding a stage-specific `packet_nonce` that cannot be replayed into `submit_review`.
   - CLI `parrhesia run-isolated` / `run-dual-review --two-stage-blind` commits and verifies `stage1_locked_estimates` (`stage1_estimate_sha256`) inside an isolated sandbox before revealing full packets in a second sandbox. It scrubs sensitive env vars (`LD_PRELOAD`/`PYTHONPATH`/etc.), redirects `APPDATA`/`XDG_*`, supports `--offline-env` and `--sandbox-mode strict_os` (Linux `bwrap` / macOS `sandbox-exec`, failing explicitly with `sandbox_unavailable` rather than silently downgrading), checks `.parrhesia` snapshot integrity (`sandbox_boundary_violation`), seals HMAC `runner_seal`, and discloses `isolation_grade.boundaries`.
2. **Bidirectional Symmetric Enforcement (`symmetry_mode="enforced"`)**
   - One-sided anti-hype checks often push models into defensive boilerplate (“further studies are needed, for reference only”). Parrhesia v2 enforces bidirectional balance by default: blocking overclaiming, unsupported `pass` labels (`uncited_check_evidence`), and failing primary endpoints (`primary_effect_crosses_null` / `primary_effect_fails_multiplicity`), while also rejecting `unjustified_downgrade`/`abstention`, `unjustified_overhedging`, `false_balance_neutrality`, and vacuous bare-term reversals—requiring `abstention_justification`, `actionable_stance`, and observable reversal conditions.
3. **11-Mode Proactive Computable Methodology Co-Pilot (Pure Stdlib)**
   - Built-in deterministic diagnostics in pure Python standard library covering **power / MDE (`power`)**, **TOST equivalence**, **E-value confounding sensitivity**, **cluster design effect (`design_effect`)**, **multiplicity with exploratory-fork inflation (`multiplicity_audit`)**, **Gelman-Stern interaction contrast & DerSimonian-Laird random-effects pooling (`interaction_heterogeneity`)**, **EPV shrinkage & Vickers Decision-Curve Net Benefit (`prediction_utility_audit`)**, **Manski worst/best-case & tipping-point attrition bounds (`attrition_bounds`)**, **evidence dominance**, **full-case audit (`case_audit`)**, and **cross-case synthesis (`lineage_synthesis`)**—proactively surfaced in `explore`, `upsert_claim`, and blind packets.
4. **Longitudinal Claim Graph & 3-Layer Semantic Cohort Deduplication (`parrhesia synthesize`)**
   - Connects follow-up studies via an append-only DAG (`claim_graph`), **5 executable `reversal_triggers`**, and source-bound **post-hoc probability calibration** (`Brier` / `Log` / `ECE` / `MCE`).
   - Cross-case synthesis runs **3-layer semantic cohort deduplication**: Layer 1 tracks `derived_from_evidence_ids` ancestor snapshot SHA-256s, canonical `cohort_id`s, and standardized `NCT`/`GSE`/`phs`/DOI IDs (while legitimately allowing multi-cohort papers with distinct explicit `cohort_id`s); Layer 2 screens identical `n ≥ 20` effect clones and high text 3-gram Jaccard (`≥ 0.65`) overlap as `suspected_cohort_overlaps`, preventing recycled cohorts from passing as `replicated_consistent` and exporting offline HTML reports with static SVG forest plots.
5. **Zero Dependencies, Budgeted Wire Schemas & Multi-Host Parity**
   - Requires only **Python 3.11+ stdlib** for the full MCP server, SQLite event SHA-256 hash chain, read-only multi-format manuscript/artifact ingestion (Markdown / LaTeX / DOCX / Quarto / HTML / JATS XML / PDF / `.ipynb` / `.xlsx` / `.parquet`), and offline HTML reports. **28 typed MCP tools** use `$defs`/`$ref` + `sha256` compaction across **5 wire-budget profiles** (`full` 81,519 B down to `review` 10,892 B), generated from a single policy source for Codex, Claude Code, Grok Build CLI, Antigravity, and ChatGPT Web.

### At a Glance: Why Not Just Another Prompt or Linter?

| Dimension | Generic Prompts / Single-Chat Review | Ordinary Linters / Literature Helpers | Parrhesia `v0.4.0` |
| :--- | :--- | :--- | :--- |
| **Review isolation** | Single shared context; anchored by framing | No cognitive role split | Role decoupling + `evidence_only` 2-stage `estimate_first` + OS subprocess sandbox & HMAC `runner_seal` |
| **Anti-hype vs. anti-hedge** | Fighting hype spawns boilerplate hedging | Shallow keyword warnings only | `symmetry_mode="enforced"` blocks both overclaiming and unjustified downgrades / false balance |
| **Methodology & statistics** | Mental math or ad-hoc brittle scripts | No study-design or effect checks | 11 stdlib diagnostic modes + `wald`/`student_t`/2×2 Fisher/GRIM/Holm-BH/primary endpoint gates |
| **Anchoring & anti-stall** | Vague citations and nominal edits | Regex format checks only | File SHA-256 + unique claim-linked `quote` + `revised_text_quote` substitution check + 4-role windowing |
| **Cross-study lineage & dedup** | Starts over each chat; recycled cohorts double-counted | Abstract lookup only | `claim_graph` + 3-layer cohort deduplication + executable `reversal_triggers` + outcome calibration |
| **Deployment & hosts** | Copy-pasted prose; non-reproducible | Platform-locked or heavy deps | Zero third-party deps (Python 3.11+ stdlib) · SQLite hash chain · 5 host integrations · works offline |

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

Rules load on demand: the main [skill](skills/parrhesia-review/SKILL.md) routes tasks to the [L2 scientific reference](skills/parrhesia-l2-reference/SKILL.md), [tool workflow](skills/parrhesia-review/references/workflow.md), or [optional integrations](skills/parrhesia-review/references/integrations.md). Project entrypoints no longer embed external plugin script names or provider-specific billing paths. All policy materials remain generated from one source.

The contract supports the same approach: call `parrhesia_contract(section="index")`, then request relevant section IDs. Excerpts include original line ranges and a document digest; `expected_sha256` prevents mixing revisions. Calls without arguments retain the full-document response.

The local MCP server and CLI require only **Python 3.11+**, with **zero third-party dependencies** and no external packages to install with `pip`. For offline installation, prebuilt packages (`parrhesia_review-0.4.0-py3-none-any.whl`, `parrhesia-0.4.0.zip`, and `SHA256SUMS.txt`) are attached to [GitHub Releases (`v0.4.0`)](https://github.com/HERRY423/Parrhesia/releases/tag/v0.4.0).

### Option 1: Codex plugin marketplace (GUI / CLI)

#### 1. “Add plugin marketplace” in the GUI (recommended)

In the Codex desktop plugin management page, choose **Add plugin marketplace** (from a GitHub repository, Git URL, or local folder):

| Field | Value | Notes |
| :--- | :--- | :--- |
| **Source** | `HERRY423/Parrhesia`<br>*(or `https://github.com/HERRY423/Parrhesia.git`)* | For an offline package or local clone, select the repository root containing `.agents/plugins/marketplace.json`, such as `C:\Parrhesia` |
| **Git ref** | `v0.4.0` *(or `main`)* | Pin `v0.4.0` for the current release, or use `main` for latest updates |
| **Sparse path** | **Leave blank** | The plugin manifest is at the root; do **not** copy the placeholder `plugins/codex` |

Click **Add marketplace**, then select **Parrhesia Marketplace** and install **Parrhesia**.

#### 2. Codex CLI installation

```powershell
# Add the GitHub marketplace and install the plugin (or use --ref main for latest commits)
codex plugin marketplace add HERRY423/Parrhesia --ref v0.4.0
codex plugin add parrhesia@parrhesia-marketplace

# Optional: add a local clone
codex plugin marketplace add C:\Parrhesia
```

> Codex uses bare `python` in `.codex-plugin/plugin.json`, so **Python 3.11+** must resolve on `PATH`; Claude Code supports configurable `userConfig.python` in `/config` via `.claude-plugin/plugin.json`.

#### 3. Sync Codex compact rules and complete layered skills

Codex uses a **resident compact policy block (`< 10 KiB`) + `parrhesia-review` navigation and on-demand references + L2 scientific reference + role packets**. The script installs both complete skill directories, including the entry skill's three reference files:

```powershell
# Sync ~/.codex/AGENTS.md and both parrhesia-review and parrhesia-l2-reference under skills/
python scripts/install-codex.py

# Read-only consistency check against the repository policy source
python scripts/install-codex.py --check
```

Updates preflight the complete source bundle, back up original bytes and roll back on failure. An unchanged repeat leaves files untouched; `--check` checks every reference. This script does not register an MCP server; see [distribution and acceptance](docs/distribution.md).

---

### Option 2: Claude Code marketplace and Agent Plugins 1.0.0 clients

#### 1. Claude Code CLI installation

```bash
claude plugin marketplace add HERRY423/Parrhesia
claude plugin install parrhesia@parrhesia-marketplace
```

The Claude-specific `.claude-plugin/plugin.json` now declares the MCP server inline, using `${CLAUDE_PLUGIN_ROOT}` for the launcher and `${CLAUDE_PLUGIN_DATA}/workspace` for the default persistent ledger, independently of the generic `mcp.json` variables. Use a recent Claude Code version supporting `userConfig` and these variables. Set the plugin's `python` option in `/config` to a working Python **3.11+** interpreter (default: `python`; use `python3` on Linux/macOS when needed, or an absolute executable path). If set, `PARRHESIA_WORKSPACE` must be an existing absolute directory and overrides the default. Back up ledgers before uninstalling: Claude may delete plugin data on uninstall.

Users with the old manifest must update the plugin and restart the session, verify that the cached manifest contains `mcpServers`, and confirm Parrhesia is connected in `/mcp`; installation alone does not establish server availability. This repair passed Claude Code 2.1.325 strict manifest validation and independent MCP subprocess checks; **real Claude Code session workflow acceptance is still pending**. [Official Claude manifest and variable reference](https://code.claude.com/docs/en/plugins-reference)

#### 2. Standard Agent Plugins 1.0.0 clients

Compatible hosts can load `plugin.json`, `mcp.json`, and `skills/` at the repository root, discovering **28 local tools**, read-only resources, and role prompts through stdio MCP (with optional `--tool-profile full|compact|explore|review|adjudication` scoping):

- **24 typed action tools (`parrhesia_<action>`)**: `create_case`, `register_evidence`, `register_hypothesis`, `scaffold_claim`, `draft_manuscript`, `import_artifact`, `extract_effects`, `set_ledger`, `upsert_claim`, `explore`, `analyze_design`, `freeze`, `review_packet`, `submit_review`, `adjudication_packet`, `submit_adjudication`, `verify`, `get_case`, `export`, `record_human_decision`, `claim_graph`, `evaluate_triggers`, `record_calibration_outcome`, and `calibration_report`, each with JSON Schema and permission annotations.
- **`parrhesia_validate`**: read-only preflight in a SQLite transaction with automatic `ROLLBACK`; supports `collect_all=true` to return per-item issues, structured `repair_hint` guidance, and `ceiling_diffs`.
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

## Core features and architecture: four pillars in `0.4.0`

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
  - **Interval–p, 2×2 contingency, multiplicity, and subgroup interaction checks**: check estimate/CI/p-value compatibility for matching two-sided unadjusted `wald`, `log_wald`, or `df`-bound `student_t` (without CI on directional primary records, `supported` rejects nonsignificant `p_value >= alpha`); verify 2×2 `contingency` tables (Fisher exact p and OR/RR/RD), `bonferroni` / `holm` / `bh_fdr` multiplicity adjustments, and `independent` subgroup `interaction_contrast` tests while leaving undeclared preconditions `unassessed`.
  - **GRIM and integer-denominator granularity**: proportion/accuracy records declaring `count_basis="unweighted_binary"` are checked using source decimal precision when anchored for integer feasibility of sample size n, event counts, and decimals.
  - **Primary null/margin/multiplicity gating and secondary separation**: directional or margin-bound `primary` / `benchmark` claims whose intervals cross null/margin (`primary_effect_crosses_null`) or fail declared adjusted alpha (`primary_effect_fails_multiplicity`) are blocked from positive verdicts; supported primary benefit can coexist with nonsignificant secondary or safety endpoints.
- **Proactive computable methodology co-pilot (`explore` / `upsert_claim` / `analyze_design` / `copilot`)**: persistent `L1-Explore` hypothesis tree and exploratory fork accounting (`explore` with kill criteria and `lock_plan` promotion to L2), compact single-claim compiler (`upsert_claim` returning `ceiling_diff`), and **11 pure-stdlib deterministic diagnostic modes** (`power`, `tost_equivalence`, `e_value`, `design_effect`, `evidence_dominance`, `multiplicity_audit` with exploratory fork inflation, `interaction_heterogeneity` for Gelman-Stern contrasts & DerSimonian-Laird meta-analysis, `prediction_utility_audit` with EPV shrinkage & Vickers Decision-Curve Net Benefit, `attrition_bounds` Manski bounds & tipping-point rates, read-only `case_audit`, and cross-case `lineage_synthesis`), surfaced proactively in `upsert_claim`, `explore`, and blind packets.
- **Manuscript scaffolding and artifact ingestion (`draft_manuscript` / `import_artifact` / `extract_effects`)**: extract location-anchored unknown claim skeletons and mixed-claim decomposition flags (`split_recommended`) in pure stdlib from Markdown / LaTeX (bounded workspace `\input`/`\include`) / DOCX / Quarto / PDF (pure-stdlib bounds by default; opt-in `pdf_backend="auto"` enables local read-only PyMuPDF/`pypdf` fallback and transparently reports `parser_backend`) / HTML / JATS XML / `.ipynb` narratives; inspect notebooks (including `out_of_order_execution`), `.rmd`/`.qmd`, multi-sheet `.xlsx`, `.parquet` footer metadata, workflows, containers/DVC (with local regular-file digest checks), HPC logs, 2×2 `contingency_json`, confusion matrices, and statistical tables (with `sheet_name` and `assumed_reported_scale`) without executing documents or inventing outcomes (see [workflow, formats, and boundaries](docs/artifact-ingestion.md)).

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
        Markdown report (export) / SQLite hash chain / read-only saved-case HTML (report)
```

The kernel rejects submissions that use unsupported `pass` labels, placeholder reasons, unrelated header quotes, or nominal acceptance without actual revision. Rejection does not advance the state machine.

| Gate | Typical evasion | Deterministic check |
| :--- | :--- | :--- |
| **Evidence binding and placeholders** | `pass` without evidence IDs; reasons such as `"ok"`, `"通过"`, `"见上"`, or `"TBD"` | Passing checks require nonempty `evidence_ids` and substantive reasons; positive decisions must cite evidence supporting required checks (`uncited_check_evidence`) |
| **Evidence kinds and synthetic isolation** | Labeling observational data as `intervention`; using synthetic data for real empirical conclusions | Enforce `kind` compatibility with claim type/level; positive synthetic support is limited to `description × recorded` and `computational × benchmark_measured` |
| **Unique source anchors and claim linkage** | Fabricated quotes or unrelated headers/copyright text | Positive references require a uniquely matching `quote` of at least 6 CJK characters or 12 visible ASCII characters, sharing numbers, substantive terms, or provenance-card locators with the claim (`unlinked_evidence_quote`) |
| **Four-role windows and lineage** | ANSI logs rejected; contradictions at the end of files larger than 128 KiB hidden by truncation; derived tables laundering synthetic ancestors | Strip ANSI controls; unique quotes produce budgeted windows preserving head metadata, primary quote, anchors, and tail summary; `derived_from_evidence_ids` tracks ancestor hashes and synthetic provenance |
| **Substantive incorporation and symmetry gate (`symmetry_mode`)** | Marking `incorporated` while retaining criticized text; unjustified downgrades without counterevidence; vacuous “future studies” deferral | `revised_text_quote` must appear uniquely in revised text, be absent from original, and substantively replace criticized terms; v2 defaults to `symmetry_mode="enforced"` (`"advisory"` optional), blocking `unjustified_overhedging`, `false_balance_neutrality`, `unjustified_underclaim`/`abstention`/`downgrade`, and vacuous bare-term reversals while requiring `abstention_justification`, `actionable_stance`, and `evidence_dominance` (`lexical_advisories` remain non-blocking) |
| **OS-process isolation & two-stage `estimate_first` blind protocol** | Reviewers anchored by author framing, or self-reported isolation inside shared context | `review_packet(..., stage="evidence_only")` strips author claims & `claim_direction`; CLI `parrhesia run-isolated` / `run-dual-review --two-stage-blind` commits `stage1_estimate_sha256` before revealing full packets in a second sandbox, redirects APPDATA/XDG, blocks `LD_PRELOAD`/`PYTHONPATH`, supports `--offline-env` & `--sandbox-mode strict_os` (`bwrap`/`sandbox-exec`, failing `sandbox_unavailable` when absent), detects `.parrhesia` tampering (`sandbox_boundary_violation`), seals HMAC `runner_seal`, and reports `isolation_grade.boundaries` (`enforced`/`not_enforced`) |

---

### Pillar 4: Execution provenance, longitudinal claim graphs, and post-hoc calibration

1. **Command provenance without recording secret environment values, and event integrity (`record-exec` / `events`)**
   - `python -m parrhesia record-exec` captures the command, Git commit/dirty state, lockfile hashes, input/output SHA-256 through `--input-file` / `--output-file`, and environment presence markers rather than secret values.
   - **Failure receipts remain durable**: timeout (wrapper `124`), start failure (wrapper `127`), and nonzero child exits preserve logs, snapshots, and events without overwriting history. Claim/run-group gates detect hidden failed forks (`selective_execution_omission`) and unadjusted selection across forks (`unadjusted_execution_multiplicity`).
   - **SQLite event hash chain & incremental indexes (`PRAGMA user_version = 3`)**: events carry `prev_event_hash` and `event_hash` verified via `event_chain_status` (`verified`, `legacy_unhashed`, `mixed_verified`, `tampered`); `case_summaries`, `case_links`, `evidence_index`, and `stale_cases` triggers let `list_cases`, `claim_graph`, `evaluate_triggers`, and `calibration_report` avoid full-workspace JSON deserialization and unrelated disk rehashing.
2. **Longitudinal claim graph (`claim_graph`) and executable reversal triggers (`reversal_triggers`)**
   - An append-only DAG connects studies through `prior_case_ids`, `supersedes_case_id`, and `prior_claim_links` (`replicates`, `refines`, `narrows`, `extends`, `supersedes`, `reverses`, `refutes`) without modifying frozen prior cases. Draft, frozen, or unadjudicated successor relations remain `pending`; `active_standing` changes only after a valid successor adjudication. Read-only `analyze_design(mode="lineage_synthesis")`, `claim_graph(include_synthesis=true)`, and CLI `parrhesia synthesize` run 3-layer semantic cohort deduplication—Layer 1 excluding same-case, direct/`derived_from_evidence_ids` ancestor SHA-256s, matching `effect_records[].cohort_id`, standardized trial/accession IDs (`NCT`/`GSE`/`phs`), and shared paper DOIs (unless distinct explicit `cohort_id`s are supplied), plus Layer 2 flagging identical `n>=20` effect clones and high text 3-gram Jaccard (`>=0.65`) as `suspected_cohort_overlaps` blocking `replicated_consistent` (`suspected_duplicate_cohort_review_needed`)—alongside cumulative DerSimonian-Laird pooling and ancestor `reversal_triggers` cascades.
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

Render an existing adjudicated case without rerunning the demo or submitting a decision:

```powershell
python -m parrhesia report --workspace C:\YourWorkspace --case-id case_... --output reports/review.html
```

The output is workspace-relative and never overwrites an existing file. The command reads a read-only database snapshot, checks frozen digests and the event chain, and preserves saved verification, unknowns and human decisions. It does not re-verify source files or record human acceptance.

### 2. Core CLI reference

```powershell
# Inspect the runtime version and full JSON contract
python -m parrhesia contract

# Scaffold an all-unknown/not_run v2 claim (optional include_effect_records and check_ceilings preview)
python -m parrhesia call scaffold_claim --workspace C:\YourWorkspace --input docs/examples/claim-v2-unknown.json

# Execute an analysis, capture Git/lockfile/input-output hashes and non-secret environment markers, and create an execution card
python -m parrhesia record-exec --workspace C:\YourWorkspace --case-id <case_id> --claim-id C1 --card-id exec-1 --input-file data/clean.csv --output-file results/metrics.json -- python your_analysis.py

# Run two-stage evidence-only commit -> reveal parallel isolated reviews with offline env and HMAC runner_seal (plus optional adjudication & export)
python -m parrhesia run-dual-review --workspace C:\YourWorkspace --case-id <case_id> --two-stage-blind --offline-env --run-adjudication --auto-export -- python your_isolated_adapter.py

# Generate read-only cross-case Living Evidence Synthesis JSON and offline HTML report (with 3-layer cohort dedup guard & SVG forest plots)
python -m parrhesia synthesize --workspace C:\YourWorkspace --output reports/living-synthesis.html

# Start the local stdio MCP server for a host client (supports --tool-profile explore|compact|review|adjudication)
python -m parrhesia serve --workspace C:\YourWorkspace
```

<details>
<summary><b>🔧 Developer commands: policy generation, Stage 0 evaluations, and packaging</b></summary>

```powershell
# 1. Check or regenerate derived policy files (AGENTS.md, host templates, SKILL.md, ChatGPT templates)
python scripts/generate-policy.py --check
python scripts/generate-policy.py

# 2. This worktree's full mechanical suite includes ingestion; a bounded mode is also available
python -X utf8 scripts/run-stage0-eval.py --mode mechanical --report-out artifacts/stage0-current.md
python -X utf8 scripts/run-stage0-eval.py --mode ingestion
python -X utf8 scripts/run-stage0-eval.py --mode prompt-export --output-dir artifacts/stage0-prompts

# 3. Automated unit tests
python -m unittest discover -s tests -v

# 4. Deterministic distribution ZIP, checking manifest/runtime version consistency
python scripts/build-release.py --output dist/parrhesia-0.4.0.zip
```
</details>

This release also provides targeted counterfactual, held-out, metamorphic and P1/P2 modes; see `--help`. See [evaluation refresh](docs/verification/evaluation-modernization-2026-11-17.md) for measured inputs, ten ingestion regressions and retained gaps. The [author-burden pilot](docs/evaluation/author-impact-pilot.md) provides four-arm preparation and observation tools; live model and author-benefit evaluation remain unrun.

---

## Documentation

- **Core policy and contracts**
  - [0.4.0 Changelog (`CHANGELOG.md`)](CHANGELOG.md) · [Single policy source (`policy/parrhesia-policy.md`)](policy/parrhesia-policy.md) · [Product design (`docs/product-design.md`)](docs/product-design.md) · [Runtime contract (`docs/contract.md`)](docs/contract.md) · [Manuscript and artifact ingestion (`docs/artifact-ingestion.md`)](docs/artifact-ingestion.md)
  - [0.4.0 migration and recovery (`docs/migration-0.4.md`)](docs/migration-0.4.md) · [0.3.0 migration (`docs/migration-0.3.md`)](docs/migration-0.3.md) · [0.2.0 migration (`docs/migration-0.2.md`)](docs/migration-0.2.md) · [Distribution and isolated wheel checks (`docs/distribution.md`)](docs/distribution.md) · [Evaluation plan (`docs/evaluation-plan.md`)](docs/evaluation-plan.md)
- **Host integrations and skills**
  - [L2 review workflow (`skills/parrhesia-review/SKILL.md`)](skills/parrhesia-review/SKILL.md) · [L2 scientific reference (`skills/parrhesia-l2-reference/SKILL.md`)](skills/parrhesia-l2-reference/SKILL.md)
  - [Antigravity](docs/antigravity-integration.md) · [Grok](docs/grok-integration.md) · [ChatGPT](docs/chatgpt-integration.md)
  - [Repository `AGENTS.md`](AGENTS.md) · [Full policy template](templates/AGENTS.parrhesia.md) · [Codex compact template](templates/AGENTS.parrhesia.codex.md) · [ChatGPT template](templates/AGENTS.parrhesia.chatgpt.md)
- **Verification and audits**
  - [2026-11-21 Hardening verification (`docs/verification/hardening-2026-11-21.md`)](docs/verification/hardening-2026-11-21.md) · [0.3.0 desktop acceptance (`docs/verification/release-0.3.0.md`)](docs/verification/release-0.3.0.md) · [0.2.0 verification (`docs/verification/release-0.2.0.md`)](docs/verification/release-0.2.0.md)
  - [Ingestion verification (`docs/verification/artifact-ingestion-2026-11-15.md`)](docs/verification/artifact-ingestion-2026-11-15.md) · [Protocol load verification (`docs/verification/protocol-load-2026-11-16.md`)](docs/verification/protocol-load-2026-11-16.md)
  - [Stage 0](docs/verification/stage0-evaluation.md) · [Anti-stall gates](docs/verification/anti-stall-gates.md) · [Gate-bypass hardening](docs/verification/gate-bypass-hardening-20261019.md)

---

## License and repository

- **License**: [Apache-2.0 License](LICENSE)
- **Releases**: [v0.4.0 Releases](https://github.com/HERRY423/Parrhesia/releases/tag/v0.4.0)
- **Repository**: [https://github.com/HERRY423/Parrhesia](https://github.com/HERRY423/Parrhesia)
