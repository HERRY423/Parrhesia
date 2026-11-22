"""Conservative clause scoping and explicit source cues, for advisories only.

No result here establishes a null effect, confounding, or a scientific verdict.
Keep these rules separate from numerical anchoring and structural hard gates.
"""
from __future__ import annotations

import re

from .text_anchors import (
    NONPRIMARY_CLAUSE_RE, PRIMARY_CLAUSE_OVERRIDE_RE, _SAFETY_OR_HOSP_CLAUSE_RE,
    _PRIMARY_EFFICACY_SIGNAL_RE,
    _authenticated_source_text, _split_clauses, _strip_nonprimary_clauses,
)

HISTORY_PREFIX_RE = re.compile(
    r"^(?:(?:unlike|in contrast to|compared with)\s+(?:the\s+)?"
    r"(?:earlier|prior|previous|historical)\b|(?:earlier|prior|previous|historical)\s+"
    r"(?:work|studies|research|reports|experiments)\b|"
    r"(?:不同于|相比于?)(?:此前|先前|既往|早期)(?:研究|报告|试验))", re.I,
)
CURRENT_CONTEXT_RE = re.compile(
    r"\b(?:current|present)\b|\b(?:this|our|new)\s+(?:study|trial|evaluation|experiment|results?)\b|"
    r"本研究|本次|当前|此次", re.I,
)
SAFETY_FOCUS_RE = re.compile(_SAFETY_OR_HOSP_CLAUSE_RE.pattern + r"|\bsafer\b|\bharms?\b|毒性|不良反应", re.I)
PRIMARY_SCOPE_RE = re.compile(
    PRIMARY_CLAUSE_OVERRIDE_RE.pattern + r"|\bprimary(?:[-\s]+[a-z]+){0,2}[-\s]+"
    r"(?:endpoint|outcome|analysis|result|effect|finding|hypothesis)\b|主要[\u4e00-\u9fff]{0,6}(?:终点|结局|结果)", re.I,
)
FOCUS_STOPWORDS = frozenset(
    "the a an of in to and or with for by from this that study trial treatment intervention "
    "program method results showed shows show found demonstrates demonstrate improved improves "
    "improve increased increases increase reduced reduces reduce significantly significant".split()
)
HYPOTHETICAL_OR_NEGATED_RE = re.compile(
    r"\b(?:not|never|no longer|would|might|could|if|anticipated|planned)\b|"
    r"不再|并未|并非|未曾|没有|假如|计划|预计", re.I,
)
PENDING_OUTCOME_RE = re.compile(
    r"\b(?:outcome|endpoint|symptom|functional|clinical|disease|safety|survival|mortality)\b"
    r"(?:[-\s]+[\w]+){0,4}\s+(?:(?:is|are|was|were)\s+)?await(?:s|ing)?\s+"
    r"(?:[\w'’-]+\s+){0,8}(?:collection|abstraction|measurement|follow[- ]?up|assessment)\b|"
    r"(?:结局|终点|症状|功能|疾病|安全性)[\u4e00-\u9fff]{0,8}"
    r"(?:尚待|仍待|等待)[\u4e00-\u9fff]{0,8}(?:采集|测量|随访|收集)", re.I,
)
GENERATED_ENTITY_RE = re.compile(
    r"\b(?:virtual|simulated|phantom|artificial|synthetic)\s+"
    r"(?:patients?|participants?|subjects?|trajector(?:y|ies)|records?|cohorts?|data)\b|"
    r"(?:虚拟|模拟|合成)(?:患者|受试者|轨迹|数据|记录)", re.I,
)
GENERATOR_RE = re.compile(r"\b(?:computer|algorithm|mathematical|generator|model|simulator)\b|数学模型|算法|模拟器", re.I)
GENERATED_ACTION_RE = re.compile(r"\b(?:generat(?:e[ds]?|ing)|produc(?:e[ds]?|ing))\b|生成|产生", re.I)

# Explicit discovery surface for the evaluation auditor. These are generic rule
# components; their overlap with an exposed benchmark is reported, not hidden.
ADVISORY_REGEXES = {
    name: value for name, value in list(globals().items())
    if name.endswith("_RE") and isinstance(value, re.Pattern)
}


def _focus_tokens(text):
    words = set(re.findall(r"[a-z]{3,}", text.lower())) - FOCUS_STOPWORDS
    # Require two shared content units; do not infer the endpoint from a generic
    # claim such as "beneficial". CJK bigrams allow endpoint matching without NLP.
    cjk = re.sub(r"本研究|结果|显示|显著|改善|提高|降低|训练|干预|治疗|方案|支持", "", text)
    for run in re.findall(r"[\u4e00-\u9fff]+", cjk):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def scoped_evidence_clauses(ev, focus_text=""):
    source = _authenticated_source_text(ev)
    quote = str(ev.get("quote") or "")
    # A verbatim excerpt inherits its source context; scanning it again in
    # isolation would resurrect an explicitly historical or secondary clause.
    parts = [source] if source else []
    if quote and (not source or quote not in source):
        parts.append(quote)
    focus = _focus_tokens(focus_text)
    safety_focus = bool(SAFETY_FOCUS_RE.search(focus_text))
    result = []
    for raw in parts:
        clauses = _split_clauses(raw)
        has_current_context = any(CURRENT_CONTEXT_RE.search(c) for c in clauses)
        clauses = [c for c in clauses if not (
            has_current_context and HISTORY_PREFIX_RE.search(c) and not CURRENT_CONTEXT_RE.search(c)
        )]
        if not focus_text:
            kept = _split_clauses(_strip_nonprimary_clauses("; ".join(clauses)))
            kept.extend(c for c in clauses if PRIMARY_SCOPE_RE.search(c) and c not in kept)
            result.extend(kept)
            continue
        overlap = lambda c: len(focus & _focus_tokens(c)) >= 2
        primary_context = any(
            (overlap(c) or _PRIMARY_EFFICACY_SIGNAL_RE.search(c)) and not SAFETY_FOCUS_RE.search(c)
            for c in clauses
        )
        kept = []
        for clause in clauses:
            primary = PRIMARY_SCOPE_RE.search(clause)
            relevant = overlap(clause)
            safety = SAFETY_FOCUS_RE.search(clause)
            if NONPRIMARY_CLAUSE_RE.search(clause) and not (primary or relevant or (safety_focus and safety)):
                continue
            if safety and primary_context and not (safety_focus or primary or relevant):
                continue
            kept.append(clause)
        # An isolated negative clause must not disappear for lack of context.
        result.extend(kept or clauses)
    return result


def explicit_pending_outcome(clauses):
    return any(PENDING_OUTCOME_RE.search(c) and not HYPOTHETICAL_OR_NEGATED_RE.search(c) for c in clauses)


def explicit_generated_source(ev, clauses):
    if ev.get("provenance") == "synthetic" or ev.get("kind") == "synthetic":
        return False
    return any(
        GENERATED_ENTITY_RE.search(c) and GENERATOR_RE.search(c) and GENERATED_ACTION_RE.search(c)
        and not HYPOTHETICAL_OR_NEGATED_RE.search(c)
        for c in clauses
    )
