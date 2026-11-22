"""Read-only claim assembly from explicit, case-local source selections."""
from __future__ import annotations

from copy import deepcopy

from .claims import scaffold_claim_template
from .contracts import array, fields, ids, obj, string, fail


def prefill_claim(claim: dict, binding: dict, case: dict, extract) -> tuple[dict, dict]:
    """Never infer support, endpoint priority, study design or historical timing."""
    obj(binding, "prefill")
    fields(binding, {"evidence_ids", "effect_sources", "hypothesis_id", "design_families"}, set(), "prefill")
    result = deepcopy(claim)
    known = {e["evidence_id"]: e for e in case["evidence"]}
    selected = ids(binding.get("evidence_ids", []), "prefill.evidence_ids")
    if set(selected) - known.keys():
        fail("unknown_evidence", "Prefill evidence must belong to this case")
    result["evidence_ids"] = list(dict.fromkeys([*result["evidence_ids"], *selected]))
    report = {"claim_id": result["id"], "sources": [], "hypothesis": None,
              "ledger_operation": "set_ledger_replaces_all_claims; merge existing claims explicitly",
              "existing_claim_ids": [c["id"] for c in case["claims"]],
              "assessment": "draft_only; checks, evidence level and origin are not promoted"}
    if "design_families" in binding:
        template = scaffold_claim_template({"domain": case["domain"], "claim_type": result["claim_type"],
                                            "design_families": binding["design_families"]})
        result["design_packages"] = template["design_packages"]
        if "causal_basis" in result:
            result["causal_basis"]["design_family"] = binding["design_families"][0] if binding["design_families"] else "observational"
    if "hypothesis_id" in binding:
        hypothesis_id = string(binding["hypothesis_id"], "prefill.hypothesis_id", maximum=200)
        hypothesis = next((h for h in case["hypotheses"] if h["hypothesis_id"] == hypothesis_id), None)
        if hypothesis is None:
            fail("unknown_hypothesis", "Prefill hypothesis must belong to this case")
        result["hypothesis_id"] = hypothesis_id
        report["hypothesis"] = {"hypothesis_id": hypothesis_id, "timing_basis": hypothesis["timing_basis"],
                                "origin": "unknown", "timing_verification": hypothesis["timing_verification"]}
    seen = set()
    records = []
    for source in array(binding.get("effect_sources", []), "prefill.effect_sources", maximum=20):
        obj(source, "effect_source")
        fields(source, {"evidence_id", "record_ids", "format", "column_map", "sheet_name"}, {"evidence_id", "record_ids"}, "effect_source")
        evidence_id = string(source["evidence_id"], "effect_source.evidence_id", maximum=200)
        record_ids = ids(source["record_ids"], "effect_source.record_ids", minimum=1, maximum=50)
        extracted = extract({"case_id": case["case_id"], **{k: v for k, v in source.items() if k != "record_ids"}})
        if len(extracted.get("xlsx", {}).get("sheet_names", ())) > 1 and "sheet_name" not in source:
            fail("ambiguous_source", "Prefill from a multi-sheet XLSX requires the explicit sheet_name used to select the records")
        by_id = {r["id"]: r for r in extracted["effect_records"]}
        if set(record_ids) - by_id.keys():
            fail("unknown_effect_record", "Selected record is absent or invalid; inspect extract_effects issues")
        source_report = {"evidence_id": evidence_id, "source_sha256": extracted["source_sha256"],
                         "selected_records": [], "unselected_record_ids": [r for r in by_id if r not in record_ids],
                         "issues": extracted["issues"], "input_row_count": extracted["input_row_count"],
                         "execution_binding": extracted["execution_binding"], "source_state": extracted["source_state"]}
        if "xlsx" in extracted:
            source_report["sheet_name"] = extracted["xlsx"]["sheet"]
        for record_id in record_ids:
            record = deepcopy(by_id[record_id])
            row = record["artifact_binding"]
            identity = (evidence_id, row.get("sheet"), row["record_index"])
            if identity in seen:
                fail("duplicate_id", "A source row may be selected only once per claim")
            seen.add(identity)
            record["id"] = f"prefill-effect-{len(records) + 1}"
            records.append(record)
            source_report["selected_records"].append({"source_record_id": record_id, "effect_record_id": record["id"]})
        report["sources"].append(source_report)
        if evidence_id not in result["evidence_ids"]:
            result["evidence_ids"].append(evidence_id)
    if len(records) > 50:
        fail("too_large", "At most 50 selected effects per claim")
    if "effect_sources" in binding:
        result["effect_records"] = records
    ids(result["evidence_ids"], "claim.evidence_ids")
    return result, report
