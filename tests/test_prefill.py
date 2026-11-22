"""Snapshot-to-ledger bridge: conservative defaults, explicit mapping, no mutation."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from parrhesia.core import Engine
from parrhesia.contracts import ContractError
from parrhesia.mcp_schemas import tool_definitions
from test_ingestion_coverage import _xlsx_bytes
from test_server import _assert_valid_against_schema


class PrefillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = Engine(self.root)
        self.case = self.engine.dispatch("create_case", {"question": "Bridge fixture", "draft": "Synthetic test only"})
        self.cid = self.case["case_id"]
        self.table = b"endpoint,metric,estimate,ci_low,ci_high\nresponse,diff,2,1,3\nharm,diff,-5,-8,-2\nmissing,diff,NA,,\n"
        (self.root / "stats.csv").write_bytes(self.table)
        self.eid = self.engine.dispatch("import_artifact", {"case_id": self.cid, "path": "stats.csv"})["evidence"]["evidence_id"]
        self.prefill = {"effect_sources": [{"evidence_id": self.eid, "record_ids": ["effect-1"]}]}

    def state(self):
        return self.engine.dispatch("get_case", {"case_id": self.cid})

    def scaffold(self, prefill=None, **kw):
        return self.engine.dispatch("scaffold_claim", {"case_id": self.cid, "prefill": self.prefill if prefill is None else prefill, **kw})

    def test_roundtrip_keeps_bound_values_unknowns_and_omitted_rows(self):
        before = self.state()
        result = self.scaffold()
        claim = result["claim"]
        self.assertEqual(claim["effect_records"][0]["estimate"], 2)
        self.assertEqual(claim["effect_records"][0]["artifact_binding"]["source_sha256"], hashlib.sha256(self.table).hexdigest())
        self.assertEqual(claim["evidence_ids"], [self.eid])
        self.assertEqual(claim["evidence_level"], "unassessed")
        self.assertEqual(claim["origin"], "unknown")
        self.assertEqual(claim["effect_records"][0]["endpoint_role"], "exploratory")
        self.assertEqual(claim["effect_records"][0]["direction"], "neutral")
        self.assertTrue(all(v["status"] == "unknown" for v in claim["checks"].values()))
        report = result["prefill_report"]["sources"][0]
        self.assertEqual(report["input_row_count"], 3)
        self.assertEqual(report["unselected_record_ids"], ["effect-2"])
        self.assertEqual(report["issues"][0]["code"], "missing_estimate")
        self.assertEqual(self.state(), before)
        self.assertTrue(self.engine.validate_action("set_ledger", result["ledger_payload"])["valid"])
        self.assertEqual(self.state(), before)
        schemas = {t["name"]: t for t in tool_definitions()}
        _assert_valid_against_schema(self, result, schemas["parrhesia_scaffold_claim"]["outputSchema"])
        _assert_valid_against_schema(self, result["ledger_payload"], schemas["parrhesia_set_ledger"]["inputSchema"])
        self.engine.dispatch("set_ledger", result["ledger_payload"])
        self.assertEqual(self.state()["claims"][0]["effect_records"], claim["effect_records"])

    def test_snapshot_is_authority_even_after_source_changes(self):
        (self.root / "stats.csv").write_text("different source", encoding="utf-8")
        self.assertEqual(self.scaffold()["claim"]["effect_records"][0]["estimate"], 2)

    def test_multisheet_prefill_binds_the_selected_sheet_and_row(self):
        header = [("inlineStr", name, None) for name in ("endpoint", "metric", "estimate")]
        workbook = _xlsx_bytes({
            "Primary": [header, [("inlineStr", "PFS", None), ("inlineStr", "HR", None), ("n", "0.71", None)]],
            "Sensitivity": [header, [("inlineStr", "PFS", None), ("inlineStr", "HR", None), ("n", "1.26", None)]],
        })
        (self.root / "table.xlsx").write_bytes(workbook)
        eid = self.engine.dispatch("import_artifact", {"case_id": self.cid, "path": "table.xlsx"})["evidence"]["evidence_id"]
        selected = self.engine.dispatch("extract_effects", {"case_id": self.cid, "evidence_id": eid, "sheet_name": "Sensitivity"})
        record = selected["effect_records"][0]
        self.assertEqual(record["estimate"], 1.26)
        base = {"evidence_id": eid, "record_ids": [record["id"]]}
        before = self.state()
        with self.assertRaisesRegex(ContractError, "ambiguous_source"):
            self.scaffold({"effect_sources": [base]})
        selection = {**base, "format": "xlsx", "sheet_name": "Sensitivity"}
        primary = {**base, "sheet_name": "Primary"}
        prefill = {"effect_sources": [selection, primary]}
        result = self.scaffold(prefill)
        records = result["claim"]["effect_records"]
        self.assertEqual([r["estimate"] for r in records], [1.26, 0.71])
        self.assertEqual([r["artifact_binding"]["sheet"] for r in records], ["Sensitivity", "Primary"])
        self.assertEqual([s["sheet_name"] for s in result["prefill_report"]["sources"]], ["Sensitivity", "Primary"])
        self.assertEqual(self.state(), before)
        self.assertTrue(self.engine.validate_action("set_ledger", result["ledger_payload"])["valid"])
        schema = next(t["inputSchema"] for t in tool_definitions() if t["name"] == "parrhesia_scaffold_claim")
        _assert_valid_against_schema(self, {"case_id": self.cid, "prefill": prefill}, schema)
        with self.assertRaisesRegex(ContractError, "duplicate_id"):
            self.scaffold({"effect_sources": [selection, selection]})

    def test_corrupt_or_missing_snapshot_cannot_prefill(self):
        for content in (b"corrupted", None):
            with closing(sqlite3.connect(self.engine.database)) as db, db:
                if content is None:
                    db.execute("DELETE FROM evidence_snapshots WHERE evidence_id=?", (self.eid,))
                else:
                    db.execute("UPDATE evidence_snapshots SET content=? WHERE evidence_id=?", (content, self.eid))
            before = self.state()
            with self.assertRaisesRegex(ContractError, "source_changed"):
                self.scaffold()
            self.assertEqual(self.state(), before)

    def test_ids_and_invalid_rows_cannot_be_guessed_or_cross_cases(self):
        before = self.state()
        cases = [
            {"effect_sources": [{"evidence_id": self.eid, "record_ids": ["effect-3"]}]},
            {"effect_sources": self.prefill["effect_sources"] * 2},
            {"evidence_ids": ["ev-absent"]}, {"hypothesis_id": "hyp-absent"},
            {"effect_sources": [{"evidence_id": self.eid, "record_ids": []}]},
        ]
        for prefill in cases:
            with self.subTest(prefill=prefill), self.assertRaises(ContractError):
                self.scaffold(prefill)
            self.assertEqual(self.state(), before)
        other = self.engine.dispatch("create_case", {"question": "Other", "draft": "Other"})
        with self.assertRaises(ContractError):
            self.engine.dispatch("scaffold_claim", {"case_id": other["case_id"], "prefill": self.prefill})
        for payload in ({"prefill": self.prefill}, {"case_id": self.cid, "prefill": None},
                        {"case_id": self.cid, "prefill": {}, "domain": "general"}):
            with self.assertRaises(ContractError):
                self.engine.dispatch("scaffold_claim", payload)

    def test_multisource_effect_ids_unique_and_design_is_not_qualified(self):
        (self.root / "second.csv").write_bytes(self.table)
        second = self.engine.dispatch("import_artifact", {"case_id": self.cid, "path": "second.csv"})["evidence"]["evidence_id"]
        result = self.scaffold({"effect_sources": [*self.prefill["effect_sources"], {"evidence_id": second, "record_ids": ["effect-2"]}],
                                "design_families": ["randomized", "observational"]})
        claim = result["claim"]
        self.assertEqual(len(set(r["id"] for r in claim["effect_records"])), 2)
        self.assertEqual([r["estimate"] for r in claim["effect_records"]], [2, -5])
        self.assertTrue(all(c["status"] == "unknown" for p in claim["design_packages"] for c in p["checks"].values()))
        self.assertTrue(self.engine.validate_action("set_ledger", result["ledger_payload"])["valid"])

    def test_hypothesis_attachment_does_not_certify_timing(self):
        hypothesis = self.engine.dispatch("register_hypothesis", {"case_id": self.cid, "statement": "Response changes", "timing_basis": "unknown"})
        result = self.scaffold({"hypothesis_id": hypothesis["hypothesis_id"]})
        self.assertEqual(result["claim"]["hypothesis_id"], hypothesis["hypothesis_id"])
        self.assertEqual(result["claim"]["origin"], "unknown")
        self.assertEqual(result["prefill_report"]["hypothesis"]["timing_basis"], "unknown")

    def test_manuscript_batch_bindings_require_hash_and_preserve_state(self):
        paper = self.root / "paper.md"
        paper.write_text("# Results\nThe response increased by 2 units.\n", encoding="utf-8")
        payload = {"path": "paper.md", "case_id": self.cid}
        draft = self.engine.dispatch("draft_manuscript", payload)
        payload.update(expected_source_sha256=draft["source"]["sha256"],
                       claim_bindings=[{"claim_id": "C1", "quote": draft["source_map"][0]["quote"],
                                        "location": draft["source_map"][0]["location"], "prefill": self.prefill}])
        before = self.state()
        result = self.engine.dispatch("draft_manuscript", payload)
        self.assertEqual(result["ledger_payload"]["claims"][0]["effect_records"][0]["estimate"], 2)
        self.assertTrue(self.engine.validate_action("set_ledger", result["ledger_payload"])["valid"])
        self.assertEqual(self.state(), before)
        for edit in ({"expected_source_sha256": "0" * 64},
                     {"claim_bindings": [{**payload["claim_bindings"][0], "claim_id": "C99"}]},
                     {"claim_bindings": [{**payload["claim_bindings"][0], "quote": "Different claim"}]},
                     {"claim_bindings": [{**payload["claim_bindings"][0], "location": "L99"}]},
                     {"claim_bindings": payload["claim_bindings"] * 2}):
            with self.subTest(edit=edit), self.assertRaises(ContractError):
                self.engine.dispatch("draft_manuscript", {**payload, **edit})
        del payload["expected_source_sha256"]
        with self.assertRaises(ContractError):
            self.engine.dispatch("draft_manuscript", payload)
        payload["expected_source_sha256"] = draft["source"]["sha256"]
        paper.write_text("# Results\nThe harm increased by 5 units.\n", encoding="utf-8")
        with self.assertRaises(ContractError):
            self.engine.dispatch("draft_manuscript", payload)

    def test_latex_draft_binds_transitive_includes_even_when_the_quote_is_unchanged(self):
        quote = "The response increased by 2 units."
        root = self.root / "paper.tex"
        root.write_text(f"\\input{{methods}}\n{quote}\n", encoding="utf-8")
        (self.root / "methods.tex").write_text("\\include{population}\n", encoding="utf-8")
        population = self.root / "population.tex"
        population.write_text("Participants were adults.\n", encoding="utf-8")
        request = {"path": "paper.tex", "case_id": self.cid, "selections": [{"quote": quote, "location": "L2"}]}
        first = self.engine.dispatch("draft_manuscript", request)
        self.assertEqual(first["source"]["root_sha256"], hashlib.sha256(root.read_bytes()).hexdigest())
        self.assertEqual([s["path"] for s in first["source"]["included_sources"]], ["methods.tex", "population.tex"])
        binding = {**request, "expected_source_sha256": first["source"]["sha256"],
                   "claim_bindings": [{"claim_id": "C1", "quote": quote, "location": "L2", "prefill": self.prefill}]}
        old = self.engine.dispatch("draft_manuscript", binding)
        self.assertEqual(old["claims"][0]["effect_records"][0]["estimate"], 2)
        population.write_text("Participants were children.\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "source_changed"):
            self.engine.dispatch("draft_manuscript", binding)
        changed = self.engine.dispatch("draft_manuscript", request)
        self.assertEqual(changed["source"]["root_sha256"], first["source"]["root_sha256"])
        self.assertEqual(changed["source_map"][0]["quote"], quote)
        self.assertNotEqual(changed["source"]["sha256"], first["source"]["sha256"])
        accepted = self.engine.dispatch("draft_manuscript", {**binding, "expected_source_sha256": changed["source"]["sha256"]})
        self.assertEqual(accepted["claims"][0]["effect_records"][0]["estimate"], 2)


if __name__ == "__main__":
    unittest.main()
