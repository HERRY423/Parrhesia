"""Pure-stdlib structured effect records and computable verification checks."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
import sys
from typing import Any

from .contracts import ContractError, array, enum, fail, fields, obj, string

MAX_EFFECT_RECORDS = 50
MAX_ARTIFACT_RECORD_INDEX = 100_000
EFFECT_RECORD_ROLES = ("primary", "secondary", "safety", "exploratory", "sensitivity", "benchmark")
EFFECT_METRICS = (
    "HR", "OR", "RR", "IRR",
    "diff", "mean_diff", "risk_diff",
    "proportion", "rate", "AUC", "AUROC", "RMSE", "MAE", "R2", "F1", "accuracy",
    "logFC", "beta", "count", "other",
)
RATIO_METRICS = ("HR", "OR", "RR", "IRR")
DIFFERENCE_METRICS = ("diff", "mean_diff", "risk_diff", "logFC", "beta")
PROPORTION_METRICS = ("proportion", "accuracy", "F1", "AUROC", "AUC")
EFFECT_DIRECTIONS = (
    "benefit", "harm", "null", "non_inferior", "equivalence", "higher_better", "lower_better", "neutral"
)
EFFECT_BENEFICIAL_POLARITY = ("below_null", "above_null")
EFFECT_SCALES = ("unit", "percentage")
INFERENCE_METHODS = ("wald", "log_wald", "student_t", "other", "unknown")
COUNT_BASES = ("unweighted_binary", "other", "unknown")
MULTIPLICITY_METHODS = ("bonferroni", "holm", "bh_fdr", "none", "unknown")

PRIMARY_EFFECT_ROLES = ("primary", "benchmark")
REQUIRED_EFFECT_KEYS = {"id", "endpoint", "endpoint_role", "metric", "estimate", "direction", "evidence_id"}
OPTIONAL_EFFECT_KEYS = {
    "null_value", "ci_level", "ci_low", "ci_high", "p_value",
    "n", "events", "decimals", "scale", "beneficial_if", "quote_substring", "notes",
    "cohort_id", "inference_method", "count_basis", "claim_direction",
    "artifact_binding",
    "df", "adjusted_p_value", "multiplicity_method", "family_size",
    "contingency", "interaction_contrast",
}
ALLOWED_EFFECT_KEYS = REQUIRED_EFFECT_KEYS | OPTIONAL_EFFECT_KEYS

_NUM_RE = re.compile(
    r"(?<![0-9A-Za-z_])([+-]?)(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("invalid_type", f"{name} must be a finite number (not bool)")
    num = float(value)
    if not math.isfinite(num):
        fail("invalid_value", f"{name} must be a finite number")
    return num


def _int_value(value: Any, name: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail("invalid_type", f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        fail("invalid_value", f"{name} must be {bound}")
    return value


def _non_empty_text(value: Any, name: str, *, maximum: int = 2000) -> str:
    text = string(value, name, maximum=maximum)
    if not text.strip():
        fail("invalid_value", f"{name} cannot be blank")
    return text


def _effective_null(record: dict[str, Any]) -> float | None:
    if record.get("null_value") is not None:
        return float(record["null_value"])
    metric = record["metric"]
    if metric in RATIO_METRICS:
        return 1.0
    if metric in DIFFERENCE_METRICS:
        return 0.0
    return None


def _norm_ppf(prob: float) -> float:
    """Inverse standard normal CDF via monotone binary search on math.erf."""
    if not (0.0 < prob < 1.0):
        raise ValueError("prob must be strictly between 0 and 1")
    lo, hi = -10.0, 10.0
    target = 2.0 * prob - 1.0
    sqrt2 = math.sqrt(2.0)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if math.erf(mid / sqrt2) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _two_sided_z(p_value: float) -> float:
    """Return |z| matching two-sided p_value = erfc(|z|/sqrt(2))."""
    if p_value <= 0.0:
        return math.inf
    if p_value >= 1.0:
        return 0.0
    lo, hi = 0.0, 10.0
    sqrt2 = math.sqrt(2.0)
    while math.erfc(hi / sqrt2) > p_value and hi < 40.0:
        hi *= 2.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if math.erfc(mid / sqrt2) > p_value:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _betacf(a: float, b: float, x: float) -> float:
    max_iter = 200
    eps = 3.0e-13
    fpmin = 1.0e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) via Lentz continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _two_sided_t_p(t_abs: float, df: int) -> float:
    if t_abs <= 0.0:
        return 1.0
    x = df / (df + t_abs * t_abs)
    return min(1.0, max(0.0, _betainc(0.5 * df, 0.5, x)))


def _t_ppf(prob: float, df: int) -> float:
    """Inverse Student-t CDF for 0.5 < prob < 1.0."""
    if not (0.5 < prob < 1.0):
        raise ValueError("prob must satisfy 0.5 < prob < 1")
    target_two_sided = 2.0 * (1.0 - prob)
    lo, hi = 0.0, 4.0
    while _two_sided_t_p(hi, df) > target_two_sided and hi < 1e9:
        hi *= 2.0
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        if _two_sided_t_p(mid, df) > target_two_sided:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _two_sided_t_from_p(p_value: float, df: int) -> float:
    if p_value <= 0.0:
        return math.inf
    if p_value >= 1.0:
        return 0.0
    return _t_ppf(1.0 - 0.5 * p_value, df)


def _record_alpha(record: dict[str, Any]) -> float:
    ci_level = record.get("ci_level")
    if ci_level is None:
        return 0.05
    return float(Decimal("1") - Decimal(str(ci_level)))


def _inferred_decimals(value: Any) -> int:
    """Infer finite decimal places from raw int/float JSON value."""
    if isinstance(value, int) and not isinstance(value, bool):
        return 0
    try:
        dec = Decimal(str(value)).normalize()
    except InvalidOperation:
        return 6
    exp = dec.as_tuple().exponent
    if not isinstance(exp, int) or exp >= 0:
        return 0
    return min(12, -exp)


def _check_pvalue_ci_compatibility(record: dict[str, Any]) -> dict[str, Any]:
    """Check only explicitly declared matching two-sided Wald/log_wald/student_t CI/test pairs."""
    p_value = record.get("p_value")
    ci_low = record.get("ci_low")
    ci_high = record.get("ci_high")
    null_val = _effective_null(record)
    if p_value is None or ci_low is None or ci_high is None or null_val is None:
        return {"checked": False, "status": "not_applicable"}
    method = record.get("inference_method", "unknown")
    if method not in ("wald", "log_wald", "student_t"):
        return {"checked": False, "status": "unassessed", "reason": "matching_wald_method_not_declared"}
    df = record.get("df")
    if method == "student_t" and df is None:
        return {"checked": False, "status": "unassessed", "reason": "student_t_requires_df"}

    p_val = float(p_value)
    ci_level = float(record.get("ci_level") if record.get("ci_level") is not None else 0.95)
    alpha = 1.0 - ci_level
    est = float(record["estimate"])
    low = float(ci_low)
    high = float(ci_high)

    if method == "log_wald":
        est_t = math.log(est)
        low_t = math.log(low)
        high_t = math.log(high)
        null_t = math.log(null_val)
    else:
        est_t = est
        low_t = low
        high_t = high
        null_t = null_val

    half_width = 0.5 * (high_t - low_t)
    ci_excludes_null = low_t > null_t or high_t < null_t
    if half_width <= 0.0:
        if est_t != null_t and p_val > max(alpha + 0.05, 0.1):
            fail(
                "effect_pvalue_ci_mismatch",
                f"effect_record '{record['id']}' has degenerate non-null interval with non-significant p_value={p_val}",
            )
        if est_t == null_t and p_val < max(0.0, alpha - 0.02):
            fail(
                "effect_pvalue_ci_mismatch",
                f"effect_record '{record['id']}' equals null_value={null_val} yet reports p_value={p_val}",
            )
        z_stat = _two_sided_t_from_p(p_val, df) if method == "student_t" else _two_sided_z(p_val)
        return {"checked": True, "status": "pass", "z_est": None, "z_p": z_stat}

    crit = _t_ppf(1.0 - alpha / 2.0, df) if method == "student_t" else _norm_ppf(1.0 - alpha / 2.0)
    se = half_width / crit
    stat_est = abs(est_t - null_t) / se

    if p_val == 0.0:
        p_calc = _two_sided_t_p(stat_est, df) if method == "student_t" else math.erfc(stat_est / math.sqrt(2.0))
        if not ci_excludes_null or p_calc > 0.01:
            fail(
                "effect_pvalue_ci_mismatch",
                f"effect_record '{record['id']}' reports p_value=0.0 which contradicts CI [{low}, {high}] vs null {null_val} (p={p_calc:.4g})",
            )
        return {"checked": True, "status": "pass", "z_est": round(stat_est, 4), "z_p": None}

    stat_p = _two_sided_t_from_p(p_val, df) if method == "student_t" else _two_sided_z(p_val)
    diff = abs(stat_est - stat_p)
    label = "t" if method == "student_t" else "z"

    if ci_excludes_null and p_val > alpha and diff > 0.65:
        fail(
            "effect_pvalue_ci_mismatch",
            f"effect_record '{record['id']}' CI [{low}, {high}] excludes null {null_val} (alpha={alpha:.3g}, {label}={stat_est:.2f}) yet p_value={p_val} ({label}={stat_p:.2f})",
        )
    if (not ci_excludes_null) and p_val < alpha and diff > 0.65:
        fail(
            "effect_pvalue_ci_mismatch",
            f"effect_record '{record['id']}' CI [{low}, {high}] includes null {null_val} (alpha={alpha:.3g}, {label}={stat_est:.2f}) yet p_value={p_val} ({label}={stat_p:.2f})",
        )
    max_tol = max(1.5, 0.60 * max(stat_est, stat_p)) if not (method == "student_t" and df <= 5) else max(2.2, 0.70 * max(stat_est, stat_p))
    if diff > max_tol:
        fail(
            "effect_pvalue_ci_mismatch",
            f"effect_record '{record['id']}' CI [{low}, {high}] ({label}={stat_est:.2f}) is incompatible with p_value={p_val} ({label}={stat_p:.2f})",
        )
    return {"checked": True, "status": "pass", "z_est": round(stat_est, 4), "z_p": round(stat_p, 4)}


def _check_grim_granularity(record: dict[str, Any], *, inferred_decimals: int | None = None) -> dict[str, Any]:
    """Check events/n granularity or GRIM integer feasibility when applicable."""
    metric = record["metric"]
    n = record.get("n")
    events = record.get("events")
    scale = record.get("scale") or "unit"
    factor = 100.0 if scale == "percentage" else 1.0
    decimals = record.get("decimals")

    if metric not in ("proportion", "accuracy"):
        return {"checked": False, "status": "not_applicable"}
    if record.get("count_basis") != "unweighted_binary":
        return {"checked": False, "status": "unassessed", "reason": "unweighted_binary_denominator_not_declared"}

    effective_decimals = decimals if decimals is not None else inferred_decimals

    if events is not None and n is not None:
        d = effective_decimals if effective_decimals is not None else _inferred_decimals(record["estimate"])
        tol = 0.5 * (10.0 ** (-d)) + 1e-9
        expected = (events / n) * factor
        est = float(record["estimate"])
        if abs(expected - est) > tol:
            fail(
                "effect_granularity_mismatch",
                f"effect_record '{record['id']}' estimate={est} does not match events/n={events}/{n} ({expected:.6g}) within +/-{tol:.6g}",
            )
        return {"checked": True, "mode": "events_over_n", "status": "pass", "expected": expected}

    if n is not None and (effective_decimals is not None or n <= 100):
        d = effective_decimals if effective_decimals is not None else _inferred_decimals(record["estimate"])
        step = 10.0 ** (-d)
        tol = 0.5 * step + 1e-12
        est = float(record["estimate"])
        low_k = max(0, math.floor((est - tol) * n / factor) - 1)
        high_k = min(n, math.ceil((est + tol) * n / factor) + 1)
        feasible = any(abs((k * factor / n) - est) <= tol for k in range(low_k, high_k + 1))
        if not feasible:
            fail(
                "effect_grim_inconsistent",
                f"effect_record '{record['id']}' estimate={est} (scale={scale}, decimals={d}) is impossible for integer k/n with n={n}",
            )
        return {"checked": True, "mode": "grim", "status": "pass", "decimals": d}

    return {"checked": False, "status": "not_applicable"}


def _contingency_cells(cont: dict[str, int]) -> tuple[int, int, int, int]:
    if "treated_events" in cont:
        a = cont["treated_events"]
        b = cont["treated_n"] - a
        c = cont["control_events"]
        d = cont["control_n"] - c
        return a, b, c, d
    return cont["a"], cont["b"], cont["c"], cont["d"]


def contingency_ratio(numerator: int, denominator: int, metric: str) -> float:
    """Convert a count ratio once, preserving exact zeros and rejecting range loss."""
    try:
        value = numerator / denominator
    except OverflowError:
        fail("effect_out_of_range", f"{metric} exceeds the finite floating-point range")
    if not math.isfinite(value):
        fail("effect_out_of_range", f"{metric} exceeds the finite floating-point range")
    if numerator and abs(value) < sys.float_info.min:
        fail("effect_underflow", f"Nonzero {metric} is below normal floating-point precision; no zero estimate is substituted")
    return value


def _check_contingency_consistency(record: dict[str, Any]) -> dict[str, Any]:
    cont = record.get("contingency")
    if cont is None:
        return {"checked": False, "status": "not_applicable"}
    a, b, c, d = _contingency_cells(cont)
    n1 = a + b
    n0 = c + d
    metric = record["metric"]
    est = float(record["estimate"])
    decimals = record.get("decimals")
    inferred_d = _inferred_decimals(record["estimate"])
    tol = (0.5 * (10.0 ** (-decimals)) + 1e-9) if decimals is not None else max(1e-6, 0.5 * (10.0 ** (-min(8, inferred_d))) + 1e-9)

    if metric == "risk_diff":
        factor = 100.0 if (record.get("scale") or "unit") == "percentage" else 1.0
        expected = contingency_ratio(a * n0 - c * n1, n1 * n0, metric) * factor
    elif metric == "RR":
        if a == 0 or c == 0:
            fail(
                "effect_contingency_mismatch",
                f"effect_record '{record['id']}' raw 2x2 table has zero event cell (a={a}, c={c}); unadjusted RR ratio is undefined or non-positive",
            )
        expected = contingency_ratio(a * n0, c * n1, metric)
    elif metric == "OR":
        if a == 0 or b == 0 or c == 0 or d == 0:
            fail(
                "effect_contingency_mismatch",
                f"effect_record '{record['id']}' raw 2x2 table has zero cell ({a},{b},{c},{d}); unadjusted OR is undefined or non-positive",
            )
        expected = contingency_ratio(a * d, b * c, metric)
    elif metric in ("proportion", "accuracy"):
        factor = 100.0 if (record.get("scale") or "unit") == "percentage" else 1.0
        total = n1 + n0
        events = a + c if metric == "proportion" else a + d
        expected = contingency_ratio(events, total, metric) * factor
    else:
        return {"checked": False, "status": "not_applicable"}

    # Accept relative tolerance only when unrounded high-precision floats diverge slightly at scale.
    eff_tol = max(tol, 1e-5 * max(1.0, abs(expected))) if decimals is None and inferred_d >= 4 else tol
    if abs(est - expected) > eff_tol:
        fail(
            "effect_contingency_mismatch",
            f"effect_record '{record['id']}' estimate={est} contradicts raw 2x2 counts ({a}/{n1} vs {c}/{n0}, expected {metric}={expected:.6g})",
        )
    return {"checked": True, "status": "pass", "expected": expected}


def _check_multiplicity_consistency(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[tuple[str, int | None], list[dict[str, Any]]] = {}
    statuses: dict[str, dict[str, Any]] = {}
    for rec in records:
        rid = rec["id"]
        adj_p = rec.get("adjusted_p_value")
        method = rec.get("multiplicity_method")
        if adj_p is None:
            statuses[rid] = {"checked": False, "status": "not_applicable"}
            continue
        p_val = rec.get("p_value")
        if p_val is not None and float(adj_p) + 1e-12 < float(p_val):
            fail(
                "effect_multiplicity_mismatch",
                f"effect_record '{rid}' adjusted_p_value={adj_p} cannot be smaller than unadjusted p_value={p_val}",
            )
        if method in ("bonferroni", "holm", "bh_fdr"):
            groups.setdefault((method, rec.get("family_size")), []).append(rec)
            statuses[rid] = {"checked": False, "status": "pending_family"}
        else:
            statuses[rid] = {"checked": True, "status": "bounds_only"}

    for (method, fam_size), group in groups.items():
        m = fam_size if fam_size is not None else (len(group) if len(group) >= 2 else None)
        if m is None:
            for rec in group:
                statuses[rec["id"]] = {"checked": False, "status": "unassessed", "reason": "family_size_unknown"}
            continue
        if method == "bonferroni":
            for rec in group:
                p_val = rec.get("p_value")
                adj_p = rec.get("adjusted_p_value")
                if p_val is None or adj_p is None:
                    statuses[rec["id"]] = {"checked": False, "status": "unassessed"}
                    continue
                d_adj = _inferred_decimals(adj_p)
                tol = max(1e-5, 0.5 * (10.0 ** (-min(6, d_adj))) + 1e-9)
                expected = min(1.0, m * float(p_val))
                if abs(float(adj_p) - expected) > tol:
                    fail(
                        "effect_multiplicity_mismatch",
                        f"effect_record '{rec['id']}' Bonferroni adjusted_p_value={adj_p} mismatches m={m} * p={p_val} (expected {expected:.6g})",
                    )
                statuses[rec["id"]] = {"checked": True, "status": "pass", "expected": expected}
        elif method in ("holm", "bh_fdr"):
            if len(group) == m and all(rec.get("p_value") is not None for rec in group):
                indexed = sorted(enumerate(group), key=lambda item: float(item[1]["p_value"]))
                computed = [0.0] * m
                if method == "holm":
                    running = 0.0
                    for rank, (_, rec) in enumerate(indexed):
                        cand = min(1.0, (m - rank) * float(rec["p_value"]))
                        running = max(running, cand)
                        computed[rank] = running
                else:
                    running = 1.0
                    for rank in range(m - 1, -1, -1):
                        rec = indexed[rank][1]
                        cand = min(1.0, (m * float(rec["p_value"])) / (rank + 1))
                        running = min(running, cand)
                        computed[rank] = running
                for rank, (_, rec) in enumerate(indexed):
                    adj_p = float(rec["adjusted_p_value"])
                    expected = computed[rank]
                    d_adj = _inferred_decimals(adj_p)
                    tol = max(1e-5, 0.5 * (10.0 ** (-min(6, d_adj))) + 1e-9)
                    if abs(adj_p - expected) > tol:
                        fail(
                            "effect_multiplicity_mismatch",
                            f"effect_record '{rec['id']}' {method} adjusted_p_value={adj_p} mismatches m={m} computed value {expected:.6g}",
                        )
                    statuses[rec["id"]] = {"checked": True, "status": "pass", "expected": expected}
            else:
                for rec in group:
                    statuses[rec["id"]] = {"checked": False, "status": "unassessed", "reason": "partial_family_only"}
    return statuses


def _check_interaction_contrasts(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id = {rec["id"]: rec for rec in records}
    statuses: dict[str, dict[str, Any]] = {}
    for rec in records:
        rid = rec["id"]
        ic = rec.get("interaction_contrast")
        if ic is None:
            statuses[rid] = {"checked": False, "status": "not_applicable"}
            continue
        id1, id2 = ic["record_ids"]
        if id1 not in by_id or id2 not in by_id:
            missing = [x for x in (id1, id2) if x not in by_id]
            fail("unknown_reference", f"effect_record '{rid}' interaction_contrast references unknown sibling record(s): {missing}")
        r1, r2 = by_id[id1], by_id[id2]
        if r1["metric"] != rec["metric"] or r2["metric"] != rec["metric"] or r1.get("scale") != rec.get("scale") or r2.get("scale") != rec.get("scale"):
            fail("effect_interaction_mismatch", f"effect_record '{rid}' interaction_contrast requires matching metric and scale across siblings")
        est = float(rec["estimate"])
        est1 = float(r1["estimate"])
        est2 = float(r2["estimate"])
        is_ratio = rec["metric"] in RATIO_METRICS
        expected_est = (est1 / est2) if is_ratio else (est1 - est2)
        d_est = rec.get("decimals") if rec.get("decimals") is not None else min(4, _inferred_decimals(est))
        tol_est = max(0.02 if is_ratio else 1e-4, 0.5 * (10.0 ** (-d_est)) + 1e-6)
        if abs(est - expected_est) > tol_est:
            fail(
                "effect_interaction_mismatch",
                f"effect_record '{rid}' estimate={est} does not match sibling interaction ({id1} vs {id2}: expected {expected_est:.4g})",
            )
        if ic["dependence"] != "independent":
            statuses[rid] = {"checked": True, "status": "point_only_dependence_unknown", "expected_estimate": expected_est}
            continue
        req_method = "log_wald" if is_ratio else "wald"
        if (
            r1.get("inference_method") != req_method
            or r2.get("inference_method") != req_method
            or r1.get("ci_low") is None
            or r1.get("ci_high") is None
            or r2.get("ci_low") is None
            or r2.get("ci_high") is None
        ):
            statuses[rid] = {"checked": True, "status": "point_only_missing_sibling_wald_ci", "expected_estimate": expected_est}
            continue

        def _wald_se(item: dict[str, Any]) -> float:
            lvl = float(item.get("ci_level") if item.get("ci_level") is not None else 0.95)
            z = _norm_ppf(1.0 - (1.0 - lvl) / 2.0)
            lo = math.log(float(item["ci_low"])) if is_ratio else float(item["ci_low"])
            hi = math.log(float(item["ci_high"])) if is_ratio else float(item["ci_high"])
            return 0.5 * (hi - lo) / z

        se_int = math.hypot(_wald_se(r1), _wald_se(r2))
        if se_int <= 0.0:
            statuses[rid] = {"checked": True, "status": "point_only", "expected_estimate": expected_est}
            continue
        delta_t = math.log(expected_est) if is_ratio else expected_est
        z_int = abs(delta_t) / se_int
        p_int = math.erfc(z_int / math.sqrt(2.0))
        if rec.get("p_value") is not None:
            p_rep = float(rec["p_value"])
            z_rep = _two_sided_z(p_rep) if p_rep > 0.0 else math.inf
            if abs(z_rep - z_int) > 0.75:
                fail(
                    "effect_interaction_mismatch",
                    f"effect_record '{rid}' interaction p_value={p_rep} (z={z_rep:.2f}) contradicts independent-subgroup Wald test (z={z_int:.2f}, p={p_int:.4g})",
                )
        if rec.get("ci_low") is not None and rec.get("ci_high") is not None:
            lvl = float(rec.get("ci_level") if rec.get("ci_level") is not None else 0.95)
            z_c = _norm_ppf(1.0 - (1.0 - lvl) / 2.0)
            lo_t = math.log(float(rec["ci_low"])) if is_ratio else float(rec["ci_low"])
            hi_t = math.log(float(rec["ci_high"])) if is_ratio else float(rec["ci_high"])
            se_rep = 0.5 * (hi_t - lo_t) / z_c
            if abs(se_rep - se_int) > max(0.05, 0.35 * se_int):
                fail(
                    "effect_interaction_mismatch",
                    f"effect_record '{rid}' interaction CI width implies SE={se_rep:.4g}, contradicting independent SE={se_int:.4g}",
                )
        statuses[rid] = {"checked": True, "status": "pass", "expected_estimate": expected_est, "z_interaction": round(z_int, 4), "p_interaction": round(p_int, 6)}
    return statuses


def _normalize_numeric_text(text: str) -> str:
    text = text.replace("\u2212", "-")
    text = re.sub(r"(?<![0-9.])[\u2013\u2014](?=\.?\d)", "-", text)
    return text.replace("\u2013", " ").replace("\u2014", " ")


def _extract_decimals(text: str) -> list[Decimal]:
    norm = _normalize_numeric_text(text)
    values: list[Decimal] = []
    for match in _NUM_RE.finditer(norm):
        token = match.group(0).replace(",", "")
        try:
            values.append(Decimal(token))
        except InvalidOperation:
            continue
    return values


def _number_in_decimals(target: float, hay_decimals: list[Decimal]) -> bool:
    try:
        target_dec = Decimal(str(target))
    except InvalidOperation:
        target_dec = None
    tol = 1e-9 * max(1.0, abs(target))
    for item in hay_decimals:
        if target_dec is not None and item == target_dec:
            return True
        if abs(float(item) - target) <= tol:
            return True
    return False


def _matched_decimal_set(text: str, target: float) -> set[int]:
    """Return distinct literal decimal place counts of tokens in text matching target."""
    try:
        target_dec = Decimal(str(target))
    except InvalidOperation:
        target_dec = None
    tol = 1e-9 * max(1.0, abs(target))
    decs: set[int] = set()
    for item in _extract_decimals(text):
        if (target_dec is not None and item == target_dec) or abs(float(item) - target) <= tol:
            exp = item.as_tuple().exponent
            decs.add(min(12, -exp) if isinstance(exp, int) and exp < 0 else 0)
    return decs


def _infer_anchored_decimals(record: dict[str, Any], matched_text: str | None) -> int | None:
    """Infer unambiguous literal decimal precision from quote_substring or anchored evidence text."""
    if record.get("decimals") is not None or not matched_text:
        return None
    target = float(record["estimate"])
    quote_sub = record.get("quote_substring")
    if isinstance(quote_sub, str) and quote_sub.strip():
        sub_decs = _matched_decimal_set(quote_sub, target)
        if len(sub_decs) == 1:
            return next(iter(sub_decs))
        if len(sub_decs) > 1:
            return None
    text_decs = _matched_decimal_set(matched_text, target)
    if len(text_decs) == 1:
        return next(iter(text_decs))
    return None


def _match_anchored_text_candidate(
    record: dict[str, Any],
    evidence: dict[str, Any],
    snapshot_text: str | None = None,
    snapshot_bytes: bytes | None = None,
) -> tuple[bool, str | None, list[str]]:
    if record.get("artifact_binding") is not None:
        from .stat_import import verify_artifact_binding
        ok, missing = verify_artifact_binding(record, evidence, snapshot_text, snapshot_bytes=snapshot_bytes)
        return ok, None, missing
    snapshot_format = evidence.get("snapshot_artifact_format") if evidence.get("snapshot_artifact_basis") == "derived_from_snapshot" else None
    if evidence.get("artifact", {}).get("format") in ("statistics", "xlsx") or snapshot_format in ("statistics", "xlsx"):
        return False, None, ["statistical artifact requires a row/formula artifact_binding; use extract_effects"]
    # Older registrations may lack artifact metadata. Reclassify the retained full
    # source, never a selected quote, before permitting the documentary fallback.
    from .artifacts import recognizable_artifact
    source = snapshot_bytes
    if source is None:
        full_text = snapshot_text
        if full_text is None and evidence.get("source_text_status") in (None, "complete"):
            full_text = evidence.get("source_text")
        if isinstance(full_text, str):
            source = full_text.encode("utf-8")
    if recognizable_artifact(source or b"", evidence.get("path", "")) in ("statistics", "xlsx"):
        return False, None, ["statistical snapshot requires a row/formula artifact_binding; use extract_effects"]
    candidates = [
        text
        for text in (
            evidence.get("quote"),
            snapshot_text,
            (evidence.get("excerpt_window") or {}).get("text") if isinstance(evidence.get("excerpt_window"), dict) else None,
        )
        if isinstance(text, str) and text.strip()
    ]
    if not candidates:
        return False, None, ["no quote or snapshot text available for evidence_id"]

    quote_sub = record.get("quote_substring")
    required_nums: list[tuple[str, float]] = [("estimate", float(record["estimate"]))]
    if record.get("ci_low") is not None and record.get("ci_high") is not None:
        required_nums.append(("ci_low", float(record["ci_low"])))
        required_nums.append(("ci_high", float(record["ci_high"])))
    if record.get("p_value") is not None:
        required_nums.append(("p_value", float(record["p_value"])))

    best_missing: list[str] | None = None
    for text in candidates:
        missing: list[str] = []
        if quote_sub is not None:
            sub_norm = " ".join(quote_sub.split())
            hay_norm = " ".join(text.split())
            if sub_norm not in hay_norm:
                missing.append("quote_substring")
        hay_decimals = _extract_decimals(text)
        for label, num in required_nums:
            if not _number_in_decimals(num, hay_decimals):
                missing.append(f"{label}={num:g}")
        if not missing:
            return True, text, []
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
    return False, None, best_missing or ["unmatched"]


def _record_is_anchored(
    record: dict[str, Any],
    evidence: dict[str, Any],
    snapshot_text: str | None = None,
) -> tuple[bool, list[str]]:
    anchored, _, missing = _match_anchored_text_candidate(record, evidence, snapshot_text)
    return anchored, missing


def _record_crosses_null(record: dict[str, Any]) -> bool:
    direction = record.get("direction")
    if direction == "null":
        return True
    ci_low = record.get("ci_low")
    ci_high = record.get("ci_high")
    if direction in ("non_inferior", "equivalence"):
        explicit_null = record.get("null_value")
        if explicit_null is None or ci_low is None or ci_high is None:
            return False
        margin = float(explicit_null)
        low = float(ci_low)
        high = float(ci_high)
        metric = record.get("metric")
        beneficial_if = record.get("beneficial_if")
        if direction == "non_inferior":
            if beneficial_if == "below_null":
                return high >= margin
            if beneficial_if == "above_null":
                return low <= margin
            metric_null = 1.0 if metric in RATIO_METRICS else 0.0 if metric in DIFFERENCE_METRICS else None
            if metric_null is not None:
                if margin > metric_null:
                    return high >= margin
                if margin < metric_null:
                    return low <= margin
                return low <= margin <= high
            return False
        if metric in DIFFERENCE_METRICS:
            abs_margin = abs(margin)
            if abs_margin <= 0.0:
                return False
            return low <= -abs_margin or high >= abs_margin
        if metric in RATIO_METRICS:
            if margin <= 0.0 or margin == 1.0:
                return False
            lo_bound = min(margin, 1.0 / margin)
            hi_bound = max(margin, 1.0 / margin)
            return low <= lo_bound or high >= hi_bound
        if beneficial_if == "below_null":
            return high >= margin
        if beneficial_if == "above_null":
            return low <= margin
        return False
    null_val = _effective_null(record)
    if null_val is not None and ci_low is not None and ci_high is not None:
        return float(ci_low) <= float(null_val) <= float(ci_high)
    return False


def _direction_conflicts_polarity(record: dict[str, Any]) -> bool:
    beneficial_if = record.get("beneficial_if")
    null_val = _effective_null(record)
    direction = record["direction"]
    if beneficial_if is None or null_val is None or direction not in ("benefit", "harm"):
        return False
    est = float(record["estimate"])
    if beneficial_if == "below_null":
        return (direction == "benefit" and est >= null_val) or (direction == "harm" and est <= null_val)
    return (direction == "benefit" and est <= null_val) or (direction == "harm" and est >= null_val)


def _strictly_supports_benefit(record: dict[str, Any]) -> bool:
    if record["endpoint_role"] not in PRIMARY_EFFECT_ROLES:
        return False
    direction = record["direction"]
    if direction not in ("benefit", "higher_better", "lower_better"):
        return False
    if record.get("claim_direction") not in (None, direction):
        return False
    if _direction_conflicts_polarity(record):
        return False
    null_val = _effective_null(record)
    ci_low = record.get("ci_low")
    ci_high = record.get("ci_high")
    if null_val is None or ci_low is None or ci_high is None:
        return False
    low = float(ci_low)
    high = float(ci_high)
    est = float(record["estimate"])
    if low <= null_val <= high:
        return False
    beneficial_if = record.get("beneficial_if")
    if beneficial_if == "below_null" and not (high < null_val and est < null_val):
        return False
    if beneficial_if == "above_null" and not (low > null_val and est > null_val):
        return False
    if direction == "higher_better" and not (low > null_val and est > null_val):
        return False
    if direction == "lower_better" and not (high < null_val and est < null_val):
        return False
    ci_level = float(record.get("ci_level") if record.get("ci_level") is not None else 0.95)
    alpha = 1.0 - ci_level
    if record.get("p_value") is not None and float(record["p_value"]) >= alpha:
        return False
    if record.get("adjusted_p_value") is not None and float(record["adjusted_p_value"]) >= alpha:
        return False
    return True


def validate_effect_records(records: Any, known_evidence: set[str] | tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    """Validate structure, bounds, P-value vs CI compatibility, and GRIM/granularity."""
    items = array(records, "effect_records", minimum=0, maximum=MAX_EFFECT_RECORDS)
    known = set(known_evidence)
    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []

    for idx, raw in enumerate(items):
        prefix = f"effect_records[{idx}]"
        rec = obj(raw, prefix)
        fields(rec, ALLOWED_EFFECT_KEYS, REQUIRED_EFFECT_KEYS, prefix)

        rec_id = _non_empty_text(rec["id"], f"{prefix}.id", maximum=200)
        if rec_id in seen_ids:
            fail("duplicate_id", f"duplicate effect_record id '{rec_id}'")
        seen_ids.add(rec_id)

        endpoint = _non_empty_text(rec["endpoint"], f"{prefix}.endpoint", maximum=500)
        role = enum(rec["endpoint_role"], EFFECT_RECORD_ROLES, f"{prefix}.endpoint_role")
        metric = enum(rec["metric"], EFFECT_METRICS, f"{prefix}.metric")
        estimate = _finite_number(rec["estimate"], f"{prefix}.estimate")
        direction = enum(rec["direction"], EFFECT_DIRECTIONS, f"{prefix}.direction")
        ev_id = _non_empty_text(rec["evidence_id"], f"{prefix}.evidence_id", maximum=200)
        if ev_id not in known:
            fail("unknown_reference", f"{prefix}.evidence_id references unknown evidence '{ev_id}'")

        scale = "unit"
        if rec.get("scale") is not None:
            scale = enum(rec["scale"], EFFECT_SCALES, f"{prefix}.scale")

        null_value: float | None = None
        if rec.get("null_value") is not None:
            null_value = _finite_number(rec["null_value"], f"{prefix}.null_value")

        has_ci_low = rec.get("ci_low") is not None
        has_ci_high = rec.get("ci_high") is not None
        if has_ci_low != has_ci_high:
            fail("effect_interval_inconsistent", f"{prefix} must supply both ci_low and ci_high or omit both")

        ci_low: float | None = None
        ci_high: float | None = None
        if has_ci_low and has_ci_high:
            ci_low = _finite_number(rec["ci_low"], f"{prefix}.ci_low")
            ci_high = _finite_number(rec["ci_high"], f"{prefix}.ci_high")
            if ci_low > estimate or estimate > ci_high or ci_low > ci_high:
                fail(
                    "effect_interval_inconsistent",
                    f"{prefix} interval [{ci_low}, {ci_high}] must satisfy ci_low <= estimate ({estimate}) <= ci_high",
                )

        ci_level: float | None = None
        if rec.get("ci_level") is not None:
            ci_level = _finite_number(rec["ci_level"], f"{prefix}.ci_level")
            if not (0.0 < ci_level < 1.0):
                fail("invalid_value", f"{prefix}.ci_level must satisfy 0 < ci_level < 1")

        p_value: float | None = None
        if rec.get("p_value") is not None:
            p_value = _finite_number(rec["p_value"], f"{prefix}.p_value")
            if not (0.0 <= p_value <= 1.0):
                fail("invalid_value", f"{prefix}.p_value must satisfy 0.0 <= p_value <= 1.0")

        n_val: int | None = None
        if rec.get("n") is not None:
            n_val = _int_value(rec["n"], f"{prefix}.n", minimum=1)

        events_val: int | None = None
        if rec.get("events") is not None:
            events_val = _int_value(rec["events"], f"{prefix}.events", minimum=0)
            if n_val is not None and events_val > n_val and (metric in ("proportion", "accuracy") or rec.get("count_basis") == "unweighted_binary"):
                fail("invalid_value", f"{prefix}.events ({events_val}) cannot exceed n ({n_val})")

        decimals_val: int | None = None
        if rec.get("decimals") is not None:
            decimals_val = _int_value(rec["decimals"], f"{prefix}.decimals", minimum=0, maximum=8)

        beneficial_if: str | None = None
        if rec.get("beneficial_if") is not None:
            beneficial_if = enum(rec["beneficial_if"], EFFECT_BENEFICIAL_POLARITY, f"{prefix}.beneficial_if")

        quote_sub: str | None = None
        if rec.get("quote_substring") is not None:
            quote_sub = _non_empty_text(rec["quote_substring"], f"{prefix}.quote_substring", maximum=2000)

        notes_text: str | None = None
        if rec.get("notes") is not None:
            notes_text = string(rec["notes"], f"{prefix}.notes", maximum=4000)

        cohort_id: str | None = None
        if rec.get("cohort_id") is not None:
            cohort_id = _non_empty_text(rec["cohort_id"], f"{prefix}.cohort_id", maximum=200)

        if metric in RATIO_METRICS:
            if estimate <= 0.0 or (ci_low is not None and ci_low <= 0.0) or (ci_high is not None and ci_high <= 0.0):
                fail("invalid_ratio_effect", f"{prefix} ratio metric '{metric}' requires strictly positive estimate and CI bounds")
            if null_value is not None and null_value <= 0.0:
                fail("invalid_ratio_effect", f"{prefix} ratio metric '{metric}' requires strictly positive null_value")

        if metric in PROPORTION_METRICS:
            upper = 100.0 if scale == "percentage" else 1.0
            if not (0.0 <= estimate <= upper):
                fail("invalid_value", f"{prefix} proportion metric '{metric}' (scale={scale}) must lie in [0, {upper:g}]")
            if ci_low is not None and ci_high is not None and (ci_low < 0.0 or ci_high > upper):
                fail("invalid_value", f"{prefix} proportion metric '{metric}' CI [{ci_low}, {ci_high}] must lie in [0, {upper:g}]")

        normalized = {
            "id": rec_id,
            "endpoint": endpoint,
            "endpoint_role": role,
            "metric": metric,
            "estimate": rec["estimate"],
            "direction": direction,
            "evidence_id": ev_id,
        }
        if null_value is not None:
            normalized["null_value"] = null_value
        if ci_level is not None:
            normalized["ci_level"] = ci_level
        if ci_low is not None:
            normalized["ci_low"] = ci_low
            normalized["ci_high"] = ci_high
        if p_value is not None:
            normalized["p_value"] = p_value
        if n_val is not None:
            normalized["n"] = n_val
        if events_val is not None:
            normalized["events"] = events_val
        if decimals_val is not None:
            normalized["decimals"] = decimals_val
        if "scale" in rec and rec["scale"] is not None:
            normalized["scale"] = scale
        if beneficial_if is not None:
            normalized["beneficial_if"] = beneficial_if
        for key, choices in (("inference_method", INFERENCE_METHODS), ("count_basis", COUNT_BASES), ("claim_direction", EFFECT_DIRECTIONS)):
            if rec.get(key) is not None:
                normalized[key] = enum(rec[key], choices, f"{prefix}.{key}")
        if normalized.get("inference_method") == "log_wald":
            vals = [estimate, _effective_null(normalized), ci_low, ci_high]
            if any(v is not None and v <= 0.0 for v in vals):
                fail("invalid_value", f"{prefix}.inference_method='log_wald' requires positive estimate, null and CI")
        if quote_sub is not None:
            normalized["quote_substring"] = quote_sub
        if notes_text is not None:
            normalized["notes"] = notes_text
        if cohort_id is not None:
            normalized["cohort_id"] = cohort_id

        if "artifact_binding" in rec:
            binding = obj(rec["artifact_binding"], f"{prefix}.artifact_binding")
            required_b = {"version", "format", "source_sha256", "record_index", "column_map"}
            allowed_b = required_b | {"sheet"}
            fields(binding, allowed_b, required_b, f"{prefix}.artifact_binding")
            if type(binding["version"]) is not int or binding["version"] != 1:
                fail("invalid_value", "artifact_binding.version must be 1")
            enum(binding["format"], ("csv", "tsv", "json", "markdown", "confusion_json", "contingency_json", "xlsx"), "artifact_binding.format")
            if not isinstance(binding["source_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", binding["source_sha256"]):
                fail("invalid_value", "artifact_binding requires lowercase SHA-256")
            _int_value(binding["record_index"], "artifact_binding.record_index", minimum=0, maximum=MAX_ARTIFACT_RECORD_INDEX)
            columns = obj(binding["column_map"], "artifact_binding.column_map")
            if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in columns.items()):
                fail("invalid_value", "artifact_binding.column_map must map strings to column names")
            if "sheet" in binding:
                _non_empty_text(binding["sheet"], f"{prefix}.artifact_binding.sheet", maximum=200)
            normalized["artifact_binding"] = dict(binding)

        if rec.get("df") is not None:
            normalized["df"] = _int_value(rec["df"], f"{prefix}.df", minimum=1)

        if rec.get("adjusted_p_value") is not None:
            adj_p = _finite_number(rec["adjusted_p_value"], f"{prefix}.adjusted_p_value")
            if not (0.0 <= adj_p <= 1.0):
                fail("invalid_value", f"{prefix}.adjusted_p_value must satisfy 0.0 <= adjusted_p_value <= 1.0")
            if p_value is not None and adj_p + 1e-12 < p_value:
                fail(
                    "effect_multiplicity_mismatch",
                    f"effect_record '{rec_id}' adjusted_p_value={adj_p} cannot be smaller than unadjusted p_value={p_value}",
                )
            normalized["adjusted_p_value"] = adj_p

        if rec.get("multiplicity_method") is not None:
            normalized["multiplicity_method"] = enum(rec["multiplicity_method"], MULTIPLICITY_METHODS, f"{prefix}.multiplicity_method")

        if rec.get("family_size") is not None:
            normalized["family_size"] = _int_value(rec["family_size"], f"{prefix}.family_size", minimum=1)

        if rec.get("contingency") is not None:
            cont = obj(rec["contingency"], f"{prefix}.contingency")
            if {"treated_events", "treated_n", "control_events", "control_n"} <= cont.keys():
                fields(cont, {"treated_events", "treated_n", "control_events", "control_n"}, {"treated_events", "treated_n", "control_events", "control_n"}, f"{prefix}.contingency")
                a = _int_value(cont["treated_events"], f"{prefix}.contingency.treated_events", minimum=0)
                n1 = _int_value(cont["treated_n"], f"{prefix}.contingency.treated_n", minimum=1)
                c = _int_value(cont["control_events"], f"{prefix}.contingency.control_events", minimum=0)
                n0 = _int_value(cont["control_n"], f"{prefix}.contingency.control_n", minimum=1)
                if a > n1 or c > n0:
                    fail("invalid_value", f"{prefix}.contingency events cannot exceed group sample size")
                normalized["contingency"] = {"treated_events": a, "treated_n": n1, "control_events": c, "control_n": n0}
            elif {"a", "b", "c", "d"} <= cont.keys():
                fields(cont, {"a", "b", "c", "d"}, {"a", "b", "c", "d"}, f"{prefix}.contingency")
                ca = _int_value(cont["a"], f"{prefix}.contingency.a", minimum=0)
                cb = _int_value(cont["b"], f"{prefix}.contingency.b", minimum=0)
                cc = _int_value(cont["c"], f"{prefix}.contingency.c", minimum=0)
                cd = _int_value(cont["d"], f"{prefix}.contingency.d", minimum=0)
                if ca + cb < 1 or cc + cd < 1:
                    fail("invalid_value", f"{prefix}.contingency groups must be non-empty")
                normalized["contingency"] = {"a": ca, "b": cb, "c": cc, "d": cd}
            else:
                fail("missing_field", f"{prefix}.contingency requires {{treated_events, treated_n, control_events, control_n}} or {{a, b, c, d}}")
            _check_contingency_consistency(normalized)

        if rec.get("interaction_contrast") is not None:
            ic = obj(rec["interaction_contrast"], f"{prefix}.interaction_contrast")
            fields(ic, {"record_ids", "dependence"}, {"record_ids"}, f"{prefix}.interaction_contrast")
            rids = array(ic["record_ids"], f"{prefix}.interaction_contrast.record_ids", minimum=2, maximum=2)
            id1 = _non_empty_text(rids[0], f"{prefix}.interaction_contrast.record_ids[0]", maximum=200)
            id2 = _non_empty_text(rids[1], f"{prefix}.interaction_contrast.record_ids[1]", maximum=200)
            if id1 == id2 or id1 == rec_id or id2 == rec_id:
                fail("invalid_value", f"{prefix}.interaction_contrast.record_ids must name two distinct sibling records")
            dep = enum(ic.get("dependence", "unknown"), ("independent", "unknown"), f"{prefix}.interaction_contrast.dependence")
            normalized["interaction_contrast"] = {"record_ids": [id1, id2], "dependence": dep}

        _check_pvalue_ci_compatibility(normalized)
        _check_grim_granularity(normalized)
        validated.append(normalized)

    _check_multiplicity_consistency(validated)
    _check_interaction_contrasts(validated)
    return validated


def verify_effect_computations(
    claim: dict[str, Any],
    decision: dict[str, Any] | None,
    evidence_by_id: dict[str, dict[str, Any]],
    snapshot_texts: dict[str, str] | None = None,
    *,
    snapshot_bytes: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Run deterministic computable verification across a claim's effect_records."""
    raw_records = claim.get("effect_records")
    if not raw_records:
        return {
            "record_count": 0,
            "primary_count": 0,
            "non_primary_count": 0,
            "checks": [],
            "underclaim_advisory": None,
        }

    validated = validate_effect_records(raw_records, set(evidence_by_id))
    mult_statuses = _check_multiplicity_consistency(validated)
    inter_statuses = _check_interaction_contrasts(validated)
    verdict = decision.get("verdict") if decision else None
    is_positive = verdict in ("supported", "partially_supported")
    decision_refs = set(decision.get("evidence_ids") or ()) if decision else set()

    checks: list[dict[str, Any]] = []
    primary_records: list[dict[str, Any]] = []
    supporting_primary: list[dict[str, Any]] = []

    for rec in validated:
        ev_id = rec["evidence_id"]
        ev = evidence_by_id[ev_id]
        snap_text = snapshot_texts.get(ev_id) if snapshot_texts else None
        snap_raw = snapshot_bytes.get(ev_id) if snapshot_bytes else None
        anchored, matched_text, missing_tokens = _match_anchored_text_candidate(rec, ev, snap_text, snap_raw)
        pval_ci = _check_pvalue_ci_compatibility(rec)
        inferred_dec = _infer_anchored_decimals(rec, matched_text) if anchored else None
        grim = _check_grim_granularity(rec, inferred_decimals=inferred_dec)
        cont_chk = _check_contingency_consistency(rec)
        mult_chk = mult_statuses.get(rec["id"], {"status": "not_applicable"})
        inter_chk = inter_statuses.get(rec["id"], {"status": "not_applicable"})
        crosses_null = _record_crosses_null(rec)
        dir_conflict = _direction_conflicts_polarity(rec)
        no_ci_nonsig = (
            rec.get("ci_low") is None
            and rec.get("p_value") is not None
            and rec["direction"] in ("benefit", "harm", "higher_better", "lower_better")
            and float(rec["p_value"]) >= _record_alpha(rec)
        )
        fails_mult = (
            rec.get("adjusted_p_value") is not None
            and rec["direction"] in ("benefit", "harm", "higher_better", "lower_better", "non_inferior", "equivalence")
            and float(rec["adjusted_p_value"]) >= _record_alpha(rec)
        )

        if is_positive and not anchored:
            fail(
                "unanchored_effect_record",
                f"effect_record '{rec['id']}' numbers/substring {missing_tokens} are not anchored in evidence '{ev_id}'",
            )
        if is_positive and dir_conflict:
            fail(
                "effect_direction_mismatch",
                f"effect_record '{rec['id']}' direction '{rec['direction']}' conflicts with estimate={rec['estimate']}, null_value={_effective_null(rec)}, beneficial_if={rec.get('beneficial_if')}",
            )
        expected_direction = rec.get("claim_direction")
        if (
            verdict == "supported"
            and rec["endpoint_role"] in PRIMARY_EFFECT_ROLES
            and crosses_null
            and (
                expected_direction in ("benefit", "harm", "higher_better", "lower_better", "non_inferior", "equivalence")
                or (rec["direction"] in ("non_inferior", "equivalence") and expected_direction is None)
            )
        ):
            fail("primary_effect_crosses_null", f"effect_record '{rec['id']}' interval includes null and cannot establish declared claim_direction '{expected_direction or rec['direction']}'")
        if verdict == "supported" and rec["endpoint_role"] in PRIMARY_EFFECT_ROLES and no_ci_nonsig:
            fail(
                "primary_effect_crosses_null",
                f"effect_record '{rec['id']}' reports non-significant p_value={rec['p_value']} >= alpha={_record_alpha(rec):g} without CI exclusion and cannot establish '{expected_direction or rec['direction']}'",
            )
        if verdict == "supported" and rec["endpoint_role"] in PRIMARY_EFFECT_ROLES and fails_mult:
            fail(
                "primary_effect_fails_multiplicity",
                f"effect_record '{rec['id']}' adjusted_p_value={rec['adjusted_p_value']} >= alpha={_record_alpha(rec):g} fails multiplicity correction",
            )
        if is_positive and expected_direction is not None and expected_direction != rec["direction"]:
            fail("effect_direction_mismatch", f"effect_record '{rec['id']}' observed direction '{rec['direction']}' does not support declared claim_direction '{expected_direction}'")

        if rec["endpoint_role"] in PRIMARY_EFFECT_ROLES:
            primary_records.append(rec)
            if not crosses_null and not no_ci_nonsig and not fails_mult and rec["direction"] != "neutral":
                supporting_primary.append(rec)

        checks.append({
            "id": rec["id"],
            "endpoint": rec["endpoint"],
            "endpoint_role": rec["endpoint_role"],
            "metric": rec["metric"],
            "estimate": rec["estimate"],
            "direction": rec["direction"],
            "evidence_id": ev_id,
            "null_value": _effective_null(rec),
            "anchored": anchored,
            "crosses_null": crosses_null,
            "direction_conflict": dir_conflict,
            "claim_direction": expected_direction,
            "claim_alignment": "unassessed" if expected_direction is None else "matched" if expected_direction == rec["direction"] else "conflict",
            "pvalue_ci_check": pval_ci["status"],
            "grim_granularity_check": grim["status"],
            "contingency_check": cont_chk["status"],
            "multiplicity_check": "fails_alpha" if fails_mult else mult_chk["status"],
            "interaction_check": inter_chk["status"],
        })

    if verdict == "supported" and primary_records:
        if supporting_primary:
            needed_primary_refs = {rec["evidence_id"] for rec in supporting_primary}
            if not (needed_primary_refs <= decision_refs):
                missing_refs = sorted(needed_primary_refs - decision_refs)
                fail(
                    "uncited_primary_effect",
                    f"supported verdict must cite primary/benchmark effect evidence_id(s): {missing_refs}",
                )
        else:
            needed_primary_refs = {rec["evidence_id"] for rec in primary_records}
            if not (needed_primary_refs & decision_refs):
                fail(
                    "uncited_primary_effect",
                    f"supported verdict must cite primary/benchmark effect evidence_id(s): {sorted(needed_primary_refs)}",
                )

    underclaim_advisory: dict[str, Any] | None = None
    if (
        verdict == "unsupported"
        and primary_records
        and all(
            c["anchored"]
            for c, r in zip(checks, validated)
            if r["endpoint_role"] in PRIMARY_EFFECT_ROLES
        )
        and all(_strictly_supports_benefit(rec) for rec in primary_records)
    ):
        underclaim_advisory = {
            "primary_evidence_ids": sorted({rec["evidence_id"] for rec in primary_records}),
            "primary_record_ids": [rec["id"] for rec in primary_records],
            "message": "Claim was adjudicated 'unsupported' while all primary/benchmark effect_records strictly exclude null in favor of stated benefit.",
        }

    return {
        "record_count": len(validated),
        "primary_count": len(primary_records),
        "non_primary_count": len(validated) - len(primary_records),
        "checks": checks,
        "underclaim_advisory": underclaim_advisory,
    }
