"""Conservative Antigravity host adapter; never touches ~/.gemini/config/config.json or calls a model."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parrhesia.adapters import (  # noqa: E402
    BEGIN,
    END,
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

OWNER = "parrhesia-antigravity-adapter-v1"
PLUGIN_NAME = "parrhesia"
MAX_RULE_BYTES = 24_000
SCOPES = ("project", "user")
RULES_TARGETS = ("plugin", "root", "both", "none")
ANTIGRAVITY_PLUGIN_ALLOWED_KEYS = frozenset({
    "name",
    "displayName",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "disabled",
    "logo",
    "suggestedPrompts",
})
_UNSAFE_CMD_CHARS = set('\r\n"&|><^%')


def _resolve_scope_layout(
    *,
    scope: str,
    project: Path | None,
    target: Path | None,
    explicit_workspace: Path | None,
    create_user_root: bool,
) -> tuple[Path, str, str, str, Path | None, Path | None]:
    if scope not in SCOPES:
        raise ValueError(f"Unsupported scope {scope!r}; expected one of {SCOPES}.")
    if scope == "project":
        if target is not None:
            raise ValueError("Do not pass --target with --scope=project; use --project instead.")
        if project is None:
            raise ValueError("--project is required when --scope=project.")
        raw_project = Path(project)
        reject_link(raw_project)
        root = raw_project.resolve()
        if not root.is_dir():
            raise ValueError("Select an existing project directory.")
        if explicit_workspace is not None:
            reject_link(Path(explicit_workspace))
            ws = Path(explicit_workspace).resolve()
            if not ws.is_dir():
                raise ValueError("Selected --workspace must already exist.")
        else:
            ws = root
        return root, "project", f".agents/plugins/{PLUGIN_NAME}", ".agents/parrhesia", ws, None

    if project is not None and target is None:
        raise ValueError("Use --target (not --project) when specifying a custom directory with --scope=user.")
    base_raw = target or os.environ.get("PARRHESIA_ANTIGRAVITY_HOME")
    base_path = Path(base_raw).expanduser() if base_raw else (Path.home() / ".gemini" / "config")
    reject_link(base_path)
    if create_user_root:
        base_path.mkdir(parents=True, exist_ok=True)
    root = base_path.resolve() if base_path.exists() else base_path
    ws: Path | None = None
    if explicit_workspace is not None:
        reject_link(Path(explicit_workspace))
        ws = Path(explicit_workspace).resolve()
        if not ws.is_dir():
            raise ValueError("Selected --workspace must already exist.")
    default_ws = root / "parrhesia" / "workspace"
    return root, "target", f"plugins/{PLUGIN_NAME}", "parrhesia", ws, default_ws


def _build_antigravity_manifest(source: Path, version: str) -> bytes:
    manifest_src = source / ".antigravity-plugin" / "plugin.json"
    if not manifest_src.is_file():
        raise ValueError("Incomplete plugin: missing .antigravity-plugin/plugin.json")
    manifest = json.loads(manifest_src.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(".antigravity-plugin/plugin.json must be a JSON object.")
    unknown = set(manifest) - ANTIGRAVITY_PLUGIN_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"Antigravity plugin.json contains unsupported keys: {sorted(unknown)}")
    if manifest.get("name") != PLUGIN_NAME or manifest.get("version") != version:
        raise ValueError(".antigravity-plugin/plugin.json name/version mismatches plugin.json.")
    return encode_json(manifest)


def _build_antigravity_rule(source: Path) -> bytes:
    compact = load_policy_body(source, "compact")
    host_note = """## Antigravity 宿主适配约定
