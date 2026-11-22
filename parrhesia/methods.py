"""Proactive computable scientific methodology co-pilot (pure stdlib + optional SciPy).

Provides deterministic pre-study, mid-study, and case-bound statistical/methodological
calculations that help Agents design discriminating tests, avoid underpowered null claims,
quantify confounding/attrition sensitivity, detect multiplicity & subgroup illusions,
evaluate clinical net benefit, flag pseudoreplication, and resist false balance:

  1. power_mde                 - Power, required N, and Minimum Detectable Effect (MDE)
  2. tost_equivalence          - Two One-Sided Tests (TOST) separating equivalence from underpowered null
  3. e_value                   - VanderWeele & Ding (2017) E-value confounding sensitivity
  4. pseudoreplication_audit   - Unit-of-analysis / Design Effect (DEFF) & effective sample size
  5. evidence_dominance        - Structured anti-false-balance comparison of competing explanations
  6. multiplicity_audit        - Bonferroni, Sidak, Holm-Bonferroni (FWER), and BH-FDR with fork inflation
  7. interaction_heterogeneity - Direct subgroup interaction test (Gelman-Stern) & DerSimonian-Laird meta-analysis
  8. prediction_utility_audit  - EPV / heuristic shrinkage adequacy & Vickers Decision-Curve Net Benefit
  9. attrition_bounds          - Manski worst-case bounds & tipping-point missing-data sensitivity
 10. case_audit                - Proactive live-case / exploration methodology audit & next-action planner
"""
from __future__ import annotations

import math
from typing import Any, Callable

from .backends import available_backends
from .contracts import array, enum, fail, fields, obj, string
from .effects import _norm_ppf, _two_sided_t_p

DESIGN_ANALYSIS_MODES = (
    "power_mde",
    "tost_equivalence",
    "e_value",
    "pseudoreplication_audit",
    "evidence_dominance",
    "multiplicity_audit",
    "interaction_heterogeneity",
    "prediction_utility_audit",
    "attrition_bounds",
    "case_audit",
    "lineage_synthesis",
)

