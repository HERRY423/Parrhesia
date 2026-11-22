"""Proactive computable methodology co-pilot bridging live cases, explorations, and packets.

Pure stdlib, strictly read-only, and strictly blind-safe (never inspects draft prose,
author framing fields, or reviewer narratives). Automatically executes applicable
statistical diagnostics (E-value, implied 90% TOST equivalence margin, Holm/BH
multiplicity with fork inflation, Gelman-Stern subgroup interaction, prediction
adequacy/utility split, and ceiling diffs) and surfaces symmetric overclaim/underclaim
guidance plus concrete next discriminating actions.
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from .compact_ledger import compute_ceiling_diff
from .contracts import fail, fields, string
from .effects import PRIMARY_EFFECT_ROLES, _norm_ppf, _record_alpha, _record_crosses_null
from .methods import (
    _compute_evalue,
    _compute_interaction_heterogeneity,
    _compute_multiplicity_audit,
    _compute_prediction_utility_audit,
)

_RATIO_METRICS = ("HR", "OR", "RR")
_LOG_SCALE_METRICS = ("HR", "OR", "RR", "IRR")
_LINEAR_DIFF_METRICS = ("diff", "mean_diff", "risk_diff", "logFC", "beta")


def _implied_tost_90_margin(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Compute the tightest symmetric equivalence margin supported by the observed 90% CI (TOST alpha=0.05)."""
    ci_lo = rec.get("ci_low")
    ci_hi = rec.get("ci_high")
    est = rec.get("estimate")
    if not isinstance(ci_lo, (int, float)) or not isinstance(ci_hi, (int, float)) or not isinstance(est, (int, float)):
        return None
    if isinstance(ci_lo, bool) or isinstance(ci_hi, bool) or isinstance(est, bool):
        return None
    ci_level = float(rec.get("ci_level", 0.95))
    if not (0.0 < ci_level < 1.0):
        return None
    metric = rec.get("metric")
    z_in = _norm_ppf(0.5 + ci_level / 2.0)
    z_90 = _norm_ppf(0.95)

    if metric in _LOG_SCALE_METRICS:
        if est <= 0.0 or ci_lo <= 0.0 or ci_hi <= 0.0 or ci_hi <= ci_lo:
            return None
        x_est = math.log(est)
        se = (math.log(ci_hi) - math.log(ci_lo)) / (2.0 * z_in)
        lo_90 = math.exp(x_est - z_90 * se)
        hi_90 = math.exp(x_est + z_90 * se)
        max_factor = math.exp(max(abs(math.log(lo_90)), abs(math.log(hi_90))))
        return {
            "scale": "log",
            "tost_90_ci_low": round(lo_90, 4),
            "tost_90_ci_high": round(hi_90, 4),
            "implied_symmetric_margin_ratio": round(max_factor, 4),
            "implied_margin_interval": [round(1.0 / max_factor, 4), round(max_factor, 4)],
            "recommended_tost_call": {
                "mode": "tost_equivalence",
                "scale": "log",
                "estimate": float(est),
                "ci_low": float(ci_lo),
                "ci_high": float(ci_hi),
                "ci_level": ci_level,
                "equiv_low": 0.8,
                "equiv_high": 1.25,
            },
        }

    if metric in _LINEAR_DIFF_METRICS:
        if ci_hi <= ci_lo:
            return None
        null_val = float(rec.get("null_value", 0.0))
        se = (float(ci_hi) - float(ci_lo)) / (2.0 * z_in)
        lo_90 = float(est) - z_90 * se
        hi_90 = float(est) + z_90 * se
        margin = max(abs(lo_90 - null_val), abs(hi_90 - null_val))
        return {
            "scale": "linear",
            "tost_90_ci_low": round(lo_90, 4),
            "tost_90_ci_high": round(hi_90, 4),
            "implied_symmetric_margin": round(margin, 4),
            "implied_margin_interval": [round(null_val - margin, 4), round(null_val + margin, 4)],
            "recommended_tost_call": {
                "mode": "tost_equivalence",
                "scale": "linear",
                "estimate": float(est),
                "ci_low": float(ci_lo),
                "ci_high": float(ci_hi),
                "ci_level": ci_level,
                "equiv_low": round(null_val - max(0.05, margin * 0.5), 4),
                "equiv_high": round(null_val + max(0.05, margin * 0.5), 4),
            },
        }
    return None


