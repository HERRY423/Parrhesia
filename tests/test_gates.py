"""Adversarial local contract tests; caller metadata fixtures are not scientific results."""
from copy import deepcopy
from contextlib import closing
import json
import sqlite3
import unittest

import test_claims_v2 as fixtures
from parrhesia.core import Engine, _digest
from parrhesia.contracts import ContractError
from parrhesia.gates import ceiling, quote_status, validate_mechanical


class GateTests(unittest.TestCase):
    setUp = fixtures.ClaimsV2Tests.setUp
    tearDown = fixtures.ClaimsV2Tests.tearDown
    register = fixtures.ClaimsV2Tests.register
    assessment = fixtures.ClaimsV2Tests.assessment
    claim = fixtures.ClaimsV2Tests.claim
    save = fixtures.ClaimsV2Tests.save
    reviewed = fixtures.ClaimsV2Tests.reviewed
    error = fixtures.ClaimsV2Tests.error

    def review_payload(self, claim):
        self.save(claim)
        self.engine.dispatch("freeze", {"case_id": self.cid})
        packet = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": "overclaim"})
        return {"case_id": self.cid, "role": "overclaim", "packet_id": packet["packet_id"], "input_digest": packet["input_digest"], "reviewer": {"context_id": "overclaim", "model": "fixture"}, "covered_claim_ids": ["C1"], "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Simulated metadata", "evidence_ids": [self.ev]}], "unread_evidence_ids": [], "findings": []}

    def test_critical_unknown_and_fail_cap_levels_and_both_positive_verdicts(self):
        c = self.claim("association", "adjusted")
        c["checks"]["unit"]["status"] = "unknown"
        c["checks"]["quality"]["status"] = "fail"
        payload = self.reviewed(c)
        packet = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        self.assertEqual(packet["check_ceilings"]["C1"]["allowed_levels"], ["unassessed"])
        for verdict in ("supported", "partially_supported", "insufficient_evidence", "unsupported"):
            payload["decisions"][0].update(verdict=verdict, condition="Bounded fixture")
            self.error("critical_check_ceiling", "submit_adjudication", payload)
        payload["decisions"][0].update(verdict="insufficient_evidence", evidence_level="unassessed")
        self.engine.dispatch("submit_adjudication", payload)

    def test_selected_design_and_statistics_cannot_be_unknown_or_failed(self):
        for section in ("design", "statistics", "essential_na"):
            c = self.claim("prediction", "internally_validated", "prediction")
            if section == "design":
                c["design_packages"][0]["checks"]["splits_leakage"]["status"] = "unknown"
            elif section == "statistics":
                c["statistical_report"]["estimate_uncertainty"]["status"] = "fail"
            else:
                c["checks"]["unit"]["status"] = "not_applicable"
            with self.subTest(section=section):
                self.assertEqual(ceiling(c)["allowed_levels"], ["unassessed"])
        # Recorded text is not a claim of checked measurement or replication.
        c = self.claim(); c["checks"]["quality"]["status"] = "unknown"
        self.assertEqual(ceiling(c)["allowed_levels"], ["unassessed", "recorded"])

    def test_compatibility_rejects_cross_type_and_unearned_validation_stage(self):
        # Independent boundary examples, not generated from the implementation table.
        examples = [
            ("association", "adjusted", "observation", True),
            ("association", "adjusted", "prediction_external", False),
            ("prediction", "apparent", "prediction_external", True),
            ("prediction", "externally_validated", "prediction_internal", False),
            ("prediction", "externally_validated", "prediction_external", True),
            ("prediction", "prospectively_evaluated", "prediction_external", False),
            ("causal_effect", "identified_under_assumptions", "observation", False),
            ("causal_effect", "identified_under_assumptions", "quasi_experiment", True),
            ("mechanism", "compatible", "observation", True),
            ("mechanism", "component_tested", "observation", False),
            ("mechanism", "component_tested", "mechanistic_assay", True),
            ("mechanism", "causal_chain_tested", "mechanistic_assay", False),
            ("necessity", "bounded_test", "intervention", True),
            ("sufficiency", "bounded_test", "observation", False),
            ("synthesis", "critically_appraised", "systematic_review", True),
            ("synthesis", "critically_appraised", "observation", False),
            ("theory", "proved_under_assumptions", "theoretical_proof", True),
            ("theory", "proved_under_assumptions", "benchmark", False),
            ("qualitative", "triangulated", "qualitative_material", True),
            ("qualitative", "triangulated", "observation", False),
            ("computational", "benchmark_measured", "benchmark_external", True),
            ("computational", "externally_evaluated", "benchmark", False),
            ("engineering", "test_passed", "test_log", True),
            ("engineering", "host_accepted", "test_log", False),
            ("engineering", "user_impact", "host_acceptance", False),
            ("engineering", "user_impact", "user_outcome", True),
            ("description", "recorded", "unknown", False),
        ]
        for kind, level, source_kind, allowed in examples:
            claim = self.claim(kind, level)
            if kind in ("necessity", "sufficiency"):
                claim["causal_basis"][kind + "_test"] = self.assessment("pass")
            decision = {**claim, "verdict": "supported"}
            evidence = {self.ev: {"kind": source_kind, "provenance": "reported", "source_text_status": "complete", "source_text": "A unique fixture quote for this test.", "quote": "A unique fixture quote", "location": "line 1"}}
            with self.subTest(kind=kind, level=level, source=source_kind):
                if allowed:
                    validate_mechanical(decision, claim, evidence)
                else:
                    with self.assertRaises(ContractError) as caught:
                        validate_mechanical(decision, claim, evidence)
                    self.assertEqual(caught.exception.code, "incompatible_evidence_kind")

    def test_intervention_does_not_bypass_check_failures(self):
        self.ev = self.register("intervention")
        c = self.claim("causal_effect", "sensitivity_supported", "randomized")
        c["checks"]["quality"]["status"] = "fail"
        self.error("critical_check_ceiling", "submit_adjudication", self.reviewed(c))

    def test_quasi_experiment_causal_positive_and_recovery(self):
        self.ev = self.register("quasi_experiment")
        payload = self.reviewed(self.claim("causal_effect", "identified_under_assumptions", "quasi_experimental"))
        self.engine.dispatch("submit_adjudication", payload)
        case = Engine(self.root).dispatch("get_case", {"case_id": self.cid})
        self.assertEqual(case["adjudication"]["decisions"][0]["verdict"], "supported")
        self.assertEqual(case["scientific_validity"], "not_established_by_engine")

    def test_synthetic_mixed_with_empirical_cannot_support_empirical_positive(self):
        syn = self.register("observation", "synthetic")
        c = self.claim("association", "adjusted"); c["evidence_ids"].append(syn)
        payload = self.reviewed(c); payload["decisions"][0]["evidence_ids"].append(syn)
        for verdict in ("supported", "partially_supported"):
            payload["decisions"][0].update(verdict=verdict, condition="Cannot bypass with a condition")
            self.error("synthetic_empirical_support", "submit_adjudication", payload)

    def test_each_positive_reference_requires_quote_and_locator(self):
        unquoted = self.register(quote=None)
        unlocated = self.register(location=None)
        c = self.claim(); c["evidence_ids"] += [unquoted, unlocated]
        payload = self.reviewed(c)
        for ref in (unquoted, unlocated):
            payload["decisions"][0]["evidence_ids"] = [self.ev, ref]
            self.error("unanchored_positive_evidence", "submit_adjudication", payload)
        payload["decisions"][0]["evidence_ids"] = [self.ev]
        self.engine.dispatch("submit_adjudication", payload)

    def test_quote_minimum_uniqueness_and_overlapping_matches(self):
        for quote, source, expected in (("a b c", "a b c", "too_short"), ("x" * 12, "x" * 13, "ambiguous"), ("unique quotation", "unique quotation twice unique quotation", "ambiguous"), ("unique quotation", "different source", "mismatch"), ("独一无二的十二字以上引用文本", "独一无二的十二字以上引用文本", "matched")):
            self.assertEqual(quote_status(quote, source), expected)
        for quote in ("effect 0", "not in source quoted here"):
            self.error("invalid_quote", "register_evidence", {"case_id": self.cid, "path": "source.txt", "kind": "observation", "provenance": "reported", "quote": quote})
        (self.root / "repeated.txt").write_text("one repeated quotation one repeated quotation", encoding="utf-8")
        self.error("invalid_quote", "register_evidence", {"case_id": self.cid, "path": "repeated.txt", "kind": "observation", "provenance": "reported", "quote": "one repeated quotation"})

    def test_binary_registration_review_and_adjudication_acknowledgments(self):
        (self.root / "binary.pdf").write_bytes(b"%PDF-1.7\nnot parsed PDF contents")
        data = {"case_id": self.cid, "path": "binary.pdf", "kind": "observation", "provenance": "reported"}
        self.error("unread_ack_required", "register_evidence", data)
        binary = self.engine.dispatch("register_evidence", {**data, "unread_content_ack": True})["evidence_id"]
        c = self.claim(); c["evidence_ids"].append(binary)
        payload = self.review_payload(c)
        self.error("unread_ack_required", "submit_review", payload)
        payload["unread_evidence_ids"] = [binary]
        payload["claim_stances"][0]["evidence_ids"] = [binary]
        self.error("unread_positive_evidence", "submit_review", payload)
        payload["claim_stances"][0].update(stance="insufficient_evidence", evidence_ids=[])
        self.engine.dispatch("submit_review", payload)
        packet = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": "underclaim"})
        payload.update(role="underclaim", packet_id=packet["packet_id"], reviewer={"context_id": "underclaim", "model": "fixture"})
        self.engine.dispatch("submit_review", payload)
        packet = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        data = {"case_id": self.cid, "adjudication_id": packet["adjudication_id"], "input_digest": packet["input_digest"], "adjudicator": {"context_id": "writer", "model": "fixture"}, "unread_evidence_ids": [], "decisions": [], "dispositions": []}
        self.error("unread_ack_required", "submit_adjudication", data)
        result = self.engine.dispatch("verify", {"case_id": self.cid})
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["evidence"][-1]["source_text_status"], "binary_not_read_by_engine")
        decision = {"claim_id": "C1", "claim_type": "description", "evidence_level": "unassessed", "claim_basis": "empirical", "scope": c["scope"], "verdict": "insufficient_evidence", "revised_text": "The binary source has not been read.", "rationale": "Unread source content", "evidence_ids": [binary], "confidence": "low", "confidence_reason": "No parsed content", "boundary": "Unread binary content", "reversal_condition": "Register and review the relevant readable extract"}
        data.update(unread_evidence_ids=[binary], decisions=[decision])
        self.engine.dispatch("submit_adjudication", data)
        result = self.engine.dispatch("export", {"case_id": self.cid})
        self.assertEqual(result["verification"]["status"], "unverified")

    def test_nonblind_is_case_wide_and_gate_version_cannot_be_requested_off(self):
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch("create_case", {"question": "Fixture", "draft": "Fixture", "gate_version": 0})
        self.assertEqual(caught.exception.code, "unknown_field")
        self.cid = self.engine.dispatch("create_case", {"question": "Fixture", "draft": "Visible draft", "blind": False})["case_id"]
        self.ev = self.register()
        self.save(self.claim()); self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            p = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            self.assertFalse(p["blind"])
            self.assertEqual(p["draft"], "Visible draft")
            self.assertEqual(p["gate_version"], 1)

    def test_truncated_source_requires_ack_and_cannot_support_positive(self):
        (self.root / "large.txt").write_text("unique long quotation " + "x" * 140000, encoding="utf-8")
        self.ev = self.register(path="large.txt", quote=None)
        payload = self.review_payload(self.claim())
        self.error("unread_ack_required", "submit_review", payload)
        payload["unread_evidence_ids"] = [self.ev]
        self.error("unread_positive_evidence", "submit_review", payload)

    def test_review_requires_exact_stance_coverage_even_without_findings(self):
        payload = self.review_payload(self.claim())
        stance = deepcopy(payload["claim_stances"])
        payload["claim_stances"] = []
        self.error("invalid_value", "submit_review", payload)
        payload["claim_stances"] = stance + stance
        self.error("duplicate_id", "submit_review", payload)
        payload["claim_stances"] = stance
        self.engine.dispatch("submit_review", payload)

    def test_review_positive_stance_cannot_bypass_critical_gate(self):
        c = self.claim("association", "adjusted"); c["checks"]["unit"]["status"] = "unknown"
        payload = self.review_payload(c)
        self.error("critical_check_ceiling", "submit_review", payload)
        payload["claim_stances"][0]["stance"] = "insufficient_evidence"
        self.engine.dispatch("submit_review", payload)

    def finding(self):
        return {"id": "O1", "claim_id": "C1", "evidence_ids": [self.ev], "issue": "Bound scope", "proposed_claim_basis": "empirical", "proposed_claim_type": "description", "proposed_evidence_level": "recorded", "proposed_scope": "Synthetic fixture only", "proposed_text": "Scoped synthetic claim", "decision_impact": "Narrow scope"}

    def test_finding_must_bind_decision_and_actually_change_text_or_disagree(self):
        c = self.claim(); payload = self.reviewed(c, self.finding())
        disp = payload["dispositions"][0]
        disp["claim_id"] = "wrong"
        self.error("finding_decision_mismatch", "submit_adjudication", payload)
        disp["claim_id"] = "C1"
        payload["decisions"][0]["revised_text"] = c["text"]
        self.error("finding_not_incorporated", "submit_adjudication", payload)
        disp.update(resolution="disagreement", disagreement="The proposed wording omits the specified fixture boundary.")
        self.error("contradictory_resolution", "submit_adjudication", payload)
        del disp["revised_text_quote"]
        self.engine.dispatch("submit_adjudication", payload)
        result = self.engine.dispatch("export", {"case_id": self.cid})
        from pathlib import Path
        report = Path(result["path"]).read_text(encoding="utf-8")
        for fragment in ("disagreement", "claim\\_stances", "gate_version=1", "Claim basis:"):
            self.assertIn(fragment, report)

    def test_accepted_classification_mismatch_and_partial_anchor(self):
        payload = self.reviewed(self.claim(), self.finding())
        payload["decisions"][0]["scope"] = "Different scope"
        self.error("finding_not_incorporated", "submit_adjudication", payload)
        payload["dispositions"][0].update(disposition="partial", condition="Adopt wording in a different specified scope")
        self.engine.dispatch("submit_adjudication", payload)

    def test_case_blind_applies_to_both_roles_cannot_be_overridden_or_mutated(self):
        c = self.claim(); c.update(best_current_explanation="Writer preference", discriminating_test="Writer framing")
        self.save(c); self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            p = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            self.assertTrue(p["blind"]); self.assertIsNone(p["draft"])
            self.assertNotIn("best_current_explanation", p["claims"][0])
            self.error("case_level_blind", "review_packet", {"case_id": self.cid, "role": role, "blind": False})
        case = self.engine.dispatch("get_case", {"case_id": self.cid}); case["blind"] = False
        with closing(sqlite3.connect(self.engine.database)) as db:
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case), self.cid)); db.commit()
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch("review_packet", {"case_id": self.cid, "role": "overclaim"})
        self.assertEqual(caught.exception.code, "frozen_integrity_error")

    def test_legacy_v2_digest_recovery_does_not_retroactively_apply_gates(self):
        self.save(self.claim())
        old = self.engine.dispatch("get_case", {"case_id": self.cid})
        old.pop("gate_version"); old.pop("blind"); old.pop("events")
        old["claims"][0].pop("claim_basis")
        for ev in old["evidence"]:
            for field in ("kind", "unread_content_ack", "content_read_status"):
                ev.pop(field)
        with closing(sqlite3.connect(self.engine.database)) as db:
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(old), self.cid)); db.commit()
        expected = _digest({key: old[key] for key in ("case_id", "question", "domain", "draft", "claims", "evidence", "hypotheses", "schema_version")})
        frozen = self.engine.dispatch("freeze", {"case_id": self.cid})
        self.assertEqual(frozen["input_digest"], expected)
        p = Engine(self.root).dispatch("review_packet", {"case_id": self.cid, "role": "overclaim", "blind": True})
        self.assertNotIn("gate_version", p)
        self.assertEqual(p["input_digest"], expected)


if __name__ == "__main__":
    unittest.main()