- **精简规则与按需 Skill**：本规则仅常驻精简核心（严格 `< 24,000 B`）；日常按此执行，仅在触发 `L2` 正式双审或核对九设计包/八统计报告时按需读取 `parrhesia-l2-reference` skill，调用 MCP 工具 `parrhesia_workflow` 前遵循 `parrhesia-review` skill。
- **审查者隔离映射**：执行 `L2` 独立双审时，通过 `invoke_subagent`（不继承起草历史）或 `swarm`（`add` 不传 `fork`）为夸大审查与低估审查分别启动干净上下文；仅传入对应角色 `review_packet` 与授权证据内容，禁止泄露起草讨论与另一侧意见，并在 `input_manifest` 中如实记录 `inherited_history: false`、实际 `memory_read` 状态、`packet_id`、`input_digest`、`blind`、`evidence_ids` 与 `unread_evidence_ids`。
- **命令行执行溯源**：运行本地分析或复现脚本并引用结果时，经 `run_command` 调用 `python -m parrhesia record-exec --workspace <project> -- <cmd>`，再将生成的 `execution` 溯源卡写入台账。
- **状态隔离**：本适配器只写入安装目标插件目录与运行时目录，不修改全局 `config.json`；`SessionStart` 钩子仅在工作区 `.parrhesia/state.sqlite3` 存在本地案例时给出单行状态提醒。"""
    text = f"{compact}\n\n{host_note}\n"
    if text.lstrip().startswith("---"):
        raise ValueError("Antigravity always-on rule file must not begin with YAML frontmatter.")
    raw = text.encode("utf-8")
    if len(raw) > MAX_RULE_BYTES:
        raise ValueError(f"Antigravity rule exceeds {MAX_RULE_BYTES} bytes ({len(raw)} B).")
    return raw


def _build_mcp_config(
    python_exe: str,
    run_mcp_path: Path,
    workspace: Path | None,
    default_workspace: Path | None,
) -> dict:
    if workspace is not None:
        args = [str(run_mcp_path), "--workspace", str(workspace)]
    elif default_workspace is not None:
        args = [str(run_mcp_path), "--default-workspace", str(default_workspace)]
    else:
        raise ValueError("Either workspace or default_workspace must be resolved for Antigravity MCP config.")
    return {
        "mcpServers": {
            "parrhesia": {
                "command": python_exe,
                "args": args,
                "env": {
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
            }
        }
    }


def _build_hook_command(python_exe: str, hook_script: Path, workspace: Path | None) -> str:
    cmd_parts = [python_exe, str(hook_script), "--event", "SessionStart"]
    if workspace is not None:
        cmd_parts.extend(["--workspace", str(workspace)])
    if os.name == "nt":
        for part in cmd_parts:
            if any(ch in _UNSAFE_CMD_CHARS for ch in part):
                raise ValueError(f"Unsafe character in Windows hook command path: {part!r}")
        # Prefix with 'call' so cmd.exe /c never strips outer quotes when >=2 arguments are quoted.
        quoted = [f'"{part}"' if part not in {"--event", "SessionStart", "--workspace"} else part for part in cmd_parts]
        return "call " + " ".join(quoted)
    return shlex.join(cmd_parts)


def _build_hooks_config(python_exe: str, hook_script: Path, workspace: Path | None) -> dict:
    return {
        "parrhesia-session-status": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": _build_hook_command(python_exe, hook_script, workspace),
                    "timeout": 10,
                }
            ]
        }
    }


def collect_bundle(
    source: Path,
    root: Path,
    *,
    plugin_prefix: str,
    state_prefix: str,
    rules_target: str,
    no_hooks: bool,
    python_exe: str,
    workspace: Path | None,
    default_workspace: Path | None,
) -> tuple[dict[str, bytes], dict, dict | None, bytes | None]:
    """Build all managed payloads for an Antigravity plugin installation."""
    source = source.resolve()
    version = read_plugin_version(source)
    payloads = collect_runtime_payloads(source, f"{state_prefix}/runtime")
    payloads.update(collect_skills_payloads(source, f"{plugin_prefix}/skills", SKILL_NAMES))
    payloads[f"{plugin_prefix}/plugin.json"] = _build_antigravity_manifest(source, version)

    run_mcp_path = root / state_prefix / "runtime" / "scripts" / "run-mcp.py"
    mcp_config = _build_mcp_config(python_exe, run_mcp_path, workspace, default_workspace)
    payloads[f"{plugin_prefix}/mcp_config.json"] = encode_json(mcp_config)

    if rules_target in ("plugin", "both"):
        payloads[f"{plugin_prefix}/rules/parrhesia.md"] = _build_antigravity_rule(source)

    hooks_config: dict | None = None
    if not no_hooks:
        hook_src = source / "scripts" / "antigravity_hook.py"
        if not hook_src.is_file():
            raise ValueError("Incomplete plugin: missing scripts/antigravity_hook.py")
        reject_link(hook_src)
        hook_rel = f"{plugin_prefix}/hooks/parrhesia_hook.py"
        payloads[hook_rel] = hook_src.read_bytes()
        hook_abs = root / hook_rel
        hooks_config = _build_hooks_config(python_exe, hook_abs, workspace)
        payloads[f"{plugin_prefix}/hooks.json"] = encode_json(hooks_config)

    root_rule_body = load_policy_body(source, "compact").encode("utf-8") if rules_target in ("root", "both") else None
    if root_rule_body is not None and len(root_rule_body) > MAX_RULE_BYTES:
        raise ValueError(f"Root rule block exceeds Antigravity {MAX_RULE_BYTES} B limit ({len(root_rule_body)} B).")
    return payloads, mcp_config, hooks_config, root_rule_body


def _load_installation(root: Path, owner_relative: str) -> tuple[Path, dict | None]:
    owner_path = contained(root, owner_relative)
    if not owner_path.exists():
        return owner_path, None
    return owner_path, json.loads(owner_path.read_text(encoding="utf-8"))


def install(
    source: Path,
    *,
    scope: str = "project",
    project: Path | None = None,
    target: Path | None = None,
    workspace: Path | None = None,
    rules_target: str = "plugin",
    no_hooks: bool = False,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Install or safely update the Antigravity adapter in project or explicit user target scope."""
    if rules_target not in RULES_TARGETS:
        raise ValueError(f"Unsupported --rules-target {rules_target!r}; expected one of {RULES_TARGETS}.")
    if scope == "user" and rules_target in ("root", "both"):
        raise ValueError("--rules-target root/both is only supported with --scope=project.")

    source = Path(source).resolve()
    version = read_plugin_version(source)
    resolved_python = resolve_python_executable(python_executable)
    root, root_key, plugin_prefix, state_prefix, resolved_ws, default_ws = _resolve_scope_layout(
        scope=scope,
        project=project,
        target=target,
        explicit_workspace=workspace,
        create_user_root=True,
    )
    owner_relative = f"{state_prefix}/installation.json"
    backup_prefix = f"{state_prefix}/backups"

    _, old = _load_installation(root, owner_relative)
    payloads, mcp_config, hooks_config, root_rule_body = collect_bundle(
        source,
        root,
        plugin_prefix=plugin_prefix,
        state_prefix=state_prefix,
        rules_target=rules_target,
        no_hooks=no_hooks,
        python_exe=resolved_python,
        workspace=resolved_ws,
        default_workspace=default_ws,
    )

    _, obsolete_files = validate_old_ownership(root, old, OWNER, root_key, payloads, state_prefix)
    old_agents_block = old.get("agents_block") if old else None
    if old_agents_block is not None and not isinstance(old_agents_block, str):
        raise ValueError("Installation AGENTS block metadata is malformed.")

    remove_list = list(obsolete_files)
    agents_block: str | None = None
    if scope == "project" and root_rule_body is not None:
        agents_path = contained(root, "AGENTS.md")
        original = agents_path.read_text(encoding="utf-8-sig") if agents_path.exists() else ""
        updated, agents_block = merge_managed_block(
            original,
            root_rule_body.decode("utf-8"),
            old_agents_block,
            begin=BEGIN,
            end=END,
        )
        payloads["AGENTS.md"] = updated.encode("utf-8")
    elif scope == "project" and old_agents_block:
        agents_path = contained(root, "AGENTS.md")
        if not agents_path.is_file():
            raise ValueError("The installed AGENTS.md block was removed or changed.")
        remaining = remove_managed_block(agents_path.read_text(encoding="utf-8-sig"), old_agents_block, begin=BEGIN, end=END)
        if remaining is None:
            remove_list.append("AGENTS.md")
        else:
            payloads["AGENTS.md"] = remaining.encode("utf-8")

    tracked_files = {key: sha256_bytes(data) for key, data in payloads.items() if key != "AGENTS.md"}
    metadata = {
        "owner": OWNER,
        "adapter": "antigravity",
        "scope": scope,
        root_key: str(root),
        "plugin_version": version,
        "plugin_dir": plugin_prefix,
        "runtime_dir": f"{state_prefix}/runtime",
        "rules_target": rules_target,
        "hooks_enabled": not no_hooks,
        "python_executable": resolved_python,
        "workspace": str(resolved_ws) if resolved_ws is not None else None,
        "default_workspace": str(default_ws) if default_ws is not None else None,
        "skills": list(SKILL_NAMES),
        "files": tracked_files,
        "mcp_config": mcp_config,
        "hooks_config": hooks_config,
        "agents_block": agents_block,
    }
    payloads[owner_relative] = encode_json(metadata)

    changes, removals, backup_relative = commit_transaction(
        root,
        payloads,
        backup_prefix,
        remove_files=tuple(sorted(set(remove_list))),
        prune_stop_rel=plugin_prefix.split("/", 1)[0],
    )
    if not changes and not removals:
        status = "unchanged"
    elif old is not None:
        status = "updated"
    else:
        status = "installed"

    return {
        "status": status,
        "adapter": "antigravity",
        "scope": scope,
        "target_root": str(root),
        "plugin_directory": str(root / plugin_prefix),
        "rules_target": rules_target,
        "hooks_enabled": not no_hooks,
        "skills": list(SKILL_NAMES),
        "changed_files": changes,
        "removed_files": removals,
        "backup_directory": backup_relative,
        "model_calls": 0,
        "global_config_touched": False,
        "activation": (
            "Antigravity discovers .agents/plugins/parrhesia/ automatically per project "
            "(or plugins/parrhesia/ under custom user target). Enable only one copy to avoid "
            "duplicate 'parrhesia' MCP server registration; this installer never edits config.json."
        ),
    }


