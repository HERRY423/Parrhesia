"""Conservative project-local Grok adapter; never changes ~/.grok or calls a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parrhesia.adapters import (  # noqa: E402
    BEGIN,
    END,
    POLICY_MODES,
    SKILL_NAMES,
    check_owned_files,
    collect_runtime_payloads,
    collect_skills_payloads,
    commit_transaction,
    contained,
    encode_json,
    load_policy_body,
    merge_managed_block,
    read_plugin_version,
    reject_link,
    remove_managed_block,
    resolve_python_executable,
    sha256_bytes,
    validate_old_ownership,
)

OWNER = "parrhesia-project-adapter-v1"
OWNER_RELATIVE = ".grok/parrhesia/installation.json"
BACKUP_PREFIX = ".grok/parrhesia/backups"
ACTIVATION_NOTE = (
    "Grok must trust this project before loading its skills, AGENTS.md and local MCP. "
    "This installer does not grant trust or mutate ~/.grok."
)


def collect_package(source: Path) -> dict[str, bytes]:
    """Collect self-contained runtime modules and both curated skills for Grok."""
    source = source.resolve()
    result = collect_runtime_payloads(source, ".grok/parrhesia/runtime")
    result.update(collect_skills_payloads(source, ".grok/skills", SKILL_NAMES))
    return result


def _load_installation(project: Path) -> tuple[Path, dict | None]:
    owner_path = contained(project, OWNER_RELATIVE)
    if not owner_path.exists():
        return owner_path, None
    return owner_path, json.loads(owner_path.read_text(encoding="utf-8"))


def _build_mcp_server(project: Path, python_exe: str) -> dict:
    return {
        "type": "stdio",
        "command": python_exe,
        "args": [str(project / ".grok" / "parrhesia" / "runtime" / "scripts" / "run-mcp.py"), "--workspace", str(project)],
    }


def _cleanup_mcp(project: Path, expected_server: dict | None) -> tuple[bytes | None, bool]:
    mcp_path = contained(project, ".mcp.json")
    if not mcp_path.exists():
        return None, False
    mcp = json.loads(mcp_path.read_text(encoding="utf-8-sig"))
    if not isinstance(mcp, dict) or not isinstance(mcp.get("mcpServers", {}), dict):
        raise ValueError("Existing .mcp.json is not a supported JSON object.")
    servers = mcp.get("mcpServers", {})
    if "parrhesia" not in servers:
        return None, False
    if expected_server is not None and servers["parrhesia"] != expected_server:
        raise ValueError("The existing parrhesia MCP server is unmanaged or modified; no files were changed.")
    del servers["parrhesia"]
    if not servers:
        mcp.pop("mcpServers", None)
    if not mcp:
        return None, True
    return encode_json(mcp), False


def install(
    source: Path,
    project: Path,
    *,
    skip_agents: bool = False,
    policy_mode: str = "compact",
    python_executable: str | None = None,
) -> dict:
    """Install or safely update the project-local Grok adapter."""
    if policy_mode not in POLICY_MODES:
        raise ValueError(f"Unsupported policy mode {policy_mode!r}; expected one of {POLICY_MODES}.")
    raw_source = Path(source)
    raw_project = Path(project)
    reject_link(raw_project)
    source = raw_source.resolve()
    project = raw_project.resolve()
    if not project.is_dir():
        raise ValueError("Select an existing project directory.")

    version = read_plugin_version(source)
    resolved_python = resolve_python_executable(python_executable)
    _, old = _load_installation(project)
    payloads = collect_package(source)

    old_files, obsolete_files = validate_old_ownership(
        project, old, OWNER, "project", payloads, ".grok/parrhesia"
    )

    mcp_path = contained(project, ".mcp.json")
    mcp = json.loads(mcp_path.read_text(encoding="utf-8-sig")) if mcp_path.exists() else {}
    if not isinstance(mcp, dict) or not isinstance(mcp.get("mcpServers", {}), dict):
        raise ValueError("Existing .mcp.json is not a supported JSON object.")
    servers = mcp.setdefault("mcpServers", {})
    if "parrhesia" in servers and (not old or servers["parrhesia"] != old.get("mcp_server")):
        raise ValueError("The existing parrhesia MCP server is unmanaged or modified; no files were changed.")
    server = _build_mcp_server(project, resolved_python)
    servers["parrhesia"] = server
    payloads[".mcp.json"] = encode_json(mcp)

    old_agents_block = old.get("agents_block") if old else None
    if old_agents_block is not None and not isinstance(old_agents_block, str):
        raise ValueError("Installation AGENTS block metadata is malformed.")

    remove_list = list(obsolete_files)
    agents_block: str | None = None
    if not skip_agents:
        body = load_policy_body(source, policy_mode)
        agents_path = contained(project, "AGENTS.md")
        original = agents_path.read_text(encoding="utf-8-sig") if agents_path.exists() else ""
        updated, agents_block = merge_managed_block(original, body, old_agents_block, begin=BEGIN, end=END)
        payloads["AGENTS.md"] = updated.encode("utf-8")
    elif old_agents_block:
        agents_path = contained(project, "AGENTS.md")
        if not agents_path.is_file():
            raise ValueError("The installed AGENTS.md block was removed or changed.")
        remaining = remove_managed_block(agents_path.read_text(encoding="utf-8-sig"), old_agents_block, begin=BEGIN, end=END)
        if remaining is None:
            remove_list.append("AGENTS.md")
        else:
            payloads["AGENTS.md"] = remaining.encode("utf-8")

    tracked_files = {
        key: sha256_bytes(data)
        for key, data in payloads.items()
        if key not in {".mcp.json", "AGENTS.md"}
    }
    metadata = {
        "owner": OWNER,
        "adapter": "grok",
        "project": str(project),
        "plugin_version": version,
        "policy_mode": policy_mode if not skip_agents else "skipped",
        "python_executable": resolved_python,
        "skills": list(SKILL_NAMES),
        "files": tracked_files,
        "mcp_server": server,
        "agents_block": agents_block,
    }
    payloads[OWNER_RELATIVE] = encode_json(metadata)

    changes, removals, backup_relative = commit_transaction(
        project,
        payloads,
        BACKUP_PREFIX,
        remove_files=tuple(sorted(set(remove_list))),
        prune_stop_rel=".grok",
    )
    if not changes and not removals:
        status = "unchanged"
    elif old is not None:
        status = "updated"
    else:
        status = "installed"
    return {
        "status": status,
        "adapter": "grok",
        "scope": "project",
        "project": str(project),
        "policy_mode": metadata["policy_mode"],
        "skills": list(SKILL_NAMES),
        "changed_files": changes,
        "removed_files": removals,
        "backup_directory": backup_relative,
        "model_calls": 0,
        "activation": ACTIVATION_NOTE,
    }


def check(source: Path, project: Path) -> dict:
    """Strictly read-only check of Grok adapter integrity and source parity."""
    raw_project = Path(project)
    reject_link(raw_project)
    source = Path(source).resolve()
    project = raw_project.resolve()
    if not project.is_dir():
        return {"status": "missing", "ok": False, "adapter": "grok", "project": str(project), "errors": ["Project directory does not exist."], "drift": []}

    owner_path = contained(project, OWNER_RELATIVE)
    if not owner_path.is_file():
        return {"status": "missing", "ok": False, "adapter": "grok", "project": str(project), "errors": [f"Missing {OWNER_RELATIVE}."], "drift": []}

    try:
        old = json.loads(owner_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "ok": False, "adapter": "grok", "project": str(project), "errors": [f"Malformed {OWNER_RELATIVE}: {exc}"], "drift": []}

    if not isinstance(old, dict) or old.get("owner") != OWNER or old.get("project") != str(project):
        return {"status": "invalid", "ok": False, "adapter": "grok", "project": str(project), "errors": ["Installation metadata belongs to another owner or project."], "drift": []}

    old_files = old.get("files", {})
    if not isinstance(old_files, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in old_files.items()):
        return {"status": "invalid", "ok": False, "adapter": "grok", "project": str(project), "errors": ["Malformed file ownership map."], "drift": []}

    expected_payloads = collect_package(source)
    errors, drift = check_owned_files(project, old_files, expected_payloads)

    source_version = read_plugin_version(source)
    if old.get("plugin_version") != source_version:
        drift.append(f"Installed version {old.get('plugin_version')!r} differs from source version {source_version!r}.")

    for skill_name in SKILL_NAMES:
        expected_skill_rel = f".grok/skills/{skill_name}/SKILL.md"
        if expected_skill_rel not in old_files:
            drift.append(f"Missing skill registration for {skill_name}.")

    mcp_path = contained(project, ".mcp.json")
    if not mcp_path.is_file():
        errors.append("Missing .mcp.json.")
    else:
        try:
            mcp = json.loads(mcp_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            errors.append(f"Malformed .mcp.json: {exc}")
        else:
            parrhesia_cfg = mcp.get("mcpServers", {}).get("parrhesia") if isinstance(mcp, dict) and isinstance(mcp.get("mcpServers"), dict) else None
            if parrhesia_cfg != old.get("mcp_server"):
                errors.append("mcpServers.parrhesia in .mcp.json does not match recorded installation.")

    agents_block = old.get("agents_block")
    if agents_block is not None:
        agents_path = contained(project, "AGENTS.md")
        if not agents_path.is_file():
            errors.append("Missing AGENTS.md containing recorded managed block.")
        else:
            agents_text = agents_path.read_text(encoding="utf-8-sig")
            if agents_text.count(agents_block) != 1:
                errors.append("Recorded Parrhesia managed block in AGENTS.md is missing or modified.")
            else:
                mode = old.get("policy_mode")
                check_mode = mode if mode in POLICY_MODES else "full"
                expected_block = f"{BEGIN}\n{load_policy_body(source, check_mode)}\n{END}"
                if agents_block != expected_block:
                    drift.append(f"AGENTS.md managed block differs from current source template ({check_mode}).")

    ok = not errors and not drift
    status = "ok" if ok else ("invalid" if errors else "drifted")
    return {
        "status": status,
        "ok": ok,
        "adapter": "grok",
        "scope": "project",
        "project": str(project),
        "plugin_version": old.get("plugin_version"),
        "source_version": source_version,
        "policy_mode": old.get("policy_mode", "legacy"),
        "skills": [s for s in SKILL_NAMES if f".grok/skills/{s}/SKILL.md" in old_files],
        "errors": errors,
        "drift": drift,
    }


def uninstall(project: Path) -> dict:
    """Safely remove managed Grok adapter files while backing up and keeping user config."""
    raw_project = Path(project)
    reject_link(raw_project)
    project = raw_project.resolve()
    if not project.is_dir():
        raise ValueError("Select an existing project directory.")

    _, old = _load_installation(project)
    if old is None:
        return {"status": "not_installed", "adapter": "grok", "scope": "project", "project": str(project), "removed_files": [], "changed_files": []}

    old_files, _ = validate_old_ownership(project, old, OWNER, "project", {}, ".grok/parrhesia")

    payloads: dict[str, bytes] = {}
    remove_list = list(old_files) + [OWNER_RELATIVE]

    mcp_bytes, remove_mcp = _cleanup_mcp(project, old.get("mcp_server"))
    if remove_mcp:
        remove_list.append(".mcp.json")
    elif mcp_bytes is not None:
        payloads[".mcp.json"] = mcp_bytes

    old_agents_block = old.get("agents_block")
    if old_agents_block:
        agents_path = contained(project, "AGENTS.md")
        if not agents_path.is_file():
            raise ValueError("The installed AGENTS.md block was removed or changed.")
        remaining = remove_managed_block(agents_path.read_text(encoding="utf-8-sig"), old_agents_block, begin=BEGIN, end=END)
        if remaining is None:
            remove_list.append("AGENTS.md")
        else:
            payloads["AGENTS.md"] = remaining.encode("utf-8")

    changes, removals, backup_relative = commit_transaction(
        project,
        payloads,
        BACKUP_PREFIX,
        remove_files=tuple(sorted(set(remove_list))),
        prune_stop_rel=".grok",
    )
    return {
        "status": "uninstalled",
        "adapter": "grok",
        "scope": "project",
        "project": str(project),
        "changed_files": changes,
        "removed_files": removals,
        "backup_directory": backup_relative,
        "model_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Existing project directory.")
    parser.add_argument("--source", type=Path, default=ROOT, help="Parrhesia package directory.")
    parser.add_argument("--policy", choices=POLICY_MODES, default="compact", help="AGENTS.md policy mode (default: compact).")
    parser.add_argument("--python", dest="python_executable", default=None, help="Explicit Python 3.11+ interpreter for .mcp.json.")
    parser.add_argument("--skip-agents", action="store_true", help="Do not add or keep the managed AGENTS.md block.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--check", action="store_true", help="Read-only check of installation integrity and source parity.")
    mode_group.add_argument("--uninstall", action="store_true", help="Remove managed Parrhesia Grok adapter files cleanly.")
    args = parser.parse_args(argv)

    if args.check:
        report = check(args.source, args.project)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.uninstall:
        report = uninstall(args.project)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    report = install(
        args.source,
        args.project,
        skip_agents=args.skip_agents,
        policy_mode=args.policy,
        python_executable=args.python_executable,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
