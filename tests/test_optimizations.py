"""Tests for the 4 Parrhesia v0.2.0 optimizations (policy sync, L1-Explore/scaffolding/record-exec, observational causal & anti-rubber-stamping gates, and Stage 0 evaluation suite)."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_claims_v2 as fixtures
from parrhesia.cli import main as cli_main
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.gates import ceiling

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OptimizationTests(unittest.TestCase):
    setUp = fixtures.ClaimsV2Tests.setUp
    tearDown = fixtures.ClaimsV2Tests.tearDown
    register = fixtures.ClaimsV2Tests.register
    assessment = fixtures.ClaimsV2Tests.assessment
    claim = fixtures.ClaimsV2Tests.claim
    save = fixtures.ClaimsV2Tests.save
    reviewed = fixtures.ClaimsV2Tests.reviewed
    error = fixtures.ClaimsV2Tests.error

    def test_scaffold_claim_generates_valid_unknown_skeleton_and_ceilings(self):
        res = self.engine.dispatch(
            "scaffold_claim",
            {
                "case_id": self.cid,
                "claim_id": "C-SCAF",
                "claim_type": "causal_effect",
                "evidence_level": "identified_under_assumptions",
                "design_families": ["observational"],
            },
        )
        self.assertEqual(res["case_id"], self.cid)
        claim = res["claim"]
        self.assertEqual(claim["id"], "C-SCAF")
        self.assertIn("causal_basis", claim)
        self.assertEqual(claim["provenance_cards"]["execution"][0]["status"], "not_run")
        self.assertEqual(res["check_ceilings"]["allowed_levels"], ["unassessed", "unidentified"])
        # The scaffolded claim is immediately schema-valid for set_ledger in draft state.
        ledger_res = self.engine.dispatch("set_ledger", {"case_id": self.cid, "claims": [claim]})
        self.assertEqual(ledger_res["claim_count"], 1)

    def test_record_exec_cli_captures_log_registers_evidence_and_builds_card(self):
        stdout_buf = io.BytesIO()
        with patch.object(sys, "stdout", SimpleNamespace := type("S", (), {"buffer": stdout_buf})()):
            rc = cli_main(
                [
                    "record-exec",
                    "--workspace",
                    str(self.root),
                    "--case-id",
                    self.cid,
                    "--card-id",
                    "exec-test-1",
                    "--kind",
                    "benchmark",
                    "--log-path",
                    "logs/test_run.log",
                    "--",
                    sys.executable,
                    "-c",
                    "print('parrhesia-exec-ok')",
                ]
            )
        self.assertEqual(rc, 0)
        out = json.loads(stdout_buf.getvalue().decode("utf-8"))
        self.assertEqual(out["exit_status"], 0)
        self.assertEqual(out["execution_card"]["status"], "checked")
        self.assertIn("evidence", out)
        ev_id = out["evidence"]["evidence_id"]
        self.assertEqual(out["execution_card"]["evidence_ids"], [ev_id])
        c = self.claim("computational", "benchmark_measured", "ml")
        c["evidence_ids"].append(ev_id)
        c["provenance_cards"]["execution"] = [out["execution_card"]]
        self.save(c)

        # Non-zero exit status records status="failed"
        fail_buf = io.BytesIO()
        with patch.object(sys, "stdout", type("S", (), {"buffer": fail_buf})()):
            rc2 = cli_main(
                [
                    "record-exec",
                    "--workspace",
                    str(self.root),
                    "--card-id",
                    "exec-fail-1",
                    "--log-path",
                    "logs/fail_run.log",
                    "--",
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(3)",
                ]
            )
        self.assertEqual(rc2, 0)
        out2 = json.loads(fail_buf.getvalue().decode("utf-8"))
        self.assertEqual(out2["exit_status"], 3)
        self.assertEqual(out2["execution_card"]["status"], "failed")

    def test_observational_causal_partially_supported_allowed_while_supported_blocked(self):
        # self.ev is registered with kind="observation" by default in setUp
        c = self.claim("causal_effect", "sensitivity_supported", "observational")
        self.save(c)
        self.engine.dispatch("freeze", {"case_id": self.cid})
        cond = "Holds under conditional exchangeability given baseline covariates and E-value >= 2.0."
        for role in ("overclaim", "underclaim"):
            pkt = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            # Reviewer stance="supported" on observational causal claim is blocked
            bad_review = {
                "case_id": self.cid,
                "role": role,
                "packet_id": pkt["packet_id"],
                "input_digest": pkt["input_digest"],
                "reviewer": {"context_id": f"rev-{role}", "model": "fixture"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [
                    {"claim_id": "C1", "stance": "supported", "rationale": "Overclaim", "evidence_ids": [self.ev]}
                ],
                "unread_evidence_ids": [],
                "findings": [],
            }
            self.error("incompatible_evidence_kind", "submit_review", bad_review)
            # Reviewer stance="partially_supported" with substantive condition succeeds
            good_review = deepcopy(bad_review)
            good_review["claim_stances"][0]["stance"] = "partially_supported"
            good_review["claim_stances"][0]["condition"] = cond
            self.engine.dispatch("submit_review", good_review)

        adj = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        payload = {
            "case_id": self.cid,
            "adjudication_id": adj["adjudication_id"],
            "input_digest": adj["input_digest"],
            "adjudicator": {"context_id": "adj-1", "model": "fixture"},
            "unread_evidence_ids": [],
            "decisions": [
                {
                    "claim_id": "C1",
                    "verdict": "supported",
                    "claim_type": "causal_effect",
                    "evidence_level": "sensitivity_supported",
                    "claim_basis": "empirical",
                    "scope": c["scope"],
                    "revised_text": c["text"],
                    "rationale": "Test",
                    "evidence_ids": [self.ev],
                    "confidence": "medium",
                    "confidence_reason": "Test",
                    "boundary": "Cohort boundary",
                    "reversal_condition": "If sensitivity fails",
                }
            ],
            "dispositions": [],
        }
        # Unconditional "supported" remains blocked for kind="observation"
        self.error("incompatible_evidence_kind", "submit_adjudication", payload)
        # Conditional "partially_supported" with explicit condition succeeds
        payload["decisions"][0]["verdict"] = "partially_supported"
        payload["decisions"][0]["condition"] = cond
        res = self.engine.dispatch("submit_adjudication", payload)
        self.assertEqual(res["state"], "adjudicated")

    def test_anti_rubber_stamping_design_stat_and_provenance_card_gates(self):
        # 1. All design checks marked not_applicable -> blocked
        c1 = self.claim("mechanism", "component_tested", "mechanism")
        for k in c1["design_packages"][0]["checks"]:
            c1["design_packages"][0]["checks"][k] = {"status": "not_applicable", "reason": "Bypass", "evidence_ids": []}
        self.assertEqual(ceiling(c1)["allowed_levels"], ["unassessed"])

        # 2. Essential statistical check marked not_applicable on quantitative claim -> blocked
        c2 = self.claim("prediction", "externally_validated", "prediction")
        c2["statistical_report"]["units_sample_size"] = {"status": "not_applicable", "reason": "Bypass", "evidence_ids": []}
        self.assertEqual(ceiling(c2)["allowed_levels"], ["unassessed"])

        # 3. Contradicting citation card -> blocked
        c3 = self.claim("association", "adjusted", "observational")
        c3["provenance_cards"]["citation"] = [
            {
                "id": "cit-1",
                "status": "checked",
                "reason": "Contradicts claim",
                "evidence_ids": [self.ev],
                "details": {
                    "source": "Paper A",
                    "locator": "p. 4",
                    "claim_link": "C1",
                    "support_relation": "反对",
                    "read_extent": "full",
                },
            }
        ]
        self.assertEqual(ceiling(c3)["allowed_levels"], ["unassessed"])

        # 4. Checked number card whose evidence_id is not cited in positive decision -> blocked
        ev2 = self.register("observation")
        c4 = self.claim("association", "adjusted", "observational")
        c4["evidence_ids"].append(ev2)
        c4["provenance_cards"]["number"] = [
            {
                "id": "num-1",
                "status": "checked",
                "reason": "Primary HR",
                "evidence_ids": [ev2],
                "details": {
                    "value": "1.62",
                    "unit_denominator": "HR",
                    "population_time": "12m",
                    "derivation": "Cox model",
                    "uncertainty": "1.21-2.16",
                    "locator": "Table 2",
                },
            }
        ]
        payload = self.reviewed(c4)
        # Decision only cites self.ev, omitting ev2 from the checked number card
        payload["decisions"][0]["evidence_ids"] = [self.ev]
        self.error("uncited_checked_card", "submit_adjudication", payload)
        # Citing both self.ev and ev2 succeeds
        payload["decisions"][0]["evidence_ids"] = [self.ev, ev2]
        self.engine.dispatch("submit_adjudication", payload)

    def test_codex_sync_script_and_policy_anchors(self):
        install_codex = _load_script("install_codex", "scripts/install-codex.py")
        tmp_dir = Path(tempfile.mkdtemp(dir=self.root, prefix="codex-home-"))
        try:
            legacy_sample = (
                "<!-- global-conventions:user-policy:start -->\n"
                "- 规则冲突时按以下顺序取舍:用户当前明确指令(更严格者优先)> 数据保密与花费上限 > 科学证据规则 > 流程规则。\n"
                "2. 每个结论标注主张级别:描述性观察 / 相关 / 可预测 / 机制线索 / 因果或必要充分性。\n"
                "<!-- global-conventions:user-policy:end -->\n\n"
                "<!-- parrhesia:judgment-policy:start -->\n"
                "L0 不启动:普通翻译、格式修改、简单事实回答、局部代码修正;探索阶段的假设生成\n"
                "<!-- parrhesia:judgment-policy:end -->\n"
            )
            (tmp_dir / "AGENTS.md").write_text(legacy_sample, encoding="utf-8")
            res1 = install_codex.sync_codex_agents(tmp_dir, ROOT)
            self.assertEqual(res1["status"], "updated")
            self.assertIsNotNone(res1["backup_path"])
            self.assertTrue(Path(res1["backup_path"]).is_file())
            skill_target = Path(res1["l2_reference_skill_path"])
            self.assertTrue(skill_target.is_file())
            check_res = install_codex.sync_codex_agents(tmp_dir, ROOT, check_only=True)
            self.assertEqual(check_res["status"], "in_sync")
            synced_text = (tmp_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("L1-Explore", synced_text)
            self.assertIn("轻量探索台账", synced_text)
            self.assertIn("exploratory", synced_text)
            self.assertIn("推荐的日常工作流", synced_text)
            self.assertIn("审查者隔离配方", synced_text)
            self.assertIn("校准锚点", synced_text)
            self.assertLess(len(synced_text.encode("utf-8")), 10240)
            self.assertNotIn("描述性观察 / 相关 / 可预测 / 机制线索 / 因果或必要充分性", synced_text)

            l2_ref_text = skill_target.read_text(encoding="utf-8")
            self.assertIn("name: parrhesia-l2-reference", l2_ref_text)
            self.assertIn("校准锚点", l2_ref_text)
            self.assertIn("reproducible-science", l2_ref_text)
            self.assertIn("record-exec", l2_ref_text)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        chatgpt_text = (ROOT / "templates" / "AGENTS.parrhesia.chatgpt.md").read_text(encoding="utf-8")
        self.assertIn("人工介入与数据保密边界", chatgpt_text)
        self.assertIn("> 1 GB", chatgpt_text)
        self.assertNotIn("parrhesia_contract", chatgpt_text)
        self.assertNotIn("search_offerings", chatgpt_text)

    def test_reviewer_input_manifest_recorded_in_reports(self):
        from parrhesia.report import render_report

        c = self.claim("association", "adjusted", "observational")
        payload = self.reviewed(c)
        self.engine.dispatch("submit_adjudication", payload)
        self.engine.dispatch("verify", {"case_id": self.cid})
        exp = self.engine.dispatch("export", {"case_id": self.cid})
        self.assertEqual(exp["state"], "exported")
        md_text = Path(exp["path"]).read_text(encoding="utf-8")
        case_doc = self.engine.dispatch("get_case", {"case_id": self.cid})
        html_path = self.root / "review.html"
        render_report(
            {
                "case_id": self.cid,
                "draft": case_doc["draft"],
                "claims": case_doc["claims"],
                "decisions": case_doc["adjudication"]["decisions"],
                "findings": {"overclaim": [], "underclaim": []},
                "dispositions": case_doc["adjudication"]["dispositions"],
                "verification": exp["verification"],
                "export": exp,
                "gate_version": case_doc["gate_version"],
                "blind": case_doc["blind"],
                "reviews": case_doc["reviews"],
                "evidence": case_doc["evidence"],
                "unread_evidence_ids": case_doc["adjudication"]["unread_evidence_ids"],
            },
            html_path,
        )
        html_text = html_path.read_text(encoding="utf-8")
        self.assertIn("input\\_manifest", md_text)
        self.assertIn("none\\_role\\_packet\\_only", md_text)
        self.assertIn("disabled\\_or\\_not\\_used\\_caller\\_reported", md_text)
        self.assertIn("reviewer_input_manifests", html_text)
        self.assertIn("none_role_packet_only", html_text)
        self.assertIn("disabled_or_not_used_caller_reported", html_text)

    def test_stage0_evaluation_suite_mechanical_and_prompt_export(self):
        stage0 = _load_script("run_stage0_eval", "scripts/run-stage0-eval.py")
        suite_path = ROOT / "docs" / "evaluation" / "stage0-cases.json"
        eval_dir = Path(tempfile.mkdtemp(dir=self.root, prefix="stage0-work-"))
        try:
            summary = stage0.run_mechanical_suite(suite_path, work_root=eval_dir / "mech")
            self.assertEqual(summary["suite_version"], "stage0-v2")
            self.assertEqual(summary["arms"], ["A_baseline", "B_compact", "B_full", "E_full_l2_workflow"])
            self.assertEqual(summary["total_cases"], 24)
            self.assertEqual(summary["passed_cases"], 24)
            self.assertEqual(summary["exploratory_cases_count"], 6)
            self.assertEqual(summary["exploratory_passed_cases"], 6)
            self.assertTrue(summary["exploratory_all_valid"])
            self.assertTrue(summary["all_passed"])
            self.assertEqual(summary["external_llm_status"], "not_run")

            exported = stage0.export_prompts(suite_path, eval_dir / "prompts")
            self.assertEqual(exported["packet_count"], 24)
            self.assertEqual(exported["exploratory_packet_count"], 6)
            self.assertEqual(exported["arms"], ["A_baseline", "B_compact", "B_full", "E_full_l2_workflow"])
            self.assertEqual(exported["external_llm_status"], "not_run")
            out_file = Path(exported["output_file"])
            self.assertTrue(out_file.is_file())
            packets_payload = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(set(packets_payload["packets"][0]["arms"].keys()), {"A_baseline", "B_compact", "B_full", "E_full_l2_workflow"})
            self.assertEqual(len(packets_payload["exploratory_packets"]), 6)
        finally:
            shutil.rmtree(eval_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
