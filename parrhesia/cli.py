"""Command-line interface, intentionally usable without installation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import shlex
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
    from .artifacts import ARTIFACT_FORMATS, inspect_artifact, restrict_kind
    from .claims import EXECUTION_FORK_ROLES
    from .contracts import ContractError, enum, fail, ids, string
    from .core import Engine
    from .gates import evidence_lineage, meaningful
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
    effective_kind = restrict_kind("unknown", getattr(args, "kind", "auto"))
    if args.case_id:
        existing_case = engine.dispatch("get_case", {"case_id": args.case_id})
        if existing_case["state"] != "draft":
            fail("invalid_state", "record-exec requires a draft case; command was not started")
        if "pause" in engine._human_holds(existing_case):
            fail("human_paused", "Case is paused; command was not started")
        known = {e["evidence_id"]: e for e in existing_case["evidence"]}
        for parent_id in derived_from:
            if parent_id not in known:
                fail("unknown_evidence", "--derived-from references unknown evidence; command was not started")
            lineage = evidence_lineage(parent_id, known)
            if lineage["cycle_detected"] or lineage["unknown_parents"]:
                fail("invalid_lineage", "Parent lineage is incomplete or cyclic; command was not started")
            ancestors = [known[eid] for eid in [parent_id, *lineage["ancestors"]]]
            if any(parent.get("kind") == "synthetic" or parent.get("provenance") == "synthetic" for parent in ancestors):
                effective_kind = restrict_kind("synthetic", getattr(args, "kind", "auto"))

    def parse_artifact_options(values):
        entries = []
        for value in values or []:
            format, sep, path = value.partition("=")
            if not sep or not path:
                fail("invalid_value", "Artifact option must be FORMAT=workspace-relative-path")
            enum(format, ARTIFACT_FORMATS, "artifact_format")
            engine._path(path)
            if path in [p for _, p in entries]:
                fail("duplicate_id", "Artifact paths must be unique")
            entries.append((format, path))
        return entries

    artifact_options = parse_artifact_options(getattr(args, "artifact", []))
    metadata_options = parse_artifact_options(getattr(args, "metadata_file", []))
    metadata = [inspect_artifact(engine._read_source(engine._path(path)), path, format) for format, path in metadata_options]
    if any(item["kind"] == "synthetic" for item in metadata):
        effective_kind = restrict_kind("synthetic", getattr(args, "kind", "auto"))
    requested_log_file = engine._path(args.log_path) if args.log_path else None
    input_snapshots = validate_input_files(engine.workspace, [*list(getattr(args, "input_file", None) or []), *(path for _, path in metadata_options)])
    measured_inputs = {item["path"]: item["sha256"] for item in input_snapshots}
    if any(measured_inputs.get(engine._path(item["path"]).relative_to(engine.workspace).as_posix()) != item["sha256"] for item in metadata):
        fail("source_changed", "Metadata changed before input hashing; command was not started")
    output_pre_snapshots = snapshot_output_files_pre(engine.workspace, [*list(getattr(args, "output_file", None) or []), *(path for _, path in artifact_options)])
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
    artifacts, artifact_errors = [], []
    for format, path in artifact_options:
        try:
            artifacts.append(inspect_artifact(engine._read_source(engine._path(path)), path, format))
        except (ContractError, OSError) as exc:
            artifact_errors.append({"path": path, "error": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
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
        "artifacts": artifacts,
        "artifact_errors": artifact_errors,
        "metadata_artifacts": metadata,
        "kind_inference": {"kind": effective_kind, "basis": "execution_log_not_study_design; metadata_can_restrict_to_synthetic"},
    }

    evidence = None
    if args.case_id:
        reg_payload = {
            "case_id": args.case_id,
            "path": rel_log_path,
            "label": args.label,
            "provenance": "synthetic" if effective_kind == "synthetic" else "observed",
            "kind": effective_kind,
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
        result["artifact_imports"] = []
        result["artifact_import_errors"] = []
        for artifact in artifacts:
            payload = {"case_id": args.case_id, "path": artifact["path"], "artifact_format": artifact["format"]}
            matching_output = next((o for o in output_snapshots if o["path"] == artifact["path"]), {})
            if status == "checked" and matching_output.get("status") in ("created", "modified"):
                payload["execution_evidence_id"] = evidence["evidence_id"]
            else:
                payload.update(derived_from_evidence_ids=[evidence["evidence_id"]], derivation_step="Artifact observed after an attempt; fresh successful production is not established")
            try:
                result["artifact_imports"].append(engine.dispatch("import_artifact", payload))
            except (ContractError, OSError) as exc:
                result["artifact_import_errors"].append({"path": artifact["path"], "error": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
    return result


def _split_cli_cmd(raw: str) -> list[str]:
    """Parse a shell-like command string safely on both Windows and POSIX."""
    tokens = shlex.split(raw, posix=(os.name != "nt"))
    if os.name == "nt":
        cleaned = []
        for tok in tokens:
            if len(tok) >= 2 and ((tok[0] == '"' and tok[-1] == '"') or (tok[0] == "'" and tok[-1] == "'")):
                tok = tok[1:-1]
            cleaned.append(tok)
        tokens = cleaned
    return tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="parrhesia", description="Local evidence review, independent packets and explicit adjudication")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    service = commands.add_parser("serve", help="Run the MCP stdio server")
    service.add_argument("--workspace", type=Path, required=True)
    service.add_argument("--schema-mode", choices=("shared", "inline"), default="shared")
    service.add_argument("--tool-profile", choices=("full", "review", "adjudication", "explore", "compact"), default="full")
    iso = commands.add_parser("isolate-packet", help="Export an isolated role packet with packet_nonce, packet_sha256, and runner receipt template")
    iso.add_argument("--workspace", type=Path, required=True)
    iso.add_argument("--case-id", required=True)
    iso.add_argument("--role", choices=("overclaim", "underclaim", "adjudication"), required=True)
    iso.add_argument("--stage", choices=("full", "evidence_only"), default="full", help="Review packet stage ('evidence_only' strips author claims for Stage 1 estimate-first lock)")
    iso.add_argument("--runner", default="parrhesia-cli-isolate")
    iso.add_argument("--output", default=None, help="Optional new workspace-relative .json path to write the exported packet bundle")
    run_iso = commands.add_parser("run-isolated", help="Execute a reviewer/adjudicator command in an OS-isolated sandbox with scrubbed env and HMAC-sealed isolation_receipt")
    run_iso.add_argument("--workspace", type=Path, required=True)
    run_iso.add_argument("--case-id", required=True)
    run_iso.add_argument("--role", choices=("overclaim", "underclaim", "adjudication"), required=True)
    run_iso.add_argument("--runner", default="parrhesia-subprocess-runner")
    run_iso.add_argument("--model-route", default=None)
    run_iso.add_argument("--timeout", type=float, default=120.0)
    run_iso.add_argument("--allow-env", action="append", default=[], help="Additional parent env var name allowed into the isolated child (repeatable)")
    run_iso.add_argument("--two-stage-blind", action="store_true", help="Run Stage 1 evidence_only commit before Stage 2 full reveal in separate sandboxes")
    run_iso.add_argument("--sandbox-mode", choices=("standard", "strict_os"), default="standard", help="Subprocess sandbox mode ('strict_os' requires bwrap/sandbox-exec)")
    run_iso.add_argument("--offline-env", action="store_true", help="Inject fail-closed loopback proxy and offline library environment variables")
    run_iso.add_argument("--auto-submit", action="store_true", help="Automatically submit the sealed child JSON payload into the case")
    run_iso.add_argument("--keep-sandbox", action="store_true", help="Keep the ephemeral isolated sandbox directory after completion for inspection")
    run_iso.add_argument("cmd", nargs=argparse.REMAINDER)
    dual = commands.add_parser("run-dual-review", help="Execute parallel OS-isolated overclaim and underclaim reviewers (and optional adjudication)")
    dual.add_argument("--workspace", type=Path, required=True)
    dual.add_argument("--case-id", required=True)
    dual.add_argument("--runner", default="parrhesia-dual-subprocess-runner")
    dual.add_argument("--overclaim-cmd", default=None, help="Explicit command string for overclaim role (falls back to trailing cmd)")
    dual.add_argument("--underclaim-cmd", default=None, help="Explicit command string for underclaim role (falls back to trailing cmd)")
    dual.add_argument("--adjudicator-cmd", default=None, help="Optional explicit command string for isolated adjudication step")
    dual.add_argument("--run-adjudication", action="store_true", help="Also run isolated adjudication using --adjudicator-cmd or trailing cmd")
    dual.add_argument("--overclaim-model-route", default=None)
    dual.add_argument("--underclaim-model-route", default=None)
    dual.add_argument("--adjudicator-model-route", default=None)
    dual.add_argument("--timeout", type=float, default=120.0)
    dual.add_argument("--allow-env", action="append", default=[], help="Additional parent env var name allowed into isolated children (repeatable)")
    dual.add_argument("--two-stage-blind", action="store_true", help="Run Stage 1 evidence_only commit before Stage 2 full reveal for both reviewers")
    dual.add_argument("--sandbox-mode", choices=("standard", "strict_os"), default="standard", help="Subprocess sandbox mode ('strict_os' requires bwrap/sandbox-exec)")
    dual.add_argument("--offline-env", action="store_true", help="Inject fail-closed loopback proxy and offline library environment variables")
    dual.add_argument("--auto-export", action="store_true", help="Verify and atomically export Markdown report after isolated adjudication succeeds")
    dual.add_argument("--keep-sandbox", action="store_true", help="Keep ephemeral sandbox directories after completion for inspection")
    dual.add_argument("cmd", nargs=argparse.REMAINDER)
    syn_cmd = commands.add_parser("synthesize", help="Compute read-only cross-case Living Evidence Synthesis (and optional offline HTML with SVG forest plot)")
    syn_cmd.add_argument("--workspace", type=Path, required=True)
    syn_cmd.add_argument("--case-id", default=None)
    syn_cmd.add_argument("--claim-id", default=None)
    syn_cmd.add_argument("--metric", default=None)
    syn_cmd.add_argument("--alpha", type=float, default=0.05)
    syn_cmd.add_argument("--ci-level", type=float, default=0.95)
    syn_cmd.add_argument("--output", default=None, help="Optional new workspace-relative .html path; existing files are never overwritten")
    call = commands.add_parser("call", help="Run one action, loading payload from a UTF-8 JSON file or stdin")
    call.add_argument("action")
    call.add_argument("--workspace", type=Path, required=True)
    call.add_argument("--input", type=Path)
    commands.add_parser("contract", help="Print the workflow contract")
    report = commands.add_parser("report", help="Render an existing adjudicated case to offline HTML without changing it")
    report.add_argument("--workspace", type=Path, required=True)
    report.add_argument("--case-id", required=True)
    report.add_argument("--output", required=True, help="New workspace-relative .html path; existing files are never overwritten")
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
    rec.add_argument("--kind", default="auto", help="auto/unknown/synthetic; self-report cannot promote an execution log to scientific evidence")
    rec.add_argument("--artifact", action="append", default=[], help="Expected artifact FORMAT=relative-path; inspect after execution and register with its output binding (repeatable)")
    rec.add_argument("--metadata-file", action="append", default=[], help="Existing metadata artifact FORMAT=relative-path; inspect and hash before execution (repeatable)")
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
            return serve(args.workspace, schema_mode=args.schema_mode, tool_profile=args.tool_profile)
        if args.command == "contract":
            from .server import contract_text
            sys.stdout.buffer.write(contract_text().encode("utf-8"))
            return 0
        if args.command == "demo":
            from .demo import run_demo
            result = run_demo(args.output)
        elif args.command == "report":
            from .report import render_case_report
            result = render_case_report(args.workspace, args.case_id, args.output)
        elif args.command == "record-exec":
            result = _record_exec(args)
        elif args.command == "isolate-packet":
            from .core import Engine
            from .isolation import packet_content_sha256
            engine = Engine(args.workspace)
            pkt = engine.get_packet(args.case_id, args.role, stage=args.stage)
            pkt_sha = packet_content_sha256(pkt)
            expected_profile = "adjudication" if args.role == "adjudication" else "review"
            result = {
                "case_id": args.case_id,
                "role": args.role,
                "stage": args.stage,
                "packet": pkt,
                "packet_sha256": pkt_sha,
                "recommended_mcp_args": ["--workspace", str(args.workspace.resolve()), "--tool-profile", expected_profile],
                "isolation_receipt_template": {
                    "runner": args.runner,
                    "packet_nonce": pkt.get("packet_nonce"),
                    "packet_sha256": pkt_sha,
                    "parent_history_messages": 0,
                    "memory_enabled": False,
                    "tool_profile": expected_profile,
                },
            }
            if args.output:
                out_path = engine._path(args.output)
                if out_path.exists():
                    raise ValueError(f"Output path already exists and will not be overwritten: {args.output}")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                result["written_path"] = str(out_path)
        elif args.command == "run-isolated":
            from .isolated_runner import run_isolated_subprocess
            cmd = list(args.cmd or [])
            if cmd and cmd[0] == "--":
                cmd = cmd[1:]
            result = run_isolated_subprocess(
                args.workspace,
                args.case_id,
                args.role,
                cmd,
                runner_name=args.runner,
                model_route=args.model_route,
                timeout=args.timeout,
                allow_env=args.allow_env,
                auto_submit=args.auto_submit,
                keep_sandbox=args.keep_sandbox,
                two_stage_blind=args.two_stage_blind,
                sandbox_mode=args.sandbox_mode,
                offline_env=args.offline_env,
            )
            sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
            term = result.get("termination_status")
            if term == "timed_out":
                return 124
            if term == "start_failed":
                return 127
            if term != "completed" or (args.auto_submit and not result.get("submitted")):
                return 1
            return 0
        elif args.command == "run-dual-review":
            from .isolated_runner import run_isolated_dual_review
            default_cmd = list(args.cmd or [])
            if default_cmd and default_cmd[0] == "--":
                default_cmd = default_cmd[1:]
            over_cmd = _split_cli_cmd(args.overclaim_cmd) if args.overclaim_cmd else default_cmd
            under_cmd = _split_cli_cmd(args.underclaim_cmd) if args.underclaim_cmd else default_cmd
            adj_cmd = _split_cli_cmd(args.adjudicator_cmd) if args.adjudicator_cmd else (default_cmd if args.run_adjudication else None)
            result = run_isolated_dual_review(
                args.workspace,
                args.case_id,
                overclaim_cmd=over_cmd,
                underclaim_cmd=under_cmd,
                adjudicator_cmd=adj_cmd,
                runner_name=args.runner,
                overclaim_model_route=args.overclaim_model_route,
                underclaim_model_route=args.underclaim_model_route,
                adjudicator_model_route=args.adjudicator_model_route,
                timeout=args.timeout,
                allow_env=args.allow_env,
                auto_export=args.auto_export,
                keep_sandbox=args.keep_sandbox,
                two_stage_blind=args.two_stage_blind,
                sandbox_mode=args.sandbox_mode,
                offline_env=args.offline_env,
            )
            sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
            status = result.get("status")
            if status in ("ready_for_adjudication", "adjudicated", "exported", "review_blocked_needs_split"):
                return 0
            role_terms = [
                (result.get("reviews") or {}).get("overclaim", {}).get("termination_status"),
                (result.get("reviews") or {}).get("underclaim", {}).get("termination_status"),
                (result.get("adjudication") or {}).get("termination_status"),
            ]
            if "timed_out" in role_terms:
                return 124
            if "start_failed" in role_terms:
                return 127
            return 1
        elif args.command == "synthesize":
            from .report import render_synthesis_report
            result = render_synthesis_report(
                args.workspace,
                args.output,
                case_id=args.case_id,
                claim_id=args.claim_id,
                metric=args.metric,
                alpha=args.alpha,
                ci_level=args.ci_level,
            )
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
