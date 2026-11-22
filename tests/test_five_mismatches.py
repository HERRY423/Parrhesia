"""Regression and integration tests for the five core Parrhesia 0.4.0 architectural upgrades.

Covers:
  1. Symmetric pre-adjudication gate (anti-underclaim / anti-false-abstention / anti-hollow-neutrality
     + tightened vacuous reversal-condition checks + actionable_stance & evidence_dominance).
  2. Proactive full-lifecycle runtime (`explore` durable hypothesis tree + `analyze_design` methods).
  3. Unexposed 12-case realistic scientific benchmark & zero-LLM dry-run pilot harness.
  4. Thin-input `upsert_claim` + `ceiling_diff`, `validate(collect_all=True)`, `estimate_first` blind
     protocol, verifiable `isolation_receipt` / `isolation_grade`, CLI `isolate-packet`, and lean profiles.
  5. Pluggable optional PDF backend (`pdf_backend="auto"`) with strict stdlib default and transparency.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from parrhesia.backends import available_backends, extract_pdf_with_fallback
from parrhesia.cli import main as cli_main
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.gates import is_vacuous_reversal_condition
from parrhesia.isolation import packet_content_sha256
from parrhesia.mcp_schemas import tool_definitions
from parrhesia.server import Server


ROOT = Path(__file__).resolve().parents[1]


def _make_external_prediction_case(
    ws: Path,
    *,
    symmetry_mode: str | None = None,
    blind_mode: str | None = None,
) -> tuple[Engine, str, str]:
    """Create a fully passing external-validation prediction case with anchored AUROC 0.84."""
    eng = Engine(ws)
    ev_path = ws / "external_validation.txt"
    ev_text = (
        "Independent external validation cohort (N=120 patients, 1-year recurrence): "
        "AUROC = 0.84 (95% CI 0.77 to 0.90, calibration slope = 0.96, Brier = 0.14). "
        "Locked preprocessing and frozen model weights; zero train-test overlap."
    )
    ev_path.write_text(ev_text, encoding="utf-8")

    create_payload: dict = {
        "question": "Does the recurrence risk model generalize to an independent external cohort?",
        "draft": "External validation yielded AUROC 0.84 (95% CI 0.77-0.90) for 1-year recurrence.",
        "domain": "scientific",
        "writer_context_id": "writer-ctx",
    }
    if symmetry_mode is not None:
        create_payload["symmetry_mode"] = symmetry_mode
    if blind_mode is not None:
        create_payload["blind_mode"] = blind_mode
    case_id = eng.dispatch("create_case", create_payload)["case_id"]
    ev_id = eng.dispatch(
        "register_evidence",
        {
            "case_id": case_id,
            "path": "external_validation.txt",
            "label": "External validation summary",
            "kind": "prediction_external",
            "provenance": "observed",
            "quote": "AUROC = 0.84 (95% CI 0.77 to 0.90, calibration slope = 0.96, Brier = 0.14).",
            "location": "line 1",
        },
    )["evidence_id"]

    eng.dispatch(
        "upsert_claim",
        {
            "case_id": case_id,
            "claim_id": "C1",
            "text": "In the independent external cohort (N=120), the model predicts 1-year recurrence with AUROC 0.84 (95% CI 0.77 to 0.90).",
            "claim_type": "prediction",
            "evidence_level": "externally_validated",
            "claim_basis": "empirical",
            "scope": "Independent external hospital cohort (N=120) for 1-year recurrence risk stratification",
            "evidence_ids": [ev_id],
            "design_families": ["prediction"],
            "effect": {"estimate": "AUROC = 0.84", "uncertainty": "95% CI 0.77 to 0.90"},
            "contribution": "Establishes external discrimination for 1-year recurrence risk stratification.",
            "alternatives": [
                {
                    "explanation": "Data leakage or cohort overlap inflated AUROC",
                    "status": "excluded",
                    "reason": "Independent external hospital cohort with frozen weights and zero patient overlap.",
                }
            ],
            "effect_records": [
                {
                    "id": "e1",
                    "endpoint": "1-year recurrence discrimination",
                    "endpoint_role": "primary",
                    "metric": "AUROC",
                    "estimate": 0.84,
                    "ci_low": 0.77,
                    "ci_high": 0.90,
                    "n": 120,
                    "direction": "higher_better",
                    "claim_direction": "higher_better",
                    "beneficial_if": "above_null",
                    "null_value": 0.50,
                    "evidence_id": ev_id,
                }
            ],
            "checks_overrides": {
                "quality": {"status": "pass", "reason": "Complete 1-year follow-up with adjudicated recurrence outcomes."},
                "batch": {"status": "pass", "reason": "Single external site recorded with locked preprocessing."},
                "unit": {"status": "pass", "reason": "Patient-level independent units (N=120 unique patients)."},
                "assumptions": {"status": "pass", "reason": "Binomial outcome and calibration slope 0.96 checked."},
                "multiplicity": {"status": "pass", "reason": "Single prespecified primary external AUROC endpoint."},
                "leakage": {"status": "pass", "reason": "Frozen model weights applied to independent external cohort."},
                "baseline": {"status": "pass", "reason": "Exceeds chance AUROC 0.50 with lower CI bound 0.77."},
                "statistics.units_sample_size": {"status": "pass", "reason": "N=120 independent patients.", "evidence_ids": [ev_id]},
                "statistics.estimand_scale": {"status": "pass", "reason": "External 1-year AUROC discrimination.", "evidence_ids": [ev_id]},
                "statistics.estimate_uncertainty": {"status": "pass", "reason": "AUROC 0.84 (95% CI 0.77-0.90).", "evidence_ids": [ev_id]},
                "statistics.model_assumptions": {"status": "pass", "reason": "Calibration slope 0.96 and Brier 0.14.", "evidence_ids": [ev_id]},
                "statistics.missingness_exclusions": {"status": "pass", "reason": "Complete external cohort follow-up.", "evidence_ids": [ev_id]},
                "statistics.multiplicity_selection": {"status": "pass", "reason": "Single primary endpoint.", "evidence_ids": [ev_id]},
                "statistics.comparisons_baselines": {"status": "pass", "reason": "Lower CI 0.77 well above 0.50 baseline.", "evidence_ids": [ev_id]},
                "statistics.robustness_limits": {"status": "pass", "reason": "External site generalization verified; clinical net benefit not yet tested.", "evidence_ids": [ev_id]},
                "design.prediction.target_horizon": {"status": "pass", "reason": "1-year recurrence horizon fixed.", "evidence_ids": [ev_id]},
                "design.prediction.splits_leakage": {"status": "pass", "reason": "Zero train-test patient overlap.", "evidence_ids": [ev_id]},
                "design.prediction.calibration_discrimination": {"status": "pass", "reason": "AUROC 0.84 and slope 0.96 reported.", "evidence_ids": [ev_id]},
                "design.prediction.validation_shift": {"status": "pass", "reason": "Evaluated in independent external cohort.", "evidence_ids": [ev_id]},
                "design.prediction.utility": {"status": "not_applicable", "reason": "Clinical decision utility reserved for prospective trial, not claimed here.", "evidence_ids": []},
            },
        },
    )
    eng.dispatch("freeze", {"case_id": case_id})
    return eng, case_id, ev_id


def _submit_positive_reviews(eng: Engine, case_id: str, ev_id: str) -> dict:
    over = eng.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
    under = eng.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})
    stance = {
        "claim_id": "C1",
        "stance": "supported",
        "rationale": "External cohort (N=120) achieves AUROC 0.84 (95% CI 0.77-0.90) with all prediction checks passing.",
        "evidence_ids": [ev_id],
    }
    eng.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "overclaim",
            "packet_id": over["packet_id"],
            "input_digest": over["input_digest"],
            "reviewer": {"context_id": "over-ctx", "model": "test-model"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance)],
            "unread_evidence_ids": [],
            "findings": [],
        },
    )
    eng.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "underclaim",
            "packet_id": under["packet_id"],
            "input_digest": under["input_digest"],
            "reviewer": {"context_id": "under-ctx", "model": "test-model"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance)],
            "unread_evidence_ids": [],
            "findings": [],
        },
    )
    return eng.dispatch("adjudication_packet", {"case_id": case_id})


class FiveMismatchesTests(unittest.TestCase):
    def test_false_balance_does_not_block_scoped_prediction_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, cid, evidence_id = _make_external_prediction_case(Path(temp))
            packet = _submit_positive_reviews(engine, cid, evidence_id)
            claim = engine.dispatch("get_case", {"case_id": cid})["claims"][0]
            decision = {
                "claim_id": "C1", "verdict": "supported", "claim_type": "prediction",
                "evidence_level": "externally_validated", "claim_basis": "empirical", "scope": claim["scope"],
                "rationale": "Independent external validation measured AUROC and calibration with frozen model weights.",
                "evidence_ids": [evidence_id], "confidence": "high",
                "confidence_reason": "External cohort applied the locked model and excluded train-test overlap.",
                "boundary": "Clinical decision utility has not been prospectively evaluated.",
                "reversal_condition": "A second independent cohort yields AUROC < 0.70.",
            }
            payload = {
                "case_id": cid, "adjudication_id": packet["adjudication_id"], "input_digest": packet["input_digest"],
                "adjudicator": {"context_id": "wording-control", "model": "fixture"},
                "unread_evidence_ids": [], "dispositions": [],
            }
            english = "the model achieved AUROC 0.84 (95% CI 0.77 to 0.90) for 1-year recurrence in the external cohort."
            chinese = "模型在独立外部队列中对一年复发的 AUROC 为 0.84（95% CI 0.77 至 0.90）。"
            for statement in (
                f"On the one hand, {english} On the other hand, clinical net benefit has not been measured.",
                f"一方面，{chinese}另一方面，临床净获益尚难定论，尚未直接测量。",
            ):
                with self.subTest(statement=statement):
                    preview = engine.validate_action("submit_adjudication", {
                        **payload, "decisions": [{**decision, "revised_text": statement}],
                    })
                    self.assertTrue(preview["valid"])
                    self.assertEqual(preview["preview"]["symmetry_audit"]["symmetry_mode"], "enforced")
            for statement in (
                f"On the one hand, {english} On the other hand, performance at chance is just as well supported.",
                f"一方面，{chinese}另一方面，模型与随机猜测相同的假说也同样可能。",
            ):
                with self.subTest(statement=statement), self.assertRaisesRegex(ContractError, "false_balance_neutrality"):
                    engine.validate_action("submit_adjudication", {
                        **payload, "decisions": [{**decision, "revised_text": statement}],
                    })

    # ------------------------------------------------------------------
    # Fix 1: Symmetric Adjudication Gate & Anti-Hollow-Neutrality
    # ------------------------------------------------------------------
    def test_enforced_symmetry_blocks_overhedging_false_abstention_underclaim_false_balance_and_unilateral_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng, cid, ev_id = _make_external_prediction_case(ws)
            adj = _submit_positive_reviews(eng, cid, ev_id)

            base_payload = {
                "case_id": cid,
                "adjudication_id": adj["adjudication_id"],
                "input_digest": adj["input_digest"],
                "adjudicator": {"context_id": "adj-ctx", "model": "test-model"},
                "unread_evidence_ids": [],
                "dispositions": [],
            }

            # 1a. False abstention without abstention_justification -> BLOCKED
            with self.assertRaises(ContractError) as ctx_abs:
                eng.dispatch(
                    "submit_adjudication",
                    {
                        **base_payload,
                        "decisions": [
                            {
                                "claim_id": "C1",
                                "verdict": "insufficient_evidence",
                                "claim_type": "prediction",
                                "evidence_level": "externally_validated",
                                "claim_basis": "empirical",
                                "scope": "Independent external cohort (N=120)",
                                "revised_text": "Evidence for external 1-year recurrence discrimination (AUROC 0.84) is insufficient.",
                                "rationale": "Sample size N=120 is modest and lacks multi-center RCT verification.",
                                "evidence_ids": [ev_id],
                                "confidence": "low",
                                "confidence_reason": "Abstaining conservatively.",
                                "boundary": "External cohort only.",
                                "reversal_condition": "External cohort AUROC drops below 0.70 or calibration slope falls below 0.75.",
                            }
                        ],
                    },
                )
            self.assertEqual(ctx_abs.exception.code, "unjustified_abstention")

            # 1b. Boilerplate over-hedging -> BLOCKED (non-rebuttable)
            with self.assertRaises(ContractError) as ctx_hedge:
                eng.dispatch(
                    "submit_adjudication",
                    {
                        **base_payload,
                        "decisions": [
                            {
                                "claim_id": "C1",
                                "verdict": "insufficient_evidence",
                                "claim_type": "prediction",
                                "evidence_level": "externally_validated",
                                "claim_basis": "empirical",
                                "scope": "Independent external cohort (N=120)",
                                "revised_text": "External validation yielded AUROC 0.84 (95% CI 0.77-0.90), 无法得出确定结论，仅供参考。",
                                "rationale": "External cohort N=120 reported AUROC 0.84 but 仅供参考。",
                                "evidence_ids": [ev_id],
                                "confidence": "low",
                                "confidence_reason": "Conservative hedging.",
                                "boundary": "External cohort only.",
                                "reversal_condition": "External cohort AUROC drops below 0.70 in prospective validation.",
                            }
                        ],
                    },
                )
            self.assertIn(ctx_hedge.exception.code, ("unjustified_overhedging", "unjustified_abstention"))

            # 1c. Unsupported against strictly beneficial primary effect -> BLOCKED
            with self.assertRaises(ContractError) as ctx_under:
                eng.dispatch(
                    "submit_adjudication",
                    {
                        **base_payload,
                        "decisions": [
                            {
                                "claim_id": "C1",
                                "verdict": "unsupported",
                                "claim_type": "prediction",
                                "evidence_level": "externally_validated",
                                "claim_basis": "empirical",
                                "scope": "Independent external cohort (N=120)",
                                "revised_text": "The external validation prediction claim is not supported.",
                                "rationale": "Rejecting the claim despite external AUROC 0.84 (95% CI 0.77-0.90).",
                                "evidence_ids": [ev_id],
                                "confidence": "medium",
                                "confidence_reason": "Conservative rejection.",
                                "boundary": "External cohort only.",
                                "reversal_condition": "External cohort AUROC drops below 0.55.",
                            }
                        ],
                    },
                )
            self.assertEqual(ctx_under.exception.code, "unjustified_underclaim")

            # 1d. Unilateral downgrade when both reviewers voted supported -> BLOCKED
            with self.assertRaises(ContractError) as ctx_down:
                eng.dispatch(
                    "submit_adjudication",
                    {
                        **base_payload,
                        "decisions": [
                            {
                                "claim_id": "C1",
                                "verdict": "partially_supported",
                                "claim_type": "prediction",
                                "evidence_level": "internally_validated",
                                "claim_basis": "empirical",
                                "scope": "Independent external cohort (N=120)",
                                "revised_text": "Model shows AUROC 0.84 (95% CI 0.77 to 0.90) in external cohort.",
                                "rationale": "Downgraded from externally_validated to internally_validated out of caution.",
                                "evidence_ids": [ev_id],
                                "confidence": "medium",
                                "confidence_reason": "Unilateral caution.",
                                "boundary": "External cohort only.",
                                "condition": "Applies only within the observed single external hospital cohort.",
                                "reversal_condition": "External cohort AUROC drops below 0.70.",
                            }
                        ],
                    },
                )
            self.assertEqual(ctx_down.exception.code, "unjustified_downgrade")

            # 1e. False-balance neutrality -> BLOCKED
            with self.assertRaises(ContractError) as ctx_fb:
                eng.dispatch(
                    "submit_adjudication",
                    {
                        **base_payload,
                        "decisions": [
                            {
                                "claim_id": "C1",
                                "verdict": "supported",
                                "claim_type": "prediction",
                                "evidence_level": "externally_validated",
                                "claim_basis": "empirical",
                                "scope": "Independent external hospital cohort (N=120) for 1-year recurrence risk stratification",
                                "revised_text": (
                                    "On the one hand the model shows AUROC 0.84 (95% CI 0.77 to 0.90) in the external cohort; "
                                    "on the other hand both sides have merit regarding whether it generalizes."
                                ),
                                "rationale": "Both sides have merit despite anchored AUROC 0.84 (95% CI 0.77-0.90).",
                                "evidence_ids": [ev_id],
                                "confidence": "medium",
                                "confidence_reason": "Balanced framing.",
                                "boundary": "Clinical utility remains untested.",
                                "reversal_condition": "External cohort AUROC drops below 0.70.",
                            }
                        ],
                    },
                )
            self.assertEqual(ctx_fb.exception.code, "false_balance_neutrality")

            # 1f. Boilerplate abstention_justification -> REJECTED
            with self.assertRaises(ContractError) as ctx_bad_just:
                eng.dispatch(
                    "submit_adjudication",
                    {
                        **base_payload,
                        "decisions": [
                            {
                                "claim_id": "C1",
                                "verdict": "insufficient_evidence",
                                "claim_type": "prediction",
                                "evidence_level": "externally_validated",
                                "claim_basis": "empirical",
                                "scope": "Independent external cohort (N=120)",
                                "revised_text": "Insufficient evidence for 1-year recurrence discrimination.",
                                "rationale": "Abstaining until future studies arrive.",
                                "evidence_ids": [ev_id],
                                "confidence": "low",
                                "confidence_reason": "Uncertain.",
                                "boundary": "External cohort only.",
                                "reversal_condition": "External AUROC drops below 0.70.",
                                "abstention_justification": {
                                    "blocking_gaps": ["More studies are needed to confirm this finding"],
                                    "reason": "Sample size is modest.",
                                },
                            }
                        ],
                    },
                )
            self.assertEqual(ctx_bad_just.exception.code, "invalid_abstention_justification")

            # 1g. Properly calibrated supported verdict with actionable_stance + evidence_dominance -> PASSES & RENDERS
            res = eng.dispatch(
                "submit_adjudication",
                {
                    **base_payload,
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": "supported",
                            "claim_type": "prediction",
                            "evidence_level": "externally_validated",
                            "claim_basis": "empirical",
                            "scope": "Independent external hospital cohort (N=120) for 1-year recurrence risk stratification",
                            "revised_text": (
                                "In the independent external cohort (N=120), the model achieves AUROC 0.84 "
                                "(95% CI 0.77 to 0.90) for 1-year recurrence risk stratification; clinical net benefit requires prospective evaluation."
                            ),
                            "rationale": "All prediction checks pass on locked external cohort N=120 with AUROC 0.84 (95% CI 0.77-0.90).",
                            "evidence_ids": [ev_id],
                            "confidence": "high",
                            "confidence_reason": "Consistent external discrimination and calibration slope 0.96.",
                            "boundary": "Clinical decision utility (net benefit) has not yet been prospectively evaluated.",
                            "reversal_condition": "Prospective or second-site external validation yields AUROC < 0.70 or calibration slope outside [0.75, 1.25].",
                            "actionable_stance": "adopt_within_scope",
                            "evidence_dominance": {
                                "favored_explanation": "Genuine external predictive signal (AUROC 0.84, slope 0.96)",
                                "rival_explanation": "Train-test leakage inflating discrimination",
                                "asymmetry_status": "dominant",
                                "basis": "Independent external hospital cohort with frozen weights and zero patient overlap excludes leakage.",
                            },
                        }
                    ],
                },
            )
            self.assertEqual(res["state"], "adjudicated")
            self.assertEqual(res["symmetry_audit"]["symmetry_mode"], "enforced")
            self.assertEqual(res["symmetry_audit"]["flag_count"], 0)

            exp = eng.dispatch("export", {"case_id": cid})
            md = Path(exp["path"]).read_text(encoding="utf-8")
            self.assertIn("adopt_within_scope", md)
            self.assertIn("Genuine external predictive signal", md)

            html_out = ws / "reports" / "case.html"
            buf_rep = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_rep})()):
                rc = cli_main(["report", "--workspace", str(ws), "--case-id", cid, "--output", "reports/case.html"])
            self.assertEqual(rc, 0)
            html = html_out.read_text(encoding="utf-8")
            self.assertIn("adopt_within_scope", html)
            self.assertIn("Genuine external predictive signal", html)

    def test_enforced_symmetry_accepts_concrete_abstention_justification_and_advisory_mode_stays_nonblocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Concrete rebuttal unblocks legitimate abstention without forcing false positives
            ws1 = Path(tmp) / "rebuttal"
            ws1.mkdir()
            eng1, cid1, ev1 = _make_external_prediction_case(ws1)
            adj1 = _submit_positive_reviews(eng1, cid1, ev1)
            res = eng1.dispatch(
                "submit_adjudication",
                {
                    "case_id": cid1,
                    "adjudication_id": adj1["adjudication_id"],
                    "input_digest": adj1["input_digest"],
                    "adjudicator": {"context_id": "adj-rebut", "model": "test-model"},
                    "unread_evidence_ids": [],
                    "dispositions": [],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": "insufficient_evidence",
                            "claim_type": "prediction",
                            "evidence_level": "externally_validated",
                            "claim_basis": "empirical",
                            "scope": "Independent external hospital cohort (N=120)",
                            "revised_text": "External discrimination cannot yet be accepted due to unaudited assay drift across site scanners.",
                            "rationale": "Frozen text omits scanner-level drift diagnostics required for cross-site transfer.",
                            "evidence_ids": [ev1],
                            "confidence": "medium",
                            "confidence_reason": "Specific unmodeled scanner batch gap.",
                            "boundary": "Site-level assay stability unaudited.",
                            "reversal_condition": "Site-stratified calibration slope stays within [0.80, 1.20] and AUROC >= 0.78.",
                            "actionable_stance": "pause_pending_qc",
                            "abstention_justification": {
                                "blocking_gaps": ["scanner_batch_calibration_drift_unaudited_in_external_site"],
                                "reason": "Frozen summary omits scanner-stratified calibration diagnostics despite hardware difference between training and external sites.",
                            },
                        }
                    ],
                },
            )
            self.assertEqual(res["state"], "adjudicated")
            self.assertEqual(len(res["symmetry_audit"]["rebuttals_accepted"]), 1)

            # Advisory mode allows non-blocking audit without raising
            ws2 = Path(tmp) / "advisory"
            ws2.mkdir()
            eng2, cid2, ev2 = _make_external_prediction_case(ws2, symmetry_mode="advisory")
            adj2 = _submit_positive_reviews(eng2, cid2, ev2)
            res2 = eng2.dispatch(
                "submit_adjudication",
                {
                    "case_id": cid2,
                    "adjudication_id": adj2["adjudication_id"],
                    "input_digest": adj2["input_digest"],
                    "adjudicator": {"context_id": "adj-adv", "model": "test-model"},
                    "unread_evidence_ids": [],
                    "dispositions": [],
                    "decisions": [
                        {
                            "claim_id": "C1",
                            "verdict": "insufficient_evidence",
                            "claim_type": "prediction",
                            "evidence_level": "externally_validated",
                            "claim_basis": "empirical",
                            "scope": "Independent external hospital cohort (N=120)",
                            "revised_text": "External cohort evidence remains insufficient.",
                            "rationale": "Conservative abstention in advisory audit mode.",
                            "evidence_ids": [ev2],
                            "confidence": "low",
                            "confidence_reason": "Advisory test.",
                            "boundary": "External cohort only.",
                            "reversal_condition": "External cohort AUROC drops below 0.70.",
                        }
                    ],
                },
            )
            self.assertEqual(res2["state"], "adjudicated")
            self.assertEqual(res2["symmetry_audit"]["symmetry_mode"], "advisory")
            self.assertTrue(res2["symmetry_audit"]["non_blocking"])
            self.assertGreaterEqual(res2["symmetry_audit"]["flag_count"], 1)

    def test_vacuous_reversal_condition_rejects_bare_buzzwords_but_accepts_observable_metrics(self):
        self.assertTrue(is_vacuous_reversal_condition("需更多研究以排查潜在混杂偏倚"))
        self.assertTrue(is_vacuous_reversal_condition("More studies are needed to check potential bias and confounding"))
        self.assertTrue(is_vacuous_reversal_condition("未来有更多研究时，再重新评估"))
        self.assertFalse(is_vacuous_reversal_condition("若独立队列中 AUROC 跌破 0.70 或校准斜率偏离 1.0 超过 0.25 则改判"))
        self.assertFalse(is_vacuous_reversal_condition("Future multi-center trial yields HR 95% CI crossing 1.0 or p > 0.05"))

    def test_diagnostic_test_p_values_do_not_mask_primary_effects(self):
        from parrhesia.symmetry_audit import _scoped_primary_numeric_null

        rdd_ev = {"quote": "LATE = -6.1% (95% CI -10.2% to -2.0%), McCrary p = 0.61, bandwidth sensitivity stable."}
        meta_ev = {"quote": "Pooled OR = 0.76 (95% CI 0.64 to 0.90), I^2 = 58%, asymmetry sensitivity p = 0.24."}
        null_ev = {"quote": "Independent replication: HR = 0.96 (95% CI 0.60 to 1.54, p = 0.88)."}
        self.assertFalse(_scoped_primary_numeric_null(rdd_ev, "RDD LATE reduces complications by 6.1%"))
        self.assertFalse(_scoped_primary_numeric_null(meta_ev, "Pooled OR 0.76 reduces complications"))
        self.assertTrue(_scoped_primary_numeric_null(null_ev, "Treatment reduces relapse hazard"))

    # ------------------------------------------------------------------
    # Fix 2: Proactive L1-Explore Runtime & Computable Design Co-Pilot
    # ------------------------------------------------------------------
    def test_explore_lifecycle_forking_paths_kill_lock_and_promote_to_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = Engine(tmp)
            init_res = eng.dispatch(
                "explore",
                {
                    "op": "init",
                    "question": "Does protein X phosphorylation drive drug resistance via pathway Y?",
                    "domain": "scientific",
                },
            )
            exp_id = init_res["exploration"]["explore_id"]

            eng.dispatch(
                "explore",
                {
                    "op": "upsert_hypothesis",
                    "explore_id": exp_id,
                    "hypothesis": {
                        "hypothesis_id": "H1",
                        "statement": "Phosphorylation of X activates pathway Y and causes drug resistance.",
                        "claim_type": "mechanism",
                        "evidence_level": "compatible",
                        "strongest_rival": "Cell-cycle proliferation batch artifact drives co-expression of X and Y.",
                        "discriminating_experiment": "CRISPR point mutation X-S42A vs wild-type across 6 independent donor organoids.",
                        "cost": "6 donor organoid lines, 3 weeks wet-lab, ~$2,400.",
                        "stopping_rule": "Stop after 6 donor organoids reach 80% power for MDE = 0.5 logFC.",
                        "kill_condition": "X-S42A mutation fails to reduce IC50 by >= 20% or pathway Y phosphorylation drops < 10%.",
                        "kill_threshold": {"metric": "ic50_reduction_pct", "operator": "lt", "threshold": 20.0},
                    },
                },
            )
            eng.dispatch(
                "explore",
                {
                    "op": "upsert_hypothesis",
                    "explore_id": exp_id,
                    "hypothesis": {
                        "hypothesis_id": "H2",
                        "statement": "Resistance is mediated by efflux transporter MDR1 independently of X.",
                        "claim_type": "mechanism",
                        "evidence_level": "compatible",
                        "strongest_rival": "Direct X->Y signaling drives resistance without efflux.",
                        "discriminating_experiment": "Pharmacologic MDR1 inhibition (tariquidar) in resistant clones across 4 donors.",
                        "cost": "4 donor lines, 1 week, ~$600.",
                        "stopping_rule": "Stop after 4 donor replicates complete viability assays.",
                        "kill_condition": "Tariquidar treatment changes IC50 by < 15% across all 4 donors.",
                        "kill_threshold": {"metric": "ic50_reduction_pct", "operator": "lt", "threshold": 15.0},
                    },
                },
            )

            # Log exploratory runs; H2 trips kill_threshold (< 15%)
            run1 = eng.dispatch(
                "explore",
                {
                    "op": "log_run",
                    "explore_id": exp_id,
                    "hypothesis_id": "H1",
                    "summary": "Pilot donor screen tested 3 dosing thresholds; S42A lowered IC50 by 34%.",
                    "outcome_status": "completed",
                    "fork_count_delta": 3,
                    "observed_metrics": {"ic50_reduction_pct": 34.0},
                },
            )
            self.assertFalse(run1["kill_triggered"])
            self.assertEqual(run1["summary"]["exploratory_forks"], 3)
            self.assertTrue(run1["summary"]["multiplicity_warning"])
            self.assertAlmostEqual(run1["summary"]["bonferroni_adjusted_alpha"], 0.05 / 3, places=5)

            run2 = eng.dispatch(
                "explore",
                {
                    "op": "log_run",
                    "explore_id": exp_id,
                    "hypothesis_id": "H2",
                    "summary": "Tariquidar MDR1 inhibition changed IC50 by only 4.2% across 4 donors.",
                    "outcome_status": "completed",
                    "fork_count_delta": 1,
                    "observed_metrics": {"ic50_reduction_pct": 4.2},
                },
            )
            self.assertTrue(run2["kill_triggered"])
            self.assertEqual(run2["summary"]["exploratory_forks"], 4)

            # Kill H2 explicitly; verify silent resurrection is blocked
            eng.dispatch(
                "explore",
                {
                    "op": "kill_hypothesis",
                    "explore_id": exp_id,
                    "hypothesis_id": "H2",
                    "reason": "MDR1 inhibition produced only 4.2% IC50 shift (< 15% kill threshold).",
                    "run_ids": [run2["run"]["run_id"]],
                },
            )
            with self.assertRaises(ContractError) as ctx_resurrect:
                eng.dispatch(
                    "explore",
                    {
                        "op": "upsert_hypothesis",
                        "explore_id": exp_id,
                        "hypothesis": {
                            "hypothesis_id": "H2",
                            "statement": "Resurrected MDR1 hypothesis.",
                            "claim_type": "mechanism",
                            "evidence_level": "compatible",
                            "strongest_rival": "Direct X->Y signaling.",
                            "discriminating_experiment": "Repeat viability assay.",
                            "cost": "1 week.",
                            "stopping_rule": "Stop at N=4.",
                            "kill_condition": "IC50 reduction < 15%.",
                            "status": "active",
                        },
                    },
                )
            self.assertEqual(ctx_resurrect.exception.code, "invalid_state")

            # Lock confirmatory plan for H1
            lock_res = eng.dispatch(
                "explore",
                {
                    "op": "lock_plan",
                    "explore_id": exp_id,
                    "hypothesis_id": "H1",
                    "estimand": "Mean difference in log-IC50 between X-S42A and WT organoids at 72h.",
                    "primary_endpoint": "72h log-IC50 fold reduction across 6 independent donor organoids.",
                    "analysis_unit": "Independent biological donor organoid line (N=6 donors).",
                    "sample_size_plan": "N=6 paired donor lines gives 80% power for >= 25% IC50 reduction at alpha=0.05.",
                    "exclusion_rules": "Exclude organoid passages failing mycoplasma QC prior to unblinding.",
                    "multiplicity_strategy": "Single prespecified primary endpoint; 4 prior exploratory forks disclosed.",
                    "negative_controls": "Non-targeting sgRNA and kinase-dead sham rescue vector.",
                    "kill_criteria": "Confirmatory paired log-IC50 reduction 95% CI crosses 0 or point reduction < 20%.",
                },
            )
            plan_id = lock_res["plan"]["plan_id"]
            self.assertEqual(len(lock_res["plan"]["plan_digest"]), 64)
            self.assertEqual(lock_res["plan"]["prior_exploratory_forks"], 4)

            promotion = {"op": "promote_to_case", "explore_id": exp_id, "hypothesis_id": "H1", "plan_id": plan_id}
            plan_file = Path(tmp) / "artifacts" / "explore-plans" / f"{plan_id}.json"
            before = eng.dispatch("explore", {"op": "get", "explore_id": exp_id})
            self.assertTrue(eng.validate_action("explore", promotion)["valid"])
            self.assertFalse(plan_file.parent.exists())
            self.assertEqual(eng.dispatch("explore", {"op": "get", "explore_id": exp_id}), before)
            promoted = eng.dispatch("explore", promotion)
            self.assertEqual(json.loads(plan_file.read_text(encoding="utf-8")), lock_res["plan"])
            case_doc = eng.dispatch("get_case", {"case_id": promoted["case_id"]})
            self.assertEqual(case_doc["state"], "draft")
            self.assertEqual(len(case_doc["evidence"]), 1)
            self.assertEqual(len(case_doc["hypotheses"]), 1)
            self.assertEqual(case_doc["hypotheses"][0]["timing_basis"], "reported_prespecified")
            self.assertEqual(len(case_doc["claims"]), 1)
            self.assertGreaterEqual(len(case_doc["claims"][0]["alternatives"]), 1)
            plan_file.write_text(plan_file.read_text(encoding="utf-8").replace("Single prespecified", "Different"), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "source_changed"):
                eng.validate_action("explore", promotion)

            listed = eng.dispatch("explore", {"op": "list"})
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["explorations"][0]["confirmatory_plans_locked"], 1)

    def test_analyze_design_all_five_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = Engine(tmp)

            # 1. power_mde
            pwr = eng.dispatch(
                "analyze_design",
                {"mode": "power_mde", "design": "two_sample_mean", "effect_size": 0.5, "sd": 1.0, "target_power": 0.80},
            )
            self.assertGreaterEqual(pwr["required_n_group1"], 60)
            self.assertLessEqual(pwr["required_n_group1"], 66)

            schoenfeld = eng.dispatch(
                "analyze_design",
                {"mode": "power_mde", "design": "log_hr_events", "hazard_ratio": 0.75, "target_power": 0.80},
            )
            self.assertGreaterEqual(schoenfeld["required_total_events"], 370)
            self.assertLessEqual(schoenfeld["required_total_events"], 390)

            # 2. tost_equivalence: equivalent vs underpowered_inconclusive
            eq = eng.dispatch(
                "analyze_design",
                {"mode": "tost_equivalence", "estimate": 0.01, "se": 0.02, "equiv_low": -0.10, "equiv_high": 0.10},
            )
            self.assertEqual(eq["classification"], "equivalent_supported")
            self.assertTrue(eq["equivalent"])

            underpowered = eng.dispatch(
                "analyze_design",
                {"mode": "tost_equivalence", "estimate": 0.02, "ci_low": -0.18, "ci_high": 0.22, "equiv_low": -0.10, "equiv_high": 0.10},
            )
            self.assertEqual(underpowered["classification"], "underpowered_inconclusive")
            self.assertFalse(underpowered["equivalent"])
            self.assertFalse(underpowered["different_from_null"])

            # 3. e_value (VanderWeele & Ding 2017: RR=2.0 -> 2 + sqrt(2) ~= 3.4142)
            ev_strong = eng.dispatch(
                "analyze_design",
                {"mode": "e_value", "metric": "RR", "estimate": 2.0, "ci_low": 1.4, "ci_high": 2.86},
            )
            self.assertAlmostEqual(ev_strong["e_value_point"], 3.4142, places=3)
            self.assertEqual(ev_strong["robustness_band"], "robust_against_moderate_confounding")

            ev_fragile = eng.dispatch(
                "analyze_design",
                {"mode": "e_value", "metric": "HR", "estimate": 1.12, "ci_low": 1.01, "ci_high": 1.24},
            )
            self.assertEqual(ev_fragile["robustness_band"], "fragile_to_weak_confounding")

            # 4. pseudoreplication_audit
            pseudo = eng.dispatch(
                "analyze_design",
                {
                    "mode": "pseudoreplication_audit",
                    "experimental_unit": "donor",
                    "observation_unit": "cell",
                    "n_clusters": 4,
                    "n_observations": 18000,
                    "icc": 0.10,
                    "clustered_inference": False,
                },
            )
            self.assertEqual(pseudo["pseudoreplication_risk"], "high")
            self.assertEqual(pseudo["recommended_unit_check_status"], "fail")
            self.assertGreater(pseudo["design_effect"], 400.0)
            self.assertGreater(pseudo["naive_se_underestimation_factor"], 20.0)

            # 5. evidence_dominance
            dom = eng.dispatch(
                "analyze_design",
                {
                    "mode": "evidence_dominance",
                    "hypotheses": [
                        {
                            "id": "H_rct",
                            "statement": "Drug reduces 1-year relapse in randomized multicenter trial",
                            "design_tier": "randomized",
                            "independent_units": 320,
                            "fatal_flaws": 0,
                            "direct_test_passed": True,
                        },
                        {
                            "id": "H_obs_null",
                            "statement": "Unadjusted retrospective case series showed no trend",
                            "design_tier": "observational_unadjusted",
                            "independent_units": 12,
                            "fatal_flaws": 2,
                            "direct_test_passed": False,
                        },
                    ],
                },
            )
            self.assertEqual(dom["asymmetry_status"], "dominant")
            self.assertEqual(dom["favored_hypothesis_id"], "H_rct")

    # ------------------------------------------------------------------
    # Fix 3: Realistic 12-Case Benchmark & Zero-LLM Dry-Run Pilot Harness
    # ------------------------------------------------------------------
    def test_realistic_pilot_benchmark_dry_run_and_prepare_summarize(self):
        script = ROOT / "scripts" / "prepare-impact-pilot.py"
        bench = ROOT / "docs" / "evaluation" / "realistic-science-pilot-v1.json"

        # 3a. Zero-LLM deterministic dry-run across all 12 unexposed realistic cases
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), "dry-run", "--benchmark", str(bench)],
            capture_output=True,
            text=True,
            check=True,
        )
        dry_report = json.loads(proc.stdout)
        self.assertEqual(dry_report["total_cases"], 12)
        self.assertEqual(dry_report["passed_cases"], 12)
        self.assertTrue(dry_report["all_passed"])
        self.assertEqual(dry_report["external_llm_status"], "not_run")

        # 3b. Prepare + summarize with behavioral_flags
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "pilot"
            subprocess.run(
                [sys.executable, "-X", "utf8", str(script), "prepare", "--output", str(out_dir), "--benchmark", str(bench)],
                capture_output=True,
                text=True,
                check=True,
            )
            proto = json.loads((out_dir / "protocol.json").read_text(encoding="utf-8"))
            assignments = [
                json.loads(line)
                for line in (out_dir / "assignments.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(assignments), 48)  # 12 cases x 4 arms
            obs_rows = []
            for row in assignments:
                arm_e = row["arm"] == "E_prefill"
                obs_rows.append(
                    {
                        "plan_digest": proto["plan_digest"],
                        "run_id": row["run_id"],
                        "status": "completed",
                        "material_sha256": row["material_sha256"],
                        "quality_pass": True if arm_e else False,
                        "scorer_blinded": True,
                        "isolated_context": True,
                        "overclaim_error": False if arm_e else True,
                        "underclaim_error": False,
                        "false_abstention": False if arm_e else True,
                        "hollow_neutrality": False,
                    }
                )
            obs_path = out_dir / "observations.jsonl"
            obs_path.write_text("\n".join(json.dumps(r) for r in obs_rows) + "\n", encoding="utf-8")
            sum_proc = subprocess.run(
                [sys.executable, "-X", "utf8", str(script), "summarize", "--plan", str(out_dir), "--observations", str(obs_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            summary = json.loads(sum_proc.stdout)
            self.assertAlmostEqual(summary["arms"]["B_compact"]["behavioral_rates"]["overclaim_error"], 1.0)
            self.assertAlmostEqual(summary["arms"]["E_prefill"]["behavioral_rates"]["overclaim_error"], 0.0)
            self.assertAlmostEqual(summary["arms"]["B_compact"]["behavioral_rates"]["false_abstention"], 1.0)
            self.assertAlmostEqual(summary["arms"]["E_prefill"]["behavioral_rates"]["false_abstention"], 0.0)

    # ------------------------------------------------------------------
    # Fix 4: Compact upsert_claim, Batch Validate, Estimate-First & Isolation Grades
    # ------------------------------------------------------------------
    def test_upsert_claim_incremental_ceiling_diff_and_batch_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            (ws / "obs.txt").write_text("Cohort N=200 observed HR 0.80 (95% CI 0.68 to 0.94, p=0.007).\n", encoding="utf-8")
            cid = eng.dispatch("create_case", {"question": "Does biomarker B associate with survival?", "draft": "Draft."})["case_id"]
            ev = eng.dispatch(
                "register_evidence",
                {
                    "case_id": cid,
                    "path": "obs.txt",
                    "kind": "observation",
                    "provenance": "observed",
                    "quote": "Cohort N=200 observed HR 0.80 (95% CI 0.68 to 0.94, p=0.007).",
                    "location": "line 1",
                },
            )["evidence_id"]

            # Upsert C1 with minimal inputs -> unsupplied checks stay 'unknown', ceiling_diff lists blockers
            u1 = eng.dispatch(
                "upsert_claim",
                {
                    "case_id": cid,
                    "claim_id": "C1",
                    "text": "Biomarker B associates with survival (HR 0.80, 95% CI 0.68 to 0.94).",
                    "claim_type": "association",
                    "evidence_level": "unadjusted",
                    "scope": "Retrospective cohort N=200",
                    "evidence_ids": [ev],
                    "design_families": ["observational"],
                    "alternatives": ["Unmeasured stage confounding"],
                },
            )
            self.assertFalse(u1["replaced"])
            self.assertEqual(u1["claim_count"], 1)
            self.assertEqual(u1["claim"]["checks"]["quality"]["status"], "unknown")
            self.assertFalse(u1["ceiling_diff"]["can_reach_target"])
            self.assertGreater(u1["ceiling_diff"]["blocker_count"], 0)

            # Upsert C2 -> preserves C1
            u2 = eng.dispatch(
                "upsert_claim",
                {
                    "case_id": cid,
                    "claim_id": "C2",
                    "text": "Cohort recorded N=200 patients.",
                    "claim_type": "description",
                    "evidence_level": "recorded",
                    "scope": "Retrospective cohort N=200",
                    "evidence_ids": [ev],
                    "design_families": ["observational"],
                    "alternatives": ["Data entry error"],
                },
            )
            self.assertEqual(u2["claim_count"], 2)
            self.assertTrue(u2["ceiling_diff"]["can_reach_target"])

            # Replace C1 with overrides that clear unadjusted ceiling -> C2 still preserved
            u1_upd = eng.dispatch(
                "upsert_claim",
                {
                    "case_id": cid,
                    "claim_id": "C1",
                    "text": "Biomarker B associates with survival (HR 0.80, 95% CI 0.68 to 0.94).",
                    "claim_type": "association",
                    "evidence_level": "unadjusted",
                    "scope": "Retrospective cohort N=200",
                    "evidence_ids": [ev],
                    "design_families": ["observational"],
                    "alternatives": ["Unmeasured stage confounding"],
                    "checks_overrides": {
                        "quality": {"status": "pass", "reason": "Complete registry ascertainment verified."},
                        "unit": {"status": "pass", "reason": "Patient-level independent survival units (N=200)."},
                        "assumptions": {"status": "pass", "reason": "Proportional hazards test non-significant."},
                        "design.observational.sampling_temporality": {"status": "pass", "reason": "Baseline biomarker precedes survival.", "evidence_ids": [ev]},
                        "design.observational.measurement": {"status": "pass", "reason": "Validated assay used.", "evidence_ids": [ev]},
                        "design.observational.confounding_selection": {"status": "not_applicable", "reason": "Unadjusted descriptive association only; confounding adjustment not claimed.", "evidence_ids": []},
                        "design.observational.missingness": {"status": "pass", "reason": "Zero missing survival status across N=200.", "evidence_ids": [ev]},
                        "design.observational.robustness": {"status": "not_applicable", "reason": "Unadjusted tier; sensitivity analysis not claimed.", "evidence_ids": []},
                        "statistics.units_sample_size": {"status": "pass", "reason": "N=200 patients.", "evidence_ids": [ev]},
                        "statistics.estimand_scale": {"status": "pass", "reason": "Unadjusted survival hazard ratio.", "evidence_ids": [ev]},
                        "statistics.estimate_uncertainty": {"status": "pass", "reason": "HR 0.80 (95% CI 0.68-0.94).", "evidence_ids": [ev]},
                        "statistics.model_assumptions": {"status": "pass", "reason": "PH assumption checked.", "evidence_ids": [ev]},
                        "statistics.missingness_exclusions": {"status": "pass", "reason": "Zero excluded patients.", "evidence_ids": [ev]},
                        "statistics.multiplicity_selection": {"status": "pass", "reason": "Single biomarker endpoint.", "evidence_ids": [ev]},
                        "statistics.comparisons_baselines": {"status": "pass", "reason": "Compared against HR=1.0 null.", "evidence_ids": [ev]},
                        "statistics.robustness_limits": {"status": "pass", "reason": "Unadjusted scope explicitly bounded.", "evidence_ids": [ev]},
                    },
                },
            )
            self.assertTrue(u1_upd["replaced"])
            self.assertEqual(u1_upd["claim_count"], 2)
            self.assertTrue(u1_upd["ceiling_diff"]["can_reach_target"])

            # Batch validate(collect_all=True) collects multiple errors in one dry-run without mutating state
            val = eng.validate_action(
                "set_ledger",
                {
                    "case_id": cid,
                    "claims": [
                        {"id": "BAD1", "text": "Missing required fields"},
                        {"id": "BAD2", "text": "Also missing fields"},
                    ],
                },
                collect_all=True,
            )
            self.assertFalse(val["valid"])
            self.assertTrue(val["dry_run"])
            self.assertGreaterEqual(len(val["issues"]), 2)
            # Stored claims remain intact (2 claims: C1 and C2)
            self.assertEqual(len(eng.dispatch("get_case", {"case_id": cid})["claims"]), 2)

    def test_estimate_first_blind_isolation_receipt_grades_cli_and_tool_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng, cid, ev_id = _make_external_prediction_case(ws, blind_mode="estimate_first")

            over = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
            self.assertEqual(over["blind_mode"], "estimate_first")
            self.assertIn("packet_nonce", over)
            self.assertIn("evidence_first_dossier", over)
            self.assertIn("ESTIMATE-FIRST BLIND PROTOCOL", over["instructions"])

            # CLI isolate-packet exports packet + sha256 + receipt template
            iso_out = ws / "packets" / "overclaim.json"
            buf_iso = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_iso})()):
                rc = cli_main(
                    [
                        "isolate-packet",
                        "--workspace", str(ws),
                        "--case-id", cid,
                        "--role", "overclaim",
                        "--output", "packets/overclaim.json",
                    ]
                )
            self.assertEqual(rc, 0)
            exported_iso = json.loads(iso_out.read_text(encoding="utf-8"))
            self.assertEqual(exported_iso["isolation_receipt_template"]["packet_nonce"], over["packet_nonce"])
            self.assertEqual(len(exported_iso["packet_sha256"]), 64)

            stance = {
                "claim_id": "C1",
                "stance": "supported",
                "rationale": "External cohort N=120 achieves AUROC 0.84 (95% CI 0.77-0.90).",
                "evidence_ids": [ev_id],
            }

            # Tampered packet_nonce rejected
            with self.assertRaises(ContractError) as ctx_nonce:
                eng.dispatch(
                    "submit_review",
                    {
                        "case_id": cid,
                        "role": "overclaim",
                        "packet_id": over["packet_id"],
                        "input_digest": over["input_digest"],
                        "reviewer": {"context_id": "over-iso", "model": "test-model"},
                        "covered_claim_ids": ["C1"],
                        "claim_stances": [dict(stance)],
                        "unread_evidence_ids": [],
                        "findings": [],
                        "isolation_receipt": {
                            "runner": "subprocess_runner",
                            "packet_nonce": "0" * 32,
                            "packet_sha256": exported_iso["packet_sha256"],
                            "parent_history_messages": 0,
                            "memory_enabled": False,
                            "tool_profile": "review",
                        },
                    },
                )
            self.assertEqual(ctx_nonce.exception.code, "invalid_isolation_receipt")

            # Valid runner isolation receipt -> runner_verified_isolated
            r_over = eng.dispatch(
                "submit_review",
                {
                    "case_id": cid,
                    "role": "overclaim",
                    "packet_id": over["packet_id"],
                    "input_digest": over["input_digest"],
                    "reviewer": {"context_id": "over-iso", "model": "test-model"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [dict(stance)],
                    "unread_evidence_ids": [],
                    "findings": [],
                    "isolation_receipt": {
                        "runner": "subprocess_runner",
                        "packet_nonce": over["packet_nonce"],
                        "packet_sha256": packet_content_sha256(over),
                        "parent_history_messages": 0,
                        "memory_enabled": False,
                        "tool_profile": "review",
                    },
                },
            )
            self.assertEqual(r_over["review"]["isolation_grade"]["grade"], "runner_verified_isolated")

            # Caller-attested underclaim review -> caller_attested
            under = eng.dispatch("review_packet", {"case_id": cid, "role": "underclaim"})
            r_under = eng.dispatch(
                "submit_review",
                {
                    "case_id": cid,
                    "role": "underclaim",
                    "packet_id": under["packet_id"],
                    "input_digest": under["input_digest"],
                    "reviewer": {"context_id": "under-att", "model": "test-model"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [dict(stance)],
                    "unread_evidence_ids": [],
                    "findings": [],
                    "isolation_attestation": {
                        "history_inheritance": "none (fresh context)",
                        "memory_access": "disabled",
                        "host_surface": "clean_subagent",
                    },
                },
            )
            self.assertEqual(r_under["review"]["isolation_grade"]["grade"], "caller_attested")

            # Lean MCP profiles
            self.assertEqual(len(tool_definitions(tool_profile="full")), 28)
            self.assertEqual(len(tool_definitions(tool_profile="compact")), 10)
            self.assertEqual(len(tool_definitions(tool_profile="explore")), 5)
            srv_explore = Server(ws, tool_profile="explore")
            srv_explore.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}})
            tools_resp = srv_explore.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
            names_exp = {t["name"] for t in tools_resp["result"]["tools"]}
            self.assertEqual(
                names_exp,
                {"parrhesia_contract", "parrhesia_select_workspace", "parrhesia_draft_manuscript", "parrhesia_explore", "parrhesia_analyze_design"},
            )

    # ------------------------------------------------------------------
    # Fix 5: Optional Pluggable PDF Backend with Strict Stdlib Default
    # ------------------------------------------------------------------
    def test_optional_pdf_backend_fallback_opt_in_and_encrypted_rejection(self):
        info = available_backends()
        self.assertEqual(info["pdf"]["default"], "stdlib_pdf")
        self.assertEqual(info["statistics"]["default"], "stdlib_math")

        # Synthesize a PDF header whose body stdlib_pdf rejects as unsupported/invalid
        complex_pdf = b"%PDF-1.7\n1 0 obj\n<< /Type /ObjStm >>\nendobj\n%%EOF\n"
        with self.assertRaises(ContractError):
            extract_pdf_with_fallback(complex_pdf, allow_optional_backend=False)

        # Mock PyMuPDF (`fitz`) to test opt-in fallback deterministically without external deps
        fake_page = types.SimpleNamespace(get_text=lambda mode="text": "External validation cohort AUROC = 0.84 (95% CI 0.77-0.90).")

        class _FakeDoc:
            is_encrypted = False

            def __iter__(self):
                return iter([fake_page])

            def close(self):
                return None

        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda stream=None, filetype=None: _FakeDoc()

        with patch("parrhesia.backends._module_available", side_effect=lambda name: name == "fitz"), patch.dict(sys.modules, {"fitz": fake_fitz}):
            units, omitted, backend = extract_pdf_with_fallback(complex_pdf, allow_optional_backend=True)
            self.assertEqual(backend, "optional_pymupdf")
            self.assertEqual(len(units), 1)
            self.assertIn("AUROC = 0.84", units[0]["text"])
            self.assertIn("pdf_images_and_ocr_not_run", omitted)

            # Encrypted PDFs remain blocked even when pdf_backend='auto'
            encrypted_pdf = b"%PDF-1.7\n1 0 obj\n<< /Encrypt 2 0 R >>\nendobj\n%%EOF\n"
            with self.assertRaises(ContractError):
                extract_pdf_with_fallback(encrypted_pdf, allow_optional_backend=True)

            # End-to-end Engine draft_manuscript(pdf_backend='auto') exposes parser_backend
            with tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp)
                (ws / "paper.pdf").write_bytes(complex_pdf)
                eng = Engine(ws)
                with self.assertRaises(ContractError):
                    eng.dispatch("draft_manuscript", {"path": "paper.pdf"})
                draft = eng.dispatch("draft_manuscript", {"path": "paper.pdf", "pdf_backend": "auto"})
                self.assertEqual(draft["source"]["parser_backend"], "optional_pymupdf")


if __name__ == "__main__":
    unittest.main()
