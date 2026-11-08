"""Frozen anti-stall gates. Enforces structure, never certifies scientific truth."""
import re
import unicodedata
from .claims import TYPE_LEVELS, needs_causal_basis
from .contracts import array, enum, fail, fields, ids, obj, string

GATE_VERSION = 1
MIN_QUOTE_CHARS = 12
GATE_GUIDANCE = (
    " Current gate_version=1: submit exactly one original-claim stance per claim, even with zero findings, "
    "and acknowledge every unread source in unread_evidence_ids. Positive references each require a unique "
    "quote of at least 12 non-whitespace characters linked to the claim and location; synthetic cannot support empirical positives. "
    "Respect check_ceilings, level-progressive design/statistical check requirements, evidenced pass rules, and evidence-kind compatibility "
    "(observational evidence may conditionally support causal_effect only as partially_supported when causal_basis and observational "
    "confounding/robustness checks pass). Adjudication binds each finding to its claim's decision with an incorporated revised_text_quote "
    "or explicit disagreement. Blind is frozen case-wide."
)
ESSENTIAL_DESIGN_CHECKS = {
    "observational": ("sampling_temporality", "confounding_selection"),
    "quasi_experimental": ("assignment_rule", "identification"),
    "randomized": ("randomization_concealment", "analysis_population"),
    "prediction": ("target_horizon", "splits_leakage"),
    "ml": ("data_contamination", "splits_tuning"),
    "mechanism": ("causal_model", "specificity_controls"),
    "evidence_synthesis": ("protocol_search", "eligibility_selection"),
    "theory": ("definitions_assumptions", "proof"),
    "qualitative": ("epistemic_position", "sampling_context"),
}
FAMILY_TIER_CHECKS = {
    "observational": {
        1: ("sampling_temporality", "measurement"),
        2: ("sampling_temporality", "measurement", "confounding_selection"),
        3: ("sampling_temporality", "measurement", "confounding_selection", "missingness", "robustness"),
    },
    "quasi_experimental": {
        1: ("assignment_rule", "identification"),
        2: ("assignment_rule", "identification", "diagnostics_placebos"),
        3: ("assignment_rule", "identification", "diagnostics_placebos", "local_scope", "sensitivity"),
    },
    "randomized": {
        1: ("randomization_concealment", "analysis_population"),
        2: ("randomization_concealment", "analysis_population", "adherence_attrition"),
        3: ("randomization_concealment", "analysis_population", "adherence_attrition", "interference", "harms"),
    },
    "prediction": {
        1: ("target_horizon", "calibration_discrimination"),
        2: ("target_horizon", "calibration_discrimination", "splits_leakage"),
        3: ("target_horizon", "calibration_discrimination", "splits_leakage", "validation_shift"),
        4: ("target_horizon", "calibration_discrimination", "splits_leakage", "validation_shift", "utility"),
    },
    "ml": {
        1: ("baselines_budget", "splits_tuning"),
        2: ("baselines_budget", "splits_tuning", "data_contamination", "seeds_uncertainty"),
        3: ("baselines_budget", "splits_tuning", "data_contamination", "seeds_uncertainty", "ablations_compute"),
    },
    "mechanism": {
        1: ("causal_model",),
        2: ("causal_model", "specificity_controls", "temporal_chain"),
        3: ("causal_model", "specificity_controls", "temporal_chain", "rescue_orthogonal", "rival_pathways"),
    },
    "evidence_synthesis": {
        1: ("protocol_search", "eligibility_selection"),
        2: ("protocol_search", "eligibility_selection", "bias_dependence", "heterogeneity"),
        3: ("protocol_search", "eligibility_selection", "bias_dependence", "heterogeneity", "certainty_missing_studies"),
    },
    "theory": {
        1: ("definitions_assumptions", "proof"),
        2: ("definitions_assumptions", "proof", "boundary_counterexamples", "independent_check"),
        3: ("definitions_assumptions", "proof", "boundary_counterexamples", "independent_check"),
    },
    "qualitative": {
        1: ("epistemic_position", "sampling_context"),
        2: ("epistemic_position", "sampling_context", "reflexivity_ethics", "analysis_audit"),
        3: ("epistemic_position", "sampling_context", "reflexivity_ethics", "analysis_audit", "negative_cases_transfer"),
    },
}
LEVEL_TIERS = {
    "description": {"measurement_checked": 1, "replicated": 2},
    "association": {"unadjusted": 1, "adjusted": 2, "robust_association": 3},
    "prediction": {"apparent": 1, "internally_validated": 2, "externally_validated": 3, "prospectively_evaluated": 4},
    "causal_effect": {"identified_under_assumptions": 2, "sensitivity_supported": 3},
    "mechanism": {"compatible": 1, "component_tested": 2, "causal_chain_tested": 3},
    "necessity": {"bounded_test": 2, "counterfactual_supported": 3},
    "sufficiency": {"bounded_test": 2, "counterfactual_supported": 3},
    "synthesis": {"mapped": 1, "critically_appraised": 2, "synthesized_with_uncertainty": 3},
    "theory": {"proved_under_assumptions": 1, "independently_checked": 3},
    "qualitative": {"situated_description": 1, "interpretation_audited": 2, "triangulated": 3},
    "computational": {"benchmark_measured": 1, "reproduced": 2, "externally_evaluated": 3},
    "engineering": {"test_passed": 1, "host_accepted": 2, "user_impact": 3},
}
ESSENTIAL_STAT_CHECKS = ("units_sample_size", "estimate_uncertainty")
TRIVIAL_REASONS = {
    "OK", "OKAY", "PASS", "PASSED", "YES", "Y", "GOOD", "FINE", "DONE",
    "VALID", "CHECKED", "TRUE", "VERIFIED", "SURE", "NA", "N/A", "NONE",
    "NIL", "UNKNOWN", "NOT_RUN", "TBD", "TODO",
}
QUOTE_STOPWORDS = {
    "this", "that", "with", "from", "were", "have", "been", "only", "text",
    "file", "line", "page", "copyright", "reserved", "rights", "header",
    "footer", "note", "document", "section", "author", "date", "time",
    "version", "status", "some", "more", "than", "into", "upon", "also",
    "such", "when", "what", "where", "which", "while", "there", "their",
    "about", "under", "after", "before",
}
CJK_STOPWORDS = {"以下", "这个", "可以", "进行", "通过", "由于", "因此", "一个", "我们", "没有"}
CONTRADICTING_RELATIONS = ("unsupported", "contradicts", "refutes", "不支持", "反对")
EVIDENCE_KINDS = (
    "observation", "intervention", "quasi_experiment", "mechanistic_assay",
    "prediction_fit", "prediction_internal", "prediction_external", "prediction_prospective",
    "benchmark", "benchmark_replication", "benchmark_external", "systematic_review",
    "theoretical_proof", "qualitative_material", "test_log", "host_acceptance", "user_outcome",
    "synthetic", "unknown",
)
BASES = ("empirical", "synthetic", "formal")
POSITIVE = ("supported", "partially_supported")
ALL_KNOWN = tuple(k for k in EVIDENCE_KINDS if k not in ("unknown", "synthetic"))
CAUSAL_KINDS = ("intervention", "quasi_experiment")
COMPATIBILITY = {
    "description": {"recorded": (*ALL_KNOWN, "synthetic"), "measurement_checked": ALL_KNOWN, "replicated": ALL_KNOWN},
    "association": {k: ("observation", *CAUSAL_KINDS) for k in ("unadjusted", "adjusted", "robust_association")},
    "prediction": {
        "apparent": ("prediction_fit", "prediction_internal", "prediction_external", "prediction_prospective"),
        "internally_validated": ("prediction_internal", "prediction_external", "prediction_prospective"),
        "externally_validated": ("prediction_external", "prediction_prospective"),
        "prospectively_evaluated": ("prediction_prospective",),
    },
    "causal_effect": {k: CAUSAL_KINDS for k in ("identified_under_assumptions", "sensitivity_supported")},
    "mechanism": {"compatible": ("observation", "mechanistic_assay", *CAUSAL_KINDS), "component_tested": ("mechanistic_assay", *CAUSAL_KINDS), "causal_chain_tested": CAUSAL_KINDS},
    "necessity": {k: CAUSAL_KINDS for k in ("bounded_test", "counterfactual_supported")},
    "sufficiency": {k: CAUSAL_KINDS for k in ("bounded_test", "counterfactual_supported")},
    "synthesis": {k: ("systematic_review",) for k in ("mapped", "critically_appraised", "synthesized_with_uncertainty")},
    "theory": {k: ("theoretical_proof",) for k in ("proved_under_assumptions", "independently_checked")},
    "qualitative": {k: ("qualitative_material",) for k in ("situated_description", "interpretation_audited", "triangulated")},
    "computational": {"benchmark_measured": ("benchmark", "benchmark_replication", "benchmark_external", "synthetic"), "reproduced": ("benchmark_replication", "benchmark_external"), "externally_evaluated": ("benchmark_external",)},
    "engineering": {"test_passed": ("test_log", "host_acceptance", "user_outcome"), "host_accepted": ("host_acceptance", "user_outcome"), "user_impact": ("user_outcome",)},
}


