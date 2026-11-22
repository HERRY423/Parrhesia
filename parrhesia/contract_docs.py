"""Read-only, source-bound navigation of bundled Markdown contracts (stdlib only)."""
from __future__ import annotations

import hashlib
import re

from .contracts import fail, ids


_HEADING = re.compile(r"^(#{2,4})[ \t]+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def contract_sections(text: str) -> list[dict]:
    """Index complete ATX sections, excluding headings inside fenced code.

    Parent sections include their children. Each non-overlapping section's body
    can instead be read using its own ID from this index. IDs are document-local,
    so callers may bind a follow-up read to the source digest returned by index.
    """
    lines = text.splitlines(keepends=True)
    headings = []
    fence_char, fence_length = "", 0
    for index, line in enumerate(lines):
        fence = _FENCE.match(line)
        if fence:
            marker, suffix = fence.groups()
            if not fence_char:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length and not suffix.strip():
                fence_char, fence_length = "", 0
            continue
        if fence_char:
            continue
        heading = _HEADING.match(line)
        if heading:
            headings.append((index, len(heading[1]), heading[2]))

    sections = []
    used = {"index", "full"}
    for pos, (start, depth, title) in enumerate(headings):
        base = re.sub(r"[^a-z0-9_]+", "-", title.lower()).strip("-") or "section"
        section_id, suffix = base, 2
        while section_id in used:
            section_id = f"{base}-{suffix}"
            suffix += 1
        used.add(section_id)
        end = next((i for i, d, _ in headings[pos + 1:] if d <= depth), len(lines))
        sections.append({
            "id": section_id, "title": title, "depth": depth,
            "start_line": start + 1, "end_line": end,
            "bytes": len("".join(lines[start:end]).encode("utf-8")),
        })
    return sections


def select_contract(text: str, section: str, expected_sha256: str | None = None) -> dict:
    """Return full text, an index, or an exact section; never silently truncate."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        fail("contract_changed", "Contract changed since the index was read; read section='index' again.")
    metadata = {"section": section, "source_sha256": digest,
                "source_bytes": len(text.encode("utf-8")), "complete_document": section == "full"}
    if section == "full":
        body = text
    else:
        sections = contract_sections(text)
        if section == "index":
            body = (
                "Contract section index (not the complete contract). Read only the relevant IDs below.\n"
                "Read lifecycle before mutations and current anti-stall gates before reviews/adjudication; "
                "legacy examples do not replace v2 input schemas. Parent sections include their children.\n"
                "Use expected_sha256 to bind later reads to this document; section='full' returns all text.\n\n"
                "| ID | Heading | Lines | UTF-8 bytes |\n|---|---|---|---:|\n"
                + "\n".join(
                    f"| {s['id']} | {s['title'].replace('|', '/')} | {s['start_line']}-{s['end_line']} | {s['bytes']} |"
                    for s in sections
                ) + "\n"
            )
        else:
            selected = next((s for s in sections if s["id"] == section), None)
            if selected is None:
                fail("unknown_contract_section", "Unknown contract section; read section='index' for current IDs.")
            metadata.update({key: selected[key] for key in ("start_line", "end_line", "title")})
            body = "".join(text.splitlines(keepends=True)[selected["start_line"] - 1:selected["end_line"]])
    metadata["returned_bytes"] = len(body.encode("utf-8"))
    return {"contract": body, "selection": metadata}


def select_contract_batch(text: str, sections: list[str], expected_sha256: str | None = None) -> dict:
    """Fetch several exact sections in one call, removing overlapping line ranges."""
    names = ids(sections, "sections", minimum=1, maximum=8)
    if any(name in ("index", "full") for name in names):
        fail("invalid_value", "Batch reads require exact section IDs, not index/full")
    parts = [select_contract(text, name, expected_sha256)["selection"] for name in names]
    lines = text.splitlines(keepends=True)
    # Source order, each line once, including parent/child overlaps.
    included = sorted({i for part in parts for i in range(part["start_line"] - 1, part["end_line"])})
    groups = []
    for index in included:
        if not groups or index != groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(index)
    body = "\n\n".join("".join(lines[i] for i in group) for group in groups)
    return {"contract": body, "selection": {
        "sections": parts, "source_sha256": parts[0]["source_sha256"],
        "source_bytes": parts[0]["source_bytes"], "returned_bytes": len(body.encode("utf-8")),
        "complete_document": False,
    }}