def _scoped_exec_count(claim_id: str, exec_events: list[dict[str, Any]] | None) -> int:
    if not exec_events:
        return 0
    count = 0
    for ev in exec_events:
        if not isinstance(ev, dict):
            continue
        ev_cid = ev.get("claim_id")
        if ev_cid is None or ev_cid == claim_id:
            count += 1
    return count


def analyze_claim_copilot(
    claim: dict[str, Any],
    *,
    exec_events: list[dict[str, Any]] | None = None,
    prior_exploratory_forks: int = 0,
    alpha: float = 0.05,
    include_ceiling_diff: bool = True,
) -> dict[str, Any]:
    """Run all applicable computable methodology diagnostics on a single v2 claim (read-only, blind-safe)."""
    cid = str(claim.get("id") or "C1")
    ctype = str(claim.get("claim_type") or "description")
    elevel = str(claim.get("evidence_level") or "unassessed")
    effect_records = [r for r in (claim.get("effect_records") or ()) if isinstance(r, dict)]
    design_families = {
        pkg.get("family")
        for pkg in (claim.get("design_packages") or ())
        if isinstance(pkg, dict) and pkg.get("family")
    }
    causal_family = (claim.get("causal_basis") or {}).get("design_family") if isinstance(claim.get("causal_basis"), dict) else None
    is_observational = "observational" in design_families or causal_family == "observational"

    probes: dict[str, Any] = {}
    advisories: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    check_drafts: dict[str, dict[str, Any]] = {}

    # --- Probe 1: Observational Causal / Association E-Value ---
    evalue_results: list[dict[str, Any]] = []
    if ctype in ("causal_effect", "association", "mechanism") or is_observational:
        for rec in effect_records:
            if rec.get("endpoint_role") not in PRIMARY_EFFECT_ROLES:
                continue
            metric = rec.get("metric")
            est = rec.get("estimate")
            if metric not in _RATIO_METRICS or not isinstance(est, (int, float)) or isinstance(est, bool) or est <= 0.0:
                continue
            ev_payload: dict[str, Any] = {"mode": "e_value", "metric": metric, "estimate": float(est)}
            if rec.get("ci_low") is not None and rec.get("ci_high") is not None:
                ev_payload["ci_low"] = float(rec["ci_low"])
                ev_payload["ci_high"] = float(rec["ci_high"])
            try:
                ev_res = _compute_evalue(ev_payload)
            except Exception:
                continue
            evalue_results.append({"record_id": rec.get("id"), "endpoint": rec.get("endpoint"), **ev_res})
            band = ev_res["robustness_band"]
            if ctype == "causal_effect" and is_observational:
                if band == "fragile_to_weak_confounding":
                    advisories.append({
                        "code": "fragile_observational_causal",
                        "risk_axis": "overclaim_risk",
                        "priority": "high",
                        "record_id": rec.get("id"),
                        "message": (
                            f"Primary observational {metric}={est:g} has E-value={ev_res['e_value_point']:.2f} "
                            f"(CI limit={ev_res['e_value_ci']}); weak unmeasured confounding could explain away the causal claim."
                        ),
                    })
                    next_actions.append({
                        "priority": "high",
                        "action_kind": "narrow_causal_claim_or_run_negative_control",
                        "reason": f"E-value={ev_res['e_value_point']:.2f} ({band}) is fragile for observational causal_effect.",
                        "decision_impact": "Downgrade to association × adjusted or add a passing negative-control outcome test before conditional causal support.",
                    })
                else:
                    advisories.append({
                        "code": "observational_confounding_buffer_quantified",
                        "risk_axis": "underclaim_risk",
                        "priority": "medium",
                        "record_id": rec.get("id"),
                        "message": (
                            f"Observational {metric}={est:g} achieves E-value={ev_res['e_value_point']:.2f} ({band}); "
                            "if temporal ordering and confounding checks pass, retain causal_effect × identified_under_assumptions (partially_supported) rather than retreating to insufficient_evidence."
                        ),
                    })
                check_drafts["design.observational.robustness"] = {
                    "candidate_reason": ev_res["suggested_causal_sensitivity_reason"],
                    "requires_evidence_verification": True,
                }
    if evalue_results:
        probes["e_value"] = evalue_results

    # --- Probe 2: Null Primary Effect -> Implied 90% TOST Equivalence Margin ---
    null_tost_results: list[dict[str, Any]] = []
    for rec in effect_records:
        if rec.get("endpoint_role") not in PRIMARY_EFFECT_ROLES:
            continue
        crosses = False
        try:
            crosses = bool(_record_crosses_null(rec))
        except Exception:
            crosses = False
        p_val = rec.get("p_value")
        non_sig = isinstance(p_val, (int, float)) and not isinstance(p_val, bool) and float(p_val) >= _record_alpha(rec)
        if not (crosses or non_sig):
            continue
        tost_info = _implied_tost_90_margin(rec)
        if tost_info is not None:
            null_tost_results.append({"record_id": rec.get("id"), "endpoint": rec.get("endpoint"), **tost_info})
            lo90, hi90 = tost_info["tost_90_ci_low"], tost_info["tost_90_ci_high"]
            advisories.append({
                "code": "null_effect_implied_equivalence_margin",
                "risk_axis": "overclaim_risk",
                "priority": "high",
                "record_id": rec.get("id"),
                "message": (
                    f"Primary endpoint '{rec.get('endpoint')}' does not exclude null; observed 90% CI [{lo90:g}, {hi90:g}] "
                    "only rules out effects outside that band. Absence of evidence != evidence of absence—verify a prespecified TOST margin before claiming equivalence or no effect."
                ),
            })
            next_actions.append({
                "priority": "high",
                "action_kind": "run_tost_equivalence",
                "reason": f"Primary effect crosses null/p>=alpha; implied 90% CI is [{lo90:g}, {hi90:g}].",
                "decision_impact": "Separates genuine equivalence_supported from underpowered_inconclusive (insufficient_evidence).",
                "recommended_analyze_design_call": tost_info["recommended_tost_call"],
            })
    if null_tost_results:
        probes["implied_tost_margins"] = null_tost_results

    # --- Probe 3: Multiplicity & Exploratory Fork Inflation ---
    p_entries: list[dict[str, Any]] = []
    for idx, rec in enumerate(effect_records):
        pv = rec.get("p_value")
        if isinstance(pv, (int, float)) and not isinstance(pv, bool) and 0.0 <= float(pv) <= 1.0:
            role_raw = rec.get("endpoint_role") or "unspecified"
            role_mapped = (
                "primary" if role_raw in ("primary", "benchmark")
                else "secondary" if role_raw in ("secondary", "safety", "sensitivity")
                else "exploratory"
            )
            p_entries.append({
                "id": str(rec.get("id") or f"rec_{idx + 1}"),
                "p_value": float(pv),
                "role": role_mapped,
            })
    scoped_execs = _scoped_exec_count(cid, exec_events)
    max_declared_family = max(
        (int(r["family_size"]) for r in effect_records if isinstance(r.get("family_size"), int) and not isinstance(r.get("family_size"), bool)),
        default=0,
    )
    extra_forks = max(int(prior_exploratory_forks), max(0, scoped_execs - len(p_entries)))
    eff_m = max(len(p_entries), len(p_entries) + extra_forks, max_declared_family)
    if p_entries and eff_m > 1:
        mult_payload: dict[str, Any] = {
            "mode": "multiplicity_audit",
            "p_values": p_entries,
            "alpha": alpha,
            "family_size": eff_m,
            "prior_exploratory_forks": int(prior_exploratory_forks),
        }
        try:
            mult_res = _compute_multiplicity_audit(mult_payload)
            probes["multiplicity_audit"] = mult_res
            eroded_primary = [
                r for r in mult_res["adjusted_tests"]
                if r["role"] == "primary" and r["status"] == "fails_multiplicity"
            ]
            if eroded_primary:
                ids_str = ", ".join(r["id"] for r in eroded_primary)
                advisories.append({
                    "code": "primary_effect_eroded_by_multiplicity",
                    "risk_axis": "overclaim_risk",
                    "priority": "high",
                    "message": (
                        f"Primary endpoint(s) [{ids_str}] are nominally p < {alpha:g} but fail Holm-Bonferroni FWER "
                        f"and BH-FDR across effective family M={eff_m} (Bonferroni cutoff={mult_res['bonferroni_alpha']:.4g})."
                    ),
                })
                next_actions.append({
                    "priority": "high",
                    "action_kind": "apply_multiplicity_correction_or_replicate",
                    "reason": f"Multiplicity erosion across M={eff_m} tests/forks.",
                    "decision_impact": "Prevents overclaiming exploratory hits as FWER-confirmed effects.",
                })
            elif mult_res["holm_fwer_significant_count"] > 0:
                advisories.append({
                    "code": "primary_effect_survives_fwer",
                    "risk_axis": "underclaim_risk",
                    "priority": "low",
                    "message": (
                        f"{mult_res['holm_fwer_significant_count']} endpoint(s) survive Holm-Bonferroni FWER across M={eff_m}; "
                        "do not downgrade FWER-surviving endpoints using generic multiplicity caveats."
                    ),
                })
            check_drafts["statistics.multiplicity_selection"] = {
                "candidate_reason": mult_res["suggested_multiplicity_reason"],
                "requires_evidence_verification": True,
            }
        except Exception:
            pass

    # --- Probe 4: Subgroup Interaction Contrast / Gelman-Stern Illusion ---
    rec_by_id = {r.get("id"): r for r in effect_records if r.get("id")}
    interaction_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for rec in effect_records:
        ic = rec.get("interaction_contrast")
        if isinstance(ic, dict) and isinstance(ic.get("record_ids"), list) and len(ic["record_ids"]) == 2:
            a, b = rec_by_id.get(ic["record_ids"][0]), rec_by_id.get(ic["record_ids"][1])
            if a and b:
                key = tuple(sorted((str(a["id"]), str(b["id"]))))
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    interaction_pairs.append((a, b))
    # Also auto-detect a clean pair of secondary/exploratory subgroup records sharing metric & CI
    if not interaction_pairs:
        non_prim = [
            r for r in effect_records
            if r.get("endpoint_role") in ("secondary", "exploratory")
            and r.get("ci_low") is not None and r.get("ci_high") is not None
        ]
        if len(non_prim) == 2 and non_prim[0].get("metric") == non_prim[1].get("metric"):
            interaction_pairs.append((non_prim[0], non_prim[1]))

    interaction_results: list[dict[str, Any]] = []
    for a, b in interaction_pairs:
        metric = a.get("metric")
        scale = "log" if metric in _LOG_SCALE_METRICS else "linear"
        if a.get("ci_low") is None or a.get("ci_high") is None or b.get("ci_low") is None or b.get("ci_high") is None:
            continue
        try:
            ires = _compute_interaction_heterogeneity({
                "mode": "interaction_heterogeneity",
                "scale": scale,
                "alpha": alpha,
                "group_a": {"label": str(a.get("endpoint") or a.get("id")), "estimate": float(a["estimate"]), "ci_low": float(a["ci_low"]), "ci_high": float(a["ci_high"])},
                "group_b": {"label": str(b.get("endpoint") or b.get("id")), "estimate": float(b["estimate"]), "ci_low": float(b["ci_low"]), "ci_high": float(b["ci_high"])},
            })
            interaction_results.append(ires)
            if ires["sig_vs_nonsig_illusion"]:
                advisories.append({
                    "code": "subgroup_sig_vs_nonsig_illusion",
                    "risk_axis": "overclaim_risk",
                    "priority": "high",
                    "message": ires["guidance"],
                })
                next_actions.append({
                    "priority": "high",
                    "action_kind": "retract_untested_subgroup_difference",
                    "reason": f"Direct interaction p={ires['interaction_p_value']:.4g} >= {alpha:g} despite opposite subgroup significance.",
                    "decision_impact": "Eliminates Gelman-Stern subgroup heterogeneity overclaim.",
                })
            elif ires["classification"] == "interaction_supported":
                advisories.append({
                    "code": "subgroup_interaction_confirmed",
                    "risk_axis": "underclaim_risk",
                    "priority": "medium",
                    "message": ires["guidance"],
                })
        except Exception:
            continue
    if interaction_results:
        probes["interaction_heterogeneity"] = interaction_results

    # --- Probe 5: Prediction External Discrimination vs Utility Split ---
    if ctype == "prediction":
        for rec in effect_records:
            if rec.get("endpoint_role") not in PRIMARY_EFFECT_ROLES:
                continue
            if rec.get("metric") not in ("AUROC", "AUC"):
                continue
            est = rec.get("estimate")
            ci_lo = rec.get("ci_low")
            if isinstance(est, (int, float)) and not isinstance(est, bool) and est >= 0.70:
                pred_payload: dict[str, Any] = {
                    "mode": "prediction_utility_audit",
                    "validation_stage": "external" if elevel in ("externally_validated", "prospectively_evaluated") else "internal",
                }
                if isinstance(rec.get("n"), int) and not isinstance(rec.get("n"), bool):
                    pred_payload["n"] = rec["n"]
                if isinstance(rec.get("events"), int) and not isinstance(rec.get("events"), bool):
                    pred_payload["events"] = rec["events"]
                if "n" in pred_payload or "events" in pred_payload:
                    try:
                        probes["prediction_utility_audit"] = _compute_prediction_utility_audit(pred_payload)
                    except Exception:
                        pass
                if isinstance(ci_lo, (int, float)) and not isinstance(ci_lo, bool) and ci_lo > 0.65:
                    advisories.append({
                        "code": "prediction_discrimination_vs_utility_split",
                        "risk_axis": "underclaim_risk",
                        "priority": "medium",
                        "record_id": rec.get("id"),
                        "message": (
                            f"Primary {rec.get('metric')}={est:g} (CI lower={ci_lo:g} > 0.65) demonstrates clear discrimination; "
                            "preserve the validated prediction contribution and restrict limitations specifically to untested clinical net benefit rather than retreating to insufficient_evidence."
                        ),
                    })
                    next_actions.append({
                        "priority": "medium",
                        "action_kind": "evaluate_decision_curve_net_benefit",
                        "reason": "Discrimination (AUROC) does not automatically establish clinical decision utility.",
                        "decision_impact": "Run analyze_design(mode='prediction_utility_audit') with confusion matrix and clinical threshold_probability to test Net Benefit separately.",
                    })

    # --- Probe 6: Check Ceiling Diff ---
    cdiff = compute_ceiling_diff(claim, elevel) if include_ceiling_diff else None
    if cdiff and not cdiff["can_reach_target"] and cdiff["blocker_count"] > 0:
        sample_blockers = [b["path"] for b in cdiff["missing_for_target"][:4]]
        next_actions.append({
            "priority": "medium",
            "action_kind": "resolve_ceiling_blockers_or_narrow_level",
            "reason": f"{cdiff['blocker_count']} check(s) currently block {ctype} x {elevel} (e.g., {', '.join(sample_blockers)}).",
            "decision_impact": f"Either supply evidenced checks for blocked paths or narrow to highest currently allowed level ({cdiff['highest_currently_allowed']}).",
        })

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    next_actions.sort(key=lambda item: priority_rank.get(item.get("priority", "low"), 3))
    risk_counts = {
        "overclaim_risk": sum(1 for a in advisories if a["risk_axis"] == "overclaim_risk"),
        "underclaim_risk": sum(1 for a in advisories if a["risk_axis"] == "underclaim_risk"),
        "neutrality_risk": sum(1 for a in advisories if a["risk_axis"] == "neutrality_risk"),
        "design_gap": sum(1 for a in advisories if a["risk_axis"] == "design_gap"),
    }

    out: dict[str, Any] = {
        "claim_id": cid,
        "claim_type": ctype,
        "evidence_level": elevel,
        "probes_executed": sorted(probes.keys()),
        "probes": probes,
        "advisory_count": len(advisories),
        "advisories": advisories,
        "risk_summary": risk_counts,
        "next_discriminating_actions": next_actions,
    }
    if cdiff is not None:
        out["ceiling_diff"] = cdiff
    if check_drafts:
        out["check_draft_templates"] = check_drafts
    return out