def gated(case):
    schema = case.get("schema_version", 1)
    if type(schema) is not int or schema not in (1, 2):
        fail("unsupported_contract_version", "stored schema_version is unsupported; no legacy fallback")
    if "gate_version" not in case:
        return False
    version = case["gate_version"]
    if type(version) is not int or version != GATE_VERSION or schema != 2:
        fail("unsupported_contract_version", "stored gate_version/schema combination is unsupported; no legacy fallback")
    return True


def text_content(content):
    try:
        value = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # PDF/archives and NUL-bearing buffers must not masquerade as read UTF-8 text.
    if content.startswith((b"%PDF-", b"PK\x03\x04", b"\x89PNG")) or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        return None
    return value


def meaningful(value):
    if not isinstance(value, str):
        return False
    visible = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    return quote_length(visible) > 0 and visible.upper() not in ("UNKNOWN", "NA", "N/A", "NONE", "NOT_RUN")


def substantive_reason(value):
    if not meaningful(value):
        return False
    visible = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    cleaned = "".join(c for c in visible if c.isalnum() or c.isspace()).strip().upper()
    if not cleaned or cleaned in TRIVIAL_REASONS:
        return False
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in visible)
    return quote_length(visible) >= (4 if has_cjk else 6)


def effective_status(record, require_evidence=True):
    status = record.get("status", "unknown")
    if status != "pass":
        return status
    if not substantive_reason(record.get("reason")):
        return "unknown"
    if require_evidence and not record.get("evidence_ids"):
        return "unknown"
    return "pass"


