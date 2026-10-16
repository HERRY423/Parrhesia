"""Deterministic generation of host instructions from one editable Markdown source."""
from __future__ import annotations

from pathlib import Path
import re


SOURCE = "policy/parrhesia-policy.md"
TARGETS = {
    "repository": "AGENTS.md",
    "generic": "templates/AGENTS.parrhesia.md",
    "codex": "templates/AGENTS.parrhesia.codex.md",
    "chatgpt": "templates/AGENTS.parrhesia.chatgpt.md",
    "skill": "skills/parrhesia-review/SKILL.md",
    "frozen_input": "templates/chatgpt/01-frozen-input.md",
    "overclaim": "templates/chatgpt/02-overclaim.md",
    "underclaim": "templates/chatgpt/03-underclaim.md",
    "adjudication": "templates/chatgpt/04-adjudication.md",
    "handoff": "templates/chatgpt/05-handoff-record.md",
}
PRIMARY_TARGETS = ("repository", "generic", "codex", "chatgpt", "skill")
GENERATED = "<!-- Generated from policy/parrhesia-policy.md; DO NOT EDIT. Run: python scripts/generate-policy.py -->"
PATTERN = re.compile(r"<!-- source:([a-z_]+):start -->\n(.*?)\n<!-- source:\1:end -->", re.DOTALL)


def render(source: str) -> dict[str, str]:
    source = source.replace("\r\n", "\n")
    matches = list(PATTERN.finditer(source))
    names = [match[1] for match in matches]
    if len(names) != len(set(names)) or set(names) != {"policy", *TARGETS}:
        raise ValueError("Policy source has missing, duplicate or unknown sections")
    if source.count("<!-- source:") != 2 * len(matches):
        raise ValueError("Malformed policy section markers")
    sections = {match[1]: match[2].strip() for match in matches}
    policy = sections["policy"]
    if not policy or "{{" in policy:
        raise ValueError("Shared policy must be nonempty and contain no placeholders")
    output = {}
    for name, path in TARGETS.items():
        template = sections[name]
        if template.count("{{generated}}") != 1:
            raise ValueError(f"Missing or duplicate generation marker: {name}")
        expected = 1 if name in PRIMARY_TARGETS else 0
        if template.count("{{policy}}") != expected:
            raise ValueError(f"Invalid shared policy inclusion: {name}")
        result = template.replace("{{generated}}", GENERATED).replace("{{policy}}", policy)
        if "{{" in result or "}}" in result:
            raise ValueError(f"Unresolved placeholder: {name}")
        output[path] = result + "\n"
    return output


def expected_files(root: Path) -> dict[str, str]:
    return render((root / SOURCE).read_text(encoding="utf-8"))


def drifted_files(root: Path) -> list[str]:
    expected = expected_files(root)
    return [name for name, content in expected.items()
            if not (root / name).is_file() or (root / name).read_text(encoding="utf-8") != content]


def check_generated(root: Path) -> None:
    stale = drifted_files(root)
    if stale:
        raise ValueError("Generated policy drift: " + ", ".join(stale) + "; run python scripts/generate-policy.py")


def generate(root: Path) -> list[str]:
    expected = expected_files(root)  # Validate the complete source before any write.
    changed = []
    for name, content in expected.items():
        path = root / name
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        changed.append(name)
    return changed
