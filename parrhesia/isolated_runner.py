"""OS-process isolated reviewer/adjudicator runner with scrubbed environment and workspace HMAC seal.

Pure stdlib. Never makes network calls or invokes paid APIs on its own; executes a
user-supplied local command inside a fresh ephemeral sandbox directory containing ONLY
the frozen role packet (`packet.json`) and role instructions (`instructions.txt`), with
all non-essential parent environment variables scrubbed, hashes the raw child transcript,
and seals the resulting `isolation_receipt` with a workspace-local HMAC key that the child
subprocess never sees.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from .contracts import ContractError, enum, fail
from .core import Engine
from .isolation import (
    OS_SANDBOX_MODES,
    PACKET_STAGES,
    compute_runner_seal,
    ensure_runner_key,
    packet_content_sha256,
    validate_stage1_estimates,
)
from .storage import canonical_json, utc_now

ISOLATED_ROLES = ("overclaim", "underclaim", "adjudication")

# Minimal OS execution environment allowlist — strips parent chat/memory/agent/secret vars.
_SAFE_BASE_ENV_KEYS = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "OS",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
)

# Protocol, config-directory, and dynamic-loader/code-injection vars cannot be injected via allow_env.
_RESERVED_RUNNER_ENV_KEYS = frozenset({
    "PARRHESIA_ISOLATED_RUNNER",
    "PARRHESIA_CASE_ID",
    "PARRHESIA_ROLE",
    "PARRHESIA_PACKET_PATH",
    "PARRHESIA_INSTRUCTIONS_PATH",
    "PARRHESIA_PACKET_NONCE",
    "PARRHESIA_PACKET_SHA256",
    "PARRHESIA_TOOL_PROFILE",
    "PARRHESIA_PARENT_HISTORY_MESSAGES",
    "PARRHESIA_MEMORY_ENABLED",
    "PARRHESIA_WORKSPACE",
    "PARRHESIA_RUNNER_KEY",
    "PARRHESIA_PACKET_STAGE",
    "PARRHESIA_TWO_STAGE_BLIND",
    "PARRHESIA_STAGE1_ESTIMATES_PATH",
    "PARRHESIA_STAGE1_ESTIMATE_SHA256",
    "PARRHESIA_SANDBOX_MODE",
    "PARRHESIA_OFFLINE_ENV",
    "HOME",
    "USERPROFILE",
    "TMP",
    "TEMP",
    "TMPDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
})
_RESERVED_RUNNER_ENV_KEYS_UPPER = frozenset(k.upper() for k in _RESERVED_RUNNER_ENV_KEYS)


def build_scrubbed_env(
    *,
    sandbox_dir: Path,
    packet_path: Path,
    instructions_path: Path,
    case_id: str,
    role: str,
    packet_nonce: str,
    packet_sha256: str,
    tool_profile: str,
    allow_env: list[str] | tuple[str, ...] = (),
    offline_env: bool = False,
    sandbox_mode: str = "standard",
    packet_stage: str = "full",
    two_stage_blind: bool = False,
    stage1_estimates_path: Path | None = None,
    stage1_estimate_sha256: str | None = None,
) -> dict[str, str]:
    """Build a minimal scrubbed subprocess environment stripped of parent session/secret/loader variables."""
    env: dict[str, str] = {}
    for key in _SAFE_BASE_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    for extra in allow_env:
        name = str(extra).strip()
        upper = name.upper()
        if (
            not name
            or upper in _RESERVED_RUNNER_ENV_KEYS_UPPER
            or upper.startswith(("PARRHESIA_RUNNER_", "PARRHESIA_TWO_STAGE_", "PARRHESIA_STAGE1_"))
        ):
            continue
        val = os.environ.get(name)
        if val is not None:
            env[name] = val

    # Isolate temp/home/XDG/AppData directories into the ephemeral sandbox so child tools do not read host caches.
    sand_tmp = sandbox_dir / "tmp"
    sand_home = sandbox_dir / "home"
    sand_appdata = sand_home / "AppData" / "Roaming"
    sand_local_appdata = sand_home / "AppData" / "Local"
    xdg_cfg = sand_home / ".config"
    xdg_cache = sand_home / ".cache"
    xdg_data = sand_home / ".local" / "share"
    xdg_state = sand_home / ".local" / "state"
    for folder in (sand_tmp, sand_home, sand_appdata, sand_local_appdata, xdg_cfg, xdg_cache, xdg_data, xdg_state):
        folder.mkdir(parents=True, exist_ok=True)
    env["TMP"] = str(sand_tmp)
    env["TEMP"] = str(sand_tmp)
    env["TMPDIR"] = str(sand_tmp)
    env["HOME"] = str(sand_home)
    env["USERPROFILE"] = str(sand_home)
    env["APPDATA"] = str(sand_appdata)
    env["LOCALAPPDATA"] = str(sand_local_appdata)
    env["XDG_CONFIG_HOME"] = str(xdg_cfg)
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["XDG_DATA_HOME"] = str(xdg_data)
    env["XDG_STATE_HOME"] = str(xdg_state)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    if offline_env:
        for pkey in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
            env[pkey] = "http://127.0.0.1:9"
        env["NO_PROXY"] = ""
        env["no_proxy"] = ""
        env["PARRHESIA_OFFLINE_ENV"] = "1"
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["PIP_NO_INDEX"] = "1"

    # Explicit read-only packet metadata for the isolated reviewer adapter.
    env["PARRHESIA_ISOLATED_RUNNER"] = "1"
    env["PARRHESIA_CASE_ID"] = case_id
    env["PARRHESIA_ROLE"] = role
    env["PARRHESIA_PACKET_PATH"] = str(packet_path)
    env["PARRHESIA_INSTRUCTIONS_PATH"] = str(instructions_path)
    env["PARRHESIA_PACKET_NONCE"] = packet_nonce
    env["PARRHESIA_PACKET_SHA256"] = packet_sha256
    env["PARRHESIA_TOOL_PROFILE"] = tool_profile
    env["PARRHESIA_PARENT_HISTORY_MESSAGES"] = "0"
    env["PARRHESIA_MEMORY_ENABLED"] = "false"
    env["PARRHESIA_PACKET_STAGE"] = packet_stage
    env["PARRHESIA_SANDBOX_MODE"] = sandbox_mode
    if two_stage_blind:
        env["PARRHESIA_TWO_STAGE_BLIND"] = "1"
    if stage1_estimates_path is not None:
        env["PARRHESIA_STAGE1_ESTIMATES_PATH"] = str(stage1_estimates_path)
    if stage1_estimate_sha256 is not None:
        env["PARRHESIA_STAGE1_ESTIMATE_SHA256"] = stage1_estimate_sha256
    return env


def _detect_os_sandbox_backend() -> str | None:
    if sys.platform.startswith("linux"):
        return "bwrap" if shutil.which("bwrap") else None
    if sys.platform == "darwin":
        return "sandbox-exec" if shutil.which("sandbox-exec") else None
    return None


def _resolve_os_sandbox(sandbox_mode: str) -> str:
    mode = enum(sandbox_mode, OS_SANDBOX_MODES, "sandbox_mode")
    if mode == "standard":
        return "none"
    backend = _detect_os_sandbox_backend()
    if backend is None:
        fail(
            "sandbox_unavailable",
            f"sandbox_mode='strict_os' requires 'bwrap' (Linux) or 'sandbox-exec' (macOS), which is unavailable on {sys.platform}",
        )
    return backend


def _wrap_os_sandbox_cmd(
    cmd: list[str],
    *,
    sandbox_dir: Path,
    backend: str,
    offline_env: bool,
) -> list[str]:
    if backend == "none":
        return list(cmd)
    if backend == "bwrap":
        wrapped = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--bind", str(sandbox_dir), str(sandbox_dir),
            "--chdir", str(sandbox_dir),
            "--die-with-parent",
        ]
        if offline_env:
            wrapped.append("--unshare-net")
        wrapped.append("--")
        wrapped.extend(cmd)
        return wrapped
    if backend == "sandbox-exec":
        s_path = str(sandbox_dir.resolve()).replace("\\", "\\\\").replace('"', '\\"')
        net_rule = "(deny network*)\n" if offline_env else ""
        profile = (
            "(version 1)\n"
            "(allow default)\n"
            f"{net_rule}"
            "(deny file-write*)\n"
            f'(allow file-write* (subpath "{s_path}"))\n'
            '(allow file-write* (literal "/dev/null"))\n'
        )
        return ["sandbox-exec", "-p", profile, *cmd]
    fail("sandbox_unavailable", f"Unsupported OS sandbox backend: {backend}")


def _snapshot_workspace_state(workspace: Path | None) -> dict[str, tuple[bool, int | None, str | None]] | None:
    if workspace is None:
        return None
    state_dir = workspace.resolve() / ".parrhesia"
    snap: dict[str, tuple[bool, int | None, str | None]] = {}
    for rel in ("state.sqlite3", "state.sqlite3-wal", "runner.key"):
        fpath = state_dir / rel
        if fpath.is_symlink():
            snap[rel] = (True, -1, None)
        elif fpath.is_file():
            raw = fpath.read_bytes()
            snap[rel] = (True, len(raw), hashlib.sha256(raw).hexdigest())
        else:
            snap[rel] = (False, None, None)
    return snap


def _cleanup_sandbox_dir(sandbox_dir: Path) -> None:
    if not sandbox_dir.exists():
        return
    try:
        items = [sandbox_dir, *sandbox_dir.rglob("*")]
    except OSError:
        items = [sandbox_dir]
    for item in items:
        try:
            mode = 0o700 if item.is_dir() else 0o600
            os.chmod(item, mode)
        except OSError:
            pass
    shutil.rmtree(sandbox_dir, ignore_errors=True)


def _extract_json_payload(stdout_text: str) -> dict[str, Any]:
    """Parse JSON object from child stdout (accepts raw JSON or last fenced ```json block)."""
    stripped = stdout_text.strip()
    if not stripped:
        fail("invalid_json", "Isolated child subprocess produced empty stdout; expected a JSON submission object")
    try:
        parsed = json.loads(stripped, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    # Fallback: extract last ```json ... ``` fenced block if an adapter wrapped its JSON output.
    marker = "```json"
    if marker in stripped:
        tail = stripped.rsplit(marker, 1)[-1]
        if "```" in tail:
            body = tail.split("```", 1)[0].strip()
            try:
                parsed = json.loads(body, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
    fail("invalid_json", "Isolated child subprocess stdout did not contain a valid JSON object")


def _execute_role_sandbox(
    packet: dict[str, Any],
    seal_key: bytes,
    *,
    case_id: str,
    role: str,
    cmd: list[str],
    runner_name: str = "parrhesia-subprocess-runner",
    model_route: str | None = None,
    timeout: float = 120.0,
    allow_env: list[str] | tuple[str, ...] = (),
    keep_sandbox: bool = False,
    workspace: Path | None = None,
    sandbox_mode: str = "standard",
    os_sandbox_backend: str | None = None,
    offline_env: bool = False,
    packet_stage: str = "full",
    two_stage_blind: bool = False,
    stage1_locked_estimates: dict[str, Any] | None = None,
    stage1_estimate_sha256: str | None = None,
    stage1_transcript_sha256: str | None = None,
    seal_receipt: bool = True,
) -> dict[str, Any]:
    """Run a single command inside an ephemeral sandbox directory for one pre-fetched role packet."""
    enum(role, ISOLATED_ROLES, "role")
    enum(packet_stage, PACKET_STAGES, "packet_stage")
    if not cmd:
        fail("missing_field", "Isolated runner requires a non-empty command")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        fail("invalid_value", "timeout must be finite and greater than zero")

    backend = os_sandbox_backend if os_sandbox_backend is not None else _resolve_os_sandbox(sandbox_mode)
    pkt_sha = packet_content_sha256(packet)
    pkt_nonce = packet.get("packet_nonce")
    if not isinstance(pkt_nonce, str) or not pkt_nonce:
        fail("invalid_state", "Role packet is missing packet_nonce")
    expected_profile = "adjudication" if role == "adjudication" else "review"

    stage_prefix = f"parrhesia-iso-{role}-s1-" if packet_stage == "evidence_only" else f"parrhesia-iso-{role}-"
    sandbox_dir = Path(tempfile.mkdtemp(prefix=stage_prefix))
    started_at = utc_now()
    try:
        packet_path = sandbox_dir / "packet.json"
        instructions_path = sandbox_dir / "instructions.txt"
        packet_bytes = (json.dumps(packet, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        inst_text = str(packet.get("instructions") or "")
        s1_est_path: Path | None = None
        staged_expected: list[tuple[Path, bytes]] = []
        if stage1_locked_estimates is not None:
            s1_est_path = sandbox_dir / "stage1_locked_estimates.json"
            s1_bytes = (json.dumps(stage1_locked_estimates, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
            s1_est_path.write_bytes(s1_bytes)
            staged_expected.append((s1_est_path, s1_bytes))
            inst_text += (
                f"\n\nSTAGE 2 BLIND REVEAL WITH LOCKED STAGE 1 ESTIMATES: Your evidence-only Stage 1 "
                f"estimates (sha256={stage1_estimate_sha256}) are staged read-only at "
                "PARRHESIA_STAGE1_ESTIMATES_PATH. Compare author claims against your locked Stage 1 judgment."
            )
        inst_bytes = (inst_text + "\n").encode("utf-8")
        packet_path.write_bytes(packet_bytes)
        instructions_path.write_bytes(inst_bytes)
        staged_expected.extend([(packet_path, packet_bytes), (instructions_path, inst_bytes)])
        for staged_file, _ in staged_expected:
            try:
                os.chmod(staged_file, 0o444)
            except OSError:
                pass

        scrubbed_env = build_scrubbed_env(
            sandbox_dir=sandbox_dir,
            packet_path=packet_path,
            instructions_path=instructions_path,
            case_id=case_id,
            role=role,
            packet_nonce=pkt_nonce,
            packet_sha256=pkt_sha,
            tool_profile=expected_profile,
            allow_env=allow_env,
            offline_env=offline_env,
            sandbox_mode=sandbox_mode,
            packet_stage=packet_stage,
            two_stage_blind=two_stage_blind,
            stage1_estimates_path=s1_est_path,
            stage1_estimate_sha256=stage1_estimate_sha256,
        )
        run_cmd = _wrap_os_sandbox_cmd(list(cmd), sandbox_dir=sandbox_dir, backend=backend, offline_env=offline_env)
        ws_before = _snapshot_workspace_state(workspace)
        popen_kwargs: dict[str, Any] = {
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.run(
                run_cmd,
                input=packet_bytes,
                capture_output=True,
                cwd=str(sandbox_dir),
                env=scrubbed_env,
                timeout=timeout,
                check=False,
                **popen_kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            ended_at = utc_now()
            out_b = exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode("utf-8")
            err_b = exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr or "").encode("utf-8")
            transcript_sha = hashlib.sha256(out_b + b"\n---STDERR---\n" + err_b).hexdigest()
            return {
                "case_id": case_id,
                "role": role,
                "packet_stage": packet_stage,
                "termination_status": "timed_out",
                "exit_status": None,
                "started_at": started_at,
                "ended_at": ended_at,
                "transcript_sha256": transcript_sha,
                "os_sandbox": backend,
                "submitted": False,
                "error": "timed_out",
                "message": f"Isolated child command timed out after {timeout:g}s",
            }
        except OSError as exc:
            ended_at = utc_now()
            return {
                "case_id": case_id,
                "role": role,
                "packet_stage": packet_stage,
                "termination_status": "start_failed",
                "exit_status": None,
                "started_at": started_at,
                "ended_at": ended_at,
                "os_sandbox": backend,
                "submitted": False,
                "error": "start_failed",
                "message": f"Failed to start isolated child command: {exc}",
            }

        ended_at = utc_now()
        stdout_b = proc.stdout or b""
        stderr_b = proc.stderr or b""
        transcript_sha = hashlib.sha256(stdout_b + b"\n---STDERR---\n" + stderr_b).hexdigest()
        stdout_text = stdout_b.decode("utf-8", errors="replace")
        stderr_text = stderr_b.decode("utf-8", errors="replace")

        ws_after = _snapshot_workspace_state(workspace)
        ws_untouched: bool | None = None
        if ws_before is not None and ws_after is not None:
            ws_untouched = (ws_before == ws_after)
            if not ws_untouched:
                return {
                    "case_id": case_id,
                    "role": role,
                    "packet_stage": packet_stage,
                    "termination_status": "sandbox_boundary_violation",
                    "exit_status": proc.returncode,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "transcript_sha256": transcript_sha,
                    "workspace_untouched": False,
                    "os_sandbox": backend,
                    "submitted": False,
                    "error": "sandbox_boundary_violation",
                    "message": "Workspace critical state (.parrhesia/state.sqlite3, -wal, or runner.key) was modified during isolated child execution.",
                }

        for staged_file, expected_bytes in staged_expected:
            try:
                tampered = staged_file.is_symlink() or not staged_file.is_file() or staged_file.read_bytes() != expected_bytes
            except OSError:
                tampered = True
            if tampered:
                return {
                    "case_id": case_id,
                    "role": role,
                    "packet_stage": packet_stage,
                    "termination_status": "sandbox_boundary_violation",
                    "exit_status": proc.returncode,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "transcript_sha256": transcript_sha,
                    "workspace_untouched": ws_untouched,
                    "os_sandbox": backend,
                    "submitted": False,
                    "error": "sandbox_boundary_violation",
                    "message": f"Read-only staged sandbox file {staged_file.name!r} was modified during child execution.",
                }

        if proc.returncode != 0:
            return {
                "case_id": case_id,
                "role": role,
                "packet_stage": packet_stage,
                "termination_status": "failed_exit",
                "exit_status": proc.returncode,
                "started_at": started_at,
                "ended_at": ended_at,
                "transcript_sha256": transcript_sha,
                "os_sandbox": backend,
                "workspace_untouched": ws_untouched,
                "stderr_excerpt": stderr_text[:1000],
                "submitted": False,
                "error": "child_nonzero_exit",
                "message": f"Isolated child exited with status {proc.returncode}",
            }

        raw_output = _extract_json_payload(stdout_text)
        if not seal_receipt:
            out_s1: dict[str, Any] = {
                "case_id": case_id,
                "role": role,
                "packet_stage": packet_stage,
                "termination_status": "completed",
                "exit_status": 0,
                "started_at": started_at,
                "ended_at": ended_at,
                "packet_sha256": pkt_sha,
                "packet_nonce": pkt_nonce,
                "transcript_sha256": transcript_sha,
                "os_sandbox": backend,
                "workspace_untouched": ws_untouched,
                "raw_output": raw_output,
                "submitted": False,
            }
            if keep_sandbox:
                out_s1["sandbox_dir"] = str(sandbox_dir)
            return out_s1

        submission = raw_output
        # Bind immutable frozen packet identifiers so the child cannot redirect submissions.
        submission["case_id"] = case_id
        submission["input_digest"] = packet["input_digest"]
        if role == "adjudication":
            submission["adjudication_id"] = packet["adjudication_id"]
        else:
            submission["role"] = role
            submission["packet_id"] = packet["packet_id"]

        receipt_core: dict[str, Any] = {
            "runner": runner_name,
            "packet_nonce": pkt_nonce,
            "packet_sha256": pkt_sha,
            "parent_history_messages": 0,
            "memory_enabled": False,
            "tool_profile": expected_profile,
            "transcript_sha256": transcript_sha,
            "env_scrubbed": True,
            "isolated_cwd": True,
            "exit_status": int(proc.returncode),
            "os_sandbox": backend,
        }
        if ws_untouched is not None:
            receipt_core["workspace_untouched"] = ws_untouched
        if two_stage_blind and stage1_estimate_sha256 and stage1_transcript_sha256:
            receipt_core["two_stage_blind"] = True
            receipt_core["stage1_estimate_sha256"] = stage1_estimate_sha256
            receipt_core["stage1_transcript_sha256"] = stage1_transcript_sha256
        if model_route:
            receipt_core["model_route"] = model_route
        receipt_core["runner_seal"] = compute_runner_seal(seal_key, receipt_core)
        submission["isolation_receipt"] = receipt_core

        result: dict[str, Any] = {
            "case_id": case_id,
            "role": role,
            "termination_status": "completed",
            "exit_status": 0,
            "started_at": started_at,
            "ended_at": ended_at,
            "packet_sha256": pkt_sha,
            "packet_nonce": pkt_nonce,
            "transcript_sha256": transcript_sha,
            "env_scrubbed": True,
            "isolated_cwd": True,
            "os_sandbox": backend,
            "workspace_untouched": ws_untouched,
            "isolation_receipt": receipt_core,
            "submission_payload": submission,
            "submitted": False,
        }
        if two_stage_blind and stage1_estimate_sha256 and stage1_transcript_sha256:
            result.update({
                "two_stage_blind": True,
                "stage1_estimate_sha256": stage1_estimate_sha256,
                "stage1_transcript_sha256": stage1_transcript_sha256,
                "stage1_locked_estimates": stage1_locked_estimates,
            })
        if keep_sandbox:
            result["sandbox_dir"] = str(sandbox_dir)
        return result
    finally:
        if not keep_sandbox:
            _cleanup_sandbox_dir(sandbox_dir)


def _execute_two_stage_role(
    stage1_packet: dict[str, Any],
    stage2_packet: dict[str, Any],
    claim_ids: set[str],
    seal_key: bytes,
    *,
    case_id: str,
    role: str,
    stage1_cmd: list[str],
    stage2_cmd: list[str],
    runner_name: str,
    model_route: str | None,
    timeout: float,
    allow_env: list[str] | tuple[str, ...],
    keep_sandbox: bool,
    workspace: Path,
    sandbox_mode: str,
    os_sandbox_backend: str,
    offline_env: bool,
) -> dict[str, Any]:
    """Execute Stage 1 (evidence_only) lock, then Stage 2 (full) reveal in separate sandboxes."""
    s1_res = _execute_role_sandbox(
        stage1_packet,
        seal_key,
        case_id=case_id,
        role=role,
        cmd=stage1_cmd,
        runner_name=runner_name,
        model_route=model_route,
        timeout=timeout,
        allow_env=allow_env,
        keep_sandbox=keep_sandbox,
        workspace=workspace,
        sandbox_mode=sandbox_mode,
        os_sandbox_backend=os_sandbox_backend,
        offline_env=offline_env,
        packet_stage="evidence_only",
        two_stage_blind=True,
        seal_receipt=False,
    )
    if s1_res.get("termination_status") != "completed":
        return s1_res

    s1_norm = validate_stage1_estimates(
        s1_res["raw_output"],
        claim_ids=claim_ids,
        expected_nonce=stage1_packet["packet_nonce"],
        expected_packet_sha256=s1_res["packet_sha256"],
        label=f"{role}.stage1_estimates",
    )
    s1_est_sha = hashlib.sha256(canonical_json(s1_norm).encode("utf-8")).hexdigest()
    s1_tsha = s1_res["transcript_sha256"]

    s2_res = _execute_role_sandbox(
        stage2_packet,
        seal_key,
        case_id=case_id,
        role=role,
        cmd=stage2_cmd,
        runner_name=runner_name,
        model_route=model_route,
        timeout=timeout,
        allow_env=allow_env,
        keep_sandbox=keep_sandbox,
        workspace=workspace,
        sandbox_mode=sandbox_mode,
        os_sandbox_backend=os_sandbox_backend,
        offline_env=offline_env,
        packet_stage="full",
        two_stage_blind=True,
        stage1_locked_estimates=s1_norm,
        stage1_estimate_sha256=s1_est_sha,
        stage1_transcript_sha256=s1_tsha,
        seal_receipt=True,
    )
    if keep_sandbox and "sandbox_dir" in s1_res:
        s2_res["stage1_sandbox_dir"] = s1_res["sandbox_dir"]
    return s2_res


def run_isolated_subprocess(
    workspace: str | Path,
    case_id: str,
    role: str,
    cmd: list[str],
    *,
    runner_name: str = "parrhesia-subprocess-runner",
    model_route: str | None = None,
    timeout: float = 120.0,
    allow_env: list[str] | tuple[str, ...] = (),
    auto_submit: bool = False,
    keep_sandbox: bool = False,
    two_stage_blind: bool = False,
    stage1_cmd: list[str] | None = None,
    sandbox_mode: str = "standard",
    offline_env: bool = False,
) -> dict[str, Any]:
    """Execute a reviewer or adjudicator command in a physically isolated sandbox and seal its receipt."""
    enum(role, ISOLATED_ROLES, "role")
    if not cmd:
        fail("missing_field", "run-isolated requires a command to execute after '--'")
    if two_stage_blind and role == "adjudication":
        fail("invalid_value", "two_stage_blind applies only to reviewer roles ('overclaim', 'underclaim')")
    backend = _resolve_os_sandbox(sandbox_mode)
    ws = Path(workspace).resolve()
    engine = Engine(ws)
    packet = engine.get_packet(case_id, role, stage="full")
    # Ensure workspace-local HMAC key exists BEFORE launching child; never expose path or key to child.
    seal_key = ensure_runner_key(ws)

    if two_stage_blind:
        case_doc = engine.dispatch("get_case", {"case_id": case_id})
        claim_ids = {c["id"] for c in (case_doc.get("claims") or ())}
        s1_packet = engine.get_packet(case_id, role, stage="evidence_only")
        result = _execute_two_stage_role(
            s1_packet,
            packet,
            claim_ids,
            seal_key,
            case_id=case_id,
            role=role,
            stage1_cmd=list(stage1_cmd or cmd),
            stage2_cmd=list(cmd),
            runner_name=runner_name,
            model_route=model_route,
            timeout=timeout,
            allow_env=allow_env,
            keep_sandbox=keep_sandbox,
            workspace=ws,
            sandbox_mode=sandbox_mode,
            os_sandbox_backend=backend,
            offline_env=offline_env,
        )
    else:
        result = _execute_role_sandbox(
            packet,
            seal_key,
            case_id=case_id,
            role=role,
            cmd=cmd,
            runner_name=runner_name,
            model_route=model_route,
            timeout=timeout,
            allow_env=allow_env,
            keep_sandbox=keep_sandbox,
            workspace=ws,
            sandbox_mode=sandbox_mode,
            os_sandbox_backend=backend,
            offline_env=offline_env,
        )
    if result.get("termination_status") == "completed" and auto_submit:
        action = "submit_adjudication" if role == "adjudication" else "submit_review"
        try:
            submitted_res = engine.dispatch(action, result["submission_payload"])
            result["submitted"] = True
            result["submission_result"] = submitted_res
            if role == "adjudication":
                result["isolation_grade"] = (submitted_res.get("adjudication") or {}).get("isolation_grade")
            else:
                result["isolation_grade"] = (submitted_res.get("review") or {}).get("isolation_grade")
        except ContractError as exc:
            result["submitted"] = False
            result["submission_error"] = exc.as_dict()
    return result


def _role_audit_entry(
    res: dict[str, Any] | None,
    *,
    persisted_record: dict[str, Any] | None = None,
    model_route: str | None = None,
) -> dict[str, Any] | None:
    if res is None:
        return None
    rec = (persisted_record or {}).get("isolation_receipt") or res.get("isolation_receipt") or {}
    ig = (persisted_record or {}).get("isolation_grade") or res.get("isolation_grade")
    entry: dict[str, Any] = {
        "termination_status": res.get("termination_status"),
        "submitted": bool(res.get("submitted", False)),
        "grade": ig.get("grade") if isinstance(ig, dict) else None,
        "runner_seal_verified": bool(rec.get("runner_seal_verified", False)),
        "env_scrubbed": bool(rec.get("env_scrubbed", res.get("env_scrubbed", False))),
        "isolated_cwd": bool(rec.get("isolated_cwd", res.get("isolated_cwd", False))),
        "two_stage_blind": bool(rec.get("two_stage_blind", res.get("two_stage_blind", False))),
        "os_sandbox": rec.get("os_sandbox", res.get("os_sandbox", "none")),
        "workspace_untouched": rec.get("workspace_untouched", res.get("workspace_untouched")),
        "transcript_sha256": res.get("transcript_sha256"),
        "packet_sha256": res.get("packet_sha256"),
        "model_route": model_route,
    }
    if rec.get("stage1_estimate_sha256") or res.get("stage1_estimate_sha256"):
        entry["stage1_estimate_sha256"] = rec.get("stage1_estimate_sha256") or res.get("stage1_estimate_sha256")
    if rec.get("stage1_transcript_sha256") or res.get("stage1_transcript_sha256"):
        entry["stage1_transcript_sha256"] = rec.get("stage1_transcript_sha256") or res.get("stage1_transcript_sha256")
    if isinstance(ig, dict) and "boundaries" in ig:
        entry["boundaries"] = ig["boundaries"]
    return entry


def _run_role_safe(
    packet: dict[str, Any],
    seal_key: bytes,
    *,
    case_id: str,
    role: str,
    cmd: list[str],
    runner_name: str,
    model_route: str | None,
    timeout: float,
    allow_env: list[str] | tuple[str, ...],
    keep_sandbox: bool,
    workspace: Path | None = None,
    sandbox_mode: str = "standard",
    os_sandbox_backend: str | None = None,
    offline_env: bool = False,
    two_stage_blind: bool = False,
    stage1_packet: dict[str, Any] | None = None,
    stage1_cmd: list[str] | None = None,
    claim_ids: set[str] | None = None,
) -> dict[str, Any]:
    try:
        if two_stage_blind and stage1_packet is not None and workspace is not None:
            return _execute_two_stage_role(
                stage1_packet,
                packet,
                claim_ids or set(),
                seal_key,
                case_id=case_id,
                role=role,
                stage1_cmd=list(stage1_cmd or cmd),
                stage2_cmd=list(cmd),
                runner_name=runner_name,
                model_route=model_route,
                timeout=timeout,
                allow_env=allow_env,
                keep_sandbox=keep_sandbox,
                workspace=workspace,
                sandbox_mode=sandbox_mode,
                os_sandbox_backend=os_sandbox_backend or "none",
                offline_env=offline_env,
            )
        return _execute_role_sandbox(
            packet,
            seal_key,
            case_id=case_id,
            role=role,
            cmd=cmd,
            runner_name=runner_name,
            model_route=model_route,
            timeout=timeout,
            allow_env=allow_env,
            keep_sandbox=keep_sandbox,
            workspace=workspace,
            sandbox_mode=sandbox_mode,
            os_sandbox_backend=os_sandbox_backend,
            offline_env=offline_env,
        )
    except ContractError as exc:
        return {
            "case_id": case_id,
            "role": role,
            "termination_status": "invalid_output",
            "exit_status": 0,
            "submitted": False,
            "error": exc.code,
            "message": exc.message,
        }


def run_isolated_dual_review(
    workspace: str | Path,
    case_id: str,
    *,
    overclaim_cmd: list[str],
    underclaim_cmd: list[str],
    adjudicator_cmd: list[str] | None = None,
    runner_name: str = "parrhesia-dual-subprocess-runner",
    overclaim_model_route: str | None = None,
    underclaim_model_route: str | None = None,
    adjudicator_model_route: str | None = None,
    timeout: float = 120.0,
    allow_env: list[str] | tuple[str, ...] = (),
    auto_export: bool = False,
    keep_sandbox: bool = False,
    two_stage_blind: bool = False,
    sandbox_mode: str = "standard",
    offline_env: bool = False,
) -> dict[str, Any]:
    """Run overclaim and underclaim reviewers concurrently in separate OS sandboxes, then optional adjudication."""
    if not overclaim_cmd:
        fail("missing_field", "run-dual-review requires a command for overclaim")
    if not underclaim_cmd:
        fail("missing_field", "run-dual-review requires a command for underclaim")
    if adjudicator_cmd is not None and not adjudicator_cmd:
        fail("missing_field", "adjudicator_cmd cannot be empty when supplied")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        fail("invalid_value", "timeout must be finite and greater than zero")

    backend = _resolve_os_sandbox(sandbox_mode)
    ws = Path(workspace).resolve()
    engine = Engine(ws)
    case_doc = engine.dispatch("get_case", {"case_id": case_id})
    if case_doc.get("state") != "frozen":
        fail("invalid_state", f"run-dual-review requires a frozen case (got state={case_doc.get('state')!r})")
    if "pause" in engine._human_holds(case_doc):
        fail("human_paused", "Case is paused; isolated reviewers were not started")

    over_pkt = engine.get_packet(case_id, "overclaim", stage="full")
    under_pkt = engine.get_packet(case_id, "underclaim", stage="full")
    claim_ids = {c["id"] for c in (case_doc.get("claims") or ())}
    over_s1_pkt = engine.get_packet(case_id, "overclaim", stage="evidence_only") if two_stage_blind else None
    under_s1_pkt = engine.get_packet(case_id, "underclaim", stage="evidence_only") if two_stage_blind else None
    seal_key = ensure_runner_key(ws)

    # Execute both reviewers concurrently in completely separate ephemeral sandboxes and scrubbed environments.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_over = pool.submit(
            _run_role_safe,
            over_pkt,
            seal_key,
            case_id=case_id,
            role="overclaim",
            cmd=list(overclaim_cmd),
            runner_name=runner_name,
            model_route=overclaim_model_route,
            timeout=timeout,
            allow_env=allow_env,
            keep_sandbox=keep_sandbox,
            workspace=ws,
            sandbox_mode=sandbox_mode,
            os_sandbox_backend=backend,
            offline_env=offline_env,
            two_stage_blind=two_stage_blind,
            stage1_packet=over_s1_pkt,
            claim_ids=claim_ids,
        )
        fut_under = pool.submit(
            _run_role_safe,
            under_pkt,
            seal_key,
            case_id=case_id,
            role="underclaim",
            cmd=list(underclaim_cmd),
            runner_name=runner_name,
            model_route=underclaim_model_route,
            timeout=timeout,
            allow_env=allow_env,
            keep_sandbox=keep_sandbox,
            workspace=ws,
            sandbox_mode=sandbox_mode,
            os_sandbox_backend=backend,
            offline_env=offline_env,
            two_stage_blind=two_stage_blind,
            stage1_packet=under_s1_pkt,
            claim_ids=claim_ids,
        )
        over_res = fut_over.result()
        under_res = fut_under.result()

    role_res_map: dict[str, dict[str, Any]] = {"overclaim": over_res, "underclaim": under_res}
    persisted_reviews: dict[str, dict[str, Any]] = {}

    def _audit_summary(adjudication_res: dict[str, Any] | None = None, persisted_adj: dict[str, Any] | None = None) -> dict[str, Any]:
        roles_summary = {
            "overclaim": _role_audit_entry(over_res, persisted_record=persisted_reviews.get("overclaim"), model_route=overclaim_model_route),
            "underclaim": _role_audit_entry(under_res, persisted_record=persisted_reviews.get("underclaim"), model_route=underclaim_model_route),
        }
        if adjudication_res is not None:
            roles_summary["adjudication"] = _role_audit_entry(
                adjudication_res,
                persisted_record=persisted_adj,
                model_route=adjudicator_model_route,
            )
        return {
            "parallel_execution": True,
            "two_stage_blind": bool(two_stage_blind),
            "sandbox_mode": sandbox_mode,
            "os_sandbox": backend,
            "offline_env": bool(offline_env),
            "roles": roles_summary,
            "honest_limit": "OS-process isolation with workspace HMAC runner seal; not a hardware enclave or proof of independent model weights.",
        }

    # Atomic pair gate: if either reviewer failed to produce a complete submission, leave SQLite untouched ("frozen").
    if over_res.get("termination_status") != "completed" or under_res.get("termination_status") != "completed":
        return {
            "case_id": case_id,
            "state": "frozen",
            "status": "review_failed",
            "submitted_roles": [],
            "reviews": role_res_map,
            "adjudication": None,
            "isolation_audit_summary": _audit_summary(),
        }

    # Preflight both submissions + cross-review collisions before mutating SQLite so partial failures do not commit.
    over_payload = over_res["submission_payload"]
    under_payload = under_res["submission_payload"]
    try:
        engine.validate_action("submit_review", over_payload)
        engine.validate_action("submit_review", under_payload)
        over_ctx = (over_payload.get("reviewer") or {}).get("context_id")
        under_ctx = (under_payload.get("reviewer") or {}).get("context_id")
        if over_ctx and under_ctx and over_ctx == under_ctx:
            fail("context_reuse", "overclaim and underclaim reviewers must report distinct context_id values")
        over_fids = {f.get("id") for f in (over_payload.get("findings") or ()) if isinstance(f, dict)}
        under_fids = {f.get("id") for f in (under_payload.get("findings") or ()) if isinstance(f, dict)}
        if over_fids & under_fids:
            fail("duplicate_id", "finding IDs must be unique across both reviews")
    except ContractError as exc:
        return {
            "case_id": case_id,
            "state": "frozen",
            "status": "review_failed",
            "submitted_roles": [],
            "reviews": role_res_map,
            "adjudication": None,
            "submission_error": exc.as_dict(),
            "isolation_audit_summary": _audit_summary(),
        }

    submitted_roles: list[str] = []
    latest_state = "frozen"
    try:
        for role_name in ("overclaim", "underclaim"):
            r_res = role_res_map[role_name]
            sub = engine.dispatch("submit_review", r_res["submission_payload"])
            r_res["submitted"] = True
            r_res["submission_result"] = sub
            r_res["isolation_grade"] = (sub.get("review") or {}).get("isolation_grade")
            persisted_reviews[role_name] = sub.get("review") or {}
            submitted_roles.append(role_name)
            latest_state = str(sub.get("state") or latest_state)
    except ContractError as exc:
        return {
            "case_id": case_id,
            "state": latest_state,
            "status": "review_failed",
            "submitted_roles": submitted_roles,
            "reviews": role_res_map,
            "adjudication": None,
            "submission_error": exc.as_dict(),
            "isolation_audit_summary": _audit_summary(),
        }

    if latest_state == "review_blocked":
        return {
            "case_id": case_id,
            "state": "review_blocked",
            "status": "review_blocked_needs_split",
            "submitted_roles": submitted_roles,
            "reviews": role_res_map,
            "adjudication": None,
            "isolation_audit_summary": _audit_summary(),
        }

    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
    adj_pkt_sha = packet_content_sha256(adj_pkt)

    if adjudicator_cmd is None:
        return {
            "case_id": case_id,
            "state": "reviewed",
            "status": "ready_for_adjudication",
            "submitted_roles": submitted_roles,
            "adjudication_id": adj_pkt["adjudication_id"],
            "adjudication_packet_sha256": adj_pkt_sha,
            "reviews": role_res_map,
            "adjudication": None,
            "isolation_audit_summary": _audit_summary(),
        }

    adj_res = _run_role_safe(
        adj_pkt,
        seal_key,
        case_id=case_id,
        role="adjudication",
        cmd=list(adjudicator_cmd),
        runner_name=runner_name,
        model_route=adjudicator_model_route,
        timeout=timeout,
        allow_env=allow_env,
        keep_sandbox=keep_sandbox,
        workspace=ws,
        sandbox_mode=sandbox_mode,
        os_sandbox_backend=backend,
        offline_env=offline_env,
    )
    if adj_res.get("termination_status") != "completed":
        return {
            "case_id": case_id,
            "state": "reviewed",
            "status": "adjudication_failed",
            "submitted_roles": submitted_roles,
            "adjudication_id": adj_pkt["adjudication_id"],
            "reviews": role_res_map,
            "adjudication": adj_res,
            "isolation_audit_summary": _audit_summary(adjudication_res=adj_res),
        }

    try:
        adj_sub = engine.dispatch("submit_adjudication", adj_res["submission_payload"])
        adj_res["submitted"] = True
        adj_res["submission_result"] = adj_sub
        persisted_adj = adj_sub.get("adjudication") or {}
        adj_res["isolation_grade"] = persisted_adj.get("isolation_grade")
        submitted_roles.append("adjudication")
        latest_state = str(adj_sub.get("state") or "adjudicated")
    except ContractError as exc:
        return {
            "case_id": case_id,
            "state": "reviewed",
            "status": "adjudication_failed",
            "submitted_roles": submitted_roles,
            "adjudication_id": adj_pkt["adjudication_id"],
            "reviews": role_res_map,
            "adjudication": adj_res,
            "submission_error": exc.as_dict(),
            "isolation_audit_summary": _audit_summary(adjudication_res=adj_res),
        }

    out: dict[str, Any] = {
        "case_id": case_id,
        "state": latest_state,
        "status": "adjudicated",
        "submitted_roles": submitted_roles,
        "adjudication_id": adj_pkt["adjudication_id"],
        "reviews": role_res_map,
        "adjudication": adj_res,
        "isolation_audit_summary": _audit_summary(adjudication_res=adj_res, persisted_adj=persisted_adj),
    }

    if auto_export:
        try:
            ver_res = engine.dispatch("verify", {"case_id": case_id})
            exp_res = engine.dispatch("export", {"case_id": case_id})
            out["status"] = "exported"
            out["state"] = str(exp_res.get("state") or "exported")
            out["verification"] = ver_res
            out["export"] = exp_res
        except ContractError as exc:
            out["status"] = "export_failed"
            out["export_error"] = exc.as_dict()
    return out
