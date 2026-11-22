"""Bounded stdlib PDF extraction with explicit page and font bindings.

Only conventional, non-incremental xref tables and directly readable objects are
supported. Unsupported structure/encoding is rejected rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import zlib

from .contracts import fail

MAX_PDF_DECOMPRESSED_BYTES = 8 * 1024 * 1024
_MAX_OBJECTS = 10000
_MAX_DEPTH = 64
_WS = b"\x00\t\n\f\r "
_DELIMS = _WS + b"()<>[]{}/%"


def _integer(raw: bytes) -> int:
    if len(raw) > 128:
        fail("too_large", "PDF integer exceeds reader limit")
    return int(raw)


class _Name(str):
    pass


class _Word(str):
    pass


@dataclass(frozen=True)
class _Ref:
    number: int
    generation: int


@dataclass
class _Object:
    value: object
    stream: bytes | None = None


class _Reader:
    """Small PDF value lexer; names, strings and indirect refs stay distinct."""
    def __init__(self, data: bytes, pos: int = 0):
        self.data, self.pos = data, pos

    def skip(self) -> None:
        while self.pos < len(self.data):
            if self.data[self.pos] in _WS:
                self.pos += 1
            elif self.data[self.pos] == 37:
                while self.pos < len(self.data) and self.data[self.pos] not in (10, 13):
                    self.pos += 1
            else:
                break

    def word(self) -> bytes:
        self.skip()
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos] not in _DELIMS:
            self.pos += 1
        if start == self.pos:
            fail("invalid_source", "Malformed PDF token")
        return self.data[start:self.pos]

    def value(self, depth: int = 0) -> object:
        if depth > _MAX_DEPTH:
            fail("too_large", "PDF value nesting exceeds reader limit")
        self.skip()
        data, pos = self.data, self.pos
        if pos >= len(data):
            fail("invalid_source", "Truncated PDF value")
        if data[pos:pos + 2] == b"<<":
            self.pos += 2
            result = {}
            while True:
                self.skip()
                if data[self.pos:self.pos + 2] == b">>":
                    self.pos += 2
                    return result
                key = self.value(depth + 1)
                if not isinstance(key, _Name) or key in result:
                    fail("invalid_source", "Invalid or duplicate PDF dictionary key")
                result[key] = self.value(depth + 1)
        if data[pos] == 91:
            self.pos += 1
            result = []
            while True:
                self.skip()
                if self.pos < len(data) and data[self.pos] == 93:
                    self.pos += 1
                    return result
                result.append(self.value(depth + 1))
        if data[pos] == 47:
            self.pos += 1
            start = self.pos
            while self.pos < len(data) and data[self.pos] not in _DELIMS:
                self.pos += 1
            raw = data[start:self.pos]
            if re.search(rb"#(?![0-9a-fA-F]{2})", raw):
                fail("invalid_source", "Invalid PDF name escape")
            return _Name(re.sub(rb"#([0-9a-fA-F]{2})", lambda m: bytes([int(m[1], 16)]), raw).decode("latin1"))
        if data[pos] == 40:
            self.pos += 1
            nesting, out = 1, bytearray()
            while self.pos < len(data):
                ch = data[self.pos]
                self.pos += 1
                if ch == 92:
                    if self.pos == len(data):
                        break
                    ch = data[self.pos]
                    self.pos += 1
                    if ch in (10, 13):
                        if ch == 13 and data[self.pos:self.pos + 1] == b"\n":
                            self.pos += 1
                    elif 48 <= ch <= 55:
                        digits = bytes([ch])
                        while len(digits) < 3 and self.pos < len(data) and 48 <= data[self.pos] <= 55:
                            digits += data[self.pos:self.pos + 1]
                            self.pos += 1
                        out.append(int(digits, 8) & 255)
                    else:
                        out.append({110: 10, 114: 13, 116: 9, 98: 8, 102: 12}.get(ch, ch))
                elif ch == 40:
                    nesting += 1
                    if nesting > _MAX_DEPTH:
                        fail("too_large", "PDF literal nesting exceeds reader limit")
                    out.append(ch)
                elif ch == 41:
                    nesting -= 1
                    if nesting == 0:
                        return bytes(out)
                    out.append(ch)
                else:
                    # PDF normalizes literal-string line endings.
                    if ch == 13:
                        if data[self.pos:self.pos + 1] == b"\n":
                            self.pos += 1
                        ch = 10
                    out.append(ch)
            fail("invalid_source", "Unterminated PDF string")
        if data[pos] == 60:
            end = data.find(b">", pos + 1)
            if end < 0:
                fail("invalid_source", "Unterminated PDF hex string")
            raw = re.sub(rb"\s+", b"", data[pos + 1:end])
            self.pos = end + 1
            try:
                return bytes.fromhex((raw + (b"0" if len(raw) % 2 else b"")).decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                fail("invalid_source", "Invalid PDF hex string")
        ref = re.match(rb"(\d+)\s+(\d+)\s+R(?=$|[\s<>()\[\]/%])", data[pos:])
        if ref:
            self.pos += ref.end()
            return _Ref(_integer(ref[1]), _integer(ref[2]))
        token = self.word()
        if len(token) > 128 and token[:1] in b"+-0123456789.":
            fail("too_large", "PDF numeric token exceeds reader limit")
        if re.fullmatch(rb"[+-]?\d+", token):
            return _integer(token)
        if re.fullmatch(rb"[+-]?(?:\d*\.\d+|\d+\.\d*)", token):
            return float(token)
        if token in (b"true", b"false", b"null"):
            return {b"true": True, b"false": False, b"null": None}[token]
        if depth:
            fail("invalid_source", "Unexpected PDF keyword inside a composite value")
        return _Word(token.decode("latin1"))


def _load_objects(content: bytes) -> tuple[dict[_Ref, _Object], _Ref]:
    if not content.startswith(b"%PDF-"):
        fail("invalid_source", "Invalid PDF header")
    reader = _Reader(content)
    objects, positions, lengths = {}, {}, []
    trailer, xref_pos, xref_entries, saw_startxref = None, None, {}, False
    while True:
        reader.skip()
        if reader.pos >= len(content):
            break
        start = reader.pos
        if content.startswith(b"xref", start):
            if xref_pos is not None:
                fail("unsupported_format", "Incremental PDF xref sections are not supported")
            xref_pos = start
            reader.pos += 4
            while True:
                reader.skip()
                if content.startswith(b"trailer", reader.pos):
                    reader.pos += 7
                    trailer = reader.value()
                    break
                first, count = reader.word(), reader.word()
                if not first.isdigit() or not count.isdigit() or _integer(count) > _MAX_OBJECTS + 1:
                    fail("invalid_source", "Invalid PDF xref subsection")
                for number in range(_integer(first), _integer(first) + _integer(count)):
                    offset, generation, flag = reader.word(), reader.word(), reader.word()
                    if not offset.isdigit() or not generation.isdigit() or flag not in (b"n", b"f"):
                        fail("invalid_source", "Invalid PDF xref entry")
                    if number in xref_entries:
                        fail("invalid_source", "Duplicate PDF xref entry")
                    xref_entries[number] = (_integer(offset), _integer(generation), flag)
                    if len(xref_entries) > _MAX_OBJECTS + 1:
                        fail("too_large", "PDF object count exceeds reader limit")
            continue
        if content.startswith(b"startxref", start):
            saw_startxref = True
            reader.pos += 9
            offset = reader.word()
            if not offset.isdigit() or _integer(offset) != xref_pos:
                fail("invalid_source", "PDF startxref does not identify the parsed xref table")
            reader.skip()
            if reader.pos != len(content):
                fail("unsupported_format", "Incremental or trailing PDF objects are not supported")
            break
        header = re.match(rb"(\d+)\s+(\d+)\s+obj\b", content[start:])
        if not header:
            fail("unsupported_format", "PDF requires conventional objects and an xref table")
        reader.pos += header.end()
        ref = _Ref(_integer(header[1]), _integer(header[2]))
        if ref in objects or len(objects) >= _MAX_OBJECTS:
            fail("unsupported_format", "Duplicate or excessive PDF objects are not supported")
        value = reader.value()
        if isinstance(value, dict) and "Encrypt" in value:
            fail("invalid_source", "Encrypted PDFs are not supported; decrypt or export to text first")
        reader.skip()
        payload = None
        if content.startswith(b"stream", reader.pos):
            if not isinstance(value, dict):
                fail("invalid_source", "PDF stream has no dictionary")
            reader.pos += 6
            eol = re.match(rb"[ \t]*(?:\r\n|\r|\n)", content[reader.pos:])
            if not eol:
                fail("invalid_source", "PDF stream has no line boundary")
            reader.pos += eol.end()
            length = value.get("Length")
            if isinstance(length, _Ref):
                # A forward scalar length is permitted, then checked against the
                # actual object/xref after parsing; ambiguous matches are rejected.
                pattern = rb"(?m)^" + str(length.number).encode() + rb"\s+" + str(length.generation).encode() + rb"\s+obj\s+(\d+)\s+endobj\b"
                matches = re.findall(pattern, content)
                if len(matches) != 1:
                    fail("unsupported_format", "Cannot resolve PDF stream length unambiguously")
                lengths.append((length, _integer(matches[0])))
                length = _integer(matches[0])
            if type(length) is not int or length < 0 or reader.pos + length > len(content):
                fail("invalid_source", "Invalid PDF stream length")
            payload = content[reader.pos:reader.pos + length]
            reader.pos += length
            if reader.word() != b"endstream":
                fail("invalid_source", "PDF stream length does not match endstream")
        if reader.word() != b"endobj":
            fail("invalid_source", "Invalid PDF object boundary")
        objects[ref], positions[ref] = _Object(value, payload), start
        if isinstance(value, dict) and value.get("Type") in (_Name("ObjStm"), _Name("XRef")):
            fail("unsupported_format", "PDF object streams and xref streams are not supported")
    if not saw_startxref or not isinstance(trailer, dict) or not isinstance(trailer.get("Root"), _Ref):
        fail("unsupported_format", "PDF has no unambiguous trailer Catalog root")
    if "Encrypt" in trailer or any(isinstance(o.value, dict) and "Encrypt" in o.value for o in objects.values()):
        fail("invalid_source", "Encrypted PDFs are not supported; decrypt or export to text first")
    if "Prev" in trailer or "XRefStm" in trailer:
        fail("unsupported_format", "Incremental and hybrid PDF xrefs are not supported")
    active = {}
    for number, (offset, generation, flag) in xref_entries.items():
        if flag == b"n":
            ref = _Ref(number, generation)
            if positions.get(ref) != offset:
                fail("invalid_source", "PDF xref offset/generation does not match its object")
            active[ref] = objects[ref]
    for ref, length in lengths:
        if ref not in active or type(active[ref].value) is not int or active[ref].value != length:
            fail("invalid_source", "PDF indirect stream length is not a valid active object")
    return active, trailer["Root"]


class _Document:
    def __init__(self, objects: dict[_Ref, _Object]):
        self.objects = objects
        self.decoded: dict[_Ref, bytes] = {}
        self.decoded_size = 0

    def resolve(self, value: object) -> object:
        seen = set()
        while isinstance(value, _Ref):
            if value in seen or len(seen) > _MAX_DEPTH or value not in self.objects:
                fail("invalid_source", "Missing or cyclic PDF object reference")
            seen.add(value)
            value = self.objects[value].value
        return value

    def dictionary(self, value: object) -> dict:
        result = self.resolve(value)
        if not isinstance(result, dict):
            fail("invalid_source", "Expected a PDF dictionary")
        return result

    def stream(self, ref: object) -> bytes:
        if not isinstance(ref, _Ref) or ref not in self.objects or self.objects[ref].stream is None:
            fail("invalid_source", "Missing PDF content or ToUnicode stream")
        if ref in self.decoded:
            return self.decoded[ref]
        obj = self.objects[ref]
        data = obj.stream
        filters = self.resolve(obj.value.get("Filter"))
        filters = [] if filters is None else filters if isinstance(filters, list) else [filters]
        if obj.value.get("DecodeParms") is not None:
            fail("unsupported_format", "PDF stream DecodeParms are not supported")
        for flt in filters:
            if flt not in (_Name("FlateDecode"), _Name("Fl")):
                fail("unsupported_format", f"PDF stream filter /{flt} is not supported")
            try:
                dec = zlib.decompressobj()
                data = dec.decompress(data, MAX_PDF_DECOMPRESSED_BYTES + 1)
                if len(data) > MAX_PDF_DECOMPRESSED_BYTES or dec.unconsumed_tail:
                    fail("too_large", "Decompressed PDF stream exceeds 8 MiB limit")
                if not dec.eof or dec.unused_data:
                    fail("invalid_source", "Incomplete or trailing FlateDecode stream")
            except zlib.error:
                fail("invalid_source", "Corrupt FlateDecode PDF stream")
        self.decoded_size += len(data)
        if self.decoded_size > MAX_PDF_DECOMPRESSED_BYTES:
            fail("too_large", "Decoded PDF streams exceed the total 8 MiB reader limit")
        self.decoded[ref] = data
        return data


def _unicode(raw: bytes) -> str:
    if len(raw) > 4096:
        fail("too_large", "PDF ToUnicode replacement exceeds reader limit")
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        fail("unsupported_format", "PDF ToUnicode contains invalid UTF-16")


def _parse_tounicode_cmap(data: bytes) -> tuple[dict[bytes, str], list[tuple[bytes, bytes]]]:
    # Tokenize CMap data as PDF/PostScript values so comments and literal strings
    # cannot inject apparent mapping blocks into the selected font.
    reader, mapping, spaces, operands = _Reader(data), {}, [], []
    mapping_characters = 0
    blocks = {"begincodespacerange": "endcodespacerange", "beginbfchar": "endbfchar", "beginbfrange": "endbfrange"}

    def code() -> bytes:
        value = reader.value()
        if not isinstance(value, bytes) or not value:
            fail("invalid_source", "PDF CMap requires nonempty character-code strings")
        return value

    def add(source: bytes, target: bytes) -> None:
        nonlocal mapping_characters
        value = _unicode(target)
        if not value:
            fail("unsupported_format", "Empty PDF ToUnicode replacement is not supported")
        if source in mapping and mapping[source] != value:
            fail("invalid_source", "Conflicting entries in a font ToUnicode CMap")
        if source not in mapping:
            mapping_characters += len(value)
        if mapping_characters > 1000000:
            fail("too_large", "PDF ToUnicode text exceeds reader limit")
        mapping[source] = value
        if len(mapping) > 65536:
            fail("too_large", "PDF ToUnicode mapping exceeds reader limit")

    while True:
        reader.skip()
        if reader.pos >= len(data):
            break
        token = reader.value()
        if not isinstance(token, _Word):
            operands.append(token)
            continue
        if token in ("usecmap", "if", "ifelse", "for", "repeat", "exec", "run") or token.startswith(("begincid", "beginnotdef")):
            fail("unsupported_format", "Inherited or executable PDF CMaps are not supported")
        if token in blocks:
            if not operands or type(operands[-1]) is not int or not 0 <= operands[-1] <= 65536:
                fail("invalid_source", "Invalid PDF CMap block count")
            for _ in range(operands[-1]):
                first, second = code(), code()
                if token == "beginbfchar":
                    add(first, second)
                elif token == "begincodespacerange":
                    if not 1 <= len(first) <= 4 or len(first) != len(second) or first > second:
                        fail("unsupported_format", "Invalid PDF CMap codespace range")
                    spaces.append((first, second))
                    if len(spaces) > 256:
                        fail("too_large", "PDF CMap codespace count exceeds reader limit")
                else:
                    lo, hi = int.from_bytes(first, "big"), int.from_bytes(second, "big")
                    if len(first) != len(second) or hi < lo or hi - lo > 65535:
                        fail("unsupported_format", "PDF ToUnicode range exceeds supported bounds")
                    destination = reader.value()
                    if isinstance(destination, bytes) and destination:
                        if len(destination) > 4096:
                            fail("too_large", "PDF ToUnicode replacement exceeds reader limit")
                        base = int.from_bytes(destination, "big")
                        if base + hi - lo >= 256 ** len(destination):
                            fail("invalid_source", "PDF ToUnicode destination range overflows")
                        targets = ((base + i).to_bytes(len(destination), "big") for i in range(hi - lo + 1))
                    elif isinstance(destination, list) and len(destination) == hi - lo + 1 and all(isinstance(item, bytes) and item for item in destination):
                        targets = destination
                    else:
                        fail("invalid_source", "PDF ToUnicode range destination has the wrong type or size")
                    for number, target in zip(range(lo, hi + 1), targets):
                        add(number.to_bytes(len(first), "big"), target)
            end = reader.value()
            if not isinstance(end, _Word) or end != blocks[token]:
                fail("invalid_source", "PDF CMap block count/terminator mismatch")
        operands.clear()
    if not spaces or not mapping:
        fail("unsupported_format", "PDF ToUnicode requires explicit codespaces and character mappings")
    if any(not any(len(code) == len(lo) and lo <= code <= hi for lo, hi in spaces) for code in mapping):
        fail("invalid_source", "PDF ToUnicode mapping lies outside its codespace")
    return mapping, spaces


_GLYPHS = dict(zip("zero one two three four five six seven eight nine".split(), "0123456789"))
_GLYPHS.update({"space": " ", "period": ".", "comma": ",", "colon": ":", "semicolon": ";", "hyphen": "-", "minus": "\u2212", "plus": "+", "equal": "=", "percent": "%", "parenleft": "(", "parenright": ")", "slash": "/", "quotedbl": '"', "quotesingle": "'", "quoteright": "\u2019", "quoteleft": "\u2018"})
_STANDARD_FONTS = {"Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique", "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic", "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"}


def _glyph(name: _Name) -> str:
    if name in _GLYPHS:
        return _GLYPHS[name]
    if len(name) == 1 and name.isascii() and name.isalpha():
        return str(name)
    if re.fullmatch(r"uni(?:[0-9A-Fa-f]{4})+", name):
        return _unicode(bytes.fromhex(name[3:]))
    if re.fullmatch(r"u[0-9A-Fa-f]{4,6}", name):
        number = int(name[1:], 16)
        if number <= 0x10FFFF and not 0xD800 <= number <= 0xDFFF:
            return chr(number)
    fail("unsupported_format", f"PDF glyph /{name} has no supported Unicode mapping")


class _Font:
    def __init__(self, document: _Document, font: dict):
        self.mapping, self.spaces = {}, []
        subtype = font.get("Subtype")
        if subtype not in (_Name("Type0"), _Name("Type1"), _Name("TrueType")):
            fail("unsupported_format", f"PDF font subtype /{subtype} is not supported")
        self.composite = subtype == _Name("Type0")
        if "ToUnicode" in font:
            ref = font["ToUnicode"]
            cmap_dict = document.dictionary(ref)
            if "UseCMap" in cmap_dict:
                fail("unsupported_format", "Inherited PDF ToUnicode CMaps are not supported")
            self.mapping, self.spaces = _parse_tounicode_cmap(document.stream(ref))
            if not self.composite and any(len(lo) != 1 for lo, _ in self.spaces):
                fail("invalid_source", "Simple PDF fonts require one-byte character codes")
        if self.composite and not self.mapping:
            fail("unsupported_format", "Composite PDF fonts require a supported ToUnicode CMap")
        self.encoding, self.differences = None, {}
        if self.composite:
            return
        encoding = document.resolve(font.get("Encoding"))
        if isinstance(encoding, dict):
            differences = document.resolve(encoding.get("Differences", []))
            if not isinstance(differences, list):
                fail("invalid_source", "Invalid PDF font Differences array")
            index = None
            for item in differences:
                if type(item) is int and 0 <= item <= 255:
                    index = item
                elif isinstance(item, _Name) and index is not None and index <= 255:
                    self.differences[index] = item
                    index += 1
                else:
                    fail("invalid_source", "Invalid PDF font Differences entry")
            encoding = encoding.get("BaseEncoding")
        if encoding is None and font.get("BaseFont") in _STANDARD_FONTS:
            encoding = _Name("StandardEncoding")
        if encoding in (_Name("WinAnsiEncoding"), _Name("MacRomanEncoding"), _Name("StandardEncoding")):
            self.encoding = encoding
        elif encoding is not None:
            fail("unsupported_format", f"PDF font encoding /{encoding} is not supported")

    def decode(self, raw: bytes) -> str:
        result, pos = [], 0
        while pos < len(raw):
            if self.composite:
                choices = {len(lo) for lo, hi in self.spaces if len(raw[pos:pos + len(lo)]) == len(lo) and lo <= raw[pos:pos + len(lo)] <= hi}
                if len(choices) != 1:
                    fail("unsupported_format", "Ambiguous or unmapped PDF character codespace")
                width = choices.pop()
            else:
                width = 1
            code = raw[pos:pos + width]
            pos += width
            if code in self.mapping:
                result.append(self.mapping[code])
            elif self.composite:
                fail("unsupported_format", "PDF character has no ToUnicode mapping")
            elif code[0] in self.differences:
                result.append(_glyph(self.differences[code[0]]))
            elif self.encoding == "StandardEncoding" and 32 <= code[0] <= 126:
                result.append({39: "\u2019", 96: "\u2018"}.get(code[0], chr(code[0])))
            elif self.encoding in ("WinAnsiEncoding", "MacRomanEncoding") and code[0] >= 32:
                try:
                    result.append(code.decode("cp1252" if self.encoding == "WinAnsiEncoding" else "mac_roman"))
                except UnicodeDecodeError:
                    fail("unsupported_format", "Undefined PDF font character code")
            else:
                fail("unsupported_format", "PDF character encoding cannot be established")
        return "".join(result)


def _page_tree(document: _Document, root: _Ref) -> list[tuple[dict, object]]:
    catalog = document.dictionary(root)
    if catalog.get("Type") != _Name("Catalog") or not isinstance(catalog.get("Pages"), _Ref):
        fail("invalid_source", "PDF trailer root is not a Catalog with a Pages reference")
    pages, seen = [], set()

    def walk(ref: object, parent: _Ref | None, resources: object, depth: int) -> int:
        if depth > _MAX_DEPTH:
            fail("too_large", "PDF page tree exceeds maximum depth")
        if not isinstance(ref, _Ref) or ref in seen:
            fail("invalid_source", "PDF page tree has a cycle, duplicate, or invalid child")
        seen.add(ref)
        node = document.dictionary(ref)
        if parent is not None and node.get("Parent") != parent:
            fail("invalid_source", "PDF page tree Parent does not match Kids traversal")
        if "Resources" in node:
            resources = node["Resources"]
        if node.get("Type") == _Name("Page"):
            pages.append((node, resources))
            return 1
        if node.get("Type") != _Name("Pages"):
            fail("invalid_source", "PDF page tree child is neither Page nor Pages")
        kids = document.resolve(node.get("Kids"))
        if not isinstance(kids, list):
            fail("invalid_source", "PDF Pages node has no valid Kids array")
        count = sum(walk(child, ref, resources, depth + 1) for child in kids)
        if type(node.get("Count")) is not int or node["Count"] != count:
            fail("invalid_source", "PDF Pages Count does not match its descendant pages")
        return count

    walk(catalog["Pages"], None, None, 0)
    return pages


def _extract_text(data: bytes, document: _Document, resources: object, omitted: list[str], page_number: int) -> list[str]:
    reader, lines, current, operands = _Reader(data), [], [], []
    selected, in_text, stack, font_cache = None, False, [], {}
    fonts = None

    def flush() -> None:
        text = "".join(current).strip()
        current.clear()
        if text:
            lines.append(text)

    def show(raw: object) -> None:
        if selected is None or not isinstance(raw, bytes):
            fail("unsupported_format", "PDF text requires an explicitly selected, resolvable font")
        current.append(selected.decode(raw))

    while True:
        reader.skip()
        if reader.pos >= len(data):
            break
        token = reader.value()
        if not isinstance(token, _Word):
            if isinstance(token, dict) and "ActualText" in token:
                fail("unsupported_format", "PDF ActualText replacement is not supported")
            operands.append(token)
            continue
        if token == "BT":
            if in_text:
                fail("invalid_source", "Nested PDF text objects")
            in_text = True
        elif token == "ET":
            if not in_text:
                fail("invalid_source", "PDF ET without BT")
            in_text = False
            flush()
        elif token == "q":
            stack.append(selected)
            if len(stack) > _MAX_DEPTH:
                fail("too_large", "PDF graphics state exceeds maximum depth")
        elif token == "Q":
            if not stack:
                fail("invalid_source", "Unbalanced PDF graphics state")
            selected = stack.pop()
        elif token == "Tf":
            if not in_text or len(operands) != 2 or not isinstance(operands[0], _Name) or type(operands[1]) not in (int, float):
                fail("invalid_source", "Invalid PDF Tf font selection")
            if fonts is None:
                fonts = document.dictionary(document.dictionary(resources).get("Font"))
            name = operands[0]
            if name not in fonts:
                fail("unsupported_format", f"Selected PDF font /{name} is absent from page resources")
            if name not in font_cache:
                font_cache[name] = _Font(document, document.dictionary(fonts[name]))
            selected = font_cache[name]
        elif token in ("BDC", "DP"):
            if len(operands) != 2 or not isinstance(operands[0], _Name):
                fail("invalid_source", "Invalid PDF marked-content properties")
            properties = operands[1]
            if isinstance(properties, _Name):
                declared = document.dictionary(document.dictionary(resources).get("Properties"))
                if properties not in declared:
                    fail("invalid_source", "Missing named PDF marked-content properties")
                properties = document.dictionary(declared[properties])
            if not isinstance(properties, dict):
                fail("invalid_source", "Invalid PDF marked-content property dictionary")
            if "ActualText" in properties:
                fail("unsupported_format", "PDF ActualText replacement is not supported")
        elif token == "gs":
            if len(operands) != 1 or not isinstance(operands[0], _Name):
                fail("invalid_source", "Invalid PDF external graphics-state selection")
            states = document.dictionary(document.dictionary(resources).get("ExtGState"))
            if operands[0] not in states:
                fail("invalid_source", "Missing PDF external graphics state")
            if "Font" in document.dictionary(states[operands[0]]):
                fail("unsupported_format", "PDF external graphics-state font replacement is not supported")
        elif token in ("Tj", "TJ", "'", '"'):
            if not in_text:
                fail("invalid_source", "PDF text operator occurs outside BT/ET")
            if token in ("'", '"'):
                flush()
            if not operands:
                fail("invalid_source", "PDF text operator has no operand")
            if token == "TJ":
                if not isinstance(operands[-1], list):
                    fail("invalid_source", "PDF TJ requires an array")
                for item in operands[-1]:
                    if isinstance(item, bytes):
                        show(item)
                    elif type(item) in (int, float):
                        if item < -180:
                            current.append(" ")
                    else:
                        fail("invalid_source", "Unsupported PDF TJ array member")
            else:
                show(operands[-1])
        elif in_text and token in ("T*", "Td", "TD", "Tm"):
            if token in ("T*", "Tm"):
                flush()
            elif len(operands) == 2 and all(type(x) in (int, float) for x in operands):
                if abs(operands[-1]) > 1:
                    flush()
                elif operands[-2] > 2:
                    current.append(" ")
        elif token == "BI":
            fail("unsupported_format", "PDF inline image content is not supported")
        elif token == "Do":
            name = operands[-1] if operands else "UNKNOWN"
            omitted.append(f"PDF page {page_number} XObject /{name} (not decoded; no OCR/form traversal)")
        operands.clear()
    if in_text or stack:
        fail("invalid_source", "Unterminated PDF text or graphics state")
    flush()
    return lines


def extract_pdf(content: bytes) -> tuple[list[dict], list[str]]:
    """Read Catalog/Kids page order and Tf-selected page/inherited font resources."""
    objects, root = _load_objects(content)
    document = _Document(objects)
    omitted, units = [], []
    for page_number, (page, resources) in enumerate(_page_tree(document, root), 1):
        contents = page.get("Contents")
        if contents is None:
            streams = []
        elif isinstance(contents, _Ref) and objects.get(contents) is not None and objects[contents].stream is not None:
            streams = [contents]
        else:
            streams = document.resolve(contents)
            if not isinstance(streams, list):
                fail("invalid_source", "PDF page Contents is not a stream or stream array")
        # A Contents array is one logical content stream. Preserve font/text state
        # across its boundaries, while resetting state at every page boundary.
        parts = [document.stream(ref) for ref in streams]
        if sum(len(part) for part in parts) > MAX_PDF_DECOMPRESSED_BYTES:
            fail("too_large", "PDF page content exceeds the 8 MiB reader limit")
        lines = _extract_text(b"\n".join(parts), document, resources, omitted, page_number)
        if not lines:
            omitted.append(f"PDF page {page_number} (no extractable text)")
        for line_number, text in enumerate(lines, 1):
            units.append({"text": text, "location": f"pdf:p{page_number}:L{line_number}"})
    if not units:
        fail("unsupported_format", "PDF yielded no readable text within the supported page/font scope")
    return units, list(dict.fromkeys(omitted))
