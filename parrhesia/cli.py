"""Command-line interface, intentionally usable without installation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


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
        else:
            from .core import Engine
            raw = args.input.read_text(encoding="utf-8-sig") if args.input else sys.stdin.buffer.read().decode("utf-8-sig")
            payload = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(payload, dict):
                raise ValueError("Payload must be a JSON object")
            result = Engine(args.workspace).dispatch(args.action, payload)
        sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        error = {"error": getattr(exc, "code", "invalid_request"), "message": str(exc)}
        sys.stderr.buffer.write((json.dumps(error, ensure_ascii=False) + "\n").encode("utf-8"))
        return 2
