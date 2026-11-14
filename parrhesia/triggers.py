"""Cross-time claim graph lineage validation and executable reversal triggers. Pure stdlib."""
from __future__ import annotations

import math
from typing import Any

from .claims import DESIGN_FIELDS, EXECUTION_FORK_ROLES, STAT_FIELDS, TYPE_LEVELS
from .contracts import CHECK_NAMES, CHECK_STATUSES, VERDICTS, array, enum, fail, fields, ids, obj, string
from .effects import DIFFERENCE_METRICS, EFFECT_METRICS, EFFECT_RECORD_ROLES, RATIO_METRICS
from .gates import (
    contradictory_evidence_kind,
    contradictory_positive_evidence_text,
    is_placeholder,
    meaningful,
    quote_status,
)

MAX_PRIOR_CASES = 20
MAX_PRIOR_CLAIM_LINKS = 20
MAX_REVERSAL_TRIGGERS = 20

CASE_RELATIONS = (
    "follow_up",
    "replication",
    "reanalysis",
    "correction",
    "extension",
    "retraction",
)

CLAIM_LINEAGE_RELATIONS = (
    "replicates",
    "refines",
    "narrows",
    "extends",
    "supersedes",
    "reverses",
    "refutes",
)

TRIGGER_KINDS = (
    "effect_metric",
    "check_status",
    "evidence_status",
    "execution_outcome",
    "replication_verdict",
)

TRIGGER_EFFECT_FIELDS = ("estimate", "ci_low", "ci_high", "p_value", "n", "events")

TRIGGER_OPERATORS = (
    "lt",
    "le",
    "gt",
    "ge",
    "eq",
    "ne",
    "crosses_null",
    "excludes_null",
    "outside_band",
    "inside_band",
)

TRIGGER_EVIDENCE_STATUSES = ("blocked", "unverified", "contradicts")
TRIGGER_EXIT_OPERATORS = ("non_zero", "eq", "ne")

_COMMON_TRIGGER_KEYS = {
    "id",
    "description",
    "kind",
    "target_verdict",
    "target_claim_type",
    "target_evidence_level",
    "target_scope",
}

_KIND_SPECS = {
    "effect_metric": {
        "required": {"metric", "field", "operator"},
        "allowed": {"metric", "field", "operator", "endpoint", "endpoint_role", "threshold", "band_low", "band_high", "null_value"},
    },
    "check_status": {
        "required": {"target_check", "target_statuses"},
        "allowed": {"target_check", "target_statuses"},
    },
    "evidence_status": {
        "required": {"trigger_on"},
        "allowed": {"trigger_on", "evidence_id"},
    },
    "execution_outcome": {
        "required": set(),
        "allowed": {"exit_operator", "exit_status", "fork_role"},
    },
    "replication_verdict": {
        "required": {"target_verdicts"},
        "allowed": {"target_verdicts", "relations"},
    },
}

_THRESHOLD_OPERATORS = ("lt", "le", "gt", "ge", "eq", "ne")
_BAND_OPERATORS = ("outside_band", "inside_band")
_NULL_OPERATORS = ("crosses_null", "excludes_null")
_POSITIVE_VERDICTS = ("supported", "partially_supported")
_NEGATIVE_VERDICTS = ("unsupported", "insufficient_evidence")
_DEFAULT_REPLICATION_RELATIONS = ("replicates", "refutes", "reverses", "supersedes")
_STANDING_PRECEDENCE = (
    ("reverses", "reversed"),
    ("refutes", "refuted"),
    ("supersedes", "superseded"),
    ("narrows", "narrowed"),
    ("refines", "refined"),
    ("replicates", "replicated"),
)