def _validate_antigravity_artifacts(root: Path, old: dict, errors: list[str]) -> None:
    plugin_prefix = str(old.get("plugin_dir") or "")
    if not plugin_prefix:
        errors.append("Missing plugin_dir in installation metadata.")
        return

    manifest_path = contained(root, f"{plugin_prefix}/plugin.json")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"Malformed plugin.json: {exc}")
        else:
            if not isinstance(manifest, dict):
                errors.append("plugin.json must be a JSON object.")
            else:
                unknown = set(manifest) - ANTIGRAVITY_PLUGIN_ALLOWED_KEYS
                if unknown:
                    errors.append(f"plugin.json contains non-Antigravity keys: {sorted(unknown)}")
                if manifest.get("name") != PLUGIN_NAME:
                    errors.append(f"plugin.json name must be {PLUGIN_NAME!r}.")

    mcp_path = contained(root, f"{plugin_prefix}/mcp_config.json")
    if mcp_path.is_file():
        try:
            mcp_cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"Malformed mcp_config.json: {exc}")
        else:
            server = mcp_cfg.get("mcpServers", {}).get("parrhesia") if isinstance(mcp_cfg, dict) and isinstance(mcp_cfg.get("mcpServers"), dict) else None
            if not isinstance(server, dict) or not isinstance(server.get("command"), str) or not isinstance(server.get("args"), list):
                errors.append("mcp_config.json missing valid mcpServers.parrhesia stdio definition.")
            elif mcp_cfg != old.get("mcp_config"):
                errors.append("mcp_config.json differs from recorded installation.")

    rules_target = old.get("rules_target", "plugin")
    if rules_target in ("plugin", "both"):
        rule_path = contained(root, f"{plugin_prefix}/rules/parrhesia.md")
        if rule_path.is_file():
            raw = rule_path.read_bytes()
            if len(raw) > MAX_RULE_BYTES:
                errors.append(f"rules/parrhesia.md exceeds Antigravity {MAX_RULE_BYTES} B cap ({len(raw)} B).")
            text = raw.decode("utf-8", errors="replace")
            if text.lstrip().startswith("---"):
                errors.append("rules/parrhesia.md unexpectedly contains YAML frontmatter.")

    for skill_name in SKILL_NAMES:
        skill_path = contained(root, f"{plugin_prefix}/skills/{skill_name}/SKILL.md")
        if skill_path.is_file():
            skill_text = skill_path.read_text(encoding="utf-8")
            if not skill_text.startswith("---\n") or f"name: {skill_name}\n" not in skill_text[:300]:
                errors.append(f"skills/{skill_name}/SKILL.md is missing expected frontmatter name.")

    if old.get("hooks_enabled"):
        hooks_path = contained(root, f"{plugin_prefix}/hooks.json")
        if hooks_path.is_file():
            try:
                hooks_cfg = json.loads(hooks_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"Malformed hooks.json: {exc}")
            else:
                if hooks_cfg != old.get("hooks_config"):
                    errors.append("hooks.json differs from recorded installation.")
                group = hooks_cfg.get("parrhesia-session-status") if isinstance(hooks_cfg, dict) else None
                session_hooks = group.get("SessionStart") if isinstance(group, dict) else None
                if not isinstance(session_hooks, list) or not session_hooks or session_hooks[0].get("type") != "command":
                    errors.append("hooks.json missing SessionStart command entry.")


