"""Shared stdlib primitives for self-contained host project/user adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

BEGIN = "<!-- parrhesia:managed:start -->"
END = "<!-- parrhesia:managed:end -->"
SKILL_NAMES = ("parrhesia-review", "parrhesia-l2-reference")
SKILL_REQUIRED_FILES = {
    "parrhesia-review": ("SKILL.md", "references/basics.md", "references/workflow.md", "references/integrations.md"),
    "parrhesia-l2-reference": ("SKILL.md",),
}
RUNTIME_DOCUMENTS = ("docs/contract.md", "docs/artifact-ingestion.md")
POLICY_MODES = ("compact", "full")

_POLICY_TEMPLATE_MAP = {
    "compact": "AGENTS.parrhesia.codex.md",
    "full": "AGENTS.parrhesia.md",
}


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def encode_json(value: object) -> bytes:
    """Encode JSON deterministically with UTF-8 encoding and trailing newline."""
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def reject_link(path: Path) -> None:
    """Fail if an existing filesystem node is a symlink or Windows reparse point."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    attributes = getattr(info, "st_file_attributes", 0)
    if stat.S_ISLNK(info.st_mode) or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ValueError(f"Refusing linked installation path: {path}")


def contained(root: Path, relative: str) -> Path:
    """Resolve a relative path inside root, refusing escapes and symlinks."""
    rel_path = Path(relative)
    if rel_path.is_absolute():
        raise ValueError(f"Path must be relative: {relative}")
    root_resolved = root.resolve()
    destination = root / rel_path
    if not destination.resolve().is_relative_to(root_resolved):
        raise ValueError(f"Path escapes the selected root: {relative}")
    current = destination
    while current != root and current != root_resolved:
        reject_link(current)
        current = current.parent
    return destination


