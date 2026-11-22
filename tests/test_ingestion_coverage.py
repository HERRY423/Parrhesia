"""Tests covering Workstream 2 manuscript formats, binary artifacts, DVC checksums, and statistical extensions."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib

from parrhesia.artifacts import inspect_artifact
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.manuscript import draft_manuscript, read_manuscript
from parrhesia.stat_import import compare_manuscript, parse_statistics


def _build_pdf(objects_body: list[bytes]) -> bytes:
    """Build PDF-1.4 with a real xref/trailer; object 1 is the Catalog."""
    parts = [b"%PDF-1.4\n"]
    offsets = []
    for idx, body in enumerate(objects_body, 1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{idx} 0 obj\n".encode("ascii"))
        parts.append(body)
        parts.append(b"\nendobj\n")
    xref_offset = sum(len(part) for part in parts)
    parts.append(f"xref\n0 {len(objects_body) + 1}\n0000000000 65535 f \n".encode())
    parts.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    parts.append(f"trailer\n<< /Size {len(objects_body) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
    return b"".join(parts)


def _xlsx_bytes(sheets: dict[str, list[list[tuple[str, str, str | None]]]], shared: list[str] | None = None) -> bytes:
    """Build minimal multi-sheet XLSX bytes. Cell tuples: (cell_type, value_or_cached, optional_formula)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        sheet_tags = []
        rel_tags = []
        for idx, (sname, rows) in enumerate(sheets.items(), 1):
            sheet_tags.append(f'<sheet name="{sname}" sheetId="{idx}" r:id="rId{idx}"/>')
            rel_tags.append(
                f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
            )
            row_xml = []
            for r_idx, row in enumerate(rows, 1):
                cells_xml = []
                for c_idx, (ctype, val, formula) in enumerate(row):
                    col_letter = chr(ord("A") + c_idx)
                    ref = f"{col_letter}{r_idx}"
                    f_xml = f"<f>{formula}</f>" if formula else ""
                    if ctype == "inlineStr":
                        cells_xml.append(f'<c r="{ref}" t="inlineStr">{f_xml}<is><t>{val}</t></is></c>')
                    elif ctype == "s":
                        cells_xml.append(f'<c r="{ref}" t="s">{f_xml}<v>{val}</v></c>')
                    elif ctype == "b":
                        cells_xml.append(f'<c r="{ref}" t="b">{f_xml}<v>{val}</v></c>')
                    else:
                        cells_xml.append(f'<c r="{ref}">{f_xml}<v>{val}</v></c>')
                row_xml.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')
            zf.writestr(
                f"xl/worksheets/sheet{idx}.xml",
                f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(row_xml)}</sheetData></worksheet>',
            )
        zf.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(sheet_tags)}</sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rel_tags)}</Relationships>',
        )
        if shared is not None:
            si_xml = "".join(f"<si><t>{s}</t></si>" for s in shared)
            zf.writestr(
                "xl/sharedStrings.xml",
                f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{si_xml}</sst>',
            )
    return buf.getvalue()


