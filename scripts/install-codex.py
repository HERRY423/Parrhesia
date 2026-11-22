"""Synchronize the Codex policy block and both complete layered skill directories."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from parrhesia.adapters import (collect_skills_payloads, commit_transaction, contained,
                                check_owned_files, reject_link, sha256_bytes)
START_MARKER = "<!-- parrhesia:judgment-policy:start -->"
END_MARKER = "<!-- parrhesia:judgment-policy:end -->"
SKILL_REL_PATH = Path("skills") / "parrhesia-l2-reference" / "SKILL.md"

LEGACY_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "- 规则冲突时按以下顺序取舍:用户当前明确指令(更严格者优先)> 数据保密与花费上限 > 科学证据规则 > 流程规则。",
        "- 指令权限:平台系统指令 > 平台开发者指令 > 用户消息。在此边界内按以下顺序取舍:数据保密与花费上限 > 证据真实 > 强度匹配 > 表达已支持的贡献 > 效率;用户可决定范围、格式、语言与流程简化,但不得改变证据等级与判定。",
    ),
    (
        "2. 每个结论标注主张级别:描述性观察 / 相关 / 可预测 / 机制线索 / 因果或必要充分性。",
        "2. 每个结论标注二维分类:主张类型(claim_type) × 类型内证据等级(evidence_level) + 适用范围(scope),不排成单一线性阶梯。",
    ),
    (
        '8. 审查分档:L0 不启动 / L1 仅规则 / L2 完整流程;不能做独立审查时必须标注"非独立审查"。',
        '8. 审查分档:首行写 [L0]、[L1](含 L1-Judge / L1-Explore 五段契约)或 [L2];不能做独立审查时必须标注"非独立审查"。',
    ),
    (
        '- 每个结论都要标明主张级别:**描述性观察 / 相关 / 可预测 / 机制线索 / 因果或必要充分性**。用词与级别保持一致:相关性证据用"与……相关""可预测……"表述,不写"调控""驱动""导致";计算预测不写"证明"。',
        '- 每个结论都要标明二维分类:**主张类型(claim_type) × 类型内证据等级(evidence_level) + 范围(scope)**(详见下方 Parrhesia 区块)。用词与证据等级保持一致:关联证据用"与……相关"表述,不写"调控""驱动""导致";预测模型不自动等于机制或因果;经验因果语言须具备设计族 + estimand + 识别假设 + 证伪/敏感度依据,必要与充分分别检验。',
    ),
    (
        "1. 核心发现与贡献,每条注明主张级别",
        "1. 核心发现与贡献(注明类型 × 类型内证据等级 + 范围)",
    ),
)

FORBIDDEN_LEGACY_SNIPPETS: tuple[str, ...] = (
    "描述性观察 / 相关 / 可预测 / 机制线索 / 因果或必要充分性",
    "L0 不启动:普通翻译、格式修改、简单事实回答、局部代码修正;探索阶段的假设生成",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_codex_block(source: Path) -> str:
    template_path = source / "templates" / "AGENTS.parrhesia.codex.md"
    if not template_path.is_file():
        raise ValueError(f"Missing template: {template_path}")
    raw = template_path.read_text(encoding="utf-8")
    start = raw.find(START_MARKER)
    end = raw.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError("templates/AGENTS.parrhesia.codex.md is missing judgment-policy markers")
    return raw[start : end + len(END_MARKER)]


def transform_agents_text(original: str, codex_block: str) -> str:
    updated = original.replace("\r\n", "\n").replace("\r", "\n")
    for old_text, new_text in LEGACY_REPLACEMENTS:
        updated = updated.replace(old_text, new_text)
    if START_MARKER in updated or END_MARKER in updated:
        start = updated.find(START_MARKER)
        end = updated.find(END_MARKER)
        if start == -1 or end == -1 or end < start or updated.count(START_MARKER) != 1 or updated.count(END_MARKER) != 1:
            raise ValueError("Malformed or duplicate parrhesia:judgment-policy markers in target AGENTS.md")
        updated = updated[:start] + codex_block + updated[end + len(END_MARKER) :]
    else:
        sep = "" if not updated else ("\n" if updated.endswith("\n\n") else ("\n\n" if not updated.endswith("\n") else "\n"))
        updated = f"{updated}{sep}{codex_block}\n"
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def sync_codex_agents(codex_home: Path, source: Path = ROOT, *, check_only: bool = False) -> dict:
    reject_link(codex_home)
    source = source.resolve()
    codex_home = codex_home.resolve()
    if not codex_home.is_dir():
        raise ValueError(f"Codex home directory does not exist: {codex_home}")
    agents_path = contained(codex_home, "AGENTS.md")
    metadata_path = contained(codex_home, ".parrhesia-codex-sync.json")
    codex_block = load_codex_block(source)
    # Preflight the whole layered bundle before modifying any target.
    payloads = collect_skills_payloads(source, "skills")
    payloads = {name: data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                if name.endswith(".md") else data for name, data in payloads.items()}
    original = agents_path.read_text(encoding="utf-8-sig") if agents_path.exists() else ""
    expected = transform_agents_text(original, codex_block)
    for snippet in FORBIDDEN_LEGACY_SNIPPETS:
        if snippet in expected:
            raise ValueError(f"Legacy v0.1.0 snippet remained after transformation: {snippet}")
    payloads["AGENTS.md"] = expected.encode("utf-8")
    files = {name: sha256_bytes(data) for name, data in sorted(payloads.items())}
    errors, _ = check_owned_files(codex_home, files)
    in_sync = not errors
    common = {
        "agents_path": str(agents_path), "agents_sha256": files["AGENTS.md"],
        "block_sha256": sha256_text(codex_block),
        "l2_reference_skill_path": str(codex_home / SKILL_REL_PATH),
        "l2_reference_skill_sha256": files[SKILL_REL_PATH.as_posix()],
        "review_skill_path": str(codex_home / "skills/parrhesia-review/SKILL.md"),
        "files": files,
    }
    if check_only:
        if errors:
            raise ValueError("Codex installation is out of sync: " + "; ".join(errors))
        return {"status": "in_sync", **common}
    old = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    if in_sync and old.get("owner") == "parrhesia-codex-sync-v3" and old.get("files") == files:
        return {"status": "unchanged", **old, "backup_path": None, "skill_backup_path": None, "backup_directory": None}
    metadata = {"owner": "parrhesia-codex-sync-v3", **common,
                "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    payloads[".parrhesia-codex-sync.json"] = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    changed, _, backup = commit_transaction(codex_home, payloads, ".parrhesia-backups")
    backup_root = codex_home / backup if backup else None
    backup_path = backup_root / "AGENTS.md" if backup_root else None
    skill_backup = backup_root / SKILL_REL_PATH if backup_root else None
    return {"status": "updated", **metadata, "changed_files": changed,
            "backup_directory": str(backup_root) if backup_root else None,
            "backup_path": str(backup_path) if backup_path and backup_path.is_file() else None,
            "skill_backup_path": str(skill_backup) if skill_backup and skill_backup.is_file() else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize Codex policy and both complete layered skills.")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex", help="Directory containing Codex AGENTS.md and skills/")
    parser.add_argument("--source", type=Path, default=ROOT, help="Parrhesia repository root")
    parser.add_argument("--check", action="store_true", help="Read-only check of Codex policy, both skills and every reference file")
    args = parser.parse_args(argv)
    try:
        result = sync_codex_agents(args.codex_home, args.source, check_only=args.check)
    except (OSError, ValueError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
