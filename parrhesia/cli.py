"""Command-line interface, intentionally usable without installation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from . import __version__


def _allocate_default_log_file(engine) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for seq in range(1, 1000):
        candidate = f"artifacts/exec-logs/exec-{stamp}" + (".log" if seq == 1 else f"-{seq}.log")
        log_file = engine._path(candidate)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(log_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            return log_file
        except FileExistsError:
            continue
    from .contracts import fail
    fail("export_exists", "could not allocate unique default execution log path")


def _record_exec(args: argparse.Namespace) -> dict:
    from .claims import EXECUTION_FORK_ROLES
    from .contracts import ContractError, enum, fail, ids, string
    from .core import Engine
    from .gates import meaningful
    from .provenance import (
        DEFAULT_STDOUT_EXCERPT_CHARS,
        collect_environment_markers,
        collect_git_state,
        compute_stream_provenance,
        discover_lockfiles,
        format_environment_description,
        hash_regular_file,
        snapshot_output_files_post,
        snapshot_output_files_pre,
        synthesize_code_version,
        synthesize_inputs_summary,
        synthesize_outputs_summary,
        validate_input_files,
    )

    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        fail("missing_field", "record-exec requires a command to execute")
    if args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        fail("invalid_value", "--timeout must be finite and greater than zero")
    claim_id = string(args.claim_id, "claim_id", maximum=200) if getattr(args, "claim_id", None) is not None else None
    run_group = string(args.run_group, "run_group", maximum=200) if getattr(args, "run_group", None) is not None else None
    fork_role = enum(args.fork_role, EXECUTION_FORK_ROLES, "fork_role") if getattr(args, "fork_role", None) is not None else None
    raw_derived = list(getattr(args, "derived_from", None) or [])
    derived_from = ids(raw_derived, "derived_from", minimum=0) if raw_derived else []
    raw_step = getattr(args, "derivation_step", None)
    derivation_step = string(raw_step, "derivation_step", maximum=2000) if raw_step is not None else None
    if derived_from and (derivation_step is None or not meaningful(derivation_step)):
        fail("missing_field" if derivation_step is None else "invalid_value", "--derived-from requires a meaningful --derivation-step")
    if derivation_step is not None and not derived_from:
        fail("missing_field", "--derivation-step requires at least one --derived-from evidence ID")
    raw_excerpt_chars = getattr(args, "stdout_excerpt_chars", DEFAULT_STDOUT_EXCERPT_CHARS)
    if raw_excerpt_chars is None:
        raw_excerpt_chars = DEFAULT_STDOUT_EXCERPT_CHARS
    if type(raw_excerpt_chars) is not int or raw_excerpt_chars < 0:
        fail("invalid_value", "--stdout-excerpt-chars must be a non-negative integer")
    explicit_code_version = string(args.code_version, "code_version") if args.code_version is not None else None
    explicit_inputs = string(args.inputs, "inputs") if args.inputs is not None else None
    explicit_outputs = string(args.outputs, "outputs") if args.outputs is not None else None

    engine = Engine(args.workspace)
    requested_log_file = engine._path(args.log_path) if args.log_path else None
    input_snapshots = validate_input_files(engine.workspace, list(getattr(args, "input_file", None) or []))
    output_pre_snapshots = snapshot_output_files_pre(engine.workspace, list(getattr(args, "output_file", None) or []))
    git_state = collect_git_state(engine.workspace)
    lockfiles = discover_lockfiles(engine.workspace)
    env_markers = collect_environment_markers()

    # Reserve the destination before launching; even failed attempts must not overwrite history.
    if requested_log_file is not None:
        requested_log_file.parent.mkdir(parents=True, exist_ok=True)
        engine._reject_link(requested_log_file)
        try:
            with requested_log_file.open("xb"):
                pass
        except FileExistsError:
            fail("export_exists", "execution log path already exists; choose a new path")
        log_file = requested_log_file
    else:
        log_file = _allocate_default_log_file(engine)
    cmd_str = subprocess.list2cmdline(cmd)
    started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    termination_status = "completed"
    execution_error = None
    try:
        completed = subprocess.run(cmd, cwd=engine.workspace, capture_output=True, text=False, timeout=args.timeout, check=False)
        exit_status = completed.returncode
        stdout_bytes, stderr_bytes = completed.stdout or b"", completed.stderr or b""
    except subprocess.TimeoutExpired as exc:
        termination_status = "timed_out"
        exit_status = None
        stdout_bytes, stderr_bytes = exc.stdout or b"", exc.stderr or b""
        execution_error = {"type": "TimeoutExpired", "timeout_seconds": args.timeout}
    except OSError as exc:
        termination_status = "start_failed"
        exit_status = None
        stdout_bytes, stderr_bytes = b"", b""
        execution_error = {"type": type(exc).__name__, "errno": exc.errno, "message": str(exc)}
    ended_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    output_snapshots = []
    for before in output_pre_snapshots:
        try:
            output_snapshots.extend(snapshot_output_files_post(engine.workspace, [before]))
        except (ContractError, OSError) as exc:
            # An invalid partial output must not erase the execution attempt itself.
            output_snapshots.append({**before, "status": "unverified", "sha256": None, "size": None,
                                     "error": getattr(exc, "code", type(exc).__name__)})
    missing_outputs = [item["path"] for item in output_snapshots if item["status"] == "missing"]
    unverified_outputs = [item["path"] for item in output_snapshots if item["status"] == "unverified"]
    stdout_text = stdout_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    stream_digests = compute_stream_provenance(
        stdout_bytes,
        stderr_bytes,
        stdout_text,
        excerpt_chars=raw_excerpt_chars,
    )

    env_desc = format_environment_description(env_markers)
    code_version_value = explicit_code_version if explicit_code_version is not None else synthesize_code_version(git_state, lockfiles)
    inputs_value = explicit_inputs if explicit_inputs is not None else synthesize_inputs_summary(input_snapshots, lockfiles)
    excerpt_line = (
        stream_digests["stdout_excerpt"]
        if stream_digests["stdout_excerpt"]
        else ("(omitted)" if stream_digests["stdout_excerpt_max_chars"] == 0 and stdout_text.strip() else "(empty)")
    )
    header_lines = [
        f"command: {cmd_str}",
        f"started_at: {started_at}",
        f"ended_at: {ended_at}",
        f"exit_status: {exit_status if exit_status is not None else 'unknown'}",
        f"termination_status: {termination_status}",
    ]
    if execution_error is not None:
        header_lines.append("execution_error: " + json.dumps(execution_error, ensure_ascii=False))
    if claim_id is not None:
        header_lines.append(f"claim_id: {claim_id}")
    if run_group is not None:
        header_lines.append(f"run_group: {run_group}")
    header_lines.extend([
        f"stdout_sha256: {stream_digests['stdout_sha256']}",
        f"stderr_sha256: {stream_digests['stderr_sha256']}",
        f"stdout_excerpt: {excerpt_line}",
    ])
    header_quote = "\n".join(header_lines)
    header_line_count = header_quote.count("\n") + 1
    meta_lines = [
        f"environment: {env_desc}",
        f"code_version: {code_version_value}",
        f"inputs: {inputs_value}",
    ]
    if output_snapshots:
        out_meta = ", ".join(
            f"{item['path']}({item['status']}" + (f",sha256={item['sha256'][:12]}" if item["sha256"] else "") + ")"
            for item in output_snapshots
        )
        meta_lines.append(f"declared_outputs: {out_meta}")
    log_text = (
        f"{header_quote}\n"
        + "\n".join(meta_lines)
        + f"\n--- stdout ---\n{stdout_text}"
        + f"\n--- stderr ---\n{stderr_text}\n"
    )
    log_file.write_text(log_text, encoding="utf-8", newline="\n")
    log_sha256, log_bytes = hash_regular_file(log_file)
    rel_log_path = log_file.relative_to(engine.workspace).as_posix()
    header_range = f"L1-L{header_line_count}"

    outputs_value = (
        explicit_outputs
        if explicit_outputs is not None
        else synthesize_outputs_summary(
            output_snapshots,
            rel_log_path,
            log_sha256,
            stream_digests["stdout_sha256"],
            stream_digests["stderr_sha256"],
        )
    )
    provenance = {
        "termination_status": termination_status,
        "execution_error": execution_error,
        "git": git_state,
        "lockfiles": lockfiles,
        "environment": env_markers,
        "inputs": input_snapshots,
        "outputs": output_snapshots,
        "missing_outputs": missing_outputs,
        "unverified_outputs": unverified_outputs,
        "all_outputs_present": not missing_outputs and not unverified_outputs,
        "streams": {
            **stream_digests,
            "log_sha256": log_sha256,
            "log_bytes": log_bytes,
        },
    }

    evidence = None
    if args.case_id:
        reg_payload = {
            "case_id": args.case_id,
            "path": rel_log_path,
            "label": args.label,
            "provenance": "observed",
            "kind": args.kind,
            "location": f"{rel_log_path}:{header_range}",
            "quote": header_quote,
        }
        if derived_from:
            reg_payload["derived_from_evidence_ids"] = derived_from
            reg_payload["derivation_step"] = derivation_step
        evidence = engine.dispatch("register_evidence", reg_payload)
        evidence_ids = [evidence["evidence_id"]]
    else:
        evidence_ids = [args.evidence_id]
    status = "checked" if termination_status == "completed" and exit_status == 0 and not missing_outputs and not unverified_outputs else "failed"
    fork_meta = {"fork_index": 1, "case_exec_count": 1, "multiplicity_required": False}
    if args.case_id:
        event_payload = {
            "card_id": args.card_id,
            "evidence_id": evidence_ids[0],
            "command": cmd_str,
            "exit_status": exit_status,
            "termination_status": termination_status,
            "execution_error": execution_error,
            "status": status,
            "log_path": rel_log_path,
            "started_at": started_at,
            "ended_at": ended_at,
            "provenance": provenance,
        }
        if claim_id is not None:
            event_payload["claim_id"] = claim_id
        if run_group is not None:
            event_payload["run_group"] = run_group
        if derived_from:
            event_payload["derived_from_evidence_ids"] = derived_from
            event_payload["derivation_step"] = derivation_step
        fork_meta = engine.record_execution_event(args.case_id, event_payload)
    fork_suffix = (
        f" (case execution fork #{fork_meta['fork_index']}; multiplicity/selection accounting required)"
        if fork_meta["multiplicity_required"]
        else ""
    )
    card_details = {
        "command": cmd_str,
        "code_version": code_version_value,
        "inputs": inputs_value,
        "environment": env_desc,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_status": str(exit_status) if exit_status is not None else f"unknown ({termination_status})",
        "outputs": outputs_value,
        "log_locator": f"{rel_log_path}:{header_range}",
    }
    if claim_id is not None:
        card_details["claim_id"] = claim_id
    if run_group is not None:
        card_details["run_group"] = run_group
    if fork_role is not None:
        card_details["fork_role"] = fork_role
    missing_note = f"; missing declared output(s): {', '.join(missing_outputs)}" if missing_outputs else ""
    if unverified_outputs:
        missing_note += f"; unverified declared output(s): {', '.join(unverified_outputs)}"
    execution_card = {
        "id": args.card_id,
        "status": status,
        "reason": f"Execution attempt `{cmd_str}`: {termination_status}, exit_status={exit_status}{missing_note}; log captured at {rel_log_path}{fork_suffix}.",
        "evidence_ids": evidence_ids,
        "details": card_details,
    }
    result = {
        "execution_card": execution_card,
        "exit_status": exit_status,
        "termination_status": termination_status,
        "execution_error": execution_error,
        "log_path": rel_log_path,
        "fork_index": fork_meta["fork_index"],
        "scoped_exec_count": fork_meta.get("scoped_exec_count", fork_meta["fork_index"]),
        "case_exec_count": fork_meta["case_exec_count"],
        "multiplicity_required": fork_meta["multiplicity_required"],
        "provenance": provenance,
    }
    if claim_id is not None:
        result["claim_id"] = claim_id
    if run_group is not None:
        result["run_group"] = run_group
    if derived_from:
        result["derived_from_evidence_ids"] = derived_from
        result["derivation_step"] = derivation_step
    if evidence is not None:
        result["evidence"] = evidence
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="parrhesia", description="Local evidence review, independent packets and explicit adjudication")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    service = commands.add_parser("serve", help="Run the MCP stdio server")
    service.add_argument("--workspace", type=Path, required=True)
    call = commands.add_parser("call", help="Run one action, loading payload from a UTF-8 JSON file or stdin")
    call.add_argument("action")
    call.add_argument("--workspace", type=Path, required=True)
    call.add_argument("--input", type=Path)
    commands.add_parser("contract", help="Print the workflow contract")
    demo = commands.add_parser("demo", help="Create an isolated, explicitly synthetic end-to-end demonstration")
    demo.add_argument("--output", type=Path, required=True)
    rec = commands.add_parser("record-exec", help="Execute a command, capture log evidence, and emit an execution card")
    rec.add_argument("--workspace", type=Path, required=True)
    rec.add_argument("--case-id")
    rec.add_argument("--claim-id")
    rec.add_argument("--run-group")
    rec.add_argument("--fork-role")
    rec.add_argument("--evidence-id", default="ev-exec-1")
    rec.add_argument("--card-id", default="exec-1")
    rec.add_argument("--kind", default="benchmark")
    rec.add_argument("--label", default="Recorded command execution log")
    rec.add_argument("--code-version", default=None, help="Explicit code version override (default: synthesized from git/lockfile provenance)")
    rec.add_argument("--inputs", default=None, help="Explicit inputs summary override (default: synthesized from declared --input-file and lockfile hashes)")
    rec.add_argument("--outputs", default=None, help="Explicit outputs summary override (default: synthesized from declared --output-file and stream/log hashes)")
    rec.add_argument("--input-file", action="append", default=[], help="Workspace-relative input file to verify and SHA-256 hash before execution (repeatable)")
    rec.add_argument("--output-file", action="append", default=[], help="Workspace-relative expected output file to snapshot pre/post execution (repeatable)")
    rec.add_argument("--stdout-excerpt-chars", type=int, default=400, help="Maximum characters for sanitized stdout excerpt in log header and quote (default: 400, capped at 2000)")
    rec.add_argument("--log-path", default=None, help="Workspace-relative log path (default: auto-generated unique file under artifacts/exec-logs/)")
    rec.add_argument("--derived-from", action="append", default=[], help="Parent evidence ID that this derived output traces from (repeatable)")
    rec.add_argument("--derivation-step", default=None, help="Explicit derivation step description (required when --derived-from is given)")
    rec.add_argument("--timeout", type=float, default=120.0)
    rec.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve
            return serve(args.workspace)
        if args.command == "contract":
            from .server import contract_text
            sys.stdout.buffer.write(contract_text().encode("utf-8"))
            return 0
        if args.command == "demo":
            from .demo import run_demo
            result = run_demo(args.output)
        elif args.command == "record-exec":
            result = _record_exec(args)
        else:
            from .core import Engine
            raw = args.input.read_text(encoding="utf-8-sig") if args.input else sys.stdin.buffer.read().decode("utf-8-sig")
            payload = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(payload, dict):
                raise ValueError("Payload must be a JSON object")
            result = Engine(args.workspace).dispatch(args.action, payload)
        sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        if args.command == "record-exec" and result.get("termination_status") in ("timed_out", "start_failed"):
            return 124 if result["termination_status"] == "timed_out" else 127
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        error = {"error": getattr(exc, "code", "invalid_request"), "message": str(exc)}
        sys.stderr.buffer.write((json.dumps(error, ensure_ascii=False) + "\n").encode("utf-8"))
        return 2
