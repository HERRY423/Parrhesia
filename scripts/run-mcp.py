"""Launch the bundled stdlib server without pip or a writable plugin directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import sys


def main() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Parrhesia requires Python 3.11 or newer.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="Explicit project directory; overrides the environment.")
    parser.add_argument("--default-workspace", help="Client-provided persistent plugin workspace.")
    args = parser.parse_args()
    selected = args.workspace or os.environ.get("PARRHESIA_WORKSPACE") or args.default_workspace
    if not selected or "${" in selected:
        parser.error("Set an absolute workspace or let the client expand PLUGIN_DATA.")
    workspace = Path(selected).expanduser()
    if not workspace.is_absolute():
        parser.error("The workspace must be an absolute path.")
    if not args.workspace and not os.environ.get("PARRHESIA_WORKSPACE"):
        workspace.mkdir(parents=True, exist_ok=True)
    elif not workspace.is_dir():
        parser.error("The explicitly selected workspace must already exist.")
    package_root = Path(__file__).resolve().parent.parent
    if not (package_root / "parrhesia" / "__main__.py").is_file():
        parser.error("Bundled parrhesia/__main__.py is missing; reinstall the complete plugin.")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(package_root))
    sys.argv = ["parrhesia", "serve", "--workspace", str(workspace.resolve())]
    runpy.run_module("parrhesia", run_name="__main__")


if __name__ == "__main__":
    main()
