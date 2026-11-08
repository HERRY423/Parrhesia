"""Version 2 claim contracts. Structural gates are not scientific verification."""
from __future__ import annotations

from .contracts import CHECK_STATUSES, array, enum, fail, fields, ids, obj, string

# These are type-local descriptors, never a global score or ordered ladder.
TYPE_LEVELS = {
    "description": ("unassessed", "recorded", "measurement_checked", "replicated"),
    "association": ("unassessed", "unadjusted", "adjusted", "robust_association"),
    "prediction": ("unassessed", "apparent", "internally_validated", "externally_validated", "prospectively_evaluated"),
    "causal_effect": ("unassessed", "unidentified", "identified_under_assumptions", "sensitivity_supported"),
    "mechanism": ("unassessed", "compatible", "component_tested", "causal_chain_tested"),
    "necessity": ("unassessed", "bounded_test", "counterfactual_supported"),
    "sufficiency": ("unassessed", "bounded_test", "counterfactual_supported"),
    "synthesis": ("unassessed", "mapped", "critically_appraised", "synthesized_with_uncertainty"),
    "theory": ("unassessed", "conjectured", "proved_under_assumptions", "independently_checked"),
    "qualitative": ("unassessed", "situated_description", "interpretation_audited", "triangulated"),
    "computational": ("unassessed", "benchmark_measured", "reproduced", "externally_evaluated"),
    "engineering": ("unassessed", "test_passed", "host_accepted", "user_impact"),
}
DESIGN_FIELDS = {
    "observational": ("sampling_temporality", "measurement", "confounding_selection", "missingness", "robustness"),
    "quasi_experimental": ("assignment_rule", "identification", "diagnostics_placebos", "local_scope", "sensitivity"),
    "randomized": ("randomization_concealment", "analysis_population", "adherence_attrition", "interference", "harms"),
    "prediction": ("target_horizon", "splits_leakage", "calibration_discrimination", "validation_shift", "utility"),
    "ml": ("data_contamination", "splits_tuning", "baselines_budget", "seeds_uncertainty", "ablations_compute"),
    "mechanism": ("causal_model", "specificity_controls", "temporal_chain", "rescue_orthogonal", "rival_pathways"),
    "evidence_synthesis": ("protocol_search", "eligibility_selection", "bias_dependence", "heterogeneity", "certainty_missing_studies"),
    "theory": ("definitions_assumptions", "proof", "boundary_counterexamples", "independent_check", "empirical_bridge"),
    "qualitative": ("epistemic_position", "sampling_context", "reflexivity_ethics", "analysis_audit", "negative_cases_transfer"),
}
STAT_FIELDS = ("units_sample_size", "estimand_scale", "estimate_uncertainty", "model_assumptions",
               "missingness_exclusions", "multiplicity_selection", "comparisons_baselines", "robustness_limits")
CARD_FIELDS = {
    "citation": ("source", "locator", "claim_link", "support_relation", "read_extent"),
    "number": ("value", "unit_denominator", "population_time", "derivation", "uncertainty", "locator"),
    "execution": ("command", "code_version", "inputs", "environment", "started_at", "ended_at", "exit_status", "outputs", "log_locator"),
    "search": ("database", "query", "searched_at", "filters", "coverage", "results", "selection", "limitations"),
}
ESTIMAND_FIELDS = ("population", "contrast", "outcome", "time_horizon", "summary", "intercurrent_events")
CAUSAL_TYPES = ("causal_effect", "necessity", "sufficiency")
DEFAULT_FAMILY = {
    "description": "observational",
    "association": "observational",
    "prediction": "prediction",
    "causal_effect": "observational",
    "mechanism": "mechanism",
    "necessity": "mechanism",
    "sufficiency": "mechanism",
    "synthesis": "evidence_synthesis",
    "theory": "theory",
    "qualitative": "qualitative",
    "computational": "ml",
}


