"""Non-blocking Antigravity lifecycle hook for Parrhesia workspace status checks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from typing import Any

MAX_STDIN_BYTES = 1_048_576


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _read_stdin_payload() -> dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    except Exception:
        return {}
    if not raw or len(raw) > MAX_STDIN_BYTES:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_workspace(explicit: str | None, payload: dict[str, Any]) -> Path | None:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for key in ("workspacePaths", "workspace_paths"):
        raw = payload.get(key)
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str) and entry.strip():
                    candidates.append(entry)
    for item in candidates:
        path = Path(item).expanduser()
        if _is_link(path) or not path.is_dir():
            continue
        return path.resolve()
    return None


def _inspect_workspace_cases(workspace: Path) -> tuple[int, dict[str, Any] | None]:
    state_dir = workspace / ".parrhesia"
    db_path = state_dir / "state.sqlite3"
    if _is_link(state_dir) or _is_link(db_path) or not db_path.is_file():
        return 0, None
    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=0.5)
    except sqlite3.Error:
        return 0, None
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cases'"
        ).fetchone()
        if row is None:
            return 0, None
        total = int(conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0])
        if total <= 0:
            return 0, None
        latest_row = None
        events_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if events_table is not None:
            latest_row = conn.execute(
                "SELECT c.id, c.document FROM events e "
                "JOIN cases c ON c.id = e.case_id "
                "ORDER BY e.sequence DESC, e.rowid DESC LIMIT 1"
            ).fetchone()
        if latest_row is None:
            latest_row = conn.execute(
                "SELECT id, document FROM cases ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return 0, None
    finally:
        conn.close()

    if latest_row is None:
        return 0, None
    case_id, raw_doc = latest_row
    try:
        doc = json.loads(raw_doc)
    except (TypeError, json.JSONDecodeError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    claims = doc.get("claims")
    return total, {
        "case_id": str(doc.get("case_id") or case_id),
        "state": str(doc.get("state") or "unknown"),
        "claims_count": len(claims) if isinstance(claims, list) else 0,
        "blind": doc.get("blind"),
    }


def handle_event(event: str, payload: dict[str, Any], *, workspace_arg: str | None = None) -> dict[str, Any]:
    """Process one Antigravity hook event cleanly and deterministically."""
    if event != "SessionStart":
        return {}
    workspace = _resolve_workspace(workspace_arg, payload)
    if workspace is None:
        return {}
    total, latest = _inspect_workspace_cases(workspace)
    if total <= 0 or latest is None:
        return {}
    blind_note = f", blind={latest['blind']}" if isinstance(latest.get("blind"), bool) else ""
    message = (
        f"Parrhesia workspace status: {total} case(s) in .parrhesia/state.sqlite3 "
        f"(active: {latest['case_id']}, state={latest['state']}, claims={latest['claims_count']}{blind_note}). "
        f"Inspect read-only resource parrhesia://cases/{latest['case_id']} or call MCP "
        "parrhesia_get_case / parrhesia_verify before finalizing L2 verdicts."
    )
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": message,
                }
            }
        ]
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="SessionStart", help="Antigravity hook event name.")
    parser.add_argument("--workspace", default=None, help="Optional explicit project workspace directory.")
    args = parser.parse_args(argv)
    payload = _read_stdin_payload()
    response = handle_event(args.event, payload, workspace_arg=args.workspace)
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