def _finite_number(value: Any, name: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        fail("invalid_type", f"{name} must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        fail("invalid_value", f"{name} must be a finite number")
    return num


def _int_value(value: Any, name: str) -> int:
    if type(value) is not int:
        fail("invalid_type", f"{name} must be an integer")
    return int(value)


def _meaningful_text(value: Any, name: str, maximum: int = 2000) -> str:
    txt = string(value, name, maximum=maximum)
    if not meaningful(txt):
        fail("placeholder_or_empty", f"{name} must be a meaningful non-placeholder explanation")
    return txt


def _enum_list(value: Any, allowed: tuple[str, ...], name: str, *, minimum: int = 1, maximum: int | None = None) -> list[str]:
    items = array(value, name, minimum=minimum, maximum=maximum or len(allowed))
    seen: list[str] = []
    for idx, item in enumerate(items):
        val = enum(item, allowed, f"{name}[{idx}]")
        if val in seen:
            fail("duplicate_id", f"{name} contains duplicate value '{val}'")
        seen.append(val)
    return seen


def _validate_target_check(target_check: Any, name: str) -> str:
    target = string(target_check, name, maximum=200)
    if target in CHECK_NAMES:
        return target
    if "." not in target:
        fail("invalid_value", f"{name} must be a top-level check name or '<family>.<key>' / 'statistical_report.<key>'")
    prefix, key = target.split(".", 1)
    if prefix == "statistical_report":
        if key in STAT_FIELDS:
            return target
        fail("invalid_value", f"{name} unknown statistical_report check '{key}'")
    if prefix in DESIGN_FIELDS:
        if key in DESIGN_FIELDS[prefix]:
            return target
        fail("invalid_value", f"{name} unknown design check '{key}' for family '{prefix}'")
    fail("invalid_value", f"{name} unknown check target '{target}'")


def validate_reversal_triggers(triggers: Any, domain: str = "scientific") -> list[dict]:
    """Validate structured reversal triggers without mutating the caller's dicts."""
    items = array(triggers, "reversal_triggers", minimum=0, maximum=MAX_REVERSAL_TRIGGERS)
    trigger_ids: list[str] = []
    validated: list[dict] = []

    for idx, raw in enumerate(items):
        prefix = f"reversal_triggers[{idx}]"
        trig = obj(raw, prefix)
        kind_raw = trig.get("kind")
        kind = enum(kind_raw, TRIGGER_KINDS, f"{prefix}.kind")
        spec = _KIND_SPECS[kind]
        allowed_keys = _COMMON_TRIGGER_KEYS | spec["allowed"]
        required_keys = {"id", "description", "kind", "target_verdict"} | spec["required"]
        fields(trig, allowed_keys, required_keys, prefix)

        trig_id = string(trig["id"], f"{prefix}.id", maximum=200)
        trigger_ids.append(trig_id)
        description = _meaningful_text(trig["description"], f"{prefix}.description", maximum=1000)
        target_verdict = enum(trig["target_verdict"], VERDICTS, f"{prefix}.target_verdict")

        target_claim_type = trig.get("target_claim_type")
        target_evidence_level = trig.get("target_evidence_level")
        if target_evidence_level is not None and target_claim_type is None:
            fail("missing_field", f"{prefix}.target_evidence_level requires {prefix}.target_claim_type")
        if target_claim_type is not None:
            ct = enum(target_claim_type, tuple(TYPE_LEVELS), f"{prefix}.target_claim_type")
            if (domain == "scientific" and ct == "engineering") or (
                domain == "general" and ct not in ("description", "computational", "engineering")
            ):
                fail("invalid_value", f"{prefix}.target_claim_type '{ct}' is incompatible with domain '{domain}'")
            if target_evidence_level is not None:
                enum(target_evidence_level, TYPE_LEVELS[ct], f"{prefix}.target_evidence_level")
        if "target_scope" in trig and trig["target_scope"] is not None:
            _meaningful_text(trig["target_scope"], f"{prefix}.target_scope", maximum=1000)

        if kind == "effect_metric":
            metric = enum(trig["metric"], EFFECT_METRICS, f"{prefix}.metric")
            enum(trig["field"], TRIGGER_EFFECT_FIELDS, f"{prefix}.field")
            op = enum(trig["operator"], TRIGGER_OPERATORS, f"{prefix}.operator")
            if "endpoint" in trig and trig["endpoint"] is not None:
                string(trig["endpoint"], f"{prefix}.endpoint", maximum=200)
            if "endpoint_role" in trig and trig["endpoint_role"] is not None:
                enum(trig["endpoint_role"], EFFECT_RECORD_ROLES, f"{prefix}.endpoint_role")
            if op in _THRESHOLD_OPERATORS:
                if trig.get("threshold") is None:
                    fail("missing_field", f"{prefix}.threshold is required for operator '{op}'")
                _finite_number(trig["threshold"], f"{prefix}.threshold")
            elif trig.get("threshold") is not None:
                _finite_number(trig["threshold"], f"{prefix}.threshold")

            if op in _BAND_OPERATORS:
                if trig.get("band_low") is None or trig.get("band_high") is None:
                    fail("missing_field", f"{prefix}.band_low and {prefix}.band_high are required for operator '{op}'")
                blow = _finite_number(trig["band_low"], f"{prefix}.band_low")
                bhigh = _finite_number(trig["band_high"], f"{prefix}.band_high")
                if blow > bhigh:
                    fail("invalid_value", f"{prefix}.band_low ({blow}) cannot exceed band_high ({bhigh})")
            elif trig.get("band_low") is not None or trig.get("band_high") is not None:
                if trig.get("band_low") is None or trig.get("band_high") is None:
                    fail("missing_field", f"{prefix}.band_low and {prefix}.band_high must be provided as a pair")
                blow = _finite_number(trig["band_low"], f"{prefix}.band_low")
                bhigh = _finite_number(trig["band_high"], f"{prefix}.band_high")
                if blow > bhigh:
                    fail("invalid_value", f"{prefix}.band_low ({blow}) cannot exceed band_high ({bhigh})")

            if "null_value" in trig and trig["null_value"] is not None:
                _finite_number(trig["null_value"], f"{prefix}.null_value")
            elif op in _NULL_OPERATORS and metric not in RATIO_METRICS and metric not in DIFFERENCE_METRICS:
                fail("missing_field", f"{prefix}.null_value is required for metric '{metric}' with operator '{op}'")

        elif kind == "check_status":
            _validate_target_check(trig["target_check"], f"{prefix}.target_check")
            _enum_list(trig["target_statuses"], CHECK_STATUSES, f"{prefix}.target_statuses", minimum=1, maximum=4)

        elif kind == "evidence_status":
            _enum_list(trig["trigger_on"], TRIGGER_EVIDENCE_STATUSES, f"{prefix}.trigger_on", minimum=1, maximum=3)
            if "evidence_id" in trig and trig["evidence_id"] is not None:
                string(trig["evidence_id"], f"{prefix}.evidence_id", maximum=200)

        elif kind == "execution_outcome":
            exit_op = "non_zero"
            if "exit_operator" in trig and trig["exit_operator"] is not None:
                exit_op = enum(trig["exit_operator"], TRIGGER_EXIT_OPERATORS, f"{prefix}.exit_operator")
            if exit_op in ("eq", "ne"):
                if trig.get("exit_status") is None:
                    fail("missing_field", f"{prefix}.exit_status is required when exit_operator is '{exit_op}'")
                _int_value(trig["exit_status"], f"{prefix}.exit_status")
            elif "exit_status" in trig and trig["exit_status"] is not None:
                _int_value(trig["exit_status"], f"{prefix}.exit_status")
            if "fork_role" in trig and trig["fork_role"] is not None:
                enum(trig["fork_role"], EXECUTION_FORK_ROLES, f"{prefix}.fork_role")

        elif kind == "replication_verdict":
            _enum_list(trig["target_verdicts"], VERDICTS, f"{prefix}.target_verdicts", minimum=1, maximum=4)
            if "relations" in trig and trig["relations"] is not None:
                _enum_list(trig["relations"], CLAIM_LINEAGE_RELATIONS, f"{prefix}.relations", minimum=1, maximum=7)

        validated.append(dict(trig, id=trig_id, description=description, kind=kind, target_verdict=target_verdict))

    ids(trigger_ids, "reversal trigger IDs")
    return validated


def validate_prior_claim_links_shape(links: Any) -> list[dict]:
    """Validate structural shape and uniqueness of prior_claim_links on a claim."""
    items = array(links, "prior_claim_links", minimum=0, maximum=MAX_PRIOR_CLAIM_LINKS)
    seen_pairs: set[tuple[str, str]] = set()
    validated: list[dict] = []

    allowed = {"prior_case_id", "prior_claim_id", "relation", "reason", "triggered_reversal_id"}
    required = {"prior_case_id", "prior_claim_id", "relation", "reason"}

    for idx, raw in enumerate(items):
        prefix = f"prior_claim_links[{idx}]"
        link = obj(raw, prefix)
        fields(link, allowed, required, prefix)
        prior_case_id = string(link["prior_case_id"], f"{prefix}.prior_case_id", maximum=200)
        prior_claim_id = string(link["prior_claim_id"], f"{prefix}.prior_claim_id", maximum=200)
        enum(link["relation"], CLAIM_LINEAGE_RELATIONS, f"{prefix}.relation")
        _meaningful_text(link["reason"], f"{prefix}.reason", maximum=2000)
        if "triggered_reversal_id" in link and link["triggered_reversal_id"] is not None:
            string(link["triggered_reversal_id"], f"{prefix}.triggered_reversal_id", maximum=200)
        pair = (prior_case_id, prior_claim_id)
        if pair in seen_pairs:
            fail("duplicate_id", f"duplicate prior_claim_links entry for '{prior_case_id}:{prior_claim_id}'")
        seen_pairs.add(pair)
        validated.append(dict(link))

    return validated


def collect_claim_triggers(claim: dict, decision: dict | None = None) -> list[dict]:
    """Merge claim-level and decision-level reversal triggers (decision overrides same ID)."""
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for raw in claim.get("reversal_triggers") or ():
        tid = raw["id"]
        if tid not in by_id:
            order.append(tid)
        by_id[tid] = dict(raw)
    if decision:
        for raw in decision.get("reversal_triggers") or ():
            tid = raw["id"]
            if tid not in by_id:
                order.append(tid)
            by_id[tid] = dict(raw)
    return [by_id[tid] for tid in order]


def validate_prior_claim_links_references(
    links: list[dict],
    current_case_id: str,
    cases_by_id: dict[str, dict],
    prior_case_ids: list[str] | None = None,
) -> None:
    """Validate that prior_claim_links resolve to valid prior cases, claims, and trigger IDs."""
    for idx, link in enumerate(links):
        prior_case_id = link["prior_case_id"]
        prior_claim_id = link["prior_claim_id"]
        if prior_case_id == current_case_id:
            fail("invalid_value", f"prior_claim_links[{idx}] cannot link a case to itself")
        if prior_case_id not in cases_by_id:
            fail("unknown_case", f"prior_case_id '{prior_case_id}' does not exist in this workspace")
        if prior_case_ids is not None and prior_case_id not in prior_case_ids:
            fail(
                "unlinked_prior_case",
                f"prior_claim_links[{idx}] references '{prior_case_id}', which is not listed in case.prior_case_ids",
            )
        prior_case = cases_by_id[prior_case_id]
        prior_claims = {c["id"]: c for c in prior_case.get("claims", ())}
        if prior_claim_id not in prior_claims:
            fail("unknown_prior_claim", f"prior_claim_id '{prior_claim_id}' does not exist in case '{prior_case_id}'")
        trig_id = link.get("triggered_reversal_id")
        if trig_id is not None:
            prior_claim = prior_claims[prior_claim_id]
            prior_decision = None
            if prior_case.get("adjudication"):
                for dec in prior_case["adjudication"].get("decisions", ()):
                    if dec.get("claim_id") == prior_claim_id:
                        prior_decision = dec
                        break
            known_triggers = {t["id"] for t in collect_claim_triggers(prior_claim, prior_decision)}
            if trig_id not in known_triggers:
                fail(
                    "unknown_reversal_trigger",
                    f"triggered_reversal_id '{trig_id}' was not defined on '{prior_case_id}:{prior_claim_id}'",
                )


def _derive_evidence_verifications(
    evidence_by_id: dict[str, dict],
    verification: dict | None = None,
) -> dict[str, dict]:
    verifications: dict[str, dict] = {}
    if verification:
        for entry in verification.get("evidence", ()):
            if isinstance(entry, dict) and entry.get("evidence_id"):
                verifications[entry["evidence_id"]] = dict(entry)
    for ev_id, ev in (evidence_by_id or {}).items():
        base = dict(verifications.get(ev_id) or {})
        contradicts = bool(base.get("contradicts")) or (
            contradictory_evidence_kind(ev) is not None
            or bool(contradictory_positive_evidence_text(ev, include_outcome_stripped=False))
        )
        if "status" not in base:
            snap_status = ev.get("snapshot_status")
            src_status = ev.get("source_text_status")
            window_ok = src_status == "truncated" and bool((ev.get("excerpt_window") or {}).get("quote_anchored"))
            if snap_status == "mismatch" or ev.get("status") == "blocked":
                status = "blocked"
            elif snap_status == "missing" or src_status in ("missing", "binary_not_read_by_engine") or (
                src_status == "truncated" and not window_ok
            ):
                status = "unverified"
            else:
                q_stat = "matched"
                if ev.get("quote") is not None and ev.get("source_text") is not None:
                    q_stat = quote_status(ev.get("quote"), ev.get("source_text"))
                if q_stat in ("mismatch", "ambiguous", "too_short"):
                    status = "blocked"
                elif q_stat in ("unknown", "not_text"):
                    status = "unverified"
                else:
                    status = ev.get("status") or "pass"
            base["status"] = status
        base["evidence_id"] = ev_id
        base["contradicts"] = contradicts
        verifications[ev_id] = base
    return verifications


def _effect_null_value(trigger: dict, record: dict) -> float | None:
    if trigger.get("null_value") is not None:
        return float(trigger["null_value"])
    if record.get("null_value") is not None:
        return float(record["null_value"])
    metric = trigger["metric"]
    if metric in RATIO_METRICS:
        return 1.0
    if metric in DIFFERENCE_METRICS:
        return 0.0
    return None


def _compare_numeric(operator: str, val: float, trigger: dict) -> bool:
    if operator == "lt":
        return val < float(trigger["threshold"])
    if operator == "le":
        return val <= float(trigger["threshold"])
    if operator == "gt":
        return val > float(trigger["threshold"])
    if operator == "ge":
        return val >= float(trigger["threshold"])
    if operator == "eq":
        t = float(trigger["threshold"])
        return abs(val - t) <= 1e-9 * max(1.0, abs(t))
    if operator == "ne":
        t = float(trigger["threshold"])
        return abs(val - t) > 1e-9 * max(1.0, abs(t))
    if operator == "outside_band":
        return val < float(trigger["band_low"]) or val > float(trigger["band_high"])
    if operator == "inside_band":
        return float(trigger["band_low"]) <= val <= float(trigger["band_high"])
    return False


def _trigger_result(
    trigger: dict,
    *,
    status: str,
    observed_value: Any,
    matched_source: str | None,
    reason: str,
) -> dict:
    return {
        "id": trigger["id"],
        "kind": trigger["kind"],
        "description": trigger["description"],
        "status": status,
        "fired": status == "fired",
        "observed_value": observed_value,
        "matched_source": matched_source,
        "target_verdict": trigger["target_verdict"],
        "target_claim_type": trigger.get("target_claim_type"),
        "target_evidence_level": trigger.get("target_evidence_level"),
        "target_scope": trigger.get("target_scope"),
        "reason": reason,
    }


def evaluate_single_trigger(trigger: dict, context: dict) -> dict:
    """Deterministically evaluate a single reversal trigger against a structured context."""
    kind = trigger["kind"]

    if kind == "effect_metric":
        records = [
            rec
            for rec in (context.get("effect_records") or ())
            if isinstance(rec, dict)
        ]
        target_role = trigger.get("endpoint_role") or "primary"
        target_endpoint = trigger.get("endpoint")
        matching = []
        for rec in records:
            if rec.get("metric") != trigger["metric"]:
                continue
            if target_endpoint is not None and rec.get("endpoint") != target_endpoint:
                continue
            rec_role = rec.get("endpoint_role") or "primary"
            if rec_role != target_role:
                continue
            matching.append(rec)

        if not matching:
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=None,
                reason=f"No matching effect_record for metric={trigger['metric']} role={target_role}",
            )

        op = trigger["operator"]
        field_name = trigger["field"]
        evaluated_vals: list[tuple[Any, str | None]] = []
        for idx, rec in enumerate(matching):
            source_id = rec.get("id") or rec.get("evidence_id") or f"effect[{idx}]"
            if op in _NULL_OPERATORS:
                null_val = _effect_null_value(trigger, rec)
                ci_low = rec.get("ci_low")
                ci_high = rec.get("ci_high")
                if null_val is None or ci_low is None or ci_high is None:
                    continue
                crosses = float(ci_low) <= float(null_val) <= float(ci_high)
                obs = {
                    "estimate": rec.get("estimate"),
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "null_value": null_val,
                }
                evaluated_vals.append((obs, source_id))
                fired = crosses if op == "crosses_null" else (not crosses)
                if fired:
                    return _trigger_result(
                        trigger,
                        status="fired",
                        observed_value=obs,
                        matched_source=source_id,
                        reason=f"Effect CI [{ci_low}, {ci_high}] {'crosses' if crosses else 'excludes'} null {null_val}",
                    )
            else:
                val = rec.get(field_name)
                if val is None:
                    continue
                fval = float(val)
                evaluated_vals.append((fval, source_id))
                if _compare_numeric(op, fval, trigger):
                    return _trigger_result(
                        trigger,
                        status="fired",
                        observed_value=fval,
                        matched_source=source_id,
                        reason=f"Effect {field_name}={fval:g} satisfied trigger condition '{op}'",
                    )

        if not evaluated_vals:
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=None,
                reason=f"Matching effect_record(s) lack required field/interval for '{op}'",
            )
        return _trigger_result(
            trigger,
            status="unfired",
            observed_value=evaluated_vals[0][0],
            matched_source=evaluated_vals[0][1],
            reason=f"Observed value {evaluated_vals[0][0]} did not meet '{op}'",
        )

    if kind == "check_status":
        target = trigger["target_check"]
        rec = None
        if target in CHECK_NAMES:
            rec = (context.get("checks") or {}).get(target)
        elif target.startswith("statistical_report."):
            key = target.split(".", 1)[1]
            rec = (context.get("statistical_report") or {}).get(key)
        elif "." in target:
            fam, key = target.split(".", 1)
            rec = ((context.get("design_packages") or {}).get(fam) or {}).get(key)

        if rec is None:
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=None,
                reason=f"Check '{target}' has no recorded observation",
            )
        if isinstance(rec, str):
            obs_status = rec
        elif isinstance(rec, dict):
            obs_status = rec.get("status")
            if obs_status == "pass" and is_placeholder(rec.get("reason")):
                obs_status = "unknown"
        else:
            obs_status = None

        if obs_status is None:
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=target,
                reason=f"Check '{target}' status is absent",
            )
        if obs_status in trigger["target_statuses"]:
            return _trigger_result(
                trigger,
                status="fired",
                observed_value=obs_status,
                matched_source=target,
                reason=f"Check '{target}' has status '{obs_status}' in {trigger['target_statuses']}",
            )
        return _trigger_result(
            trigger,
            status="unfired",
            observed_value=obs_status,
            matched_source=target,
            reason=f"Check '{target}' status '{obs_status}' is outside {trigger['target_statuses']}",
        )

    if kind == "evidence_status":
        ev_verifications = context.get("evidence_verifications") or {}
        trigger_on = set(trigger["trigger_on"])
        target_ev_id = trigger.get("evidence_id")
        if target_ev_id is not None:
            candidate_ids = [target_ev_id] if target_ev_id in ev_verifications else []
        else:
            claim_refs = context.get("claim_evidence_ids")
            if claim_refs:
                candidate_ids = [eid for eid in claim_refs if eid in ev_verifications]
                for eid in ev_verifications:
                    if eid not in candidate_ids:
                        candidate_ids.append(eid)
            else:
                candidate_ids = list(ev_verifications.keys())

        if not candidate_ids:
            if "contradicts" in trigger_on and context.get("claim_has_contradiction"):
                return _trigger_result(
                    trigger,
                    status="fired",
                    observed_value="contradicts",
                    matched_source="claim.provenance_cards",
                    reason="Claim carries a contradicting provenance card",
                )
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=None,
                reason="No matching evidence verification records available",
            )

        observed_map: dict[str, str] = {}
        for ev_id in candidate_ids:
            entry = ev_verifications[ev_id]
            if isinstance(entry, str):
                status_val = entry
                contradicts = entry == "contradicts"
            elif isinstance(entry, dict):
                status_val = entry.get("status")
                contradicts = bool(entry.get("contradicts")) or status_val == "contradicts"
            else:
                continue
            if status_val:
                observed_map[ev_id] = status_val
            if contradicts and "contradicts" in trigger_on:
                return _trigger_result(
                    trigger,
                    status="fired",
                    observed_value="contradicts",
                    matched_source=ev_id,
                    reason=f"Evidence '{ev_id}' exhibits contradiction cue or contradicting kind",
                )
            if status_val in trigger_on:
                return _trigger_result(
                    trigger,
                    status="fired",
                    observed_value=status_val,
                    matched_source=ev_id,
                    reason=f"Evidence '{ev_id}' status is '{status_val}'",
                )

        if "contradicts" in trigger_on and context.get("claim_has_contradiction") and target_ev_id is None:
            return _trigger_result(
                trigger,
                status="fired",
                observed_value="contradicts",
                matched_source="claim.provenance_cards",
                reason="Claim carries a contradicting provenance card",
            )
        if not observed_map:
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=None,
                reason="Evidence verification status is absent",
            )
        return _trigger_result(
            trigger,
            status="unfired",
            observed_value=observed_map,
            matched_source=candidate_ids[0],
            reason=f"Evidence status {observed_map} did not match {sorted(trigger_on)}",
        )

    if kind == "execution_outcome":
        fork_role_filter = trigger.get("fork_role")
        exit_op = trigger.get("exit_operator") or "non_zero"
        candidates: list[tuple[int, str]] = []

        for idx, ev_rec in enumerate(context.get("exec_events") or ()):
            if not isinstance(ev_rec, dict):
                continue
            if fork_role_filter is not None and ev_rec.get("fork_role") != fork_role_filter:
                continue
            raw_code = ev_rec.get("exit_status")
            if raw_code is None or str(raw_code).strip().upper() == "UNKNOWN":
                continue
            try:
                code = int(raw_code)
            except (TypeError, ValueError):
                continue
            src = str(ev_rec.get("evidence_id") or ev_rec.get("command") or f"exec_event[{idx}]")
            candidates.append((code, src))

        for card in (context.get("provenance_cards") or {}).get("execution") or ():
            if not isinstance(card, dict):
                continue
            details = card.get("details") or {}
            if not isinstance(details, dict):
                continue
            if fork_role_filter is not None and details.get("fork_role") != fork_role_filter:
                continue
            raw_code = details.get("exit_status")
            if raw_code is None or str(raw_code).strip().upper() == "UNKNOWN":
                continue
            try:
                code = int(str(raw_code).strip())
            except (TypeError, ValueError):
                continue
            src = str(card.get("id") or "execution_card")
            candidates.append((code, src))

        if not candidates:
            return _trigger_result(
                trigger,
                status="pending_data",
                observed_value=None,
                matched_source=None,
                reason="No execution outcome with a numeric exit_status found",
            )

        for code, src in candidates:
            if exit_op == "non_zero":
                hit = code != 0
            elif exit_op == "eq":
                hit = code == int(trigger["exit_status"])
            else:
                hit = code != int(trigger["exit_status"])
            if hit:
                return _trigger_result(
                    trigger,
                    status="fired",
                    observed_value=code,
                    matched_source=src,
                    reason=f"Execution '{src}' exit_status={code} satisfied '{exit_op}'",
                )
        return _trigger_result(
            trigger,
            status="unfired",
            observed_value=candidates[0][0],
            matched_source=candidates[0][1],
            reason=f"Observed execution exit_status {candidates[0][0]} did not satisfy '{exit_op}'",
        )

    # kind == "replication_verdict"
    allowed_relations = tuple(trigger.get("relations") or _DEFAULT_REPLICATION_RELATIONS)
    target_verdicts = tuple(trigger["target_verdicts"])
    links = [
        lnk
        for lnk in (context.get("replication_links") or ())
        if isinstance(lnk, dict) and lnk.get("relation") in allowed_relations
    ]
    adjudicated_links = [lnk for lnk in links if lnk.get("verdict") is not None]
    if not adjudicated_links:
        return _trigger_result(
            trigger,
            status="pending_data",
            observed_value=None,
            matched_source=None,
            reason="No adjudicated replication/follow-up link available yet",
        )
    for lnk in adjudicated_links:
        if lnk["verdict"] in target_verdicts:
            src = f"{lnk.get('downstream_case_id', 'downstream')}:{lnk.get('downstream_claim_id', '')}".strip(":")
            return _trigger_result(
                trigger,
                status="fired",
                observed_value=lnk["verdict"],
                matched_source=src or lnk.get("relation"),
                reason=f"Downstream {lnk.get('relation')} claim adjudicated '{lnk['verdict']}'",
            )
    return _trigger_result(
        trigger,
        status="unfired",
        observed_value=[lnk["verdict"] for lnk in adjudicated_links],
        matched_source=f"{adjudicated_links[0].get('downstream_case_id', 'downstream')}:{adjudicated_links[0].get('downstream_claim_id', '')}".strip(":"),
        reason=f"Adjudicated follow-up verdicts {[lnk['verdict'] for lnk in adjudicated_links]} did not match {list(target_verdicts)}",
    )


