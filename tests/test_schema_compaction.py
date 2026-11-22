"""Schema payload budgets, local reference resolution, and nested rejection checks."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from parrhesia.claims import DESIGN_FIELDS
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.mcp_schemas import tool_definitions, _action_specs, _share_repeated_values, inline_schema
from test_server import _assert_valid_against_schema, _expand_local_refs


class SchemaCompactionTests(unittest.TestCase):
    def test_inline_fallback_and_role_profiles_preserve_constraints(self):
        full = {t["name"]: t for t in tool_definitions()}
        inline = {t["name"]: t for t in tool_definitions(schema_mode="inline")}
        self.assertEqual(full.keys(), inline.keys())
        for name in full:
            for direction in ("inputSchema", "outputSchema"):
                self.assertEqual(_expand_local_refs(full[name][direction]), inline[name][direction])
        for profile, submission, expected_count, budget in (
            ("review", "parrhesia_submit_review", 5, 12_000),
            ("adjudication", "parrhesia_submit_adjudication", 5, 15_000),
            ("explore", "parrhesia_explore", 5, 12_000),
            ("compact", "parrhesia_upsert_claim", 10, 20_000),
        ):
            tools = tool_definitions(tool_profile=profile)
            self.assertEqual(len(tools), expected_count)
            self.assertIn(submission, {t["name"] for t in tools})
            self.assertNotIn("parrhesia_workflow", {t["name"] for t in tools})
            self.assertLess(len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode()), budget)
            for tool in tools:
                self.assertEqual(tool, full[tool["name"]])
        for args in ({"schema_mode": "typo"}, {"tool_profile": "typo"}):
            with self.assertRaises(ValueError):
                tool_definitions(**args)
        for schema in ({"$ref": "https://example.invalid/schema"},
                       {"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/a"}}}):
            with self.assertRaises(ValueError):
                inline_schema(schema)

    def test_launcher_profiles_and_inline_mode_over_stdio(self):
        from test_server import INITIALIZE, request
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            messages = [INITIALIZE, request("tools/list", {}, 2),
                        request("tools/call", {"name": "parrhesia_workflow", "arguments": {"action": "create_case", "payload": {}}}, 3)]
            for mode in ("shared", "inline"):
                result = subprocess.run([sys.executable, str(root / "scripts/run-mcp.py"), "--workspace", directory,
                                         "--schema-mode", mode, "--tool-profile", "review"],
                                        input="".join(json.dumps(m) + "\n" for m in messages), text=True,
                                        capture_output=True, timeout=20, cwd=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                responses = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(responses[1]["result"]["tools"], tool_definitions(schema_mode=mode, tool_profile="review"))
                self.assertIn("error", responses[2])

    def setUp(self):
        self.tools = {tool["name"]: tool for tool in tool_definitions()}
        self.ledger_schema = self.tools["parrhesia_set_ledger"]["inputSchema"]

    def test_wire_budgets_and_self_contained_references(self):
        size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLess(size(list(self.tools.values())), 82_000)
        self.assertLess(size(self.tools["parrhesia_set_ledger"]), 25_000)
        self.assertLess(size(self.tools["parrhesia_upsert_claim"]), 4_500)
        self.assertLess(size(self.tools["parrhesia_draft_manuscript"]), 4_800)
        for tool in self.tools.values():
            for direction in ("inputSchema", "outputSchema"):
                expanded = _expand_local_refs(tool[direction])
                self.assertNotIn('"$ref"', json.dumps(expanded))
                self.assertEqual(expanded["type"], "object")
        self.assertEqual(self.ledger_schema["properties"]["claims"]["items"], {"$ref": "#/$defs/claim"})
        # A caller mutating a definition must not corrupt subsequent tools/list calls.
        self.ledger_schema["$defs"]["assessment"]["properties"].clear()
        fresh = {tool["name"]: tool for tool in tool_definitions()}
        self.assertIn("status", fresh["parrhesia_set_ledger"]["inputSchema"]["$defs"]["assessment"]["properties"])

    def test_sharing_preserves_all_typed_inputs_and_is_idempotent(self):
        for raw in _action_specs():
            final = self.tools[raw["name"]]["inputSchema"]
            self.assertEqual(_expand_local_refs(raw["inputSchema"]), _expand_local_refs(final), raw["name"])
            self.assertEqual(_share_repeated_values(final), final)
        for name in ("parrhesia_set_ledger", "parrhesia_submit_adjudication"):
            self.assertIn("evidence_level", self.tools[name]["inputSchema"]["$defs"])
        # No indirection/definitions added to tiny one-off schemas.
        tiny = {"type": "object", "properties": {"x": {"type": "string"}}}
        self.assertEqual(_share_repeated_values(tiny), tiny)

    def test_nested_constraints_still_reject_invalid_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(Path(directory))
            case = engine.dispatch("create_case", {"question": "Schema checks", "draft": "Draft"})
            claim = engine.dispatch("scaffold_claim", {
                "case_id": case["case_id"], "claim_type": "causal_effect",
                "design_families": list(DESIGN_FIELDS), "include_causal_basis": True,
            })["claim"]
            payload = {"case_id": case["case_id"], "claims": [claim]}
            _assert_valid_against_schema(self, payload, self.ledger_schema)
            self.assertTrue(engine.validate_action("set_ledger", payload)["valid"])

            corruptions = [
                lambda c: c["checks"]["quality"].update(status="made_up"),
                lambda c: c["design_packages"][0]["checks"]["measurement"].pop("evidence_ids"),
                lambda c: c["statistical_report"]["units_sample_size"].update(reason=""),
                lambda c: c["causal_basis"]["assumptions"][0].pop("name"),
                lambda c: c["causal_basis"]["necessity_test"].update(unexpected=True),
                lambda c: c.update(unexpected="reject unknown fields"),
            ]
            for corrupt in corruptions:
                bad = deepcopy(payload)
                corrupt(bad["claims"][0])
                with self.subTest(payload=bad), self.assertRaises(AssertionError):
                    _assert_valid_against_schema(self, bad, self.ledger_schema)
                with self.assertRaises(ContractError):
                    engine.validate_action("set_ledger", bad)
            self.assertEqual(engine.dispatch("get_case", {"case_id": case["case_id"]})["claims"], [])

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Optional standards validator is not installed")
    def test_draft202012_validation_and_real_draft_roundtrip(self):
        from jsonschema import Draft202012Validator, ValidationError
        for tool in self.tools.values():
            for direction in ("inputSchema", "outputSchema"):
                Draft202012Validator.check_schema(tool[direction])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.md").write_text("# Results\nThe model predicts recurrence with AUROC 0.84.\n", encoding="utf-8")
            engine = Engine(root)
            case = engine.dispatch("create_case", {"question": "Check saved draft", "draft": "Draft"})
            result = engine.dispatch("draft_manuscript", {"path": "paper.md", "case_id": case["case_id"]})
            Draft202012Validator(self.tools["parrhesia_draft_manuscript"]["outputSchema"]).validate(result)
            validator = Draft202012Validator(self.ledger_schema)
            validator.validate(result["ledger_payload"])
            self.assertIn("checks", result["claims"][0])
            self.assertIn("provenance_cards", result["claims"][0])
            bad = deepcopy(result["ledger_payload"])
            bad["claims"][0]["statistical_report"]["units_sample_size"]["status"] = "invented"
            with self.assertRaises(ValidationError):
                validator.validate(bad)
            with self.assertRaises(ContractError):
                engine.validate_action("set_ledger", bad)
            saved = engine.dispatch("set_ledger", result["ledger_payload"])
            self.assertEqual(saved["claim_count"], len(result["claims"]))


if __name__ == "__main__":
    unittest.main()
