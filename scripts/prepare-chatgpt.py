"""Create a local, template-only ChatGPT handoff kit; no account or network access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "templates/AGENTS.parrhesia.chatgpt.md",
    "templates/chatgpt/01-frozen-input.md",
    "templates/chatgpt/02-overclaim.md",
    "templates/chatgpt/03-underclaim.md",
    "templates/chatgpt/04-adjudication.md",
    "templates/chatgpt/05-handoff-record.md",
    "docs/chatgpt-integration.md",
)
START = """# Parrhesia ChatGPT 交接套件

先读 [使用说明](docs/chatgpt-integration.md)，再复制
[ChatGPT 指令](templates/AGENTS.parrhesia.chatgpt.md)。

templates/chatgpt/ 按 01–05 提供冻结资料、两侧提示词、裁决和操作者记录。
每侧只接收自己的提示词和同版本冻结资料，不要上传整套文件给审查者。
这是空白模板，尚未执行审查；没有持久工具记录与机械核对。
KIT-MANIFEST.json 只核对套件原始文件，不核对后来填写的资料或科学结论。
"""


def reject_links(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("Linked paths are not allowed")
        if item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("Reparse points are not allowed")


def prepare(output: Path, source: Path = ROOT) -> dict:
    output = output.absolute()
    reject_links(output)
    if output.exists():
        raise ValueError("Output already exists; choose a new directory")
    source = source.absolute()
    contents = {"START-HERE.md": START.encode("utf-8")}
    # Read the entire allowlist before creating output: a missing source leaves no kit.
    for name in FILES:
        path = source / name
        reject_links(path)
        contents[name] = path.read_bytes()
    manifest = {
        "format": "parrhesia-chatgpt-kit-v1",
        "mode": "manual_text_protocol",
        "native_host_acceptance": "NOT_RUN",
        "model_effectiveness": "NOT_MEASURED",
        "evidence_scope": "template file identity only; no case evidence included",
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in sorted(contents.items())},
    }
    output.mkdir(parents=True, exist_ok=False)
    # Keep partial output on I/O failure for inspection; never overwrite or remove it.
    for name, data in contents.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
    with (output / "KIT-MANIFEST.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"path": str(output), "files": len(contents) + 1, "mode": manifest["mode"], "native_host_acceptance": "NOT_RUN"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.output)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": "kit_not_created_or_incomplete", "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
