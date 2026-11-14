"""Pure-stdlib structured effect records and computable verification checks."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from .contracts import ContractError, array, enum, fail, fields, obj, string

MAX_EFFECT_RECORDS = 50
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

PRIMARY_EFFECT_ROLES = ("primary", "benchmark")
REQUIRED_EFFECT_KEYS = {"id", "endpoint", "endpoint_role", "metric", "estimate", "direction", "evidence_id"}
OPTIONAL_EFFECT_KEYS = {
    "null_value", "ci_level", "ci_low", "ci_high", "p_value",
    "n", "events", "decimals", "scale", "beneficial_if", "quote_substring", "notes",
    "inference_method", "count_basis", "claim_direction",
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
    """Check only explicitly declared matching two-sided Wald CI/test pairs."""
    p_value = record.get("p_value")
    ci_low = record.get("ci_low")
    ci_high = record.get("ci_high")
    null_val = _effective_null(record)
    if p_value is None or ci_low is None or ci_high is None or null_val is None:
        return {"checked": False, "status": "not_applicable"}
    method = record.get("inference_method", "unknown")
    if method not in ("wald", "log_wald"):
        return {"checked": False, "status": "unassessed", "reason": "matching_wald_method_not_declared"}

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
        return {"checked": True, "status": "pass", "z_est": None, "z_p": _two_sided_z(p_val)}

    z_ci = _norm_ppf(1.0 - alpha / 2.0)
    se = half_width / z_ci
    z_est = abs(est_t - null_t) / se

    if p_val == 0.0:
        p_wald = math.erfc(z_est / math.sqrt(2.0))
        if not ci_excludes_null or p_wald > 0.01:
            fail(
                "effect_pvalue_ci_mismatch",
                f"effect_record '{record['id']}' reports p_value=0.0 which contradicts CI [{low}, {high}] vs null {null_val} (Wald p={p_wald:.4g})",
            )
        return {"checked": True, "status": "pass", "z_est": round(z_est, 4), "z_p": None}

    z_p = _two_sided_z(p_val)
    z_diff = abs(z_est - z_p)

    if ci_excludes_null and p_val > alpha and z_diff > 0.65:
        fail(
            "effect_pvalue_ci_mismatch",
            f"effect_record '{record['id']}' CI [{low}, {high}] excludes null {null_val} (alpha={alpha:.3g}, z={z_est:.2f}) yet p_value={p_val} (z={z_p:.2f})",
        )
    if (not ci_excludes_null) and p_val < alpha and z_diff > 0.65:
        fail(
            "effect_pvalue_ci_mismatch",
            f"effect_record '{record['id']}' CI [{low}, {high}] includes null {null_val} (alpha={alpha:.3g}, z={z_est:.2f}) yet p_value={p_val} (z={z_p:.2f})",
        )
    if z_diff > max(1.5, 0.60 * max(z_est, z_p)):
        fail(
            "effect_pvalue_ci_mismatch",
            f"effect_record '{record['id']}' CI [{low}, {high}] (z={z_est:.2f}) is incompatible with p_value={p_val} (z={z_p:.2f})",
        )
    return {"checked": True, "status": "pass", "z_est": round(z_est, 4), "z_p": round(z_p, 4)}


def _check_grim_granularity(record: dict[str, Any]) -> dict[str, Any]:
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

    if events is not None and n is not None:
        d = decimals if decimals is not None else _inferred_decimals(record["estimate"])
        tol = 0.5 * (10.0 ** (-d)) + 1e-9
        expected = (events / n) * factor
        est = float(record["estimate"])
        if abs(expected - est) > tol:
            fail(
                "effect_granularity_mismatch",
                f"effect_record '{record['id']}' estimate={est} does not match events/n={events}/{n} ({expected:.6g}) within +/-{tol:.6g}",
            )
        return {"checked": True, "mode": "events_over_n", "status": "pass", "expected": expected}

    if n is not None and (decimals is not None or n <= 100):
        d = decimals if decimals is not None else _inferred_decimals(record["estimate"])
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


def _record_is_anchored(
    record: dict[str, Any],
    evidence: dict[str, Any],
    snapshot_text: str | None = None,
) -> tuple[bool, list[str]]:
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
        return False, ["no quote or snapshot text available for evidence_id"]

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
            return True, []
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
    return False, best_missing or ["unmatched"]


def _record_crosses_null(record: dict[str, Any]) -> bool:
    if record.get("direction") in ("non_inferior", "equivalence"):
        return False
    if record.get("direction") == "null":
        return True
    null_val = _effective_null(record)
    ci_low = record.get("ci_low")
    ci_high = record.get("ci_high")
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

        if rec.get("notes") is not None:
            string(rec["notes"], f"{prefix}.notes", maximum=4000)

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

        _check_pvalue_ci_compatibility(normalized)
        _check_grim_granularity(normalized)
        validated.append(normalized)

    return validated


def verify_effect_computations(
    claim: dict[str, Any],
    decision: dict[str, Any] | None,
    evidence_by_id: dict[str, dict[str, Any]],
    snapshot_texts: dict[str, str] | None = None,
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
        anchored, missing_tokens = _record_is_anchored(rec, ev, snap_text)
        pval_ci = _check_pvalue_ci_compatibility(rec)
        grim = _check_grim_granularity(rec)
        crosses_null = _record_crosses_null(rec)
        dir_conflict = _direction_conflicts_polarity(rec)

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
        if verdict == "supported" and rec["endpoint_role"] in PRIMARY_EFFECT_ROLES and crosses_null and expected_direction in ("benefit", "harm", "higher_better", "lower_better"):
            fail("primary_effect_crosses_null", f"effect_record '{rec['id']}' interval includes null and cannot establish declared claim_direction '{expected_direction}'")
        if is_positive and expected_direction is not None and expected_direction != rec["direction"]:
            fail("effect_direction_mismatch", f"effect_record '{rec['id']}' observed direction '{rec['direction']}' does not support declared claim_direction '{expected_direction}'")

        if rec["endpoint_role"] in PRIMARY_EFFECT_ROLES:
            primary_records.append(rec)
            if not crosses_null and rec["direction"] != "neutral":
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
