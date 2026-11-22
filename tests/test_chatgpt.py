"""Local kit safety/portability checks, not ChatGPT model or host acceptance."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = load_script("prepare_chatgpt", "prepare-chatgpt.py")


class ChatGPTKitTests(unittest.TestCase):
    def test_kit_excludes_case_data_and_manifest_matches_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            for name in kit.FILES:
                destination = source / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / name).read_bytes())
            (source / ".env").write_text("TEST_ONLY_PRIVATE_SENTINEL", encoding="utf-8")
            (source / "workspaces").mkdir()
            (source / "workspaces" / "case.md").write_text("TEST_ONLY_PRIVATE_SENTINEL", encoding="utf-8")
            output = base / "交接套件 with spaces"
            result = kit.prepare(output, source)
            manifest = json.loads((output / "KIT-MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(result["native_host_acceptance"], "NOT_RUN")
            self.assertEqual(manifest["model_effectiveness"], "NOT_MEASURED")
            actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(actual, set(manifest["files"]) | {"KIT-MANIFEST.json"})
            self.assertFalse({".env", "workspaces/case.md"} & actual)
            for name, record in manifest["files"].items():
                data = (output / name).read_bytes()
                self.assertNotIn(b"TEST_ONLY_PRIVATE_SENTINEL", data)
                self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(record["bytes"], len(data))
                if name in kit.FILES:
                    self.assertEqual(data, (source / name).read_bytes())

    def test_existing_edited_kit_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "kit"
            kit.prepare(output)
            (output / "templates/chatgpt/01-frozen-input.md").write_text("User's filled ledger", encoding="utf-8")
            before = {str(path): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError, "already exists"):
                kit.prepare(output)
            after = {str(path): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_missing_template_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "incomplete"
            source.mkdir()
            output = base / "kit"
            with self.assertRaises(FileNotFoundError):
                kit.prepare(output, source)
            self.assertFalse(output.exists())

    def test_release_copy_generates_kit_without_original_checkout(self):
        builder = load_script("chatgpt_release_builder", "build-release.py")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive = base / "release.zip"
            builder.build(archive)
            package = base / "unpacked"
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(package)
            output = base / "kit"
            command = [sys.executable, str(package / "scripts/prepare-chatgpt.py"), "--output", str(output)]
            completed = subprocess.run(command, cwd=base, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["mode"], "manual_text_protocol")
            manifest = json.loads((output / "KIT-MANIFEST.json").read_text(encoding="utf-8"))
            for name, record in manifest["files"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), record["sha256"])
            repeated = subprocess.run(command, cwd=base, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("already exists", json.loads(repeated.stderr)["message"])

    def test_kit_content_p0_defaults_isolation_provenance_and_self_contained_templates(self):
        from parrhesia.claims import TYPE_LEVELS

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "kit"
            kit.prepare(output)

            start_here = (output / "START-HERE.md").read_text(encoding="utf-8")
            for required in (
                "01-frozen-input-blind.md",
                "Project-Only Memory",
                "Unpersonalized Temporary Chat",
                "session_anchored",
                "AUROC 0.84",
            ):
                self.assertIn(required, start_here)

            guide = (output / "docs/chatgpt-integration.md").read_text(encoding="utf-8")
            for required in (
                "01-frozen-input-blind.md",
                "session_anchored",
                "Code Interpreter",
                "Project-Only Memory",
                "Unpersonalized Temporary Chat",
                "无机械哈希核对",
            ):
                self.assertIn(required, guide)

            entry = (output / "templates/AGENTS.parrhesia.chatgpt.md").read_text(encoding="utf-8")
            self.assertIn("AUROC 0.84", entry)
            self.assertIn("01-frozen-input-blind.md", entry)
            for forbidden in ("$0.10", "$1.00", "可能超过 1 GB", "parrhesia-review", "packet_id", "input_digest", "review_packet", "本插件", "本地可运行"):
                self.assertNotIn(forbidden, entry)

            blind = (output / "templates/chatgpt/01-frozen-input-blind.md").read_text(encoding="utf-8")
            self.assertNotIn("当前最佳解释", blind)
            self.assertNotIn("区分检验设计", blind)
            self.assertNotIn("字段见主指令", blind)
            self.assertIn("claim_direction", blind)
            self.assertIn("endpoint_role", blind)

            for role_file in ("templates/chatgpt/02-overclaim.md", "templates/chatgpt/03-underclaim.md"):
                role_text = (output / role_file).read_text(encoding="utf-8")
                self.assertIn("AUROC 0.84", role_text)
                for ctype in TYPE_LEVELS:
                    self.assertIn(f"`{ctype}`", role_text)

            adjudication = (output / "templates/chatgpt/04-adjudication.md").read_text(encoding="utf-8")
            for required in ("6 个汉字", "symmetry_audit", "partially_supported", "仅在报告开头显式标明一次“非独立审查，未排除起草偏差”"):
                self.assertIn(required, adjudication)
            self.assertNotIn("在报告开头和每条判定旁标", adjudication)

            l2_ref = (output / "skills/parrhesia-l2-reference/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("session_anchored", l2_ref)
            self.assertNotIn("L1-Judge", l2_ref)
            self.assertNotIn("## 8.", l2_ref)


if __name__ == "__main__":
    unittest.main()
