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


if __name__ == "__main__":
    unittest.main()
