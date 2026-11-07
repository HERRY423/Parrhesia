"""Synchronize Codex AGENTS.md (compact block) and parrhesia-l2-reference skill from generated Parrhesia v0.2.0 targets."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
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


def load_l2_reference_skill(source: Path) -> str:
    skill_path = source / SKILL_REL_PATH
    if not skill_path.is_file():
        raise ValueError(f"Missing generated skill: {skill_path}")
    raw = skill_path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.endswith("\n"):
        raw += "\n"
    return raw


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
    source = source.resolve()
    codex_home = codex_home.resolve()
    if not codex_home.is_dir():
        raise ValueError(f"Codex home directory does not exist: {codex_home}")
    agents_path = codex_home / "AGENTS.md"
    skill_target_path = codex_home / SKILL_REL_PATH
    codex_block = load_codex_block(source)
    expected_skill = load_l2_reference_skill(source)
    original = agents_path.read_text(encoding="utf-8-sig") if agents_path.exists() else ""
    expected = transform_agents_text(original, codex_block)
    for snippet in FORBIDDEN_LEGACY_SNIPPETS:
        if snippet in expected:
            raise ValueError(f"Legacy v0.1.0 snippet remained after transformation: {snippet}")
    normalized_original = original.replace("\r\n", "\n").replace("\r", "\n")
    agents_in_sync = agents_path.exists() and normalized_original == expected

    original_skill = skill_target_path.read_text(encoding="utf-8-sig") if skill_target_path.exists() else ""
    normalized_skill = original_skill.replace("\r\n", "\n").replace("\r", "\n")
    skill_in_sync = skill_target_path.exists() and normalized_skill == expected_skill
    in_sync = agents_in_sync and skill_in_sync

    if check_only:
        if not agents_in_sync:
            raise ValueError(f"{agents_path} is out of sync with templates/AGENTS.parrhesia.codex.md")
        if not skill_in_sync:
            raise ValueError(f"{skill_target_path} is out of sync with {SKILL_REL_PATH.as_posix()}")
        return {
            "status": "in_sync",
            "agents_path": str(agents_path),
            "agents_sha256": sha256_text(expected),
            "block_sha256": sha256_text(codex_block),
            "l2_reference_skill_path": str(skill_target_path),
            "l2_reference_skill_sha256": sha256_text(expected_skill),
        }
    backup_path = None
    skill_backup_path = None
    backup_dir = codex_home / ".parrhesia-backups"
    if agents_path.exists() and not agents_in_sync:
        backup_dir.mkdir(parents=True, exist_ok=True)
        orig_hash = sha256_text(normalized_original)[:12]
        backup_file = backup_dir / f"AGENTS.{orig_hash}.bak.md"
        if not backup_file.exists():
            backup_file.write_text(normalized_original, encoding="utf-8", newline="\n")
        backup_path = str(backup_file)
    if skill_target_path.exists() and not skill_in_sync:
        backup_dir.mkdir(parents=True, exist_ok=True)
        skill_hash = sha256_text(normalized_skill)[:12]
        skill_backup_file = backup_dir / f"parrhesia-l2-reference.SKILL.{skill_hash}.bak.md"
        if not skill_backup_file.exists():
            skill_backup_file.write_text(normalized_skill, encoding="utf-8", newline="\n")
        skill_backup_path = str(skill_backup_file)
    agents_path.write_text(expected, encoding="utf-8", newline="\n")
    skill_target_path.parent.mkdir(parents=True, exist_ok=True)
    skill_target_path.write_text(expected_skill, encoding="utf-8", newline="\n")
    metadata = {
        "owner": "parrhesia-codex-sync-v2",
        "agents_path": str(agents_path),
        "agents_sha256": sha256_text(expected),
        "block_sha256": sha256_text(codex_block),
        "l2_reference_skill_path": str(skill_target_path),
        "l2_reference_skill_sha256": sha256_text(expected_skill),
        "backup_path": backup_path,
        "skill_backup_path": skill_backup_path,
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path = codex_home / ".parrhesia-codex-sync.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"status": "unchanged" if in_sync else "updated", **metadata}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize Codex AGENTS.md (compact block) and parrhesia-l2-reference skill.")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex", help="Directory containing Codex AGENTS.md and skills/")
    parser.add_argument("--source", type=Path, default=ROOT, help="Parrhesia repository root")
    parser.add_argument("--check", action="store_true", help="Check whether Codex AGENTS.md and parrhesia-l2-reference skill are in sync")
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
