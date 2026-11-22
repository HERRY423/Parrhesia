"""Thin-input / thick-kernel compact claim compiler and ceiling-diff helper.

Reduces Agent protocol friction from ~112-144 manual leaf fields down to ~8-15 core
scientific inputs, while keeping every unassessed check honestly marked 'unknown' or
'not_run' and never upgrading evidence levels or study design automatically.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS, TYPE_LEVELS, needs_causal_basis, scaffold_claim_template
from .contracts import ALTERNATIVE_STATUSES, CHECK_NAMES, CHECK_STATUSES, ORIGINS, array, enum, fail, fields, ids, obj, string
from .gates import BASES, ceiling


def compute_ceiling_diff(claim: dict[str, Any], target_level: str | None = None) -> dict[str, Any]:
    """Compute current allowed levels and exact minimal blockers keeping claim below target_level."""
    kind = claim["claim_type"]
    goal = target_level or claim["evidence_level"]
    limits = ceiling(claim, kind)
    allowed = limits["allowed_levels"]
    blocked = limits["blocked_levels"]
    missing = blocked.get(goal, [])
    return {
        "claim_id": claim["id"],
        "claim_type": kind,
        "target_level": goal,
        "current_allowed_levels": allowed,
        "highest_currently_allowed": allowed[-1] if allowed else "unassessed",
        "can_reach_target": goal in allowed,
        "missing_for_target": missing,
        "blocker_count": len(missing),
        "verdict_ceiling": limits["verdict_ceiling"],
    }


def _apply_check_override(claim: dict[str, Any], path: str, value: Any, known_evidence: set[str]) -> None:
    rec = obj(value, f"checks_overrides['{path}']")
    parts = path.split(".")
    if len(parts) == 1 and parts[0] in CHECK_NAMES:
        fields(rec, {"status", "reason"}, {"status", "reason"}, f"checks_overrides['{path}']")
        status = enum(rec["status"], CHECK_STATUSES, f"{path}.status")
        reason = string(rec["reason"], f"{path}.reason")
        claim["checks"][parts[0]] = {"status": status, "reason": reason}
        return
    if len(parts) == 2 and parts[0] == "checks" and parts[1] in CHECK_NAMES:
        fields(rec, {"status", "reason"}, {"status", "reason"}, f"checks_overrides['{path}']")
        claim["checks"][parts[1]] = {
            "status": enum(rec["status"], CHECK_STATUSES, f"{path}.status"),
            "reason": string(rec["reason"], f"{path}.reason"),
        }
        return
    if len(parts) == 2 and parts[0] == "statistics" and parts[1] in STAT_FIELDS:
        fields(rec, {"status", "reason", "evidence_ids"}, {"status", "reason"}, f"checks_overrides['{path}']")
        eids = ids(rec.get("evidence_ids", []), f"{path}.evidence_ids")
        if not set(eids) <= known_evidence:
            fail("unknown_reference", f"{path}.evidence_ids contains unregistered evidence IDs")
        claim["statistical_report"][parts[1]] = {
            "status": enum(rec["status"], CHECK_STATUSES, f"{path}.status"),
            "reason": string(rec["reason"], f"{path}.reason"),
            "evidence_ids": eids,
        }
        return
    if len(parts) == 3 and parts[0] == "design" and parts[1] in DESIGN_FIELDS and parts[2] in DESIGN_FIELDS[parts[1]]:
        fam, field_name = parts[1], parts[2]
        fields(rec, {"status", "reason", "evidence_ids"}, {"status", "reason"}, f"checks_overrides['{path}']")
        eids = ids(rec.get("evidence_ids", []), f"{path}.evidence_ids")
        if not set(eids) <= known_evidence:
            fail("unknown_reference", f"{path}.evidence_ids contains unregistered evidence IDs")
        pkg = next((p for p in claim["design_packages"] if p["family"] == fam), None)
        if pkg is None:
            pkg = {
                "family": fam,
                "checks": {
                    k: {"status": "unknown", "reason": "Not yet assessed", "evidence_ids": []}
                    for k in DESIGN_FIELDS[fam]
                },
            }
            claim["design_packages"].append(pkg)
        pkg["checks"][field_name] = {
            "status": enum(rec["status"], CHECK_STATUSES, f"{path}.status"),
            "reason": string(rec["reason"], f"{path}.reason"),
            "evidence_ids": eids,
        }
        return
    fail(
        "unknown_field",
        f"Unsupported checks_overrides path '{path}'. Use a check name ({', '.join(CHECK_NAMES)}), "
        "'statistics.<field>', or 'design.<family>.<field>'.",
    )


def compile_compact_claim(
    payload: dict[str, Any],
    case: dict[str, Any],
    extract_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile a compact (~8-15 field) scientific claim input into a schema-valid v2 claim."""
    allowed = {
        "case_id", "claim_id", "text", "claim_type", "evidence_level", "claim_basis",
        "scope", "evidence_ids", "effect", "origin", "hypothesis_id", "contribution",
        "alternatives", "design_families", "checks_overrides", "provenance_cards_overrides",
        "causal_basis", "effect_records", "effect_sources", "reversal_triggers",
        "prior_claim_links", "best_current_explanation", "discriminating_test",
    }
    required = {"case_id", "claim_id", "text", "claim_type"}
    fields(payload, allowed, required, "upsert_claim")

    domain = case.get("domain", "scientific")
    claim_id = string(payload["claim_id"], "claim_id", maximum=200)
    claim_type = enum(payload["claim_type"], tuple(TYPE_LEVELS), "claim_type")
    target_level = enum(payload.get("evidence_level", TYPE_LEVELS[claim_type][0]), TYPE_LEVELS[claim_type], "evidence_level")
    default_basis = "formal" if claim_type == "theory" else "empirical"
    claim_basis = enum(payload.get("claim_basis", default_basis), BASES, "claim_basis")

    scaffold_req: dict[str, Any] = {
        "claim_id": claim_id,
        "text": string(payload["text"], "text"),
        "claim_type": claim_type,
        "evidence_level": target_level,
        "claim_basis": claim_basis,
        "scope": string(payload.get("scope", "UNKNOWN"), "scope"),
        "domain": domain,
        "include_causal_basis": bool(
            "causal_basis" in payload or needs_causal_basis({"claim_type": claim_type, "evidence_level": target_level})
        ),
    }
    if "design_families" in payload:
        scaffold_req["design_families"] = payload["design_families"]
    claim = scaffold_claim_template(scaffold_req)

    known_ev = {e["evidence_id"] for e in case.get("evidence") or ()}
    ev_ids = ids(payload.get("evidence_ids", []), "evidence_ids")
    if not set(ev_ids) <= known_ev:
        fail("unknown_reference", "upsert_claim.evidence_ids contains unregistered evidence IDs")
    claim["evidence_ids"] = list(ev_ids)

    prefill_report: dict[str, Any] | None = None
    if "effect_sources" in payload:
        if extract_fn is None:
            fail("invalid_state", "effect_sources prefill requires extract callback")
        from .prefill import prefill_claim
        claim, prefill_report = prefill_claim(
            claim,
            {"evidence_ids": ev_ids, "effect_sources": payload["effect_sources"]},
            case,
            extract_fn,
        )

    if "effect_records" in payload:
        claim["effect_records"] = deepcopy(payload["effect_records"])
        for rec in claim["effect_records"]:
            if isinstance(rec, dict) and isinstance(rec.get("evidence_id"), str) and rec["evidence_id"] in known_ev:
                if rec["evidence_id"] not in claim["evidence_ids"]:
                    claim["evidence_ids"].append(rec["evidence_id"])

    if "effect" in payload:
        eff = obj(payload["effect"], "effect")
        fields(eff, {"estimate", "uncertainty"}, {"estimate", "uncertainty"}, "effect")
        claim["effect"] = {
            "estimate": string(eff["estimate"], "effect.estimate"),
            "uncertainty": string(eff["uncertainty"], "effect.uncertainty"),
        }
    if "origin" in payload:
        claim["origin"] = enum(payload["origin"], ORIGINS, "origin")
    if "hypothesis_id" in payload and payload["hypothesis_id"] is not None:
        claim["hypothesis_id"] = string(payload["hypothesis_id"], "hypothesis_id", maximum=200)
    if "contribution" in payload:
        claim["contribution"] = string(payload["contribution"], "contribution")
    if "best_current_explanation" in payload:
        claim["best_current_explanation"] = string(payload["best_current_explanation"], "best_current_explanation", optional=True)
    if "discriminating_test" in payload:
        claim["discriminating_test"] = string(payload["discriminating_test"], "discriminating_test", optional=True)

    if "alternatives" in payload:
        alts_in = array(payload["alternatives"], "alternatives", minimum=1 if domain == "scientific" else 0, maximum=3)
        compiled_alts = []
        for idx, item in enumerate(alts_in):
            if isinstance(item, str):
                compiled_alts.append({
                    "explanation": string(item, f"alternatives[{idx}]"),
                    "status": "not_excluded",
                    "reason": "Registered rival explanation; exclusion status not yet assessed",
                })
            else:
                aobj = obj(item, f"alternatives[{idx}]")
                fields(aobj, {"explanation", "status", "reason"}, {"explanation"}, f"alternatives[{idx}]")
                compiled_alts.append({
                    "explanation": string(aobj["explanation"], f"alternatives[{idx}].explanation"),
                    "status": enum(aobj.get("status", "not_excluded"), ALTERNATIVE_STATUSES, f"alternatives[{idx}].status"),
                    "reason": string(aobj.get("reason", "Not yet evaluated against evidence"), f"alternatives[{idx}].reason"),
                })
        claim["alternatives"] = compiled_alts

    if "checks_overrides" in payload:
        overrides = obj(payload["checks_overrides"], "checks_overrides")
        claim_ev_set = set(claim["evidence_ids"])
        for path, val in overrides.items():
            # Allow referencing any case evidence and auto-attach to claim.evidence_ids
            if isinstance(val, dict):
                for ref in val.get("evidence_ids") or ():
                    if isinstance(ref, str) and ref in known_ev and ref not in claim_ev_set:
                        claim["evidence_ids"].append(ref)
                        claim_ev_set.add(ref)
            _apply_check_override(claim, path, val, known_ev)

    if "provenance_cards_overrides" in payload:
        pc_over = obj(payload["provenance_cards_overrides"], "provenance_cards_overrides")
        for kind, cards in pc_over.items():
            if kind not in CARD_FIELDS:
                fail("unknown_field", f"Unknown provenance card kind '{kind}'")
            claim["provenance_cards"][kind] = deepcopy(cards)
            for card in cards if isinstance(cards, list) else ():
                if isinstance(card, dict):
                    for ref in card.get("evidence_ids") or ():
                        if isinstance(ref, str) and ref in known_ev and ref not in claim["evidence_ids"]:
                            claim["evidence_ids"].append(ref)

    if "causal_basis" in payload:
        cb_in = obj(payload["causal_basis"], "causal_basis")
        base_cb = claim.get("causal_basis") or {}
        for k, v in cb_in.items():
            if k == "estimand" and isinstance(v, dict) and isinstance(base_cb.get("estimand"), dict):
                base_cb["estimand"] = {**base_cb["estimand"], **v}
            else:
                base_cb[k] = deepcopy(v)
        claim["causal_basis"] = base_cb
        # Auto-attach referenced causal evidence IDs to claim.evidence_ids
        for key in ("assessment", "necessity_test", "sufficiency_test"):
            item = base_cb.get(key)
            if isinstance(item, dict):
                for ref in item.get("evidence_ids") or ():
                    if isinstance(ref, str) and ref in known_ev and ref not in claim["evidence_ids"]:
                        claim["evidence_ids"].append(ref)
        for key in ("assumptions", "falsification_sensitivity"):
            for item in base_cb.get(key) or ():
                if isinstance(item, dict):
                    for ref in item.get("evidence_ids") or ():
                        if isinstance(ref, str) and ref in known_ev and ref not in claim["evidence_ids"]:
                            claim["evidence_ids"].append(ref)

    if "reversal_triggers" in payload:
        claim["reversal_triggers"] = deepcopy(payload["reversal_triggers"])
    if "prior_claim_links" in payload:
        claim["prior_claim_links"] = deepcopy(payload["prior_claim_links"])

    meta = {
        "prefill_report": prefill_report,
        "ceiling_diff": compute_ceiling_diff(claim, target_level),
    }
    return claim, meta
