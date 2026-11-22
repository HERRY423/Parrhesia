"""Regression tests for git/diff provenance visibility and internal artifact filtering."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from parrhesia.provenance import (
    _hash_git_diff,
    collect_git_state,
    synthesize_code_version,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return proc.stdout.strip()


def _init_git_repo(root: Path) -> str:
    _git(root, "init")
    _git(root, "config", "user.name", "Parrhesia Test")
    _git(root, "config", "user.email", "test@parrhesia.local")
    (root / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-m", "init")
    return _git(root, "rev-parse", "HEAD")


class _FakePopenCM:
    def __init__(self, stdout_chunks: list[bytes], wait_side_effect=None, wait_rc: int = 0):
        self._chunks = list(stdout_chunks)
        self._wait_side_effect = wait_side_effect
        self._wait_rc = wait_rc
        self.killed = False
        self.stdout = MagicMock()
        self.stdout.read.side_effect = self._read

    def _read(self, _n: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def wait(self, timeout: float | None = None) -> int:
        if self._wait_side_effect is not None and not self.killed:
            raise self._wait_side_effect
        return self._wait_rc

    def kill(self) -> None:
        self.killed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "artifacts" / "test-workspaces"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="prov-", dir=base)
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_hash_git_diff_distinguishes_timeout_error_and_clean(self):
        timeout_proc = _FakePopenCM(
            [b"partial-diff", b""],
            wait_side_effect=subprocess.TimeoutExpired(cmd=["git", "diff"], timeout=10.0),
        )
        with patch("parrhesia.provenance.subprocess.Popen", return_value=timeout_proc):
            sha, size, status = _hash_git_diff(self.root, ["diff", "--binary"])
        self.assertIsNone(sha)
        self.assertEqual(size, 0)
        self.assertEqual(status, "timed_out")
        self.assertTrue(timeout_proc.killed)

        err_proc = _FakePopenCM([b""], wait_rc=128)
        with patch("parrhesia.provenance.subprocess.Popen", return_value=err_proc):
            sha, size, status = _hash_git_diff(self.root, ["diff", "--binary"])
        self.assertIsNone(sha)
        self.assertEqual(size, 0)
        self.assertEqual(status, "error")

        with patch("parrhesia.provenance.subprocess.Popen", side_effect=OSError("no git")):
            sha, size, status = _hash_git_diff(self.root, ["diff", "--binary"])
        self.assertIsNone(sha)
        self.assertEqual(size, 0)
        self.assertEqual(status, "error")

        clean_proc = _FakePopenCM([b""], wait_rc=0)
        with patch("parrhesia.provenance.subprocess.Popen", return_value=clean_proc):
            sha, size, status = _hash_git_diff(self.root, ["diff", "--binary"])
        self.assertEqual(sha, hashlib.sha256(b"").hexdigest())
        self.assertEqual(size, 0)
        self.assertEqual(status, "ok")

    def test_collect_git_state_and_code_version_expose_diff_timeouts_and_errors(self):
        head_sha = _init_git_repo(self.root)
        sha12 = head_sha[:12]

        # Clean baseline includes explicit ok status and False timeout flags.
        clean_state = collect_git_state(self.root)
        self.assertTrue(clean_state["git_available"])
        self.assertFalse(clean_state["dirty"])
        self.assertEqual(clean_state["working_tree_diff_status"], "ok")
        self.assertFalse(clean_state["working_tree_diff_timed_out"])
        self.assertEqual(clean_state["staged_diff_status"], "ok")
        self.assertFalse(clean_state["staged_diff_timed_out"])
        self.assertTrue(clean_state["status_ok"])
        self.assertEqual(synthesize_code_version(clean_state, []), f"git:{sha12}(clean)")

        # Timeout when working tree is clean must NOT report clean.
        empty_sha = hashlib.sha256(b"").hexdigest()
        with patch(
            "parrhesia.provenance._hash_git_diff",
            side_effect=[(None, 0, "timed_out"), (empty_sha, 0, "ok")],
        ):
            clean_timeout_state = collect_git_state(self.root)
        self.assertTrue(clean_timeout_state["working_tree_diff_timed_out"])
        self.assertIsNone(clean_timeout_state["working_tree_diff_sha256"])
        clean_timeout_ver = synthesize_code_version(clean_timeout_state, [])
        self.assertIn("working_tree_diff_timed_out", clean_timeout_ver)
        self.assertNotEqual(clean_timeout_ver, f"git:{sha12}(clean)")

        # Dirty working tree whose diff times out must NOT mask timeout as plain "dirty".
        (self.root / "app.py").write_text("print('v2')\n", encoding="utf-8")
        with patch(
            "parrhesia.provenance._hash_git_diff",
            side_effect=[(None, 0, "timed_out"), (empty_sha, 0, "ok")],
        ):
            dirty_timeout_state = collect_git_state(self.root)
        self.assertTrue(dirty_timeout_state["dirty"])
        self.assertTrue(dirty_timeout_state["working_tree_diff_timed_out"])
        self.assertEqual(dirty_timeout_state["working_tree_diff_status"], "timed_out")
        dirty_timeout_ver = synthesize_code_version(dirty_timeout_state, [])
        self.assertNotEqual(dirty_timeout_ver, f"git:{sha12}(dirty)")
        self.assertIn("working_tree_diff_timed_out", dirty_timeout_ver)

        # Subprocess diff error must mark unavailable rather than clean or plain dirty.
        with patch(
            "parrhesia.provenance._hash_git_diff",
            side_effect=[(None, 0, "error"), (None, 0, "timed_out")],
        ):
            err_state = collect_git_state(self.root)
        self.assertFalse(err_state["working_tree_diff_timed_out"])
        self.assertEqual(err_state["working_tree_diff_status"], "error")
        self.assertTrue(err_state["staged_diff_timed_out"])
        err_ver = synthesize_code_version(err_state, [])
        self.assertIn("working_tree_diff_unavailable", err_ver)
        self.assertIn("staged_diff_timed_out", err_ver)

        # Legacy 2-tuple patch compatibility + failed git status visibility.
        real_run_git = None
        from parrhesia import provenance as prov_mod
        real_run_git = prov_mod._run_git

        def fail_status(ws: Path, args: list[str]):
            if args and args[0] == "status":
                return subprocess.CompletedProcess(["git", *args], returncode=128, stdout=b"", stderr=b"")
            return real_run_git(ws, args)

        with patch("parrhesia.provenance._run_git", side_effect=fail_status), patch(
            "parrhesia.provenance._hash_git_diff", side_effect=[(None, 0), (empty_sha, 0)]
        ):
            bad_status_state = collect_git_state(self.root)
        self.assertFalse(bad_status_state["status_ok"])
        bad_status_ver = synthesize_code_version(bad_status_state, [])
        self.assertIn("working_tree_diff_unavailable", bad_status_ver)
        self.assertIn("git_status_unavailable", bad_status_ver)

    def test_internal_prefixes_ignore_parrhesia_internals_but_flag_dirty_code(self):
        head_sha = _init_git_repo(self.root)
        sha12 = head_sha[:12]

        # Parrhesia workspace-internal files at root do not mark git dirty.
        (self.root / ".parrhesia").mkdir(parents=True, exist_ok=True)
        (self.root / ".parrhesia" / "state.sqlite3").write_bytes(b"sqlite")
        (self.root / "artifacts" / "exec-logs").mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts" / "exec-logs" / "exec-1.log").write_text("ok\n", encoding="utf-8")

        internal_state = collect_git_state(self.root)
        self.assertFalse(internal_state["dirty"])
        self.assertFalse(internal_state["tracked_dirty"])
        self.assertEqual(internal_state["untracked_count"], 0)
        self.assertEqual(synthesize_code_version(internal_state, []), f"git:{sha12}(clean)")

        # Subdirectory workspace also ignores its own internal state/log prefixes.
        import shutil
        shutil.rmtree(self.root / ".parrhesia")
        shutil.rmtree(self.root / "artifacts")
        sub_ws = self.root / "nested" / "ws"
        (sub_ws / ".parrhesia").mkdir(parents=True, exist_ok=True)
        (sub_ws / ".parrhesia" / "state.sqlite3").write_bytes(b"sqlite")
        (sub_ws / "artifacts" / "exec-logs").mkdir(parents=True, exist_ok=True)
        (sub_ws / "artifacts" / "exec-logs" / "exec-2.log").write_text("ok\n", encoding="utf-8")
        sub_state = collect_git_state(sub_ws)
        self.assertFalse(sub_state["dirty"])
        self.assertEqual(sub_state["untracked_count"], 0)
        shutil.rmtree(self.root / "nested")

        # Untracked code in exports/ or artifacts/ (outside exec-logs/) still flags dirty=True cleanly.
        (self.root / "exports").mkdir(exist_ok=True)
        (self.root / "exports" / "dirty.py").write_text("x = 1\n", encoding="utf-8")
        dirty_exports_state = collect_git_state(self.root)
        self.assertTrue(dirty_exports_state["dirty"])
        self.assertEqual(dirty_exports_state["untracked_count"], 1)
        self.assertEqual(synthesize_code_version(dirty_exports_state, []), f"git:{sha12}(untracked=1)")

        # Non-exec-log artifact under artifacts/ also flags dirty=True.
        (self.root / "exports" / "dirty.py").unlink()
        (self.root / "artifacts" / "exec-logs").mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts" / "model.py").write_text("y = 2\n", encoding="utf-8")
        dirty_art_state = collect_git_state(self.root)
        self.assertTrue(dirty_art_state["dirty"])
        self.assertEqual(dirty_art_state["untracked_count"], 1)

    def test_verified_exports_and_agentmuxer_ledger_stay_clean_while_tampering_flags_dirty(self):
        from parrhesia.core import Engine

        head_sha = _init_git_repo(self.root)
        sha12 = head_sha[:12]

        # Optional `.agentmuxer/ledger.md` does not pollute clean repo state, whereas other files there do.
        (self.root / ".agentmuxer").mkdir(exist_ok=True)
        (self.root / ".agentmuxer" / "ledger.md").write_text("# ledger entry\n", encoding="utf-8")
        muxer_clean = collect_git_state(self.root)
        self.assertFalse(muxer_clean["dirty"])
        self.assertEqual(synthesize_code_version(muxer_clean, []), f"git:{sha12}(clean)")

        (self.root / ".agentmuxer" / "helper.py").write_text("print(1)\n", encoding="utf-8")
        muxer_dirty = collect_git_state(self.root)
        self.assertTrue(muxer_dirty["dirty"])
        self.assertEqual(muxer_dirty["untracked_count"], 1)
        (self.root / ".agentmuxer" / "helper.py").unlink()

        # Commit source fixture, run full v2 workflow to produce a SQLite-recorded `.md` export.
        src = self.root / "obs.txt"
        src.write_text("Cohort observation showed 14 events in 100 patients.\n", encoding="utf-8")
        _git(self.root, "add", "obs.txt")
        _git(self.root, "commit", "-m", "add obs source")
        head_sha = _git(self.root, "rev-parse", "HEAD")
        sha12 = head_sha[:12]

        engine = Engine(self.root)
        case_id = engine.dispatch("create_case", {
            "question": "How many events occurred in the cohort?",
            "draft": "Fourteen events occurred in 100 patients.",
            "writer_context_id": "writer-ctx",
        })["case_id"]
        ev_id = engine.dispatch("register_evidence", {
            "case_id": case_id,
            "path": "obs.txt",
            "provenance": "observed",
            "kind": "observation",
            "quote": "Cohort observation showed 14 events in 100 patients.",
            "location": "obs.txt:1",
        })["evidence_id"]
        from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS
        from parrhesia.contracts import CHECK_NAMES

        claim = engine.dispatch("scaffold_claim", {
            "case_id": case_id,
            "claim_type": "description",
            "evidence_level": "recorded",
            "text": "Cohort observation recorded 14 events in 100 patients.",
            "scope": "Cohort of 100 patients in obs.txt",
        })["claim"]
        claim["evidence_ids"] = [ev_id]
        claim["effect"] = {"estimate": "14 events", "uncertainty": "UNKNOWN"}
        claim["contribution"] = "Records cohort event count"
        claim["checks"] = {
            name: {"status": "pass", "reason": "Source obs.txt:1 verified"}
            for name in CHECK_NAMES
        }
        claim["design_packages"] = [{
            "family": "observational",
            "checks": {
                key: {"status": "pass", "reason": "Verified against obs.txt:1", "evidence_ids": [ev_id]}
                for key in DESIGN_FIELDS["observational"]
            },
        }]
        claim["statistical_report"] = {
            key: {"status": "pass", "reason": "Count denominator in obs.txt:1", "evidence_ids": [ev_id]}
            for key in STAT_FIELDS
        }
        claim["provenance_cards"] = {key: [] for key in CARD_FIELDS}
        claim["alternatives"] = [{
            "explanation": "Misread row denominator",
            "status": "excluded",
            "reason": "Direct line obs.txt:1 specifies 100 patients",
        }]
        engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
        engine.dispatch("freeze", {"case_id": case_id})
        for role in ("overclaim", "underclaim"):
            pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": role})
            engine.dispatch("submit_review", {
                "case_id": case_id,
                "role": role,
                "packet_id": pkt["packet_id"],
                "input_digest": pkt["input_digest"],
                "reviewer": {"context_id": f"{role}-ctx", "model": "same"},
                "covered_claim_ids": ["C1"],
                "unread_evidence_ids": [],
                "claim_stances": [{
                    "claim_id": "C1",
                    "stance": "supported",
                    "rationale": "Exact match to obs.txt:1",
                    "evidence_ids": [ev_id],
                }],
                "findings": [],
            })
        adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
        engine.dispatch("submit_adjudication", {
            "case_id": case_id,
            "adjudication_id": adj_pkt["adjudication_id"],
            "input_digest": adj_pkt["input_digest"],
            "adjudicator": {"context_id": "writer-ctx", "model": "same"},
            "unread_evidence_ids": [],
            "decisions": [{
                "claim_id": "C1",
                "verdict": "supported",
                "claim_type": "description",
                "evidence_level": "recorded",
                "claim_basis": "empirical",
                "scope": "Cohort of 100 patients in obs.txt",
                "revised_text": "Cohort observation recorded 14 events in 100 patients.",
                "rationale": "Exact literal match in obs.txt:1",
                "evidence_ids": [ev_id],
                "confidence": "high",
                "confidence_reason": "Direct verified quote",
                "boundary": "Descriptive scope only",
                "reversal_condition": "Different primary observation record",
            }],
            "dispositions": [],
        })
        engine.dispatch("record_human_decision", {
            "case_id": case_id,
            "decision": "accept",
            "responsible_human": "reviewer",
            "reason": "Verified recorded observation",
        })
        export_res = engine.dispatch("export", {"case_id": case_id})
        export_file = Path(export_res["path"])
        self.assertTrue(export_file.is_file())

        # Untracked hash-verified export report keeps repo clean.
        clean_after_export = collect_git_state(self.root)
        self.assertFalse(clean_after_export["dirty"])
        self.assertEqual(synthesize_code_version(clean_after_export, []), f"git:{sha12}(clean)")

        # Unrecorded file under exports/ or byte-tampered export MUST flag dirty=True.
        unrecorded_md = self.root / "exports" / "other-notes.md"
        unrecorded_md.write_text("unrelated\n", encoding="utf-8")
        self.assertTrue(collect_git_state(self.root)["dirty"])
        unrecorded_md.unlink()

        export_file.write_text(export_file.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
        self.assertTrue(collect_git_state(self.root)["dirty"])


if __name__ == "__main__":
    unittest.main()
