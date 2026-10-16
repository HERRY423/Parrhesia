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


if __name__ == "__main__":
    unittest.main()
