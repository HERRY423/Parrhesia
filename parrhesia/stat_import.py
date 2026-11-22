"""Bounded statistical-output parsing with row-bound, recomputable effect records."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys

from .binary_artifacts import list_xlsx_sheets
from .contracts import ContractError, enum, fail
from .effects import EFFECT_METRICS, contingency_ratio, validate_effect_records

STAT_FORMATS = ("auto", "csv", "tsv", "json", "markdown", "confusion_json", "contingency_json", "xlsx")
# Bound both enumeration and integer operand size before combinatorial work.
# Point estimates remain available when exact inference exceeds these limits.
MAX_FISHER_TOTAL = 20_000
MAX_FISHER_TABLES = 10_000
ALIASES = {
    "endpoint": ("endpoint", "term", "outcome", "variable", "parameter"),
    "estimate": ("estimate", "coef", "coefficient", "value"),
    "metric": ("metric", "measure"),
    "ci_low": ("ci_low", "conf.low", "ci_lower", "lower", "[0.025", "2.5 %"),
    "ci_high": ("ci_high", "conf.high", "ci_upper", "upper", "0.975]", "97.5 %"),
    "p_value": ("p_value", "p.value", "pvalue", "p", "P>|t|", "P>|z|", "Pr(>|t|)", "Pr(>|z|)"),
    "adjusted_p_value": ("adjusted_p_value", "adj_p_value", "adj.p.val", "p_adj", "padj", "p.adjust", "fdr", "q_value", "q.value"),
    "n": ("n", "nobs", "sample_size"),
    "df": ("df",),
    "ci_level": ("ci_level", "conf.level"),
    "null_value": ("null_value",),
    "scale": ("scale",), "inference_method": ("inference_method",),
    "multiplicity_method": ("multiplicity_method",),
    "family_size": ("family_size",),
}
_MISSING = {"", "na", "nan", "null", "none", "unknown", "n/a", "not_run"}


def strict_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("invalid_source", f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda x: fail("invalid_source", f"Nonfinite JSON value: {x}"))
    except (json.JSONDecodeError, RecursionError) as exc:
        fail("invalid_source", f"Malformed JSON: {exc}")


def _number(value, name: str):
    if value is None or (isinstance(value, str) and value.strip().lower() in _MISSING):
        return None
    if isinstance(value, bool):
        fail("invalid_source", f"{name} cannot be boolean")
    try:
        number = float(str(value).strip().replace("\u2212", "-"))
    except (ValueError, TypeError):
        fail("invalid_source", f"{name} is not an exact number: {value!r}; inequalities are not exact p-values")
    if not math.isfinite(number):
        fail("invalid_source", f"{name} must be finite")
    if name in ("n", "df", "family_size"):
        if number != int(number) or number < 1:
            fail("invalid_source", f"{name} must be a positive integer")
        return int(number)
    return number


def _resolve_format(path: str, format: str, text: str | None) -> str:
    if format not in STAT_FORMATS:
        fail("invalid_value", f"format must be one of {STAT_FORMATS}")
    if format != "auto":
        return format
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        return "xlsx"
    json_content = text is not None and text.lstrip().startswith(("{", "["))
    value = None
    if suffix == ".json" or json_content:
        assert text is not None
        try:
            value = strict_json(text)
        except ContractError:
            if suffix == ".json":
                raise
            # A table header can start with '['; only complete JSON wins over
            # an otherwise supported table suffix.
            json_content = False
    if suffix == ".json" or json_content:
        if isinstance(value, dict) and {"tp", "tn", "fp", "fn"} <= value.keys():
            return "confusion_json"
        if isinstance(value, dict) and ({"treated_events", "treated_n", "control_events", "control_n"} <= value.keys() or {"a", "b", "c", "d"} <= value.keys()):
            return "contingency_json"
        return "json"
    detected = {".csv": "csv", ".tsv": "tsv", ".md": "markdown"}.get(suffix)
    if not detected:
        fail("unsupported_format", "Statistics require CSV, TSV, JSON, XLSX, a Markdown table, or explicit format")
    return detected


def _table(text: str, format: str) -> list[tuple[dict, str]]:
    if format == "json":
        value = strict_json(text)
        rows = value.get("rows") if isinstance(value, dict) else value
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            fail("invalid_source", "JSON statistics require a row array or an object with rows")
        return [(row, f"rows[{i}]") for i, row in enumerate(rows)]
    if format == "markdown":
        lines = [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1) if "|" in line]
        if len(lines) < 3:
            fail("invalid_source", "Expected one Markdown table with header and separator")
        if not re.fullmatch(r"[\s|:\-]+", lines[1][1]):
            fail("invalid_source", "Markdown table separator missing")
        rows = [[s.strip() for s in line.strip("|").split("|")] for _, line in lines]
        header, data = rows[0], [(row, f"L{lines[i][0]}") for i, row in enumerate(rows[2:], 2)]
    else:
        reader = csv.reader(io.StringIO(text), delimiter="\t" if format == "tsv" else ",", strict=True)
        try:
            header = next(reader)
            data = [(row, f"L{reader.line_num}") for row in reader if row]
        except (StopIteration, csv.Error) as exc:
            fail("invalid_source", f"Empty or malformed table: {exc}")
        header = [h.strip() for h in header]
    if len(set(h.casefold() for h in header)) != len(header) or not all(header):
        fail("invalid_source", "Table headers must be nonempty and unique")
    result = []
    for row, locator in data:
        if len(row) != len(header):
            fail("invalid_source", f"Table width mismatch at {locator}; no columns are guessed")
        result.append((dict(zip(header, row)), locator))
    return result


def _row_record(row: dict, index: int, evidence_id: str, columns: dict) -> dict:
    estimate_col = None
    values = {}
    for name, aliases in ALIASES.items():
        keys = [columns[name]] if name in columns else [key for key in row if str(key).casefold() in {a.casefold() for a in aliases}]
        if len(keys) > 1:
            fail("ambiguous_columns", f"Multiple columns for {name}: {keys}; supply column_map")
        if keys:
            if keys[0] not in row:
                fail("invalid_source", f"Mapped column {keys[0]} is absent")
            values[name] = row[keys[0]]
            if name == "estimate":
                estimate_col = keys[0]
    endpoint = values.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        fail("invalid_source", "A row needs an explicit endpoint/term; no endpoint is invented")
    estimate = _number(values.get("estimate"), "estimate")
    if estimate is None:
        fail("missing_estimate", "Missing estimate retained as an unresolved row, never zero")
    # coef/broom outputs denote beta; a generic estimate with no scale is 'other'.
    raw_metric = values.get("metric")
    if raw_metric is None or str(raw_metric).strip().lower() in _MISSING:
        metric = "beta" if (estimate_col is not None and str(estimate_col).casefold() in ("coef", "coefficient")) else "other"
    else:
        matches = [m for m in EFFECT_METRICS if m.casefold() == str(raw_metric).strip().casefold()]
        if not matches:
            fail("invalid_source", f"Unsupported metric {raw_metric!r}; no effect scale is guessed")
        metric = matches[0]
    record = {"id": f"effect-{index + 1}", "endpoint": endpoint.strip(), "metric": metric,
              "estimate": estimate, "endpoint_role": "exploratory", "direction": "neutral", "evidence_id": evidence_id}
    for key in ("ci_low", "ci_high", "ci_level", "p_value", "adjusted_p_value", "n", "df", "family_size", "null_value"):
        value = _number(values.get(key), key)
        if value is not None:
            record[key] = value
    for key in ("scale", "inference_method", "multiplicity_method"):
        if values.get(key) is not None and str(values[key]).strip().lower() not in _MISSING:
            record[key] = str(values[key]).strip()
    return record


def _fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> tuple[float | None, dict | None]:
    """Bounded exact integer tail selection; never turn underflow into p=0.

    All tables have the same denominator C(total, m1), so integer weights
    select the two-sided tail without floating-point tie tolerances. Advance
    the weights by the hypergeometric recurrence rather than recomputing each
    binomial coefficient. Limits are a supported computation scope, not a
    statistical significance threshold.
    """
    n1 = a + b
    n0 = c + d
    m1 = a + c
    total = n1 + n0
    lo = max(0, m1 - n0)
    hi = min(m1, n1)
    support_size = hi - lo + 1
    if total > MAX_FISHER_TOTAL or support_size > MAX_FISHER_TABLES:
        return None, {
            "code": "fisher_work_limit", "field": "p_value",
            "message": "Fisher exact p-value not computed: bounded computation scope exceeded; point estimates retained.",
            "total_count": total, "support_size": support_size,
            "max_total_count": MAX_FISHER_TOTAL, "max_support_size": MAX_FISHER_TABLES,
        }
    denominator = math.comb(total, m1)
    observed = math.comb(n1, a) * math.comb(n0, c)
    weight = math.comb(n1, lo) * math.comb(n0, m1 - lo)
    numerator = 0
    for k in range(lo, hi + 1):
        if weight <= observed:
            numerator += weight
        if k < hi:
            weight = weight * (n1 - k) * (m1 - k) // ((k + 1) * (n0 - m1 + k + 1))
    p_value = numerator / denominator
    if p_value < sys.float_info.min:
        return None, {
            "code": "fisher_p_underflow", "field": "p_value",
            "message": "Exact Fisher probability is positive but below normal float precision; p_value omitted, never zero.",
            "log_p_value": math.log(numerator) - math.log(denominator),
            "log_base": "e", "log_precision": "floating_point_approximation",
            "p_upper_bound": sys.float_info.min,
        }
    return p_value, None


def _contingency(text: str, evidence_id: str) -> tuple[list[tuple[dict, str]], list[dict]]:
    value = strict_json(text)
    if not isinstance(value, dict):
        fail("invalid_source", "Contingency JSON must be an object with named 2x2 counts")
    endpoint = value.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        fail("invalid_source", "Contingency 2x2 table requires endpoint")
    if {"treated_events", "treated_n", "control_events", "control_n"} <= value.keys():
        for k in ("treated_events", "treated_n", "control_events", "control_n"):
            if type(value.get(k)) is not int or value[k] < 0:
                fail("invalid_source", f"{k} must be a nonnegative integer")
        a, n1, c, n0 = value["treated_events"], value["treated_n"], value["control_events"], value["control_n"]
        if n1 < 1 or n0 < 1 or a > n1 or c > n0:
            fail("invalid_source", "Contingency counts must satisfy n1>=1, n0>=1, treated_events<=treated_n, control_events<=control_n")
        b, d = n1 - a, n0 - c
        cont_payload = {"treated_events": a, "treated_n": n1, "control_events": c, "control_n": n0}
    elif {"a", "b", "c", "d"} <= value.keys():
        for k in ("a", "b", "c", "d"):
            if type(value.get(k)) is not int or value[k] < 0:
                fail("invalid_source", f"{k} must be a nonnegative integer")
        a, b, c, d = value["a"], value["b"], value["c"], value["d"]
        n1, n0 = a + b, c + d
        if n1 < 1 or n0 < 1:
            fail("invalid_source", "Contingency treatment/control groups must be nonempty")
        cont_payload = {"a": a, "b": b, "c": c, "d": d}
    else:
        fail("invalid_source", "Contingency JSON requires {treated_events, treated_n, control_events, control_n} or {a, b, c, d}")

    p_fisher, p_issue = _fisher_exact_two_sided(a, b, c, d)
    base = {
        "endpoint": endpoint.strip(),
        "endpoint_role": "exploratory",
        "direction": "neutral",
        "evidence_id": evidence_id,
        "inference_method": "other",
        "contingency": cont_payload,
    }
    if p_fisher is not None:
        base["p_value"] = p_fisher
    else:
        base["notes"] = p_issue["message"]
    records, issues = [], [p_issue] if p_issue else []

    def append(metric: str, numerator: int, denominator: int, derivation: str) -> None:
        try:
            estimate = contingency_ratio(numerator, denominator, metric)
        except ContractError as exc:
            issues.append({"code": exc.code, "metric": metric, "field": "estimate", "message": exc.message})
            return
        record = {**base, "id": f"effect-{len(records) + 1}", "metric": metric, "estimate": estimate, "n": n1 + n0}
        if metric == "risk_diff":
            record["events"] = a + c
        records.append((record, derivation))

    append("risk_diff", a * n0 - c * n1, n1 * n0, "(a/n1)-(c/n0); fisher_exact_two_sided")
    if a > 0 and c > 0:
        append("RR", a * n0, c * n1, "(a/n1)/(c/n0); fisher_exact_two_sided")
    if a > 0 and b > 0 and c > 0 and d > 0:
        append("OR", a * d, b * c, "(a*d)/(b*c); fisher_exact_two_sided")
    return records, issues


def _confusion(text: str, evidence_id: str) -> list[tuple[dict, str]]:
    value = strict_json(text)
    if not isinstance(value, dict):
        fail("invalid_source", "Confusion matrix must be an object with named tp/tn/fp/fn counts")
    counts = []
    for key in ("tp", "tn", "fp", "fn"):
        v = value.get(key)
        if type(v) is not int or v < 0:
            fail("invalid_source", f"{key} must be a nonnegative integer; weighted/ambiguous matrices are not accepted")
        counts.append(v)
    tp, tn, fp, fn = counts
    total = sum(counts)
    if total == 0:
        fail("invalid_source", "Empty confusion matrix has no defined performance")
    endpoint = value.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        fail("invalid_source", "Confusion matrix requires endpoint")
    base = {"endpoint": endpoint, "endpoint_role": "exploratory", "direction": "neutral", "evidence_id": evidence_id}
    records = [({**base, "id": "effect-1", "metric": "accuracy", "estimate": (tp + tn) / total,
                 "n": total, "events": tp + tn, "count_basis": "unweighted_binary"}, "(tp+tn)/(tp+tn+fp+fn)")]
    if 2 * tp + fp + fn:
        records.append(({**base, "id": "effect-2", "metric": "F1", "estimate": 2 * tp / (2 * tp + fp + fn)}, "2*tp/(2*tp+fp+fn)"))
    return records


def _select_xlsx_table(content: bytes, sheet_name: str | None = None) -> tuple[list[tuple[dict, str]], dict]:
    book = list_xlsx_sheets(content, sheet_name=sheet_name)
    sheet_names = book["sheet_names"]
    sheets = book["sheets"]
    selected = sheet_name
    if selected is None:
        ep_aliases = {a.casefold() for a in ALIASES["endpoint"]}
        est_aliases = {a.casefold() for a in ALIASES["estimate"]}
        for sname in sheet_names:
            info = sheets[sname]
            folded = {h.casefold() for h in info["header"]}
            if (folded & ep_aliases) and (folded & est_aliases) and info["rows"]:
                selected = sname
                break
        if selected is None:
            selected = sheet_names[0]
    chosen = sheets[selected]
    if not chosen["rows"]:
        fail("invalid_source", f"XLSX sheet {selected!r} has no readable statistical table rows")
    meta = {
        "sheet": selected,
        "sheet_names": sheet_names,
        "omitted_sheets": [s for s in sheet_names if s != selected],
        "formula_cached_values": chosen["formula_cached_values"],
    }
    return chosen["rows"], meta


def parse_statistics(
    content: bytes,
    path: str,
    evidence_id: str,
    format: str = "auto",
    column_map: dict | None = None,
    *,
    sheet_name: str | None = None,
) -> dict:
    is_xlsx = format == "xlsx" or (format == "auto" and Path(path).suffix.lower() == ".xlsx")
    text: str | None = None
    if not is_xlsx:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            fail("invalid_source", "Statistics must be UTF-8 text or XLSX")
    resolved_format = _resolve_format(path, format, text)
    if resolved_format == "xlsx" and is_xlsx is False:
        # Caller forced format="xlsx" on a non-.xlsx extension.
        text = None
    columns = column_map or {}
    if not isinstance(columns, dict) or set(columns) - set(ALIASES) or not all(isinstance(v, str) and v for v in columns.values()):
        fail("invalid_value", "column_map maps known effect fields to exact source column names")
    if len(set(columns.values())) != len(columns):
        fail("invalid_value", "A column cannot supply multiple effect fields")
    digest = hashlib.sha256(content).hexdigest()
    xlsx_meta = None
    calculation_issues = []
    if resolved_format == "xlsx":
        rows, xlsx_meta = _select_xlsx_table(content, sheet_name=sheet_name)
    elif resolved_format == "confusion_json":
        assert text is not None
        rows = _confusion(text, evidence_id)
    elif resolved_format == "contingency_json":
        assert text is not None
        rows, calculation_issues = _contingency(text, evidence_id)
    else:
        assert text is not None
        rows = _table(text, resolved_format)
    if len(rows) > 50:
        fail("too_large", "At most 50 effect rows per import; split explicitly without dropping unfavorable rows")
    records, issues, bindings = [], calculation_issues, []
    for index, (row, locator) in enumerate(rows):
        try:
            if resolved_format in ("confusion_json", "contingency_json"):
                record = row
                derivation = locator
            else:
                record = _row_record(row, index, evidence_id, columns)
                derivation = "direct xlsx cell extraction (cached formula values if formulas present)" if resolved_format == "xlsx" else "direct row extraction"
            record = validate_effect_records([record], [evidence_id])[0]
            binding: dict = {"version": 1, "format": resolved_format, "source_sha256": digest, "record_index": index, "column_map": columns}
            if xlsx_meta is not None:
                binding["sheet"] = xlsx_meta["sheet"]
            record["artifact_binding"] = binding
            records.append(record)
            bindings.append({"record_id": record["id"], "location": locator, "derivation": derivation})
        except ContractError as exc:
            issues.append({"row_index": index, "location": locator, "code": exc.code, "message": exc.message, "raw": row})
    if resolved_format == "confusion_json" and len(rows) == 1:
        issues.append({"code": "undefined_f1", "message": "F1 denominator is zero; no F1 record generated"})
    out = {"effect_records": records, "issues": issues, "source_map": bindings, "format": resolved_format,
           "source_sha256": digest, "input_row_count": len(rows), "status": "parsed_with_issues" if issues else "parsed",
           "assessment": "numeric_extraction_only; endpoint role, direction, independence and scientific validity are not inferred"}
    if xlsx_meta is not None:
        out["xlsx"] = xlsx_meta
    return out


def verify_artifact_binding(
    record: dict,
    evidence: dict,
    snapshot_text: str | None,
    *,
    snapshot_bytes: bytes | None = None,
) -> tuple[bool, list[str]]:
    """Reparse the bound full snapshot, not a bag of numbers across unrelated rows."""
    binding = record["artifact_binding"]
    if binding["source_sha256"] != evidence.get("sha256"):
        return False, ["artifact source hash differs from registered evidence"]
    content: bytes | None = None
    if snapshot_bytes is not None:
        if hashlib.sha256(snapshot_bytes).hexdigest() == binding["source_sha256"]:
            content = snapshot_bytes
        else:
            return False, ["complete binary snapshot bytes mismatch registered sha256"]
    else:
        text = snapshot_text if snapshot_text is not None else evidence.get("source_text")
        if not isinstance(text, str):
            return False, ["full artifact snapshot unavailable"]
        # Core preserves UTF-8 text, but may strip BOM; accept only the exact byte hash variant.
        variants = [text.encode("utf-8"), b"\xef\xbb\xbf" + text.encode("utf-8")]
        content = next((b for b in variants if hashlib.sha256(b).hexdigest() == binding["source_sha256"]), None)
        if content is None:
            return False, ["complete artifact bytes required (truncated/changed text cannot verify)"]
    try:
        parsed = parse_statistics(
            content,
            evidence.get("path", "artifact"),
            record["evidence_id"],
            binding["format"],
            binding["column_map"],
            sheet_name=binding.get("sheet"),
        )
    except (ContractError, ValueError, TypeError):
        return False, ["artifact could not be reparsed"]
    expected = next((r for r in parsed["effect_records"] if r["artifact_binding"]["record_index"] == binding["record_index"]), None)
    if expected is None:
        return False, ["bound row is not a valid effect record"]
    # Endpoint role/direction and identifiers are human interpretation; all numeric/source semantics are bound.
    keys = {
        "endpoint", "metric", "estimate", "ci_low", "ci_high", "ci_level", "p_value",
        "adjusted_p_value", "multiplicity_method", "family_size",
        "n", "events", "df", "scale", "null_value", "count_basis", "inference_method", "contingency",
    }
    mismatch = [key for key in sorted(keys) if record.get(key) != expected.get(key)]
    return (not mismatch), mismatch


_METRIC_ALIAS_GROUPS = (
    ("HR", "hazard_ratio", "hazard ratio", "hazard-ratio"),
    ("OR", "odds_ratio", "odds ratio", "odds-ratio"),
    ("RR", "risk_ratio", "risk ratio", "risk-ratio", "relative risk", "relative_risk", "relative-risk"),
    ("IRR", "incidence_rate_ratio", "incidence rate ratio", "incidence-rate-ratio",
     "incident_rate_ratio", "incident rate ratio", "incident-rate-ratio"),
    ("AUROC", "AUC", "area under the ROC curve", "area under ROC curve"),
    ("mean_diff", "mean diff", "mean difference", "mean-difference", "MD"),
    ("risk_diff", "risk diff", "risk difference", "risk-difference", "RD"),
    ("diff", "difference"),
    ("beta", "β", "b"),
    ("R2", "R²", "R^2", "R-squared"),
    ("RMSE", "root mean square error", "root mean squared error"),
    ("MAE", "mean absolute error"),
    ("F1", "F1 score", "F1-score"),
    ("accuracy",),
    ("proportion",),
    ("rate",),
    ("logFC", "log_fc", "log fold change"),
    ("count",),
    ("other",),
)
_OPERATOR_ONLY_ALIASES = frozenset({"b"})
_CASE_SENSITIVE_BARE_ALIASES = frozenset({"HR", "OR", "RR", "IRR", "MD", "RD"})


def _alias_prefix(token: str, *, operator_only: bool = False) -> str:
    esc = re.escape(token).replace(r"\ ", r"\s+")
    if operator_only or token in _OPERATOR_ONLY_ALIASES:
        return rf"(?<!\w)(?i:{esc})\s*(?:=|:|为|是)\s*"
    if token in _CASE_SENSITIVE_BARE_ALIASES:
        return rf"(?<!\w)(?:{esc}(?:\s*(?:=|:|为|是)\s*|\s+)|(?i:{esc})\s*(?:=|:|为|是)\s*)"
    return rf"(?<!\w)(?i:{esc})(?:\s*(?:=|:|为|是)\s*|\s+)"


def _metric_aliases(metric: str) -> tuple[str, ...]:
    folded = metric.casefold()
    for group in _METRIC_ALIAS_GROUPS:
        if any(alias.casefold() == folded for alias in group):
            return group
    return (metric,)


def _metric_pattern(metric: str, number: str) -> re.Pattern[str]:
    aliases = sorted(_metric_aliases(metric), key=len, reverse=True)
    cores = "|".join(_alias_prefix(alias) for alias in aliases)
    return re.compile(rf"(?:{cores})({number})(%?)")


def _next_metric_pattern(number: str) -> re.Pattern[str]:
    skip_bare = {"other", "count", "diff", "difference"}
    tokens: list[str] = []
    operator_only: set[str] = set()
    for group in _METRIC_ALIAS_GROUPS:
        for alias in group:
            if alias in ("other", "count"):
                continue
            tokens.append(alias)
            if alias in skip_bare:
                operator_only.add(alias)
    ordered = sorted(dict.fromkeys(tokens), key=len, reverse=True)
    cores = "|".join(_alias_prefix(tok, operator_only=tok in operator_only) for tok in ordered)
    return re.compile(rf"(?:{cores}){number}")


def _endpoint_pattern(endpoint: str) -> re.Pattern[str]:
    # Latin acronyms need token boundaries even in prose adjacent to CJK text.
    endpoint = endpoint.strip().casefold()
    left = r"(?<![a-z0-9_])" if re.match(r"[a-z0-9_]", endpoint) else ""
    right = r"(?![a-z0-9_])" if re.search(r"[a-z0-9_]$", endpoint) else ""
    return re.compile(left + re.escape(endpoint) + right)


def compare_manuscript(records: list[dict], document: dict, *, assumed_reported_scale: str = "auto") -> list[dict]:
    """Compare explicit endpoint+metric spans, preserving absent/ambiguous findings."""
    enum(assumed_reported_scale, ("auto", "unit", "percentage"), "assumed_reported_scale")
    result = []
    number = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
    next_metric_re = _next_metric_pattern(number)
    ci_re = re.compile(
        rf"(?:(\d+(?:\.\d+)?)%[-\s]*)?"
        rf"(?:(?<!\w)(?:(?:confidence|credible)\s+intervals?(?:\s*\((?:CrI|CI)\))?|CrI|CI)(?!\w)|置信区间)"
        rf"\s*(?:[:=,：]|为|是)?\s*[\[(]?\s*"
        rf"({number})\s*(%?)\s*(?:,|;|\bto\b|至|–|—|-|~|～)\s*({number})(?:\s*(%)|\s*[\])]\s*(%))?",
        re.I,
    )
    p_re = re.compile(rf"(?<!\w)p(?:[-\s]?value)?\s*(<=|>=|=|<|>|≤|≥)\s*({number})", re.I)

    for record in records:
        metric_re = _metric_pattern(record["metric"], number)
        endpoint_re = _endpoint_pattern(record["endpoint"])
        matches = []
        for unit in document["units"]:
            if not endpoint_re.search(unit["text"].casefold()):
                continue
            for match in metric_re.finditer(unit["text"]):
                matches.append((match, unit))
        item = {"record_id": record["id"], "endpoint": record["endpoint"], "metric": record["metric"]}
        if len(matches) != 1:
            item["status"] = "not_found" if not matches else "ambiguous"
            item["match_count"] = len(matches)
        else:
            match, unit = matches[0]
            token = match[1]
            estimate_pct = bool(match[2])
            source_scale = record.get("scale", "unit")
            reported = Decimal(token)
            estimate = Decimal(str(record["estimate"]))
            scale_assumption = None
            if not estimate_pct and source_scale == "percentage" and assumed_reported_scale == "auto":
                unchecked = ["estimate", "ci_low", "ci_high", "p_value"]
                item.update(
                    status="ambiguous_scale",
                    reported=token,
                    source_estimate=record["estimate"],
                    source_scale="percentage",
                    reported_scale="unspecified",
                    scale_conversion="ambiguous",
                    location=unit["location"],
                    quote=unit["text"],
                    compared_fields=[],
                    unchecked_fields=unchecked,
                    scale_note="Source record uses percentage scale, but manuscript estimate omits '%'; unit vs percentage scale is ambiguous.",
                )
                result.append(item)
                continue
            if estimate_pct and source_scale == "unit":
                estimate *= 100
                scale_conversion = "unit_to_percentage"
                reported_scale = "percentage"
            elif (not estimate_pct) and source_scale == "percentage" and assumed_reported_scale != "auto":
                reported_scale = assumed_reported_scale
                scale_assumption = f"caller_declared_{assumed_reported_scale}"
                if assumed_reported_scale == "unit":
                    estimate /= 100
                    scale_conversion = "percentage_to_unit"
                else:
                    scale_conversion = "none"
            elif (not estimate_pct) and source_scale == "unit" and assumed_reported_scale == "percentage":
                estimate *= 100
                reported_scale = "percentage"
                scale_conversion = "unit_to_percentage"
                scale_assumption = "caller_declared_percentage"
            else:
                scale_conversion = "none"
                reported_scale = "percentage" if estimate_pct else "unit"
            tolerance = Decimal(10) ** reported.as_tuple().exponent / 2
            item.update(
                status="match_at_reported_precision" if abs(estimate - reported) <= tolerance else "mismatch",
                reported=token + match[2],
                source_estimate=record["estimate"],
                source_scale=source_scale,
                reported_scale=reported_scale,
                scale_conversion=scale_conversion,
                location=unit["location"],
                quote=unit["text"],
                compared_fields=["estimate"],
                unchecked_fields=[],
            )
            if scale_assumption is not None:
                item["scale_assumption"] = scale_assumption
            # Restrict uncertainty to the same metric span, before any subsequent metric mention.
            tail = unit["text"][match.end():]
            next_metric = next_metric_re.search(tail)
            if next_metric:
                tail = tail[:next_metric.start()]
            checks = []
            ci_matches = list(ci_re.finditer(tail))
            if len(ci_matches) == 1:
                ci = ci_matches[0]
                ci_level_tok = ci.group(1)
                low_tok, low_pct = ci.group(2), ci.group(3)
                high_tok = ci.group(4)
                high_pct = ci.group(5) or ci.group(6) or ""
                if low_pct and not high_pct:
                    ci_scale_mode = "ambiguous"
                elif high_pct:
                    ci_scale_mode = "percentage"
                elif assumed_reported_scale != "auto":
                    ci_scale_mode = assumed_reported_scale
                elif source_scale == "unit" and not estimate_pct:
                    ci_scale_mode = "unit"
                else:
                    ci_scale_mode = "ambiguous"

                if ci_scale_mode == "ambiguous":
                    for field, tok_val, tok_pct in (("ci_low", low_tok, low_pct), ("ci_high", high_tok, high_pct)):
                        item["unchecked_fields"].append(field)
                        if field in record:
                            checks.append({
                                "field": field,
                                "reported": tok_val + tok_pct,
                                "source": record[field],
                                "source_scale": source_scale,
                                "reported_scale": "percentage" if tok_pct else "unspecified",
                                "status": "ambiguous_scale",
                            })
                        else:
                            checks.append({"field": field, "status": "source_missing"})
                else:
                    if ci_scale_mode == "percentage" and source_scale == "unit":
                        ci_scale_conv = "unit_to_percentage"
                        ci_factor = Decimal(100)
                    elif ci_scale_mode == "unit" and source_scale == "percentage":
                        ci_scale_conv = "percentage_to_unit"
                        ci_factor = Decimal("0.01")
                    else:
                        ci_scale_conv = "none"
                        ci_factor = Decimal(1)
                    for field, tok_val in (("ci_low", low_tok), ("ci_high", high_tok)):
                        if field in record:
                            value = Decimal(tok_val)
                            actual_ci = Decimal(str(record[field])) * ci_factor
                            equal = abs(actual_ci - value) <= Decimal(10) ** value.as_tuple().exponent / 2
                            checks.append({
                                "field": field,
                                "reported": tok_val + ("%" if ci_scale_mode == "percentage" else ""),
                                "source": record[field],
                                "source_scale": source_scale,
                                "reported_scale": ci_scale_mode,
                                "scale_conversion": ci_scale_conv,
                                "status": "match_at_reported_precision" if equal else "mismatch",
                            })
                            item["compared_fields"].append(field)
                        else:
                            checks.append({"field": field, "status": "source_missing"})
                if ci_level_tok:
                    if "ci_level" in record:
                        equal = abs(Decimal(str(record["ci_level"])) * 100 - Decimal(ci_level_tok)) < Decimal("1e-9")
                        checks.append({"field": "ci_level", "status": "match" if equal else "mismatch"})
                    else:
                        checks.append({"field": "ci_level", "status": "source_missing"})
            else:
                item["unchecked_fields"].extend(["ci_low", "ci_high"])
                if len(ci_matches) > 1:
                    checks.append({"field": "ci", "status": "ambiguous"})
            p_matches = list(p_re.finditer(tail))
            if len(p_matches) == 1:
                pm = p_matches[0]
                operator, token = pm.groups()
                value = Decimal(token)
                source_p = record.get("p_value")
                check = {"field": "p_value", "reported": operator + token, "source": source_p}
                if not 0 <= value <= 1 or (value == 0 and operator in ("=", "<", "<=", "≤")):
                    check.update(status="mismatch", reason="invalid_reported_p_value")
                elif source_p is None:
                    check["status"] = "source_missing"
                else:
                    actual = Decimal(str(source_p))
                    equal = {
                        "=": lambda: abs(actual - value) <= Decimal(10) ** value.as_tuple().exponent / 2,
                        "<": lambda: actual < value,
                        ">": lambda: actual > value,
                        "≤": lambda: actual <= value,
                        "<=": lambda: actual <= value,
                        "≥": lambda: actual >= value,
                        ">=": lambda: actual >= value,
                    }[operator]()
                    check["status"] = "match" if equal else "mismatch"
                    item["compared_fields"].append("p_value")
                if source_p is None:
                    item["unchecked_fields"].append("p_value")
                checks.append(check)
            else:
                item["unchecked_fields"].append("p_value")
                if p_matches:
                    checks.append({"field": "p_value", "status": "ambiguous"})
            item["field_checks"] = checks
            if any(c["status"] == "mismatch" for c in checks):
                item["status"] = "mismatch"
            elif item["status"] != "mismatch" and any(c["status"] in ("source_missing", "ambiguous", "ambiguous_scale") for c in checks):
                item["status"] = "incomplete_comparison"
        result.append(item)
    return result