def _claim_has_contradiction(claim: dict) -> bool:
    for cards in (claim.get("provenance_cards") or {}).values():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if isinstance(card, dict) and str(card.get("status") or "").strip().lower() in (
                "fail",
                "failed",
                "contradicted",
                "refuted",
            ):
                return True
    return False


def _context_from_claim(
    claim: dict,
    *,
    evidence_by_id: dict[str, dict] | None = None,
    verification: dict | None = None,
    exec_events: list[dict] | None = None,
    replication_links: list[dict] | None = None,
) -> dict:
    claim_id = claim.get("id")
    card_groups = {
        c.get("details", {}).get("run_group")
        for c in (claim.get("provenance_cards") or {}).get("execution", ())
        if isinstance(c, dict) and isinstance(c.get("details"), dict) and c["details"].get("run_group")
    }
    scoped_exec = []
    for ev_rec in exec_events or ():
        if not isinstance(ev_rec, dict):
            continue
        ev_cid = ev_rec.get("claim_id")
        ev_rg = ev_rec.get("run_group")
        if ev_cid is not None and claim_id is not None and ev_cid != claim_id:
            continue
        if ev_cid is None and ev_rg is not None and ev_rg not in card_groups:
            continue
        scoped_exec.append(ev_rec)

    return {
        "effect_records": list(claim.get("effect_records") or ()),
        "checks": dict(claim.get("checks") or {}),
        "statistical_report": dict(claim.get("statistical_report") or {}),
        "design_packages": dict(claim.get("design_packages") or {}),
        "provenance_cards": dict(claim.get("provenance_cards") or {}),
        "claim_evidence_ids": list(claim.get("evidence_ids") or ()),
        "claim_has_contradiction": _claim_has_contradiction(claim),
        "evidence_verifications": _derive_evidence_verifications(evidence_by_id or {}, verification=verification),
        "exec_events": scoped_exec,
        "replication_links": list(replication_links or ()),
    }