def check(
    source: Path,
    *,
    scope: str = "project",
    project: Path | None = None,
    target: Path | None = None,
) -> dict[str, Any]:
    """Strictly read-only check of Antigravity adapter integrity and source parity."""
    source = Path(source).resolve()
    try:
        root, root_key, plugin_prefix, state_prefix, resolved_ws, default_ws = _resolve_scope_layout(
            scope=scope,
            project=project,
            target=target,
            explicit_workspace=None,
            create_user_root=False,
        )
    except ValueError as exc:
        return {"status": "missing", "ok": False, "adapter": "antigravity", "scope": scope, "errors": [str(exc)], "drift": []}

    if not root.is_dir():
        return {"status": "missing", "ok": False, "adapter": "antigravity", "scope": scope, "target_root": str(root), "errors": ["Target directory does not exist."], "drift": []}

    owner_relative = f"{state_prefix}/installation.json"
    owner_path = contained(root, owner_relative)
    if not owner_path.is_file():
        return {"status": "missing", "ok": False, "adapter": "antigravity", "scope": scope, "target_root": str(root), "errors": [f"Missing {owner_relative}."], "drift": []}

    try:
        old = json.loads(owner_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "ok": False, "adapter": "antigravity", "scope": scope, "target_root": str(root), "errors": [f"Malformed {owner_relative}: {exc}"], "drift": []}

    if not isinstance(old, dict) or old.get("owner") != OWNER or old.get(root_key) != str(root):
        return {"status": "invalid", "ok": False, "adapter": "antigravity", "scope": scope, "target_root": str(root), "errors": ["Installation metadata belongs to another owner or target."], "drift": []}

    old_files = old.get("files", {})
    if not isinstance(old_files, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in old_files.items()):
        return {"status": "invalid", "ok": False, "adapter": "antigravity", "scope": scope, "target_root": str(root), "errors": ["Malformed file ownership map."], "drift": []}

    recorded_ws = Path(old["workspace"]) if old.get("workspace") else resolved_ws
    recorded_default_ws = Path(old["default_workspace"]) if old.get("default_workspace") else default_ws
    recorded_python = str(old.get("python_executable") or sys.executable)
    recorded_rules_target = str(old.get("rules_target") or "plugin")
    recorded_no_hooks = not bool(old.get("hooks_enabled", True))
    expected_payloads, _, _, expected_root_rule = collect_bundle(
        source,
        root,
        plugin_prefix=plugin_prefix,
        state_prefix=state_prefix,
        rules_target=recorded_rules_target,
        no_hooks=recorded_no_hooks,
        python_exe=recorded_python,
        workspace=recorded_ws,
        default_workspace=recorded_default_ws,
    )

    errors, drift = check_owned_files(root, old_files, expected_payloads)
    _validate_antigravity_artifacts(root, old, errors)

    source_version = read_plugin_version(source)
    if old.get("plugin_version") != source_version:
        drift.append(f"Installed version {old.get('plugin_version')!r} differs from source version {source_version!r}.")

    agents_block = old.get("agents_block")
    if agents_block is not None:
        agents_path = contained(root, "AGENTS.md")
        if not agents_path.is_file():
            errors.append("Missing AGENTS.md containing recorded managed block.")
        else:
            agents_text = agents_path.read_text(encoding="utf-8-sig")
            if agents_text.count(agents_block) != 1:
                errors.append("Recorded Parrhesia managed block in AGENTS.md is missing or modified.")
            elif expected_root_rule is not None:
                expected_block = f"{BEGIN}\n{expected_root_rule.decode('utf-8')}\n{END}"
                if agents_block != expected_block:
                    drift.append("AGENTS.md managed block differs from current source compact template.")

    ok = not errors and not drift
    status = "ok" if ok else ("invalid" if errors else "drifted")
    return {
        "status": status,
        "ok": ok,
        "adapter": "antigravity",
        "scope": scope,
        "target_root": str(root),
        "plugin_directory": str(root / plugin_prefix),
        "plugin_version": old.get("plugin_version"),
        "source_version": source_version,
        "rules_target": recorded_rules_target,
        "hooks_enabled": bool(old.get("hooks_enabled")),
        "skills": [s for s in SKILL_NAMES if f"{plugin_prefix}/skills/{s}/SKILL.md" in old_files],
        "errors": errors,
        "drift": drift,
    }


