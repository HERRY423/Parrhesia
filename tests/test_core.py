"""Adversarial lifecycle/integrity tests; these are not tests of scientific validity."""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.contracts import CHECK_NAMES, ContractError
from parrhesia.core import Engine


class CoreTest(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "artifacts" / "test-workspaces"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="core-", dir=base)
        self.workspace = Path(self.directory.name)
        self.engine = Engine(self.workspace)
        self.source = self.workspace / "evidence.txt"
        self.source.write_text("Synthetic engineering fixture. Effect = 2; CI [1, 3].\n", encoding="utf-8")
        self.case = self.engine.dispatch("create_case", {
            "question": "Does this synthetic fixture support the example description?",
            "draft": "An example draft, with no scientific-validity claim.",
            "writer_context_id": "writer",
        })["case_id"]
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.case, "path": "evidence.txt", "provenance": "synthetic", "quote": "Effect = 2",
        })["evidence_id"]
        self.claim = {
            "id": "C1", "text": "The fixture says effect 2.", "level": "descriptive",
            "evidence_ids": [self.ev], "effect": {"estimate": "2 (synthetic)", "uncertainty": "[1, 3] (synthetic)"},
            "scope": "Synthetic fixture text only", "origin": "unknown",
            "alternatives": [{"explanation": "Fixture could be unrelated to any scientific observation", "status": "not_excluded", "reason": "It is synthetic"}],
            "checks": {name: {"status": "not_applicable", "reason": "Synthetic engineering fixture only"} for name in CHECK_NAMES},
            "contribution": "Demonstrates the software contract only",
        }
        self.engine.dispatch("set_ledger", {"case_id": self.case, "claims": [self.claim]})

    def tearDown(self):
        self.directory.cleanup()

    def error(self, code, action, payload):
        with self.assertRaises(ContractError) as caught:
            self.engine.dispatch(action, payload)
        self.assertEqual(code, caught.exception.code)

    def freeze(self):
        return self.engine.dispatch("freeze", {"case_id": self.case})

    def review_payload(self, role, findings=None):
        packet = self.engine.dispatch("review_packet", {"case_id": self.case, "role": role})
        return {
            "case_id": self.case, "role": role, "packet_id": packet["packet_id"], "input_digest": packet["input_digest"],
            "reviewer": {"context_id": f"fresh-{role}", "model": "same-model-is-permitted"},
            "covered_claim_ids": ["C1"], "findings": findings or [],
        }

    def reviews(self, findings=None):
        self.freeze()
        self.engine.dispatch("submit_review", self.review_payload("overclaim", findings))
        self.engine.dispatch("submit_review", self.review_payload("underclaim"))

    def finding(self):
        return {"id": "O1", "claim_id": "C1", "evidence_ids": [self.ev], "issue": "Illustrative issue", "proposed_level": "descriptive", "proposed_text": "The fixture states effect 2.", "decision_impact": "Restrict to fixture contents"}

    def adjudication_payload(self, verdict="supported", dispositions=None):
        packet = self.engine.dispatch("adjudication_packet", {"case_id": self.case})
        return {
            "case_id": self.case, "adjudication_id": packet["adjudication_id"], "input_digest": packet["input_digest"],
            "adjudicator": {"context_id": "writer", "model": "same-model-is-permitted"},
            "decisions": [{"claim_id": "C1", "verdict": verdict, "level": "descriptive", "revised_text": "The synthetic fixture states effect 2.", "rationale": "Direct literal statement only", "evidence_ids": [self.ev], "confidence": "high", "confidence_reason": "Literal quote matches", "boundary": "No scientific inference beyond fixture contents", "reversal_condition": "A different source statement would change this judgment"}],
            "dispositions": dispositions or [],
        }

    def adjudicate(self, verdict="supported"):
        self.reviews()
        return self.engine.dispatch("submit_adjudication", self.adjudication_payload(verdict))

    def test_restarts_preserve_snapshots_reviews_and_report(self):
        self.adjudicate()
        self.engine = Engine(self.workspace)
        result = self.engine.dispatch("export", {"case_id": self.case})
        report = Path(result["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(report).hexdigest(), result["sha256"])
        self.assertIn(b"synthetic", report)
        self.assertIn(b"not established by this engine", report)
        self.assertIn(b"No human acceptance has been recorded", report)
        reloaded = Engine(self.workspace).dispatch("get_case", {"case_id": self.case})
        self.assertEqual("exported", reloaded["state"])
        self.assertEqual(result["sha256"], reloaded["export"]["sha256"])

    def test_both_review_packets_are_frozen_before_first_review(self):
        frozen = self.freeze()
        before = self.engine.dispatch("review_packet", {"case_id": self.case, "role": "underclaim"})
        self.engine.dispatch("submit_review", self.review_payload("overclaim", [self.finding()]))
        after = self.engine.dispatch("review_packet", {"case_id": self.case, "role": "underclaim"})
        self.assertEqual(before, after)
        self.assertEqual(frozen["packet_ids"]["underclaim"], after["packet_id"])
        self.assertNotIn("writer_context_id", after)
        self.assertNotIn("reviews", after)
        self.assertNotIn("reviewer", after)
        self.assertEqual(before["input_digest"], frozen["input_digest"])

    def test_adjudication_requires_both_reviews(self):
        self.freeze()
        self.error("invalid_state", "adjudication_packet", {"case_id": self.case})
        self.engine.dispatch("submit_review", self.review_payload("overclaim"))
        self.error("invalid_state", "adjudication_packet", {"case_id": self.case})

    def test_stale_packet_and_context_reuse_do_not_advance(self):
        self.freeze()
        payload = self.review_payload("overclaim")
        original = deepcopy(payload)
        payload["packet_id"] = "stale"
        self.error("stale_packet", "submit_review", payload)
        payload = deepcopy(original)
        payload["reviewer"]["context_id"] = "writer"
        self.error("context_reuse", "submit_review", payload)
        self.engine.dispatch("submit_review", original)
        payload = self.review_payload("underclaim")
        payload["reviewer"]["context_id"] = original["reviewer"]["context_id"]
        self.error("context_reuse", "submit_review", payload)
        self.assertEqual(["overclaim"], list(self.engine.dispatch("get_case", {"case_id": self.case})["reviews"]))

    def test_duplicate_and_missing_claim_coverage_rejected(self):
        self.freeze()
        payload = self.review_payload("overclaim")
        payload["covered_claim_ids"] = ["C1", "C1"]
        self.error("duplicate_id", "submit_review", payload)
        payload["covered_claim_ids"] = []
        self.error("incomplete_coverage", "submit_review", payload)

    def test_finding_limit_and_split_are_real_gates(self):
        self.freeze()
        payload = self.review_payload("overclaim", [dict(self.finding(), id=f"F{i}") for i in range(4)])
        self.error("invalid_value", "submit_review", payload)
        payload["findings"] = payload["findings"][:3]
        payload["review_status"] = "needs_split"
        self.engine.dispatch("submit_review", payload)
        self.engine.dispatch("submit_review", self.review_payload("underclaim"))
        self.assertEqual("review_blocked", self.engine.dispatch("get_case", {"case_id": self.case})["state"])
        self.error("invalid_state", "adjudication_packet", {"case_id": self.case})

    def test_duplicate_finding_ids_across_reviews(self):
        self.freeze()
        self.engine.dispatch("submit_review", self.review_payload("overclaim", [self.finding()]))
        self.error("duplicate_id", "submit_review", self.review_payload("underclaim", [self.finding()]))

    def test_finding_cannot_introduce_unregistered_evidence(self):
        self.freeze()
        finding = self.finding()
        finding["evidence_ids"] = ["invented"]
        self.error("unknown_reference", "submit_review", self.review_payload("overclaim", [finding]))

    def test_empty_findings_are_valid(self):
        self.reviews()
        self.assertEqual("reviewed", self.engine.dispatch("get_case", {"case_id": self.case})["state"])

    def test_simultaneous_reviewers_serialize_without_lost_updates(self):
        self.freeze()
        payloads = [self.review_payload(role) for role in ("overclaim", "underclaim")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda payload: self.engine.dispatch("submit_review", payload), payloads))
        self.assertEqual(2, len(results))
        case = self.engine.dispatch("get_case", {"case_id": self.case})
        self.assertEqual("reviewed", case["state"])
        self.assertEqual({"overclaim", "underclaim"}, case["reviews"].keys())

    def test_racing_duplicate_review_only_one_is_accepted(self):
        self.freeze()
        payload = self.review_payload("overclaim")
        def submit(_):
            try:
                self.engine.dispatch("submit_review", payload)
                return "accepted"
            except ContractError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, range(2)))
        self.assertCountEqual(["accepted", "duplicate_review"], outcomes)

    def test_every_finding_requires_one_disposition(self):
        self.reviews([self.finding()])
        payload = self.adjudication_payload()
        self.error("incomplete_dispositions", "submit_adjudication", payload)
        disposition = {"finding_id": "O1", "disposition": "accepted", "reason": "Narrow wording"}
        payload["dispositions"] = [disposition, disposition]
        self.error("duplicate_id", "submit_adjudication", payload)
        payload["dispositions"] = [dict(disposition, disposition="partial")]
        self.error("invalid_value", "submit_adjudication", payload)
        payload["dispositions"] = [disposition]
        self.engine.dispatch("submit_adjudication", payload)

    def test_partial_verdict_requires_condition(self):
        self.reviews()
        payload = self.adjudication_payload("partially_supported")
        self.error("invalid_value", "submit_adjudication", payload)
        payload["decisions"][0]["condition"] = "Only literal fixture content"
        self.engine.dispatch("submit_adjudication", payload)

    def test_adjudicator_cannot_reuse_reviewer_context(self):
        self.reviews()
        payload = self.adjudication_payload()
        payload["adjudicator"]["context_id"] = "fresh-underclaim"
        self.error("context_reuse", "submit_adjudication", payload)

    def test_stale_adjudication_digest_rejected(self):
        self.reviews()
        payload = self.adjudication_payload()
        payload["input_digest"] = "stale"
        self.error("stale_packet", "submit_adjudication", payload)

    def test_ledger_duplicate_refs_and_missing_checks_rejected(self):
        claim = deepcopy(self.claim)
        claim["evidence_ids"] *= 2
        self.error("duplicate_id", "set_ledger", {"case_id": self.case, "claims": [claim]})
        claim = deepcopy(self.claim)
        del claim["checks"]["unit"]
        self.error("missing_field", "set_ledger", {"case_id": self.case, "claims": [claim]})
        claim = deepcopy(self.claim)
        claim["checks"]["unit"]["status"] = True
        self.error("invalid_value", "set_ledger", {"case_id": self.case, "claims": [claim]})

    def test_frozen_ledger_and_evidence_are_immutable(self):
        self.freeze()
        self.error("invalid_state", "set_ledger", {"case_id": self.case, "claims": [self.claim]})
        self.error("invalid_state", "register_evidence", {"case_id": self.case, "path": "evidence.txt", "provenance": "reported"})

    def test_unknown_fields_not_silently_ignored(self):
        self.error("unknown_field", "create_case", {"question": "Q", "draft": "D", "desired_verdict": "supported"})

    def test_prespecification_requires_documentary_hypothesis(self):
        claim = deepcopy(self.claim)
        claim["origin"] = "prespecified"
        self.error("missing_timing_source", "set_ledger", {"case_id": self.case, "claims": [claim]})
        self.error("missing_timing_source", "register_hypothesis", {"case_id": self.case, "statement": "H", "timing_basis": "reported_prespecified"})
        hypothesis = self.engine.dispatch("register_hypothesis", {"case_id": self.case, "statement": "Reported external hypothesis", "timing_basis": "reported_prespecified", "source_evidence_id": self.ev})
        self.assertEqual("self_report_not_historical_proof", hypothesis["timing_verification"])
        claim["hypothesis_id"] = hypothesis["hypothesis_id"]
        self.engine.dispatch("set_ledger", {"case_id": self.case, "claims": [claim]})

    def test_missing_source_distinct_from_mismatch_and_blocks_positive(self):
        self.adjudicate()
        self.source.unlink()
        verification = self.engine.dispatch("verify", {"case_id": self.case})
        self.assertEqual("unverified", verification["status"])
        self.assertEqual("matched", verification["evidence"][0]["snapshot_status"])
        self.assertEqual("missing", verification["evidence"][0]["file_status"])
        self.error("unverified_support", "export", {"case_id": self.case})
        self.assertEqual("adjudicated", self.engine.dispatch("get_case", {"case_id": self.case})["state"])

    def test_insufficient_evidence_can_export_explicit_unknown(self):
        self.adjudicate("insufficient_evidence")
        self.source.unlink()
        result = self.engine.dispatch("export", {"case_id": self.case})
        self.assertEqual("unverified", result["verification"]["status"])
        self.assertIn("current file: missing", Path(result["path"]).read_text(encoding="utf-8"))

    def test_source_mismatch_blocks_even_nonpositive_report(self):
        self.adjudicate("insufficient_evidence")
        self.source.write_text("Changed result", encoding="utf-8")
        self.assertEqual("blocked", self.engine.dispatch("verify", {"case_id": self.case})["status"])
        self.error("verification_mismatch", "export", {"case_id": self.case})
        self.assertFalse((self.workspace / "exports").exists())

    def test_bad_quote_is_not_verified_by_a_matching_hash(self):
        ev = self.engine.dispatch("register_evidence", {"case_id": self.case, "path": "evidence.txt", "provenance": "reported", "quote": "invented quote"})
        verification = self.engine.dispatch("verify", {"case_id": self.case})
        result = next(item for item in verification["evidence"] if item["evidence_id"] == ev["evidence_id"])
        self.assertEqual("matched", result["file_status"])
        self.assertEqual("mismatch", result["anchor_status"])
        self.assertEqual("blocked", verification["status"])

    def test_snapshot_corruption_blocks_packets_and_verification(self):
        self.freeze()
        with closing(sqlite3.connect(self.engine.database)) as db, db:
            db.execute("UPDATE evidence_snapshots SET content=? WHERE case_id=?", (b"tampered", self.case))
        self.error("snapshot_mismatch", "review_packet", {"case_id": self.case, "role": "overclaim"})
        self.assertEqual("blocked", self.engine.dispatch("verify", {"case_id": self.case})["status"])

    def test_frozen_metadata_corruption_detected(self):
        self.freeze()
        with closing(sqlite3.connect(self.engine.database)) as db, db:
            document = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (self.case,)).fetchone()[0])
            document["claims"][0]["text"] = "Silently changed claim"
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(document), self.case))
        self.error("frozen_integrity_error", "get_case", {"case_id": self.case})

    def test_adjudication_corruption_blocks_export(self):
        self.adjudicate()
        with closing(sqlite3.connect(self.engine.database)) as db, db:
            document = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (self.case,)).fetchone()[0])
            document["adjudication"]["decisions"][0]["revised_text"] = "Untracked replacement"
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(document), self.case))
        self.error("adjudication_integrity_error", "export", {"case_id": self.case})

    def test_review_corruption_blocks_adjudication(self):
        self.reviews()
        with closing(sqlite3.connect(self.engine.database)) as db, db:
            document = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (self.case,)).fetchone()[0])
            document["reviews"]["overclaim"]["findings"] = [self.finding()]
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(document), self.case))
        self.error("review_integrity_error", "adjudication_packet", {"case_id": self.case})

    def test_unsafe_paths_and_internal_state_rejected(self):
        for path in ("../evidence.txt", "C:/secret.txt", "/etc/passwd", "evidence.txt:secret", ".parrhesia/state.sqlite3", ".parrhesia./state.sqlite3", "a/../evidence.txt", "CON.txt"):
            with self.subTest(path=path):
                self.error("unsafe_path", "register_evidence", {"case_id": self.case, "path": path, "provenance": "reported"})

    def test_symlink_source_rejected_if_host_permits_creation(self):
        link = self.workspace / "linked.txt"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("host account cannot create symlinks")
        self.error("unsafe_path", "register_evidence", {"case_id": self.case, "path": "linked.txt", "provenance": "reported"})

    def test_export_never_overwrites_existing_content(self):
        self.adjudicate()
        target = self.workspace / "existing.md"
        target.write_text("User's document", encoding="utf-8")
        self.error("export_exists", "export", {"case_id": self.case, "path": "existing.md"})
        self.assertEqual("User's document", target.read_text(encoding="utf-8"))

    def test_report_escapes_remote_image_and_html(self):
        self.reviews()
        payload = self.adjudication_payload()
        payload["decisions"][0]["revised_text"] = "![pixel](https://example.invalid/private) <script>danger()</script>"
        self.engine.dispatch("submit_adjudication", payload)
        report = self.engine.dispatch("export", {"case_id": self.case})
        text = Path(report["path"]).read_text(encoding="utf-8")
        self.assertNotIn("![pixel](", text)
        self.assertNotIn("<script>", text)

    def test_pending_export_recovers_after_io_failure(self):
        self.adjudicate()
        with patch("parrhesia.core.os.link", side_effect=PermissionError("simulated")):
            self.error("export_failed", "export", {"case_id": self.case})
        case = self.engine.dispatch("get_case", {"case_id": self.case})
        self.assertEqual("export_pending", case["state"])
        self.assertFalse(Path(case["export"]["path"]).exists())
        expected_hash = case["export"]["sha256"]
        result = Engine(self.workspace).dispatch("export", {"case_id": self.case})
        self.assertEqual("exported", result["state"])
        self.assertEqual(expected_hash, result["sha256"])

    def test_pending_export_recovers_matching_file_without_overwrite(self):
        self.adjudicate()
        with patch("parrhesia.core.os.link", side_effect=PermissionError("simulated")):
            self.error("export_failed", "export", {"case_id": self.case})
        case = self.engine.dispatch("get_case", {"case_id": self.case})
        with closing(sqlite3.connect(self.engine.database)) as db, db:
            content = db.execute("SELECT content FROM export_artifacts WHERE case_id=?", (self.case,)).fetchone()[0]
        target = Path(case["export"]["path"])
        target.write_bytes(content)
        mtime = target.stat().st_mtime_ns
        result = Engine(self.workspace).dispatch("export", {"case_id": self.case})
        self.assertEqual("exported", result["state"])
        self.assertEqual(mtime, target.stat().st_mtime_ns)

    def test_human_pause_hold_and_accept_are_reported_events(self):
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "pause", "responsible_human": "Researcher", "reason": "Inspect scope"})
        self.error("human_paused", "freeze", {"case_id": self.case})
        self.engine.dispatch("verify", {"case_id": self.case})
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "accept", "responsible_human": "Researcher", "reason": "Resume unchanged example"})
        self.adjudicate()
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "challenge", "responsible_human": "Researcher", "reason": "Need review"})
        self.error("human_hold", "export", {"case_id": self.case})
        case = self.engine.dispatch("get_case", {"case_id": self.case})
        self.assertEqual(3, len(case["human_decisions"]))
        self.assertEqual("caller_report_not_identity_authentication", case["human_decisions"][-1]["identity_basis"])

    def test_challenge_or_defer_after_pause_does_not_resume_writes(self):
        for followup in ("challenge", "defer"):
            with self.subTest(followup=followup):
                for decision in ("pause", followup):
                    self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": decision, "responsible_human": "Researcher", "reason": "Keep work on hold"})
                self.engine = Engine(self.workspace)
                self.error("human_paused", "set_ledger", {"case_id": self.case, "claims": [self.claim]})
                self.engine.dispatch("verify", {"case_id": self.case})
                self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "accept", "responsible_human": "Researcher", "reason": "Explicitly resume"})
                self.engine.dispatch("set_ledger", {"case_id": self.case, "claims": [self.claim]})

    def test_pause_after_challenge_blocks_until_explicit_accept(self):
        for decision in ("challenge", "pause", "defer", "challenge"):
            self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": decision, "responsible_human": "Researcher", "reason": "Keep work on hold"})
        self.error("human_paused", "freeze", {"case_id": self.case})
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "accept", "responsible_human": "Researcher", "reason": "Explicitly resume"})
        self.freeze()

    def test_pause_allows_existing_packet_read_but_not_packet_creation(self):
        self.reviews()
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "pause", "responsible_human": "Researcher", "reason": "Inspect before adjudication"})
        self.error("human_paused", "adjudication_packet", {"case_id": self.case})
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "accept", "responsible_human": "Researcher", "reason": "Allow packet preparation"})
        before = self.engine.dispatch("adjudication_packet", {"case_id": self.case})
        self.engine.dispatch("record_human_decision", {"case_id": self.case, "decision": "pause", "responsible_human": "Researcher", "reason": "Inspect prepared packet"})
        after = self.engine.dispatch("adjudication_packet", {"case_id": self.case})
        self.assertEqual(before, after)

    def test_engineering_evidence_levels_lifecycle(self):
        for eng_level in ("test_passed", "host_accepted", "user_impact"):
            with self.subTest(level=eng_level):
                case_id = self.engine.dispatch("create_case", {
                    "question": f"Engineering test for {eng_level}",
                    "draft": "Engineering draft.",
                    "domain": "general",
                })["case_id"]
                ev_id = self.engine.dispatch("register_evidence", {
                    "case_id": case_id, "path": "evidence.txt", "provenance": "synthetic", "quote": "Effect = 2",
                })["evidence_id"]
                claim = {
                    "id": "C1", "text": f"Engineering claim at level {eng_level}.", "level": eng_level,
                    "evidence_ids": [ev_id], "effect": {"estimate": "100%", "uncertainty": "exact"},
                    "scope": "Local test execution", "origin": "unknown",
                    "alternatives": [{"explanation": "Environment variance", "status": "not_excluded", "reason": "Untested on other platforms"}],
                    "checks": {name: {"status": "not_applicable", "reason": "Engineering assertion"} for name in CHECK_NAMES},
                    "contribution": f"Validates {eng_level} level in schema",
                }
                self.engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
                self.engine.dispatch("freeze", {"case_id": case_id})
                packet = self.engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
                self.engine.dispatch("submit_review", {
                    "case_id": case_id, "role": "overclaim", "packet_id": packet["packet_id"],
                    "input_digest": packet["input_digest"],
                    "reviewer": {"context_id": "rev-o", "model": "m"},
                    "covered_claim_ids": ["C1"],
                    "findings": [{"id": "O1", "claim_id": "C1", "evidence_ids": [ev_id], "issue": "Overclaimed scope", "proposed_level": eng_level, "proposed_text": "Scoped text", "decision_impact": "None"}],
                })


if __name__ == "__main__":
    unittest.main()
