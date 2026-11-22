"""First-class L1-Explore runtime: competing hypothesis tree, forking-paths tracker, and confirmatory lock.

Turns L1-Explore from prose-only guidelines into a lightweight, durable SQLite workflow:
  - init               : Start an exploratory tree around a scientific question
  - upsert_hypothesis  : Maintain 2-5 competing hypothesis cards (strongest_rival, discriminating_experiment,
                         cost, stopping_rule, kill_condition + optional numeric kill_threshold)
  - log_run            : Log exploratory experiments/analyses, track cumulative forking_paths_count (m),
                         compute multiplicity inflation, and evaluate kill thresholds automatically
  - kill_hypothesis    : Explicitly falsify/retire a hypothesis while preserving negative records
  - lock_plan          : Hash-lock a pre-committed confirmatory plan (estimand, primary endpoint,
                         analysis unit, sample size/MDE, exclusions, multiplicity, negative controls)
  - promote_to_case    : Transition a locked or explored hypothesis into a draft L2 case with the
                         frozen plan registered as evidence, rival/killed hypotheses as alternatives,
                         and cumulative exploratory_forks recorded honestly
  - get / list         : Read exploration tree state and prioritized next discriminating test
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Callable

from .claims import TYPE_LEVELS
from .contracts import DOMAINS, array, enum, fail, fields, obj, string
from .gates import validate_non_placeholder_text, validate_reversal_condition
from .storage import canonical_json, json_digest, new_id, utc_now


def _append_explore_event(db: sqlite3.Connection, explore_id: str, action: str, details: dict[str, Any]) -> None:
    recorded_at = utc_now()
    details_json = canonical_json(details)
    prev_row = db.execute(
        "SELECT event_hash FROM explore_events WHERE explore_id=? ORDER BY sequence DESC LIMIT 1",
        (explore_id,),
    ).fetchone()
    prev_hash = prev_row[0] if prev_row and prev_row[0] else "GENESIS"
    event_hash = json_digest({
        "explore_id": explore_id,
        "action": action,
        "recorded_at": recorded_at,
        "details": details_json,
        "prev_event_hash": prev_hash,
    })
    db.execute(
        "INSERT INTO explore_events(explore_id, action, recorded_at, details, prev_event_hash, event_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (explore_id, action, recorded_at, details_json, prev_hash, event_hash),
    )

EXPLORE_OPS = (
    "init",
    "upsert_hypothesis",
    "log_run",
    "kill_hypothesis",
    "lock_plan",
    "promote_to_case",
    "get",
    "list",
)
HYPOTHESIS_STATUSES = ("active", "killed", "promoted", "paused")
KILL_OPERATORS = ("lt", "le", "gt", "ge", "eq", "ne")
RUN_OUTCOMES = ("completed", "failed", "inconclusive", "killed_hypothesis")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("invalid_type", f"{name} must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        fail("invalid_value", f"{name} must be finite")
    return num


def _eval_threshold(observed: float, operator: str, threshold: float) -> bool:
    if operator == "lt":
        return observed < threshold
    if operator == "le":
        return observed <= threshold
    if operator == "gt":
        return observed > threshold
    if operator == "ge":
        return observed >= threshold
    if operator == "eq":
        return abs(observed - threshold) <= 1e-12
    return abs(observed - threshold) > 1e-12


def _validate_kill_threshold(raw: Any, label: str) -> dict[str, Any]:
    kt = obj(raw, label)
    fields(kt, {"metric", "operator", "threshold"}, {"metric", "operator", "threshold"}, label)
    return {
        "metric": string(kt["metric"], f"{label}.metric", maximum=100),
        "operator": enum(kt["operator"], KILL_OPERATORS, f"{label}.operator"),
        "threshold": _finite(kt["threshold"], f"{label}.threshold"),
    }


def _validate_hypothesis_card(raw: Any, domain: str) -> dict[str, Any]:
    card = obj(raw, "hypothesis")
    required = {
        "hypothesis_id",
        "statement",
        "claim_type",
        "evidence_level",
        "strongest_rival",
        "discriminating_experiment",
        "cost",
        "stopping_rule",
        "kill_condition",
    }
    allowed = required | {"kill_threshold", "status", "notes"}
    fields(card, allowed, required, "hypothesis")
    hid = string(card["hypothesis_id"], "hypothesis.hypothesis_id", maximum=100)
    ctype = enum(card["claim_type"], tuple(TYPE_LEVELS), "hypothesis.claim_type")
    if (domain == "scientific" and ctype == "engineering") or (
        domain == "general" and ctype not in ("description", "computational", "engineering")
    ):
        fail("invalid_value", "hypothesis.claim_type is incompatible with exploration domain")
    elevel = enum(card["evidence_level"], TYPE_LEVELS[ctype], "hypothesis.evidence_level")
    stmt = validate_non_placeholder_text(card["statement"], "hypothesis.statement")
    rival = validate_non_placeholder_text(card["strongest_rival"], "hypothesis.strongest_rival")
    exp = validate_non_placeholder_text(card["discriminating_experiment"], "hypothesis.discriminating_experiment")
    cost = validate_non_placeholder_text(card["cost"], "hypothesis.cost")
    stop = validate_non_placeholder_text(card["stopping_rule"], "hypothesis.stopping_rule")
    kill_cond = validate_reversal_condition(card["kill_condition"], "hypothesis.kill_condition")
    status = enum(card.get("status", "active"), HYPOTHESIS_STATUSES, "hypothesis.status")
    out: dict[str, Any] = {
        "hypothesis_id": hid,
        "origin": "exploratory",
        "statement": stmt,
        "claim_type": ctype,
        "evidence_level": elevel,
        "strongest_rival": rival,
        "discriminating_experiment": exp,
        "cost": cost,
        "stopping_rule": stop,
        "kill_condition": kill_cond,
        "status": status,
        "updated_at": utc_now(),
    }
    if "kill_threshold" in card and card["kill_threshold"] is not None:
        out["kill_threshold"] = _validate_kill_threshold(card["kill_threshold"], "hypothesis.kill_threshold")
    if "notes" in card and card["notes"] is not None:
        out["notes"] = string(card["notes"], "hypothesis.notes", maximum=4000)
    return out


def _load_exploration(db: sqlite3.Connection, explore_id: str) -> dict[str, Any]:
    row = db.execute("SELECT document FROM explorations WHERE id=?", (explore_id,)).fetchone()
    if row is None:
        fail("unknown_exploration", f"explore_id '{explore_id}' does not exist in this workspace")
    return json.loads(row[0])


def _save_exploration(db: sqlite3.Connection, doc: dict[str, Any]) -> None:
    doc["updated_at"] = utc_now()
    db.execute(
        "INSERT OR REPLACE INTO explorations(id, document, updated_at) VALUES (?, ?, ?)",
        (doc["explore_id"], canonical_json(doc), doc["updated_at"]),
    )


def _forking_summary(doc: dict[str, Any], alpha: float = 0.05) -> dict[str, Any]:
    forks = int(doc.get("exploratory_forks", 0))
    effective_m = max(1, forks)
    bonf = alpha / effective_m
    active = [h for h in doc["hypotheses"] if h.get("status") == "active"]
    killed = [h for h in doc["hypotheses"] if h.get("status") == "killed"]
    return {
        "exploratory_forks": forks,
        "nominal_alpha": alpha,
        "bonferroni_adjusted_alpha": round(bonf, 8),
        "multiplicity_warning": forks > 1,
        "active_hypotheses": len(active),
        "killed_hypotheses": len(killed),
        "total_runs": len(doc.get("runs") or ()),
        "confirmatory_plans_locked": len(doc.get("locked_plans") or ()),
        "next_discriminating_tests": [
            {
                "hypothesis_id": h["hypothesis_id"],
                "discriminating_experiment": h["discriminating_experiment"],
                "cost": h["cost"],
                "kill_condition": h["kill_condition"],
            }
            for h in active[:3]
        ],
    }


def dispatch_explore(
    db: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    promote_callback: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one durable L1-Explore operation inside an active SQLite transaction."""
    obj(payload, "explore")
    op = enum(payload.get("op"), EXPLORE_OPS, "explore.op")

    if op == "list":
        fields(payload, {"op"}, {"op"}, "explore.list")
        rows = db.execute("SELECT document FROM explorations ORDER BY updated_at DESC, id ASC").fetchall()
        items = []
        for (raw,) in rows:
            doc = json.loads(raw)
            items.append({
                "explore_id": doc["explore_id"],
                "question": doc["question"],
                "domain": doc["domain"],
                "created_at": doc["created_at"],
                "updated_at": doc["updated_at"],
                **_forking_summary(doc),
            })
        return {"op": "list", "count": len(items), "explorations": items}

    if op == "init":
        fields(payload, {"op", "question", "domain", "hypotheses"}, {"op", "question"}, "explore.init")
        question = validate_non_placeholder_text(payload["question"], "explore.question")
        domain = enum(payload.get("domain", "scientific"), DOMAINS, "explore.domain")
        initial_cards: list[dict[str, Any]] = []
        seen: set[str] = set()
        if "hypotheses" in payload:
            for item in array(payload["hypotheses"], "explore.hypotheses", minimum=1, maximum=8):
                card = _validate_hypothesis_card(item, domain)
                if card["hypothesis_id"] in seen:
                    fail("duplicate_id", f"Duplicate hypothesis_id '{card['hypothesis_id']}'")
                seen.add(card["hypothesis_id"])
                initial_cards.append(card)
        now = utc_now()
        doc: dict[str, Any] = {
            "explore_id": new_id("exp"),
            "question": question,
            "domain": domain,
            "created_at": now,
            "updated_at": now,
            "hypotheses": initial_cards,
            "runs": [],
            "exploratory_forks": 0,
            "locked_plans": [],
            "promoted_case_ids": [],
        }
        _save_exploration(db, doc)
        _append_explore_event(db, doc["explore_id"], "explore_init", {"domain": domain, "hypothesis_count": len(initial_cards)})
        return {"op": "init", "exploration": doc, "summary": _forking_summary(doc)}

    explore_id = string(payload.get("explore_id"), "explore.explore_id", maximum=200)
    doc = _load_exploration(db, explore_id)

    if op == "get":
        fields(payload, {"op", "explore_id"}, {"op", "explore_id"}, "explore.get")
        return {"op": "get", "exploration": doc, "summary": _forking_summary(doc)}

    if op == "upsert_hypothesis":
        fields(payload, {"op", "explore_id", "hypothesis"}, {"op", "explore_id", "hypothesis"}, "explore.upsert_hypothesis")
        card = _validate_hypothesis_card(payload["hypothesis"], doc["domain"])
        replaced = False
        for idx, existing in enumerate(doc["hypotheses"]):
            if existing["hypothesis_id"] == card["hypothesis_id"]:
                if existing.get("status") == "killed" and card["status"] == "active":
                    fail("invalid_state", f"Killed hypothesis '{card['hypothesis_id']}' cannot be silently resurrected; register a revised hypothesis_id")
                doc["hypotheses"][idx] = card
                replaced = True
                break
        if not replaced:
            if len(doc["hypotheses"]) >= 12:
                fail("too_large", "At most 12 hypothesis cards per exploration session")
            doc["hypotheses"].append(card)
        _save_exploration(db, doc)
        _append_explore_event(db, explore_id, "explore_upsert_hypothesis", {"hypothesis_id": card["hypothesis_id"], "replaced": replaced})
        return {"op": "upsert_hypothesis", "explore_id": explore_id, "hypothesis": card, "replaced": replaced, "summary": _forking_summary(doc)}

    if op == "log_run":
        allowed = {
            "op", "explore_id", "hypothesis_id", "summary", "outcome_status",
            "fork_count_delta", "observed_metrics", "command", "evidence_path", "notes",
        }
        required = {"op", "explore_id", "hypothesis_id", "summary", "outcome_status"}
        fields(payload, allowed, required, "explore.log_run")
        hid = string(payload["hypothesis_id"], "explore.hypothesis_id", maximum=100)
        target = next((h for h in doc["hypotheses"] if h["hypothesis_id"] == hid), None)
        if target is None:
            fail("unknown_hypothesis", f"hypothesis_id '{hid}' is not registered in exploration '{explore_id}'")
        summary_text = validate_non_placeholder_text(payload["summary"], "explore.summary")
        outcome = enum(payload["outcome_status"], RUN_OUTCOMES, "explore.outcome_status")
        delta = payload.get("fork_count_delta", 1)
        if isinstance(delta, bool) or not isinstance(delta, int) or delta < 1 or delta > 10_000:
            fail("invalid_value", "explore.fork_count_delta must be an integer between 1 and 10000")
        metrics_clean: dict[str, float] = {}
        if "observed_metrics" in payload and payload["observed_metrics"] is not None:
            raw_m = obj(payload["observed_metrics"], "explore.observed_metrics")
            for mk, mv in raw_m.items():
                metrics_clean[string(mk, "observed_metrics key", maximum=100)] = _finite(mv, f"observed_metrics.{mk}")
        kill_triggered = False
        kill_eval_detail: dict[str, Any] | None = None
        kt = target.get("kill_threshold")
        if kt and kt["metric"] in metrics_clean:
            obs_val = metrics_clean[kt["metric"]]
            kill_triggered = _eval_threshold(obs_val, kt["operator"], kt["threshold"])
            kill_eval_detail = {
                "metric": kt["metric"],
                "observed": obs_val,
                "operator": kt["operator"],
                "threshold": kt["threshold"],
                "triggered": kill_triggered,
            }
        run_record: dict[str, Any] = {
            "run_id": new_id("erun"),
            "hypothesis_id": hid,
            "summary": summary_text,
            "outcome_status": outcome,
            "fork_count_delta": delta,
            "observed_metrics": metrics_clean,
            "kill_triggered": kill_triggered,
            "kill_evaluation": kill_eval_detail,
            "recorded_at": utc_now(),
        }
        for opt in ("command", "evidence_path", "notes"):
            if opt in payload and payload[opt] is not None:
                run_record[opt] = string(payload[opt], f"explore.{opt}", maximum=2000)
        doc["runs"].append(run_record)
        doc["exploratory_forks"] = int(doc.get("exploratory_forks", 0)) + delta
        if outcome == "killed_hypothesis":
            target["status"] = "killed"
            target["killed_at"] = run_record["recorded_at"]
            target["kill_reason"] = summary_text
        _save_exploration(db, doc)
        _append_explore_event(
            db,
            explore_id,
            "explore_log_run",
            {"run_id": run_record["run_id"], "hypothesis_id": hid, "fork_delta": delta, "kill_triggered": kill_triggered},
        )
        from .copilot import build_explore_copilot_guidance

        return {
            "op": "log_run",
            "explore_id": explore_id,
            "run": run_record,
            "kill_triggered": kill_triggered,
            "summary": _forking_summary(doc),
            "copilot_guidance": build_explore_copilot_guidance(doc),
        }

    if op == "kill_hypothesis":
        fields(payload, {"op", "explore_id", "hypothesis_id", "reason", "run_ids"}, {"op", "explore_id", "hypothesis_id", "reason"}, "explore.kill_hypothesis")
        hid = string(payload["hypothesis_id"], "explore.hypothesis_id", maximum=100)
        target = next((h for h in doc["hypotheses"] if h["hypothesis_id"] == hid), None)
        if target is None:
            fail("unknown_hypothesis", f"hypothesis_id '{hid}' is not registered in exploration '{explore_id}'")
        reason = validate_non_placeholder_text(payload["reason"], "explore.reason")
        known_runs = {r["run_id"] for r in doc["runs"]}
        run_ids = []
        if "run_ids" in payload:
            for rid in array(payload["run_ids"], "explore.run_ids", minimum=0, maximum=50):
                s = string(rid, "explore.run_ids", maximum=200)
                if s not in known_runs:
                    fail("unknown_reference", f"Unknown exploration run_id '{s}'")
                run_ids.append(s)
        target["status"] = "killed"
        target["killed_at"] = utc_now()
        target["kill_reason"] = reason
        target["kill_run_ids"] = run_ids
        _save_exploration(db, doc)
        _append_explore_event(db, explore_id, "explore_kill_hypothesis", {"hypothesis_id": hid, "run_ids": run_ids})
        return {"op": "kill_hypothesis", "explore_id": explore_id, "hypothesis": target, "summary": _forking_summary(doc)}

    if op == "lock_plan":
        required = {
            "op", "explore_id", "hypothesis_id", "estimand", "primary_endpoint",
            "analysis_unit", "sample_size_plan", "exclusion_rules",
            "multiplicity_strategy", "negative_controls", "kill_criteria",
        }
        fields(payload, required | {"notes"}, required, "explore.lock_plan")
        hid = string(payload["hypothesis_id"], "explore.hypothesis_id", maximum=100)
        target = next((h for h in doc["hypotheses"] if h["hypothesis_id"] == hid), None)
        if target is None:
            fail("unknown_hypothesis", f"hypothesis_id '{hid}' is not registered in exploration '{explore_id}'")
        if target.get("status") == "killed":
            fail("invalid_state", f"Cannot lock a confirmatory plan on killed hypothesis '{hid}'")
        plan_body = {
            "explore_id": explore_id,
            "hypothesis_id": hid,
            "hypothesis_statement": target["statement"],
            "prior_exploratory_forks": int(doc.get("exploratory_forks", 0)),
            "estimand": validate_non_placeholder_text(payload["estimand"], "lock_plan.estimand"),
            "primary_endpoint": validate_non_placeholder_text(payload["primary_endpoint"], "lock_plan.primary_endpoint"),
            "analysis_unit": validate_non_placeholder_text(payload["analysis_unit"], "lock_plan.analysis_unit"),
            "sample_size_plan": validate_non_placeholder_text(payload["sample_size_plan"], "lock_plan.sample_size_plan"),
            "exclusion_rules": validate_non_placeholder_text(payload["exclusion_rules"], "lock_plan.exclusion_rules"),
            "multiplicity_strategy": validate_non_placeholder_text(payload["multiplicity_strategy"], "lock_plan.multiplicity_strategy"),
            "negative_controls": validate_non_placeholder_text(payload["negative_controls"], "lock_plan.negative_controls"),
            "kill_criteria": validate_reversal_condition(payload["kill_criteria"], "lock_plan.kill_criteria"),
        }
        if "notes" in payload and payload["notes"] is not None:
            plan_body["notes"] = string(payload["notes"], "lock_plan.notes", maximum=4000)
        plan_record = {
            "plan_id": new_id("plan"),
            **plan_body,
            "locked_at": utc_now(),
            "plan_digest": json_digest(plan_body),
            "timing_basis": "local_hash_lock_not_external_registry",
        }
        doc["locked_plans"].append(plan_record)
        _save_exploration(db, doc)
        _append_explore_event(db, explore_id, "explore_lock_plan", {"plan_id": plan_record["plan_id"], "plan_digest": plan_record["plan_digest"]})
        from .copilot import build_explore_copilot_guidance

        return {
            "op": "lock_plan",
            "explore_id": explore_id,
            "plan": plan_record,
            "summary": _forking_summary(doc),
            "copilot_guidance": build_explore_copilot_guidance(doc),
        }

    # promote_to_case
    fields(
        payload,
        {"op", "explore_id", "hypothesis_id", "plan_id", "draft", "scope", "writer_context_id", "symmetry_mode", "blind_mode"},
        {"op", "explore_id", "hypothesis_id"},
        "explore.promote_to_case",
    )
    hid = string(payload["hypothesis_id"], "explore.hypothesis_id", maximum=100)
    target = next((h for h in doc["hypotheses"] if h["hypothesis_id"] == hid), None)
    if target is None:
        fail("unknown_hypothesis", f"hypothesis_id '{hid}' is not registered in exploration '{explore_id}'")
    if target.get("status") == "killed":
        fail("invalid_state", f"Cannot promote killed hypothesis '{hid}' into a positive confirmatory L2 case")
    if promote_callback is None:
        fail("invalid_state", "promote_to_case requires an Engine workspace callback")
    promoted = promote_callback(doc, payload)
    target["status"] = "promoted"
    target["promoted_case_id"] = promoted["case_id"]
    doc["promoted_case_ids"].append(promoted["case_id"])
    _save_exploration(db, doc)
    _append_explore_event(db, explore_id, "explore_promote_to_case", {"hypothesis_id": hid, "case_id": promoted["case_id"]})
    return {
        "op": "promote_to_case",
        "explore_id": explore_id,
        "hypothesis_id": hid,
        **promoted,
        "summary": _forking_summary(doc),
    }
