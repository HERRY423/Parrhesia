"""Build a wheel and exercise its CLI/MCP/report in a clean venv outside the checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parrhesia.adapters import RUNTIME_DOCUMENTS, collect_runtime_payloads, contained, reject_link


def check_wheel(source: Path, output: Path, *, build_isolation: bool = True) -> dict:
    if not __debug__:
        raise ValueError("Run wheel checks without Python -O so every acceptance assertion is active")
    source = source.resolve()
    output = output.absolute()
    for node in (output, *output.parents):
        reject_link(node)
    output.mkdir(parents=True, exist_ok=False)
    summary = {"status": "failed", "build_isolation": build_isolation,
               "python": platform.python_version(), "platform": platform.platform(),
               "installation_isolation": "fresh_venv_no_system_site_packages", "checks": {}, "commands": []}
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PARRHESIA_WORKSPACE"):
        env.pop(key, None)
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1")

    def run(label, command, cwd, stdin=None, expected=0):
        result = subprocess.run([str(v) for v in command], cwd=cwd, env=env, input=stdin,
                                capture_output=True, timeout=180)
        (output / f"{label}.log").write_bytes(result.stdout + b"\n--- stderr ---\n" + result.stderr)
        summary["commands"].append({"label": label, "returncode": result.returncode})
        if result.returncode != expected:
            raise ValueError(f"{label} exited {result.returncode}; see {output / (label + '.log')}")
        return result.stdout

    try:
        # Build from a bounded copy: no build/egg-info writes in the user's checkout.
        with tempfile.TemporaryDirectory(prefix="parrhesia-wheel-") as temporary:
            work = Path(temporary).resolve()
            if work.is_relative_to(source):
                raise ValueError("Wheel verification temporary directory must be outside the source checkout")
            build_source = work / "source"
            payloads = collect_runtime_payloads(source, "source")
            payloads["source/pyproject.toml"] = (source / "pyproject.toml").read_bytes()
            payloads["source/LICENSE"] = (source / "LICENSE").read_bytes()
            for name, data in payloads.items():
                path = contained(work, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            summary["source_sha256"] = {name.removeprefix("source/"): hashlib.sha256(data).hexdigest()
                                        for name, data in sorted(payloads.items())}
            project = tomllib.loads((build_source / "pyproject.toml").read_text(encoding="utf-8"))
            declared = project["tool"]["setuptools"]["data-files"]["share/parrhesia"]
            if set(declared) != set(RUNTIME_DOCUMENTS):
                raise ValueError("Wheel document inventory differs from the shared runtime inventory")
            command = [sys.executable, "-I", "-m", "pip", "--isolated", "wheel", "--no-deps", "--no-cache-dir",
                       "--wheel-dir", work / "wheels"]
            if not build_isolation:
                command += ["--no-build-isolation", "--no-index"]
            run("build", [*command, build_source], work)
            wheels = list((work / "wheels").glob("*.whl"))
            if len(wheels) != 1:
                raise ValueError("Expected exactly one built wheel")
            wheel = wheels[0]
            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
                for relative in RUNTIME_DOCUMENTS:
                    matches = [n for n in names if n.endswith(".data/data/share/parrhesia/" + Path(relative).name)]
                    if len(matches) != 1 or archive.read(matches[0]) != (build_source / relative).read_bytes():
                        raise ValueError(f"Wheel document missing or changed: {relative}")
                for path in (build_source / "parrhesia").rglob("*.py"):
                    relative = path.relative_to(build_source).as_posix()
                    if archive.read(relative) != path.read_bytes():
                        raise ValueError(f"Wheel code differs from build snapshot: {relative}")
            shutil.copyfile(wheel, output / wheel.name)
            summary["wheel"] = {"file": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "bytes": wheel.stat().st_size}
            summary["checks"]["wheel_inventory_and_bytes"] = True
            venv = work / "venv"
            run("venv", [sys.executable, "-I", "-m", "venv", venv], work)
            bindir = venv / ("Scripts" if os.name == "nt" else "bin")
            python = bindir / ("python.exe" if os.name == "nt" else "python")
            console = bindir / ("parrhesia.exe" if os.name == "nt" else "parrhesia")
            run("install", [python, "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", wheel], work)
            outside = work / "outside"
            outside.mkdir()
            # A cwd document must never shadow the wheel's packaged contract.
            (outside / "docs").mkdir()
            (outside / "docs/contract.md").write_text("WRONG CWD CONTRACT", encoding="utf-8")
            probe = r'''
import json,sys
from pathlib import Path
from importlib.metadata import distribution
import parrhesia
from parrhesia.server import contract_text
package_root=Path(parrhesia.__file__).resolve().parent.parent
assert Path(parrhesia.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert not Path(parrhesia.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert not (package_root/'docs/contract.md').exists()
assert not (package_root/'share/parrhesia/contract.md').exists()
dist=distribution('parrhesia-review')
docs=[dist.locate_file(p) for p in dist.files if str(p).replace('\\','/').endswith('share/parrhesia/contract.md')]
assert len(docs)==1 and docs[0].is_file()
assert contract_text()==docs[0].read_text(encoding='utf-8')
print(json.dumps({'version':parrhesia.__version__,'distribution_fallback':True,'import_inside_venv':True}))
'''
            imported = json.loads(run("isolated-import", [python, "-I", "-c", probe, source], outside))
            assert imported["version"] == project["project"]["version"], "Installed version differs from build snapshot"
            summary["checks"].update(imported)
            expected_contract = (build_source / "docs/contract.md").read_text(encoding="utf-8").encode("utf-8")
            assert run("console-contract", [console, "contract"], outside) == expected_contract, "Console contract differs from packaged document"
            assert run("module-version", [python, "-I", "-m", "parrhesia", "--version"], outside).decode().strip() == imported["version"], "Module version differs"
            assert run("console-version", [console, "--version"], outside).decode().strip() == imported["version"], "Console version differs"
            frames = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "wheel-check", "version": "1"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "parrhesia_contract", "arguments": {}}},
            ]
            wire = ("\n".join(json.dumps(frame) for frame in frames) + "\n").encode()
            responses = [json.loads(line) for line in run("mcp", [console, "serve", "--workspace", outside], outside, wire).splitlines()]
            assert responses[0]["result"]["serverInfo"]["version"] == imported["version"], "MCP version differs"
            assert responses[2]["result"]["structuredContent"]["contract"].encode() == expected_contract, "MCP contract differs"
            tools = responses[1]["result"]["tools"]
            assert {"parrhesia_contract", "parrhesia_set_ledger"} <= {t["name"] for t in tools}, "Required MCP tools missing"
            summary["checks"]["stdio_tools"] = len(tools)
            # Fixed synthetic fixture checks a persisted case, not a scientific outcome.
            demo_path = outside / "synthetic-fixture"
            demo = json.loads(run("synthetic-fixture", [console, "demo", "--output", demo_path], outside))
            database = demo_path / ".parrhesia/state.sqlite3"
            before = database.read_bytes()
            report = json.loads(run("case-report", [console, "report", "--workspace", demo_path,
                                                   "--case-id", demo["case_id"], "--output", "reports/case.html"], outside))
            assert database.read_bytes() == before, "Report command changed saved database bytes"
            html = Path(report["path"]).read_text(encoding="utf-8")
            assert demo["case_id"] in html and "saved_record_only" in html, "Report omits case identity or verification scope"
            shutil.copyfile(report["path"], output / "synthetic-case.html")
            summary["case_report"] = {"file": "synthetic-case.html", "sha256": report["sha256"],
                                      "fixture": "SYNTHETIC_NO_MODEL_CALL", "case_id": demo["case_id"]}
            summary["checks"].update(console_and_module=True, case_report_read_only=True)
            summary["status"] = "passed"
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True, help="New directory for the wheel, command logs and report.json")
    parser.add_argument("--no-build-isolation", action="store_true", help="Offline local build using installed backend; install/import isolation stays mandatory")
    args = parser.parse_args()
    try:
        result = check_wheel(args.source, args.output, build_isolation=not args.no_build_isolation)
    except (OSError, ValueError, AssertionError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "wheel": result["wheel"], "checks": result["checks"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
