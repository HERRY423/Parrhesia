#!/usr/bin/env python3
"""Static leakage and n-gram overlap checker for Parrhesia Stage 0 benchmarks.

The original overlap gate covers the legacy gates.py lexicon. New advisory
grammar is audited separately with all component overlaps exposed and a copied
case-literal guard. Exposed samples are regression tests, not a fresh holdout.

Extracts lexical phrase lists, inline marker tuples, and heuristic regex patterns
directly from `parrhesia/gates.py` (via module import + AST inspection), then
verifies that:
1. Held-out benchmark subsets (`heldout_generalization`,
   `heldout_realistic_controls`, `heldout_adversarial_paraphrases`, and any
   exported held-out prompt packets) have zero lexical phrase, n-gram, or
   heuristic regex overlap with `parrhesia/gates.py`.
2. Exported `--mode prompt-export` `arms` prompts contain zero ground-truth,
   scenario-label, or expected-outcome answer leakage across all subsets.

Usage:
    python scripts/check-eval-leakage.py --strict
    python scripts/check-eval-leakage.py --suite docs/evaluation/stage0-cases.json --prompt-export tmp/stage0-prompt-packets.json --strict
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GATES_PATH = REPO_ROOT / "parrhesia" / "gates.py"
DEFAULT_SUITE_PATH = REPO_ROOT / "docs" / "evaluation" / "stage0-cases.json"

# Module-level constant names in parrhesia/gates.py representing lexical rule lists
# (checked dynamically alongside any *_PHRASES / *_MARKERS / *_BLACKLIST globals).
KNOWN_LEXICON_CONSTANTS = (
    "CONTRADICTING_PHRASES",
    "NULL_OR_REFUTING_EVIDENCE_PHRASES",
    "OUTCOME_STRIPPED_EVIDENCE_PHRASES",
    "SELECTIVE_EXECUTION_OMISSION_PHRASES",
    "FALSE_SINGLE_RUN_MULTIPLICITY_PHRASES",
    "MULTIPLICITY_ADJUSTMENT_MARKERS",
)
LEXICON_NAME_SUFFIXES = ("_PHRASES", "_MARKERS", "_BLACKLIST", "_LEXICON")
LEXICON_NAME_EXCLUSIONS = {
    "CONTRADICTING_RELATIONS",
    "NON_CONTRADICTING_NEGATIONS",
    "PLACEHOLDER_TOKENS",
    "TRIVIAL_REASONS",
    "QUOTE_STOPWORDS",
    "DISPOSITION_BOILERPLATE",
    "CJK_STOPWORDS",
    "NON_PRIMARY_FAILED_FORK_ROLES",
    "ESSENTIAL_STAT_CHECKS",
}

HEURISTIC_REGEX_NAMES = (
    "BOILERPLATE_OVERHEDGING_RE",
    "NO_RANDOMIZATION_RE",
    "FUTURE_OR_NO_EXTERNAL_RE",
    "FUTURE_OR_NO_PROSPECTIVE_RE",
)

# Explicit phrase forms represented inside BOILERPLATE_OVERHEDGING_RE for n-gram checks.
BOILERPLATE_PHRASE_EXPANSIONS = (
    "无法得出确定结论",
    "尚无法得出确定结论",
    "难以得出明确结论",
    "仅供参考",
    "尚无法下结论",
    "cannot draw firm conclusion",
    "cannot draw firm conclusions",
    "cannot draw definitive conclusion",
    "cannot draw definitive conclusions",
    "cannot draw any firm conclusion",
    "cannot draw any firm conclusions",
    "cannot draw any definitive conclusion",
    "cannot draw any definitive conclusions",
    "no firm conclusion can be drawn",
    "no firm conclusions can be drawn",
    "for reference only",
    "remains inconclusive pending",
)

# Positive allow-list variable names and stems in contradictory_evidence_kind
# that guard against false rejections rather than functioning as blacklists.
ALLOWLIST_VAR_NAMES = {"ext_markers", "int_markers"}
ALLOWLIST_STEMS = {
    "random",
    "rct",
    "interven",
    "knockout",
    "crispr",
    "perturb",
    "随机",
    "干预",
    "敲除",
    "external cohort",
    "external validation",
    "external hospital",
    "independent hospital",
    "prospective cohort",
    "external test",
    "external dataset",
    "external site",
    "independent cohort",
    "independent validation",
    "independent dataset",
    "geographic validation",
    "double-blind",
    "placebo-controlled",
    "sham-controlled",
    "安慰剂对照",
    "外部测试",
    "独立验证",
    "独立队列",
    "外部验证",
    "外部队列",
    "前瞻性",
}

NGRAM_FUNCTION_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "and",
    "to",
    "by",
    "with",
    "without",
    "at",
    "that",
    "this",
}

# Prompt-export ground-truth / scenario identifier leakage markers inside `arms`.
ANSWER_LEAKAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("expected_target", r"\bexpected_target\b"),
        ("expected_verdict", r"\bexpected_verdict\b"),
        ("expected_error", r"\bexpected_error(?:_code)?\b"),
        ("expected_rubber_stamp", r"\bexpected_rubber_stamp(?:_error)?\b"),
        ("expected_calibrated", r"\bexpected_calibrated(?:_verdict|_mode)?\b"),
        ("expected_gate_outcome", r"\bexpected_gate_outcome\b"),
        ("target_classification_header", r"\bTarget\s+classification\s*:"),
        ("scenario_P1_null_flip", r"\bP1_null_flip\b"),
        ("scenario_P2_outcome_stripped", r"\bP2_outcome_stripped\b"),
        ("scenario_P3_synthetic_swap", r"\bP3_synthetic_swap\b"),
        ("scenario_F1_hidden_failed_forks", r"\bF1_hidden_failed_forks\b"),
        ("scenario_F2_unadjusted_multi_fork", r"\bF2_unadjusted_multi_fork\b"),
        ("scenario_U1_false_abstention", r"\bU1_false_abstention\b"),
        ("paired_id_PAIR", r"\bPAIR-0\d\b"),
        ("twin_role_label", r"\b(?:strong_twin|weak_twin)\b"),
        ("lineage_id_LIN", r"\bLIN-0\d\b"),
        ("rubber_stamp_marker", r"\brubber_stamp\b"),
        ("keyed_evidence_kind", r"\bevidence_kind\s*="),
        ("keyed_error_code", r"\berror_code\s*="),
        ("keyed_verdict", r"\bverdict\s*="),
    )
)

# Fields inside suite JSON that carry structural schema enums or ground truth
# rather than human-authored benchmark text.
NON_TEXT_FIELD_KEYS = {
    "case_code",
    "run_id",
    "pair_code",
    "twin_id",
    "id",
    "family",
    "scenario",
    "scenario_id",
    "perturbation_id",
    "statistical_unit",
    "claim_type",
    "evidence_level",
    "claim_basis",
    "evidence_kind",
    "source_kind",
    "kind",
    "basis",
    "verdict",
    "stance",
    "disposition",
    "expected_target",
    "expected_verdict",
    "expected_error",
    "expected_error_code",
    "expected_outcome",
    "expected_gate_outcome",
    "expected_classification",
    "expected_rubber_stamp_error",
    "expected_calibrated_verdict",
    "expected_calibrated_mode",
    "expected_advisory_hooks",
    "split",
    "partition",
}

ASCII_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)?")
CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]+")


def _load_gates_module(gates_path: Path) -> Any:
    """Load `parrhesia/gates.py` (or a standalone fixture gates module) dynamically."""
    resolved = gates_path.resolve()
    pkg_dir = resolved.parent
    repo_candidate = pkg_dir.parent
    has_pkg = (pkg_dir / "__init__.py").exists()
    mod_name = f"{pkg_dir.name}.gates" if has_pkg and resolved.stem == "gates" else f"_parrhesia_gates_inspect_{abs(hash(str(resolved)))}"

    added_sys_path = False
    repo_str = str(repo_candidate)
    if has_pkg and repo_str not in sys.path:
        sys.path.insert(0, repo_str)
        added_sys_path = True

    try:
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, resolved)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load gates module from {resolved}")
        module = importlib.util.module_from_spec(spec)
        if has_pkg:
            module.__package__ = pkg_dir.name
        spec.loader.exec_module(module)
        return module
    finally:
        if added_sys_path and repo_str in sys.path:
            sys.path.remove(repo_str)


def _is_schema_token_tuple(items: list[str]) -> bool:
    """Return True if all items look like internal snake_case enum identifiers."""
    return bool(items) and all(
        " " not in s and re.fullmatch(r"[a-z0-9_.*-]+", s) is not None and ("_" in s or "." in s or s in {"supported", "partially_supported", "accepted", "partial", "failed", "missing", "reported", "checked", "value", "uncertainty", "design", "statistics", "number", "execution", "citation"})
        for s in items
    )


def _extract_inline_lexicon_tuples(gates_source: str) -> dict[str, list[str]]:
    """Extract inline heuristic string tuples from gates.py functions via AST."""
    tree = ast.parse(gates_source)
    target_funcs = {
        "contradictory_evidence_kind",
        "contradictory_positive_evidence_text",
        "collect_lexical_advisories",
        "validate_execution_forks",
    }
    extracted: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in target_funcs:
            continue
        # Walk statements tracking assignments so named tuples get descriptive labels.
        parent_map: dict[int, ast.AST] = {}
        for parent in ast.walk(node):
            for child in ast.iter_child_nodes(parent):
                parent_map[id(child)] = parent

        for sub in ast.walk(node):
            if not isinstance(sub, (ast.Tuple, ast.List, ast.Set)):
                continue
            strings = [
                elt.value
                for elt in sub.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and len(elt.value) >= 3
            ]
            if len(strings) < 2 or _is_schema_token_tuple(strings):
                continue
            cleaned = [s for s in strings if s.lower() not in ALLOWLIST_STEMS]
            if len(cleaned) < 2 and not any(s.lower() in {"not randomized", "unrandomized"} for s in strings):
                continue
            # Preserve all non-allowlist markers (including short 2-item tuples like not randomized).
            kept = [s for s in strings if s.lower() not in ALLOWLIST_STEMS]
            if not kept:
                continue
            parent = parent_map.get(id(sub))
            var_label = None
            if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
                var_label = parent.targets[0].id
                if var_label in ALLOWLIST_VAR_NAMES or any(
                    tok in var_label.lower() for tok in ("allow", "override", "whitelist", "positive")
                ):
                    continue
            label = f"{node.name}:{var_label or f'line_{sub.lineno}'}"
            existing = extracted.setdefault(label, [])
            for item in kept:
                if item not in existing:
                    existing.append(item)
    return extracted


def extract_gates_lexicon(gates_path: Path = DEFAULT_GATES_PATH) -> dict[str, Any]:
    """Extract module-level phrase lists, inline marker tuples, and heuristic regexes."""
    gates_source = gates_path.read_text(encoding="utf-8")
    gates_mod = _load_gates_module(gates_path)

    phrase_groups: dict[str, list[str]] = {}
    for name, val in vars(gates_mod).items():
        if not name.isupper() or name in LEXICON_NAME_EXCLUSIONS:
            continue
        if name not in KNOWN_LEXICON_CONSTANTS and not name.endswith(LEXICON_NAME_SUFFIXES):
            continue
        if isinstance(val, (tuple, list, set)):
            items = [str(x).strip() for x in val if isinstance(x, str) and str(x).strip()]
            if items:
                phrase_groups[name] = items

    inline_groups = _extract_inline_lexicon_tuples(gates_source)
    phrase_groups.update(inline_groups)
    phrase_groups["BOILERPLATE_OVERHEDGING_EXPANSIONS"] = list(BOILERPLATE_PHRASE_EXPANSIONS)

    regex_patterns: dict[str, re.Pattern[str]] = {}
    for name in HEURISTIC_REGEX_NAMES:
        val = getattr(gates_mod, name, None)
        if isinstance(val, re.Pattern):
            regex_patterns[name] = val

    # Deduplicate phrases with source attribution.
    phrase_sources: dict[str, list[str]] = {}
    for src_name, items in phrase_groups.items():
        for raw in items:
            norm = raw.strip().lower()
            if norm:
                phrase_sources.setdefault(norm, []).append(src_name)

    return {
        "gates_path": str(gates_path),
        "phrase_groups": phrase_groups,
        "phrase_sources": phrase_sources,
        "regex_patterns": regex_patterns,
        "unique_phrase_count": len(phrase_sources),
    }


def _normalize_words(text: str) -> list[str]:
    """Extract normalized lowercase ASCII word/decimal tokens for n-gram checks."""
    return ASCII_WORD_RE.findall(text.lower())


def _is_cjk(text: str) -> bool:
    return bool(CJK_CHAR_RE.search(text))


def _compile_phrase_matcher(phrase: str) -> re.Pattern[str]:
    """Compile boundary-aware matcher avoiding numeric-prefix or word-interior false hits."""
    if _is_cjk(phrase):
        return re.compile(re.escape(phrase), re.IGNORECASE)
    escaped = re.escape(phrase.strip())
    # Allow flexible internal whitespace when spaces appear inside phrase.
    escaped = re.sub(r"\\ ", r"\\s+", escaped)
    return re.compile(rf"(?<![A-Za-z0-9_.]){escaped}(?![A-Za-z0-9_.])", re.IGNORECASE)


def find_lexical_overlaps(
    text: str,
    lexicon: dict[str, Any],
    *,
    ngram_n: int = 3,
    include_regex: bool = True,
) -> list[dict[str, Any]]:
    """Detect exact phrase hits, word n-gram overlaps, and heuristic regex hits."""
    if not text or not text.strip():
        return []

    hits: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    phrase_sources: dict[str, list[str]] = lexicon["phrase_sources"]

    # 1. Boundary-aware exact phrase match.
    for phrase, sources in phrase_sources.items():
        matcher = _compile_phrase_matcher(phrase)
        m = matcher.search(text)
        if m:
            key = ("exact_phrase", phrase)
            if key not in seen_keys:
                seen_keys.add(key)
                hits.append(
                    {
                        "kind": "exact_phrase",
                        "pattern": phrase,
                        "matched": m.group(0),
                        "sources": sources,
                    }
                )

    # 2. Word n-gram overlap against >= ngram_n word blacklist phrases.
    text_words = _normalize_words(text)
    if ngram_n >= 2 and len(text_words) >= ngram_n:
        text_ngrams = {
            tuple(text_words[i : i + ngram_n])
            for i in range(len(text_words) - ngram_n + 1)
        }
        for phrase, sources in phrase_sources.items():
            if _is_cjk(phrase):
                continue
            p_words = _normalize_words(phrase)
            if len(p_words) < ngram_n:
                continue
            for i in range(len(p_words) - ngram_n + 1):
                gram = tuple(p_words[i : i + ngram_n])
                if sum(1 for w in gram if w not in NGRAM_FUNCTION_WORDS) < 2:
                    continue
                if gram in text_ngrams:
                    gram_str = " ".join(gram)
                    if gram_str == " ".join(p_words) and ("exact_phrase", phrase) in seen_keys:
                        continue
                    key = ("word_ngram", gram_str)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        hits.append(
                            {
                                "kind": "word_ngram",
                                "pattern": gram_str,
                                "from_phrase": phrase,
                                "sources": sources,
                            }
                        )

    # 3. Heuristic regex patterns in parrhesia/gates.py.
    if include_regex:
        for rname, pat in lexicon["regex_patterns"].items():
            m = pat.search(text)
            if m:
                key = ("regex_pattern", rname)
                if key not in seen_keys:
                    seen_keys.add(key)
                    hits.append(
                        {
                            "kind": "regex_pattern",
                            "pattern": rname,
                            "matched": m.group(0),
                            "sources": [rname],
                        }
                    )

    return hits


def _collect_text_fields(node: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Collect human-authored prose fields recursively, ignoring enum/ground-truth keys."""
    collected: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in NON_TEXT_FIELD_KEYS:
                continue
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            collected.extend(_collect_text_fields(value, child_prefix))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            child_prefix = f"{prefix}[{idx}]"
            collected.extend(_collect_text_fields(item, child_prefix))
    elif isinstance(node, str) and node.strip():
        collected.append((prefix or "text", node))
    return collected