def _trigger_conflicts_with_decision(trigger: dict, decision: dict) -> bool:
    dec_verdict = decision.get("verdict")
    targ_verdict = trigger.get("target_verdict")
    if dec_verdict in _POSITIVE_VERDICTS and targ_verdict in _NEGATIVE_VERDICTS:
        return True
    if dec_verdict == "supported" and targ_verdict == "partially_supported":
        return True
    targ_level = trigger.get("target_evidence_level")
    targ_type = trigger.get("target_claim_type")
    dec_type = decision.get("claim_type")
    dec_level = decision.get("evidence_level")
    if (
        dec_verdict in _POSITIVE_VERDICTS
        and targ_level is not None
        and dec_type in TYPE_LEVELS
        and (targ_type is None or targ_type == dec_type)
        and dec_level in TYPE_LEVELS[dec_type]
        and targ_level in TYPE_LEVELS[dec_type]
    ):
        levels = TYPE_LEVELS[dec_type]
        if levels.index(targ_level) < levels.index(dec_level):
            return True
    return False


def check_self_triggering_reversals(
    claim: dict,
    decision: dict,
    evidence_by_id: dict[str, dict],
    exec_events: list[dict] | None = None,
) -> None:
    """Fail if any reversal trigger already fires against the claim's own frozen evidence/checks."""
    triggers = collect_claim_triggers(claim, decision)
    if not triggers:
        return
    ctx = _context_from_claim(
        claim,
        evidence_by_id=evidence_by_id,
        exec_events=exec_events,
        replication_links=[],
    )
    for trigger in triggers:
        res = evaluate_single_trigger(trigger, ctx)
        if res["fired"] and _trigger_conflicts_with_decision(trigger, decision):
            target_desc = trigger["target_verdict"]
            if trigger.get("target_evidence_level"):
                target_desc = f"{target_desc} ({trigger.get('target_claim_type', '')} x {trigger['target_evidence_level']})"
            fail(
                "self_triggering_reversal_condition",
                f"claim '{claim['id']}' trigger '{trigger['id']}' already fires on frozen evidence/checks "
                f"(prescribes {target_desc}: {res['reason']}) in conflict with decision '{decision['verdict']}'",
            )


