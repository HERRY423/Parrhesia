"""Measure exactly the current Stage 0 policy inputs, separate from historical runs."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from parrhesia import __version__
from parrhesia.mcp_schemas import tool_definitions

POLICY_FILES = (
    "templates/AGENTS.parrhesia.codex.md", "templates/AGENTS.parrhesia.md",
    "skills/parrhesia-l2-reference/SKILL.md", "skills/parrhesia-review/SKILL.md",
    "skills/parrhesia-review/references/workflow.md",
)


def policy_inputs(root: Path) -> dict:
    raw = {name: (root / name).read_bytes() for name in POLICY_FILES}
    compact, full, l2, skill, workflow = [raw[name].decode("utf-8").replace("\r\n", "\n").strip() for name in POLICY_FILES]
    prompts = {
        "A_baseline": "Evaluate the draft claim strictly against the provided evidence. No external policy instructions apply.",
        "B_compact_l1": compact,
        "B_compact_l2": "\n\n".join((compact, l2)),
        "B_full": "\n\n".join((full, l2, workflow)),
        "E_full_l2_workflow": "\n\n".join((skill, compact, l2, workflow)),
    }
    tools = tool_definitions()
    return {
        "runtime_version": __version__, "policy_layout": "layered-v1",
        "policy_source_files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in raw.items()},
        "policy_size_bytes": {
            "B_compact_agents_block_bytes": len(raw[POLICY_FILES[0]]),
            "B_compact_l2_reference_skill_bytes": len(raw[POLICY_FILES[2]]),
            "B_full_policy_bytes": len(prompts["B_full"].encode()),
            "E_full_l2_workflow_skill_bytes": len(prompts["E_full_l2_workflow"].encode()),
            "E_skill_entrypoint_bytes": len(raw[POLICY_FILES[3]]),
            "B_full_entrypoint_bytes": len(raw[POLICY_FILES[1]]),
        },
        "arm_system_prompts": prompts,
        "arm_prompt_bytes": {arm: len(value.encode("utf-8")) for arm, value in prompts.items()},
        "mcp": {"tool_count": len(tools), "compact_utf8_bytes": len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), "schema_mode": "shared", "tool_profile": "full"},
        "measurement_basis": "raw source bytes; assembled prompt UTF-8 with LF and strip; compact tool JSON; not model token counts",
    }


def input_fingerprint(root: Path, suite: Path) -> dict:
    paths = [*sorted((root / "parrhesia").glob("*.py")), root / "scripts/run-stage0-eval.py",
             *sorted((root / "scripts").glob("eval_*.py")), root / "scripts/check-eval-leakage.py",
             root / "docs/evaluation/text-advisory-cases-v1.json", suite]
    return {p.relative_to(root).as_posix() if p.is_relative_to(root) else "external_suite": hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
