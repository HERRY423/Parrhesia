"""Measurable epistemic calibration, scoring rules, and interval coverage. Pure stdlib."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .effects import EFFECT_METRICS, INFERENCE_METHODS, PRIMARY_EFFECT_ROLES, RATIO_METRICS, _norm_ppf, _record_is_anchored
from .contracts import enum, fail, fields, string
from .gates import meaningful
from .triggers import adjudication_is_effective, collect_claim_triggers, evaluate_case_triggers

CALIBRATION_OUTCOMES = ("replicated", "partially_replicated", "refuted", "inconclusive")
CALIBRATION_RESOLUTION_SOURCES = ("follow_up_case", "external_evidence", "trigger_evaluation")
COMPARISON_KINDS = ("replication_estimate", "known_truth")
COMPARISON_ASSUMPTIONS = ("independent", "covariance_supplied", "unknown")

DEFAULT_OUTCOME_SCORES: dict[str, float | None] = {
    "replicated": 1.0,
    "partially_replicated": 0.5,
    "refuted": 0.0,
    "inconclusive": None,
}

DEFAULT_CONFIDENCE_PROBABILITIES: dict[str, float] = {
    "high": 0.85,
    "medium": 0.60,
    "low": 0.30,
}

CALIBRATION_BINS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0),
)

_CALIBRATION_STATES = ("adjudicated", "export_pending", "exported")
_POSITIVE_VERDICTS = ("supported", "partially_supported")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _finite_number(value: Any, name: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        fail("invalid_type", f"{name} must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        fail("invalid_value", f"{name} must be a finite number")
    return num


def validate_forecast_probability(value: Any, name: str = "decision.forecast_probability") -> float:
    """Validate optional explicit probability in [0.0, 1.0]."""
    num = _finite_number(value, name)
    if num < 0.0 or num > 1.0:
        fail("invalid_value", f"{name} must be in [0.0, 1.0]")
    return num


def _resolution_binding(record: dict, case: dict, cases_by_id: dict[str, dict], evidence_by_id: dict[str, dict]) -> dict:
    """Assess traceability, never the truth of an outcome reported by the caller."""
    source = record.get("resolution_source")
    refs: list[str] = []
    reason = None
    if source == "external_evidence":
        if record.get("evidence_id"):
            refs = [record["evidence_id"]]
        else:
            reason = "missing_outcome_evidence"
    elif source == "follow_up_case":
        follow = cases_by_id.get(record.get("follow_up_case_id")) or {}
        fc_id = record.get("follow_up_claim_id")
        cl = next((c for c in follow.get("claims", ()) if c["id"] == fc_id), None)
        dec = next((d for d in (follow.get("adjudication") or {}).get("decisions", ()) if d["claim_id"] == fc_id), None)
        linked = cl and any(l.get("prior_case_id") == case["case_id"] and l.get("prior_claim_id") == record["claim_id"] for l in cl.get("prior_claim_links", ()))
        if not adjudication_is_effective(follow) or not cl or not dec or not linked:
            reason = "follow_up_not_adjudicated_and_bound"
        elif dec.get("verdict") == "insufficient_evidence":
            reason = "follow_up_inconclusive"
        else:
            refs = sorted(set(dec.get("evidence_ids") or ()) & set(cl.get("evidence_ids") or ()))
            link = next(l for l in cl["prior_claim_links"] if l.get("prior_case_id") == case["case_id"] and l.get("prior_claim_id") == record["claim_id"])
            inferred, _ = _infer_graph_outcome(link["relation"], dec["verdict"])
            if record.get("outcome") != "inconclusive" and inferred != record.get("outcome"):
                reason = "reported_outcome_conflicts_with_follow_up"
    else:
        reason = "trigger_is_not_independent_outcome"
    if not reason and (not refs or any((evidence_by_id.get(e) or {}).get("traceability_status") != "verified" for e in refs)):
        reason = "outcome_source_not_verified"
    # A numeric observation must identify a specific original endpoint and be in the source.
    if not reason and record.get("observed_estimate") is not None:
        cl = next((c for c in case.get("claims", ()) if c["id"] == record["claim_id"]), {})
        target = next((r for r in cl.get("effect_records", ()) if r["id"] == record.get("effect_record_id")), None)
        if target is None or target.get("metric") != record.get("metric"):
            reason = "observed_endpoint_not_bound"
        else:
            obs = {"estimate": record["observed_estimate"], "ci_low": record.get("observed_ci_low"), "ci_high": record.get("observed_ci_high")}
            if not any(_record_is_anchored(obs, evidence_by_id[e], evidence_by_id[e].get("source_text"))[0] for e in refs):
                reason = "observed_numbers_not_anchored"
    return {"status": "pending" if reason else "source_verified", "reason": reason,
            "evidence_ids": refs, "scope": "source_identity_and_binding_only; outcome_semantics_caller_reported"}


def validate_calibration_outcome(payload: dict, case: dict, cases_by_id: dict[str, dict], evidence_by_id: dict[str, dict] | None = None) -> dict:
    """Validate an append-only post-adjudication calibration outcome payload."""
    if case.get("state") not in _CALIBRATION_STATES:
        fail("invalid_state", "calibration outcomes can only be recorded after adjudication")

    allowed = {
        "case_id",
        "claim_id",
        "outcome",
        "outcome_score",
        "resolution_source",
        "follow_up_case_id",
        "follow_up_claim_id",
        "evidence_id",
        "observed_estimate",
        "observed_ci_low",
        "observed_ci_high",
        "metric",
        "reason",
        "effect_record_id", "comparison_kind", "comparison_assumption", "estimate_covariance",
        "observed_ci_level", "observed_ci_method",
    }
    required = {"case_id", "claim_id", "outcome", "resolution_source", "reason"}
    fields(payload, allowed, required, "record_calibration_outcome")

    claim_id = string(payload["claim_id"], "claim_id", maximum=200)
    known_claims = {c["id"] for c in case.get("claims", ())}
    if claim_id not in known_claims:
        fail("unknown_claim", f"claim_id '{claim_id}' does not exist in case '{case['case_id']}'")

    outcome = enum(payload["outcome"], CALIBRATION_OUTCOMES, "outcome")
    resolution_source = enum(payload["resolution_source"], CALIBRATION_RESOLUTION_SOURCES, "resolution_source")
    reason = string(payload["reason"], "reason", maximum=4000)
    if not meaningful(reason):
        fail("placeholder_or_empty", "calibration outcome reason must be substantive")

    raw_score = payload.get("outcome_score")
    if outcome == "inconclusive":
        if raw_score is not None:
            fail("invalid_calibration_outcome", "inconclusive outcomes must omit outcome_score or set it to null")
        score: float | None = None
    elif raw_score is None:
        score = DEFAULT_OUTCOME_SCORES[outcome]
    else:
        if type(raw_score) is bool or not isinstance(raw_score, (int, float)) or not math.isfinite(float(raw_score)):
            fail("invalid_calibration_outcome", "outcome_score must be a finite number in [0.0, 1.0]")
        score = float(raw_score)
        if score < 0.0 or score > 1.0:
            fail("invalid_calibration_outcome", "outcome_score must be within [0.0, 1.0]")

    follow_up_case_id = payload.get("follow_up_case_id")
    follow_up_claim_id = payload.get("follow_up_claim_id")
    if resolution_source == "follow_up_case" and follow_up_case_id is None:
        fail("invalid_calibration_outcome", "follow_up_case_id is required when resolution_source is 'follow_up_case'")
    if follow_up_claim_id is not None and follow_up_case_id is None:
        fail("invalid_calibration_outcome", "follow_up_claim_id requires follow_up_case_id")

    record: dict[str, Any] = {
        "claim_id": claim_id,
        "outcome": outcome,
        "outcome_score": score,
        "resolution_source": resolution_source,
        "reason": reason,
        "recorded_at": _now(),
    }

    if follow_up_case_id is not None:
        fu_cid = string(follow_up_case_id, "follow_up_case_id", maximum=200)
        if fu_cid == case["case_id"]:
            fail("invalid_calibration_outcome", "follow_up_case_id cannot point to the same case")
        if fu_cid not in cases_by_id:
            fail("unknown_case", f"follow_up_case_id '{fu_cid}' does not exist in this workspace")
        record["follow_up_case_id"] = fu_cid
        if follow_up_claim_id is not None:
            fu_clmid = string(follow_up_claim_id, "follow_up_claim_id", maximum=200)
            fu_claims = {c["id"] for c in cases_by_id[fu_cid].get("claims", ())}
            if fu_clmid not in fu_claims:
                fail("unknown_prior_claim", f"follow_up_claim_id '{fu_clmid}' does not exist in case '{fu_cid}'")
            record["follow_up_claim_id"] = fu_clmid

    if payload.get("evidence_id") is not None:
        record["evidence_id"] = string(payload["evidence_id"], "evidence_id", maximum=200)
        known = {e["evidence_id"] for c in cases_by_id.values() for e in c.get("evidence", ())}
        if record["evidence_id"] not in known:
            fail("unknown_reference", "calibration evidence_id is not registered in this workspace")

    if payload.get("metric") is not None:
        record["metric"] = enum(payload["metric"], EFFECT_METRICS, "metric")

    has_ci_low = payload.get("observed_ci_low") is not None
    has_ci_high = payload.get("observed_ci_high") is not None
    has_est = payload.get("observed_estimate") is not None
    if has_ci_low or has_ci_high:
        if not (has_ci_low and has_ci_high and has_est):
            fail("invalid_calibration_outcome", "observed_ci_low and observed_ci_high require each other and observed_estimate")
        obs_est = _finite_number(payload["observed_estimate"], "observed_estimate")
        obs_low = _finite_number(payload["observed_ci_low"], "observed_ci_low")
        obs_high = _finite_number(payload["observed_ci_high"], "observed_ci_high")
        if not (obs_low <= obs_est <= obs_high):
            fail("effect_interval_inconsistent", "observed_estimate must fall within [observed_ci_low, observed_ci_high]")
        record["observed_estimate"] = obs_est
        record["observed_ci_low"] = obs_low
        record["observed_ci_high"] = obs_high
    elif has_est:
        record["observed_estimate"] = _finite_number(payload["observed_estimate"], "observed_estimate")

    if payload.get("effect_record_id") is not None:
        record["effect_record_id"] = string(payload["effect_record_id"], "effect_record_id", maximum=200)
        claim = next(c for c in case["claims"] if c["id"] == claim_id)
        target = next((r for r in claim.get("effect_records", ()) if r["id"] == record["effect_record_id"]), None)
        if target is None or record.get("metric") not in (None, target["metric"]):
            fail("invalid_calibration_outcome", "effect_record_id and metric must identify the original endpoint")
    for key, choices in (("comparison_kind", COMPARISON_KINDS), ("comparison_assumption", COMPARISON_ASSUMPTIONS), ("observed_ci_method", INFERENCE_METHODS)):
        if payload.get(key) is not None:
            record[key] = enum(payload[key], choices, key)
    if payload.get("observed_ci_level") is not None:
        level = _finite_number(payload["observed_ci_level"], "observed_ci_level")
        if not 0 < level < 1:
            fail("invalid_value", "observed_ci_level must be between 0 and 1")
        record["observed_ci_level"] = level
    if payload.get("estimate_covariance") is not None:
        record["estimate_covariance"] = _finite_number(payload["estimate_covariance"], "estimate_covariance")
        if record.get("comparison_assumption") != "covariance_supplied":
            fail("invalid_calibration_outcome", "estimate_covariance requires comparison_assumption='covariance_supplied'")
    if record.get("comparison_assumption") == "covariance_supplied" and "estimate_covariance" not in record:
        fail("invalid_calibration_outcome", "covariance_supplied requires estimate_covariance")
    if record.get("comparison_kind") == "known_truth" and (has_ci_low or source_is_followup(record)):
        fail("invalid_calibration_outcome", "known_truth requires an explicit external reference value, not a follow-up estimate/CI")
    if record.get("metric") in RATIO_METRICS or record.get("observed_ci_method") == "log_wald":
        if any(record.get(k) is not None and record[k] <= 0 for k in ("observed_estimate", "observed_ci_low", "observed_ci_high")):
            fail("invalid_ratio_effect", "ratio/log-scale observations must be strictly positive")
    record["source_binding"] = _resolution_binding(record, case, cases_by_id, evidence_by_id or {})

    return record


def source_is_followup(record: dict) -> bool:
    return record.get("resolution_source") != "external_evidence"


def _default_effective_probability(decision: dict) -> float:
    verdict = decision.get("verdict")
    conf = decision.get("confidence", "low")
    base = DEFAULT_CONFIDENCE_PROBABILITIES.get(conf, 0.5)
    if verdict == "unsupported":
        return 1.0 - base
    if verdict == "insufficient_evidence":
        return 0.5
    return base


def _infer_graph_outcome(relation: str, downstream_verdict: str) -> tuple[str, float | None]:
    if relation in ("reverses", "refutes"):
        if downstream_verdict in _POSITIVE_VERDICTS:
            return "refuted", 0.0
        return "inconclusive", None
    if relation == "replicates":
        if downstream_verdict == "supported":
            return "replicated", 1.0
        if downstream_verdict == "partially_supported":
            return "partially_replicated", 0.5
        return "inconclusive", None
    # Refinement/replacement/extension and failed replication are not truth outcomes.
    return "inconclusive", None


def _log_loss(p: float, y: float) -> float:
    eps = 1e-12
    p_clip = min(1.0 - eps, max(eps, p))
    return -(y * math.log(p_clip) + (1.0 - y) * math.log(1.0 - p_clip))


def _mean_or_none(values: list[float], digits: int = 6) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _assign_bin_index(p: float) -> int:
    for idx, (lo, hi) in enumerate(CALIBRATION_BINS):
        if idx == len(CALIBRATION_BINS) - 1:
            if lo <= p <= hi:
                return idx
        elif lo <= p < hi:
            return idx
    return len(CALIBRATION_BINS) - 1


def _downstream_followups_index(cases: list[dict], evidence_by_id: dict[str, dict]) -> dict[tuple[str, str], list[dict]]:
    ordered = sorted(cases, key=lambda c: (c.get("created_at") or "", c["case_id"]))
    by_prior: dict[tuple[str, str], list[dict]] = {}
    for ds_case in ordered:
        ds_id = ds_case["case_id"]
        ds_adj = ds_case.get("adjudication")
        if not adjudication_is_effective(ds_case):
            continue
        dec_map = {d["claim_id"]: d for d in ds_adj.get("decisions", ())}
        for ds_claim in ds_case.get("claims", ()):
            dec = dec_map.get(ds_claim["id"])
            if not dec:
                continue
            refs = set(dec.get("evidence_ids") or ()) & set(ds_claim.get("evidence_ids") or ())
            if not refs or any((evidence_by_id.get(e) or {}).get("traceability_status") != "verified" for e in refs):
                continue
            for lnk in ds_claim.get("prior_claim_links") or ():
                key = (lnk["prior_case_id"], lnk["prior_claim_id"])
                by_prior.setdefault(key, []).append({
                    "follow_up_case_id": ds_id,
                    "follow_up_claim_id": ds_claim["id"],
                    "relation": lnk["relation"],
                    "verdict": dec["verdict"],
                    "effect_records": list(ds_claim.get("effect_records") or ()),
                    "evidence_ids": sorted(refs),
                })
    return by_prior


def _evaluate_interval_for_claim(
    case_id: str,
    claim: dict,
    explicit_outcome: dict | None,
    followups: list[dict],
) -> list[dict]:
    primary_recs = [
        rec
        for rec in (claim.get("effect_records") or ())
        if rec.get("endpoint_role") in PRIMARY_EFFECT_ROLES
        and rec.get("ci_low") is not None
        and rec.get("ci_high") is not None
    ]
    if not primary_recs:
        return []

    evaluated: list[dict] = []
    explicit_obs = explicit_outcome.get("observed_estimate") if explicit_outcome else None
    explicit_metric = explicit_outcome.get("metric") if explicit_outcome else None

    for rec in primary_recs:
        obs_est: float | None = None
        obs_source: str | None = None
        observation = None

        if explicit_obs is not None and explicit_metric == rec.get("metric") and explicit_outcome.get("effect_record_id") == rec["id"]:
            obs_est = float(explicit_obs)
            obs_source = "explicit_outcome"
            observation = explicit_outcome
        else:
            for fu in reversed(followups):
                for fu_rec in fu.get("effect_records") or ():
                    if fu_rec.get("endpoint_role") not in PRIMARY_EFFECT_ROLES:
                        continue
                    if fu_rec.get("metric") != rec.get("metric"):
                        continue
                    if rec.get("endpoint") and fu_rec.get("endpoint") and fu_rec["endpoint"] != rec["endpoint"]:
                        continue
                    obs_est = float(fu_rec["estimate"])
                    obs_source = f"{fu['follow_up_case_id']}:{fu['follow_up_claim_id']}"
                    observation = {"observed_ci_low": fu_rec.get("ci_low"), "observed_ci_high": fu_rec.get("ci_high"), "observed_ci_level": fu_rec.get("ci_level", 0.95), "observed_ci_method": fu_rec.get("inference_method", "unknown"), "comparison_kind": "replication_estimate", "comparison_assumption": "unknown"}
                    break
                if obs_est is not None:
                    break

        if obs_est is None:
            continue

        ci_low = float(rec["ci_low"])
        ci_high = float(rec["ci_high"])
        est = float(rec["estimate"])
        ci_level = float(rec.get("ci_level") if rec.get("ci_level") is not None else 0.95)
        kind = observation.get("comparison_kind", "replication_estimate")
        in_interval = ci_low <= obs_est <= ci_high
        z_difference = None
        comparison_status = "not_applicable" if kind == "known_truth" else "unassessed"
        comparison_reason = None if kind == "known_truth" else "both_wald_methods_and_dependence_assumption_required"
        method = rec.get("inference_method")
        obs_method = observation.get("observed_ci_method")
        assumption = observation.get("comparison_assumption", "unknown")
        obs_low, obs_high = observation.get("observed_ci_low"), observation.get("observed_ci_high")
        if kind == "replication_estimate" and method in ("wald", "log_wald") and obs_method == method and obs_low is not None and obs_high is not None and assumption in ("independent", "covariance_supplied"):
            transform = math.log if method == "log_wald" else float
            values = (est, ci_low, ci_high, obs_est, obs_low, obs_high)
            if method != "log_wald" or all(v > 0 for v in values):
                est_t, low_t, high_t, obs_t, obs_low_t, obs_high_t = map(transform, values)
                obs_level = observation.get("observed_ci_level", 0.95)
                se = (high_t - low_t) / (2 * _norm_ppf((1 + ci_level) / 2))
                obs_se = (obs_high_t - obs_low_t) / (2 * _norm_ppf((1 + obs_level) / 2))
                covariance = 0.0 if assumption == "independent" else observation.get("estimate_covariance")
                if covariance is not None and abs(covariance) <= se * obs_se + 1e-12:
                    variance = se * se + obs_se * obs_se - 2 * covariance
                    if variance > 0:
                        z_difference = round((obs_t - est_t) / math.sqrt(variance), 6)
                        comparison_status, comparison_reason = "computed_under_assumptions", None
                    else:
                        comparison_reason = "nonpositive_difference_variance"
                else:
                    comparison_reason = "invalid_or_missing_covariance"

        evaluated.append({
            "case_id": case_id,
            "claim_id": claim["id"],
            "record_id": rec["id"],
            "metric": rec["metric"],
            "estimate": est,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "ci_level": ci_level,
            "observed_estimate": obs_est,
            "comparison_kind": kind,
            "point_in_original_interval": in_interval,
            "covered": in_interval if kind == "known_truth" else None,
            "observed_ci_low": obs_low,
            "observed_ci_high": obs_high,
            "comparison_assumption": assumption,
            "comparison_status": comparison_status,
            "comparison_reason": comparison_reason,
            "z_difference": z_difference,
            "z_drift": None,
            "source": obs_source,
        })

    return evaluated


def compute_calibration_report(
    cases: list[dict],
    *,
    case_id: str | None = None,
    domain: str | None = None,
    claim_type: str | None = None,
    evidence_by_id: dict[str, dict] | None = None,
) -> dict:
    """Compute longitudinal epistemic calibration metrics across adjudicated claims."""
    cases_by_id = {c["case_id"]: c for c in cases}
    if case_id is not None and case_id not in cases_by_id:
        fail("unknown_case", f"case_id '{case_id}' does not exist in this workspace")

    evidence_by_id = evidence_by_id or {}
    followups_index = _downstream_followups_index(cases, evidence_by_id)
    ordered = sorted(cases, key=lambda c: (c.get("created_at") or "", c["case_id"]))

    claim_records: list[dict] = []
    interval_records: list[dict] = []
    explicit_briers: list[float] = []
    explicit_logs: list[float] = []
    combined_briers: list[float] = []
    combined_logs: list[float] = []

    claims_with_triggers_count = 0
    fired_triggers_resolved_count = 0
    fired_triggers_confirmed_reversal_count = 0

    for c in ordered:
        if case_id is not None and c["case_id"] != case_id:
            continue
        if domain is not None and c.get("domain") != domain:
            continue
        adj = c.get("adjudication")
        if not adjudication_is_effective(c):
            continue

        explicit_by_claim: dict[str, dict] = {}
        for item in c.get("calibration_outcomes") or ():
            if isinstance(item, dict) and item.get("claim_id"):
                explicit_by_claim[item["claim_id"]] = item

        claims_by_id = {cl["id"]: cl for cl in c.get("claims", ())}
        ds_cases = [other for other in ordered if other["case_id"] != c["case_id"]]
        trig_eval = evaluate_case_triggers(c, downstream_cases=ds_cases)
        trig_eval_by_cid = {te["claim_id"]: te for te in trig_eval["claim_evaluations"]}

        for dec in adj.get("decisions", ()):
            cid = dec["claim_id"]
            clm = claims_by_id.get(cid)
            if clm is None:
                continue
            dec_type = dec.get("claim_type") or clm.get("claim_type")
            if claim_type is not None and dec_type != claim_type:
                continue

            explicit_p = dec.get("forecast_probability")
            effective_p = float(explicit_p) if explicit_p is not None else _default_effective_probability(dec)
            explicit_out = explicit_by_claim.get(cid)
            source_binding = _resolution_binding(explicit_out, c, cases_by_id, evidence_by_id) if explicit_out else None
            followups = followups_index.get((c["case_id"], cid), [])

            resolution_mode = "unresolved"
            outcome: str | None = None
            outcome_score: float | None = None
            resolution_source: str | None = None

            if explicit_out is not None:
                resolution_mode = "explicit" if source_binding["status"] == "source_verified" else "reported_unverified"
                outcome = explicit_out["outcome"]
                outcome_score = explicit_out["outcome_score"] if source_binding["status"] == "source_verified" else None
                resolution_source = explicit_out["resolution_source"]
            elif followups:
                latest_fu = followups[-1]
                outcome, outcome_score = _infer_graph_outcome(latest_fu["relation"], latest_fu["verdict"])
                resolution_mode = "graph_inferred"
                resolution_source = "follow_up_case"

            if outcome_score is not None:
                brier = (effective_p - outcome_score) ** 2
                lloss = _log_loss(effective_p, outcome_score)
                combined_briers.append(brier)
                combined_logs.append(lloss)
                if explicit_p is not None and outcome_score in (0.0, 1.0):
                    explicit_briers.append((float(explicit_p) - outcome_score) ** 2)
                    explicit_logs.append(_log_loss(float(explicit_p), outcome_score))

            claims_trigs = collect_claim_triggers(clm, dec)
            te_entry = trig_eval_by_cid.get(cid) or {}
            fired_trigs = [t for t in te_entry.get("triggers", ()) if t.get("fired")]
            if claims_trigs:
                claims_with_triggers_count += 1
                if fired_trigs and outcome_score is not None:
                    fired_triggers_resolved_count += 1
                    expects_refutation = any(
                        t.get("target_verdict") in ("unsupported", "insufficient_evidence")
                        for t in fired_trigs
                    )
                    if (expects_refutation and outcome == "refuted") or (
                        not expects_refutation and outcome in ("refuted", "partially_replicated")
                    ):
                        fired_triggers_confirmed_reversal_count += 1

            interval_records.extend(_evaluate_interval_for_claim(c["case_id"], clm, explicit_out if source_binding and source_binding["status"] == "source_verified" else None, followups if explicit_out is None else []))

            claim_records.append({
                "case_id": c["case_id"],
                "claim_id": cid,
                "domain": c.get("domain"),
                "claim_type": dec_type,
                "evidence_level": dec.get("evidence_level") or dec.get("level") or clm.get("evidence_level") or clm.get("level"),
                "verdict": dec.get("verdict"),
                "confidence": dec.get("confidence"),
                "forecast_probability": explicit_p,
                "effective_probability": round(effective_p, 6),
                "resolution_mode": resolution_mode,
                "resolution_source": resolution_source,
                "source_binding": source_binding,
                "reported_outcome_score": explicit_out.get("outcome_score") if explicit_out else None,
                "probability_basis": "explicit_forecast" if explicit_p is not None else "heuristic_confidence_mapping",
                "outcome": outcome,
                "outcome_score": outcome_score,
                "trigger_count": len(claims_trigs),
                "fired_trigger_ids": [t["id"] for t in fired_trigs],
            })

    resolved_scored = [r for r in claim_records if r["outcome_score"] is not None]
    explicit_scored = [r for r in resolved_scored if r["forecast_probability"] is not None and r["outcome_score"] in (0.0, 1.0)]
    inconclusive_count = sum(1 for r in claim_records if r["outcome"] == "inconclusive")

    # 5 canonical reliability bins
    bins_out: list[dict] = []
    ece_sum = 0.0
    gaps: list[float] = []
    for idx, (lo, hi) in enumerate(CALIBRATION_BINS):
        bucket = [
            r for r in explicit_scored
            if _assign_bin_index(r["effective_probability"]) == idx
        ]
        cnt = len(bucket)
        if cnt > 0:
            mf = sum(r["effective_probability"] for r in bucket) / cnt
            ea = sum(float(r["outcome_score"]) for r in bucket) / cnt
            gap = abs(mf - ea)
            over_gap = max(0.0, mf - ea)
            under_gap = max(0.0, ea - mf)
            ece_sum += (cnt / len(explicit_scored)) * gap
            gaps.append(gap)
            bins_out.append({
                "bin_index": idx,
                "lower": lo,
                "upper": hi,
                "label": f"[{lo:.1f}, {hi:.1f}{']' if idx == 4 else ')'}",
                "count": cnt,
                "mean_forecast": round(mf, 6),
                "empirical_accuracy": round(ea, 6),
                "calibration_gap": round(gap, 6),
                "overconfidence_gap": round(over_gap, 6),
                "underconfidence_gap": round(under_gap, 6),
            })
        else:
            bins_out.append({
                "bin_index": idx,
                "lower": lo,
                "upper": hi,
                "label": f"[{lo:.1f}, {hi:.1f}{']' if idx == 4 else ')'}",
                "count": 0,
                "mean_forecast": None,
                "empirical_accuracy": None,
                "calibration_gap": None,
                "overconfidence_gap": None,
                "underconfidence_gap": None,
            })

    ece = round(ece_sum, 6) if explicit_scored else None
    mce = round(max(gaps), 6) if gaps else None

    confidence_strata: dict[str, dict] = {}
    for conf_level in ("high", "medium", "low"):
        stratum_all = [r for r in claim_records if r["confidence"] == conf_level]
        stratum_res = [r for r in stratum_all if r["outcome_score"] is not None]
        confidence_strata[conf_level] = {
            "scope": "descriptive; explicit forecasts and heuristic mappings are mixed here, not in proper_scores",
            "count": len(stratum_all),
            "resolved_count": len(stratum_res),
            "mean_forecast": _mean_or_none([r["effective_probability"] for r in stratum_res]),
            "empirical_accuracy": _mean_or_none([float(r["outcome_score"]) for r in stratum_res]),
            "brier_score": _mean_or_none(
                [(r["effective_probability"] - float(r["outcome_score"])) ** 2 for r in stratum_res]
            ),
        }

    # Interval calibration
    truth_records = [ir for ir in interval_records if ir["comparison_kind"] == "known_truth"]
    replication_records = [ir for ir in interval_records if ir["comparison_kind"] == "replication_estimate"]
    ev_cnt = len(truth_records)
    cov_cnt = sum(1 for ir in truth_records if ir["covered"])
    emp_cov = round(cov_cnt / ev_cnt, 6) if ev_cnt else None
    nom_cov = _mean_or_none([float(ir["ci_level"]) for ir in truth_records])
    cov_err = round(emp_cov - nom_cov, 6) if (emp_cov is not None and nom_cov is not None) else None
    abs_zs = [abs(float(ir["z_difference"])) for ir in replication_records if ir["z_difference"] is not None]

    # Decision calibration
    res_pos = [r for r in resolved_scored if r["verdict"] in _POSITIVE_VERDICTS]
    res_neg = [r for r in resolved_scored if r["verdict"] == "unsupported"]
    res_part = [r for r in resolved_scored if r["verdict"] == "partially_supported"]
    abstentions = [r for r in claim_records if r["verdict"] == "insufficient_evidence"]

    false_conf_rate = (
        round(sum(1 for r in res_pos if r["outcome"] == "refuted") / len(res_pos), 6)
        if res_pos
        else None
    )
    false_rej_rate = (
        round(sum(1 for r in res_neg if r["outcome"] == "replicated") / len(res_neg), 6)
        if res_neg
        else None
    )
    abstention_rate = (
        round(len(abstentions) / len(claim_records), 6)
        if claim_records
        else None
    )
    part_acc = _mean_or_none([float(r["outcome_score"]) for r in res_part])
    trig_prec = (
        round(fired_triggers_confirmed_reversal_count / fired_triggers_resolved_count, 6)
        if fired_triggers_resolved_count
        else None
    )

    return {
        "filters": {"case_id": case_id, "domain": domain, "claim_type": claim_type},
        "summary": {
            "total_adjudicated_claims": len(claim_records),
            "explicit_forecast_count": sum(1 for r in claim_records if r["forecast_probability"] is not None),
            "resolved_claim_count": len(resolved_scored),
            "explicit_resolved_count": sum(1 for r in resolved_scored if r["resolution_mode"] == "explicit"),
            "graph_inferred_resolved_count": sum(1 for r in resolved_scored if r["resolution_mode"] == "graph_inferred"),
            "inconclusive_outcome_count": inconclusive_count,
            "unresolved_claim_count": sum(1 for r in claim_records if r["resolution_mode"] in ("unresolved", "reported_unverified")),
            "unverified_outcome_count": sum(1 for r in claim_records if r["resolution_mode"] == "reported_unverified"),
            "proper_score_count": len(explicit_scored),
        },
        "proper_scores": {
            "scope": "explicit_forecasts_and_source_verified_binary_outcomes_only",
            "explicit_brier_score": _mean_or_none(explicit_briers),
            "explicit_log_score": _mean_or_none(explicit_logs),
            "combined_brier_score": None,
            "combined_log_score": None,
            "ece": ece,
            "mce": mce,
        },
        "reliability_bins": bins_out,
        "confidence_strata": confidence_strata,
        "heuristic_scores": {
            "scope": "descriptive_confidence_mapping_and_soft_outcomes; not proper forecast calibration",
            "combined_brier_score": _mean_or_none(combined_briers),
            "combined_log_score": _mean_or_none(combined_logs),
        },
        "interval_calibration": {
            "scope": "known_truth_only; replication_point_containment_is_not_nominal_CI_coverage",
            "evaluated_count": ev_cnt,
            "covered_count": cov_cnt,
            "empirical_coverage_rate": emp_cov,
            "nominal_coverage_rate": nom_cov,
            "coverage_error": cov_err,
            "mean_absolute_z_drift": None,
            "replication_count": len(replication_records),
            "replication_point_containment_rate": _mean_or_none([float(ir["point_in_original_interval"]) for ir in replication_records]),
            "mean_absolute_z_difference": _mean_or_none(abs_zs),
            "records": interval_records,
        },
        "decision_calibration": {
            "false_confirmation_rate": false_conf_rate,
            "false_rejection_rate": false_rej_rate,
            "abstention_rate": abstention_rate,
            "partially_supported_accuracy": part_acc,
            "trigger_calibration": {
                "claims_with_triggers_count": claims_with_triggers_count,
                "fired_triggers_resolved_count": fired_triggers_resolved_count,
                "fired_triggers_confirmed_reversal_count": fired_triggers_confirmed_reversal_count,
                "trigger_precision": trig_prec,
            },
        },
        "claim_records": claim_records,
    }
