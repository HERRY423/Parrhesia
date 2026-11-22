"""Unit and integration tests for longitudinal claim graph, executable reversal triggers, and calibration."""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from parrhesia.calibration import (
    CALIBRATION_BINS,
    CALIBRATION_OUTCOMES,
    CALIBRATION_RESOLUTION_SOURCES,
    DEFAULT_CONFIDENCE_PROBABILITIES,
    DEFAULT_OUTCOME_SCORES,
    compute_calibration_report,
    validate_calibration_outcome,
    validate_forecast_probability,
)
from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS, scaffold_claim_template
from parrhesia.contracts import ACTIONS, CHECK_NAMES, ContractError
from parrhesia.core import Engine, _digest
from parrhesia.report import render_report
from parrhesia.triggers import (
    CASE_RELATIONS,
    CLAIM_LINEAGE_RELATIONS,
    TRIGGER_KINDS,
    build_claim_graph,
    evaluate_case_triggers,
    validate_prior_claim_links_shape,
    validate_reversal_triggers,
)


def _v2_claim(
    claim_id: str,
    ev_ids: list[str],
    *,
    text: str = "Treatment lowers primary hazard (HR 0.71, 95% CI 0.55 to 0.91, p=0.004).",
    claim_type: str = "association",
    evidence_level: str = "adjusted",
    scope: str = "Adult cohort over 12 months",
    effect: dict | None = None,
    effect_records: list[dict] | None = None,
    prior_claim_links: list[dict] | None = None,
    reversal_triggers: list[dict] | None = None,
    checks_override: dict | None = None,
) -> dict:
    checks = {
        name: {
            "status": "pass",
            "reason": "Checked and verified against published cohort methods and primary tables.",
        }
        for name in CHECK_NAMES
    }
    if checks_override:
        checks.update(checks_override)
    claim = {
        "id": claim_id,
        "text": text,
        "claim_type": claim_type,
        "evidence_level": evidence_level,
        "claim_basis": "empirical",
        "scope": scope,
        "evidence_ids": list(ev_ids),
        "effect": dict(effect) if effect is not None else {"estimate": "HR 0.71", "uncertainty": "95% CI 0.55-0.91, p=0.004"},
        "origin": "unknown",
        "contribution": "Primary effect synthesis",
        "alternatives": [
            {
                "explanation": "Residual confounding",
                "status": "not_excluded",
                "reason": "Observational adjustment evaluated against baseline covariates.",
            }
        ],
        "checks": checks,
        "design_packages": [
            {
                "family": "observational",
                "checks": {
                    key: {
                        "status": "pass",
                        "reason": "Verified observational cohort design criteria in registered source.",
                        "evidence_ids": [ev_ids[0]],
                    }
                    for key in DESIGN_FIELDS["observational"]
                },
            }
        ],
        "statistical_report": {
            key: {
                "status": "pass",
                "reason": "Verified statistical reporting criteria in registered source tables.",
                "evidence_ids": [ev_ids[0]],
            }
            for key in STAT_FIELDS
        },
        "provenance_cards": {key: [] for key in CARD_FIELDS},
    }
    if effect_records is not None:
        claim["effect_records"] = effect_records
    if prior_claim_links is not None:
        claim["prior_claim_links"] = prior_claim_links
    if reversal_triggers is not None:
        claim["reversal_triggers"] = reversal_triggers
    return claim


def _decision(
    claim: dict,
    ev_ids: list[str],
    *,
    verdict: str = "supported",
    revised_text: str | None = None,
    confidence: str = "medium",
    forecast_probability: float | None = None,
    condition: str | None = None,
    reversal_triggers: list[dict] | None = None,
) -> dict:
    dec = {
        "claim_id": claim["id"],
        "claim_type": claim["claim_type"],
        "evidence_level": claim["evidence_level"],
        "claim_basis": claim["claim_basis"],
        "scope": claim["scope"],
        "verdict": verdict,
        "revised_text": revised_text or claim["text"],
        "rationale": "Primary quantitative endpoint and design checks substantiate this judgment within stated boundaries.",
        "evidence_ids": list(ev_ids),
        "confidence": confidence,
        "confidence_reason": "Anchored to registered primary record.",
        "boundary": "Applies to studied population under stated adjustment model.",
        "reversal_condition": "Null or reversed primary hazard ratio upon independent replication.",
    }
    if condition is not None:
        dec["condition"] = condition
    if forecast_probability is not None:
        dec["forecast_probability"] = forecast_probability
    if reversal_triggers is not None:
        dec["reversal_triggers"] = reversal_triggers
    return dec


