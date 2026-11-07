"""Structural v2 gates and legacy recovery, not scientific acceptance tests."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, ESTIMAND_FIELDS, STAT_FIELDS, TYPE_LEVELS
from parrhesia.claims import validate_support
from legacy_fixtures import seed_legacy_case
from parrhesia.contracts import CHECK_NAMES, ContractError
from parrhesia.core import Engine, _digest
from parrhesia.report import render_report


class ClaimsV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "source.txt").write_text("Synthetic fixture: effect 0. NO real scientific execution.\n", encoding="utf-8")
        self.engine = Engine(self.root)
        self.cid = self.engine.dispatch("create_case", {"question": "Fixture?", "draft": "Synthetic", "writer_context_id": "writer"})["case_id"]
        # These are simulated caller metadata, not empirical evidence about science.
        self.ev = self.register()

    def register(self, kind="observation", provenance="reported", **extra):
        return self.engine.dispatch("register_evidence", {"case_id": self.cid, "path": "source.txt", "provenance": provenance, "kind": kind, "quote": "Synthetic fixture: effect 0.", "location": "line 1", **extra})["evidence_id"]

    def tearDown(self):
        self.temp.cleanup()

    def assessment(self, status="unknown"):
        return {"status": status, "reason": "Synthetic structural fixture only", "evidence_ids": [self.ev] if status == "pass" else []}

    def claim(self, kind="description", level="recorded", family="observational"):
        c = {"id": "C1", "text": "Only a synthetic fixture", "claim_type": kind, "evidence_level": level,
             "claim_basis": "formal" if kind == "theory" else "empirical",
             "scope": "Synthetic fixture only", "evidence_ids": [self.ev], "effect": {"estimate": "0", "uncertainty": "UNKNOWN"},
             "origin": "unknown", "contribution": "Exercises structural contract",
             "alternatives": [{"explanation": "Synthetic only", "status": "not_excluded", "reason": "No research conducted"}],
             "checks": {name: {"status": "pass", "reason": "Simulated caller assessment, not scientific validation"} for name in CHECK_NAMES},
             "design_packages": [{"family": family, "checks": {key: self.assessment("pass") for key in DESIGN_FIELDS[family]}}],
             "statistical_report": {key: self.assessment("pass") for key in STAT_FIELDS},
             "provenance_cards": {key: [] for key in CARD_FIELDS}}
        if kind in ("causal_effect", "necessity", "sufficiency") or level == "causal_chain_tested":
            c["causal_basis"] = {"design_family": family, "estimand": {key: "Specified synthetic " + key for key in ESTIMAND_FIELDS},
                                 "assumptions": [{"name": "Identification assumption", **self.assessment("pass")}],
                                 "falsification_sensitivity": [{"name": "Sensitivity within stated range", **self.assessment("pass")}],
                                 "assessment": self.assessment("pass"), "necessity_test": self.assessment(), "sufficiency_test": self.assessment()}
        return c

    def save(self, claim):
        return self.engine.dispatch("set_ledger", {"case_id": self.cid, "claims": [claim]})

    def reviewed(self, claim, finding=None):
        self.save(claim)
        frozen = self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            packet = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            self.assertEqual(packet["schema_version"], 2)
            self.engine.dispatch("submit_review", {"case_id": self.cid, "role": role, "packet_id": packet["packet_id"], "input_digest": frozen["input_digest"], "reviewer": {"context_id": role, "model": "fixture"}, "covered_claim_ids": ["C1"], "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Fixture only", "evidence_ids": []}], "unread_evidence_ids": [], "findings": [finding] if finding and role == "overclaim" else []})
        packet = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        return {"case_id": self.cid, "adjudication_id": packet["adjudication_id"], "input_digest": packet["input_digest"], "adjudicator": {"context_id": "writer", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [{"finding_id": finding["id"], "claim_id": "C1", "disposition": "accepted", "resolution": "incorporated", "revised_text_quote": finding["proposed_text"], "reason": "Scoped"}] if finding else [], "decisions": [{"claim_id": "C1", "claim_basis": claim["claim_basis"], "claim_type": claim["claim_type"], "evidence_level": claim["evidence_level"], "scope": claim["scope"], "verdict": "supported", "revised_text": "Scoped synthetic claim", "rationale": "Fixture only", "evidence_ids": [self.ev], "confidence": "low", "confidence_reason": "Synthetic", "boundary": "No scientific result", "reversal_condition": "Different fixture changes the judgment"}]}

    def error(self, code, action, payload):
        before = self.engine.dispatch("get_case", {"case_id": self.cid})
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch(action, payload)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(before, self.engine.dispatch("get_case", {"case_id": self.cid}))

    def test_new_default_and_type_local_levels_reject_mixed_or_legacy_input(self):
        self.assertEqual(self.engine.dispatch("get_case", {"case_id": self.cid})["schema_version"], 2)
        for kind in TYPE_LEVELS:
            if kind == "engineering":
                continue
            for level in TYPE_LEVELS[kind]:
                with self.subTest(kind=kind, level=level):
                    self.save(self.claim(kind, level))
        c = self.claim("association", "externally_validated")
        self.error("invalid_value", "set_ledger", {"case_id": self.cid, "claims": [c]})
        c = self.claim(); c["level"] = "descriptive"
        self.error("unknown_field", "set_ledger", {"case_id": self.cid, "claims": [c]})

    def test_all_design_packages_require_their_own_checks_and_stats(self):
        for family in DESIGN_FIELDS:
            self.save(self.claim(family=family))
        c = self.claim(); c["design_packages"][0]["checks"].pop("measurement")
        self.error("missing_field", "set_ledger", {"case_id": self.cid, "claims": [c]})
        c = self.claim(); c["statistical_report"].pop("missingness_exclusions")
        self.error("missing_field", "set_ledger", {"case_id": self.cid, "claims": [c]})

    def test_cards_keep_zero_na_unknown_and_reject_bad_references(self):
        example = Path(__file__).resolve().parents[1] / "docs/examples/claim-v2-unknown.json"
        self.save(json.loads(example.read_text(encoding="utf-8")))
        c = self.claim()
        for kind, keys in CARD_FIELDS.items():
            c["provenance_cards"][kind] = [{"id": kind + "-1", "status": "not_run" if kind in ("search", "execution") else "reported", "reason": "Fixture", "evidence_ids": [self.ev], "details": {key: "UNKNOWN" for key in keys}}]
        c["provenance_cards"]["number"][0]["details"].update(value="0", uncertainty="NA")
        self.save(c)
        stored = self.engine.dispatch("get_case", {"case_id": self.cid})["claims"][0]
        self.assertEqual(stored["provenance_cards"], c["provenance_cards"])
        c["provenance_cards"]["citation"][0]["evidence_ids"] = ["made-up"]
        self.error("unknown_reference", "set_ledger", {"case_id": self.cid, "claims": [c]})
        c["provenance_cards"]["citation"][0].update(status="checked", evidence_ids=[])
        self.error("missing_card_evidence", "set_ledger", {"case_id": self.cid, "claims": [c]})

    def test_unassessed_cannot_be_supported_or_conditionally_supported(self):
        payload = self.reviewed(self.claim("prediction", "unassessed"))
        self.error("unsupported_evidence_level", "submit_adjudication", payload)
        payload["decisions"][0].update(verdict="partially_supported", condition="If later validated")
        self.error("unsupported_evidence_level", "submit_adjudication", payload)
        payload["decisions"][0].update(verdict="insufficient_evidence")
        self.engine.dispatch("submit_adjudication", payload)

    def test_observational_causal_record_no_longer_passes_current_gate(self):
        payload = self.reviewed(self.claim("causal_effect", "identified_under_assumptions"))
        self.error("incompatible_evidence_kind", "submit_adjudication", payload)
        case = self.engine.dispatch("get_case", {"case_id": self.cid})
        self.assertEqual(case["scientific_validity"], "not_established_by_engine")

    def test_randomization_does_not_bypass_identification_gap(self):
        c = self.claim("causal_effect", "identified_under_assumptions", "randomized")
        c["causal_basis"]["assumptions"][0]["status"] = "unknown"
        payload = self.reviewed(c)
        self.error("causal_identification_gap", "submit_adjudication", payload)
        payload["decisions"][0]["verdict"] = "insufficient_evidence"
        self.error("critical_check_ceiling", "submit_adjudication", payload)
        payload["decisions"][0]["evidence_level"] = "unidentified"
        self.engine.dispatch("submit_adjudication", payload)

    def test_necessity_does_not_grant_sufficiency(self):
        self.ev = self.register("intervention")
        c = self.claim("necessity", "bounded_test", "mechanism")
        c["causal_basis"]["necessity_test"] = self.assessment("pass")
        payload = self.reviewed(c)
        payload["decisions"][0]["claim_type"] = "sufficiency"
        self.error("causal_identification_gap", "submit_adjudication", payload)
        payload["decisions"][0]["claim_type"] = "necessity"
        self.engine.dispatch("submit_adjudication", payload)

    def test_causal_gate_rejects_unspecified_estimand_failed_sensitivity_and_uncited_basis(self):
        original = self.claim("causal_effect", "sensitivity_supported")
        decision = {"claim_type": "causal_effect", "evidence_level": "sensitivity_supported", "verdict": "supported", "evidence_ids": [self.ev]}
        for gap in ("estimand", "sensitivity", "citation"):
            claim, proposed = deepcopy(original), deepcopy(decision)
            if gap == "estimand":
                claim["causal_basis"]["estimand"]["contrast"] = "UNKNOWN"
            elif gap == "sensitivity":
                claim["causal_basis"]["falsification_sensitivity"][0]["status"] = "fail"
            else:
                proposed["evidence_ids"] = []
            with self.subTest(gap=gap), self.assertRaises(ContractError):
                validate_support(proposed, claim)

    def test_v2_review_rejects_legacy_fields_and_type_mismatch_without_mutation(self):
        self.save(self.claim())
        self.engine.dispatch("freeze", {"case_id": self.cid})
        packet = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": "overclaim"})
        self.assertIn("estimand", packet["instructions"])
        finding = {"id": "O1", "claim_id": "C1", "evidence_ids": [self.ev], "issue": "Scope", "proposed_claim_basis": "empirical", "proposed_claim_type": "description", "proposed_evidence_level": "externally_validated", "proposed_scope": "Fixture", "proposed_text": "Scoped synthetic claim", "decision_impact": "Narrow scope"}
        payload = {"case_id": self.cid, "role": "overclaim", "packet_id": packet["packet_id"], "input_digest": packet["input_digest"], "reviewer": {"context_id": "overclaim", "model": "fixture"}, "covered_claim_ids": ["C1"], "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Fixture", "evidence_ids": []}], "unread_evidence_ids": [], "findings": [finding]}
        self.error("invalid_value", "submit_review", payload)
        finding.update(proposed_evidence_level="recorded", proposed_level="descriptive")
        self.error("unknown_field", "submit_review", payload)

    def test_general_v2_requires_explicit_seven_check_coverage(self):
        cid = self.engine.dispatch("create_case", {"question": "Engineering", "draft": "Fixture", "domain": "general"})["case_id"]
        c = self.claim("engineering", "test_passed")
        c.update(evidence_ids=[], design_packages=[], alternatives=[])
        c["statistical_report"] = {key: self.assessment() for key in STAT_FIELDS}
        del c["checks"]
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch("set_ledger", {"case_id": cid, "claims": [c]})
        self.assertEqual(caught.exception.code, "missing_field")
        c["checks"] = {key: {"status": "not_applicable", "reason": "Unit contract fixture, no scientific data"} for key in CHECK_NAMES}
        self.engine.dispatch("set_ledger", {"case_id": cid, "claims": [c]})

    def test_reviewer_classification_and_export_readable_escaped_fields(self):
        c = self.claim(); c["scope"] = "<script>bad</script> | fixture"
        finding = {"id": "O1", "claim_id": "C1", "evidence_ids": [self.ev], "issue": "Scope", "proposed_claim_basis": "empirical", "proposed_claim_type": "description", "proposed_evidence_level": "recorded", "proposed_scope": c["scope"], "proposed_text": "Scoped synthetic claim", "decision_impact": "Narrow scope"}
        payload = self.reviewed(c, finding)
        self.engine.dispatch("submit_adjudication", payload)
        self.engine = Engine(self.root)
        result = self.engine.dispatch("export", {"case_id": self.cid})
        md = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("description × recorded", md)
        self.assertIn("statistical_report", md)
        self.assertIn("provenance_cards", md)
        self.assertNotIn("<script>", md)
        case = self.engine.dispatch("get_case", {"case_id": self.cid})
        target = self.root / "report.html"
        render_report({"claims": case["claims"], "decisions": payload["decisions"], "findings": {"overclaim": [finding], "underclaim": []}, "dispositions": payload["dispositions"], "verification": {}, "export": {}, "draft": "D", "case_id": self.cid}, target)
        html = target.read_text(encoding="utf-8")
        self.assertIn("<table>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>bad", html)
        self.assertNotIn("人工构造的工程演示", html)
        self.assertIn("提交者记录", html)

    def test_new_fields_are_frozen_and_old_digest_remains_compatible(self):
        self.save(self.claim())
        self.engine.dispatch("freeze", {"case_id": self.cid})
        case = self.engine.dispatch("get_case", {"case_id": self.cid})
        case["claims"][0]["statistical_report"]["units_sample_size"]["reason"] = "changed"
        with closing(sqlite3.connect(self.engine.database)) as db:
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case), self.cid))
            db.commit()
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch("review_packet", {"case_id": self.cid, "role": "overclaim"})
        self.assertEqual(caught.exception.code, "frozen_integrity_error")
        legacy = seed_legacy_case(self.engine, {"question": "Old", "draft": "Old", "schema_version": 1})["case_id"]
        old = self.engine.dispatch("get_case", {"case_id": legacy})
        expected = {key: old[key] for key in ("case_id", "question", "domain", "draft", "claims", "evidence", "hypotheses")}
        self.assertEqual(_digest(Engine._frozen_input(old)), _digest(expected))
        self.assertNotIn("claim_type", json.dumps(old))


if __name__ == "__main__":
    unittest.main()