def quote_length(value):
    # Whitespace, format controls, standalone combining marks and private-use
    # codepoints cannot pad a short anchor. Matching still uses the exact original.
    return sum(not c.isspace() and unicodedata.category(c)[0] not in "CM" for c in value)


def quote_status(quote, source):
    if quote is None:
        return "not_supplied"
    if quote_length(quote) < MIN_QUOTE_CHARS:
        return "too_short"
    if source is None:
        return "not_text"
    first = source.find(quote)
    if first < 0:
        return "mismatch"
    if source.find(quote, first + 1) >= 0:
        return "ambiguous"
    return "matched"


def contradictory_evidence_kind(ev):
    kind = ev.get("kind")
    text = " ".join(str(ev.get(k) or "") for k in ("source_text", "quote", "label")).lower()
    if not text.strip():
        return None
    if kind == "intervention":
        obs_markers = (
            "observational cohort", "observational study", "observational registry",
            "cross-sectional observational", "retrospective observational", "non-randomized",
            "nonrandomized", "观察性队列", "观察性研究", "非随机",
        )
        scrubbed = text
        for neg in ("non-randomized", "nonrandomized", "not randomized", "unrandomized", "非随机", "未随机"):
            scrubbed = scrubbed.replace(neg, " ")
        int_markers = ("random", "rct", "interven", "knockout", "crispr", "perturb", "随机", "干预", "敲除")
        if any(m in text for m in obs_markers) and not any(m in scrubbed for m in int_markers):
            return "observational_source_declared_as_intervention"
    elif kind == "quasi_experiment":
        if any(m in text for m in ("cross-sectional observational comparison without pre-policy", "purely cross-sectional observational", "纯横断面观察")):
            return "cross_sectional_source_declared_as_quasi_experiment"
    elif kind in ("prediction_external", "prediction_prospective"):
        int_cv_markers = (
            "internal cross-validation", "internal 5-fold", "internal validation only",
            "no external validation", "no external cohort", "仅内部交叉验证", "无外部验证",
        )
        ext_markers = ("external cohort", "external validation", "external hospital", "independent hospital", "prospective cohort", "外部验证", "外部队列", "前瞻性")
        if any(m in text for m in int_cv_markers) and not any(m in text for m in ext_markers):
            return "internal_validation_declared_as_external"
    if kind == "prediction_prospective":
        if any(m in text for m in ("retrospective cohort", "retrospective validation", "回顾性")) and "prospective" not in text and "前瞻" not in text:
            return "retrospective_source_declared_as_prospective"
    return None


