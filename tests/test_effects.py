"""Unit and integration tests for structured effect_records and computable checks."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS, scaffold_claim_template
from parrhesia.contracts import CHECK_NAMES, ContractError
from parrhesia.core import Engine, _digest
from parrhesia.effects import (
    DIFFERENCE_METRICS,
    EFFECT_BENEFICIAL_POLARITY,
    EFFECT_DIRECTIONS,
    EFFECT_METRICS,
    EFFECT_RECORD_ROLES,
    EFFECT_SCALES,
    PROPORTION_METRICS,
    RATIO_METRICS,
    validate_effect_records,
    verify_effect_computations,
)
from parrhesia.report import render_report


def _base_claim(ev_ids: list[str], *, effect_records=None, claim_type="association", evidence_level="adjusted"):
    claim = {
        "id": "C1",
        "text": "Intervention X lowers primary risk (HR 0.71, 95% CI 0.55 to 0.91, p=0.004).",
        "claim_type": claim_type,
        "evidence_level": evidence_level,
        "claim_basis": "empirical",
        "scope": "Adult cohort over 12 months",
        "evidence_ids": list(ev_ids),
        "effect": {"estimate": "HR 0.71", "uncertainty": "95% CI 0.55-0.91, p=0.004"},
        "origin": "unknown",
        "contribution": "Primary effect synthesis",
        "alternatives": [{"explanation": "Residual confounding", "status": "not_excluded", "reason": "Observational adjustment evaluated against baseline covariates"}],
        "checks": {name: {"status": "pass", "reason": "Checked and verified against published cohort methods and primary tables"} for name in CHECK_NAMES},
        "design_packages": [
            {
                "family": "observational",
                "checks": {
                    key: {"status": "pass", "reason": "Verified observational cohort design criteria in registered source", "evidence_ids": [ev_ids[0]]}
                    for key in DESIGN_FIELDS["observational"]
                },
            }
        ],
        "statistical_report": {
            key: {"status": "pass", "reason": "Verified statistical reporting criteria in registered source tables", "evidence_ids": [ev_ids[0]]}
            for key in STAT_FIELDS
        },
        "provenance_cards": {key: [] for key in CARD_FIELDS},
    }
    if effect_records is not None:
        claim["effect_records"] = effect_records
    return claim


def _decision(claim, ev_ids, *, verdict="supported", condition=None):
    dec = {
        "claim_id": claim["id"],
        "claim_type": claim["claim_type"],
        "evidence_level": claim["evidence_level"],
        "claim_basis": claim["claim_basis"],
        "scope": claim["scope"],
        "verdict": verdict,
        "revised_text": "Adjusted association HR 0.71 (95% CI 0.55-0.91, p=0.008) for primary endpoint.",
        "rationale": "Primary endpoint excludes null with compatible p-value.",
        "evidence_ids": list(ev_ids),
        "confidence": "medium",
        "confidence_reason": "Primary record anchored cleanly",
        "boundary": "Applies to studied cohort only",
        "reversal_condition": "Null primary effect on replication",
    }
    if condition is not None:
        dec["condition"] = condition
    return dec


class EffectRecordsTests(unittest.TestCase):
    def test_exported_constants(self):
        self.assertEqual(EFFECT_RECORD_ROLES, ("primary", "secondary", "safety", "exploratory", "sensitivity", "benchmark"))
        self.assertIn("HR", EFFECT_METRICS)
        self.assertEqual(RATIO_METRICS, ("HR", "OR", "RR", "IRR"))
        self.assertEqual(DIFFERENCE_METRICS, ("diff", "mean_diff", "risk_diff", "logFC", "beta"))
        self.assertEqual(PROPORTION_METRICS, ("proportion", "accuracy", "F1", "AUROC", "AUC"))
        self.assertEqual(EFFECT_DIRECTIONS, ("benefit", "harm", "null", "non_inferior", "equivalence", "higher_better", "lower_better", "neutral"))
        self.assertEqual(EFFECT_BENEFICIAL_POLARITY, ("below_null", "above_null"))
        self.assertEqual(EFFECT_SCALES, ("unit", "percentage"))

    def test_bounds_and_interval_validation(self):
        bad_bool = [{"id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": True, "direction": "benefit", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_bool, {"ev1"})
        self.assertEqual(cm.exception.code, "invalid_type")

        bad_nan = [{"id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "diff", "estimate": float("nan"), "direction": "benefit", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_nan, {"ev1"})
        self.assertEqual(cm.exception.code, "invalid_value")

        half_ci = [{"id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR", "estimate": 0.71, "ci_low": 0.55, "direction": "benefit", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(half_ci, {"ev1"})
        self.assertEqual(cm.exception.code, "effect_interval_inconsistent")

        inverted_ci = [{"id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR", "estimate": 0.71, "ci_low": 0.80, "ci_high": 0.91, "direction": "benefit", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(inverted_ci, {"ev1"})
        self.assertEqual(cm.exception.code, "effect_interval_inconsistent")

        neg_ratio = [{"id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR", "estimate": -0.2, "direction": "benefit", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(neg_ratio, {"ev1"})
        self.assertEqual(cm.exception.code, "invalid_ratio_effect")

        bad_prop = [{"id": "E1", "endpoint": "Acc", "endpoint_role": "benchmark", "metric": "accuracy", "estimate": 1.2, "scale": "unit", "direction": "higher_better", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_prop, {"ev1"})
        self.assertEqual(cm.exception.code, "invalid_value")

        bad_events = [{"id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": 0.5, "n": 10, "events": 11, "direction": "benefit", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_events, {"ev1"})
        self.assertEqual(cm.exception.code, "invalid_value")

    def test_numeric_quote_anchoring_formats_and_failures(self):
        ev = {
            "ev1": {"evidence_id": "ev1", "quote": "Primary survival HR 0.710 (95% CI .55\u2013.91, p=.004)."},
            "ev_neg": {"evidence_id": "ev_neg", "quote": "Mean diff \u22120.35 (95% CI -0.60 to -0.10), N = 1,234."},
        }
        claim = _base_claim(
            ["ev1", "ev_neg"],
            effect_records=[
                {
                    "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.004,
                    "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "ev1",
                },
                {
                    "id": "E2", "endpoint": "Score", "endpoint_role": "secondary", "metric": "mean_diff",
                    "estimate": -0.35, "ci_low": -0.60, "ci_high": -0.10,
                    "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "ev_neg",
                },
            ],
        )
        res = verify_effect_computations(claim, _decision(claim, ["ev1", "ev_neg"]), ev)
        self.assertEqual(res["record_count"], 2)
        self.assertTrue(all(c["anchored"] for c in res["checks"]))

        # Missing / different number triggers unanchored_effect_record
        claim_bad = deepcopy(claim)
        claim_bad["effect_records"][0]["estimate"] = 0.69
        with self.assertRaises(ContractError) as cm:
            verify_effect_computations(claim_bad, _decision(claim_bad, ["ev1", "ev_neg"]), ev)
        self.assertEqual(cm.exception.code, "unanchored_effect_record")

        # quote_substring mismatch also triggers unanchored_effect_record
        claim_sub = deepcopy(claim)
        claim_sub["effect_records"][0]["quote_substring"] = "nonexistent phrase"
        with self.assertRaises(ContractError) as cm:
            verify_effect_computations(claim_sub, _decision(claim_sub, ["ev1", "ev_neg"]), ev)
        self.assertEqual(cm.exception.code, "unanchored_effect_record")

        # snapshot_texts fallback works cleanly when supplied
        ev_no_quote = {"ev1": {"evidence_id": "ev1", "quote": None}}
        res_snap = verify_effect_computations(
            _base_claim(["ev1"], effect_records=[claim["effect_records"][0]]),
            _decision(claim, ["ev1"]),
            ev_no_quote,
            snapshot_texts={"ev1": "Kaplan-Meier HR = 0.71 (0.55-0.91, p = 0.004)"},
        )
        self.assertTrue(res_snap["checks"][0]["anchored"])

    def test_primary_vs_secondary_safety_asymmetry_and_polarity(self):
        ev = {
            "ev_prim": {"evidence_id": "ev_prim", "quote": "Primary outcome HR 0.71 (95% CI 0.55 to 0.91, p=0.008)."},
            "ev_safe": {"evidence_id": "ev_safe", "quote": "Serious adverse events OR 1.05 (95% CI 0.80 to 1.38, p=0.72)."},
        }
        claim = _base_claim(
            ["ev_prim", "ev_safe"],
            effect_records=[
                {
                    "id": "E_PRIM", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.008,
                    "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "ev_prim",
                },
                {
                    "id": "E_SAFE", "endpoint": "AE", "endpoint_role": "safety", "metric": "OR",
                    "estimate": 1.05, "ci_low": 0.80, "ci_high": 1.38, "p_value": 0.72,
                    "direction": "null", "evidence_id": "ev_safe",
                },
            ],
        )
        # Null safety record MUST NOT block supported judgment on primary claim
        res = verify_effect_computations(claim, _decision(claim, ["ev_prim"]), ev)
        self.assertEqual(res["primary_count"], 1)
        self.assertEqual(res["non_primary_count"], 1)

        # Failing to cite primary evidence_id blocks supported
        with self.assertRaises(ContractError) as cm:
            verify_effect_computations(claim, _decision(claim, ["ev_safe"]), ev)
        self.assertEqual(cm.exception.code, "uncited_primary_effect")

        # All primary records crossing null block supported, allow partially_supported or non_inferior
        ev_null = {"ev_prim": {"evidence_id": "ev_prim", "quote": "Primary outcome HR 0.92 (95% CI 0.72 to 1.18, p=0.51)."}}
        claim_null = _base_claim(
            ["ev_prim"],
            effect_records=[
                {
                    "id": "E_PRIM", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.92, "ci_low": 0.72, "ci_high": 1.18, "p_value": 0.51,
                    "direction": "null", "claim_direction": "benefit", "evidence_id": "ev_prim",
                }
            ],
        )
        with self.assertRaises(ContractError) as cm:
            verify_effect_computations(claim_null, _decision(claim_null, ["ev_prim"], verdict="supported"), ev_null)
        self.assertEqual(cm.exception.code, "primary_effect_crosses_null")

        # Non-inferiority allowed cleanly when margin-based
        claim_ni = deepcopy(claim_null)
        claim_ni["effect_records"][0]["direction"] = "non_inferior"
        claim_ni["effect_records"][0]["claim_direction"] = "non_inferior"
        verify_effect_computations(claim_ni, _decision(claim_ni, ["ev_prim"], verdict="supported"), ev_null)

        # Polarity conflict blocked
        ev_flip = {"ev_prim": {"evidence_id": "ev_prim", "quote": "Primary outcome HR 1.30 (95% CI 1.05 to 1.61, p=0.015)."}}
        claim_flip = _base_claim(
            ["ev_prim"],
            effect_records=[
                {
                    "id": "E_PRIM", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 1.30, "ci_low": 1.05, "ci_high": 1.61, "p_value": 0.015,
                    "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "ev_prim",
                }
            ],
        )
        with self.assertRaises(ContractError) as cm:
            verify_effect_computations(claim_flip, _decision(claim_flip, ["ev_prim"]), ev_flip)
        self.assertEqual(cm.exception.code, "effect_direction_mismatch")

    def test_pvalue_ci_compatibility(self):
        # Compatible (including slight rounding around 0.05)
        ok_records = [
            {
                "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.008,
                "direction": "benefit", "evidence_id": "ev1",
            },
            {
                "id": "E2", "endpoint": "Rounded", "endpoint_role": "secondary", "metric": "OR",
                "estimate": 0.80, "ci_low": 0.64, "ci_high": 0.99, "p_value": 0.052,
                "direction": "benefit", "evidence_id": "ev1",
            },
        ]
        for rec in ok_records:
            rec["inference_method"] = "log_wald"
        validate_effect_records(ok_records, {"ev1"})

        # Contradiction 1: CI excludes null yet p=0.45
        bad_high_p = [{
            "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
            "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.45,
            "direction": "benefit", "evidence_id": "ev1",
        }]
        bad_high_p[0]["inference_method"] = "log_wald"
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_high_p, {"ev1"})
        self.assertEqual(cm.exception.code, "effect_pvalue_ci_mismatch")

        # Contradiction 2: CI spans null widely yet p=0.001
        bad_low_p = [{
            "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
            "estimate": 1.05, "ci_low": 0.70, "ci_high": 1.60, "p_value": 0.001,
            "direction": "null", "evidence_id": "ev1",
        }]
        bad_low_p[0]["inference_method"] = "log_wald"
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_low_p, {"ev1"})
        self.assertEqual(cm.exception.code, "effect_pvalue_ci_mismatch")

    def test_grim_and_granularity_checks(self):
        # events/n exact within 2 decimals
        ok_gran = [{"id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": 0.43, "n": 23, "events": 10, "decimals": 2, "direction": "higher_better", "evidence_id": "ev1"}]
        validate_effect_records(ok_gran, {"ev1"})

        ok_pct = [{"id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": 52.17, "scale": "percentage", "n": 23, "events": 12, "decimals": 2, "direction": "higher_better", "evidence_id": "ev1"}]
        validate_effect_records(ok_pct, {"ev1"})

        bad_gran = [{"id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": 0.50, "n": 23, "events": 10, "decimals": 2, "direction": "higher_better", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_gran, {"ev1"})
        self.assertEqual(cm.exception.code, "effect_granularity_mismatch")

        # GRIM impossible fraction without events: n=23, 0.50 with decimals=2
        bad_grim = [{"id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": 0.50, "n": 23, "decimals": 2, "direction": "higher_better", "evidence_id": "ev1"}]
        with self.assertRaises(ContractError) as cm:
            validate_effect_records(bad_grim, {"ev1"})
        self.assertEqual(cm.exception.code, "effect_grim_inconsistent")

        # GRIM feasible fraction: 12/23 = 0.5217 -> 0.52 passes
        ok_grim = [{"id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary", "estimate": 0.52, "n": 23, "decimals": 2, "direction": "higher_better", "evidence_id": "ev1"}]
        validate_effect_records(ok_grim, {"ev1"})

    def test_scaffold_frozen_digest_and_e2e_workflow_symmetry_and_reports(self):
        # scaffold default omits effect_records so frozen digests stay untouched
        base_skel = scaffold_claim_template({"claim_type": "association", "evidence_level": "adjusted"})
        self.assertNotIn("effect_records", base_skel)
        eff_skel = scaffold_claim_template({"claim_type": "association", "evidence_level": "adjusted", "include_effect_records": True})
        self.assertEqual(eff_skel["effect_records"], [])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "primary.txt").write_text("Primary cohort mortality HR 0.71 (95% CI 0.55-0.91, p=0.008).\n", encoding="utf-8")
            (root / "safety.txt").write_text("Serious adverse event rate showed no significant difference: OR 1.05 (95% CI 0.80 to 1.38, p=0.72).\n", encoding="utf-8")
            engine = Engine(root)
            case = engine.dispatch("create_case", {"question": "Effect verification?", "draft": "Draft text", "writer_context_id": "writer", "symmetry_mode": "advisory"})
            cid = case["case_id"]
            ev_p = engine.dispatch("register_evidence", {
                "case_id": cid, "path": "primary.txt", "provenance": "observed", "kind": "observation",
                "quote": "Primary cohort mortality HR 0.71 (95% CI 0.55-0.91, p=0.008).", "location": "Table 1",
            })["evidence_id"]
            ev_s = engine.dispatch("register_evidence", {
                "case_id": cid, "path": "safety.txt", "provenance": "observed", "kind": "observation",
                "quote": "Serious adverse event rate showed no significant difference: OR 1.05 (95% CI 0.80 to 1.38, p=0.72).", "location": "Table 2",
            })["evidence_id"]

            claim = _base_claim(
                [ev_p, ev_s],
                effect_records=[
                    {
                        "id": "E_PRIM", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                        "estimate": 0.71, "ci_low": 0.55, "ci_high": 0.91, "p_value": 0.008,
                        "direction": "benefit", "beneficial_if": "below_null", "evidence_id": ev_p,
                    },
                    {
                        "id": "E_SAFE", "endpoint": "SAE", "endpoint_role": "safety", "metric": "OR",
                        "estimate": 1.05, "ci_low": 0.80, "ci_high": 1.38, "p_value": 0.72,
                        "direction": "null", "evidence_id": ev_s,
                    },
                ],
            )
            claim["text"] = "Intervention X lowers primary risk (HR 0.71, 95% CI 0.55 to 0.91, p=0.008)."
            claim["effect"] = {"estimate": "HR 0.71", "uncertainty": "95% CI 0.55-0.91, p=0.008"}
            # Check _frozen_input digest excludes effect_records when omitted
            claim_no_eff = _base_claim([ev_p, ev_s])
            self.assertNotIn("effect_records", claim_no_eff)
            d1 = _digest(claim_no_eff)
            claim_no_eff_copy = deepcopy(claim_no_eff)
            self.assertEqual(d1, _digest(claim_no_eff_copy))

            engine.dispatch("set_ledger", {"case_id": cid, "claims": [claim]})
            frozen = engine.dispatch("freeze", {"case_id": cid})
            for role in ("overclaim", "underclaim"):
                pkt = engine.dispatch("review_packet", {"case_id": cid, "role": role})
                engine.dispatch("submit_review", {
                    "case_id": cid, "role": role, "packet_id": pkt["packet_id"], "input_digest": frozen["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Primary benefit HR 0.71", "evidence_ids": [ev_p]}],
                    "unread_evidence_ids": [], "findings": [],
                })
            adj_pkt = engine.dispatch("adjudication_packet", {"case_id": cid})

            # False unsupported triggers non-blocking advisory flag despite safety null
            unsupported_adj = {
                "case_id": cid, "adjudication_id": adj_pkt["adjudication_id"], "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                "decisions": [{
                    **_decision(claim, [ev_p, ev_s], verdict="unsupported"),
                    "rationale": "However, preliminary sensitivity remains unconfirmed so we remain cautious.",
                }],
            }
            dry_unsupported = engine.validate_action("submit_adjudication", unsupported_adj)
            self.assertTrue(dry_unsupported["valid"])
            sym = dry_unsupported["preview"]["symmetry_audit"]
            self.assertTrue(sym["non_blocking"])
            self.assertIn("unsupported_despite_beneficial_primary_effect", {f["hook_code"] for f in sym["flags"]})

            # Verify valid supported judgment + verify + export + HTML sym_html rendering both flags & lexical_advisories
            supported_adj = {
                "case_id": cid, "adjudication_id": adj_pkt["adjudication_id"], "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                "decisions": [_decision(claim, [ev_p])],
            }
            engine.dispatch("submit_adjudication", supported_adj)
            ver = engine.dispatch("verify", {"case_id": cid})
            self.assertEqual(ver["status"], "pass")
            self.assertIn("C1", ver["effect_checks"])
            self.assertEqual(ver["effect_checks"]["C1"]["primary_count"], 1)
            engine.dispatch("record_human_decision", {"case_id": cid, "decision": "accept", "responsible_human": "lead", "reason": "Reviewed"})
            exp = engine.dispatch("export", {"case_id": cid})
            md_text = (root / exp["relative_path"]).read_text(encoding="utf-8")
            self.assertIn("effect_records", md_text)
            self.assertIn("effect_checks", md_text)
            self.assertIn("SQLite event chain", md_text)

            # HTML report renders effect_checks AND both flags and lexical_advisories in sym_html
            html_out = root / "report.html"
            case_data = engine.dispatch("get_case", {"case_id": cid})
            case_data["symmetry_audit"] = {
                "non_blocking": True,
                "severity": "advisory",
                "flag_count": 1,
                "flags": [{"claim_id": "C1", "hook_code": "possible_false_abstention", "message": "Flag msg", "observed_verdict": "unsupported"}],
                "lexical_advisory_count": 1,
                "lexical_advisories": [{"claim_id": "C1", "hook_code": "unsupported_despite_evidence", "detail_code": "preliminary_overclaim_cue", "message": "Lex cue msg"}],
            }
            render_report(case_data, html_out)
            html_text = html_out.read_text(encoding="utf-8")
            self.assertIn("effect_checks", html_text)
            self.assertIn("possible_false_abstention", html_text)
            self.assertIn("preliminary_overclaim_cue", html_text)
            self.assertIn("Lex cue msg", html_text)

    def test_engine_blocks_unanchored_effect_record_and_primary_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "primary.txt").write_text("Primary outcome HR 0.92 (95% CI 0.72-1.18, p=0.51).\n", encoding="utf-8")
            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "Null?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
            ev_p = engine.dispatch("register_evidence", {
                "case_id": cid, "path": "primary.txt", "provenance": "observed", "kind": "observation",
                "quote": "Primary outcome HR 0.92 (95% CI 0.72-1.18, p=0.51).", "location": "Table 1",
            })["evidence_id"]
            claim = _base_claim(
                [ev_p],
                effect_records=[{
                    "id": "E1", "endpoint": "OS", "endpoint_role": "primary", "metric": "HR",
                    "estimate": 0.92, "ci_low": 0.72, "ci_high": 1.18, "p_value": 0.51,
                    "direction": "null", "claim_direction": "benefit", "evidence_id": ev_p,
                }],
            )
            claim["text"] = "Primary outcome HR 0.92 (95% CI 0.72-1.18, p=0.51)."
            claim["effect"] = {"estimate": "HR 0.92", "uncertainty": "95% CI 0.72-1.18, p=0.51"}
            engine.dispatch("set_ledger", {"case_id": cid, "claims": [claim]})
            frozen = engine.dispatch("freeze", {"case_id": cid})
            for role in ("overclaim", "underclaim"):
                pkt = engine.dispatch("review_packet", {"case_id": cid, "role": role})
                engine.dispatch("submit_review", {
                    "case_id": cid, "role": role, "packet_id": pkt["packet_id"], "input_digest": frozen["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Primary crosses null", "evidence_ids": [ev_p]}],
                    "unread_evidence_ids": [], "findings": [],
                })
            adj_pkt = engine.dispatch("adjudication_packet", {"case_id": cid})
            bad_adj = {
                "case_id": cid, "adjudication_id": adj_pkt["adjudication_id"], "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                "decisions": [{
                    **_decision(claim, [ev_p], verdict="supported"),
                    "revised_text": "Cohort HR 0.92 (95% CI 0.72-1.18, p=0.51).",
                }],
            }
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("submit_adjudication", bad_adj)
            self.assertEqual(cm.exception.code, "primary_effect_crosses_null")

            # Also verify set_ledger catches GRIM inconsistency upfront
            cid2 = engine.dispatch("create_case", {"question": "GRIM?", "draft": "Draft"})["case_id"]
            ev2 = engine.dispatch("register_evidence", {
                "case_id": cid2, "path": "primary.txt", "provenance": "observed", "kind": "observation",
                "quote": "Primary outcome HR 0.92 (95% CI 0.72-1.18, p=0.51).", "location": "Table 1",
            })["evidence_id"]
            bad_grim_claim = _base_claim([ev2], effect_records=[{
                "id": "E1", "endpoint": "Resp", "endpoint_role": "primary", "metric": "proportion", "count_basis": "unweighted_binary",
                "estimate": 0.50, "n": 23, "decimals": 2, "direction": "higher_better", "evidence_id": ev2,
            }])
            with self.assertRaises(ContractError) as cm2:
                engine.dispatch("set_ledger", {"case_id": cid2, "claims": [bad_grim_claim]})
            self.assertEqual(cm2.exception.code, "effect_grim_inconsistent")

    def test_notes_preserved_and_artifact_binding_record_index_decoupled_from_max_records(self):
        sha = "a" * 64
        records = [
            {
                "id": "EFF1",
                "endpoint": "Primary survival",
                "endpoint_role": "primary",
                "metric": "HR",
                "estimate": 0.71,
                "ci_low": 0.55,
                "ci_high": 0.91,
                "p_value": 0.004,
                "direction": "benefit",
                "evidence_id": "E1",
                "notes": "Pre-specified subgroup sensitivity row",
                "artifact_binding": {
                    "version": 1,
                    "format": "csv",
                    "source_sha256": sha,
                    "record_index": 120,
                    "column_map": {"estimate": "hr"},
                },
            },
            {
                "id": "EFF2",
                "endpoint": "All-cause mortality",
                "endpoint_role": "secondary",
                "metric": "HR",
                "estimate": 0.88,
                "direction": "benefit",
                "evidence_id": "E1",
            },
        ]
        validated = validate_effect_records(records, {"E1"})
        self.assertEqual(validated[0]["notes"], "Pre-specified subgroup sensitivity row")
        self.assertEqual(validated[0]["artifact_binding"]["record_index"], 120)
        self.assertNotIn("notes", validated[1])

        over_index = deepcopy(records[0])
        over_index["artifact_binding"]["record_index"] = 100_001
        with self.assertRaises(ContractError) as cm_idx:
            validate_effect_records([over_index], {"E1"})
        self.assertEqual(cm_idx.exception.code, "invalid_value")

        fifty_one = [{**records[1], "id": f"EFF{i}"} for i in range(51)]
        with self.assertRaises(ContractError):
            validate_effect_records(fifty_one, {"E1"})

    def test_grim_trailing_zero_preserved_from_anchored_evidence(self):
        ev_text = "Responder proportion was 0.50 (11 of 23 participants; n=23)."
        ev = {
            "evidence_id": "E1",
            "source_text_status": "complete",
            "source_text": ev_text,
            "quote": ev_text,
        }
        base_rec = {
            "id": "EFF1",
            "endpoint": "Response",
            "endpoint_role": "primary",
            "metric": "proportion",
            "scale": "unit",
            "estimate": 0.5,
            "n": 23,
            "count_basis": "unweighted_binary",
            "direction": "higher_better",
            "evidence_id": "E1",
        }
        c_bad = _base_claim(["E1"], effect_records=[base_rec])
        c_bad["text"] = "Responder proportion was 0.50 (n=23)."
        with self.assertRaises(ContractError) as cm_grim:
            verify_effect_computations(c_bad, _decision(c_bad, ["E1"], verdict="supported"), {"E1": ev})
        self.assertEqual(cm_grim.exception.code, "effect_grim_inconsistent")

        c_gran = _base_claim(["E1"], effect_records=[{**base_rec, "events": 11}])
        c_gran["text"] = "Responder proportion was 0.50 (11/23)."
        with self.assertRaises(ContractError) as cm_gran:
            verify_effect_computations(c_gran, _decision(c_gran, ["E1"], verdict="supported"), {"E1": ev})
        self.assertEqual(cm_gran.exception.code, "effect_granularity_mismatch")

        ok_text = "Responder proportion was 0.50 (10 of 20 participants; n=20)."
        ok_ev = {"evidence_id": "E1", "source_text_status": "complete", "source_text": ok_text, "quote": ok_text}
        c_ok = _base_claim(["E1"], effect_records=[{**base_rec, "n": 20, "events": 10}])
        c_ok["text"] = "Responder proportion was 0.50 (10/20)."
        res_ok = verify_effect_computations(c_ok, _decision(c_ok, ["E1"], verdict="supported"), {"E1": ok_ev})
        self.assertEqual(res_ok["checks"][0]["grim_granularity_check"], "pass")

        amb_text = "Table A proportion 0.5 vs Table B proportion 0.50 (n=23)."
        amb_ev = {"evidence_id": "E1", "source_text_status": "complete", "source_text": amb_text, "quote": amb_text}
        c_amb = _base_claim(["E1"], effect_records=[base_rec])
        c_amb["text"] = "Proportion was 0.5 (n=23)."
        res_amb = verify_effect_computations(c_amb, _decision(c_amb, ["E1"], verdict="supported"), {"E1": amb_ev})
        self.assertEqual(res_amb["record_count"], 1)

        c_disamb = _base_claim(
            ["E1"],
            effect_records=[{**base_rec, "quote_substring": "Table B proportion 0.50 (n=23)"}],
        )
        c_disamb["text"] = "Proportion was 0.50 (n=23)."
        with self.assertRaises(ContractError) as cm_disamb:
            verify_effect_computations(c_disamb, _decision(c_disamb, ["E1"], verdict="supported"), {"E1": amb_ev})
        self.assertEqual(cm_disamb.exception.code, "effect_grim_inconsistent")

    def test_non_inferior_and_equivalence_margin_compliance_and_no_ci_pvalue_alpha_gate(self):
        ev_text = (
            "NI HR 1.05 (95% CI 0.90-1.20, margin 1.25); "
            "NI fail HR 1.08 (95% CI 0.90-1.30, margin 1.25); "
            "NI strict above margin HR 1.40 (95% CI 1.30-1.50, margin 1.25); "
            "NI diff fail -0.03 (95% CI -0.12 to 0.06, margin -0.10); "
            "NI diff ok -0.02 (95% CI -0.08 to 0.04, margin -0.10); "
            "EQ diff ok 0.02 (95% CI -0.04 to 0.08, margin 0.10); "
            "EQ diff fail 0.06 (95% CI -0.01 to 0.13, margin 0.10); "
            "EQ HR ok 1.01 (95% CI 0.85 to 1.18, margin 1.25); "
            "EQ HR fail 0.95 (95% CI 0.76 to 1.20, margin 1.25); "
            "No-CI HR 0.71 (p=0.05, p=0.31, p=0.02, p=0.012)."
        )
        ev = {"evidence_id": "E1", "source_text_status": "complete", "source_text": ev_text, "quote": ev_text}

        def check_record(rec, *, verdict="supported"):
            c = _base_claim(["E1"], effect_records=[rec])
            c["text"] = ev_text
            return verify_effect_computations(c, _decision(c, ["E1"], verdict=verdict), {"E1": ev})

        ni_ok = check_record({
            "id": "NI1", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
            "estimate": 1.05, "ci_low": 0.90, "ci_high": 1.20, "null_value": 1.25,
            "direction": "non_inferior", "evidence_id": "E1",
        })
        self.assertFalse(ni_ok["checks"][0]["crosses_null"])

        for bad_rec in (
            {
                "id": "NI2", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 1.08, "ci_low": 0.90, "ci_high": 1.30, "null_value": 1.25,
                "direction": "non_inferior", "evidence_id": "E1",
            },
            {
                "id": "NI3", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 1.40, "ci_low": 1.30, "ci_high": 1.50, "null_value": 1.25,
                "direction": "non_inferior", "evidence_id": "E1",
            },
            {
                "id": "NI4", "endpoint": "Primary", "endpoint_role": "primary", "metric": "risk_diff",
                "estimate": -0.03, "ci_low": -0.12, "ci_high": 0.06, "null_value": -0.10,
                "beneficial_if": "above_null", "direction": "non_inferior", "evidence_id": "E1",
            },
            {
                "id": "EQ2", "endpoint": "Primary", "endpoint_role": "primary", "metric": "risk_diff",
                "estimate": 0.06, "ci_low": -0.01, "ci_high": 0.13, "null_value": 0.10,
                "direction": "equivalence", "evidence_id": "E1",
            },
            {
                "id": "EQ4", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.95, "ci_low": 0.76, "ci_high": 1.20, "null_value": 1.25,
                "direction": "equivalence", "evidence_id": "E1",
            },
        ):
            with self.subTest(bad_rec=bad_rec["id"]):
                with self.assertRaises(ContractError) as cm:
                    check_record(bad_rec)
                self.assertEqual(cm.exception.code, "primary_effect_crosses_null")

        for good_rec in (
            {
                "id": "NI5", "endpoint": "Primary", "endpoint_role": "primary", "metric": "risk_diff",
                "estimate": -0.02, "ci_low": -0.08, "ci_high": 0.04, "null_value": -0.10,
                "beneficial_if": "above_null", "direction": "non_inferior", "evidence_id": "E1",
            },
            {
                "id": "EQ1", "endpoint": "Primary", "endpoint_role": "primary", "metric": "risk_diff",
                "estimate": 0.02, "ci_low": -0.04, "ci_high": 0.08, "null_value": 0.10,
                "direction": "equivalence", "evidence_id": "E1",
            },
            {
                "id": "EQ3", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 1.01, "ci_low": 0.85, "ci_high": 1.18, "null_value": 1.25,
                "direction": "equivalence", "evidence_id": "E1",
            },
        ):
            with self.subTest(good_rec=good_rec["id"]):
                res_good = check_record(good_rec)
                self.assertFalse(res_good["checks"][0]["crosses_null"])

        for bad_pval_rec in (
            {
                "id": "NCI_EQ", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.71, "p_value": 0.05, "direction": "benefit", "evidence_id": "E1",
            },
            {
                "id": "NCI_NS", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.71, "p_value": 0.31, "direction": "benefit", "evidence_id": "E1",
            },
            {
                "id": "NCI_99", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.71, "p_value": 0.02, "ci_level": 0.99, "direction": "benefit", "evidence_id": "E1",
            },
        ):
            with self.subTest(bad_pval=bad_pval_rec["id"]):
                with self.assertRaises(ContractError) as cm_nci:
                    check_record(bad_pval_rec, verdict="supported")
                self.assertEqual(cm_nci.exception.code, "primary_effect_crosses_null")

        check_record(
            {"id": "NCI_OK", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR", "estimate": 0.71, "p_value": 0.012, "direction": "benefit", "evidence_id": "E1"},
            verdict="supported",
        )
        check_record(
            {"id": "NCI_PART", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR", "estimate": 0.71, "p_value": 0.31, "direction": "benefit", "evidence_id": "E1"},
            verdict="partially_supported",
        )
        check_record(
            {"id": "NCI_SEC", "endpoint": "Secondary", "endpoint_role": "secondary", "metric": "HR", "estimate": 0.71, "p_value": 0.31, "direction": "benefit", "evidence_id": "E1"},
            verdict="supported",
        )

    def test_student_t_pvalue_ci_compatibility_and_missing_df_unassessed(self):
        # student_t without df remains explicitly unassessed (never invents df)
        res_no_df = verify_effect_computations(
            {
                "id": "C1",
                "effect_records": [{
                    "id": "T0", "endpoint": "Diff", "endpoint_role": "primary", "metric": "mean_diff",
                    "estimate": 2.0, "ci_low": -0.5, "ci_high": 4.5, "p_value": 0.40,
                    "inference_method": "student_t", "direction": "neutral", "evidence_id": "E1",
                }],
            },
            None,
            {"E1": {"evidence_id": "E1", "quote": "Diff mean_diff 2.0 (-0.5 to 4.5, p=0.40)"}},
        )
        self.assertEqual(res_no_df["checks"][0]["pvalue_ci_check"], "unassessed")

        # Exact df=4 two-sided 95% t-interval: t_{0.975, 4} = 2.7764451051977987, SE = 1.0, t = 2.0 -> p = 0.1161165
        res_ok = verify_effect_computations(
            {
                "id": "C1",
                "effect_records": [{
                    "id": "T1", "endpoint": "Diff", "endpoint_role": "primary", "metric": "mean_diff",
                    "estimate": 2.0, "ci_low": -0.7764, "ci_high": 4.7764, "p_value": 0.1161,
                    "df": 4, "inference_method": "student_t", "direction": "neutral", "evidence_id": "E1",
                }],
            },
            None,
            {"E1": {"evidence_id": "E1", "quote": "Diff mean_diff 2.0 (-0.7764 to 4.7764, p=0.1161)"}},
        )
        self.assertEqual(res_ok["checks"][0]["pvalue_ci_check"], "pass")

        # Contradictory student_t: CI excludes 0 yet p=0.50 with df=4
        with self.assertRaises(ContractError) as cm:
            validate_effect_records([{
                "id": "T2", "endpoint": "Diff", "endpoint_role": "primary", "metric": "mean_diff",
                "estimate": 2.0, "ci_low": 0.2, "ci_high": 3.8, "p_value": 0.50,
                "df": 4, "inference_method": "student_t", "direction": "benefit",
                "beneficial_if": "above_null", "evidence_id": "E1",
            }], {"E1"})
        self.assertEqual(cm.exception.code, "effect_pvalue_ci_mismatch")

    def test_contingency_consistency_and_mismatch_errors(self):
        valid = [
            {
                "id": "CT1", "endpoint": "Event", "endpoint_role": "primary", "metric": "OR",
                "estimate": 0.3333, "contingency": {"treated_events": 10, "treated_n": 40, "control_events": 20, "control_n": 40},
                "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1",
            },
            {
                "id": "CT2", "endpoint": "RD", "endpoint_role": "secondary", "metric": "risk_diff",
                "estimate": -25.0, "scale": "percentage", "decimals": 1,
                "contingency": {"a": 10, "b": 30, "c": 20, "d": 20},
                "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1",
            },
            {
                "id": "CT3", "endpoint": "Acc", "endpoint_role": "benchmark", "metric": "accuracy",
                "estimate": 0.75, "decimals": 2,
                "contingency": {"a": 30, "b": 10, "c": 10, "d": 30},
                "direction": "higher_better", "evidence_id": "E1",
            },
        ]
        validate_effect_records(valid, {"E1"})

        # Wrong estimate vs raw 2x2 table
        with self.assertRaises(ContractError) as cm:
            validate_effect_records([{
                "id": "CT_BAD", "endpoint": "Event", "endpoint_role": "primary", "metric": "RR",
                "estimate": 0.90, "contingency": {"treated_events": 10, "treated_n": 40, "control_events": 20, "control_n": 40},
                "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1",
            }], {"E1"})
        self.assertEqual(cm.exception.code, "effect_contingency_mismatch")

        # Zero cell in OR is caught cleanly
        with self.assertRaises(ContractError) as cm_zero:
            validate_effect_records([{
                "id": "CT_ZERO", "endpoint": "Event", "endpoint_role": "primary", "metric": "OR",
                "estimate": 0.25, "contingency": {"a": 0, "b": 40, "c": 10, "d": 30},
                "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1",
            }], {"E1"})
        self.assertEqual(cm_zero.exception.code, "effect_contingency_mismatch")

    def test_multiplicity_consistency_and_primary_adjusted_alpha_gate(self):
        # Valid Holm and BH-FDR families across all m endpoints
        holm_recs = [
            {"id": "H1", "endpoint": "E1", "endpoint_role": "primary", "metric": "HR", "estimate": 0.70, "p_value": 0.01, "adjusted_p_value": 0.03, "multiplicity_method": "holm", "family_size": 3, "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1"},
            {"id": "H2", "endpoint": "E2", "endpoint_role": "secondary", "metric": "HR", "estimate": 0.80, "p_value": 0.03, "adjusted_p_value": 0.06, "multiplicity_method": "holm", "family_size": 3, "direction": "neutral", "evidence_id": "E1"},
            {"id": "H3", "endpoint": "E3", "endpoint_role": "secondary", "metric": "HR", "estimate": 0.85, "p_value": 0.04, "adjusted_p_value": 0.06, "multiplicity_method": "holm", "family_size": 3, "direction": "neutral", "evidence_id": "E1"},
        ]
        validate_effect_records(holm_recs, {"E1"})

        bh_recs = [
            {"id": "B1", "endpoint": "E1", "endpoint_role": "primary", "metric": "HR", "estimate": 0.70, "p_value": 0.01, "adjusted_p_value": 0.03, "multiplicity_method": "bh_fdr", "family_size": 3, "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1"},
            {"id": "B2", "endpoint": "E2", "endpoint_role": "secondary", "metric": "HR", "estimate": 0.80, "p_value": 0.03, "adjusted_p_value": 0.04, "multiplicity_method": "bh_fdr", "family_size": 3, "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1"},
            {"id": "B3", "endpoint": "E3", "endpoint_role": "secondary", "metric": "HR", "estimate": 0.85, "p_value": 0.04, "adjusted_p_value": 0.04, "multiplicity_method": "bh_fdr", "family_size": 3, "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1"},
        ]
        validate_effect_records(bh_recs, {"E1"})

        # Bad Bonferroni adjusted p-value
        with self.assertRaises(ContractError) as cm_bonf:
            validate_effect_records([{
                "id": "M1", "endpoint": "E1", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.70, "p_value": 0.015, "adjusted_p_value": 0.03,
                "multiplicity_method": "bonferroni", "family_size": 4,
                "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1",
            }], {"E1"})
        self.assertEqual(cm_bonf.exception.code, "effect_multiplicity_mismatch")

        # Partial family remains explicitly unassessed instead of fabricating sibling tests
        res_partial = verify_effect_computations(
            {
                "id": "C1",
                "effect_records": [{
                    "id": "PF1", "endpoint": "E1", "endpoint_role": "secondary", "metric": "HR",
                    "estimate": 0.80, "p_value": 0.03, "adjusted_p_value": 0.09,
                    "multiplicity_method": "holm", "family_size": 5, "direction": "neutral", "evidence_id": "E1",
                }],
            },
            None,
            {"E1": {"evidence_id": "E1", "quote": "E1 HR 0.80 p=0.03 adj=0.09"}},
        )
        self.assertEqual(res_partial["checks"][0]["multiplicity_check"], "unassessed")

        # Primary directional record passes unadjusted alpha (0.015 < 0.05) & CI, but fails adjusted_p_value (0.06 >= 0.05) -> blocked on supported verdict!
        ev_map = {"E1": {"evidence_id": "E1", "quote": "Primary HR 0.70 (95% CI 0.52-0.94, p=0.015, adj=0.06)."}}
        claim = {
            "id": "C1",
            "effect_records": [{
                "id": "PM1", "endpoint": "Primary", "endpoint_role": "primary", "metric": "HR",
                "estimate": 0.70, "ci_low": 0.52, "ci_high": 0.94, "p_value": 0.015,
                "adjusted_p_value": 0.06, "multiplicity_method": "bonferroni", "family_size": 4,
                "direction": "benefit", "beneficial_if": "below_null", "evidence_id": "E1",
            }],
        }
        with self.assertRaises(ContractError) as cm_gate:
            verify_effect_computations(claim, {"claim_id": "C1", "verdict": "supported", "evidence_ids": ["E1"]}, ev_map)
        self.assertEqual(cm_gate.exception.code, "primary_effect_fails_multiplicity")

    def test_subgroup_interaction_contrast_checks(self):
        # Two independent subgroups: diff1 = 1.8 [0.8, 2.8] -> SE=0.5102; diff2 = 0.2 [-0.6, 1.0] -> SE=0.4082
        # se_int = hypot(0.5102, 0.4082) = 0.6534; delta = 1.6; z = 2.4487 -> two-sided p = 0.01434
        recs = [
            {"id": "S1", "endpoint": "Male", "endpoint_role": "exploratory", "metric": "mean_diff", "estimate": 1.8, "ci_low": 0.8, "ci_high": 2.8, "inference_method": "wald", "direction": "neutral", "evidence_id": "E1"},
            {"id": "S2", "endpoint": "Female", "endpoint_role": "exploratory", "metric": "mean_diff", "estimate": 0.2, "ci_low": -0.6, "ci_high": 1.0, "inference_method": "wald", "direction": "neutral", "evidence_id": "E1"},
            {"id": "INT", "endpoint": "Sex interaction", "endpoint_role": "exploratory", "metric": "mean_diff", "estimate": 1.6, "p_value": 0.0143, "interaction_contrast": {"record_ids": ["S1", "S2"], "dependence": "independent"}, "direction": "neutral", "evidence_id": "E1"},
        ]
        validate_effect_records(recs, {"E1"})

        # Bad interaction p_value under independent Wald CIs
        bad_recs = [recs[0], recs[1], {**recs[2], "p_value": 0.70}]
        with self.assertRaises(ContractError) as cm_p:
            validate_effect_records(bad_recs, {"E1"})
        self.assertEqual(cm_p.exception.code, "effect_interaction_mismatch")

        # Unknown dependence checks point difference only and never fabricates SE/p-value rejection
        unk_recs = [recs[0], recs[1], {**recs[2], "p_value": 0.70, "interaction_contrast": {"record_ids": ["S1", "S2"], "dependence": "unknown"}}]
        res_unk = verify_effect_computations(
            {"id": "C1", "effect_records": unk_recs},
            None,
            {"E1": {"evidence_id": "E1", "quote": "Male 1.8 (0.8-2.8); Female 0.2 (-0.6-1.0); Sex interaction 1.6 p=0.70"}},
        )
        self.assertEqual(res_unk["checks"][2]["interaction_check"], "point_only_dependence_unknown")

    def test_xlsx_artifact_binding_verified_with_snapshot_bytes(self):
        import hashlib, io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Summary" sheetId="1" r:id="rId1"/><sheet name="Effects" sheetId="2" r:id="rId2"/></sheets></workbook>')
            zf.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
            zf.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Note</t></is></c></row></sheetData></worksheet>')
            zf.writestr("xl/worksheets/sheet2.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>endpoint</t></is></c><c r="B1" t="inlineStr"><is><t>metric</t></is></c><c r="C1" t="inlineStr"><is><t>estimate</t></is></c><c r="D1" t="inlineStr"><is><t>ci_low</t></is></c><c r="E1" t="inlineStr"><is><t>ci_high</t></is></c><c r="F1" t="inlineStr"><is><t>p_value</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>OS</t></is></c><c r="B2" t="inlineStr"><is><t>HR</t></is></c><c r="C2"><v>0.71</v></c><c r="D2"><v>0.55</v></c><c r="E2"><v>0.91</v></c><c r="F2"><v>0.008</v></c></row></sheetData></worksheet>')
        xlsx_bytes = buf.getvalue()
        sha = hashlib.sha256(xlsx_bytes).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "results.xlsx").write_bytes(xlsx_bytes)
            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "XLSX binding?", "draft": "OS HR 0.71"})["case_id"]
            imp = engine.dispatch("import_artifact", {"case_id": cid, "path": "results.xlsx"})
            ev_id = imp["evidence"]["evidence_id"]
            ext = engine.dispatch("extract_effects", {"case_id": cid, "evidence_id": ev_id, "sheet_name": "Effects"})
            rec = ext["effect_records"][0]
            self.assertEqual(rec["artifact_binding"]["format"], "xlsx")
            self.assertEqual(rec["artifact_binding"]["sheet"], "Effects")
            self.assertEqual(rec["artifact_binding"]["source_sha256"], sha)
            claim = _base_claim([ev_id], effect_records=[{**rec, "endpoint_role": "primary", "direction": "benefit", "beneficial_if": "below_null"}])
            engine.dispatch("set_ledger", {"case_id": cid, "claims": [claim]})
            verified = engine.dispatch("verify", {"case_id": cid})
            self.assertTrue(verified["effect_checks"]["C1"]["checks"][0]["anchored"])


if __name__ == "__main__":
    unittest.main()
