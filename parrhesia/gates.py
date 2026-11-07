"""Frozen anti-stall gates. Enforces structure, never certifies scientific truth."""
import unicodedata
from .claims import TYPE_LEVELS, needs_causal_basis
from .contracts import array, enum, fail, fields, ids, obj, string

GATE_VERSION = 1
MIN_QUOTE_CHARS = 12
GATE_GUIDANCE = (
    " Current gate_version=1: submit exactly one original-claim stance per claim, even with zero findings, "
    "and acknowledge every unread source in unread_evidence_ids. Positive references each require a unique "
    "quote of at least 12 non-whitespace characters and location; synthetic cannot support empirical positives. "
    "Respect check_ceilings and evidence-kind compatibility (observational evidence may conditionally support "
    "causal_effect only as partially_supported when causal_basis and observational confounding/robustness checks pass). "
    "Adjudication binds each finding to its claim's decision with an incorporated revised_text_quote or explicit "
    "disagreement. Blind is frozen case-wide."
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
ESSENTIAL_STAT_CHECKS = ("units_sample_size", "estimate_uncertainty")
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
        return ("checks.assumptions",)
    if kind == "qualitative":
        return ("checks.quality", "checks.unit")
    if kind == "engineering":
        return ("checks.quality", "checks.baseline")
    if kind == "description":
        return ("checks.quality", "checks.unit") + (("checks.batch",) if level == "replicated" else ())
    if kind in ("prediction", "computational"):
        return common + ("checks.leakage", "checks.baseline", "checks.multiplicity")
    return common + ("checks.batch", "checks.multiplicity", "checks.baseline")


def required_records(claim, kind, level):
    paths = critical_paths(kind, level)
    records = [(path, claim["checks"][path.split(".")[1]]) for path in paths]
    if not paths:
        return records
    causal_needed = needs_causal_basis({"claim_type": kind, "evidence_level": level})
    causal_family = claim.get("causal_basis", {}).get("design_family") if causal_needed else None
    # All selected design checks apply unless explicitly justified as not applicable.
    for package in claim["design_packages"]:
        fam = package["family"]
        checks = package["checks"]
        if checks and all(v["status"] == "not_applicable" for v in checks.values()):
            records.append((f"design.{fam}._all_not_applicable", {"status": "fail"}))
        apply_essential = (
            (causal_needed and fam == causal_family)
            or kind in ("mechanism", "prediction", "computational")
            or (kind == "association" and level in ("adjusted", "robust_association") and fam == "observational")
        )
        essential_design = set(ESSENTIAL_DESIGN_CHECKS.get(fam, ())) if apply_essential else set()
        for name, value in checks.items():
            if name in essential_design and value["status"] != "pass":
                records.append((f"design.{fam}.{name}", {"status": "fail" if value["status"] == "fail" else "unknown"}))
            else:
                records.append((f"design.{fam}.{name}", value))
    if kind not in ("description", "theory", "qualitative", "engineering"):
        for key, value in claim["statistical_report"].items():
            if key in ESSENTIAL_STAT_CHECKS and value["status"] != "pass":
                records.append(("statistics." + key, {"status": "fail" if value["status"] == "fail" else "unknown"}))
            else:
                records.append(("statistics." + key, value))
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
            causal_records = [("assessment", basis["assessment"])]
            for key in ("assumptions", "falsification_sensitivity"):
                causal_records += [(f"{key}[{i}]", value) for i, value in enumerate(basis[key])]
            if kind in ("necessity", "sufficiency"):
                causal_records.append((kind + "_test", basis[kind + "_test"]))
            for key, value in causal_records:
                records.append(("causal_basis." + key, value if value["status"] == "pass" and value["evidence_ids"] else {"status": "fail" if value["status"] == "fail" else "unknown"}))
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
        if chk.get("status") != "pass" or not chk.get("evidence_ids"):
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
        if ev["kind"] not in compatible:
            fail("incompatible_evidence_kind", f"{ev['kind']} cannot support {kind} × {level}")
        if ev.get("source_text_status") != "complete":
            fail("unread_positive_evidence", "positive references require fully available readable source text; register a readable extract instead")
        if quote_status(ev.get("quote"), ev.get("source_text")) != "matched" or not meaningful(ev.get("location")):
            fail("unanchored_positive_evidence", "each positive reference needs a unique quote of at least 12 non-whitespace characters and a concrete location")
    allowed_causal_kinds = (*CAUSAL_KINDS, "observation") if obs_causal_ok else CAUSAL_KINDS
    if needs_causal_basis(decision) and not all(evidence[ref]["kind"] in allowed_causal_kinds for ref in decision["evidence_ids"]):
        fail("incompatible_evidence_kind", "causal positives require intervention/quasi-experiment evidence (or observational evidence with partially_supported verdict, condition, and evidenced confounding/robustness checks)")
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