def quote_links_to_claim(ev, claim, decision):
    quote = ev.get("quote") or ""
    ev_id = ev.get("evidence_id")
    parts = [
        claim.get("text", ""),
        decision.get("revised_text", ""),
        claim.get("scope", ""),
        decision.get("scope", ""),
        claim.get("contribution", ""),
        claim.get("effect", {}).get("estimate", ""),
        claim.get("effect", {}).get("uncertainty", ""),
    ]
    for cards in claim.get("provenance_cards", {}).values():
        for card in cards:
            if card.get("status") == "checked" and (not ev_id or ev_id in card.get("evidence_ids", [])):
                parts.extend(str(v) for v in card.get("details", {}).values())
    target = " ".join(str(p) for p in parts if p)
    q_nums = set(re.findall(r"\d+(?:\.\d+)?", quote))
    t_nums = set(re.findall(r"\d+(?:\.\d+)?", target))
    if q_nums & t_nums:
        return True
    q_words = {w for w in re.findall(r"[a-zA-Z]{4,}", quote.lower()) if w not in QUOTE_STOPWORDS}
    t_words = {w for w in re.findall(r"[a-zA-Z]{4,}", target.lower()) if w not in QUOTE_STOPWORDS}
    if q_words & t_words or ({w[:5] for w in q_words if len(w) >= 5} & {w[:5] for w in t_words if len(w) >= 5}):
        return True
    q_cjk = "".join(c for c in quote if "\u4e00" <= c <= "\u9fff")
    t_cjk = "".join(c for c in target if "\u4e00" <= c <= "\u9fff")
    q_bigrams = {q_cjk[i:i + 2] for i in range(len(q_cjk) - 1)} - CJK_STOPWORDS
    t_bigrams = {t_cjk[i:i + 2] for i in range(len(t_cjk) - 1)} - CJK_STOPWORDS
    return bool(q_bigrams & t_bigrams)


def validate_basis(value):
    basis = enum(value["claim_basis"], BASES, "claim_basis")
    kind = value["claim_type"]
    if basis == "formal" and kind != "theory":
        fail("basis_mismatch", "formal basis is reserved for theory claims")
    if kind == "theory" and basis != "formal":
        fail("basis_mismatch", "theory claims require formal basis")
    if basis == "synthetic" and kind not in ("description", "computational"):
        fail("basis_mismatch", "synthetic positive scope is limited to description/computational demonstrations")


