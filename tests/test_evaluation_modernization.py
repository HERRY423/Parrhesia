"""Evaluation checks must expose missing outcomes and avoid self-certifying success."""
from collections import Counter
from copy import deepcopy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.eval_inputs import policy_inputs
from scripts.eval_ingestion import run_ingestion_suite

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("impact_pilot", ROOT / "scripts/prepare-impact-pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class IngestionEvaluationTests(unittest.TestCase):
    def test_pipeline_and_boundaries_have_observed_actions_and_no_impact_claim(self):
        result = run_ingestion_suite()
        self.assertTrue(result["summary"]["all_passed"], [(r["case_code"], r["error"]) for r in result["results"] if not r["passed"]])
        self.assertEqual(result["summary"]["total_cases"], 10)
        calls = Counter(c["action"] for r in result["results"] for c in r["calls"])
        self.assertEqual(result["summary"]["action_calls"], dict(calls))
        self.assertTrue(all(result["summary"]["action_coverage"].values()))
        self.assertTrue(any(c["status"] == "rejected" for r in result["results"] for c in r["calls"]))
        self.assertEqual(result["user_impact"], "not_run")
        self.assertEqual(result["host_accepted"], "not_run")

    def test_broken_parser_cannot_leave_suite_green(self):
        with patch("scripts.eval_ingestion.Engine.dispatch", autospec=True, side_effect=self.dispatch_without_effects):
            result = run_ingestion_suite()
        self.assertFalse(result["summary"]["all_passed"])
        self.assertFalse(result["results"][0]["passed"])

    original_dispatch = __import__("parrhesia.core", fromlist=["Engine"]).Engine.dispatch

    @staticmethod
    def dispatch_without_effects(engine, action, payload):
        result = IngestionEvaluationTests.original_dispatch(engine, action, payload)
        if action == "extract_effects":
            result["effect_records"] = []
        return result

    def test_prompt_measurement_is_exact_and_missing_policy_does_not_become_empty(self):
        result = policy_inputs(ROOT)
        for name, prompt in result["arm_system_prompts"].items():
            self.assertEqual(result["arm_prompt_bytes"][name], len(prompt.encode("utf-8")))
        self.assertEqual(result["policy_size_bytes"]["B_full_policy_bytes"], result["arm_prompt_bytes"]["B_full"])
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            policy_inputs(Path(directory))

    def test_ingestion_cli_report_stays_a_bounded_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/run-stage0-eval.py"), "--mode", "ingestion", "--report-out", str(report)],
                                 cwd=ROOT, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", errors="replace"))
            result = json.loads(run.stdout)
            self.assertEqual(result["mode"], "ingestion")
            self.assertEqual(len(result["results"]), 10)
            self.assertNotIn("counterfactual_results", result)
            self.assertTrue(report.is_file())


class ImpactPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = self.root / "plan"
        self.prepared = pilot.prepare(self.plan, cases=4)
        self.assignments = [json.loads(s) for s in (self.plan / "assignments.jsonl").read_text().splitlines()]

    def observations(self, rows):
        path = self.root / "observations.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def row(self, index=0, **changes):
        return {"run_id": self.assignments[index]["run_id"], "plan_digest": self.prepared["plan_digest"], "status": "completed", **changes}

    def test_balanced_reproducible_assignment_does_not_claim_execution(self):
        second = self.root / "second"
        pilot.prepare(second, cases=4)
        self.assertEqual((self.plan / "assignments.jsonl").read_bytes(), (second / "assignments.jsonl").read_bytes())
        for arm in pilot.ARMS:
            self.assertEqual(sorted(r["planned_order"] for r in self.assignments if r["arm"] == arm), [1, 2, 3, 4])
        summary = pilot.summarize(self.plan)
        self.assertEqual(summary["status"], "not_run")
        self.assertEqual(pilot.summarize(self.plan, self.observations([self.row(status="not_run")]))["observed_runs"], 0)
        for arm in summary["arms"].values():
            self.assertEqual(arm["missing_records"], 4)
            self.assertIsNone(arm["observed_quality_pass_rate"])
            self.assertIsNone(arm["metrics"]["cost_usd"]["observed_sum"])
        with self.assertRaises(FileExistsError):
            pilot.prepare(self.plan, cases=4)

    def test_failure_missing_cost_and_true_zero_keep_denominators(self):
        rows = [self.row(0, active_seconds=0, corrections=0, quality_pass=True, scorer_blinded=True), self.row(1, status="failed", active_seconds=12, reason="form rejected")]
        summary = pilot.summarize(self.plan, self.observations(rows))
        self.assertEqual(sum(a["assigned"] for a in summary["arms"].values()), 16)
        self.assertEqual(sum(a["missing_records"] for a in summary["arms"].values()), 14)
        arm = summary["arms"][self.assignments[0]["arm"]]
        self.assertEqual(arm["metrics"]["active_seconds"]["observed_mean"], 0)
        self.assertIsNone(arm["metrics"]["cost_usd"]["observed_sum"])
        self.assertIn("not_established", summary["user_impact"])

    def test_invalid_observations_cannot_silently_change_outcome(self):
        invalid = [self.row(cost_usd=float("nan")), self.row(corrections=-1), self.row(active_seconds=True), self.row(quality_pass=1),
                   self.row(plan_digest="changed"), self.row(run_id="unknown"), self.row(status="cancelled", quality_pass=True),
                   self.row(status="not_run", cost_usd=0), self.row(quality_pass=True, serious_evidence_errors=1)]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                pilot.summarize(self.plan, self.observations([row]))
        with self.assertRaises(ValueError):
            pilot.summarize(self.plan, self.observations([self.row(), self.row()]))

    def test_hydrated_pilot_verifies_observation_material_identity(self):
        benchmark = self.root / "four-cases.json"
        benchmark.write_text(json.dumps({"cases": [
            {"case_code": f"P{i}", "trap_category": "synthetic", "family": "prediction"} for i in range(4)
        ]}), encoding="utf-8")
        plan = self.root / "hydrated"
        pilot.prepare(plan, benchmark=benchmark)
        template = json.loads((plan / "observation-template.json").read_text(encoding="utf-8"))
        correct = {**template, "status": "completed", "quality_pass": True, "scorer_blinded": True}
        for wrong in ("0" * 64, None):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError, "material digest"):
                pilot.summarize(plan, self.observations([{**correct, "material_sha256": wrong}]))
        summary = pilot.summarize(plan, self.observations([correct]))
        self.assertEqual(sum(a["blinded_quality_scored"] for a in summary["arms"].values()), 1)
        failed = {**template, "status": "failed", "material_sha256": None, "reason": "Failed before loading material"}
        summary = pilot.summarize(plan, self.observations([failed]))
        self.assertEqual(sum(a["statuses"].get("failed", 0) for a in summary["arms"].values()), 1)

    def test_changed_assignment_or_protocol_fails_closed(self):
        path = self.plan / "assignments.jsonl"
        original = path.read_bytes()
        changed = deepcopy(self.assignments)
        changed[0]["arm"] = pilot.ARMS[(pilot.ARMS.index(changed[0]["arm"]) + 1) % 4]
        path.write_text("".join(json.dumps(r) + "\n" for r in changed))
        with self.assertRaisesRegex(ValueError, "Assignment content"):
            pilot.summarize(self.plan)
        path.write_bytes(original)
        protocol_path = self.plan / "protocol.json"
        protocol = json.loads(protocol_path.read_text())
        protocol["seed"] += 1
        protocol_path.write_text(json.dumps(protocol))
        with self.assertRaisesRegex(ValueError, "Plan changed"):
            pilot.summarize(self.plan)


if __name__ == "__main__":
    unittest.main()