def scaffold_claim_template(payload: dict) -> dict:
    """Build a schema-valid v2 claim skeleton with explicit unknown/not_run defaults."""
    obj(payload, "scaffold_claim")
    allowed = {"case_id", "claim_id", "text", "scope", "claim_type", "evidence_level", "claim_basis", "domain", "design_families", "include_causal_basis"}
    fields(payload, allowed, set(), "scaffold_claim")
    domain = enum(payload.get("domain", "scientific"), ("scientific", "general"), "domain")
    default_type = "description" if domain == "scientific" else "engineering"
    claim_type = enum(payload.get("claim_type", default_type), tuple(TYPE_LEVELS), "claim_type")
    if (domain == "scientific" and claim_type == "engineering") or (domain == "general" and claim_type not in ("description", "computational", "engineering")):
        fail("invalid_value", "claim_type is incompatible with the case domain")
    evidence_level = enum(payload.get("evidence_level", TYPE_LEVELS[claim_type][0]), TYPE_LEVELS[claim_type], "evidence_level")
    default_basis = "formal" if claim_type == "theory" else "empirical"
    claim_basis = enum(payload.get("claim_basis", default_basis), ("empirical", "synthetic", "formal"), "claim_basis")
    if claim_basis == "formal" and claim_type != "theory":
        fail("basis_mismatch", "formal basis is reserved for theory claims")
    if claim_type == "theory" and claim_basis != "formal":
        fail("basis_mismatch", "theory claims require formal basis")
    if claim_basis == "synthetic" and claim_type not in ("description", "computational"):
        fail("basis_mismatch", "synthetic positive scope is limited to description/computational demonstrations")
    claim_id = string(payload.get("claim_id", "C1"), "claim_id", maximum=200)
    text = string(payload.get("text", f"待填写的 {claim_type} 命题；当前未提供证据"), "text")
    scope = string(payload.get("scope", "UNKNOWN"), "scope")
    if "design_families" in payload:
        families = [enum(f, tuple(DESIGN_FIELDS), "design_families") for f in array(payload["design_families"], "design_families", minimum=1 if domain == "scientific" else 0, maximum=9)]
        ids(families, "design families")
    else:
        families = [DEFAULT_FAMILY[claim_type]] if domain == "scientific" else []
    include_causal = payload.get("include_causal_basis", needs_causal_basis({"claim_type": claim_type, "evidence_level": evidence_level}))
    if type(include_causal) is not bool:
        fail("invalid_type", "include_causal_basis must be a boolean")
    if needs_causal_basis({"claim_type": claim_type, "evidence_level": evidence_level}) and not include_causal:
        fail("missing_causal_basis", "causal, necessity, sufficiency and causal_chain_tested claims require causal_basis")

    def unknown_assessment(reason: str = "Template only; no evidence supplied") -> dict:
        return {"status": "unknown", "reason": reason, "evidence_ids": []}

    from .contracts import CHECK_NAMES
    claim = {
        "id": claim_id,
        "text": text,
        "claim_type": claim_type,
        "claim_basis": claim_basis,
        "evidence_level": evidence_level,
        "scope": scope,
        "evidence_ids": [],
        "effect": {"estimate": "UNKNOWN", "uncertainty": "UNKNOWN"},
        "origin": "unknown",
        "contribution": "UNKNOWN",
        "alternatives": [{"explanation": "命题尚未由证据建立", "status": "not_excluded", "reason": "模板未提供数据"}] if domain == "scientific" else [],
        "checks": {name: {"status": "unknown", "reason": "Template only; no evidence supplied"} for name in CHECK_NAMES},
        "design_packages": [
            {"family": fam, "checks": {key: unknown_assessment() for key in DESIGN_FIELDS[fam]}}
            for fam in families
        ],
        "statistical_report": {key: unknown_assessment() for key in STAT_FIELDS},
        "provenance_cards": {
            kind: [{
                "id": f"{claim_id}-{kind}-1",
                "status": "not_run" if kind in ("execution", "search") else "unknown",
                "reason": "空白脚手架模板，不表示发生过检索、执行或证据核对",
                "evidence_ids": [],
                "details": {k: "UNKNOWN" for k in detail_keys},
            }]
            for kind, detail_keys in CARD_FIELDS.items()
        },
    }
    if include_causal:
        causal_family = families[0] if families else "observational"
        claim["causal_basis"] = {
            "design_family": causal_family,
            "estimand": {key: "UNKNOWN" for key in ESTIMAND_FIELDS},
            "assumptions": [{"name": "待填写的关键识别假设", **unknown_assessment()}],
            "falsification_sensitivity": [{"name": "待填写的负对照或敏感度分析", **unknown_assessment()}],
            "assessment": unknown_assessment(),
            "necessity_test": unknown_assessment(),
            "sufficiency_test": unknown_assessment(),
        }
    return claim