def critical_paths(kind, level):
    """Minimum fixed checks; callers cannot relabel essential checks as optional."""
    if level in ("unassessed", "unidentified", "conjectured"):
        return ()
    if kind == "description" and level == "recorded":
        return ()  # Literal anchored record only; not verified measurement or inference.
    common = ("checks.quality", "checks.unit", "checks.assumptions")
    if kind == "theory":
        if level == "proved_under_assumptions":
            return ("checks.assumptions", "checks.unit")
        return ("checks.assumptions", "checks.unit", "checks.quality", "checks.baseline")
    if kind == "qualitative":
        if level == "situated_description":
            return ("checks.quality", "checks.unit")
        if level == "interpretation_audited":
            return ("checks.quality", "checks.unit", "checks.assumptions", "checks.batch")
        return ("checks.quality", "checks.unit", "checks.assumptions", "checks.batch", "checks.multiplicity", "checks.baseline")
    if kind == "synthesis":
        if level == "mapped":
            return common
        return common + ("checks.batch", "checks.multiplicity", "checks.baseline")
    if kind == "engineering":
        if level == "test_passed":
            return ("checks.quality", "checks.baseline")
        if level == "host_accepted":
            return ("checks.quality", "checks.baseline", "checks.unit")
        return ("checks.quality", "checks.baseline", "checks.unit", "checks.assumptions")
    if kind == "description":
        return ("checks.quality", "checks.unit") + (("checks.batch",) if level == "replicated" else ())
    if kind == "association":
        if level == "unadjusted":
            return common
        return common + ("checks.batch", "checks.multiplicity", "checks.baseline")
    if kind == "mechanism":
        if level == "compatible":
            return common
        return common + ("checks.batch", "checks.multiplicity", "checks.baseline")
    if kind in ("prediction", "computational"):
        return common + ("checks.leakage", "checks.baseline", "checks.multiplicity")
    return common + ("checks.batch", "checks.multiplicity", "checks.baseline")


def level_essential_design_checks(kind, level, fam):
    tier = LEVEL_TIERS.get(kind, {}).get(level, 0)
    if tier <= 0:
        return ()
    fam_tiers = FAMILY_TIER_CHECKS.get(fam, {})
    if not fam_tiers:
        return ESSENTIAL_DESIGN_CHECKS.get(fam, ())
    max_tier = max(fam_tiers)
    return fam_tiers.get(min(tier, max_tier), ESSENTIAL_DESIGN_CHECKS.get(fam, ()))


def level_essential_stat_checks(kind, level):
    tier = LEVEL_TIERS.get(kind, {}).get(level, 0)
    if tier <= 0 or kind == "theory":
        return ()
    if kind == "description":
        return ESSENTIAL_STAT_CHECKS if level == "replicated" else ()
    if kind == "qualitative":
        return ("units_sample_size", "robustness_limits") if level == "triangulated" else ("units_sample_size",)
    if kind == "engineering":
        return ESSENTIAL_STAT_CHECKS if level == "user_impact" else ()
    if kind == "synthesis":
        if level == "mapped":
            return ("units_sample_size",)
        if level == "critically_appraised":
            return ("units_sample_size", "estimate_uncertainty", "model_assumptions")
        return ("units_sample_size", "estimate_uncertainty", "model_assumptions", "comparisons_baselines", "robustness_limits")
    if tier == 1:
        return ESSENTIAL_STAT_CHECKS
    if tier == 2:
        return ("units_sample_size", "estimate_uncertainty", "model_assumptions", "comparisons_baselines")
    return ("units_sample_size", "estimate_uncertainty", "model_assumptions", "comparisons_baselines", "robustness_limits")