def uninstall(
    *,
    scope: str = "project",
    project: Path | None = None,
    target: Path | None = None,
) -> dict[str, Any]:
    """Safely remove managed Antigravity adapter files cleanly with backup."""
    root, root_key, plugin_prefix, state_prefix, _, _ = _resolve_scope_layout(
        scope=scope,
        project=project,
        target=target,
        explicit_workspace=None,
        create_user_root=False,
    )
    if not root.is_dir():
        return {"status": "not_installed", "adapter": "antigravity", "scope": scope, "target_root": str(root), "removed_files": [], "changed_files": []}

    owner_relative = f"{state_prefix}/installation.json"
    backup_prefix = f"{state_prefix}/backups"
    _, old = _load_installation(root, owner_relative)
    if old is None:
        return {"status": "not_installed", "adapter": "antigravity", "scope": scope, "target_root": str(root), "removed_files": [], "changed_files": []}

    old_files, _ = validate_old_ownership(root, old, OWNER, root_key, {}, state_prefix)
    payloads: dict[str, bytes] = {}
    remove_list = list(old_files) + [owner_relative]

    old_agents_block = old.get("agents_block")
    if old_agents_block and scope == "project":
        agents_path = contained(root, "AGENTS.md")
        if not agents_path.is_file():
            raise ValueError("The installed AGENTS.md block was removed or changed.")
        remaining = remove_managed_block(agents_path.read_text(encoding="utf-8-sig"), old_agents_block, begin=BEGIN, end=END)
        if remaining is None:
            remove_list.append("AGENTS.md")
        else:
            payloads["AGENTS.md"] = remaining.encode("utf-8")

    changes, removals, backup_relative = commit_transaction(
        root,
        payloads,
        backup_prefix,
        remove_files=tuple(sorted(set(remove_list))),
        prune_stop_rel=plugin_prefix.split("/", 1)[0],
    )
    return {
        "status": "uninstalled",
        "adapter": "antigravity",
        "scope": scope,
        "target_root": str(root),
        "changed_files": changes,
        "removed_files": removals,
        "backup_directory": backup_relative,
        "model_calls": 0,
        "global_config_touched": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=SCOPES, default="project", help="Install scope: project (.agents/plugins/parrhesia) or user (custom/Antigravity home).")
    parser.add_argument("--project", type=Path, default=None, help="Existing project directory (required for --scope=project).")
    parser.add_argument("--target", type=Path, default=None, help="Explicit Antigravity config root for --scope=user (defaults to $PARRHESIA_ANTIGRAVITY_HOME or ~/.gemini/config).")
    parser.add_argument("--workspace", type=Path, default=None, help="Optional explicit Parrhesia workspace directory for MCP & SessionStart hook.")
    parser.add_argument("--source", type=Path, default=ROOT, help="Parrhesia package directory.")
    parser.add_argument("--rules-target", choices=RULES_TARGETS, default="plugin", help="Where to place compact rules (default: plugin).")
    parser.add_argument("--python", dest="python_executable", default=None, help="Explicit Python 3.11+ interpreter for mcp_config.json and hooks.json.")
    parser.add_argument("--no-hooks", action="store_true", help="Skip installing hooks.json and hooks/parrhesia_hook.py.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--check", action="store_true", help="Read-only check of installation integrity and source parity.")
    mode_group.add_argument("--uninstall", action="store_true", help="Remove managed Parrhesia Antigravity files cleanly.")
    args = parser.parse_args(argv)

    if args.check:
        report = check(args.source, scope=args.scope, project=args.project, target=args.target)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.uninstall:
        report = uninstall(scope=args.scope, project=args.project, target=args.target)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    report = install(
        args.source,
        scope=args.scope,
        project=args.project,
        target=args.target,
        workspace=args.workspace,
        rules_target=args.rules_target,
        no_hooks=args.no_hooks,
        python_executable=args.python_executable,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