def validate_lineage_transition(
    claim: dict,
    decision: dict,
    cases_by_id: dict[str, dict],
    evidence_by_id: dict[str, dict],
    exec_events: list[dict] | None = None,
    *,
    current_case_id: str | None = None,
) -> None:
    """Verify prior_claim_links coherence and triggered_reversal_id execution at adjudication."""
    links = claim.get("prior_claim_links") or ()
    if not links:
        return

    for link in links:
        prior_case_id = link["prior_case_id"]
        prior_claim_id = link["prior_claim_id"]
        prior_case = cases_by_id.get(prior_case_id)
        if prior_case is None:
            fail("unknown_case", f"prior_case_id '{prior_case_id}' does not exist in this workspace")
        prior_claim = next((c for c in prior_case.get("claims", ()) if c.get("id") == prior_claim_id), None)
        if prior_claim is None:
            fail("unknown_prior_claim", f"prior_claim_id '{prior_claim_id}' does not exist in case '{prior_case_id}'")

        prior_decision = None
        if prior_case.get("adjudication"):
            for dec in prior_case["adjudication"].get("decisions", ()):
                if dec.get("claim_id") == prior_claim_id:
                    prior_decision = dec
                    break

        if link["relation"] in ("reverses", "refutes") and prior_decision is not None:
            same_verdict = prior_decision.get("verdict") == "supported" and decision.get("verdict") == "supported"
            same_class = (
                decision.get("claim_type") == prior_decision.get("claim_type")
                and decision.get("evidence_level") == prior_decision.get("evidence_level")
                and (decision.get("scope") or "").strip() == (prior_decision.get("scope") or "").strip()
            )
            same_text = (decision.get("revised_text") or "").strip() == (prior_decision.get("revised_text") or "").strip()
            if same_verdict and same_class and same_text:
                fail(
                    "contradictory_claim_lineage_transition",
                    f"claim '{claim['id']}' declares '{link['relation']}' against '{prior_case_id}:{prior_claim_id}' "
                    f"yet reproduces an identical supported proposition, scope, and classification",
                )

        trig_id = link.get("triggered_reversal_id")
        if trig_id is not None:
            prior_triggers = {t["id"]: t for t in collect_claim_triggers(prior_claim, prior_decision)}
            if trig_id not in prior_triggers:
                fail(
                    "unknown_reversal_trigger",
                    f"triggered_reversal_id '{trig_id}' was not defined on '{prior_case_id}:{prior_claim_id}'",
                )
            rep_entry = {
                "prior_case_id": prior_case_id,
                "prior_claim_id": prior_claim_id,
                "downstream_case_id": current_case_id,
                "downstream_claim_id": claim["id"],
                "relation": link["relation"],
                "verdict": decision.get("verdict"),
                "claim_type": decision.get("claim_type"),
                "evidence_level": decision.get("evidence_level"),
                "scope": decision.get("scope"),
                "reason": link.get("reason"),
            }
            ctx = _context_from_claim(
                claim,
                evidence_by_id=evidence_by_id,
                exec_events=exec_events,
                replication_links=[rep_entry],
            )
            res = evaluate_single_trigger(prior_triggers[trig_id], ctx)
            if not res["fired"]:
                fail(
                    "untriggered_reversal_link",
                    f"claim '{claim['id']}' declared triggered_reversal_id='{trig_id}' on "
                    f"'{prior_case_id}:{prior_claim_id}', but trigger evaluation status was '{res['status']}' ({res['reason']})",
                )


