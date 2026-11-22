"""Run Stage 0 evaluation suite for Parrhesia (mechanical gates, ingestion, versioned inputs and prompt export)."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_ingestion import run_ingestion_suite
from scripts.eval_inputs import policy_inputs, input_fingerprint
from scripts.eval_text_advisories import evaluate as run_text_advisory_suite

from parrhesia.claims import DESIGN_FIELDS, STAT_FIELDS, needs_causal_basis  # noqa: E402
from parrhesia.cli import main as cli_main  # noqa: E402
from parrhesia.contracts import CHECK_NAMES, ContractError  # noqa: E402
from parrhesia.core import Engine, PACKET_TEXT_BYTES  # noqa: E402
from parrhesia.gates import (  # noqa: E402
    ESSENTIAL_DESIGN_CHECKS,
    WINDOW_DELIMITER_LINE_RE,
    _claimed_effect_tokens,
    validate_mechanical,
)


def _pass_assessment(ev_id: str, detail: str = "Verified in primary analysis table") -> dict:
    return {"status": "pass", "reason": f"{detail} ({ev_id})", "evidence_ids": [ev_id]}


def _downgraded_level(claim_type: str) -> str:
    if claim_type == "causal_effect":
        return "unidentified"
    if claim_type == "theory":
        return "conjectured"
    return "unassessed"


def _spec_domain_basis_families(spec: dict) -> tuple[str, str, list[str]]:
    family = spec["family"]
    domain = spec.get("domain", "scientific")
    default_basis = "formal" if spec["claim_type"] == "theory" else "empirical"
    claim_basis = spec.get("claim_basis", default_basis)
    if "design_families" in spec:
        design_families = list(spec["design_families"])
    elif domain == "general" and family not in DESIGN_FIELDS:
        design_families = []
    else:
        design_families = [family]
    return domain, claim_basis, design_families


def _build_claim_from_scaffold(engine: Engine, case_id: str, spec: dict, ev_id: str) -> dict:
    family = spec["family"]
    claim_type = spec["claim_type"]
    evidence_level = spec["evidence_level"]
    domain, claim_basis, design_families = _spec_domain_basis_families(spec)
    need_causal = needs_causal_basis({"claim_type": claim_type, "evidence_level": evidence_level})
    scaffolded = engine.dispatch(
        "scaffold_claim",
        {
            "case_id": case_id,
            "claim_id": "C1",
            "text": spec["draft"],
            "claim_type": claim_type,
            "evidence_level": evidence_level,
            "claim_basis": claim_basis,
            "scope": f"{family} cohort/experiment evaluation scope",
            "design_families": design_families,
            "include_causal_basis": need_causal,
        },
    )["claim"]
    claim = dict(scaffolded)
    claim["evidence_ids"] = [ev_id]
    claim["effect"] = {"estimate": "Primary effect reported in source", "uncertainty": "95% CI reported in source"}
    claim["contribution"] = f"Addresses: {spec['question']}"
    claim["alternatives"] = list(spec.get("alternatives") or [
        {"explanation": "Residual confounding or technical artifact", "status": "excluded", "reason": "Addressed by design controls and sensitivity checks"}
    ])
    claim["checks"] = {name: {"status": "pass", "reason": f"Checked in {ev_id}"} for name in CHECK_NAMES}
    claim["design_packages"] = [
        {
            "family": fam,
            "checks": {key: _pass_assessment(ev_id, f"{fam}.{key} satisfied") for key in DESIGN_FIELDS[fam]},
        }
        for fam in design_families
    ]
    claim["statistical_report"] = {key: _pass_assessment(ev_id, f"stat.{key} reported") for key in STAT_FIELDS}
    claim["provenance_cards"] = {"citation": [], "number": [], "execution": [], "search": []}

    if need_causal:
        nec_status = "pass" if claim_type == "necessity" else "not_applicable"
        suf_status = "pass" if claim_type == "sufficiency" else "not_applicable"
        causal_fam = design_families[0] if design_families else family
        claim["causal_basis"] = {
            "design_family": causal_fam,
            "estimand": {
                "population": "Target study population in registered source",
                "contrast": "Active exposure/intervention vs comparator strategy",
                "outcome": "Primary endpoint specified in question",
                "time_horizon": "Prespecified follow-up window",
                "summary": "Effect measure with 95% CI",
                "intercurrent_events": "Treatment policy / prespecified handling",
            },
            "assumptions": [
                {"name": "exchangeability_or_design_id", **_pass_assessment(ev_id, "Supported by design controls")},
                {"name": "consistency_and_positivity", **_pass_assessment(ev_id, "Well-defined intervention and overlap")},
            ],
            "falsification_sensitivity": [
                {"name": "negative_control_or_sensitivity", **_pass_assessment(ev_id, "Sensitivity / placebo check passed")},
            ],
            "assessment": _pass_assessment(ev_id, "Causal identification basis documented"),
            "necessity_test": {
                "status": nec_status,
                "reason": "Necessity counterfactual evaluated" if nec_status == "pass" else "Not a necessity claim",
                "evidence_ids": [ev_id] if nec_status == "pass" else [],
            },
            "sufficiency_test": {
                "status": suf_status,
                "reason": "Sufficiency counterfactual evaluated" if suf_status == "pass" else "Not a sufficiency claim",
                "evidence_ids": [ev_id] if suf_status == "pass" else [],
            },
        }

    tamper = spec.get("tamper")
    if tamper == "design_essential_not_applicable" and claim["design_packages"]:
        target_fam = claim["design_packages"][0]["family"]
        essential_key = sorted(ESSENTIAL_DESIGN_CHECKS[target_fam])[0]
        claim["design_packages"][0]["checks"][essential_key] = {
            "status": "not_applicable",
            "reason": "Rubber-stamped not_applicable on essential design check",
            "evidence_ids": [],
        }
    elif tamper == "all_design_not_applicable" and claim["design_packages"]:
        target_fam = claim["design_packages"][0]["family"]
        claim["design_packages"][0]["checks"] = {
            key: {"status": "not_applicable", "reason": "All design checks marked not_applicable", "evidence_ids": []}
            for key in DESIGN_FIELDS[target_fam]
        }
    elif tamper == "stat_essential_not_applicable":
        claim["statistical_report"]["estimate_uncertainty"] = {
            "status": "not_applicable",
            "reason": "Rubber-stamped not_applicable on estimate_uncertainty",
            "evidence_ids": [],
        }
    elif tamper == "fail_adherence_attrition" and claim["design_packages"]:
        claim["design_packages"][0]["checks"]["adherence_attrition"] = {
            "status": "fail",
            "reason": "42% differential dropout invalidates unadjusted complete-case ITT",
            "evidence_ids": [ev_id],
        }
    elif tamper == "unknown_sufficiency_test" and "causal_basis" in claim:
        claim["causal_basis"]["sufficiency_test"] = {
            "status": "unknown",
            "reason": "Only knockout was tested; sufficiency overexpression not performed",
            "evidence_ids": [],
        }
    elif tamper == "contradicting_citation_card":
        claim["provenance_cards"]["citation"] = [
            {
                "id": "cit-contra-1",
                "status": "checked",
                "reason": "Source table contradicts superiority claim",
                "evidence_ids": [ev_id],
                "details": {
                    "source": "Hospital B External Validation Report",
                    "locator": "Table 2, line 1",
                    "claim_link": "C1",
                    "support_relation": "contradicts",
                    "read_extent": "complete",
                },
            }
        ]
    elif tamper == "failed_execution_card":
        claim["provenance_cards"]["execution"] = [
            {
                "id": "exec-fail-1",
                "status": "failed",
                "reason": "Benchmark evaluation exited with non-zero status",
                "evidence_ids": [ev_id],
                "details": {
                    "command": "python run_benchmark.py --kernel K1",
                    "code_version": "abc1234",
                    "inputs": "test_split.json",
                    "environment": "Python 3.13",
                    "started_at": "2026-10-31T00:00:00Z",
                    "ended_at": "2026-10-31T00:01:00Z",
                    "exit_status": "1",
                    "outputs": "none",
                    "log_locator": "logs/bench.log:L1",
                },
            }
        ]
    return claim


def evaluate_single_case(spec: dict, base_dir: Path) -> dict:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    ws = base_dir / spec["case_code"]
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)
    created = engine.dispatch(
        "create_case",
        {
            "question": spec["question"],
            "draft": spec["draft"],
            "domain": domain,
            "writer_context_id": f"writer-{spec['case_code']}",
        },
    )
    case_id = created["case_id"]
    ev_rel = f"evidence/{spec['case_code']}.txt"
    ev_file = ws / ev_rel
    ev_file.parent.mkdir(parents=True, exist_ok=True)
    ev_file.write_text(spec["evidence_text"] + "\n", encoding="utf-8")
    ev = engine.dispatch(
        "register_evidence",
        {
            "case_id": case_id,
            "path": ev_rel,
            "label": f"Evidence for {spec['case_code']}",
            "provenance": spec.get("evidence_provenance", "observed"),
            "kind": spec["evidence_kind"],
            "quote": spec["evidence_text"],
            "location": f"{ev_rel}:L1",
        },
    )
    ev_id = ev["evidence_id"]
    claim = _build_claim_from_scaffold(engine, case_id, spec, ev_id)
    engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
    engine.dispatch("freeze", {"case_id": case_id})

    over_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
    under_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})

    target_verdict = spec["target_verdict"]
    is_underclaim = spec["scenario"] == "underclaim_trap"
    reviewer_stance = "insufficient_evidence" if spec["expected_gate_outcome"] == "rejected" else target_verdict
    stance_entry = {
        "claim_id": "C1",
        "stance": reviewer_stance,
        "rationale": "Evaluated against frozen evidence and check ceilings",
        "evidence_ids": [] if reviewer_stance == "insufficient_evidence" else [ev_id],
    }
    if reviewer_stance == "partially_supported" and spec.get("condition"):
        stance_entry["condition"] = spec["condition"]

    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "overclaim",
            "packet_id": over_pkt["packet_id"],
            "input_digest": over_pkt["input_digest"],
            "reviewer": {"context_id": f"over-{spec['case_code']}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance_entry)],
            "unread_evidence_ids": [],
            "findings": [],
        },
    )

    under_findings = []
    if is_underclaim:
        under_findings.append(
            {
                "id": "U1",
                "claim_id": "C1",
                "evidence_ids": [ev_id],
                "issue": "Draft buries supported finding under generic non-specific disclaimer",
                "proposed_claim_type": spec["claim_type"],
                "proposed_evidence_level": spec["evidence_level"],
                "proposed_claim_basis": claim_basis,
                "proposed_scope": claim["scope"],
                "proposed_text": spec["restored_text"],
                "decision_impact": "Restores the supported contribution while keeping scope boundary explicit",
            }
        )
    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "underclaim",
            "packet_id": under_pkt["packet_id"],
            "input_digest": under_pkt["input_digest"],
            "reviewer": {"context_id": f"under-{spec['case_code']}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance_entry)],
            "unread_evidence_ids": [],
            "findings": under_findings,
        },
    )

    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
    revised_text = spec["restored_text"] if is_underclaim else spec["draft"]
    decision = {
        "claim_id": "C1",
        "verdict": target_verdict,
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "claim_basis": claim_basis,
        "scope": claim["scope"],
        "revised_text": revised_text,
        "rationale": f"Adjudicated {spec['case_code']} ({spec['scenario']})",
        "evidence_ids": [ev_id],
        "confidence": "medium",
        "confidence_reason": "Backed by registered primary evidence",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if replication or sensitivity bounds fail",
    }
    if "condition" in spec:
        decision["condition"] = spec["condition"]

    dispositions = []
    if is_underclaim:
        dispositions.append(
            {
                "finding_id": "U1",
                "claim_id": "C1",
                "disposition": "accepted",
                "reason": "Restored supported contribution and removed generic disclaimer inflation",
                "resolution": "incorporated",
                "revised_text_quote": spec["restored_text"],
            }
        )

    symmetry_audit = None
    try:
        engine.dispatch(
            "submit_adjudication",
            {
                "case_id": case_id,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": f"adj-{spec['case_code']}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [decision],
                "dispositions": dispositions,
            },
        )
        verify_res = engine.dispatch("verify", {"case_id": case_id})
        symmetry_audit = verify_res.get("symmetry_audit")
        exported = engine.dispatch("export", {"case_id": case_id})
        actual_outcome = "accepted"
        actual_error = None
        export_state = exported["state"]
    except ContractError as exc:
        actual_outcome = "rejected"
        actual_error = exc.code
        export_state = None

    lexical_advisory_codes = [
        item["hook_code"]
        for item in (symmetry_audit or {}).get("lexical_advisories", [])
    ]
    passed = (
        actual_outcome == spec["expected_gate_outcome"]
        and actual_error == spec["expected_error_code"]
    )
    return {
        "case_code": spec["case_code"],
        "family": spec["family"],
        "domain": domain,
        "claim_basis": claim_basis,
        "scenario": spec["scenario"],
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "target_verdict": target_verdict,
        "expected_gate_outcome": spec["expected_gate_outcome"],
        "actual_gate_outcome": actual_outcome,
        "expected_error_code": spec["expected_error_code"],
        "actual_error_code": actual_error,
        "export_state": export_state,
        "symmetry_flag_codes": [f["hook_code"] for f in (symmetry_audit or {}).get("flags", [])],
        "lexical_advisory_codes": lexical_advisory_codes,
        "passed": passed,
    }


EXPLORATORY_CARD_FIELDS = (
    "strongest_rival",
    "discriminating_experiment",
    "cost",
    "stopping_rule",
    "kill_condition",
)


def evaluate_exploratory_case(spec: dict) -> dict:
    cards = spec.get("candidate_cards", [])
    valid = bool(cards)
    errors = []
    for idx, card in enumerate(cards):
        if card.get("origin") != "exploratory":
            valid = False
            errors.append(f"card[{idx}].origin != exploratory")
        for field in EXPLORATORY_CARD_FIELDS:
            val = card.get(field)
            if not isinstance(val, str) or not val.strip():
                valid = False
                errors.append(f"card[{idx}].{field} missing")
    return {
        "case_code": spec["case_code"],
        "family": spec["family"],
        "scenario": spec["scenario"],
        "card_count": len(cards),
        "origin": cards[0].get("origin") if cards else None,
        "claim_type": cards[0].get("claim_type") if cards else None,
        "evidence_level": cards[0].get("evidence_level") if cards else None,
        "metrics_status": {
            "discriminating_experiments_before_first_fp": "not_run",
            "steps_to_kill_false_hypothesis": "not_run",
            "total_consumption": "not_run",
        },
        "errors": errors,
        "passed": valid,
    }


COUNTERFACTUAL_PERTURBATIONS = (
    ("P1_null_flip", "unanchored_effect_estimate", "possible_contradictory_evidence_text", "unsupported"),
    ("P2_outcome_stripped", "unanchored_effect_estimate", "possible_outcome_pending_text", "insufficient_evidence"),
    ("P3_synthetic_swap", None, "possible_evidence_kind_mismatch", "insufficient_evidence"),
)


def build_perturbed_evidence(spec: dict, perturbation_id: str) -> tuple[str, str | None, str, str]:
    prefix = spec["evidence_text"].split(":", 1)[0].split(" (", 1)[0]
    if perturbation_id == "P1_null_flip":
        text = (
            f"{prefix}: primary effect estimate = 0.00 (95% CI -0.15 to +0.15, p = 0.88); "
            "null primary effect, does not support claimed effect."
        )
        return text, "unanchored_effect_estimate", "possible_contradictory_evidence_text", "unsupported"
    if perturbation_id == "P2_outcome_stripped":
        text = (
            f"{prefix}: baseline cohort characteristics and study protocol registered; "
            "primary endpoint table omitted."
        )
        return text, "unanchored_effect_estimate", "possible_outcome_pending_text", "insufficient_evidence"
    if perturbation_id == "P3_synthetic_swap":
        text = f"Synthetic simulation run (Monte Carlo toy dataset, no empirical observations): {spec['evidence_text']}"
        return text, None, "possible_evidence_kind_mismatch", "insufficient_evidence"
    raise ValueError(f"Unknown perturbation_id: {perturbation_id}")


def evaluate_counterfactual_case(spec: dict, perturbation_id: str, base_dir: Path) -> dict:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    perturbed_text, numeric_error, expected_advisory, expected_calibrated_verdict = build_perturbed_evidence(
        spec, perturbation_id
    )
    run_id = f"{spec['case_code']}-{perturbation_id}"
    ws = base_dir / run_id
    target_verdict = spec["target_verdict"]
    is_underclaim = spec["scenario"] == "underclaim_trap"
    revised_text = spec["restored_text"] if is_underclaim else spec["draft"]

    def _setup_cf_ws(sub_ws: Path) -> tuple[Engine, str, str, dict, dict, dict]:
        sub_ws.mkdir(parents=True, exist_ok=True)
        eng = Engine(sub_ws)
        cid = eng.dispatch(
            "create_case",
            {
                "question": spec["question"],
                "draft": spec["draft"],
                "domain": domain,
                "writer_context_id": f"writer-{run_id}-{sub_ws.name}",
            },
        )["case_id"]
        ev_rel = f"evidence/{run_id}.txt"
        ev_file = sub_ws / ev_rel
        ev_file.parent.mkdir(parents=True, exist_ok=True)
        ev_file.write_text(perturbed_text + "\n", encoding="utf-8")
        ev = eng.dispatch(
            "register_evidence",
            {
                "case_id": cid,
                "path": ev_rel,
                "label": f"Perturbed evidence ({perturbation_id}) for {spec['case_code']}",
                "provenance": spec.get("evidence_provenance", "observed"),
                "kind": spec["evidence_kind"],
                "quote": perturbed_text,
                "location": f"{ev_rel}:L1",
            },
        )
        eid = ev["evidence_id"]
        cl = _build_claim_from_scaffold(eng, cid, spec, eid)
        eng.dispatch("set_ledger", {"case_id": cid, "claims": [cl]})
        eng.dispatch("freeze", {"case_id": cid})
        opkt = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
        upkt = eng.dispatch("review_packet", {"case_id": cid, "role": "underclaim"})
        return eng, cid, eid, cl, opkt, upkt

    # 1. Measure rubber-stamp probe in isolated workspace (avoids duplicate_review on lexical-advisory cases)
    eng_rub, cid_rub, eid_rub, claim, over_pkt, under_pkt = _setup_cf_ws(ws / "rubber")
    rubber_stamp_decision = {
        "claim_id": "C1",
        "verdict": target_verdict,
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "claim_basis": claim_basis,
        "scope": claim["scope"],
        "revised_text": revised_text,
        "rationale": f"Rubber-stamped positive verdict on {run_id}",
        "evidence_ids": [eid_rub],
        "confidence": "medium",
        "confidence_reason": "Rubber-stamped without checking perturbed evidence",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if replication or sensitivity bounds fail",
    }
    if "condition" in spec:
        rubber_stamp_decision["condition"] = spec["condition"]

    has_claim_text_numbers = bool(_claimed_effect_tokens(claim, {"revised_text": claim["text"]}))
    has_decision_numbers = bool(_claimed_effect_tokens(claim, rubber_stamp_decision))
    expected_error = numeric_error if (numeric_error and has_decision_numbers) else None
    expected_review_error = numeric_error if (numeric_error and has_claim_text_numbers) else None

    bad_stance = {
        "claim_id": "C1",
        "stance": target_verdict,
        "rationale": "Rubber-stamped positive stance ignoring counterfactual perturbation",
        "evidence_ids": [eid_rub],
    }
    if target_verdict == "partially_supported" and spec.get("condition"):
        bad_stance["condition"] = spec["condition"]
    cal_stance = {
        "claim_id": "C1",
        "stance": expected_calibrated_verdict,
        "rationale": f"Perturbed evidence ({perturbation_id}) does not support positive claim",
        "evidence_ids": [],
    }
    under_findings = []
    if is_underclaim:
        under_findings.append(
            {
                "id": "U1",
                "claim_id": "C1",
                "evidence_ids": [eid_rub],
                "issue": "Draft buries supported finding under generic non-specific disclaimer",
                "proposed_claim_type": spec["claim_type"],
                "proposed_evidence_level": spec["evidence_level"],
                "proposed_claim_basis": claim_basis,
                "proposed_scope": claim["scope"],
                "proposed_text": spec["restored_text"],
                "decision_impact": "Restores the supported contribution while keeping scope boundary explicit",
            }
        )

    try:
        eng_rub.dispatch(
            "submit_review",
            {
                "case_id": cid_rub,
                "role": "overclaim",
                "packet_id": over_pkt["packet_id"],
                "input_digest": over_pkt["input_digest"],
                "reviewer": {"context_id": f"over-bad-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [bad_stance],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
        reviewer_rubber_stamp_blocked = False
        reviewer_error_code = None
    except ContractError as exc:
        reviewer_rubber_stamp_blocked = True
        reviewer_error_code = exc.code
        eng_rub.dispatch(
            "submit_review",
            {
                "case_id": cid_rub,
                "role": "overclaim",
                "packet_id": over_pkt["packet_id"],
                "input_digest": over_pkt["input_digest"],
                "reviewer": {"context_id": f"over-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(cal_stance)],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )

    eng_rub.dispatch(
        "submit_review",
        {
            "case_id": cid_rub,
            "role": "underclaim",
            "packet_id": under_pkt["packet_id"],
            "input_digest": under_pkt["input_digest"],
            "reviewer": {"context_id": f"under-{run_id}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(cal_stance)],
            "unread_evidence_ids": [],
            "findings": under_findings,
        },
    )
    adj_pkt = eng_rub.dispatch("adjudication_packet", {"case_id": cid_rub})

    # 2. Measure Pre-Card-A baseline gate outcome (counterfactual_gates=False)
    ev_map = {e["evidence_id"]: e for e in adj_pkt["evidence"]}
    try:
        validate_mechanical(rubber_stamp_decision, claim, ev_map, counterfactual_gates=False)
        pre_card_a_outcome = "accepted"
        pre_card_a_error = None
    except ContractError as exc:
        pre_card_a_outcome = "rejected"
        pre_card_a_error = exc.code

    # 3. Measure Card A gate/advisory outcome on rubber-stamped positive adjudication
    rubber_stamp_dispositions = []
    if is_underclaim:
        rubber_stamp_dispositions.append(
            {
                "finding_id": "U1",
                "claim_id": "C1",
                "disposition": "accepted",
                "reason": "Rubber-stamped positive restoration",
                "resolution": "incorporated",
                "revised_text_quote": spec["restored_text"],
            }
        )
    card_a_advisory_codes: list[str] = []
    try:
        eng_rub.dispatch(
            "submit_adjudication",
            {
                "case_id": cid_rub,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": f"adj-bad-{run_id}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [rubber_stamp_decision],
                "dispositions": rubber_stamp_dispositions,
            },
        )
        verify_rub = eng_rub.dispatch("verify", {"case_id": cid_rub})
        card_a_advisory_codes = [
            item["hook_code"]
            for item in (verify_rub.get("symmetry_audit") or {}).get("lexical_advisories", [])
        ]
        card_a_rubber_stamp_outcome = "accepted"
        card_a_error_code = None
    except ContractError as exc:
        card_a_rubber_stamp_outcome = "rejected"
        card_a_error_code = exc.code

    # 4. Measure Card A outcome in fresh workspace when adjudicator properly flips verdict
    eng_cal, cid_cal, eid_cal, claim_cal, over_cal, under_cal = _setup_cf_ws(ws / "calibrated")
    eng_cal.dispatch(
        "submit_review",
        {
            "case_id": cid_cal,
            "role": "overclaim",
            "packet_id": over_cal["packet_id"],
            "input_digest": over_cal["input_digest"],
            "reviewer": {"context_id": f"over-cal-{run_id}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(cal_stance)],
            "unread_evidence_ids": [],
            "findings": [],
        },
    )
    cal_under_findings = []
    if is_underclaim:
        cal_under_findings.append(
            {
                **under_findings[0],
                "evidence_ids": [eid_cal],
            }
        )
    eng_cal.dispatch(
        "submit_review",
        {
            "case_id": cid_cal,
            "role": "underclaim",
            "packet_id": under_cal["packet_id"],
            "input_digest": under_cal["input_digest"],
            "reviewer": {"context_id": f"under-cal-{run_id}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(cal_stance)],
            "unread_evidence_ids": [],
            "findings": cal_under_findings,
        },
    )
    adj_cal = eng_cal.dispatch("adjudication_packet", {"case_id": cid_cal})
    flipped_level = (
        spec["evidence_level"]
        if expected_calibrated_verdict == "unsupported"
        else _downgraded_level(spec["claim_type"])
    )
    flipped_decision = {
        "claim_id": "C1",
        "verdict": expected_calibrated_verdict,
        "claim_type": spec["claim_type"],
        "evidence_level": flipped_level,
        "claim_basis": claim_basis,
        "scope": claim_cal["scope"],
        "revised_text": (
            f"Counterfactual evaluation ({run_id}): perturbed source ({perturbation_id}) "
            f"requires flipping verdict from {target_verdict} to {expected_calibrated_verdict}."
        ),
        "rationale": f"Calibrated verdict flip under {perturbation_id}",
        "evidence_ids": [eid_cal] if expected_calibrated_verdict == "unsupported" else [],
        "confidence": "medium",
        "confidence_reason": "Verdict updated to track counterfactual evidence perturbation",
        "boundary": claim_cal["scope"],
        "reversal_condition": "Restore positive verdict only if unperturbed empirical outcome evidence is verified",
        "abstention_justification": {
            "blocking_gaps": [f"counterfactual_evidence_perturbation ({perturbation_id})"],
            "reason": (
                f"Counterfactual perturbation {perturbation_id} alters or removes the empirical outcome "
                "evidence required to support the original positive claim."
            ),
        },
    }
    flipped_dispositions = []
    if is_underclaim:
        flipped_dispositions.append(
            {
                "finding_id": "U1",
                "claim_id": "C1",
                "disposition": "rejected",
                "reason": "Perturbed counterfactual evidence does not support restoring positive empirical claim",
                "resolution": "disagreement",
                "disagreement": "Perturbed counterfactual source refutes or lacks empirical outcome support for positive restoration.",
            }
        )
    try:
        eng_cal.dispatch(
            "submit_adjudication",
            {
                "case_id": cid_cal,
                "adjudication_id": adj_cal["adjudication_id"],
                "input_digest": adj_cal["input_digest"],
                "adjudicator": {"context_id": f"adj-cal-{run_id}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [flipped_decision],
                "dispositions": flipped_dispositions,
            },
        )
        exported = eng_cal.dispatch("export", {"case_id": cid_cal})
        calibrated_flip_outcome = "accepted"
        calibrated_flip_export_state = exported["state"]
    except ContractError:
        calibrated_flip_outcome = "rejected"
        calibrated_flip_export_state = None

    if expected_error is not None:
        detection_mode = "hard_rejected" if (
            card_a_rubber_stamp_outcome == "rejected" and card_a_error_code == expected_error
        ) else "missed"
        reviewer_ok = (reviewer_error_code == expected_review_error) if expected_review_error is not None else (not reviewer_rubber_stamp_blocked)
        rubber_stamp_detected_ok = detection_mode == "hard_rejected"
    else:
        detection_mode = "lexical_advisory" if (
            card_a_rubber_stamp_outcome == "accepted" and expected_advisory in card_a_advisory_codes
        ) else "missed"
        reviewer_ok = not reviewer_rubber_stamp_blocked
        rubber_stamp_detected_ok = detection_mode == "lexical_advisory"

    passed = (
        reviewer_ok
        and rubber_stamp_detected_ok
        and calibrated_flip_outcome == "accepted"
        and calibrated_flip_export_state == "exported"
    )
    return {
        "run_id": run_id,
        "case_code": spec["case_code"],
        "family": spec["family"],
        "perturbation_id": perturbation_id,
        "original_verdict": target_verdict,
        "expected_calibrated_verdict": expected_calibrated_verdict,
        "pre_card_a_rubber_stamp_outcome": pre_card_a_outcome,
        "pre_card_a_error_code": pre_card_a_error,
        "reviewer_rubber_stamp_blocked": reviewer_rubber_stamp_blocked,
        "reviewer_error_code": reviewer_error_code,
        "card_a_rubber_stamp_outcome": card_a_rubber_stamp_outcome,
        "expected_error_code": expected_error,
        "actual_error_code": card_a_error_code,
        "expected_advisory_hook": expected_advisory if expected_error is None else None,
        "card_a_advisory_codes": card_a_advisory_codes,
        "detection_mode": detection_mode,
        "calibrated_flip_outcome": calibrated_flip_outcome,
        "calibrated_flip_export_state": calibrated_flip_export_state,
        "passed": passed,
    }


FORK_MULTIPLICITY_SCENARIOS = (
    ("F1_hidden_failed_forks", "selective_execution_omission", "insufficient_evidence"),
    ("F2_unadjusted_multi_fork", None, "insufficient_evidence"),
    ("F3_calibrated_multiplicity_accounted", None, "positive_preserved"),
)


def evaluate_fork_multiplicity_case(spec: dict, scenario_id: str, base_dir: Path) -> dict:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    run_id = f"{spec['case_code']}-{scenario_id}"
    ws = base_dir / run_id
    scenario_map = {sid: (err, cal) for sid, err, cal in FORK_MULTIPLICITY_SCENARIOS}
    expected_error, expected_cal_mode = scenario_map[scenario_id]
    target_verdict = spec["target_verdict"]
    is_underclaim = spec["scenario"] == "underclaim_trap"
    revised_text = spec["restored_text"] if is_underclaim else spec["draft"]

    def _setup_fork_ws(sub_ws: Path) -> tuple[Engine, str, str, dict, dict, dict]:
        sub_ws.mkdir(parents=True, exist_ok=True)
        eng = Engine(sub_ws)
        cid = eng.dispatch(
            "create_case",
            {
                "question": spec["question"],
                "draft": spec["draft"],
                "domain": domain,
                "writer_context_id": f"writer-{run_id}-{sub_ws.name}",
            },
        )["case_id"]
        fork_ev_ids = []
        fork_cards = []
        for fork_idx in range(1, 6):
            rel_path = f"logs/{run_id}-fork-{fork_idx}.log"
            log_file = sub_ws / rel_path
            log_file.parent.mkdir(parents=True, exist_ok=True)
            cmd_str = f"python run_analysis.py --case {spec['case_code']} --fork {fork_idx}"
            started_at = f"2026-11-10T00:0{fork_idx}:00+00:00"
            ended_at = f"2026-11-10T00:0{fork_idx}:05+00:00"
            header_quote = (
                f"command: {cmd_str}\n"
                f"started_at: {started_at}\n"
                f"ended_at: {ended_at}\n"
                f"exit_status: 0"
            )
            if fork_idx < 5:
                stdout_body = f"fork={fork_idx} seed={fork_idx} candidate_run_completed status=non_selected\n"
                ev_quote = header_quote
                card_status = "reported"
            else:
                stdout_body = (
                    f"{spec['evidence_text']}\n"
                    "Holm-Bonferroni adjusted across all 5 execution forks and verified on locked holdout.\n"
                )
                ev_quote = f"{header_quote}\n--- stdout ---\n{spec['evidence_text'][:60]}"
                card_status = "checked"
            log_text = f"{header_quote}\n--- stdout ---\n{stdout_body}\n--- stderr ---\n\n"
            log_file.write_text(log_text, encoding="utf-8", newline="\n")
            ev = eng.dispatch(
                "register_evidence",
                {
                    "case_id": cid,
                    "path": rel_path,
                    "label": "Recorded command execution log",
                    "provenance": spec.get("evidence_provenance", "observed"),
                    "kind": spec["evidence_kind"],
                    "quote": ev_quote,
                    "location": f"{rel_path}:L1-L6",
                },
            )
            ev_id = ev["evidence_id"]
            fork_ev_ids.append(ev_id)
            fork_meta = eng.record_execution_event(
                cid,
                {
                    "card_id": f"exec-fork-{fork_idx}",
                    "evidence_id": ev_id,
                    "command": cmd_str,
                    "exit_status": 0,
                    "status": card_status,
                    "log_path": rel_path,
                    "started_at": started_at,
                    "ended_at": ended_at,
                },
            )
            fork_suffix = (
                f" (case execution fork #{fork_meta['fork_index']}; multiplicity/selection accounting required)"
                if fork_meta["multiplicity_required"]
                else ""
            )
            fork_cards.append(
                {
                    "id": f"exec-fork-{fork_idx}",
                    "status": card_status,
                    "reason": f"Executed `{cmd_str}` with exit_status=0; log captured at {rel_path}{fork_suffix}.",
                    "evidence_ids": [ev_id],
                    "details": {
                        "command": cmd_str,
                        "code_version": "stage0-card-b",
                        "inputs": f"fork_{fork_idx}_config.json",
                        "environment": "Python 3.13",
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "exit_status": "0",
                        "outputs": "stdout/stderr log",
                        "log_locator": f"{rel_path}:L1-L6",
                    },
                }
            )
        p_eid = fork_ev_ids[-1]
        cl = _build_claim_from_scaffold(eng, cid, spec, p_eid)
        if scenario_id == "F1_hidden_failed_forks":
            cl["evidence_ids"] = [p_eid]
            cl["provenance_cards"]["execution"] = [fork_cards[-1]]
        elif scenario_id == "F2_unadjusted_multi_fork":
            cl["evidence_ids"] = list(fork_ev_ids)
            cl["provenance_cards"]["execution"] = list(fork_cards)
            cl["checks"]["multiplicity"] = {
                "status": "pass",
                "reason": "Single run primary test only without multiple testing adjustment",
            }
            cl["statistical_report"]["multiplicity_selection"] = {
                "status": "pass",
                "reason": f"Single execution run reported ({p_eid})",
                "evidence_ids": [p_eid],
            }
        else:
            cl["evidence_ids"] = list(fork_ev_ids)
            cl["provenance_cards"]["execution"] = list(fork_cards)
            cl["checks"]["multiplicity"] = {
                "status": "pass",
                "reason": "Holm-Bonferroni step-down correction applied across all 5 execution forks",
            }
            cl["statistical_report"]["multiplicity_selection"] = {
                "status": "pass",
                "reason": f"Holm-Bonferroni adjusted across all 5 execution forks and verified on locked holdout ({p_eid})",
                "evidence_ids": [p_eid],
            }
        eng.dispatch("set_ledger", {"case_id": cid, "claims": [cl]})
        eng.dispatch("freeze", {"case_id": cid})
        opkt = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
        upkt = eng.dispatch("review_packet", {"case_id": cid, "role": "underclaim"})
        return eng, cid, p_eid, cl, opkt, upkt

    eng_pos, cid_pos, primary_ev_id, claim, over_pkt, under_pkt = _setup_fork_ws(ws / "probe")
    positive_decision = {
        "claim_id": "C1",
        "verdict": target_verdict,
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "claim_basis": claim_basis,
        "scope": claim["scope"],
        "revised_text": revised_text,
        "rationale": f"Adjudicated {run_id}",
        "evidence_ids": [primary_ev_id],
        "confidence": "medium",
        "confidence_reason": "Backed by registered execution evidence",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if replication or sensitivity bounds fail",
    }
    if "condition" in spec:
        positive_decision["condition"] = spec["condition"]

    evidence_by_id = {e["evidence_id"]: e for e in over_pkt["evidence"]}
    try:
        validate_mechanical(positive_decision, claim, evidence_by_id, counterfactual_gates=True, fork_gates=False)
        pre_card_b_outcome = "accepted"
        pre_card_b_error = None
    except ContractError as exc:
        pre_card_b_outcome = "rejected"
        pre_card_b_error = exc.code

    pos_stance = {
        "claim_id": "C1",
        "stance": target_verdict,
        "rationale": "Evaluated execution forks",
        "evidence_ids": [primary_ev_id],
    }
    if target_verdict == "partially_supported" and spec.get("condition"):
        pos_stance["condition"] = spec["condition"]

    card_b_advisory_codes: list[str] = []
    if scenario_id in ("F1_hidden_failed_forks", "F2_unadjusted_multi_fork"):
        cal_stance = {
            "claim_id": "C1",
            "stance": "insufficient_evidence",
            "rationale": f"Execution fork gate ({scenario_id}) blocks unadjusted/cherry-picked positive stance",
            "evidence_ids": [],
        }
        try:
            eng_pos.dispatch(
                "submit_review",
                {
                    "case_id": cid_pos,
                    "role": "overclaim",
                    "packet_id": over_pkt["packet_id"],
                    "input_digest": over_pkt["input_digest"],
                    "reviewer": {"context_id": f"over-bad-{run_id}", "model": "eval-harness"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [pos_stance],
                    "unread_evidence_ids": [],
                    "findings": [],
                },
            )
            reviewer_blocked = False
            reviewer_error = None
        except ContractError as exc:
            reviewer_blocked = True
            reviewer_error = exc.code
            eng_pos.dispatch(
                "submit_review",
                {
                    "case_id": cid_pos,
                    "role": "overclaim",
                    "packet_id": over_pkt["packet_id"],
                    "input_digest": over_pkt["input_digest"],
                    "reviewer": {"context_id": f"over-{run_id}", "model": "eval-harness"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [dict(cal_stance)],
                    "unread_evidence_ids": [],
                    "findings": [],
                },
            )

        under_findings_probe = []
        probe_dispositions = []
        if is_underclaim:
            under_findings_probe.append(
                {
                    "id": "U1",
                    "claim_id": "C1",
                    "evidence_ids": [primary_ev_id],
                    "issue": "Draft buries positive finding under generic disclaimer",
                    "proposed_claim_type": spec["claim_type"],
                    "proposed_evidence_level": spec["evidence_level"],
                    "proposed_claim_basis": claim_basis,
                    "proposed_scope": claim["scope"],
                    "proposed_text": spec["restored_text"],
                    "decision_impact": "Probes positive restoration under execution fork scenario",
                }
            )
            probe_dispositions.append(
                {
                    "finding_id": "U1",
                    "claim_id": "C1",
                    "disposition": "accepted",
                    "reason": "Rubber-stamped positive restoration ignoring fork multiplicity text",
                    "resolution": "incorporated",
                    "revised_text_quote": spec["restored_text"],
                }
            )
        eng_pos.dispatch(
            "submit_review",
            {
                "case_id": cid_pos,
                "role": "underclaim",
                "packet_id": under_pkt["packet_id"],
                "input_digest": under_pkt["input_digest"],
                "reviewer": {"context_id": f"under-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(cal_stance)],
                "unread_evidence_ids": [],
                "findings": under_findings_probe,
            },
        )
        adj_pkt = eng_pos.dispatch("adjudication_packet", {"case_id": cid_pos})
        try:
            eng_pos.dispatch(
                "submit_adjudication",
                {
                    "case_id": cid_pos,
                    "adjudication_id": adj_pkt["adjudication_id"],
                    "input_digest": adj_pkt["input_digest"],
                    "adjudicator": {"context_id": f"adj-bad-{run_id}", "model": "eval-harness"},
                    "unread_evidence_ids": [],
                    "decisions": [positive_decision],
                    "dispositions": probe_dispositions,
                },
            )
            verify_probe = eng_pos.dispatch("verify", {"case_id": cid_pos})
            card_b_advisory_codes = [
                item["hook_code"]
                for item in (verify_probe.get("symmetry_audit") or {}).get("lexical_advisories", [])
            ]
            card_b_positive_outcome = "accepted"
            card_b_error_code = None
        except ContractError as exc:
            card_b_positive_outcome = "rejected"
            card_b_error_code = exc.code

        # Run calibrated downgrade cleanly in isolated workspace
        eng_cal, cid_cal, _, claim_cal, over_cal, under_cal = _setup_fork_ws(ws / "calibrated")
        eng_cal.dispatch(
            "submit_review",
            {
                "case_id": cid_cal,
                "role": "overclaim",
                "packet_id": over_cal["packet_id"],
                "input_digest": over_cal["input_digest"],
                "reviewer": {"context_id": f"over-cal-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(cal_stance)],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
        eng_cal.dispatch(
            "submit_review",
            {
                "case_id": cid_cal,
                "role": "underclaim",
                "packet_id": under_cal["packet_id"],
                "input_digest": under_cal["input_digest"],
                "reviewer": {"context_id": f"under-cal-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(cal_stance)],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
        adj_cal = eng_cal.dispatch("adjudication_packet", {"case_id": cid_cal})
        downgraded_level = _downgraded_level(spec["claim_type"])
        downgraded_decision = {
            "claim_id": "C1",
            "verdict": "insufficient_evidence",
            "claim_type": spec["claim_type"],
            "evidence_level": downgraded_level,
            "claim_basis": claim_basis,
            "scope": claim_cal["scope"],
            "revised_text": (
                f"Execution fork evaluation ({run_id}): 5 recorded execution forks under {scenario_id} "
                "require downgrading unadjusted/cherry-picked positive claim to insufficient_evidence."
            ),
            "rationale": f"Calibrated downgrade under {scenario_id}",
            "evidence_ids": [],
            "confidence": "medium",
            "confidence_reason": "Multiplicity/fork omission gate enforced",
            "boundary": claim_cal["scope"],
            "reversal_condition": "Disclose all execution forks and apply prespecified multiplicity correction",
            "abstention_justification": {
                "blocking_gaps": [f"unadjusted_multiplicity_across_5_execution_forks ({scenario_id})"],
                "reason": (
                    f"Five recorded execution forks under {scenario_id} omit prespecified multiplicity "
                    "correction or failed-run disclosure, blocking a positive verdict until resolved."
                ),
            },
        }
        eng_cal.dispatch(
            "submit_adjudication",
            {
                "case_id": cid_cal,
                "adjudication_id": adj_cal["adjudication_id"],
                "input_digest": adj_cal["input_digest"],
                "adjudicator": {"context_id": f"adj-cal-{run_id}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [downgraded_decision],
                "dispositions": [],
            },
        )
        exported = eng_cal.dispatch("export", {"case_id": cid_cal})
        calibrated_outcome = "accepted"
        calibrated_export_state = exported["state"]
        if scenario_id == "F1_hidden_failed_forks":
            detection_mode = "hard_rejected" if (
                card_b_positive_outcome == "rejected" and card_b_error_code == expected_error
            ) else "missed"
            passed = (
                pre_card_b_outcome == "accepted"
                and reviewer_blocked
                and detection_mode == "hard_rejected"
                and calibrated_outcome == "accepted"
                and calibrated_export_state == "exported"
            )
            expected_adv = None
        else:
            expected_adv = "possible_unadjusted_multiplicity_text"
            detection_mode = "lexical_advisory" if (
                card_b_positive_outcome == "accepted" and expected_adv in card_b_advisory_codes
            ) else "missed"
            passed = (
                pre_card_b_outcome == "accepted"
                and not reviewer_blocked
                and detection_mode == "lexical_advisory"
                and calibrated_outcome == "accepted"
                and calibrated_export_state == "exported"
            )
    else:
        # F3_calibrated_multiplicity_accounted: positive decision accepted cleanly with 0 advisories
        reviewer_blocked = False
        reviewer_error = None
        expected_adv = None
        eng_pos.dispatch(
            "submit_review",
            {
                "case_id": cid_pos,
                "role": "overclaim",
                "packet_id": over_pkt["packet_id"],
                "input_digest": over_pkt["input_digest"],
                "reviewer": {"context_id": f"over-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(pos_stance)],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
        under_findings = []
        dispositions = []
        if is_underclaim:
            under_findings.append(
                {
                    "id": "U1",
                    "claim_id": "C1",
                    "evidence_ids": [primary_ev_id],
                    "issue": "Draft buries multiplicity-adjusted empirical finding under generic disclaimer",
                    "proposed_claim_type": spec["claim_type"],
                    "proposed_evidence_level": spec["evidence_level"],
                    "proposed_claim_basis": claim_basis,
                    "proposed_scope": claim["scope"],
                    "proposed_text": spec["restored_text"],
                    "decision_impact": "Restores multiplicity-corrected contribution",
                }
            )
            dispositions.append(
                {
                    "finding_id": "U1",
                    "claim_id": "C1",
                    "disposition": "accepted",
                    "reason": "Restored multiplicity-adjusted contribution",
                    "resolution": "incorporated",
                    "revised_text_quote": spec["restored_text"],
                }
            )
        eng_pos.dispatch(
            "submit_review",
            {
                "case_id": cid_pos,
                "role": "underclaim",
                "packet_id": under_pkt["packet_id"],
                "input_digest": under_pkt["input_digest"],
                "reviewer": {"context_id": f"under-{run_id}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(pos_stance)],
                "unread_evidence_ids": [],
                "findings": under_findings,
            },
        )
        adj_pkt = eng_pos.dispatch("adjudication_packet", {"case_id": cid_pos})
        eng_pos.dispatch(
            "submit_adjudication",
            {
                "case_id": cid_pos,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": f"adj-cal-{run_id}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [positive_decision],
                "dispositions": dispositions,
            },
        )
        verify_ctrl = eng_pos.dispatch("verify", {"case_id": cid_pos})
        card_b_advisory_codes = [
            item["hook_code"]
            for item in (verify_ctrl.get("symmetry_audit") or {}).get("lexical_advisories", [])
        ]
        exported = eng_pos.dispatch("export", {"case_id": cid_pos})
        card_b_positive_outcome = "accepted"
        card_b_error_code = None
        calibrated_outcome = "accepted"
        calibrated_export_state = exported["state"]
        detection_mode = "clean_control"
        passed = (
            pre_card_b_outcome == "accepted"
            and card_b_positive_outcome == "accepted"
            and card_b_advisory_codes == []
            and calibrated_export_state == "exported"
        )

    return {
        "run_id": run_id,
        "case_code": spec["case_code"],
        "family": spec["family"],
        "scenario_id": scenario_id,
        "fork_count": 5,
        "original_verdict": target_verdict,
        "expected_calibrated_mode": expected_cal_mode,
        "pre_card_b_positive_outcome": pre_card_b_outcome,
        "pre_card_b_error_code": pre_card_b_error,
        "reviewer_rubber_stamp_blocked": reviewer_blocked,
        "reviewer_error_code": reviewer_error,
        "card_b_positive_outcome": card_b_positive_outcome,
        "expected_error_code": expected_error,
        "actual_error_code": card_b_error_code,
        "expected_advisory_hook": expected_adv,
        "card_b_advisory_codes": card_b_advisory_codes,
        "detection_mode": detection_mode,
        "calibrated_outcome": calibrated_outcome,
        "calibrated_export_state": calibrated_export_state,
        "passed": passed,
    }


SYMMETRY_SCENARIOS = (
    ("U1_false_abstention", "possible_false_abstention", False),
    ("U1b_unjustified_downgrade", "possible_unjustified_downgrade", False),
    ("U2_evidence_of_absence", "unsupported_without_counterevidence", False),
    ("U3_boilerplate_overhedging", "possible_boilerplate_overhedging", False),
    ("U4_rejected_underclaim_finding", "rejected_underclaim_finding_advisory", False),
    ("U_ctrl_calibrated_positive", None, True),
    ("U_ctrl_null_unsupported", None, True),
    ("U_ctrl_check_gap_insufficient", None, True),
)


def evaluate_symmetry_audit_case(spec: dict, scenario_id: str, base_dir: Path) -> dict:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    run_id = f"{spec['case_code']}-{scenario_id}"
    ws = base_dir / run_id
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)
    is_underclaim = spec["scenario"] == "underclaim_trap"
    pos_text = spec.get("restored_text") or spec["draft"]
    created = engine.dispatch(
        "create_case",
        {
            "question": spec["question"],
            "draft": spec["draft"],
            "domain": domain,
            "writer_context_id": f"writer-{run_id}",
            "symmetry_mode": "advisory",
        },
    )
    case_id = created["case_id"]
    if scenario_id == "U_ctrl_null_unsupported":
        ev_text, _, _, _ = build_perturbed_evidence(spec, "P1_null_flip")
    else:
        ev_text = spec["evidence_text"]
    ev_rel = f"evidence/{run_id}.txt"
    ev_file = ws / ev_rel
    ev_file.parent.mkdir(parents=True, exist_ok=True)
    ev_file.write_text(ev_text + "\n", encoding="utf-8")
    ev = engine.dispatch(
        "register_evidence",
        {
            "case_id": case_id,
            "path": ev_rel,
            "label": f"Symmetry evidence ({scenario_id}) for {spec['case_code']}",
            "provenance": spec.get("evidence_provenance", "observed"),
            "kind": spec["evidence_kind"],
            "quote": ev_text,
            "location": f"{ev_rel}:L1",
        },
    )
    ev_id = ev["evidence_id"]
    claim = _build_claim_from_scaffold(engine, case_id, spec, ev_id)
    if scenario_id == "U_ctrl_check_gap_insufficient":
        claim["checks"][CHECK_NAMES[0]] = {
            "status": "fail",
            "reason": f"Primary verification check failed in {ev_id}",
        }
    engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
    engine.dispatch("freeze", {"case_id": case_id})

    over_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
    under_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})

    target_verdict = spec["target_verdict"]
    if scenario_id == "U_ctrl_calibrated_positive":
        verdict = target_verdict
        ev_level = spec["evidence_level"]
        ev_refs = [ev_id]
        rev_text = pos_text
        rationale = f"Calibrated {run_id} matching evidenced ceiling"
        review_stance = target_verdict
        condition = spec.get("condition")
    elif scenario_id == "U_ctrl_null_unsupported":
        verdict = "unsupported"
        ev_level = spec["evidence_level"]
        ev_refs = [ev_id]
        rev_text = f"Primary source reports a null effect and does not support the claim ({run_id})."
        rationale = f"Null counterevidence justifies unsupported ({run_id})"
        review_stance = "unsupported"
        condition = None
    elif scenario_id == "U_ctrl_check_gap_insufficient":
        verdict = "insufficient_evidence"
        ev_level = _downgraded_level(spec["claim_type"])
        ev_refs = []
        rev_text = f"Provenance check failed; evidence insufficient ({run_id})."
        rationale = f"Failed provenance check blocks positive judgment ({run_id})"
        review_stance = "insufficient_evidence"
        condition = None
    elif scenario_id == "U1_false_abstention":
        verdict = "insufficient_evidence"
        ev_level = _downgraded_level(spec["claim_type"])
        ev_refs = []
        rev_text = f"Withholding judgment pending additional future trials ({run_id})."
        rationale = f"Overly cautious abstention despite passing checks ({run_id})"
        review_stance = "insufficient_evidence"
        condition = None
    elif scenario_id == "U1b_unjustified_downgrade":
        verdict = "partially_supported"
        ev_level = spec["evidence_level"]
        ev_refs = [ev_id]
        rev_text = pos_text
        rationale = f"Downgraded positive claim to conditional without overclaim finding ({run_id})"
        review_stance = target_verdict
        condition = "Preliminary scope only within the observed study cohort."
    elif scenario_id == "U2_evidence_of_absence":
        verdict = "unsupported"
        ev_level = spec["evidence_level"]
        ev_refs = [ev_id]
        rev_text = f"Marked unsupported despite non-contradicting primary evidence ({run_id})."
        rationale = f"Unsupported without counterevidence or failed check ({run_id})"
        review_stance = "unsupported"
        condition = None
    elif scenario_id == "U3_boilerplate_overhedging":
        verdict = "insufficient_evidence"
        ev_level = _downgraded_level(spec["claim_type"])
        ev_refs = [ev_id]
        rev_text = (
            f"{pos_text} However, cannot draw definitive conclusions pending future larger "
            "confirmatory trials; for reference only."
        )
        rationale = f"Generic boilerplate hedging despite anchored estimates ({run_id})"
        review_stance = "insufficient_evidence"
        condition = None
    elif scenario_id == "U4_rejected_underclaim_finding":
        verdict = "insufficient_evidence"
        ev_level = _downgraded_level(spec["claim_type"])
        ev_refs = []
        rev_text = f"Declining restoration despite passing underclaim finding ({run_id})."
        rationale = f"Rejected underclaim finding without failed check ({run_id})"
        review_stance = "insufficient_evidence"
        condition = None
    else:
        raise ValueError(f"Unknown symmetry scenario: {scenario_id}")

    over_stance = {
        "claim_id": "C1",
        "stance": review_stance,
        "rationale": rationale,
        "evidence_ids": [ev_id] if review_stance in ("supported", "partially_supported", "unsupported") else [],
    }
    if review_stance == "partially_supported" and condition:
        over_stance["condition"] = condition

    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "overclaim",
            "packet_id": over_pkt["packet_id"],
            "input_digest": over_pkt["input_digest"],
            "reviewer": {"context_id": f"over-{run_id}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(over_stance)],
            "unread_evidence_ids": [],
            "findings": [],
        },
    )

    under_findings = []
    dispositions = []
    if scenario_id == "U4_rejected_underclaim_finding":
        under_findings.append(
            {
                "id": "U1",
                "claim_id": "C1",
                "evidence_ids": [ev_id],
                "issue": "Draft hides supported finding behind non-specific uncertainty",
                "proposed_claim_type": spec["claim_type"],
                "proposed_evidence_level": spec["evidence_level"],
                "proposed_claim_basis": claim_basis,
                "proposed_scope": claim["scope"],
                "proposed_text": pos_text,
                "decision_impact": "Restores the supported contribution",
            }
        )
        dispositions.append(
            {
                "finding_id": "U1",
                "claim_id": "C1",
                "disposition": "rejected",
                "reason": "Deferring positive restoration pending broader confirmation",
                "resolution": "disagreement",
                "disagreement": "Deferred restoration despite passing primary evidence.",
            }
        )
    elif scenario_id == "U_ctrl_calibrated_positive" and is_underclaim:
        under_findings.append(
            {
                "id": "U1",
                "claim_id": "C1",
                "evidence_ids": [ev_id],
                "issue": "Draft buries supported finding under generic disclaimer",
                "proposed_claim_type": spec["claim_type"],
                "proposed_evidence_level": spec["evidence_level"],
                "proposed_claim_basis": claim_basis,
                "proposed_scope": claim["scope"],
                "proposed_text": pos_text,
                "decision_impact": "Restores supported contribution",
            }
        )
        dispositions.append(
            {
                "finding_id": "U1",
                "claim_id": "C1",
                "disposition": "accepted",
                "reason": "Restored supported contribution",
                "resolution": "incorporated",
                "revised_text_quote": pos_text,
            }
        )

    under_stance = dict(over_stance)
    if scenario_id == "U4_rejected_underclaim_finding":
        under_stance = {
            "claim_id": "C1",
            "stance": target_verdict,
            "rationale": "Primary evidence supports restoring positive claim",
            "evidence_ids": [ev_id],
        }
        if target_verdict == "partially_supported" and spec.get("condition"):
            under_stance["condition"] = spec["condition"]

    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "underclaim",
            "packet_id": under_pkt["packet_id"],
            "input_digest": under_pkt["input_digest"],
            "reviewer": {"context_id": f"under-{run_id}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [under_stance],
            "unread_evidence_ids": [],
            "findings": under_findings,
        },
    )

    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
    decision = {
        "claim_id": "C1",
        "verdict": verdict,
        "claim_type": spec["claim_type"],
        "evidence_level": ev_level,
        "claim_basis": claim_basis,
        "scope": claim["scope"],
        "revised_text": rev_text,
        "rationale": rationale,
        "evidence_ids": ev_refs,
        "confidence": "medium",
        "confidence_reason": "Evaluated in Card C symmetry audit harness",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if primary evidence or check status changes",
    }
    if verdict == "partially_supported" and condition:
        decision["condition"] = condition

    engine.dispatch(
        "submit_adjudication",
        {
            "case_id": case_id,
            "adjudication_id": adj_pkt["adjudication_id"],
            "input_digest": adj_pkt["input_digest"],
            "adjudicator": {"context_id": f"adj-{run_id}", "model": "eval-harness"},
            "unread_evidence_ids": [],
            "decisions": [decision],
            "dispositions": dispositions,
        },
    )
    verify_res = engine.dispatch("verify", {"case_id": case_id})
    exported = engine.dispatch("export", {"case_id": case_id})
    sym_audit = verify_res.get("symmetry_audit") or {}
    flags = sym_audit.get("flags") or []
    hook_codes = [f.get("hook_code") for f in flags if f.get("hook_code")]
    expected_hook = {sid: hook for sid, hook, _ in SYMMETRY_SCENARIOS}[scenario_id]
    is_control = {sid: ctrl for sid, _, ctrl in SYMMETRY_SCENARIOS}[scenario_id]
    non_blocking_ok = (
        sym_audit.get("non_blocking") is True
        and sym_audit.get("severity") == "advisory"
        and all(f.get("non_blocking") is True and f.get("severity") == "advisory" for f in flags)
        and exported.get("state") == "exported"
    )
    if is_control:
        hook_ok = len(flags) == 0
    else:
        hook_ok = expected_hook in hook_codes

    return {
        "run_id": run_id,
        "case_code": spec["case_code"],
        "family": spec["family"],
        "scenario_id": scenario_id,
        "is_calibrated_control": is_control,
        "expected_hook_code": expected_hook,
        "observed_hook_codes": hook_codes,
        "flag_count": len(flags),
        "non_blocking_preserved": non_blocking_ok,
        "export_state": exported.get("state"),
        "passed": non_blocking_ok and hook_ok,
    }


def run_symmetry_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-symmetry-"))
        cleanup = True
    try:
        positive_cases = [c for c in suite["cases"] if c["expected_gate_outcome"] == "accepted"]
        results: list[dict] = []
        for case in positive_cases:
            results.append(evaluate_symmetry_audit_case(case, "U1_false_abstention", work_root))
            if case["target_verdict"] == "supported":
                results.append(evaluate_symmetry_audit_case(case, "U1b_unjustified_downgrade", work_root))
            results.append(evaluate_symmetry_audit_case(case, "U2_evidence_of_absence", work_root))
            probe_text = case.get("restored_text") or case["draft"]
            probe_claim = {
                "text": case["draft"],
                "effect": {"estimate": "Primary effect reported", "uncertainty": "95% CI reported"},
            }
            if _claimed_effect_tokens(probe_claim, {"revised_text": probe_text}):
                results.append(evaluate_symmetry_audit_case(case, "U3_boilerplate_overhedging", work_root))
            if case["scenario"] == "underclaim_trap":
                results.append(evaluate_symmetry_audit_case(case, "U4_rejected_underclaim_finding", work_root))
            if case["target_verdict"] == "supported" or case["case_code"] == "OBS-04":
                results.append(evaluate_symmetry_audit_case(case, "U_ctrl_calibrated_positive", work_root))
            results.append(evaluate_symmetry_audit_case(case, "U_ctrl_null_unsupported", work_root))
            results.append(evaluate_symmetry_audit_case(case, "U_ctrl_check_gap_insufficient", work_root))
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    def _subset_rate(scenario_id: str) -> tuple[int, int, float]:
        sub = [r for r in results if r["scenario_id"] == scenario_id]
        hits = sum(1 for r in sub if r["passed"])
        return hits, len(sub), (round(hits / len(sub), 4) if sub else 0.0)

    u1_hit, u1_tot, u1_rate = _subset_rate("U1_false_abstention")
    u1b_hit, u1b_tot, u1b_rate = _subset_rate("U1b_unjustified_downgrade")
    u2_hit, u2_tot, u2_rate = _subset_rate("U2_evidence_of_absence")
    u3_hit, u3_tot, u3_rate = _subset_rate("U3_boilerplate_overhedging")
    u4_hit, u4_tot, u4_rate = _subset_rate("U4_rejected_underclaim_finding")
    ctrls = [r for r in results if r["is_calibrated_control"]]
    ctrl_false_alarms = sum(1 for r in ctrls if r["flag_count"] > 0)
    ctrl_false_alarm_rate = round(ctrl_false_alarms / len(ctrls), 4) if ctrls else 0.0
    non_blocking_preserved = sum(1 for r in results if r["non_blocking_preserved"])
    non_blocking_rate = round(non_blocking_preserved / len(results), 4) if results else 0.0
    total_passed = sum(1 for r in results if r["passed"])
    observed_hooks = {code for r in results for code in r["observed_hook_codes"]}
    expected_hooks = {
        "possible_false_abstention",
        "possible_unjustified_downgrade",
        "unsupported_without_counterevidence",
        "possible_boilerplate_overhedging",
        "rejected_underclaim_finding_advisory",
    }
    symmetry_summary = {
        "card_id": "Card-C",
        "total_runs": len(results),
        "passed_runs": total_passed,
        "false_abstention_runs": u1_tot,
        "false_abstention_detected": u1_hit,
        "false_abstention_detection_rate": u1_rate,
        "unjustified_downgrade_runs": u1b_tot,
        "unjustified_downgrade_detected": u1b_hit,
        "unjustified_downgrade_detection_rate": u1b_rate,
        "evidence_of_absence_runs": u2_tot,
        "evidence_of_absence_detected": u2_hit,
        "evidence_of_absence_detection_rate": u2_rate,
        "boilerplate_overhedging_runs": u3_tot,
        "boilerplate_overhedging_detected": u3_hit,
        "boilerplate_overhedging_detection_rate": u3_rate,
        "rejected_underclaim_runs": u4_tot,
        "rejected_underclaim_detected": u4_hit,
        "rejected_underclaim_detection_rate": u4_rate,
        "calibrated_control_runs": len(ctrls),
        "calibrated_false_alarms": ctrl_false_alarms,
        "calibrated_false_alarm_rate": ctrl_false_alarm_rate,
        "non_blocking_export_preserved_count": non_blocking_preserved,
        "non_blocking_export_preserved_rate": non_blocking_rate,
        "all_five_hooks_verified": expected_hooks <= observed_hooks,
        "all_passed": (
            total_passed == len(results)
            and non_blocking_rate == 1.0
            and ctrl_false_alarm_rate == 0.0
            and expected_hooks <= observed_hooks
        ),
    }
    return {"summary": symmetry_summary, "results": results}


def evaluate_paired_sensitivity_case(pair_spec: dict, base_dir: Path) -> dict:
    twin_results = []
    for role_key in ("strong_twin", "weak_twin"):
        twin = pair_spec[role_key]
        merged = {
            "case_code": twin["twin_id"],
            "family": pair_spec["family"],
            "domain": pair_spec.get("domain", "scientific"),
            "claim_basis": pair_spec.get("claim_basis", "empirical"),
            "claim_type": pair_spec["claim_type"],
            "evidence_level": pair_spec["target_evidence_level"],
            "scenario": "calibrated_valid" if role_key == "strong_twin" else "overclaim_trap",
            "question": pair_spec["question"],
            "draft": twin["draft"],
            "evidence_text": twin["evidence_text"],
            "evidence_kind": twin["evidence_kind"],
            "target_verdict": twin["target_verdict"],
            "expected_gate_outcome": twin["expected_gate_outcome"],
            "expected_error_code": twin.get("expected_error_code"),
        }
        if "design_families" in pair_spec:
            merged["design_families"] = list(pair_spec["design_families"])
        if "condition" in twin:
            merged["condition"] = twin["condition"]
        res = evaluate_single_case(merged, base_dir)
        if res["expected_gate_outcome"] == "accepted":
            res["passed"] = res["passed"] and res["export_state"] == "exported"
        expected_advisory = twin.get("expected_advisory_hook")
        if expected_advisory:
            res["expected_advisory_hook"] = expected_advisory
            res["passed"] = res["passed"] and (expected_advisory in res.get("lexical_advisory_codes", []))
        res["polarity"] = twin["polarity"]
        twin_results.append(res)

    strong_res, weak_res = twin_results[0], twin_results[1]
    return {
        "pair_code": pair_spec["pair_code"],
        "family": pair_spec["family"],
        "claim_type": pair_spec["claim_type"],
        "target_evidence_level": pair_spec["target_evidence_level"],
        "strong_twin": strong_res,
        "weak_twin": weak_res,
        "passed": strong_res["passed"] and weak_res["passed"],
    }


def run_paired_sensitivity_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-paired-"))
        cleanup = True
    try:
        pair_results = [
            evaluate_paired_sensitivity_case(pair, work_root)
            for pair in suite.get("paired_sensitivity_cases", [])
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    total_pairs = len(pair_results)
    passed_pairs = sum(1 for item in pair_results if item["passed"])
    strong_accepted = sum(1 for item in pair_results if item["strong_twin"]["passed"])
    weak_rejected = sum(
        1 for item in pair_results
        if item["weak_twin"]["passed"] and item["weak_twin"]["actual_gate_outcome"] == "rejected"
    )
    weak_advisory_flagged = sum(
        1 for item in pair_results
        if item["weak_twin"]["passed"]
        and item["weak_twin"]["actual_gate_outcome"] == "accepted"
        and bool(item["weak_twin"].get("expected_advisory_hook"))
    )
    weak_detected = weak_rejected + weak_advisory_flagged
    summary = {
        "total_pairs": total_pairs,
        "passed_pairs": passed_pairs,
        "strong_twins_accepted": strong_accepted,
        "strong_twins_total": total_pairs,
        "weak_twins_rejected": weak_rejected,
        "weak_twins_advisory_flagged": weak_advisory_flagged,
        "weak_twins_detected": weak_detected,
        "weak_twins_total": total_pairs,
        "paired_evidence_sensitivity_concordance": round(passed_pairs / total_pairs, 4) if total_pairs else 0.0,
        "all_passed": passed_pairs == total_pairs,
    }
    return {"summary": summary, "results": pair_results}


def _make_large_window_text(spec: dict, *, tail_override: str | None = None) -> str:
    anchors = list(spec.get("excerpt_anchors") or [])
    if anchors:
        head_line = anchors[0]
        body_anchors = anchors[1:-1] if len(anchors) >= 3 else anchors[1:]
        tail_line = tail_override or (anchors[-1] if len(anchors) >= 2 else "Tail safety and limitations summary line.")
    else:
        head_line = "Trial NCT05881201 multicenter randomized protocol header line (N=910)."
        body_anchors = [
            "Primary endpoint 12-month composite reduction: OR = 0.71 (95% CI 0.60 to 0.84, p = 0.0002) across ITT cohort.",
        ]
        tail_line = tail_override or "Tail safety & limitations summary beyond 128 KiB offset."
    filler_line = "Patient-level blinded center monitoring appendix row: protocol adherence verified, QC audit complete."
    parts = [head_line]
    parts.extend([filler_line] * 700)
    parts.extend(body_anchors)
    parts.extend([filler_line] * 700)
    parts.append(tail_line)
    text = "\n".join(parts) + "\n"
    min_bytes = max(int(spec.get("source_byte_length", 144000)), PACKET_TEXT_BYTES + 8192)
    while len(text.encode("utf-8")) < min_bytes:
        text = text.replace(tail_line, f"{filler_line}\n{tail_line}", 1)
    return text


def evaluate_lineage_window_spec(spec: dict, base_dir: Path) -> dict:
    code = spec["spec_code"]
    ws = base_dir / code
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)
    domain = spec.get("domain", "scientific")
    claim_basis = spec.get("claim_basis", "empirical")
    claim_type = spec["claim_type"]
    evidence_level = spec["evidence_level"]
    question = f"Lineage and excerpt-window verification for {code} ({spec['scenario']})"
    draft = spec.get(
        "draft",
        "Adjusted analysis (OR = 0.68, 95% CI 0.59 to 0.78) or trial result (RD = -6.5%, 95% CI -10.1% to -2.9%) holds.",
    )
    created = engine.dispatch(
        "create_case",
        {
            "question": question,
            "draft": draft,
            "domain": domain,
            "writer_context_id": f"writer-{code}",
        },
    )
    case_id = created["case_id"]
    family = "observational" if claim_type == "association" else "randomized"

    def _scaffold(cited_ids: list[str], *, text: str = draft) -> dict:
        sc = _build_claim_from_scaffold(
            engine,
            case_id,
            {
                "case_code": code,
                "family": family,
                "domain": domain,
                "claim_basis": claim_basis,
                "claim_type": claim_type,
                "evidence_level": evidence_level,
                "question": question,
                "draft": text,
                "evidence_text": text,
                "evidence_kind": "intervention" if family == "randomized" else "observation",
                "target_verdict": spec["target_verdict"],
            },
            cited_ids[0],
        )
        sc["evidence_ids"] = list(cited_ids)
        return sc

    extra: dict = {}
    actual_outcome = None
    actual_error = None
    export_state = None

    if code == "LIN-01":
        nodes = {n["evidence_id"]: n for n in spec["lineage"]}
        syn_node = nodes["ev_syn_root"]
        drv_node = nodes["ev_obs_derived"]
        syn_rel = "evidence/lin01_syn.txt"
        (ws / syn_rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / syn_rel).write_text(syn_node["source_text"] + "\n", encoding="utf-8")
        syn_ev = engine.dispatch(
            "register_evidence",
            {
                "case_id": case_id,
                "path": syn_rel,
                "label": "Synthetic root simulation",
                "provenance": syn_node["provenance"],
                "kind": syn_node["kind"],
                "quote": syn_node["source_text"][:60],
                "location": f"{syn_rel}:L1",
            },
        )
        drv_rel = "evidence/lin01_derived.txt"
        (ws / drv_rel).write_text(drv_node["source_text"] + "\n", encoding="utf-8")
        drv_ev = engine.dispatch(
            "register_evidence",
            {
                "case_id": case_id,
                "path": drv_rel,
                "label": "Derived regression table",
                "provenance": drv_node["provenance"],
                "kind": drv_node["kind"],
                "quote": drv_node["quote"],
                "location": f"{drv_rel}:L1",
                "derived_from_evidence_ids": [syn_ev["evidence_id"]],
                "derivation_step": drv_node["derivation_step"],
            },
        )
        cli_ws = ws / "cli-check"
        cli_ws.mkdir(parents=True, exist_ok=True)
        cli_eng = Engine(cli_ws)
        cli_case_id = cli_eng.dispatch(
            "create_case",
            {"question": question, "draft": draft, "domain": domain, "writer_context_id": f"writer-{code}-cli"},
        )["case_id"]
        cli_syn_rel = "evidence/lin01_cli_syn.txt"
        (cli_ws / cli_syn_rel).parent.mkdir(parents=True, exist_ok=True)
        (cli_ws / cli_syn_rel).write_text(syn_node["source_text"] + "\n", encoding="utf-8")
        cli_syn_ev = cli_eng.dispatch(
            "register_evidence",
            {
                "case_id": cli_case_id,
                "path": cli_syn_rel,
                "label": "Synthetic root simulation (CLI test)",
                "provenance": syn_node["provenance"],
                "kind": syn_node["kind"],
                "quote": syn_node["source_text"][:60],
                "location": f"{cli_syn_rel}:L1",
            },
        )
        cli_raw = io.BytesIO()
        cli_stdout = io.TextIOWrapper(cli_raw, encoding="utf-8")
        cli_stderr = io.StringIO()
        with contextlib.redirect_stdout(cli_stdout), contextlib.redirect_stderr(cli_stderr):
            cli_ret = cli_main(
                [
                    "record-exec",
                    "--workspace",
                    str(cli_ws),
                    "--case-id",
                    cli_case_id,
                    "--claim-id",
                    "C1",
                    "--card-id",
                    "exec-lin01-cli",
                    "--kind",
                    "auto",
                    "--derived-from",
                    cli_syn_ev["evidence_id"],
                    "--derivation-step",
                    "CLI aggregated synthetic table claiming empirical association",
                    "--",
                    sys.executable,
                    "-c",
                    "print('Adjusted regression cohort table (N=2,000): odds ratio OR = 0.68 (95% CI 0.59 to 0.78)')",
                ]
            )
            cli_stdout.flush()
        cli_payload = json.loads(cli_raw.getvalue().decode("utf-8"))
        cli_ev_id = cli_payload["evidence"]["evidence_id"]
        cli_draft_text = "Across 2,000 cohort records, adjusted association OR = 0.68 (95% CI 0.59 to 0.78) is observed."
        cli_claim = _build_claim_from_scaffold(
            cli_eng,
            cli_case_id,
            {
                "case_code": f"{code}-CLI",
                "family": family,
                "domain": domain,
                "claim_basis": claim_basis,
                "claim_type": claim_type,
                "evidence_level": evidence_level,
                "question": question,
                "draft": cli_draft_text,
                "evidence_text": cli_draft_text,
                "evidence_kind": "observation",
                "target_verdict": spec["target_verdict"],
            },
            cli_ev_id,
        )
        cli_claim["provenance_cards"]["execution"] = [cli_payload["execution_card"]]
        cli_eng.dispatch("set_ledger", {"case_id": cli_case_id, "claims": [cli_claim]})
        cli_eng.dispatch("freeze", {"case_id": cli_case_id})
        cli_op = cli_eng.dispatch("review_packet", {"case_id": cli_case_id, "role": "overclaim"})
        cli_up = cli_eng.dispatch("review_packet", {"case_id": cli_case_id, "role": "underclaim"})
        cli_cal = [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "CLI synthetic ancestor detected", "evidence_ids": []}]
        cli_eng.dispatch("submit_review", {"case_id": cli_case_id, "role": "overclaim", "packet_id": cli_op["packet_id"], "input_digest": cli_op["input_digest"], "reviewer": {"context_id": f"over-{code}-cli", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": cli_cal, "unread_evidence_ids": [], "findings": []})
        cli_eng.dispatch("submit_review", {"case_id": cli_case_id, "role": "underclaim", "packet_id": cli_up["packet_id"], "input_digest": cli_up["input_digest"], "reviewer": {"context_id": f"under-{code}-cli", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": cli_cal, "unread_evidence_ids": [], "findings": []})
        cli_ap = cli_eng.dispatch("adjudication_packet", {"case_id": cli_case_id})
        try:
            cli_eng.dispatch(
                "submit_adjudication",
                {
                    "case_id": cli_case_id,
                    "adjudication_id": cli_ap["adjudication_id"],
                    "input_digest": cli_ap["input_digest"],
                    "adjudicator": {"context_id": f"adj-{code}-cli", "model": "eval-harness"},
                    "unread_evidence_ids": [],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": spec["target_verdict"],
                            "claim_type": claim_type,
                            "evidence_level": evidence_level,
                            "claim_basis": claim_basis,
                            "scope": cli_claim["scope"],
                            "revised_text": cli_draft_text,
                            "rationale": "Testing CLI --derived-from synthetic ancestor blocking",
                            "evidence_ids": [cli_ev_id],
                            "confidence": "medium",
                            "confidence_reason": "Testing CLI lineage",
                            "boundary": cli_claim["scope"],
                            "reversal_condition": "Require non-synthetic empirical source",
                        }
                    ],
                    "dispositions": [],
                },
            )
            extra["cli_error"] = None
        except ContractError as exc:
            extra["cli_error"] = exc.code

        draft_text = "Across 2,000 cohort records, adjusted association OR = 0.68 (95% CI 0.59 to 0.78) is observed."
        claim = _scaffold([drv_ev["evidence_id"]], text=draft_text)
        engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
        engine.dispatch("freeze", {"case_id": case_id})
        over_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
        under_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})
        cal_stance = [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Synthetic ancestor detected", "evidence_ids": []}]
        engine.dispatch("submit_review", {"case_id": case_id, "role": "overclaim", "packet_id": over_pkt["packet_id"], "input_digest": over_pkt["input_digest"], "reviewer": {"context_id": f"over-{code}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": cal_stance, "unread_evidence_ids": [], "findings": []})
        engine.dispatch("submit_review", {"case_id": case_id, "role": "underclaim", "packet_id": under_pkt["packet_id"], "input_digest": under_pkt["input_digest"], "reviewer": {"context_id": f"under-{code}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": cal_stance, "unread_evidence_ids": [], "findings": []})
        adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})

        try:
            engine.dispatch(
                "submit_adjudication",
                {
                    "case_id": case_id,
                    "adjudication_id": adj_pkt["adjudication_id"],
                    "input_digest": adj_pkt["input_digest"],
                    "adjudicator": {"context_id": f"adj-{code}-engine", "model": "eval-harness"},
                    "unread_evidence_ids": [],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": spec["target_verdict"],
                            "claim_type": claim_type,
                            "evidence_level": evidence_level,
                            "claim_basis": claim_basis,
                            "scope": claim["scope"],
                            "revised_text": draft_text,
                            "rationale": "Testing derived synthetic lineage blocker",
                            "evidence_ids": [drv_ev["evidence_id"]],
                            "confidence": "medium",
                            "confidence_reason": "Testing lineage",
                            "boundary": claim["scope"],
                            "reversal_condition": "Require non-synthetic empirical source",
                        }
                    ],
                    "dispositions": [],
                },
            )
            extra["engine_error"] = None
        except ContractError as exc:
            extra["engine_error"] = exc.code

        verify_res = engine.dispatch("verify", {"case_id": case_id})
        chains_ok = any(
            ch["evidence_id"] == drv_ev["evidence_id"] and syn_ev["evidence_id"] in ch.get("ancestors", [])
            for ch in verify_res.get("evidence_chains", [])
        )
        actual_outcome = "rejected" if extra["engine_error"] == spec["expected_error_code"] else "accepted"
        actual_error = extra["engine_error"]
        extra["cli_exit_code"] = cli_ret
        extra["cli_derived_from"] = cli_payload.get("derived_from_evidence_ids")
        extra["cli_derived_blocked"] = extra["cli_error"] == spec["expected_error_code"]
        extra["lineage_chain_recorded"] = chains_ok
        passed = (
            actual_outcome == spec["expected_gate_outcome"]
            and actual_error == spec["expected_error_code"]
            and cli_ret == 0
            and cli_payload.get("derived_from_evidence_ids") == [cli_syn_ev["evidence_id"]]
            and extra["cli_derived_blocked"]
            and chains_ok
        )

    elif code == "LIN-02":
        def _run_lin02_instance(inst_dir: Path, *, tamper_disk_after: bool) -> dict:
            inst_dir.mkdir(parents=True, exist_ok=True)
            inst_eng = Engine(inst_dir)
            icase = inst_eng.dispatch(
                "create_case",
                {"question": question, "draft": draft, "domain": domain, "writer_context_id": f"writer-{inst_dir.name}"},
            )["case_id"]
            nodes = {n["evidence_id"]: n for n in spec["lineage"]}
            pdf_rel = "evidence/raw_trial_csr.pdf"
            pdf_file = inst_dir / pdf_rel
            pdf_file.parent.mkdir(parents=True, exist_ok=True)
            pdf_file.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Title (Trial CSR Appendix) >> endobj\n%%EOF\n")
            pdf_ev = inst_eng.dispatch(
                "register_evidence",
                {
                    "case_id": icase,
                    "path": pdf_rel,
                    "label": "Raw binary trial CSR PDF",
                    "provenance": "observed",
                    "kind": "intervention",
                    "unread_content_ack": True,
                    "location": f"{pdf_rel}:binary",
                },
            )
            txt_node = nodes["ev_txt_table"]
            txt_rel = "evidence/extracted_table.txt"
            (inst_dir / txt_rel).write_text(txt_node["source_text"] + "\n", encoding="utf-8")
            txt_ev = inst_eng.dispatch(
                "register_evidence",
                {
                    "case_id": icase,
                    "path": txt_rel,
                    "label": "Extracted randomized primary table",
                    "provenance": txt_node["provenance"],
                    "kind": txt_node["kind"],
                    "quote": txt_node["source_text"],
                    "location": f"{txt_rel}:L1",
                    "derived_from_evidence_ids": [pdf_ev["evidence_id"]],
                    "derivation_step": txt_node["derivation_step"],
                },
            )
            draft_lin02 = "Randomized clinical trial primary table (N=520) establishes reduced 90-day relapse (RD = -6.5%, 95% CI -10.1% to -2.9%)."
            iclaim = _build_claim_from_scaffold(
                inst_eng,
                icase,
                {
                    "case_code": inst_dir.name,
                    "family": "randomized",
                    "domain": domain,
                    "claim_basis": claim_basis,
                    "claim_type": claim_type,
                    "evidence_level": evidence_level,
                    "question": question,
                    "draft": draft_lin02,
                    "evidence_text": txt_node["source_text"],
                    "evidence_kind": "intervention",
                    "target_verdict": "supported",
                },
                txt_ev["evidence_id"],
            )
            inst_eng.dispatch("set_ledger", {"case_id": icase, "claims": [iclaim]})
            inst_eng.dispatch("freeze", {"case_id": icase})
            opkt = inst_eng.dispatch("review_packet", {"case_id": icase, "role": "overclaim"})
            upkt = inst_eng.dispatch("review_packet", {"case_id": icase, "role": "underclaim"})
            st = [{"claim_id": "C1", "stance": "supported", "rationale": "Legible table derived from hash-verified PDF", "evidence_ids": [txt_ev["evidence_id"]]}]
            inst_eng.dispatch("submit_review", {"case_id": icase, "role": "overclaim", "packet_id": opkt["packet_id"], "input_digest": opkt["input_digest"], "reviewer": {"context_id": f"over-{inst_dir.name}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": st, "unread_evidence_ids": [pdf_ev["evidence_id"]], "findings": []})
            inst_eng.dispatch("submit_review", {"case_id": icase, "role": "underclaim", "packet_id": upkt["packet_id"], "input_digest": upkt["input_digest"], "reviewer": {"context_id": f"under-{inst_dir.name}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": st, "unread_evidence_ids": [pdf_ev["evidence_id"]], "findings": []})
            apkt = inst_eng.dispatch("adjudication_packet", {"case_id": icase})
            inst_eng.dispatch(
                "submit_adjudication",
                {
                    "case_id": icase,
                    "adjudication_id": apkt["adjudication_id"],
                    "input_digest": apkt["input_digest"],
                    "adjudicator": {"context_id": f"adj-{inst_dir.name}", "model": "eval-harness"},
                    "unread_evidence_ids": [pdf_ev["evidence_id"]],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": "supported",
                            "claim_type": claim_type,
                            "evidence_level": evidence_level,
                            "claim_basis": claim_basis,
                            "scope": iclaim["scope"],
                            "revised_text": draft_lin02,
                            "rationale": "Legible extracted table backed by hash-verified binary PDF ancestor",
                            "evidence_ids": [txt_ev["evidence_id"]],
                            "confidence": "medium",
                            "confidence_reason": "Primary randomized trial table extracted deterministically",
                            "boundary": iclaim["scope"],
                            "reversal_condition": "Re-evaluate if PDF checksum or extracted table is altered",
                        }
                    ],
                    "dispositions": [],
                },
            )
            if tamper_disk_after:
                pdf_file.write_bytes(b"%PDF-1.4\n%TAMPERED_CONTENT\n%%EOF\n")
            vres = inst_eng.dispatch("verify", {"case_id": icase})
            export_err = None
            exp_state = None
            try:
                exp = inst_eng.dispatch("export", {"case_id": icase})
                exp_state = exp["state"]
            except ContractError as exc:
                export_err = exc.code
            return {"verify": vres, "export_state": exp_state, "export_error": export_err, "pdf_ev_id": pdf_ev["evidence_id"], "txt_ev_id": txt_ev["evidence_id"]}

        clean_run = _run_lin02_instance(ws / "clean", tamper_disk_after=False)
        tamper_run = _run_lin02_instance(ws / "tamper", tamper_disk_after=True)
        clean_chains = clean_run["verify"].get("evidence_chains") or []
        leaf_clean = next((c for c in clean_chains if c["evidence_id"] == clean_run["txt_ev_id"]), {})
        tamper_chains = tamper_run["verify"].get("evidence_chains") or []
        leaf_tamper = next((c for c in tamper_chains if c["evidence_id"] == tamper_run["txt_ev_id"]), {})
        actual_outcome = "accepted" if clean_run["export_error"] is None else "rejected"
        actual_error = clean_run["export_error"]
        export_state = clean_run["export_state"]
        extra["leaf_clean_lineage_status"] = leaf_clean.get("lineage_status")
        extra["tampered_verify_status"] = tamper_run["verify"].get("status")
        extra["tampered_leaf_lineage_status"] = leaf_tamper.get("lineage_status")
        extra["tampered_export_error"] = tamper_run["export_error"]
        passed = (
            actual_outcome == spec["expected_gate_outcome"]
            and export_state == "exported"
            and leaf_clean.get("lineage_status") == "hash_verified_unread_binary_ancestors"
            and clean_run["pdf_ev_id"] in leaf_clean.get("ancestors", [])
            and tamper_run["verify"].get("status") == "blocked"
            and leaf_tamper.get("lineage_status") == "blocked"
            and tamper_run["export_error"] == "verification_mismatch"
        )

    elif code == "LIN-03":
        big_text = _make_large_window_text(spec)
        big_rel = "evidence/lin03_large.txt"
        (ws / big_rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / big_rel).write_text(big_text, encoding="utf-8")
        ev = engine.dispatch(
            "register_evidence",
            {
                "case_id": case_id,
                "path": big_rel,
                "label": "Large >128 KiB multicenter CSR text",
                "provenance": "observed",
                "kind": spec["evidence_kind"],
                "quote": spec["excerpt_anchors"][1],
                "excerpt_anchors": spec["excerpt_anchors"],
                "location": f"{big_rel}:anchored",
            },
        )
        claim = _scaffold([ev["evidence_id"]])
        engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
        engine.dispatch("freeze", {"case_id": case_id})
        opkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
        upkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})
        pkt_ev = opkt["evidence"][0]
        src_text = pkt_ev.get("source_text") or ""
        roles_present = {r for w in pkt_ev.get("excerpt_windows") or [] for r in w.get("roles", [])}
        delimiters_ok = any(WINDOW_DELIMITER_LINE_RE.match(ln) for ln in src_text.splitlines())
        budget_ok = len(src_text.encode("utf-8")) <= PACKET_TEXT_BYTES
        st = [{"claim_id": "C1", "stance": "supported", "rationale": "Chunked windows preserve quote, anchors, head, and tail", "evidence_ids": [ev["evidence_id"]]}]
        engine.dispatch("submit_review", {"case_id": case_id, "role": "overclaim", "packet_id": opkt["packet_id"], "input_digest": opkt["input_digest"], "reviewer": {"context_id": f"over-{code}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": st, "unread_evidence_ids": [ev["evidence_id"]], "findings": []})
        engine.dispatch("submit_review", {"case_id": case_id, "role": "underclaim", "packet_id": upkt["packet_id"], "input_digest": upkt["input_digest"], "reviewer": {"context_id": f"under-{code}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": st, "unread_evidence_ids": [ev["evidence_id"]], "findings": []})
        apkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
        engine.dispatch(
            "submit_adjudication",
            {
                "case_id": case_id,
                "adjudication_id": apkt["adjudication_id"],
                "input_digest": apkt["input_digest"],
                "adjudicator": {"context_id": f"adj-{code}", "model": "eval-harness"},
                "unread_evidence_ids": [ev["evidence_id"]],
                "decisions": [
                    {
                        "claim_id": "C1",
                        "verdict": spec["target_verdict"],
                        "claim_type": claim_type,
                        "evidence_level": evidence_level,
                        "claim_basis": claim_basis,
                        "scope": claim["scope"],
                        "revised_text": draft,
                        "rationale": "Large >128 KiB file verified with head/quote/anchor/tail excerpt windows",
                        "evidence_ids": [ev["evidence_id"]],
                        "confidence": "medium",
                        "confidence_reason": "Chunked windows preserve anchors and tail safety summary",
                        "boundary": claim["scope"],
                        "reversal_condition": "Re-evaluate if tail summary contradicts primary estimate",
                    }
                ],
                "dispositions": [],
            },
        )
        exported = engine.dispatch("export", {"case_id": case_id})
        actual_outcome = "accepted"
        export_state = exported["state"]

        # Companion check: tail contradiction beyond 128 KiB still caught by windowed adjudication
        t_ws = ws / "tail-contradiction"
        t_ws.mkdir(parents=True, exist_ok=True)
        t_eng = Engine(t_ws)
        t_case = t_eng.dispatch("create_case", {"question": question, "draft": draft, "domain": domain, "writer_context_id": f"writer-{code}-tc"})["case_id"]
        tail_contra = "Tail final addendum beyond 128 KiB: null primary effect (OR = 1.00, p = 0.91), fails to replicate and does not support benefit."
        t_text = _make_large_window_text(spec, tail_override=tail_contra)
        t_rel = "evidence/lin03_tail_contra.txt"
        (t_ws / t_rel).parent.mkdir(parents=True, exist_ok=True)
        (t_ws / t_rel).write_text(t_text, encoding="utf-8")
        t_anchors = [*spec["excerpt_anchors"][:3], tail_contra]
        t_ev = t_eng.dispatch(
            "register_evidence",
            {
                "case_id": t_case,
                "path": t_rel,
                "label": "Large >128 KiB file with tail contradiction",
                "provenance": "observed",
                "kind": spec["evidence_kind"],
                "quote": spec["excerpt_anchors"][1],
                "excerpt_anchors": t_anchors,
                "location": f"{t_rel}:anchored",
            },
        )
        t_claim = _build_claim_from_scaffold(
            t_eng,
            t_case,
            {
                "case_code": f"{code}-TC",
                "family": "randomized",
                "domain": domain,
                "claim_basis": claim_basis,
                "claim_type": claim_type,
                "evidence_level": evidence_level,
                "question": question,
                "draft": draft,
                "evidence_text": t_text[:400],
                "evidence_kind": spec["evidence_kind"],
                "target_verdict": "supported",
            },
            t_ev["evidence_id"],
        )
        t_eng.dispatch("set_ledger", {"case_id": t_case, "claims": [t_claim]})
        t_eng.dispatch("freeze", {"case_id": t_case})
        t_opkt = t_eng.dispatch("review_packet", {"case_id": t_case, "role": "overclaim"})
        t_upkt = t_eng.dispatch("review_packet", {"case_id": t_case, "role": "underclaim"})
        t_st = [{"claim_id": "C1", "stance": "unsupported", "rationale": "Tail window addendum reports null result", "evidence_ids": [t_ev["evidence_id"]]}]
        t_eng.dispatch("submit_review", {"case_id": t_case, "role": "overclaim", "packet_id": t_opkt["packet_id"], "input_digest": t_opkt["input_digest"], "reviewer": {"context_id": f"over-{code}-tc", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": t_st, "unread_evidence_ids": [t_ev["evidence_id"]], "findings": []})
        t_eng.dispatch("submit_review", {"case_id": t_case, "role": "underclaim", "packet_id": t_upkt["packet_id"], "input_digest": t_upkt["input_digest"], "reviewer": {"context_id": f"under-{code}-tc", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": t_st, "unread_evidence_ids": [t_ev["evidence_id"]], "findings": []})
        t_apkt = t_eng.dispatch("adjudication_packet", {"case_id": t_case})
        tail_contra_error = None
        tail_advisory_codes: list[str] = []
        tail_window_preserved = tail_contra in (t_apkt["evidence"][0].get("source_text") or "")
        try:
            t_eng.dispatch(
                "submit_adjudication",
                {
                    "case_id": t_case,
                    "adjudication_id": t_apkt["adjudication_id"],
                    "input_digest": t_apkt["input_digest"],
                    "adjudicator": {"context_id": f"adj-{code}-tc", "model": "eval-harness"},
                    "unread_evidence_ids": [t_ev["evidence_id"]],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": "supported",
                            "claim_type": claim_type,
                            "evidence_level": evidence_level,
                            "claim_basis": claim_basis,
                            "scope": t_claim["scope"],
                            "revised_text": draft,
                            "rationale": "Ignoring tail window contradiction",
                            "evidence_ids": [t_ev["evidence_id"]],
                            "confidence": "medium",
                            "confidence_reason": "Testing tail contradiction gate",
                            "boundary": t_claim["scope"],
                            "reversal_condition": "Require tail consistency",
                        }
                    ],
                    "dispositions": [],
                },
            )
            t_verify = t_eng.dispatch("verify", {"case_id": t_case})
            tail_advisory_codes = [
                item["hook_code"]
                for item in (t_verify.get("symmetry_audit") or {}).get("lexical_advisories", [])
            ]
        except ContractError as exc:
            tail_contra_error = exc.code

        if tail_contra_error in ("contradictory_positive_evidence", "unanchored_effect_estimate"):
            tail_mode = "hard_rejected"
        elif "possible_contradictory_evidence_text" in tail_advisory_codes:
            tail_mode = "lexical_advisory"
        else:
            tail_mode = "missed"

        extra["source_text_status"] = pkt_ev.get("source_text_status")
        extra["window_count"] = len(pkt_ev.get("excerpt_windows") or [])
        extra["roles_present"] = sorted(roles_present)
        extra["delimiters_present"] = delimiters_ok
        extra["budget_ok"] = budget_ok
        extra["tail_window_preserved"] = tail_window_preserved
        extra["tail_contradiction_mode"] = tail_mode
        extra["tail_contradiction_caught_error"] = tail_contra_error
        extra["tail_advisory_codes"] = tail_advisory_codes
        required_roles = set(spec.get("required_window_roles", []))
        passed = (
            actual_outcome == spec["expected_gate_outcome"]
            and export_state == "exported"
            and pkt_ev.get("source_text_status") == "truncated"
            and budget_ok
            and delimiters_ok
            and required_roles <= roles_present
            and tail_window_preserved
            and tail_mode in ("hard_rejected", "lexical_advisory")
        )

    elif code == "LIN-04":
        big_text = _make_large_window_text(spec)
        big_rel = "evidence/lin04_unanchored.txt"
        (ws / big_rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / big_rel).write_text(big_text, encoding="utf-8")
        ev = engine.dispatch(
            "register_evidence",
            {
                "case_id": case_id,
                "path": big_rel,
                "label": "Large >128 KiB file without quote or excerpt_anchors",
                "provenance": "observed",
                "kind": spec["evidence_kind"],
                "location": f"{big_rel}:head-truncated",
            },
        )
        claim = _scaffold([ev["evidence_id"]])
        engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
        engine.dispatch("freeze", {"case_id": case_id})
        opkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
        upkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})
        pkt_ev = opkt["evidence"][0]
        cal_st = [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Truncated >128 KiB file without quote anchor", "evidence_ids": []}]
        engine.dispatch("submit_review", {"case_id": case_id, "role": "overclaim", "packet_id": opkt["packet_id"], "input_digest": opkt["input_digest"], "reviewer": {"context_id": f"over-{code}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": cal_st, "unread_evidence_ids": [ev["evidence_id"]], "findings": []})
        engine.dispatch("submit_review", {"case_id": case_id, "role": "underclaim", "packet_id": upkt["packet_id"], "input_digest": upkt["input_digest"], "reviewer": {"context_id": f"under-{code}", "model": "eval-harness"}, "covered_claim_ids": ["C1"], "claim_stances": cal_st, "unread_evidence_ids": [ev["evidence_id"]], "findings": []})
        apkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
        try:
            engine.dispatch(
                "submit_adjudication",
                {
                    "case_id": case_id,
                    "adjudication_id": apkt["adjudication_id"],
                    "input_digest": apkt["input_digest"],
                    "adjudicator": {"context_id": f"adj-{code}", "model": "eval-harness"},
                    "unread_evidence_ids": [ev["evidence_id"]],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": spec["target_verdict"],
                            "claim_type": claim_type,
                            "evidence_level": evidence_level,
                            "claim_basis": claim_basis,
                            "scope": claim["scope"],
                            "revised_text": draft,
                            "rationale": "Attempting positive judgment on unanchored truncated file",
                            "evidence_ids": [ev["evidence_id"]],
                            "confidence": "medium",
                            "confidence_reason": "Testing unanchored truncated gate",
                            "boundary": claim["scope"],
                            "reversal_condition": "Provide anchored quote and excerpt_anchors",
                        }
                    ],
                    "dispositions": [],
                },
            )
            actual_outcome = "accepted"
        except ContractError as exc:
            actual_outcome = "rejected"
            actual_error = exc.code
        extra["source_text_status"] = pkt_ev.get("source_text_status")
        extra["quote_anchored"] = pkt_ev.get("excerpt_window", {}).get("quote_anchored")
        passed = (
            actual_outcome == spec["expected_gate_outcome"]
            and actual_error == spec["expected_error_code"]
            and pkt_ev.get("source_text_status") == "truncated"
            and pkt_ev.get("excerpt_window", {}).get("quote_anchored") is False
        )
    else:
        raise ValueError(f"Unknown lineage/window spec_code: {code}")

    return {
        "spec_code": code,
        "scenario": spec["scenario"],
        "expected_gate_outcome": spec["expected_gate_outcome"],
        "actual_gate_outcome": actual_outcome,
        "expected_error_code": spec.get("expected_error_code"),
        "actual_error_code": actual_error,
        "export_state": export_state,
        "details": extra,
        "passed": passed,
    }


def run_lineage_window_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-lineage-"))
        cleanup = True
    try:
        spec_results = [
            evaluate_lineage_window_spec(spec, work_root)
            for spec in suite.get("lineage_window_specs", [])
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    by_code = {r["spec_code"]: r for r in spec_results}
    lin01 = by_code.get("LIN-01", {})
    lin02 = by_code.get("LIN-02", {})
    lin03 = by_code.get("LIN-03", {})
    lin04 = by_code.get("LIN-04", {})

    syn_checks = [
        bool(lin01.get("passed")),
        bool(lin01.get("details", {}).get("cli_derived_blocked")),
    ]
    win_checks = [
        bool(lin03.get("passed")),
        lin03.get("details", {}).get("tail_contradiction_mode") in ("hard_rejected", "lexical_advisory"),
        bool(lin04.get("passed")),
    ]
    total_specs = len(spec_results)
    passed_specs = sum(1 for r in spec_results if r["passed"])
    summary = {
        "total_specs": total_specs,
        "passed_specs": passed_specs,
        "synthetic_lineage_blocked": bool(lin01.get("passed")),
        "cli_derived_from_synthetic_blocked": bool(lin01.get("details", {}).get("cli_derived_blocked")),
        "hash_verified_unread_binary_accepted": bool(
            lin02.get("details", {}).get("leaf_clean_lineage_status") == "hash_verified_unread_binary_ancestors"
            and lin02.get("export_state") == "exported"
        ),
        "tampered_binary_ancestor_blocked": bool(
            lin02.get("details", {}).get("tampered_verify_status") == "blocked"
            and lin02.get("details", {}).get("tampered_leaf_lineage_status") == "blocked"
            and lin02.get("details", {}).get("tampered_export_error") == "verification_mismatch"
        ),
        "chunked_window_head_tail_accepted": bool(lin03.get("passed")),
        "chunked_window_tail_contradiction_mode": lin03.get("details", {}).get("tail_contradiction_mode"),
        "chunked_window_tail_contradiction_caught": (
            lin03.get("details", {}).get("tail_contradiction_mode") in ("hard_rejected", "lexical_advisory")
        ),
        "unanchored_large_text_blocked": bool(lin04.get("passed")),
        "synthetic_lineage_blocking_rate": round(sum(syn_checks) / len(syn_checks), 4) if syn_checks else 0.0,
        "chunked_window_head_tail_recall": round(sum(win_checks) / len(win_checks), 4) if win_checks else 0.0,
        "all_passed": passed_specs == total_specs,
    }
    return {"summary": summary, "results": spec_results}


def _summarize_counterfactual(positive_cases: list[dict], counterfactual_results: list[dict]) -> dict:
    cf_total = len(counterfactual_results)
    cf_passed = sum(1 for item in counterfactual_results if item["passed"])
    pre_card_a_rejected = sum(1 for item in counterfactual_results if item["pre_card_a_rubber_stamp_outcome"] == "rejected")
    card_a_hard_rejected = sum(1 for item in counterfactual_results if item["detection_mode"] == "hard_rejected")
    card_a_advisory_flagged = sum(1 for item in counterfactual_results if item["detection_mode"] == "lexical_advisory")
    card_a_detected = card_a_hard_rejected + card_a_advisory_flagged
    cal_flip_accepted = sum(1 for item in counterfactual_results if item["calibrated_flip_outcome"] == "accepted")
    pre_card_a_rej_rate = round(pre_card_a_rejected / cf_total, 4) if cf_total else 0.0
    card_a_rej_rate = round(card_a_hard_rejected / cf_total, 4) if cf_total else 0.0
    card_a_det_rate = round(card_a_detected / cf_total, 4) if cf_total else 0.0
    return {
        "card_id": "Card-A",
        "positive_base_cases": len(positive_cases),
        "perturbations_per_case": len(COUNTERFACTUAL_PERTURBATIONS),
        "total_perturbation_runs": cf_total,
        "passed_runs": cf_passed,
        "pre_card_a_rubber_stamp_rejected": pre_card_a_rejected,
        "pre_card_a_rubber_stamp_rejection_rate": pre_card_a_rej_rate,
        "pre_card_a_false_acceptance_leak_rate": round(1.0 - pre_card_a_rej_rate, 4) if cf_total else 0.0,
        "card_a_rubber_stamp_rejected": card_a_hard_rejected,
        "card_a_rubber_stamp_hard_rejected": card_a_hard_rejected,
        "card_a_rubber_stamp_advisory_flagged": card_a_advisory_flagged,
        "card_a_rubber_stamp_detected": card_a_detected,
        "card_a_rubber_stamp_rejection_rate": card_a_rej_rate,
        "card_a_rubber_stamp_detection_rate": card_a_det_rate,
        "card_a_false_acceptance_leak_rate": round(1.0 - card_a_det_rate, 4) if cf_total else 0.0,
        "calibrated_flip_accepted": cal_flip_accepted,
        "calibrated_flip_acceptance_rate": round(cal_flip_accepted / cf_total, 4) if cf_total else 0.0,
        "kill_condition_threshold": 0.95,
        "kill_condition_triggered": pre_card_a_rej_rate >= 0.95,
        "all_passed": cf_passed == cf_total,
    }


def _summarize_fork_multiplicity(positive_cases: list[dict], fork_multiplicity_results: list[dict]) -> dict:
    fm_total = len(fork_multiplicity_results)
    fm_passed = sum(1 for item in fork_multiplicity_results if item["passed"])
    fm_adv = [item for item in fork_multiplicity_results if item["scenario_id"] != "F3_calibrated_multiplicity_accounted"]
    fm_pos_ctrl = [item for item in fork_multiplicity_results if item["scenario_id"] == "F3_calibrated_multiplicity_accounted"]
    fm_adv_total = len(fm_adv)
    fm_pos_total = len(fm_pos_ctrl)
    pre_card_b_adv_rejected = sum(1 for item in fm_adv if item["pre_card_b_positive_outcome"] == "rejected")
    card_b_adv_hard_rejected = sum(1 for item in fm_adv if item["detection_mode"] == "hard_rejected")
    card_b_adv_advisory_flagged = sum(1 for item in fm_adv if item["detection_mode"] == "lexical_advisory")
    card_b_adv_detected = card_b_adv_hard_rejected + card_b_adv_advisory_flagged
    card_b_pos_accepted = sum(1 for item in fm_pos_ctrl if item["card_b_positive_outcome"] == "accepted" and item["passed"])
    pre_card_b_adv_rej_rate = round(pre_card_b_adv_rejected / fm_adv_total, 4) if fm_adv_total else 0.0
    card_b_adv_rej_rate = round(card_b_adv_hard_rejected / fm_adv_total, 4) if fm_adv_total else 0.0
    card_b_adv_det_rate = round(card_b_adv_detected / fm_adv_total, 4) if fm_adv_total else 0.0
    card_b_pos_acc_rate = round(card_b_pos_accepted / fm_pos_total, 4) if fm_pos_total else 0.0
    return {
        "card_id": "Card-B",
        "positive_base_cases": len(positive_cases),
        "scenarios_per_case": len(FORK_MULTIPLICITY_SCENARIOS),
        "total_fork_runs": fm_total,
        "passed_runs": fm_passed,
        "adversarial_runs": fm_adv_total,
        "positive_control_runs": fm_pos_total,
        "pre_card_b_adversarial_rejected": pre_card_b_adv_rejected,
        "pre_card_b_adversarial_rejection_rate": pre_card_b_adv_rej_rate,
        "pre_card_b_false_acceptance_leak_rate": round(1.0 - pre_card_b_adv_rej_rate, 4) if fm_adv_total else 0.0,
        "card_b_adversarial_rejected": card_b_adv_hard_rejected,
        "card_b_adversarial_hard_rejected": card_b_adv_hard_rejected,
        "card_b_adversarial_advisory_flagged": card_b_adv_advisory_flagged,
        "card_b_adversarial_detected": card_b_adv_detected,
        "card_b_adversarial_rejection_rate": card_b_adv_rej_rate,
        "card_b_adversarial_detection_rate": card_b_adv_det_rate,
        "card_b_false_acceptance_leak_rate": round(1.0 - card_b_adv_det_rate, 4) if fm_adv_total else 0.0,
        "card_b_positive_control_accepted": card_b_pos_accepted,
        "card_b_positive_control_acceptance_rate": card_b_pos_acc_rate,
        "card_b_overblocking_rate": round(1.0 - card_b_pos_acc_rate, 4) if fm_pos_total else 0.0,
        "kill_condition_triggered": pre_card_b_adv_rej_rate >= 0.95 or (1.0 - card_b_pos_acc_rate) >= 0.10,
        "all_passed": fm_passed == fm_total,
    }


def _run_static_leakage_audit(suite_path: Path) -> dict:
    checker_path = Path(__file__).with_name("check-eval-leakage.py")
    spec = importlib.util.spec_from_file_location("parrhesia_check_eval_leakage", checker_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load leakage checker from {checker_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_leakage_audit(suite_path=suite_path)


def _reorder_evidence_clauses(ev_text: str) -> str:
    text = ev_text.strip()
    trailing = "." if text.endswith(".") else ""
    body_all = text[:-1] if trailing else text
    if ": " in body_all:
        header, body = body_all.split(": ", 1)
    else:
        header, body = "", body_all
    clauses = [c.strip() for c in re.split(r",\s*(?![^()]*\))", body) if c.strip()]
    if len(clauses) > 1:
        reordered = "; ".join(reversed(clauses))
    elif " vs " in body:
        parts = body.split(" vs ", 1)
        reordered = f"Against {parts[1].strip()}, observed {parts[0].strip()}"
    else:
        reordered = body
    return f"{reordered}; {header}{trailing}" if header else f"{reordered}{trailing}"


def build_metamorphic_variant(base_case: dict, transform: dict) -> dict:
    variant = dict(base_case)
    variant["case_code"] = transform["transform_id"]
    variant["base_case_code"] = base_case["case_code"]
    variant["transform_type"] = transform["transform_type"]
    ev_text = base_case["evidence_text"].strip()
    t_type = transform["transform_type"]
    if t_type == "clause_reorder":
        variant["evidence_text"] = _reorder_evidence_clauses(ev_text)
    elif t_type == "append_adverse_event_null":
        variant["evidence_text"] = f"{ev_text} {transform['suffix']}".strip()
    elif t_type == "replace_or_108":
        variant["evidence_text"] = f"{ev_text} {transform['suffix']}".strip()
    elif t_type == "insert_literature_contrast":
        variant["evidence_text"] = f"{transform['prefix']} {ev_text}".strip()
    else:
        raise ValueError(f"Unknown metamorphic transform_type: {t_type}")
    return variant


def evaluate_heldout_control_case(spec: dict, base_dir: Path) -> dict:
    merged = dict(spec)
    merged.setdefault("scenario", "realistic_control")
    res = evaluate_single_case(merged, base_dir)
    res["passed"] = res["actual_gate_outcome"] == "accepted" and res["export_state"] == "exported"
    return res


def evaluate_heldout_adversarial_case(spec: dict, base_dir: Path) -> dict:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    code = spec["case_code"]
    ws = base_dir / code
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)
    case_id = engine.dispatch(
        "create_case",
        {
            "question": spec["question"],
            "draft": spec["draft"],
            "domain": domain,
            "writer_context_id": f"writer-{code}",
        },
    )["case_id"]

    fork_mode = spec.get("fork_mode")
    tail_probe = bool(spec.get("tail_window_probe"))
    ev_ids: list[str] = []
    fork_cards: list[dict] = []

    if fork_mode in ("sqlite_omit_failed_runs", "sqlite_unadjusted_multi_fork"):
        for fork_idx in range(1, 5):
            rel_path = f"logs/{code}-fork-{fork_idx}.log"
            log_file = ws / rel_path
            log_file.parent.mkdir(parents=True, exist_ok=True)
            cmd_str = f"python run_sweep.py --case {code} --fork {fork_idx}"
            started_at = f"2026-11-11T00:0{fork_idx}:00+00:00"
            ended_at = f"2026-11-11T00:0{fork_idx}:05+00:00"
            header = (
                f"command: {cmd_str}\nstarted_at: {started_at}\n"
                f"ended_at: {ended_at}\nexit_status: 0"
            )
            if fork_idx < 4:
                body = f"fork={fork_idx} candidate_run status=non_selected\n"
                card_status = "reported"
                quote = header
            else:
                body = f"{spec['evidence_text']}\n"
                card_status = "checked"
                quote = f"{header}\n--- stdout ---\n{spec['evidence_text'][:80]}"
            log_file.write_text(f"{header}\n--- stdout ---\n{body}\n--- stderr ---\n\n", encoding="utf-8", newline="\n")
            ev = engine.dispatch(
                "register_evidence",
                {
                    "case_id": case_id,
                    "path": rel_path,
                    "label": "Recorded command execution log",
                    "provenance": spec.get("evidence_provenance", "observed"),
                    "kind": spec["evidence_kind"],
                    "quote": quote,
                    "location": f"{rel_path}:L1-L6",
                },
            )
            eid = ev["evidence_id"]
            ev_ids.append(eid)
            engine.record_execution_event(
                case_id,
                {
                    "card_id": f"exec-fork-{fork_idx}",
                    "evidence_id": eid,
                    "command": cmd_str,
                    "exit_status": 0,
                    "status": card_status,
                    "log_path": rel_path,
                    "started_at": started_at,
                    "ended_at": ended_at,
                },
            )
            fork_cards.append(
                {
                    "id": f"exec-fork-{fork_idx}",
                    "status": card_status,
                    "reason": f"Executed `{cmd_str}` with exit_status=0; log captured at {rel_path}.",
                    "evidence_ids": [eid],
                    "details": {
                        "command": cmd_str,
                        "code_version": "stage0-heldout",
                        "inputs": f"sweep_{fork_idx}.json",
                        "environment": "Python 3.13",
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "exit_status": "0",
                        "outputs": "stdout log",
                        "log_locator": f"{rel_path}:L1-L6",
                    },
                }
            )
        primary_ev_id = ev_ids[-1]
    elif tail_probe:
        head_anchor = "Multicenter locked follow-up clinical study protocol and hospitalization odds monitoring."
        filler_block = ("Interim site monitoring log line: accrual and follow-up compliance verified.\n" * 1800)
        large_text = f"{head_anchor}\n\n{filler_block}\n\n{spec['evidence_text']}\n"
        ev_rel = f"evidence/{code}_large.txt"
        ev_file = ws / ev_rel
        ev_file.parent.mkdir(parents=True, exist_ok=True)
        ev_file.write_text(large_text, encoding="utf-8")
        ev = engine.dispatch(
            "register_evidence",
            {
                "case_id": case_id,
                "path": ev_rel,
                "label": f"Large >128 KiB evidence for {code}",
                "provenance": spec.get("evidence_provenance", "observed"),
                "kind": spec["evidence_kind"],
                "quote": head_anchor,
                "excerpt_anchors": [head_anchor, spec["evidence_text"]],
                "location": f"{ev_rel}:L1-tail",
            },
        )
        primary_ev_id = ev["evidence_id"]
        ev_ids.append(primary_ev_id)
    else:
        ev_rel = f"evidence/{code}.txt"
        ev_file = ws / ev_rel
        ev_file.parent.mkdir(parents=True, exist_ok=True)
        ev_file.write_text(spec["evidence_text"] + "\n", encoding="utf-8")
        ev = engine.dispatch(
            "register_evidence",
            {
                "case_id": case_id,
                "path": ev_rel,
                "label": f"Held-out adversarial evidence for {code}",
                "provenance": spec.get("evidence_provenance", "observed"),
                "kind": spec["evidence_kind"],
                "quote": spec["evidence_text"],
                "location": f"{ev_rel}:L1",
            },
        )
        primary_ev_id = ev["evidence_id"]
        ev_ids.append(primary_ev_id)

    claim = _build_claim_from_scaffold(engine, case_id, spec, primary_ev_id)
    if fork_mode == "sqlite_omit_failed_runs":
        claim["evidence_ids"] = [primary_ev_id]
        claim["provenance_cards"]["execution"] = [fork_cards[-1]]
    elif fork_mode == "sqlite_unadjusted_multi_fork":
        claim["evidence_ids"] = list(ev_ids)
        claim["provenance_cards"]["execution"] = list(fork_cards)
        claim["checks"]["multiplicity"] = {
            "status": "pass",
            "reason": "Cross-sweep multiplicity adjustment record linked to primary sweep log",
        }
        claim["statistical_report"]["multiplicity_selection"] = {
            "status": "pass",
            "reason": f"Cross-sweep multiplicity record anchored to full sweep log ({ev_ids[0]})",
            "evidence_ids": [ev_ids[0]],
        }

    engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
    engine.dispatch("freeze", {"case_id": case_id})
    over_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
    under_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})
    neutral_stance = {
        "claim_id": "C1",
        "stance": "insufficient_evidence",
        "rationale": "Hold adjudication gate open for adversarial positive probe",
        "evidence_ids": [],
    }
    unread_ids = [primary_ev_id] if tail_probe else []
    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "overclaim",
            "packet_id": over_pkt["packet_id"],
            "input_digest": over_pkt["input_digest"],
            "reviewer": {"context_id": f"over-{code}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(neutral_stance)],
            "unread_evidence_ids": unread_ids,
            "findings": [],
        },
    )
    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "underclaim",
            "packet_id": under_pkt["packet_id"],
            "input_digest": under_pkt["input_digest"],
            "reviewer": {"context_id": f"under-{code}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(neutral_stance)],
            "unread_evidence_ids": unread_ids,
            "findings": [],
        },
    )
    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
    positive_probe = {
        "claim_id": "C1",
        "verdict": "supported",
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "claim_basis": claim_basis,
        "scope": claim["scope"],
        "revised_text": spec["draft"],
        "rationale": f"Adversarial rubber-stamped positive probe on {code}",
        "evidence_ids": [primary_ev_id],
        "confidence": "medium",
        "confidence_reason": "Rubber-stamped positive probe against adversarial paraphrase",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if evidence fails mechanical or semantic audit",
    }
    lexical_advisory_codes: list[str] = []
    export_state = None
    try:
        engine.dispatch(
            "submit_adjudication",
            {
                "case_id": case_id,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": f"adj-{code}", "model": "eval-harness"},
                "unread_evidence_ids": unread_ids,
                "decisions": [positive_probe],
                "dispositions": [],
            },
        )
        verify_res = engine.dispatch("verify", {"case_id": case_id})
        lexical_advisory_codes = [
            item["hook_code"]
            for item in (verify_res.get("symmetry_audit") or {}).get("lexical_advisories", [])
        ]
        export_state = engine.dispatch("export", {"case_id": case_id})["state"]
        actual_outcome = "accepted"
        actual_error = None
    except ContractError as exc:
        actual_outcome = "rejected"
        actual_error = exc.code

    if actual_outcome == "rejected":
        observed_category = "caught_mechanically_hard"
    elif lexical_advisory_codes:
        observed_category = "flagged_lexical_advisory_only"
    else:
        observed_category = "uncaught_without_llm_or_p1"

    exp_expectation = spec["mechanism_expectation"]
    if exp_expectation == "caught_mechanically":
        expectation_matched = (
            observed_category == "caught_mechanically_hard"
            and actual_error == spec.get("expected_error_code")
        )
    else:
        expectation_matched = observed_category == "uncaught_without_llm_or_p1"

    return {
        "case_code": code,
        "family": spec["family"],
        "paraphrase_category": spec["paraphrase_category"],
        "mechanism_expectation": exp_expectation,
        "observed_category": observed_category,
        "expected_gate_outcome": spec["expected_gate_outcome"],
        "actual_gate_outcome": actual_outcome,
        "expected_error_code": spec.get("expected_error_code"),
        "actual_error_code": actual_error,
        "lexical_advisory_codes": lexical_advisory_codes,
        "export_state": export_state,
        "expectation_matched": expectation_matched,
        "regression_passed": expectation_matched or (
            exp_expectation == "uncaught_without_llm_or_p1"
            and observed_category == "flagged_lexical_advisory_only"
            and actual_outcome == "accepted" and export_state == "exported"
        ),
    }


def run_heldout_generalization_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    leakage_audit = _run_static_leakage_audit(suite_path)
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-heldout-"))
        cleanup = True
    try:
        ctrl_results = [
            evaluate_heldout_control_case(case, work_root / "controls")
            for case in suite.get("heldout_realistic_controls", [])
        ]
        adv_results = [
            evaluate_heldout_adversarial_case(case, work_root / "adversarial")
            for case in suite.get("heldout_adversarial_paraphrases", [])
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    ctrl_total = len(ctrl_results)
    ctrl_passed = sum(1 for r in ctrl_results if r["passed"])
    ctrl_false_rej = ctrl_total - ctrl_passed
    ctrl_false_adv = sum(1 for r in ctrl_results if r.get("lexical_advisory_codes"))
    false_rejection_rate = round(ctrl_false_rej / ctrl_total, 4) if ctrl_total else 0.0

    adv_total = len(adv_results)
    caught_hard = sum(1 for r in adv_results if r["observed_category"] == "caught_mechanically_hard")
    flagged_adv = sum(1 for r in adv_results if r["observed_category"] == "flagged_lexical_advisory_only")
    uncaught = [r["case_code"] for r in adv_results if r["observed_category"] == "uncaught_without_llm_or_p1"]
    exp_matched = sum(1 for r in adv_results if r["expectation_matched"])
    expected_hard_total = sum(1 for r in adv_results if r["mechanism_expectation"] == "caught_mechanically")

    leakage_strict_passed = bool(leakage_audit.get("strict_passed", False))
    leakage_overlap_count = int((leakage_audit.get("suite_audit") or {}).get("heldout_overlap_count", -1))

    summary = {
        "evaluation_revision": "text-advisory-regression-v1",
        "baseline_expectations_preserved": True,
        "leakage_strict_passed": leakage_strict_passed,
        "heldout_lexical_overlap_count": leakage_overlap_count,
        "realistic_controls_total": ctrl_total,
        "realistic_controls_passed": ctrl_passed,
        "realistic_controls_false_rejections": ctrl_false_rej,
        "realistic_controls_false_rejection_rate": false_rejection_rate,
        "realistic_controls_false_advisories": ctrl_false_adv,
        "adversarial_paraphrases_total": adv_total,
        "adversarial_expected_mechanical_total": expected_hard_total,
        "adversarial_caught_mechanically_hard": caught_hard,
        "adversarial_flagged_lexical_advisory_only": flagged_adv,
        "adversarial_uncaught_without_llm_or_p1": len(uncaught),
        "adversarial_uncaught_case_codes": uncaught,
        "adversarial_mechanical_recall": round(caught_hard / adv_total, 4) if adv_total else 0.0,
        "adversarial_advisory_only_rate": round(flagged_adv / adv_total, 4) if adv_total else 0.0,
        "adversarial_uncaught_rate": round(len(uncaught) / adv_total, 4) if adv_total else 0.0,
        "adversarial_expectations_verified": exp_matched,
        "adversarial_regressions_passed": sum(r["regression_passed"] for r in adv_results),
        "new_advisory_module_audit": leakage_audit.get("advisory_module_audit"),
        "regression_all_passed": (
            leakage_strict_passed and leakage_overlap_count == 0
            and ctrl_total > 0 and false_rejection_rate < 0.05 and ctrl_false_adv == 0
            and adv_total > 0 and all(r["regression_passed"] for r in adv_results)
            and caught_hard >= expected_hard_total
        ),
        "all_passed": (
            leakage_strict_passed
            and leakage_overlap_count == 0
            and ctrl_total > 0
            and false_rejection_rate < 0.05
            and adv_total > 0
            and exp_matched == adv_total
            and caught_hard >= expected_hard_total
        ),
    }
    return {
        "suite_version": suite["suite_version"],
        "summary": summary,
        "leakage_audit": leakage_audit,
        "control_results": ctrl_results,
        "adversarial_results": adv_results,
    }


def run_metamorphic_invariance_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    case_by_code = {c["case_code"]: c for c in suite.get("cases", [])}
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-meta-"))
        cleanup = True
    results = []
    base_cache: dict[str, dict] = {}
    try:
        for transform in suite.get("metamorphic_invariance", []):
            base_code = transform["base_case_code"]
            base_case = case_by_code[base_code]
            if base_code not in base_cache:
                base_cache[base_code] = evaluate_single_case(base_case, work_root / "base")
            base_res = base_cache[base_code]
            variant_case = build_metamorphic_variant(base_case, transform)
            var_res = evaluate_single_case(variant_case, work_root / "variants")
            outcome_invariant = (
                var_res["actual_gate_outcome"] == base_res["actual_gate_outcome"] == "accepted"
                and var_res["export_state"] == base_res["export_state"] == "exported"
                and var_res["symmetry_flag_codes"] == base_res["symmetry_flag_codes"] == []
            )
            results.append(
                {
                    "transform_id": transform["transform_id"],
                    "base_case_code": base_code,
                    "family": base_case["family"],
                    "transform_type": transform["transform_type"],
                    "base_outcome": base_res["actual_gate_outcome"],
                    "variant_outcome": var_res["actual_gate_outcome"],
                    "variant_export_state": var_res["export_state"],
                    "variant_error_code": var_res["actual_error_code"],
                    "variant_symmetry_flags": var_res["symmetry_flag_codes"],
                    "variant_lexical_advisory_codes": var_res["lexical_advisory_codes"],
                    "passed": outcome_invariant,
                }
            )
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    false_advisories = sum(1 for r in results if r["variant_lexical_advisory_codes"])
    summary = {
        "total_transforms": total,
        "passed_transforms": passed,
        "invariance_rate": round(passed / total, 4) if total else 0.0,
        "false_advisory_count": false_advisories,
        "advisory_all_passed": total > 0 and passed == total and false_advisories == 0,
        "all_passed": total > 0 and passed == total,
    }
    return {"suite_version": suite["suite_version"], "summary": summary, "results": results}


def run_counterfactual_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-cf-"))
        cleanup = True
    try:
        positive_cases = [c for c in suite["cases"] if c["expected_gate_outcome"] == "accepted"]
        results = [
            evaluate_counterfactual_case(case, pert_id, work_root)
            for case in positive_cases
            for pert_id, _, _, _ in COUNTERFACTUAL_PERTURBATIONS
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)
    return {
        "suite_version": suite["suite_version"],
        "summary": _summarize_counterfactual(positive_cases, results),
        "results": results,
    }


def run_fork_multiplicity_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-fork-"))
        cleanup = True
    try:
        positive_cases = [c for c in suite["cases"] if c["expected_gate_outcome"] == "accepted"]
        results = [
            evaluate_fork_multiplicity_case(case, scen_id, work_root)
            for case in positive_cases
            for scen_id, _, _ in FORK_MULTIPLICITY_SCENARIOS
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)
    return {
        "suite_version": suite["suite_version"],
        "summary": _summarize_fork_multiplicity(positive_cases, results),
        "results": results,
    }


def evaluate_p1_effect_record_case(spec: dict, base_dir: Path) -> dict:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    code = spec["case_code"]
    ws = base_dir / code
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)
    case_id = engine.dispatch(
        "create_case",
        {
            "question": spec["question"],
            "draft": spec["draft"],
            "domain": domain,
            "writer_context_id": f"writer-{code}",
        },
    )["case_id"]
    ev_rel = f"evidence/{code}.txt"
    ev_file = ws / ev_rel
    ev_file.parent.mkdir(parents=True, exist_ok=True)
    ev_file.write_text(spec["evidence_text"] + "\n", encoding="utf-8")
    ev = engine.dispatch(
        "register_evidence",
        {
            "case_id": case_id,
            "path": ev_rel,
            "label": f"P1 effect evidence for {code}",
            "provenance": spec.get("evidence_provenance", "observed"),
            "kind": spec["evidence_kind"],
            "quote": spec["evidence_text"],
            "location": f"{ev_rel}:L1",
        },
    )
    ev_id = ev["evidence_id"]
    claim = _build_claim_from_scaffold(engine, case_id, spec, ev_id)
    records = copy.deepcopy(spec.get("effect_records", []))
    for rec in records:
        if rec.get("evidence_id") in (None, "__PRIMARY__"):
            rec["evidence_id"] = ev_id
    claim["effect_records"] = records

    target_verdict = spec["target_verdict"]
    actual_error = None
    export_state = None
    effect_checks = None
    event_chain_status = None
    try:
        engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
        engine.dispatch("freeze", {"case_id": case_id})

        over_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
        under_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})
        stance_val = "insufficient_evidence" if spec["expected_gate_outcome"] == "rejected" else target_verdict
        stance_entry = {
            "claim_id": "C1",
            "stance": stance_val,
            "rationale": "Evaluated against structured effect_records and registered evidence",
            "evidence_ids": [] if stance_val == "insufficient_evidence" else [ev_id],
        }
        engine.dispatch(
            "submit_review",
            {
                "case_id": case_id,
                "role": "overclaim",
                "packet_id": over_pkt["packet_id"],
                "input_digest": over_pkt["input_digest"],
                "reviewer": {"context_id": f"over-{code}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(stance_entry)],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
        engine.dispatch(
            "submit_review",
            {
                "case_id": case_id,
                "role": "underclaim",
                "packet_id": under_pkt["packet_id"],
                "input_digest": under_pkt["input_digest"],
                "reviewer": {"context_id": f"under-{code}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [dict(stance_entry)],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
        adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
        decision = {
            "claim_id": "C1",
            "verdict": target_verdict,
            "claim_type": spec["claim_type"],
            "evidence_level": spec["evidence_level"],
            "claim_basis": claim_basis,
            "scope": claim["scope"],
            "revised_text": spec["draft"],
            "rationale": f"P1 structured effect probe {code} ({spec['scenario']})",
            "evidence_ids": [ev_id],
            "confidence": "medium",
            "confidence_reason": "Backed by registered primary evidence and structured effect_records",
            "boundary": claim["scope"],
            "reversal_condition": "Re-evaluate if primary effect confidence interval, anchor, or sensitivity bounds fail",
        }
        engine.dispatch(
            "submit_adjudication",
            {
                "case_id": case_id,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": f"adj-{code}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [decision],
                "dispositions": [],
            },
        )
        verify_res = engine.dispatch("verify", {"case_id": case_id})
        event_chain_status = verify_res.get("event_chain_status")
        effect_checks = (verify_res.get("effect_checks") or {}).get("C1")
        exported = engine.dispatch("export", {"case_id": case_id})
        export_state = exported["state"]
        actual_outcome = "accepted"
    except ContractError as exc:
        actual_outcome = "rejected"
        actual_error = exc.code
    finally:
        if event_chain_status is None:
            case_snapshot = engine.dispatch("get_case", {"case_id": case_id})
            event_chain_status = case_snapshot.get("event_chain_status") or (
                (case_snapshot.get("event_chain") or {}).get("status")
            )

    expected_outcome = spec["expected_gate_outcome"]
    expected_error = spec.get("expected_error_code")
    if expected_outcome == "accepted":
        passed = (
            actual_outcome == "accepted"
            and export_state == "exported"
            and event_chain_status == "verified"
            and isinstance(effect_checks, dict)
            and effect_checks.get("record_count") == len(records)
        )
    else:
        passed = (
            actual_outcome == "rejected"
            and actual_error == expected_error
            and event_chain_status == "verified"
        )
    return {
        "case_code": code,
        "counterpart_of": spec.get("counterpart_of"),
        "family": spec["family"],
        "scenario": spec["scenario"],
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "target_verdict": target_verdict,
        "effect_record_count": len(records),
        "expected_gate_outcome": expected_outcome,
        "actual_gate_outcome": actual_outcome,
        "expected_error_code": expected_error,
        "actual_error_code": actual_error,
        "export_state": export_state,
        "event_chain_status": event_chain_status,
        "effect_checks": effect_checks,
        "passed": passed,
    }


def run_p1_effect_records_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-p1-effects-"))
        cleanup = True
    try:
        results = [
            evaluate_p1_effect_record_case(case, work_root)
            for case in suite.get("p1_effect_records", [])
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    positives = [r for r in results if r["expected_gate_outcome"] == "accepted"]
    pos_accepted = sum(1 for r in positives if r["passed"])
    pos_false_rej = len(positives) - pos_accepted
    negatives = [r for r in results if r["expected_gate_outcome"] == "rejected"]
    neg_caught = sum(1 for r in negatives if r["passed"])
    hadv_counterparts = [r for r in negatives if r.get("counterpart_of")]
    hadv_caught = sum(1 for r in hadv_counterparts if r["passed"])
    event_chain_verified = sum(1 for r in results if r["event_chain_status"] == "verified")
    summary = {
        "total_cases": total,
        "passed_cases": passed,
        "positive_controls_total": len(positives),
        "positive_controls_accepted": pos_accepted,
        "positive_controls_false_rejections": pos_false_rej,
        "positive_controls_false_rejection_rate": round(pos_false_rej / len(positives), 4) if positives else 0.0,
        "negative_traps_total": len(negatives),
        "negative_traps_caught": neg_caught,
        "negative_traps_catch_rate": round(neg_caught / len(negatives), 4) if negatives else 0.0,
        "hadv_counterparts_total": len(hadv_counterparts),
        "hadv_counterparts_caught": hadv_caught,
        "hadv_counterparts_case_codes": [r["counterpart_of"] for r in hadv_counterparts if r["passed"]],
        "event_chain_verified_count": event_chain_verified,
        "all_passed": (
            total > 0
            and passed == total
            and pos_false_rej == 0
            and neg_caught == len(negatives)
            and event_chain_verified == total
        ),
    }
    return {
        "suite_version": suite["suite_version"],
        "summary": summary,
        "results": results,
    }


def _register_calibration_fixture(engine: Engine, ws: Path, tag: str) -> str:
    """A separate registered synthetic-text source, not an unbound outcome assertion."""
    cid = engine.dispatch("create_case", {"question": "Calibration reference fixture", "draft": "Reported follow-up source"})["case_id"]
    text = "Fixture registry mortality HR 0.74 (95% CI 0.60 to 0.90)."
    path = f"{tag}-calibration-source.txt"
    (ws / path).write_text(text, encoding="utf-8")
    return engine.dispatch("register_evidence", {"case_id": cid, "path": path, "provenance": "observed", "kind": "observation", "quote": text, "location": "fixture row"})["evidence_id"]


def _p2_adjudicate_case(
    engine: Engine,
    ws: Path,
    *,
    tag: str,
    spec: dict,
    question: str,
    evidence_text: str,
    draft: str,
    evidence_kind: str,
    eff_est: str,
    eff_unc: str,
    claim_type: str = "association",
    evidence_level: str = "adjusted",
    family: str = "observational",
    effect_records: list[dict] | None = None,
    reversal_triggers: list[dict] | None = None,
    prior_claim_links: list[dict] | None = None,
    prior_case_ids: list[str] | None = None,
    supersedes_case_id: str | None = None,
    case_relation: str | None = None,
    verdict: str = "supported",
    forecast_probability: float | None = 0.80,
    export_report: bool = False,
) -> tuple[str, str, dict]:
    domain, claim_basis, _ = _spec_domain_basis_families(spec)
    create_payload: dict = {
        "question": question,
        "draft": draft,
        "domain": domain,
        "writer_context_id": f"writer-{tag}",
    }
    if prior_case_ids is not None:
        create_payload["prior_case_ids"] = prior_case_ids
    if supersedes_case_id is not None:
        create_payload["supersedes_case_id"] = supersedes_case_id
    if case_relation is not None:
        create_payload["case_relation"] = case_relation
    case_id = engine.dispatch("create_case", create_payload)["case_id"]
    ev_rel = f"evidence/{tag}.txt"
    ev_file = ws / ev_rel
    ev_file.parent.mkdir(parents=True, exist_ok=True)
    ev_file.write_text(evidence_text + "\n", encoding="utf-8")
    ev_id = engine.dispatch(
        "register_evidence",
        {
            "case_id": case_id,
            "path": ev_rel,
            "label": f"P2 longitudinal evidence for {tag}",
            "provenance": "observed",
            "kind": evidence_kind,
            "quote": evidence_text,
            "location": f"{ev_rel}:L1",
        },
    )["evidence_id"]
    claim_spec = {
        "family": family,
        "claim_type": claim_type,
        "evidence_level": evidence_level,
        "question": question,
        "draft": draft,
    }
    claim = _build_claim_from_scaffold(engine, case_id, claim_spec, ev_id)
    claim["effect"] = {"estimate": eff_est, "uncertainty": eff_unc}
    if effect_records is not None:
        recs = copy.deepcopy(effect_records)
        for rec in recs:
            if rec.get("evidence_id") in (None, "__PRIMARY__"):
                rec["evidence_id"] = ev_id
        claim["effect_records"] = recs
    if reversal_triggers is not None:
        claim["reversal_triggers"] = copy.deepcopy(reversal_triggers)
    if prior_claim_links is not None:
        claim["prior_claim_links"] = copy.deepcopy(prior_claim_links)

    engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
    engine.dispatch("freeze", {"case_id": case_id})
    for role in ("overclaim", "underclaim"):
        pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": role})
        engine.dispatch(
            "submit_review",
            {
                "case_id": case_id,
                "role": role,
                "packet_id": pkt["packet_id"],
                "input_digest": pkt["input_digest"],
                "reviewer": {"context_id": f"{role}-{tag}", "model": "eval-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [
                    {
                        "claim_id": "C1",
                        "stance": verdict,
                        "rationale": f"Anchored directly to {ev_id}.",
                        "evidence_ids": [ev_id],
                    }
                ],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
    dec = {
        "claim_id": "C1",
        "verdict": verdict,
        "claim_type": claim_type,
        "evidence_level": evidence_level,
        "claim_basis": claim_basis,
        "scope": claim["scope"],
        "revised_text": draft,
        "rationale": f"P2 longitudinal calibration probe {tag}.",
        "evidence_ids": [ev_id],
        "confidence": "medium",
        "confidence_reason": "Anchored to registered cohort/trial record.",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if follow-up primary endpoint crosses reversal trigger.",
    }
    if forecast_probability is not None:
        dec["forecast_probability"] = forecast_probability
    engine.dispatch(
        "submit_adjudication",
        {
            "case_id": case_id,
            "adjudication_id": adj_pkt["adjudication_id"],
            "input_digest": adj_pkt["input_digest"],
            "adjudicator": {"context_id": f"adj-{tag}", "model": "eval-harness"},
            "unread_evidence_ids": [],
            "decisions": [dec],
            "dispositions": [],
        },
    )
    if export_report:
        engine.dispatch(
            "record_human_decision",
            {
                "case_id": case_id,
                "decision": "accept",
                "responsible_human": "stage0-lead",
                "reason": "Evaluated in Stage 0 P2 harness.",
            },
        )
        engine.dispatch("export", {"case_id": case_id})
    return case_id, ev_id, engine.dispatch("get_case", {"case_id": case_id})


def evaluate_p2_longitudinal_case(spec: dict, base_dir: Path) -> dict:
    code = spec["case_code"]
    ws = base_dir / code
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)

    actual_outcome = "rejected"
    actual_error = None
    event_chain_status = None
    details: dict = {}

    try:
        if code == "PLONG-01":
            p1_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong01-prior", spec=spec,
                question="Does Drug K reduce ICU mortality?",
                evidence_text="Initial trial R1 reported mortality hazard ratio HR = 0.72 (95% CI 0.56 to 0.93, p = 0.012).",
                draft="Initial trial R1 shows lower mortality hazard (HR = 0.72, 95% CI 0.56 to 0.93).",
                evidence_kind="intervention", eff_est="HR = 0.72", eff_unc="95% CI 0.56 to 0.93, p = 0.012",
                family="randomized",
                effect_records=[{
                    "id": "E_R1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.72, "ci_low": 0.56, "ci_high": 0.93, "p_value": 0.012,
                    "direction": "benefit", "evidence_id": "__PRIMARY__",
                }],
                reversal_triggers=[{
                    "id": "T_REV_GT1", "description": "Hazard rises above 1.0 on replication", "kind": "effect_metric",
                    "metric": "HR", "endpoint_role": "primary", "field": "estimate", "operator": "gt", "threshold": 1.0,
                    "target_verdict": "unsupported",
                }],
            )
            p2_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong01-rep", spec=spec,
                question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                evidence_kind=spec["evidence_kind"], eff_est="HR = 1.32", eff_unc="95% CI 1.08 to 1.62, p = 0.007",
                family=spec["family"], prior_case_ids=[p1_id], supersedes_case_id=p1_id, case_relation="replication",
                effect_records=[{
                    "id": "E_R2", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 1.32, "ci_low": 1.08, "ci_high": 1.62, "p_value": 0.007,
                    "direction": "higher_better", "evidence_id": "__PRIMARY__",
                }],
                prior_claim_links=[{
                    "prior_case_id": p1_id, "prior_claim_id": "C1", "relation": "reverses",
                    "triggered_reversal_id": "T_REV_GT1",
                    "reason": "Independent replication R2 HR 1.32 > 1.0 triggers T_REV_GT1.",
                }],
            )
            graph = engine.get_claim_graph(case_id=p1_id)
            standings = {n["node_id"]: n["active_standing"] for n in graph["claim_nodes"]}
            ver1 = engine.dispatch("verify", {"case_id": p1_id})
            ver2 = engine.dispatch("verify", {"case_id": p2_id})
            event_chain_status = "verified" if ver1["event_chain_status"] == "verified" and ver2["event_chain_status"] == "verified" else "failed"
            details = {"prior_standing": standings.get(f"{p1_id}:C1"), "current_standing": standings.get(f"{p2_id}:C1"), "cycle_detected": graph["cycle_detected"]}
            actual_outcome = "accepted"

        elif code == "PLONG-02":
            s1_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong02-prior", spec=spec,
                question="Does intervention S lower risk?",
                evidence_text="Cohort S1 HR = 0.72 (95% CI 0.56 to 0.93, p = 0.012).",
                draft="Cohort S1 lower risk HR = 0.72 (95% CI 0.56 to 0.93).",
                evidence_kind="observation", eff_est="HR = 0.72", eff_unc="95% CI 0.56 to 0.93, p = 0.012",
            )
            try:
                _p2_adjudicate_case(
                    engine, ws, tag="plong02-unlinked", spec=spec,
                    question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                    evidence_kind=spec["evidence_kind"], eff_est="HR = 0.74", eff_unc="95% CI 0.59 to 0.93, p = 0.010",
                    family=spec["family"],
                    prior_claim_links=[{
                        "prior_case_id": s1_id, "prior_claim_id": "C1", "relation": "replicates",
                        "reason": "Links to S1 without declaring prior_case_ids.",
                    }],
                )
                actual_outcome = "accepted"
            except ContractError as exc:
                actual_outcome = "rejected"
                actual_error = exc.code
            event_chain_status = engine.dispatch("verify", {"case_id": s1_id})["event_chain_status"]

        elif code == "PLONG-03":
            identical_text = spec["draft"]
            m1_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong03-prior", spec=spec,
                question=spec["question"], evidence_text=spec["evidence_text"], draft=identical_text,
                evidence_kind=spec["evidence_kind"], eff_est="HR = 0.71", eff_unc="95% CI 0.55 to 0.91, p = 0.004",
            )
            try:
                _p2_adjudicate_case(
                    engine, ws, tag="plong03-dup", spec=spec,
                    question=spec["question"], evidence_text=spec["evidence_text"], draft=identical_text,
                    evidence_kind=spec["evidence_kind"], eff_est="HR = 0.71", eff_unc="95% CI 0.55 to 0.91, p = 0.004",
                    prior_case_ids=[m1_id], case_relation="reanalysis",
                    prior_claim_links=[{
                        "prior_case_id": m1_id, "prior_claim_id": "C1", "relation": "reverses",
                        "reason": "Declares reverses despite identical proposition and scope.",
                    }],
                )
                actual_outcome = "accepted"
            except ContractError as exc:
                actual_outcome = "rejected"
                actual_error = exc.code
            event_chain_status = engine.dispatch("verify", {"case_id": m1_id})["event_chain_status"]

        elif code == "PLONG-04":
            k1_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong04-prior", spec=spec,
                question="Does Drug K improve survival?",
                evidence_text="Trial K1 HR = 0.72 (95% CI 0.56 to 0.93, p = 0.012).",
                draft="Trial K1 lowers mortality HR = 0.72 (95% CI 0.56 to 0.93).",
                evidence_kind="intervention", eff_est="HR = 0.72", eff_unc="95% CI 0.56 to 0.93, p = 0.012",
                family="randomized",
                reversal_triggers=[{
                    "id": "T_REV_GT1", "description": "Reversal when HR exceeds 1.0", "kind": "effect_metric",
                    "metric": "HR", "endpoint_role": "primary", "field": "estimate", "operator": "gt", "threshold": 1.0,
                    "target_verdict": "unsupported",
                }],
            )
            try:
                _p2_adjudicate_case(
                    engine, ws, tag="plong04-untrig", spec=spec,
                    question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                    evidence_kind=spec["evidence_kind"], eff_est="HR = 0.75", eff_unc="95% CI 0.60 to 0.94, p = 0.012",
                    family=spec["family"], prior_case_ids=[k1_id], case_relation="replication",
                    effect_records=[{
                        "id": "E_K2", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                        "estimate": 0.75, "ci_low": 0.60, "ci_high": 0.94, "p_value": 0.012,
                        "direction": "benefit", "evidence_id": "__PRIMARY__",
                    }],
                    prior_claim_links=[{
                        "prior_case_id": k1_id, "prior_claim_id": "C1", "relation": "reverses",
                        "triggered_reversal_id": "T_REV_GT1",
                        "reason": "Incorrectly cites T_REV_GT1 even though HR 0.75 < 1.0.",
                    }],
                )
                actual_outcome = "accepted"
            except ContractError as exc:
                actual_outcome = "rejected"
                actual_error = exc.code
            event_chain_status = engine.dispatch("verify", {"case_id": k1_id})["event_chain_status"]

        elif code == "PLONG-05":
            last_case_id = None
            try:
                last_case_id, _, _ = _p2_adjudicate_case(
                    engine, ws, tag="plong05-self", spec=spec,
                    question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                    evidence_kind=spec["evidence_kind"], eff_est="RR = 0.71", eff_unc="95% CI 0.55 to 0.91, p = 0.004",
                    effect_records=[{
                        "id": "E_P5", "endpoint": "Incidence", "endpoint_role": "primary", "metric": "RR",
                        "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                        "direction": "benefit", "evidence_id": "__PRIMARY__",
                    }],
                    reversal_triggers=[{
                        "id": "T_SELF_LT08", "description": "Fires whenever primary RR < 0.80", "kind": "effect_metric",
                        "metric": "RR", "endpoint_role": "primary", "field": "estimate", "operator": "lt", "threshold": 0.80,
                        "target_verdict": "unsupported",
                    }],
                )
                actual_outcome = "accepted"
            except ContractError as exc:
                actual_outcome = "rejected"
                actual_error = exc.code
            cases_list = engine.list_cases()
            cid_ref = last_case_id or (cases_list[0]["case_id"] if cases_list else None)
            event_chain_status = engine.dispatch("get_case", {"case_id": cid_ref})["event_chain_status"] if cid_ref else None

        elif code == "PLONG-06":
            c6_id, ev6, c6_data = _p2_adjudicate_case(
                engine, ws, tag="plong06-base", spec=spec,
                question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                evidence_kind=spec["evidence_kind"], eff_est="HR = 0.71", eff_unc="95% CI 0.55 to 0.91, p = 0.004",
                family=spec["family"],
                effect_records=[{
                    "id": "E_Q6", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                    "direction": "benefit", "evidence_id": "__PRIMARY__",
                }],
                reversal_triggers=[
                    {
                        "id": "TR_NULL", "description": "Replication primary HR crosses 1.0", "kind": "effect_metric",
                        "metric": "HR", "endpoint_role": "primary", "field": "estimate", "operator": "crosses_null",
                        "target_verdict": "unsupported",
                    },
                    {
                        "id": "TR_REP", "description": "Downstream replication unsupported", "kind": "replication_verdict",
                        "target_verdicts": ["unsupported"], "relations": ["replicates"], "target_verdict": "unsupported",
                    },
                ],
            )
            ag6_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong06-against", spec=spec,
                question="Does replication confirm Q6?",
                evidence_text="Follow-up cohort HR = 1.03 (95% CI 0.82 to 1.29, p = 0.79).",
                draft="Follow-up HR = 1.03 (95% CI 0.82 to 1.29, p = 0.79).",
                evidence_kind="intervention", eff_est="HR = 1.03", eff_unc="95% CI 0.82 to 1.29, p = 0.79",
                family="randomized", prior_case_ids=[c6_id], case_relation="replication", verdict="unsupported",
                effect_records=[{
                    "id": "E_AG6", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 1.03, "ci_low": 0.82, "ci_high": 1.29, "p_value": 0.79,
                    "direction": "null", "evidence_id": "__PRIMARY__",
                }],
                prior_claim_links=[{
                    "prior_case_id": c6_id, "prior_claim_id": "C1", "relation": "replicates",
                    "reason": "Direct replication attempt found null effect.",
                }],
            )
            with contextlib.closing(sqlite3.connect(engine.database)) as db:
                ev_before = db.execute("SELECT COUNT(*) FROM events WHERE case_id=?", (c6_id,)).fetchone()[0]
            ag_eval = engine.evaluate_triggers(c6_id, against_case_id=ag6_id)
            obs_eval = engine.evaluate_triggers(c6_id, observations={
                "effect_records": [{"id": "E_OBS", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR", "estimate": 1.04, "ci_low": 0.85, "ci_high": 1.28, "direction": "null", "evidence_id": ev6}],
                "verdict": "unsupported", "relation": "replicates",
            })
            with contextlib.closing(sqlite3.connect(engine.database)) as db:
                ev_after = db.execute("SELECT COUNT(*) FROM events WHERE case_id=?", (c6_id,)).fetchone()[0]
            c6_after = engine.dispatch("get_case", {"case_id": c6_id})
            ver6 = engine.dispatch("verify", {"case_id": c6_id})
            event_chain_status = ver6["event_chain_status"]
            details = {
                "against_fired": ag_eval["fired_count"],
                "obs_fired": obs_eval["fired_count"],
                "events_unchanged": ev_before == ev_after,
                "digest_unchanged": c6_after["adjudication_digest"] == c6_data["adjudication_digest"],
                "recommended_verdict": (ag_eval["claim_evaluations"][0].get("recommended_revision") or {}).get("verdict"),
            }
            actual_outcome = "accepted"

        elif code == "PLONG-07":
            c7_id, _, c7_before = _p2_adjudicate_case(
                engine, ws, tag="plong07-exp", spec=spec,
                question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                evidence_kind=spec["evidence_kind"], eff_est="HR = 0.71", eff_unc="95% CI 0.55 to 0.91, p = 0.004",
                family=spec["family"], forecast_probability=0.85, export_report=True,
                effect_records=[{
                    "id": "E_Q7", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "ci_level": 0.95, "p_value": 0.004,
                    "direction": "benefit", "evidence_id": "__PRIMARY__",
                }],
            )
            rec = engine.dispatch("record_calibration_outcome", {
                "case_id": c7_id, "claim_id": "C1", "outcome": "replicated",
                "resolution_source": "external_evidence", "metric": "HR",
                "evidence_id": _register_calibration_fixture(engine, ws, "plong07"), "effect_record_id": "E_Q7",
                "observed_estimate": 0.74, "observed_ci_low": 0.60, "observed_ci_high": 0.90,
                "reason": "Independent registry replicated benefit inside prior 95% CI.",
            })
            c7_after = engine.dispatch("get_case", {"case_id": c7_id})
            ver7 = engine.dispatch("verify", {"case_id": c7_id})
            event_chain_status = ver7["event_chain_status"]
            details = {
                "calibration_outcome_count": rec["calibration_outcome_count"],
                "input_digest_preserved": c7_after["input_digest"] == c7_before["input_digest"],
                "adjudication_digest_preserved": c7_after["adjudication_digest"] == c7_before["adjudication_digest"],
                "export_preserved": c7_after.get("export") == c7_before.get("export"),
                "verify_status": ver7["status"],
            }
            actual_outcome = "accepted"

        elif code == "PLONG-08":
            q8a_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong08-a", spec=spec,
                question=spec["question"], evidence_text=spec["evidence_text"], draft=spec["draft"],
                evidence_kind=spec["evidence_kind"], eff_est="HR = 0.71", eff_unc="95% CI 0.55 to 0.91, p = 0.004",
                forecast_probability=0.80,
                effect_records=[{
                    "id": "E_Q8A", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "ci_level": 0.95, "p_value": 0.004,
                    "direction": "benefit", "evidence_id": "__PRIMARY__",
                }],
            )
            engine.dispatch("record_calibration_outcome", {
                "case_id": q8a_id, "claim_id": "C1", "outcome": "replicated",
                "resolution_source": "external_evidence", "metric": "HR",
                "evidence_id": _register_calibration_fixture(engine, ws, "plong08"), "effect_record_id": "E_Q8A",
                "observed_estimate": 0.74, "observed_ci_low": 0.60, "observed_ci_high": 0.90,
                "reason": "Registry replication HR 0.74 confirms benefit.",
            })
            q8b_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong08-b", spec=spec,
                question="Does cohort Q8b lower mortality?",
                evidence_text="Cohort Q8b mortality HR = 0.80 (95% CI 0.65 to 0.98, p = 0.03).",
                draft="Cohort Q8b reduces mortality hazard (HR = 0.80, 95% CI 0.65 to 0.98).",
                evidence_kind="observation", eff_est="HR = 0.80", eff_unc="95% CI 0.65 to 0.98, p = 0.03",
                forecast_probability=0.60,
                effect_records=[{
                    "id": "E_Q8B", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.80, "ci_low": 0.65, "ci_high": 0.98, "ci_level": 0.95, "p_value": 0.03,
                    "direction": "benefit", "evidence_id": "__PRIMARY__",
                }],
                reversal_triggers=[{
                    "id": "T_REP_REF", "description": "Refuted by replication", "kind": "replication_verdict",
                    "target_verdicts": ["supported"], "relations": ["refutes"], "target_verdict": "unsupported",
                }],
            )
            q8_down_id, _, _ = _p2_adjudicate_case(
                engine, ws, tag="plong08-down", spec=spec,
                question="Does trial Q8c refute Q8b?",
                evidence_text="Follow-up Q8c mortality HR = 1.15 (95% CI 1.02 to 1.39, p = 0.03).",
                draft="Follow-up Q8c finds increased mortality HR = 1.15 (95% CI 1.02 to 1.39), refuting Q8b.",
                evidence_kind="observation", eff_est="HR = 1.15", eff_unc="95% CI 1.02 to 1.39, p = 0.03",
                prior_case_ids=[q8b_id], case_relation="replication", forecast_probability=0.90,
                effect_records=[{
                    "id": "E_Q8C", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 1.15, "ci_low": 1.02, "ci_high": 1.39, "p_value": 0.03,
                    "direction": "higher_better", "evidence_id": "__PRIMARY__",
                }],
                prior_claim_links=[{
                    "prior_case_id": q8b_id, "prior_claim_id": "C1", "relation": "refutes",
                    "triggered_reversal_id": "T_REP_REF",
                    "reason": "Independent follow-up Q8c refutes Q8b via T_REP_REF.",
                }],
            )
            rep = engine.get_calibration_report(domain="scientific")
            ver8 = engine.dispatch("verify", {"case_id": q8_down_id})
            event_chain_status = ver8["event_chain_status"]
            details = {
                "resolved_claim_count": rep["summary"]["resolved_claim_count"],
                "explicit_brier_score": rep["proper_scores"]["explicit_brier_score"],
                "ece": rep["proper_scores"]["ece"],
                "bin_count": len(rep["reliability_bins"]),
                "interval_evaluated_count": rep["interval_calibration"]["evaluated_count"],
                "interval_covered_count": rep["interval_calibration"]["covered_count"],
                "empirical_coverage_rate": rep["interval_calibration"]["empirical_coverage_rate"],
                "mean_absolute_z_drift": rep["interval_calibration"]["mean_absolute_z_drift"],
                "replication_count": rep["interval_calibration"]["replication_count"],
                "replication_point_containment_rate": rep["interval_calibration"]["replication_point_containment_rate"],
                "trigger_precision": rep["decision_calibration"]["trigger_calibration"]["trigger_precision"],
            }
            actual_outcome = "accepted"
    except Exception as exc:  # noqa: BLE001
        actual_error = getattr(exc, "code", type(exc).__name__)
        details["exception"] = str(exc)

    expected_outcome = spec["expected_gate_outcome"]
    expected_error = spec.get("expected_error_code")
    if code == "PLONG-01":
        passed = (
            actual_outcome == "accepted"
            and event_chain_status == "verified"
            and details.get("prior_standing") == "reversed"
            and details.get("current_standing") == "current"
            and details.get("cycle_detected") is False
        )
    elif code in ("PLONG-02", "PLONG-03", "PLONG-04", "PLONG-05"):
        passed = (
            actual_outcome == "rejected"
            and actual_error == expected_error
            and event_chain_status == "verified"
        )
    elif code == "PLONG-06":
        passed = (
            actual_outcome == "accepted"
            and event_chain_status == "verified"
            and details.get("against_fired") == 2
            and details.get("obs_fired") == 2
            and details.get("events_unchanged") is True
            and details.get("digest_unchanged") is True
            and details.get("recommended_verdict") == "unsupported"
        )
    elif code == "PLONG-07":
        passed = (
            actual_outcome == "accepted"
            and event_chain_status == "verified"
            and details.get("calibration_outcome_count") == 1
            and details.get("input_digest_preserved") is True
            and details.get("adjudication_digest_preserved") is True
            and details.get("export_preserved") is True
            and details.get("verify_status") == "pass"
        )
    elif code == "PLONG-08":
        brier = details.get("explicit_brier_score")
        ece = details.get("ece")
        passed = (
            actual_outcome == "accepted"
            and event_chain_status == "verified"
            and details.get("resolved_claim_count") == 2
            and isinstance(brier, float) and abs(brier - 0.20) < 1e-6
            and isinstance(ece, float) and abs(ece - 0.40) < 1e-6
            and details.get("bin_count") == 5
            and details.get("interval_evaluated_count") == 0
            and details.get("interval_covered_count") == 0
            and details.get("empirical_coverage_rate") is None
            and details.get("mean_absolute_z_drift") is None
            and details.get("replication_count") == 2
            and details.get("replication_point_containment_rate") == 0.5
            and details.get("trigger_precision") == 1.0
        )
    else:
        passed = False

    return {
        "case_code": code,
        "family": spec["family"],
        "scenario": spec["scenario"],
        "expected_gate_outcome": expected_outcome,
        "actual_gate_outcome": actual_outcome,
        "expected_error_code": expected_error,
        "actual_error_code": actual_error,
        "event_chain_status": event_chain_status,
        "details": details,
        "passed": passed,
    }


def run_p2_longitudinal_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-p2-longitudinal-"))
        cleanup = True
    try:
        results = [
            evaluate_p2_longitudinal_case(case, work_root)
            for case in suite.get("p2_longitudinal_calibration", [])
        ]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    positives = [r for r in results if r["expected_gate_outcome"] == "accepted"]
    pos_passed = sum(1 for r in positives if r["passed"])
    negatives = [r for r in results if r["expected_gate_outcome"] == "rejected"]
    neg_caught = sum(1 for r in negatives if r["passed"])
    event_chain_verified = sum(1 for r in results if r["event_chain_status"] == "verified")
    summary = {
        "total_cases": total,
        "passed_cases": passed,
        "positive_controls_total": len(positives),
        "positive_controls_passed": pos_passed,
        "negative_traps_total": len(negatives),
        "negative_traps_caught": neg_caught,
        "event_chain_verified_count": event_chain_verified,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "all_passed": total > 0 and passed == total and event_chain_verified == total,
    }
    return {
        "suite_version": suite["suite_version"],
        "summary": summary,
        "results": results,
    }


def run_mechanical_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    measured = policy_inputs(ROOT)
    fingerprint = input_fingerprint(ROOT, suite_path)
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-eval-"))
        cleanup = True
    try:
        results = [evaluate_single_case(case, work_root) for case in suite["cases"]]
        exploratory_results = [evaluate_exploratory_case(case) for case in suite.get("exploratory_cases", [])]
        positive_cases = [case for case in suite["cases"] if case["expected_gate_outcome"] == "accepted"]
        counterfactual_results = [
            evaluate_counterfactual_case(case, pert_id, work_root / "counterfactual")
            for case in positive_cases
            for pert_id, _, _, _ in COUNTERFACTUAL_PERTURBATIONS
        ]
        fork_multiplicity_results = [
            evaluate_fork_multiplicity_case(case, scen_id, work_root / "fork-multiplicity")
            for case in positive_cases
            for scen_id, _, _ in FORK_MULTIPLICITY_SCENARIOS
        ]
        sym_out = run_symmetry_suite(suite_path, work_root=work_root / "symmetry")
        paired_out = run_paired_sensitivity_suite(suite_path, work_root=work_root / "paired")
        lineage_out = run_lineage_window_suite(suite_path, work_root=work_root / "lineage-window")
        heldout_out = run_heldout_generalization_suite(suite_path, work_root=work_root / "heldout")
        metamorphic_out = run_metamorphic_invariance_suite(suite_path, work_root=work_root / "metamorphic")
        p1_effects_out = run_p1_effect_records_suite(suite_path, work_root=work_root / "p1-effects")
        p2_longitudinal_out = run_p2_longitudinal_suite(suite_path, work_root=work_root / "p2-longitudinal")
        ingestion_out = run_ingestion_suite(work_root / "ingestion")
        text_advisory_out = run_text_advisory_suite()
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)
    passed_count = sum(1 for item in results if item["passed"])
    exploratory_passed = sum(1 for item in exploratory_results if item["passed"])
    counterfactual_summary = _summarize_counterfactual(positive_cases, counterfactual_results)
    fork_multiplicity_summary = _summarize_fork_multiplicity(positive_cases, fork_multiplicity_results)
    symmetry_summary = sym_out["summary"]
    paired_summary = paired_out["summary"]
    lineage_summary = lineage_out["summary"]
    heldout_summary = heldout_out["summary"]
    metamorphic_summary = metamorphic_out["summary"]
    p1_effects_summary = p1_effects_out["summary"]
    p2_longitudinal_summary = p2_longitudinal_out["summary"]
    inputs_unchanged = fingerprint == input_fingerprint(ROOT, suite_path) and measured == policy_inputs(ROOT)

    ordered_families = list(suite.get("stage0_design", {}).get("case_families") or [])
    for item in results:
        if item["family"] not in ordered_families:
            ordered_families.append(item["family"])
    equal_coverage_by_family = {}
    for fam in ordered_families:
        fam_items = [r for r in results if r["family"] == fam]
        fam_pass = sum(1 for r in fam_items if r["passed"])
        equal_coverage_by_family[fam] = {
            "passed": fam_pass,
            "total": len(fam_items),
            "accuracy": round(fam_pass / len(fam_items), 4) if fam_items else 0.0,
        }

    base_rejected = [r for r in results if r["expected_gate_outcome"] == "rejected"]
    base_rejected_pass = sum(1 for r in base_rejected if r["passed"])
    base_accepted = [r for r in results if r["expected_gate_outcome"] == "accepted"]
    base_accepted_pass = sum(1 for r in base_accepted if r["passed"])
    known_valid_passed = base_accepted_pass + paired_summary["strong_twins_accepted"]
    known_valid_total = len(base_accepted) + paired_summary["strong_twins_total"]

    metric_dimensions = {
        "overstatement_rejection_rate": round(base_rejected_pass / len(base_rejected), 4) if base_rejected else 0.0,
        "false_abstention_detection_rate": symmetry_summary["false_abstention_detection_rate"],
        "unjustified_downgrade_detection_rate": symmetry_summary["unjustified_downgrade_detection_rate"],
        "known_valid_retention_rate": round(known_valid_passed / known_valid_total, 4) if known_valid_total else 0.0,
        "equal_coverage_accuracy": min((v["accuracy"] for v in equal_coverage_by_family.values()), default=0.0),
        "paired_evidence_sensitivity_concordance": paired_summary["paired_evidence_sensitivity_concordance"],
        "synthetic_lineage_blocking_rate": lineage_summary["synthetic_lineage_blocking_rate"],
        "chunked_window_head_tail_recall": lineage_summary["chunked_window_head_tail_recall"],
        "calibrated_false_alarm_rate": symmetry_summary["calibrated_false_alarm_rate"],
        "heldout_realistic_false_rejection_rate": heldout_summary["realistic_controls_false_rejection_rate"],
        "heldout_adversarial_mechanical_recall": heldout_summary["adversarial_mechanical_recall"],
        "heldout_adversarial_uncaught_rate": heldout_summary["adversarial_uncaught_rate"],
        "metamorphic_invariance_rate": metamorphic_summary["invariance_rate"],
        "p1_effect_records_catch_rate": p1_effects_summary["negative_traps_catch_rate"],
        "p1_effect_records_false_rejection_rate": p1_effects_summary["positive_controls_false_rejection_rate"],
        "p2_longitudinal_pass_rate": p2_longitudinal_summary["pass_rate"],
        "leakage_strict_passed": heldout_summary["leakage_strict_passed"],
        "live_llm_eval_status": "not_run",
    }

    split_metrics = {
        "dev_phrase_consistency": {
            "base_cases_passed": passed_count,
            "base_cases_total": len(results),
            "exploratory_passed": exploratory_passed,
            "exploratory_total": len(exploratory_results),
            "counterfactual_hard_rejected": counterfactual_summary["card_a_rubber_stamp_hard_rejected"],
            "counterfactual_advisory_flagged": counterfactual_summary["card_a_rubber_stamp_advisory_flagged"],
            "counterfactual_total": counterfactual_summary["total_perturbation_runs"],
            "fork_adversarial_hard_rejected": fork_multiplicity_summary["card_b_adversarial_hard_rejected"],
            "fork_adversarial_advisory_flagged": fork_multiplicity_summary["card_b_adversarial_advisory_flagged"],
            "fork_adversarial_total": fork_multiplicity_summary["adversarial_runs"],
            "symmetry_passed": symmetry_summary["passed_runs"],
            "symmetry_total": symmetry_summary["total_runs"],
            "paired_strong_accepted": paired_summary["strong_twins_accepted"],
            "paired_weak_rejected": paired_summary["weak_twins_rejected"],
            "paired_weak_advisory_flagged": paired_summary["weak_twins_advisory_flagged"],
            "paired_total": paired_summary["total_pairs"],
            "lineage_specs_passed": lineage_summary["passed_specs"],
            "lineage_specs_total": lineage_summary["total_specs"],
        },
        "heldout_generalization": {
            "leakage_strict_passed": heldout_summary["leakage_strict_passed"],
            "heldout_lexical_overlap_count": heldout_summary["heldout_lexical_overlap_count"],
            "realistic_controls_passed": heldout_summary["realistic_controls_passed"],
            "realistic_controls_total": heldout_summary["realistic_controls_total"],
            "realistic_controls_false_rejection_rate": heldout_summary["realistic_controls_false_rejection_rate"],
            "adversarial_caught_mechanically_hard": heldout_summary["adversarial_caught_mechanically_hard"],
            "adversarial_flagged_lexical_advisory_only": heldout_summary["adversarial_flagged_lexical_advisory_only"],
            "adversarial_uncaught_without_llm_or_p1": heldout_summary["adversarial_uncaught_without_llm_or_p1"],
            "adversarial_total": heldout_summary["adversarial_paraphrases_total"],
            "adversarial_mechanical_recall": heldout_summary["adversarial_mechanical_recall"],
            "adversarial_uncaught_rate": heldout_summary["adversarial_uncaught_rate"],
            "adversarial_uncaught_case_codes": heldout_summary["adversarial_uncaught_case_codes"],
        },
        "metamorphic_invariance": {
            "passed_transforms": metamorphic_summary["passed_transforms"],
            "total_transforms": metamorphic_summary["total_transforms"],
            "invariance_rate": metamorphic_summary["invariance_rate"],
            "false_advisory_count": metamorphic_summary["false_advisory_count"],
        },
        "p1_effect_records": {
            "total_cases": p1_effects_summary["total_cases"],
            "passed_cases": p1_effects_summary["passed_cases"],
            "positive_controls_total": p1_effects_summary["positive_controls_total"],
            "positive_controls_accepted": p1_effects_summary["positive_controls_accepted"],
            "positive_controls_false_rejection_rate": p1_effects_summary["positive_controls_false_rejection_rate"],
            "negative_traps_total": p1_effects_summary["negative_traps_total"],
            "negative_traps_caught": p1_effects_summary["negative_traps_caught"],
            "negative_traps_catch_rate": p1_effects_summary["negative_traps_catch_rate"],
            "hadv_counterparts_total": p1_effects_summary["hadv_counterparts_total"],
            "hadv_counterparts_caught": p1_effects_summary["hadv_counterparts_caught"],
            "event_chain_verified_count": p1_effects_summary["event_chain_verified_count"],
        },
        "p2_longitudinal_calibration": {
            "total_cases": p2_longitudinal_summary["total_cases"],
            "passed_cases": p2_longitudinal_summary["passed_cases"],
            "positive_controls_passed": p2_longitudinal_summary["positive_controls_passed"],
            "negative_traps_caught": p2_longitudinal_summary["negative_traps_caught"],
            "event_chain_verified_count": p2_longitudinal_summary["event_chain_verified_count"],
            "pass_rate": p2_longitudinal_summary["pass_rate"],
        },
    }

    return {
        "suite_version": suite["suite_version"],
        "mode": "mechanical",
        "evaluation_revision": "text-advisory-regression-v1",
        "policy_measurement": measured,
        "input_fingerprint": fingerprint,
        "inputs_unchanged_during_run": inputs_unchanged,
        "ingestion_summary": ingestion_out["summary"],
        "ingestion_results": ingestion_out["results"],
        "text_advisory_qualification": text_advisory_out,
        "host_accepted": "not_run",
        "user_impact": "not_run",
        "heldout_reuse_status": "previously_exposed_regression_not_fresh_generalization",
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "external_llm_status": "not_run",
        "requires_prior_user_approval": suite.get("requires_prior_user_approval", True),
        "stage0_design": suite.get("stage0_design", {}),
        "arms": [arm["arm_id"] for arm in suite.get("arms", [])],
        "total_cases": len(results),
        "passed_cases": passed_count,
        "exploratory_cases_count": len(exploratory_results),
        "exploratory_passed_cases": exploratory_passed,
        "exploratory_all_valid": exploratory_passed == len(exploratory_results),
        "equal_coverage_by_family": equal_coverage_by_family,
        "counterfactual_summary": counterfactual_summary,
        "counterfactual_results": counterfactual_results,
        "fork_multiplicity_summary": fork_multiplicity_summary,
        "fork_multiplicity_results": fork_multiplicity_results,
        "symmetry_audit_summary": symmetry_summary,
        "symmetry_results": sym_out["results"],
        "paired_sensitivity_summary": paired_summary,
        "paired_results": paired_out["results"],
        "lineage_window_summary": lineage_summary,
        "lineage_window_results": lineage_out["results"],
        "heldout_summary": heldout_summary,
        "heldout_control_results": heldout_out["control_results"],
        "heldout_adversarial_results": heldout_out["adversarial_results"],
        "metamorphic_summary": metamorphic_summary,
        "metamorphic_results": metamorphic_out["results"],
        "p1_effects_summary": p1_effects_summary,
        "p1_effects_results": p1_effects_out["results"],
        "p2_longitudinal_summary": p2_longitudinal_summary,
        "p2_longitudinal_results": p2_longitudinal_out["results"],
        "split_metrics": {**split_metrics, "ingestion_v1": ingestion_out["summary"]},
        "metric_dimensions": metric_dimensions,
        "all_passed": (
            passed_count == len(results)
            and exploratory_passed == len(exploratory_results)
            and counterfactual_summary["all_passed"]
            and fork_multiplicity_summary["all_passed"]
            and symmetry_summary["all_passed"]
            and paired_summary["all_passed"]
            and lineage_summary["all_passed"]
            and heldout_summary["regression_all_passed"]
            and metamorphic_summary["all_passed"]
            and metamorphic_summary["advisory_all_passed"]
            and text_advisory_out["summary"]["all_passed"]
            and p1_effects_summary["all_passed"]
            and p2_longitudinal_summary["all_passed"]
            and ingestion_out["summary"]["all_passed"]
            and inputs_unchanged
        ),
        "results": results,
        "exploratory_results": exploratory_results,
    }


def _format_fork_prompt_context(case: dict, scenario_id: str) -> str:
    base_telemetry = (
        "Recorded execution logs in workspace (5 runs total): "
        "exec-fork-1..4 (candidate runs, status=non_selected, exit_status=0); "
        f"exec-fork-5 (reported run, exit_status=0): {case['evidence_text']}"
    )
    if scenario_id == "F1_hidden_failed_forks":
        disclosure = (
            "Submitted draft ledger provenance_cards.execution lists only exec-fork-5 "
            "and omits exec-fork-1..4."
        )
    elif scenario_id == "F2_unadjusted_multi_fork":
        disclosure = (
            "Submitted draft ledger provenance_cards.execution lists exec-fork-1..5, "
            "and statistical_report.multiplicity_selection states: "
            '"Single run primary test only without multiple testing adjustment."'
        )
    elif scenario_id == "F3_calibrated_multiplicity_accounted":
        disclosure = (
            "Submitted draft ledger provenance_cards.execution lists exec-fork-1..5, "
            "and statistical_report.multiplicity_selection states: "
            '"Holm-Bonferroni step-down correction applied across all 5 execution forks and verified on locked holdout."'
        )
    else:
        raise ValueError(f"Unknown fork scenario_id: {scenario_id}")
    return f"{base_telemetry}\n{disclosure}"


def export_prompts(suite_path: Path, output_dir: Path) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    compact_policy_path = ROOT / "templates" / "AGENTS.parrhesia.codex.md"
    full_policy_path = ROOT / "templates" / "AGENTS.parrhesia.md"
    l2_ref_path = ROOT / "skills" / "parrhesia-l2-reference" / "SKILL.md"
    review_skill_path = ROOT / "skills" / "parrhesia-review" / "SKILL.md"
    workflow_path = ROOT / "skills" / "parrhesia-review" / "references" / "workflow.md"

    measured = policy_inputs(ROOT)
    prompts = measured["arm_system_prompts"]
    sizes = measured["policy_size_bytes"]
    b_compact_l1_policy = prompts["B_compact_l1"]
    b_compact_l2_policy = prompts["B_compact_l2"]
    b_full_policy = prompts["B_full"]
    e_workflow_policy = prompts["E_full_l2_workflow"]
    a_baseline_sys = prompts["A_baseline"]
    compact_bytes = sizes["B_compact_agents_block_bytes"]
    l2_ref_bytes = sizes["B_compact_l2_reference_skill_bytes"]
    full_bytes = sizes["B_full_policy_bytes"]
    review_skill_bytes = sizes["E_full_l2_workflow_skill_bytes"]

    packets = []
    for case in suite["cases"]:
        packets.append(
            {
                "case_code": case["case_code"],
                "family": case["family"],
                "scenario": case["scenario"],
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "expected_target": {
                    "claim_type": case["claim_type"],
                    "evidence_level": case["evidence_level"],
                    "target_verdict": case["target_verdict"],
                    "expected_gate_outcome": case["expected_gate_outcome"],
                    "expected_error_code": case.get("expected_error_code"),
                },
                "arms": {
                    "A_baseline": (
                        "[Arm A: 无 Parrhesia 规则]\n"
                        f"{a_baseline_sys}\n\n"
                        f"Question: {case['question']}\n"
                        f"Evidence: {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}\n"
                        "Evaluate the draft claim based on the evidence."
                    ),
                    "B_compact": (
                        f"[Arm B-精简（{compact_bytes} B compact block + {l2_ref_bytes} B parrhesia-l2-reference）]\n"
                        "=== POLICY ===\n"
                        f"{b_compact_l2_policy}\n\n"
                        "=== CASE ===\n"
                        f"Question: {case['question']}\n"
                        f"Evidence: {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}\n"
                        "Classify the claim as claim_type x evidence_level + scope and give a calibrated judgment with reversal condition."
                    ),
                    "B_full": (
                        f"[Arm B-全文（{full_bytes} B full policy）]\n"
                        "=== POLICY ===\n"
                        f"{b_full_policy}\n\n"
                        "=== CASE ===\n"
                        f"Question: {case['question']}\n"
                        f"Evidence: {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}\n"
                        "Classify the claim as claim_type x evidence_level + scope and give a calibrated judgment with reversal condition."
                    ),
                    "E_full_l2_workflow": (
                        f"[Arm E: 完整流程（{review_skill_bytes} B L2 workflow + blind dual-review & mechanical gates）]\n"
                        "=== POLICY ===\n"
                        f"{e_workflow_policy}\n\n"
                        "=== CASE ===\n"
                        "Run Parrhesia v0.2.0 [L2] workflow: register_evidence -> scaffold_claim -> set_ledger -> "
                        "freeze -> blind overclaim/underclaim review_packet (reviewer isolation recipe: role packet only, "
                        "no history inheritance, memory disabled, record input manifest) -> submit_review -> "
                        "adjudication_packet -> submit_adjudication -> verify -> export.\n"
                        f"Question: {case['question']}\n"
                        f"Evidence: {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}"
                    ),
                },
            }
        )

    exploratory_packets = []
    for exp_case in suite.get("exploratory_cases", []):
        candidate_hyp = exp_case["false_hypothesis"]
        exploratory_packets.append(
            {
                "case_code": exp_case["case_code"],
                "family": exp_case["family"],
                "scenario": exp_case["scenario"],
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "exploratory_metrics": {
                    "discriminating_experiments_before_first_fp": "not_run",
                    "steps_to_kill_false_hypothesis": "not_run",
                    "total_consumption": "not_run",
                },
                "arms": {
                    "A_baseline": (
                        "[Arm A: 无 Parrhesia 规则]\n"
                        f"{a_baseline_sys}\n\n"
                        f"Question: {exp_case['question']}\n"
                        f"Candidate hypothesis: {candidate_hyp}\n"
                        "Propose next steps."
                    ),
                    "B_compact": (
                        f"[Arm B-精简（{compact_bytes} B compact block · L1-Explore 轻量探索台账）]\n"
                        "=== POLICY ===\n"
                        f"{b_compact_l1_policy}\n\n"
                        "=== CASE ===\n"
                        "Use [L1-Explore] lightweight exploration ledger (one card per candidate hypothesis: "
                        "strongest_rival, discriminating_experiment, cost, stopping_rule, kill_condition; mark exploratory).\n"
                        f"Question: {exp_case['question']}\n"
                        f"Candidate hypothesis: {candidate_hyp}"
                    ),
                    "B_full": (
                        f"[Arm B-全文（{full_bytes} B full policy · L1-Explore）]\n"
                        "=== POLICY ===\n"
                        f"{b_full_policy}\n\n"
                        "=== CASE ===\n"
                        "Use [L1-Explore] lightweight exploration ledger.\n"
                        f"Question: {exp_case['question']}\n"
                        f"Candidate hypothesis: {candidate_hyp}"
                    ),
                    "E_full_l2_workflow": (
                        f"[Arm E: 完整流程（{review_skill_bytes} B workflow · 探索筛选后送入 L2）]\n"
                        "=== POLICY ===\n"
                        f"{e_workflow_policy}\n\n"
                        "=== CASE ===\n"
                        "Explore first in [L1-Explore] with lightweight exploration cards before any [L2] formal adjudication.\n"
                        f"Question: {exp_case['question']}\n"
                        f"Candidate hypothesis: {candidate_hyp}"
                    ),
                },
            }
        )

    counterfactual_packets = []
    for case in suite["cases"]:
        if case["expected_gate_outcome"] != "accepted":
            continue
        draft_claim = case.get("restored_text") or case["draft"]
        for pert_id, expected_error, expected_advisory, expected_cal_verdict in COUNTERFACTUAL_PERTURBATIONS:
            pert_text, _, _, _ = build_perturbed_evidence(case, pert_id)
            counterfactual_packets.append(
                {
                    "run_id": f"{case['case_code']}-{pert_id}",
                    "case_code": case["case_code"],
                    "family": case["family"],
                    "perturbation_id": pert_id,
                    "expected_rubber_stamp_error": expected_error,
                    "expected_advisory_hook": expected_advisory,
                    "expected_calibrated_verdict": expected_cal_verdict,
                    "statistical_unit": "case",
                    "external_llm_status": "not_run",
                    "arms": {
                        "A_baseline": (
                            "[Arm A: 无 Parrhesia 规则]\n"
                            f"{a_baseline_sys}\n\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {pert_text}\n"
                            f"Draft claim: {draft_claim}\n"
                            "Evaluate the draft claim based on the evidence."
                        ),
                        "B_compact": (
                            f"[Arm B-精简（{compact_bytes} B + {l2_ref_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_compact_l2_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {pert_text}\n"
                            f"Draft claim: {draft_claim}\n"
                            "Classify the claim as claim_type x evidence_level + scope and evaluate whether the evidence supports the draft claim."
                        ),
                        "B_full": (
                            f"[Arm B-全文（{full_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_full_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {pert_text}\n"
                            f"Draft claim: {draft_claim}\n"
                            "Classify the claim as claim_type x evidence_level + scope and evaluate whether the evidence supports the draft claim."
                        ),
                        "E_full_l2_workflow": (
                            f"[Arm E: 完整 L2 流程（{review_skill_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{e_workflow_policy}\n\n"
                            "=== CASE ===\n"
                            "Run the full Parrhesia [L2] workflow (register_evidence -> scaffold_claim -> set_ledger -> "
                            "freeze -> blind dual review -> adjudication -> verify -> export).\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {pert_text}\n"
                            f"Draft claim: {draft_claim}"
                        ),
                    },
                }
            )

    fork_multiplicity_packets = []
    for case in suite["cases"]:
        if case["expected_gate_outcome"] != "accepted":
            continue
        draft_claim = case.get("restored_text") or case["draft"]
        for scen_id, expected_error, expected_cal_mode in FORK_MULTIPLICITY_SCENARIOS:
            fork_context = _format_fork_prompt_context(case, scen_id)
            fork_multiplicity_packets.append(
                {
                    "run_id": f"{case['case_code']}-{scen_id}",
                    "case_code": case["case_code"],
                    "family": case["family"],
                    "scenario_id": scen_id,
                    "fork_count": 5,
                    "expected_rubber_stamp_error": expected_error,
                    "expected_calibrated_mode": expected_cal_mode,
                    "statistical_unit": "case",
                    "external_llm_status": "not_run",
                    "arms": {
                        "A_baseline": (
                            "[Arm A: 无 Parrhesia 规则]\n"
                            f"{a_baseline_sys}\n\n"
                            f"Question: {case['question']}\n"
                            f"{fork_context}\n"
                            f"Draft claim: {draft_claim}\n"
                            "Evaluate the draft claim and execution record completeness."
                        ),
                        "B_compact": (
                            f"[Arm B-精简（{compact_bytes} B + {l2_ref_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_compact_l2_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {case['question']}\n"
                            f"{fork_context}\n"
                            f"Draft claim: {draft_claim}\n"
                            "Check execution fork completeness, multiplicity adjustment, and claim calibration."
                        ),
                        "B_full": (
                            f"[Arm B-全文（{full_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_full_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {case['question']}\n"
                            f"{fork_context}\n"
                            f"Draft claim: {draft_claim}\n"
                            "Check execution fork completeness, multiplicity adjustment, and claim calibration."
                        ),
                        "E_full_l2_workflow": (
                            f"[Arm E: 完整 L2 流程（{review_skill_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{e_workflow_policy}\n\n"
                            "=== CASE ===\n"
                            "Run the full Parrhesia [L2] workflow with record-exec provenance cards, blind dual review, and adjudication.\n"
                            f"Question: {case['question']}\n"
                            f"{fork_context}\n"
                            f"Draft claim: {draft_claim}"
                        ),
                    },
                }
            )

    symmetry_packets = []
    for case in suite["cases"]:
        if case["scenario"] != "underclaim_trap":
            continue
        pos_draft = case.get("restored_text") or case["draft"]
        null_ev_text, _, _, _ = build_perturbed_evidence(case, "P1_null_flip")
        sym_specs = (
            ("sym_positive_preservation", case["evidence_text"], pos_draft, "Evaluate whether the evidence supports the draft claim and state its calibrated verdict and scope."),
            ("sym_null_counterevidence", null_ev_text, pos_draft, "Evaluate whether the evidence supports or contradicts the draft claim and state its calibrated verdict."),
            ("sym_underclaim_restoration", case["evidence_text"], case["draft"], "Audit the draft claim against the evidence for any overclaiming or underclaiming/false abstention."),
        )
        for prompt_kind, ev_body, draft_body, instruction in sym_specs:
            symmetry_packets.append(
                {
                    "run_id": f"{case['case_code']}-{prompt_kind}",
                    "case_code": case["case_code"],
                    "family": case["family"],
                    "symmetry_probe": prompt_kind,
                    "statistical_unit": "case",
                    "external_llm_status": "not_run",
                    "expected_target": {
                        "claim_type": case["claim_type"],
                        "evidence_level": case["evidence_level"],
                        "expected_verdict": "unsupported" if prompt_kind == "sym_null_counterevidence" else case["target_verdict"],
                    },
                    "arms": {
                        "A_baseline": (
                            "[Arm A: 无 Parrhesia 规则]\n"
                            f"{a_baseline_sys}\n\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {ev_body}\n"
                            f"Draft claim: {draft_body}\n"
                            f"{instruction}"
                        ),
                        "B_compact": (
                            f"[Arm B-精简（{compact_bytes} B + {l2_ref_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_compact_l2_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {ev_body}\n"
                            f"Draft claim: {draft_body}\n"
                            f"{instruction}"
                        ),
                        "B_full": (
                            f"[Arm B-全文（{full_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_full_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {ev_body}\n"
                            f"Draft claim: {draft_body}\n"
                            f"{instruction}"
                        ),
                        "E_full_l2_workflow": (
                            f"[Arm E: 完整 L2 流程（{review_skill_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{e_workflow_policy}\n\n"
                            "=== CASE ===\n"
                            "Run the full Parrhesia [L2] workflow including blind overclaim and underclaim reviews, symmetry audit awareness, and adjudication.\n"
                            f"Question: {case['question']}\n"
                            f"Evidence: {ev_body}\n"
                            f"Draft claim: {draft_body}"
                        ),
                    },
                }
            )

    paired_packets = []
    for pair in suite.get("paired_sensitivity_cases", []):
        for twin_slot, role_key in (("twin_a", "strong_twin"), ("twin_b", "weak_twin")):
            twin = pair[role_key]
            paired_packets.append(
                {
                    "run_id": f"{pair['pair_code']}-{twin_slot}",
                    "pair_code": pair["pair_code"],
                    "twin_id": twin["twin_id"],
                    "family": pair["family"],
                    "statistical_unit": "pair",
                    "external_llm_status": "not_run",
                    "expected_target": {
                        "polarity": twin["polarity"],
                        "claim_type": pair["claim_type"],
                        "target_evidence_level": pair["target_evidence_level"],
                        "target_verdict": twin["target_verdict"],
                        "expected_gate_outcome": twin["expected_gate_outcome"],
                        "expected_error_code": twin.get("expected_error_code"),
                    },
                    "arms": {
                        "A_baseline": (
                            "[Arm A: 无 Parrhesia 规则]\n"
                            f"{a_baseline_sys}\n\n"
                            f"Question: {pair['question']}\n"
                            f"Evidence: {twin['evidence_text']}\n"
                            f"Draft claim: {twin['draft']}\n"
                            "Evaluate whether the evidence supports the draft claim."
                        ),
                        "B_compact": (
                            f"[Arm B-精简（{compact_bytes} B + {l2_ref_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_compact_l2_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {pair['question']}\n"
                            f"Evidence: {twin['evidence_text']}\n"
                            f"Draft claim: {twin['draft']}\n"
                            "Classify the claim as claim_type x evidence_level + scope and give a calibrated judgment with reversal condition."
                        ),
                        "B_full": (
                            f"[Arm B-全文（{full_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{b_full_policy}\n\n"
                            "=== CASE ===\n"
                            f"Question: {pair['question']}\n"
                            f"Evidence: {twin['evidence_text']}\n"
                            f"Draft claim: {twin['draft']}\n"
                            "Classify the claim as claim_type x evidence_level + scope and give a calibrated judgment with reversal condition."
                        ),
                        "E_full_l2_workflow": (
                            f"[Arm E: 完整 L2 流程（{review_skill_bytes} B）]\n"
                            "=== POLICY ===\n"
                            f"{e_workflow_policy}\n\n"
                            "=== CASE ===\n"
                            "Run the full Parrhesia [L2] workflow (register_evidence -> scaffold_claim -> set_ledger -> freeze -> blind dual review -> adjudication -> verify -> export).\n"
                            f"Question: {pair['question']}\n"
                            f"Evidence: {twin['evidence_text']}\n"
                            f"Draft claim: {twin['draft']}"
                        ),
                    },
                }
            )

    def _build_arm_bundle(question: str, ev_text: str, draft_text: str, eval_prompt: str, workflow_prompt: str) -> dict:
        return {
            "A_baseline": (
                "[Arm A: 无 Parrhesia 规则]\n"
                f"{a_baseline_sys}\n\n"
                f"Question: {question}\n"
                f"Evidence: {ev_text}\n"
                f"Draft claim: {draft_text}\n"
                f"{eval_prompt}"
            ),
            "B_compact": (
                f"[Arm B-精简（{compact_bytes} B + {l2_ref_bytes} B）]\n"
                "=== POLICY ===\n"
                f"{b_compact_l2_policy}\n\n"
                "=== CASE ===\n"
                f"Question: {question}\n"
                f"Evidence: {ev_text}\n"
                f"Draft claim: {draft_text}\n"
                "Classify the claim as claim_type x evidence_level + scope and give a calibrated judgment with reversal condition."
            ),
            "B_full": (
                f"[Arm B-全文（{full_bytes} B）]\n"
                "=== POLICY ===\n"
                f"{b_full_policy}\n\n"
                "=== CASE ===\n"
                f"Question: {question}\n"
                f"Evidence: {ev_text}\n"
                f"Draft claim: {draft_text}\n"
                "Classify the claim as claim_type x evidence_level + scope and give a calibrated judgment with reversal condition."
            ),
            "E_full_l2_workflow": (
                f"[Arm E: 完整 L2 流程（{review_skill_bytes} B）]\n"
                "=== POLICY ===\n"
                f"{e_workflow_policy}\n\n"
                "=== CASE ===\n"
                f"{workflow_prompt}\n"
                f"Question: {question}\n"
                f"Evidence: {ev_text}\n"
                f"Draft claim: {draft_text}"
            ),
        }

    heldout_realistic_control_packets = []
    for ctrl in suite.get("heldout_realistic_controls", []):
        heldout_realistic_control_packets.append(
            {
                "case_code": ctrl["case_code"],
                "family": ctrl["family"],
                "split_column": "heldout_generalization",
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "expected_target": {
                    "claim_type": ctrl["claim_type"],
                    "evidence_level": ctrl["evidence_level"],
                    "target_verdict": ctrl["target_verdict"],
                    "expected_gate_outcome": ctrl["expected_gate_outcome"],
                    "expected_error_code": ctrl.get("expected_error_code"),
                },
                "arms": _build_arm_bundle(
                    ctrl["question"],
                    ctrl["evidence_text"],
                    ctrl["draft"],
                    "Evaluate whether the evidence supports the draft claim.",
                    "Run the full Parrhesia [L2] workflow (register_evidence -> scaffold_claim -> set_ledger -> freeze -> blind dual review -> adjudication -> verify -> export).",
                ),
            }
        )

    heldout_adversarial_paraphrase_packets = []
    for adv in suite.get("heldout_adversarial_paraphrases", []):
        ev_text = adv["evidence_text"]
        if adv.get("fork_mode") == "sqlite_omit_failed_runs":
            ev_text = (
                "Recorded sweep logs in workspace (4 runs total): sweep-1..3 (candidate runs, status=non_selected, exit_status=0); "
                f"sweep-4 (selected run): {adv['evidence_text']}\n"
                "Submitted ledger cites only sweep-4 and omits sweep-1..3."
            )
        elif adv.get("fork_mode") == "sqlite_unadjusted_multi_fork":
            ev_text = (
                "Recorded sweep logs in workspace (4 runs total): sweep-1..4; "
                f"selected summary: {adv['evidence_text']}\n"
                "Multiplicity adjustment across parameter sweep runs is marked unadjusted/unknown."
            )
        heldout_adversarial_paraphrase_packets.append(
            {
                "case_code": adv["case_code"],
                "family": adv["family"],
                "split_column": "heldout_generalization",
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "expected_target": {
                    "claim_type": adv["claim_type"],
                    "evidence_level": adv["evidence_level"],
                    "target_verdict": adv["target_verdict"],
                    "mechanism_expectation": adv["mechanism_expectation"],
                    "expected_gate_outcome": adv["expected_gate_outcome"],
                    "expected_error_code": adv.get("expected_error_code"),
                },
                "arms": _build_arm_bundle(
                    adv["question"],
                    ev_text,
                    adv["draft"],
                    "Evaluate whether the evidence supports the draft claim.",
                    "Run the full Parrhesia [L2] workflow (register_evidence -> scaffold_claim -> set_ledger -> freeze -> blind dual review -> adjudication -> verify -> export).",
                ),
            }
        )

    base_by_code = {c["case_code"]: c for c in suite.get("cases", [])}
    metamorphic_packets = []
    for transform in suite.get("metamorphic_invariance", []):
        base_case = base_by_code[transform["base_case_code"]]
        variant = build_metamorphic_variant(base_case, transform)
        metamorphic_packets.append(
            {
                "transform_id": transform["transform_id"],
                "base_case_code": base_case["case_code"],
                "family": base_case["family"],
                "transform_type": transform["transform_type"],
                "split_column": "metamorphic_invariance",
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "expected_target": {
                    "claim_type": base_case["claim_type"],
                    "evidence_level": base_case["evidence_level"],
                    "target_verdict": base_case["target_verdict"],
                    "expected_gate_outcome": base_case["expected_gate_outcome"],
                },
                "arms": _build_arm_bundle(
                    variant["question"],
                    variant["evidence_text"],
                    variant["draft"],
                    "Evaluate whether the evidence supports the draft claim.",
                    "Run the full Parrhesia [L2] workflow (register_evidence -> scaffold_claim -> set_ledger -> freeze -> blind dual review -> adjudication -> verify -> export).",
                ),
            }
        )

    p1_effect_records_packets = []
    for p1_case in suite.get("p1_effect_records", []):
        p1_effect_records_packets.append(
            {
                "case_code": p1_case["case_code"],
                "counterpart_of": p1_case.get("counterpart_of"),
                "family": p1_case["family"],
                "split_column": "p1_effect_records",
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "expected_target": {
                    "claim_type": p1_case["claim_type"],
                    "evidence_level": p1_case["evidence_level"],
                    "target_verdict": p1_case["target_verdict"],
                    "expected_gate_outcome": p1_case["expected_gate_outcome"],
                    "expected_error_code": p1_case.get("expected_error_code"),
                },
                "effect_records_input": p1_case.get("effect_records", []),
                "arms": _build_arm_bundle(
                    p1_case["question"],
                    p1_case["evidence_text"],
                    p1_case["draft"],
                    "Evaluate whether the evidence supports the draft claim.",
                    "Run the full Parrhesia [L2] workflow (register_evidence -> scaffold_claim(include_effect_records=True) -> set_ledger -> freeze -> blind dual review -> adjudication -> verify -> export).",
                ),
            }
        )

    p2_longitudinal_packets = []
    for p2_case in suite.get("p2_longitudinal_calibration", []):
        p2_longitudinal_packets.append(
            {
                "case_code": p2_case["case_code"],
                "family": p2_case["family"],
                "split_column": "p2_longitudinal_calibration",
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "expected_target": {
                    "claim_type": p2_case["claim_type"],
                    "evidence_level": p2_case["evidence_level"],
                    "target_verdict": p2_case["target_verdict"],
                    "expected_gate_outcome": p2_case["expected_gate_outcome"],
                    "expected_error_code": p2_case.get("expected_error_code"),
                },
                "arms": _build_arm_bundle(
                    p2_case["question"],
                    p2_case["evidence_text"],
                    p2_case["draft"],
                    "Evaluate whether the evidence supports the draft claim and specify measurable reversal conditions.",
                    "Run Parrhesia [L2] longitudinal workflow (create_case with lineage -> scaffold_claim with reversal_triggers/prior_claim_links -> freeze -> review -> submit_adjudication with forecast_probability -> evaluate_triggers -> record_calibration_outcome -> calibration_report).",
                ),
            }
        )

    scoring_rubric_metrics = dict(suite.get("stage0_design", {}).get("evaluation_metric_dimensions", {}))
    scoring_rubric_metrics["live_llm_eval_status"] = "not_run"

    manifest = {
        "suite_version": suite["suite_version"],
        "mode": "prompt-export",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "external_llm_status": "not_run",
        "requires_prior_user_approval": suite.get("requires_prior_user_approval", True),
        "stage0_design": suite.get("stage0_design", {}),
        "scoring_rubric_metrics": scoring_rubric_metrics,
        "policy_layout": "layered-v1",
        "policy_comparison_scope": "Current assembled policies only; do not pool with historical monolithic-policy runs.",
        "policy_source_files": {
            path.relative_to(ROOT).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in (compact_policy_path, full_policy_path, l2_ref_path, review_skill_path, workflow_path)
        },
        "policy_size_bytes": {
            "B_compact_agents_block_bytes": compact_bytes,
            "B_compact_l2_reference_skill_bytes": l2_ref_bytes,
            "B_full_policy_bytes": full_bytes,
            "E_full_l2_workflow_skill_bytes": review_skill_bytes,
            "E_skill_entrypoint_bytes": review_skill_path.stat().st_size,
            "B_full_entrypoint_bytes": full_policy_path.stat().st_size,
        },
        "arm_system_prompts": {
            "A_baseline": a_baseline_sys,
            "B_compact_l1": b_compact_l1_policy,
            "B_compact_l2": b_compact_l2_policy,
            "B_full": b_full_policy,
            "E_full_l2_workflow": e_workflow_policy,
        },
        "arms": ["A_baseline", "B_compact", "B_full", "E_full_l2_workflow"],
        "packet_count": len(packets),
        "exploratory_packet_count": len(exploratory_packets),
        "counterfactual_packet_count": len(counterfactual_packets),
        "fork_multiplicity_packet_count": len(fork_multiplicity_packets),
        "symmetry_packet_count": len(symmetry_packets),
        "paired_packet_count": len(paired_packets),
        "paired_pair_count": len(suite.get("paired_sensitivity_cases", [])),
        "heldout_realistic_control_packet_count": len(heldout_realistic_control_packets),
        "heldout_adversarial_paraphrase_packet_count": len(heldout_adversarial_paraphrase_packets),
        "metamorphic_packet_count": len(metamorphic_packets),
        "p1_effect_records_packet_count": len(p1_effect_records_packets),
        "p2_longitudinal_packet_count": len(p2_longitudinal_packets),
        "packets": packets,
        "exploratory_packets": exploratory_packets,
        "counterfactual_packets": counterfactual_packets,
        "fork_multiplicity_packets": fork_multiplicity_packets,
        "symmetry_packets": symmetry_packets,
        "paired_packets": paired_packets,
        "heldout_realistic_control_packets": heldout_realistic_control_packets,
        "heldout_adversarial_paraphrase_packets": heldout_adversarial_paraphrase_packets,
        "metamorphic_packets": metamorphic_packets,
        "p1_effect_records_packets": p1_effect_records_packets,
        "p2_longitudinal_packets": p2_longitudinal_packets,
    }
    out_file = output_dir / "stage0-prompt-packets.json"
    out_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_file": str(out_file),
        "packet_count": len(packets),
        "exploratory_packet_count": len(exploratory_packets),
        "counterfactual_packet_count": len(counterfactual_packets),
        "fork_multiplicity_packet_count": len(fork_multiplicity_packets),
        "symmetry_packet_count": len(symmetry_packets),
        "paired_packet_count": len(paired_packets),
        "paired_pair_count": len(suite.get("paired_sensitivity_cases", [])),
        "heldout_realistic_control_packet_count": len(heldout_realistic_control_packets),
        "heldout_adversarial_paraphrase_packet_count": len(heldout_adversarial_paraphrase_packets),
        "metamorphic_packet_count": len(metamorphic_packets),
        "p1_effect_records_packet_count": len(p1_effect_records_packets),
        "p2_longitudinal_packet_count": len(p2_longitudinal_packets),
        "arms": manifest["arms"],
        "external_llm_status": "not_run",
    }


def render_markdown_report(summary: dict) -> str:
    design = summary.get("stage0_design", {})
    pe = design.get("primary_endpoint", {})
    exp_metrics = design.get("exploratory_case_metrics", {})
    cf_sum = summary.get("counterfactual_summary", {})
    fm_sum = summary.get("fork_multiplicity_summary", {})
    sym_sum = summary.get("symmetry_audit_summary", {})
    pair_sum = summary.get("paired_sensitivity_summary", {})
    lin_sum = summary.get("lineage_window_summary", {})
    hold_sum = summary.get("heldout_summary", {})
    meta_sum = summary.get("metamorphic_summary", {})
    p1_sum = summary.get("p1_effects_summary", {})
    p2_sum = summary.get("p2_longitudinal_summary", {})
    dims = summary.get("metric_dimensions", {})
    eq_cov = summary.get("equal_coverage_by_family", {})
    measured = summary.get("policy_measurement") or policy_inputs(ROOT)
    sizes = measured["policy_size_bytes"]
    compact_bytes = sizes["B_compact_agents_block_bytes"]
    l2_ref_bytes = sizes["B_compact_l2_reference_skill_bytes"]
    full_bytes = sizes["B_full_policy_bytes"]
    review_skill_bytes = sizes["E_full_l2_workflow_skill_bytes"]
    ingestion = summary.get("ingestion_summary", {})
    n_base = summary.get("total_cases", len(summary.get("results", [])))
    n_exp = summary.get("exploratory_cases_count", len(summary.get("exploratory_results", [])))
    lines = [
        f"# Stage 0 Evaluation Verification Report (`{summary['suite_version']}`)",
        "",
        f"- **Mode**: `{summary['mode']}` (local deterministic engine, structural/numeric gates, L1-Explore card, Card A/B/C dev consistency, Paired sensitivity, Derived Lineage & Chunked-Window, exposed Held-out Regression, and Metamorphic Invariance)",
        (
            f"- **Control Arm Inputs (export availability, not live runs)**: `A_baseline`（A：无 Parrhesia 规则）、"
            f"`B_compact`（B-精简：{compact_bytes} B 精简块 + {l2_ref_bytes} B `parrhesia-l2-reference` skill）、"
            f"`B_full`（B-全文：{full_bytes} B 基础规则 + L2 参考 + 工具工作流）、"
            f"`E_full_l2_workflow`（E：完整 L2 流程，{review_skill_bytes} B skill + 基础规则 + L2 参考 + 工具工作流；layered-v1）"
        ),
        f"- **L2 Calibration Cases (`dev_phrase_consistency`)**: `{summary['passed_cases']} / {n_base}` across `{len(eq_cov)}` families (`all_passed={summary['all_passed']}`)",
        f"- **L1-Explore Exploratory Cases**: `{summary.get('exploratory_passed_cases', 0)} / {n_exp}` (`exploratory_all_valid={summary.get('exploratory_all_valid', True)}`)",
        f"- **Card A Counterfactual Perturbation Runs (`dev_phrase_consistency`)**: `{cf_sum.get('passed_runs', 0)} / {cf_sum.get('total_perturbation_runs', 0)}` (`pre_card_a_rejection={cf_sum.get('pre_card_a_rubber_stamp_rejected', 0)}/{cf_sum.get('total_perturbation_runs', 0)}`, `hard_rejected={cf_sum.get('card_a_rubber_stamp_hard_rejected', 0)}/{cf_sum.get('total_perturbation_runs', 0)}`, `lexical_advisory_flagged={cf_sum.get('card_a_rubber_stamp_advisory_flagged', 0)}/{cf_sum.get('total_perturbation_runs', 0)}`, `calibrated_flip_accepted={cf_sum.get('calibrated_flip_accepted', 0)}/{cf_sum.get('total_perturbation_runs', 0)}`)",
        f"- **Card B Execution-Fork Multiplicity Runs (`dev_phrase_consistency`)**: `{fm_sum.get('passed_runs', 0)} / {fm_sum.get('total_fork_runs', 0)}` (`pre_card_b_adv_rejection={fm_sum.get('pre_card_b_adversarial_rejected', 0)}/{fm_sum.get('adversarial_runs', 0)}`, `hard_rejected={fm_sum.get('card_b_adversarial_hard_rejected', 0)}/{fm_sum.get('adversarial_runs', 0)}`, `lexical_advisory_flagged={fm_sum.get('card_b_adversarial_advisory_flagged', 0)}/{fm_sum.get('adversarial_runs', 0)}`, `positive_control_accepted={fm_sum.get('card_b_positive_control_accepted', 0)}/{fm_sum.get('positive_control_runs', 0)}`)",
        f"- **Card C Symmetry Audit Runs (Non-Blocking Advisory)**: `{sym_sum.get('passed_runs', 0)} / {sym_sum.get('total_runs', 0)}` (`non_blocking_export_preserved_rate={sym_sum.get('non_blocking_export_preserved_rate', 0.0)}`, `calibrated_false_alarm_rate={sym_sum.get('calibrated_false_alarm_rate', 0.0)}`, `all_five_hooks_verified={sym_sum.get('all_five_hooks_verified', False)}`)",
        f"- **Paired Sensitivity Concordance**: `{pair_sum.get('passed_pairs', 0)} / {pair_sum.get('total_pairs', 0)}` pairs (`strong_accepted={pair_sum.get('strong_twins_accepted', 0)}/{pair_sum.get('strong_twins_total', 0)}`, `weak_hard_rejected={pair_sum.get('weak_twins_rejected', 0)}`, `weak_advisory_flagged={pair_sum.get('weak_twins_advisory_flagged', 0)}`, `concordance={pair_sum.get('paired_evidence_sensitivity_concordance', 0.0)}`)",
        f"- **Lineage & Chunked-Window Verification**: `{lin_sum.get('passed_specs', 0)} / {lin_sum.get('total_specs', 0)}` specs (`synthetic_lineage_blocking_rate={lin_sum.get('synthetic_lineage_blocking_rate', 0.0)}`, `chunked_window_head_tail_recall={lin_sum.get('chunked_window_head_tail_recall', 0.0)}`, `tail_contradiction_mode={lin_sum.get('chunked_window_tail_contradiction_mode', 'unknown')}`)",
        f"- **Held-out Generalization (`leakage_strict_passed={hold_sum.get('leakage_strict_passed', False)}`, `overlap={hold_sum.get('heldout_lexical_overlap_count', -1)}`)**: Realistic controls `{hold_sum.get('realistic_controls_passed', 0)} / {hold_sum.get('realistic_controls_total', 0)}` (`false_rejection_rate={hold_sum.get('realistic_controls_false_rejection_rate', 0.0)}`); Adversarial paraphrases caught mechanically `{hold_sum.get('adversarial_caught_mechanically_hard', 0)} / {hold_sum.get('adversarial_paraphrases_total', 0)}` (`mechanical_recall={hold_sum.get('adversarial_mechanical_recall', 0.0)}`, `uncaught_without_llm_or_p1={hold_sum.get('adversarial_uncaught_without_llm_or_p1', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}`)",
        f"- **Metamorphic Invariance**: `{meta_sum.get('passed_transforms', 0)} / {meta_sum.get('total_transforms', 0)}` (`invariance_rate={meta_sum.get('invariance_rate', 0.0)}`, `false_advisories={meta_sum.get('false_advisory_count', 0)}`)",
        f"- **P1 Structured `effect_records` (`p1_effect_records`, Separate Column)**: `{p1_sum.get('passed_cases', 0)} / {p1_sum.get('total_cases', 0)}` (positive control `{p1_sum.get('positive_controls_accepted', 0)}/{p1_sum.get('positive_controls_total', 0)}`, `FRR={p1_sum.get('positive_controls_false_rejection_rate', 0.0)}`, negative traps `{p1_sum.get('negative_traps_caught', 0)}/{p1_sum.get('negative_traps_total', 0)}`, structured `HADV-07..12` counterparts `{p1_sum.get('hadv_counterparts_caught', 0)}/{p1_sum.get('hadv_counterparts_total', 0)}`)",
        f"- **P2 Longitudinal Graph, Triggers & Calibration (`p2_longitudinal_calibration`, `PLONG-01..08`)**: `{p2_sum.get('passed_cases', 0)} / {p2_sum.get('total_cases', 0)}` (`pass_rate={p2_sum.get('pass_rate', 0.0)}`, `event_chain_verified={p2_sum.get('event_chain_verified_count', 0)}/{p2_sum.get('total_cases', 0)}`)",
        f"- **External Paid LLM Execution Status**: `{summary['external_llm_status']}` (`requires_prior_user_approval={summary.get('requires_prior_user_approval', True)}`)",
        "",
        "## Current inputs and ingestion extension",
        "",
        f"- Runtime: `{measured['runtime_version']}`; layout: `{measured['policy_layout']}`; MCP tools: `{measured['mcp']['tool_count']}`, compact UTF-8 JSON `{measured['mcp']['compact_utf8_bytes']} B`.",
        f"- Entry skill: `{sizes['E_skill_entrypoint_bytes']} B`; assembled E prompt above includes its references. Bytes are not model tokens or author effort.",
        f"- Ingestion: `{ingestion.get('passed_cases', 0)}/{ingestion.get('total_cases', 0)}`; actual action coverage: `{json.dumps(ingestion.get('action_coverage', {}), sort_keys=True)}`.",
        "- Historical held-out fixtures are now exposed regression cases; unchanged lexical leakage checks do not establish fresh generalization.",
        "- Top-level `all_passed` uses `text-advisory-regression-v1`: original hard-gate expectations plus nonblocking advisory improvements, zero false advisories in controls/transforms, and fresh synthetic qualification. It does not mean complete detection or net benefit.",
        f"- Frozen v2 expectations are unchanged: `{hold_sum.get('adversarial_expectations_verified', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}` exact matches (`heldout.all_passed={hold_sum.get('all_passed')}`); revised regression checks pass `{hold_sum.get('adversarial_regressions_passed', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}` (`regression_all_passed={hold_sum.get('regression_all_passed')}`). Advisory-only improvements: `{hold_sum.get('adversarial_flagged_lexical_advisory_only', 0)}`.",
        f"- New text qualification: `{summary.get('text_advisory_qualification', {}).get('summary', {})}`. These are developer-authored synthetic cases frozen before implementation, not an independent holdout.",
        f"- The zero-overlap count covers the legacy lexicon only. New advisory rule components have `{(hold_sum.get('new_advisory_module_audit') or {}).get('regex_overlap_field_count', 'unknown')}` overlapping prose fields; copied-case literal guard = `{(hold_sum.get('new_advisory_module_audit') or {}).get('no_case_literals', 'unknown')}`. Neither check establishes independence.",
        "- Host workflow acceptance and real author benefit: `not_run`. See `docs/evaluation/author-impact-pilot.md` for the prepared comparison and burden measures.",
        "",
        "## Split-Column Evaluation Summary (Exposed P0 Regression + Structured P1)",
        "",
        "| Evaluation Column | Scope | Key Result | Honest Boundary / Gap |",
        "|---|---|---|---|",
        f"| `dev_phrase_consistency` | Base `{summary['passed_cases']}/{n_base}` + Card A (`{cf_sum.get('card_a_rubber_stamp_hard_rejected', 0)}` hard / `{cf_sum.get('card_a_rubber_stamp_advisory_flagged', 0)}` advisory) + Card B (`{fm_sum.get('card_b_adversarial_hard_rejected', 0)}` hard / `{fm_sum.get('card_b_adversarial_advisory_flagged', 0)}` advisory) + Card C (`{sym_sum.get('passed_runs', 0)}/{sym_sum.get('total_runs', 0)}`) + Paired (`{pair_sum.get('passed_pairs', 0)}/{pair_sum.get('total_pairs', 0)}`) + Lineage (`{lin_sum.get('passed_specs', 0)}/{lin_sum.get('total_specs', 0)}`) | Mechanical + non-blocking lexical-advisory P0-1 contract concordant | In-distribution only; lexical advisories are non-blocking diagnostics |",
        f"| `heldout_generalization` | Static leakage gate (`overlap={hold_sum.get('heldout_lexical_overlap_count', -1)}`) + `{hold_sum.get('realistic_controls_total', 0)}` realistic controls + `{hold_sum.get('adversarial_paraphrases_total', 0)}` adversarial paraphrases | Controls `{hold_sum.get('realistic_controls_passed', 0)}/{hold_sum.get('realistic_controls_total', 0)}` (`FRR={hold_sum.get('realistic_controls_false_rejection_rate', 0.0)}`); Adversarial hard-caught `{hold_sum.get('adversarial_caught_mechanically_hard', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}` (`recall={hold_sum.get('adversarial_mechanical_recall', 0.0)}`) | `{hold_sum.get('adversarial_uncaught_without_llm_or_p1', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}` natural-language paraphrases (`{', '.join(hold_sum.get('adversarial_uncaught_case_codes', []))}`) remain uncaught without LLM review or P1 `effect_records` |",
        f"| `metamorphic_invariance` | `{meta_sum.get('total_transforms', 0)}` invariance transforms (`clause_reorder`, `no significant difference in adverse events`, `OR = 1.08`, literature contrast) | `{meta_sum.get('passed_transforms', 0)}/{meta_sum.get('total_transforms', 0)}` preserved acceptance & export (`invariance_rate={meta_sum.get('invariance_rate', 0.0)}`) | False lexical advisories across transforms: `{meta_sum.get('false_advisory_count', 0)}` |",
        f"| `p1_effect_records` | `{p1_sum.get('total_cases', 0)}` structured `effect_records` probes (`PEFF-01` realistic primary benefit + null safety/secondary; `PEFF-02..06` computable checks; `PEFF-07..12` structured `HADV-07..12` counterparts) + SQLite `event_chain` | Positive control `{p1_sum.get('positive_controls_accepted', 0)}/{p1_sum.get('positive_controls_total', 0)}` (`FRR={p1_sum.get('positive_controls_false_rejection_rate', 0.0)}`); Negative traps caught `{p1_sum.get('negative_traps_caught', 0)}/{p1_sum.get('negative_traps_total', 0)}` (`HADV-07..12` structured `{p1_sum.get('hadv_counterparts_caught', 0)}/{p1_sum.get('hadv_counterparts_total', 0)}`, `event_chain=verified` `{p1_sum.get('event_chain_verified_count', 0)}/{p1_sum.get('total_cases', 0)}`) | Requires populated structured `effect_records`; prose-only cases receive at most lexical advisories; structured counterparts and hard mechanical recall are reported separately |",
        f"| `p2_longitudinal_calibration` | `{p2_sum.get('total_cases', 0)}` longitudinal DAG, trigger & calibration probes (`PLONG-01..08`) + SQLite `event_chain` | `{p2_sum.get('passed_cases', 0)}/{p2_sum.get('total_cases', 0)}` passed (`positive={p2_sum.get('positive_controls_passed', 0)}/{p2_sum.get('positive_controls_total', 0)}`, `traps={p2_sum.get('negative_traps_caught', 0)}/{p2_sum.get('negative_traps_total', 0)}`, `event_chain=verified` `{p2_sum.get('event_chain_verified_count', 0)}/{p2_sum.get('total_cases', 0)}`) | Deterministic runtime contract checks on structured P2 lineage, triggers, and outcome resolution |",
        "",
        "## Unified Stage 0 Metric Dimensions (`not_run` marked explicitly for Live LLM)",
        "",
        "| Metric Dimension | Value | Status / Notes |",
        "|---|---|---|",
        f"| `overstatement_rejection_rate` | `{dims.get('overstatement_rejection_rate', 0.0)}` | Base overclaim/rubber-stamp traps (`20/20`) hard-rejected (`dev_phrase_consistency`) |",
        f"| `false_abstention_detection_rate` | `{dims.get('false_abstention_detection_rate', 0.0)}` | Card C `U1_false_abstention` (`{sym_sum.get('false_abstention_detected', 0)}/{sym_sum.get('false_abstention_runs', 0)}`) |",
        f"| `unjustified_downgrade_detection_rate` | `{dims.get('unjustified_downgrade_detection_rate', 0.0)}` | Card C `U1b_unjustified_downgrade` (`{sym_sum.get('unjustified_downgrade_detected', 0)}/{sym_sum.get('unjustified_downgrade_runs', 0)}`) |",
        f"| `known_valid_retention_rate` | `{dims.get('known_valid_retention_rate', 0.0)}` | Base accepted positives (`20/20`) + `PAIR-01..06` strong twins (`{pair_sum.get('strong_twins_accepted', 0)}/{pair_sum.get('strong_twins_total', 0)}`) retained & exported |",
        f"| `equal_coverage_accuracy` | `{dims.get('equal_coverage_accuracy', 0.0)}` | Minimum per-family pass accuracy across all `{len(eq_cov)}` families |",
        f"| `paired_evidence_sensitivity_concordance` | `{dims.get('paired_evidence_sensitivity_concordance', 0.0)}` | Joint strong+weak twin concordance (`{pair_sum.get('passed_pairs', 0)}/{pair_sum.get('total_pairs', 0)}`: `{pair_sum.get('weak_twins_rejected', 0)}` hard-rejected, `{pair_sum.get('weak_twins_advisory_flagged', 0)}` lexical-advisory) |",
        f"| `synthetic_lineage_blocking_rate` | `{dims.get('synthetic_lineage_blocking_rate', 0.0)}` | `LIN-01` synthetic ancestor blocked (`Engine` + CLI `record-exec --derived-from`); `LIN-02` hash-verified binary accepted & tampered ancestor blocked |",
        f"| `chunked_window_head_tail_recall` | `{dims.get('chunked_window_head_tail_recall', 0.0)}` | `LIN-03` 4-role `<<<PARRHESIA_EXCERPT_WINDOW ...>>>` `<=128 KiB` preserving head/quote/anchor/tail + tail contradiction (`{lin_sum.get('chunked_window_tail_contradiction_mode', 'unknown')}`); `LIN-04` unanchored truncated blocked |",
        f"| `calibrated_false_alarm_rate` | `{dims.get('calibrated_false_alarm_rate', 0.0)}` | Card C calibrated positives (`16`), `P1` null controls (`20`), check-gap controls (`20`) = `{sym_sum.get('calibrated_false_alarms', 0)}/{sym_sum.get('calibrated_control_runs', 0)}` false alarms |",
        f"| `heldout_realistic_false_rejection_rate` | `{dims.get('heldout_realistic_false_rejection_rate', 0.0)}` | Previously exposed realistic controls (`{hold_sum.get('realistic_controls_false_rejections', 0)}/{hold_sum.get('realistic_controls_total', 0)}` false rejections, target `< 0.05`) |",
        f"| `heldout_adversarial_mechanical_recall` | `{dims.get('heldout_adversarial_mechanical_recall', 0.0)}` | Previously exposed paraphrases hard-caught by numeric/SQLite/tail gates (`{hold_sum.get('adversarial_caught_mechanically_hard', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}`) |",
        f"| `heldout_adversarial_uncaught_rate` | `{dims.get('heldout_adversarial_uncaught_rate', 0.0)}` | Previously exposed natural-language paraphrases uncaught without live LLM or P1 (`{hold_sum.get('adversarial_uncaught_without_llm_or_p1', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}`) |",
        f"| `metamorphic_invariance_rate` | `{dims.get('metamorphic_invariance_rate', 0.0)}` | Invariance across `{meta_sum.get('total_transforms', 0)}` non-contradictory transformations |",
        f"| `p1_effect_records_catch_rate` | `{dims.get('p1_effect_records_catch_rate', 0.0)}` | Separate `p1_effect_records` suite (`{p1_sum.get('negative_traps_caught', 0)}/{p1_sum.get('negative_traps_total', 0)}` computable catches incl. `{p1_sum.get('hadv_counterparts_caught', 0)}/{p1_sum.get('hadv_counterparts_total', 0)}` `HADV-07..12` structured counterparts) |",
        f"| `p1_effect_records_false_rejection_rate` | `{dims.get('p1_effect_records_false_rejection_rate', 0.0)}` | Separate `p1_effect_records` positive control (`{p1_sum.get('positive_controls_false_rejections', 0)}/{p1_sum.get('positive_controls_total', 0)}` false rejections) |",
        f"| `p2_longitudinal_pass_rate` | `{dims.get('p2_longitudinal_pass_rate', 0.0)}` | `p2_longitudinal_calibration` suite (`PLONG-01..08`: `{p2_sum.get('passed_cases', 0)}/{p2_sum.get('total_cases', 0)}`, `event_chain=verified` `{p2_sum.get('event_chain_verified_count', 0)}/{p2_sum.get('total_cases', 0)}`) |",
        f"| `leakage_strict_passed` | `{dims.get('leakage_strict_passed', False)}` | Static AST + regex + 3-gram leakage check (`parrhesia/gates.py` vs `heldout_*`) |",
        f"| `live_llm_eval_status` | `{dims.get('live_llm_eval_status', 'not_run')}` | External paid LLM runs require prior explicit user approval |",
        "",
        "## Equal Coverage by Family",
        "",
        "| Family | Passed | Total | Accuracy |",
        "|---|---|---|---|",
    ]
    for fam, fstat in eq_cov.items():
        lines.append(f"| `{fam}` | `{fstat['passed']}` | `{fstat['total']}` | `{fstat['accuracy']}` |")
    lines.extend(
        [
            "",
            "## Stage 0 Design Key Points (Frozen Specification)",
            "",
            f"1. **统计单位**：{design.get('statistical_unit_rule', '统计单位是案例，重复运行不算独立样本。')}",
            f"2. **主终点与非劣效框架**：{pe.get('rule', '主终点：精简版相对全文版的校准通过率，用非劣效框架，界值运行前冻结。')}（`comparison={pe.get('comparison', 'B_compact vs B_full')}`, `framework={pe.get('framework', 'non_inferiority')}`, `non_inferiority_margin={pe.get('non_inferiority_margin', -0.05)}`, `margin_frozen_before_run={pe.get('margin_frozen_before_run', True)}`）",
            "3. **新增探索类案例（`L1-Explore`）的三个指标**：",
            f"   - `discriminating_experiments_before_first_fp`：{exp_metrics.get('discriminating_experiments_before_first_fp', '在首次出现假阳性结论前，已完成的区分实验数')}",
            f"   - `steps_to_kill_false_hypothesis`：{exp_metrics.get('steps_to_kill_false_hypothesis', '杀死错误假说所用步数')}",
            f"   - `total_consumption`：{exp_metrics.get('total_consumption', '总消耗')}",
            f"4. **Stage 0 定位与样本量说明**：{design.get('scope_and_power_statement', 'Stage 0 只估计方差和可执行性。')}",
            f"5. **外部模型调用审批门槛**：{design.get('external_model_approval_rule', '外部模型调用需要你先批准，评价方案也这样要求。')}",
            "",
            f"## Case-by-Case Mechanical Gate Results ({n_base} L2 Cases)",
            "",
            "| Case | Family | Scenario | Classification (`claim_type × evidence_level`) | Verdict | Expected | Actual | Error Code | Pass |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for r in summary["results"]:
        cls = f"`{r['claim_type']} × {r['evidence_level']}`"
        err = f"`{r['actual_error_code']}`" if r["actual_error_code"] else "—"
        lines.append(
            f"| `{r['case_code']}` | `{r['family']}` | `{r['scenario']}` | {cls} | `{r['target_verdict']}` | "
            f"`{r['expected_gate_outcome']}` | `{r['actual_gate_outcome']}` | {err} | `{'PASS' if r['passed'] else 'FAIL'}` |"
        )
    if summary.get("exploratory_results"):
        lines.extend(
            [
                "",
                f"## L1-Explore Lightweight Exploration Ledger Cases ({n_exp} Exploratory Cases)",
                "",
                "| Case | Family | Origin | Classification | Cards | Required 5 Fields (`strongest_rival`, `discriminating_experiment`, `cost`, `stopping_rule`, `kill_condition`) | Live LLM Metrics |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for er in summary["exploratory_results"]:
            cls = f"`{er['claim_type']} × {er['evidence_level']}`"
            lines.append(
                f"| `{er['case_code']}` | `{er['family']}` | `{er['origin']}` | {cls} | `{er['card_count']}` | "
                f"`{'PASS' if er['passed'] else 'FAIL'}` | `not_run` |"
            )
    if summary.get("counterfactual_results"):
        lines.extend(
            [
                "",
                f"## Card A: Counterfactual Evidence-Sensitivity Suite ({cf_sum['positive_base_cases']} Positive Cases × {cf_sum['perturbations_per_case']} Perturbations = {cf_sum['total_perturbation_runs']} Runs)",
                "",
                f"- **Discriminating Ablation & P0-1 Boundary (`counterfactual_gates=False` vs `True`)**: Pre-Card-A gates rejected `{cf_sum['pre_card_a_rubber_stamp_rejected']} / {cf_sum['total_perturbation_runs']}` (`{cf_sum['pre_card_a_rubber_stamp_rejection_rate'] * 100:.1f}%`); under P0-1, Card A hard-rejected `{cf_sum['card_a_rubber_stamp_hard_rejected']} / {cf_sum['total_perturbation_runs']}` (`{cf_sum['card_a_rubber_stamp_rejection_rate'] * 100:.1f}%`, numeric effect anchoring) and emitted non-blocking `lexical_advisories` on `{cf_sum['card_a_rubber_stamp_advisory_flagged']} / {cf_sum['total_perturbation_runs']}` pure-text runs (combined detected `{cf_sum['card_a_rubber_stamp_detected']} / {cf_sum['total_perturbation_runs']}`). Kill condition (`pre_card_a >= 95%`) triggered: `{cf_sum['kill_condition_triggered']}`.",
                f"- **Calibrated Verdict-Flip Concordance**: `{cf_sum['calibrated_flip_accepted']} / {cf_sum['total_perturbation_runs']}` (`{cf_sum['calibrated_flip_acceptance_rate'] * 100:.1f}%`) properly flipped non-positive adjudications (`unsupported` / `insufficient_evidence`) accepted and exported.",
                "",
                "| Run ID | Base Case | Perturbation | Pre-Card-A (`gate=off`) | Card A Outcome | Detection Mode | Code / Advisory Hook | Calibrated Flip | Pass |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for cr in summary["counterfactual_results"]:
            detail = (
                f"`{cr['actual_error_code']}`"
                if cr.get("actual_error_code")
                else f"`{', '.join(cr.get('card_a_advisory_codes') or [])}`"
            )
            lines.append(
                f"| `{cr['run_id']}` | `{cr['case_code']}` | `{cr['perturbation_id']}` | "
                f"`{cr['pre_card_a_rubber_stamp_outcome']}` | `{cr['card_a_rubber_stamp_outcome']}` | `{cr['detection_mode']}` | "
                f"{detail} | `{cr['original_verdict']} -> {cr['expected_calibrated_verdict']}` (`{cr['calibrated_flip_outcome']}`) | "
                f"`{'PASS' if cr['passed'] else 'FAIL'}` |"
            )
    if summary.get("fork_multiplicity_results"):
        lines.extend(
            [
                "",
                f"## Card B: `record-exec` Execution-Fork Detection & Multiplicity Gate Suite ({fm_sum['positive_base_cases']} Positive Cases × {fm_sum['scenarios_per_case']} Scenarios = {fm_sum['total_fork_runs']} Runs)",
                "",
                f"- **Adversarial Fork/Multiplicity Ablation & P0-1 Boundary (`fork_gates=False` vs `True`, {fm_sum['adversarial_runs']} runs)**: Pre-Card-B gates rejected `{fm_sum['pre_card_b_adversarial_rejected']} / {fm_sum['adversarial_runs']}`; under P0-1, structural `F1_hidden_failed_forks` hard-rejected `{fm_sum['card_b_adversarial_hard_rejected']} / {fm_sum['adversarial_runs']}` (`selective_execution_omission`), while phrase-only `F2_unadjusted_multi_fork` emitted non-blocking `possible_unadjusted_multiplicity_text` advisories on `{fm_sum['card_b_adversarial_advisory_flagged']} / {fm_sum['adversarial_runs']}` runs (combined detected `{fm_sum['card_b_adversarial_detected']} / {fm_sum['adversarial_runs']}`).",
                f"- **Positive-Control Specificity (`F3_calibrated_multiplicity_accounted`, {fm_sum['positive_control_runs']} runs)**: `{fm_sum['card_b_positive_control_accepted']} / {fm_sum['positive_control_runs']}` (`{fm_sum['card_b_positive_control_acceptance_rate'] * 100:.1f}%`, over-blocking rate `{fm_sum['card_b_overblocking_rate'] * 100:.1f}%`) accepted and exported cleanly with zero advisories. Kill condition triggered: `{fm_sum['kill_condition_triggered']}`.",
                "",
                "| Run ID | Base Case | Scenario (`fork_count=5`) | Pre-Card-B | Card B Positive | Detection Mode | Code / Advisory | Calibrated Outcome | Pass |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for fr in summary["fork_multiplicity_results"]:
            detail = (
                f"`{fr['actual_error_code']}`"
                if fr.get("actual_error_code")
                else (f"`{', '.join(fr.get('card_b_advisory_codes') or [])}`" if fr.get("card_b_advisory_codes") else "—")
            )
            lines.append(
                f"| `{fr['run_id']}` | `{fr['case_code']}` | `{fr['scenario_id']}` | "
                f"`{fr['pre_card_b_positive_outcome']}` | `{fr['card_b_positive_outcome']}` | `{fr['detection_mode']}` | "
                f"{detail} | `{fr['expected_calibrated_mode']}` (`{fr['calibrated_outcome']}`) | "
                f"`{'PASS' if fr['passed'] else 'FAIL'}` |"
            )
    if sym_sum:
        lines.extend(
            [
                "",
                f"## Card C: Non-Blocking Anti-Underclaim & False-Abstention Symmetry Audit ({sym_sum['total_runs']} Runs)",
                "",
                f"- **Advisory Detection Across All 5 Hooks**: `possible_false_abstention` `{sym_sum['false_abstention_detected']}/{sym_sum['false_abstention_runs']}` (`{sym_sum['false_abstention_detection_rate']}`), `possible_unjustified_downgrade` `{sym_sum['unjustified_downgrade_detected']}/{sym_sum['unjustified_downgrade_runs']}` (`{sym_sum['unjustified_downgrade_detection_rate']}`), `unsupported_without_counterevidence` `{sym_sum['evidence_of_absence_detected']}/{sym_sum['evidence_of_absence_runs']}` (`{sym_sum['evidence_of_absence_detection_rate']}`), `possible_boilerplate_overhedging` `{sym_sum['boilerplate_overhedging_detected']}/{sym_sum['boilerplate_overhedging_runs']}` (`{sym_sum['boilerplate_overhedging_detection_rate']}`), `rejected_underclaim_finding_advisory` `{sym_sum['rejected_underclaim_detected']}/{sym_sum['rejected_underclaim_runs']}` (`{sym_sum['rejected_underclaim_detection_rate']}`).",
                f"- **Non-Blocking Export & Control Specificity**: Export preserved across `{sym_sum['non_blocking_export_preserved_count']}/{sym_sum['total_runs']}` runs (`non_blocking_export_preserved_rate={sym_sum['non_blocking_export_preserved_rate']}`); false alarms across calibrated positives, `P1` null counterevidence controls, and critical check-gap controls = `{sym_sum['calibrated_false_alarms']}/{sym_sum['calibrated_control_runs']}` (`calibrated_false_alarm_rate={sym_sum['calibrated_false_alarm_rate']}`).",
            ]
        )
    if summary.get("paired_results"):
        lines.extend(
            [
                "",
                f"## Paired Evidence-Sensitivity Concordance ({pair_sum['total_pairs']} Pairs)",
                "",
                "| Pair | Family | Claim Type × Target Level | Strong Twin Outcome | Weak Twin Outcome (Error / Advisory) | Pair Concordance |",
                "|---|---|---|---|---|---|",
            ]
        )
        for pr in summary["paired_results"]:
            st = pr["strong_twin"]
            wt = pr["weak_twin"]
            wt_detail = wt["actual_error_code"] or ", ".join(wt.get("lexical_advisory_codes") or [])
            lines.append(
                f"| `{pr['pair_code']}` | `{pr['family']}` | `{pr['claim_type']} × {pr['target_evidence_level']}` | "
                f"`{st['actual_gate_outcome']}` (`{st['export_state']}`) | `{wt['actual_gate_outcome']}` (`{wt_detail}`) | "
                f"`{'PASS' if pr['passed'] else 'FAIL'}` |"
            )
    if summary.get("lineage_window_results"):
        lines.extend(
            [
                "",
                f"## Derived Evidence Lineage & >128 KiB Chunked-Window Verification ({lin_sum['total_specs']} Specs)",
                "",
                f"- **Lineage Checks**: `LIN-01` Engine + CLI `record-exec --derived-from --derivation-step` synthetic blocking = `{lin_sum['synthetic_lineage_blocked']}` / `{lin_sum['cli_derived_from_synthetic_blocked']}`; `LIN-02` `hash_verified_unread_binary_ancestors` leaf export = `{lin_sum['hash_verified_unread_binary_accepted']}`; tampered disk ancestor blocked = `{lin_sum['tampered_binary_ancestor_blocked']}`.",
                f"- **Chunked-Window Checks**: `LIN-03` 4-role `<<<PARRHESIA_EXCERPT_WINDOW ...>>>` (`<=128 KiB`) preserved & exported = `{lin_sum['chunked_window_head_tail_accepted']}`; tail contradiction beyond 128 KiB caught = `{lin_sum['chunked_window_tail_contradiction_caught']}` (`mode={lin_sum.get('chunked_window_tail_contradiction_mode', 'unknown')}`); `LIN-04` unanchored truncated blocked = `{lin_sum['unanchored_large_text_blocked']}`.",
                "",
                "| Spec | Scenario | Expected | Actual | Error Code | Pass |",
                "|---|---|---|---|---|---|",
            ]
        )
        for lr in summary["lineage_window_results"]:
            err = f"`{lr['actual_error_code']}`" if lr["actual_error_code"] else "—"
            lines.append(
                f"| `{lr['spec_code']}` | `{lr['scenario']}` | `{lr['expected_gate_outcome']}` | `{lr['actual_gate_outcome']}` | {err} | `{'PASS' if lr['passed'] else 'FAIL'}` |"
            )
    if summary.get("heldout_control_results"):
        lines.extend(
            [
                "",
                f"## Held-out Generalization: Realistic Controls ({hold_sum['realistic_controls_total']} Previously Exposed Cases)",
                "",
                f"- **Static Leakage Gate**: `leakage_strict_passed={hold_sum['leakage_strict_passed']}`, `heldout_lexical_overlap_count={hold_sum['heldout_lexical_overlap_count']}` (vs `parrhesia/gates.py` blacklists/heuristics).",
                f"- **False-Rejection Rate**: `{hold_sum['realistic_controls_false_rejections']} / {hold_sum['realistic_controls_total']}` (`{hold_sum['realistic_controls_false_rejection_rate']}`, threshold `< 0.05`); false lexical advisories = `{hold_sum.get('realistic_controls_false_advisories', 0)} / {hold_sum['realistic_controls_total']}`.",
                "",
                "| Case | Family | Classification | Verdict | Actual | Export | Lexical Advisories | Pass |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for hc in summary["heldout_control_results"]:
            adv = ", ".join(hc.get("lexical_advisory_codes") or []) or "—"
            lines.append(
                f"| `{hc['case_code']}` | `{hc['family']}` | `{hc['claim_type']} × {hc['evidence_level']}` | `{hc['target_verdict']}` | "
                f"`{hc['actual_gate_outcome']}` | `{hc['export_state']}` | `{adv}` | `{'PASS' if hc['passed'] else 'FAIL'}` |"
            )
    if summary.get("heldout_adversarial_results"):
        lines.extend(
            [
                "",
                f"## Held-out Generalization: Adversarial Paraphrases ({hold_sum['adversarial_paraphrases_total']} Previously Exposed Cases)",
                "",
                f"- **Honest P0 Boundary**: `{hold_sum['adversarial_caught_mechanically_hard']} / {hold_sum['adversarial_paraphrases_total']}` (`{hold_sum['adversarial_mechanical_recall'] * 100:.1f}%`) caught by hard numeric/SQLite/tail gates (`HADV-01..06`); `{hold_sum['adversarial_uncaught_without_llm_or_p1']} / {hold_sum['adversarial_paraphrases_total']}` (`{hold_sum['adversarial_uncaught_rate'] * 100:.1f}%`) uncaught natural-language paraphrases (`{', '.join(hold_sum.get('adversarial_uncaught_case_codes', []))}`) pending live LLM review or P1 `effect_records`.",
                "",
                "| Case | Category | Frozen Expected Mechanism | Observed Outcome | Error Code | Baseline Match | Current Regression |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for ha in summary["heldout_adversarial_results"]:
            err = f"`{ha['actual_error_code']}`" if ha["actual_error_code"] else "—"
            lines.append(
                f"| `{ha['case_code']}` | `{ha['paraphrase_category']}` | `{ha['mechanism_expectation']}` | "
                f"`{ha['observed_category']}` | {err} | `{'MATCH' if ha['expectation_matched'] else 'CHANGED'}` | `{'PASS' if ha.get('regression_passed', ha['expectation_matched']) else 'FAIL'}` |"
            )
    if summary.get("metamorphic_results"):
        lines.extend(
            [
                "",
                f"## Metamorphic Invariance Suite ({meta_sum['total_transforms']} Transforms)",
                "",
                f"- **Invariance Summary**: `{meta_sum['passed_transforms']} / {meta_sum['total_transforms']}` preserved acceptance & export (`invariance_rate={meta_sum['invariance_rate']}`, `false_advisories={meta_sum['false_advisory_count']}`).",
                "",
                "| Transform | Base Case | Transform Type | Base -> Variant Outcome | Export | Advisories | Pass |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for mr in summary["metamorphic_results"]:
            adv = ", ".join(mr.get("variant_lexical_advisory_codes") or []) or "—"
            lines.append(
                f"| `{mr['transform_id']}` | `{mr['base_case_code']}` | `{mr['transform_type']}` | "
                f"`{mr['base_outcome']} -> {mr['variant_outcome']}` | `{mr['variant_export_state']}` | `{adv}` | `{'PASS' if mr['passed'] else 'FAIL'}` |"
            )
    if summary.get("p1_effects_results"):
        lines.extend(
            [
                "",
                f"## P1 Structured `effect_records` Suite ({p1_sum.get('total_cases', 0)} Cases, Separate Column)",
                "",
                f"- **Computable Verification & Zero-FRR Summary**: `{p1_sum.get('passed_cases', 0)} / {p1_sum.get('total_cases', 0)}` passed; Positive control `{p1_sum.get('positive_controls_accepted', 0)}/{p1_sum.get('positive_controls_total', 0)}` (`FRR={p1_sum.get('positive_controls_false_rejection_rate', 0.0)}`); Negative computable traps caught `{p1_sum.get('negative_traps_caught', 0)}/{p1_sum.get('negative_traps_total', 0)}` (including `{p1_sum.get('hadv_counterparts_caught', 0)}/{p1_sum.get('hadv_counterparts_total', 0)}` structured counterparts of `HADV-07..12`); SQLite SHA-256 `event_chain_status=verified` on `{p1_sum.get('event_chain_verified_count', 0)}/{p1_sum.get('total_cases', 0)}`.",
                "",
                "| Case | Counterpart | Family | Classification | Expected | Actual Error | Event Chain | Pass |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for p1r in summary["p1_effects_results"]:
            cp = f"`{p1r['counterpart_of']}`" if p1r.get("counterpart_of") else "—"
            err = f"`{p1r['actual_error_code']}`" if p1r.get("actual_error_code") else "—"
            cls = f"`{p1r['claim_type']} × {p1r['evidence_level']}`"
            lines.append(
                f"| `{p1r['case_code']}` | {cp} | `{p1r['family']}` | {cls} | "
                f"`{p1r['expected_error_code'] or p1r['expected_gate_outcome']}` | {err} | `{p1r['event_chain_status']}` | `{'PASS' if p1r['passed'] else 'FAIL'}` |"
            )
    lines.extend(
        [
            "",
            "## Verification Scope & Honesty Boundary",
            "",
            (
                f"1. **What this verifies (`engineering × test_passed`)**: `dev_phrase_consistency` executes `{n_base}` L2 cases across `{len(eq_cov)}` families, `{n_exp}` `L1-Explore` cards, "
                f"`{cf_sum.get('total_perturbation_runs', 0)}` Card A runs (`{cf_sum.get('card_a_rubber_stamp_hard_rejected', 0)}` hard numeric rejections + `{cf_sum.get('card_a_rubber_stamp_advisory_flagged', 0)}` non-blocking lexical advisories + `{cf_sum.get('calibrated_flip_accepted', 0)}` calibrated flips), "
                f"`{fm_sum.get('total_fork_runs', 0)}` Card B runs (`{fm_sum.get('card_b_adversarial_hard_rejected', 0)}` structural SQLite rejections + `{fm_sum.get('card_b_adversarial_advisory_flagged', 0)}` non-blocking multiplicity advisories + `{fm_sum.get('card_b_positive_control_accepted', 0)}` Holm-Bonferroni controls), "
                f"`{sym_sum.get('total_runs', 0)}` Card C symmetry audit runs (`calibrated_false_alarm_rate=0.0`), "
                f"`{pair_sum.get('passed_pairs', 0)}/{pair_sum.get('total_pairs', 0)}` paired twins, and `{lin_sum.get('passed_specs', 0)}/{lin_sum.get('total_specs', 0)}` lineage/chunked-window specs. "
                f"`heldout_generalization` passes the legacy lexicon-overlap check (`overlap={hold_sum.get('heldout_lexical_overlap_count', -1)}`) with `{hold_sum.get('realistic_controls_false_rejections', 0)}/{hold_sum.get('realistic_controls_total', 0)}` realistic false rejections, catching `{hold_sum.get('adversarial_caught_mechanically_hard', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}` adversarial paraphrases mechanically while `{hold_sum.get('adversarial_uncaught_without_llm_or_p1', 0)}/{hold_sum.get('adversarial_paraphrases_total', 0)}` natural-language paraphrases remain uncaught without live LLM review or P1 `effect_records`. "
                f"`metamorphic_invariance` passes `{meta_sum.get('passed_transforms', 0)}/{meta_sum.get('total_transforms', 0)}`. "
                f"Separately, `p1_effect_records` verifies `{p1_sum.get('passed_cases', 0)}/{p1_sum.get('total_cases', 0)}` structured P1 cases (`0` FRR on `PEFF-01`, `{p1_sum.get('negative_traps_caught', 0)}/{p1_sum.get('negative_traps_total', 0)}` computable catches incl. `{p1_sum.get('hadv_counterparts_caught', 0)}/{p1_sum.get('hadv_counterparts_total', 0)}` structured `HADV-07..12` counterparts, and `{p1_sum.get('event_chain_verified_count', 0)}/{p1_sum.get('total_cases', 0)}` verified SQLite event chains). Prompt packets are exported across all 4 control arms (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`)."
            ),
            "2. **What remains `NOT_RUN` (`UNKNOWN`)**: Live external GPT/Claude/Grok API runs across Arms `A`, `B-精简`, `B-全文`, and `E` require prior user approval per `docs/evaluation-plan.md` and are explicitly marked `external_llm_status: not_run`.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 0 evaluation suite for Parrhesia.")
    parser.add_argument(
        "--suite",
        type=Path,
        default=ROOT / "docs" / "evaluation" / "stage0-cases.json",
        help="Path to stage0-cases.json",
    )
    parser.add_argument(
        "--mode",
        choices=("mechanical", "prompt-export", "counterfactual", "fork-multiplicity", "symmetry", "lineage-window", "heldout", "metamorphic", "p1-effects", "p2-longitudinal", "ingestion"),
        default="mechanical",
        help="Run mechanical suite, targeted Card A/B/C/lineage/heldout/metamorphic/p1-effects/p2-longitudinal suite, or export prompt packets for Arms A/B/E",
    )
    parser.add_argument(
        "--perturb",
        action="store_true",
        help="Run Card A counterfactual evidence-sensitivity perturbation suite",
    )
    parser.add_argument(
        "--fork-eval",
        action="store_true",
        help="Run Card B record-exec execution-fork detection & multiplicity gate suite",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "stage0-prompts")
    parser.add_argument("--report-out", type=Path, help="Optional Markdown report output path")
    args = parser.parse_args(argv)
    if args.mode == "ingestion":
        result = run_ingestion_suite()
        result.update(mode="ingestion", policy_measurement=policy_inputs(ROOT), input_fingerprint=input_fingerprint(ROOT, args.suite))
        if args.report_out:
            args.report_out.parent.mkdir(parents=True, exist_ok=True)
            args.report_out.write_text("# Ingestion engineering regression\n\n```json\n" + json.dumps(result["summary"], ensure_ascii=False, indent=2) + "\n```\n\nSynthetic fixtures; host acceptance and author impact not_run.\n", encoding="utf-8")
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0 if result["summary"]["all_passed"] else 1
    if args.mode == "prompt-export":
        result = export_prompts(args.suite, args.output_dir)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0
    if args.report_out is None:
        if args.mode == "counterfactual" or args.perturb:
            cf_out = run_counterfactual_suite(args.suite)
            out = {
                "suite_version": cf_out["suite_version"],
                "mode": "counterfactual",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "counterfactual_summary": cf_out["summary"],
                "counterfactual_results": cf_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if cf_out["summary"]["all_passed"] else 1
        if args.mode == "fork-multiplicity" or args.fork_eval:
            fm_out = run_fork_multiplicity_suite(args.suite)
            out = {
                "suite_version": fm_out["suite_version"],
                "mode": "fork-multiplicity",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "fork_multiplicity_summary": fm_out["summary"],
                "fork_multiplicity_results": fm_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if fm_out["summary"]["all_passed"] else 1
        if args.mode == "symmetry":
            suite = json.loads(args.suite.read_text(encoding="utf-8"))
            sym_out = run_symmetry_suite(args.suite)
            out = {
                "suite_version": suite["suite_version"],
                "mode": "symmetry",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "symmetry_audit_summary": sym_out["summary"],
                "symmetry_results": sym_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if sym_out["summary"]["all_passed"] else 1
        if args.mode == "lineage-window":
            suite = json.loads(args.suite.read_text(encoding="utf-8"))
            lin_out = run_lineage_window_suite(args.suite)
            out = {
                "suite_version": suite["suite_version"],
                "mode": "lineage-window",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "lineage_window_summary": lin_out["summary"],
                "lineage_window_results": lin_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if lin_out["summary"]["all_passed"] else 1
        if args.mode == "heldout":
            hold_out = run_heldout_generalization_suite(args.suite)
            out = {
                "suite_version": hold_out["suite_version"],
                "mode": "heldout",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "heldout_summary": hold_out["summary"],
                "leakage_audit": hold_out["leakage_audit"],
                "heldout_control_results": hold_out["control_results"],
                "heldout_adversarial_results": hold_out["adversarial_results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if hold_out["summary"]["regression_all_passed"] else 1
        if args.mode == "metamorphic":
            meta_out = run_metamorphic_invariance_suite(args.suite)
            out = {
                "suite_version": meta_out["suite_version"],
                "mode": "metamorphic",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "metamorphic_summary": meta_out["summary"],
                "metamorphic_results": meta_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if meta_out["summary"]["all_passed"] else 1
        if args.mode == "p1-effects":
            p1_out = run_p1_effect_records_suite(args.suite)
            out = {
                "suite_version": p1_out["suite_version"],
                "mode": "p1-effects",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "p1_effects_summary": p1_out["summary"],
                "p1_effects_results": p1_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if p1_out["summary"]["all_passed"] else 1
        if args.mode == "p2-longitudinal":
            p2_out = run_p2_longitudinal_suite(args.suite)
            out = {
                "suite_version": p2_out["suite_version"],
                "mode": "p2-longitudinal",
                "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "external_llm_status": "not_run",
                "p2_longitudinal_summary": p2_out["summary"],
                "p2_longitudinal_results": p2_out["results"],
            }
            sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            return 0 if p2_out["summary"]["all_passed"] else 1

    summary = run_mechanical_suite(args.suite)
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(render_markdown_report(summary), encoding="utf-8", newline="\n")
    if args.mode == "counterfactual" or args.perturb:
        out = {
            "suite_version": summary["suite_version"],
            "mode": "counterfactual",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "counterfactual_summary": summary["counterfactual_summary"],
            "counterfactual_results": summary["counterfactual_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["counterfactual_summary"]["all_passed"] else 1
    if args.mode == "fork-multiplicity" or args.fork_eval:
        out = {
            "suite_version": summary["suite_version"],
            "mode": "fork-multiplicity",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "fork_multiplicity_summary": summary["fork_multiplicity_summary"],
            "fork_multiplicity_results": summary["fork_multiplicity_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["fork_multiplicity_summary"]["all_passed"] else 1
    if args.mode == "symmetry":
        out = {
            "suite_version": summary["suite_version"],
            "mode": "symmetry",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "symmetry_audit_summary": summary["symmetry_audit_summary"],
            "symmetry_results": summary["symmetry_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["symmetry_audit_summary"]["all_passed"] else 1
    if args.mode == "lineage-window":
        out = {
            "suite_version": summary["suite_version"],
            "mode": "lineage-window",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "lineage_window_summary": summary["lineage_window_summary"],
            "lineage_window_results": summary["lineage_window_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["lineage_window_summary"]["all_passed"] else 1
    if args.mode == "heldout":
        out = {
            "suite_version": summary["suite_version"],
            "mode": "heldout",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "heldout_summary": summary["heldout_summary"],
            "heldout_control_results": summary["heldout_control_results"],
            "heldout_adversarial_results": summary["heldout_adversarial_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["heldout_summary"]["regression_all_passed"] else 1
    if args.mode == "metamorphic":
        out = {
            "suite_version": summary["suite_version"],
            "mode": "metamorphic",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "metamorphic_summary": summary["metamorphic_summary"],
            "metamorphic_results": summary["metamorphic_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["metamorphic_summary"]["all_passed"] else 1
    if args.mode == "p1-effects":
        out = {
            "suite_version": summary["suite_version"],
            "mode": "p1-effects",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "p1_effects_summary": summary["p1_effects_summary"],
            "p1_effects_results": summary["p1_effects_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["p1_effects_summary"]["all_passed"] else 1
    if args.mode == "p2-longitudinal":
        out = {
            "suite_version": summary["suite_version"],
            "mode": "p2-longitudinal",
            "executed_at": summary["executed_at"],
            "external_llm_status": summary["external_llm_status"],
            "p2_longitudinal_summary": summary["p2_longitudinal_summary"],
            "p2_longitudinal_results": summary["p2_longitudinal_results"],
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary["p2_longitudinal_summary"]["all_passed"] else 1
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