def _thrift_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _thrift_zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _build_parquet_bytes(num_rows: int = 42, created_by: str = "parrhesia-test") -> bytes:
    """Build a minimal valid PAR1 + TCompactProtocol FileMetaData Parquet file."""
    footer = bytearray()
    # field 1: version (i32 = 1) -> delta 1, type 5
    footer.append((1 << 4) | 5)
    footer.extend(_thrift_varint(_thrift_zigzag(1)))
    # field 2: schema LIST<SchemaElement> (3 elems: root, col1 INT64 REQUIRED, col2 BYTE_ARRAY OPTIONAL)
    footer.append((1 << 4) | 9)
    footer.append((3 << 4) | 12)
    # elem 0: name="schema" (fid=4, bin=8), num_children=2 (fid=5, i32=5)
    footer.append(0x08)
    footer.extend(_thrift_varint(_thrift_zigzag(4)))
    footer.extend(_thrift_varint(len(b"schema")) + b"schema")
    footer.append((1 << 4) | 5)
    footer.extend(_thrift_varint(_thrift_zigzag(2)))
    footer.append(0x00)
    # elem 1: type=INT64(2) (fid=1), rep=REQUIRED(0) (fid=3), name="id" (fid=4)
    footer.append((1 << 4) | 5)
    footer.extend(_thrift_varint(_thrift_zigzag(2)))
    footer.append((2 << 4) | 5)
    footer.extend(_thrift_varint(_thrift_zigzag(0)))
    footer.append((1 << 4) | 8)
    footer.extend(_thrift_varint(len(b"id")) + b"id")
    footer.append(0x00)
    # elem 2: type=BYTE_ARRAY(6) (fid=1), rep=OPTIONAL(1) (fid=3), name="arm" (fid=4)
    footer.append((1 << 4) | 5)
    footer.extend(_thrift_varint(_thrift_zigzag(6)))
    footer.append((2 << 4) | 5)
    footer.extend(_thrift_varint(_thrift_zigzag(1)))
    footer.append((1 << 4) | 8)
    footer.extend(_thrift_varint(len(b"arm")) + b"arm")
    footer.append(0x00)
    # field 3: num_rows (i64) -> delta 1, type 6
    footer.append((1 << 4) | 6)
    footer.extend(_thrift_varint(_thrift_zigzag(num_rows)))
    # field 4: row_groups LIST<RowGroup> (1 empty struct)
    footer.append((1 << 4) | 9)
    footer.append((1 << 4) | 12)
    footer.append(0x00)
    # field 6: created_by BINARY -> delta 2, type 8
    cb = created_by.encode("utf-8")
    footer.append((2 << 4) | 8)
    footer.extend(_thrift_varint(len(cb)) + cb)
    footer.append(0x00)
    return b"PAR1" + bytes(footer) + struct.pack("<I", len(footer)) + b"PAR1"


