"""Tests for the 4 Parrhesia v0.2.0 optimizations (policy sync, L1-Explore/scaffolding/record-exec, observational causal & anti-rubber-stamping gates, and Stage 0 evaluation suite)."""

from __future__ import annotations

from copy import deepcopy
import html
import importlib.util
import io
import json
from pathlib import Path
import re
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
                    "auto",
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
            self.assertNotIn("reproducible-science", l2_ref_text)
            self.assertIn("外部插件不构成使用前提", l2_ref_text)
            self.assertIn("record-exec", l2_ref_text)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertIn("可能超过 1 GB", synced_text)
        self.assertIn("$0.10", synced_text)

        chatgpt_text = (ROOT / "templates" / "AGENTS.parrhesia.chatgpt.md").read_text(encoding="utf-8")
        self.assertIn("不代填接受", chatgpt_text)
        self.assertNotIn("可能超过 1 GB", chatgpt_text)
        self.assertNotIn("$0.10", chatgpt_text)
        self.assertNotIn("parrhesia-review", chatgpt_text)
        self.assertNotIn("packet_id", chatgpt_text)
        self.assertNotIn("parrhesia_contract", chatgpt_text)
        self.assertNotIn("search_offerings", chatgpt_text)

    def test_reviewer_input_manifest_recorded_in_reports(self):
        from parrhesia.report import render_report

        def _extract_html_audit(html_text: str) -> dict:
            match = re.search(r"<pre>(.*?)</pre>", html_text, flags=re.S)
            self.assertIsNotNone(match)
            return json.loads(html.unescape(match.group(1)))

        def _render_html(case_id: str, exp_doc: dict, target: Path) -> str:
            case_doc = self.engine.dispatch("get_case", {"case_id": case_id})
            render_report(
                {
                    "case_id": case_id,
                    "draft": case_doc["draft"],
                    "claims": case_doc["claims"],
                    "decisions": case_doc["adjudication"]["decisions"],
                    "findings": {"overclaim": [], "underclaim": []},
                    "dispositions": case_doc["adjudication"]["dispositions"],
                    "verification": exp_doc["verification"],
                    "export": exp_doc,
                    "gate_version": case_doc["gate_version"],
                    "blind": case_doc["blind"],
                    "reviews": case_doc["reviews"],
                    "adjudication": case_doc["adjudication"],
                    "evidence": case_doc["evidence"],
                    "unread_evidence_ids": case_doc["adjudication"]["unread_evidence_ids"],
                },
                target,
            )
            return target.read_text(encoding="utf-8")

        # 1. Omitted isolation_attestation defaults to UNKNOWN (never legacy hardcoded strings)
        c = self.claim("association", "adjusted", "observational")
        payload = self.reviewed(c)
        self.engine.dispatch("submit_adjudication", payload)
        self.engine.dispatch("verify", {"case_id": self.cid})
        exp = self.engine.dispatch("export", {"case_id": self.cid})
        self.assertEqual(exp["state"], "exported")
        md_text = Path(exp["path"]).read_text(encoding="utf-8")
        html_text = _render_html(self.cid, exp, self.root / "review.html")

        for legacy in (
            "none_role_packet_only",
            "none\\_role\\_packet\\_only",
            "disabled_or_not_used_caller_reported",
            "disabled\\_or\\_not\\_used\\_caller\\_reported",
        ):
            self.assertNotIn(legacy, md_text)
            self.assertNotIn(legacy, html_text)

        self.assertIn("input\\_manifest", md_text)
        self.assertIn("input\\_manifest.history\\_inheritance | UNKNOWN", md_text)
        self.assertIn("input\\_manifest.memory\\_access | UNKNOWN", md_text)
        self.assertIn("input\\_manifest.host\\_surface | UNKNOWN", md_text)
        self.assertIn("adjudication\\_isolation\\_attestation.history\\_inheritance | UNKNOWN", md_text)
        self.assertIn("adjudication\\_isolation\\_attestation.memory\\_access | UNKNOWN", md_text)
        self.assertIn("adjudication\\_isolation\\_attestation.host\\_surface | UNKNOWN", md_text)
        self.assertIn("reviewer_input_manifests", html_text)

        audit = _extract_html_audit(html_text)
        for role in ("overclaim", "underclaim"):
            manifest = audit["reviewer_input_manifests"][role]
            self.assertEqual(manifest["history_inheritance"], "UNKNOWN")
            self.assertEqual(manifest["memory_access"], "UNKNOWN")
            self.assertEqual(manifest["host_surface"], "UNKNOWN")
        self.assertEqual(
            audit["adjudication_isolation_attestation"],
            {"history_inheritance": "UNKNOWN", "memory_access": "UNKNOWN", "host_surface": "UNKNOWN"},
        )

        # 2. Caller-supplied isolation_attestation is validated and round-trips to Markdown & HTML
        cid2 = self.engine.dispatch(
            "create_case",
            {"question": "Attested fixture?", "draft": "Synthetic", "writer_context_id": "writer-2"},
        )["case_id"]
        ev2 = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": cid2,
                "path": "source.txt",
                "provenance": "reported",
                "kind": "observation",
                "quote": "Synthetic fixture: effect 0.",
                "location": "line 1",
            },
        )["evidence_id"]
        c2 = json.loads(json.dumps(self.claim("association", "adjusted", "observational")).replace(self.ev, ev2))
        self.engine.dispatch("set_ledger", {"case_id": cid2, "claims": [c2]})
        frozen2 = self.engine.dispatch("freeze", {"case_id": cid2})

        role_attestations = {
            "overclaim": {
                "history_inheritance": "none_fresh_subagent_overclaim",
                "memory_access": "disabled_host_setting",
                "host_surface": "codex-subagent",
            },
            "underclaim": {
                "history_inheritance": "none_fresh_subagent_underclaim",
                "memory_access": "disabled_host_setting",
                "host_surface": "claude-subagent",
            },
        }
        adj_attestation = {
            "history_inheritance": "coordinator_session_main",
            "memory_access": "workspace_memory_read",
            "host_surface": "antigravity-coordinator",
        }
        over_pkt = self.engine.dispatch("review_packet", {"case_id": cid2, "role": "overclaim"})
        with self.assertRaises(ContractError) as bad_att:
            self.engine.dispatch(
                "submit_review",
                {
                    "case_id": cid2,
                    "role": "overclaim",
                    "packet_id": over_pkt["packet_id"],
                    "input_digest": frozen2["input_digest"],
                    "reviewer": {"context_id": "bad-att", "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [
                        {"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Fixture", "evidence_ids": []}
                    ],
                    "unread_evidence_ids": [],
                    "isolation_attestation": {"extra_flag": "disallowed"},
                    "findings": [],
                },
            )
        self.assertEqual(bad_att.exception.code, "unknown_field")

        for role in ("overclaim", "underclaim"):
            pkt = over_pkt if role == "overclaim" else self.engine.dispatch("review_packet", {"case_id": cid2, "role": role})
            self.engine.dispatch(
                "submit_review",
                {
                    "case_id": cid2,
                    "role": role,
                    "packet_id": pkt["packet_id"],
                    "input_digest": frozen2["input_digest"],
                    "reviewer": {"context_id": f"rev-{role}-2", "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [
                        {"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Fixture only", "evidence_ids": []}
                    ],
                    "unread_evidence_ids": [],
                    "isolation_attestation": role_attestations[role],
                    "findings": [],
                },
            )

        adj_pkt2 = self.engine.dispatch("adjudication_packet", {"case_id": cid2})
        self.engine.dispatch(
            "submit_adjudication",
            {
                "case_id": cid2,
                "adjudication_id": adj_pkt2["adjudication_id"],
                "input_digest": adj_pkt2["input_digest"],
                "adjudicator": {"context_id": "writer-2", "model": "fixture"},
                "unread_evidence_ids": [],
                "isolation_attestation": adj_attestation,
                "dispositions": [],
                "decisions": [
                    {
                        "claim_id": "C1",
                        "claim_basis": c2["claim_basis"],
                        "claim_type": c2["claim_type"],
                        "evidence_level": c2["evidence_level"],
                        "scope": c2["scope"],
                        "verdict": "supported",
                        "revised_text": "Scoped synthetic claim",
                        "rationale": "Fixture only",
                        "evidence_ids": [ev2],
                        "confidence": "low",
                        "confidence_reason": "Synthetic",
                        "boundary": "No scientific result",
                        "reversal_condition": "Different fixture changes the judgment",
                    }
                ],
            },
        )
        self.engine.dispatch("verify", {"case_id": cid2})
        exp2 = self.engine.dispatch("export", {"case_id": cid2})
        md_text2 = Path(exp2["path"]).read_text(encoding="utf-8")
        html_text2 = _render_html(cid2, exp2, self.root / "review-attested.html")
        audit2 = _extract_html_audit(html_text2)

        for role, expected in role_attestations.items():
            self.assertEqual(audit2["reviewer_input_manifests"][role]["history_inheritance"], expected["history_inheritance"])
            self.assertEqual(audit2["reviewer_input_manifests"][role]["memory_access"], expected["memory_access"])
            self.assertEqual(audit2["reviewer_input_manifests"][role]["host_surface"], expected["host_surface"])
            for field_val in expected.values():
                self.assertIn(field_val.replace("_", "\\_"), md_text2)
        self.assertEqual(audit2["adjudication_isolation_attestation"], adj_attestation)
        for field_val in adj_attestation.values():
            self.assertIn(field_val.replace("_", "\\_"), md_text2)

    def test_stage0_evaluation_suite_mechanical_and_prompt_export(self):
        stage0 = _load_script("run_stage0_eval", "scripts/run-stage0-eval.py")
        suite_path = ROOT / "docs" / "evaluation" / "stage0-cases.json"
        eval_dir = Path(tempfile.mkdtemp(dir=self.root, prefix="stage0-work-"))
        try:
            summary = stage0.run_mechanical_suite(suite_path, work_root=eval_dir / "mech")
            self.assertEqual(summary["suite_version"], "stage0-v2")
            self.assertEqual(summary["arms"], ["A_baseline", "B_compact", "B_full", "E_full_l2_workflow"])
            self.assertEqual(summary["total_cases"], 40)
            self.assertEqual(summary["passed_cases"], 40)
            self.assertEqual(summary["exploratory_cases_count"], 9)
            self.assertEqual(summary["exploratory_passed_cases"], 9)
            self.assertTrue(summary["exploratory_all_valid"])

            eq_cov = summary["equal_coverage_by_family"]
            self.assertEqual(len(eq_cov), 10)
            for fam, fstat in eq_cov.items():
                self.assertEqual(fstat["passed"], 4, msg=f"Family {fam} failed")
                self.assertEqual(fstat["total"], 4, msg=f"Family {fam} total mismatch")
                self.assertEqual(fstat["accuracy"], 1.0, msg=f"Family {fam} accuracy mismatch")

            cf = summary["counterfactual_summary"]
            self.assertEqual(cf["card_id"], "Card-A")
            self.assertEqual(cf["positive_base_cases"], 20)
            self.assertEqual(cf["perturbations_per_case"], 3)
            self.assertEqual(cf["total_perturbation_runs"], 60)
            self.assertEqual(cf["passed_runs"], 60)
            self.assertEqual(cf["pre_card_a_rubber_stamp_rejected"], 0)
            self.assertEqual(cf["card_a_rubber_stamp_rejected"], 30)
            self.assertEqual(cf["card_a_rubber_stamp_hard_rejected"], 30)
            self.assertEqual(cf["card_a_rubber_stamp_advisory_flagged"], 30)
            self.assertEqual(cf["card_a_rubber_stamp_detected"], 60)
            self.assertEqual(cf["calibrated_flip_accepted"], 60)
            self.assertFalse(cf["kill_condition_triggered"])
            self.assertTrue(cf["all_passed"])
            self.assertEqual(len(summary["counterfactual_results"]), 60)

            fm = summary["fork_multiplicity_summary"]
            self.assertEqual(fm["card_id"], "Card-B")
            self.assertEqual(fm["positive_base_cases"], 20)
            self.assertEqual(fm["scenarios_per_case"], 3)
            self.assertEqual(fm["total_fork_runs"], 60)
            self.assertEqual(fm["passed_runs"], 60)
            self.assertEqual(fm["adversarial_runs"], 40)
            self.assertEqual(fm["positive_control_runs"], 20)
            self.assertEqual(fm["pre_card_b_adversarial_rejected"], 0)
            self.assertEqual(fm["card_b_adversarial_rejected"], 20)
            self.assertEqual(fm["card_b_adversarial_hard_rejected"], 20)
            self.assertEqual(fm["card_b_adversarial_advisory_flagged"], 20)
            self.assertEqual(fm["card_b_adversarial_detected"], 40)
            self.assertEqual(fm["card_b_positive_control_accepted"], 20)
            self.assertEqual(fm["card_b_overblocking_rate"], 0.0)
            self.assertFalse(fm["kill_condition_triggered"])
            self.assertTrue(fm["all_passed"])
            self.assertEqual(len(summary["fork_multiplicity_results"]), 60)

            sym = summary["symmetry_audit_summary"]
            self.assertEqual(sym["card_id"], "Card-C")
            self.assertEqual(sym["false_abstention_detection_rate"], 1.0)
            self.assertEqual(sym["unjustified_downgrade_detection_rate"], 1.0)
            self.assertEqual(sym["evidence_of_absence_detection_rate"], 1.0)
            self.assertEqual(sym["boilerplate_overhedging_detection_rate"], 1.0)
            self.assertEqual(sym["rejected_underclaim_detection_rate"], 1.0)
            self.assertEqual(sym["calibrated_false_alarm_rate"], 0.0)
            self.assertEqual(sym["non_blocking_export_preserved_rate"], 1.0)
            self.assertTrue(sym["all_five_hooks_verified"])
            self.assertTrue(sym["all_passed"])

            paired = summary["paired_sensitivity_summary"]
            self.assertEqual(paired["total_pairs"], 6)
            self.assertEqual(paired["passed_pairs"], 6)
            self.assertEqual(paired["strong_twins_accepted"], 6)
            self.assertEqual(paired["weak_twins_rejected"], 4)
            self.assertEqual(paired["weak_twins_advisory_flagged"], 2)
            self.assertEqual(paired["weak_twins_detected"], 6)
            self.assertEqual(paired["paired_evidence_sensitivity_concordance"], 1.0)
            self.assertTrue(paired["all_passed"])

            ho = summary["heldout_summary"]
            self.assertTrue(ho["leakage_strict_passed"])
            self.assertEqual(ho["heldout_lexical_overlap_count"], 0)
            self.assertEqual(ho["realistic_controls_total"], 24)
            self.assertEqual(ho["realistic_controls_false_rejections"], 0)
            self.assertEqual(ho["adversarial_caught_mechanically_hard"], 6)
            self.assertEqual(ho["adversarial_uncaught_without_llm_or_p1"], 4)
            self.assertEqual(ho["adversarial_flagged_lexical_advisory_only"], 2)
            self.assertEqual(ho["adversarial_expectations_verified"], 10)
            self.assertFalse(ho["all_passed"])  # Frozen v2 expected six uncaught cases.
            self.assertTrue(ho["regression_all_passed"])
            self.assertTrue(summary["text_advisory_qualification"]["summary"]["all_passed"])

            meta = summary["metamorphic_summary"]
            self.assertEqual(meta["total_transforms"], 12)
            self.assertEqual(meta["passed_transforms"], 12)
            self.assertEqual(meta["invariance_rate"], 1.0)
            self.assertEqual(meta["false_advisory_count"], 0)
            self.assertTrue(meta["all_passed"])

            lin = summary["lineage_window_summary"]
            self.assertEqual(lin["total_specs"], 4)
            self.assertEqual(lin["passed_specs"], 4)
            self.assertTrue(lin["synthetic_lineage_blocked"])
            self.assertTrue(lin["cli_derived_from_synthetic_blocked"])
            self.assertTrue(lin["hash_verified_unread_binary_accepted"])
            self.assertTrue(lin["tampered_binary_ancestor_blocked"])
            self.assertTrue(lin["chunked_window_head_tail_accepted"])
            self.assertTrue(lin["chunked_window_tail_contradiction_caught"])
            self.assertTrue(lin["unanchored_large_text_blocked"])
            self.assertEqual(lin["synthetic_lineage_blocking_rate"], 1.0)
            self.assertEqual(lin["chunked_window_head_tail_recall"], 1.0)
            self.assertTrue(lin["all_passed"])

            dims = summary["metric_dimensions"]
            self.assertEqual(dims["overstatement_rejection_rate"], 1.0)
            self.assertEqual(dims["false_abstention_detection_rate"], 1.0)
            self.assertEqual(dims["unjustified_downgrade_detection_rate"], 1.0)
            self.assertEqual(dims["known_valid_retention_rate"], 1.0)
            self.assertEqual(dims["equal_coverage_accuracy"], 1.0)
            self.assertEqual(dims["paired_evidence_sensitivity_concordance"], 1.0)
            self.assertEqual(dims["synthetic_lineage_blocking_rate"], 1.0)
            self.assertEqual(dims["chunked_window_head_tail_recall"], 1.0)
            self.assertEqual(dims["calibrated_false_alarm_rate"], 0.0)
            self.assertEqual(dims["live_llm_eval_status"], "not_run")

            self.assertTrue(summary["all_passed"])
            self.assertEqual(summary["external_llm_status"], "not_run")

            exported = stage0.export_prompts(suite_path, eval_dir / "prompts")
            self.assertEqual(exported["packet_count"], 40)
            self.assertEqual(exported["exploratory_packet_count"], 9)
            self.assertEqual(exported["counterfactual_packet_count"], 60)
            self.assertEqual(exported["fork_multiplicity_packet_count"], 60)
            self.assertEqual(exported["symmetry_packet_count"], 30)
            self.assertEqual(exported["paired_packet_count"], 12)
            self.assertEqual(exported["paired_pair_count"], 6)
            self.assertEqual(exported["heldout_realistic_control_packet_count"], 24)
            self.assertEqual(exported["heldout_adversarial_paraphrase_packet_count"], 12)
            self.assertEqual(exported["metamorphic_packet_count"], 12)
            self.assertEqual(exported["arms"], ["A_baseline", "B_compact", "B_full", "E_full_l2_workflow"])
            self.assertEqual(exported["external_llm_status"], "not_run")
            out_file = Path(exported["output_file"])
            self.assertTrue(out_file.is_file())
            packets_payload = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(set(packets_payload["packets"][0]["arms"].keys()), {"A_baseline", "B_compact", "B_full", "E_full_l2_workflow"})
            self.assertEqual(len(packets_payload["exploratory_packets"]), 9)
            self.assertEqual(len(packets_payload["counterfactual_packets"]), 60)
            self.assertEqual(len(packets_payload["fork_multiplicity_packets"]), 60)
            self.assertEqual(len(packets_payload["symmetry_packets"]), 30)
            self.assertEqual(len(packets_payload["paired_packets"]), 12)
            self.assertEqual(len(packets_payload["heldout_realistic_control_packets"]), 24)
            self.assertEqual(len(packets_payload["heldout_adversarial_paraphrase_packets"]), 12)
            self.assertEqual(len(packets_payload["metamorphic_packets"]), 12)
            self.assertIn("scoring_rubric_metrics", packets_payload)
            self.assertEqual(packets_payload["scoring_rubric_metrics"]["live_llm_eval_status"], "not_run")

            psb = packets_payload["policy_size_bytes"]
            self.assertLess(psb["B_compact_agents_block_bytes"], 10240)
            self.assertGreater(psb["B_compact_l2_reference_skill_bytes"], 0)
            self.assertGreater(psb["B_full_policy_bytes"], psb["B_compact_agents_block_bytes"])
            self.assertGreater(psb["E_full_l2_workflow_skill_bytes"], 0)

            sys_prompts = packets_payload["arm_system_prompts"]
            self.assertEqual(
                set(sys_prompts.keys()),
                {"A_baseline", "B_compact_l1", "B_compact_l2", "B_full", "E_full_l2_workflow"},
            )
            self.assertIn("L1-Explore", sys_prompts["B_compact_l1"])
            self.assertIn("审查者隔离配方", sys_prompts["B_compact_l2"])
            self.assertIn("审查者隔离配方", sys_prompts["B_full"])
            self.assertIn("parrhesia_workflow", sys_prompts["E_full_l2_workflow"])
            self.assertIn("九个设计包", sys_prompts["E_full_l2_workflow"])
            self.assertIn("反空转机械门控", sys_prompts["B_full"])
            self.assertEqual(packets_payload["policy_layout"], "layered-v1")
            self.assertEqual(len(packets_payload["policy_source_files"]), 5)
            self.assertEqual(psb["B_full_policy_bytes"], len(sys_prompts["B_full"].encode("utf-8")))
            self.assertEqual(psb["E_full_l2_workflow_skill_bytes"], len(sys_prompts["E_full_l2_workflow"].encode("utf-8")))

            leak_pattern = re.compile(
                r"Target classification|Expected calibrated|expected_error=|expected_calibrated_mode=|expected_verdict|"
                r"templates/AGENTS|skills/parrhesia|Evidence \(|"
                r"F1_hidden|F2_unadjusted|F3_calibrated|P1_null|P2_outcome|P3_synthetic|"
                r"U1_false_abstention|U1b_unjustified_downgrade|U2_evidence_of_absence|U3_boilerplate_overhedging|"
                r"U4_rejected_underclaim_finding|PAIR-0\d-(?:STRONG|WEAK)|strong_twin|weak_twin"
            )
            for section in (
                "packets",
                "exploratory_packets",
                "counterfactual_packets",
                "fork_multiplicity_packets",
                "symmetry_packets",
                "paired_packets",
                "heldout_realistic_control_packets",
                "heldout_adversarial_paraphrase_packets",
                "metamorphic_packets",
            ):
                for pkt in packets_payload[section]:
                    self.assertEqual(set(pkt["arms"].keys()), {"A_baseline", "B_compact", "B_full", "E_full_l2_workflow"})
                    label_id = pkt.get("case_code") or pkt.get("run_id") or pkt.get("pair_code") or pkt.get("transform_id")
                    for arm_name, prompt_text in pkt["arms"].items():
                        self.assertIsNone(
                            leak_pattern.search(prompt_text),
                            msg=f"Unexpected ground-truth or path leak in {section}/{label_id}/{arm_name}",
                        )
                        if arm_name != "A_baseline":
                            self.assertIn("=== POLICY ===", prompt_text)
                            self.assertIn("L1-Explore", prompt_text)

            for pkt in packets_payload["packets"]:
                self.assertIn("expected_target", pkt)
            for pkt in packets_payload["counterfactual_packets"]:
                self.assertIn("expected_rubber_stamp_error", pkt)
                self.assertIn("expected_calibrated_verdict", pkt)
            for pkt in packets_payload["fork_multiplicity_packets"]:
                self.assertIn("expected_rubber_stamp_error", pkt)
                self.assertIn("expected_calibrated_mode", pkt)
            for pkt in packets_payload["symmetry_packets"]:
                self.assertIn("expected_target", pkt)
            for pkt in packets_payload["paired_packets"]:
                self.assertIn("expected_target", pkt)
        finally:
            shutil.rmtree(eval_dir, ignore_errors=True)

    def test_card_a_counterfactual_evidence_sensitivity_gates(self):
        # 1. Numeric-only null perturbation (without verbal negative phrase) blocked by unanchored_effect_estimate
        self.cid = self.engine.dispatch(
            "create_case",
            {"question": "Does B1 predict progression?", "draft": "Draft", "writer_context_id": "writer"},
        )["case_id"]
        (self.root / "null_num.txt").write_text(
            "Observational cohort analysis (N=420 patients, 12-month follow-up): adjusted HR = 1.00 (95% CI 0.82 to 1.22, p = 0.88).\n",
            encoding="utf-8",
        )
        self.ev = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "null_num.txt",
                "provenance": "observed",
                "kind": "observation",
                "quote": "Observational cohort analysis (N=420 patients, 12-month follow-up): adjusted HR = 1.00",
                "location": "line 1",
            },
        )["evidence_id"]
        c_num = self.claim("association", "adjusted", "observational")
        c_num["text"] = "In 420 patients, B1 is associated with progression (HR = 1.62, 95% CI 1.21 to 2.16)."
        payload_num = self.reviewed(c_num)
        payload_num["decisions"][0]["revised_text"] = c_num["text"]
        self.error("unanchored_effect_estimate", "submit_adjudication", payload_num)
        # Flipping verdict to unsupported succeeds on the same case
        payload_num["decisions"][0]["verdict"] = "unsupported"
        payload_num["decisions"][0]["revised_text"] = "In 420 patients, adjusted HR was 1.00 (95% CI 0.82 to 1.22), showing no association."
        self.engine.dispatch("submit_adjudication", payload_num)

        # 2. Verbal null / outcome-stripped text emits non-blocking lexical advisory (while numeric mismatch remains blocked)
        self.cid = self.engine.dispatch(
            "create_case",
            {"question": "Outcome collected?", "draft": "Draft", "writer_context_id": "writer"},
        )["case_id"]
        (self.root / "pending.txt").write_text(
            "Observational cohort protocol (N=420 patients): outcome data not yet collected; primary results pending.\n",
            encoding="utf-8",
        )
        self.ev = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "pending.txt",
                "provenance": "observed",
                "kind": "observation",
                "quote": "Observational cohort protocol (N=420 patients): outcome data not yet collected",
                "location": "line 1",
            },
        )["evidence_id"]
        c_pend = self.claim("association", "unadjusted", "observational")
        c_pend["text"] = "In 420 patients, observational cohort protocol shows positive association."
        payload_pend = self.reviewed(c_pend)
        payload_pend["decisions"][0]["revised_text"] = c_pend["text"]
        res_pend = self.engine.dispatch("submit_adjudication", payload_pend)
        self.assertEqual(res_pend["state"], "adjudicated")
        self.assertIn(
            ("possible_outcome_pending_text", "outcome_stripped_or_pending_evidence"),
            {(a["hook_code"], a["detail_code"]) for a in res_pend["symmetry_audit"]["lexical_advisories"]},
        )

        # 3. Synthetic simulation text emits non-blocking lexical advisory, while synthetic provenance remains hard-blocked
        self.cid = self.engine.dispatch(
            "create_case",
            {"question": "Empirical or synthetic?", "draft": "Draft", "writer_context_id": "writer"},
        )["case_id"]
        (self.root / "syn_sim.txt").write_text(
            "Synthetic simulation run (Monte Carlo toy dataset, no empirical observations): N=420, HR = 1.62 (95% CI 1.21 to 2.16).\n",
            encoding="utf-8",
        )
        self.ev = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "syn_sim.txt",
                "provenance": "observed",
                "kind": "observation",
                "quote": "Synthetic simulation run (Monte Carlo toy dataset, no empirical observations): N=420, HR = 1.62",
                "location": "line 1",
            },
        )["evidence_id"]
        c_syn = self.claim("association", "adjusted", "observational")
        c_syn["text"] = "In N=420, HR = 1.62 (95% CI 1.21 to 2.16)."
        payload_syn = self.reviewed(c_syn)
        payload_syn["decisions"][0]["revised_text"] = c_syn["text"]
        res_syn = self.engine.dispatch("submit_adjudication", payload_syn)
        self.assertEqual(res_syn["state"], "adjudicated")
        self.assertIn(
            ("possible_evidence_kind_mismatch", "synthetic_source_declared_as_empirical"),
            {(a["hook_code"], a["detail_code"]) for a in res_syn["symmetry_audit"]["lexical_advisories"]},
        )

    def test_record_execution_event_scopes_forks_by_claim_id_and_run_group(self):
        # 1. record_execution_event isolates fork_index per claim_id / run_group while keeping case_exec_count global
        m1 = self.engine.record_execution_event(
            self.cid, {"card_id": "e1", "claim_id": "C1", "command": "cmd1", "exit_status": 0}
        )
        m2 = self.engine.record_execution_event(
            self.cid, {"card_id": "e2", "claim_id": "C2", "command": "cmd2", "exit_status": 0}
        )
        m3 = self.engine.record_execution_event(
            self.cid, {"card_id": "e3", "run_group": "grp-a", "command": "cmd3", "exit_status": 0}
        )
        m4 = self.engine.record_execution_event(
            self.cid, {"card_id": "e4", "claim_id": "C1", "command": "cmd4", "exit_status": 0}
        )
        self.assertEqual((m1["fork_index"], m1["scoped_exec_count"], m1["case_exec_count"], m1["multiplicity_required"]), (1, 1, 1, False))
        self.assertEqual((m2["fork_index"], m2["scoped_exec_count"], m2["case_exec_count"], m2["multiplicity_required"]), (1, 1, 2, False))
        self.assertEqual((m3["fork_index"], m3["scoped_exec_count"], m3["case_exec_count"], m3["multiplicity_required"]), (1, 1, 3, False))
        self.assertEqual((m4["fork_index"], m4["scoped_exec_count"], m4["case_exec_count"], m4["multiplicity_required"]), (2, 2, 4, True))

        # 2. End-to-end 2-claim case via CLI record-exec (default unique log paths + --claim-id isolation)
        cid2 = self.engine.dispatch(
            "create_case",
            {"question": "Scoped multi-claim execution?", "draft": "Draft", "writer_context_id": "writer-scoped"},
        )["case_id"]
        outs = []
        for idx, cid_claim in enumerate(("C1", "C2"), start=1):
            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main(
                    [
                        "record-exec",
                        "--workspace",
                        str(self.root),
                        "--case-id",
                        cid2,
                        "--claim-id",
                        cid_claim,
                        "--card-id",
                        f"exec-{cid_claim}",
                        "--kind",
                        "auto",
                        "--",
                        sys.executable,
                        "-c",
                        f"print('claim-{cid_claim}-metric={idx}')",
                    ]
                )
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue().decode("utf-8"))
            self.assertEqual(out["fork_index"], 1)
            self.assertEqual(out["case_exec_count"], idx)
            self.assertFalse(out["multiplicity_required"])
            self.assertEqual(out["claim_id"], cid_claim)
            outs.append(out)
        self.assertNotEqual(outs[0]["log_path"], outs[1]["log_path"])

        ev1 = outs[0]["evidence"]["evidence_id"]
        ev2 = outs[1]["evidence"]["evidence_id"]
        c1 = json.loads(json.dumps(self.claim("computational", "benchmark_measured", "ml")).replace(self.ev, ev1))
        c1["id"] = "C1"
        c1["text"] = f"Benchmark execution for C1 exited 0 at {outs[0]['log_path']}."
        c1["evidence_ids"] = [ev1]
        c1["provenance_cards"]["execution"] = [outs[0]["execution_card"]]

        c2 = json.loads(json.dumps(self.claim("computational", "benchmark_measured", "ml")).replace(self.ev, ev2))
        c2["id"] = "C2"
        c2["text"] = f"Benchmark execution for C2 exited 0 at {outs[1]['log_path']}."
        c2["evidence_ids"] = [ev2]
        c2["provenance_cards"]["execution"] = [outs[1]["execution_card"]]

        self.engine.dispatch("set_ledger", {"case_id": cid2, "claims": [c1, c2]})
        frozen2 = self.engine.dispatch("freeze", {"case_id": cid2})
        for role in ("overclaim", "underclaim"):
            pkt = self.engine.dispatch("review_packet", {"case_id": cid2, "role": role})
            self.engine.dispatch(
                "submit_review",
                {
                    "case_id": cid2,
                    "role": role,
                    "packet_id": pkt["packet_id"],
                    "input_digest": frozen2["input_digest"],
                    "reviewer": {"context_id": f"{role}-scoped", "model": "fixture"},
                    "covered_claim_ids": ["C1", "C2"],
                    "claim_stances": [
                        {"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Fixture", "evidence_ids": []},
                        {"claim_id": "C2", "stance": "insufficient_evidence", "rationale": "Fixture", "evidence_ids": []},
                    ],
                    "unread_evidence_ids": [],
                    "findings": [],
                },
            )
        adj = self.engine.dispatch("adjudication_packet", {"case_id": cid2})
        res = self.engine.dispatch(
            "submit_adjudication",
            {
                "case_id": cid2,
                "adjudication_id": adj["adjudication_id"],
                "input_digest": adj["input_digest"],
                "adjudicator": {"context_id": "writer-scoped", "model": "fixture"},
                "unread_evidence_ids": [],
                "dispositions": [],
                "decisions": [
                    {
                        "claim_id": "C1",
                        "claim_basis": "empirical",
                        "claim_type": "computational",
                        "evidence_level": "benchmark_measured",
                        "scope": c1["scope"],
                        "verdict": "insufficient_evidence",
                        "revised_text": c1["text"],
                        "rationale": "C1 command ran; independent benchmark evidence is missing",
                        "evidence_ids": [ev1],
                        "confidence": "low",
                        "confidence_reason": "Synthetic",
                        "boundary": c1["scope"],
                        "reversal_condition": "Different run changes result",
                    },
                    {
                        "claim_id": "C2",
                        "claim_basis": "empirical",
                        "claim_type": "computational",
                        "evidence_level": "benchmark_measured",
                        "scope": c2["scope"],
                        "verdict": "insufficient_evidence",
                        "revised_text": c2["text"],
                        "rationale": "C2 command ran; independent benchmark evidence is missing",
                        "evidence_ids": [ev2],
                        "confidence": "low",
                        "confidence_reason": "Synthetic",
                        "boundary": c2["scope"],
                        "reversal_condition": "Different run changes result",
                    },
                ],
            },
        )
        self.assertEqual(res["state"], "adjudicated")


if __name__ == "__main__":
    unittest.main()
