"""Conservative project-local Grok adapter; never changes ~/.grok or calls a model."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

OWNER = "parrhesia-project-adapter-v1"
BEGIN = "<!-- parrhesia:managed:start -->"
END = "<!-- parrhesia:managed:end -->"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def contained(root: Path, relative: str) -> Path:
    destination = root / relative
    if not destination.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes the selected project: {relative}")
    # Do not follow reparse points, including a link that currently stays inside root.
    current = destination
    while current != root:
        attributes = getattr(current.lstat(), "st_file_attributes", 0) if current.exists() else 0
        if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError(f"Refusing linked installation path: {relative}")
        current = current.parent
    return destination


def collect_package(source: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    package = source / "parrhesia"
    skill = source / "skills" / "parrhesia-review"
    required = [package / "__main__.py", skill / "SKILL.md", source / "plugin.json", source / "mcp.json", source / "scripts" / "run-mcp.py", source / "docs" / "contract.md"]
    for item in required:
        if not item.is_file():
            raise ValueError(f"Incomplete plugin: missing {item.relative_to(source)}")
    inputs = list(package.rglob("*.py")) + [source / "plugin.json", source / "mcp.json", source / "scripts" / "run-mcp.py", source / "docs" / "contract.md"]
    for item in inputs:
        if not item.resolve().is_relative_to(source):
            raise ValueError("Package includes a path outside its root.")
        result[f".grok/parrhesia/runtime/{item.relative_to(source).as_posix()}"] = item.read_bytes()
    for item in skill.rglob("*"):
        if not item.is_file():
            continue
        if not item.resolve().is_relative_to(source):
            raise ValueError("Skill includes a path outside the package root.")
        result[f".grok/skills/parrhesia-review/{item.relative_to(skill).as_posix()}"] = item.read_bytes()
    return result


def install(source: Path, project: Path, *, skip_agents: bool = False) -> dict:
    source, project = source.resolve(), project.resolve()
    if not project.is_dir():
        raise ValueError("Select an existing project directory.")
    owner_relative = ".grok/parrhesia/installation.json"
    owner_path = contained(project, owner_relative)
    old = json.loads(owner_path.read_text(encoding="utf-8")) if owner_path.exists() else None
    if old is not None and (not isinstance(old, dict) or old.get("owner") != OWNER or old.get("project") != str(project)):
        raise ValueError("Existing installation metadata belongs to another owner or project.")
    if old is None and owner_path.parent.exists() and any(owner_path.parent.iterdir()):
        raise ValueError("Existing .grok/parrhesia directory is unmanaged; choose a clean location or reconcile it manually.")
    payloads = collect_package(source)
    old_files = old.get("files", {}) if old else {}
    if not isinstance(old_files, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in old_files.items()):
        raise ValueError("Installation file ownership metadata is malformed.")
    for relative, expected in old_files.items():
        existing = contained(project, relative)
        if not existing.is_file() or digest(existing.read_bytes()) != expected:
            raise ValueError(f"An installed file was changed or removed: {relative}. Preserve/reconcile it before updating.")
    for relative, data in payloads.items():
        existing = contained(project, relative)
        if existing.exists() and relative not in old_files:
            raise ValueError(f"Refusing to replace unmanaged file: {relative}")
    mcp_path = contained(project, ".mcp.json")
    mcp = json.loads(mcp_path.read_text(encoding="utf-8-sig")) if mcp_path.exists() else {}
    if not isinstance(mcp, dict) or not isinstance(mcp.get("mcpServers", {}), dict):
        raise ValueError("Existing .mcp.json is not a supported JSON object.")
    servers = mcp.setdefault("mcpServers", {})
    if "parrhesia" in servers and (not old or servers["parrhesia"] != old.get("mcp_server")):
        raise ValueError("The existing parrhesia MCP server is unmanaged or modified; no files were changed.")
    server = {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(project / ".grok" / "parrhesia" / "runtime" / "scripts" / "run-mcp.py"), "--workspace", str(project)],
    }
    servers["parrhesia"] = server
    payloads[".mcp.json"] = encoded(mcp)
    agents_block = old.get("agents_block") if old else None
    if agents_block is not None and not isinstance(agents_block, str):
        raise ValueError("Installation AGENTS block metadata is malformed.")
    if not skip_agents:
        template = source / "templates" / "AGENTS.parrhesia.md"
        if not template.is_file():
            raise ValueError("Missing templates/AGENTS.parrhesia.md; use the complete package.")
        agents_path = contained(project, "AGENTS.md")
        original = agents_path.read_text(encoding="utf-8-sig") if agents_path.exists() else ""
        if (BEGIN in original or END in original) and (not agents_block or original.count(agents_block) != 1):
            raise ValueError("The AGENTS.md Parrhesia block is unmanaged or modified; no files were changed.")
        new_block = BEGIN + "\n" + template.read_text(encoding="utf-8").strip() + "\n" + END
        if agents_block:
            if original.count(agents_block) != 1:
                raise ValueError("The installed AGENTS.md block was removed or changed.")
            updated = original.replace(agents_block, new_block, 1)
        else:
            updated = original + ("\n\n" if original and not original.endswith("\n\n") else "") + new_block + "\n"
        agents_block = new_block
        payloads["AGENTS.md"] = updated.encode("utf-8")
    files = dict(old_files)
    files.update({key: digest(data) for key, data in payloads.items() if key not in {".mcp.json", "AGENTS.md"}})
    metadata = {
        "owner": OWNER,
        "project": str(project),
        "plugin_version": json.loads((source / "plugin.json").read_text(encoding="utf-8"))["version"],
        "files": files,
        "mcp_server": server,
        "agents_block": agents_block,
    }
    payloads[owner_relative] = encoded(metadata)
    changes = {relative: data for relative, data in payloads.items() if not contained(project, relative).is_file() or contained(project, relative).read_bytes() != data}
    if not changes:
        return {"status": "unchanged", "scope": "project", "project": str(project), "changed_files": [], "model_calls": 0, "activation": "Grok must trust this project before loading its skill, AGENTS.md and local MCP. This installer does not grant trust."}
    backup_relative = ".grok/parrhesia/backups/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    previous: dict[str, bytes | None] = {}
    # Complete conflict/containment checks above before any mutation.
    for relative in changes:
        target = contained(project, relative)
        previous[relative] = target.read_bytes() if target.is_file() else None
        if previous[relative] is not None:
            backup = contained(project, f"{backup_relative}/{relative}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(previous[relative])
    applied: list[str] = []
    try:
        for relative, data in changes.items():
            target = contained(project, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".parrhesia-" + uuid.uuid4().hex + ".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, target)
            applied.append(relative)
    except Exception:
        for relative in reversed(applied):
            target = contained(project, relative)
            if previous[relative] is None:
                target.unlink()
            else:
                target.write_bytes(previous[relative])
        raise
    return {"status": "installed", "scope": "project", "project": str(project), "changed_files": list(changes), "backup_directory": backup_relative if any(value is not None for value in previous.values()) else None, "model_calls": 0, "activation": "Grok must trust this project before loading its skill, AGENTS.md and local MCP. This installer does not grant trust."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--source", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--skip-agents", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required.")
    try:
        result = install(Path(args.source), Path(args.project), skip_agents=args.skip_agents)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Parrhesia installation stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
