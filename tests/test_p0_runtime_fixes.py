"""Regression tests for P0 runtime fixes across triggers.py and symmetry_audit.py."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS
from parrhesia.contracts import CHECK_NAMES, ContractError
from parrhesia.core import Engine
from parrhesia.symmetry_audit import _has_failed_check, audit_underclaim_and_abstention
from parrhesia.triggers import (
    _context_from_claim,
    _derive_evidence_verifications,
    _normalize_design_packages,
    check_self_triggering_reversals,
    evaluate_single_trigger,
)
from test_longitudinal_calibration import _adjudicate_case, _decision, _v2_claim


def _evidence_dict(
    ev_id: str,
    text: str,
    *,
    quote: str | None = None,
    kind: str = "observation",
    provenance: str = "observed",
) -> dict:
    return {
        "evidence_id": ev_id,
        "kind": kind,
        "provenance": provenance,
        "source_text_status": "complete",
        "source_text": text,
        "quote": quote if quote is not None else text,
        "location": "Table 1",
    }


def _causal_basis(
    ev_id: str,
    *,
    design_family: str = "randomized",
    assessment_status: str = "pass",
    assumption_status: str = "pass",
    sensitivity_status: str = "pass",
    necessity_status: str = "not_applicable",
    sufficiency_status: str = "not_applicable",
) -> dict:
    def _rec(status: str, label: str) -> dict:
        return {
            "status": status,
            "reason": f"{label} evaluated from registered trial protocol ({ev_id})",
            "evidence_ids": [ev_id] if status == "pass" else [],
        }

    return {
        "design_family": design_family,
        "estimand": {
            "population": "Adult ICU trial population",
            "contrast": "Active regimen vs standard care",
            "outcome": "90-day mortality",
            "time_horizon": "90 days post-randomization",
            "summary": "Hazard ratio with 95% CI",
            "intercurrent_events": "Treatment policy strategy",
        },
        "assumptions": [{"name": "randomization_exchangeability", **_rec(assumption_status, "Exchangeability")}],
        "falsification_sensitivity": [
            {"name": "tipping_point_sensitivity", **_rec(sensitivity_status, "Sensitivity analysis")}
        ],
        "assessment": _rec(assessment_status, "Causal identification"),
        "necessity_test": _rec(necessity_status, "Necessity test"),
        "sufficiency_test": _rec(sufficiency_status, "Sufficiency test"),
    }


class Bug1DesignPackageTriggerTests(unittest.TestCase):
    def test_normalize_design_packages_handles_v2_list_3key_and_legacy_dicts(self):
        v2_list = [
            {
                "family": "observational",
                "checks": {
                    "confounding_selection": {"status": "fail", "reason": "Unmeasured bias", "evidence_ids": ["ev1"]},
                    "measurement": {"status": "pass", "reason": "Validated instrument", "evidence_ids": ["ev1"]},
                },
            },
            {
                "family": "prediction",
                "checks": {
                    "splits_leakage": {"status": "pass", "reason": "Strict temporal split", "evidence_ids": ["ev1"]},
                },
                "extra_metadata": "must_not_crash_dict_coercion",
            },
        ]
        norm_v2 = _normalize_design_packages(v2_list)
        self.assertEqual(set(norm_v2.keys()), {"observational", "prediction"})
        self.assertEqual(norm_v2["observational"]["confounding_selection"]["status"], "fail")
        self.assertEqual(norm_v2["prediction"]["splits_leakage"]["status"], "pass")

        legacy_flat = {
            "observational": {
                "confounding_selection": {"status": "fail", "reason": "Legacy dict check"},
            }
        }
        norm_flat = _normalize_design_packages(legacy_flat)
        self.assertEqual(norm_flat["observational"]["confounding_selection"]["status"], "fail")

        legacy_wrapped = {
            "observational": {
                "family": "observational",
                "checks": {
                    "confounding_selection": {"status": "pass", "reason": "Wrapped legacy dict"},
                },
            }
        }
        norm_wrapped = _normalize_design_packages(legacy_wrapped)
        self.assertEqual(norm_wrapped["observational"]["confounding_selection"]["status"], "pass")

        self.assertEqual(_normalize_design_packages(None), {})
        self.assertEqual(_normalize_design_packages([]), {})
        self.assertEqual(_normalize_design_packages(["malformed", {"family": "observational"}]), {})

    def test_direct_trigger_evaluation_accepts_v2_design_packages_list(self):
        trig = {
            "id": "T_CONF",
            "description": "Confounding check fails",
            "kind": "check_status",
            "target_check": "observational.confounding_selection",
            "target_statuses": ["fail", "unknown"],
            "target_verdict": "unsupported",
        }
        claim = _v2_claim("C1", ["ev1"])
        ctx_pass = _context_from_claim(claim)
        res_pass = evaluate_single_trigger(trig, ctx_pass)
        self.assertEqual(res_pass["status"], "unfired")
        self.assertFalse(res_pass["fired"])
        self.assertEqual(res_pass["observed_value"], "pass")

        # Direct call with raw v2 list in context["design_packages"]
        fail_pkgs = deepcopy(claim["design_packages"])
        fail_pkgs[0]["checks"]["confounding_selection"] = {
            "status": "fail",
            "reason": "Severe selection bias uncovered in sensitivity check",
            "evidence_ids": ["ev1"],
        }
        res_fail = evaluate_single_trigger(trig, {"design_packages": fail_pkgs})
        self.assertEqual(res_fail["status"], "fired")
        self.assertTrue(res_fail["fired"])
        self.assertEqual(res_fail["observed_value"], "fail")
        self.assertEqual(res_fail["matched_source"], "observational.confounding_selection")

        # Placeholder reason on "pass" coerces to "unknown" and fires
        placeholder_pkgs = deepcopy(claim["design_packages"])
        placeholder_pkgs[0]["checks"]["confounding_selection"] = {
            "status": "pass",
            "reason": "TBD",
            "evidence_ids": ["ev1"],
        }
        res_placeholder = evaluate_single_trigger(trig, {"design_packages": placeholder_pkgs})
        self.assertEqual(res_placeholder["status"], "fired")
        self.assertEqual(res_placeholder["observed_value"], "unknown")

    def test_e2e_v2_design_package_triggers_self_block_and_evaluate_all_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)

            # 1. Self-triggering <family>.<key> on non-required unknown check blocks adjudication
            (root / "self_dp.txt").write_text(
                "Observational cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n", encoding="utf-8"
            )
            scid = engine.dispatch(
                "create_case",
                {"question": "Self-trigger design check?", "draft": "Draft", "writer_context_id": "writer"},
            )["case_id"]
            sev = engine.dispatch(
                "register_evidence",
                {
                    "case_id": scid,
                    "path": "self_dp.txt",
                    "provenance": "observed",
                    "kind": "observation",
                    "quote": "Observational cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).",
                    "location": "Table 1",
                },
            )["evidence_id"]
            # For association x adjusted (tier 2), observational.robustness is not required by ceiling,
            # so marking it not_applicable passes validate_mechanical, letting check_self_triggering_reversals run.
            self_claim = _v2_claim(
                "C1",
                [sev],
                reversal_triggers=[
                    {
                        "id": "T_DP_SELF",
                        "description": "Downgrade if observational robustness check is not_applicable or fail",
                        "kind": "check_status",
                        "target_check": "observational.robustness",
                        "target_statuses": ["not_applicable", "fail"],
                        "target_verdict": "insufficient_evidence",
                    }
                ],
            )
            self_claim["design_packages"][0]["checks"]["robustness"] = {
                "status": "not_applicable",
                "reason": "Sensitivity robustness check deferred for this tier-2 adjusted analysis",
                "evidence_ids": [],
            }
            engine.dispatch("set_ledger", {"case_id": scid, "claims": [self_claim]})
            fr = engine.dispatch("freeze", {"case_id": scid})
            for role in ("overclaim", "underclaim"):
                pkt = engine.dispatch("review_packet", {"case_id": scid, "role": role})
                engine.dispatch(
                    "submit_review",
                    {
                        "case_id": scid,
                        "role": role,
                        "packet_id": pkt["packet_id"],
                        "input_digest": fr["input_digest"],
                        "reviewer": {"context_id": role, "model": "fixture"},
                        "covered_claim_ids": ["C1"],
                        "claim_stances": [
                            {"claim_id": "C1", "stance": "supported", "rationale": "Anchored", "evidence_ids": [sev]}
                        ],
                        "unread_evidence_ids": [],
                        "findings": [],
                    },
                )
            apkt = engine.dispatch("adjudication_packet", {"case_id": scid})
            with self.assertRaises(ContractError) as cm:
                engine.dispatch(
                    "submit_adjudication",
                    {
                        "case_id": scid,
                        "adjudication_id": apkt["adjudication_id"],
                        "input_digest": apkt["input_digest"],
                        "adjudicator": {"context_id": "adj", "model": "fixture"},
                        "unread_evidence_ids": [],
                        "dispositions": [],
                        "decisions": [_decision(self_claim, [sev], verdict="supported")],
                    },
                )
            self.assertEqual(cm.exception.code, "self_triggering_reversal_condition")

            # 2. Clean v2 case with observational.confounding_selection trigger evaluated in live, obs, and against_case
            c1_id, _, _ = _adjudicate_case(
                engine,
                root,
                filename="c1.txt",
                file_text="Primary cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).\n",
                quote="Primary cohort HR 0.71 (95% CI 0.55 to 0.91, p=0.004).",
                question="Does exposure lower hazard?",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1",
                        [ev],
                        reversal_triggers=[
                            {
                                "id": "T_CONF_FAIL",
                                "description": "Reverse if observational confounding check fails",
                                "kind": "check_status",
                                "target_check": "observational.confounding_selection",
                                "target_statuses": ["fail"],
                                "target_verdict": "unsupported",
                            }
                        ],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported")],
            )
            live_eval = engine.evaluate_triggers(c1_id)
            t_live = live_eval["claim_evaluations"][0]["triggers"][0]
            self.assertEqual(t_live["status"], "unfired")
            self.assertEqual(t_live["observed_value"], "pass")

            # Observations mode: v2 list format
            obs_v2 = engine.evaluate_triggers(
                c1_id,
                observations={
                    "design_packages": [
                        {
                            "family": "observational",
                            "checks": {
                                "confounding_selection": {
                                    "status": "fail",
                                    "reason": "Reanalysis found unmeasured baseline severity confounding",
                                    "evidence_ids": [],
                                }
                            },
                        }
                    ]
                },
            )
            self.assertTrue(obs_v2["claim_evaluations"][0]["triggers"][0]["fired"])
            self.assertEqual(obs_v2["claim_evaluations"][0]["triggers"][0]["observed_value"], "fail")

            # Observations mode: legacy dict format
            obs_legacy = engine.evaluate_triggers(
                c1_id,
                observations={
                    "design_packages": {
                        "observational": {
                            "confounding_selection": {"status": "fail", "reason": "Legacy dict confounding failure"}
                        }
                    }
                },
            )
            self.assertTrue(obs_legacy["claim_evaluations"][0]["triggers"][0]["fired"])

            # Against-case mode: downstream v2 case with failing observational.confounding_selection
            def _failing_downstream_claim(ev):
                cl = _v2_claim(
                    "C1",
                    [ev],
                    prior_claim_links=[
                        {
                            "prior_case_id": c1_id,
                            "prior_claim_id": "C1",
                            "relation": "reanalysis",
                            "reason": "Reanalysis identified unmeasured baseline confounding.",
                        }
                    ],
                )
                cl["design_packages"][0]["checks"]["confounding_selection"] = {
                    "status": "fail",
                    "reason": "Unmeasured indication bias invalidates adjusted estimate",
                    "evidence_ids": [ev],
                }
                return [cl]

            c2_id, _, _ = _adjudicate_case(
                engine,
                root,
                filename="c2.txt",
                file_text="Reanalysis cohort HR 0.94 (95% CI 0.72 to 1.23, p=0.64).\n",
                quote="Reanalysis cohort HR 0.94 (95% CI 0.72 to 1.23, p=0.64).",
                question="Reanalysis of confounding?",
                prior_case_ids=[c1_id],
                case_relation="reanalysis",
                claims_fn=lambda ev: [
                    {
                        **_failing_downstream_claim(ev)[0],
                        "prior_claim_links": [
                            {
                                "prior_case_id": c1_id,
                                "prior_claim_id": "C1",
                                "relation": "reverses",
                                "triggered_reversal_id": "T_CONF_FAIL",
                                "reason": "Reanalysis found failed confounding_selection, firing T_CONF_FAIL.",
                            }
                        ],
                    }
                ],
                decisions_fn=lambda claims, ev: [
                    {
                        **_decision(
                            claims[0],
                            [ev],
                            verdict="unsupported",
                            revised_text="Adjusted association is unsupported after confounding check failure.",
                        ),
                        "evidence_level": "unassessed",
                    }
                ],
                stances_fn=lambda clm: "unsupported",
            )
            ag_eval = engine.evaluate_triggers(c1_id, against_case_id=c2_id)
            t_ag = ag_eval["claim_evaluations"][0]["triggers"][0]
            self.assertTrue(t_ag["fired"])
            self.assertEqual(t_ag["status"], "fired")
            self.assertEqual(t_ag["observed_value"], "fail")


class Bug2LexicalBoundaryInTriggersTests(unittest.TestCase):
    def test_benign_baseline_balance_and_kind_caveat_prose_never_trigger_hard_contract_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)

            # 1. Baseline-balance null sentence + positive primary outcome
            baseline_text = (
                "Baseline age showed no significant difference between arms (p = 0.82). "
                "Primary endpoint relapse fell with HR = 0.70 (95% CI 0.54 to 0.91, p = 0.008)."
            )
            quote = "Primary endpoint relapse fell with HR = 0.70 (95% CI 0.54 to 0.91, p = 0.008)."
            cid, _, case = _adjudicate_case(
                engine,
                root,
                filename="baseline_balance.txt",
                file_text=baseline_text + "\n",
                quote=quote,
                question="Does therapy reduce primary relapse?",
                claims_fn=lambda ev: [
                    _v2_claim(
                        "C1",
                        [ev],
                        text="Therapy lowers primary relapse (HR = 0.70, 95% CI 0.54 to 0.91, p = 0.008).",
                        effect={"estimate": "HR = 0.70", "uncertainty": "95% CI 0.54 to 0.91, p = 0.008"},
                        reversal_triggers=[
                            {
                                "id": "TR_EVID",
                                "description": "Reverse if evidence is blocked or structurally contradicts claim",
                                "kind": "evidence_status",
                                "trigger_on": ["contradicts", "blocked"],
                                "target_verdict": "unsupported",
                            }
                        ],
                    )
                ],
                decisions_fn=lambda claims, ev: [_decision(claims[0], [ev], verdict="supported")],
            )
            self.assertEqual(case["state"], "adjudicated")
            trig_eval = engine.evaluate_triggers(cid)
            t0 = trig_eval["claim_evaluations"][0]["triggers"][0]
            self.assertFalse(t0["fired"])
            self.assertEqual(t0["status"], "unfired")

            # 2. Free-text study-design caveat prose ("internal validation only" in background)
            # must remain a non-blocking lexical advisory, NOT a hard self_triggering_reversal_condition.
            caveat_text = (
                "Earlier pilot work relied on internal validation only. "
                "Here, independent external cohort validation (N=420) achieved AUROC = 0.84 (95% CI 0.78 to 0.90)."
            )
            (root / "caveat_ext.txt").write_text(caveat_text + "\n", encoding="utf-8")
            cid2 = engine.dispatch(
                "create_case",
                {"question": "External AUROC?", "draft": "Draft", "writer_context_id": "writer-2"},
            )["case_id"]
            ev2 = engine.dispatch(
                "register_evidence",
                {
                    "case_id": cid2,
                    "path": "caveat_ext.txt",
                    "provenance": "observed",
                    "kind": "prediction_external",
                    "quote": "independent external cohort validation (N=420) achieved AUROC = 0.84 (95% CI 0.78 to 0.90).",
                    "location": "Table 2",
                },
            )["evidence_id"]
            pred_claim = _v2_claim(
                "C1",
                [ev2],
                text="Model achieves externally validated AUROC = 0.84 (95% CI 0.78 to 0.90).",
                claim_type="prediction",
                evidence_level="externally_validated",
                effect={"estimate": "AUROC = 0.84", "uncertainty": "95% CI 0.78 to 0.90"},
                reversal_triggers=[
                    {
                        "id": "TR_EVID_2",
                        "description": "Reverse if evidence structurally contradicts claim",
                        "kind": "evidence_status",
                        "trigger_on": ["contradicts", "blocked"],
                        "target_verdict": "unsupported",
                    }
                ],
            )
            pred_claim["design_packages"] = [
                {
                    "family": "prediction",
                    "checks": {
                        k: {"status": "pass", "reason": "Verified prediction criterion", "evidence_ids": [ev2]}
                        for k in DESIGN_FIELDS["prediction"]
                    },
                }
            ]
            # Direct check_self_triggering_reversals with explicit lexical kind-mismatch prose
            ev_kind_mismatch_prose = _evidence_dict(
                ev2,
                "Internal validation only with no external cohort tested; AUROC = 0.84 (95% CI 0.78 to 0.90).",
                kind="prediction_external",
            )
            check_self_triggering_reversals(
                pred_claim,
                _decision(pred_claim, [ev2], verdict="supported"),
                {ev2: ev_kind_mismatch_prose},
            )

    def test_structured_contradictions_still_fire_evidence_status_triggers(self):
        base_ev = _evidence_dict(
            "ev1",
            "Primary cohort mortality HR = 0.71 (95% CI 0.55 to 0.91, p = 0.004).",
        )
        trig_any = {
            "id": "TR_ANY",
            "description": "Any contradicting evidence",
            "kind": "evidence_status",
            "trigger_on": ["contradicts"],
            "target_verdict": "unsupported",
        }
        trig_targeted = {
            **trig_any,
            "id": "TR_TARGET",
            "evidence_id": "ev1",
        }

        # 1. Explicit verification status="contradicts"
        ver_map = _derive_evidence_verifications(
            {"ev1": base_ev},
            verification={"evidence": [{"evidence_id": "ev1", "status": "contradicts"}]},
        )
        self.assertTrue(ver_map["ev1"]["contradicts"])
        res_ver = evaluate_single_trigger(trig_targeted, {"evidence_verifications": ver_map})
        self.assertTrue(res_ver["fired"])
        self.assertEqual(res_ver["matched_source"], "ev1")

        # 2. Structural contradicting citation provenance card (English & Chinese support_relation)
        for rel in ("contradicts", "反对"):
            cl = _v2_claim("C1", ["ev1"], reversal_triggers=[trig_any, trig_targeted])
            cl["provenance_cards"]["citation"] = [
                {
                    "id": "CIT1",
                    "status": "checked",
                    "reason": "Primary citation directly opposes claim",
                    "evidence_ids": ["ev1"],
                    "details": {
                        "source": "trial.txt",
                        "locator": "Table 2",
                        "claim_link": "C1",
                        "support_relation": rel,
                        "read_extent": "complete",
                    },
                }
            ]
            ctx = _context_from_claim(cl, evidence_by_id={"ev1": base_ev})
            self.assertTrue(ctx["claim_has_contradiction"])
            self.assertTrue(ctx["evidence_verifications"]["ev1"]["contradicts"])
            self.assertTrue(evaluate_single_trigger(trig_any, ctx)["fired"])
            self.assertTrue(evaluate_single_trigger(trig_targeted, ctx)["fired"])
            with self.assertRaises(ContractError) as cm:
                check_self_triggering_reversals(cl, _decision(cl, ["ev1"], verdict="supported"), {"ev1": base_ev})
            self.assertEqual(cm.exception.code, "self_triggering_reversal_condition")

        # 3. Disclosed exploratory_failed execution fork alongside passing primary run must NOT set contradicts
        cl_fork = _v2_claim("C1", ["ev1"], reversal_triggers=[trig_any, trig_targeted])
        cl_fork["provenance_cards"]["execution"] = [
            {
                "id": "EX_PRIM",
                "status": "checked",
                "reason": "Primary execution succeeded with exit status 0",
                "evidence_ids": ["ev1"],
                "details": {
                    **{k: "primary-val" for k in CARD_FIELDS["execution"]},
                    "exit_status": "0",
                    "fork_role": "primary",
                },
            },
            {
                "id": "EX_EXP_FAIL",
                "status": "failed",
                "reason": "Disclosed exploratory sensitivity run diverged on alternate kernel",
                "evidence_ids": ["ev1"],
                "details": {
                    **{k: "exp-val" for k in CARD_FIELDS["execution"]},
                    "exit_status": "1",
                    "fork_role": "exploratory_failed",
                },
            },
        ]
        ctx_fork = _context_from_claim(cl_fork, evidence_by_id={"ev1": base_ev})
        self.assertFalse(ctx_fork["claim_has_contradiction"])
        self.assertFalse(ctx_fork["evidence_verifications"]["ev1"]["contradicts"])
        self.assertFalse(evaluate_single_trigger(trig_any, ctx_fork)["fired"])

        # 4. Integrity-blocked evidence still fires trigger_on=["blocked"]
        blocked_ev = {**base_ev, "snapshot_status": "mismatch"}
        trig_blocked = {
            "id": "TR_BLK",
            "description": "Tampered evidence blocks claim",
            "kind": "evidence_status",
            "trigger_on": ["blocked"],
            "target_verdict": "insufficient_evidence",
        }
        ctx_blk = _context_from_claim(_v2_claim("C1", ["ev1"]), evidence_by_id={"ev1": blocked_ev})
        res_blk = evaluate_single_trigger(trig_blocked, ctx_blk)
        self.assertTrue(res_blk["fired"])
        self.assertEqual(res_blk["observed_value"], "blocked")


class Bug3SymmetryAuditV2ChecksTests(unittest.TestCase):
    def _clean_claim_and_ev(self):
        ev = _evidence_dict("ev1", "Cohort study HR = 0.71 (95% CI 0.55 to 0.91, p = 0.004).")
        claim = _v2_claim(
            "C1",
            ["ev1"],
            text="Cohort study shows adjusted HR = 0.71 (95% CI 0.55 to 0.91).",
            effect={"estimate": "HR = 0.71", "uncertainty": "95% CI 0.55 to 0.91"},
        )
        return claim, ev

    def test_v2_design_stat_and_causal_failures_suppress_spurious_unsupported_flag(self):
        claim, ev = self._clean_claim_and_ev()
        unsup_dec = _decision(claim, ["ev1"], verdict="unsupported", revised_text="Claim unsupported due to check fail.")

        # Baseline control: with all passing checks, unsupported MUST fire unsupported_without_counterevidence
        base_audit = audit_underclaim_and_abstention([unsup_dec], [claim], [ev])
        self.assertIn("unsupported_without_counterevidence", {f["hook_code"] for f in base_audit["flags"]})

        # 1. v2 design_packages failure
        cl_dp = deepcopy(claim)
        cl_dp["design_packages"][0]["checks"]["confounding_selection"]["status"] = "fail"
        self.assertTrue(_has_failed_check(cl_dp))
        self.assertEqual(audit_underclaim_and_abstention([unsup_dec], [cl_dp], [ev])["flag_count"], 0)

        # 2. v2 statistical_report failure
        cl_stat = deepcopy(claim)
        cl_stat["statistical_report"]["model_assumptions"]["status"] = "fail"
        self.assertTrue(_has_failed_check(cl_stat))
        self.assertEqual(audit_underclaim_and_abstention([unsup_dec], [cl_stat], [ev])["flag_count"], 0)

        # 3. v2 causal_basis failures (assessment, assumptions, falsification_sensitivity)
        for field_case in ("assessment", "assumptions", "falsification_sensitivity"):
            cl_cb = deepcopy(claim)
            cl_cb["claim_type"] = "causal_effect"
            cl_cb["evidence_level"] = "sensitivity_supported"
            cl_cb["design_packages"] = [
                {
                    "family": "randomized",
                    "checks": {
                        k: {"status": "pass", "reason": "Verified randomized criterion", "evidence_ids": ["ev1"]}
                        for k in DESIGN_FIELDS["randomized"]
                    },
                }
            ]
            cl_cb["causal_basis"] = _causal_basis(
                "ev1",
                assessment_status="fail" if field_case == "assessment" else "pass",
                assumption_status="fail" if field_case == "assumptions" else "pass",
                sensitivity_status="fail" if field_case == "falsification_sensitivity" else "pass",
            )
            dec_cb = _decision(cl_cb, ["ev1"], verdict="unsupported", revised_text="Causal claim unsupported.")
            self.assertTrue(_has_failed_check(cl_cb), msg=field_case)
            self.assertEqual(audit_underclaim_and_abstention([dec_cb], [cl_cb], [ev])["flag_count"], 0, msg=field_case)

        # 4. necessity_test vs sufficiency_test isolation on causal_basis
        cl_nec_fail = deepcopy(claim)
        cl_nec_fail["claim_type"] = "necessity"
        cl_nec_fail["causal_basis"] = _causal_basis("ev1", necessity_status="fail", sufficiency_status="not_applicable")
        self.assertTrue(_has_failed_check(cl_nec_fail))

        # A necessity claim where sufficiency_test="fail" (necessary, not sufficient) is NOT a failed necessity check
        cl_nec_only = deepcopy(claim)
        cl_nec_only["claim_type"] = "necessity"
        cl_nec_only["causal_basis"] = _causal_basis("ev1", necessity_status="pass", sufficiency_status="fail")
        self.assertFalse(_has_failed_check(cl_nec_only))

        cl_suf_fail = deepcopy(claim)
        cl_suf_fail["claim_type"] = "sufficiency"
        cl_suf_fail["causal_basis"] = _causal_basis("ev1", necessity_status="not_applicable", sufficiency_status="fail")
        self.assertTrue(_has_failed_check(cl_suf_fail))

        # 5. Partial claim with checks=None must still inspect design_packages and statistical_report
        cl_partial = {
            "id": "C1",
            "checks": None,
            "design_packages": [{"family": "observational", "checks": {"measurement": {"status": "fail", "reason": "Bad assay"}}}],
        }
        self.assertTrue(_has_failed_check(cl_partial))

        # 6. Legacy checks["design"] / checks["statistics"] remain supported
        cl_legacy = {"id": "C1", "checks": {"design": {"confounding": {"status": "fail", "reason": "Legacy fail"}}}}
        self.assertTrue(_has_failed_check(cl_legacy))

    def test_e2e_v2_failed_design_check_unsupported_has_zero_spurious_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            _, _, case = _adjudicate_case(
                engine,
                root,
                filename="fail_dp.txt",
                file_text="Cohort HR = 0.71 (95% CI 0.55 to 0.91, p = 0.004).\n",
                quote="Cohort HR = 0.71 (95% CI 0.55 to 0.91, p = 0.004).",
                question="Does exposure reduce risk despite confounding failure?",
                claims_fn=lambda ev: [
                    {
                        **_v2_claim("C1", [ev]),
                        "design_packages": [
                            {
                                "family": "observational",
                                "checks": {
                                    k: {
                                        "status": "fail" if k == "confounding_selection" else "pass",
                                        "reason": "Severe unmeasured confounding invalidates estimate"
                                        if k == "confounding_selection"
                                        else "Verified observational criterion in source",
                                        "evidence_ids": [ev],
                                    }
                                    for k in DESIGN_FIELDS["observational"]
                                },
                            }
                        ],
                    }
                ],
                decisions_fn=lambda claims, ev: [
                    {
                        **_decision(
                            claims[0],
                            [ev],
                            verdict="unsupported",
                            revised_text="Unsupported due to failed confounding_selection check.",
                        ),
                        "evidence_level": "unassessed",
                    }
                ],
                stances_fn=lambda clm: "unsupported",
            )
            self.assertEqual(case["symmetry_audit"]["flag_count"], 0)


class Bug4ConditionalPartiallySupportedCalibrationTests(unittest.TestCase):
    def _clean_assoc_claim_and_ev(self):
        ev = _evidence_dict(
            "ev1",
            "Multivariable adult cohort (N=1,200): exposure associated with HR = 0.71 (95% CI 0.55 to 0.91, p = 0.004).",
        )
        claim = _v2_claim(
            "C1",
            ["ev1"],
            text="Exposure is associated with lower 12-month hazard (HR = 0.71, 95% CI 0.55 to 0.91).",
            claim_type="association",
            evidence_level="adjusted",
            scope="Adult inpatient cohort over 12 months",
            effect={"estimate": "HR = 0.71", "uncertainty": "95% CI 0.55 to 0.91"},
        )
        return claim, ev

    def test_clean_conditional_partially_supported_does_not_fire_unjustified_downgrade(self):
        claim, ev = self._clean_assoc_claim_and_ev()

        clean_conditions = [
            "Holds among studied adult inpatients over 12 months under measured multivariable covariate adjustment; unmeasured confounding is not excluded.",
            "Holds in adult ICU cohort under measured covariate adjustment; subgroup replication pending external validation.",
            "仅适用于本队列已测协变量校正后的成人住院患者，未测混杂尚未排除。",
        ]
        for cond in clean_conditions:
            dec = _decision(claim, ["ev1"], verdict="partially_supported", condition=cond)
            audit = audit_underclaim_and_abstention([dec], [claim], [ev])
            self.assertEqual(audit["flag_count"], 0, msg=f"False flag for clean condition: {cond}")

        # Clean conditional partially_supported across synthesis, theory, qualitative, engineering archetypes
        domain_cases = [
            (
                "synthesis",
                "synthesized_with_uncertainty",
                "evidence_synthesis",
                "empirical",
                "systematic_review",
                "Systematic review across 11 inpatient cohorts (N=3,410): pooled OR = 0.76 (95% CI 0.64 to 0.90), I^2 = 58%.",
                "Systematic review conditionally supports lower complication odds (pooled OR = 0.76, 95% CI 0.64 to 0.90).",
                {"estimate": "OR = 0.76", "uncertainty": "95% CI 0.64 to 0.90"},
                "Holds across inpatient medical cohorts with documented heterogeneity (I^2 = 58%); outpatient generalization requires separate verification.",
            ),
            (
                "theory",
                "independently_checked",
                "theory",
                "formal",
                "theoretical_proof",
                "Independent Lean 4 derivation of Theorem T4 confirms contraction factor 0.85 under strict convexity.",
                "Theorem T4 conditionally holds in finite-dimensional strictly convex spaces with contraction factor 0.85.",
                {"estimate": "0.85", "uncertainty": "exact under strict convexity"},
                "Holds in finite-dimensional Hilbert spaces under strict convexity and zero gradient bias; non-convex objectives fall outside the proof boundary.",
            ),
            (
                "qualitative",
                "triangulated",
                "qualitative",
                "empirical",
                "qualitative_material",
                "Triangulated fieldwork in two urban emergency departments (N=34 interviews): duplicate triage screening delays intake handoffs.",
                "Triangulated qualitative fieldwork conditionally supports that duplicate triage screening creates handoff delays.",
                {"estimate": "UNKNOWN", "uncertainty": "34 interviews"},
                "Transferable to urban safety-net emergency departments with comparable triage staffing ratios; rural settings remain unexamined.",
            ),
            (
                "engineering",
                "user_impact",
                None,
                "empirical",
                "user_outcome",
                "14-day US enterprise tenant telemetry (N=12,400 sessions): task completion time delta = -18.5% (95% CI -22.1% to -14.9%).",
                "Post-deployment telemetry conditionally supports lower task completion time (delta = -18.5%, 95% CI -22.1% to -14.9%).",
                {"estimate": "-18.5%", "uncertainty": "95% CI -22.1% to -14.9%"},
                "Holds across 12,400 active sessions in the 14-day US enterprise tenant cohort under steady telemetry; low-bandwidth mobile clients require separate rollout evaluation.",
            ),
        ]
        for ctype, elevel, fam, basis, ev_kind, ev_txt, cl_txt, eff, cond in domain_cases:
            ev_d = _evidence_dict("ev1", ev_txt, kind=ev_kind)
            cl_d = _v2_claim(
                "C1",
                ["ev1"],
                text=cl_txt,
                claim_type=ctype,
                evidence_level=elevel,
                effect=eff,
            )
            cl_d["claim_basis"] = basis
            cl_d["design_packages"] = (
                [
                    {
                        "family": fam,
                        "checks": {
                            k: {"status": "pass", "reason": f"Verified {fam}.{k} criterion", "evidence_ids": ["ev1"]}
                            for k in DESIGN_FIELDS[fam]
                        },
                    }
                ]
                if fam
                else []
            )
            dec_d = _decision(cl_d, ["ev1"], verdict="partially_supported", condition=cond)
            audit_d = audit_underclaim_and_abstention([dec_d], [cl_d], [ev_d])
            self.assertEqual(audit_d["flag_count"], 0, msg=f"False flag on clean {ctype} partially_supported")

        # Full end-to-end Engine flow for clean conditional partially_supported (reviewers + adjudicator aligned)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            (root / "cond.txt").write_text(ev["source_text"] + "\n", encoding="utf-8")
            cid = engine.dispatch(
                "create_case",
                {"question": "Conditional adjusted association?", "draft": claim["text"], "writer_context_id": "w"},
            )["case_id"]
            ev_id = engine.dispatch(
                "register_evidence",
                {
                    "case_id": cid,
                    "path": "cond.txt",
                    "provenance": "observed",
                    "kind": "observation",
                    "quote": ev["quote"],
                    "location": "Table 1",
                },
            )["evidence_id"]
            cl_e2e = _v2_claim(
                "C1",
                [ev_id],
                text=claim["text"],
                claim_type="association",
                evidence_level="adjusted",
                scope=claim["scope"],
                effect=claim["effect"],
            )
            engine.dispatch("set_ledger", {"case_id": cid, "claims": [cl_e2e]})
            fr = engine.dispatch("freeze", {"case_id": cid})
            cond = "Holds in the studied 12-month adult inpatient cohort given measured baseline covariates; residual unmeasured confounding cannot be ruled out."
            for role in ("overclaim", "underclaim"):
                pkt = engine.dispatch("review_packet", {"case_id": cid, "role": role})
                rev = engine.dispatch(
                    "submit_review",
                    {
                        "case_id": cid,
                        "role": role,
                        "packet_id": pkt["packet_id"],
                        "input_digest": fr["input_digest"],
                        "reviewer": {"context_id": role, "model": "fixture"},
                        "covered_claim_ids": ["C1"],
                        "claim_stances": [
                            {
                                "claim_id": "C1",
                                "stance": "partially_supported",
                                "condition": cond,
                                "rationale": "Adjusted observational estimate holds conditionally on measured covariates.",
                                "evidence_ids": [ev_id],
                            }
                        ],
                        "unread_evidence_ids": [],
                        "findings": [],
                    },
                )
                self.assertEqual(rev["symmetry_audit"]["flag_count"], 0)
            apkt = engine.dispatch("adjudication_packet", {"case_id": cid})
            adj = engine.dispatch(
                "submit_adjudication",
                {
                    "case_id": cid,
                    "adjudication_id": apkt["adjudication_id"],
                    "input_digest": apkt["input_digest"],
                    "adjudicator": {"context_id": "adj", "model": "fixture"},
                    "unread_evidence_ids": [],
                    "dispositions": [],
                    "decisions": [_decision(cl_e2e, [ev_id], verdict="partially_supported", condition=cond)],
                },
            )
            self.assertEqual(adj["symmetry_audit"]["flag_count"], 0)

    def test_genuine_downgrades_still_fire_possible_unjustified_downgrade(self):
        claim, ev = self._clean_assoc_claim_and_ev()
        claim["evidence_level"] = "robust_association"

        # 1. Level downgrade (robust_association -> adjusted) with partially_supported
        dec_lvl_partial = _decision(
            claim,
            ["ev1"],
            verdict="partially_supported",
            condition="Holds within studied adult cohort under covariate adjustment.",
        )
        dec_lvl_partial["evidence_level"] = "adjusted"
        flags_1 = {f["hook_code"] for f in audit_underclaim_and_abstention([dec_lvl_partial], [claim], [ev])["flags"]}
        self.assertIn("possible_unjustified_downgrade", flags_1)

        # 2. Level downgrade (robust_association -> adjusted) while keeping verdict="supported"
        dec_lvl_supp = _decision(claim, ["ev1"], verdict="supported")
        dec_lvl_supp["evidence_level"] = "adjusted"
        flags_2 = {f["hook_code"] for f in audit_underclaim_and_abstention([dec_lvl_supp], [claim], [ev])["flags"]}
        self.assertIn("possible_unjustified_downgrade", flags_2)

        # 3. Generic preliminary / pending-confirmation deferral conditions
        for bad_cond in (
            "Preliminary scope only pending broader multi-center confirmation.",
            "Pending further independent trials.",
            "初步结果，尚待进一步验证。",
            "For reference only; cannot draw definitive conclusions.",
            "",
            "UNKNOWN",
        ):
            dec_defer = _decision(claim, ["ev1"], verdict="partially_supported", condition=bad_cond)
            flags_defer = {f["hook_code"] for f in audit_underclaim_and_abstention([dec_defer], [claim], [ev])["flags"]}
            self.assertIn("possible_unjustified_downgrade", flags_defer, msg=f"Missed downgrade for condition={bad_cond!r}")

        # 4. Unilateral adjudicator downgrade despite unanimous "supported" reviewer stances and 0 overclaim findings
        clean_cond = "Holds among studied adult inpatients under measured baseline covariates."
        dec_unilateral = _decision(claim, ["ev1"], verdict="partially_supported", condition=clean_cond)
        unanimous_reviews = {
            "overclaim": {"claim_stances": [{"claim_id": "C1", "stance": "supported"}], "findings": []},
            "underclaim": {"claim_stances": [{"claim_id": "C1", "stance": "supported"}], "findings": []},
        }
        flags_uni = {
            f["hook_code"]
            for f in audit_underclaim_and_abstention(
                [dec_unilateral], [claim], [ev], findings=unanimous_reviews, dispositions=[]
            )["flags"]
        }
        self.assertIn("possible_unjustified_downgrade", flags_uni)

        # 5. Accepted overclaim finding still suppresses possible_unjustified_downgrade
        overclaim_reviews = {
            "overclaim": {
                "claim_stances": [{"claim_id": "C1", "stance": "partially_supported"}],
                "findings": [{"id": "O1", "claim_id": "C1", "role": "overclaim"}],
            },
            "underclaim": {"claim_stances": [{"claim_id": "C1", "stance": "supported"}], "findings": []},
        }
        dispositions = [{"finding_id": "O1", "claim_id": "C1", "disposition": "accepted"}]
        flags_justified = {
            f["hook_code"]
            for f in audit_underclaim_and_abstention(
                [dec_lvl_partial], [claim], [ev], findings=overclaim_reviews, dispositions=dispositions
            )["flags"]
        }
        self.assertNotIn("possible_unjustified_downgrade", flags_justified)


if __name__ == "__main__":
    unittest.main()