def _recommended_revision_from_fired(claim: dict, decision: dict | None, fired_results: list[dict]) -> dict | None:
    if not fired_results:
        return None
    verdict_rank = {"unsupported": 0, "insufficient_evidence": 1, "partially_supported": 2, "supported": 3}
    chosen_verdict = min((r["target_verdict"] for r in fired_results), key=lambda v: verdict_rank.get(v, 99))

    chosen_type = next((r["target_claim_type"] for r in fired_results if r.get("target_claim_type")), None)
    if chosen_type is None:
        chosen_type = (decision or claim).get("claim_type")

    chosen_level = None
    if chosen_type in TYPE_LEVELS:
        levels = TYPE_LEVELS[chosen_type]
        cand_levels = [
            r["target_evidence_level"]
            for r in fired_results
            if r.get("target_evidence_level") in levels and (r.get("target_claim_type") in (None, chosen_type))
        ]
        if cand_levels:
            chosen_level = min(cand_levels, key=lambda lv: levels.index(lv))
    if chosen_level is None:
        chosen_level = (decision or claim).get("evidence_level")

    chosen_scope = next((r["target_scope"] for r in fired_results if r.get("target_scope")), None)
    if chosen_scope is None:
        chosen_scope = (decision or claim).get("scope")

    return {
        "verdict": chosen_verdict,
        "claim_type": chosen_type,
        "evidence_level": chosen_level,
        "scope": chosen_scope,
        "trigger_ids": [r["id"] for r in fired_results],
        "reasons": [r["reason"] for r in fired_results],
    }


def _downstream_links_for_claim(source_case_id: str, source_claim_id: str, downstream_cases: list[dict] | None) -> tuple[list[dict], list[dict]]:
    links: list[dict] = []
    matched_claims: list[dict] = []
    for ds_case in downstream_cases or ():
        ds_id = ds_case.get("case_id")
        if ds_id == source_case_id:
            continue
        ds_dec_by_cid = {}
        if ds_case.get("adjudication"):
            for dec in ds_case["adjudication"].get("decisions", ()):
                ds_dec_by_cid[dec.get("claim_id")] = dec
        for ds_claim in ds_case.get("claims", ()):
            for lnk in ds_claim.get("prior_claim_links") or ():
                if lnk.get("prior_case_id") == source_case_id and lnk.get("prior_claim_id") == source_claim_id:
                    matched_claims.append(ds_claim)
                    dec = ds_dec_by_cid.get(ds_claim.get("id"))
                    links.append({
                        "prior_case_id": source_case_id,
                        "prior_claim_id": source_claim_id,
                        "downstream_case_id": ds_id,
                        "downstream_claim_id": ds_claim.get("id"),
                        "relation": lnk.get("relation"),
                        "verdict": dec.get("verdict") if dec else None,
                        "claim_type": (dec or ds_claim).get("claim_type"),
                        "evidence_level": (dec or ds_claim).get("evidence_level"),
                        "scope": (dec or ds_claim).get("scope"),
                        "reason": lnk.get("reason"),
                    })
    return links, matched_claims


def _match_against_claims(source_case: dict, source_claim: dict, against_case: dict) -> list[dict]:
    explicit = []
    source_id = source_case.get("case_id")
    src_cid = source_claim.get("id")
    for ag_claim in against_case.get("claims", ()):
        for lnk in ag_claim.get("prior_claim_links") or ():
            if lnk.get("prior_case_id") == source_id and lnk.get("prior_claim_id") == src_cid:
                explicit.append(ag_claim)
                break
    if explicit:
        return explicit
    same_id = [c for c in against_case.get("claims", ()) if c.get("id") == src_cid]
    if same_id:
        return same_id
    if len(source_case.get("claims", ())) == 1 and len(against_case.get("claims", ())) == 1:
        return list(against_case.get("claims", ()))
    return []


def evaluate_case_triggers(
    case: dict,
    *,
    against_case: dict | None = None,
    observations: dict | None = None,
    downstream_cases: list[dict] | None = None,
    verification: dict | None = None,
    exec_events: list[dict] | None = None,
    evidence_by_id: dict[str, dict] | None = None,
    against_verification: dict | None = None,
    against_exec_events: list[dict] | None = None,
    against_evidence_by_id: dict[str, dict] | None = None,
) -> dict:
    """Evaluate all claim/decision triggers for a case across against_case, observations, or live workspace."""
    case_id = case["case_id"]
    dec_by_cid = {}
    if case.get("adjudication"):
        for dec in case["adjudication"].get("decisions", ()):
            dec_by_cid[dec["claim_id"]] = dec

    if observations is not None:
        evaluation_mode = "observations"
        against_case_id = None
    elif against_case is not None:
        evaluation_mode = "against_case"
        against_case_id = against_case["case_id"]
    else:
        evaluation_mode = "live_workspace"
        against_case_id = None

    total_triggers = 0
    fired_count = 0
    unfired_count = 0
    pending_data_count = 0
    fired_trigger_ids: list[str] = []
    claim_evaluations: list[dict] = []

    for claim in case.get("claims", ()):
        cid = claim["id"]
        decision = dec_by_cid.get(cid)
        triggers = collect_claim_triggers(claim, decision)

        if evaluation_mode == "observations":
            obs = dict(observations or {})
            if isinstance(obs.get("claims"), dict) and cid in obs["claims"]:
                per_claim = obs["claims"][cid]
                if isinstance(per_claim, dict):
                    obs = {**obs, **per_claim}
            rep_links = list(obs.get("replication_links") or ())
            if not rep_links and obs.get("verdict") is not None:
                rep_links.append({
                    "prior_case_id": case_id,
                    "prior_claim_id": cid,
                    "downstream_case_id": obs.get("downstream_case_id") or "observation",
                    "downstream_claim_id": obs.get("downstream_claim_id") or cid,
                    "relation": obs.get("relation") or "replicates",
                    "verdict": obs.get("verdict"),
                })
            obs_ev_verifications = {}
            for k, v in (obs.get("evidence_verifications") or {}).items():
                if isinstance(v, str):
                    obs_ev_verifications[k] = {"evidence_id": k, "status": v, "contradicts": v == "contradicts"}
                elif isinstance(v, dict):
                    obs_ev_verifications[k] = {
                        "evidence_id": k,
                        **v,
                        "contradicts": bool(v.get("contradicts")) or v.get("status") == "contradicts",
                    }
            ctx = {
                "effect_records": list(obs.get("effect_records") or ()),
                "checks": dict(obs.get("checks") or {}),
                "statistical_report": dict(obs.get("statistical_report") or {}),
                "design_packages": dict(obs.get("design_packages") or {}),
                "provenance_cards": dict(obs.get("provenance_cards") or {}),
                "claim_evidence_ids": [],
                "claim_has_contradiction": bool(obs.get("claim_has_contradiction")),
                "evidence_verifications": obs_ev_verifications,
                "exec_events": list(obs.get("exec_events") or ()),
                "replication_links": rep_links,
            }
        elif evaluation_mode == "against_case":
            assert against_case is not None
            matched = _match_against_claims(case, claim, against_case)
            rep_links, _ = _downstream_links_for_claim(case_id, cid, [against_case])
            ag_dec_by_cid = {}
            if against_case.get("adjudication"):
                for dec in against_case["adjudication"].get("decisions", ()):
                    ag_dec_by_cid[dec["claim_id"]] = dec
            if not rep_links and matched:
                for ag_claim in matched:
                    ag_dec = ag_dec_by_cid.get(ag_claim["id"])
                    if ag_dec:
                        rep_links.append({
                            "prior_case_id": case_id,
                            "prior_claim_id": cid,
                            "downstream_case_id": against_case["case_id"],
                            "downstream_claim_id": ag_claim["id"],
                            "relation": "replicates",
                            "verdict": ag_dec.get("verdict"),
                        })
            if matched:
                target_claim = matched[0]
                ctx = _context_from_claim(
                    target_claim,
                    evidence_by_id=against_evidence_by_id or {e["evidence_id"]: e for e in against_case.get("evidence", ())},
                    verification=against_verification or against_case.get("verification"),
                    exec_events=against_exec_events,
                    replication_links=rep_links,
                )
            else:
                ctx = {
                    "effect_records": [],
                    "checks": {},
                    "statistical_report": {},
                    "design_packages": {},
                    "provenance_cards": {},
                    "claim_evidence_ids": [],
                    "claim_has_contradiction": False,
                    "evidence_verifications": {},
                    "exec_events": [],
                    "replication_links": rep_links,
                }
        else:
            rep_links, _ = _downstream_links_for_claim(case_id, cid, downstream_cases)
            ctx = _context_from_claim(
                claim,
                evidence_by_id=evidence_by_id or {e["evidence_id"]: e for e in case.get("evidence", ())},
                verification=verification or case.get("verification"),
                exec_events=exec_events,
                replication_links=rep_links,
            )

        trigger_results = [evaluate_single_trigger(trig, ctx) for trig in triggers]
        claim_fired = [r for r in trigger_results if r["fired"]]
        total_triggers += len(trigger_results)
        for r in trigger_results:
            if r["status"] == "fired":
                fired_count += 1
                fired_trigger_ids.append(f"{cid}:{r['id']}")
            elif r["status"] == "unfired":
                unfired_count += 1
            else:
                pending_data_count += 1

        claim_evaluations.append({
            "claim_id": cid,
            "current_verdict": decision.get("verdict") if decision else None,
            "trigger_count": len(triggers),
            "fired_count": len(claim_fired),
            "unfired_count": sum(1 for r in trigger_results if r["status"] == "unfired"),
            "pending_data_count": sum(1 for r in trigger_results if r["status"] == "pending_data"),
            "triggers": trigger_results,
            "recommended_revision": _recommended_revision_from_fired(claim, decision, claim_fired),
        })

    return {
        "case_id": case_id,
        "evaluation_mode": evaluation_mode,
        "against_case_id": against_case_id,
        "total_triggers": total_triggers,
        "fired_count": fired_count,
        "unfired_count": unfired_count,
        "pending_data_count": pending_data_count,
        "fired_trigger_ids": fired_trigger_ids,
        "claim_evaluations": claim_evaluations,
    }


