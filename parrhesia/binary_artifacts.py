"""Bounded, pure-stdlib readers for multi-sheet .xlsx workbooks and Apache Parquet metadata."""
from __future__ import annotations

import io
import re
import struct
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from .contracts import fail

MAX_BINARY_XML_BYTES = 8 * 1024 * 1024
MAX_PARQUET_FOOTER_BYTES = 8 * 1024 * 1024
MAX_THRIFT_ITEMS = 20_000
MAX_THRIFT_DEPTH = 16

_PARQUET_TYPES = {
    0: "BOOLEAN",
    1: "INT32",
    2: "INT64",
    3: "INT96",
    4: "FLOAT",
    5: "DOUBLE",
    6: "BYTE_ARRAY",
    7: "FIXED_LEN_BYTE_ARRAY",
}
_PARQUET_REPETITION = {0: "REQUIRED", 1: "OPTIONAL", 2: "REPEATED"}

_CELL_REF_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _safe_xml_bytes(content: bytes) -> ET.Element:
    if b"\x00" in content:
        fail("invalid_source", "XML reader accepts UTF-8 only, not NUL-bearing content")
    upper = content[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        fail("invalid_source", "XML document types and entities are not supported")
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        fail("invalid_source", f"Malformed XML: {exc}")


def _col_to_idx(letters: str) -> int:
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _read_zip_member_capped(archive: zipfile.ZipFile, name: str, budget: list[int]) -> bytes:
    info = archive.getinfo(name)
    if info.file_size < 0 or info.file_size > MAX_BINARY_XML_BYTES or budget[0] + info.file_size > MAX_BINARY_XML_BYTES:
        fail("too_large", "XLSX uncompressed XML exceeds 8 MiB limit")
    data = archive.read(info)
    if len(data) > MAX_BINARY_XML_BYTES or budget[0] + len(data) > MAX_BINARY_XML_BYTES:
        fail("too_large", "XLSX uncompressed XML exceeds 8 MiB limit")
    budget[0] += len(data)
    return data


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_sheet_rows(root: ET.Element, shared_strings: list[str]) -> tuple[list[tuple[int, list[str]]], bool]:
    rows_out: list[tuple[int, list[str]]] = []
    saw_formula = False
    for row_el in root.iter():
        if _local_name(row_el.tag) != "row":
            continue
        r_attr = row_el.attrib.get("r")
        row_num = int(r_attr) if r_attr and r_attr.isdigit() else (len(rows_out) + 1)
        cells: dict[int, str] = {}
        next_col = 0
        for cell_el in row_el:
            if _local_name(cell_el.tag) != "c":
                continue
            ref = cell_el.attrib.get("r") or ""
            m = _CELL_REF_RE.match(ref)
            col_idx = _col_to_idx(m.group(1)) if m else next_col
            if m and int(m.group(2)) > 0:
                row_num = int(m.group(2))
            next_col = col_idx + 1
            ctype = cell_el.attrib.get("t", "")
            val_text: str | None = None
            has_f = False
            for child in cell_el:
                cname = _local_name(child.tag)
                if cname == "f":
                    has_f = True
                elif cname == "v" and val_text is None:
                    val_text = child.text or ""
                elif cname == "is" and ctype == "inlineStr":
                    val_text = "".join(t.text or "" for t in child.iter() if _local_name(t.tag) == "t")
            if has_f:
                saw_formula = True
            if ctype == "s" and val_text is not None:
                try:
                    val = shared_strings[int(val_text)]
                except (ValueError, IndexError):
                    fail("invalid_source", f"Invalid XLSX shared string index {val_text!r}")
            elif ctype == "b" and val_text is not None:
                val = "true" if val_text.strip() in ("1", "true", "TRUE") else "false"
            else:
                val = val_text if val_text is not None else ""
            if val != "":
                cells[col_idx] = val.strip()
        if cells:
            width = max(cells) + 1
            row_vals = [cells.get(i, "") for i in range(width)]
            rows_out.append((row_num, row_vals))
    return rows_out, saw_formula


def list_xlsx_sheets(content: bytes, *, sheet_name: str | None = None) -> dict[str, Any]:
    """Parse sheets from an XLSX workbook cleanly in pure stdlib."""
    if len(content) > MAX_BINARY_XML_BYTES:
        fail("too_large", "XLSX workbook exceeds 8 MiB limit")
    budget = [0]
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names:
                fail("invalid_source", "XLSX archive is missing xl/workbook.xml")
            wb_root = _safe_xml_bytes(_read_zip_member_capped(archive, "xl/workbook.xml", budget))
            rel_targets: dict[str, str] = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rels_root = _safe_xml_bytes(_read_zip_member_capped(archive, "xl/_rels/workbook.xml.rels", budget))
                for rel in rels_root:
                    if _local_name(rel.tag) != "Relationship":
                        continue
                    rid = rel.attrib.get("Id")
                    target = rel.attrib.get("Target") or ""
                    if rid and target and "://" not in target and ".." not in target.replace("\\", "/").split("/"):
                        norm = target.lstrip("/")
                        if not norm.startswith("xl/"):
                            norm = "xl/" + norm
                        rel_targets[rid] = norm

            sheets_meta: list[tuple[str, str]] = []
            for el in wb_root.iter():
                if _local_name(el.tag) != "sheet":
                    continue
                sname = el.attrib.get("name")
                if not sname:
                    continue
                rid = next((v for k, v in el.attrib.items() if _local_name(k) == "id"), None)
                target_path = rel_targets.get(rid or "")
                if target_path and target_path in names:
                    sheets_meta.append((sname, target_path))
                else:
                    fallback_idx = len(sheets_meta) + 1
                    candidate = f"xl/worksheets/sheet{fallback_idx}.xml"
                    if candidate in names:
                        sheets_meta.append((sname, candidate))
            if not sheets_meta:
                fail("invalid_source", "XLSX workbook contains no readable worksheets")

            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                ss_root = _safe_xml_bytes(_read_zip_member_capped(archive, "xl/sharedStrings.xml", budget))
                for si in ss_root:
                    if _local_name(si.tag) == "si":
                        shared_strings.append("".join(t.text or "" for t in si.iter() if _local_name(t.tag) == "t"))

            sheet_names = [name for name, _ in sheets_meta]
            if sheet_name is not None:
                selected_pair = next(((n, p) for n, p in sheets_meta if n == sheet_name), None)
                if selected_pair is None:
                    fail("invalid_value", f"XLSX sheet {sheet_name!r} not found; available sheets: {sheet_names}")
                target_sheets = [selected_pair]
            else:
                target_sheets = sheets_meta

            parsed_sheets: dict[str, dict[str, Any]] = {}
            for sname, spath in target_sheets:
                s_root = _safe_xml_bytes(_read_zip_member_capped(archive, spath, budget))
                raw_rows, has_formulas = _parse_sheet_rows(s_root, shared_strings)
                if not raw_rows:
                    parsed_sheets[sname] = {"header": [], "rows": [], "formula_cached_values": has_formulas}
                    continue
                header_row_num, raw_header = raw_rows[0]
                header = [h.strip() for h in raw_header]
                if len(header) < 2 or not all(header) or len(set(h.casefold() for h in header)) != len(header):
                    parsed_sheets[sname] = {"header": header, "rows": [], "formula_cached_values": has_formulas, "header_row": header_row_num}
                    continue
                data_rows: list[tuple[dict[str, str], str]] = []
                for row_num, vals in raw_rows[1:]:
                    padded = vals + [""] * max(0, len(header) - len(vals))
                    if len(vals) > len(header):
                        fail("invalid_source", f"XLSX table width mismatch at {sname}!R{row_num}")
                    data_rows.append((dict(zip(header, padded)), f"{sname}!R{row_num}"))
                parsed_sheets[sname] = {
                    "header": header,
                    "rows": data_rows,
                    "formula_cached_values": has_formulas,
                    "header_row": header_row_num,
                }
            return {"sheet_names": sheet_names, "sheets": parsed_sheets}
    except (zipfile.BadZipFile, RuntimeError) as exc:
        fail("invalid_source", f"Cannot read XLSX: {exc}")


class _ThriftCompactReader:
    """Bounded Apache Thrift TCompactProtocol reader for Parquet FileMetaData."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.ops = 0

    def _tick(self) -> None:
        self.ops += 1
        if self.ops > MAX_THRIFT_ITEMS:
            fail("too_large", "Parquet metadata exceeds bounded Thrift element cap")

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            fail("invalid_source", "Truncated Parquet Thrift metadata")
        val = self.data[self.pos]
        self.pos += 1
        return val

    def read_varint(self) -> int:
        shift = 0
        result = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result
            shift += 7
            if shift > 64:
                fail("invalid_source", "Parquet Thrift varint overflow")

    def read_zigzag(self) -> int:
        n = self.read_varint()
        return (n >> 1) ^ -(n & 1)

    def read_binary(self) -> bytes:
        length = self.read_varint()
        if length < 0 or self.pos + length > len(self.data):
            fail("invalid_source", "Invalid Parquet Thrift string length")
        out = self.data[self.pos:self.pos + length]
        self.pos += length
        return out

    def skip_field(self, ftype: int, depth: int = 0) -> None:
        self._tick()
        if depth > MAX_THRIFT_DEPTH:
            fail("invalid_source", "Parquet Thrift nesting depth exceeded")
        if ftype in (1, 2):  # BOOL true/false
            return
        if ftype == 3:  # BYTE
            self.read_byte()
        elif ftype in (4, 5, 6):  # I16/I32/I64
            self.read_varint()
        elif ftype == 7:  # DOUBLE
            if self.pos + 8 > len(self.data):
                fail("invalid_source", "Truncated Thrift double")
            self.pos += 8
        elif ftype == 8:  # BINARY
            self.read_binary()
        elif ftype in (9, 10):  # LIST / SET
            head = self.read_byte()
            size = (head >> 4) & 0x0F
            if size == 15:
                size = self.read_varint()
            elem_type = head & 0x0F
            if size > MAX_THRIFT_ITEMS:
                fail("too_large", "Parquet Thrift container too large")
            for _ in range(size):
                self.skip_field(elem_type, depth + 1)
        elif ftype == 11:  # MAP
            size = self.read_varint()
            if size == 0:
                return
            if size > MAX_THRIFT_ITEMS:
                fail("too_large", "Parquet Thrift map too large")
            kv = self.read_byte()
            ktype, vtype = (kv >> 4) & 0x0F, kv & 0x0F
            for _ in range(size):
                self.skip_field(ktype, depth + 1)
                self.skip_field(vtype, depth + 1)
        elif ftype == 12:  # STRUCT
            last_id = 0
            while True:
                fid, ft = self.read_field_header(last_id)
                if ft == 0:
                    break
                last_id = fid
                self.skip_field(ft, depth + 1)
        else:
            fail("invalid_source", f"Unsupported Thrift compact wire type {ftype}")

    def read_field_header(self, last_id: int) -> tuple[int, int]:
        self._tick()
        b = self.read_byte()
        if b == 0:
            return 0, 0
        delta = (b >> 4) & 0x0F
        ftype = b & 0x0F
        fid = self.read_zigzag() if delta == 0 else last_id + delta
        return fid, ftype


def inspect_parquet_metadata(content: bytes) -> dict[str, Any]:
    """Read Parquet PAR1 magic and Thrift FileMetaData without deserializing data pages."""
    if len(content) < 12 or content[:4] != b"PAR1" or content[-4:] != b"PAR1":
        fail("invalid_source", "Parquet file requires leading and trailing PAR1 magic bytes")
    footer_len = struct.unpack("<I", content[-8:-4])[0]
    if footer_len <= 0 or footer_len > len(content) - 12 or footer_len > MAX_PARQUET_FOOTER_BYTES:
        fail("invalid_source", "Invalid Parquet footer length")
    footer = content[-8 - footer_len:-8]
    reader = _ThriftCompactReader(footer)

    version: int | None = None
    num_rows: int | None = None
    schema_cols: list[dict[str, Any]] = []
    row_group_count = 0
    created_by: str | None = None

    last_id = 0
    while True:
        fid, ftype = reader.read_field_header(last_id)
        if ftype == 0:
            break
        last_id = fid
        if fid == 1 and ftype == 5:
            version = reader.read_zigzag()
        elif fid == 2 and ftype == 9:
            head = reader.read_byte()
            size = (head >> 4) & 0x0F
            if size == 15:
                size = reader.read_varint()
            elem_type = head & 0x0F
            if elem_type != 12 or size > MAX_THRIFT_ITEMS:
                fail("invalid_source", "Malformed Parquet schema list")
            for _ in range(size):
                col: dict[str, Any] = {}
                s_last = 0
                while True:
                    sfid, sft = reader.read_field_header(s_last)
                    if sft == 0:
                        break
                    s_last = sfid
                    if sfid == 1 and sft == 5:
                        ptype = reader.read_zigzag()
                        col["type"] = _PARQUET_TYPES.get(ptype, f"TYPE_{ptype}")
                    elif sfid == 3 and sft == 5:
                        rep = reader.read_zigzag()
                        col["repetition"] = _PARQUET_REPETITION.get(rep, f"REP_{rep}")
                    elif sfid == 4 and sft == 8:
                        col["name"] = reader.read_binary().decode("utf-8", "replace")
                    elif sfid == 5 and sft == 5:
                        col["num_children"] = reader.read_zigzag()
                    else:
                        reader.skip_field(sft, 1)
                if "name" in col:
                    schema_cols.append(col)
        elif fid == 3 and ftype == 6:
            num_rows = reader.read_zigzag()
        elif fid == 4 and ftype == 9:
            head = reader.read_byte()
            row_group_count = (head >> 4) & 0x0F
            if row_group_count == 15:
                row_group_count = reader.read_varint()
            elem_type = head & 0x0F
            for _ in range(row_group_count):
                reader.skip_field(elem_type, 1)
        elif fid == 6 and ftype == 8:
            created_by = reader.read_binary().decode("utf-8", "replace")
        else:
            reader.skip_field(ftype, 0)

    if version is None or num_rows is None or num_rows < 0 or not schema_cols:
        fail("invalid_source", "Parquet footer lacks required FileMetaData (version, schema, num_rows)")
    leaf_columns = [c for c in schema_cols if "num_children" not in c and c.get("name") != "schema"]
    return {
        "format_version": version,
        "num_rows": num_rows,
        "row_group_count": row_group_count,
        "column_count": len(leaf_columns),
        "columns": leaf_columns[:200],
        "created_by": created_by,
        "data_content_verified": False,
    }
