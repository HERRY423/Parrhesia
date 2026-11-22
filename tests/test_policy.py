"""Regression checks for policy drift; no model or scientific acceptance claims."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.claims import TYPE_LEVELS
from parrhesia.policy import (
    SOURCE, TARGETS, MODULES, SNIPPETS, TARGET_MODULES, PRIMARY_TARGETS,
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
        references = {path.relative_to(ROOT).as_posix() for path in (ROOT / "skills/parrhesia-review/references").glob("*.md")}
        self.assertEqual(
            templates | handoffs | references | {"AGENTS.md", "skills/parrhesia-review/SKILL.md", "skills/parrhesia-l2-reference/SKILL.md"},
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
        for forbidden in (
            "search_offerings",
            "parrhesia_contract",
            "$0.10",
            "$1.00",
            "可能超过 1 GB",
            "1 GB",
            "搜索市场",
            "子代理不付费",
            "parrhesia-review",
            "review_packet",
            "packet_id",
            "input_digest",
            "本插件",
            "本地可运行",
        ):
            self.assertNotIn(forbidden, chatgpt_output, f"Non-ChatGPT token leaked into ChatGPT entry: {forbidden}")
        for required in (
            "AUROC 0.84",
            "01-frozen-input-blind.md",
            "01-frozen-input.md",
            "session_anchored",
            "Code Interpreter",
            "Project-Only Memory",
            "Unpersonalized Temporary Chat",
        ):
            self.assertIn(required, chatgpt_output, f"Missing expected ChatGPT entry phrase: {required}")
        self.assertGreaterEqual(len(chatgpt_output), 4000)
        self.assertLessEqual(len(chatgpt_output), 5500)

        for tool_target in ("repository", "generic", "codex", "basic_reference"):
            tool_output = outputs[TARGETS[tool_target]]
            for preserved in ("$0.10", "$1.00", "可能超过 1 GB", "parrhesia-review", "review_packet", "packet_id", "input_digest", "AUROC 0.84", "审查者隔离配方"):
                self.assertIn(preserved, tool_output, f"Missing expected tool-host phrase in {tool_target}: {preserved}")

        for snip in SNIPPETS:
            self.assertTrue(len(matches[snip]) > 0, f"Snippet {snip} must be nonempty")

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

    def test_detailed_rules_are_on_demand_and_entrypoints_keep_boundaries(self):
        source = (ROOT / SOURCE).read_text(encoding="utf-8")
        outputs = render(source)
        for key in PRIMARY_TARGETS:
            content = outputs[TARGETS[key]]
            self.assertIn("七项底线", content)
            self.assertIn("轻量探索台账", content)
            self.assertIn("条件性支持", content)
            self.assertIn("用户期望不是证据", content)
            self.assertIn("未事先冻结", content)
            self.assertIn("输入/输出关系", content)
            self.assertIn("未读证据", content)
            self.assertIn("不代填接受", content)
            self.assertNotIn("reproducible-science", content)
            self.assertNotIn(".agentmuxer/ledger.md", content)
            self.assertNotIn("parrhesia_draft_manuscript", content)
            self.assertLess(len(content.encode("utf-8")), 11_000)
            self.assertNotIn("非 L0 任务默认执行以下五项要求", content)
        reference = outputs[TARGETS["l2_reference"]]
        for phrase in (
            "九个设计包",
            "最低统计报告标准",
            "四类",
            "七项底线",
            "≥2 个竞争解释",
            "record-exec",
            "审查者隔离配方",
            "tool_bound",
            "session_anchored",
            "unanchored",
            "无机械哈希核对",
            "Code Interpreter",
        ):
            self.assertIn(phrase, reference)
        for removed in ("L1-Judge", "## 8.", "必须来自 `record-exec` 或钩子绑定的输出"):
            self.assertNotIn(removed, reference)
        self.assertIn("反空转机械门控", outputs[TARGETS["workflow_reference"]])

        # ChatGPT handoff templates P0 parity & self-containment checks
        frozen = outputs[TARGETS["frozen_input"]]
        blind = outputs[TARGETS["frozen_input_blind"]]
        for forbidden in ("当前最佳解释", "区分检验设计", "初稿正文（非盲审版）", "字段见主指令"):
            self.assertNotIn(forbidden, blind, f"Blind template leaked: {forbidden}")
        self.assertNotIn("字段见主指令", frozen)
        for required in ("claim_direction", "endpoint_role", "skills/parrhesia-l2-reference/SKILL.md", "session_anchored"):
            self.assertIn(required, frozen)
            self.assertIn(required, blind)
        self.assertIn("当前最佳解释", frozen)
        self.assertIn("区分检验设计", frozen)

        for role_key in ("overclaim", "underclaim"):
            role_text = outputs[TARGETS[role_key]]
            self.assertIn("AUROC 0.84", role_text)
            self.assertIn("session_anchored", role_text)
            self.assertIn("无机械哈希核对", role_text)
            for ctype, levels in TYPE_LEVELS.items():
                self.assertIn(f"`{ctype}`", role_text, f"Missing claim_type {ctype} in {role_key}")
                for lvl in levels:
                    self.assertIn(lvl, role_text, f"Missing evidence_level {lvl} in {role_key}")

        adjudication = outputs[TARGETS["adjudication"]]
        for required in (
            "6 个汉字",
            "12 个 ASCII 可见字符",
            "symmetry_audit",
            "partially_supported",
            "causal_basis",
            "sampling_temporality",
            "session_anchored",
            "仅在报告开头显式标明一次“非独立审查，未排除起草偏差”",
        ):
            self.assertIn(required, adjudication)
        self.assertNotIn("在报告开头和每条判定旁标", adjudication)

        handoff = outputs[TARGETS["handoff"]]
        for required in (
            "01-frozen-input-blind.md",
            "blind=true",
            "Project-Only Memory",
            "Unpersonalized Temporary Chat",
            "session_anchored",
            "tool_bound",
            "unanchored",
        ):
            self.assertIn(required, handoff)
        integration = outputs[TARGETS["integration_reference"]]
        self.assertIn(".agentmuxer/ledger.md", integration)
        self.assertIn("不覆盖", integration)
        self.assertIn("未使用该集成", integration)
        self.assertLess(len(outputs[TARGETS["skill"]].encode("utf-8")), 5000)
        self.assertLess(len(source.encode("utf-8")), 80_000)

    def test_skill_references_resolve_inside_distributed_skill_tree(self):
        # Adapters copy the skill tree without the repository templates directory.
        skill_dir = ROOT / "skills/parrhesia-review"
        for link in re.findall(r"\]\(([^)]+)\)", (skill_dir / "SKILL.md").read_text(encoding="utf-8")):
            target = (skill_dir / link).resolve()
            self.assertTrue(target.is_relative_to(ROOT / "skills"), link)
            self.assertTrue(target.is_file(), link)
        from parrhesia.adapters import collect_skills_payloads
        payloads = collect_skills_payloads(ROOT, "installed/skills")
        for key in ("basic_reference", "workflow_reference", "integration_reference", "l2_reference"):
            self.assertIn("installed/" + TARGETS[key], payloads)

    def test_trigger_change_invalidates_every_primary_output_then_regenerates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            source = root / SOURCE
            text = source.read_text(encoding="utf-8")
            anchor = "推荐的日常工作流（不新增工具）"
            self.assertEqual(text.count(anchor), 1)
            source.write_text(text.replace(anchor, anchor + "（测试用触发变更）"), encoding="utf-8")
            expected_drifted = {TARGETS[name] for name in PRIMARY_TARGETS}
            self.assertEqual(set(drifted_files(root)), expected_drifted)
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
            original + "\n<!-- source:epistemic_core:start -->\nduplicate\n<!-- source:epistemic_core:end -->\n",
            original.replace("<!-- modules: epistemic_core, tool_host_l2 -->", "<!-- modules: unknown_mod -->", 1),
            original.replace("{{chatgpt_reviewer_ref}}", "{{unknown_snippet}}", 1),
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