def _detect_cycles(adj: dict[str, list[str]]) -> bool:
    state: dict[str, int] = {}

    def _visit(node: str) -> bool:
        st = state.get(node, 0)
        if st == 1:
            return True
        if st == 2:
            return False
        state[node] = 1
        for nxt in adj.get(node, ()):
            if _visit(nxt):
                return True
        state[node] = 2
        return False

    return any(_visit(n) for n in adj if state.get(n, 0) == 0)


def _compute_active_standing(
    node_id: str,
    case_id: str,
    incoming_edges: list[dict],
    superseded_case_ids: set[str],
    dec_by_node: dict[str, dict | None],
) -> str:
    effective_relations: set[str] = set()
    for edge in incoming_edges:
        rel = edge["relation"]
        ds_dec = dec_by_node.get(edge["to_node_id"])
        if edge.get("status") != "effective" or ds_dec is None or ds_dec.get("verdict") not in _POSITIVE_VERDICTS:
            # A failed/inconclusive follow-up attempt does not alter prior standing.
            continue
        effective_relations.add(rel)

    for rel, standing in _STANDING_PRECEDENCE:
        if rel in effective_relations:
            return standing
    if case_id in superseded_case_ids:
        return "superseded"
    return "current"


def adjudication_is_effective(case: dict) -> bool:
    """A pending or held successor is visible in the graph but has no effect."""
    if case.get("state") not in ("adjudicated", "export_pending", "exported") or not case.get("adjudication"):
        return False
    if (case.get("verification") or {}).get("status") == "blocked":
        return False
    for event in reversed(case.get("human_decisions") or ()):
        if event.get("decision") == "accept":
            break
        if event.get("decision") in ("pause", "challenge", "defer"):
            return False
    return True


