"""Tests for Wave 2 Track C: CLI provenance auto-collector for `record-exec`."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.cli import main as cli_main
from parrhesia.core import Engine
from parrhesia.provenance import MAX_STDOUT_EXCERPT_CHARS


def _run_cli(argv: list[str]) -> tuple[int, dict, str]:
    out_buf = io.BytesIO()
    err_buf = io.BytesIO()
    with (
        patch.object(sys, "stdout", type("Out", (), {"buffer": out_buf})()),
        patch.object(sys, "stderr", type("Err", (), {"buffer": err_buf})()),
    ):
        rc = cli_main(argv)
    stdout_text = out_buf.getvalue().decode("utf-8", errors="replace")
    stderr_text = err_buf.getvalue().decode("utf-8", errors="replace")
    parsed = json.loads(stdout_text) if stdout_text.strip() else {}
    return rc, parsed, stderr_text


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        check=True,
    )


class RecordExecProvenanceTests(unittest.TestCase):
    def test_git_clean_vs_dirty_diff_hash_and_untracked_count(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-git-prov-") as tmp:
            ws = Path(tmp).resolve()
            _git(ws, "init")
            _git(ws, "config", "user.email", "test@example.com")
            _git(ws, "config", "user.name", "Test User")
            (ws / "script.py").write_text("print('clean-run-v1')\n", encoding="utf-8")
            (ws / "pyproject.toml").write_text("[project]\nname = 'demo'\nversion = '0.1.0'\n", encoding="utf-8")
            _git(ws, "add", "script.py", "pyproject.toml")
            _git(ws, "commit", "-m", "initial commit")
            head_sha = _git(ws, "rev-parse", "HEAD").stdout.decode("utf-8").strip()

            engine = Engine(ws)
            cid = engine.dispatch("create_case", {
                "question": "Does clean vs dirty git state get captured?",
                "draft": "Draft",
                "writer_context_id": "writer-git",
            })["case_id"]

            rc_clean, out_clean, err_clean = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid,
                "--claim-id", "C1", "--card-id", "exec-clean",
                "--", sys.executable, "script.py",
            ])
            self.assertEqual(rc_clean, 0, err_clean)
            git_clean = out_clean["provenance"]["git"]
            self.assertTrue(git_clean["git_available"])
            self.assertEqual(git_clean["head_sha"], head_sha)
            self.assertEqual(git_clean["head_sha12"], head_sha[:12])
            self.assertFalse(git_clean["dirty"])
            self.assertFalse(git_clean["tracked_dirty"])
            self.assertEqual(git_clean["untracked_count"], 0)
            self.assertEqual(git_clean["working_tree_diff_bytes"], 0)
            self.assertEqual(git_clean["working_tree_diff_sha256"], hashlib.sha256(b"").hexdigest())
            self.assertTrue(out_clean["execution_card"]["details"]["code_version"].startswith(f"git:{head_sha[:12]}(clean)"))
            self.assertEqual(engine.dispatch("verify", {"case_id": cid})["status"], "pass")

            # A second run on the same clean git repo must remain clean (prior log dir does not pollute status).
            rc_clean2, out_clean2, err_clean2 = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid,
                "--claim-id", "C1B", "--card-id", "exec-clean-2",
                "--", sys.executable, "script.py",
            ])
            self.assertEqual(rc_clean2, 0, err_clean2)
            self.assertFalse(out_clean2["provenance"]["git"]["dirty"])
            self.assertEqual(out_clean2["provenance"]["git"]["untracked_count"], 0)

            # Introduce tracked modification and untracked file.
            (ws / "script.py").write_text("print('dirty-run-v2')\n# DIRTY_MARKER_DO_NOT_DUMP\n", encoding="utf-8")
            (ws / "extra_notes.txt").write_text("untracked\n", encoding="utf-8")
            expected_diff = _git(ws, "diff", "--binary").stdout
            expected_diff_sha = hashlib.sha256(expected_diff).hexdigest()

            rc_dirty, out_dirty, err_dirty = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid,
                "--claim-id", "C2", "--card-id", "exec-dirty",
                "--", sys.executable, "script.py",
            ])
            self.assertEqual(rc_dirty, 0, err_dirty)
            git_dirty = out_dirty["provenance"]["git"]
            self.assertTrue(git_dirty["git_available"])
            self.assertEqual(git_dirty["head_sha"], head_sha)
            self.assertTrue(git_dirty["dirty"])
            self.assertTrue(git_dirty["tracked_dirty"])
            self.assertEqual(git_dirty["untracked_count"], 1)
            self.assertEqual(git_dirty["working_tree_diff_bytes"], len(expected_diff))
            self.assertEqual(git_dirty["working_tree_diff_sha256"], expected_diff_sha)
            self.assertNotEqual(git_dirty["working_tree_diff_sha256"], git_clean["working_tree_diff_sha256"])
            self.assertTrue(
                out_dirty["execution_card"]["details"]["code_version"].startswith(
                    f"git:{head_sha[:12]}(dirty_diff={expected_diff_sha[:12]})"
                )
            )
            self.assertNotIn("DIRTY_MARKER_DO_NOT_DUMP", json.dumps(out_dirty))

    def test_non_git_fallback_and_lockfile_discovery_no_symlink_traversal(self):
        with (
            tempfile.TemporaryDirectory(prefix="parrhesia-nogit-ws-") as tmp_ws,
            tempfile.TemporaryDirectory(prefix="parrhesia-outside-") as tmp_out,
        ):
            ws = Path(tmp_ws).resolve()
            outside = Path(tmp_out).resolve()
            outside_secret = outside / "secret_reqs.txt"
            outside_secret.write_text("secret-dep==9.9.9\n", encoding="utf-8")

            lock_contents = {
                "pyproject.toml": b"[project]\nname='x'\n",
                "requirements.txt": b"numpy==1.26.0\n",
                "requirements-dev.txt": b"pytest==8.0.0\n",
                "uv.lock": b"version = 1\n",
                "poetry.lock": b"[[package]]\n",
                "package-lock.json": b'{"lockfileVersion": 3}\n',
                "Cargo.lock": b"version = 3\n",
                "Pipfile.lock": b'{"_meta": {}}\n',
                "environment.yml": b"name: env\n",
            }
            for fname, raw in lock_contents.items():
                (ws / fname).write_bytes(raw)
            (ws / "nested").mkdir()
            (ws / "nested" / "requirements.txt").write_text("ignored-nested==1.0\n", encoding="utf-8")

            symlink_created = False
            try:
                (ws / "requirements-link.txt").symlink_to(outside_secret)
                symlink_created = True
            except OSError:
                pass

            rc, out, err = _run_cli([
                "record-exec", "--workspace", str(ws),
                "--", sys.executable, "-c", "print('no-git-ok')",
            ])
            self.assertEqual(rc, 0, err)
            git_info = out["provenance"]["git"]
            self.assertFalse(git_info["git_available"])
            self.assertIsNone(git_info["head_sha"])
            self.assertFalse(git_info["dirty"])
            self.assertEqual(git_info["untracked_count"], 0)

            found = {item["path"]: item for item in out["provenance"]["lockfiles"]}
            self.assertEqual(set(found), set(lock_contents))
            for fname, raw in lock_contents.items():
                self.assertEqual(found[fname]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(found[fname]["size"], len(raw))
            if symlink_created:
                self.assertNotIn("requirements-link.txt", found)
            self.assertTrue(out["execution_card"]["details"]["code_version"].startswith("workspace-local(lockfiles="))

            # Deterministic symlink-guard check even on hosts that deny symlink creation.
            with patch("parrhesia.provenance.is_link_or_reparse", side_effect=lambda p: p.name == "uv.lock"):
                from parrhesia.provenance import discover_lockfiles
                filtered = {item["path"] for item in discover_lockfiles(ws)}
                self.assertNotIn("uv.lock", filtered)

            # Fallback when `git` binary is unavailable.
            with patch("parrhesia.provenance.subprocess.run", side_effect=FileNotFoundError("git missing")):
                from parrhesia.provenance import collect_git_state
                self.assertFalse(collect_git_state(ws)["git_available"])

    def test_input_file_missing_rejection_traversal_and_sha256_capture(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-inputs-") as tmp:
            ws = Path(tmp).resolve()
            (ws / "data").mkdir()
            input_a = ws / "data" / "cohort.csv"
            input_b = ws / "config.json"
            input_a.write_bytes(b"id,val\n1,42\n")
            input_b.write_bytes(b'{"seed": 7}\n')

            marker = ws / "should_not_exist.txt"
            rc_missing, _, err_missing = _run_cli([
                "record-exec", "--workspace", str(ws),
                "--input-file", "data/missing.csv",
                "--", sys.executable, "-c",
                "from pathlib import Path; Path('should_not_exist.txt').write_text('ran')",
            ])
            self.assertEqual(rc_missing, 2)
            self.assertEqual(json.loads(err_missing)["error"], "missing_input_file")
            self.assertFalse(marker.exists())

            for bad_path in ("../outside.txt", ".parrhesia/state.sqlite3", "data"):
                rc_bad, _, err_bad = _run_cli([
                    "record-exec", "--workspace", str(ws),
                    "--input-file", bad_path,
                    "--", sys.executable, "-c", "print('x')",
                ])
                self.assertEqual(rc_bad, 2)
                self.assertIn(json.loads(err_bad)["error"], ("unsafe_path", "invalid_source"))

            # Verify pre-execution SHA-256 capture even if cmd mutates input_b later.
            rc_ok, out_ok, err_ok = _run_cli([
                "record-exec", "--workspace", str(ws),
                "--input-file", "data/cohort.csv",
                "--input-file", "config.json",
                "--input-file", "data/cohort.csv",
                "--", sys.executable, "-c",
                "from pathlib import Path; Path('config.json').write_text('mutated'); print('inputs-ok')",
            ])
            self.assertEqual(rc_ok, 0, err_ok)
            inputs = out_ok["provenance"]["inputs"]
            self.assertEqual(len(inputs), 2)
            self.assertEqual(inputs[0]["path"], "data/cohort.csv")
            self.assertEqual(inputs[0]["sha256"], hashlib.sha256(b"id,val\n1,42\n").hexdigest())
            self.assertEqual(inputs[1]["path"], "config.json")
            self.assertEqual(inputs[1]["sha256"], hashlib.sha256(b'{"seed": 7}\n').hexdigest())
            self.assertIn("data/cohort.csv", out_ok["execution_card"]["details"]["inputs"])
            self.assertIn(inputs[0]["sha256"][:12], out_ok["execution_card"]["details"]["inputs"])

    def test_output_file_snapshots_created_modified_unchanged_and_missing(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-outputs-") as tmp:
            ws = Path(tmp).resolve()
            engine = Engine(ws)
            cid = engine.dispatch("create_case", {
                "question": "Are outputs snapshotted accurately?",
                "draft": "Draft",
                "writer_context_id": "writer-out",
            })["case_id"]

            mod_file = ws / "metrics.json"
            same_file = ws / "constants.txt"
            mod_file.write_bytes(b'{"acc": 0.50}\n')
            same_file.write_bytes(b"alpha=0.05\n")

            cmd_code = (
                "from pathlib import Path; "
                "Path('results').mkdir(exist_ok=True); "
                "Path('results/new.csv').write_bytes(b'x,y\\n1,2\\n'); "
                "Path('metrics.json').write_bytes(b'{\"acc\": 0.91, \"n\": 100}\\n'); "
                "print('outputs-done')"
            )
            rc, out, err = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid, "--claim-id", "C1",
                "--output-file", "results/new.csv",
                "--output-file", "metrics.json",
                "--output-file", "constants.txt",
                "--", sys.executable, "-c", cmd_code,
            ])
            self.assertEqual(rc, 0, err)
            self.assertEqual(out["execution_card"]["status"], "checked")
            self.assertTrue(out["provenance"]["all_outputs_present"])
            self.assertEqual(out["provenance"]["missing_outputs"], [])

            by_path = {item["path"]: item for item in out["provenance"]["outputs"]}
            self.assertEqual(by_path["results/new.csv"]["status"], "created")
            self.assertTrue(by_path["results/new.csv"]["changed"])
            self.assertFalse(by_path["results/new.csv"]["pre_exists"])
            self.assertEqual(by_path["results/new.csv"]["sha256"], hashlib.sha256(b"x,y\n1,2\n").hexdigest())
            self.assertEqual(by_path["results/new.csv"]["delta_bytes"], len(b"x,y\n1,2\n"))

            self.assertEqual(by_path["metrics.json"]["status"], "modified")
            self.assertTrue(by_path["metrics.json"]["changed"])
            self.assertEqual(by_path["metrics.json"]["pre_sha256"], hashlib.sha256(b'{"acc": 0.50}\n').hexdigest())
            self.assertEqual(by_path["metrics.json"]["sha256"], hashlib.sha256(b'{"acc": 0.91, "n": 100}\n').hexdigest())
            self.assertEqual(by_path["metrics.json"]["delta_bytes"], len(b'{"acc": 0.91, "n": 100}\n') - len(b'{"acc": 0.50}\n'))

            self.assertEqual(by_path["constants.txt"]["status"], "unchanged")
            self.assertFalse(by_path["constants.txt"]["changed"])
            self.assertEqual(by_path["constants.txt"]["delta_bytes"], 0)
            self.assertIn("results/new.csv(status=created", out["execution_card"]["details"]["outputs"])

            # Missing declared output marks execution failed and persists report in SQLite.
            rc_miss, out_miss, err_miss = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid, "--claim-id", "C2",
                "--output-file", "never_created.parquet",
                "--", sys.executable, "-c", "print('exited-zero-without-output')",
            ])
            self.assertEqual(rc_miss, 0, err_miss)
            self.assertEqual(out_miss["exit_status"], 0)
            self.assertEqual(out_miss["execution_card"]["status"], "failed")
            self.assertIn("never_created.parquet", out_miss["execution_card"]["reason"])
            self.assertFalse(out_miss["provenance"]["all_outputs_present"])
            self.assertEqual(out_miss["provenance"]["missing_outputs"], ["never_created.parquet"])
            self.assertEqual(out_miss["provenance"]["outputs"][0]["status"], "missing")
            self.assertIn("never_created.parquet(missing)", out_miss["execution_card"]["details"]["outputs"])

            events = engine.dispatch("get_case", {"case_id": cid})["events"]
            miss_ev = [e for e in events if e["action"] == "record_exec"][-1]
            self.assertEqual(miss_ev["details"]["status"], "failed")
            self.assertEqual(miss_ev["details"]["provenance"]["missing_outputs"], ["never_created.parquet"])

    def test_stream_digests_bounded_excerpt_quote_verify_and_full_case_compatibility(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-stream-") as tmp:
            ws = Path(tmp).resolve()
            engine = Engine(ws)
            cid = engine.dispatch("create_case", {
                "question": "Do stream digests and header_range pass verify and claim schema?",
                "draft": "Benchmark accuracy=0.92.",
                "writer_context_id": "writer-stream",
            })["case_id"]

            script = (
                "import sys; "
                "sys.stdout.write('\\x1b[1;32mPASS\\x1b[0m accuracy=0.92\\n' + ('Z' * 150) + '\\n'); "
                "sys.stderr.write('warn-channel-line\\n')"
            )
            rc, out, err = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid,
                "--claim-id", "C1", "--card-id", "exec-stream",
                "--stdout-excerpt-chars", "45",
                "--", sys.executable, "-c", script,
            ])
            self.assertEqual(rc, 0, err)

            streams = out["provenance"]["streams"]
            log_file = ws / out["log_path"]
            log_bytes = log_file.read_bytes()
            log_text = log_bytes.decode("utf-8")
            self.assertEqual(streams["log_sha256"], hashlib.sha256(log_bytes).hexdigest())
            self.assertEqual(streams["log_sha256"], out["evidence"]["sha256"])
            self.assertNotIn("\x1b", streams["stdout_excerpt"])
            self.assertNotIn("\n", streams["stdout_excerpt"])
            self.assertLessEqual(len(streams["stdout_excerpt"]), 45)
            self.assertTrue(streams["stdout_excerpt"].endswith("..."))
            self.assertTrue(streams["stdout_excerpt_truncated"])
            self.assertIn("PASS accuracy=0.92", streams["stdout_excerpt"])

            quote = out["evidence"]["quote"]
            self.assertIn(f"stdout_sha256: {streams['stdout_sha256']}", quote)
            self.assertIn(f"stderr_sha256: {streams['stderr_sha256']}", quote)
            self.assertIn(f"stdout_excerpt: {streams['stdout_excerpt']}", quote)
            locator = out["execution_card"]["details"]["log_locator"]
            self.assertEqual(locator, out["evidence"]["location"])
            line_range = locator.split(":")[-1]
            start_s, end_s = line_range.split("-")
            self.assertEqual(start_s, "L1")
            end_line = int(end_s[1:])
            self.assertEqual("\n".join(log_text.splitlines()[:end_line]), quote)

            verify_res = engine.dispatch("verify", {"case_id": cid})
            self.assertEqual(verify_res["status"], "pass")
            self.assertEqual(verify_res["evidence"][0]["anchor_status"], "matched")

            # Verify synthesized execution_card satisfies claims.py schema in set_ledger.
            claim = engine.dispatch("scaffold_claim", {
                "case_id": cid, "claim_id": "C1", "claim_type": "computational",
                "evidence_level": "benchmark_measured", "design_families": ["ml"],
            })["claim"]
            ev_id = out["evidence"]["evidence_id"]
            claim["text"] = "Benchmark accuracy=0.92."
            claim["scope"] = "Isolated test script benchmark"
            claim["origin"] = "exploratory"
            claim["evidence_ids"] = [ev_id]
            claim["effect"] = {"estimate": "accuracy=0.92", "uncertainty": "single benchmark script"}
            claim["provenance_cards"]["execution"] = [out["execution_card"]]
            ledger = engine.dispatch("set_ledger", {"case_id": cid, "claims": [claim]})
            self.assertEqual(ledger["claim_count"], 1)

            # Verify large --stdout-excerpt-chars is capped safely and negative values fail cleanly.
            rc_cap, out_cap, err_cap = _run_cli([
                "record-exec", "--workspace", str(ws),
                "--stdout-excerpt-chars", "99999",
                "--", sys.executable, "-c", "print('A' * 3000)",
            ])
            self.assertEqual(rc_cap, 0, err_cap)
            self.assertEqual(out_cap["provenance"]["streams"]["stdout_excerpt_max_chars"], MAX_STDOUT_EXCERPT_CHARS)
            self.assertLessEqual(len(out_cap["provenance"]["streams"]["stdout_excerpt"]), MAX_STDOUT_EXCERPT_CHARS)

            rc_neg, _, err_neg = _run_cli([
                "record-exec", "--workspace", str(ws),
                "--stdout-excerpt-chars", "-1",
                "--", sys.executable, "-c", "print('x')",
            ])
            self.assertEqual(rc_neg, 2)
            self.assertEqual(json.loads(err_neg)["error"], "invalid_value")

    def test_secret_env_var_isolation_and_safe_markers(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-env-") as tmp:
            ws = Path(tmp).resolve()
            engine = Engine(ws)
            cid = engine.dispatch("create_case", {
                "question": "Does secret env stay isolated?",
                "draft": "Draft",
                "writer_context_id": "writer-env",
            })["case_id"]

            secret_env = {
                "API_KEY": "secret123",
                "GITHUB_TOKEN": "ghp_secret456",
                "AWS_SECRET_ACCESS_KEY": "aws_super_secret789",
                "KUBERNETES_SERVICE_HOST": "10.96.0.1",
            }
            receipt = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "parrhesia", "record-exec", "--workspace", str(ws),
                 "--case-id", cid, "--", sys.executable, "-c", "print('env-check-ok')"],
                cwd=Path(__file__).resolve().parents[1], env={**os.environ, **secret_env},
                capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(receipt.returncode, 0, receipt.stderr)
            out = json.loads(receipt.stdout)

            env_markers = out["provenance"]["environment"]
            self.assertTrue(env_markers["python_version"])
            self.assertEqual(env_markers["python_executable"], Path(sys.executable).name)
            self.assertNotIn(os.sep, env_markers["python_executable"])
            self.assertIs(type(env_markers["virtualenv_active"]), bool)
            self.assertIs(type(env_markers["dockerenv_present"]), bool)
            self.assertIs(env_markers["kubernetes_service_host_present"], True)

            log_body = (ws / out["log_path"]).read_text(encoding="utf-8")
            case_dump = json.dumps(engine.dispatch("get_case", {"case_id": cid}))
            stdout_dump = json.dumps(out)
            for forbidden in (
                "secret123", "ghp_secret456", "aws_super_secret789", "10.96.0.1",
                "API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY",
            ):
                self.assertNotIn(forbidden, log_body)
                self.assertNotIn(forbidden, case_dump)
                self.assertNotIn(forbidden, stdout_dump)

    def test_explicit_overrides_and_sqlite_provenance_persistence(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-override-") as tmp:
            ws = Path(tmp).resolve()
            (ws / "pyproject.toml").write_text("[project]\nname='ov'\n", encoding="utf-8")
            (ws / "in.txt").write_text("row1\n", encoding="utf-8")

            engine = Engine(ws)
            cid = engine.dispatch("create_case", {
                "question": "Do explicit overrides remain backward-compatible?",
                "draft": "Draft",
                "writer_context_id": "writer-ov",
            })["case_id"]

            rc, out, err = _run_cli([
                "record-exec", "--workspace", str(ws), "--case-id", cid,
                "--code-version", "release-v9.9",
                "--inputs", "explicit-input-label",
                "--outputs", "explicit-output-label",
                "--input-file", "in.txt",
                "--output-file", "out.txt",
                "--", sys.executable, "-c",
                "from pathlib import Path; Path('out.txt').write_text('done'); print('override-ok')",
            ])
            self.assertEqual(rc, 0, err)
            details = out["execution_card"]["details"]
            self.assertEqual(details["code_version"], "release-v9.9")
            self.assertEqual(details["inputs"], "explicit-input-label")
            self.assertEqual(details["outputs"], "explicit-output-label")

            events = engine.dispatch("get_case", {"case_id": cid})["events"]
            exec_ev = next(e for e in events if e["action"] == "record_exec")
            self.assertEqual(exec_ev["details"]["provenance"], out["provenance"])
            self.assertEqual(exec_ev["details"]["provenance"]["inputs"][0]["path"], "in.txt")
            self.assertEqual(exec_ev["details"]["provenance"]["outputs"][0]["status"], "created")

            rc_blank, _, err_blank = _run_cli([
                "record-exec", "--workspace", str(ws),
                "--code-version", "   ",
                "--", sys.executable, "-c", "print('x')",
            ])
            self.assertEqual(rc_blank, 2)
            self.assertEqual(json.loads(err_blank)["error"], "invalid_value")


if __name__ == "__main__":
    unittest.main()
