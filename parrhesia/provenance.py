"""Pure-stdlib provenance auto-collection for Parrhesia `record-exec`."""
from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import stat
import subprocess
import sys
import unicodedata

from .contracts import fail, string
from .gates import strip_terminal_escapes

LOCKFILE_EXACT_NAMES = frozenset({
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "Cargo.lock",
    "Pipfile.lock",
    "environment.yml",
})
DEFAULT_STDOUT_EXCERPT_CHARS = 400
MAX_STDOUT_EXCERPT_CHARS = 2000
MAX_DETAIL_SUMMARY_CHARS = 4000
GIT_TIMEOUT_SECONDS = 10.0
_HASH_CHUNK_BYTES = 64 * 1024
_WINDOWS_RESERVED_NAMES = frozenset({
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
})


def is_link_or_reparse(path: Path) -> bool:
    """Return True if path is a symlink or Windows reparse point."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return bool(stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & 0x400))


def _reject_link(path: Path) -> None:
    if is_link_or_reparse(path):
        fail("unsafe_path", "symlinks and reparse points are not allowed")


def resolve_workspace_path(workspace: Path, relative: str) -> Path:
    """Validate and resolve a workspace-relative path without symlink traversal."""
    ws = Path(workspace).resolve(strict=True)
    value = string(relative, "path", maximum=2000)
    windows = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if windows.drive or windows.root or normalized.startswith("/") or ":" in value or "\x00" in value:
        fail("unsafe_path", "path must be relative to the workspace")
    if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in parts):
        fail("unsafe_path", "empty, traversal, and ambiguous path components are not allowed")
    if parts[0].casefold() == ".parrhesia":
        fail("unsafe_path", "the internal state directory cannot be referenced")
    if any(part.split(".")[0].casefold() in _WINDOWS_RESERVED_NAMES for part in parts):
        fail("unsafe_path", "Windows device names are not allowed")
    current = ws
    for part in parts:
        current = current / part
        _reject_link(current)
    try:
        current.resolve(strict=False).relative_to(ws)
    except (ValueError, OSError):
        fail("unsafe_path", "path escapes the workspace")
    return current


def hash_regular_file(path: Path) -> tuple[str, int]:
    """Stream-hash a regular non-link file as (sha256_hex, size_bytes)."""
    _reject_link(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail("invalid_source", f"file does not exist: {path.name}")
    except OSError as exc:
        fail("source_unreadable", f"cannot inspect file: {exc.__class__.__name__}")
    if not stat.S_ISREG(info.st_mode):
        fail("invalid_source", f"path must reference a regular file: {path.name}")
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                fail("invalid_source", f"path must reference a regular file: {path.name}")
            while True:
                chunk = handle.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        fail("source_unreadable", f"cannot read file: {exc.__class__.__name__}")
    return digest.hexdigest(), total


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _run_git(workspace: Path, args: list[str]) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            env=_git_env(),
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _hash_git_diff(workspace: Path, args: list[str]) -> tuple[str | None, int]:
    """Stream `git diff` bytes directly into SHA-256 without buffering large diffs."""
    digest = hashlib.sha256()
    total = 0
    try:
        with subprocess.Popen(
            ["git", "-C", str(workspace), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_env(),
        ) as proc:
            try:
                assert proc.stdout is not None
                while True:
                    chunk = proc.stdout.read(_HASH_CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
                    total += len(chunk)
                rc = proc.wait(timeout=GIT_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                return None, 0
    except OSError:
        return None, 0
    if rc != 0:
        return None, 0
    return digest.hexdigest(), total


def _parse_git_status_porcelain_z(raw_bytes: bytes, internal_prefixes: tuple[str, ...]) -> tuple[bool, int]:
    """Parse `git status --porcelain=v1 -z` excluding untracked Parrhesia internal/log dirs."""
    tokens = raw_bytes.split(b"\x00")
    idx = 0
    tracked_dirty = False
    untracked_count = 0
    while idx < len(tokens):
        entry = tokens[idx]
        idx += 1
        if not entry:
            continue
        text_entry = entry.decode("utf-8", errors="replace")
        if len(text_entry) < 4:
            continue
        xy = text_entry[:2]
        rel_path = text_entry[3:].replace("\\", "/")
        if xy == "??":
            if any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in internal_prefixes):
                continue
            untracked_count += 1
        elif xy == "!!":
            continue
        else:
            tracked_dirty = True
            if xy[0] in ("R", "C"):
                idx += 1
    return tracked_dirty, untracked_count


def collect_git_state(workspace: Path) -> dict:
    """Auto-collect git state cleanly; fall back to `git_available=False` outside git."""
    ws = Path(workspace).resolve(strict=True)
    fallback = {
        "git_available": False,
        "head_sha": None,
        "head_sha12": None,
        "branch": None,
        "detached": False,
        "dirty": False,
        "tracked_dirty": False,
        "working_tree_diff_sha256": None,
        "working_tree_diff_bytes": 0,
        "staged_diff_sha256": None,
        "staged_diff_bytes": 0,
        "untracked_count": 0,
    }
    inside = _run_git(ws, ["rev-parse", "--is-inside-work-tree"])
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != b"true":
        return fallback

    toplevel_proc = _run_git(ws, ["rev-parse", "--show-toplevel"])
    ws_prefix = ""
    if toplevel_proc is not None and toplevel_proc.returncode == 0:
        top_text = toplevel_proc.stdout.decode("utf-8", errors="replace").strip()
        if top_text:
            try:
                rel_ws = ws.relative_to(Path(top_text).resolve()).as_posix()
                if rel_ws not in ("", "."):
                    ws_prefix = rel_ws + "/"
            except (ValueError, OSError):
                pass
    internal_prefixes = (f"{ws_prefix}.parrhesia", f"{ws_prefix}artifacts/exec-logs")

    head_proc = _run_git(ws, ["rev-parse", "--verify", "HEAD"])
    head_sha = (
        head_proc.stdout.decode("utf-8", errors="replace").strip()
        if head_proc is not None and head_proc.returncode == 0
        else None
    ) or None

    branch_proc = _run_git(ws, ["symbolic-ref", "--short", "-q", "HEAD"])
    branch_name = (
        branch_proc.stdout.decode("utf-8", errors="replace").strip()
        if branch_proc is not None and branch_proc.returncode == 0
        else ""
    )
    if branch_name:
        branch: str | None = branch_name
        detached = False
    elif head_sha is not None:
        branch = None
        detached = True
    else:
        branch = None
        detached = False

    status_proc = _run_git(ws, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if status_proc is not None and status_proc.returncode == 0:
        tracked_dirty, untracked_count = _parse_git_status_porcelain_z(status_proc.stdout, internal_prefixes)
    else:
        tracked_dirty, untracked_count = False, 0

    wt_diff_sha256, wt_diff_bytes = _hash_git_diff(ws, ["diff", "--binary"])
    staged_diff_sha256, staged_diff_bytes = _hash_git_diff(ws, ["diff", "--cached", "--binary"])
    dirty = bool(tracked_dirty or untracked_count > 0 or wt_diff_bytes > 0 or staged_diff_bytes > 0)
    return {
        "git_available": True,
        "head_sha": head_sha,
        "head_sha12": head_sha[:12] if head_sha else None,
        "branch": branch,
        "detached": detached,
        "dirty": dirty,
        "tracked_dirty": tracked_dirty,
        "working_tree_diff_sha256": wt_diff_sha256,
        "working_tree_diff_bytes": wt_diff_bytes,
        "staged_diff_sha256": staged_diff_sha256,
        "staged_diff_bytes": staged_diff_bytes,
        "untracked_count": untracked_count,
    }


def _is_lockfile_name(name: str) -> bool:
    return name in LOCKFILE_EXACT_NAMES or fnmatch.fnmatchcase(name, "requirements*.txt")


def discover_lockfiles(workspace: Path) -> list[dict]:
    """Auto-discover and SHA-256 hash top-level workspace dependency/lockfiles safely."""
    ws = Path(workspace).resolve(strict=True)
    discovered: list[dict] = []
    try:
        entries = sorted(ws.iterdir(), key=lambda item: item.name)
    except OSError:
        return discovered
    for entry in entries:
        if not _is_lockfile_name(entry.name):
            continue
        if is_link_or_reparse(entry):
            continue
        try:
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            resolved = entry.resolve(strict=True)
            resolved.relative_to(ws)
            if resolved.parent != ws:
                continue
        except (OSError, ValueError):
            continue
        try:
            digest, size = hash_regular_file(entry)
        except ValueError:
            continue
        discovered.append({"path": entry.name, "sha256": digest, "size": size})
    return discovered


def _sentinel_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def collect_environment_markers() -> dict:
    """Collect safe non-secret runtime and container presence markers only."""
    return {
        "python_version": sys.version.split()[0],
        "python_executable": Path(sys.executable).name if sys.executable else "",
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "virtualenv_active": bool(sys.prefix != sys.base_prefix),
        "dockerenv_present": _sentinel_exists(Path("/.dockerenv")),
        "kubernetes_service_host_present": bool(os.environ.get("KUBERNETES_SERVICE_HOST")),
    }


def validate_input_files(workspace: Path, raw_paths: list[str]) -> list[dict]:
    """Validate and SHA-256 hash declared `--input-file` paths before execution."""
    ws = Path(workspace).resolve(strict=True)
    seen: set[str] = set()
    inputs: list[dict] = []
    for raw_path in raw_paths:
        target = resolve_workspace_path(ws, raw_path)
        rel = target.relative_to(ws).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        try:
            info = target.lstat()
        except FileNotFoundError:
            fail("missing_input_file", f"declared --input-file does not exist: {rel}")
        except OSError as exc:
            fail("source_unreadable", f"cannot inspect --input-file {rel}: {exc.__class__.__name__}")
        if not stat.S_ISREG(info.st_mode):
            fail("invalid_source", f"declared --input-file must be a regular file: {rel}")
        sha256, size = hash_regular_file(target)
        inputs.append({"path": rel, "sha256": sha256, "size": size, "exists": True})
    return inputs


def snapshot_output_files_pre(workspace: Path, raw_paths: list[str]) -> list[dict]:
    """Validate declared `--output-file` paths and record pre-execution snapshots."""
    ws = Path(workspace).resolve(strict=True)
    seen: set[str] = set()
    snapshots: list[dict] = []
    for raw_path in raw_paths:
        target = resolve_workspace_path(ws, raw_path)
        rel = target.relative_to(ws).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        try:
            info = target.lstat()
        except FileNotFoundError:
            snapshots.append({
                "path": rel,
                "pre_exists": False,
                "pre_sha256": None,
                "pre_size": None,
            })
            continue
        except OSError as exc:
            fail("source_unreadable", f"cannot inspect --output-file {rel}: {exc.__class__.__name__}")
        if not stat.S_ISREG(info.st_mode):
            fail("invalid_source", f"declared --output-file must reference a regular file path: {rel}")
        pre_sha256, pre_size = hash_regular_file(target)
        snapshots.append({
            "path": rel,
            "pre_exists": True,
            "pre_sha256": pre_sha256,
            "pre_size": pre_size,
        })
    return snapshots


def snapshot_output_files_post(workspace: Path, pre_snapshots: list[dict]) -> list[dict]:
    """Verify post-execution `--output-file` presence, SHA-256, and delta/unchanged status."""
    ws = Path(workspace).resolve(strict=True)
    results: list[dict] = []
    for pre in pre_snapshots:
        rel = pre["path"]
        target = resolve_workspace_path(ws, rel)
        try:
            info = target.lstat()
        except FileNotFoundError:
            results.append({
                "path": rel,
                "status": "missing",
                "exists": False,
                "changed": bool(pre["pre_exists"]),
                "sha256": None,
                "size": None,
                "pre_exists": pre["pre_exists"],
                "pre_sha256": pre["pre_sha256"],
                "pre_size": pre["pre_size"],
                "delta_bytes": None,
            })
            continue
        except OSError as exc:
            fail("source_unreadable", f"cannot inspect --output-file {rel}: {exc.__class__.__name__}")
        if not stat.S_ISREG(info.st_mode):
            fail("invalid_source", f"declared --output-file is not a regular file after execution: {rel}")
        sha256, size = hash_regular_file(target)
        if not pre["pre_exists"]:
            status = "created"
            changed = True
            delta_bytes = size
        elif sha256 != pre["pre_sha256"]:
            status = "modified"
            changed = True
            delta_bytes = size - pre["pre_size"]
        else:
            status = "unchanged"
            changed = False
            delta_bytes = 0
        results.append({
            "path": rel,
            "status": status,
            "exists": True,
            "changed": changed,
            "sha256": sha256,
            "size": size,
            "pre_exists": pre["pre_exists"],
            "pre_sha256": pre["pre_sha256"],
            "pre_size": pre["pre_size"],
            "delta_bytes": delta_bytes,
        })
    return results


def sanitize_stdout_excerpt(
    stdout_text: str,
    max_chars: int = DEFAULT_STDOUT_EXCERPT_CHARS,
) -> tuple[str, bool, int]:
    """Return (single_line_excerpt, truncated, effective_max_chars) safe for log headers/quotes."""
    if type(max_chars) is not int or max_chars < 0:
        fail("invalid_value", "--stdout-excerpt-chars must be a non-negative integer")
    effective_max = min(max_chars, MAX_STDOUT_EXCERPT_CHARS)
    cleaned = strip_terminal_escapes(stdout_text or "")
    cleaned = "".join(
        " " if ch in "\r\n\t" else ch
        for ch in cleaned
        if ch in "\r\n\t" or (ord(ch) >= 32 and ord(ch) != 127 and unicodedata.category(ch) != "Cc")
    )
    normalized = re.sub(r"\s+", " ", cleaned).strip()
    if effective_max == 0:
        return "", bool(normalized), effective_max
    if len(normalized) <= effective_max:
        return normalized, False, effective_max
    if effective_max >= 4:
        return normalized[:effective_max - 3].rstrip() + "...", True, effective_max
    return normalized[:effective_max], True, effective_max


def compute_stream_provenance(
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    stdout_text: str,
    *,
    excerpt_chars: int = DEFAULT_STDOUT_EXCERPT_CHARS,
) -> dict:
    """Compute stdout/stderr SHA-256 digests and bounded sanitized stdout excerpt."""
    excerpt, truncated, effective_max = sanitize_stdout_excerpt(stdout_text, max_chars=excerpt_chars)
    return {
        "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
        "stdout_bytes": len(stdout_bytes),
        "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
        "stderr_bytes": len(stderr_bytes),
        "stdout_excerpt": excerpt,
        "stdout_excerpt_chars": len(excerpt),
        "stdout_excerpt_max_chars": effective_max,
        "stdout_excerpt_truncated": truncated,
    }


def _cap_summary(text: str, maximum: int = MAX_DETAIL_SUMMARY_CHARS) -> str:
    if len(text) <= maximum:
        return text
    return text[:maximum - 3] + "..."


def synthesize_code_version(git_state: dict, lockfiles: list[dict]) -> str:
    """Build a schema-valid non-empty `code_version` string from git/lockfile state."""
    lock_summary = ", ".join(f"{item['path']}:{item['sha256'][:12]}" for item in lockfiles)
    if git_state.get("git_available"):
        sha_tag = git_state.get("head_sha12") or "unborn"
        wt_bytes = git_state.get("working_tree_diff_bytes", 0)
        staged_bytes = git_state.get("staged_diff_bytes", 0)
        wt_sha = git_state.get("working_tree_diff_sha256")
        staged_sha = git_state.get("staged_diff_sha256")
        untracked = git_state.get("untracked_count", 0)
        if wt_bytes > 0 and wt_sha:
            state_part = f"dirty_diff={wt_sha[:12]}"
        elif staged_bytes > 0 and staged_sha:
            state_part = f"staged_diff={staged_sha[:12]}"
        elif untracked > 0:
            state_part = f"untracked={untracked}"
        elif git_state.get("dirty"):
            state_part = "dirty"
        else:
            state_part = "clean"
        base = f"git:{sha_tag}({state_part})"
        if lock_summary:
            return _cap_summary(f"{base}; lockfiles={lock_summary}")
        return _cap_summary(base)
    if lock_summary:
        return _cap_summary(f"workspace-local(lockfiles={lock_summary})")
    return "workspace-local(no-git,no-lockfiles)"


def synthesize_inputs_summary(input_files: list[dict], lockfiles: list[dict]) -> str:
    """Build a schema-valid non-empty `inputs` string from hashed inputs and lockfiles."""
    parts: list[str] = []
    if input_files:
        items = ", ".join(f"{item['path']}(sha256={item['sha256'][:12]})" for item in input_files)
        parts.append(f"files=[{items}]")
    if lockfiles:
        items = ", ".join(f"{item['path']}(sha256={item['sha256'][:12]})" for item in lockfiles)
        parts.append(f"lockfiles=[{items}]")
    if parts:
        return _cap_summary("; ".join(parts))
    return "workspace(no-declared-inputs)"


def synthesize_outputs_summary(
    output_files: list[dict],
    rel_log_path: str,
    log_sha256: str,
    stdout_sha256: str,
    stderr_sha256: str,
) -> str:
    """Build a schema-valid non-empty `outputs` string from output snapshots and digests."""
    stream_part = (
        f"log={rel_log_path}(sha256={log_sha256[:12]}), "
        f"stdout_sha256={stdout_sha256[:12]}, stderr_sha256={stderr_sha256[:12]}"
    )
    if not output_files:
        return _cap_summary(stream_part)
    out_items = [
        f"{item['path']}(missing)"
        if item["status"] == "missing"
        else f"{item['path']}(status={item['status']},sha256={item['sha256'][:12] if item.get('sha256') else 'UNKNOWN'})"
        for item in output_files
    ]
    return _cap_summary(f"files=[{', '.join(out_items)}]; {stream_part}")


def format_environment_description(env_markers: dict) -> str:
    """Format safe non-secret environment markers into an execution card string."""
    return (
        f"Python {env_markers['python_version']} "
        f"({env_markers['python_executable']}; "
        f"{env_markers['os']} {env_markers['os_release']} {env_markers['architecture']}; "
        f"venv={env_markers['virtualenv_active']}; "
        f"docker={env_markers['dockerenv_present']}; "
        f"k8s={env_markers['kubernetes_service_host_present']})"
    )