_POWER_DESIGNS = ("two_sample_mean", "two_proportion", "log_hr_events")
_EVALUE_METRICS = ("RR", "HR", "OR", "SMD")
_DESIGN_TIER_WEIGHTS = {
    "randomized": 5,
    "quasi_experimental": 4,
    "mechanistic_intervention": 4,
    "prediction_prospective": 4,
    "prediction_external": 3,
    "observational_sensitivity": 3,
    "observational_adjusted": 2,
    "observational_unadjusted": 1,
    "benchmark_external": 3,
    "benchmark_reproduced": 2,
    "benchmark_single": 1,
    "mechanistic_compatible": 1,
    "synthetic_or_conjecture": 0,
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("invalid_type", f"{name} must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        fail("invalid_value", f"{name} must be finite")
    return num


def _positive(value: Any, name: str) -> float:
    num = _finite(value, name)
    if num <= 0.0:
        fail("invalid_value", f"{name} must be > 0")
    return num


def _prob(value: Any, name: str, *, strict_open: bool = True) -> float:
    num = _finite(value, name)
    ok = (0.0 < num < 1.0) if strict_open else (0.0 <= num <= 1.0)
    if not ok:
        fail("invalid_value", f"{name} must be in {'(0, 1)' if strict_open else '[0, 1]'}")
    return num


def _norm_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def _one_sided_t_p(t_stat: float, df: int, *, upper: bool) -> float:
    """Upper-tail P(T >= t_stat) or lower-tail P(T <= t_stat) for Student-t(df)."""
    two_sided = _two_sided_t_p(abs(t_stat), df)
    half = 0.5 * two_sided
    if upper:
        return half if t_stat >= 0.0 else 1.0 - half
    return half if t_stat <= 0.0 else 1.0 - half


def _t_ppf(prob: float, df: int) -> float:
    if not (0.0 < prob < 1.0):
        fail("invalid_value", "probability must lie in (0, 1)")
    if prob == 0.5:
        return 0.0
    sign = 1.0 if prob > 0.5 else -1.0
    target_upper = 1.0 - prob if prob > 0.5 else prob
    lo, hi = 0.0, 2.0
    while _one_sided_t_p(hi, df, upper=True) > target_upper and hi < 1e6:
        hi *= 2.0
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        if _one_sided_t_p(mid, df, upper=True) > target_upper:
            lo = mid
        else:
            hi = mid
    return sign * 0.5 * (lo + hi)


def _compute_power_mde(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "mode", "design", "alpha", "target_power", "allocation_ratio",
        "n_per_group", "total_events", "effect_size", "sd",
        "baseline_rate", "treatment_rate", "hazard_ratio",
    }
    fields(payload, allowed, {"mode", "design"}, "analyze_design.power_mde")
    design = enum(payload["design"], _POWER_DESIGNS, "design")
    alpha = _prob(payload.get("alpha", 0.05), "alpha")
    target_power = _prob(payload.get("target_power", 0.80), "target_power")
    ratio = _positive(payload.get("allocation_ratio", 1.0), "allocation_ratio")
    z_alpha = _norm_ppf(1.0 - alpha / 2.0)
    z_beta = _norm_ppf(target_power)
    out: dict[str, Any] = {
        "mode": "power_mde",
        "design": design,
        "alpha": alpha,
        "target_power": target_power,
        "allocation_ratio": ratio,
        "approximation": "two_sided_normal_asymptotic",
    }

    if design == "two_sample_mean":
        sd = _positive(payload.get("sd", 1.0), "sd")
        n1 = _positive(payload["n_per_group"], "n_per_group") if "n_per_group" in payload else None
        delta = abs(_finite(payload["effect_size"], "effect_size")) if "effect_size" in payload else None
        if n1 is None and (delta is None or delta == 0.0):
            fail("missing_field", "two_sample_mean requires n_per_group and/or nonzero effect_size")
        var_factor = 1.0 + 1.0 / ratio
        if n1 is not None:
            se = sd * math.sqrt(var_factor / n1)
            mde = (z_alpha + z_beta) * se
            out["n_group1"] = n1
            out["n_group2"] = round(n1 * ratio, 4)
            out["se_difference"] = round(se, 6)
            out["mde_raw"] = round(mde, 6)
            out["mde_cohens_d"] = round(mde / sd, 6)
            if delta is not None:
                ncp = delta / se
                power = _norm_cdf(ncp - z_alpha) + _norm_cdf(-ncp - z_alpha)
                out["achieved_power"] = round(min(1.0, max(0.0, power)), 6)
                out["underpowered"] = power < target_power
        if delta is not None and delta > 0.0:
            req_n1 = math.ceil(var_factor * ((z_alpha + z_beta) * sd / delta) ** 2)
            req_n2 = math.ceil(req_n1 * ratio)
            out["required_n_group1"] = req_n1
            out["required_n_group2"] = req_n2
            out["required_total_n"] = req_n1 + req_n2
            out["cohens_d"] = round(delta / sd, 6)
        guidance = []
        if out.get("underpowered"):
            guidance.append(
                f"Underpowered ({out['achieved_power']:.2%} < {target_power:.0%}): a non-significant result "
                f"cannot distinguish null from effects smaller than MDE={out['mde_raw']:.4g} (d={out['mde_cohens_d']:.3g})."
            )
        elif "mde_raw" in out:
            guidance.append(
                f"At N={out['n_group1']:g}/{out['n_group2']:g}, {target_power:.0%} power detects |delta| >= {out['mde_raw']:.4g} (d >= {out['mde_cohens_d']:.3g})."
            )
        out["guidance"] = guidance
        return out

    if design == "two_proportion":
        p0 = _prob(payload["baseline_rate"], "baseline_rate")
        p1 = _prob(payload["treatment_rate"], "treatment_rate") if "treatment_rate" in payload else None
        n1 = _positive(payload["n_per_group"], "n_per_group") if "n_per_group" in payload else None
        if p1 is None and n1 is None:
            fail("missing_field", "two_proportion requires treatment_rate and/or n_per_group")
        out["baseline_rate"] = p0
        if p1 is not None:
            rd = abs(p1 - p0)
            out["treatment_rate"] = p1
            out["risk_difference"] = round(p1 - p0, 6)
            pbar = (p0 + ratio * p1) / (1.0 + ratio)
            if rd > 0.0:
                num = (
                    z_alpha * math.sqrt(pbar * (1.0 - pbar) * (1.0 + 1.0 / ratio))
                    + z_beta * math.sqrt(p0 * (1.0 - p0) + p1 * (1.0 - p1) / ratio)
                )
                req_n1 = math.ceil((num / rd) ** 2)
                req_n2 = math.ceil(req_n1 * ratio)
                out["required_n_group1"] = req_n1
                out["required_n_group2"] = req_n2
                out["required_total_n"] = req_n1 + req_n2
            if n1 is not None:
                se_alt = math.sqrt(p0 * (1.0 - p0) / n1 + p1 * (1.0 - p1) / (n1 * ratio))
                se_null = math.sqrt(pbar * (1.0 - pbar) * (1.0 / n1 + 1.0 / (n1 * ratio)))
                z_crit = z_alpha * se_null
                power = _norm_cdf((rd - z_crit) / se_alt) + _norm_cdf((-rd - z_crit) / se_alt)
                out["achieved_power"] = round(min(1.0, max(0.0, power)), 6)
                out["underpowered"] = power < target_power
        if n1 is not None:
            # Conservative local MDE around baseline_rate
            se0 = math.sqrt(p0 * (1.0 - p0) * (1.0 + 1.0 / ratio) / n1)
            out["n_group1"] = n1
            out["n_group2"] = round(n1 * ratio, 4)
            out["approx_mde_risk_diff"] = round((z_alpha + z_beta) * se0, 6)
        return out

    # log_hr_events (Schoenfeld formula)
    prop_treated = ratio / (1.0 + ratio)
    pq = prop_treated * (1.0 - prop_treated)
    events = _positive(payload["total_events"], "total_events") if "total_events" in payload else None
    hr = _positive(payload["hazard_ratio"], "hazard_ratio") if "hazard_ratio" in payload else None
    if events is None and (hr is None or abs(math.log(hr)) < 1e-12):
        fail("missing_field", "log_hr_events requires total_events and/or hazard_ratio != 1.0")
    if events is not None:
        se_log_hr = 1.0 / math.sqrt(events * pq)
        mde_log_hr = (z_alpha + z_beta) * se_log_hr
        out["total_events"] = events
        out["mde_hr_below_null"] = round(math.exp(-mde_log_hr), 6)
        out["mde_hr_above_null"] = round(math.exp(mde_log_hr), 6)
        if hr is not None:
            ncp = abs(math.log(hr)) / se_log_hr
            power = _norm_cdf(ncp - z_alpha) + _norm_cdf(-ncp - z_alpha)
            out["achieved_power"] = round(min(1.0, max(0.0, power)), 6)
            out["underpowered"] = power < target_power
    if hr is not None and abs(math.log(hr)) > 1e-12:
        req_events = math.ceil(((z_alpha + z_beta) ** 2) / (pq * (math.log(hr) ** 2)))
        out["hazard_ratio"] = hr
        out["required_total_events"] = req_events
    return out


def _compute_tost(payload: dict[str, Any]) -> dict[str, Any]:
    """Two One-Sided Tests (TOST) distinguishing equivalence from underpowered null."""
    allowed = {
        "mode", "estimate", "se", "ci_low", "ci_high", "ci_level",
        "equiv_low", "equiv_high", "alpha", "df", "null_value", "scale",
    }
    fields(payload, allowed, {"mode", "estimate", "equiv_low", "equiv_high"}, "analyze_design.tost_equivalence")
    est = _finite(payload["estimate"], "estimate")
    eq_lo = _finite(payload["equiv_low"], "equiv_low")
    eq_hi = _finite(payload["equiv_high"], "equiv_high")
    if not (eq_lo < eq_hi):
        fail("invalid_value", "equiv_low must be strictly less than equiv_high")
    alpha = _prob(payload.get("alpha", 0.05), "alpha")
    scale = enum(payload.get("scale", "linear"), ("linear", "log"), "scale")
    null_val = _finite(payload.get("null_value", 1.0 if scale == "log" else 0.0), "null_value")
    df = None
    if "df" in payload and payload["df"] is not None:
        if isinstance(payload["df"], bool) or not isinstance(payload["df"], int) or payload["df"] < 1:
            fail("invalid_value", "df must be a positive integer")
        df = payload["df"]

    def _xform(v: float, name: str) -> float:
        if scale == "log":
            if v <= 0.0:
                fail("invalid_value", f"{name} must be > 0 when scale='log'")
            return math.log(v)
        return v

    x_est = _xform(est, "estimate")
    x_lo = _xform(eq_lo, "equiv_low")
    x_hi = _xform(eq_hi, "equiv_high")
    x_null = _xform(null_val, "null_value")

    if "se" in payload and payload["se"] is not None:
        se = _positive(payload["se"], "se")
    elif "ci_low" in payload and "ci_high" in payload:
        ci_lo = _xform(_finite(payload["ci_low"], "ci_low"), "ci_low")
        ci_hi = _xform(_finite(payload["ci_high"], "ci_high"), "ci_high")
        if ci_hi <= ci_lo:
            fail("invalid_value", "ci_high must exceed ci_low")
        ci_level = _prob(payload.get("ci_level", 0.95), "ci_level")
        crit = _t_ppf(0.5 + ci_level / 2.0, df) if df is not None else _norm_ppf(0.5 + ci_level / 2.0)
        se = (ci_hi - ci_lo) / (2.0 * crit)
    else:
        fail("missing_field", "tost_equivalence requires either se or both ci_low and ci_high")

    t_low = (x_est - x_lo) / se   # H01: theta <= eq_lo (upper-tail test)
    t_high = (x_est - x_hi) / se  # H02: theta >= eq_hi (lower-tail test)
    t_null = (x_est - x_null) / se

    if df is not None:
        p_low = _one_sided_t_p(t_low, df, upper=True)
        p_high = _one_sided_t_p(t_high, df, upper=False)
        p_null = _two_sided_t_p(abs(t_null), df)
        crit_tost = _t_ppf(1.0 - alpha, df)
    else:
        p_low = 1.0 - _norm_cdf(t_low)
        p_high = _norm_cdf(t_high)
        p_null = math.erfc(abs(t_null) / math.sqrt(2.0))
        crit_tost = _norm_ppf(1.0 - alpha)

    p_tost = max(p_low, p_high)
    tost_ci_low = x_est - crit_tost * se
    tost_ci_high = x_est + crit_tost * se
    if scale == "log":
        tost_ci_low = math.exp(tost_ci_low)
        tost_ci_high = math.exp(tost_ci_high)

    equivalent = p_tost < alpha
    different = p_null < alpha
    if equivalent and not different:
        classification = "equivalent_supported"
        guidance = (
            f"TOST establishes equivalence within [{eq_lo:g}, {eq_hi:g}] (p_TOST={p_tost:.4g} < {alpha:g}); "
            f"the {(1 - 2 * alpha) * 100:.0f}% CI [{tost_ci_low:.4g}, {tost_ci_high:.4g}] lies strictly inside bounds."
        )
    elif equivalent and different:
        classification = "statistically_different_yet_practically_equivalent"
        guidance = (
            f"Effect differs statistically from null (p={p_null:.4g}) yet lies strictly within practical "
            f"equivalence bounds [{eq_lo:g}, {eq_hi:g}] (p_TOST={p_tost:.4g})."
        )
    elif different and not equivalent:
        classification = "difference_supported"
        guidance = (
            f"Null hypothesis rejected (p={p_null:.4g} < {alpha:g}); equivalence not established (p_TOST={p_tost:.4g})."
        )
    else:
        classification = "underpowered_inconclusive"
        guidance = (
            f"Neither difference from null (p={p_null:.4g}) nor equivalence within [{eq_lo:g}, {eq_hi:g}] "
            f"(p_TOST={p_tost:.4g}) is established. Do NOT claim 'no effect' or 'equivalent'; verdict should remain insufficient_evidence."
        )

    return {
        "mode": "tost_equivalence",
        "scale": scale,
        "alpha": alpha,
        "df": df,
        "se_working_scale": round(se, 6),
        "tost_ci_level": round(1.0 - 2.0 * alpha, 6),
        "tost_ci_low": round(tost_ci_low, 6),
        "tost_ci_high": round(tost_ci_high, 6),
        "p_lower_bound": round(p_low, 8),
        "p_upper_bound": round(p_high, 8),
        "p_tost": round(p_tost, 8),
        "p_null_two_sided": round(p_null, 8),
        "equivalent": equivalent,
        "different_from_null": different,
        "classification": classification,
        "guidance": guidance,
    }


def _rr_evalue(rr: float) -> float:
    if rr <= 1.0:
        return 1.0
    return rr + math.sqrt(rr * (rr - 1.0))


def _compute_evalue(payload: dict[str, Any]) -> dict[str, Any]:
    """VanderWeele & Ding (2017) E-value for observational unmeasured confounding."""
    allowed = {"mode", "metric", "estimate", "ci_low", "ci_high", "rare_outcome", "sd"}
    fields(payload, allowed, {"mode", "metric", "estimate"}, "analyze_design.e_value")
    metric = enum(payload["metric"], _EVALUE_METRICS, "metric")
    est = _finite(payload["estimate"], "estimate")
    rare = payload.get("rare_outcome", True)
    if type(rare) is not bool:
        fail("invalid_type", "rare_outcome must be a boolean")

    def to_rr_scale(val: float) -> float:
        if metric == "RR":
            if val <= 0.0:
                fail("invalid_value", "RR must be > 0")
            return val if val >= 1.0 else 1.0 / val
        if metric == "OR":
            if val <= 0.0:
                fail("invalid_value", "OR must be > 0")
            rr_eq = val if rare else math.sqrt(val)
            return rr_eq if rr_eq >= 1.0 else 1.0 / rr_eq
        if metric == "HR":
            if val <= 0.0:
                fail("invalid_value", "HR must be > 0")
            if rare:
                rr_eq = val
            else:
                # VanderWeele & Ding (2017) common-outcome HR approximation: (1 - 0.5^sqrt(HR)) / (1 - 0.5^sqrt(1/HR))
                rr_eq = (1.0 - 0.5 ** math.sqrt(val)) / (1.0 - 0.5 ** math.sqrt(1.0 / val))
            return rr_eq if rr_eq >= 1.0 else 1.0 / rr_eq
        # SMD / Cohen's d -> Chinn (2000) / VanderWeele (2017): RR ~= exp(0.91 * |d|)
        return math.exp(0.91 * abs(val))

    rr_point = to_rr_scale(est)
    e_point = _rr_evalue(rr_point)
    e_ci: float | None = None
    ci_crosses_null = False
    if "ci_low" in payload or "ci_high" in payload:
        if "ci_low" not in payload or "ci_high" not in payload:
            fail("missing_field", "Provide both ci_low and ci_high when computing CI E-value")
        lo = _finite(payload["ci_low"], "ci_low")
        hi = _finite(payload["ci_high"], "ci_high")
        if lo > hi:
            fail("invalid_value", "ci_low must be <= ci_high")
        null_val = 0.0 if metric == "SMD" else 1.0
        if lo <= null_val <= hi:
            ci_crosses_null = True
            e_ci = 1.0
        else:
            closest = lo if est > null_val else hi
            e_ci = _rr_evalue(to_rr_scale(closest))

    if e_point < 1.5 or (e_ci is not None and e_ci < 1.25):
        band = "fragile_to_weak_confounding"
    elif e_point < 2.5 or (e_ci is not None and e_ci < 1.5):
        band = "moderate_confounding_robustness"
    else:
        band = "robust_against_moderate_confounding"

    ci_note = f", CI-limit E-value = {e_ci:.2f}" if e_ci is not None else ""
    return {
        "mode": "e_value",
        "metric": metric,
        "rare_outcome": rare,
        "rr_equivalent": round(rr_point, 6),
        "e_value_point": round(e_point, 4),
        "e_value_ci": round(e_ci, 4) if e_ci is not None else None,
        "ci_crosses_null": ci_crosses_null,
        "robustness_band": band,
        "suggested_causal_sensitivity_reason": (
            f"VanderWeele-Ding E-value = {e_point:.2f}{ci_note} ({metric}={est:g}, rare_outcome={rare}); "
            f"an unmeasured confounder would need RR >= {e_point:.2f} with both exposure and outcome "
            "beyond measured covariates to fully explain away the point estimate."
        ),
    }


def _compute_pseudoreplication(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit unit-of-analysis mismatch, Design Effect (DEFF), and effective sample size."""
    allowed = {
        "mode", "experimental_unit", "observation_unit",
        "n_clusters", "n_observations", "icc", "clustered_inference",
    }
    fields(
        payload,
        allowed,
        {"mode", "experimental_unit", "observation_unit", "n_clusters", "n_observations", "clustered_inference"},
        "analyze_design.pseudoreplication_audit",
    )
    exp_unit = string(payload["experimental_unit"], "experimental_unit", maximum=120)
    obs_unit = string(payload["observation_unit"], "observation_unit", maximum=120)
    n_clusters = _positive(payload["n_clusters"], "n_clusters")
    n_obs = _positive(payload["n_observations"], "n_observations")
    if n_obs < n_clusters:
        fail("invalid_value", "n_observations must be >= n_clusters")
    clustered = payload["clustered_inference"]
    if type(clustered) is not bool:
        fail("invalid_type", "clustered_inference must be a boolean")
    icc = _prob(payload.get("icc", 0.05), "icc", strict_open=False)

    mean_cluster_size = n_obs / n_clusters
    deff = 1.0 + max(0.0, mean_cluster_size - 1.0) * icc
    n_eff = n_obs / deff
    se_inflation = math.sqrt(deff)
    unit_mismatch = exp_unit.strip().casefold() != obs_unit.strip().casefold() and mean_cluster_size > 1.0
    pseudoreplication_risk = (
        "high" if (unit_mismatch and not clustered and (mean_cluster_size >= 5.0 or deff >= 2.0))
        else "moderate" if (unit_mismatch and not clustered)
        else "controlled"
    )
    return {
        "mode": "pseudoreplication_audit",
        "experimental_unit": exp_unit,
        "observation_unit": obs_unit,
        "n_clusters": n_clusters,
        "n_observations": n_obs,
        "mean_cluster_size": round(mean_cluster_size, 4),
        "assumed_icc": icc,
        "clustered_inference": clustered,
        "design_effect": round(deff, 4),
        "effective_sample_size": round(n_eff, 2),
        "naive_se_underestimation_factor": round(se_inflation, 4),
        "unit_mismatch": unit_mismatch,
        "pseudoreplication_risk": pseudoreplication_risk,
        "recommended_unit_check_status": "fail" if pseudoreplication_risk == "high" else "unknown" if pseudoreplication_risk == "moderate" else "pass",
        "guidance": (
            f"Pseudoreplication detected: {n_obs:g} {obs_unit} nested in {n_clusters:g} independent {exp_unit} "
            f"(mean {mean_cluster_size:.1f}/unit) analyzed without cluster/mixed/pseudobulk inference. "
            f"At ICC={icc:g}, DEFF={deff:.2f}, N_eff={n_eff:.1f}, naive SE is underestimated by {se_inflation:.2f}x."
            if pseudoreplication_risk != "controlled"
            else f"Clustered/hierarchical inference accounts for {n_clusters:g} independent {exp_unit} (N_eff={n_eff:.1f} at ICC={icc:g})."
        ),
    }


def _compute_evidence_dominance(payload: dict[str, Any]) -> dict[str, Any]:
    """Compare competing explanations quantitatively to prevent hollow-neutrality false balance."""
    fields(payload, {"mode", "hypotheses"}, {"mode", "hypotheses"}, "analyze_design.evidence_dominance")
    hyps = array(payload["hypotheses"], "hypotheses", minimum=2, maximum=5)
    scored: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(hyps):
        obj(item, f"hypotheses[{idx}]")
        fields(
            item,
            {
                "id", "statement", "design_tier", "independent_units",
                "fatal_flaws", "contradicting_evidence_count", "direct_test_passed",
            },
            {"id", "statement", "design_tier", "independent_units", "fatal_flaws"},
            f"hypotheses[{idx}]",
        )
        hid = string(item["id"], f"hypotheses[{idx}].id", maximum=100)
        if hid in seen_ids:
            fail("duplicate_id", f"Duplicate hypothesis id '{hid}'")
        seen_ids.add(hid)
        stmt = string(item["statement"], f"hypotheses[{idx}].statement")
        tier = enum(item["design_tier"], tuple(_DESIGN_TIER_WEIGHTS), f"hypotheses[{idx}].design_tier")
        units = item["independent_units"]
        flaws = item["fatal_flaws"]
        contras = item.get("contradicting_evidence_count", 0)
        direct_ok = item.get("direct_test_passed", False)
        for nm, v in (("independent_units", units), ("fatal_flaws", flaws), ("contradicting_evidence_count", contras)):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                fail("invalid_value", f"hypotheses[{idx}].{nm} must be a non-negative integer")
        if type(direct_ok) is not bool:
            fail("invalid_type", f"hypotheses[{idx}].direct_test_passed must be a boolean")
        tier_score = _DESIGN_TIER_WEIGHTS[tier]
        # Design metadata can rank observed evidence, but does not substitute for it.
        score = 0 if units == 0 else (
            tier_score * 10
            + (6 if direct_ok else 0)
            + min(units, 20)
            - flaws * 12
            - contras * 8
        )
        scored.append({
            "id": hid,
            "statement": stmt,
            "design_tier": tier,
            "tier_weight": tier_score,
            "independent_units": units,
            "fatal_flaws": flaws,
            "contradicting_evidence_count": contras,
            "direct_test_passed": direct_ok,
            "evidence_weight_score": score,
        })

    ranked = sorted(scored, key=lambda r: (r["evidence_weight_score"], r["tier_weight"], -r["fatal_flaws"]), reverse=True)
    top, runner_up = ranked[0], ranked[1]
    margin = top["evidence_weight_score"] - runner_up["evidence_weight_score"]

    if top["independent_units"] == 0 or not top["direct_test_passed"]:
        status = "genuinely_unresolved"
        anti_neutrality_directive = (
            "No supported lead is established by the supplied comparison. Provide observed independent units "
            "and a direct test distinguishing the leading explanation from its rival."
        )
    elif top["tier_weight"] == 0 or (top["fatal_flaws"] > 0 and top["fatal_flaws"] >= runner_up["fatal_flaws"]):
        status = "genuinely_unresolved"
        anti_neutrality_directive = (
            "No explanation has flaw-free empirical dominance; an explicit 'insufficient_evidence' verdict "
            "with a concrete discriminating experiment is warranted."
        )
    elif margin >= 15 and top["fatal_flaws"] == 0 and (top["tier_weight"] > runner_up["tier_weight"] or runner_up["fatal_flaws"] > 0 or runner_up["contradicting_evidence_count"] > 0):
        status = "dominant"
        anti_neutrality_directive = (
            f"The reported evidence favors '{top['id']}' over '{runner_up['id']}' "
            f"(margin={margin}, tier={top['design_tier']} vs {runner_up['design_tier']}). "
            "State the result within the tested comparison and retain limits for untested questions."
        )
    elif margin >= 8 and top["fatal_flaws"] == 0:
        status = "conditionally_dominant"
        anti_neutrality_directive = (
            f"'{top['id']}' holds conditional advantage over '{runner_up['id']}' (margin={margin}); "
            "state why it is currently favored and name the single test that would flip to the rival."
        )
    else:
        status = "balanced_unresolved"
        anti_neutrality_directive = (
            f"Evidence between '{top['id']}' and '{runner_up['id']}' is closely balanced (margin={margin}); "
            "do not force a winner—issue explicit 'insufficient_evidence' plus a discriminating experiment."
        )

    return {
        "mode": "evidence_dominance",
        "asymmetry_status": status,
        "favored_hypothesis_id": top["id"] if status in ("dominant", "conditionally_dominant") else None,
        "strongest_rival_id": runner_up["id"],
        "weight_margin": margin,
        "ranked_hypotheses": ranked,
        "anti_neutrality_directive": anti_neutrality_directive,
    }


def _gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) = Gamma(a, x) / Gamma(a) (Numerical Recipes §6.2)."""
    if a <= 0.0:
        fail("invalid_value", "gamma shape parameter must be > 0")
    if x <= 0.0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        # Series representation for P(a, x), then Q = 1 - P.
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(400):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) <= abs(total) * 1e-14:
                break
        p_val = total * math.exp(-x + a * math.log(x) - gln)
        return min(1.0, max(0.0, 1.0 - p_val))
    # Modified Lentz continued fraction for Q(a, x).
    fpmin = 1e-300
    b = x + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b if abs(b) > fpmin else 1.0 / fpmin
    h = d
    for i in range(1, 400):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) <= 1e-14:
            break
    q_val = math.exp(-x + a * math.log(x) - gln) * h
    return min(1.0, max(0.0, q_val))


def _chi2_sf(x: float, df: int) -> float:
    """Exact upper-tail chi-square p-value P(Chi2_df >= x)."""
    if df < 1:
        fail("invalid_value", "chi-square df must be >= 1")
    if x <= 0.0:
        return 1.0
    if df == 1:
        return math.erfc(math.sqrt(x / 2.0))
    if df == 2:
        return math.exp(-x / 2.0)
    return _gamma_q(df / 2.0, x / 2.0)


def _nonneg_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        fail("invalid_value", f"{name} must be a non-negative integer")
    return value


def _pos_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        fail("invalid_value", f"{name} must be a positive integer")
    return value


def _compute_multiplicity_audit(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute Bonferroni, Sidak, Holm-Bonferroni (FWER), and Benjamini-Hochberg (FDR) adjustments."""
    allowed = {"mode", "p_values", "alpha", "prior_exploratory_forks", "family_size"}
    fields(payload, allowed, {"mode", "p_values"}, "analyze_design.multiplicity_audit")
    alpha = _prob(payload.get("alpha", 0.05), "alpha")
    prior_forks = _nonneg_int(payload.get("prior_exploratory_forks", 0), "prior_exploratory_forks")
    raw_items = array(payload["p_values"], "p_values", minimum=1, maximum=200)

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(raw_items):
        if isinstance(entry, (int, float)) and not isinstance(entry, bool):
            p = _prob(entry, f"p_values[{idx}]", strict_open=False)
            cid = f"test_{idx + 1}"
            role = "unspecified"
        else:
            rec = obj(entry, f"p_values[{idx}]")
            fields(rec, {"id", "p_value", "role"}, {"id", "p_value"}, f"p_values[{idx}]")
            cid = string(rec["id"], f"p_values[{idx}].id", maximum=120)
            p = _prob(rec["p_value"], f"p_values[{idx}].p_value", strict_open=False)
            role = enum(
                rec.get("role", "unspecified"),
                ("primary", "secondary", "subgroup", "exploratory", "unspecified"),
                f"p_values[{idx}].role",
            )
        if cid in seen_ids:
            fail("duplicate_id", f"Duplicate p_values id '{cid}'")
        seen_ids.add(cid)
        items.append({"id": cid, "p_value": p, "role": role})

    k = len(items)
    if "family_size" in payload and payload["family_size"] is not None:
        m = _pos_int(payload["family_size"], "family_size")
        if m < k:
            fail("invalid_value", f"family_size ({m}) cannot be smaller than submitted p_values count ({k})")
    else:
        m = max(k, k + prior_forks)

    # Sort ascending by raw p_value for step-down Holm and step-up BH.
    order = sorted(range(k), key=lambda i: (items[i]["p_value"], i))
    holm_adj = [0.0] * k
    running_max = 0.0
    for rank_idx, orig_idx in enumerate(order):
        mult = max(1, m - rank_idx)
        val = min(1.0, items[orig_idx]["p_value"] * mult)
        running_max = max(running_max, val)
        holm_adj[orig_idx] = running_max

    bh_adj = [0.0] * k
    running_min = 1.0
    for rank_pos in range(k, 0, -1):
        orig_idx = order[rank_pos - 1]
        val = min(1.0, items[orig_idx]["p_value"] * (m / rank_pos))
        running_min = min(running_min, val)
        bh_adj[orig_idx] = running_min

    adjusted_rows: list[dict[str, Any]] = []
    nominal_sig = 0
    fwer_sig = 0
    fdr_sig = 0
    for idx, item in enumerate(items):
        p = item["p_value"]
        bonf = min(1.0, p * m)
        sidak = 1.0 if p >= 1.0 else (0.0 if p <= 0.0 else min(1.0, max(0.0, -math.expm1(m * math.log1p(-p)))))
        holm = holm_adj[idx]
        bh = bh_adj[idx]
        is_nom = p < alpha
        is_fwer = holm < alpha
        is_fdr = bh < alpha
        if is_nom:
            nominal_sig += 1
        if is_fwer:
            fwer_sig += 1
        if is_fdr:
            fdr_sig += 1
        if is_fwer:
            status = "survives_fwer"
        elif is_fdr:
            status = "survives_fdr_only"
        elif is_nom:
            status = "fails_multiplicity"
        else:
            status = "not_nominally_significant"
        adjusted_rows.append({
            "id": item["id"],
            "role": item["role"],
            "raw_p": round(p, 8),
            "bonferroni_p": round(bonf, 8),
            "sidak_p": round(sidak, 8),
            "holm_p": round(holm, 8),
            "bh_fdr_q": round(bh, 8),
            "status": status,
        })

    global_null_fwer = min(1.0, max(0.0, -math.expm1(m * math.log1p(-alpha))))
    bonf_threshold = alpha / m
    sidak_threshold = 1.0 - (1.0 - alpha) ** (1.0 / m)
    cherry_picking_risk = bool(nominal_sig > 0 and fwer_sig == 0 and (m >= 4 or prior_forks > 0))
    eroded_ids = [r["id"] for r in adjusted_rows if r["status"] == "fails_multiplicity"]

    if cherry_picking_risk:
        guidance = (
            f"Multiplicity erosion detected: {nominal_sig}/{k} test(s) are nominally p < {alpha:g}, "
            f"but 0 survive Holm-Bonferroni FWER across effective family M={m} "
            f"(global-null FWER={global_null_fwer:.1%}, Bonferroni cutoff={bonf_threshold:.4g}). "
            "Do NOT claim confirmatory significance without independent replication."
        )
    elif fwer_sig > 0:
        guidance = (
            f"{fwer_sig}/{k} test(s) survive Holm-Bonferroni FWER across M={m} "
            f"(Bonferroni cutoff={bonf_threshold:.4g}); retain supported conclusion for FWER-passing endpoints "
            "and bound eroded secondary endpoints explicitly."
        )
    elif fdr_sig > 0:
        guidance = (
            f"{fdr_sig}/{k} test(s) survive BH-FDR at q < {alpha:g} across M={m}, but none survive strict FWER; "
            "label as discovery/FDR-controlled rather than FWER-confirmed."
        )
    else:
        guidance = f"No tests cross nominal alpha={alpha:g} across M={m} (global-null FWER={global_null_fwer:.1%})."

    return {
        "mode": "multiplicity_audit",
        "alpha": alpha,
        "submitted_tests": k,
        "prior_exploratory_forks": prior_forks,
        "effective_family_size": m,
        "global_null_fwer_at_alpha": round(global_null_fwer, 6),
        "bonferroni_alpha": round(bonf_threshold, 8),
        "sidak_alpha": round(sidak_threshold, 8),
        "nominal_significant_count": nominal_sig,
        "holm_fwer_significant_count": fwer_sig,
        "bh_fdr_significant_count": fdr_sig,
        "eroded_after_adjustment_ids": eroded_ids,
        "cherry_picking_risk": cherry_picking_risk,
        "adjusted_tests": adjusted_rows,
        "guidance": guidance,
        "suggested_multiplicity_reason": (
            f"Across M={m} tests (k={k} reported, prior_exploratory_forks={prior_forks}), "
            f"{fwer_sig} survive Holm-Bonferroni FWER and {fdr_sig} survive BH-FDR at alpha={alpha:g} "
            f"(Bonferroni threshold={bonf_threshold:.4g})."
        ),
    }


def _extract_working_est_se(
    rec: dict[str, Any],
    *,
    scale: str,
    ci_level: float,
    label: str,
) -> tuple[float, float, float]:
    """Return (working_estimate, working_se, raw_estimate) from an item with se or ci_low/ci_high."""
    est = _finite(rec["estimate"], f"{label}.estimate")
    if scale == "log":
        if est <= 0.0:
            fail("invalid_value", f"{label}.estimate must be > 0 when scale='log'")
        x_est = math.log(est)
    else:
        x_est = est

    if "se" in rec and rec["se"] is not None:
        se = _positive(rec["se"], f"{label}.se")
    elif "ci_low" in rec and "ci_high" in rec:
        lo = _finite(rec["ci_low"], f"{label}.ci_low")
        hi = _finite(rec["ci_high"], f"{label}.ci_high")
        if scale == "log":
            if lo <= 0.0 or hi <= 0.0:
                fail("invalid_value", f"{label}.ci_low and ci_high must be > 0 when scale='log'")
            x_lo, x_hi = math.log(lo), math.log(hi)
        else:
            x_lo, x_hi = lo, hi
        if x_hi <= x_lo:
            fail("invalid_value", f"{label}.ci_high must exceed ci_low")
        source_level = _prob(rec.get("ci_level", ci_level), f"{label}.ci_level")
        quantile = 0.5 + source_level / 2.0
        if rec.get("df") is None:
            critical = _norm_ppf(quantile)
        else:
            critical = _t_ppf(quantile, _pos_int(rec["df"], f"{label}.df"))
        se = (x_hi - x_lo) / (2.0 * critical)
    else:
        fail("missing_field", f"{label} requires either se or both ci_low and ci_high")
    return x_est, se, est


def _compute_interaction_heterogeneity(payload: dict[str, Any]) -> dict[str, Any]:
    """Subgroup direct interaction test (Gelman-Stern) or DerSimonian-Laird meta-analysis."""
    allowed = {"mode", "group_a", "group_b", "studies", "scale", "alpha", "ci_level", "null_value"}
    fields(payload, allowed, {"mode"}, "analyze_design.interaction_heterogeneity")
    scale = enum(payload.get("scale", "linear"), ("linear", "log"), "scale")
    alpha = _prob(payload.get("alpha", 0.05), "alpha")
    ci_level = _prob(payload.get("ci_level", 0.95), "ci_level")
    z_ci = _norm_ppf(0.5 + ci_level / 2.0)
    has_pair = "group_a" in payload or "group_b" in payload
    has_studies = "studies" in payload
    if has_pair and has_studies:
        fail("invalid_value", "Provide either (group_a, group_b) for subgroup interaction OR studies for meta-analysis, not both")
    if not has_pair and not has_studies:
        fail("missing_field", "interaction_heterogeneity requires either (group_a and group_b) or studies")

    if has_pair:
        if "group_a" not in payload or "group_b" not in payload:
            fail("missing_field", "Subgroup interaction requires both group_a and group_b")
        ga = obj(payload["group_a"], "group_a")
        gb = obj(payload["group_b"], "group_b")
        for grp, nm in ((ga, "group_a"), (gb, "group_b")):
            fields(grp, {"label", "estimate", "se", "ci_low", "ci_high", "ci_level", "df"}, {"estimate"}, nm)
        null_val = _finite(payload.get("null_value", 1.0 if scale == "log" else 0.0), "null_value")
        x_null = math.log(null_val) if (scale == "log" and null_val > 0.0) else (0.0 if scale == "linear" else fail("invalid_value", "null_value must be > 0 for scale='log'"))
        ya, sa, raw_a = _extract_working_est_se(ga, scale=scale, ci_level=ci_level, label="group_a")
        yb, sb, raw_b = _extract_working_est_se(gb, scale=scale, ci_level=ci_level, label="group_b")
        label_a = string(ga.get("label", "Group A"), "group_a.label", maximum=120)
        label_b = string(gb.get("label", "Group B"), "group_b.label", maximum=120)

        p_a = math.erfc(abs((ya - x_null) / sa) / math.sqrt(2.0))
        p_b = math.erfc(abs((yb - x_null) / sb) / math.sqrt(2.0))
        delta = ya - yb
        se_delta = math.sqrt(sa * sa + sb * sb)
        z_int = delta / se_delta
        p_int = math.erfc(abs(z_int) / math.sqrt(2.0))
        ci_lo_w = delta - z_ci * se_delta
        ci_hi_w = delta + z_ci * se_delta
        contrast_est = math.exp(delta) if scale == "log" else delta
        contrast_lo = math.exp(ci_lo_w) if scale == "log" else ci_lo_w
        contrast_hi = math.exp(ci_hi_w) if scale == "log" else ci_hi_w

        a_sig = p_a < alpha
        b_sig = p_b < alpha
        int_sig = p_int < alpha
        illusion = (a_sig != b_sig) and (not int_sig)
        if int_sig:
            classification = "interaction_supported"
            guidance = (
                f"Direct interaction test between '{label_a}' and '{label_b}' is statistically significant "
                f"(p_interaction={p_int:.4g} < {alpha:g}); subgroup heterogeneity is supported on the {scale} scale."
            )
        elif illusion:
            classification = "sig_vs_nonsig_illusion"
            guidance = (
                f"Gelman-Stern fallacy alert: '{label_a}' (p={p_a:.4g}) and '{label_b}' (p={p_b:.4g}) sit on "
                f"opposite sides of alpha={alpha:g}, YET the direct interaction contrast is NOT significant "
                f"(p_interaction={p_int:.4g}, {ci_level:.0%} CI [{contrast_lo:.4g}, {contrast_hi:.4g}]). "
                "Do NOT claim a differential subgroup effect."
            )
        else:
            classification = "no_interaction_detected"
            guidance = (
                f"No statistically significant interaction between '{label_a}' and '{label_b}' "
                f"(p_interaction={p_int:.4g}); subgroup estimates are compatible with a common effect within uncertainty."
            )

        return {
            "mode": "interaction_heterogeneity",
            "analysis_type": "subgroup_interaction",
            "scale": scale,
            "alpha": alpha,
            "ci_level": ci_level,
            "group_a": {"label": label_a, "estimate": raw_a, "se_working": round(sa, 6), "p_value": round(p_a, 8), "significant": a_sig},
            "group_b": {"label": label_b, "estimate": raw_b, "se_working": round(sb, 6), "p_value": round(p_b, 8), "significant": b_sig},
            "interaction_contrast": round(contrast_est, 6),
            "contrast_metric": "ratio_of_ratios" if scale == "log" else "difference_of_effects",
            "interaction_se_working": round(se_delta, 6),
            "interaction_z": round(z_int, 6),
            "interaction_p_value": round(p_int, 8),
            "interaction_ci_low": round(contrast_lo, 6),
            "interaction_ci_high": round(contrast_hi, 6),
            "sig_vs_nonsig_illusion": illusion,
            "classification": classification,
            "guidance": guidance,
        }

    # Sub-mode 2: DerSimonian-Laird random-effects & fixed-effect meta-analysis
    raw_studies = array(payload["studies"], "studies", minimum=2, maximum=100)
    null_val = _finite(payload.get("null_value", 1.0 if scale == "log" else 0.0), "null_value")
    if scale == "log" and null_val <= 0.0:
        fail("invalid_value", "null_value must be > 0 when scale='log'")
    x_null = math.log(null_val) if scale == "log" else null_val

    ys: list[float] = []
    ses: list[float] = []
    seen_sids: set[str] = set()
    for idx, st in enumerate(raw_studies):
        rec = obj(st, f"studies[{idx}]")
        fields(rec, {"id", "estimate", "se", "ci_low", "ci_high", "ci_level", "df"}, {"id", "estimate"}, f"studies[{idx}]")
        sid = string(rec["id"], f"studies[{idx}].id", maximum=120)
        if sid in seen_sids:
            fail("duplicate_id", f"Duplicate study id '{sid}'")
        seen_sids.add(sid)
        y, s, _ = _extract_working_est_se(rec, scale=scale, ci_level=ci_level, label=f"studies[{idx}]")
        ys.append(y)
        ses.append(s)

    k = len(ys)
    ws = [1.0 / (s * s) for s in ses]
    sum_w = sum(ws)
    sum_w2 = sum(w * w for w in ws)
    mu_fe = sum(w * y for w, y in zip(ws, ys)) / sum_w
    se_fe = math.sqrt(1.0 / sum_w)
    q_stat = sum(w * (y - mu_fe) ** 2 for w, y in zip(ws, ys))
    df_q = k - 1
    p_q = _chi2_sf(q_stat, df_q)
    i2_pct = 0.0 if q_stat <= df_q or q_stat <= 0.0 else 100.0 * (q_stat - df_q) / q_stat
    c_denom = sum_w - (sum_w2 / sum_w)
    tau2 = max(0.0, (q_stat - df_q) / c_denom) if c_denom > 0.0 else 0.0
    tau = math.sqrt(tau2)

    ws_re = [1.0 / (s * s + tau2) for s in ses]
    sum_w_re = sum(ws_re)
    mu_re = sum(w * y for w, y in zip(ws_re, ys)) / sum_w_re
    se_re = math.sqrt(1.0 / sum_w_re)

    def _pack_pool(mu: float, se: float) -> dict[str, Any]:
        lo_w, hi_w = mu - z_ci * se, mu + z_ci * se
        z_v = (mu - x_null) / se
        p_v = math.erfc(abs(z_v) / math.sqrt(2.0))
        return {
            "estimate": round(math.exp(mu) if scale == "log" else mu, 6),
            "ci_low": round(math.exp(lo_w) if scale == "log" else lo_w, 6),
            "ci_high": round(math.exp(hi_w) if scale == "log" else hi_w, 6),
            "se_working": round(se, 6),
            "p_value": round(p_v, 8),
            "excludes_null": not (lo_w <= x_null <= hi_w),
        }

    fe_res = _pack_pool(mu_fe, se_fe)
    re_res = _pack_pool(mu_re, se_re)

    pi_low: float | None = None
    pi_high: float | None = None
    pi_crosses_null: bool | None = None
    if k >= 3:
        t_pi = _t_ppf(0.5 + ci_level / 2.0, k - 2)
        pi_sd = math.sqrt(tau2 + se_re * se_re)
        pi_lo_w = mu_re - t_pi * pi_sd
        pi_hi_w = mu_re + t_pi * pi_sd
        pi_low = round(math.exp(pi_lo_w) if scale == "log" else pi_lo_w, 6)
        pi_high = round(math.exp(pi_hi_w) if scale == "log" else pi_hi_w, 6)
        pi_crosses_null = bool(pi_lo_w <= x_null <= pi_hi_w)

    if re_res["excludes_null"] and pi_crosses_null is True:
        classification = "pooled_sig_but_prediction_interval_crosses_null"
        guidance = (
            f"Random-effects pooled estimate excludes null ({re_res['estimate']:g}, CI [{re_res['ci_low']:g}, {re_res['ci_high']:g}], "
            f"I^2={i2_pct:.1f}%), BUT the {ci_level:.0%} prediction interval [{pi_low:g}, {pi_high:g}] crosses null. "
            "Report average benefit while scoping generalizability to heterogeneous settings."
        )
    elif re_res["excludes_null"] and i2_pct < 40.0:
        classification = "homogeneous_consistent_effect"
        guidance = (
            f"Consistent pooled effect across k={k} studies ({re_res['estimate']:g}, CI [{re_res['ci_low']:g}, {re_res['ci_high']:g}], "
            f"I^2={i2_pct:.1f}%, Q p={p_q:.4g}); do not underclaim cross-study replication."
        )
    elif re_res["excludes_null"]:
        classification = "heterogeneous_average_effect"
        guidance = (
            f"Average random-effects estimate excludes null ({re_res['estimate']:g}) under substantial heterogeneity "
            f"(I^2={i2_pct:.1f}%, tau={tau:.4g}); investigate effect modifiers."
        )
    else:
        classification = "pooled_interval_includes_null"
        guidance = (
            f"Random-effects pooled {ci_level:.0%} CI [{re_res['ci_low']:g}, {re_res['ci_high']:g}] includes null "
            f"(I^2={i2_pct:.1f}%, Q p={p_q:.4g})."
        )

    return {
        "mode": "interaction_heterogeneity",
        "analysis_type": "dersimonian_laird_meta",
        "scale": scale,
        "alpha": alpha,
        "ci_level": ci_level,
        "k_studies": k,
        "fixed_effect": fe_res,
        "random_effects": re_res,
        "cochran_q": round(q_stat, 6),
        "q_df": df_q,
        "q_p_value": round(p_q, 8),
        "i2_percent": round(i2_pct, 2),
        "tau2": round(tau2, 6),
        "tau": round(tau, 6),
        "prediction_interval_low": pi_low,
        "prediction_interval_high": pi_high,
        "prediction_interval_crosses_null": pi_crosses_null,
        "classification": classification,
        "guidance": guidance,
    }


def _compute_prediction_utility_audit(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit EPV/heuristic overfitting shrinkage (Riley 2020) and Vickers Decision-Curve Net Benefit."""
    allowed = {
        "mode", "validation_stage", "events", "non_events", "n",
        "candidate_predictors", "model_chi2", "c_statistic",
        "threshold_probability", "confusion", "prevalence", "sensitivity", "specificity",
    }
    fields(payload, allowed, {"mode"}, "analyze_design.prediction_utility_audit")
    stage = enum(payload.get("validation_stage", "unknown"), ("development", "internal", "external", "unknown"), "validation_stage")

    has_adequacy = any(k in payload for k in ("events", "non_events", "n", "candidate_predictors", "model_chi2"))
    has_utility = "threshold_probability" in payload
    if not has_adequacy and not has_utility:
        fail("missing_field", "prediction_utility_audit requires sample adequacy inputs (events/n/candidate_predictors) and/or threshold_probability for Net Benefit")

    out: dict[str, Any] = {"mode": "prediction_utility_audit", "validation_stage": stage}
    guidance_parts: list[str] = []

    if has_adequacy:
        events = _nonneg_int(payload["events"], "events") if "events" in payload else None
        n_total = _pos_int(payload["n"], "n") if "n" in payload else None
        non_events = _nonneg_int(payload["non_events"], "non_events") if "non_events" in payload else None
        if events is not None and non_events is None and n_total is not None:
            if events > n_total:
                fail("invalid_value", "events cannot exceed n")
            non_events = n_total - events
        elif events is not None and non_events is not None and n_total is None:
            n_total = events + non_events
        adequacy: dict[str, Any] = {"events": events, "non_events": non_events, "n": n_total}

        if "candidate_predictors" in payload and payload["candidate_predictors"] is not None:
            p_cand = _pos_int(payload["candidate_predictors"], "candidate_predictors")
            adequacy["candidate_predictors"] = p_cand
            if events is not None:
                epv = events / p_cand
                adequacy["epv"] = round(epv, 3)
                adequacy["epv_risk"] = "high_overfitting_risk" if epv < 10.0 else ("moderate" if epv < 20.0 else "low")
            if "model_chi2" in payload and payload["model_chi2"] is not None:
                chi2 = _positive(payload["model_chi2"], "model_chi2")
                shrinkage = 1.0 - (p_cand / chi2)
                adequacy["van_houwelingen_shrinkage"] = round(shrinkage, 4)
                adequacy["shrinkage_adequate"] = shrinkage >= 0.90
                if shrinkage < 0.90:
                    guidance_parts.append(
                        f"Heuristic shrinkage S={shrinkage:.3f} < 0.90 ({p_cand} candidate predictors, LR chi2={chi2:g}): "
                        "high overfitting risk; apply penalization or increase sample size before claiming generalization."
                    )

        if stage == "external" and events is not None and non_events is not None:
            if events >= 100 and non_events >= 100:
                ext_band = "adequate_external_sample"
            elif events >= 30 and non_events >= 30:
                ext_band = "modest_external_precision"
            else:
                ext_band = "underpowered_external_validation"
            adequacy["external_validation_adequacy"] = ext_band
            if ext_band == "underpowered_external_validation":
                guidance_parts.append(
                    f"External validation has only {events} events / {non_events} non-events (Vergouwe/Collins benchmark >=100 each): "
                    "calibration slope and subgroup performance remain imprecise."
                )
            elif ext_band == "modest_external_precision":
                guidance_parts.append(
                    f"External validation ({events} events, {non_events} non-events) supports external discrimination "
                    "with reported CI width; do not dismiss valid discrimination solely for lacking an RCT, "
                    "while bounding untested clinical utility."
                )
        out["sample_adequacy"] = adequacy

    if has_utility:
        pt = _prob(payload["threshold_probability"], "threshold_probability")
        odds_w = pt / (1.0 - pt)
        if "confusion" in payload and payload["confusion"] is not None:
            cm = obj(payload["confusion"], "confusion")
            fields(cm, {"tp", "fp", "tn", "fn"}, {"tp", "fp", "tn", "fn"}, "confusion")
            tp = _nonneg_int(cm["tp"], "confusion.tp")
            fp = _nonneg_int(cm["fp"], "confusion.fp")
            tn = _nonneg_int(cm["tn"], "confusion.tn")
            fn = _nonneg_int(cm["fn"], "confusion.fn")
            n_cm = tp + fp + tn + fn
            if n_cm <= 0:
                fail("invalid_value", "confusion matrix total count must be > 0")
            prev = (tp + fn) / n_cm
            tp_rate = tp / n_cm
            fp_rate = fp / n_cm
            sens = tp / (tp + fn) if (tp + fn) > 0 else None
            spec = tn / (tn + fp) if (tn + fp) > 0 else None
        elif all(k in payload for k in ("prevalence", "sensitivity", "specificity")):
            prev = _prob(payload["prevalence"], "prevalence")
            sens = _prob(payload["sensitivity"], "sensitivity", strict_open=False)
            spec = _prob(payload["specificity"], "specificity", strict_open=False)
            tp_rate = prev * sens
            fp_rate = (1.0 - prev) * (1.0 - spec)
        else:
            fail("missing_field", "Net Benefit requires either confusion={tp,fp,tn,fn} or (prevalence, sensitivity, specificity)")

        nb_model = tp_rate - fp_rate * odds_w
        nb_all = prev - (1.0 - prev) * odds_w
        nb_none = 0.0
        best_default = max(nb_all, nb_none)
        delta_nb = nb_model - best_default
        interventions_avoided_per_100 = (100.0 * delta_nb / odds_w) if delta_nb > 0.0 else 0.0

        if delta_nb > 1e-6:
            util_status = "positive_net_benefit_over_defaults"
            guidance_parts.append(
                f"At threshold p_t={pt:.2%}, model Net Benefit ({nb_model:.4f}) exceeds both treat-all ({nb_all:.4f}) "
                f"and treat-none (0) by delta_NB={delta_nb:.4f} (~{interventions_avoided_per_100:.1f} unnecessary interventions avoided per 100 patients)."
            )
        elif delta_nb >= -1e-6:
            util_status = "no_net_benefit_over_treat_all_or_none"
            guidance_parts.append(
                f"At threshold p_t={pt:.2%}, model Net Benefit ({nb_model:.4f}) offers zero gain over default strategies "
                f"(max default={best_default:.4f}); do NOT claim clinical decision utility from discrimination alone."
            )
        else:
            util_status = "harmful_net_benefit_below_defaults"
            guidance_parts.append(
                f"At threshold p_t={pt:.2%}, the estimated model net benefit for the supplied inputs ({nb_model:.4f}) "
                f"is below the best default strategy ({best_default:.4f}, delta_NB={delta_nb:.4f}). "
                "Actual clinical outcomes after deployment require separate evidence."
            )

        out["decision_curve_utility"] = {
            "threshold_probability": pt,
            "prevalence": round(prev, 6),
            "sensitivity": round(sens, 6) if sens is not None else None,
            "specificity": round(spec, 6) if spec is not None else None,
            "net_benefit_model": round(nb_model, 6),
            "net_benefit_treat_all": round(nb_all, 6),
            "net_benefit_treat_none": nb_none,
            "delta_net_benefit_vs_best_default": round(delta_nb, 6),
            "interventions_avoided_per_100": round(interventions_avoided_per_100, 2),
            "utility_classification": util_status,
        }

    out["guidance"] = " ".join(guidance_parts) if guidance_parts else "Prediction sample adequacy recorded; verify calibration slope and decision-curve utility separately from discrimination."
    return out


def _compute_attrition_bounds(payload: dict[str, Any]) -> dict[str, Any]:
    """Manski worst-case / best-case bounds and tipping-point sensitivity for binary outcome attrition."""
    allowed = {"mode", "treated", "control", "beneficial_if", "alpha"}
    fields(payload, allowed, {"mode", "treated", "control"}, "analyze_design.attrition_bounds")
    alpha = _prob(payload.get("alpha", 0.05), "alpha")
    z_crit = _norm_ppf(1.0 - alpha / 2.0)
    beneficial_if = enum(payload.get("beneficial_if", "lower_event_rate"), ("lower_event_rate", "higher_event_rate"), "beneficial_if")

    def _parse_arm(raw: Any, name: str) -> tuple[int, int, int]:
        arm = obj(raw, name)
        fields(arm, {"events", "analyzed", "missing"}, {"events", "analyzed", "missing"}, name)
        ev = _nonneg_int(arm["events"], f"{name}.events")
        an = _pos_int(arm["analyzed"], f"{name}.analyzed")
        mi = _nonneg_int(arm["missing"], f"{name}.missing")
        if ev > an:
            fail("invalid_value", f"{name}.events ({ev}) cannot exceed {name}.analyzed ({an})")
        return ev, an, mi

    e_t, n_t, m_t = _parse_arm(payload["treated"], "treated")
    e_c, n_c, m_c = _parse_arm(payload["control"], "control")
    tot_t, tot_c = n_t + m_t, n_c + m_c
    p_t = e_t / n_t
    p_c = e_c / n_c
    rd_cc = p_t - p_c
    se_cc = math.sqrt(p_t * (1.0 - p_t) / n_t + p_c * (1.0 - p_c) / n_c)
    cc_lo = rd_cc - z_crit * se_cc
    cc_hi = rd_cc + z_crit * se_cc
    cc_p = math.erfc(abs(rd_cc / se_cc) / math.sqrt(2.0)) if se_cc > 0.0 else (0.0 if rd_cc != 0.0 else 1.0)

    att_t = m_t / tot_t
    att_c = m_c / tot_c
    att_total = (m_t + m_c) / (tot_t + tot_c)
    diff_att = abs(att_t - att_c)

    # Manski bounds over full randomized denominators tot_t, tot_c
    p_t_min, p_t_max = e_t / tot_t, (e_t + m_t) / tot_t
    p_c_min, p_c_max = e_c / tot_c, (e_c + m_c) / tot_c
    if beneficial_if == "lower_event_rate":
        rd_worst = p_t_max - p_c_min
        rd_best = p_t_min - p_c_max
        se_worst = math.sqrt(p_t_max * (1.0 - p_t_max) / tot_t + p_c_min * (1.0 - p_c_min) / tot_c)
        survives_manski = rd_worst < 0.0
        survives_manski_ci = (rd_worst + z_crit * se_worst) < 0.0
        cc_beneficial = rd_cc < 0.0
    else:
        rd_worst = p_t_min - p_c_max
        rd_best = p_t_max - p_c_min
        se_worst = math.sqrt(p_t_min * (1.0 - p_t_min) / tot_t + p_c_max * (1.0 - p_c_max) / tot_c)
        survives_manski = rd_worst > 0.0
        survives_manski_ci = (rd_worst - z_crit * se_worst) > 0.0
        cc_beneficial = rd_cc > 0.0

    # Tipping-point analysis holding missing control at observed p_c, varying missing treated rate q in [0, 1]
    q_null: float | None = None
    q_ci_cross: float | None = None
    if m_t > 0:
        # Solve (e_t + q * m_t) / tot_t = p_c
        q_raw = (p_c * tot_t - e_t) / m_t
        if 0.0 <= q_raw <= 1.0:
            q_null = round(q_raw, 6)

        def _ci_still_sig(q: float) -> bool:
            pt_q = (e_t + q * m_t) / tot_t
            rd_q = pt_q - p_c
            se_q = math.sqrt(pt_q * (1.0 - pt_q) / tot_t + p_c * (1.0 - p_c) / tot_c)
            if beneficial_if == "lower_event_rate":
                return (rd_q + z_crit * se_q) < 0.0
            return (rd_q - z_crit * se_q) > 0.0

        start_q = p_t
        end_q = 1.0 if beneficial_if == "lower_event_rate" else 0.0
        if _ci_still_sig(start_q) and not _ci_still_sig(end_q):
            lo_q, hi_q = (start_q, end_q) if start_q < end_q else (end_q, start_q)
            for _ in range(60):
                mid_q = 0.5 * (lo_q + hi_q)
                if beneficial_if == "lower_event_rate":
                    if _ci_still_sig(mid_q):
                        lo_q = mid_q
                    else:
                        hi_q = mid_q
                else:
                    if _ci_still_sig(mid_q):
                        hi_q = mid_q
                    else:
                        lo_q = mid_q
            q_ci_cross = round(0.5 * (lo_q + hi_q), 6)

    if m_t == 0 and m_c == 0:
        robustness = "no_missing_outcomes"
    elif survives_manski_ci:
        robustness = "robust_survives_manski_worst_case"
    elif diff_att >= 0.10 or att_total >= 0.20:
        robustness = "fragile_severe_or_differential_attrition"
    elif q_ci_cross is None and cc_beneficial and cc_p < alpha:
        robustness = "robust_treated_missing_cannot_tip_ci"
    else:
        robustness = "sensitive_to_missingness_assumptions"

    if robustness == "robust_survives_manski_worst_case":
        guidance = (
            f"Effect survives even extreme Manski worst-case bounds (RD_worst={rd_worst:+.4f}); "
            "do NOT dismiss the complete-case benefit solely due to modest missingness."
        )
    elif robustness == "fragile_severe_or_differential_attrition":
        guidance = (
            f"High/differential attrition ({att_t:.1%} treated vs {att_c:.1%} control, diff={diff_att:.1%}) "
            f"causes Manski worst-case RD={rd_worst:+.4f} to cross/reverse null (complete-case RD={rd_cc:+.4f}). "
            "Complete-case efficacy claim is NOT robust; require ITT sensitivity or downgrade."
        )
    elif robustness == "no_missing_outcomes":
        guidance = f"Zero outcome attrition in both arms (complete-case RD={rd_cc:+.4f}, p={cc_p:.4g})."
    else:
        tip_msg = f", CI tipping rate among missing treated q_CI={q_ci_cross:.2%}" if q_ci_cross is not None else ""
        guidance = (
            f"Complete-case RD={rd_cc:+.4f} (CI [{cc_lo:+.4f}, {cc_hi:+.4f}]) does not survive extreme Manski worst case "
            f"(RD_worst={rd_worst:+.4f}){tip_msg}; report ITT/MNAR sensitivity alongside complete-case results."
        )

    return {
        "mode": "attrition_bounds",
        "beneficial_if": beneficial_if,
        "alpha": alpha,
        "complete_case": {
            "treated_rate": round(p_t, 6),
            "control_rate": round(p_c, 6),
            "risk_difference": round(rd_cc, 6),
            "ci_low": round(cc_lo, 6),
            "ci_high": round(cc_hi, 6),
            "p_value": round(cc_p, 8),
        },
        "attrition": {
            "treated_attrition_rate": round(att_t, 6),
            "control_attrition_rate": round(att_c, 6),
            "total_attrition_rate": round(att_total, 6),
            "differential_attrition": round(diff_att, 6),
        },
        "manski_bounds": {
            "worst_case_rd": round(rd_worst, 6),
            "best_case_rd": round(rd_best, 6),
            "survives_worst_case_sign": survives_manski,
            "survives_worst_case_ci": survives_manski_ci,
        },
        "tipping_point": {
            "treated_missing_rate_to_null": q_null,
            "treated_missing_rate_to_cross_ci": q_ci_cross,
            "control_missing_assumption": "held_at_observed_control_rate",
        },
        "attrition_robustness": robustness,
        "guidance": guidance,
    }


def analyze_design(
    payload: dict[str, Any],
    *,
    case_audit_callback: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    lineage_synthesis_callback: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Dispatch read-only computable scientific methodology analysis."""
    obj(payload, "analyze_design")
    mode = enum(payload.get("mode"), DESIGN_ANALYSIS_MODES, "analyze_design.mode")
    if mode == "power_mde":
        result = _compute_power_mde(payload)
    elif mode == "tost_equivalence":
        result = _compute_tost(payload)
    elif mode == "e_value":
        result = _compute_evalue(payload)
    elif mode == "pseudoreplication_audit":
        result = _compute_pseudoreplication(payload)
    elif mode == "evidence_dominance":
        result = _compute_evidence_dominance(payload)
    elif mode == "multiplicity_audit":
        result = _compute_multiplicity_audit(payload)
    elif mode == "interaction_heterogeneity":
        result = _compute_interaction_heterogeneity(payload)
    elif mode == "prediction_utility_audit":
        result = _compute_prediction_utility_audit(payload)
    elif mode == "attrition_bounds":
        result = _compute_attrition_bounds(payload)
    elif mode == "case_audit":
        if case_audit_callback is None:
            fail("invalid_state", "case_audit requires an Engine workspace context")
        result = case_audit_callback(payload)
    else:
        if lineage_synthesis_callback is None:
            fail("invalid_state", "lineage_synthesis requires an Engine workspace context")
        result = lineage_synthesis_callback(payload)
    result["computation_backend"] = available_backends()["statistics"]["default"]
    result["scientific_validity"] = "computable_diagnostic_only_not_empirical_proof"
    return result
