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


if __name__ == "__main__":
    unittest.main()
