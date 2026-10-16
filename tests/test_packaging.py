"""Portable-package invariants and real project-adapter installation checks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
TEMP_ROOT = ROOT / "artifacts" / "packaging-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
if not TEMP_ROOT.resolve().is_relative_to(ROOT.resolve()):
    raise RuntimeError("Temporary packaging checks must remain inside the repository.")
SPEC = "https://agent-plugins.org/schemas/1.0.0/"
module_spec = importlib.util.spec_from_file_location("parrhesia_grok_installer", ROOT / "scripts" / "install-grok.py")
installer = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(installer)


def tree_hashes(root: Path) -> dict[str, str]:
    return {str(item.relative_to(root)): hashlib.sha256(item.read_bytes()).hexdigest() for item in root.rglob("*") if item.is_file()}


def handshake(command: list[str], cwd: Path) -> list[dict]:
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "package-smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "parrhesia_contract", "arguments": {}}},
    ]
    environment = dict(os.environ)
    environment.pop("PARRHESIA_WORKSPACE", None)
    environment["PYTHONUTF8"] = "1"
    result = subprocess.run(command, input=("\n".join(json.dumps(frame) for frame in frames) + "\n").encode("utf-8"), cwd=cwd, env=environment, capture_output=True, timeout=20)
    if result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
    return [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]


class PackagingTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Optional jsonschema is needed for canonical-schema validation")
    def test_actual_official_schemas(self):
        import jsonschema
        source = json.loads((ROOT / "docs" / "schemas" / "agent-plugins-1.0.0" / "sources.json").read_text(encoding="utf-8"))
        for kind in ("plugin", "mcp"):
            raw = (ROOT / "docs" / "schemas" / "agent-plugins-1.0.0" / f"{kind}.schema.json").read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source[kind]["sha256"])
            schema = json.loads(raw)
            self.assertEqual(schema["$id"], source[kind]["url"])
            jsonschema.Draft202012Validator.check_schema(schema)
            validator = jsonschema.Draft202012Validator(schema)
            validator.validate(json.loads((ROOT / f"{kind}.json").read_text(encoding="utf-8")))

    def test_portable_metadata_uses_fixed_v1_contract(self):
        manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["$schema"], SPEC + "plugin.schema.json")
        self.assertLessEqual(set(manifest), {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords", "extensions"})
        self.assertRegex(manifest["name"], r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
        self.assertLessEqual(len(manifest["name"]), 64)
        mcp = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(set(mcp), {"$schema", "mcpServers"})
        self.assertEqual(mcp["$schema"], SPEC + "mcp.schema.json")
        server = mcp["mcpServers"]["parrhesia"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "python")
        self.assertEqual(server["cwd"], "${PLUGIN_ROOT}")
        self.assertLessEqual(set(server), {"type", "command", "args", "env", "cwd"})
        self.assertFalse({"PLUGIN_ROOT", "PLUGIN_DATA"} & set(server.get("env", {})))
        self.assertTrue((ROOT / "skills" / "parrhesia-review" / "SKILL.md").is_file())

    def test_portable_expansion_launches_server_outside_checkout(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-portable-", dir=TEMP_ROOT) as directory:
            data = Path(directory)
            server = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["parrhesia"]
            arguments = [arg.replace("${PLUGIN_ROOT}", str(ROOT)).replace("${PLUGIN_DATA}", str(data)) for arg in server["args"]]
            responses = handshake([sys.executable, *arguments], data)
            self.assertEqual([response["id"] for response in responses], [1, 2, 3])
            self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "parrhesia")
            self.assertEqual({tool["name"] for tool in responses[1]["result"]["tools"]}, {"parrhesia_contract", "parrhesia_select_workspace", "parrhesia_workflow"})
            result = responses[2]["result"]
            self.assertFalse(result["isError"])
            self.assertEqual(Path(result["structuredContent"]["workspace"]), data / "workspace")
            self.assertIn("create_case", result["structuredContent"]["contract"])

    def test_install_preserves_existing_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia project ", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            original_agents = "# My project\nKeep this user instruction.\n"
            original_mcp = {"mcpServers": {"other": {"command": "existing-server", "args": []}}, "custom": {"keep": True}}
            (project / "AGENTS.md").write_text(original_agents, encoding="utf-8")
            (project / ".mcp.json").write_text(json.dumps(original_mcp), encoding="utf-8")
            result = installer.install(ROOT, project)
            self.assertEqual(result["scope"], "project")
            self.assertTrue((project / "AGENTS.md").read_text(encoding="utf-8").startswith(original_agents))
            configured = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(configured["mcpServers"]["other"], original_mcp["mcpServers"]["other"])
            self.assertEqual(configured["custom"], original_mcp["custom"])
            backup = project / result["backup_directory"]
            self.assertEqual((backup / "AGENTS.md").read_text(encoding="utf-8"), original_agents)
            before = tree_hashes(project)
            self.assertEqual(installer.install(ROOT, project)["status"], "unchanged")
            self.assertEqual(tree_hashes(project), before)
            server = configured["mcpServers"]["parrhesia"]
            responses = handshake([server["command"], *server["args"]], project)
            self.assertFalse(responses[2]["result"]["isError"])
            self.assertEqual(Path(responses[2]["result"]["structuredContent"]["workspace"]), project)

    def test_modified_owned_file_refuses_before_mutation(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-conflict-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            installer.install(ROOT, project)
            skill = project / ".grok" / "skills" / "parrhesia-review" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nUser edit\n", encoding="utf-8")
            before = tree_hashes(project)
            with self.assertRaisesRegex(ValueError, "changed or removed"):
                installer.install(ROOT, project)
            self.assertEqual(tree_hashes(project), before)

    def test_unmanaged_mcp_entry_refuses_before_mutation(self):
        with tempfile.TemporaryDirectory(prefix="parrhesia-conflict-", dir=TEMP_ROOT) as directory:
            project = Path(directory)
            (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"parrhesia": {"command": "something-else"}}}), encoding="utf-8")
            before = tree_hashes(project)
            with self.assertRaisesRegex(ValueError, "unmanaged or modified"):
                installer.install(ROOT, project)
            self.assertEqual(tree_hashes(project), before)

    def test_unexpanded_or_relative_workspace_fails_explicitly(self):
        for workspace in ("${PLUGIN_DATA}/workspace", "relative/project"):
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "run-mcp.py"), "--workspace", workspace], text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
