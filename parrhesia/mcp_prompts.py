"""MCP resource, prompt, and error repair-hint definitions. Pure stdlib."""
from __future__ import annotations

from typing import Any


def resource_definitions() -> list[dict[str, str]]:
    """Return concrete static/collection MCP resources."""
    return [
        {
            "uri": "parrhesia://contract",
            "name": "Parrhesia workflow contract",
            "description": "Complete Parrhesia workflow payload and structural gate contract.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "parrhesia://cases",
            "name": "Parrhesia workspace cases",
            "description": "Summary list of all cases stored in the active workspace.",
            "mimeType": "application/json",
        },
        {
            "uri": "parrhesia://claim-graph",
            "name": "Parrhesia longitudinal claim graph",
            "description": "Read-only cross-case claim lineage DAG and active standing across workspace cases.",
            "mimeType": "application/json",
        },
        {
            "uri": "parrhesia://calibration",
            "name": "Parrhesia workspace calibration report",
            "description": "Read-only proper scoring, ECE/MCE reliability bins, interval coverage, and trigger calibration.",
            "mimeType": "application/json",
        },
    ]


def resource_template_definitions() -> list[dict[str, str]]:
    """Return dynamic MCP resource URI templates."""
    return [
        {
            "uriTemplate": "parrhesia://contract/{section}",
            "name": "Contract index or section",
            "description": "Read index first, then a section ID. JSON includes source digest, line range and explicit partial/full status.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases",
            "name": "Workspace case list",
            "description": "Summary list of all cases stored in the active workspace.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://claim-graph",
            "name": "Longitudinal claim graph",
            "description": "Cross-case claim lineage DAG and verdict/standing trajectories.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://calibration",
            "name": "Workspace calibration report",
            "description": "Measurable calibration metrics across adjudicated cases and outcomes.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}",
            "name": "Case audit document",
            "description": "Read-only durable case state, claims, reviews, adjudication, and event chain.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}/ceilings",
            "name": "Case claim check ceilings",
            "description": "Read-only type-local check ceilings and effect_records summary per claim.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}/triggers",
            "name": "Case executable reversal triggers",
            "description": "Read-only evaluation of a case's structured reversal triggers against live workspace state.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}/packet/{role}",
            "name": "Isolated role packet",
            "description": "Read-only isolated packet for role in overclaim, underclaim, or adjudication.",
            "mimeType": "application/json",
        },
    ]


def prompt_definitions() -> list[dict[str, Any]]:
    """Return MCP prompt definitions for isolated review and adjudication roles."""
    case_arg = {
        "name": "case_id",
        "description": "Optional frozen/reviewed case ID to inject the live isolated role packet.",
        "required": False,
    }
    return [
        {
            "name": "parrhesia_review_overclaim",
            "description": "Overclaim reviewer instructions and optional live isolated overclaim packet.",
            "arguments": [case_arg],
        },
        {
            "name": "parrhesia_review_underclaim",
            "description": "Underclaim reviewer instructions and optional live isolated underclaim packet.",
            "arguments": [case_arg],
        },
        {
            "name": "parrhesia_adjudicate",
            "description": "Adjudicator instructions and optional live adjudication packet (requires built packet).",
            "arguments": [case_arg],
        },
    ]