def _find_linked_exploration(db: sqlite3.Connection, case_id: str, explicit_explore_id: str | None = None) -> dict[str, Any] | None:
    if explicit_explore_id:
        row = db.execute("SELECT document FROM explorations WHERE id=?", (explicit_explore_id,)).fetchone()
        if row is None:
            fail("unknown_exploration", f"explore_id '{explicit_explore_id}' does not exist in this workspace")
        return json.loads(row[0])
    try:
        rows = db.execute("SELECT document FROM explorations ORDER BY updated_at DESC").fetchall()
    except sqlite3.OperationalError:
        return None
    for (raw,) in rows:
        doc = json.loads(raw)
        if case_id in (doc.get("promoted_case_ids") or ()):
            return doc
    return None


def _load_case_exec_events(db: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT details FROM events WHERE case_id=? AND action='record_exec' ORDER BY sequence ASC",
        (case_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                out.append(data)
        except Exception:
            continue
    return out


def analyze_case_copilot(db: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Proactively audit a live workspace case and optional exploration tree (read-only)."""
    fields(
        payload,
        {"mode", "case_id", "claim_id", "explore_id", "alpha"},
        {"mode", "case_id"},
        "analyze_design.case_audit",
    )
    case_id = string(payload["case_id"], "case_id", maximum=200)
    target_claim_id = string(payload["claim_id"], "claim_id", maximum=200) if "claim_id" in payload else None
    explicit_exp_id = string(payload["explore_id"], "explore_id", maximum=200) if "explore_id" in payload else None
    alpha = payload.get("alpha", 0.05)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not (0.0 < float(alpha) < 1.0):
        fail("invalid_value", "alpha must lie in (0, 1)")
    alpha = float(alpha)

    row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        fail("unknown_case", f"case_id '{case_id}' does not exist in this workspace")
    case = json.loads(row[0])
    if case.get("schema_version", 1) != 2:
        fail("invalid_state", "case_audit requires a v2 case")

    claims = list(case.get("claims") or ())
    if target_claim_id is not None:
        claims = [c for c in claims if c.get("id") == target_claim_id]
        if not claims:
            fail("unknown_claim", f"claim_id '{target_claim_id}' does not exist in case '{case_id}'")

    exec_events = _load_case_exec_events(db, case_id)
    explore_doc = _find_linked_exploration(db, case_id, explicit_exp_id)
    prior_forks = int(explore_doc.get("exploratory_forks", 0)) if explore_doc else 0

    claim_audits = [
        analyze_claim_copilot(
            cl,
            exec_events=exec_events,
            prior_exploratory_forks=prior_forks,
            alpha=alpha,
            include_ceiling_diff=True,
        )
        for cl in claims
    ]
    total_risks = {
        key: sum(ca["risk_summary"][key] for ca in claim_audits)
        for key in ("overclaim_risk", "underclaim_risk", "neutrality_risk", "design_gap")
    }
    all_actions: list[dict[str, Any]] = []
    for ca in claim_audits:
        for act in ca["next_discriminating_actions"]:
            all_actions.append({"claim_id": ca["claim_id"], **act})
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    all_actions.sort(key=lambda item: priority_rank.get(item.get("priority", "low"), 3))

    out: dict[str, Any] = {
        "mode": "case_audit",
        "case_id": case_id,
        "case_state": case.get("state"),
        "linked_explore_id": explore_doc["explore_id"] if explore_doc else None,
        "prior_exploratory_forks": prior_forks,
        "exec_event_count": len(exec_events),
        "audited_claim_count": len(claim_audits),
        "risk_summary": total_risks,
        "claim_audits": claim_audits,
        "next_discriminating_actions": all_actions[:12],
    }

    # Proactively attach cross-case living synthesis summary when this case participates in a multi-case lineage.
    try:
        from .storage import load_connected_component_cases
        from .synthesis import synthesize_claim_lineage

        component = load_connected_component_cases(db, case_id=case_id, claim_id=target_claim_id)
        if len(component) > 1:
            synth = synthesize_claim_lineage(component, case_id=case_id, claim_id=target_claim_id, alpha=alpha)
            out["lineage_synthesis_summary"] = {
                "scoped_case_count": synth["scoped_case_count"],
                "independent_pooled_case_count": synth["independent_pooled_case_count"],
                "living_status": synth["living_status"],
                "triggered_ancestor_count": synth["triggered_ancestor_count"],
                "triggered_ancestors": synth["triggered_ancestors"],
                "excluded_non_independent_count": synth["deduplication_guard"]["excluded_non_independent_count"],
                "living_next_actions": synth["living_next_actions"],
            }
    except Exception:
        pass
    return out


def build_packet_computable_diagnostics(
    case: dict[str, Any],
    *,
    exec_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build a blind-safe, de-narrativized quantitative diagnostic summary for review/adjudication packets.

    Returns None if no claim triggers any computable statistical probe, keeping simple packets minimal.
    """
    claims = case.get("claims") or ()
    per_claim: list[dict[str, Any]] = []
    for cl in claims:
        if not isinstance(cl, dict):
            continue
        audit = analyze_claim_copilot(
            cl,
            exec_events=exec_events,
            prior_exploratory_forks=0,
            include_ceiling_diff=False,
        )
        if audit["probes"]:
            per_claim.append({
                "claim_id": audit["claim_id"],
                "probes_executed": audit["probes_executed"],
                "probes": audit["probes"],
                "advisories": audit["advisories"],
                "risk_summary": audit["risk_summary"],
            })
    if not per_claim:
        return None
    return {
        "protocol": "computable_copilot_v1",
        "basis": "deterministic_math_from_frozen_effect_records_and_exec_events_only",
        "blind_safe": True,
        "claims": per_claim,
    }


def build_explore_copilot_guidance(doc: dict[str, Any], *, alpha: float = 0.05) -> dict[str, Any]:
    """Compute real-time forking-paths multiplicity inflation and pre-lock methodology guidance for L1-Explore."""
    forks = int(doc.get("exploratory_forks", 0))
    eff_m = max(1, forks)
    global_null_fwer = min(1.0, max(0.0, -math.expm1(eff_m * math.log1p(-alpha))))
    bonf = alpha / eff_m
    sidak = 1.0 - (1.0 - alpha) ** (1.0 / eff_m)
    active = [h for h in (doc.get("hypotheses") or ()) if h.get("status") == "active"]
    killed = [h for h in (doc.get("hypotheses") or ()) if h.get("status") == "killed"]
    hints: list[str] = []
    if forks > 1:
        hints.append(
            f"Cumulative exploratory_forks={forks} inflates nominal alpha={alpha:g} global-null FWER to {global_null_fwer:.1%} "
            f"(Bonferroni={bonf:.4g}, Sidak={sidak:.4g}); do NOT treat exploratory p < 0.05 as confirmatory."
        )
    if len(active) == 1 and not killed:
        hints.append(
            "Only 1 active hypothesis without a competing rival card: register at least one strongest rival to prevent confirmation bias."
        )
    if active and not (doc.get("locked_plans") or ()):
        hints.append(
            "Before lock_plan, verify sample size/MDE with analyze_design(mode='power_mde') and clustering with analyze_design(mode='pseudoreplication_audit')."
        )
    return {
        "effective_forks": eff_m,
        "global_null_fwer_at_alpha": round(global_null_fwer, 6),
        "bonferroni_alpha": round(bonf, 8),
        "sidak_alpha": round(sidak, 8),
        "active_hypotheses": len(active),
        "killed_hypotheses": len(killed),
        "guidance": hints,
    }
