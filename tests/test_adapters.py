"""Engineering tests for Antigravity and Grok 0.2.0 host adapters; no live LLM claims."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TEMP_ROOT = ROOT / "artifacts" / "adapter-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
if not TEMP_ROOT.resolve().is_relative_to(ROOT.resolve()):
    raise RuntimeError("Temporary adapter checks must remain inside the repository.")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


grok_installer = _load_module("parrhesia_grok_installer_test", ROOT / "scripts" / "install-grok.py")
agy_installer = _load_module("parrhesia_agy_installer_test", ROOT / "scripts" / "install-antigravity.py")
release_builder = _load_module("parrhesia_release_builder_test", ROOT / "scripts" / "build-release.py")


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(item.relative_to(root)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


def _mcp_handshake(command: list[str], cwd: Path) -> list[dict]:
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "adapter-smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "parrhesia_contract", "arguments": {}}},
    ]
    env = dict(os.environ)
    env.pop("PARRHESIA_WORKSPACE", None)
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        command,
        input=("\n".join(json.dumps(frame) for frame in frames) + "\n").encode("utf-8"),
        cwd=cwd,
        env=env,
        capture_output=True,
        timeout=20,
    )
    if result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
    return [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]


def _run_shell_hook(command: str, payload: dict | bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    stdin_bytes = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return subprocess.run(command, shell=True, input=stdin_bytes, cwd=cwd, capture_output=True, timeout=15)


class GrokAdapterV2Tests(unittest.TestCase):
    def test_installs_both_skills_compact_default_and_passes_check(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia grok ", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install-grok.py"), "--project", str(project)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["status"], "installed")
            self.assertEqual(report["policy_mode"], "compact")
            self.assertEqual(set(report["skills"]), {"parrhesia-review", "parrhesia-l2-reference"})

            self.assertTrue((project / ".grok" / "skills" / "parrhesia-review" / "SKILL.md").is_file())
            self.assertTrue((project / ".grok" / "skills" / "parrhesia-l2-reference" / "SKILL.md").is_file())
            for module in ("adapters.py", "claims.py", "gates.py", "policy.py", "core.py", "report.py", "server.py"):
                self.assertTrue((project / ".grok" / "parrhesia" / "runtime" / "parrhesia" / module).is_file())

            agents_bytes = (project / "AGENTS.md").read_bytes()
            self.assertLess(len(agents_bytes), 10_240)
            self.assertIn("parrhesia-l2-reference", agents_bytes.decode("utf-8"))

            before = _tree_hashes(project)
            chk = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install-grok.py"), "--project", str(project), "--check"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(chk.returncode, 0, chk.stderr)
            chk_report = json.loads(chk.stdout)
            self.assertTrue(chk_report["ok"])
            self.assertEqual(chk_report["status"], "ok")
            self.assertEqual(_tree_hashes(project), before)

    def test_policy_mode_switches_and_skip_agents_cleanup_preserve_user_text(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-grok-policy-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            original_agents = "# Existing Project Rule\nNever drop this line.\n"
            (project / "AGENTS.md").write_text(original_agents, encoding="utf-8")

            r_full = grok_installer.install(ROOT, project, policy_mode="full")
            self.assertEqual(r_full["status"], "installed")
            self.assertEqual(r_full["policy_mode"], "full")
            full_text = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("九个设计包", full_text)
            self.assertIn("反空转机械门控", full_text)
            self.assertNotIn(".agentmuxer/ledger.md", full_text)

            r_compact = grok_installer.install(ROOT, project, policy_mode="compact")
            self.assertEqual(r_compact["status"], "updated")
            self.assertEqual(r_compact["policy_mode"], "compact")
            self.assertIsNotNone(r_compact["backup_directory"])
            self.assertLess(len((project / "AGENTS.md").read_bytes()), 10_240)
            self.assertTrue(grok_installer.check(ROOT, project)["ok"])

            r_skip = grok_installer.install(ROOT, project, skip_agents=True)
            self.assertEqual(r_skip["status"], "updated")
            self.assertEqual(r_skip["policy_mode"], "skipped")
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), original_agents)
            self.assertTrue(grok_installer.check(ROOT, project)["ok"])

    def test_check_detects_tampering_and_source_drift_read_only(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-grok-drift-", dir=TEMP_ROOT) as directory:
            root_dir = Path(directory)
            project = root_dir / "proj"
            project.mkdir()
            grok_installer.install(ROOT, project)

            fake_src = root_dir / "fake-source"
            shutil.copytree(ROOT / "parrhesia", fake_src / "parrhesia", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "skills", fake_src / "skills")
            shutil.copytree(ROOT / "templates", fake_src / "templates")
            (fake_src / "scripts").mkdir()
            shutil.copy2(ROOT / "scripts" / "run-mcp.py", fake_src / "scripts" / "run-mcp.py")
            (fake_src / "docs").mkdir()
            shutil.copy2(ROOT / "docs" / "contract.md", fake_src / "docs" / "contract.md")
            shutil.copy2(ROOT / "docs" / "artifact-ingestion.md", fake_src / "docs" / "artifact-ingestion.md")
            shutil.copy2(ROOT / "mcp.json", fake_src / "mcp.json")
            manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
            manifest["version"] = "0.2.1"
            (fake_src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

            before = _tree_hashes(project)
            drift_report = grok_installer.check(fake_src, project)
            self.assertFalse(drift_report["ok"])
            self.assertEqual(drift_report["status"], "drifted")
            self.assertTrue(any("0.2.1" in item for item in drift_report["drift"]))
            self.assertEqual(_tree_hashes(project), before)

            l2_skill = project / ".grok" / "skills" / "parrhesia-l2-reference" / "SKILL.md"
            l2_skill.write_text(l2_skill.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
            tamper_proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install-grok.py"), "--project", str(project), "--check"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertNotEqual(tamper_proc.returncode, 0)
            self.assertEqual(json.loads(tamper_proc.stdout)["status"], "invalid")

    def test_uninstall_preserves_third_party_config_and_allows_reinstall(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-grok-uninstall-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            original_agents = "# User instructions\nKeep intact.\n"
            original_mcp = {"mcpServers": {"other": {"command": "tool", "args": ["--flag"]}}, "meta": {"ok": True}}
            (project / "AGENTS.md").write_text(original_agents, encoding="utf-8")
            (project / ".mcp.json").write_text(json.dumps(original_mcp), encoding="utf-8")

            grok_installer.install(ROOT, project)
            un = grok_installer.uninstall(project)
            self.assertEqual(un["status"], "uninstalled")
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), original_agents)
            mcp = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(mcp, original_mcp)
            self.assertFalse((project / ".grok" / "skills").exists())
            self.assertFalse((project / ".grok" / "parrhesia" / "runtime").exists())
            self.assertFalse((project / ".grok" / "parrhesia" / "installation.json").exists())

            reinstalled = grok_installer.install(ROOT, project)
            self.assertEqual(reinstalled["status"], "installed")
            self.assertTrue(grok_installer.check(ROOT, project)["ok"])

    def test_invalid_python_executable_refuses_before_mutation(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-grok-badpy-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            before = _tree_hashes(project)
            with self.assertRaisesRegex(ValueError, "Python executable was not found"):
                grok_installer.install(ROOT, project, python_executable="Z:/nonexistent/python311.exe")
            self.assertEqual(_tree_hashes(project), before)

    @unittest.skipUnless(shutil.which("grok"), "Requires local grok CLI")
    def test_grok_cli_validates_repo_manifest_and_discovers_project_mcp(self):
        validate = subprocess.run(
            ["grok", "plugin", "validate", str(ROOT)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)
        with tempfile.TemporaryDirectory(prefix="parrhesia-grok-cli-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True, timeout=10)
            grok_installer.install(ROOT, project)
            inspected = subprocess.run(
                ["grok", "inspect", "--json"],
                cwd=project,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            data = json.loads(inspected.stdout)
            names = [
                entry.get("name")
                for entry in data.get("mcpServers", [])
                if str(project.name).lower() in json.dumps(entry).lower()
            ]
            self.assertIn("parrhesia", names)


class AntigravityAdapterTests(unittest.TestCase):
    def test_project_install_schema_limits_mcp_and_check_clean(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia agy ", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install-antigravity.py"), "--project", str(project)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["status"], "installed")
            self.assertEqual(report["scope"], "project")
            self.assertFalse(report["global_config_touched"])

            # Clean project root: default --rules-target plugin does not create AGENTS.md or .mcp.json
            self.assertFalse((project / "AGENTS.md").exists())
            self.assertFalse((project / ".mcp.json").exists())

            plugin_dir = project / ".agents" / "plugins" / "parrhesia"
            self.assertFalse((plugin_dir / "installation.json").exists())
            self.assertTrue((project / ".agents" / "parrhesia" / "installation.json").is_file())

            manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
            self.assertLessEqual(set(manifest), agy_installer.ANTIGRAVITY_PLUGIN_ALLOWED_KEYS)
            self.assertEqual(manifest["name"], "parrhesia")
            self.assertEqual(manifest["version"], json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"])

            rule_path = plugin_dir / "rules" / "parrhesia.md"
            rule_bytes = rule_path.read_bytes()
            self.assertLessEqual(len(rule_bytes), 24_000)
            rule_text = rule_bytes.decode("utf-8")
            self.assertFalse(rule_text.lstrip().startswith("---"))
            self.assertIn("invoke_subagent", rule_text)
            self.assertIn("record-exec", rule_text)
            self.assertIn("parrhesia://cases/{case_id}", rule_text)
            self.assertIn("parrhesia_set_ledger", rule_text)

            for skill in ("parrhesia-review", "parrhesia-l2-reference"):
                skill_text = (plugin_dir / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertTrue(skill_text.startswith(f"---\nname: {skill}\n"))

            mcp_cfg = json.loads((plugin_dir / "mcp_config.json").read_text(encoding="utf-8"))
            server = mcp_cfg["mcpServers"]["parrhesia"]
            self.assertEqual(set(server), {"command", "args", "env"})
            responses = _mcp_handshake([server["command"], *server["args"]], project)
            self.assertFalse(responses[2]["result"]["isError"])
            self.assertEqual(Path(responses[2]["result"]["structuredContent"]["workspace"]), project)

            before = _tree_hashes(project)
            chk = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install-antigravity.py"), "--project", str(project), "--check"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(chk.returncode, 0, chk.stderr)
            self.assertEqual(json.loads(chk.stdout)["status"], "ok")
            self.assertEqual(_tree_hashes(project), before)

    def test_hook_shell_execution_with_spaces_empty_active_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia agy hook ", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            agy_installer.install(ROOT, scope="project", project=project)
            hooks_cfg = json.loads((project / ".agents" / "plugins" / "parrhesia" / "hooks.json").read_text(encoding="utf-8"))
            command = hooks_cfg["parrhesia-session-status"]["SessionStart"][0]["command"]

            # No SQLite database -> quiet empty JSON object {}
            res_empty = _run_shell_hook(
                command,
                {"conversationId": "c1", "workspacePaths": [str(project)], "modelName": "auto"},
                ROOT,
            )
            self.assertEqual(res_empty.returncode, 0, res_empty.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(json.loads(res_empty.stdout.decode("utf-8")), {})

            # Invalid JSON stdin -> fails open cleanly with {}
            res_bad = _run_shell_hook(command, b"{not json", ROOT)
            self.assertEqual(res_bad.returncode, 0)
            self.assertEqual(json.loads(res_bad.stdout.decode("utf-8")), {})

            # Active local case -> injects non-blocking status message without modifying SQLite bytes
            from parrhesia.core import Engine
            engine = Engine(project)
            created = engine.dispatch("create_case", {"question": "Does treatment Y change endpoint Z?", "draft": "Draft claim"})
            db_file = project / ".parrhesia" / "state.sqlite3"
            db_before = hashlib.sha256(db_file.read_bytes()).hexdigest()

            res_active = _run_shell_hook(
                command,
                {"conversationId": "c2", "workspacePaths": [str(project)], "modelName": "auto"},
                ROOT,
            )
            self.assertEqual(res_active.returncode, 0, res_active.stderr.decode("utf-8", errors="replace"))
            out = json.loads(res_active.stdout.decode("utf-8"))
            msg = out["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn(created["case_id"], msg)
            self.assertIn(f"parrhesia://cases/{created['case_id']}", msg)
            self.assertIn("parrhesia_get_case / parrhesia_verify", msg)
            self.assertNotIn("parrhesia_workflow", msg)
            self.assertIn("state=draft", msg)
            self.assertEqual(hashlib.sha256(db_file.read_bytes()).hexdigest(), db_before)

            # Mutating an earlier case makes it the active case even after a newer case row is inserted.
            second = engine.dispatch("create_case", {"question": "Does treatment Z change endpoint W?", "draft": "Second draft"})
            (project / "note.txt").write_text("Observation note >= 12 chars in source.", encoding="utf-8")
            engine.dispatch("register_evidence", {
                "case_id": created["case_id"],
                "path": "note.txt",
                "provenance": "observed",
                "kind": "observation",
                "quote": "Observation note >= 12 chars",
                "location": "note.txt:1",
            })
            res_reactivated = _run_shell_hook(
                command,
                {"conversationId": "c3", "workspacePaths": [str(project)], "modelName": "auto"},
                ROOT,
            )
            self.assertEqual(res_reactivated.returncode, 0, res_reactivated.stderr.decode("utf-8", errors="replace"))
            msg2 = json.loads(res_reactivated.stdout.decode("utf-8"))["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn(created["case_id"], msg2)
            self.assertNotIn(second["case_id"], msg2)
            self.assertIn("2 case(s)", msg2)

            # PostToolUse endpoint contract returns empty {}
            hook_py = project / ".agents" / "plugins" / "parrhesia" / "hooks" / "parrhesia_hook.py"
            post = subprocess.run(
                [sys.executable, str(hook_py), "--event", "PostToolUse"],
                input=b'{"toolCall":{"name":"run_command"}}',
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(post.returncode, 0)
            self.assertEqual(json.loads(post.stdout.decode("utf-8")), {})

    def test_rules_targets_no_hooks_transitions_and_uninstall(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-agy-modes-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            original_agents = "# Existing Workspace Rule\nKeep this untouched.\n"
            (project / "AGENTS.md").write_text(original_agents, encoding="utf-8")

            agy_installer.install(ROOT, scope="project", project=project, rules_target="both")
            plugin_dir = project / ".agents" / "plugins" / "parrhesia"
            self.assertTrue((plugin_dir / "rules" / "parrhesia.md").is_file())
            self.assertTrue((plugin_dir / "hooks.json").is_file())
            self.assertTrue((project / "AGENTS.md").read_text(encoding="utf-8").startswith(original_agents))
            self.assertTrue(agy_installer.check(ROOT, scope="project", project=project)["ok"])

            # Switch to root-only rules and disable hooks -> obsolete plugin files backed up and pruned
            upd = agy_installer.install(ROOT, scope="project", project=project, rules_target="root", no_hooks=True)
            self.assertEqual(upd["status"], "updated")
            self.assertIsNotNone(upd["backup_directory"])
            self.assertFalse((plugin_dir / "rules" / "parrhesia.md").exists())
            self.assertFalse((plugin_dir / "hooks.json").exists())
            self.assertFalse((plugin_dir / "hooks").exists())
            self.assertTrue(agy_installer.check(ROOT, scope="project", project=project)["ok"])

            # Check detects tampered rule without modifying disk
            (project / "AGENTS.md").write_text(
                (project / "AGENTS.md").read_text(encoding="utf-8").replace("L1-Explore", "L1-BROKEN"),
                encoding="utf-8",
            )
            self.assertEqual(agy_installer.check(ROOT, scope="project", project=project)["status"], "invalid")

            # Revert tampering to uninstall cleanly and confirm reinstall
            (project / "AGENTS.md").write_text(
                (project / "AGENTS.md").read_text(encoding="utf-8").replace("L1-BROKEN", "L1-Explore"),
                encoding="utf-8",
            )
            un = agy_installer.uninstall(scope="project", project=project)
            self.assertEqual(un["status"], "uninstalled")
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), original_agents)
            self.assertFalse(plugin_dir.exists())
            self.assertEqual(agy_installer.install(ROOT, scope="project", project=project)["status"], "installed")

    def test_user_scope_custom_target_never_touches_global_config(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-agy-user-", dir=TEMP_ROOT) as directory:
            fake_home = Path(directory) / "fake-gemini-config"
            fake_home.mkdir()
            sentinels = {
                "config.json": b'{"theme":"dark","custom":[1,2]}\n',
                "mcp_config.json": b'{"mcpServers":{"existing":{"command":"x","args":[]}}}\n',
                "accounts.json": b'{"do_not_touch":true}\n',
            }
            for name, raw in sentinels.items():
                (fake_home / name).write_bytes(raw)

            with self.assertRaisesRegex(ValueError, "only supported with --scope=project"):
                agy_installer.install(ROOT, scope="user", target=fake_home, rules_target="root")
            with self.assertRaisesRegex(ValueError, "Do not pass --target with --scope=project"):
                agy_installer.install(ROOT, scope="project", project=fake_home, target=fake_home)

            installed = agy_installer.install(ROOT, scope="user", target=fake_home)
            self.assertEqual(installed["scope"], "user")
            self.assertFalse(installed["global_config_touched"])

            mcp_cfg = json.loads((fake_home / "plugins" / "parrhesia" / "mcp_config.json").read_text(encoding="utf-8"))
            server = mcp_cfg["mcpServers"]["parrhesia"]
            self.assertIn("--default-workspace", server["args"])
            responses = _mcp_handshake([server["command"], *server["args"]], fake_home)
            self.assertFalse(responses[2]["result"]["isError"])
            self.assertEqual(Path(responses[2]["result"]["structuredContent"]["workspace"]), fake_home / "parrhesia" / "workspace")

            self.assertTrue(agy_installer.check(ROOT, scope="user", target=fake_home)["ok"])
            agy_installer.uninstall(scope="user", target=fake_home)
            self.assertFalse((fake_home / "plugins" / "parrhesia").exists())

            for name, raw in sentinels.items():
                self.assertEqual((fake_home / name).read_bytes(), raw)

    def test_collision_and_release_archive_unpacked_adapters(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-agy-release-", dir=TEMP_ROOT) as directory:
            root_dir = Path(directory)
            collision_proj = root_dir / "collision"
            collision_proj.mkdir()
            unmanaged_plugin = collision_proj / ".agents" / "plugins" / "parrhesia" / "plugin.json"
            unmanaged_plugin.parent.mkdir(parents=True)
            unmanaged_plugin.write_text('{"name":"other"}\n', encoding="utf-8")
            before = _tree_hashes(collision_proj)
            with self.assertRaisesRegex(ValueError, "Refusing to replace unmanaged file"):
                agy_installer.install(ROOT, scope="project", project=collision_proj)
            self.assertEqual(_tree_hashes(collision_proj), before)

            archive_path = root_dir / "parrhesia-release.zip"
            built = release_builder.build(archive_path)
            self.assertEqual(Path(built["path"]), archive_path.resolve())
            with zipfile.ZipFile(archive_path, "r") as zf:
                names = set(zf.namelist())
                for expected in (
                    ".antigravity-plugin/plugin.json",
                    "parrhesia/adapters.py",
                    "scripts/antigravity_hook.py",
                    "scripts/install-antigravity.py",
                    "scripts/install-antigravity.ps1",
                    "scripts/install-grok.py",
                    "scripts/install-grok.ps1",
                    "docs/antigravity-integration.md",
                    "docs/grok-integration.md",
                ):
                    self.assertIn(expected, names)
                unpacked = root_dir / "unpacked"
                zf.extractall(unpacked)

            target_proj = root_dir / "fresh project"
            target_proj.mkdir()
            agy_res = subprocess.run(
                [sys.executable, str(unpacked / "scripts" / "install-antigravity.py"), "--project", str(target_proj)],
                cwd=root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(agy_res.returncode, 0, agy_res.stderr)
            grok_res = subprocess.run(
                [sys.executable, str(unpacked / "scripts" / "install-grok.py"), "--project", str(target_proj)],
                cwd=root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(grok_res.returncode, 0, grok_res.stderr)
            self.assertEqual(
                subprocess.run(
                    [sys.executable, str(unpacked / "scripts" / "install-antigravity.py"), "--project", str(target_proj), "--check"],
                    cwd=root_dir,
                    capture_output=True,
                    timeout=20,
                ).returncode,
                0,
            )
            self.assertEqual(
                subprocess.run(
                    [sys.executable, str(unpacked / "scripts" / "install-grok.py"), "--project", str(target_proj), "--check"],
                    cwd=root_dir,
                    capture_output=True,
                    timeout=20,
                ).returncode,
                0,
            )

    @unittest.skipUnless(os.name == "nt" and (shutil.which("pwsh") or shutil.which("powershell")), "Windows PowerShell required")
    def test_powershell_wrappers_install_check_and_uninstall(self):
        ps_exe = shutil.which("pwsh") or shutil.which("powershell")
        assert ps_exe is not None
        with tempfile.TemporaryDirectory(prefix="parrhesia ps ", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            for script_name in ("install-antigravity.ps1", "install-grok.ps1"):
                script_path = ROOT / "scripts" / script_name
                base = [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), "-Project", str(project), "-Python", sys.executable]
                inst = subprocess.run(base, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(inst.returncode, 0, inst.stdout + inst.stderr)
                chk = subprocess.run([*base, "-Check"], capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)
                un = subprocess.run([*base, "-Uninstall"], capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(un.returncode, 0, un.stdout + un.stderr)


if __name__ == "__main__":
    unittest.main()