def references(value, known, name):
    refs = ids(value, name)
    if not set(refs) <= known:
        fail("unknown_reference", f"{name} contains unregistered evidence IDs")
    return refs


def classification(value, domain, prefix="", scope_key="scope"):
    claim_type = enum(value[prefix + "claim_type"], tuple(TYPE_LEVELS), prefix + "claim_type")
    if (domain == "scientific" and claim_type == "engineering") or (domain == "general" and claim_type not in ("description", "computational", "engineering")):
        fail("invalid_value", "claim_type is incompatible with the case domain")
    enum(value[prefix + "evidence_level"], TYPE_LEVELS[claim_type], prefix + "evidence_level")
    string(value[scope_key], scope_key)


def assessment(value, known, name):
    obj(value, name)
    required = {"status", "reason", "evidence_ids"}
    fields(value, required, required, name)
    enum(value["status"], CHECK_STATUSES, name + ".status")
    string(value["reason"], name + ".reason")
    references(value["evidence_ids"], known, name + ".evidence_ids")


def assessment_map(value, keys, known, name):
    obj(value, name)
    fields(value, set(keys), set(keys), name)
    for key in keys:
        assessment(value[key], known, name + "." + key)


def needs_causal_basis(value):
    return value["claim_type"] in CAUSAL_TYPES or (value["claim_type"] == "mechanism" and value["evidence_level"] == "causal_chain_tested")


def causal_basis(value, known, families):
    obj(value, "causal_basis")
    required = {"design_family", "estimand", "assumptions", "falsification_sensitivity", "assessment", "necessity_test", "sufficiency_test"}
    fields(value, required, required, "causal_basis")
    family = enum(value["design_family"], tuple(DESIGN_FIELDS), "causal_basis.design_family")
    if family not in families:
        fail("missing_design", "causal design family must have a registered design package")
    estimand = obj(value["estimand"], "estimand")
    fields(estimand, set(ESTIMAND_FIELDS), set(ESTIMAND_FIELDS), "estimand")
    for name in ESTIMAND_FIELDS:
        string(estimand[name], "estimand." + name)
    for key in ("assumptions", "falsification_sensitivity"):
        entries = array(value[key], key, minimum=1, maximum=30)
        names = []
        for entry in entries:
            obj(entry, key)
            fields(entry, {"name", "status", "reason", "evidence_ids"}, {"name", "status", "reason", "evidence_ids"}, key)
            names.append(string(entry["name"], key + ".name"))
            assessment({k: v for k, v in entry.items() if k != "name"}, known, key)
        ids(names, key + " names")
    for key in ("assessment", "necessity_test", "sufficiency_test"):
        assessment(value[key], known, "causal_basis." + key)


