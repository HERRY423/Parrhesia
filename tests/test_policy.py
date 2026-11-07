"""Regression checks for policy drift; no model or scientific acceptance claims."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.policy import (
    SOURCE, TARGETS, MODULES, TARGET_MODULES, PRIMARY_TARGETS,
    check_generated, drifted_files, generate, render
)


ROOT = Path(__file__).resolve().parents[1]
PRIORITY = "平台系统指令 > 平台开发者指令 > 用户消息。"


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
        self.assertEqual(
            templates | handoffs | {"AGENTS.md", "skills/parrhesia-review/SKILL.md", "skills/parrhesia-l2-reference/SKILL.md"},
            set(TARGETS.values()),
        )
        self.assertTrue((ROOT / TARGETS["skill"]).read_text(encoding="utf-8").startswith("---\nname: parrhesia-review\n"))
        self.assertTrue((ROOT / TARGETS["l2_reference"]).read_text(encoding="utf-8").startswith("---\nname: parrhesia-l2-reference\n"))
        # Repository root AGENTS.md uses compact_core + repo dev rules, not 41 KB full text
        self.assertLess(len((ROOT / "AGENTS.md").read_bytes()), 10240)

    def test_modules_are_verbatim_identical_in_declared_entrypoints(self):
        source = (ROOT / SOURCE).read_text(encoding="utf-8")
        outputs = render(source)
        matches = {m[1]: m[2].strip() for m in re.finditer(r"<!-- source:([a-z0-9_]+):start -->\n(.*?)\n<!-- source:\1:end -->", source, re.DOTALL)}
        for mod in MODULES:
            mod_text = matches[mod]
            self.assertTrue(len(mod_text) > 0, f"Module {mod} must be nonempty")
            for target_name, expected_mods in TARGET_MODULES.items():
                content = outputs[TARGETS[target_name]]
                if mod in expected_mods:
                    self.assertIn(mod_text, content, f"Module '{mod}' missing or not verbatim in {target_name}")
                else:
                    self.assertNotIn(mod_text, content, f"Module '{mod}' unexpectedly present in {target_name}")

        chatgpt_output = outputs[TARGETS["chatgpt"]]
        self.assertNotIn("search_offerings", chatgpt_output)
        self.assertNotIn("parrhesia_contract", chatgpt_output)

    def test_report_labels_match_policy_verdicts(self):
        from parrhesia.report import LABELS
        source = (ROOT / SOURCE).read_text(encoding="utf-8")
        policy_verdicts = ["支持", "条件性支持", "不支持", "证据不足"]
        for pv in policy_verdicts:
            self.assertIn(pv, source)
        report_verdicts = [LABELS["supported"], LABELS["partially_supported"], LABELS["unsupported"], LABELS["insufficient_evidence"]]
        self.assertEqual(report_verdicts, policy_verdicts)
        self.assertEqual(LABELS["partially_supported"], "条件性支持")
        self.assertNotIn("部分支持", LABELS.values())

    def test_research_advancement_rules_in_core(self):
        source = (ROOT / SOURCE).read_text(encoding="utf-8")
        outputs = render(source)
        for key in ("generic", "chatgpt", "skill"):
            content = outputs[TARGETS[key]]
            self.assertIn("研究推进（按档位执行）", content)
            self.assertNotIn("非 L0 任务默认执行以下五项要求", content)
            self.assertIn("研究类压缩版（仅 L1，嵌入五段）", content)
            self.assertIn("完整版（仅研究类 L2，嵌入 L2 报告）", content)
            self.assertIn("现在我认为……（类型 × 类型内证据等级 + 范围）", content)
            self.assertIn("≥2 个竞争解释", content)
            self.assertIn("未检索的不写“经检索”", content)
            self.assertIn("必要性与充分性分别判断", content)
        for key in ("repository", "codex", "l2_reference"):
            content = outputs[TARGETS[key]]
            self.assertIn("轻量探索台账", content)
            self.assertIn("exploratory", content)
            self.assertIn("推荐的日常工作流", content)
            self.assertIn("审查者隔离配方", content)
            self.assertIn("reproducible-science", content)
            self.assertIn("record-exec", content)

    def test_trigger_change_invalidates_every_primary_output_then_regenerates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            source = root / SOURCE
            text = source.read_text(encoding="utf-8")
            anchor = "推荐的日常工作流（不新增工具）"
            self.assertEqual(text.count(anchor), 3)
            source.write_text(text.replace(anchor, anchor + "（测试用触发变更）"), encoding="utf-8")
            expected_drifted = {TARGETS[name] for name in PRIMARY_TARGETS} | {TARGETS["l2_reference"]}
            self.assertEqual(set(drifted_files(root)), expected_drifted)
            generate(root)
            check_generated(root)
            for name in PRIMARY_TARGETS + ("l2_reference",):
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
            original + "\n<!-- source:core:start -->\nduplicate\n<!-- source:core:end -->\n",
            original.replace("<!-- modules: core, l2_protocol -->", "<!-- modules: core, unknown_mod -->", 1),
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
