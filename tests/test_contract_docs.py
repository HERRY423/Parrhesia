"""Contract discovery is bounded, honest about scope, and independent of case state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.contract_docs import contract_sections, select_contract, select_contract_batch
from parrhesia.contracts import ContractError
from parrhesia.server import Server, contract_text
from parrhesia.mcp_schemas import tool_definitions
import test_server
from test_server import INITIALIZE, request, _assert_valid_against_schema


class ContractDocumentTests(unittest.TestCase):
    def test_batch_deduplicates_overlaps_and_binds_one_document(self):
        text = "# Title\n## Parent\nparent\n### Child\nchild\n## Last\nlast\n"
        digest = hashlib.sha256(text.encode()).hexdigest()
        result = select_contract_batch(text, ["child", "parent", "last"], digest)
        self.assertEqual(result["contract"], text.split("\n", 1)[1])
        self.assertFalse(result["selection"]["complete_document"])
        self.assertEqual(len(result["selection"]["sections"]), 3)
        for names in ([], ["parent", "parent"], ["full"], ["index"], ["absent"], "parent", [None]):
            with self.subTest(names=names), self.assertRaises(ContractError):
                select_contract_batch(text, names)
        with self.assertRaisesRegex(ContractError, "contract_changed"):
            select_contract_batch(text, ["parent"], "0" * 64)
        with tempfile.TemporaryDirectory() as directory:
            server = Server(directory)
            result = server.tool("parrhesia_contract", {"sections": ["scaffold_claim", "v2-ledger-records-and-shared-assessment-shape"]})
            self.assertIn("### scaffold_claim", result["contract"])
            self.assertIn("V2 ledger records", result["contract"])
            with self.assertRaises(ContractError):
                server.tool("parrhesia_contract", {"section": "index", "sections": ["scaffold_claim"]})

    def test_exact_sections_nested_boundaries_fences_and_duplicate_titles(self):
        text = ("# Title\nIntro\n## First\nα β\n```md\n## Hidden\n```\n"
                "### Child\nbody\n~~~~\n## Also hidden\n~~~\n~~~~\n"
                "## First\nsecond\n## Full\nreserved name\n")
        sections = contract_sections(text)
        self.assertEqual([s["id"] for s in sections], ["first", "child", "first-2", "full-2"])
        self.assertEqual(sections[0]["start_line"], 3)
        self.assertEqual(sections[0]["end_line"], 13)
        digest = hashlib.sha256(text.encode()).hexdigest()
        for section in sections:
            result = select_contract(text, section["id"], digest)
            self.assertEqual(result["contract"], "".join(text.splitlines(keepends=True)[section["start_line"]-1:section["end_line"]]))
            self.assertEqual(result["selection"]["returned_bytes"], section["bytes"])
            self.assertFalse(result["selection"]["complete_document"])
        self.assertEqual(select_contract(text, "full")["contract"], text)
        with self.assertRaisesRegex(ContractError, "contract_changed"):
            select_contract(text + "changed\n", "first", digest)
        for unknown in ("missing", "../../private", "", "first/child"):
            with self.assertRaisesRegex(ContractError, "unknown_contract_section"):
                select_contract(text, unknown)

    def test_index_and_excerpts_are_read_only_and_legacy_full_shape_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = Server(temporary)
            snapshot = lambda: {str(p): p.read_bytes() for p in Path(temporary).rglob("*") if p.is_file()}
            before = snapshot()
            legacy = server.tool("parrhesia_contract", {})
            self.assertEqual(set(legacy), {"workspace", "version", "actions", "contract"})
            self.assertEqual(legacy["contract"], contract_text())
            index = server.tool("parrhesia_contract", {"section": "index"})
            self.assertLess(index["selection"]["returned_bytes"], 10_000)
            self.assertLess(index["selection"]["returned_bytes"], index["selection"]["source_bytes"] / 5)
            excerpt = server.tool("parrhesia_contract", {"section": "scaffold_claim", "expected_sha256": index["selection"]["source_sha256"]})
            self.assertTrue(excerpt["contract"].startswith("### scaffold_claim"))
            self.assertNotIn("### create_case", excerpt["contract"])
            schema = next(t for t in tool_definitions() if t["name"] == "parrhesia_contract")["outputSchema"]
            for response in (legacy, index, excerpt):
                _assert_valid_against_schema(self, response, schema)
            for args in ({"section": None}, {"section": 1}, {"section": "index", "extra": True},
                         {"section": "index", "expected_sha256": None}, {"expected_sha256": "G" * 64}):
                with self.assertRaises(ContractError):
                    server.tool("parrhesia_contract", args)
            with patch("parrhesia.server.contract_text", return_value=legacy["contract"] + "\nUpdated"):
                with self.assertRaisesRegex(ContractError, "contract_changed"):
                    server.tool("parrhesia_contract", {"section": "scaffold_claim", "expected_sha256": index["selection"]["source_sha256"]})
            self.assertEqual(before, snapshot())

    def test_real_stdio_section_resource_errors_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            exchange = test_server.MCPTests().exchange
            frames = exchange(temporary, [
                INITIALIZE,
                request("tools/call", {"name": "parrhesia_contract", "arguments": {"section": "index"}}, 2),
                request("resources/read", {"uri": "parrhesia://contract/scaffold_claim"}, 3),
                request("tools/call", {"name": "parrhesia_contract", "arguments": {"section": "missing"}}, 4),
                request("tools/call", {"name": "parrhesia_contract", "arguments": {"expected_sha256": "0" * 64}}, 5),
                request("resources/read", {"uri": "parrhesia://contract/%2e%2e%2fprivate"}, 6),
                request("tools/call", {"name": "parrhesia_contract"}, 7),
            ])
            self.assertIn("section='index'", frames[0]["result"]["instructions"])
            self.assertFalse(frames[1]["result"]["isError"])
            resource = json.loads(frames[2]["result"]["contents"][0]["text"])
            self.assertEqual(resource["selection"]["source_sha256"], frames[1]["result"]["structuredContent"]["selection"]["source_sha256"])
            for pos, code in ((3, "unknown_contract_section"), (4, "contract_changed")):
                self.assertTrue(frames[pos]["result"]["isError"])
                error = json.loads(frames[pos]["result"]["content"][0]["text"])
                self.assertEqual(error["error"], code)
                self.assertIn("index", error["repair_hint"])
            self.assertEqual(frames[5]["error"]["code"], -32602)
            self.assertEqual(frames[6]["result"]["structuredContent"]["contract"], contract_text())


if __name__ == "__main__":
    unittest.main()