_REPAIR_HINTS: dict[str, str] = {
    "kind_upgrade_forbidden": "Use kind='auto' or retain the source-derived kind. A command receipt or table cannot establish intervention/external validation; supply separate study-design evidence.",
    "unbound_execution": "Use an execution_evidence_id from this case whose completed successful record-exec run created/modified this exact declared output. Unchanged, failed or historical artifacts may be imported without execution binding.",
    "source_changed": "Preserve the changed source as a new version and import it again; do not alter frozen snapshots or claim the old hash still applies.",
    "ambiguous_source": "Supply the sheet_name used by extract_effects when prefilling rows from a multi-sheet XLSX.",
    "ambiguous_columns": "Supply column_map mapping each effect field to one exact source header; do not guess between multiple estimates or p-value columns.",
    "unsupported_format": "Use a documented manuscript/artifact format or export a UTF-8 table; unsupported content is not considered read or verified.",
    "invalid_state": (
        "Check the case's current state via parrhesia_get_case or parrhesia://cases/{case_id}. "
        "Draft edits require state='draft' (create a new case via parrhesia_create_case if already frozen); "
        "adjudication requires state='reviewed' (both overclaim and underclaim reviews submitted); "
        "export requires state='adjudicated' or 'export_pending'."
    ),
    "missing_field": (
        "Add every missing required field listed in the error message. Call parrhesia_scaffold_claim for a full v2 claim template, "
        "or inspect this tool's inputSchema / parrhesia_contract."
    ),
    "unknown_field": (
        "Remove the unsupported fields named in the error message; inspect this tool's inputSchema or parrhesia_contract for exact allowed keys."
    ),
    "invalid_type": (
        "Fix the field data type reported in the error message (for numeric effect_records fields, pass JSON numbers rather than strings or booleans)."
    ),
    "invalid_value": (
        "Replace the rejected value with a non-empty string or an allowed enum value defined in this tool's inputSchema / parrhesia_contract."
    ),
    "invalid_json": "Ensure the JSON payload contains only finite numbers (no NaN or Infinity) and valid JSON values.",
    "too_large": "Shorten oversized fields or register large artifacts as separate files within documented size limits.",
    "duplicate_id": (
        "Ensure all IDs in the submitted array (claim.id, finding.id, provenance card id, effect_record.id, or design_packages.family) are unique."
    ),
    "invalid_request": (
        "Check tool arguments against its inputSchema: parrhesia_contract accepts optional section and expected_sha256, "
        "parrhesia_select_workspace requires an existing absolute directory 'path', and action tools require valid typed fields."
    ),
    "invalid_workspace": "Pass an existing absolute directory path in parrhesia_select_workspace.",
    "unknown_contract_section": "Read parrhesia_contract(section='index') and use an exact listed ID; do not guess a filename or path.",
    "contract_changed": "Read parrhesia_contract(section='index') again and bind the next excerpt with its selection.source_sha256.",
    "unknown_case": (
        "Verify case_id against parrhesia://cases, switch to the correct project directory via parrhesia_select_workspace, "
        "or create a new case with parrhesia_create_case."
    ),
    "legacy_creation_disabled": "Omit schema_version or set schema_version=2 on parrhesia_create_case; schema_version=1 creation is disabled.",
    "unsupported_contract_version": "Create a new v2 case via parrhesia_create_case; unsupported stored schema/gate versions cannot be upgraded in place.",
    "case_level_blind": "Omit 'blind' when calling parrhesia_review_packet; case blindness is frozen at parrhesia_create_case.",
    "human_paused": (
        "A human 'pause' hold is active. Call parrhesia_record_human_decision with decision='accept', "
        "responsible_human, and reason before performing workflow mutations."
    ),
    "human_hold": (
        "An active human hold ('challenge', 'defer', or 'pause') blocks export. "
        "Record an explicit parrhesia_record_human_decision with decision='accept' before retrying export."
    ),
    "missing_ledger": "Call parrhesia_set_ledger with 1 to 100 schema-valid claims before calling parrhesia_freeze.",
    "missing_packet": "Call parrhesia_adjudication_packet with case_id first to build the packet and obtain adjudication_id and input_digest.",
    "stale_packet": (
        "Re-read the packet via parrhesia_review_packet or parrhesia_adjudication_packet and supply its exact packet_id/adjudication_id and input_digest."
    ),
    "duplicate_review": "Each role ('overclaim' and 'underclaim') can submit only once per case; create a new case to revise.",
    "context_reuse": (
        "Use a distinct reviewer/adjudicator context_id that does not match writer_context_id or the other reviewer's context_id."
    ),
    "unsafe_path": (
        "Pass a workspace-relative regular file path using forward slashes with no '..', drive letters, symlinks/reparse points, or '.parrhesia' components."
    ),
    "invalid_source": "Point 'path' to an existing regular file inside the workspace (not a directory or symlink).",
    "source_unreadable": "Verify the target file exists and is readable within the workspace.",
    "invalid_quote": (
        "Provide an exact, unique UTF-8 substring from the source file with at least 12 visible non-whitespace units (>= 6 CJK characters)."
    ),
    "conflicting_provenance": "When evidence kind is 'synthetic', set provenance='synthetic'.",
    "unread_ack_required": (
        "Inspect source_text_status for every evidence entry in the packet and include all IDs where source_text_status != 'complete' in unread_evidence_ids "
        "(or set unread_content_ack=true when registering binary files)."
    ),
    "unread_positive_evidence": (
        "Positive citations require readable text or a quote-anchored >128 KiB window; register a unique quote on the text source "
        "or cite a readable verified summary derived via derived_from_evidence_ids."
    ),
    "unanchored_positive_evidence": (
        "Register both a unique verbatim quote (>= 12 visible non-whitespace units) and a concrete non-placeholder location (e.g. 'Table 2, L14-L18') on the cited evidence."
    ),
    "unlinked_evidence_quote": (
        "Register a quote on the cited evidence that shares quantitative figures, domain terminology, or checked provenance-card locators with the claim."
    ),
    "unanchored_effect_estimate": (
        "Ensure the numeric estimates and confidence intervals stated in claim.effect and revised_text appear literally in the cited evidence quote or snapshot window."
    ),
    "unanchored_effect_record": (
        "Verify that every effect_record's estimate (and ci_low, ci_high, p_value, or quote_substring when provided) appears literally in the referenced evidence_id's "
        "registered quote or snapshot text, or register a quote/excerpt_anchors window containing those numbers."
    ),
    "primary_effect_crosses_null": (
        "The primary/benchmark interval includes null and cannot establish the explicitly asserted claim_direction. "
        "Use insufficient_evidence for an unestablished directional claim; a descriptive null result is different from a directional effect or equivalence. Do not change metadata merely to bypass the check."
    ),
    "effect_direction_mismatch": (
        "Align effect_record.direction ('benefit'/'harm') with estimate relative to null_value and beneficial_if ('below_null'/'above_null'), "
        "and any explicitly declared claim_direction. A supported harm proposition is valid; do not relabel harm as benefit."
    ),
    "effect_interval_inconsistent": "Provide both ci_low and ci_high (or omit both) and ensure ci_low <= estimate <= ci_high.",
    "invalid_ratio_effect": "Ratio metrics (HR, OR, RR, IRR) require strictly positive estimate > 0, ci_low > 0, ci_high > 0, and null_value > 0.",
    "effect_pvalue_ci_mismatch": (
        "Check p_value against the explicitly declared matching two-sided CI/test pair, including scale, null, df (for student_t), and rounding. "
        "Use the actual source method; unsupported/unknown methods are recorded as unassessed, never silently verified."
    ),
    "effect_granularity_mismatch": (
        "Verify events, n, scale ('unit' vs 'percentage'), and decimals so estimate matches events/n (multiplied by 100 when scale='percentage')."
    ),
    "effect_grim_inconsistent": (
        "Check estimate, n, scale, and decimals: no integer count k/n reproduces the reported proportion at the specified decimal precision."
    ),
    "effect_contingency_mismatch": (
        "Check raw 2x2 counts against reported OR/RR/risk_diff estimate and zero-cell bounds."
    ),
    "effect_multiplicity_mismatch": (
        "Verify adjusted_p_value >= p_value and ensure declared multiplicity_method (bonferroni/holm/bh_fdr) and family_size match the reported adjustment."
    ),
    "primary_effect_fails_multiplicity": (
        "A primary/benchmark record's adjusted_p_value >= alpha after multiplicity adjustment; use insufficient_evidence or lower certainty rather than 'supported'."
    ),
    "effect_interaction_mismatch": (
        "Verify subgroup interaction_contrast record_ids, metric compatibility, and independent-SE interaction estimate/CI/p calculation."
    ),
    "uncited_primary_effect": (
        "Include the evidence_id(s) backing the supporting primary/benchmark effect_records inside decision.evidence_ids."
    ),
    "selective_execution_omission": (
        "Account for every SQLite record_exec run for this case/claim inside claim.provenance_cards.execution with its registered evidence_id, "
        "exit_status, and fork_role rather than omitting runs or leaving cards as 'not_run'."
    ),
    "unadjusted_execution_multiplicity": (
        "Multiple execution forks exist; set statistical_report.multiplicity_selection and checks.multiplicity to 'pass' with substantive reasons "
        "and cite their backing evidence_ids in the positive decision."
    ),
    "critical_check_ceiling": (
        "Read parrhesia://cases/{case_id}/ceilings to inspect blocked levels. Either downgrade evidence_level/verdict to an allowed level, "
        "or supply evidenced passing design/statistical checks and valid provenance_cards in a new case."
    ),
    "uncited_check_evidence": (
        "Add all evidence_ids cited by required passing design_packages and statistical_report checks into decision.evidence_ids (or stance.evidence_ids)."
    ),
    "uncited_checked_card": (
        "Add the evidence_ids from every provenance card with status='checked' into decision.evidence_ids (or stance.evidence_ids)."
    ),
    "missing_card_evidence": (
        "Supply at least one registered evidence_id on every provenance card marked status='checked', or change its status to 'reported' or 'unknown'."
    ),
    "missing_causal_basis": (
        "Include a complete causal_basis record (design_family, estimand, assumptions, falsification_sensitivity, assessment, necessity_test, sufficiency_test) "
        "for causal_effect, necessity, sufficiency, or mechanism x causal_chain_tested claims."
    ),
    "missing_design": "Ensure causal_basis.design_family matches one of the families registered in claim.design_packages.",
    "causal_identification_gap": (
        "For positive causal verdicts, fill concrete non-placeholder estimand fields and set causal_basis assessment, assumptions, required falsification_sensitivity, "
        "and matching necessity/sufficiency tests to 'pass' with substantive reasons and cited evidence_ids."
    ),
    "missing_causal_citation": "Include every evidence_id referenced by causal_basis assessments in decision.evidence_ids (or stance.evidence_ids).",
    "unsupported_evidence_level": (
        "Levels 'unassessed', 'unidentified', and 'conjectured' cannot receive 'supported' or 'partially_supported'; record 'insufficient_evidence' or 'unsupported'."
    ),
    "basis_mismatch": (
        "Reserve claim_basis='formal' exclusively for claim_type='theory', and limit positive claim_basis='synthetic' claims to description or computational."
    ),
    "basis_revision_required": "When changing claim_basis in a positive decision, update both revised_text and scope to reflect the new basis.",
    "synthetic_empirical_support": (
        "Evidence with provenance='synthetic' or kind='synthetic' (including derived ancestors) cannot support empirical/formal positives; "
        "cite non-synthetic evidence or reclassify within synthetic bounds."
    ),
    "synthetic_ceiling": "Positive synthetic decisions are capped at description x recorded or computational x benchmark_measured.",
    "incompatible_evidence_kind": (
        "Cite evidence whose registered kind supports the chosen claim_type x evidence_level (observational evidence supports causal_effect only via "
        "partially_supported with an explicit condition, complete causal_basis, and passing observational checks)."
    ),
    "invalid_lineage": "Remove circular derived_from_evidence_ids links so evidence derivation forms an acyclic DAG.",
    "unknown_reference": "Reference only registered evidence_ids belonging to this case (and to the specific claim when required).",
    "unknown_evidence": "Register the referenced source via parrhesia_register_evidence before linking it.",
    "unknown_hypothesis": "Register the hypothesis via parrhesia_register_hypothesis before linking its hypothesis_id in set_ledger.",
    "unknown_claim": "Reference only claim IDs defined in the frozen ledger (inspect parrhesia://cases/{case_id}).",
    "unknown_finding": "Reference only finding IDs submitted by the overclaim/underclaim reviews.",
    "missing_timing_source": (
        "Register the protocol/preregistration source via parrhesia_register_evidence, register a reported_prespecified hypothesis citing it, "
        "and link that hypothesis_id on the prespecified claim."
    ),
    "conflicting_origin": "An exploratory claim cannot link to a reported_prespecified hypothesis; either mark origin='prespecified' or register an exploratory hypothesis.",
    "incomplete_coverage": "List every frozen claim ID exactly once in covered_claim_ids.",
    "incomplete_stances": "Provide exactly one claim_stances entry for every frozen claim ID.",
    "missing_stance_condition": "Provide a concrete, non-placeholder 'condition' whenever stance='partially_supported', and avoid placeholder or generic future-study deferral condition text.",
    "incomplete_decisions": "Provide exactly one decision entry for every frozen claim ID.",
    "incomplete_dispositions": "Provide exactly one disposition entry for every finding submitted across both reviews.",
    "invalid_condition": "Supply a concrete scope or assumption 'condition' whenever verdict='partially_supported' or disposition='partial'; placeholders, trivial labels, and generic future-study deferrals are rejected.",
    "invalid_rationale": (
        "Supply a concrete evidence- or check-grounded 'rationale' (or disposition 'reason'); placeholders, trivial labels, "
        "and generic future-study deferrals (such as '未来有更多研究时，再重新评估' or 'more research needed') are rejected."
    ),
    "invalid_reversal_condition": (
        "State a concrete observable 'reversal_condition' specifying what outcome, metric/threshold (e.g. HR >= 1.0, CI crossing null, AUROC drop), "
        "direction reversal, check status change, or specific evidence event would change or narrow the judgment. Generic deferrals such as "
        "'未来有更多研究时，再重新评估' or 're-evaluate when more studies are available' are rejected."
    ),
    "finding_decision_mismatch": "Set disposition.claim_id to match finding.claim_id and the corresponding decision.claim_id.",
    "missing_disagreement": "Provide a substantive non-empty 'disagreement' explanation when resolution='disagreement'.",
    "contradictory_resolution": (
        "Use resolution='disagreement' with 'disagreement' (and no revised_text_quote) when rejecting or declining a finding; "
        "omit 'disagreement' when resolution='incorporated'."
    ),
    "finding_not_incorporated": (
        "For resolution='incorporated', revise decision.revised_text to adopt the finding's issue-linked replacement terms and quote a unique >=12-unit substring "
        "present in both proposed_text and revised_text (not original.text), or switch to resolution='disagreement' with explicit explanation."
    ),
    "export_exists": "Choose a new workspace-relative .md path that does not already exist; parrhesia_export never overwrites files.",
    "export_pending": "Retry parrhesia_export using the exact relative path already recorded for the pending export.",
    "invalid_export_path": "Supply a workspace-relative export path ending with '.md' outside '.parrhesia'.",
    "export_failed": "Retry parrhesia_export with the same path once filesystem permissions/availability are restored.",
    "export_verification_changed": "Restore the source files matching the pending export's verification snapshot before retrying parrhesia_export.",
    "verification_mismatch": (
        "Run parrhesia_verify to inspect snapshot/file/anchor/event_chain mismatches; resolve tampered or modified sources before exporting."
    ),
    "unverified_support": (
        "Run parrhesia_verify: every evidence_id cited by a supported or partially_supported decision must have verification status='pass'."
    ),
    "frozen_integrity_error": "The frozen case document no longer matches input_digest; do not modify .parrhesia/state.sqlite3 directly.",
    "review_integrity_error": "Stored review content no longer matches its recorded digest; inspect state integrity via parrhesia_verify.",
    "adjudication_integrity_error": "Stored adjudication content no longer matches its recorded digest; inspect state integrity via parrhesia_verify.",
    "snapshot_mismatch": "Stored evidence snapshot bytes do not match the registered sha256; inspect integrity via parrhesia_verify.",
    "artifact_mismatch": "Prepared export bytes do not match the recorded export digest; inspect integrity via parrhesia_verify.",
    "unlinked_prior_case": (
        "Add every prior_case_id referenced in claim.prior_claim_links to case.prior_case_ids when creating the follow-up case "
        "via parrhesia_create_case."
    ),
    "unknown_prior_claim": (
        "Ensure prior_claim_id (or follow_up_claim_id) exists inside the target prior_case_id / follow_up_case_id; inspect the prior case via parrhesia_get_case."
    ),
    "unknown_reversal_trigger": (
        "Reference an actual trigger ID defined in the prior claim's or prior decision's reversal_triggers when setting triggered_reversal_id."
    ),
    "self_triggering_reversal_condition": (
        "One or more reversal_triggers already fired on the frozen evidence, effect_records, or checks in conflict with the decision. "
        "Update the verdict/evidence_level to match the trigger's target_verdict/target_evidence_level (or withdraw the contradicted positive claim)."
    ),
    "contradictory_claim_lineage_transition": (
        "A claim declaring relation='reverses' or 'refutes' cannot adjudicate the exact same 'supported' wording, scope, and classification as the prior claim. "
        "Revise the claim text/scope/verdict to reflect the actual reversal or refutation."
    ),
    "untriggered_reversal_link": (
        "When linking via triggered_reversal_id, the referenced prior trigger must actually fire on the follow-up claim's data or verdict. "
        "Preflight with parrhesia_evaluate_triggers or remove triggered_reversal_id if the trigger did not fire."
    ),
    "invalid_calibration_outcome": (
        "Use the score implied by the outcome label: 1 for replicated, 0 for refuted, strictly between 0 and 1 for partially_replicated, and null for inconclusive. "
        "Include follow_up_case_id when resolution_source='follow_up_case', "
        "and supply observed_ci_low <= observed_estimate <= observed_ci_high when providing observed CIs."
    ),
    "unjustified_overhedging": (
        "Remove generic boilerplate disclaimers (such as 'for reference only' / 'cannot draw definitive conclusions') from decisions with anchored quantitative evidence and zero failed checks, "
        "and state the evidenced conclusion with scoped limits."
    ),
    "unjustified_underclaim": (
        "Primary evidence supports the proposition without failed checks or counterevidence. Either restore the evidenced verdict/level, or provide a concrete `abstention_justification` "
        "(blocking_gaps + reason + optional counterevidence_ids) identifying a specific unmodeled flaw."
    ),
    "unjustified_abstention": (
        "Claim clears all mechanical and check gates without counterevidence. Either adjudicate the evidenced scope/level clearly, or supply a concrete `abstention_justification` "
        "(blocking_gaps + reason) naming the exact missing empirical check or unmodeled confounder."
    ),
    "unjustified_downgrade": (
        "Claim was downgraded without failed checks or accepted overclaim findings. Either retain the supported level/verdict, or supply a concrete `abstention_justification` "
        "(blocking_gaps + reason) stating the specific unmodeled scope boundary."
    ),
    "false_balance_neutrality": (
        "Ground any claim of equal support in evidence for the same tested question. State the calibrated judgment and observable reversal condition, and retain specific limits on untested outcomes."
    ),
    "invalid_abstention_justification": (
        "Provide concrete, non-boilerplate `blocking_gaps` (naming specific unmodeled confounders, flaws, or missing empirical tests) and a grounded `reason`."
    ),
    "invalid_isolation_receipt": (
        "Ensure `isolation_receipt.packet_nonce`, `packet_sha256`, Stage 1 hashes (when `two_stage_blind=true`), and `runner_seal` match the frozen Stage 2 packet and workspace key."
    ),
    "invalid_stage1_estimates": (
        "Stage 1 output must be JSON with `protocol='estimate_first_stage1_v1'` and valid `claims` (`claim_type`, `evidence_level`, `direction`, `rationale`) before Stage 2 reveal."
    ),
    "incomplete_stage1_estimates": (
        "Stage 1 locked estimates must cover every frozen dossier claim ID before Stage 2 author wording is revealed."
    ),
    "sandbox_boundary_violation": (
        "An isolated child process modified `.parrhesia` workspace state or read-only staged files; submission was blocked without sealing."
    ),
    "sandbox_unavailable": (
        "`sandbox_mode='strict_os'` requires `bwrap` (Linux) or `sandbox-exec` (macOS); omit or use `'standard'` where OS kernel sandboxing is absent."
    ),
    "unknown_exploration": (
        "Verify explore_id via `parrhesia_explore(op='list')` or start a new L1-Explore session via `parrhesia_explore(op='init', question=...)`."
    ),
}


def repair_hint_for(code: str, message: str = "", *, action: str | None = None) -> str:
    """Return an actionable repair instruction for a ContractError or argument error."""
    base = _REPAIR_HINTS.get(code)
    if base:
        if action and code in ("missing_field", "unknown_field", "invalid_value", "invalid_type"):
            return f"[{action}] {base}"
        return base
    suffix = f" for action '{action}'" if action else ""
    detail = f" ({message})" if message else ""
    return f"Review the input schema and workflow contract{suffix} and correct the rejected value{detail}."
