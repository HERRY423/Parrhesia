"""Command-line interface, intentionally usable without installation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import platform
import subprocess
import sys
from pathlib import Path

from . import __version__


def _record_exec(args: argparse.Namespace) -> dict:
    from .contracts import fail
    from .core import Engine

    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        fail("missing_field", "record-exec requires a command to execute")
    engine = Engine(args.workspace)
    log_file = engine._path(args.log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd_str = subprocess.list2cmdline(cmd)
    started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    completed = subprocess.run(
        cmd,
        cwd=engine.workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout,
        check=False,
    )
    ended_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    env_desc = f"Python {sys.version.split()[0]} ({platform.system()} {platform.release()})"
    header_quote = (
        f"command: {cmd_str}\n"
        f"started_at: {started_at}\n"
        f"ended_at: {ended_at}\n"
        f"exit_status: {completed.returncode}"
    )
    log_text = (
        f"{header_quote}\n"
        f"environment: {env_desc}\n"
        f"--- stdout ---\n{completed.stdout}"
        f"\n--- stderr ---\n{completed.stderr}\n"
    )
    log_file.write_text(log_text, encoding="utf-8", newline="\n")
    rel_log_path = log_file.relative_to(engine.workspace).as_posix()
    evidence = None
    if args.case_id:
        evidence = engine.dispatch(
            "register_evidence",
            {
                "case_id": args.case_id,
                "path": rel_log_path,
                "label": args.label,
                "provenance": "observed",
                "kind": args.kind,
                "location": f"{rel_log_path}:L1-L4",
                "quote": header_quote,
            },
        )
        evidence_ids = [evidence["evidence_id"]]
    else:
        evidence_ids = [args.evidence_id]
    status = "checked" if completed.returncode == 0 else "failed"
    execution_card = {
        "id": args.card_id,
        "status": status,
        "reason": f"Executed `{cmd_str}` with exit_status={completed.returncode}; log captured at {rel_log_path}.",
        "evidence_ids": evidence_ids,
        "details": {
            "command": cmd_str,
            "code_version": args.code_version,
            "inputs": args.inputs,
            "environment": env_desc,
            "started_at": started_at,
            "ended_at": ended_at,
            "exit_status": str(completed.returncode),
            "outputs": args.outputs,
            "log_locator": f"{rel_log_path}:L1-L4",
        },
    }
    result = {
        "execution_card": execution_card,
        "exit_status": completed.returncode,
        "log_path": rel_log_path,
    }
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
    rec.add_argument("--evidence-id", default="ev-exec-1")
    rec.add_argument("--card-id", default="exec-1")
    rec.add_argument("--kind", default="benchmark")
    rec.add_argument("--label", default="Recorded command execution log")
    rec.add_argument("--code-version", default="workspace-local")
    rec.add_argument("--inputs", default="workspace")
    rec.add_argument("--outputs", default="stdout/stderr log")
    rec.add_argument("--log-path", default="artifacts/exec-logs/exec.log")
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
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        error = {"error": getattr(exc, "code", "invalid_request"), "message": str(exc)}
        sys.stderr.buffer.write((json.dumps(error, ensure_ascii=False) + "\n").encode("utf-8"))
        return 2