def validate_content(claim, domain, known):
    classification(claim, domain)
    packages = array(claim["design_packages"], "design_packages", minimum=1 if domain == "scientific" else 0, maximum=9)
    families = []
    for package in packages:
        obj(package, "design_package")
        fields(package, {"family", "checks"}, {"family", "checks"}, "design_package")
        family = enum(package["family"], tuple(DESIGN_FIELDS), "design_package.family")
        families.append(family)
        assessment_map(package["checks"], DESIGN_FIELDS[family], known, family)
    ids(families, "design families")
    assessment_map(claim["statistical_report"], STAT_FIELDS, known, "statistical_report")
    cards = obj(claim["provenance_cards"], "provenance_cards")
    fields(cards, set(CARD_FIELDS), set(CARD_FIELDS), "provenance_cards")
    card_ids = []
    for kind, detail_keys in CARD_FIELDS.items():
        for card in array(cards[kind], kind + " cards", maximum=100):
            obj(card, kind + " card")
            keys = {"id", "status", "reason", "evidence_ids", "details"}
            fields(card, keys, keys, kind + " card")
            card_ids.append(string(card["id"], "card.id", maximum=200))
            status = enum(card["status"], ("reported", "checked", "unknown", "missing", "failed", "not_run", "not_applicable"), "card.status")
            string(card["reason"], "card.reason")
            refs = references(card["evidence_ids"], known, "card.evidence_ids")
            if status == "checked" and not refs:
                fail("missing_card_evidence", "checked cards need a registered source; this still does not certify truth")
            details = obj(card["details"], "card.details")
            fields(details, set(detail_keys), set(detail_keys), "card.details")
            for key in detail_keys:
                string(details[key], "card.details." + key)
    ids(card_ids, "card IDs")
    if needs_causal_basis(claim) and "causal_basis" not in claim:
        fail("missing_causal_basis", "causal, necessity and sufficiency claims require an explicit identification record (UNKNOWN allowed)")
    if "causal_basis" in claim:
        causal_basis(claim["causal_basis"], known, families)


def validate_support(decision, claim):
    """Reject explicit contradictions/gaps, without inferring validity from form filling."""
    if decision["verdict"] not in ("supported", "partially_supported"):
        return
    if decision["evidence_level"] in ("unassessed", "unidentified", "conjectured"):
        fail("unsupported_evidence_level", "unassessed, unidentified or conjectured claims cannot receive a positive verdict")
    if not needs_causal_basis(decision):
        return
    basis = claim.get("causal_basis")
    if not basis:
        fail("missing_causal_basis", "positive causal decisions require frozen identification evidence; create a new case for new evidence")
    if basis["design_family"] not in ("observational", "quasi_experimental", "randomized", "mechanism", "evidence_synthesis"):
        fail("causal_identification_gap", "this design package alone does not identify an empirical causal claim")
    # These are documented assessments, not automated proof of the assumptions.
    required = [basis["assessment"], *basis["assumptions"]]
    if decision["evidence_level"] in ("sensitivity_supported", "counterfactual_supported", "causal_chain_tested"):
        required.extend(basis["falsification_sensitivity"])
    elif any(item["status"] == "fail" for item in basis["falsification_sensitivity"]):
        fail("causal_identification_gap", "failed falsification/sensitivity checks block positive causal support")
    if decision["claim_type"] == "necessity":
        required.append(basis["necessity_test"])
    if decision["claim_type"] == "sufficiency":
        required.append(basis["sufficiency_test"])
    from .gates import substantive_reason
    if any(item["status"] != "pass" or not item["evidence_ids"] or not substantive_reason(item.get("reason")) for item in required):
        fail("causal_identification_gap", "positive causal judgments require evidenced identification and required sensitivity assessments with substantive reasons; unresolved gaps cannot be relabelled conditional support")
    unknown = {"UNKNOWN", "NA", "N/A", "NOT_IDENTIFIABLE"}
    if any(v.strip().upper() in unknown for k, v in basis["estimand"].items() if k != "intercurrent_events"):
        fail("causal_identification_gap", "the causal estimand must be specified")
    used = {ref for item in required for ref in item["evidence_ids"]}
    if not used <= set(decision["evidence_ids"]):
        fail("missing_causal_citation", "the decision must cite its frozen identification evidence")


def describe(value, prefix="", scope_key="scope"):
    if prefix + "claim_type" in value:
        return f"{value[prefix + 'claim_type']} × {value[prefix + 'evidence_level']} | {value[scope_key]}"
    return "legacy v1: " + value[prefix + "level"]