def required_records(claim, kind, level):
    paths = critical_paths(kind, level)
    records = [(path, {"status": effective_status(claim["checks"][path.split(".")[1]], require_evidence=False)}) for path in paths]
    if not paths:
        return records
    causal_needed = needs_causal_basis({"claim_type": kind, "evidence_level": level})
    # All selected design packages enforce level-progressive essential checks; core checks cannot be bypassed via N/A.
    for package in claim["design_packages"]:
        fam = package["family"]
        checks = package["checks"]
        if checks and all(v["status"] == "not_applicable" for v in checks.values()):
            records.append((f"design.{fam}._all_not_applicable", {"status": "fail"}))
        essential_design = set(level_essential_design_checks(kind, level, fam))
        for name, value in checks.items():
            eff = effective_status(value, require_evidence=True)
            if name in essential_design and eff != "pass":
                records.append((f"design.{fam}.{name}", {"status": "fail" if eff == "fail" else "unknown"}))
            else:
                records.append((f"design.{fam}.{name}", {"status": eff, "evidence_ids": value.get("evidence_ids", [])}))
    essential_stats = set(level_essential_stat_checks(kind, level))
    if essential_stats or kind not in ("description", "theory", "qualitative", "engineering"):
        for key, value in claim["statistical_report"].items():
            eff = effective_status(value, require_evidence=True)
            if key in essential_stats and eff != "pass":
                records.append(("statistics." + key, {"status": "fail" if eff == "fail" else "unknown"}))
            else:
                records.append(("statistics." + key, {"status": eff, "evidence_ids": value.get("evidence_ids", [])}))
    for card_kind, cards in claim.get("provenance_cards", {}).items():
        for idx, card in enumerate(cards):
            if card["status"] in ("failed", "missing"):
                records.append((f"provenance_cards.{card_kind}[{idx}]", {"status": "fail"}))
            elif card_kind == "citation" and card["status"] in ("reported", "checked"):
                rel = card.get("details", {}).get("support_relation", "").strip().lower()
                if rel in CONTRADICTING_RELATIONS:
                    records.append((f"provenance_cards.citation[{idx}].support_relation", {"status": "fail"}))
    if causal_needed:
        basis = claim.get("causal_basis")
        if not basis:
            records.append(("causal_basis", {"status": "unknown"}))
        else:
            if basis["design_family"] not in ("observational", "quasi_experimental", "randomized", "mechanism", "evidence_synthesis"):
                records.append(("causal_basis.design_family", {"status": "unknown"}))
            require_sensitivity = level in ("sensitivity_supported", "counterfactual_supported", "causal_chain_tested")
            causal_records = [("assessment", basis["assessment"], True)]
            causal_records += [(f"assumptions[{i}]", value, True) for i, value in enumerate(basis["assumptions"])]
            causal_records += [(f"falsification_sensitivity[{i}]", value, require_sensitivity) for i, value in enumerate(basis["falsification_sensitivity"])]
            if kind in ("necessity", "sufficiency"):
                causal_records.append((kind + "_test", basis[kind + "_test"], True))
            for key, value, must_pass in causal_records:
                eff = effective_status(value, require_evidence=True)
                if must_pass:
                    records.append(("causal_basis." + key, {"status": "pass", "evidence_ids": value.get("evidence_ids", [])} if eff == "pass" else {"status": "fail" if eff == "fail" else "unknown"}))
                elif eff == "fail":
                    records.append(("causal_basis." + key, {"status": "fail"}))
            for key, value in basis["estimand"].items():
                if key != "intercurrent_events" and (not meaningful(value) or value.strip().upper() == "NOT_IDENTIFIABLE"):
                    records.append(("causal_basis.estimand." + key, {"status": "unknown"}))
    return records


def observational_causal_eligible(decision, claim):
    if decision.get("verdict") != "partially_supported" or not meaningful(decision.get("condition")):
        return False
    if decision["claim_type"] != "causal_effect" or decision["evidence_level"] not in ("identified_under_assumptions", "sensitivity_supported"):
        return False
    basis = claim.get("causal_basis")
    if not basis or basis.get("design_family") != "observational":
        return False
    obs_pkg = next((p for p in claim.get("design_packages", []) if p["family"] == "observational"), None)
    if not obs_pkg:
        return False
    for key in ("sampling_temporality", "confounding_selection", "robustness"):
        chk = obs_pkg["checks"].get(key, {})
        if effective_status(chk, require_evidence=True) != "pass":
            return False
    return True


