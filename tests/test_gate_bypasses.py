"""Regression probes for bypasses found during the 2026-10-19 local audit."""
from contextlib import closing
import json
import sqlite3
import unittest

import test_gates as fixtures
from parrhesia.contracts import ContractError


class GateBypassTests(unittest.TestCase):
    setUp = fixtures.GateTests.setUp
    tearDown = fixtures.GateTests.tearDown
    register = fixtures.GateTests.register
    assessment = fixtures.GateTests.assessment
    claim = fixtures.GateTests.claim
    save = fixtures.GateTests.save
    reviewed = fixtures.GateTests.reviewed
    error = fixtures.GateTests.error
    review_payload = fixtures.GateTests.review_payload
    finding = fixtures.GateTests.finding

    def test_new_legacy_case_cannot_disable_current_gates(self):
        with closing(sqlite3.connect(self.engine.database)) as db:
            before = db.execute("SELECT count(*) FROM cases").fetchone()[0]
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch("create_case", {"question": "Bypass", "draft": "Bypass", "schema_version": 1})
        self.assertEqual(caught.exception.code, "legacy_creation_disabled")
        with closing(sqlite3.connect(self.engine.database)) as db:
            self.assertEqual(before, db.execute("SELECT count(*) FROM cases").fetchone()[0])

    def test_conditional_stance_needs_a_real_condition(self):
        payload = self.review_payload(self.claim())
        stance = payload["claim_stances"][0]
        stance["stance"] = "partially_supported"
        self.error("missing_stance_condition", "submit_review", payload)
        for condition in ("UNKNOWN", "\u200b" * 20):
            stance["condition"] = condition
            self.error("missing_stance_condition", "submit_review", payload)
        stance["condition"] = "Only as a literal description of the supplied fixture"
        result = self.engine.dispatch("submit_review", payload)
        self.assertEqual(result["review"]["claim_stances"][0]["condition"], stance["condition"])

    def test_preexisting_anchor_is_not_incorporation(self):
        claim = self.claim()
        claim["text"] = "Shared unchanged paragraph. Original conclusion."
        finding = self.finding()
        finding["proposed_text"] = "Shared unchanged paragraph. Proposed replacement conclusion."
        payload = self.reviewed(claim, finding)
        payload["decisions"][0]["revised_text"] = claim["text"] + " Unrelated addition."
        disp = payload["dispositions"][0]
        disp.update(disposition="partial", condition="Only part adopted", revised_text_quote="Shared unchanged paragraph.")
        self.error("finding_not_incorporated", "submit_adjudication", payload)
        payload["decisions"][0]["revised_text"] = finding["proposed_text"]
        disp["revised_text_quote"] = "Proposed replacement conclusion."
        self.engine.dispatch("submit_adjudication", payload)

    def test_repeated_revision_anchor_is_not_unique(self):
        finding = self.finding()
        payload = self.reviewed(self.claim(), finding)
        payload["decisions"][0]["revised_text"] = finding["proposed_text"] * 2
        self.error("finding_not_incorporated", "submit_adjudication", payload)

    def test_invisible_quote_cannot_satisfy_minimum_length(self):
        (self.root / "invisible.txt").write_text("x" + "\u200b" * 12, encoding="utf-8")
        self.error("invalid_quote", "register_evidence", {"case_id": self.cid, "path": "invisible.txt", "kind": "observation", "provenance": "reported", "quote": "\u200b" * 12})

    def test_conditional_decision_and_adoption_reject_placeholder_conditions(self):
        payload = self.reviewed(self.claim(), self.finding())
        payload["decisions"][0].update(verdict="partially_supported", condition="UNKNOWN")
        self.error("invalid_condition", "submit_adjudication", payload)
        payload["decisions"][0]["condition"] = "Only describes the supplied fixture"
        payload["dispositions"][0].update(disposition="partial", condition="\u200b" * 12)
        self.error("invalid_condition", "submit_adjudication", payload)
        payload["dispositions"][0]["condition"] = "Adopt wording only within the fixture scope"
        self.engine.dispatch("submit_adjudication", payload)

    def test_unknown_contract_versions_never_fall_back_to_legacy(self):
        original = self.engine.dispatch("get_case", {"case_id": self.cid})
        for field, value in (("gate_version", 2), ("gate_version", True), ("schema_version", 3), ("schema_version", True)):
            case = {**original, field: value}
            case.pop("events")
            with closing(sqlite3.connect(self.engine.database)) as db:
                db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case), self.cid)); db.commit()
            with self.subTest(field=field, value=value):
                with self.assertRaises(ContractError) as caught:
                    self.engine.dispatch("get_case", {"case_id": self.cid})
                self.assertEqual(caught.exception.code, "unsupported_contract_version")

    def test_issue1_unbacked_pass_trivial_reason_uncited_check_quote_link_and_kind_contradiction(self):
        from parrhesia.claims import validate_support
        from parrhesia.gates import ceiling

        # 1a. Design or statistical check with status="pass" but empty evidence_ids is blocked
        c_unbacked = self.claim("association", "adjusted", "observational")
        c_unbacked["design_packages"][0]["checks"]["confounding_selection"]["evidence_ids"] = []
        self.assertEqual(ceiling(c_unbacked)["allowed_levels"], ["unassessed"])

        c_unbacked_stat = self.claim("association", "adjusted", "observational")
        c_unbacked_stat["statistical_report"]["estimate_uncertainty"]["evidence_ids"] = []
        self.assertEqual(ceiling(c_unbacked_stat)["allowed_levels"], ["unassessed"])

        # 1b. Trivial rubber-stamp reasons ("ok", "pass", "yes", "done") on pass checks are blocked
        for bad_reason in ("ok", "pass", "yes", "done"):
            c_trivial = self.claim("association", "adjusted", "observational")
            c_trivial["design_packages"][0]["checks"]["confounding_selection"]["reason"] = bad_reason
            self.assertEqual(ceiling(c_trivial)["allowed_levels"], ["unassessed"])

            c_trivial_fixed = self.claim("association", "adjusted", "observational")
            c_trivial_fixed["checks"]["quality"]["reason"] = bad_reason
            self.assertEqual(ceiling(c_trivial_fixed)["allowed_levels"], ["unassessed"])

        c_trivial_causal = self.claim("causal_effect", "identified_under_assumptions", "randomized")
        c_trivial_causal["causal_basis"]["assumptions"][0]["reason"] = "ok"
        with self.assertRaises(ContractError) as caught:
            validate_support({**c_trivial_causal, "verdict": "supported"}, c_trivial_causal)
        self.assertEqual(caught.exception.code, "causal_identification_gap")

        # 1c. Positive decision omitting evidence_ids that back required passing design/stat checks is rejected
        ev2 = self.register("observation")
        c_uncited = self.claim("association", "adjusted", "observational")
        c_uncited["evidence_ids"].append(ev2)
        c_uncited["design_packages"][0]["checks"]["confounding_selection"]["evidence_ids"] = [ev2]
        payload = self.reviewed(c_uncited)
        payload["decisions"][0]["evidence_ids"] = [self.ev]
        self.error("uncited_check_evidence", "submit_adjudication", payload)
        payload["decisions"][0]["evidence_ids"] = [self.ev, ev2]
        self.engine.dispatch("submit_adjudication", payload)

        # 1d. Arbitrary 12+ char unique quote unrelated to the claim is rejected with unlinked_evidence_quote
        self.cid = self.engine.dispatch("create_case", {"question": "Quote relevance?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
        (self.root / "unrelated_quote.txt").write_text(
            "Header metadata: archived internal working file on Tuesday morning.\n"
            "Primary result: systolic pressure reduction 8.5 mmHg (95% CI 5.6 to 11.4).\n",
            encoding="utf-8",
        )
        ev_unrelated = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "unrelated_quote.txt",
                "provenance": "observed",
                "kind": "observation",
                "quote": "Header metadata: archived internal working",
                "location": "line 1",
            },
        )["evidence_id"]
        self.ev = ev_unrelated
        c_unlinked = self.claim("association", "unadjusted", "observational")
        c_unlinked["text"] = "Treatment lowers systolic pressure by 8.5 mmHg."
        c_unlinked["effect"] = {"estimate": "8.5 mmHg", "uncertainty": "5.6 to 11.4"}
        c_unlinked["scope"] = "Outpatient hypertension cohort"
        c_unlinked["contribution"] = "Quantifies blood pressure association"
        payload_unlinked = self.reviewed(c_unlinked)
        payload_unlinked["decisions"][0]["revised_text"] = "Treatment is associated with an 8.5 mmHg systolic reduction."
        self.error("unlinked_evidence_quote", "submit_adjudication", payload_unlinked)

        # 1e. Observational study text registered as kind="intervention" is rejected with contradictory_evidence_kind
        self.cid = self.engine.dispatch("create_case", {"question": "Kind contradiction?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
        (self.root / "obs_as_int.txt").write_text(
            "Observational cohort analysis (non-randomized, N=420): adjusted HR = 1.62.\n",
            encoding="utf-8",
        )
        ev_contra = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "obs_as_int.txt",
                "provenance": "observed",
                "kind": "intervention",
                "quote": "Observational cohort analysis (non-randomized, N=420)",
                "location": "line 1",
            },
        )["evidence_id"]
        self.ev = ev_contra
        c_contra = self.claim("causal_effect", "identified_under_assumptions", "randomized")
        c_contra["text"] = "Cohort HR = 1.62 in N=420."
        payload_contra = self.reviewed(c_contra)
        self.error("contradictory_evidence_kind", "submit_adjudication", payload_contra)

    def test_issue2_level_differentiation_across_association_causal_theory_qualitative_synthesis(self):
        from parrhesia.claims import validate_support
        from parrhesia.gates import ceiling

        na = {"status": "not_applicable", "reason": "Not evaluated at this stage", "evidence_ids": []}

        # 2a. association: unadjusted < adjusted < robust_association
        c_assoc = self.claim("association", "unadjusted", "observational")
        for k in ("confounding_selection", "missingness", "robustness"):
            c_assoc["design_packages"][0]["checks"][k] = dict(na)
        for k in ("model_assumptions", "comparisons_baselines", "robustness_limits"):
            c_assoc["statistical_report"][k] = dict(na)
        self.assertEqual(ceiling(c_assoc)["allowed_levels"], ["unassessed", "unadjusted"])

        c_assoc["design_packages"][0]["checks"]["confounding_selection"] = self.assessment("pass")
        c_assoc["statistical_report"]["model_assumptions"] = self.assessment("pass")
        c_assoc["statistical_report"]["comparisons_baselines"] = self.assessment("pass")
        self.assertEqual(ceiling(c_assoc)["allowed_levels"], ["unassessed", "unadjusted", "adjusted"])

        c_assoc["design_packages"][0]["checks"]["missingness"] = self.assessment("pass")
        c_assoc["design_packages"][0]["checks"]["robustness"] = self.assessment("pass")
        c_assoc["statistical_report"]["robustness_limits"] = self.assessment("pass")
        self.assertEqual(
            ceiling(c_assoc)["allowed_levels"],
            ["unassessed", "unadjusted", "adjusted", "robust_association"],
        )

        # 2b. causal_effect: identified_under_assumptions < sensitivity_supported
        c_causal = self.claim("causal_effect", "identified_under_assumptions", "quasi_experimental")
        c_causal["causal_basis"]["falsification_sensitivity"][0] = {
            "name": "Bandwidth sensitivity",
            "status": "unknown",
            "reason": "Sensitivity check not yet run",
            "evidence_ids": [],
        }
        c_causal["design_packages"][0]["checks"]["sensitivity"] = dict(na)
        c_causal["statistical_report"]["robustness_limits"] = dict(na)
        self.assertEqual(
            ceiling(c_causal)["allowed_levels"],
            ["unassessed", "unidentified", "identified_under_assumptions"],
        )
        validate_support({**c_causal, "verdict": "supported"}, c_causal)
        with self.assertRaises(ContractError) as caught:
            validate_support({**c_causal, "evidence_level": "sensitivity_supported", "verdict": "supported"}, c_causal)
        self.assertEqual(caught.exception.code, "causal_identification_gap")

        # 2c. theory: proved_under_assumptions < independently_checked
        c_theory = self.claim("theory", "proved_under_assumptions", "theory")
        c_theory["design_packages"][0]["checks"]["boundary_counterexamples"] = dict(na)
        c_theory["design_packages"][0]["checks"]["independent_check"] = dict(na)
        self.assertEqual(
            ceiling(c_theory)["allowed_levels"],
            ["unassessed", "conjectured", "proved_under_assumptions"],
        )
        c_theory["design_packages"][0]["checks"]["boundary_counterexamples"] = self.assessment("pass")
        c_theory["design_packages"][0]["checks"]["independent_check"] = self.assessment("pass")
        self.assertEqual(
            ceiling(c_theory)["allowed_levels"],
            ["unassessed", "conjectured", "proved_under_assumptions", "independently_checked"],
        )

        # 2d. qualitative: situated_description < interpretation_audited < triangulated
        c_qual = self.claim("qualitative", "situated_description", "qualitative")
        for k in ("reflexivity_ethics", "analysis_audit", "negative_cases_transfer"):
            c_qual["design_packages"][0]["checks"][k] = dict(na)
        c_qual["statistical_report"]["robustness_limits"] = dict(na)
        self.assertEqual(ceiling(c_qual)["allowed_levels"], ["unassessed", "situated_description"])
        c_qual["design_packages"][0]["checks"]["reflexivity_ethics"] = self.assessment("pass")
        c_qual["design_packages"][0]["checks"]["analysis_audit"] = self.assessment("pass")
        self.assertEqual(
            ceiling(c_qual)["allowed_levels"],
            ["unassessed", "situated_description", "interpretation_audited"],
        )
        c_qual["design_packages"][0]["checks"]["negative_cases_transfer"] = self.assessment("pass")
        c_qual["statistical_report"]["robustness_limits"] = self.assessment("pass")
        self.assertEqual(
            ceiling(c_qual)["allowed_levels"],
            ["unassessed", "situated_description", "interpretation_audited", "triangulated"],
        )

        # 2e. synthesis: mapped < critically_appraised < synthesized_with_uncertainty
        c_syn = self.claim("synthesis", "mapped", "evidence_synthesis")
        for k in ("bias_dependence", "heterogeneity", "certainty_missing_studies"):
            c_syn["design_packages"][0]["checks"][k] = dict(na)
        for k in ("estimate_uncertainty", "model_assumptions", "comparisons_baselines", "robustness_limits"):
            c_syn["statistical_report"][k] = dict(na)
        self.assertEqual(ceiling(c_syn)["allowed_levels"], ["unassessed", "mapped"])
        c_syn["design_packages"][0]["checks"]["bias_dependence"] = self.assessment("pass")
        c_syn["design_packages"][0]["checks"]["heterogeneity"] = self.assessment("pass")
        c_syn["statistical_report"]["estimate_uncertainty"] = self.assessment("pass")
        c_syn["statistical_report"]["model_assumptions"] = self.assessment("pass")
        self.assertEqual(ceiling(c_syn)["allowed_levels"], ["unassessed", "mapped", "critically_appraised"])
        c_syn["design_packages"][0]["checks"]["certainty_missing_studies"] = self.assessment("pass")
        c_syn["statistical_report"]["comparisons_baselines"] = self.assessment("pass")
        c_syn["statistical_report"]["robustness_limits"] = self.assessment("pass")
        self.assertEqual(
            ceiling(c_syn)["allowed_levels"],
            ["unassessed", "mapped", "critically_appraised", "synthesized_with_uncertainty"],
        )

    def test_issue3_essential_design_checks_enforced_for_theory_qualitative_and_synthesis(self):
        from parrhesia.gates import ceiling

        na = {"status": "not_applicable", "reason": "Attempted N/A bypass on core check", "evidence_ids": []}

        # Theory: marking proof as not_applicable blocks all positive theory levels
        c_theory = self.claim("theory", "proved_under_assumptions", "theory")
        c_theory["design_packages"][0]["checks"]["proof"] = dict(na)
        self.assertEqual(ceiling(c_theory)["allowed_levels"], ["unassessed", "conjectured"])

        # Qualitative: marking epistemic_position as not_applicable blocks all positive qualitative levels
        c_qual = self.claim("qualitative", "situated_description", "qualitative")
        c_qual["design_packages"][0]["checks"]["epistemic_position"] = dict(na)
        self.assertEqual(ceiling(c_qual)["allowed_levels"], ["unassessed"])

        # Evidence synthesis: marking protocol_search as not_applicable blocks all positive synthesis levels
        c_syn = self.claim("synthesis", "mapped", "evidence_synthesis")
        c_syn["design_packages"][0]["checks"]["protocol_search"] = dict(na)
        self.assertEqual(ceiling(c_syn)["allowed_levels"], ["unassessed"])

    def test_issue4_bilingual_placeholders_contradiction_phrases_and_cjk_quote_length(self):
        from parrhesia.claims import validate_support
        from parrhesia.gates import ceiling, is_contradicting_relation, meaningful, quote_status

        # 4a. Chinese and English placeholders are rejected across conditions, locations, estimands, and reasons
        for bad in (
            "未知", "无", "暂无", "待定", "待填", "见上", "同上", "如上", "略", "不适用", "不可识别",
            "TBD", "TODO", "SEE ABOVE", "SAME AS ABOVE", "N/A", "NULL", "NIL", "PENDING", "---", " [待定] ",
        ):
            self.assertFalse(meaningful(bad), f"placeholder {bad!r} should not be meaningful")

        c_est = self.claim("causal_effect", "identified_under_assumptions", "quasi_experimental")
        for bad_est in ("未知", "待定", "见上", "TBD", "see above"):
            c_est["causal_basis"]["estimand"]["treatment"] = bad_est
            self.assertEqual(ceiling(c_est)["allowed_levels"], ["unassessed", "unidentified"])
            with self.assertRaises(ContractError) as caught:
                validate_support({**c_est, "verdict": "supported"}, c_est)
            self.assertEqual(caught.exception.code, "causal_identification_gap")

        # 4b. Natural-language contradiction phrases in English and Chinese block positive ceilings
        for phrase in (
            "does not support", "Paper does not support the claimed effect", "fails to support",
            "cannot support", "contrary to hypothesis", "inconsistent with findings",
            "无法支持", "不能支持", "不足以支持该结论", "与主张矛盾", "与结论相悖", "文献证伪该机制",
        ):
            self.assertTrue(is_contradicting_relation(phrase), f"contradiction {phrase!r} should be detected")
            c_cit = self.claim("association", "adjusted", "observational")
            c_cit["provenance_cards"]["citation"] = [
                {
                    "id": "CIT1",
                    "status": "checked",
                    "evidence_ids": [self.ev],
                    "details": {
                        "locator": "doi:10.1000/test",
                        "quoted_span": "Synthetic fixture: effect 0.",
                        "support_relation": phrase,
                    },
                }
            ]
            self.assertEqual(ceiling(c_cit)["allowed_levels"], ["unassessed"])

        for non_contra in ("supports", "directly supports", "consistent with and does not contradict", "支持，且不矛盾"):
            self.assertFalse(is_contradicting_relation(non_contra))

        # 4c. Language-aware quote length: 6 CJK characters (12 units) match, <6 CJK characters fail as too_short
        self.assertEqual(quote_status("显著降低复发", "临床随访显示显著降低复发风险"), "matched")
        self.assertEqual(quote_status("显著降低", "临床随访显示显著降低复发风险"), "too_short")

    def test_issue5_ansi_terminal_logs_and_large_text_windowed_support(self):
        # 5a. ANSI-colored terminal logs from record-exec are read as text and support positive verdicts
        self.cid = self.engine.dispatch("create_case", {"question": "ANSI log?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
        ansi_log = (
            "\x1b[1;32m[PASS]\x1b[0m Regression test suite completed:\r\n"
            "\x1b[36mmetric:\x1b[0m systolic reduction 8.5 mmHg in N=120 cohort\x08\n"
        )
        (self.root / "ansi_exec.log").write_bytes(ansi_log.encode("utf-8"))
        ev_ansi = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "ansi_exec.log",
                "provenance": "observed",
                "kind": "observation",
                "quote": "systolic reduction 8.5 mmHg in N=120 cohort",
                "location": "line 2",
            },
        )["evidence_id"]
        self.ev = ev_ansi
        c_ansi = self.claim("association", "unadjusted", "observational")
        c_ansi["text"] = "Observed systolic reduction 8.5 mmHg in N=120 cohort."
        payload_ansi = self.reviewed(c_ansi)
        payload_ansi["decisions"][0]["revised_text"] = "Systolic reduction 8.5 mmHg in N=120 cohort."
        self.engine.dispatch("submit_adjudication", payload_ansi)
        ver_ansi = self.engine.dispatch("verify", {"case_id": self.cid})
        self.assertEqual(ver_ansi["status"], "pass")

        # 5b. >128 KiB text source with a unique claim-linked quote automatically extracts a readable window
        # and supports positive verdicts + export once acknowledged in unread_evidence_ids
        self.cid = self.engine.dispatch("create_case", {"question": "Large log?", "draft": "Draft", "writer_context_id": "writer"})["case_id"]
        large_text = ("header line\n" * 12000) + "Anchored result: mortality reduction 14.2% in N=850 patients.\n" + ("footer line\n" * 2000)
        (self.root / "large_anchored.txt").write_text(large_text, encoding="utf-8")
        ev_large = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": "large_anchored.txt",
                "provenance": "observed",
                "kind": "observation",
                "quote": "Anchored result: mortality reduction 14.2% in N=850 patients.",
                "location": "line 12001",
            },
        )["evidence_id"]
        self.ev = ev_large
        c_large = self.claim("association", "unadjusted", "observational")
        c_large["text"] = "Mortality reduction 14.2% in N=850 patients."
        self.save(c_large)
        frozen = self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            pkt = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            ev_pkt = pkt["evidence"][0]
            self.assertEqual(ev_pkt["source_text_status"], "truncated")
            self.assertTrue(ev_pkt["excerpt_window"]["quote_anchored"])
            self.assertIn("mortality reduction 14.2% in N=850 patients", ev_pkt["source_text"])
            self.engine.dispatch(
                "submit_review",
                {
                    "case_id": self.cid,
                    "role": role,
                    "packet_id": pkt["packet_id"],
                    "input_digest": frozen["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Anchored window verified", "evidence_ids": [ev_large]}],
                    "unread_evidence_ids": [ev_large],
                    "findings": [],
                },
            )
        adj_pkt = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        self.engine.dispatch(
            "submit_adjudication",
            {
                "case_id": self.cid,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": "writer", "model": "fixture"},
                "unread_evidence_ids": [ev_large],
                "dispositions": [],
                "decisions": [
                    {
                        "claim_id": "C1",
                        "claim_basis": "empirical",
                        "claim_type": "association",
                        "evidence_level": "unadjusted",
                        "scope": c_large["scope"],
                        "verdict": "supported",
                        "revised_text": "Mortality reduction 14.2% is associated with exposure in N=850 patients.",
                        "rationale": "Backed by quote-anchored window",
                        "evidence_ids": [ev_large],
                        "confidence": "medium",
                        "confidence_reason": "Windowed full-hash snapshot",
                        "boundary": "Observational only",
                        "reversal_condition": "Null association in adjusted model",
                    }
                ],
            },
        )
        exported = self.engine.dispatch("export", {"case_id": self.cid})
        self.assertEqual(exported["verification"]["status"], "pass")

    def test_issue6_substantive_disposition_incorporation_blocks_appended_or_unrelated_edits(self):
        # 6a. Keeping the original claim verbatim and appending a sentence from proposed_text is rejected
        claim = self.claim("association", "unadjusted", "observational")
        claim["text"] = "The drug universally cures all patients permanently."
        finding = self.finding()
        finding.update(
            issue="Universal permanent cure is unsupported; only short-term symptom association was observed.",
            decision_impact="Downgrade from universal cure to short-term symptom association",
            proposed_claim_type="association",
            proposed_evidence_level="unadjusted",
            proposed_scope="Outpatient cohort short-term follow-up",
            proposed_text="Short-term symptom scores were associated with exposure in the outpatient cohort; additional follow-up is noted.",
        )
        payload = self.reviewed(claim, finding)
        disp = payload["dispositions"][0]
        disp.update(
            disposition="partial",
            condition="Partially adopt qualification",
            revised_text_quote="additional follow-up is noted.",
        )
        payload["decisions"][0].update(
            claim_type="association",
            evidence_level="unadjusted",
            scope="Outpatient cohort short-term follow-up",
            revised_text="The drug universally cures all patients permanently; additional follow-up is noted.",
        )
        self.error("finding_not_incorporated", "submit_adjudication", payload)

        # 6b. Slightly tweaking original wording while retaining criticized terms ("universally", "cures", "permanently")
        # and quoting only the trailing filler clause is also rejected
        payload["decisions"][0]["revised_text"] = "This drug universally cures patients permanently; additional follow-up is noted."
        self.error("finding_not_incorporated", "submit_adjudication", payload)

        # 6c. Replacing the claim with only the unrelated trailing clause (omitting issue-linked replacement terms) is rejected
        payload["decisions"][0]["revised_text"] = "In this study, additional follow-up is noted."
        self.error("finding_not_incorporated", "submit_adjudication", payload)

        # 6d. Actually replacing the criticized overclaim with the issue-linked replacement succeeds
        payload["decisions"][0]["revised_text"] = finding["proposed_text"]
        disp["revised_text_quote"] = "Short-term symptom scores were associated with exposure"
        self.engine.dispatch("submit_adjudication", payload)


if __name__ == "__main__":
    unittest.main()