def _adjudicate_case(
    engine: Engine,
    root: Path,
    *,
    filename: str,
    file_text: str,
    quote: str,
    question: str,
    claims_fn,
    decisions_fn,
    stances_fn=None,
    prior_case_ids: list[str] | None = None,
    supersedes_case_id: str | None = None,
    case_relation: str | None = None,
    export_report: bool = False,
) -> tuple[str, list[str], dict]:
    (root / filename).write_text(file_text, encoding="utf-8")
    create_payload = {
        "question": question,
        "draft": "Draft claim analysis",
        "writer_context_id": "writer",
    }
    if prior_case_ids is not None:
        create_payload["prior_case_ids"] = prior_case_ids
    if supersedes_case_id is not None:
        create_payload["supersedes_case_id"] = supersedes_case_id
    if case_relation is not None:
        create_payload["case_relation"] = case_relation
    case = engine.dispatch("create_case", create_payload)
    cid = case["case_id"]
    ev_id = engine.dispatch(
        "register_evidence",
        {
            "case_id": cid,
            "path": filename,
            "provenance": "observed",
            "kind": "observation",
            "quote": quote,
            "location": "Table 1",
        },
    )["evidence_id"]
    claims = claims_fn(ev_id)
    engine.dispatch("set_ledger", {"case_id": cid, "claims": claims})
    frozen = engine.dispatch("freeze", {"case_id": cid})
    claim_ids = [c["id"] for c in claims]
    for role in ("overclaim", "underclaim"):
        pkt = engine.dispatch("review_packet", {"case_id": cid, "role": role})
        engine.dispatch(
            "submit_review",
            {
                "case_id": cid,
                "role": role,
                "packet_id": pkt["packet_id"],
                "input_digest": frozen["input_digest"],
                "reviewer": {"context_id": role, "model": "fixture"},
                "covered_claim_ids": claim_ids,
                "claim_stances": [
                    {
                        "claim_id": clm["id"],
                        "stance": stances_fn(clm) if stances_fn is not None else "supported",
                        "rationale": f"Anchored directly to {ev_id}.",
                        "evidence_ids": [ev_id],
                    }
                    for clm in claims
                ],
                "unread_evidence_ids": [],
                "findings": [],
            },
        )
    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": cid})
    decisions = decisions_fn(claims, ev_id)
    engine.dispatch(
        "submit_adjudication",
        {
            "case_id": cid,
            "adjudication_id": adj_pkt["adjudication_id"],
            "input_digest": adj_pkt["input_digest"],
            "adjudicator": {"context_id": "adj", "model": "fixture"},
            "unread_evidence_ids": [],
            "dispositions": [],
            "decisions": decisions,
        },
    )
    if export_report:
        engine.dispatch(
            "record_human_decision",
            {
                "case_id": cid,
                "decision": "accept",
                "responsible_human": "lead",
                "reason": "Reviewed and accepted.",
            },
        )
        engine.dispatch("export", {"case_id": cid})
    return cid, [ev_id], engine.dispatch("get_case", {"case_id": cid})


