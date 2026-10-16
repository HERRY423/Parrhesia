"""Build an allowlisted Agent Plugins directory ZIP, without runtime data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("plugin.json", "mcp.json", "README.md", "AGENTS.md", "pyproject.toml", ".gitignore")
DIRECTORIES = ("parrhesia", "scripts", "skills", "templates", "docs", "tests")
EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".ps1", ".txt"}


def build(output: Path) -> dict:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    files = [ROOT / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        files.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in EXTENSIONS and "__pycache__" not in path.parts)
    contents = {}
    for path in sorted(files):
        if not path.is_file() or path.is_symlink() or path.resolve().is_relative_to(ROOT) is False:
            raise ValueError(f"Missing or unsafe release source: {path.name}")
        contents[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    records = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in contents.items()}
    contents["RELEASE-MANIFEST.json"] = (json.dumps({"name": manifest["name"], "version": manifest["version"], "format": "Agent Plugins 1.0.0", "files": records, "evidence_scope": "package content identity only"}, indent=2) + "\n").encode("utf-8")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, data)
    data = buffer.getvalue()
    if output.exists():
        if output.read_bytes() != data:
            raise ValueError("Output already exists with different bytes; choose a new release path")
    else:
        with output.open("xb") as stream:
            stream.write(data)
    return {"path": str(output), "sha256": hashlib.sha256(data).hexdigest(), "files": len(contents), "bytes": len(data)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
