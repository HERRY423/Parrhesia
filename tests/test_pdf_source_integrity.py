"""PDF source integrity: font-scoped decoding and catalog page order.

These fixtures use a conventional xref/trailer and independent, explicit glyph
expectations. They do not reuse the release-audit samples or change old fixtures.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zlib

from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.manuscript import read_manuscript


def stream(data: bytes, *, compressed: bool = False) -> bytes:
    payload = zlib.compress(data) if compressed else data
    flt = b" /Filter /FlateDecode" if compressed else b""
    return b"<< /Length " + str(len(payload)).encode() + flt + b" >>\nstream\n" + payload + b"\nendstream"


def pdf(objects: dict[int, bytes], *, root: int = 1) -> bytes:
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num, body in objects.items():
        offsets[num] = len(result)
        result.extend(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(result)
    size = max(objects) + 1
    result.extend(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
    for num in range(1, size):
        result.extend(f"{offsets.get(num, 0):010d} 00000 {'n' if num in offsets else 'f'} \n".encode())
    result.extend(f"trailer\n<< /Size {size} /Root {root} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


def cmap(mapping: dict[bytes, str], *, compressed: bool = False) -> bytes:
    widths = sorted({len(code) for code in mapping})
    spaces = b"\n".join(b"<" + b"00" * width + b"> <" + b"FF" * width + b">" for width in widths)
    pairs = b"\n".join(b"<" + code.hex().encode() + b"> <" + value.encode("utf-16-be").hex().encode() + b">" for code, value in mapping.items())
    data = b"begincmap\n" + str(len(widths)).encode() + b" begincodespacerange\n" + spaces + b"\nendcodespacerange\n"
    data += str(len(mapping)).encode() + b" beginbfchar\n" + pairs + b"\nendbfchar\nendcmap"
    return stream(data, compressed=compressed)


def page(contents: bytes = b"4 0 R", resources: bytes = b"<< /Font << /Body 5 0 R >> >>", parent: int = 2) -> bytes:
    return b"<< /Type /Page /Parent " + str(parent).encode() + b" 0 R /MediaBox [0 0 200 300] /Resources " + resources + b" /Contents " + contents + b" >>"


def simple_document(content: bytes = b"BT /Body 12 Tf (Sample) Tj ET") -> dict[int, bytes]:
    return {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: page(), 4: stream(content),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }


class PDFSourceIntegrityTests(unittest.TestCase):
    def text(self, objects: dict[int, bytes]) -> list[str]:
        return [unit["text"] for unit in read_manuscript(pdf(objects), "fixture.pdf")["units"]]

    def assert_rejected(self, objects: dict[int, bytes]) -> None:
        with self.assertRaises(ContractError) as cm:
            read_manuscript(pdf(objects), "fixture.pdf")
        self.assertIn(cm.exception.code, {"invalid_source", "unsupported_format", "too_large"})

    def test_distinct_font_maps_switch_within_text_object_and_restore_graphics_state(self):
        objects = simple_document(b"BT /Body 12 Tf (Estimate=) Tj <51> Tj /Note 9 Tf <51> Tj ET q BT /Body 12 Tf <51> Tj ET Q BT <51> Tj ET")
        objects[3] = page(resources=b"<< /Font << /Body 5 0 R /Note 6 0 R >> >>")
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [81 /four] >> /ToUnicode 7 0 R >>"
        objects[6] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [81 /seven] >> /ToUnicode 8 0 R >>"
        objects[7] = cmap({b"Q": "4"}, compressed=True)
        objects[8] = cmap({b"Q": "7"})
        self.assertEqual(self.text(objects), ["Estimate=47", "4", "7"])

    def test_page_resources_inherit_indirect_fonts_and_local_override(self):
        objects = simple_document(b"BT /Body 12 Tf <52> Tj ET")
        objects[2] = b"<< /Type /Pages /Kids [3 0 R 9 0 R] /Count 2 /Resources 10 0 R >>"
        objects[3] = b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>"
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [82 /two] >> /ToUnicode 7 0 R >>"
        objects[6] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [82 /eight] >> /ToUnicode 8 0 R >>"
        objects[7] = cmap({b"R": "2"})
        objects[8] = cmap({b"R": "8"})
        objects[9] = page(resources=b"<< /Font << /Body 6 0 R >> >>")
        objects[10] = b"<< /Font 11 0 R >>"
        objects[11] = b"<< /Body 5 0 R >>"
        self.assertEqual(self.text(objects), ["2", "8"])

    def test_content_array_keeps_selected_font_and_order(self):
        objects = simple_document(b"BT /Body 12 Tf (left) Tj")
        objects[3] = page(contents=b"[4 0 R 6 0 R]")
        objects[6] = stream(b"(right) Tj ET")
        self.assertEqual(self.text(objects), ["leftright"])

    def test_type0_multibyte_glyphs_and_unicode_ligatures(self):
        objects = simple_document(b"BT /Body 12 Tf <00a100b2> Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type0 /Encoding /Identity-H /ToUnicode 6 0 R >>"
        objects[6] = cmap({b"\x00\xa1": "\u03b2", b"\x00\xb2": "fi"})
        self.assertEqual(self.text(objects), ["\u03b2fi"])

    def test_cmap_range_targets_and_array_targets_remain_font_local(self):
        objects = simple_document(b"BT /Body 12 Tf <e0e1e2e3> Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>"
        objects[6] = stream(b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 2 beginbfrange <e0> <e1> <0036> <e2> <e3> [<03bb> <00660069>] endbfrange endcmap")
        self.assertEqual(self.text(objects), ["67\u03bbfi"])

    def test_stream_length_can_be_indirect_and_text_can_contain_object_keywords(self):
        data = b"BT /Body 12 Tf (endobj endstream /Type /Page) Tj ET"
        objects = simple_document()
        objects[4] = b"<< /Length 6 0 R >>\nstream\n" + data + b"\nendstream"
        objects[6] = str(len(data)).encode()
        self.assertEqual(self.text(objects), ["endobj endstream /Type /Page"])

    def test_conflicting_cmap_ambiguous_codespace_and_bad_ranges_are_rejected(self):
        data = [
            b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 2 beginbfchar <51> <0031> <51> <0032> endbfchar endcmap",
            b"begincmap 2 begincodespacerange <00> <ff> <0000> <ffff> endcodespacerange 2 beginbfchar <51> <0031> <5151> <0032> endbfchar endcmap",
            b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 1 beginbfrange <51> <53> [<0031>] endbfrange endcmap",
            b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 1 beginbfchar <51> <d800> endbfchar endcmap",
        ]
        for data_stream in data:
            with self.subTest(data=data_stream):
                objects = simple_document(b"BT /Body 12 Tf <5151> Tj ET")
                objects[5] = b"<< /Type /Font /Subtype /Type0 /Encoding /Identity-H /ToUnicode 6 0 R >>"
                objects[6] = stream(data_stream)
                self.assert_rejected(objects)

    def test_xref_integrity_is_checked_and_incremental_revision_rejected(self):
        raw = pdf(simple_document())
        for corrupt in (raw.replace(b"0000000015 00000 n", b"0000000016 00000 n"), raw.replace(b"/Size 6", b"/Prev 1 /Size 6")):
            self.assertNotEqual(corrupt, raw)
            with self.assertRaises(ContractError):
                read_manuscript(corrupt, "corrupt.pdf")

    def test_legacy_resource_less_and_unselected_text_structures_are_rejected(self):
        # Explicitly retain the rejected old fixture shapes; never guess /F1 or
        # apply the only CMap globally to a text object with no Tf.
        objects = simple_document()
        objects[3] = b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>"
        self.assert_rejected(objects)
        objects = simple_document(b"BT <51> Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>"
        objects[6] = cmap({b"Q": "5"})
        self.assert_rejected(objects)

    def test_invalid_parent_and_cyclic_resource_reference_are_rejected(self):
        objects = simple_document()
        objects[3] = page(parent=88)
        self.assert_rejected(objects)
        objects[3] = page(resources=b"6 0 R")
        objects[6] = b"7 0 R"
        objects[7] = b"6 0 R"
        self.assert_rejected(objects)

    def test_named_or_inline_actualtext_is_rejected_instead_of_claiming_complete(self):
        for operator in (b"BDC", b"DP"):
            with self.subTest(operator=operator):
                objects = simple_document(b"/Span /Replacement " + operator + b" BT /Body 12 Tf (Shown) Tj ET EMC")
                objects[3] = page(resources=b"<< /Font << /Body 5 0 R >> /Properties 6 0 R >>")
                objects[6] = b"<< /Replacement 7 0 R >>"
                objects[7] = b"<< /ActualText (Different source words) >>"
                self.assert_rejected(objects)
        self.assert_rejected(simple_document(b"/Span << /ActualText (Different) >> BDC BT /Body 12 Tf (Shown) Tj ET EMC"))

    def test_external_graphics_state_font_replacement_is_explicitly_rejected(self):
        objects = simple_document(b"BT /Body 12 Tf /Switch gs (Q) Tj ET")
        objects[3] = page(resources=b"<< /Font << /Body 5 0 R >> /ExtGState << /Switch 6 0 R >> >>")
        objects[6] = b"<< /Font [7 0 R 10] >>"
        objects[7] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [81 /six] >> >>"
        self.assert_rejected(objects)

    def test_non_replacing_named_properties_do_not_hide_text(self):
        objects = simple_document(b"/Span /Mark BDC BT /Body 12 Tf (Named content) Tj ET EMC")
        objects[3] = page(resources=b"<< /Font << /Body 5 0 R >> /Properties << /Mark << /MCID 0 >> >> >>")
        self.assertEqual(self.text(objects), ["Named content"])

    def test_cmap_comments_and_literal_strings_cannot_inject_mappings(self):
        objects = simple_document(b"BT /Body 12 Tf (XY) Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>"
        objects[6] = stream(b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange\n% 1 beginbfchar <58> <0039> endbfchar\n/Decoy (1 beginbfchar <59> <0030> endbfchar) def 1 beginbfchar <5a> <0038> endbfchar endcmap")
        self.assertEqual(self.text(objects), ["XY"])

    def test_unreferenced_cmap_cannot_rewrite_page_text(self):
        objects = simple_document(b"BT /Body 12 Tf (CODE) Tj ET")
        objects[8] = cmap({b"C": "9", b"O": "8", b"D": "7", b"E": "6"})
        self.assertEqual(self.text(objects), ["CODE"])

    def test_encoding_differences_apply_without_tounicode(self):
        objects = simple_document(b"BT /Body 12 Tf (AQB) Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [81 /five] >> >>"
        self.assertEqual(self.text(objects), ["A5B"])

    def test_font_resource_names_decode_pdf_name_escapes(self):
        objects = simple_document(b"BT /Bo#64y 12 Tf (Escaped) Tj ET")
        self.assertEqual(self.text(objects), ["Escaped"])

    def test_unknown_selected_font_or_no_selection_is_rejected(self):
        for content in (b"BT /Missing 12 Tf (123) Tj ET", b"BT (123) Tj ET"):
            with self.subTest(content=content):
                self.assert_rejected(simple_document(content))

    def test_missing_resources_do_not_invent_standard_font(self):
        objects = simple_document()
        objects[3] = b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>"
        self.assert_rejected(objects)

    def test_unmapped_composite_code_and_unknown_encoding_are_rejected(self):
        objects = simple_document(b"BT /Body 12 Tf <0042> Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type0 /Encoding /Identity-H /ToUnicode 6 0 R >>"
        objects[6] = cmap({b"\x00\x41": "3"})
        self.assert_rejected(objects)
        objects[5] = b"<< /Type /Font /Subtype /TrueType /Encoding /CustomUnknown >>"
        self.assert_rejected(objects)

    def test_unknown_differences_and_broken_cmap_do_not_fallback_to_ascii(self):
        objects = simple_document(b"BT /Body 12 Tf (Q) Tj ET")
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [81 /unknownGlyph] >> >>"
        self.assert_rejected(objects)
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 99 0 R >>"
        self.assert_rejected(objects)

    def test_font_state_does_not_leak_between_pages(self):
        objects = simple_document()
        objects[2] = b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>"
        objects[6] = page(contents=b"7 0 R")
        objects[7] = stream(b"BT (No selection on this page) Tj ET")
        self.assert_rejected(objects)

    def test_catalog_page_tree_nested_order_ignores_physical_order_and_orphans(self):
        objects = simple_document(b"BT /Body 12 Tf (Third) Tj ET")
        objects[2] = b"<< /Type /Pages /Kids [6 0 R 3 0 R] /Count 3 >>"
        objects[6] = b"<< /Type /Pages /Parent 2 0 R /Kids [10 0 R 8 0 R] /Count 2 >>"
        objects[8] = page(contents=b"9 0 R", parent=6)
        objects[9] = stream(b"BT /Body 12 Tf (Second) Tj ET")
        objects[10] = page(contents=b"11 0 R", parent=6)
        objects[11] = stream(b"BT /Body 12 Tf (First) Tj ET")
        objects[12] = page(contents=b"13 0 R")
        objects[13] = stream(b"BT /Body 12 Tf (Orphan) Tj ET")
        doc = read_manuscript(pdf(objects), "nested.pdf")
        self.assertEqual([(u["text"], u["location"]) for u in doc["units"]], [("First", "pdf:p1:L1"), ("Second", "pdf:p2:L1"), ("Third", "pdf:p3:L1")])

    def test_nested_page_tree_inherits_nearest_resources(self):
        objects = simple_document()
        objects[2] = b"<< /Type /Pages /Kids [6 0 R] /Count 1 /Resources << /Font << /Unused 99 0 R >> >> >>"
        objects[6] = b"<< /Type /Pages /Parent 2 0 R /Kids [3 0 R] /Count 1 /Resources << /Font << /Body 5 0 R >> >> >>"
        objects[3] = b"<< /Type /Page /Parent 6 0 R /Contents 4 0 R >>"
        self.assertEqual(self.text(objects), ["Sample"])

    def test_empty_page_keeps_following_page_number(self):
        objects = simple_document()
        objects[2] = b"<< /Type /Pages /Kids [6 0 R 3 0 R] /Count 2 >>"
        objects[6] = b"<< /Type /Page /Parent 2 0 R >>"
        doc = read_manuscript(pdf(objects), "blank.pdf")
        self.assertEqual(doc["units"][0]["location"], "pdf:p2:L1")
        self.assertEqual(doc["read_status"], "partial")

    def test_page_tree_cycle_duplicate_missing_and_count_mismatch_are_rejected(self):
        for kids, count in ((b"[2 0 R]", 1), (b"[3 0 R 3 0 R]", 2), (b"[77 0 R]", 1), (b"[3 0 R]", 2)):
            with self.subTest(kids=kids, count=count):
                objects = simple_document()
                objects[2] = b"<< /Type /Pages /Kids " + kids + b" /Count " + str(count).encode() + b" >>"
                self.assert_rejected(objects)

    def test_missing_catalog_pages_or_content_cannot_use_object_order_fallback(self):
        for mutation in ("catalog", "pages", "content", "generation"):
            with self.subTest(mutation=mutation):
                objects = simple_document()
                if mutation == "catalog": objects[1] = b"<< /Producer (No catalog) >>"
                elif mutation == "pages": objects[1] = b"<< /Type /Catalog /Pages 99 0 R >>"
                elif mutation == "content": objects[3] = page(contents=b"99 0 R")
                else: objects[1] = b"<< /Type /Catalog /Pages 2 1 R >>"
                self.assert_rejected(objects)

    def test_public_quote_uses_font_and_page_binding(self):
        objects = simple_document(b"BT /Body 12 Tf (Result = ) Tj <56> Tj ET")
        objects[2] = b"<< /Type /Pages /Kids [8 0 R 3 0 R] /Count 2 >>"
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /BaseEncoding /WinAnsiEncoding /Differences [86 /six] >> /ToUnicode 6 0 R >>"
        objects[6] = cmap({b"V": "6"})
        objects[7] = cmap({b"V": "2"})
        objects[8] = page(contents=b"9 0 R")
        objects[9] = stream(b"BT /Body 12 Tf (Cover) Tj ET")
        with tempfile.TemporaryDirectory(prefix="parrhesia-pdf-source-") as tmp:
            root = Path(tmp)
            (root / "source.pdf").write_bytes(pdf(objects))
            engine = Engine(root)
            result = engine.dispatch("draft_manuscript", {"path": "source.pdf", "selections": [{"quote": "Result = 6", "location": "pdf:p2:L1"}]})
            self.assertEqual(result["source_map"][0]["quote"], "Result = 6")
            for quote, location in (("Result = 2", "pdf:p2:L1"), ("Result = 6", "pdf:p1:L1")):
                with self.subTest(quote=quote, location=location), self.assertRaises(ContractError):
                    engine.dispatch("draft_manuscript", {"path": "source.pdf", "selections": [{"quote": quote, "location": location}]})


if __name__ == "__main__":
    unittest.main()