def build_claim_graph(cases: list[dict], *, case_id: str | None = None, claim_id: str | None = None) -> dict:
    """Construct the longitudinal cross-case claim graph DAG and verdict/standing trajectories."""
    cases_by_id = {c["case_id"]: c for c in cases}
    if case_id is not None and case_id not in cases_by_id:
        fail("unknown_case", f"case_id '{case_id}' does not exist in this workspace")
    if case_id is not None and claim_id is not None:
        target_claims = {c["id"] for c in cases_by_id[case_id].get("claims", ())}
        if claim_id not in target_claims:
            fail("unknown_claim", f"claim_id '{claim_id}' does not exist in case '{case_id}'")

    ordered_cases = sorted(cases, key=lambda c: (c.get("created_at") or "", c["case_id"]))
    case_edges: list[dict] = []
    downstream_cases_map: dict[str, list[str]] = {c["case_id"]: [] for c in ordered_cases}
    superseded_case_ids: set[str] = set()

    for c in ordered_cases:
        cid = c["case_id"]
        rel = c.get("case_relation")
        seen_parents: set[str] = set()
        for pid in c.get("prior_case_ids") or ():
            if pid in cases_by_id and pid != cid:
                edge_type = rel or "follow_up"
                case_edges.append({"from_case_id": pid, "to_case_id": cid, "edge_type": edge_type})
                downstream_cases_map[pid].append(cid)
                seen_parents.add(pid)
        sup_id = c.get("supersedes_case_id")
        if sup_id and sup_id in cases_by_id and sup_id != cid:
            decisions = (c.get("adjudication") or {}).get("decisions") or []
            effective = adjudication_is_effective(c) and bool(decisions) and all(d.get("verdict") in _POSITIVE_VERDICTS for d in decisions)
            if effective:
                superseded_case_ids.add(sup_id)
            if sup_id not in seen_parents:
                downstream_cases_map[sup_id].append(cid)
            case_edges.append({"from_case_id": sup_id, "to_case_id": cid, "edge_type": "supersedes", "status": "effective" if effective else "pending"})

    dec_by_node: dict[str, dict | None] = {}
    claim_by_node: dict[str, dict] = {}
    for c in ordered_cases:
        cid = c["case_id"]
        decs = {}
        if c.get("adjudication"):
            for dec in c["adjudication"].get("decisions", ()):
                decs[dec["claim_id"]] = dec
        for clm in c.get("claims", ()):
            nid = f"{cid}:{clm['id']}"
            claim_by_node[nid] = clm
            dec_by_node[nid] = decs.get(clm["id"])

    claim_edges: list[dict] = []
    downstream_by_node: dict[str, list[dict]] = {nid: [] for nid in claim_by_node}
    upstream_by_node: dict[str, list[dict]] = {nid: [] for nid in claim_by_node}

    for c in ordered_cases:
        cid = c["case_id"]
        for clm in c.get("claims", ()):
            to_nid = f"{cid}:{clm['id']}"
            to_dec = dec_by_node[to_nid]
            for lnk in clm.get("prior_claim_links") or ():
                from_cid = lnk["prior_case_id"]
                from_clmid = lnk["prior_claim_id"]
                from_nid = f"{from_cid}:{from_clmid}"
                from_clm = claim_by_node.get(from_nid)
                from_dec = dec_by_node.get(from_nid)
                from_type = (from_dec or from_clm or {}).get("claim_type")
                from_level = (from_dec or from_clm or {}).get("evidence_level")
                to_type = (to_dec or clm).get("claim_type")
                to_level = (to_dec or clm).get("evidence_level")
                edge = {
                    "status": "effective" if adjudication_is_effective(c) and to_dec and to_dec.get("verdict") in _POSITIVE_VERDICTS else "pending",
                    "from_case_id": from_cid,
                    "from_claim_id": from_clmid,
                    "to_case_id": cid,
                    "to_claim_id": clm["id"],
                    "from_node_id": from_nid,
                    "to_node_id": to_nid,
                    "relation": lnk["relation"],
                    "reason": lnk["reason"],
                    "triggered_reversal_id": lnk.get("triggered_reversal_id"),
                    "verdict_transition": {
                        "from": from_dec.get("verdict") if from_dec else None,
                        "to": to_dec.get("verdict") if to_dec else None,
                    },
                    "level_transition": {
                        "from": f"{from_type} x {from_level}" if from_type and from_level else from_level,
                        "to": f"{to_type} x {to_level}" if to_type and to_level else to_level,
                    },
                }
                claim_edges.append(edge)
                if from_nid in downstream_by_node:
                    downstream_by_node[from_nid].append(edge)
                if to_nid in upstream_by_node:
                    upstream_by_node[to_nid].append(edge)

    claim_nodes_all: list[dict] = []
    for c in ordered_cases:
        cid = c["case_id"]
        for clm in c.get("claims", ()):
            nid = f"{cid}:{clm['id']}"
            dec = dec_by_node[nid]
            triggers = collect_claim_triggers(clm, dec)
            standing = _compute_active_standing(
                nid,
                cid,
                downstream_by_node.get(nid, ()),
                superseded_case_ids,
                dec_by_node,
            )
            claim_nodes_all.append({
                "node_id": nid,
                "case_id": cid,
                "claim_id": clm["id"],
                "text": (dec or clm).get("revised_text") or clm.get("text"),
                "scope": (dec or clm).get("scope"),
                "claim_type": (dec or clm).get("claim_type"),
                "evidence_level": (dec or clm).get("evidence_level") or clm.get("level"),
                "frozen_claim_type": clm.get("claim_type"),
                "frozen_evidence_level": clm.get("evidence_level") or clm.get("level"),
                "verdict": dec.get("verdict") if dec else None,
                "forecast_probability": dec.get("forecast_probability") if dec else None,
                "trigger_count": len(triggers),
                "prior_links_count": len(clm.get("prior_claim_links") or ()),
                "downstream_links_count": len(downstream_by_node.get(nid, ())),
                "active_standing": standing,
            })

    case_nodes_all = [
        {
            "case_id": c["case_id"],
            "question": c["question"],
            "domain": c["domain"],
            "state": c["state"],
            "schema_version": c.get("schema_version", 1),
            "created_at": c.get("created_at"),
            "prior_case_ids": list(c.get("prior_case_ids") or ()),
            "supersedes_case_id": c.get("supersedes_case_id"),
            "case_relation": c.get("case_relation"),
            "claim_count": len(c.get("claims", ())),
            "downstream_case_ids": sorted(set(downstream_cases_map.get(c["case_id"], ()))),
        }
        for c in ordered_cases
    ]

    if case_id is not None or claim_id is not None:
        # Filter to connected component around the requested case/claim(s).
        seed_claims: set[str] = set()
        seed_cases: set[str] = set()
        if case_id is not None:
            seed_cases.add(case_id)
            if claim_id is not None:
                seed_claims.add(f"{case_id}:{claim_id}")
            else:
                seed_claims.update(
                    f"{case_id}:{clm['id']}" for clm in cases_by_id[case_id].get("claims", ())
                )
        elif claim_id is not None:
            for c in ordered_cases:
                for clm in c.get("claims", ()):
                    if clm["id"] == claim_id:
                        seed_claims.add(f"{c['case_id']}:{claim_id}")
                        seed_cases.add(c["case_id"])

        keep_claims = set(seed_claims)
        claim_undir: dict[str, set[str]] = {n["node_id"]: set() for n in claim_nodes_all}
        for e in claim_edges:
            if e["from_node_id"] in claim_undir and e["to_node_id"] in claim_undir:
                claim_undir[e["from_node_id"]].add(e["to_node_id"])
                claim_undir[e["to_node_id"]].add(e["from_node_id"])
        stack = list(keep_claims)
        while stack:
            cur = stack.pop()
            for nb in claim_undir.get(cur, ()):
                if nb not in keep_claims:
                    keep_claims.add(nb)
                    stack.append(nb)

        keep_cases = set(seed_cases) | {nid.split(":", 1)[0] for nid in keep_claims}
        case_undir: dict[str, set[str]] = {c["case_id"]: set() for c in ordered_cases}
        for ce in case_edges:
            if ce["from_case_id"] in case_undir and ce["to_case_id"] in case_undir:
                case_undir[ce["from_case_id"]].add(ce["to_case_id"])
                case_undir[ce["to_case_id"]].add(ce["from_case_id"])
        cstack = list(keep_cases)
        while cstack:
            cur = cstack.pop()
            for nb in case_undir.get(cur, ()):
                if nb not in keep_cases:
                    keep_cases.add(nb)
                    cstack.append(nb)

        if claim_id is None:
            keep_claims.update(
                n["node_id"] for n in claim_nodes_all if n["case_id"] in keep_cases
            )

        case_nodes = [n for n in case_nodes_all if n["case_id"] in keep_cases]
        case_edges = [e for e in case_edges if e["from_case_id"] in keep_cases and e["to_case_id"] in keep_cases]
        claim_nodes = [n for n in claim_nodes_all if n["node_id"] in keep_claims]
        claim_edges = [e for e in claim_edges if e["from_node_id"] in keep_claims and e["to_node_id"] in keep_claims]
    else:
        case_nodes = case_nodes_all
        claim_nodes = claim_nodes_all

    node_set = {n["node_id"] for n in claim_nodes}
    claim_adj: dict[str, list[str]] = {nid: [] for nid in node_set}
    indegree: dict[str, int] = {nid: 0 for nid in node_set}
    for e in claim_edges:
        if e["from_node_id"] in node_set and e["to_node_id"] in node_set:
            claim_adj[e["from_node_id"]].append(e["to_node_id"])
            indegree[e["to_node_id"]] += 1

    case_adj: dict[str, list[str]] = {n["case_id"]: [] for n in case_nodes}
    for ce in case_edges:
        if ce["from_case_id"] in case_adj and ce["to_case_id"] in case_adj:
            case_adj[ce["from_case_id"]].append(ce["to_case_id"])

    cycle_detected = _detect_cycles(claim_adj) or _detect_cycles(case_adj)

    # Extract root-to-leaf longitudinal claim chains (cycle-guarded).
    roots = sorted(nid for nid, deg in indegree.items() if deg == 0)
    if not roots and node_set:
        roots = sorted(node_set)
    chains: list[list[str]] = []

    def _dfs_chains(node: str, path: list[str], seen: set[str]) -> None:
        children = [nxt for nxt in sorted(claim_adj.get(node, ())) if nxt not in seen]
        if not children:
            chains.append(list(path))
            return
        for nxt in children:
            seen.add(nxt)
            path.append(nxt)
            _dfs_chains(nxt, path, seen)
            path.pop()
            seen.remove(nxt)

    for root in roots:
        _dfs_chains(root, [root], {root})

    return {
        "filter": {"case_id": case_id, "claim_id": claim_id},
        "case_nodes": case_nodes,
        "case_edges": case_edges,
        "claim_nodes": claim_nodes,
        "claim_edges": claim_edges,
        "chains": chains,
        "cycle_detected": cycle_detected,
    }