def ceiling(claim, kind=None):
    kind = kind or claim["claim_type"]
    allowed, blocked = [], {}
    for level in TYPE_LEVELS[kind]:
        blockers = []
        fixed = set(critical_paths(kind, level))
        for path, record in required_records(claim, kind, level):
            # Essential global checks cannot be opted out; design/stat N/A retains a reason.
            if record["status"] in ("unknown", "fail") or (path in fixed and record["status"] != "pass"):
                blockers.append({"path": path, "status": record["status"]})
        if blockers:
            blocked[level] = blockers
        else:
            allowed.append(level)
    return {"claim_type": kind, "allowed_levels": allowed, "blocked_levels": blocked,
            "verdict_ceiling": "nonpositive_only" if not any(x in COMPATIBILITY[kind] for x in allowed) else "positive_possible_subject_to_evidence_gates"}


def validate_mechanical(decision, claim, evidence):
    validate_basis(decision)
    kind, level = decision["claim_type"], decision["evidence_level"]
    limits = ceiling(claim, kind)
    if level not in limits["allowed_levels"]:
        fail("critical_check_ceiling", f"{kind} × {level} exceeds frozen critical-check ceiling; blocked: {limits['blocked_levels'][level]}")
    if decision["verdict"] not in POSITIVE:
        return
    if decision["claim_basis"] == "synthetic" and (kind, level) not in (("description", "recorded"), ("computational", "benchmark_measured")):
        fail("synthetic_ceiling", "synthetic scope permits only recorded descriptions or measured synthetic benchmarks")
    obs_causal_ok = observational_causal_eligible(decision, claim)
    compatible = COMPATIBILITY[kind].get(level, ())
    if obs_causal_ok:
        compatible = (*compatible, "observation")
    for ref in decision["evidence_ids"]:
        ev = evidence[ref]
        synthetic = ev["provenance"] == "synthetic" or ev["kind"] == "synthetic"
        if synthetic and decision["claim_basis"] != "synthetic":
            fail("synthetic_empirical_support", "synthetic evidence cannot support empirical or formal positive judgments")
        contradiction = contradictory_evidence_kind(ev)
        if contradiction:
            fail("contradictory_evidence_kind", f"evidence '{ref}' content contradicts declared kind '{ev['kind']}': {contradiction}")
        if ev["kind"] not in compatible:
            fail("incompatible_evidence_kind", f"{ev['kind']} cannot support {kind} × {level}")
        if ev.get("source_text_status") != "complete":
            fail("unread_positive_evidence", "positive references require fully available readable source text; register a readable extract instead")
        if quote_status(ev.get("quote"), ev.get("source_text")) != "matched" or not meaningful(ev.get("location")):
            fail("unanchored_positive_evidence", "each positive reference needs a unique quote of at least 12 non-whitespace characters and a concrete location")
        if not quote_links_to_claim(ev, claim, decision):
            fail("unlinked_evidence_quote", f"positive reference '{ref}' quote does not share quantitative values, domain terms, or checked-card anchors with the claim")
    allowed_causal_kinds = (*CAUSAL_KINDS, "observation") if obs_causal_ok else CAUSAL_KINDS
    if needs_causal_basis(decision) and not all(evidence[ref]["kind"] in allowed_causal_kinds for ref in decision["evidence_ids"]):
        fail("incompatible_evidence_kind", "causal positives require intervention/quasi-experiment evidence (or observational evidence with partially_supported verdict, condition, and evidenced confounding/robustness checks)")
    # Positive decisions must cite the evidence backing their required passing design and statistical checks.
    decision_refs = set(decision["evidence_ids"])
    for path, record in required_records(claim, kind, level):
        if (path.startswith("design.") or path.startswith("statistics.")) and record.get("status") == "pass":
            check_refs = set(record.get("evidence_ids") or ())
            if check_refs and not (check_refs <= decision_refs):
                fail("uncited_check_evidence", f"positive decision must cite evidence backing passing check '{path}'")
    for card_kind in ("number", "execution", "citation"):
        for card in claim.get("provenance_cards", {}).get(card_kind, []):
            if card["status"] == "checked" and not (set(card["evidence_ids"]) & set(decision["evidence_ids"])):
                fail("uncited_checked_card", f"positive decision must cite evidence backing checked {card_kind} card '{card['id']}'")