class LongitudinalCalibrationTests(unittest.TestCase):
    def test_exported_constants_and_scaffold_omits_optional_p2_keys_by_default(self):
        for act in ("claim_graph", "evaluate_triggers", "record_calibration_outcome", "calibration_report"):
            self.assertIn(act, ACTIONS)
        self.assertEqual(len(ACTIONS), 24)
        self.assertEqual(CASE_RELATIONS, ("follow_up", "replication", "reanalysis", "correction", "extension", "retraction"))
        self.assertEqual(CLAIM_LINEAGE_RELATIONS, ("replicates", "refines", "narrows", "extends", "supersedes", "reverses", "refutes"))
        self.assertEqual(TRIGGER_KINDS, ("effect_metric", "check_status", "evidence_status", "execution_outcome", "replication_verdict"))
        self.assertEqual(CALIBRATION_OUTCOMES, ("replicated", "partially_replicated", "refuted", "inconclusive"))
        self.assertEqual(CALIBRATION_RESOLUTION_SOURCES, ("follow_up_case", "external_evidence", "trigger_evaluation"))
        self.assertEqual(len(CALIBRATION_BINS), 5)

        base_skel = scaffold_claim_template({"claim_type": "association", "evidence_level": "adjusted"})
        self.assertNotIn("prior_claim_links", base_skel)
        self.assertNotIn("reversal_triggers", base_skel)

        p2_skel = scaffold_claim_template({
            "claim_type": "association",
            "evidence_level": "adjusted",
            "include_prior_claim_links": True,
            "include_reversal_triggers": True,
        })
        self.assertEqual(len(p2_skel["prior_claim_links"]), 1)
        self.assertEqual(p2_skel["prior_claim_links"][0]["relation"], "replicates")
        self.assertEqual(len(p2_skel["reversal_triggers"]), 1)
        self.assertEqual(p2_skel["reversal_triggers"][0]["id"], "C1-RT1")

    def test_case_and_claim_lineage_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            (root / "base.txt").write_text("Effect HR 0.71 (95% CI 0.55-0.91, p=0.004).\n", encoding="utf-8")

            # Missing prior_case_id or supersedes_case_id -> unknown_case
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("create_case", {
                    "question": "Follow up?", "draft": "Draft", "writer_context_id": "writer",
                    "prior_case_ids": ["nonexistent_case"], "case_relation": "follow_up",
                })
            self.assertEqual(cm.exception.code, "unknown_case")

            with self.assertRaises(ContractError) as cm:
                engine.dispatch("create_case", {
                    "question": "Supersede?", "draft": "Draft", "writer_context_id": "writer",
                    "supersedes_case_id": "nonexistent_case", "case_relation": "reanalysis",
                })
            self.assertEqual(cm.exception.code, "unknown_case")

            # Create valid prior case P1 with claim C1 and trigger T_NULL
            p1_id, _, p1_data = _adjudicate_case(
                engine, root,
                filename="p1.txt",
                file_text="Primary outcome HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n",
                quote="Primary outcome HR 0.71 (95% CI 0.55 to 0.91, p=0.004).",
                question="Does drug X lower primary hazard?",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        effect_records=[{
                            "id": "E1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                            "direction": "benefit", "evidence_id": ev,
                        }],
                        reversal_triggers=[{
                            "id": "T_NULL",
                            "description": "Primary HR CI crosses 1.0 in independent replication",
                            "kind": "effect_metric",
                            "metric": "HR",
                            "endpoint_role": "primary",
                            "field": "estimate",
                            "operator": "crosses_null",
                            "target_verdict": "unsupported",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], forecast_probability=0.82)],
            )
            # Legacy omitted keys absent, input_digest stable
            self.assertNotIn("prior_case_ids", p1_data)
            self.assertIsInstance(p1_data["input_digest"], str)

            # Create child case without prior_case_ids -> unlinked_prior_case
            (root / "c2.txt").write_text("Replication HR 1.02 (95% CI 0.80 to 1.29, p=0.85).\n", encoding="utf-8")
            c2_id = engine.dispatch("create_case", {
                "question": "Follow up check?", "draft": "Draft", "writer_context_id": "writer",
            })["case_id"]
            ev2 = engine.dispatch("register_evidence", {
                "case_id": c2_id, "path": "c2.txt", "provenance": "observed", "kind": "observation",
                "quote": "Replication HR 1.02 (95% CI 0.80 to 1.29, p=0.85).", "location": "Table 1",
            })["evidence_id"]

            with self.assertRaises(ContractError) as cm:
                engine.dispatch("set_ledger", {
                    "case_id": c2_id,
                    "claims": [_v2_claim("C1", [ev2], prior_claim_links=[{
                        "prior_case_id": p1_id, "prior_claim_id": "C1", "relation": "replicates",
                        "reason": "Direct replication attempt in independent cohort.",
                    }])],
                })
            self.assertEqual(cm.exception.code, "unlinked_prior_case")

            # Linked case with unknown_prior_claim and unknown_reversal_trigger
            c3_id = engine.dispatch("create_case", {
                "question": "Linked case?", "draft": "Draft", "writer_context_id": "writer",
                "prior_case_ids": [p1_id], "case_relation": "replication",
            })["case_id"]
            ev3 = engine.dispatch("register_evidence", {
                "case_id": c3_id, "path": "c2.txt", "provenance": "observed", "kind": "observation",
                "quote": "Replication HR 1.02 (95% CI 0.80 to 1.29, p=0.85).", "location": "Table 1",
            })["evidence_id"]

            with self.assertRaises(ContractError) as cm:
                engine.dispatch("set_ledger", {
                    "case_id": c3_id,
                    "claims": [_v2_claim("C1", [ev3], prior_claim_links=[{
                        "prior_case_id": p1_id, "prior_claim_id": "C_MISSING", "relation": "replicates",
                        "reason": "Points to missing prior claim ID.",
                    }])],
                })
            self.assertEqual(cm.exception.code, "unknown_prior_claim")

            with self.assertRaises(ContractError) as cm:
                engine.dispatch("set_ledger", {
                    "case_id": c3_id,
                    "claims": [_v2_claim("C1", [ev3], prior_claim_links=[{
                        "prior_case_id": p1_id, "prior_claim_id": "C1", "relation": "reverses",
                        "triggered_reversal_id": "T_NONEXISTENT",
                        "reason": "Points to nonexistent reversal trigger ID.",
                    }])],
                })
            self.assertEqual(cm.exception.code, "unknown_reversal_trigger")

    def test_lineage_transition_coherence_triggered_reversal_and_claim_graph_standing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)

            # Case 1: Original supported claim with T_NULL trigger
            p1_id, _, _ = _adjudicate_case(
                engine, root,
                filename="orig.txt",
                file_text="Original cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n",
                quote="Original cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).",
                question="Original association?",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Drug X reduces mortality HR 0.71 (95% CI 0.55-0.91).",
                        effect_records=[{
                            "id": "E1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                            "direction": "benefit", "evidence_id": ev,
                        }],
                        reversal_triggers=[{
                            "id": "T_NULL",
                            "description": "Replication primary HR reverses above 1.0 threshold",
                            "kind": "effect_metric",
                            "metric": "HR",
                            "endpoint_role": "primary",
                            "field": "estimate",
                            "operator": "gt",
                            "threshold": 1.0,
                            "target_verdict": "unsupported",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported", forecast_probability=0.80)],
            )

            # Case 2: Declares reverses with IDENTICAL proposition/scope/class and UNTRIGGERED link
            (root / "bad_rev.txt").write_text("Repeat cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n", encoding="utf-8")
            bad_id = engine.dispatch("create_case", {
                "question": "Contradictory reversal?", "draft": "Draft", "writer_context_id": "writer",
                "prior_case_ids": [p1_id], "case_relation": "reanalysis",
            })["case_id"]
            ev_bad = engine.dispatch("register_evidence", {
                "case_id": bad_id, "path": "bad_rev.txt", "provenance": "observed", "kind": "observation",
                "quote": "Repeat cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).", "location": "Table 1",
            })["evidence_id"]
            bad_claim = _v2_claim(
                "C1", [ev_bad],
                text="Drug X reduces mortality HR 0.71 (95% CI 0.55-0.91).",
                effect_records=[{
                    "id": "E1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                    "direction": "benefit", "evidence_id": ev_bad,
                }],
                prior_claim_links=[{
                    "prior_case_id": p1_id, "prior_claim_id": "C1", "relation": "reverses",
                    "triggered_reversal_id": "T_NULL",
                    "reason": "Claims reversal despite identical HR.",
                }],
            )
            engine.dispatch("set_ledger", {"case_id": bad_id, "claims": [bad_claim]})
            fr_bad = engine.dispatch("freeze", {"case_id": bad_id})
            for role in ("overclaim", "underclaim"):
                pkt = engine.dispatch("review_packet", {"case_id": bad_id, "role": role})
                engine.dispatch("submit_review", {
                    "case_id": bad_id, "role": role, "packet_id": pkt["packet_id"], "input_digest": fr_bad["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Identical HR", "evidence_ids": [ev_bad]}],
                    "unread_evidence_ids": [], "findings": [],
                })
            adj_bad = engine.dispatch("adjudication_packet", {"case_id": bad_id})
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("submit_adjudication", {
                    "case_id": bad_id, "adjudication_id": adj_bad["adjudication_id"], "input_digest": adj_bad["input_digest"],
                    "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                    "decisions": [_decision(bad_claim, [ev_bad], verdict="supported", revised_text="Drug X reduces mortality HR 0.71 (95% CI 0.55-0.91).")],
                })
            self.assertEqual(cm.exception.code, "contradictory_claim_lineage_transition")

            # Change wording to trigger untriggered_reversal_link when T_NULL does not fire
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("submit_adjudication", {
                    "case_id": bad_id, "adjudication_id": adj_bad["adjudication_id"], "input_digest": adj_bad["input_digest"],
                    "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                    "decisions": [_decision(bad_claim, [ev_bad], verdict="supported", revised_text="Revised wording but HR still excludes null.")],
                })
            self.assertEqual(cm.exception.code, "untriggered_reversal_link")

            # Case 3: Genuine harm reversal that triggers T_NULL (>1.0) and reverses P1:C1
            p2_id, _, _ = _adjudicate_case(
                engine, root,
                filename="null_rep.txt",
                file_text="Replication trial HR 1.35 (95% CI 1.12 to 1.63, p=0.002).\n",
                quote="Replication trial HR 1.35 (95% CI 1.12 to 1.63, p=0.002).",
                question="Does independent trial replicate drug X?",
                prior_case_ids=[p1_id],
                supersedes_case_id=p1_id,
                case_relation="replication",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Drug X reverses benefit with harm signal in replication (HR 1.35, 95% CI 1.12-1.63).",
                        effect={"estimate": "HR 1.35", "uncertainty": "95% CI 1.12 to 1.63, p=0.002"},
                        effect_records=[{
                            "id": "E1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 1.35, "ci_low": 1.12, "ci_high": 1.63, "p_value": 0.002,
                            "direction": "higher_better", "evidence_id": ev,
                        }],
                        prior_claim_links=[{
                            "prior_case_id": p1_id, "prior_claim_id": "C1", "relation": "reverses",
                            "triggered_reversal_id": "T_NULL",
                            "reason": "Independent replication HR 1.35 > 1.0, firing T_NULL.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [
                    _decision(claims[0], [ev], verdict="supported", forecast_probability=0.90)
                ],
            )

            # Verify frozen P1 was NEVER mutated and graph reflects reversed standing
            p1_after = engine.dispatch("get_case", {"case_id": p1_id})
            self.assertEqual(p1_after["adjudication"]["decisions"][0]["verdict"], "supported")
            graph = engine.get_claim_graph(case_id=p1_id)
            self.assertFalse(graph["cycle_detected"])
            nodes_by_id = {n["node_id"]: n for n in graph["claim_nodes"]}
            self.assertEqual(nodes_by_id[f"{p1_id}:C1"]["active_standing"], "reversed")
            self.assertEqual(nodes_by_id[f"{p2_id}:C1"]["active_standing"], "current")
            self.assertIn([f"{p1_id}:C1", f"{p2_id}:C1"], graph["chains"])

            # Check failed follow-up claim (unsupported) does NOT change standing of target
            p_fail_id, _, _ = _adjudicate_case(
                engine, root,
                filename="failed_rep.txt",
                file_text="Flawed attempt HR 0.99 (95% CI 0.70 to 1.40, p=0.95).\n",
                quote="Flawed attempt HR 0.99 (95% CI 0.70 to 1.40, p=0.95).",
                question="Inconclusive follow-up?",
                prior_case_ids=[p2_id],
                case_relation="reanalysis",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Flawed attempt HR 0.99 (95% CI 0.70 to 1.40, p=0.95).",
                        effect={"estimate": "HR 0.99", "uncertainty": "95% CI 0.70 to 1.40, p=0.95"},
                        prior_claim_links=[{
                            "prior_case_id": p2_id, "prior_claim_id": "C1", "relation": "refutes",
                            "reason": "Underpowered critique later rejected at adjudication.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="unsupported")],
            )
            graph2 = engine.get_claim_graph(case_id=p2_id)
            nodes2 = {n["node_id"]: n for n in graph2["claim_nodes"]}
            self.assertEqual(nodes2[f"{p2_id}:C1"]["active_standing"], "current")
            self.assertIn(p_fail_id, {c["case_id"] for c in graph2["case_nodes"]})

            # Synthetic cycle check in build_claim_graph
            cyc_a = {"case_id": "CA", "question": "Q", "domain": "scientific", "state": "draft", "claims": [{"id": "C1", "prior_claim_links": [{"prior_case_id": "CB", "prior_claim_id": "C1", "relation": "refines", "reason": "Cycle A->B"}]}]}
            cyc_b = {"case_id": "CB", "question": "Q", "domain": "scientific", "state": "draft", "claims": [{"id": "C1", "prior_claim_links": [{"prior_case_id": "CA", "prior_claim_id": "C1", "relation": "refines", "reason": "Cycle B->A"}]}]}
            cyc_graph = build_claim_graph([cyc_a, cyc_b])
            self.assertTrue(cyc_graph["cycle_detected"])

    def test_all_five_trigger_kinds_self_trigger_block_and_readonly_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)

            # 1. Self-triggering reversal condition must block adjudication (passing checks so ceiling passes cleanly)
            (root / "self_trig.txt").write_text("Primary cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n", encoding="utf-8")
            scid = engine.dispatch("create_case", {"question": "Self-trigger?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
            sev = engine.dispatch("register_evidence", {
                "case_id": scid, "path": "self_trig.txt", "provenance": "observed", "kind": "observation",
                "quote": "Primary cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).", "location": "Table 1",
            })["evidence_id"]
            self_claim = _v2_claim(
                "C1", [sev],
                effect_records=[{
                    "id": "E1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                    "direction": "benefit", "evidence_id": sev,
                }],
                reversal_triggers=[{
                    "id": "T_EFF_SELF",
                    "description": "Downgrade whenever primary HR is strictly below 0.80.",
                    "kind": "effect_metric",
                    "metric": "HR",
                    "endpoint_role": "primary",
                    "field": "estimate",
                    "operator": "lt",
                    "threshold": 0.80,
                    "target_verdict": "unsupported",
                }],
            )
            engine.dispatch("set_ledger", {"case_id": scid, "claims": [self_claim]})
            fr = engine.dispatch("freeze", {"case_id": scid})
            for role in ("overclaim", "underclaim"):
                pkt = engine.dispatch("review_packet", {"case_id": scid, "role": role})
                engine.dispatch("submit_review", {
                    "case_id": scid, "role": role, "packet_id": pkt["packet_id"], "input_digest": fr["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Test", "evidence_ids": [sev]}],
                    "unread_evidence_ids": [], "findings": [],
                })
            apkt = engine.dispatch("adjudication_packet", {"case_id": scid})
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("submit_adjudication", {
                    "case_id": scid, "adjudication_id": apkt["adjudication_id"], "input_digest": apkt["input_digest"],
                    "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                    "decisions": [_decision(self_claim, [sev], verdict="supported")],
                })
            self.assertEqual(cm.exception.code, "self_triggering_reversal_condition")

            # 2. Case with all 5 trigger kinds (does NOT self-fire)
            triggers_all = [
                {
                    "id": "TR_EFF", "description": "Primary HR crosses null", "kind": "effect_metric",
                    "metric": "HR", "endpoint_role": "primary", "field": "estimate", "operator": "crosses_null",
                    "target_verdict": "unsupported",
                },
                {
                    "id": "TR_CHK", "description": "Baseline check fail", "kind": "check_status",
                    "target_check": "baseline", "target_statuses": ["fail"], "target_verdict": "partially_supported",
                },
                {
                    "id": "TR_EVID", "description": "Evidence contradicts or blocked", "kind": "evidence_status",
                    "trigger_on": ["contradicts", "blocked"], "target_verdict": "unsupported",
                },
                {
                    "id": "TR_EXEC", "description": "Primary run exits non-zero", "kind": "execution_outcome",
                    "exit_operator": "non_zero", "fork_role": "primary", "target_verdict": "insufficient_evidence",
                },
                {
                    "id": "TR_REP", "description": "Downstream replication unsupported", "kind": "replication_verdict",
                    "target_verdicts": ["unsupported"], "relations": ["replicates"], "target_verdict": "unsupported",
                },
            ]
            mcid, [mev], mcase = _adjudicate_case(
                engine, root,
                filename="multi_trig.txt",
                file_text="Primary cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n",
                quote="Primary cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).",
                question="Multi-trigger claim?",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        effect_records=[{
                            "id": "E1", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                            "direction": "benefit", "evidence_id": ev,
                        }],
                        reversal_triggers=triggers_all,
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported", forecast_probability=0.80)],
            )
            orig_adj_digest = mcase["adjudication_digest"]
            with closing(sqlite3.connect(engine.database)) as db:
                events_before = db.execute("SELECT COUNT(*) FROM events WHERE case_id=?", (mcid,)).fetchone()[0]

            # 2a. Observations evaluation (fires multiple triggers, read-only)
            obs_eval = engine.evaluate_triggers(mcid, observations={
                "effect_records": [{
                    "id": "E_NEW", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 1.05, "ci_low": 0.88, "ci_high": 1.25, "p_value": 0.62,
                    "direction": "null", "evidence_id": mev,
                }],
                "checks": {"baseline": {"status": "fail", "reason": "Unmeasured confounding found"}},
                "evidence_verifications": {mev: {"status": "contradicts", "contradicts": True}},
                "exec_events": [{"exit_status": 2, "fork_role": "primary", "command": "python rep.py"}],
                "verdict": "unsupported",
                "relation": "replicates",
            })
            self.assertEqual(obs_eval["evaluation_mode"], "observations")
            self.assertEqual(obs_eval["fired_count"], 5)
            self.assertEqual(obs_eval["claim_evaluations"][0]["recommended_revision"]["verdict"], "unsupported")

            # Assert strictly read-only on DB events & digest
            with closing(sqlite3.connect(engine.database)) as db:
                events_after = db.execute("SELECT COUNT(*) FROM events WHERE case_id=?", (mcid,)).fetchone()[0]
            self.assertEqual(events_after, events_before)
            self.assertEqual(engine.dispatch("get_case", {"case_id": mcid})["adjudication_digest"], orig_adj_digest)

            # 2b. Against-case evaluation
            ag_id, _, _ = _adjudicate_case(
                engine, root,
                filename="against.txt",
                file_text="Follow-up HR 1.03 (95% CI 0.82 to 1.29, p=0.79).\n",
                quote="Follow-up HR 1.03 (95% CI 0.82 to 1.29, p=0.79).",
                question="Follow-up against check?",
                prior_case_ids=[mcid],
                case_relation="replication",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Follow-up HR 1.03 (95% CI 0.82 to 1.29, p=0.79).",
                        effect={"estimate": "HR 1.03", "uncertainty": "95% CI 0.82 to 1.29, p=0.79"},
                        effect_records=[{
                            "id": "E_AG", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 1.03, "ci_low": 0.82, "ci_high": 1.29, "p_value": 0.79,
                            "direction": "null", "evidence_id": ev,
                        }],
                        prior_claim_links=[{
                            "prior_case_id": mcid, "prior_claim_id": "C1", "relation": "replicates",
                            "reason": "Independent replication cohort failed to reproduce protective effect.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="unsupported")],
                stances_fn=lambda clm: "unsupported",
            )
            ag_eval = engine.evaluate_triggers(mcid, against_case_id=ag_id)
            self.assertEqual(ag_eval["evaluation_mode"], "against_case")
            by_tid = {t["id"]: t for t in ag_eval["claim_evaluations"][0]["triggers"]}
            self.assertTrue(by_tid["TR_EFF"]["fired"])
            self.assertTrue(by_tid["TR_REP"]["fired"])

            # 2c. Live workspace evaluation reads downstream case AND record_execution_event
            engine.record_execution_event(mcid, {"command": "pytest replication", "claim_id": "C1", "exit_status": 1, "fork_role": "primary"})
            live_eval = engine.evaluate_triggers(mcid)
            self.assertEqual(live_eval["evaluation_mode"], "live_workspace")
            live_by_tid = {t["id"]: t for t in live_eval["claim_evaluations"][0]["triggers"]}
            self.assertTrue(live_by_tid["TR_EXEC"]["fired"])
            self.assertTrue(live_by_tid["TR_REP"]["fired"])

    def test_calibration_recording_digest_invariance_and_report_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)

            # Pre-adjudication rejection
            pre_cid = engine.dispatch("create_case", {"question": "Draft?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("record_calibration_outcome", {
                    "case_id": pre_cid, "claim_id": "C1", "outcome": "replicated",
                    "resolution_source": "external_evidence", "reason": "Too early.",
                })
            self.assertEqual(cm.exception.code, "invalid_state")

            # Exported case C_EXP: forecast_probability=0.80, primary HR 0.71 (0.55..0.91), recorded as replicated with observed_estimate=0.74
            c_exp_id, _, c_exp_before = _adjudicate_case(
                engine, root,
                filename="c_exp.txt",
                file_text="Study A HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n",
                quote="Study A HR 0.71 (95% CI 0.55 to 0.91, p=0.004).",
                question="Study A efficacy?",
                export_report=True,
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        effect_records=[{
                            "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "ci_level": 0.95, "p_value": 0.004,
                            "direction": "benefit", "evidence_id": ev,
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], confidence="high", forecast_probability=0.80)],
            )

            # Reject bad calibration payloads
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("record_calibration_outcome", {
                    "case_id": c_exp_id, "claim_id": "C1", "outcome": "inconclusive",
                    "outcome_score": 0.5, "resolution_source": "external_evidence", "reason": "Invalid score with inconclusive.",
                })
            self.assertEqual(cm.exception.code, "invalid_calibration_outcome")

            with self.assertRaises(ContractError) as cm:
                engine.dispatch("record_calibration_outcome", {
                    "case_id": c_exp_id, "claim_id": "C1", "outcome": "replicated",
                    "resolution_source": "external_evidence",
                    "observed_estimate": 0.95, "observed_ci_low": 0.55, "observed_ci_high": 0.91,
                    "reason": "Interval does not contain estimate.",
                })
            self.assertEqual(cm.exception.code, "effect_interval_inconsistent")

            with self.assertRaises(ContractError) as cm:
                engine.dispatch("record_calibration_outcome", {
                    "case_id": c_exp_id, "claim_id": "C1", "outcome": "replicated",
                    "resolution_source": "follow_up_case", "reason": "Missing follow_up_case_id.",
                })
            self.assertEqual(cm.exception.code, "invalid_calibration_outcome")

            # Valid post-export calibration outcome must preserve input_digest, adjudication_digest, export, and verified event chain
            source_case = engine.dispatch("create_case", {"question": "Registered follow-up fixture", "draft": "External reference"})["case_id"]
            source_text = "Fixture registry OS HR 0.74 with 95% CI 0.60 to 0.90."
            (root / "calibration-source.txt").write_text(source_text, encoding="utf-8")
            source_id = engine.dispatch("register_evidence", {"case_id": source_case, "path": "calibration-source.txt", "provenance": "observed", "kind": "observation", "quote": source_text, "location": "fixture row"})["evidence_id"]
            cal_res = engine.dispatch("record_calibration_outcome", {
                "case_id": c_exp_id, "claim_id": "C1", "outcome": "replicated",
                "resolution_source": "external_evidence",
                "evidence_id": source_id, "effect_record_id": "E1",
                "metric": "HR", "observed_estimate": 0.74, "observed_ci_low": 0.60, "observed_ci_high": 0.90,
                "reason": "External registry confirmed OS benefit HR 0.74 (0.60-0.90) within original 95% CI.",
            })
            self.assertEqual(cal_res["calibration_outcome_count"], 1)
            c_exp_after = engine.dispatch("get_case", {"case_id": c_exp_id})
            self.assertEqual(c_exp_after["input_digest"], c_exp_before["input_digest"])
            self.assertEqual(c_exp_after["adjudication_digest"], c_exp_before["adjudication_digest"])
            self.assertEqual(c_exp_after["export"], c_exp_before["export"])
            self.assertEqual(c_exp_after["event_chain_status"], "verified")
            ver_after = engine.dispatch("verify", {"case_id": c_exp_id})
            self.assertEqual(ver_after["status"], "pass")
            self.assertEqual(ver_after["event_chain_status"], "verified")

            # HTML report renders forecast_probability and calibration_outcomes
            html_path = root / "p2_report.html"
            render_report({**c_exp_after, "verification": ver_after}, html_path)
            html_txt = html_path.read_text(encoding="utf-8")
            self.assertIn("预测概率：0.8", html_txt)
            self.assertIn("calibration_outcomes", html_txt)

            # Second case C_REF with fired trigger -> confirmed refuted
            c_ref_id, _, _ = _adjudicate_case(
                engine, root,
                filename="c_ref.txt",
                file_text="Study B HR 0.80 (95% CI 0.65 to 0.98, p=0.03).\n",
                quote="Study B HR 0.80 (95% CI 0.65 to 0.98, p=0.03).",
                question="Study B efficacy?",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Study B HR 0.80 (95% CI 0.65 to 0.98, p=0.03).",
                        effect={"estimate": "HR 0.80", "uncertainty": "95% CI 0.65 to 0.98, p=0.03"},
                        effect_records=[{
                            "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
                            "estimate": 0.80, "ci_low": 0.65, "ci_high": 0.98, "ci_level": 0.95, "p_value": 0.03,
                            "direction": "benefit", "evidence_id": ev,
                        }],
                        reversal_triggers=[{
                            "id": "T_REP_REF", "description": "Refuted by replication", "kind": "replication_verdict",
                            "target_verdicts": ["supported"], "relations": ["refutes"], "target_verdict": "unsupported",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], confidence="medium", forecast_probability=0.60)],
            )
            # Downstream case C_DOWN refutes C_REF without explicit calibration outcome on C_REF -> graph-inferred resolution!
            _adjudicate_case(
                engine, root,
                filename="c_down.txt",
                file_text="Follow-up B HR 1.15 (95% CI 0.95 to 1.39, p=0.15).\n",
                quote="Follow-up B HR 1.15 (95% CI 0.95 to 1.39, p=0.15).",
                question="Refutation of Study B?",
                prior_case_ids=[c_ref_id],
                case_relation="replication",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Study B does not lower mortality (HR 1.15, 95% CI 0.95-1.39).",
                        effect={"estimate": "HR 1.15", "uncertainty": "95% CI 0.95 to 1.39, p=0.15"},
                        prior_claim_links=[{
                            "prior_case_id": c_ref_id, "prior_claim_id": "C1", "relation": "refutes",
                            "triggered_reversal_id": "T_REP_REF",
                            "reason": "Independent trial refuted prior Study B conclusion via T_REP_REF.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported", forecast_probability=0.90)],
            )

            report = engine.get_calibration_report(domain="scientific")
            self.assertEqual(report["summary"]["total_adjudicated_claims"], 3)
            self.assertEqual(report["summary"]["explicit_resolved_count"], 1)
            self.assertEqual(report["summary"]["graph_inferred_resolved_count"], 1)
            self.assertEqual(report["summary"]["resolved_claim_count"], 2)
            self.assertEqual(report["summary"]["unresolved_claim_count"], 1)

            # Exact proper scores on the 2 resolved claims: (0.80 - 1.0)^2 = 0.04, (0.60 - 0.0)^2 = 0.36 -> mean 0.20
            self.assertAlmostEqual(report["proper_scores"]["explicit_brier_score"], 0.20, places=6)
            self.assertIsNone(report["proper_scores"]["combined_brier_score"])
            self.assertAlmostEqual(report["heuristic_scores"]["combined_brier_score"], 0.20, places=6)
            expected_log = (-math.log(0.80) - math.log(0.40)) / 2.0
            self.assertAlmostEqual(report["proper_scores"]["explicit_log_score"], expected_log, places=6)
            # ECE: |(0.8-1.0)|/2 + |(0.6-0.0)|/2 = (0.2 + 0.6)/2 = 0.40
            self.assertAlmostEqual(report["proper_scores"]["ece"], 0.40, places=6)
            self.assertAlmostEqual(report["proper_scores"]["mce"], 0.60, places=6)
            self.assertEqual(len(report["reliability_bins"]), 5)

            # Replication point containment is descriptive, never nominal truth coverage.
            ic = report["interval_calibration"]
            self.assertEqual(ic["evaluated_count"], 0)
            self.assertEqual(ic["covered_count"], 0)
            self.assertIsNone(ic["empirical_coverage_rate"])
            self.assertIsNone(ic["mean_absolute_z_drift"])
            self.assertEqual(ic["replication_count"], 1)
            self.assertEqual(ic["replication_point_containment_rate"], 1.0)

            # Decision & trigger calibration: C_REF had fired trigger -> confirmed refuted -> precision=1.0
            dc = report["decision_calibration"]
            self.assertAlmostEqual(dc["false_confirmation_rate"], 0.5, places=6)
            self.assertEqual(dc["trigger_calibration"]["claims_with_triggers_count"], 1)
            self.assertEqual(dc["trigger_calibration"]["fired_triggers_resolved_count"], 1)
            self.assertEqual(dc["trigger_calibration"]["fired_triggers_confirmed_reversal_count"], 1)
            self.assertAlmostEqual(dc["trigger_calibration"]["trigger_precision"], 1.0, places=6)

            # Filtered report by case_id returns only C_EXP
            filtered = engine.get_calibration_report(case_id=c_exp_id)
            self.assertEqual(filtered["summary"]["total_adjudicated_claims"], 1)
            self.assertAlmostEqual(filtered["proper_scores"]["explicit_brier_score"], 0.04, places=6)

    def test_forecast_probability_and_direct_helpers_validation(self):
        with self.assertRaises(ContractError) as cm:
            validate_forecast_probability(True)
        self.assertEqual(cm.exception.code, "invalid_type")
        with self.assertRaises(ContractError) as cm:
            validate_forecast_probability(1.2)
        self.assertEqual(cm.exception.code, "invalid_value")
        with self.assertRaises(ContractError) as cm:
            validate_forecast_probability(float("nan"))
        self.assertEqual(cm.exception.code, "invalid_value")
        self.assertEqual(validate_forecast_probability(0), 0.0)
        self.assertEqual(validate_forecast_probability(1), 1.0)

        empty_rep = compute_calibration_report([])
        self.assertEqual(empty_rep["summary"]["total_adjudicated_claims"], 0)
        self.assertIsNone(empty_rep["proper_scores"]["combined_brier_score"])
        self.assertEqual(len(empty_rep["reliability_bins"]), 5)

    def test_refutes_standing_distinguishes_effective_refutation_from_negative_verdicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            quote = "Primary trial showed HR 0.71 (95% CI 0.55 to 0.91, p=0.004)."
            p1_id, _, _ = _adjudicate_case(
                engine, root, filename="p1.txt", file_text=quote, quote=quote,
                question="Does intervention reduce primary risk?",
                claims_fn=lambda ev: [_v2_claim("C1", [ev])],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported")],
            )
            ref_quote = "Independent trial proved HR 1.02 (95% CI 0.95 to 1.09, p=0.61), refuting benefit."
            f_eff_id, _, _ = _adjudicate_case(
                engine, root, filename="f_eff.txt", file_text=ref_quote, quote=ref_quote,
                question="Independent counter-evidence trial",
                prior_case_ids=[p1_id], case_relation="replication",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Independent trial refuted prior benefit (HR 1.02, 95% CI 0.95-1.09, p=0.61).",
                        effect={"estimate": "HR 1.02", "uncertainty": "95% CI 0.95-1.09, p=0.61"},
                        prior_claim_links=[{
                            "prior_case_id": p1_id,
                            "prior_claim_id": "C1",
                            "relation": "refutes",
                            "reason": "Well-powered replication refuted the prior protective effect.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported")],
            )
            g1 = engine.get_claim_graph(case_id=p1_id)
            nodes1 = {n["node_id"]: n for n in g1["claim_nodes"]}
            edges1 = {e["to_node_id"]: e for e in g1["claim_edges"]}
            self.assertEqual(edges1[f"{f_eff_id}:C1"]["status"], "effective")
            self.assertEqual(nodes1[f"{p1_id}:C1"]["active_standing"], "refuted")

            p2_id, _, _ = _adjudicate_case(
                engine, root, filename="p2.txt", file_text=quote, quote=quote,
                question="Second primary claim",
                claims_fn=lambda ev: [_v2_claim("C1", [ev])],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported")],
            )
            fail_quote = "Underpowered follow-up HR 0.96 (95% CI 0.60 to 1.54, p=0.88)."
            f_neg_ref_id, _, _ = _adjudicate_case(
                engine, root, filename="f_neg_ref.txt", file_text=fail_quote, quote=fail_quote,
                question="Rejected refutation critique",
                prior_case_ids=[p2_id], case_relation="replication",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Follow-up refutes prior protective effect (HR 0.96, 95% CI 0.60-1.54, p=0.88).",
                        effect={"estimate": "HR 0.96", "uncertainty": "95% CI 0.60-1.54, p=0.88"},
                        prior_claim_links=[{
                            "prior_case_id": p2_id,
                            "prior_claim_id": "C1",
                            "relation": "refutes",
                            "reason": "Critique unsupported due to insufficient power.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="unsupported")],
            )
            f_neg_rep_id, _, _ = _adjudicate_case(
                engine, root, filename="f_neg_rep.txt", file_text=fail_quote, quote=fail_quote,
                question="Failed replication",
                prior_case_ids=[p2_id], case_relation="replication",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1", [ev],
                        text="Replication confirms prior protective effect (HR 0.96, 95% CI 0.60-1.54, p=0.88).",
                        effect={"estimate": "HR 0.96", "uncertainty": "95% CI 0.60-1.54, p=0.88"},
                        prior_claim_links=[{
                            "prior_case_id": p2_id,
                            "prior_claim_id": "C1",
                            "relation": "replicates",
                            "reason": "Direct replication failed to reproduce benefit.",
                        }],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="unsupported")],
            )
            g2 = engine.get_claim_graph(case_id=p2_id)
            nodes2 = {n["node_id"]: n for n in g2["claim_nodes"]}
            edges2 = {e["to_node_id"]: e for e in g2["claim_edges"]}
            self.assertEqual(edges2[f"{f_neg_ref_id}:C1"]["status"], "pending")
            self.assertEqual(edges2[f"{f_neg_rep_id}:C1"]["status"], "pending")
            self.assertEqual(nodes2[f"{p2_id}:C1"]["active_standing"], "current")


if __name__ == "__main__":
    unittest.main()
