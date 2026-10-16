"""Regression checks for policy drift; no model or scientific acceptance claims."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.policy import SOURCE, TARGETS, PRIMARY_TARGETS, check_generated, drifted_files, generate, render


ROOT = Path(__file__).resolve().parents[1]
PRIORITY = "用户当前的明确指令 > 数据保密 > 证据真实 > 强度匹配 > 表达已支持的贡献 > 效率。"


class PolicyTests(unittest.TestCase):
    def fixture(self, root):
        path = root / SOURCE
        path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / SOURCE).read_bytes())
        generate(root)

    def snapshot(self, root):
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def test_checked_in_outputs_and_entrypoint_inventory(self):
        check_generated(ROOT)
        templates = {path.relative_to(ROOT).as_posix() for path in (ROOT / "templates").glob("AGENTS.parrhesia*.md")}
        handoffs = {path.relative_to(ROOT).as_posix() for path in (ROOT / "templates/chatgpt").glob("*.md")}
        self.assertEqual(templates | handoffs | {"AGENTS.md", "skills/parrhesia-review/SKILL.md"}, set(TARGETS.values()))
        self.assertTrue((ROOT / TARGETS["skill"]).read_text(encoding="utf-8").startswith("---\nname: parrhesia-review\n"))

    def test_priority_and_trigger_block_are_identical_in_all_primary_outputs(self):
        source = (ROOT / SOURCE).read_text(encoding="utf-8")
        self.assertEqual(source.count(PRIORITY), 1)
        outputs = render(source)
        blocks = []
        for name in PRIMARY_TARGETS:
            content = outputs[TARGETS[name]]
            self.assertEqual(content.count(PRIORITY), 1)
            chains = [line for line in content.splitlines() if line.count(" > ") >= 2]
            self.assertEqual(chains, [PRIORITY])
            blocks.append(content.split("## 统一触发条件\n", 1)[1].split("\n## ", 1)[0])
        self.assertEqual(len(set(blocks)), 1)
        for level in ("L0", "L1", "L2"):
            self.assertIn(level, blocks[0])

    def test_trigger_change_invalidates_every_primary_output_then_regenerates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            source = root / SOURCE
            text = source.read_text(encoding="utf-8")
            old = "已有结论被质疑，需要正式回应"
            self.assertEqual(text.count(old), 1)
            source.write_text(text.replace(old, old + "（测试用触发变更）"), encoding="utf-8")
            self.assertEqual(set(drifted_files(root)), {TARGETS[name] for name in PRIMARY_TARGETS})
            generate(root)
            check_generated(root)
            for name in PRIMARY_TARGETS:
                self.assertIn("测试用触发变更", (root / TARGETS[name]).read_text(encoding="utf-8"))

    def test_manual_drift_and_missing_output_fail_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            target = root / TARGETS["skill"]
            target.write_text(target.read_text(encoding="utf-8") + "\nAlways run full review.\n", encoding="utf-8")
            (root / TARGETS["codex"]).unlink()
            before = self.snapshot(root)
            with self.assertRaisesRegex(ValueError, "Generated policy drift"):
                check_generated(root)
            self.assertEqual(before, self.snapshot(root))
            generate(root)
            check_generated(root)
            before = self.snapshot(root)
            self.assertEqual(generate(root), [])
            self.assertEqual(before, self.snapshot(root))

    def test_malformed_source_is_rejected_before_outputs_change(self):
        original = (ROOT / SOURCE).read_text(encoding="utf-8")
        cases = [
            original + "\n<!-- source:policy:start -->\nduplicate\n<!-- source:policy:end -->\n",
            original.replace("{{policy}}", "{{unknown}}", 1),
            original.replace("<!-- source:skill:end -->", "<!-- source:wrong:end -->"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for broken in cases:
                with self.subTest(source=broken[-50:]):
                    (root / SOURCE).write_text(broken, encoding="utf-8")
                    before = self.snapshot(root)
                    with self.assertRaises(ValueError):
                        generate(root)
                    self.assertEqual(before, self.snapshot(root))

    def test_release_build_refuses_drift_before_creating_archive(self):
        spec = importlib.util.spec_from_file_location("policy_release_builder", ROOT / "scripts/build-release.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            (root / TARGETS["generic"]).write_text("stale rules", encoding="utf-8")
            output = root / "must-not-exist.zip"
            with patch.object(builder, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "Generated policy drift"):
                    builder.build(output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