def validate_unread_ack(value, evidence):
    ack = ids(value, "unread_evidence_ids")
    unread = {e["evidence_id"] for e in evidence if e["source_text_status"] != "complete"}
    if set(ack) != unread:
        fail("unread_ack_required", "explicitly acknowledge every binary, truncated or missing source in unread_evidence_ids")


def validate_stances(value, claims, evidence):
    seen = []
    by_evidence = {e["evidence_id"]: e for e in evidence}
    for stance in array(value, "claim_stances", minimum=1, maximum=100):
        obj(stance, "stance")
        keys = {"claim_id", "stance", "rationale", "evidence_ids"}
        fields(stance, keys | {"condition"}, keys, "stance")
        cid = string(stance["claim_id"], "stance.claim_id")
        if cid not in claims:
            fail("unknown_claim", "stance refers to a non-frozen claim")
        seen.append(cid)
        enum(stance["stance"], ("supported", "partially_supported", "unsupported", "insufficient_evidence"), "stance")
        if stance["stance"] == "partially_supported" and not meaningful(stance.get("condition")):
            fail("missing_stance_condition", "a conditionally supportive stance must specify its actual condition")
        if "condition" in stance and not meaningful(stance["condition"]):
            fail("missing_stance_condition", "condition cannot be empty, invisible or an unknown placeholder")
        string(stance["rationale"], "stance.rationale")
        refs = ids(stance["evidence_ids"], "stance.evidence_ids", minimum=1 if stance["stance"] in POSITIVE else 0)
        if not set(refs) <= set(claims[cid]["evidence_ids"]):
            fail("unknown_reference", "stance references evidence outside its claim")
        # A stance evaluates the original claim, never silently a proposed revision.
        if stance["stance"] in POSITIVE:
            from .claims import validate_support
            decision = {**claims[cid], "verdict": stance["stance"], "evidence_ids": refs}
            if "condition" in stance:
                decision["condition"] = stance["condition"]
            validate_support(decision, claims[cid])
            validate_mechanical(decision, claims[cid], by_evidence)
    ids(seen, "stance claim IDs")
    if set(seen) != set(claims):
        fail("incomplete_stances", "every frozen claim needs exactly one stance")


def validate_disposition(disposition, finding, decision, original):
    if disposition["claim_id"] != finding["claim_id"] or disposition["claim_id"] != decision["claim_id"]:
        fail("finding_decision_mismatch", "disposition must bind finding and decision for the same claim")
    resolution = enum(disposition["resolution"], ("incorporated", "disagreement"), "disposition.resolution")
    if resolution == "disagreement":
        if not meaningful(disposition.get("disagreement")):
            fail("missing_disagreement", "an explicit, substantive disagreement is required")
        if "revised_text_quote" in disposition:
            fail("contradictory_resolution", "disagreement cannot claim an incorporated text anchor")
        return
    if disposition["disposition"] == "rejected":
        fail("contradictory_resolution", "rejected findings must record disagreement")
    if "disagreement" in disposition:
        fail("contradictory_resolution", "incorporation cannot also claim disagreement")
    anchor = string(disposition.get("revised_text_quote"), "disposition.revised_text_quote")
    if quote_status(anchor, decision["revised_text"]) != "matched" or quote_status(anchor, finding["proposed_text"]) != "matched" or anchor in original["text"]:
        fail("finding_not_incorporated", "anchor must uniquely identify new proposed wording in revised_text, not a preexisting original fragment (at least 12 visible non-whitespace characters)")
    if decision["revised_text"].strip() == original["text"].strip():
        fail("finding_not_incorporated", "unchanged wording cannot be marked incorporated; record disagreement explicitly")
    if disposition["disposition"] == "accepted":
        if finding["proposed_text"] not in decision["revised_text"]:
            fail("finding_not_incorporated", "accepted incorporation requires the proposed text; deviations need explicit disagreement or partial adoption")
        for key in ("claim_type", "evidence_level", "scope", "claim_basis"):
            if finding["proposed_" + key] != decision[key]:
                fail("finding_not_incorporated", "accepted classification/scope must match the decision, or record disagreement")
