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
    "l2_reference": "skills/parrhesia-l2-reference/SKILL.md",
    "frozen_input": "templates/chatgpt/01-frozen-input.md",
    "frozen_input_blind": "templates/chatgpt/01-frozen-input-blind.md",
    "overclaim": "templates/chatgpt/02-overclaim.md",
    "underclaim": "templates/chatgpt/03-underclaim.md",
    "adjudication": "templates/chatgpt/04-adjudication.md",
    "handoff": "templates/chatgpt/05-handoff-record.md",
}
MODULES = ("compact_core", "core", "l2_protocol", "plugin_tools", "agentmuxer")
TARGET_MODULES = {
    "repository": ("compact_core",),
    "generic": ("core", "l2_protocol", "plugin_tools", "agentmuxer"),
    "codex": ("compact_core",),
    "chatgpt": ("core", "l2_protocol"),
    "skill": ("core", "l2_protocol", "plugin_tools", "agentmuxer"),
}
PRIMARY_TARGETS = tuple(TARGET_MODULES.keys())
GENERATED = "<!-- Generated from policy/parrhesia-policy.md; DO NOT EDIT. Run: python scripts/generate-policy.py -->"
PATTERN = re.compile(r"<!-- source:([a-z0-9_]+):start -->\n(.*?)\n<!-- source:\1:end -->", re.DOTALL)
MODULE_DECLARATION = re.compile(r"<!-- modules:\s*([a-z0-9_,\s]+)\s*-->")


def render(source: str) -> dict[str, str]:
    source = source.replace("\r\n", "\n")
    matches = list(PATTERN.finditer(source))
    names = [match[1] for match in matches]
    expected_sections = set(MODULES) | set(TARGETS)
    if len(names) != len(set(names)) or set(names) != expected_sections:
        raise ValueError("Policy source has missing, duplicate or unknown sections")
    if source.count("<!-- source:") != 2 * len(matches):
        raise ValueError("Malformed policy section markers")
    sections = {match[1]: match[2].strip() for match in matches}
    for mod in MODULES:
        if not sections[mod] or "{{" in sections[mod]:
            raise ValueError(f"Module '{mod}' must be nonempty and contain no placeholders")

    output = {}
    for name, path in TARGETS.items():
        template = sections[name]
        if template.count("{{generated}}") != 1:
            raise ValueError(f"Missing or duplicate generation marker: {name}")

        result = template.replace("{{generated}}", GENERATED)
        if name in TARGET_MODULES:
            decl_match = MODULE_DECLARATION.search(template)
            if decl_match:
                if template.count("<!-- modules:") != 1:
                    raise ValueError(f"Duplicate module declaration in {name}")
                declared = tuple(m.strip() for m in decl_match.group(1).split(",") if m.strip())
                if declared != TARGET_MODULES[name]:
                    raise ValueError(f"Module declaration mismatch for {name}: got {declared}, expected {TARGET_MODULES[name]}")
                combined = "\n\n".join(sections[m] for m in declared)
                result = result.replace(decl_match.group(0), combined)
            else:
                expected = TARGET_MODULES[name]
                for mod in MODULES:
                    count = template.count(f"{{{{{mod}}}}}")
                    should_have = 1 if mod in expected else 0
                    if count != should_have:
                        raise ValueError(f"Invalid module placeholder for {name}: {mod}")
                for mod in expected:
                    result = result.replace(f"{{{{{mod}}}}}", sections[mod])
        else:
            if "<!-- modules:" in template:
                raise ValueError(f"Unexpected module declaration in non-primary target: {name}")

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
