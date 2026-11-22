"""Regression cases from the 2026-11-14 review; all scientific inputs are fixtures."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import tempfile
import unittest

from parrhesia.calibration import compute_calibration_report
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.effects import validate_effect_records, verify_effect_computations
from parrhesia.triggers import build_claim_graph
from test_longitudinal_calibration import _adjudicate_case, _v2_claim, _decision
from test_record_exec_provenance import _run_cli


def effect(**updates):
    rec = dict(id="E1", endpoint="adverse outcome", endpoint_role="primary", metric="HR",
               estimate=1.5, ci_low=1.2, ci_high=1.8, direction="harm", beneficial_if="below_null", evidence_id="ev1")
    rec.update(updates)
    return rec


def check_effect(rec, quote=None):
    if quote is None:
        quote = "Fixture result: " + " ".join(str(rec[k]) for k in ("estimate", "ci_low", "ci_high", "p_value") if k in rec)
    return verify_effect_computations({"effect_records": [rec]}, {"verdict": "supported", "evidence_ids": ["ev1"]}, {"ev1": {"quote": quote}})


class EffectReviewRegressions(unittest.TestCase):
    def test_supported_harm_and_opposite_claim_control(self):
        self.assertTrue(check_effect(effect(claim_direction="harm"))["checks"][0]["anchored"])
        with self.assertRaises(ContractError) as cm:
            check_effect(effect(claim_direction="benefit"))
        self.assertEqual(cm.exception.code, "effect_direction_mismatch")

    def test_unspecified_proposition_is_unassessed_not_assumed_beneficial(self):
        self.assertEqual(check_effect(effect())["checks"][0]["claim_alignment"], "unassessed")
        # Recording a non-significant result is allowed; it does not establish no effect.
        rec = effect(estimate=1.0, ci_low=0.8, ci_high=1.2, direction="null")
        self.assertEqual(check_effect(rec)["checks"][0]["claim_alignment"], "unassessed")
        rec.update(direction="benefit", claim_direction="benefit", estimate=0.95)
        with self.assertRaises(ContractError):
            check_effect(rec)

    def test_hazard_ratio_and_auc_are_not_event_proportions(self):
        for metric, estimate in (("HR", 0.7), ("OR", 0.7), ("AUROC", 0.8), ("F1", 0.6)):
            rec = effect(metric=metric, estimate=estimate, n=100, events=20)
            rec.pop("ci_low"); rec.pop("ci_high")
            result = validate_effect_records([rec], {"ev1"})
            self.assertEqual(result[0]["estimate"], estimate)

    def test_binary_count_controls_and_unknown_weighting(self):
        rec = effect(metric="proportion", estimate=0.2, n=100, events=20, count_basis="unweighted_binary")
        rec.pop("ci_low"); rec.pop("ci_high")
        validate_effect_records([rec], {"ev1"})
        rec["estimate"] = 0.3
        with self.assertRaises(ContractError) as cm:
            validate_effect_records([rec], {"ev1"})
        self.assertEqual(cm.exception.code, "effect_granularity_mismatch")
        rec["count_basis"] = "other"
        validate_effect_records([rec], {"ev1"})
        rec.pop("count_basis")
        self.assertEqual(check_effect(rec)["checks"][0]["grim_granularity_check"], "unassessed")

    def test_valid_student_t_and_unknown_method_not_rejected_by_wald(self):
        # Samples 99,101: mean=100, SE=1, df=1; exact Cauchy t distribution.
        critical = math.tan(math.pi * (0.975 - 0.5))
        rec = effect(metric="mean_diff", estimate=100, ci_low=100-critical, ci_high=100+critical,
                     p_value=2 * math.atan(0.01) / math.pi, direction="neutral")
        for method in (None, "student_t", "other"):
            item = deepcopy(rec)
            if method:
                item["inference_method"] = method
            self.assertEqual(check_effect(item)["checks"][0]["pvalue_ci_check"], "unassessed")

    def test_declared_wald_mismatch_still_blocked(self):
        rec = effect(metric="mean_diff", estimate=2, ci_low=0.04003601546, ci_high=3.95996398454,
                     p_value=math.erfc(2/math.sqrt(2)), direction="neutral", inference_method="wald")
        self.assertEqual(check_effect(rec)["checks"][0]["pvalue_ci_check"], "pass")
        rec["p_value"] = 0.9
        with self.assertRaises(ContractError) as cm:
            validate_effect_records([rec], {"ev1"})
        self.assertEqual(cm.exception.code, "effect_pvalue_ci_mismatch")

    def test_incidence_rate_is_not_bounded_by_one_or_subject_count(self):
        rec = effect(metric="rate", estimate=2.5, n=100, events=250)
        rec.pop("ci_low"); rec.pop("ci_high")
        validate_effect_records([rec], {"ev1"})

    def test_supported_harm_without_new_metadata_remains_valid(self):
        # This input uses the pre-repair wire contract, isolating the original defect.
        self.assertTrue(check_effect(effect())["checks"][0]["anchored"])

    def test_correct_rejection_of_opposite_proposition_has_no_underclaim_flag(self):
        rec = effect(estimate=0.7, ci_low=0.5, ci_high=0.9, direction="benefit", claim_direction="harm")
        result = verify_effect_computations({"effect_records":[rec]}, {"verdict":"unsupported","evidence_ids":["ev1"]},
            {"ev1":{"quote":"Fixture hazard ratio 0.7 interval 0.5 to 0.9."}})
        self.assertIsNone(result["underclaim_advisory"])


def graph_cases():
    old = dict(case_id="old", question="Old", domain="general", state="adjudicated", created_at="1",
               claims=[dict(id="C1", text="Old claim", claim_type="description", evidence_level="recorded")],
               adjudication={"decisions": [dict(claim_id="C1", verdict="supported")]})
    new = dict(case_id="new", question="New", domain="general", state="draft", created_at="2",
               supersedes_case_id="old", claims=[], human_decisions=[])
    return old, new


class StandingReviewRegressions(unittest.TestCase):
    def standing(self, old, new):
        return next(n for n in build_claim_graph([old, new])["claim_nodes"] if n["node_id"] == "old:C1")["active_standing"]

    def test_case_replacement_requires_effective_positive_adjudication(self):
        old, new = graph_cases()
        for state in ("draft", "frozen", "reviewing", "reviewed", "adjudication_pending"):
            new["state"] = state
            self.assertEqual(self.standing(old, new), "current")
        new.update(state="adjudicated", adjudication={"decisions": [{"claim_id": "C2", "verdict": "supported"}]})
        self.assertEqual(self.standing(old, new), "superseded")
        for verdict in ("unsupported", "insufficient_evidence"):
            new["adjudication"]["decisions"][0]["verdict"] = verdict
            self.assertEqual(self.standing(old, new), "current")

    def test_claim_link_without_adjudication_is_pending_and_holds_do_not_apply(self):
        old, new = graph_cases()
        new.pop("supersedes_case_id")
        new["claims"] = [dict(id="C2", text="New claim", prior_claim_links=[dict(prior_case_id="old", prior_claim_id="C1", relation="supersedes", reason="Fixture correction")])]
        self.assertEqual(self.standing(old, new), "current")
        self.assertEqual(build_claim_graph([old, new])["claim_edges"][0]["status"], "pending")
        new.update(state="adjudicated", adjudication={"decisions": [{"claim_id": "C2", "verdict": "supported"}]})
        self.assertEqual(self.standing(old, new), "superseded")
        new["human_decisions"] = [{"decision": "challenge"}]
        self.assertEqual(self.standing(old, new), "current")
        new["human_decisions"].append({"decision": "accept"})
        self.assertEqual(self.standing(old, new), "superseded")


class CalibrationReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.engine = Engine(self.root)
        z = 1.959963984540054
        self.cid, _, self.before = _adjudicate_case(
            self.engine, self.root, filename="original.txt", file_text=f"Fixture original mean difference 0, interval {-z} to {z}.\n",
            quote=f"Fixture original mean difference 0, interval {-z} to {z}.", question="Fixture original mean?",
            claims_fn=lambda ev: [_v2_claim("C1", [ev], text="Observed mean difference is 0 with reported uncertainty.",
                effect={"estimate": "mean difference 0", "uncertainty": f"interval {-z} to {z}"},
                effect_records=[dict(id="E1", endpoint="score", endpoint_role="primary", metric="mean_diff", estimate=0,
                    ci_low=-z, ci_high=z, direction="neutral", inference_method="wald", evidence_id=ev)])],
            decisions_fn=lambda cs, ev: [_decision(cs[0], [ev], forecast_probability=0.8)])
        self.source_case = self.engine.dispatch("create_case", {"question": "External reference fixture", "draft": "Reported source"})["case_id"]
        text = "Fixture follow-up score mean_diff estimate 2, narrow CI 1.8 to 2.2, wide CI -17.6 to 21.6; known truth reference 2."
        (self.root/"followup.txt").write_text(text, encoding="utf-8")
        self.eid = self.engine.dispatch("register_evidence", dict(case_id=self.source_case, path="followup.txt", provenance="observed", kind="observation", quote=text, location="fixture row"))["evidence_id"]

    def payload(self, **updates):
        p = dict(case_id=self.cid, claim_id="C1", outcome="replicated", resolution_source="external_evidence", evidence_id=self.eid,
                 reason="Explicit fixture outcome with registered reference data.")
        p.update(updates)
        return p

    def report(self):
        return self.engine.get_calibration_report(case_id=self.cid)

    def test_nonexistent_source_rejected_and_missing_source_remains_unresolved(self):
        with self.assertRaises(ContractError) as cm:
            self.engine.dispatch("record_calibration_outcome", self.payload(evidence_id="does-not-exist"))
        self.assertEqual(cm.exception.code, "unknown_reference")
        p = self.payload(); p.pop("evidence_id")
        self.engine.dispatch("record_calibration_outcome", p)
        rep = self.report()
        self.assertEqual(rep["summary"]["resolved_claim_count"], 0)
        self.assertIsNone(rep["proper_scores"]["explicit_brier_score"])
        self.assertEqual(rep["claim_records"][0]["reported_outcome_score"], 1.0)

    def test_verified_source_scores_and_tampering_removes_eligibility_without_rewriting_history(self):
        self.engine.dispatch("record_calibration_outcome", self.payload())
        self.assertAlmostEqual(self.report()["proper_scores"]["explicit_brier_score"], 0.04)
        after = self.engine.dispatch("get_case", {"case_id": self.cid})
        self.assertEqual(after["input_digest"], self.before["input_digest"])
        self.assertEqual(after["adjudication_digest"], self.before["adjudication_digest"])
        (self.root/"followup.txt").write_text("Changed reference", encoding="utf-8")
        self.assertEqual(self.report()["summary"]["resolved_claim_count"], 0)
        preserved = self.engine.dispatch("get_case", {"case_id": self.cid})
        self.assertEqual(preserved["calibration_outcomes"], after["calibration_outcomes"])

    def test_outcome_labels_constrain_proper_brier_scores(self):
        for outcome, score in (("replicated", 0), ("refuted", 1), ("partially_replicated", 1), ("partially_replicated", 0)):
            with self.subTest(outcome=outcome, score=score), self.assertRaisesRegex(ContractError, "invalid_calibration_outcome"):
                self.engine.dispatch("record_calibration_outcome", self.payload(outcome=outcome, outcome_score=score))
        self.assertEqual(self.engine.dispatch("get_case", {"case_id": self.cid}).get("calibration_outcomes", []), [])
        self.engine.dispatch("record_calibration_outcome", self.payload(outcome="partially_replicated", outcome_score=0.5))
        report = self.report()
        self.assertEqual(report["claim_records"][0]["outcome_score"], 0.5)
        self.assertIsNotNone(report["heuristic_scores"]["combined_brier_score"])
        self.assertEqual(report["summary"]["proper_score_count"], 0)
        self.assertIsNone(report["proper_scores"]["explicit_brier_score"])
        self.assertEqual(sum(b["count"] for b in report["reliability_bins"]), 0)

    def test_historical_conflicting_scores_remain_visible_without_entering_scoring(self):
        for outcome, score in (("replicated", 0.0), ("partially_replicated", 1.0)):
            with self.subTest(outcome=outcome):
                case = deepcopy(self.before)
                case["calibration_outcomes"] = [dict(self.payload(outcome=outcome, outcome_score=score))]
                before = deepcopy(case)
                report = compute_calibration_report([case], evidence_by_id={self.eid: {"traceability_status": "verified"}})
                row = report["claim_records"][0]
                self.assertEqual(row["source_binding"]["status"], "source_verified")
                self.assertEqual(row["reported_outcome_score"], score)
                self.assertIsNone(row["outcome_score"])
                self.assertEqual(row["score_issue"], "outcome_score_conflicts_with_label")
                self.assertEqual(report["summary"]["outcome_score_conflict_count"], 1)
                self.assertEqual(report["summary"]["proper_score_count"], 0)
                self.assertIsNone(report["proper_scores"]["explicit_brier_score"])
                self.assertEqual(case, before)

    def test_draft_followup_and_self_confirming_trigger_are_pending(self):
        self.engine.dispatch("record_calibration_outcome", self.payload(resolution_source="follow_up_case", follow_up_case_id=self.source_case))
        self.assertEqual(self.report()["summary"]["resolved_claim_count"], 0)
        self.engine.dispatch("record_calibration_outcome", self.payload(resolution_source="trigger_evaluation"))
        self.assertEqual(self.report()["summary"]["resolved_claim_count"], 0)

    def test_replication_interval_uses_both_uncertainties_and_does_not_claim_coverage(self):
        obs = dict(metric="mean_diff", effect_record_id="E1", observed_estimate=2, observed_ci_low=1.8, observed_ci_high=2.2,
                   observed_ci_method="wald", observed_ci_level=0.95, comparison_assumption="independent")
        self.engine.dispatch("record_calibration_outcome", self.payload(**obs))
        narrow = self.report()["interval_calibration"]
        self.assertIsNone(narrow["empirical_coverage_rate"])
        self.assertIsNone(narrow["coverage_error"])
        self.assertEqual(narrow["replication_count"], 1)
        self.assertFalse(narrow["records"][0]["point_in_original_interval"])
        expected = 2/math.sqrt(1 + (0.2/1.959963984540054)**2)
        self.assertAlmostEqual(narrow["records"][0]["z_difference"], expected, places=6)
        obs.update(observed_ci_low=-17.6, observed_ci_high=21.6)
        self.engine.dispatch("record_calibration_outcome", self.payload(**obs))
        wide = self.report()["interval_calibration"]
        self.assertLess(wide["records"][0]["z_difference"], narrow["records"][0]["z_difference"])

    def test_unknown_dependence_does_not_produce_standardized_difference(self):
        self.engine.dispatch("record_calibration_outcome", self.payload(metric="mean_diff", effect_record_id="E1", observed_estimate=2,
            observed_ci_low=1.8, observed_ci_high=2.2, observed_ci_method="wald"))
        rec = self.report()["interval_calibration"]["records"][0]
        self.assertEqual(rec["comparison_status"], "unassessed")
        self.assertIsNone(rec["z_difference"])

    def test_known_truth_coverage_is_separate_and_endpoint_binding_required(self):
        self.engine.dispatch("record_calibration_outcome", self.payload(metric="mean_diff", effect_record_id="E1", observed_estimate=2, comparison_kind="known_truth"))
        rep = self.report()["interval_calibration"]
        self.assertEqual(rep["evaluated_count"], 1)
        self.assertEqual(rep["empirical_coverage_rate"], 0)
        self.assertEqual(rep["nominal_coverage_rate"], 0.95)
        self.assertEqual(rep["replication_count"], 0)
        with self.assertRaises(ContractError):
            self.engine.dispatch("record_calibration_outcome", self.payload(metric="HR", effect_record_id="E1", observed_estimate=2))
        self.engine.dispatch("record_calibration_outcome", self.payload(metric="mean_diff", observed_estimate=2))
        self.assertEqual(self.report()["summary"]["resolved_claim_count"], 0)

    def test_heuristic_confidence_not_in_proper_scores_or_reliability_bins(self):
        self.engine.dispatch("record_calibration_outcome", self.payload())
        case = self.engine.dispatch("get_case", {"case_id": self.cid})
        case["adjudication"]["decisions"][0].pop("forecast_probability")
        # Pure-function fixture does not modify the persisted decision.
        sources = {self.eid: {"traceability_status": "verified"}}
        rep = compute_calibration_report([case], evidence_by_id=sources)
        self.assertIsNone(rep["proper_scores"]["explicit_brier_score"])
        self.assertIsNone(rep["proper_scores"]["combined_brier_score"])
        self.assertIsNone(rep["proper_scores"]["ece"])
        self.assertEqual(sum(b["count"] for b in rep["reliability_bins"]), 0)
        self.assertIsNotNone(rep["heuristic_scores"]["combined_brier_score"])

    def test_legacy_unbound_outcomes_are_preserved_but_not_scored(self):
        case = deepcopy(self.before)
        case["calibration_outcomes"] = [dict(claim_id="C1", outcome="replicated", outcome_score=1.0,
            resolution_source="external_evidence", evidence_id="never-registered", reason="Legacy assertion")]
        before = deepcopy(case)
        rep = compute_calibration_report([case])
        self.assertEqual(rep["summary"]["unverified_outcome_count"], 1)
        self.assertEqual(rep["summary"]["resolved_claim_count"], 0)
        self.assertEqual(case, before)

    def test_normal_api_draft_and_frozen_replacement_do_not_change_standing(self):
        cid = self.engine.dispatch("create_case", {"question": "Pending replacement", "draft": "Draft", "supersedes_case_id": self.cid})["case_id"]
        def standing():
            return next(n for n in self.engine.dispatch("claim_graph", {"case_id": self.cid})["claim_nodes"] if n["node_id"] == f"{self.cid}:C1")["active_standing"]
        self.assertEqual(standing(), "current")
        ev = self.engine.dispatch("register_evidence", dict(case_id=cid, path="followup.txt", provenance="observed", kind="observation",
            quote=(self.root/"followup.txt").read_text(), location="fixture row"))["evidence_id"]
        cl = _v2_claim("C1", [ev], text="Follow-up estimate is 2.", effect={"estimate":"2", "uncertainty":"interval 1.8 to 2.2"})
        self.engine.dispatch("set_ledger", {"case_id":cid,"claims":[cl]})
        self.engine.dispatch("freeze", {"case_id":cid})
        self.assertEqual(standing(), "current")
        after = self.engine.dispatch("get_case", {"case_id":self.cid})
        self.assertEqual(after["input_digest"], self.before["input_digest"])

    def test_covariance_and_unsupported_method_are_explicit_boundaries(self):
        obs = dict(metric="mean_diff", effect_record_id="E1", observed_estimate=2, observed_ci_low=1.8,
                   observed_ci_high=2.2, observed_ci_method="wald", comparison_assumption="covariance_supplied", estimate_covariance=0.05)
        self.engine.dispatch("record_calibration_outcome", self.payload(**obs))
        rec = self.report()["interval_calibration"]["records"][0]
        expected = 2/math.sqrt(1+(0.2/1.959963984540054)**2-0.1)
        self.assertAlmostEqual(rec["z_difference"], expected, places=6)
        obs["estimate_covariance"] = 50
        self.engine.dispatch("record_calibration_outcome", self.payload(**obs))
        self.assertEqual(self.report()["interval_calibration"]["records"][0]["comparison_reason"], "invalid_or_missing_covariance")
        obs.update(observed_ci_method="student_t", estimate_covariance=0)
        self.engine.dispatch("record_calibration_outcome", self.payload(**obs))
        self.assertIsNone(self.report()["interval_calibration"]["records"][0]["z_difference"])

    def test_endpoint_numbers_must_match_the_registered_source(self):
        self.engine.dispatch("record_calibration_outcome", self.payload(metric="mean_diff", effect_record_id="E1", observed_estimate=999))
        rep = self.report()
        self.assertEqual(rep["summary"]["resolved_claim_count"], 0)
        self.assertEqual(rep["claim_records"][0]["source_binding"]["reason"], "observed_numbers_not_anchored")


class ExecutionReviewRegressions(unittest.TestCase):
    def test_invalid_partial_output_does_not_erase_timeout_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eng = Engine(root)
            cid = eng.dispatch("create_case", {"question":"Invalid output fixture","draft":"Draft"})["case_id"]
            rc, out, err = _run_cli(["record-exec", "--workspace", str(root), "--case-id", cid, "--timeout", "1",
                "--output-file", "result.txt", "--", sys.executable, "-u", "-c",
                "from pathlib import Path; import time; Path('result.txt').mkdir(); print('partial result'); time.sleep(20)"])
            self.assertEqual(rc, 124, err)
            self.assertEqual(out["provenance"]["unverified_outputs"], ["result.txt"])
            self.assertFalse(out["provenance"]["all_outputs_present"])
            self.assertEqual(out["execution_card"]["status"], "failed")
            self.assertIn("partial result", (root/out["log_path"]).read_text())
            case = eng.dispatch("get_case", {"case_id":cid})
            self.assertEqual(len(case["evidence"]), 1)
            self.assertEqual(len([e for e in case["events"] if e["action"]=="record_exec"]), 1)

    def test_timeout_start_failure_and_nonzero_exit_all_leave_distinct_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "Failure recording fixture", "draft": "Draft"})["case_id"]
            base = ["record-exec", "--workspace", str(root), "--case-id", cid]
            cases = [
                (["--timeout", "1", "--", sys.executable, "-u", "-c", "import time; print('partial-output'); time.sleep(20)"], 124, "timed_out", None),
                (["--", str(root/"nonexistent-program")], 127, "start_failed", None),
                (["--", sys.executable, "-c", "print('nonzero-output'); raise SystemExit(7)"], 0, "completed", 7),
            ]
            logs = []
            for args, expected_rc, state, child_code in cases:
                rc, out, err = _run_cli(base + args)
                self.assertEqual(rc, expected_rc, err)
                self.assertEqual(out["termination_status"], state)
                self.assertEqual(out["exit_status"], child_code)
                self.assertEqual(out["execution_card"]["status"], "failed")
                content = (root/out["log_path"]).read_text(encoding="utf-8")
                self.assertIn("started_at:", content)
                self.assertIn(state, content)
                if state == "timed_out":
                    self.assertIn("partial-output", content)
                logs.append(out["log_path"])
            self.assertEqual(len(set(logs)), 3)
            case = engine.dispatch("get_case", {"case_id": cid})
            self.assertEqual(len(case["evidence"]), 3)
            events = [e for e in case["events"] if e["action"] == "record_exec"]
            self.assertEqual(len(events), 3)
            self.assertEqual(case["event_chain_status"], "verified")

    def test_existing_execution_log_is_preserved_and_command_not_launched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"retained.log").write_text("previous failure", encoding="utf-8")
            rc, _, _ = _run_cli(["record-exec", "--workspace", str(root), "--log-path", "retained.log", "--", sys.executable, "-c", "from pathlib import Path; Path('launched').touch()"])
            self.assertEqual(rc, 2)
            self.assertFalse((root/"launched").exists())
            self.assertEqual((root/"retained.log").read_text(), "previous failure")


if __name__ == "__main__":
    unittest.main()