class IngestionCoverageTests(unittest.TestCase):
    def test_pdf_uncompressed_flatedecode_tounicode_encrypted_and_empty_rejection(self):
        # 1. Uncompressed PDF
        plain_stream = b"BT /F1 12 Tf (Treatment lowers risk by HR 0.65 (95% CI 0.50 to 0.85).) Tj ET"
        pdf_plain = _build_pdf([
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(plain_stream)).encode() + b" >>\nstream\n" + plain_stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        ])
        doc_plain = read_manuscript(pdf_plain, "paper.pdf")
        self.assertEqual(doc_plain["format"], "pdf")
        self.assertEqual(doc_plain["units"][0]["location"], "pdf:p1:L1")
        self.assertIn("HR 0.65", doc_plain["units"][0]["text"])

        # 2. FlateDecode + ToUnicode CMap (beginbfchar + beginbfrange)
        cmap = (
            b"/CIDInit /ProcSet findresource begin\n"
            b"begincmap\n"
            b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
            b"1 beginbfchar\n<01> <0041>\nendbfchar\n"
            b"1 beginbfrange\n<02> <03> <0042>\nendbfrange\n"
            b"endcmap\n"
        )
        content_stream = zlib.compress(b"BT /F1 12 Tf (\x01\x02\x03 risk dropped) Tj ET")
        cmap_stream = zlib.compress(cmap)
        pdf_flate = _build_pdf([
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 6 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(content_stream)).encode() + b" /Filter /FlateDecode >>\nstream\n" + content_stream + b"\nendstream",
            b"<< /Length " + str(len(cmap_stream)).encode() + b" /Filter /FlateDecode >>\nstream\n" + cmap_stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [1 /A /B /C] >> /ToUnicode 5 0 R >>",
        ])
        doc_flate = read_manuscript(pdf_flate, "encoded.pdf")
        self.assertIn("ABC risk dropped", doc_flate["units"][0]["text"])

        # 3. Encrypted PDF fails cleanly
        pdf_enc = _build_pdf([b"<< /Encrypt 2 0 R >>"])
        with self.assertRaises(ContractError) as cm_enc:
            read_manuscript(pdf_enc, "locked.pdf")
        self.assertEqual(cm_enc.exception.code, "invalid_source")

        # 4. Empty/scanned-image PDF with zero text fails cleanly
        pdf_empty = _build_pdf([
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
        ])
        with self.assertRaises(ContractError) as cm_emp:
            read_manuscript(pdf_empty, "scanned.pdf")
        self.assertEqual(cm_emp.exception.code, "unsupported_format")

    def test_html_jats_xml_and_ipynb_narrative_manuscript_parsing(self):
        html = (
            "<html><head><style>.hide{display:none}</style>"
            "<script>window.evil = 'do not execute';</script></head>"
            "<body><!-- hidden comment --><h1>Outcome Summary</h1>"
            "<p>Therapy predicts 6-month survival (AUROC 0.84) across external cohorts.</p>"
            "<table><tr><td>OR</td><td>0.70</td></tr></table></body></html>"
        ).encode("utf-8")
        doc_html = read_manuscript(html, "report.html")
        joined_html = "\n".join(u["text"] for u in doc_html["units"])
        self.assertNotIn("evil", joined_html)
        self.assertNotIn("hidden comment", joined_html)
        self.assertIn("Therapy predicts 6-month survival", joined_html)
        self.assertIn("OR | 0.70", joined_html)

        jats = (
            "<article><front><article-meta><title-group>"
            "<article-title>Cohort Study of Drug Z</article-title>"
            "</title-group></article-meta></front>"
            "<body><sec><title>Results</title>"
            "<p>Drug Z reduces hazard of mortality (HR 0.71, p=0.004).</p>"
            "</sec></body></article>"
        ).encode("utf-8")
        doc_jats = read_manuscript(jats, "article.nxml")
        joined_jats = "\n".join(u["text"] for u in doc_jats["units"])
        self.assertIn("Cohort Study of Drug Z", joined_jats)
        self.assertIn("Drug Z reduces hazard of mortality", joined_jats)

        # JATS rejects DTD/ENTITY
        with self.assertRaises(ContractError) as cm_dtd:
            read_manuscript(b'<!DOCTYPE article [<!ENTITY x "boom">]><article/>', "evil.nxml")
        self.assertEqual(cm_dtd.exception.code, "invalid_source")

        nb = json.dumps({
            "nbformat": 4,
            "cells": [
                {"cell_type": "markdown", "source": ["# Study Notes\n", "Model generalizes across external sites with F1 0.89."]},
                {"cell_type": "code", "source": ["print('IGNORE CODE BODY')"]},
            ],
        }).encode("utf-8")
        doc_nb = read_manuscript(nb, "analysis.ipynb")
        joined_nb = "\n".join(u["text"] for u in doc_nb["units"])
        self.assertIn("Model generalizes across external sites", joined_nb)
        self.assertNotIn("IGNORE CODE BODY", joined_nb)

    def test_multifile_latex_includes_boundaries_and_mixed_claim_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sec = root / "sections"
            sec.mkdir()
            (root / "main.tex").write_text(
                "\\section{Intro}\n"
                "Treatment causes remission and predicts relapse via pathway P in cohorts.\n"
                "\\input{sections/results}\n"
                "\\input{sections/missing}\n"
                "\\input{../../outside}\n",
                encoding="utf-8",
            )
            (sec / "results.tex").write_text(
                "Subfile observation shows OR 0.65 (95% CI 0.48 to 0.88, p=0.005).\n"
                "\\input{cycle_a}\n",
                encoding="utf-8",
            )
            (sec / "cycle_a.tex").write_text("\\input{sections/results}\nCycle line.\n", encoding="utf-8")

            engine = Engine(root)
            drafted = engine.dispatch("draft_manuscript", {"path": "main.tex", "domain": "scientific"})
            locations = [m["location"] for m in drafted["source_map"]]
            self.assertIn("L2", locations)
            self.assertIn("sections/results.tex:L1", locations)

            mixed_entry = next(m for m in drafted["source_map"] if m["location"] == "L2")
            self.assertGreaterEqual(len(mixed_entry["detected_claim_types"]), 2)
            self.assertTrue(mixed_entry["split_recommended"])

            omitted = drafted["source"]["omitted"]
            self.assertTrue(any("missing" in o for o in omitted))
            self.assertTrue(any("outside" in o for o in omitted))
            self.assertTrue(any("cyclic LaTeX include" in o for o in omitted))

    def test_binary_xlsx_parquet_notebook_rmd_and_dvc_local_verification(self):
        xlsx = _xlsx_bytes(
            {
                "Summary": [[("inlineStr", "Report", None), ("inlineStr", "Count", None)], [("s", "0", None), ("n", "12", "=6+6")]],
                "Endpoints": [[("inlineStr", "endpoint", None), ("inlineStr", "metric", None), ("inlineStr", "estimate", None), ("inlineStr", "p_value", None)],
                              [("inlineStr", "OS", None), ("inlineStr", "HR", None), ("n", "0.71", None), ("n", "0.008", None)]],
            },
            shared=["Cohort Summary"],
        )
        pq = _build_parquet_bytes(num_rows=42, created_by="parrhesia-test")

        nb_bad_order = json.dumps({
            "nbformat": 4,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}, "secret_env": "DO_NOT_LEAK"},
            "cells": [
                {"cell_type": "markdown", "source": ["# Intro"]},
                {"cell_type": "code", "execution_count": 3, "outputs": []},
                {"cell_type": "code", "execution_count": 1, "outputs": []},
            ],
        }).encode("utf-8")

        qmd = (
            "---\n"
            "title: \"Study Report\"\n"
            "author: Research Team\n"
            "format: !expr evil()\n"
            "output: html\n"
            "---\n\n"
            "```{r setup, include=FALSE}\nlibrary(stats)\n```\n"
            "```{python model}\nprint(1)\n```\n"
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workbook.xlsx").write_bytes(xlsx)
            (root / "cohort.parquet").write_bytes(pq)
            (root / "nb.ipynb").write_bytes(nb_bad_order)
            (root / "report.qmd").write_bytes(qmd)
            data_bytes = b"endpoint,estimate\nOS,0.71\n"
            (root / "data.csv").write_bytes(data_bytes)
            good_md5 = hashlib.md5(data_bytes).hexdigest()
            (root / "data.csv.dvc").write_text(f"outs:\n- md5: {good_md5}\n  path: data.csv\n", encoding="utf-8")
            (root / "dir.dvc").write_text(f"outs:\n- md5: {'a'*32}.dir\n  path: data.csv\n", encoding="utf-8")

            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "Artifacts check?", "draft": "Draft"})["case_id"]

            imp_x = engine.dispatch("import_artifact", {"case_id": cid, "path": "workbook.xlsx"})
            self.assertEqual(imp_x["artifact"]["format"], "xlsx")
            self.assertEqual(imp_x["artifact"]["kind"], "unknown")
            self.assertTrue(imp_x["artifact"]["details"]["any_formula_cached_values"])
            self.assertEqual(imp_x["artifact"]["details"]["sheet_names"], ["Summary", "Endpoints"])

            imp_p = engine.dispatch("import_artifact", {"case_id": cid, "path": "cohort.parquet"})
            self.assertEqual(imp_p["artifact"]["format"], "parquet")
            self.assertEqual(imp_p["artifact"]["details"]["num_rows"], 42)
            self.assertEqual(imp_p["artifact"]["details"]["column_count"], 2)
            self.assertFalse(imp_p["artifact"]["details"]["data_content_verified"])

            imp_nb = engine.dispatch("import_artifact", {"case_id": cid, "path": "nb.ipynb"})
            self.assertTrue(imp_nb["artifact"]["details"]["out_of_order_execution"])
            self.assertEqual(imp_nb["artifact"]["details"]["markdown_cells"], 1)
            self.assertEqual(imp_nb["artifact"]["details"]["kernelspec"]["name"], "python3")

            imp_q = engine.dispatch("import_artifact", {"case_id": cid, "path": "report.qmd"})
            self.assertEqual(imp_q["artifact"]["details"]["chunk_languages"], ["python", "r"])
            self.assertEqual(imp_q["artifact"]["details"]["yaml_header"], {"title": "Study Report", "author": "Research Team", "output": "html"})

            imp_dvc_ok = engine.dispatch("import_artifact", {"case_id": cid, "path": "data.csv.dvc"})
            self.assertTrue(imp_dvc_ok["artifact"]["details"]["data_content_verified"])
            self.assertEqual(imp_dvc_ok["artifact"]["details"]["recorded_checksums"][0]["verification"], "matched")

            # Mutate local data -> DVC check catches mismatch honestly
            (root / "data.csv").write_bytes(b"endpoint,estimate\nOS,0.50\n")
            imp_dvc_bad = engine.dispatch("import_artifact", {"case_id": cid, "path": "data.csv.dvc"})
            self.assertFalse(imp_dvc_bad["artifact"]["details"]["data_content_verified"])
            self.assertEqual(imp_dvc_bad["artifact"]["details"]["recorded_checksums"][0]["verification"], "mismatch")

            # Directory .dir hash remains unverified
            imp_dvc_dir = engine.dispatch("import_artifact", {"case_id": cid, "path": "dir.dvc"})
            self.assertFalse(imp_dvc_dir["artifact"]["details"]["data_content_verified"])
            self.assertEqual(imp_dvc_dir["artifact"]["details"]["recorded_checksums"][0]["verification"], "unverified_dir")

            # Corrupted Parquet fails invalid_source
            with self.assertRaises(ContractError) as cm_pq:
                inspect_artifact(b"BAD1footerPAR1", "broken.parquet")
            self.assertEqual(cm_pq.exception.code, "invalid_source")

    def test_manuscript_p_values_and_similar_endpoint_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "PFS fixture", "draft": "Synthetic comparison"})["case_id"]
            (root / "table.csv").write_text("endpoint,metric,estimate,p_value\nPFS,HR,0.99,0.40\n", encoding="utf-8")
            eid = engine.dispatch("import_artifact", {"case_id": cid, "path": "table.csv"})["evidence"]["evidence_id"]
            request = {"case_id": cid, "evidence_id": eid, "manuscript_path": "result.md"}
            for statement, expected in (
                ("PFS HR 0.99 (p=0).", "mismatch"),
                ("PFS HR 0.99 (p=0.00).", "mismatch"),
                ("PFS HR 0.99 (p=0.01).", "mismatch"),
                ("PFS HR 0.99 (p=0.40).", "match_at_reported_precision"),
                ("主要终点PFS的 HR 0.99 (p>0.05)。", "match_at_reported_precision"),
                ("iPFS HR 0.99 (p=0.40).", "not_found"),
                ("PFS2 HR 0.99 (p=0.40).", "not_found"),
            ):
                with self.subTest(statement=statement):
                    (root / "result.md").write_text(statement + "\n", encoding="utf-8")
                    comparison = engine.dispatch("extract_effects", request)["manuscript_comparison"][0]
                    self.assertEqual(comparison["status"], expected)
                    if "p=0)" in statement or "p=0.00)" in statement:
                        self.assertEqual(comparison["field_checks"][0]["reason"], "invalid_reported_p_value")

    def test_stat_import_contingency_json_xlsx_sheet_selection_and_scale_assumption(self):
        # 1. contingency_json computes RD, RR, OR, Fisher two-sided p
        cont_json = json.dumps({
            "endpoint": "Relapse",
            "treated_events": 12,
            "treated_n": 40,
            "control_events": 24,
            "control_n": 40,
        }).encode("utf-8")
        parsed_c = parse_statistics(cont_json, "table2x2.json", "ev_c", format="contingency_json")
        self.assertEqual([r["metric"] for r in parsed_c["effect_records"]], ["risk_diff", "RR", "OR"])
        or_rec = parsed_c["effect_records"][2]
        self.assertAlmostEqual(or_rec["estimate"], (12 * 16) / (28 * 24), places=6)
        self.assertLess(or_rec["p_value"], 0.02)

        # 2. XLSX auto-selection skips non-stats Summary sheet and supports explicit sheet_name
        xlsx = _xlsx_bytes({
            "Notes": [[("inlineStr", "Title", None), ("inlineStr", "Description", None)], [("inlineStr", "Study", None), ("inlineStr", "Phase 2", None)]],
            "Primary": [[("inlineStr", "endpoint", None), ("inlineStr", "metric", None), ("inlineStr", "estimate", None)],
                        [("inlineStr", "OS", None), ("inlineStr", "HR", None), ("n", "0.72", None)]],
            "Sensitivity": [[("inlineStr", "endpoint", None), ("inlineStr", "metric", None), ("inlineStr", "estimate", None)],
                            [("inlineStr", "OS_sens", None), ("inlineStr", "HR", None), ("n", "0.75", None)]],
        })
        auto_res = parse_statistics(xlsx, "table.xlsx", "ev_x")
        self.assertEqual(auto_res["effect_records"][0]["endpoint"], "OS")
        self.assertEqual(auto_res["xlsx"]["sheet"], "Primary")
        self.assertEqual(auto_res["xlsx"]["omitted_sheets"], ["Notes", "Sensitivity"])

        sens_res = parse_statistics(xlsx, "table.xlsx", "ev_x", sheet_name="Sensitivity")
        self.assertEqual(sens_res["effect_records"][0]["endpoint"], "OS_sens")
        self.assertEqual(sens_res["effect_records"][0]["artifact_binding"]["sheet"], "Sensitivity")

        # 3. assumed_reported_scale disambiguates percentage table vs bare unit report
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pct.csv").write_text(
                "endpoint,metric,estimate,ci_low,ci_high,ci_level,scale\n"
                "Response,proportion,52.0,38.0,66.0,0.95,percentage\n",
                encoding="utf-8",
            )
            (root / "paper.md").write_text(
                "Observed Response proportion 0.52 (95% CI 0.38 to 0.66).\n",
                encoding="utf-8",
            )
            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "Scale?", "draft": "Response"})["case_id"]
            ev = engine.dispatch("register_evidence", {
                "case_id": cid, "path": "pct.csv", "provenance": "reported",
                "kind": "unknown", "quote": "Response,proportion,52.0,38.0,66.0,0.95,percentage", "location": "L2",
            })["evidence_id"]

            cmp_auto = engine.dispatch("extract_effects", {"case_id": cid, "evidence_id": ev, "manuscript_path": "paper.md"})
            self.assertEqual(cmp_auto["manuscript_comparison"][0]["status"], "ambiguous_scale")

            cmp_unit = engine.dispatch("extract_effects", {
                "case_id": cid, "evidence_id": ev, "manuscript_path": "paper.md", "assumed_reported_scale": "unit",
            })
            self.assertEqual(cmp_unit["manuscript_comparison"][0]["status"], "match_at_reported_precision")
            self.assertEqual(cmp_unit["manuscript_comparison"][0]["scale_assumption"], "caller_declared_unit")


if __name__ == "__main__":
    unittest.main()