def read_plugin_version(source: Path) -> str:
    """Read and validate the plugin version string from source/plugin.json."""
    manifest_path = source / "plugin.json"
    if not manifest_path.is_file():
        raise ValueError("Incomplete plugin: missing plugin.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("plugin.json is missing a valid version string")
    return version


def resolve_python_executable(python_executable: str | None = None) -> str:
    """Resolve and validate a Python 3.11+ interpreter path."""
    if python_executable is None:
        if sys.version_info < (3, 11):
            raise ValueError("Parrhesia requires Python 3.11 or newer.")
        return sys.executable
    candidate = python_executable.strip()
    if not candidate:
        raise ValueError("Python executable path must not be empty.")
    located = shutil.which(candidate) if not Path(candidate).is_absolute() and os.sep not in candidate and "/" not in candidate else candidate
    exe_path = Path(located or candidate)
    if not exe_path.exists():
        raise ValueError(f"Python executable was not found: {python_executable}")
    resolved = str(exe_path.resolve())
    probe = subprocess.run(
        [resolved, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}', end='')"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    if probe.returncode != 0:
        raise ValueError(f"Python executable failed version check: {python_executable}")
    try:
        major, minor = (int(part) for part in probe.stdout.strip().split(".")[:2])
    except ValueError as exc:
        raise ValueError(f"Could not parse Python version from {python_executable}: {probe.stdout!r}") from exc
    if (major, minor) < (3, 11):
        raise ValueError(f"Parrhesia requires Python 3.11 or newer; got {major}.{minor} from {python_executable}")
    return resolved


def collect_runtime_payloads(source: Path, runtime_prefix: str) -> dict[str, bytes]:
    """Collect self-contained Parrhesia runtime modules, manifests, and contract docs."""
    prefix = runtime_prefix.strip("/")
    package = source / "parrhesia"
    required = [
        package / "__main__.py",
        source / "plugin.json",
        source / "mcp.json",
        source / "scripts" / "run-mcp.py",
        *(source / name for name in RUNTIME_DOCUMENTS),
    ]
    for item in required:
        if not item.is_file():
            raise ValueError(f"Incomplete plugin: missing {item.relative_to(source).as_posix()}")

    inputs = [
        *[p for p in sorted(package.rglob("*.py")) if "__pycache__" not in p.parts],
        source / "plugin.json",
        source / "mcp.json",
        source / "scripts" / "run-mcp.py",
        *(source / name for name in RUNTIME_DOCUMENTS),
    ]
    payloads: dict[str, bytes] = {}
    source_resolved = source.resolve()
    for item in inputs:
        reject_link(item)
        if not item.resolve().is_relative_to(source_resolved):
            raise ValueError(f"Package includes a path outside its root: {item}")
        payloads[f"{prefix}/{item.relative_to(source).as_posix()}"] = item.read_bytes()
    return payloads


def collect_skills_payloads(
    source: Path,
    skills_prefix: str,
    skill_names: tuple[str, ...] = SKILL_NAMES,
) -> dict[str, bytes]:
    """Collect one or more named skill directories under source/skills/."""
    prefix = skills_prefix.strip("/")
    source_resolved = source.resolve()
    errors = skill_layout_errors(source, "skills", skill_names)
    if errors:
        raise ValueError("Incomplete skill bundle: " + "; ".join(errors))
    payloads: dict[str, bytes] = {}
    for name in skill_names:
        skill_dir = source / "skills" / name
        entrypoint = skill_dir / "SKILL.md"
        if not entrypoint.is_file():
            raise ValueError(f"Incomplete plugin: missing {entrypoint.relative_to(source).as_posix()}")
        for item in sorted(skill_dir.rglob("*")):
            contained(source, item.relative_to(source).as_posix())
            if not item.is_file() or "__pycache__" in item.parts:
                continue
            reject_link(item)
            if not item.resolve().is_relative_to(source_resolved):
                raise ValueError(f"Skill includes a path outside the package root: {item}")
            payloads[f"{prefix}/{name}/{item.relative_to(skill_dir).as_posix()}"] = item.read_bytes()
    return payloads


def skill_layout_errors(root: Path, skills_prefix: str, skill_names: tuple[str, ...] = SKILL_NAMES) -> list[str]:
    """One source of required entrypoints/references for every filesystem adapter."""
    errors = []
    for name in skill_names:
        for relative in SKILL_REQUIRED_FILES.get(name, ("SKILL.md",)):
            path = contained(root, f"{skills_prefix}/{name}/{relative}")
            if not path.is_file():
                errors.append(f"Missing required skill file: {skills_prefix}/{name}/{relative}")
            elif relative == "SKILL.md":
                body = path.read_text(encoding="utf-8-sig")
                if not body.startswith("---\n") or f"name: {name}\n" not in body[:300]:
                    errors.append(f"Invalid skill frontmatter: {skills_prefix}/{name}/SKILL.md")
    return errors


def load_policy_body(source: Path, mode: str = "compact") -> str:
    """Load the policy Markdown body for the selected mode without outer generator markers."""
    if mode not in POLICY_MODES:
        raise ValueError(f"Unsupported policy mode {mode!r}; expected one of {POLICY_MODES}.")
    rel = Path("templates") / _POLICY_TEMPLATE_MAP[mode]
    template = source / rel
    if not template.is_file():
        raise ValueError(f"Missing {rel.as_posix()}; use the complete package.")
    text = template.read_text(encoding="utf-8")
    start_marker = "<!-- parrhesia:judgment-policy:start -->"
    end_marker = "<!-- parrhesia:judgment-policy:end -->"
    if start_marker in text and end_marker in text:
        _, _, rest = text.partition(start_marker)
        body, _, _ = rest.partition(end_marker)
        body = body.strip()
    else:
        lines = [
            line for line in text.splitlines()
            if not line.strip().startswith("<!-- Generated from policy/parrhesia-policy.md")
        ]
        body = "\n".join(lines).strip()
    if mode == "full":
        # Explicit legacy full mode still means all applicable rules. Default
        # compact installs keep these references in the on-demand skill tree.
        for rel in (
            "skills/parrhesia-l2-reference/SKILL.md",
            "skills/parrhesia-review/references/workflow.md",
        ):
            body += "\n\n" + (source / rel).read_text(encoding="utf-8").strip()
    return body


def merge_managed_block(
    original: str,
    body: str,
    old_block: str | None,
    *,
    begin: str = BEGIN,
    end: str = END,
) -> tuple[str, str]:
    """Safely insert or replace a uniquely owned managed Markdown block."""
    if (begin in original or end in original) and (not old_block or original.count(old_block) != 1):
        raise ValueError("The AGENTS.md Parrhesia block is unmanaged or modified; no files were changed.")
    new_block = f"{begin}\n{body.strip()}\n{end}"
    if old_block:
        if original.count(old_block) != 1:
            raise ValueError("The installed AGENTS.md block was removed or changed.")
        updated = original.replace(old_block, new_block, 1)
    else:
        sep = "\n\n" if original and not original.endswith("\n\n") else ""
        if original and not original.endswith("\n"):
            sep = "\n\n"
        updated = original + sep + new_block + "\n"
    return updated, new_block


def remove_managed_block(original: str, old_block: str, *, begin: str = BEGIN, end: str = END) -> str | None:
    """Remove an owned managed block cleanly; return None if no user content remains."""
    if not old_block:
        return original
    if original.count(old_block) != 1:
        raise ValueError("The installed AGENTS.md block was removed or changed; refusing to modify AGENTS.md.")
    before, after = original.split(old_block, 1)
    before_clean = before.rstrip("\r\n")
    after_clean = after.lstrip("\r\n")
    if before_clean and after_clean:
        return f"{before_clean}\n\n{after_clean}"
    combined = before_clean or after_clean
    if not combined.strip():
        return None
    return combined if combined.endswith("\n") else f"{combined}\n"


def validate_old_ownership(
    root: Path,
    old: dict | None,
    expected_owner: str,
    root_key: str,
    new_payloads: dict[str, bytes],
    metadata_dir_rel: str,
    *,
    allowed_orphans: set[str] | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Verify prior ownership integrity and check for unmanaged collisions before writing."""
    root_str = str(root)
    if old is not None and (not isinstance(old, dict) or old.get("owner") != expected_owner or old.get(root_key) != root_str):
        raise ValueError("Existing installation metadata belongs to another owner or target.")
    meta_dir = contained(root, metadata_dir_rel)
    if old is None and meta_dir.exists() and any(item.name != "backups" for item in meta_dir.iterdir()):
        raise ValueError(f"Existing {metadata_dir_rel} directory is unmanaged; choose a clean location or reconcile it manually.")

    old_files = old.get("files", {}) if old else {}
    if not isinstance(old_files, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in old_files.items()):
        raise ValueError("Installation file ownership metadata is malformed.")

    for relative, expected_hash in old_files.items():
        existing = contained(root, relative)
        if not existing.is_file() or sha256_bytes(existing.read_bytes()) != expected_hash:
            raise ValueError(f"An installed file was changed or removed: {relative}. Preserve/reconcile it before updating.")

    for relative in new_payloads:
        existing = contained(root, relative)
        if existing.exists() and relative not in old_files:
            if allowed_orphans and relative in allowed_orphans:
                continue
            raise ValueError(f"Refusing to replace unmanaged file: {relative}")

    obsolete = tuple(sorted(set(old_files) - set(new_payloads)))
    return dict(old_files), obsolete


def _prune_empty_dirs(root: Path, candidate: Path, stop_at: Path) -> None:
    current = candidate
    root_resolved = root.resolve()
    stop_resolved = stop_at.resolve()
    while current != stop_at and current.resolve() != stop_resolved and current.resolve().is_relative_to(root_resolved):
        if current.is_dir() and not any(current.iterdir()):
            current.rmdir()
            current = current.parent
        else:
            break


def commit_transaction(
    root: Path,
    payloads: dict[str, bytes],
    backup_root_prefix: str,
    *,
    remove_files: tuple[str, ...] = (),
    prune_stop_rel: str | None = None,
) -> tuple[list[str], list[str], str | None]:
    """Compute deltas, create timestamped backups, write atomically, and roll back on error."""
    changes = {
        relative: data
        for relative, data in payloads.items()
        if not contained(root, relative).is_file() or contained(root, relative).read_bytes() != data
    }
    removals = [
        relative for relative in remove_files
        if contained(root, relative).is_file()
    ]
    if not changes and not removals:
        return [], [], None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    backup_relative = f"{backup_root_prefix.rstrip('/')}/{stamp}"
    previous: dict[str, bytes | None] = {}
    for relative in list(changes) + removals:
        target = contained(root, relative)
        previous[relative] = target.read_bytes() if target.is_file() else None
        if previous[relative] is not None:
            backup = contained(root, f"{backup_relative}/{relative}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(previous[relative])

    applied_writes: list[str] = []
    applied_removes: list[str] = []
    stop_path = contained(root, prune_stop_rel) if prune_stop_rel else root
    try:
        for relative, data in changes.items():
            target = contained(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f"{target.name}.parrhesia-{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(data)
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            applied_writes.append(relative)
        for relative in removals:
            target = contained(root, relative)
            if target.exists():
                target.unlink()
                applied_removes.append(relative)
                _prune_empty_dirs(root, target.parent, stop_path)
    except Exception:
        for relative in reversed(applied_removes):
            if previous.get(relative) is not None:
                target = contained(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(previous[relative])  # type: ignore[arg-type]
        for relative in reversed(applied_writes):
            target = contained(root, relative)
            if previous.get(relative) is None:
                if target.exists():
                    target.unlink()
            else:
                target.write_bytes(previous[relative])  # type: ignore[arg-type]
        raise

    has_backup = any(value is not None for value in previous.values())
    return list(changes), list(removals), (backup_relative if has_backup else None)


def check_owned_files(
    root: Path,
    owned_files: dict[str, str],
    expected_payloads: dict[str, bytes] | None = None,
) -> tuple[list[str], list[str]]:
    """Read-only verification of installed file integrity and optional source drift."""
    errors: list[str] = []
    drift: list[str] = []
    for relative, expected_hash in sorted(owned_files.items()):
        try:
            target = contained(root, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not target.is_file():
            errors.append(f"Missing installed file: {relative}")
            continue
        actual_hash = sha256_bytes(target.read_bytes())
        if actual_hash != expected_hash:
            errors.append(f"Hash mismatch for installed file: {relative}")
            continue
        if expected_payloads is not None and relative in expected_payloads:
            if sha256_bytes(expected_payloads[relative]) != actual_hash:
                drift.append(f"Source drift for {relative}")
    if expected_payloads is not None:
        for relative in sorted(set(expected_payloads) - set(owned_files)):
            drift.append(f"Missing newly shipped file from installation: {relative}")
    return errors, drift
