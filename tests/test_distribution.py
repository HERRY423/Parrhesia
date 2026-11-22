"""Layered installer completeness, transactional updates and saved-case HTML output."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.adapters import SKILL_REQUIRED_FILES, collect_skills_payloads
from parrhesia.core import Engine
from parrhesia.report import render_case_report
from parrhesia.storage import connect_readonly
from parrhesia.contracts import ContractError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("codex_distribution_installer", ROOT / "scripts/install-codex.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class CodexDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="parrhesia-codex-sync-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "codex"
        self.target.mkdir()
        (self.target / "AGENTS.md").write_text("# User rules\nKeep my preferences.\n", encoding="utf-8")

    def test_complete_bundle_readonly_check_and_byte_stable_repeat(self):
        result = installer.sync_codex_agents(self.target)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(len(result["files"]), 6)
        for name, required in SKILL_REQUIRED_FILES.items():
            for relative in required:
                installed = self.target / "skills" / name / relative
                self.assertEqual(installed.read_text(encoding="utf-8"), (ROOT / "skills" / name / relative).read_text(encoding="utf-8"))
        self.assertTrue((self.target / "AGENTS.md").read_text(encoding="utf-8").startswith("# User rules\nKeep my preferences."))
        before = hashes(self.target)
        self.assertEqual(installer.sync_codex_agents(self.target, check_only=True)["status"], "in_sync")
        self.assertEqual(installer.sync_codex_agents(self.target)["status"], "unchanged")
        self.assertEqual(hashes(self.target), before)

    def test_v2_upgrade_backs_up_exact_bytes_and_preserves_user_files(self):
        l2 = self.target / "skills/parrhesia-l2-reference/SKILL.md"
        l2.parent.mkdir(parents=True)
        original = b"\xef\xbb\xbflegacy\r\n"
        l2.write_bytes(original)
        (l2.parent / "my-notes.md").write_text("User notes", encoding="utf-8")
        (self.target / ".parrhesia-codex-sync.json").write_text('{"owner":"parrhesia-codex-sync-v2"}', encoding="utf-8")
        result = installer.sync_codex_agents(self.target)
        self.assertEqual(Path(result["skill_backup_path"]).read_bytes(), original)
        self.assertEqual((l2.parent / "my-notes.md").read_text(), "User notes")
        self.assertEqual(result["owner"], "parrhesia-codex-sync-v3")
        installer.sync_codex_agents(self.target, check_only=True)

    def test_modified_or_missing_reference_fails_check_without_writes(self):
        installer.sync_codex_agents(self.target)
        path = self.target / "skills/parrhesia-review/references/workflow.md"
        for content in ("User-edited workflow", None):
            if content is None:
                path.unlink()
            else:
                path.write_text(content, encoding="utf-8")
            before = hashes(self.target)
            with self.assertRaisesRegex(ValueError, "out of sync"):
                installer.sync_codex_agents(self.target, check_only=True)
            self.assertEqual(hashes(self.target), before)

    def test_missing_source_reference_is_rejected_before_any_target_write(self):
        source = self.root / "source"
        shutil.copytree(ROOT / "skills", source / "skills")
        (source / "templates").mkdir()
        shutil.copyfile(ROOT / "templates/AGENTS.parrhesia.codex.md", source / "templates/AGENTS.parrhesia.codex.md")
        (source / "skills/parrhesia-review/references/basics.md").unlink()
        before = hashes(self.target)
        with self.assertRaisesRegex(ValueError, "Missing required skill file"):
            installer.sync_codex_agents(self.target, source)
        self.assertEqual(hashes(self.target), before)
        # The same validation is shared by Grok and Antigravity collectors.
        with self.assertRaises(ValueError):
            collect_skills_payloads(source, "any-host/skills")

    def test_write_failure_rolls_back_managed_files_and_keeps_backups(self):
        previous = (self.target / "AGENTS.md").read_bytes()
        original_replace = __import__("os").replace
        def fail_one(src, dst):
            if Path(dst).name == "workflow.md":
                raise OSError("simulated partial installation")
            return original_replace(src, dst)
        with patch("parrhesia.adapters.os.replace", side_effect=fail_one):
            with self.assertRaises(OSError):
                installer.sync_codex_agents(self.target)
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), previous)
        self.assertFalse((self.target / ".parrhesia-codex-sync.json").exists())
        self.assertFalse((self.target / "skills/parrhesia-review/SKILL.md").exists())
        self.assertEqual(list(self.target.rglob("*.tmp")), [])

    def test_linked_target_is_rejected_without_touching_destination(self):
        link = self.target / "skills"
        actual = self.root / "unrelated"
        actual.mkdir()
        try:
            link.symlink_to(actual, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Directory symlink unavailable: {exc}")
        with self.assertRaises(ValueError):
            installer.sync_codex_agents(self.target)
        self.assertEqual(list(actual.iterdir()), [])

    def test_script_runs_from_outside_checkout(self):
        command = [sys.executable, "-I", str(ROOT / "scripts/install-codex.py"), "--codex-home", str(self.target)]
        for extra in ([], ["--check"]):
            result = subprocess.run([*command, *extra], cwd=self.root, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


def adjudicated_case(engine):
    cid = engine.dispatch("create_case", {"question": "Synthetic report fixture", "draft": "<script>not instructions</script>", "domain": "general"})["case_id"]
    claim = engine.dispatch("scaffold_claim", {"case_id": cid, "text": "A candidate engineering claim"})["claim"]
    engine.dispatch("set_ledger", {"case_id": cid, "claims": [claim]})
    engine.dispatch("freeze", {"case_id": cid})
    for role in ("overclaim", "underclaim"):
        packet = engine.dispatch("review_packet", {"case_id": cid, "role": role})
        engine.dispatch("submit_review", {"case_id": cid, "role": role, "packet_id": packet["packet_id"], "input_digest": packet["input_digest"],
                        "reviewer": {"context_id": role, "model": "FIXTURE_NO_MODEL_CALL"}, "covered_claim_ids": ["C1"],
                        "findings": [], "unread_evidence_ids": [], "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Fixture has no evidence", "evidence_ids": []}]})
    packet = engine.dispatch("adjudication_packet", {"case_id": cid})
    engine.dispatch("submit_adjudication", {"case_id": cid, "adjudication_id": packet["adjudication_id"], "input_digest": packet["input_digest"],
                    "adjudicator": {"context_id": "adjudicator", "model": "FIXTURE_NO_MODEL_CALL"}, "unread_evidence_ids": [], "dispositions": [],
                    "decisions": [{"claim_id": "C1", "verdict": "insufficient_evidence", "claim_type": "engineering", "evidence_level": "unassessed", "claim_basis": "empirical",
                                   "revised_text": "No test evidence was supplied.", "scope": "Synthetic fixture only", "evidence_ids": [], "rationale": "No verification performed",
                                   "confidence": "high", "confidence_reason": "The missing evidence is explicit", "boundary": "No real-world conclusion", "reversal_condition": "Reassess if concrete test evidence is supplied"}]})
    return cid


class SavedCaseReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="parrhesia-saved-report-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = Engine(self.root)

    def test_saved_case_report_preserves_unknowns_escapes_text_and_never_writes_case(self):
        cid = adjudicated_case(self.engine)
        before = self.engine.dispatch("get_case", {"case_id": cid})
        database_before = self.engine.database.read_bytes()
        result = render_case_report(self.root, cid, "reports/review.html")
        self.assertEqual(self.engine.database.read_bytes(), database_before)
        self.assertEqual(self.engine.dispatch("get_case", {"case_id": cid}), before)
        self.assertFalse(result["case_mutated"])
        html = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;not instructions&lt;/script&gt;", html)
        self.assertIn("not_run", html)
        self.assertIn("UNKNOWN", html)
        self.assertIn("saved_record_only", html)
        self.assertIn("head_event_hash", html)
        self.assertIn("No test evidence was supplied.", html)
        self.assertEqual(result["snapshot"]["case_state"], "adjudicated")
        original = Path(result["path"]).read_bytes()
        with self.assertRaisesRegex(ContractError, "export_exists"):
            render_case_report(self.root, cid, "reports/review.html")
        self.assertEqual(Path(result["path"]).read_bytes(), original)

    def test_unadjudicated_cases_and_unsafe_destinations_are_rejected(self):
        cid = self.engine.dispatch("create_case", {"question": "Draft", "draft": "Not reviewed"})["case_id"]
        with self.assertRaisesRegex(ContractError, "case_not_adjudicated"):
            render_case_report(self.root, cid, "draft.html")
        self.assertFalse((self.root / "draft.html").exists())
        cid = adjudicated_case(self.engine)
        for name in ("../escape.html", ".parrhesia/output.html", "report.txt"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                render_case_report(self.root, cid, name)

    def test_cli_report_reads_existing_case(self):
        cid = adjudicated_case(self.engine)
        before = self.engine.dispatch("get_case", {"case_id": cid})
        database_before = self.engine.database.read_bytes()
        result = subprocess.run([sys.executable, "-m", "parrhesia", "report", "--workspace", str(self.root), "--case-id", cid, "--output", "case.html"],
                                cwd=ROOT, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(result.stdout)["snapshot"]["case_id"], cid)
        self.assertEqual(self.engine.database.read_bytes(), database_before)
        self.assertEqual(self.engine.dispatch("get_case", {"case_id": cid}), before)

    def test_readonly_connection_enforces_no_writes(self):
        adjudicated_case(self.engine)
        before = self.engine.database.read_bytes()
        with connect_readonly(self.engine.state_dir, self.engine.database) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM cases")
        self.assertEqual(self.engine.database.read_bytes(), before)

    def test_missing_saved_audit_stays_not_run(self):
        cid = adjudicated_case(self.engine)
        with self.engine._connect() as db:
            case = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone()[0])
            case.pop("symmetry_audit", None)
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case), cid))
        report = render_case_report(self.root, cid, "missing-audit.html")
        html = Path(report["path"]).read_text(encoding="utf-8")
        self.assertIn("没有已保存的对称性审计结果", html)
        self.assertNotIn("flag_count=0", html)

    def test_snapshot_reads_committed_wal_content_without_initialization(self):
        cid = adjudicated_case(self.engine)
        with sqlite3.connect(self.engine.database) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            case = json.loads(writer.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone()[0])
            case["human_decisions"].append({"decision": "defer", "reason": "Saved in live WAL"})
            writer.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case), cid))
            writer.commit()
            self.assertTrue(Path(str(self.engine.database) + "-wal").is_file())
            with patch("parrhesia.core.initialize_database", side_effect=AssertionError("Must not initialize")):
                snapshot = Engine.read_case_snapshot(self.root, cid)
            self.assertEqual(snapshot["human_decisions"], case["human_decisions"])
        writer.close()

    def test_missing_workspace_does_not_initialize_state(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(ContractError, "missing_workspace"):
            render_case_report(empty, "unknown", "report.html")
        self.assertEqual(list(empty.iterdir()), [])
        with self.assertRaisesRegex(ContractError, "unknown_case"):
            render_case_report(self.root, "unknown", "report.html")

    def test_tampered_frozen_content_and_events_do_not_get_reports(self):
        cid = adjudicated_case(self.engine)
        with self.engine._connect() as db:
            original = db.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone()[0]
            altered = json.loads(original)
            altered["draft"] = "Changed after freezing"
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(altered), cid))
        with self.assertRaisesRegex(ContractError, "frozen_integrity_error"):
            render_case_report(self.root, cid, "report.html")
        with self.engine._connect() as db:
            db.execute("UPDATE cases SET document=? WHERE id=?", (original, cid))
            db.execute("UPDATE events SET details='{}' WHERE action='freeze'")
        before = self.engine.database.read_bytes()
        with self.assertRaisesRegex(ContractError, "event_chain_tampered"):
            render_case_report(self.root, cid, "report.html")
        self.assertEqual(self.engine.database.read_bytes(), before)
        self.assertFalse((self.root / "report.html").exists())


if __name__ == "__main__":
    unittest.main()