def _extract_heldout_groups(suite: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Discover held-out groups across top-level or nested `heldout_generalization` schema."""
    groups: dict[str, list[dict[str, Any]]] = {}
    nested = suite.get("heldout_generalization")
    if isinstance(nested, dict):
        for sub_key in ("realistic_controls", "adversarial_paraphrases", "cases"):
            val = nested.get(sub_key)
            if isinstance(val, list):
                groups[f"heldout_generalization.{sub_key}"] = [x for x in val if isinstance(x, dict)]
    elif isinstance(nested, list):
        groups["heldout_generalization"] = [x for x in nested if isinstance(x, dict)]

    for top_key in ("heldout_realistic_controls", "heldout_adversarial_paraphrases"):
        val = suite.get(top_key)
        if isinstance(val, list):
            groups[top_key] = [x for x in val if isinstance(x, dict)]
    return groups


def _scan_case_list(
    items: list[dict[str, Any]],
    lexicon: dict[str, Any],
    *,
    ngram_n: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Scan a list of case/transform dicts and return (count, findings)."""
    findings: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        item_id = (
            item.get("case_code")
            or item.get("id")
            or item.get("pair_code")
            or item.get("transform_id")
            or f"item[{idx}]"
        )
        for field_path, text in _collect_text_fields(item):
            hits = find_lexical_overlaps(text, lexicon, ngram_n=ngram_n)
            if hits:
                findings.append(
                    {
                        "item_id": str(item_id),
                        "field": field_path,
                        "hits": hits,
                    }
                )
    return len(items), findings


def scan_stage0_suite(
    suite: dict[str, Any],
    lexicon: dict[str, Any],
    *,
    ngram_n: int = 3,
    allow_empty_heldout: bool = False,
) -> dict[str, Any]:
    """Scan held-out (strict) and dev/metamorphic (informational) sets in stage0-cases.json."""
    heldout_groups = _extract_heldout_groups(suite)
    heldout_report: dict[str, Any] = {}
    heldout_overlap_count = 0
    missing_or_empty_heldout: list[str] = []

    if not heldout_groups:
        missing_or_empty_heldout.append("heldout_generalization / heldout_realistic_controls / heldout_adversarial_paraphrases")
    else:
        has_realistic = any("realistic_controls" in k and v for k, v in heldout_groups.items())
        has_adversarial = any("adversarial_paraphrases" in k and v for k, v in heldout_groups.items())
        if not has_realistic:
            missing_or_empty_heldout.append("heldout_realistic_controls")
        if not has_adversarial:
            missing_or_empty_heldout.append("heldout_adversarial_paraphrases")
        for gname, items in heldout_groups.items():
            count, findings = _scan_case_list(items, lexicon, ngram_n=ngram_n)
            heldout_overlap_count += len(findings)
            heldout_report[gname] = {
                "item_count": count,
                "finding_count": len(findings),
                "findings": findings,
            }

    # Informational scans for dev / legacy / metamorphic / P1 effect suites (reported, never strict failure).
    informational_report: dict[str, Any] = {}
    for sec_key in ("cases", "exploratory_cases", "paired_sensitivity_cases", "lineage_window_specs", "metamorphic_invariance", "p1_effect_records", "p2_longitudinal_calibration"):
        raw = suite.get(sec_key)
        if isinstance(raw, list):
            count, findings = _scan_case_list(
                [x for x in raw if isinstance(x, dict)],
                lexicon,
                ngram_n=ngram_n,
            )
            informational_report[sec_key] = {
                "item_count": count,
                "finding_count": len(findings),
            }

    strict_passed = heldout_overlap_count == 0 and (
        allow_empty_heldout or not missing_or_empty_heldout
    )

    return {
        "strict_passed": strict_passed,
        "heldout_overlap_count": heldout_overlap_count,
        "missing_or_empty_heldout": missing_or_empty_heldout,
        "heldout_groups": heldout_report,
        "informational_dev_and_metamorphic": informational_report,
    }


def _extract_case_slice(arm_text: str) -> str:
    """Extract the case prompt payload after `=== CASE ===`, or whole string for Arm A."""
    marker = "=== CASE ==="
    idx = arm_text.find(marker)
    if idx >= 0:
        return arm_text[idx + len(marker) :]
    return arm_text


def _find_answer_leaks(arm_text: str) -> list[dict[str, str]]:
    """Detect ground-truth answer, expected verdict/error, or scenario ID leakage."""
    leaks: list[dict[str, str]] = []
    for name, pat in ANSWER_LEAKAGE_PATTERNS:
        m = pat.search(arm_text)
        if m:
            leaks.append({"rule": name, "matched": m.group(0)})
    return leaks


def scan_prompt_export(
    export_data: dict[str, Any],
    lexicon: dict[str, Any],
    *,
    ngram_n: int = 3,
) -> dict[str, Any]:
    """Scan prompt-export packets for answer leakage (all) & gates overlap (held-out)."""
    packet_lists = [
        "packets",
        "exploratory_packets",
        "counterfactual_packets",
        "fork_multiplicity_packets",
        "symmetry_packets",
        "paired_packets",
        "heldout_packets",
        "heldout_realistic_control_packets",
        "heldout_adversarial_paraphrase_packets",
        "metamorphic_packets",
        "p1_effect_records_packets",
        "p2_longitudinal_packets",
    ]
    heldout_packet_keys = {
        "heldout_packets",
        "heldout_realistic_control_packets",
        "heldout_adversarial_paraphrase_packets",
    }

    answer_leaks: list[dict[str, Any]] = []
    heldout_lexical_findings: list[dict[str, Any]] = []
    dev_lexical_counts: dict[str, int] = {}
    scanned_packets = 0

    for list_key in packet_lists:
        packets = export_data.get(list_key)
        if not isinstance(packets, list):
            continue
        for idx, pkt in enumerate(packets):
            if not isinstance(pkt, dict):
                continue
            scanned_packets += 1
            pkt_id = str(pkt.get("run_id") or pkt.get("case_code") or f"{list_key}[{idx}]")
            is_heldout = (
                list_key in heldout_packet_keys
                or str(pkt.get("split") or pkt.get("partition") or "").lower() == "heldout"
            )
            arms = pkt.get("arms")
            if not isinstance(arms, dict):
                continue
            for arm_name, arm_text in arms.items():
                if not isinstance(arm_text, str):
                    continue
                leaks = _find_answer_leaks(arm_text)
                if leaks:
                    answer_leaks.append(
                        {
                            "packet_group": list_key,
                            "packet_id": pkt_id,
                            "arm": arm_name,
                            "leaks": leaks,
                        }
                    )
                case_payload = _extract_case_slice(arm_text)
                lex_hits = find_lexical_overlaps(case_payload, lexicon, ngram_n=ngram_n)
                if lex_hits:
                    if is_heldout:
                        heldout_lexical_findings.append(
                            {
                                "packet_group": list_key,
                                "packet_id": pkt_id,
                                "arm": arm_name,
                                "hits": lex_hits,
                            }
                        )
                    else:
                        dev_lexical_counts[list_key] = dev_lexical_counts.get(list_key, 0) + 1

    strict_passed = len(answer_leaks) == 0 and len(heldout_lexical_findings) == 0
    return {
        "strict_passed": strict_passed,
        "scanned_packets": scanned_packets,
        "answer_leak_count": len(answer_leaks),
        "answer_leaks": answer_leaks,
        "heldout_prompt_overlap_count": len(heldout_lexical_findings),
        "heldout_prompt_overlaps": heldout_lexical_findings,
        "informational_dev_packet_arm_overlaps": dev_lexical_counts,
    }


def run_leakage_audit(
    *,
    gates_path: Path = DEFAULT_GATES_PATH,
    suite_path: Path = DEFAULT_SUITE_PATH,
    prompt_export_path: Path | None = None,
    ngram_n: int = 3,
    allow_empty_heldout: bool = False,
) -> dict[str, Any]:
    """Run full static leakage audit against suite JSON and optional prompt export."""
    lexicon = extract_gates_lexicon(gates_path)
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    suite_report = scan_stage0_suite(
        suite,
        lexicon,
        ngram_n=ngram_n,
        allow_empty_heldout=allow_empty_heldout,
    )

    prompt_report: dict[str, Any] | None = None
    if prompt_export_path is not None:
        resolved_pe = prompt_export_path
        if resolved_pe.is_dir():
            resolved_pe = resolved_pe / "stage0-prompt-packets.json"
        pe_data = json.loads(resolved_pe.read_text(encoding="utf-8"))
        prompt_report = scan_prompt_export(pe_data, lexicon, ngram_n=ngram_n)

    strict_passed = suite_report["strict_passed"] and (
        prompt_report is None or prompt_report["strict_passed"]
    )
    advisory_audit = None
    if gates_path.resolve() == DEFAULT_GATES_PATH.resolve():
        advisory_audit = audit_advisory_module(suite)
        strict_passed = strict_passed and advisory_audit["no_case_literals"]
    return {
        "strict_passed": strict_passed,
        "strict_scope": "Legacy lexicon overlap and prompt answer leakage; new advisory module case-literal guard. Generic advisory regex overlaps are separately reported, not evidence of an independent holdout.",
        "advisory_module_audit": advisory_audit,
        "ngram_n": ngram_n,
        "lexicon_summary": {
            "gates_path": lexicon["gates_path"],
            "unique_phrase_count": lexicon["unique_phrase_count"],
            "phrase_group_names": sorted(lexicon["phrase_groups"].keys()),
            "regex_names": sorted(lexicon["regex_patterns"].keys()),
        },
        "suite_audit": suite_report,
        "prompt_export_audit": prompt_report,
    }


def audit_advisory_module(suite, module_path=None):
    """Expose every new rule component and forbid case IDs / copied passages.

    Generic grammar components necessarily overlap ordinary source prose. Report
    that overlap explicitly; neither it nor absence of copied literals proves
    independence after the original examples have been exposed.
    """
    from parrhesia.text_advisories import ADVISORY_REGEXES

    path = module_path or REPO_ROOT / "parrhesia/text_advisories.py"
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    literals = []
    overlaps = []
    for group, cases in suite.items():
        if not isinstance(cases, list):
            continue
        for case in cases:
            if not isinstance(case, dict):
                continue
            cid = case.get("case_code") or case.get("transform_id") or case.get("id")
            if cid and str(cid) in source:
                literals.append({"case": cid, "field": "identifier"})
            for field in ("evidence_text", "draft", "source", "claim", "prefix", "suffix"):
                value = case.get(field)
                if not isinstance(value, str):
                    continue
                if len(value) >= 40 and value in source:
                    literals.append({"case": cid, "field": field})
                matches = sorted(name for name, regex in ADVISORY_REGEXES.items() if regex.search(value))
                if matches:
                    overlaps.append({"group": group, "case": cid, "field": field, "rule_components": matches})
    return {
        "source": path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "regex_components": sorted(ADVISORY_REGEXES),
        "no_case_literals": not literals, "case_literal_findings": literals,
        "regex_overlap_field_count": len(overlaps), "regex_overlaps": overlaps,
        "independent_holdout": False,
        "scope": "Exposed regression samples. Literal guard is not a proof against overfitting; new synthetic qualification is also developer-authored.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static leakage and n-gram overlap checker for Parrhesia Stage 0.")
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES_PATH, help="Path to parrhesia/gates.py")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH, help="Path to stage0-cases.json")
    parser.add_argument(
        "--prompt-export",
        type=Path,
        default=None,
        help="Optional path to stage0-prompt-packets.json or export output directory",
    )
    parser.add_argument("--ngram-n", type=int, default=3, help="Word n-gram overlap window size (default: 3)")
    parser.add_argument(
        "--allow-empty-heldout",
        action="store_true",
        help="Allow missing/empty heldout sections (useful only for isolated synthetic tests)",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any strict leakage check fails")
    args = parser.parse_args(argv)

    report = run_leakage_audit(
        gates_path=args.gates,
        suite_path=args.suite,
        prompt_export_path=args.prompt_export,
        ngram_n=args.ngram_n,
        allow_empty_heldout=args.allow_empty_heldout,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and not report["strict_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
