"""Adversarial lifecycle/integrity tests; these are not tests of scientific validity."""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

try:
    from legacy_fixtures import seed_legacy_case
except ImportError:
    from tests.legacy_fixtures import seed_legacy_case
from parrhesia.contracts import CHECK_NAMES, ContractError
from parrhesia.core import Engine, PACKET_TEXT_BYTES, _digest


class CoreTest(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "artifacts" / "test-workspaces"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="core-", dir=base)
        self.workspace = Path(self.directory.name)
        self.engine = Engine(self.workspace)
        self.source = self.workspace / "evidence.txt"
        self.source.write_text("Synthetic engineering fixture. Effect = 2; CI [1, 3].\n", encoding="utf-8")
        self.case = seed_legacy_case(self.engine, {"schema_version": 1,
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

    @staticmethod
    def _fail_export_target_open(exc: BaseException):
        real_open = os.open

        def wrapper(path, flags, mode=0o777, *args, **kwargs):
            if Path(path).suffix.lower() == ".md":
                raise exc
            return real_open(path, flags, mode, *args, **kwargs)

        return patch("parrhesia.core.os.open", side_effect=wrapper)

    def test_pending_export_recovers_after_io_failure(self):
        self.adjudicate()
        with patch("parrhesia.core.os.link", side_effect=PermissionError("simulated")), self._fail_export_target_open(PermissionError("simulated")):
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
        with patch("parrhesia.core.os.link", side_effect=PermissionError("simulated")), self._fail_export_target_open(PermissionError("simulated")):
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
                case_id = seed_legacy_case(self.engine, {"schema_version": 1,
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

    def test_domain_level_validation_and_general_defaults(self):
        # 1. Scientific domain rejects engineering levels
        sci_case = seed_legacy_case(self.engine, {"schema_version": 1,
            "question": "Scientific question",
            "draft": "Scientific draft.",
            "domain": "scientific",
        })["case_id"]
        ev_id = self.engine.dispatch("register_evidence", {
            "case_id": sci_case, "path": "evidence.txt", "provenance": "synthetic", "quote": "Effect = 2",
        })["evidence_id"]
        for eng_lvl in ("test_passed", "host_accepted", "user_impact"):
            claim = {
                "id": "C1", "text": "Claim", "level": eng_lvl, "evidence_ids": [ev_id],
                "effect": {"estimate": "1", "uncertainty": "0.1"}, "scope": "Scope", "origin": "unknown",
                "alternatives": [{"explanation": "Alt", "status": "not_excluded", "reason": "R"}],
                "checks": {name: {"status": "not_applicable", "reason": "R"} for name in CHECK_NAMES},
                "contribution": "Contrib",
            }
            self.error("invalid_value", "set_ledger", {"case_id": sci_case, "claims": [claim]})

        # 2. General domain rejects scientific-only levels
        gen_case = seed_legacy_case(self.engine, {"schema_version": 1,
            "question": "General question",
            "draft": "General draft.",
            "domain": "general",
        })["case_id"]
        ev_id2 = self.engine.dispatch("register_evidence", {
            "case_id": gen_case, "path": "evidence.txt", "provenance": "synthetic", "quote": "Effect = 2",
        })["evidence_id"]
        for sci_lvl in ("causal", "mechanistic", "association", "predictive"):
            claim = {
                "id": "C1", "text": "Claim", "level": sci_lvl, "evidence_ids": [ev_id2],
                "effect": {"estimate": "1", "uncertainty": "0.1"}, "scope": "Scope", "origin": "unknown",
                "contribution": "Contrib",
            }
            self.error("invalid_value", "set_ledger", {"case_id": gen_case, "claims": [claim]})

        # 3. General domain allows omitting checks (defaults to not_applicable) and alternatives (defaults to [])
        valid_gen_claim = {
            "id": "C1", "text": "Claim", "level": "test_passed", "evidence_ids": [ev_id2],
            "effect": {"estimate": "100%", "uncertainty": "exact"}, "scope": "Scope", "origin": "unknown",
            "contribution": "Contrib",
        }
        res = self.engine.dispatch("set_ledger", {"case_id": gen_case, "claims": [valid_gen_claim]})
        self.assertEqual(res["claim_count"], 1)
        case_doc = self.engine.dispatch("get_case", {"case_id": gen_case})
        stored_claim = case_doc["claims"][0]
        self.assertEqual(stored_claim["alternatives"], [])
        self.assertEqual(len(stored_claim["checks"]), len(CHECK_NAMES))
        for check in stored_claim["checks"].values():
            self.assertEqual(check["status"], "not_applicable")

        # 4. Review enforces general domain levels
        self.engine.dispatch("freeze", {"case_id": gen_case})
        packet = self.engine.dispatch("review_packet", {"case_id": gen_case, "role": "overclaim"})
        self.error("invalid_value", "submit_review", {
            "case_id": gen_case, "role": "overclaim", "packet_id": packet["packet_id"],
            "input_digest": packet["input_digest"],
            "reviewer": {"context_id": "rev-o", "model": "m"},
            "covered_claim_ids": ["C1"],
            "findings": [{"id": "O1", "claim_id": "C1", "evidence_ids": [ev_id2], "issue": "Issue", "proposed_level": "causal", "proposed_text": "Text", "decision_impact": "Impact"}],
        })

    def test_research_advancement_fields_and_blind_review(self):
        case_id = seed_legacy_case(self.engine, {"schema_version": 1,
            "question": "Advance research on gene pathway?",
            "draft": "Draft mentioning speculative hypothesis and preliminary results.",
            "domain": "scientific",
        })["case_id"]
        ev_id = self.engine.dispatch("register_evidence", {
            "case_id": case_id, "path": "evidence.txt", "provenance": "synthetic", "quote": "Effect = 2",
        })["evidence_id"]
        claim = {
            "id": "C1", "text": "Gene X activates Pathway Y.", "level": "mechanistic",
            "evidence_ids": [ev_id], "effect": {"estimate": "2-fold", "uncertainty": "p < 0.05"},
            "scope": "Cell culture assay", "origin": "unknown",
            "best_current_explanation": "Direct kinase phosphorylation by Gene X product",
            "discriminating_test": "Phosphorylation assay with kinase-dead mutant",
            "alternatives": [{"explanation": "Secondary indirect response", "status": "not_excluded", "reason": "No cycloheximide control"}],
            "checks": {name: {"status": "unknown", "reason": "Preliminary"} for name in CHECK_NAMES},
            "contribution": "Proposes direct mechanism",
        }
        self.engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
        case_doc = self.engine.dispatch("get_case", {"case_id": case_id})
        self.assertEqual(case_doc["claims"][0]["best_current_explanation"], "Direct kinase phosphorylation by Gene X product")
        self.assertEqual(case_doc["claims"][0]["discriminating_test"], "Phosphorylation assay with kinase-dead mutant")

        self.engine.dispatch("freeze", {"case_id": case_id})

        # Test blind review packet
        blind_packet = self.engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim", "blind": True})
        self.assertTrue(blind_packet["blind"])
        self.assertIsNone(blind_packet["draft"])
        self.assertEqual(len(blind_packet["claims"]), 1)
        self.assertEqual(blind_packet["claims"][0]["best_current_explanation"], "Direct kinase phosphorylation by Gene X product")
        self.assertEqual(len(blind_packet["evidence"]), 1)

        # Test standard (non-blind) review packet
        standard_packet = self.engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim", "blind": False})
        self.assertFalse(standard_packet.get("blind", False))
        self.assertEqual(standard_packet["draft"], "Draft mentioning speculative hypothesis and preliminary results.")

        # Complete review, adjudication and export, verifying report rendering
        self.engine.dispatch("submit_review", {
            "case_id": case_id, "role": "overclaim", "packet_id": blind_packet["packet_id"],
            "input_digest": blind_packet["input_digest"],
            "reviewer": {"context_id": "rev-over", "model": "m"},
            "covered_claim_ids": ["C1"], "findings": [],
        })
        under_packet = self.engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim", "blind": True})
        self.engine.dispatch("submit_review", {
            "case_id": case_id, "role": "underclaim", "packet_id": under_packet["packet_id"],
            "input_digest": under_packet["input_digest"],
            "reviewer": {"context_id": "rev-under", "model": "m"},
            "covered_claim_ids": ["C1"], "findings": [],
        })
        adj_packet = self.engine.dispatch("adjudication_packet", {"case_id": case_id})
        self.engine.dispatch("submit_adjudication", {
            "case_id": case_id, "adjudication_id": adj_packet["adjudication_id"],
            "input_digest": adj_packet["input_digest"],
            "adjudicator": {"context_id": "adj-1", "model": "m"},
            "decisions": [{
                "claim_id": "C1", "verdict": "insufficient_evidence", "level": "mechanistic",
                "revised_text": "Gene X may participate in Pathway Y activation.",
                "rationale": "Direct mechanism lacks kinase-dead control.",
                "evidence_ids": [], "confidence": "low",
                "confidence_reason": "No kinase mutant assay yet.",
                "boundary": "In vitro preliminary cell culture only.",
                "reversal_condition": "Kinase mutant assay showing no phosphorylation.",
            }],
            "dispositions": [],
        })
        export_result = self.engine.dispatch("export", {"case_id": case_id})
        report_text = Path(export_result["path"]).read_text(encoding="utf-8")
        self.assertIn("Best current explanation: Direct kinase phosphorylation by Gene X product", report_text)
        self.assertIn("Discriminating test: Phosphorylation assay with kinase-dead mutant", report_text)

    def test_record_execution_event_scoping_and_cli_default_log_paths(self):
        import io
        import sys
        from parrhesia.cli import main as cli_main

        case_id = self.engine.dispatch("create_case", {
            "question": "Scoped execution runs?", "draft": "Draft", "writer_context_id": "writer",
        })["case_id"]
        c1_ev1 = self.engine.record_execution_event(case_id, {"card_id": "ex-1", "claim_id": "C1", "exit_status": 0})
        c2_ev1 = self.engine.record_execution_event(case_id, {"card_id": "ex-2", "claim_id": "C2", "exit_status": 0})
        c2_ev2 = self.engine.record_execution_event(case_id, {"card_id": "ex-3", "claim_id": "C2", "exit_status": 0})
        self.assertEqual(c1_ev1["fork_index"], 1)
        self.assertFalse(c1_ev1["multiplicity_required"])
        self.assertEqual(c2_ev1["fork_index"], 1)
        self.assertFalse(c2_ev1["multiplicity_required"])
        self.assertEqual(c2_ev2["fork_index"], 2)
        self.assertTrue(c2_ev2["multiplicity_required"])
        self.assertEqual(c2_ev2["case_exec_count"], 3)

        outputs = []
        for idx in range(2):
            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main([
                    "record-exec", "--workspace", str(self.workspace),
                    "--case-id", case_id, "--claim-id", f"CLI-{idx}",
                    "--", sys.executable, "-c", f"print('run-{idx}')",
                ])
            self.assertEqual(rc, 0)
            outputs.append(json.loads(buf.getvalue().decode("utf-8")))
        self.assertNotEqual(outputs[0]["log_path"], outputs[1]["log_path"])
        self.assertTrue(outputs[0]["log_path"].startswith("artifacts/exec-logs/"))
        self.assertIn("run-0", (self.workspace / outputs[0]["log_path"]).read_text(encoding="utf-8"))
        self.assertIn("run-1", (self.workspace / outputs[1]["log_path"]).read_text(encoding="utf-8"))

    def _v2_pass_claim(self, cid: str, claim_id: str, ev_id: str, text: str, est: str) -> dict:
        c = self.engine.dispatch("scaffold_claim", {
            "case_id": cid, "claim_id": claim_id, "claim_type": "association",
            "evidence_level": "unadjusted", "design_families": ["observational"],
        })["claim"]
        c["text"] = text
        c["scope"] = "Adult ICU retrospective cohort, 30-day mortality"
        c["origin"] = "exploratory"
        c["evidence_ids"] = [ev_id]
        c["effect"] = {"estimate": est, "uncertainty": "95% CI 11.0%-17.4%"}
        for name in ("quality", "unit", "assumptions"):
            c["checks"][name] = {"status": "pass", "reason": f"Checked {name} directly against {ev_id}"}
        for key in c["design_packages"][0]["checks"]:
            c["design_packages"][0]["checks"][key] = {
                "status": "pass",
                "reason": f"Verified {key} directly in {ev_id}",
                "evidence_ids": [ev_id],
            }
        for key in c["statistical_report"]:
            c["statistical_report"][key] = {
                "status": "pass",
                "reason": f"Verified statistical item {key} directly in {ev_id}",
                "evidence_ids": [ev_id],
            }
        return c

    def test_chunked_windows_preserve_budget_anchors_verify_and_old_digest(self):
        # 1. Omitting optional P1 fields preserves legacy _frozen_input key shape and digest.
        cid_compat = self.engine.dispatch("create_case", {
            "question": "Compat check?", "draft": "Draft", "writer_context_id": "writer",
        })["case_id"]
        (self.workspace / "small.txt").write_text("Mortality reduction 14.2% in N=850 ICU patients.\n", encoding="utf-8")
        ev_small = self.engine.dispatch("register_evidence", {
            "case_id": cid_compat, "path": "small.txt", "provenance": "observed",
            "kind": "observation", "quote": "Mortality reduction 14.2% in N=850", "location": "line 1",
        })
        self.assertNotIn("excerpt_anchors", ev_small)
        self.assertNotIn("derived_from_evidence_ids", ev_small)
        self.assertNotIn("derivation_step", ev_small)
        c_small = self._v2_pass_claim(cid_compat, "C1", ev_small["evidence_id"], "Mortality reduction 14.2% in N=850 ICU patients.", "14.2% reduction")
        self.engine.dispatch("set_ledger", {"case_id": cid_compat, "claims": [c_small]})
        frozen_compat = self.engine.dispatch("freeze", {"case_id": cid_compat})
        case_doc = self.engine.dispatch("get_case", {"case_id": cid_compat})
        expected_frozen = {k: case_doc[k] for k in ("case_id", "question", "domain", "draft", "claims", "evidence", "hypotheses", "schema_version", "gate_version", "blind")}
        self.assertEqual(frozen_compat["input_digest"], _digest(expected_frozen))

        # 2. Validation failures for bad excerpt_anchors.
        long_path = self.workspace / "large_multi.txt"
        head = "HEADER_META cohort=ICU-2025 design=retrospective protocol_v=2\n"
        anchor1 = "ANCHOR_SUBGROUP_A age>=65 mortality reduction 11.8% (n=410)."
        primary = "PRIMARY_RESULT mortality reduction 14.2% (95% CI 11.0%-17.4%) in N=850 patients."
        anchor2 = "ANCHOR_SENSITIVITY_B E-value=2.4; imputation robust across 500 draws."
        tail = "TAIL_SUMMARY analysis_completed=true checksum_note=final_summary_row\n"
        pad_block = "filler line without numbers or clinical signals alpha=0.05 table=9\n" * 800
        text_body = f"{head}{pad_block}{anchor1}\n{pad_block}{primary}\n{pad_block}{anchor2}\n{pad_block}{tail}"
        self.assertGreater(len(text_body.encode("utf-8")), PACKET_TEXT_BYTES)
        long_path.write_text(text_body, encoding="utf-8")

        cid = self.engine.dispatch("create_case", {
            "question": "Chunked windows?", "draft": "Draft", "writer_context_id": "writer",
        })["case_id"]
        with self.assertRaises(ContractError) as err_dup:
            self.engine.dispatch("register_evidence", {
                "case_id": cid, "path": "large_multi.txt", "provenance": "observed", "kind": "observation",
                "quote": primary, "location": "line 1602", "excerpt_anchors": [anchor1, anchor1],
            })
        self.assertEqual(err_dup.exception.code, "invalid_quote")
        with self.assertRaises(ContractError) as err_miss:
            self.engine.dispatch("register_evidence", {
                "case_id": cid, "path": "large_multi.txt", "provenance": "observed", "kind": "observation",
                "quote": primary, "location": "line 1602", "excerpt_anchors": ["nonexistent anchor string >12 chars"],
            })
        self.assertEqual(err_miss.exception.code, "invalid_quote")

        ev_id = self.engine.dispatch("register_evidence", {
            "case_id": cid, "path": "large_multi.txt", "provenance": "observed", "kind": "observation",
            "quote": primary, "location": "middle results section",
            "excerpt_anchors": [anchor1, anchor2],
        })["evidence_id"]
        c1 = self._v2_pass_claim(cid, "C1", ev_id, "Observed mortality reduction 14.2% (95% CI 11.0%-17.4%) in N=850 patients.", "14.2% reduction")
        self.engine.dispatch("set_ledger", {"case_id": cid, "claims": [c1]})
        frozen = self.engine.dispatch("freeze", {"case_id": cid})
        pkt = self.engine.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
        ev_pkt = pkt["evidence"][0]
        self.assertEqual(ev_pkt["source_text_status"], "truncated")
        src_text = ev_pkt["source_text"]
        self.assertLessEqual(len(src_text.encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEADER_META", src_text)
        self.assertIn(primary, src_text)
        self.assertIn(anchor1, src_text)
        self.assertIn(anchor2, src_text)
        self.assertIn("TAIL_SUMMARY", src_text)
        self.assertIn("<<<PARRHESIA_EXCERPT_WINDOW index=1", src_text)
        self.assertTrue(ev_pkt["excerpt_window"]["quote_anchored"])
        self.assertGreaterEqual(ev_pkt["excerpt_window"]["window_count"], 4)
        self.assertEqual(ev_pkt["excerpt_window"]["window_count"], len(ev_pkt["excerpt_windows"]))
        self.assertGreater(ev_pkt["excerpt_window"]["total_lines"], 3000)

        ver = self.engine.dispatch("verify", {"case_id": cid})
        self.assertEqual(ver["status"], "pass")
        self.assertEqual(ver["evidence"][0]["excerpt_window_count"], len(ev_pkt["excerpt_windows"]))

    def test_derived_evidence_lineage_verification_binary_ancestors_and_cli(self):
        import io
        import sys
        from parrhesia.cli import main as cli_main
        from parrhesia.report import render_report

        bin_path = self.workspace / "raw_assay.pdf"
        bin_path.write_bytes(b"%PDF-1.4\n\x00\x01\x02raw-binary-instrument-dump")
        summary_path = self.workspace / "summary_metrics.txt"
        summary_path.write_text("Parsed raw_assay.pdf: AUC = 0.87 (95% CI 0.81-0.93) in cohort N=240.\n", encoding="utf-8")

        cid = self.engine.dispatch("create_case", {
            "question": "Derived summary from hash-verified binary raw data?", "draft": "Draft", "writer_context_id": "writer",
        })["case_id"]
        ev_bin = self.engine.dispatch("register_evidence", {
            "case_id": cid, "path": "raw_assay.pdf", "provenance": "observed",
            "kind": "observation", "unread_content_ack": True,
        })["evidence_id"]

        # Orphan derivation_step without parents & unknown parent both fail cleanly.
        with self.assertRaises(ContractError) as err_orphan:
            self.engine.dispatch("register_evidence", {
                "case_id": cid, "path": "summary_metrics.txt", "provenance": "observed",
                "kind": "observation", "derivation_step": "Orphan derivation text",
            })
        self.assertEqual(err_orphan.exception.code, "missing_field")
        with self.assertRaises(ContractError) as err_unk:
            self.engine.dispatch("register_evidence", {
                "case_id": cid, "path": "summary_metrics.txt", "provenance": "observed",
                "kind": "observation", "derived_from_evidence_ids": ["nonexistent_ev"],
                "derivation_step": "Derived from missing parent",
            })
        self.assertEqual(err_unk.exception.code, "unknown_reference")

        # Register derived text log via CLI record-exec --derived-from / --derivation-step.
        buf = io.BytesIO()
        with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
            rc = cli_main([
                "record-exec", "--workspace", str(self.workspace),
                "--case-id", cid, "--claim-id", "C1", "--kind", "auto",
                "--derived-from", ev_bin,
                "--derivation-step", "Extracted summary AUC = 0.87 from raw_assay.pdf via verified parser",
                "--", sys.executable, "-c", "print('Derived result: AUC = 0.87 (95% CI 0.81-0.93) in N=240.')",
            ])
        self.assertEqual(rc, 0)
        cli_out = json.loads(buf.getvalue().decode("utf-8"))
        ev_log = cli_out["evidence"]["evidence_id"]
        self.assertEqual(cli_out["evidence"]["kind"], "unknown")
        # A print-only command receipt is not an observational study. Keep this
        # lineage test's scientific source as the separately registered summary.
        ev_derived = self.engine.dispatch("register_evidence", {
            "case_id": cid, "path": "summary_metrics.txt", "kind": "observation", "provenance": "reported",
            "quote": "AUC = 0.87 (95% CI 0.81-0.93)", "location": "L1", "derived_from_evidence_ids": [ev_bin],
            "derivation_step": "Fixture summary of the registered binary source; not a CLI execution attestation",
        })["evidence_id"]
        self.assertEqual(cli_out["derived_from_evidence_ids"], [ev_bin])
        self.assertEqual(cli_out["evidence"]["derived_from_evidence_ids"], [ev_bin])

        case_events = self.engine.dispatch("get_case", {"case_id": cid})["events"]
        exec_ev = next(e for e in case_events if e["action"] == "record_exec")
        self.assertEqual(exec_ev["details"]["derived_from_evidence_ids"], [ev_bin])

        c1 = self._v2_pass_claim(cid, "C1", ev_derived, "Derived result: AUC = 0.87 (95% CI 0.81-0.93) in N=240.", "AUC 0.87")
        c1["evidence_ids"] = [ev_derived, ev_bin, ev_log]
        c1["effect"]["uncertainty"] = "95% CI 0.81-0.93"
        c1["provenance_cards"]["execution"] = [cli_out["execution_card"]]
        self.engine.dispatch("set_ledger", {"case_id": cid, "claims": [c1]})
        frozen = self.engine.dispatch("freeze", {"case_id": cid})
        for role, ctx in (("overclaim", "rev-over"), ("underclaim", "rev-under")):
            pkt = self.engine.dispatch("review_packet", {"case_id": cid, "role": role})
            self.engine.dispatch("submit_review", {
                "case_id": cid, "role": role, "packet_id": pkt["packet_id"], "input_digest": frozen["input_digest"],
                "reviewer": {"context_id": ctx, "model": "fixture"}, "covered_claim_ids": ["C1"],
                "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Verified derived summary and supplemental execution receipt", "evidence_ids": [ev_derived, ev_log]}],
                "unread_evidence_ids": [ev_bin], "findings": [],
            })
        adj_pkt = self.engine.dispatch("adjudication_packet", {"case_id": cid})
        self.engine.dispatch("submit_adjudication", {
            "case_id": cid, "adjudication_id": adj_pkt["adjudication_id"], "input_digest": adj_pkt["input_digest"],
            "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [ev_bin],
            "dispositions": [],
            "decisions": [{
                "claim_id": "C1", "claim_basis": "empirical", "claim_type": "association",
                "evidence_level": "unadjusted", "scope": c1["scope"], "verdict": "supported",
                "revised_text": "Derived summary shows AUC = 0.87 (95% CI 0.81-0.93) in N=240.",
                "rationale": "Cites readable verified derived output traced to hash-verified binary raw_assay.pdf",
                "evidence_ids": [ev_derived, ev_log], "confidence": "medium", "confidence_reason": "Binary ancestor SHA-256 matched",
                "boundary": "Cohort summary only", "reversal_condition": "Re-extraction discrepancy on raw_assay.pdf",
            }],
        })
        ver_ok = self.engine.dispatch("verify", {"case_id": cid})
        derived_ver = next(e for e in ver_ok["evidence"] if e["evidence_id"] == ev_derived)
        self.assertEqual(derived_ver["lineage_status"], "hash_verified_unread_binary_ancestors")
        self.assertEqual(derived_ver["status"], "pass")
        self.assertEqual(ver_ok["evidence_chains"][0]["lineage_status"], "hash_verified_unread_binary_ancestors")

        # Exporting positive verdict citing derived summary SUCCEEDS despite binary ancestor unread status!
        exp = self.engine.dispatch("export", {"case_id": cid})
        md_report = Path(exp["path"]).read_text(encoding="utf-8")
        self.assertIn("hash_verified_unread_binary_ancestors", md_report)
        self.assertIn("Non-blocking Advisory / 非强制性反低估审计提示", md_report)
        html_path = self.workspace / "report.html"
        render_report(self.engine.dispatch("get_case", {"case_id": cid}), html_path)
        html_text = html_path.read_text(encoding="utf-8")
        self.assertIn("hash_verified_unread_binary_ancestors", html_text)
        self.assertIn("Non-blocking Advisory / 非强制性反低估审计提示", html_text)

        # Missing vs corrupted binary ancestor blocks/downgrades derived leaf on verify & export!
        cid_bad = self.engine.dispatch("create_case", {
            "question": "Corrupted ancestor?", "draft": "Draft", "writer_context_id": "writer",
        })["case_id"]
        ev_bin2 = self.engine.dispatch("register_evidence", {
            "case_id": cid_bad, "path": "raw_assay.pdf", "provenance": "observed",
            "kind": "observation", "unread_content_ack": True,
        })["evidence_id"]
        ev_der2 = self.engine.dispatch("register_evidence", {
            "case_id": cid_bad, "path": "summary_metrics.txt", "provenance": "observed",
            "kind": "observation", "quote": "AUC = 0.87 (95% CI 0.81-0.93)", "location": "line 1",
            "derived_from_evidence_ids": [ev_bin2], "derivation_step": "Aggregated table",
        })["evidence_id"]
        c2 = self._v2_pass_claim(cid_bad, "C1", ev_der2, "AUC = 0.87 (95% CI 0.81-0.93).", "AUC 0.87")
        c2["evidence_ids"] = [ev_der2, ev_bin2]
        c2["effect"]["uncertainty"] = "95% CI 0.81-0.93"
        self.engine.dispatch("set_ledger", {"case_id": cid_bad, "claims": [c2]})
        fr2 = self.engine.dispatch("freeze", {"case_id": cid_bad})
        for role, ctx in (("overclaim", "o2"), ("underclaim", "u2")):
            p2 = self.engine.dispatch("review_packet", {"case_id": cid_bad, "role": role})
            self.engine.dispatch("submit_review", {
                "case_id": cid_bad, "role": role, "packet_id": p2["packet_id"], "input_digest": fr2["input_digest"],
                "reviewer": {"context_id": ctx, "model": "fixture"}, "covered_claim_ids": ["C1"],
                "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Derived text checked", "evidence_ids": [ev_der2]}],
                "unread_evidence_ids": [ev_bin2], "findings": [],
            })
        ap2 = self.engine.dispatch("adjudication_packet", {"case_id": cid_bad})
        self.engine.dispatch("submit_adjudication", {
            "case_id": cid_bad, "adjudication_id": ap2["adjudication_id"], "input_digest": ap2["input_digest"],
            "adjudicator": {"context_id": "a2", "model": "fixture"}, "unread_evidence_ids": [ev_bin2],
            "dispositions": [], "decisions": [{
                "claim_id": "C1", "claim_basis": "empirical", "claim_type": "association",
                "evidence_level": "unadjusted", "scope": c2["scope"], "verdict": "supported",
                "revised_text": "AUC = 0.87 (95% CI 0.81-0.93).", "rationale": "Derived metric",
                "evidence_ids": [ev_der2], "confidence": "medium", "confidence_reason": "Anchored",
                "boundary": "Single dataset", "reversal_condition": "Hash mismatch",
            }],
        })
        bin_path.unlink()
        ver_miss = self.engine.dispatch("verify", {"case_id": cid_bad})
        der2_miss = next(e for e in ver_miss["evidence"] if e["evidence_id"] == ev_der2)
        self.assertEqual(der2_miss["lineage_status"], "unverified")
        self.assertEqual(der2_miss["status"], "unverified")
        self.error("unverified_support", "export", {"case_id": cid_bad})

        bin_path.write_bytes(b"%PDF-1.4\n\x00corrupted-raw-binary")
        ver_blk = self.engine.dispatch("verify", {"case_id": cid_bad})
        der2_blk = next(e for e in ver_blk["evidence"] if e["evidence_id"] == ev_der2)
        self.assertEqual(der2_blk["lineage_status"], "blocked")
        self.assertEqual(ver_blk["status"], "blocked")
        self.error("verification_mismatch", "export", {"case_id": cid_bad})

    def test_build_chunked_windows_enforces_budget_cap_head_retention_and_total_chars(self):
        from parrhesia.core import Engine, PACKET_TEXT_BYTES

        head = "HEAD_LINE_1 protocol=strict study=ICU-2026\n"
        tail = "\nTAIL_SUMMARY analysis_done=true\n"
        filler = "x" * 2000

        # 1. 140,000-char quote: must stay <= 131072 B, preserve HEAD_LINE_1, set quote_anchored=False, record total_chars.
        q140 = "Q140_" + ("a" * 139995)
        src140 = f"{head}{filler}\n{q140}{tail}"
        rendered140, wins140, sum140 = Engine._build_chunked_windows(src140, q140, None)
        self.assertLessEqual(len(rendered140.encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEAD_LINE_1", rendered140)
        self.assertFalse(sum140["quote_anchored"])
        self.assertTrue(all(w["total_chars"] == len(src140) for w in wins140))

        # End-to-end positive adjudication on clipped >128 KiB quote rejects as unread_positive_evidence.
        cid140 = self.engine.dispatch("create_case", {
            "question": "Oversized quote?", "draft": "Draft", "writer_context_id": "writer",
        })["case_id"]
        (self.workspace / "q140.txt").write_text(f"{head}{filler}\n{q140} OR = 1.50 (95% CI 1.10-2.05)\n", encoding="utf-8")
        ev140 = self.engine.dispatch("register_evidence", {
            "case_id": cid140, "path": "q140.txt", "provenance": "observed", "kind": "observation",
            "quote": q140, "location": "line 2", "unread_content_ack": True,
        })["evidence_id"]
        c140 = self._v2_pass_claim(cid140, "C1", ev140, "OR = 1.50 (95% CI 1.10-2.05) mortality reduction 14.2%.", "OR = 1.50")
        c140["effect"]["uncertainty"] = "95% CI 1.10-2.05"
        self.engine.dispatch("set_ledger", {"case_id": cid140, "claims": [c140]})
        fr140 = self.engine.dispatch("freeze", {"case_id": cid140})
        pkt140 = self.engine.dispatch("review_packet", {"case_id": cid140, "role": "overclaim"})
        ev_pkt140 = pkt140["evidence"][0]
        self.assertLessEqual(len(ev_pkt140["source_text"].encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEAD_LINE_1", ev_pkt140["source_text"])
        self.assertFalse(ev_pkt140["excerpt_window"]["quote_anchored"])
        for role, ctx in (("overclaim", "o140"), ("underclaim", "u140")):
            pr = self.engine.dispatch("review_packet", {"case_id": cid140, "role": role})
            self.engine.dispatch("submit_review", {
                "case_id": cid140, "role": role, "packet_id": pr["packet_id"], "input_digest": fr140["input_digest"],
                "reviewer": {"context_id": ctx, "model": "fixture"}, "covered_claim_ids": ["C1"],
                "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Clipped quote", "evidence_ids": []}],
                "unread_evidence_ids": [ev140], "findings": [],
            })
        ap140 = self.engine.dispatch("adjudication_packet", {"case_id": cid140})
        self.error("unread_positive_evidence", "submit_adjudication", {
            "case_id": cid140, "adjudication_id": ap140["adjudication_id"], "input_digest": ap140["input_digest"],
            "adjudicator": {"context_id": "a140", "model": "fixture"}, "unread_evidence_ids": [ev140],
            "dispositions": [], "decisions": [{
                "claim_id": "C1", "claim_basis": "empirical", "claim_type": "association",
                "evidence_level": "unadjusted", "scope": c140["scope"], "verdict": "supported",
                "revised_text": c140["text"], "rationale": "Attempt positive on clipped quote",
                "evidence_ids": [ev140], "confidence": "low", "confidence_reason": "Attempted",
                "boundary": "Sample", "reversal_condition": "Lower effect",
            }],
        })

        # 2. 131,000-char quote: capped <= 131072 B, retains HEAD_LINE_1, sets quote_anchored=False.
        q131 = "Q131_" + ("b" * 130995)
        src131 = f"{head}{filler}\n{q131}{tail}"
        rendered131, wins131, sum131 = Engine._build_chunked_windows(src131, q131, None)
        self.assertLessEqual(len(rendered131.encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEAD_LINE_1", rendered131)
        self.assertFalse(sum131["quote_anchored"])

        # 3. 130,000-char quote: fits alongside compact HEAD_LINE_1 with quote_anchored=True.
        q130 = "Q130_" + ("c" * 129995)
        src130 = f"{head}{filler}\n{q130}{tail}"
        rendered130, wins130, sum130 = Engine._build_chunked_windows(src130, q130, None)
        self.assertLessEqual(len(rendered130.encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEAD_LINE_1", rendered130)
        self.assertTrue(sum130["quote_anchored"])

        # 4. 4 x 35,000-char anchors + normal quote: sheds trailing anchors first, keeps head + quote + <=131072 B.
        q_small = "PRIMARY_QUOTE_MARKER_123456"
        anchors_4x35 = [f"A{i}_" + (chr(ord("d") + i) * 34997) for i in range(4)]
        src_4x = f"{head}{filler}\n{q_small}\n" + "\n".join(anchors_4x35) + tail
        rendered_4x, wins_4x, sum_4x = Engine._build_chunked_windows(src_4x, q_small, anchors_4x35)
        self.assertLessEqual(len(rendered_4x.encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEAD_LINE_1", rendered_4x)
        self.assertIn(q_small, rendered_4x)
        self.assertTrue(sum_4x["quote_anchored"])
        self.assertIn("A0_", rendered_4x)
        self.assertIn("A1_", rendered_4x)
        self.assertIn("A2_", rendered_4x)
        self.assertNotIn("A3_", rendered_4x)

        # 5. Multi-byte UTF-8 oversized quote stays <= budget_bytes with valid UTF-8 boundary slicing.
        q_cjk = "结论" * 30000  # 60,000 chars == 180,000 UTF-8 bytes > 131,072
        src_cjk = f"{head}{q_cjk}{tail}"
        rendered_cjk, wins_cjk, sum_cjk = Engine._build_chunked_windows(src_cjk, q_cjk, None)
        self.assertLessEqual(len(rendered_cjk.encode("utf-8")), PACKET_TEXT_BYTES)
        self.assertIn("HEAD_LINE_1", rendered_cjk)
        self.assertFalse(sum_cjk["quote_anchored"])
        self.assertTrue(all(w["total_chars"] == len(src_cjk) for w in wins_cjk))

    def test_export_fallback_to_exclusive_open_on_link_permission_and_oserror(self):
        self.adjudicate()
        with patch("parrhesia.core.os.link", side_effect=PermissionError("hard links disabled")):
            result = self.engine.dispatch("export", {"case_id": self.case})
        self.assertEqual("exported", result["state"])
        target = Path(result["path"])
        raw_bytes = target.read_bytes()
        self.assertEqual(hashlib.sha256(raw_bytes).hexdigest(), result["sha256"])
        self.assertNotIn(b"\r\n", raw_bytes)
        self.assertEqual([], list(target.parent.glob(".parrhesia-export-*.tmp")))

        # Cross-device / unsupported link OSError also falls back atomically without corruption.
        with tempfile.TemporaryDirectory(prefix="exdev-", dir=self.workspace.parent) as tmp2:
            ws2 = Path(tmp2)
            eng2 = Engine(ws2)
            (ws2 / "evidence.txt").write_text("Synthetic engineering fixture. Effect = 2; CI [1, 3].\n", encoding="utf-8")
            cid2 = seed_legacy_case(eng2, {
                "schema_version": 1,
                "question": "Does EXDEV fallback preserve bytes?",
                "draft": "An example draft, with no scientific-validity claim.",
                "writer_context_id": "writer",
            })["case_id"]
            ev2 = eng2.dispatch("register_evidence", {
                "case_id": cid2, "path": "evidence.txt", "provenance": "synthetic", "quote": "Effect = 2",
            })["evidence_id"]
            claim2 = deepcopy(self.claim)
            claim2["evidence_ids"] = [ev2]
            eng2.dispatch("set_ledger", {"case_id": cid2, "claims": [claim2]})
            eng2.dispatch("freeze", {"case_id": cid2})
            for role in ("overclaim", "underclaim"):
                pkt = eng2.dispatch("review_packet", {"case_id": cid2, "role": role})
                eng2.dispatch("submit_review", {
                    "case_id": cid2, "role": role, "packet_id": pkt["packet_id"], "input_digest": pkt["input_digest"],
                    "reviewer": {"context_id": f"fresh-{role}", "model": "same-model-is-permitted"},
                    "covered_claim_ids": ["C1"], "findings": [],
                })
            adj_pkt = eng2.dispatch("adjudication_packet", {"case_id": cid2})
            eng2.dispatch("submit_adjudication", {
                "case_id": cid2, "adjudication_id": adj_pkt["adjudication_id"], "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": "writer", "model": "same-model-is-permitted"},
                "decisions": [{
                    "claim_id": "C1", "verdict": "supported", "level": "descriptive",
                    "revised_text": "The synthetic fixture states effect 2.", "rationale": "Direct literal statement only",
                    "evidence_ids": [ev2], "confidence": "high", "confidence_reason": "Literal quote matches",
                    "boundary": "No scientific inference beyond fixture contents",
                    "reversal_condition": "A different source statement would change this judgment",
                }],
                "dispositions": [],
            })
            with patch("parrhesia.core.os.link", side_effect=OSError(errno.EXDEV, "cross-device link")):
                res2 = eng2.dispatch("export", {"case_id": cid2, "path": "exports/exdev.md"})
            self.assertEqual("exported", res2["state"])
            target2 = Path(res2["path"])
            self.assertEqual(hashlib.sha256(target2.read_bytes()).hexdigest(), res2["sha256"])
            self.assertEqual([], list(target2.parent.glob(".parrhesia-export-*.tmp")))

    def test_export_fallback_preserves_non_overwrite_on_concurrent_file_exists(self):
        self.adjudicate()
        with patch("parrhesia.core.os.link", side_effect=PermissionError("blocked")), self._fail_export_target_open(
            FileExistsError("concurrent destination")
        ):
            self.error("export_exists", "export", {"case_id": self.case})
        case = self.engine.dispatch("get_case", {"case_id": self.case})
        self.assertEqual("export_pending", case["state"])

        # FileExistsError directly from os.link must NOT invoke the fallback writer.
        with patch("parrhesia.core.os.link", side_effect=FileExistsError("already created")), patch(
            "parrhesia.core._write_exclusive_export"
        ) as fallback_mock:
            self.error("export_exists", "export", {"case_id": self.case})
        fallback_mock.assert_not_called()

    def test_export_rejects_non_markdown_extension(self):
        self.adjudicate()
        self.error("invalid_export_path", "export", {"case_id": self.case, "path": "exports/report.html"})

    def test_register_evidence_indexed_kind_restriction_avoids_cases_full_scan(self):
        # Create several unrelated cases that must never be deserialized during another case's registration.
        marker = "UNRELATED_CASE_SHOULD_NOT_BE_DESERIALIZED"
        unrelated_file = self.workspace / "unrelated_doc.txt"
        unrelated_file.write_text("Unrelated background note with unique phrase 123456.\n", encoding="utf-8")
        for idx in range(5):
            cid = self.engine.dispatch("create_case", {
                "question": f"{marker}_{idx}", "draft": "Draft text", "writer_context_id": "writer",
            })["case_id"]
            self.engine.dispatch("register_evidence", {
                "case_id": cid, "path": "unrelated_doc.txt", "provenance": "observed", "kind": "observation",
                "quote": "Unrelated background note with unique phrase 123456.", "location": "L1",
            })

        stats_path = self.workspace / "stats.json"
        stats_path.write_text('{"rules": {"fit": {"runtime": 1.2}}, "total_runtime": 1.2}\n', encoding="utf-8")
        src_cid = self.engine.dispatch("create_case", {
            "question": f"{marker}_importer", "draft": "Draft text", "writer_context_id": "writer",
        })["case_id"]
        imported = self.engine.dispatch("import_artifact", {
            "case_id": src_cid, "path": "stats.json", "artifact_format": "snakemake_stats",
        })
        restricted_kind = imported["evidence"]["kind"]
        self.assertEqual(restricted_kind, "unknown")

        # Copy exact bytes to a generic extension so restriction enforcement relies on the SHA-256 index.
        copy_path = self.workspace / "copied.txt"
        copy_path.write_bytes(stats_path.read_bytes())

        dst_cid = self.engine.dispatch("create_case", {
            "question": "Destination case", "draft": "Draft text", "writer_context_id": "writer",
        })["case_id"]

        # Dry-run validate_action rolls back any inserted restriction row cleanly.
        dry = self.engine.validate_action("register_evidence", {
            "case_id": dst_cid, "path": "unrelated_doc.txt", "provenance": "observed", "kind": "observation",
            "quote": "Unrelated background note with unique phrase 123456.", "location": "L1",
        })
        self.assertTrue(dry["valid"])

        real_loads = json.loads
        seen_blobs: list[str] = []

        def tracked_loads(text, *args, **kwargs):
            seen_blobs.append(text)
            return real_loads(text, *args, **kwargs)

        with patch("parrhesia.core.json.loads", side_effect=tracked_loads):
            with self.assertRaises(ContractError) as cm:
                self.engine.dispatch("register_evidence", {
                    "case_id": dst_cid, "path": "copied.txt", "provenance": "observed",
                    "kind": "observation", "quote": '"total_runtime": 1.2', "location": "L1",
                })
            self.assertEqual(cm.exception.code, "kind_upgrade_forbidden")
            registered = self.engine.dispatch("register_evidence", {
                "case_id": dst_cid, "path": "copied.txt", "provenance": "observed",
                "kind": "unknown", "quote": '"total_runtime": 1.2', "location": "L1",
            })

        self.assertEqual(registered["kind"], "unknown")
        self.assertEqual(registered["kind_inference"]["format"], "snakemake_stats")
        self.assertFalse(any(marker in blob for blob in seen_blobs))


if __name__ == "__main__":
    unittest.main()
