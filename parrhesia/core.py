"""Durable claim review, without pretending that provenance is scientific truth."""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from pathlib import Path
import sqlite3
from typing import Any

from .contracts import (
    ACTIONABLE_STANCES, ACTIONS, ALTERNATIVE_STATUSES, CHECK_NAMES, CHECK_STATUSES, DOMAINS,
    ENGINEERING_LEVELS, GENERAL_LEVELS, LEVELS, ORIGINS, PROVENANCE, ROLES,
    SCIENTIFIC_LEVELS, SYMMETRY_MODES, VERDICTS, ContractError, array, enum, fail, fields, ids, obj, string,
)
from .claims import TYPE_LEVELS, classification, describe, scaffold_claim_template, validate_content, validate_support
from .calibration import compute_calibration_report, validate_calibration_outcome, validate_forecast_probability
from .compact_ledger import compile_compact_claim, compute_ceiling_diff
from .copilot import _load_case_exec_events, analyze_case_copilot, analyze_claim_copilot
from .effects import verify_effect_computations
from .explore import dispatch_explore
from .gates import (
    BOILERPLATE_OVERHEDGING_RE, GATE_VERSION, GATE_GUIDANCE, EVIDENCE_KINDS, audit_underclaim_and_abstention,
    ceiling, enforce_symmetry_adjudication, evidence_lineage, gated, is_placeholder, is_vacuous_rationale,
    quote_status, strip_terminal_escapes, text_content, meaningful, validate_abstention_justification,
    validate_basis, validate_condition_text, validate_disposition, validate_evidence_dominance,
    validate_mechanical, validate_non_placeholder_text, validate_rationale, validate_reversal_condition,
    validate_stances, validate_unread_ack,
)
from .isolation import BLIND_MODES, PACKET_STAGES, compute_isolation_grade, packet_content_sha256, validate_isolation_receipt
from .methods import analyze_design
from .synthesis import dispatch_lineage_synthesis, synthesize_claim_lineage
from .packets import (
    INTEGRITY_BOUNDARY,
    PACKET_TEXT_BYTES,
    ROLE_INSTRUCTIONS,
    V2_REVIEW_GUIDANCE,
    assemble_adjudication_packet,
    assemble_review_packet,
    build_chunked_windows,
    check_calibration_sources,
    line_span,
    packet_evidence,
    packet_evidence_entry,
)
from .report import (
    escape_markdown as _md,
    render_markdown_report,
    structured_markdown as _structured_markdown,
)
from .storage import (
    MAX_SOURCE_BYTES,
    append_event,
    bytes_digest as _bytes_digest,
    canonical_json as _json,
    connect_db,
    connect_readonly,
    initialize_database,
    json_digest as _digest,
    list_case_summaries,
    load_all_cases_by_id,
    load_calibration_relevant_cases,
    load_cases_for_ids,
    load_connected_component_cases,
    load_downstream_cases,
    lookup_evidence_case_ids,
    materialize_file_atomically,
    new_id as _id,
    read_regular_source,
    record_kind_restriction,
    reject_link,
    safe_workspace_path,
    should_fallback_from_link as _should_fallback_from_link,
    sync_case_indexes,
    utc_now as _now,
    verify_event_chain as _verify_event_chain,
    write_exclusive_export as _write_exclusive_export,
)
from .triggers import (
    CASE_RELATIONS, MAX_PRIOR_CASES, build_claim_graph, check_self_triggering_reversals,
    collect_claim_triggers, evaluate_case_triggers, validate_lineage_transition,
    validate_prior_claim_links_references, validate_reversal_triggers,
)


class Engine:
    """One local workspace. Each dispatch is serialized with a SQLite transaction."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            fail("invalid_workspace", "workspace must be an existing directory")
        self.state_dir = self.workspace / ".parrhesia"
        self._reject_link(self.state_dir)
        self.state_dir.mkdir(exist_ok=True)
        self.database = self.state_dir / "state.sqlite3"
        self._reject_link(self.database)
        initialize_database(self.state_dir, self.database)

    @staticmethod
    def _record_kind_restriction(db: sqlite3.Connection, case_id: str, evidence: dict[str, Any]) -> None:
        record_kind_restriction(db, case_id, evidence)

    def _connect(self):
        return connect_db(self.state_dir, self.database)

    @staticmethod
    def _reject_link(path: Path) -> None:
        reject_link(path)

    def _path(self, relative: Any) -> Path:
        return safe_workspace_path(self.workspace, relative)

    @classmethod
    def read_case_snapshot(cls, workspace: str | Path, case_id: str) -> dict:
        """Load and integrity-check a saved case without constructing a writable engine."""
        root = Path(workspace).resolve(strict=True)
        string(case_id, "case_id", maximum=200)
        state_dir = root / ".parrhesia"
        try:
            with connect_readonly(state_dir, state_dir / "state.sqlite3") as db:
                row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
                if row is None:
                    fail("unknown_case", "case_id does not identify a saved case")
                case = json.loads(row[0])
                if case["case_id"] != case_id:
                    fail("case_integrity_error", "Stored case identity differs from its database key")
                if case["state"] != "draft":
                    cls._validate_frozen(case)
                return cls._get_case(db, case, {"case_id": case_id})
        except sqlite3.DatabaseError as exc:
            fail("snapshot_unavailable", f"Cannot read saved database without migration: {exc.__class__.__name__}")

    @classmethod
    def read_workspace_cases_snapshot(cls, workspace: str | Path) -> list[dict]:
        """Load and integrity-check every saved case read-only without constructing a writable engine."""
        raw_path = Path(workspace)
        if not raw_path.exists() or not raw_path.is_dir():
            fail("missing_workspace", "Select an existing Parrhesia workspace with a saved case")
        root = raw_path.resolve(strict=True)
        state_dir = root / ".parrhesia"
        try:
            with connect_readonly(state_dir, state_dir / "state.sqlite3") as db:
                chain = _verify_event_chain(db, None)
                if chain["status"] == "tampered":
                    fail("event_chain_tampered", "Saved event history failed integrity checks; synthesis aborted")
                rows = db.execute("SELECT id, document FROM cases ORDER BY rowid ASC").fetchall()
                cases: list[dict] = []
                for row_id, raw_doc in rows:
                    case = json.loads(raw_doc)
                    if case.get("case_id") != row_id:
                        fail("case_integrity_error", "Stored case identity differs from its database key")
                    if case.get("state") != "draft":
                        cls._validate_frozen(case)
                    cases.append(case)
                return cases
        except sqlite3.DatabaseError as exc:
            fail("snapshot_unavailable", f"Cannot read saved database without migration: {exc.__class__.__name__}")

    def _read_source(self, path: Path) -> bytes:
        return read_regular_source(path)

    def _tex_include_resolver(self, target: str, cur_path: str) -> tuple[str, bytes] | None:
        raw = target.strip().replace("\\", "/")
        if not raw or raw.startswith("/") or ":" in raw or "\x00" in raw:
            return None
        cur_dir = posixpath.dirname(cur_path.replace("\\", "/"))
        base_candidates: list[str] = []
        rel_cur = posixpath.normpath(posixpath.join(cur_dir, raw)) if cur_dir else posixpath.normpath(raw)
        base_candidates.append(rel_cur)
        root_norm = posixpath.normpath(raw)
        if root_norm not in base_candidates:
            base_candidates.append(root_norm)
        expanded: list[str] = []
        for cand in base_candidates:
            if Path(cand).suffix:
                expanded.extend([cand, f"{cand}.tex"])
            else:
                expanded.extend([f"{cand}.tex", cand])
        for cand in expanded:
            if not cand or cand == "." or cand.startswith(".."):
                continue
            try:
                resolved = self._path(cand)
                if not resolved.exists() or not resolved.is_file():
                    continue
                content = self._read_source(resolved)
                return resolved.relative_to(self.workspace).as_posix(), content
            except ContractError as exc:
                if exc.code == "too_large":
                    raise
                continue
            except OSError:
                continue
        return None

    def _dvc_digest_resolver(self, dvc_path: str, target_path: str, algorithm: str) -> dict[str, Any]:
        raw = str(target_path).strip().replace("\\", "/")
        if not raw or raw.startswith("/") or ":" in raw or "\x00" in raw:
            return {"status": "outside_workspace", "reason": "DVC target path must be relative to workspace"}
        dvc_dir = posixpath.dirname(dvc_path.replace("\\", "/"))
        cand = posixpath.normpath(posixpath.join(dvc_dir, raw)) if dvc_dir else posixpath.normpath(raw)
        if not cand or cand == "." or cand.startswith(".."):
            return {"status": "outside_workspace", "reason": "DVC target path escapes workspace"}
        try:
            resolved = self._path(cand)
        except ContractError as exc:
            return {"status": "outside_workspace", "reason": exc.message}
        try:
            if not resolved.exists():
                return {"status": "missing"}
            if not resolved.is_file():
                return {"status": "not_regular_file"}
            data = self._read_source(resolved)
        except ContractError as exc:
            return {"status": exc.code, "reason": exc.message}
        except OSError:
            return {"status": "unreadable"}
        digest = hashlib.md5(data).hexdigest() if algorithm.lower() == "md5" else hashlib.sha256(data).hexdigest()
        return {
            "status": "hashed",
            "actual_digest": digest,
            "resolved_path": resolved.relative_to(self.workspace).as_posix(),
            "size": len(data),
        }

    def _dispatch_tx(self, db: sqlite3.Connection, action: str, payload: dict, *, dry_run: bool = False) -> dict:
        if action == "create_case":
            return self._create_case(db, payload)
        if action == "scaffold_claim":
            return self._scaffold_claim(db, payload)
        if action == "draft_manuscript":
            return self._draft_manuscript(db, payload)
        if action == "explore":
            return dispatch_explore(
                db,
                payload,
                promote_callback=lambda doc, req: self._promote_exploration_to_case(db, doc, req, dry_run=dry_run),
            )
        if action == "analyze_design":
            def _lineage_cb(p: dict) -> dict:
                cid = p.get("case_id") if isinstance(p.get("case_id"), str) else None
                clmid = p.get("claim_id") if isinstance(p.get("claim_id"), str) else None
                cases = load_connected_component_cases(db, case_id=cid, claim_id=clmid)
                return dispatch_lineage_synthesis(cases, p)

            return analyze_design(
                payload,
                case_audit_callback=lambda p: analyze_case_copilot(db, p),
                lineage_synthesis_callback=_lineage_cb,
            )
        if action == "claim_graph":
            return self._claim_graph(db, payload)
        if action == "calibration_report":
            return self._calibration_report(db, payload)
        case_id = string(payload.get("case_id"), "case_id", maximum=200)
        row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            fail("unknown_case", "case_id does not exist in this workspace")
        case = json.loads(row[0])
        gated(case)  # Reject unsupported contracts before any legacy dispatch.
        if case["state"] != "draft":
            self._validate_frozen(case)
        if "pause" in self._human_holds(case):
            read_actions = {
                "record_human_decision", "get_case", "verify", "review_packet",
                "claim_graph", "evaluate_triggers", "calibration_report",
                "extract_effects",
            }
            # Retrieving an existing adjudication packet is a read; creating one is a workflow step.
            if case.get("adjudication_packet"):
                read_actions.add("adjudication_packet")
            if action not in read_actions:
                fail("human_paused", "a reported human pause requires a subsequent explicit accept before workflow mutation")
        if action == "evaluate_triggers":
            return self._evaluate_triggers(db, case, payload)
        handler = getattr(self, "_" + action)
        result = handler(db, case, payload)
        db.execute("UPDATE cases SET document=? WHERE id=?", (_json(case), case_id))
        sync_case_indexes(db, case)
        return result

    def dispatch(self, action: str, payload: dict) -> dict:
        enum(action, ACTIONS, "action")
        obj(payload, "payload")
        # A JSON round trip prevents callers retaining mutable references into stored results.
        try:
            payload = json.loads(_json(payload))
        except (ValueError, TypeError):
            fail("invalid_json", "payload must contain finite JSON-compatible values")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = self._dispatch_tx(db, action, payload)
        if action == "export":
            return self._materialize_export(payload["case_id"])
        return json.loads(_json(result))

    def validate_action(self, action: str, payload: dict, *, collect_all: bool = False) -> dict:
        """Run full dispatch validation inside BEGIN IMMEDIATE and always roll back."""
        enum(action, ACTIONS, "action")
        obj(payload, "payload")
        try:
            payload = json.loads(_json(payload))
        except (ValueError, TypeError):
            fail("invalid_json", "payload must contain finite JSON-compatible values")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if collect_all and action in ("set_ledger", "submit_adjudication"):
                    return self._collect_batch_diagnostics(db, action, payload)
                preview = json.loads(_json(self._dispatch_tx(db, action, payload, dry_run=True)))
            finally:
                db.rollback()
        return {"valid": True, "action": action, "dry_run": True, "preview": preview}

    def _collect_batch_diagnostics(self, db: sqlite3.Connection, action: str, payload: dict) -> dict:
        """Collect all per-item validation issues and ceiling diffs in a single dry-run pass."""
        from .mcp_prompts import repair_hint_for

        issues: list[dict[str, Any]] = []
        ceilings: dict[str, Any] = {}
        try:
            preview = json.loads(_json(self._dispatch_tx(db, action, payload)))
            return {"valid": True, "action": action, "dry_run": True, "issues": [], "preview": preview}
        except ContractError as top_exc:
            cid = payload.get("case_id")
            row = db.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone() if isinstance(cid, str) else None
            if row is None:
                return {
                    "valid": False,
                    "action": action,
                    "dry_run": True,
                    "error": top_exc.code,
                    "message": top_exc.message,
                    "repair_hint": repair_hint_for(top_exc.code, top_exc.message, action=action),
                    "issues": [{"path": action, "error": top_exc.code, "message": top_exc.message, "repair_hint": repair_hint_for(top_exc.code, top_exc.message, action=action)}],
                }
            case = json.loads(row[0])
            if action == "set_ledger" and isinstance(payload.get("claims"), list):
                ev_ids = {item["evidence_id"] for item in case.get("evidence") or ()}
                hyps = {item["hypothesis_id"]: item for item in case.get("hypotheses") or ()}
                domain = case.get("domain", "scientific")
                for idx, raw_cl in enumerate(payload["claims"]):
                    cl_label = raw_cl.get("id") if isinstance(raw_cl, dict) and raw_cl.get("id") else f"claims[{idx}]"
                    try:
                        validated_cl = self._claim(json.loads(_json(raw_cl)), ev_ids, hyps, domain, case.get("schema_version", 1), gated(case))
                        ceilings[validated_cl["id"]] = compute_ceiling_diff(validated_cl)
                    except ContractError as exc:
                        issues.append({
                            "path": f"claims[{idx}] ({cl_label})",
                            "error": exc.code,
                            "message": exc.message,
                            "repair_hint": repair_hint_for(exc.code, exc.message, action=action),
                        })
            elif action == "submit_adjudication" and isinstance(payload.get("decisions"), list):
                claims_map = {c["id"]: c for c in case.get("claims") or ()}
                ev_pkt = self._packet_evidence(db, case, strict=False) if gated(case) else []
                ev_by_id = {e["evidence_id"]: e for e in ev_pkt}
                exec_events = self._exec_events(db, case["case_id"]) if gated(case) else []
                for idx, raw_dec in enumerate(payload["decisions"]):
                    if not isinstance(raw_dec, dict):
                        issues.append({"path": f"decisions[{idx}]", "error": "invalid_type", "message": "decision must be an object", "repair_hint": repair_hint_for("invalid_type", action=action)})
                        continue
                    cl_id = raw_dec.get("claim_id")
                    if cl_id in claims_map:
                        ceilings[cl_id] = compute_ceiling_diff(claims_map[cl_id], raw_dec.get("evidence_level"))
                        try:
                            if gated(case):
                                validate_support(raw_dec, claims_map[cl_id])
                                validate_mechanical(raw_dec, claims_map[cl_id], ev_by_id, exec_events=exec_events)
                                validate_rationale(raw_dec.get("rationale", ""), "decision.rationale")
                                validate_reversal_condition(raw_dec.get("reversal_condition", ""), "decision.reversal_condition", decision=raw_dec, claim=claims_map[cl_id])
                        except ContractError as exc:
                            issues.append({
                                "path": f"decisions[{idx}] ({cl_id})",
                                "error": exc.code,
                                "message": exc.message,
                                "repair_hint": repair_hint_for(exc.code, exc.message, action=action),
                            })
            if not issues:
                issues.append({
                    "path": action,
                    "error": top_exc.code,
                    "message": top_exc.message,
                    "repair_hint": repair_hint_for(top_exc.code, top_exc.message, action=action),
                })
            return {
                "valid": False,
                "action": action,
                "dry_run": True,
                "error": top_exc.code,
                "message": top_exc.message,
                "repair_hint": repair_hint_for(top_exc.code, top_exc.message, action=action),
                "issue_count": len(issues),
                "issues": issues,
                "ceiling_diffs": ceilings,
            }

    def list_cases(self) -> list[dict]:
        """Return read-only metadata summaries for all cases without parsing case JSON blobs."""
        with self._connect() as db:
            summaries = list_case_summaries(db)
        return json.loads(_json(summaries))

    def get_claim_graph(self, case_id: str | None = None, claim_id: str | None = None) -> dict:
        """Read-only helper returning the longitudinal claim graph DAG."""
        payload = {}
        if case_id is not None:
            payload["case_id"] = case_id
        if claim_id is not None:
            payload["claim_id"] = claim_id
        return self.dispatch("claim_graph", payload)

    def evaluate_triggers(
        self,
        case_id: str,
        *,
        against_case_id: str | None = None,
        observations: dict | None = None,
    ) -> dict:
        """Read-only helper evaluating reversal triggers for a case."""
        payload: dict[str, Any] = {"case_id": case_id}
        if against_case_id is not None:
            payload["against_case_id"] = against_case_id
        if observations is not None:
            payload["observations"] = observations
        return self.dispatch("evaluate_triggers", payload)

    def get_calibration_report(
        self,
        *,
        case_id: str | None = None,
        domain: str | None = None,
        claim_type: str | None = None,
    ) -> dict:
        """Read-only helper computing longitudinal calibration scores and interval coverage."""
        payload: dict[str, Any] = {}
        if case_id is not None:
            payload["case_id"] = case_id
        if domain is not None:
            payload["domain"] = domain
        if claim_type is not None:
            payload["claim_type"] = claim_type
        return self.dispatch("calibration_report", payload)

    def _claim_graph(self, db: sqlite3.Connection, payload: dict) -> dict:
        fields(payload, {"case_id", "claim_id", "include_synthesis"}, set(), "claim_graph")
        cid = string(payload["case_id"], "claim_graph.case_id", maximum=200) if "case_id" in payload and payload["case_id"] is not None else None
        clmid = string(payload["claim_id"], "claim_graph.claim_id", maximum=200) if "claim_id" in payload and payload["claim_id"] is not None else None
        include_syn = payload.get("include_synthesis", False)
        if type(include_syn) is not bool:
            fail("invalid_type", "claim_graph.include_synthesis must be a boolean")
        cases = load_connected_component_cases(db, case_id=cid, claim_id=clmid)
        graph = build_claim_graph(cases, case_id=cid, claim_id=clmid)
        if include_syn:
            graph["living_synthesis"] = synthesize_claim_lineage(cases, case_id=cid, claim_id=clmid)
        return graph

    def _evaluate_triggers(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        fields(payload, {"case_id", "against_case_id", "observations"}, {"case_id"}, "evaluate_triggers")
        has_against = "against_case_id" in payload and payload["against_case_id"] is not None
        has_obs = "observations" in payload and payload["observations"] is not None
        if has_against and has_obs:
            fail("invalid_value", "evaluate_triggers accepts at most one of against_case_id or observations")
        if has_against:
            ag_cid = string(payload["against_case_id"], "evaluate_triggers.against_case_id", maximum=200)
            loaded = load_cases_for_ids(db, {ag_cid})
            if ag_cid not in loaded:
                fail("unknown_case", f"against_case_id '{ag_cid}' does not exist in this workspace")
            ag_case = loaded[ag_cid]
            ag_ev_map = {e["evidence_id"]: e for e in self._packet_evidence(db, ag_case, strict=False)}
            ag_exec = self._exec_events(db, ag_cid)
            return evaluate_case_triggers(
                case,
                against_case=ag_case,
                against_evidence_by_id=ag_ev_map,
                against_verification=ag_case.get("verification"),
                against_exec_events=ag_exec,
            )
        if has_obs:
            obs = obj(payload["observations"], "evaluate_triggers.observations")
            return evaluate_case_triggers(case, observations=obs)
        downstream = load_downstream_cases(db, case["case_id"])
        ev_map = {e["evidence_id"]: e for e in self._packet_evidence(db, case, strict=False)}
        exec_events = self._exec_events(db, case["case_id"])
        return evaluate_case_triggers(
            case,
            downstream_cases=downstream,
            verification=case.get("verification"),
            exec_events=exec_events,
            evidence_by_id=ev_map,
        )

    @staticmethod
    def _needed_calibration_evidence_ids(cases: list[dict[str, Any]]) -> set[str]:
        needed: set[str] = set()
        by_cid = {c["case_id"]: c for c in cases}
        for c in cases:
            for co in c.get("calibration_outcomes") or ():
                if not isinstance(co, dict):
                    continue
                if co.get("resolution_source") == "external_evidence" and isinstance(co.get("evidence_id"), str):
                    needed.add(co["evidence_id"])
                elif co.get("resolution_source") == "follow_up_case":
                    fu = by_cid.get(co.get("follow_up_case_id"))
                    if fu:
                        fc_id = co.get("follow_up_claim_id")
                        decs = (fu.get("adjudication") or {}).get("decisions") or ()
                        dec = next((d for d in decs if d.get("claim_id") == fc_id), None)
                        cl = next((x for x in fu.get("claims") or () if x.get("id") == fc_id), None)
                        if dec and cl:
                            needed.update(set(dec.get("evidence_ids") or ()) & set(cl.get("evidence_ids") or ()))
            if c.get("adjudication"):
                dec_map = {d.get("claim_id"): d for d in c["adjudication"].get("decisions") or ()}
                for cl in c.get("claims") or ():
                    if cl.get("prior_claim_links"):
                        dec = dec_map.get(cl.get("id"))
                        if dec:
                            needed.update(set(dec.get("evidence_ids") or ()) & set(cl.get("evidence_ids") or ()))
        return needed

    def _record_calibration_outcome(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        target_ids: set[str] = set()
        fu_cid = payload.get("follow_up_case_id")
        if isinstance(fu_cid, str) and fu_cid and fu_cid != case["case_id"]:
            target_ids.add(fu_cid)
        ev_id = payload.get("evidence_id")
        if isinstance(ev_id, str) and ev_id:
            target_ids.update(lookup_evidence_case_ids(db, ev_id))
        needed_cases = {case["case_id"]: case, **load_cases_for_ids(db, target_ids)}
        needed_eids: set[str] = set()
        if payload.get("resolution_source") == "external_evidence" and isinstance(ev_id, str) and ev_id:
            needed_eids.add(ev_id)
        elif payload.get("resolution_source") == "follow_up_case" and isinstance(fu_cid, str) and fu_cid in needed_cases:
            fu = needed_cases[fu_cid]
            fc_id = payload.get("follow_up_claim_id")
            decs = (fu.get("adjudication") or {}).get("decisions") or ()
            dec = next((d for d in decs if d.get("claim_id") == fc_id), None)
            cl = next((x for x in fu.get("claims") or () if x.get("id") == fc_id), None)
            if dec and cl:
                needed_eids.update(set(dec.get("evidence_ids") or ()) & set(cl.get("evidence_ids") or ()))
        sources = self._calibration_sources(db, list(needed_cases.values()), target_evidence_ids=needed_eids)
        record = validate_calibration_outcome(payload, case, needed_cases, sources)
        case.setdefault("calibration_outcomes", []).append(record)
        self._event(
            db,
            case["case_id"],
            "record_calibration_outcome",
            {
                "claim_id": record["claim_id"],
                "outcome": record["outcome"],
                "outcome_score": record["outcome_score"],
                "resolution_source": record["resolution_source"],
                "outcome_digest": _digest(record),
            },
        )
        return {
            "case_id": case["case_id"],
            "state": case["state"],
            "recorded_outcome": record,
            "calibration_outcome_count": len(case["calibration_outcomes"]),
        }

    def _calibration_sources(
        self,
        db: sqlite3.Connection,
        cases: list[dict],
        *,
        target_evidence_ids: set[str] | None = None,
    ) -> dict[str, dict]:
        """Read current source identity without mutating historic cases or re-hashing identical files."""
        disk_cache: dict[tuple[str, str], bool] = {}

        def disk_matches(rel_path: str, expected_sha256: str) -> bool:
            key = (rel_path, expected_sha256)
            cached = disk_cache.get(key)
            if cached is not None:
                return cached
            try:
                ok = _bytes_digest(self._read_source(self._path(rel_path))) == expected_sha256
            except ContractError:
                ok = False
            disk_cache[key] = ok
            return ok

        return check_calibration_sources(
            db,
            cases,
            disk_hash_checker=disk_matches,
            target_evidence_ids=target_evidence_ids,
        )

    def _calibration_report(self, db: sqlite3.Connection, payload: dict) -> dict:
        fields(payload, {"case_id", "domain", "claim_type"}, set(), "calibration_report")
        cid = string(payload["case_id"], "calibration_report.case_id", maximum=200) if "case_id" in payload and payload["case_id"] is not None else None
        dom = enum(payload["domain"], ("scientific", "general"), "calibration_report.domain") if "domain" in payload and payload["domain"] is not None else None
        ctype = enum(payload["claim_type"], tuple(TYPE_LEVELS), "calibration_report.claim_type") if "claim_type" in payload and payload["claim_type"] is not None else None
        cases = load_calibration_relevant_cases(db, case_id=cid, domain=dom)
        needed_eids = self._needed_calibration_evidence_ids(cases)
        return compute_calibration_report(
            cases,
            case_id=cid,
            domain=dom,
            claim_type=ctype,
            evidence_by_id=self._calibration_sources(db, cases, target_evidence_ids=needed_eids),
        )

    def get_ceilings(self, case_id: str) -> dict:
        """Return read-only critical-check ceilings and effect record counts per claim."""
        case_id = string(case_id, "case_id", maximum=200)
        with self._connect() as db:
            row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            fail("unknown_case", "case_id does not exist in this workspace")
        case = json.loads(row[0])
        gated(case)
        claims_summary = []
        check_ceilings = {}
        effect_record_counts = {}
        for claim in case.get("claims") or ():
            cid = claim["id"]
            rec_count = len(claim.get("effect_records") or ())
            effect_record_counts[cid] = rec_count
            claim_ceiling = ceiling(claim) if "claim_type" in claim else None
            if claim_ceiling is not None:
                check_ceilings[cid] = claim_ceiling
            claims_summary.append({
                "claim_id": cid,
                "claim_type": claim.get("claim_type"),
                "evidence_level": claim.get("evidence_level"),
                "ceiling": claim_ceiling,
                "effect_record_count": rec_count,
            })
        return json.loads(_json({
            "case_id": case_id,
            "state": case["state"],
            "schema_version": case.get("schema_version", 1),
            "gate_version": case.get("gate_version"),
            "claims": claims_summary,
            "check_ceilings": check_ceilings,
            "effect_record_counts": effect_record_counts,
        }))

    def get_packet(self, case_id: str, role: str, *, stage: str = "full") -> dict:
        """Read-only lookup of a built review or adjudication packet."""
        case_id = string(case_id, "case_id", maximum=200)
        role = enum(role, (*ROLES, "adjudication"), "role")
        stage = enum(stage, PACKET_STAGES, "stage")
        if role == "adjudication" and stage != "full":
            fail("invalid_value", "adjudication packets only support stage='full'")
        with self._connect() as db:
            row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                fail("unknown_case", "case_id does not exist in this workspace")
            case = json.loads(row[0])
            gated(case)
            if case["state"] != "draft":
                self._validate_frozen(case)
            if role in ROLES:
                packets = case.get("packets") or {}
                if case["state"] == "draft" or role not in packets:
                    fail("missing_packet", f"review packet '{role}' has not been built; freeze the case first")
                packet = self._assemble_review_packet(db, case, role, bool(case.get("blind", False)), stage=stage)
            else:
                if not case.get("adjudication_packet"):
                    fail("missing_packet", "adjudication_packet has not been built yet")
                digest = _digest({"input_digest": case["input_digest"], "reviews": case["reviews"]})
                if case["adjudication_packet"]["input_digest"] != digest:
                    fail("review_integrity_error", "adjudication no longer matches the registered reviews")
                packet = self._assemble_adjudication_packet(db, case)
        return json.loads(_json(packet))

    @staticmethod
    def _state(case: dict, allowed: tuple[str, ...]) -> None:
        if case["state"] not in allowed:
            fail("invalid_state", f"requires {', '.join(allowed)}; current state is {case['state']}")

    @staticmethod
    def _human_holds(case: dict) -> set[str]:
        """Accumulate holds until explicit acceptance; comments cannot implicitly resume."""
        active = set()
        for event in reversed(case["human_decisions"]):
            if event["decision"] == "accept":
                break
            active.add(event["decision"])
        return active

    @staticmethod
    def _event(db: sqlite3.Connection, case_id: str, action: str, details: dict) -> None:
        append_event(db, case_id, action, details)

    @staticmethod
    def verify_event_chain(db: sqlite3.Connection, case_id: str | None = None) -> dict:
        """Verify contiguity and SHA-256 chain links across the events log."""
        return _verify_event_chain(db, case_id)

    def _create_case(self, db: sqlite3.Connection, payload: dict) -> dict:
        fields(
            payload,
            {
                "question", "draft", "domain", "writer_context_id", "schema_version",
                "blind", "blind_mode", "symmetry_mode",
                "prior_case_ids", "supersedes_case_id", "case_relation",
            },
            {"question", "draft"},
            "create_case",
        )
        version = payload.get("schema_version", 2)
        if type(version) is not int or version not in (1, 2):
            fail("invalid_value", "schema_version must be 2 for new cases")
        if version == 1:
            fail("legacy_creation_disabled", "new cases require schema_version=2; existing legacy records remain recoverable without rewriting their digests")
        case = {
            "case_id": _id("case"), "schema_version": version, "state": "draft", "created_at": _now(),
            "question": string(payload["question"], "question"),
            "draft": string(payload["draft"], "draft", maximum=1_000_000),
            "domain": enum(payload.get("domain", "scientific"), ("scientific", "general"), "domain"),
            "writer_context_id": string(payload.get("writer_context_id"), "writer_context_id", optional=True, maximum=200),
            "evidence": [], "hypotheses": [], "claims": [], "reviews": {}, "human_decisions": [],
            "scientific_validity": "not_established_by_engine",
        }
        if version == 2:
            blind = payload.get("blind", True)
            if type(blind) is not bool:
                fail("invalid_type", "blind must be a boolean")
            case.update(gate_version=GATE_VERSION, blind=blind)
            if "blind_mode" in payload and payload["blind_mode"] is not None:
                blind_mode = enum(payload["blind_mode"], BLIND_MODES, "blind_mode")
                if blind_mode == "estimate_first" and not blind:
                    fail("invalid_value", "blind_mode='estimate_first' requires blind=true")
                case["blind_mode"] = blind_mode
            if "symmetry_mode" in payload and payload["symmetry_mode"] is not None:
                case["symmetry_mode"] = enum(payload["symmetry_mode"], SYMMETRY_MODES, "symmetry_mode")
            if "prior_case_ids" in payload and payload["prior_case_ids"] is not None:
                prior_ids = ids(payload["prior_case_ids"], "prior_case_ids", minimum=0, maximum=MAX_PRIOR_CASES)
                for pid in prior_ids:
                    if not db.execute("SELECT 1 FROM cases WHERE id=?", (pid,)).fetchone():
                        fail("unknown_case", f"prior_case_id '{pid}' does not exist in this workspace")
                case["prior_case_ids"] = list(prior_ids)
            if "supersedes_case_id" in payload and payload["supersedes_case_id"] is not None:
                sup_id = string(payload["supersedes_case_id"], "supersedes_case_id", maximum=200)
                if not db.execute("SELECT 1 FROM cases WHERE id=?", (sup_id,)).fetchone():
                    fail("unknown_case", f"supersedes_case_id '{sup_id}' does not exist in this workspace")
                case["supersedes_case_id"] = sup_id
            if "case_relation" in payload and payload["case_relation"] is not None:
                case["case_relation"] = enum(payload["case_relation"], CASE_RELATIONS, "case_relation")
        elif "blind" in payload:
            fail("unknown_field", "case-level blind is available only for new v2 cases")
        db.execute("INSERT INTO cases(id,document) VALUES(?,?)", (case["case_id"], _json(case)))
        sync_case_indexes(db, case)
        self._event(db, case["case_id"], "create_case", {"domain": case["domain"], "symmetry_mode": case.get("symmetry_mode"), "blind_mode": case.get("blind_mode")})
        result = {key: case[key] for key in ("case_id", "state", "created_at", "schema_version")}
        if gated(case):
            result.update(
                gate_version=case["gate_version"],
                blind=case["blind"],
                blind_mode=case.get("blind_mode", "standard"),
                symmetry_mode=case.get("symmetry_mode", "enforced"),
            )
        for opt_key in ("prior_case_ids", "supersedes_case_id", "case_relation"):
            if opt_key in case:
                result[opt_key] = case[opt_key]
        return result

    def _scaffold_claim(self, db: sqlite3.Connection, payload: dict) -> dict:
        template_payload = dict(payload)
        prefill = template_payload.pop("prefill", None)
        if "prefill" in payload and not isinstance(prefill, dict):
            fail("invalid_type", "prefill must be an object")
        case_id = template_payload.get("case_id")
        if prefill is not None and case_id is None:
            fail("missing_field", "prefill requires case_id")
        if case_id is not None:
            case_id = string(case_id, "case_id", maximum=200)
            row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                fail("unknown_case", "case_id does not exist in this workspace")
            case = json.loads(row[0])
            gated(case)
            template_payload.setdefault("domain", case["domain"])
            if template_payload["domain"] != case["domain"]:
                fail("invalid_value", "domain differs from target case")
        claim = scaffold_claim_template(template_payload)
        if prefill is not None:
            from .prefill import prefill_claim
            if case["state"] != "draft":
                self._validate_frozen(case)
            claim, report = prefill_claim(claim, prefill, case, lambda p: self._extract_effects(db, case, p))
        result = {"claim": claim, "check_ceilings": ceiling(claim)}
        if case_id is not None:
            result["case_id"] = case_id
        if prefill is not None:
            result["prefill_report"] = report
            result["ledger_payload"] = {"case_id": case_id, "claims": [claim]}
        return result

    def _register_evidence(
        self, db: sqlite3.Connection, case: dict, payload: dict, *, captured_content: bytes | None = None,
    ) -> dict:
        self._state(case, ("draft",))
        allowed = {"case_id", "path", "label", "provenance", "quote", "location"}
        required = {"case_id", "path", "provenance"}
        if gated(case):
            allowed |= {"kind", "unread_content_ack", "excerpt_anchors", "derived_from_evidence_ids", "derivation_step"}
            required.add("kind")
        fields(payload, allowed, required, "register_evidence")
        path = self._path(payload["path"])
        content = self._read_source(path) if captured_content is None else captured_content
        evidence = {
            "evidence_id": _id("ev"), "path": path.relative_to(self.workspace).as_posix(),
            "label": string(payload.get("label", path.name), "label"),
            "provenance": enum(payload["provenance"], PROVENANCE, "provenance"),
            "provenance_basis": "registrant_report_not_execution_attestation",
            "quote": string(payload.get("quote"), "quote", optional=True),
            "location": string(payload.get("location"), "location", optional=True),
            "sha256": _bytes_digest(content), "size": len(content), "captured_at": _now(),
        }
        if gated(case):
            evidence["kind"] = enum(payload["kind"], EVIDENCE_KINDS, "evidence.kind")
            # A second registration must not launder an imported artifact's restriction.
            from .artifacts import inspect_artifact, recognizable_artifact, restrict_kind
            detected_format = recognizable_artifact(content, evidence["path"])
            if detected_format:
                try:
                    artifact = inspect_artifact(content, evidence["path"], detected_format)
                except ContractError as exc:
                    artifact = {"format": detected_format, "kind": "unknown", "inferred_kind": "unknown", "parse_error": exc.code}
                evidence["kind"] = restrict_kind(artifact["kind"], evidence["kind"])
                evidence["kind_inference"] = {"inferred_kind": artifact["inferred_kind"], "basis": "recognized_artifact_structure", "format": detected_format}
                evidence["artifact"] = artifact
            for restricted_kind, kind_inference_json, artifact_json in db.execute(
                "SELECT restricted_kind, kind_inference, artifact_json FROM evidence_kind_restrictions WHERE sha256=? ORDER BY rowid ASC",
                (evidence["sha256"],),
            ):
                evidence["kind"] = restrict_kind(restricted_kind, evidence["kind"])
                evidence["kind_inference"] = json.loads(kind_inference_json)
                if artifact_json is not None:
                    evidence["artifact"] = json.loads(artifact_json)
            # Ordinary documentary evidence remains explicitly reported for backwards compatibility.
            # Recognizable execution logs cannot be promoted by passing a stronger --kind later.
            if re.match(rb"command: [^\n]+\nstarted_at: [^\n]+\nended_at: [^\n]+\nexit_status: [^\n]+\ntermination_status: ", content):
                evidence["kind"] = restrict_kind("unknown", evidence["kind"])
                evidence["kind_inference"] = {"inferred_kind": "unknown", "basis": "execution_log_not_study_design"}
            if evidence["kind"] == "synthetic" and evidence["provenance"] != "synthetic":
                fail("conflicting_provenance", "synthetic kind requires synthetic provenance")
            source = text_content(content)
            ack = payload.get("unread_content_ack", False)
            if type(ack) is not bool:
                fail("invalid_type", "unread_content_ack must be a boolean")
            if source is None and ack is not True:
                fail("unread_ack_required", "binary contents are not read by this engine; explicitly acknowledge with unread_content_ack=true")
            evidence.update(content_read_status="text" if source is not None else "binary_unread", unread_content_ack=ack)
            if evidence["quote"] is not None:
                anchor = quote_status(evidence["quote"], source)
                if anchor != "matched":
                    fail("invalid_quote", f"quote must be uniquely anchored and at least 12 non-whitespace characters: {anchor}")
            if "excerpt_anchors" in payload:
                raw_anchors = array(payload["excerpt_anchors"], "excerpt_anchors", minimum=1, maximum=8)
                anchors = []
                seen_anchors = set()
                for idx, raw_anchor in enumerate(raw_anchors):
                    anchor_val = string(raw_anchor, f"excerpt_anchors[{idx}]")
                    clean_anchor = strip_terminal_escapes(anchor_val)
                    if clean_anchor in seen_anchors:
                        fail("invalid_quote", "excerpt_anchors entries must be distinct")
                    seen_anchors.add(clean_anchor)
                    anchor_state = quote_status(anchor_val, source)
                    if anchor_state != "matched":
                        fail("invalid_quote", f"excerpt_anchors[{idx}] must be uniquely anchored and at least 12 non-whitespace characters: {anchor_state}")
                    anchors.append(anchor_val)
                evidence["excerpt_anchors"] = anchors
            has_parents = "derived_from_evidence_ids" in payload
            parents = ids(payload["derived_from_evidence_ids"], "derived_from_evidence_ids", minimum=0) if has_parents else []
            if parents:
                known_evidence = {item["evidence_id"] for item in case["evidence"]}
                for parent_id in parents:
                    if parent_id not in known_evidence:
                        fail("unknown_reference", f"derived_from_evidence_ids references unknown evidence '{parent_id}'")
                if "derivation_step" not in payload or payload["derivation_step"] is None:
                    fail("missing_field", "derived_from_evidence_ids requires a non-empty derivation_step")
                step = string(payload["derivation_step"], "derivation_step", maximum=2000)
                if not meaningful(step):
                    fail("invalid_value", "derivation_step cannot be empty, invisible or a placeholder")
                evidence["derived_from_evidence_ids"] = parents
                evidence["derivation_step"] = step
            else:
                if "derivation_step" in payload:
                    if payload["derivation_step"] is None:
                        fail("invalid_type", "derivation_step must be a string")
                    string(payload["derivation_step"], "derivation_step", maximum=2000)
                    fail("missing_field", "derivation_step requires at least one parent in derived_from_evidence_ids")
                if has_parents:
                    evidence["derived_from_evidence_ids"] = []
        case["evidence"].append(evidence)
        db.execute("INSERT INTO evidence_snapshots(case_id,evidence_id,content) VALUES(?,?,?)", (case["case_id"], evidence["evidence_id"], content))
        self._record_kind_restriction(db, case["case_id"], evidence)
        self._event(db, case["case_id"], "register_evidence", {"evidence_id": evidence["evidence_id"], "sha256": evidence["sha256"]})
        return evidence

    def _draft_manuscript(self, db: sqlite3.Connection, payload: dict) -> dict:
        from .manuscript import draft_manuscript
        fields(payload, {"path", "case_id", "domain", "max_claims", "selections", "claim_bindings", "expected_source_sha256", "pdf_backend"}, {"path"}, "draft_manuscript")
        if "claim_bindings" in payload and "case_id" not in payload:
            fail("missing_field", "claim_bindings requires case_id")
        if "claim_bindings" in payload and "expected_source_sha256" not in payload:
            fail("missing_field", "claim_bindings requires expected_source_sha256 from the manuscript draft")
        domain = enum(payload.get("domain", "scientific"), DOMAINS, "domain")
        if "case_id" in payload:
            case_id = string(payload["case_id"], "case_id", maximum=200)
            row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                fail("unknown_case", "case_id does not exist in this workspace")
            case = json.loads(row[0])
            gated(case)
            domain = case["domain"]
            if "domain" in payload and payload["domain"] != domain:
                fail("invalid_value", "domain differs from target case")
        path = self._path(payload["path"])
        result = draft_manuscript(
            self._read_source(path),
            path.relative_to(self.workspace).as_posix(),
            payload,
            domain,
            include_resolver=self._tex_include_resolver,
        )
        if "expected_source_sha256" in payload:
            digest = string(payload["expected_source_sha256"], "expected_source_sha256", maximum=64)
            if digest != result["source"]["sha256"]:
                fail("source_changed", "Manuscript changed; draft and bind claims again")
        if "claim_bindings" in payload:
            from .prefill import prefill_claim
            if case["state"] != "draft":
                self._validate_frozen(case)
            bindings = array(payload["claim_bindings"], "claim_bindings", minimum=1, maximum=20)
            by_id = {claim["id"]: index for index, claim in enumerate(result["claims"])}
            seen = set()
            result["prefill_reports"] = []
            for binding in bindings:
                obj(binding, "claim_binding")
                fields(binding, {"claim_id", "quote", "location", "prefill"}, {"claim_id", "quote", "location", "prefill"}, "claim_binding")
                claim_id = string(binding["claim_id"], "claim_binding.claim_id", maximum=200)
                if claim_id not in by_id:
                    fail("unknown_claim", "claim_binding does not identify a selected manuscript claim")
                if claim_id in seen:
                    fail("duplicate_id", "Only one prefill binding per claim")
                seen.add(claim_id)
                index = by_id[claim_id]
                anchor = result["source_map"][index]
                if binding["quote"] != anchor["quote"] or binding["location"] != anchor["location"]:
                    fail("source_changed", "Claim selection changed; use quote/location from the current draft source_map")
                claim, report = prefill_claim(result["claims"][index], binding["prefill"], case,
                                              lambda p: self._extract_effects(db, case, p))
                result["claims"][index] = claim
                result["prefill_reports"].append(report)
        if "case_id" in payload:
            result["ledger_payload"] = {"case_id": payload["case_id"], "claims": result["claims"]}
        result["check_ceilings"] = {c["id"]: ceiling(c) for c in result["claims"]}
        return result

    def _import_artifact(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        from .artifacts import inspect_artifact, restrict_kind
        self._state(case, ("draft",))
        fields(payload, {"case_id", "path", "artifact_format", "kind", "label", "execution_evidence_id", "derived_from_evidence_ids", "derivation_step"},
               {"case_id", "path"}, "import_artifact")
        path = self._path(payload["path"])
        content = self._read_source(path)
        summary = inspect_artifact(
            content,
            path.relative_to(self.workspace).as_posix(),
            payload.get("artifact_format", "auto"),
            payload.get("kind"),
            dvc_path_resolver=self._dvc_digest_resolver,
        )
        parents = ids(payload.get("derived_from_evidence_ids", []), "derived_from_evidence_ids")
        known = {e["evidence_id"]: e for e in case["evidence"]}
        self._refs(parents, set(known), "derived_from_evidence_ids")
        for parent_id in parents:
            lineage = evidence_lineage(parent_id, known)
            if lineage["cycle_detected"] or lineage["unknown_parents"]:
                fail("invalid_lineage", "Artifact parent lineage is incomplete or cyclic")
            ancestors = [known[eid] for eid in [parent_id, *lineage["ancestors"]]]
            if any(parent.get("kind") == "synthetic" or parent.get("provenance") == "synthetic" for parent in ancestors):
                summary["kind"] = restrict_kind("synthetic", payload.get("kind"))
        execution_id = payload.get("execution_evidence_id")
        binding = None
        if execution_id is not None:
            string(execution_id, "execution_evidence_id", maximum=200)
            if self.verify_event_chain(db, case["case_id"])["status"] == "tampered":
                fail("event_chain_tampered", "Cannot bind artifact to a tampered event history")
            events = [e for e in self._exec_events(db, case["case_id"]) if e.get("evidence_id") == execution_id]
            if len(events) != 1 or execution_id not in known:
                fail("unbound_execution", "execution_evidence_id must identify one recorded execution in this case")
            event = events[0]
            if event.get("status") != "checked" or event.get("exit_status") != 0 or event.get("termination_status", "completed") != "completed":
                fail("unbound_execution", "Failed, pending or timed-out execution cannot attest successful artifact production")
            outputs = event.get("provenance", {}).get("outputs", [])
            matches = [o for o in outputs if o.get("path") == summary["path"] and o.get("sha256") == summary["sha256"] and o.get("status") in ("created", "modified")]
            if len(matches) != 1:
                fail("unbound_execution", "Artifact must match a created/modified declared output; existence or unchanged hash is insufficient")
            log = known[execution_id]
            log_snapshot = db.execute("SELECT content FROM evidence_snapshots WHERE case_id=? AND evidence_id=?", (case["case_id"], execution_id)).fetchone()
            if log_snapshot is None or _bytes_digest(log_snapshot[0]) != log["sha256"]:
                fail("unbound_execution", "Recorded execution log snapshot is missing or changed")
            binding = {"evidence_id": execution_id, "output_sha256": summary["sha256"], "output_status": matches[0]["status"]}
            if log.get("provenance") == "synthetic" or log.get("kind") == "synthetic":
                summary["kind"] = restrict_kind("synthetic", payload.get("kind"))
            if execution_id not in parents:
                parents.append(execution_id)
        reg = {"case_id": case["case_id"], "path": summary["path"], "kind": summary["kind"],
               "provenance": "synthetic" if summary["kind"] == "synthetic" else "observed" if binding else "reported",
               "label": payload.get("label", f"Imported {summary['format']} artifact")}
        readable = text_content(content)
        if readable is not None:
            excerpt = readable[:2000].strip()
            if quote_status(excerpt, readable) == "matched":
                reg.update(quote=excerpt, location=f"{summary['path']}:L1-L{readable[:2000].count(chr(10)) + 1}")
        else:
            # Binary artifacts (e.g., xlsx/parquet) were structurally inspected above; preserve unread_binary status while allowing import.
            reg["unread_content_ack"] = True
        if parents:
            reg.update(derived_from_evidence_ids=parents,
                       derivation_step=payload.get("derivation_step", "Artifact output bound to the recorded execution and declared source snapshots"))
        evidence = self._register_evidence(db, case, reg)
        # Snapshot exactly the bytes inspected above, even if a source changes during import.
        if evidence["sha256"] != summary["sha256"]:
            fail("source_changed", "Source changed while being imported; transaction rolled back")
        evidence["kind_inference"] = {"inferred_kind": summary["inferred_kind"], "basis": summary["kind_basis"], "format": summary["format"]}
        evidence["artifact"] = summary
        self._record_kind_restriction(db, case["case_id"], evidence)
        evidence["execution_binding"] = binding
        evidence["provenance_basis"] = "record_exec_changed_output_binding" if binding else "imported_artifact_not_execution_attestation"
        self._event(db, case["case_id"], "import_artifact", {"evidence_id": evidence["evidence_id"], "sha256": evidence["sha256"], "format": summary["format"], "execution_binding": binding})
        return {"evidence": evidence, "artifact": summary, "execution_binding": binding}

    def _extract_effects(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        from .manuscript import read_manuscript
        from .stat_import import compare_manuscript, parse_statistics
        fields(
            payload,
            {"case_id", "evidence_id", "format", "column_map", "manuscript_path", "sheet_name", "assumed_reported_scale"},
            {"case_id", "evidence_id"},
            "extract_effects",
        )
        evidence_id = string(payload["evidence_id"], "evidence_id", maximum=200)
        sheet_name = string(payload["sheet_name"], "sheet_name", maximum=200) if "sheet_name" in payload else None
        assumed_reported_scale = enum(
            payload.get("assumed_reported_scale", "auto"),
            ("auto", "unit", "percentage"),
            "assumed_reported_scale",
        )
        evidence = next((e for e in case["evidence"] if e["evidence_id"] == evidence_id), None)
        if evidence is None:
            fail("unknown_evidence", "evidence_id is not registered in this case")
        row = db.execute("SELECT content FROM evidence_snapshots WHERE case_id=? AND evidence_id=?", (case["case_id"], evidence_id)).fetchone()
        if row is None or _bytes_digest(row[0]) != evidence["sha256"]:
            fail("source_changed", "Evidence snapshot is missing or corrupt")
        result = parse_statistics(
            row[0],
            evidence["path"],
            evidence_id,
            payload.get("format", "auto"),
            payload.get("column_map"),
            sheet_name=sheet_name,
        )
        result["execution_binding"] = evidence.get("execution_binding")
        result["source_state"] = "registered_snapshot"
        if "manuscript_path" in payload:
            path = self._path(payload["manuscript_path"])
            document = read_manuscript(
                self._read_source(path),
                path.relative_to(self.workspace).as_posix(),
                include_resolver=self._tex_include_resolver,
            )
            result["manuscript_comparison"] = compare_manuscript(
                result["effect_records"],
                document,
                assumed_reported_scale=assumed_reported_scale,
            )
            result["manuscript_source"] = {k: v for k, v in document.items() if k != "units"}
        return result

    @staticmethod
    def _exec_events(db: sqlite3.Connection, case_id: str) -> list[dict]:
        rows = db.execute(
            "SELECT details FROM events WHERE case_id=? AND action='record_exec' ORDER BY sequence",
            (case_id,),
        ).fetchall()
        events = []
        for row in rows:
            try:
                item = json.loads(row[0])
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                events.append(item)
        return events

    @staticmethod
    def _isolation_attestation(value: Any, label: str = "isolation_attestation") -> dict:
        att = obj(value, label)
        allowed = {"history_inheritance", "memory_access", "host_surface"}
        fields(att, allowed, set(), label)
        return {
            key: string(att[key], f"{label}.{key}", maximum=200)
            for key in ("history_inheritance", "memory_access", "host_surface")
            if key in att
        }

    def record_execution_event(self, case_id: str, details: dict) -> dict:
        case_id = string(case_id, "case_id", maximum=200)
        obj(details, "record_exec.details")
        claim_id = string(details["claim_id"], "record_exec.details.claim_id", maximum=200) if "claim_id" in details and details["claim_id"] is not None else None
        run_group = string(details["run_group"], "record_exec.details.run_group", maximum=200) if "run_group" in details and details["run_group"] is not None else None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                fail("unknown_case", "case_id does not exist in this workspace")
            existing = self._exec_events(db, case_id)
            case_exec_count = len(existing) + 1
            if claim_id is not None:
                scoped_count = sum(1 for ev in existing if ev.get("claim_id") == claim_id) + 1
            elif run_group is not None:
                scoped_count = sum(1 for ev in existing if ev.get("run_group") == run_group) + 1
            else:
                scoped_count = sum(1 for ev in existing if not ev.get("claim_id") and not ev.get("run_group")) + 1
            fork_index = scoped_count
            event_details = {**details, "fork_index": fork_index, "scoped_exec_count": scoped_count, "case_exec_count": case_exec_count}
            if claim_id is not None:
                event_details["claim_id"] = claim_id
            if run_group is not None:
                event_details["run_group"] = run_group
            self._event(db, case_id, "record_exec", event_details)
            result = {
                "fork_index": fork_index,
                "scoped_exec_count": scoped_count,
                "case_exec_count": case_exec_count,
                "multiplicity_required": fork_index > 1,
            }
            if claim_id is not None:
                result["claim_id"] = claim_id
            if run_group is not None:
                result["run_group"] = run_group
            return result

    def _register_hypothesis(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("draft",))
        fields(payload, {"case_id", "statement", "timing_basis", "source_evidence_id"}, {"case_id", "statement", "timing_basis"}, "register_hypothesis")
        timing = enum(payload["timing_basis"], ("reported_prespecified", "exploratory", "unknown"), "timing_basis")
        source = string(payload.get("source_evidence_id"), "source_evidence_id", optional=True, maximum=200)
        if timing == "reported_prespecified" and not source:
            fail("missing_timing_source", "reported prespecification requires its documentary source")
        if source and source not in {item["evidence_id"] for item in case["evidence"]}:
            fail("unknown_evidence", "hypothesis source_evidence_id is not registered")
        hypothesis = {
            "hypothesis_id": _id("hyp"), "statement": string(payload["statement"], "statement"),
            "timing_basis": timing, "source_evidence_id": source, "recorded_at": _now(),
            "timing_verification": "self_report_not_historical_proof",
        }
        case["hypotheses"].append(hypothesis)
        self._event(db, case["case_id"], "register_hypothesis", {"hypothesis_id": hypothesis["hypothesis_id"]})
        return hypothesis

    @staticmethod
    def _refs(references: list[str], known: set[str], label: str) -> None:
        missing = set(references) - known
        if missing:
            fail("unknown_reference", f"{label} contains unknown IDs: {', '.join(sorted(missing))}")

    def _claim(self, claim: Any, evidence_ids: set[str], hypotheses: dict, domain: str = "scientific", version: int = 1, gate: bool = False) -> dict:
        claim = obj(claim, "claim")
        allowed_levels = SCIENTIFIC_LEVELS if domain == "scientific" else GENERAL_LEVELS
        base_required = {"id", "text", "level", "evidence_ids", "effect", "scope", "origin", "contribution"}
        optional = {"hypothesis_id", "best_current_explanation", "discriminating_test"}
        if version == 2:
            base_required = (base_required - {"level"}) | {"claim_type", "evidence_level", "design_packages", "statistical_report", "provenance_cards"}
            optional.update(("causal_basis", "effect_records", "prior_claim_links", "reversal_triggers"))
        if gate:
            base_required.add("claim_basis")
        if domain == "scientific":
            required = base_required | {"alternatives", "checks"}
            allowed = required | optional
        else:
            required = base_required
            allowed = base_required | {"alternatives", "checks"} | optional
            if version == 2:
                required = required | {"checks"}
        fields(claim, allowed, required, "claim")
        string(claim["id"], "claim.id", maximum=200)
        string(claim["text"], "claim.text")
        if version == 1:
            enum(claim["level"], allowed_levels, "claim.level")
        refs = ids(claim["evidence_ids"], "claim.evidence_ids")
        self._refs(refs, evidence_ids, "claim.evidence_ids")
        if version == 2:
            validate_content(claim, domain, set(refs))
        if gate:
            validate_basis(claim)
        effect = obj(claim["effect"], "claim.effect")
        fields(effect, {"estimate", "uncertainty"}, {"estimate", "uncertainty"}, "claim.effect")
        string(effect["estimate"], "claim.effect.estimate")
        string(effect["uncertainty"], "claim.effect.uncertainty")
        string(claim["scope"], "claim.scope")
        string(claim["contribution"], "claim.contribution")
        enum(claim["origin"], ORIGINS, "claim.origin")
        hypothesis_id = string(claim.get("hypothesis_id"), "claim.hypothesis_id", optional=True, maximum=200)
        if hypothesis_id and hypothesis_id not in hypotheses:
            fail("unknown_hypothesis", "claim hypothesis is not registered")
        if claim["origin"] == "prespecified":
            if not hypothesis_id or hypotheses[hypothesis_id]["timing_basis"] != "reported_prespecified":
                fail("missing_timing_source", "prespecified claims require a documented reported-prespecified hypothesis")
        if claim["origin"] == "exploratory" and hypothesis_id and hypotheses[hypothesis_id]["timing_basis"] == "reported_prespecified":
            fail("conflicting_origin", "exploratory claim cannot reuse a prespecified hypothesis entry")
        if "best_current_explanation" in claim:
            string(claim["best_current_explanation"], "claim.best_current_explanation", optional=True)
        if "discriminating_test" in claim:
            string(claim["discriminating_test"], "claim.discriminating_test", optional=True)
            if gate and claim["discriminating_test"] is not None and not is_placeholder(claim["discriminating_test"]):
                if is_vacuous_rationale(claim["discriminating_test"]) or BOILERPLATE_OVERHEDGING_RE.search(claim["discriminating_test"]):
                    fail("invalid_reversal_condition", "claim.discriminating_test must state a concrete falsifiable test, not a trivial label or generic future-study deferral")

        if domain == "scientific":
            alternatives = array(claim["alternatives"], "claim.alternatives", minimum=1, maximum=3)
        else:
            raw_alts = claim.get("alternatives", [])
            if raw_alts is None:
                raw_alts = []
            alternatives = array(raw_alts, "claim.alternatives", minimum=0, maximum=3)
        for alternative in alternatives:
            obj(alternative, "alternative")
            fields(alternative, {"explanation", "status", "reason"}, {"explanation", "status", "reason"}, "alternative")
            string(alternative["explanation"], "alternative.explanation")
            enum(alternative["status"], ALTERNATIVE_STATUSES, "alternative.status")
            string(alternative["reason"], "alternative.reason")
        claim["alternatives"] = alternatives

        if domain == "scientific":
            checks = obj(claim["checks"], "claim.checks")
            fields(checks, set(CHECK_NAMES), set(CHECK_NAMES), "claim.checks")
            for name in CHECK_NAMES:
                check = obj(checks[name], f"checks.{name}")
                fields(check, {"status", "reason"}, {"status", "reason"}, f"checks.{name}")
                enum(check["status"], CHECK_STATUSES, f"checks.{name}.status")
                string(check["reason"], f"checks.{name}.reason")
        else:
            raw_checks = claim.get("checks")
            checks = {} if raw_checks is None else obj(raw_checks, "claim.checks")
            if version == 2:
                fields(checks, set(CHECK_NAMES), set(CHECK_NAMES), "claim.checks")
            defaulted_checks = {}
            for name in CHECK_NAMES:
                if name in checks:
                    check = obj(checks[name], f"checks.{name}")
                    fields(check, {"status", "reason"}, {"status", "reason"}, f"checks.{name}")
                    enum(check["status"], CHECK_STATUSES, f"checks.{name}.status")
                    string(check["reason"], f"checks.{name}.reason")
                    defaulted_checks[name] = check
                else:
                    defaulted_checks[name] = {"status": "not_applicable", "reason": "not applicable to general engineering claim"}
            claim["checks"] = defaulted_checks
        return claim

    @staticmethod
    def _load_cases_by_id(db: sqlite3.Connection) -> dict[str, dict]:
        return load_all_cases_by_id(db)

    def _set_ledger(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("draft",))
        fields(payload, {"case_id", "claims"}, {"case_id", "claims"}, "set_ledger")
        evidence_ids = {item["evidence_id"] for item in case["evidence"]}
        hypotheses = {item["hypothesis_id"]: item for item in case["hypotheses"]}
        domain = case.get("domain", "scientific")
        claims = [self._claim(claim, evidence_ids, hypotheses, domain, case.get("schema_version", 1), gated(case)) for claim in array(payload["claims"], "claims", minimum=1, maximum=100)]
        ids([claim["id"] for claim in claims], "claim IDs")
        if any("prior_claim_links" in claim for claim in claims):
            linked_prior_ids = list(case.get("prior_case_ids") or ())
            if case.get("supersedes_case_id") and case["supersedes_case_id"] not in linked_prior_ids:
                linked_prior_ids.append(case["supersedes_case_id"])
            ref_ids = set(linked_prior_ids)
            for claim in claims:
                for lnk in claim.get("prior_claim_links") or ():
                    if isinstance(lnk, dict) and isinstance(lnk.get("prior_case_id"), str):
                        ref_ids.add(lnk["prior_case_id"])
            cases_by_id = {case["case_id"]: case, **load_cases_for_ids(db, ref_ids)}
            for claim in claims:
                if "prior_claim_links" in claim:
                    validate_prior_claim_links_references(
                        claim["prior_claim_links"],
                        case["case_id"],
                        cases_by_id,
                        prior_case_ids=linked_prior_ids,
                    )
        case["claims"] = claims
        self._event(db, case["case_id"], "set_ledger", {"claim_count": len(claims), "ledger_digest": _digest(claims)})
        return {"case_id": case["case_id"], "state": case["state"], "claim_count": len(claims)}

    def _upsert_claim(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("draft",))
        compiled, meta = compile_compact_claim(
            payload,
            case,
            extract_fn=lambda p: self._extract_effects(db, case, p),
        )
        evidence_ids = {item["evidence_id"] for item in case["evidence"]}
        hypotheses = {item["hypothesis_id"]: item for item in case["hypotheses"]}
        domain = case.get("domain", "scientific")
        validated = self._claim(compiled, evidence_ids, hypotheses, domain, case.get("schema_version", 1), gated(case))
        if "prior_claim_links" in validated:
            linked_prior_ids = list(case.get("prior_case_ids") or ())
            if case.get("supersedes_case_id") and case["supersedes_case_id"] not in linked_prior_ids:
                linked_prior_ids.append(case["supersedes_case_id"])
            ref_ids = set(linked_prior_ids)
            for lnk in validated.get("prior_claim_links") or ():
                if isinstance(lnk, dict) and isinstance(lnk.get("prior_case_id"), str):
                    ref_ids.add(lnk["prior_case_id"])
            cases_by_id = {case["case_id"]: case, **load_cases_for_ids(db, ref_ids)}
            validate_prior_claim_links_references(
                validated["prior_claim_links"],
                case["case_id"],
                cases_by_id,
                prior_case_ids=linked_prior_ids,
            )
        existing = list(case.get("claims") or ())
        replaced = False
        for idx, prev in enumerate(existing):
            if prev["id"] == validated["id"]:
                existing[idx] = validated
                replaced = True
                break
        if not replaced:
            if len(existing) >= 100:
                fail("too_large", "At most 100 claims per case")
            existing.append(validated)
        case["claims"] = existing
        self._event(db, case["case_id"], "upsert_claim", {"claim_id": validated["id"], "replaced": replaced, "claim_count": len(existing)})
        exec_events = _load_case_exec_events(db, case["case_id"])
        result = {
            "case_id": case["case_id"],
            "state": case["state"],
            "claim_id": validated["id"],
            "replaced": replaced,
            "claim_count": len(existing),
            "claim": validated,
            "ceiling_diff": compute_ceiling_diff(validated, validated["evidence_level"]),
            "copilot_diagnostics": analyze_claim_copilot(
                validated,
                exec_events=exec_events,
                include_ceiling_diff=False,
            ),
        }
        if meta.get("prefill_report") is not None:
            result["prefill_report"] = meta["prefill_report"]
        return result

    def _promote_exploration_to_case(
        self, db: sqlite3.Connection, explore_doc: dict, req: dict, *, dry_run: bool,
    ) -> dict:
        hid = req["hypothesis_id"]
        target = next(h for h in explore_doc["hypotheses"] if h["hypothesis_id"] == hid)
        plans = explore_doc.get("locked_plans") or []
        plan = None
        if "plan_id" in req and req["plan_id"] is not None:
            plan = next((p for p in plans if p["plan_id"] == req["plan_id"]), None)
            if plan is None or plan["hypothesis_id"] != hid:
                fail("unknown_reference", f"plan_id '{req['plan_id']}' is not locked for hypothesis '{hid}'")
        else:
            matching_plans = [p for p in plans if p["hypothesis_id"] == hid]
            if matching_plans:
                plan = matching_plans[-1]

        create_req: dict[str, Any] = {
            "question": explore_doc["question"],
            "draft": req.get("draft") or target["statement"],
            "domain": explore_doc["domain"],
            "symmetry_mode": req.get("symmetry_mode", "enforced"),
            "blind_mode": req.get("blind_mode", "estimate_first"),
        }
        if req.get("writer_context_id"):
            create_req["writer_context_id"] = req["writer_context_id"]
        created = self._create_case(db, create_req)
        case_id = created["case_id"]
        row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
        case = json.loads(row[0])

        plan_evidence_id = None
        hyp_id = None
        plan_file: tuple[Path, bytes] | None = None
        if plan is not None:
            rel_plan_path = f"artifacts/explore-plans/{plan['plan_id']}.json"
            abs_plan_path = self._path(rel_plan_path)
            plan_text = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            expected_bytes = plan_text.encode("utf-8")
            source_bytes = self._read_source(abs_plan_path) if abs_plan_path.exists() else expected_bytes
            if source_bytes not in (expected_bytes, expected_bytes.replace(b"\n", b"\r\n")):
                fail("source_changed", "Existing exploration plan artifact differs from the locked plan")
            plan_file = (abs_plan_path, source_bytes)
            quote_line = f'"plan_digest": "{plan["plan_digest"]}"'
            reg_ev = self._register_evidence(
                db,
                case,
                {
                    "case_id": case_id,
                    "path": rel_plan_path,
                    "label": f"Locked confirmatory plan {plan['plan_id']}",
                    "provenance": "observed",
                    "kind": "unknown",
                    "quote": quote_line,
                    "location": f"{rel_plan_path}:plan_digest",
                },
                captured_content=source_bytes,
            )
            plan_evidence_id = reg_ev["evidence_id"]
            hyp_rec = self._register_hypothesis(
                db,
                case,
                {
                    "case_id": case_id,
                    "statement": target["statement"],
                    "timing_basis": "reported_prespecified",
                    "source_evidence_id": plan_evidence_id,
                },
            )
            hyp_id = hyp_rec["hypothesis_id"]
        else:
            hyp_rec = self._register_hypothesis(
                db,
                case,
                {
                    "case_id": case_id,
                    "statement": target["statement"],
                    "timing_basis": "exploratory",
                },
            )
            hyp_id = hyp_rec["hypothesis_id"]

        alternatives: list[dict[str, str]] = [
            {
                "explanation": target["strongest_rival"],
                "status": "not_excluded",
                "reason": f"Carry-over strongest rival from exploration {explore_doc['explore_id']}",
            }
        ]
        for other in explore_doc["hypotheses"]:
            if other["hypothesis_id"] == hid or len(alternatives) >= 3:
                continue
            alternatives.append({
                "explanation": other["statement"],
                "status": "excluded" if other.get("status") == "killed" else "not_excluded",
                "reason": other.get("kill_reason") or f"Competing exploration hypothesis {other['hypothesis_id']}",
            })

        prior_forks = int(explore_doc.get("exploratory_forks", 0))
        checks_overrides: dict[str, Any] = {}
        if prior_forks > 1:
            checks_overrides["multiplicity"] = {
                "status": "unknown",
                "reason": f"Carried over {prior_forks} prior exploratory forks from {explore_doc['explore_id']}; confirmatory multiplicity control required.",
            }
        upsert_payload: dict[str, Any] = {
            "case_id": case_id,
            "claim_id": "C1",
            "text": target["statement"],
            "claim_type": target["claim_type"],
            "evidence_level": "unassessed",
            "scope": req.get("scope") or (plan["estimand"] if plan else "UNKNOWN"),
            "evidence_ids": [plan_evidence_id] if plan_evidence_id else [],
            "origin": "prespecified" if plan is not None else "exploratory",
            "hypothesis_id": hyp_id,
            "contribution": f"Promoted from L1-Explore {explore_doc['explore_id']} (prior_exploratory_forks={prior_forks})",
            "alternatives": alternatives,
            "discriminating_test": target["discriminating_experiment"],
        }
        if checks_overrides:
            upsert_payload["checks_overrides"] = checks_overrides
        upserted = self._upsert_claim(db, case, upsert_payload)
        db.execute("UPDATE cases SET document=? WHERE id=?", (_json(case), case_id))
        sync_case_indexes(db, case)
        if plan_file is not None and not dry_run:
            materialize_file_atomically(*plan_file)
        return {
            "case_id": case_id,
            "state": case["state"],
            "plan_id": plan["plan_id"] if plan else None,
            "plan_evidence_id": plan_evidence_id,
            "hypothesis_record_id": hyp_id,
            "prior_exploratory_forks": prior_forks,
            "claim_id": upserted["claim_id"],
            "ceiling_diff": upserted["ceiling_diff"],
        }

    @staticmethod
    def _frozen_input(case: dict) -> dict:
        result = {key: case[key] for key in ("case_id", "question", "domain", "draft", "claims", "evidence", "hypotheses")}
        # Never change the byte/digest contract of already frozen v1 cases.
        if case.get("schema_version", 1) == 2:
            result["schema_version"] = 2
            for opt_key in ("prior_case_ids", "supersedes_case_id", "case_relation", "symmetry_mode", "blind_mode"):
                if opt_key in case:
                    result[opt_key] = case[opt_key]
        if gated(case):
            result.update(gate_version=case["gate_version"], blind=case["blind"])
        return result

    @classmethod
    def _validate_frozen(cls, case: dict) -> None:
        if _digest(cls._frozen_input(case)) != case["input_digest"]:
            fail("frozen_integrity_error", "the frozen case no longer matches its revision digest")
        for role, review in case["reviews"].items():
            if _digest(review) != case.get("review_digests", {}).get(role):
                fail("review_integrity_error", "an immutable submitted review changed")
        if "adjudication" in case and _digest(case["adjudication"]) != case.get("adjudication_digest"):
            fail("adjudication_integrity_error", "the immutable adjudication changed")

    def _freeze(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("draft",))
        fields(payload, {"case_id"}, {"case_id"}, "freeze")
        if not case["claims"]:
            fail("missing_ledger", "set a nonempty claim ledger before freezing")
        case["revision_id"] = _id("rev")
        case["input_digest"] = _digest(self._frozen_input(case))
        case["frozen_at"] = _now()
        case["packets"] = {
            role: {"packet_id": _id("packet"), "role": role, "created_at": case["frozen_at"], "input_digest": case["input_digest"]}
            for role in ROLES
        }
        case["state"] = "frozen"
        self._event(db, case["case_id"], "freeze", {"revision_id": case["revision_id"], "input_digest": case["input_digest"]})
        return {
            "case_id": case["case_id"], "state": case["state"], "revision_id": case["revision_id"],
            "input_digest": case["input_digest"], "packet_ids": {role: packet["packet_id"] for role, packet in case["packets"].items()},
        }

    @staticmethod
    def _line_span(source_text: str, start: int, end: int) -> tuple[int, int]:
        return line_span(source_text, start, end)

    @classmethod
    def _build_chunked_windows(
        cls,
        source_text: str,
        quote: str | None,
        excerpt_anchors: list[str] | None,
        *,
        budget_bytes: int = PACKET_TEXT_BYTES,
    ) -> tuple[str, list[dict], dict]:
        return build_chunked_windows(source_text, quote, excerpt_anchors, budget_bytes=budget_bytes)

    def _packet_evidence_entry(self, db: sqlite3.Connection, case: dict, entry: dict, *, strict: bool = True) -> dict:
        return packet_evidence_entry(db, case, entry, strict=strict)

    def _packet_evidence(self, db: sqlite3.Connection, case: dict, *, strict: bool = True) -> list[dict]:
        return packet_evidence(db, case, strict=strict)

    def _assemble_review_packet(
        self,
        db: sqlite3.Connection,
        case: dict,
        role: str,
        blind: bool,
        *,
        stage: str = "full",
    ) -> dict:
        return assemble_review_packet(db, case, role, blind, self._frozen_input(case), stage=stage)

    def _review_packet(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("frozen", "reviewed", "review_blocked", "adjudicated", "export_pending", "exported"))
        fields(payload, {"case_id", "role", "blind", "stage"}, {"case_id", "role"}, "review_packet")
        role = enum(payload["role"], ROLES, "role")
        stage = enum(payload.get("stage", "full"), PACKET_STAGES, "stage")
        blind = payload.get("blind", False)
        if gated(case):
            if "blind" in payload:
                fail("case_level_blind", "blind is frozen at case creation; per-request overrides are forbidden")
            blind = case["blind"]
        if not isinstance(blind, bool):
            fail("invalid_type", "blind must be a boolean")
        return self._assemble_review_packet(db, case, role, blind, stage=stage)

    @staticmethod
    def _identity(value: Any, label: str) -> dict:
        value = obj(value, label)
        fields(value, {"context_id", "model"}, {"context_id", "model"}, label)
        string(value["context_id"], f"{label}.context_id", maximum=200)
        string(value["model"], f"{label}.model", maximum=200)
        return value

    def _submit_review(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("frozen", "review_blocked"))
        required = {"case_id", "role", "packet_id", "input_digest", "reviewer", "covered_claim_ids", "findings"}
        if gated(case):
            required |= {"claim_stances", "unread_evidence_ids"}
        fields(payload, required | {"review_status", "isolation_attestation", "isolation_receipt"}, required, "submit_review")
        role = enum(payload["role"], ROLES, "role")
        if role in case["reviews"]:
            fail("duplicate_review", "each reviewer submits once; start a new case to revise")
        packet = case["packets"][role]
        if payload["packet_id"] != packet["packet_id"] or payload["input_digest"] != packet["input_digest"]:
            fail("stale_packet", "review must bind to this role's exact frozen packet and input digest")
        reviewer = self._identity(payload["reviewer"], "reviewer")
        used = {review["reviewer"]["context_id"] for review in case["reviews"].values()}
        if case["writer_context_id"]:
            used.add(case["writer_context_id"])
        if reviewer["context_id"] in used:
            fail("context_reuse", "reviewer must report a context distinct from the writer and other reviewer")
        isolation_attestation = self._isolation_attestation(payload["isolation_attestation"], "submit_review.isolation_attestation") if "isolation_attestation" in payload else None
        isolation_receipt = (
            validate_isolation_receipt(
                payload["isolation_receipt"],
                expected_packet_id=packet["packet_id"],
                expected_input_digest=packet["input_digest"],
                expected_role=role,
                expected_packet_sha256=packet_content_sha256(
                    self._assemble_review_packet(db, case, role, bool(case.get("blind", False)))
                ),
                workspace=self.workspace,
                label="submit_review.isolation_receipt",
            )
            if "isolation_receipt" in payload
            else None
        )
        isolation_grade = compute_isolation_grade(isolation_attestation, isolation_receipt, expected_profile="review")
        claims = {claim["id"]: claim for claim in case["claims"]}
        coverage = ids(payload["covered_claim_ids"], "covered_claim_ids")
        if set(coverage) != claims.keys():
            fail("incomplete_coverage", "covered_claim_ids must contain each frozen claim exactly once")
        if gated(case):
            evidence_packet = self._packet_evidence(db, case)
            exec_events = self._exec_events(db, case["case_id"])
            validate_unread_ack(payload["unread_evidence_ids"], evidence_packet)
            validate_stances(payload["claim_stances"], claims, evidence_packet, exec_events=exec_events)
        else:
            evidence_packet = case["evidence"]
            exec_events = None
        findings = array(payload["findings"], "findings", maximum=3)
        known_findings = {finding["id"] for review in case["reviews"].values() for finding in review["findings"]}
        for finding in findings:
            obj(finding, "finding")
            required_finding = {"id", "claim_id", "evidence_ids", "issue", "proposed_level", "proposed_text", "decision_impact"}
            if case.get("schema_version", 1) == 2:
                required_finding = (required_finding - {"proposed_level"}) | {"proposed_claim_type", "proposed_evidence_level", "proposed_scope"}
            if gated(case):
                required_finding.add("proposed_claim_basis")
            fields(finding, required_finding, required_finding, "finding")
            fid = string(finding["id"], "finding.id", maximum=200)
            if fid in known_findings:
                fail("duplicate_id", "finding IDs must be unique across both reviews")
            known_findings.add(fid)
            cid = string(finding["claim_id"], "finding.claim_id", maximum=200)
            if cid not in claims:
                fail("unknown_claim", "finding references a claim outside the frozen ledger")
            self._refs(ids(finding["evidence_ids"], "finding.evidence_ids"), set(claims[cid]["evidence_ids"]), "finding.evidence_ids")
            allowed_levels = SCIENTIFIC_LEVELS if case.get("domain", "scientific") == "scientific" else GENERAL_LEVELS
            if case.get("schema_version", 1) == 2:
                classification(finding, case["domain"], "proposed_", "proposed_scope")
                if gated(case):
                    validate_basis({"claim_type": finding["proposed_claim_type"], "claim_basis": finding["proposed_claim_basis"]})
            else:
                enum(finding["proposed_level"], allowed_levels, "finding.proposed_level")
            for key in ("issue", "proposed_text", "decision_impact"):
                string(finding[key], f"finding.{key}")
            if gated(case):
                for key in ("issue", "proposed_text", "proposed_scope"):
                    validate_non_placeholder_text(finding[key], f"finding.{key}")
                validate_rationale(finding["decision_impact"], "finding.decision_impact")
        review = {key: payload[key] for key in required - {"case_id"}}
        if isolation_attestation is not None:
            review["isolation_attestation"] = isolation_attestation
        if isolation_receipt is not None:
            review["isolation_receipt"] = isolation_receipt
        review.update({
            "review_status": enum(payload.get("review_status", "complete"), ("complete", "needs_split"), "review_status"),
            "submitted_at": _now(), "identity_basis": "caller_self_report",
            "independence": isolation_grade["basis"],
            "isolation_grade": isolation_grade,
        })
        case["reviews"][role] = review
        case.setdefault("review_digests", {})[role] = _digest(review)
        sym_audit = audit_underclaim_and_abstention(
            payload.get("claim_stances") or [],
            claims,
            evidence_packet,
            findings=[{**f, "role": role} for f in findings],
            exec_events=exec_events,
            is_review=True,
        )
        case.setdefault("review_symmetry_audits", {})[role] = sym_audit
        if any(item["review_status"] == "needs_split" for item in case["reviews"].values()):
            case["state"] = "review_blocked"
        elif len(case["reviews"]) == 2:
            case["state"] = "reviewed"
        self._event(db, case["case_id"], "submit_review", {"role": role, "review_digest": _digest(review), "review_status": review["review_status"]})
        return {"case_id": case["case_id"], "state": case["state"], "review": review, "symmetry_audit": sym_audit}

    def _assemble_adjudication_packet(self, db: sqlite3.Connection, case: dict) -> dict:
        return assemble_adjudication_packet(db, case, self._frozen_input(case))

    def _adjudication_packet(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("reviewed", "adjudicated", "export_pending", "exported"))
        fields(payload, {"case_id"}, {"case_id"}, "adjudication_packet")
        digest = _digest({"input_digest": case["input_digest"], "reviews": case["reviews"]})
        if "adjudication_packet" not in case:
            case["adjudication_packet"] = {"adjudication_id": _id("adj"), "input_digest": digest, "created_at": _now()}
            self._event(db, case["case_id"], "adjudication_packet", case["adjudication_packet"])
        elif case["adjudication_packet"]["input_digest"] != digest:
            fail("review_integrity_error", "adjudication no longer matches the registered reviews")
        return self._assemble_adjudication_packet(db, case)

    def _submit_adjudication(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("reviewed",))
        required = {"case_id", "adjudication_id", "input_digest", "adjudicator", "decisions", "dispositions"}
        if gated(case):
            required.add("unread_evidence_ids")
        fields(payload, required | {"isolation_attestation", "isolation_receipt"}, required, "submit_adjudication")
        packet = case.get("adjudication_packet")
        if not packet:
            fail("missing_packet", "retrieve adjudication_packet before submitting a judgment")
        if payload["adjudication_id"] != packet["adjudication_id"] or payload["input_digest"] != packet["input_digest"]:
            fail("stale_packet", "adjudication must bind to both reviews and the exact frozen input")
        if packet["input_digest"] != _digest({"input_digest": case["input_digest"], "reviews": case["reviews"]}):
            fail("review_integrity_error", "stored reviews changed after the adjudication packet was created")
        identity = self._identity(payload["adjudicator"], "adjudicator")
        if identity["context_id"] in {review["reviewer"]["context_id"] for review in case["reviews"].values()}:
            fail("context_reuse", "adjudicator must report a context distinct from both reviewers")
        isolation_attestation = self._isolation_attestation(payload["isolation_attestation"], "submit_adjudication.isolation_attestation") if "isolation_attestation" in payload else None
        isolation_receipt = (
            validate_isolation_receipt(
                payload["isolation_receipt"],
                expected_packet_id=packet["adjudication_id"],
                expected_input_digest=packet["input_digest"],
                expected_role="adjudication",
                expected_packet_sha256=packet_content_sha256(
                    self._assemble_adjudication_packet(db, case)
                ),
                workspace=self.workspace,
                label="submit_adjudication.isolation_receipt",
            )
            if "isolation_receipt" in payload
            else None
        )
        isolation_grade = compute_isolation_grade(isolation_attestation, isolation_receipt, expected_profile="adjudication")
        claims = {claim["id"]: claim for claim in case["claims"]}
        evidence_packet = self._packet_evidence(db, case) if gated(case) else []
        exec_events = self._exec_events(db, case["case_id"]) if gated(case) else []
        if gated(case):
            validate_unread_ack(payload["unread_evidence_ids"], evidence_packet)
        decisions = array(payload["decisions"], "decisions", minimum=1, maximum=100)
        decision_ids = []
        decision_fields = {"claim_id", "verdict", "level", "revised_text", "rationale", "evidence_ids", "confidence", "confidence_reason", "boundary", "reversal_condition"}
        if case.get("schema_version", 1) == 2:
            decision_fields = (decision_fields - {"level"}) | {"claim_type", "evidence_level", "scope"}
        if gated(case):
            decision_fields.add("claim_basis")
        decision_allowed = decision_fields | {"condition"}
        if case.get("schema_version", 1) == 2:
            decision_allowed |= {
                "reversal_triggers",
                "forecast_probability",
                "actionable_stance",
                "abstention_justification",
                "evidence_dominance",
            }
        prior_link_ids = {
            lnk["prior_case_id"]
            for c in case["claims"]
            for lnk in (c.get("prior_claim_links") or ())
            if isinstance(lnk, dict) and isinstance(lnk.get("prior_case_id"), str)
        }
        cases_by_id_for_lineage = (
            {case["case_id"]: case, **load_cases_for_ids(db, prior_link_ids)}
            if gated(case) and prior_link_ids
            else None
        )
        ev_by_id = {e["evidence_id"]: e for e in evidence_packet} if gated(case) else {}
        for decision in decisions:
            obj(decision, "decision")
            fields(decision, decision_allowed, decision_fields, "decision")
            cid = string(decision["claim_id"], "decision.claim_id", maximum=200)
            if cid not in claims:
                fail("unknown_claim", "decision references a claim outside the frozen ledger")
            decision_ids.append(cid)
            verdict = enum(decision["verdict"], VERDICTS, "decision.verdict")
            allowed_levels = SCIENTIFIC_LEVELS if case.get("domain", "scientific") == "scientific" else GENERAL_LEVELS
            if case.get("schema_version", 1) == 2:
                classification(decision, case["domain"])
            else:
                enum(decision["level"], allowed_levels, "decision.level")
            enum(decision["confidence"], ("high", "medium", "low"), "decision.confidence")
            if "forecast_probability" in decision:
                validate_forecast_probability(decision["forecast_probability"], "decision.forecast_probability")
            if "reversal_triggers" in decision:
                validate_reversal_triggers(decision["reversal_triggers"], case.get("domain", "scientific"))
            if "actionable_stance" in decision:
                enum(decision["actionable_stance"], ACTIONABLE_STANCES, "decision.actionable_stance")
            if "abstention_justification" in decision:
                decision["abstention_justification"] = validate_abstention_justification(
                    decision["abstention_justification"],
                    set(claims[cid]["evidence_ids"]),
                    "decision.abstention_justification",
                )
            if "evidence_dominance" in decision:
                decision["evidence_dominance"] = validate_evidence_dominance(
                    decision["evidence_dominance"],
                    "decision.evidence_dominance",
                )
            refs = ids(decision["evidence_ids"], "decision.evidence_ids", minimum=1 if verdict in ("supported", "partially_supported") else 0)
            self._refs(refs, set(claims[cid]["evidence_ids"]), "decision.evidence_ids")
            if case.get("schema_version", 1) == 2:
                validate_support(decision, claims[cid])
            if gated(case):
                validate_mechanical(decision, claims[cid], ev_by_id, exec_events=exec_events)
                if decision["verdict"] in ("supported", "partially_supported") and decision["claim_basis"] != claims[cid]["claim_basis"]:
                    if decision["revised_text"] == claims[cid]["text"] or decision["scope"] == claims[cid]["scope"]:
                        fail("basis_revision_required", "changing empirical/synthetic/formal basis requires revised wording and scope")
                check_self_triggering_reversals(claims[cid], decision, ev_by_id, exec_events=exec_events)
                if cases_by_id_for_lineage is not None and claims[cid].get("prior_claim_links"):
                    validate_lineage_transition(
                        claims[cid],
                        decision,
                        cases_by_id_for_lineage,
                        ev_by_id,
                        exec_events=exec_events,
                        current_case_id=case["case_id"],
                    )
            for key in ("revised_text", "rationale", "confidence_reason", "boundary", "reversal_condition"):
                string(decision[key], f"decision.{key}")
            if verdict == "partially_supported":
                string(decision.get("condition"), "decision.condition")
            elif "condition" in decision:
                string(decision["condition"], "decision.condition")
            if gated(case):
                if "condition" in decision:
                    validate_condition_text(decision["condition"], "decision.condition", missing_code="invalid_condition")
                for key in ("revised_text", "confidence_reason", "boundary"):
                    validate_non_placeholder_text(decision[key], f"decision.{key}")
                if verdict in ("supported", "partially_supported"):
                    validate_non_placeholder_text(decision["scope"], "decision.scope")
                validate_rationale(decision["rationale"], "decision.rationale")
                validate_reversal_condition(
                    decision["reversal_condition"],
                    "decision.reversal_condition",
                    decision=decision,
                    claim=claims[cid],
                )
        ids(decision_ids, "decision claim IDs")
        if set(decision_ids) != claims.keys():
            fail("incomplete_decisions", "every claim needs exactly one final decision")
        findings = {finding["id"] for review in case["reviews"].values() for finding in review["findings"]}
        finding_map = {f["id"]: f for review in case["reviews"].values() for f in review["findings"]}
        decision_map = {d["claim_id"]: d for d in decisions}
        dispositions = array(payload["dispositions"], "dispositions", maximum=6)
        disposition_ids = []
        for disposition in dispositions:
            obj(disposition, "disposition")
            disposition_required = {"finding_id", "disposition", "reason"}
            disposition_allowed = disposition_required | {"condition"}
            if gated(case):
                disposition_required |= {"claim_id", "resolution"}
                disposition_allowed |= disposition_required | {"revised_text_quote", "disagreement"}
            fields(disposition, disposition_allowed, disposition_required, "disposition")
            fid = string(disposition["finding_id"], "disposition.finding_id", maximum=200)
            disposition_ids.append(fid)
            enum(disposition["disposition"], ("accepted", "partial", "rejected"), "disposition.disposition")
            string(disposition["reason"], "disposition.reason")
            if disposition["disposition"] == "partial":
                string(disposition.get("condition"), "disposition.condition")
            elif "condition" in disposition:
                string(disposition["condition"], "disposition.condition")
            if gated(case) and "condition" in disposition:
                validate_condition_text(disposition["condition"], "disposition.condition", missing_code="invalid_condition")
            if gated(case):
                validate_rationale(disposition["reason"], "disposition.reason")
                if fid not in finding_map:
                    fail("unknown_finding", "disposition references an unknown finding")
                finding = finding_map[fid]
                validate_disposition(disposition, finding, decision_map[finding["claim_id"]], claims[finding["claim_id"]])
        ids(disposition_ids, "disposition finding IDs")
        if set(disposition_ids) != findings:
            fail("incomplete_dispositions", "every finding needs exactly one disposition; extra IDs are forbidden")
        sym_mode = case.get("symmetry_mode", "enforced") if gated(case) else "advisory"
        sym_audit = enforce_symmetry_adjudication(
            decisions,
            claims,
            evidence_packet if gated(case) else case["evidence"],
            findings=case["reviews"],
            dispositions=dispositions,
            exec_events=exec_events if gated(case) else None,
            symmetry_mode=sym_mode,
        )
        adjudication = {key: payload[key] for key in required - {"case_id"}}
        if isolation_attestation is not None:
            adjudication["isolation_attestation"] = isolation_attestation
        if isolation_receipt is not None:
            adjudication["isolation_receipt"] = isolation_receipt
        adjudication.update({
            "submitted_at": _now(),
            "identity_basis": "caller_self_report",
            "isolation_grade": isolation_grade,
            "scientific_validity": "not_established_by_engine",
        })
        case["adjudication"] = adjudication
        case["adjudication_digest"] = _digest(adjudication)
        case["symmetry_audit"] = sym_audit
        case["state"] = "adjudicated"
        self._event(db, case["case_id"], "submit_adjudication", {"adjudication_digest": _digest(adjudication), "symmetry_mode": sym_mode})
        return {"case_id": case["case_id"], "state": case["state"], "adjudication": adjudication, "symmetry_audit": sym_audit}

    def _verify(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        fields(payload, {"case_id"}, {"case_id"}, "verify")
        result = {"case_id": case["case_id"], "checked_at": _now(), "status": "pass", "evidence": [], "evidence_chains": [], "scientific_validity": "not_established_by_engine", "scope": "content_integrity_and_quote_traceability_only"}
        packet_map = {e["evidence_id"]: self._packet_evidence_entry(db, case, e, strict=False) for e in case["evidence"]} if gated(case) else {}
        snapshot_texts: dict[str, str] = {}
        snapshot_bytes: dict[str, bytes] = {}
        for evidence in case["evidence"]:
            row = db.execute("SELECT content FROM evidence_snapshots WHERE case_id=? AND evidence_id=?", (case["case_id"], evidence["evidence_id"])).fetchone()
            content = row[0] if row else None
            if content is not None:
                snapshot_bytes[evidence["evidence_id"]] = content
                decoded_snapshot = text_content(content)
                if decoded_snapshot is not None:
                    snapshot_texts[evidence["evidence_id"]] = decoded_snapshot
            snapshot_status = "missing" if content is None else "matched" if _bytes_digest(content) == evidence["sha256"] else "mismatch"
            file_status = "unreadable"
            try:
                source = self._path(evidence["path"])
                if not source.exists():
                    file_status = "missing"
                elif not source.is_file():
                    file_status = "mismatch"
                else:
                    current = self._read_source(source)
                    file_status = "matched" if _bytes_digest(current) == evidence["sha256"] else "mismatch"
            except ContractError as exc:
                file_status = "mismatch" if exc.code in ("unsafe_path", "too_large", "invalid_source") else "unreadable"
            except OSError:
                file_status = "unreadable"
            anchor_status = "not_supplied"
            if evidence["quote"] is not None:
                if content is None:
                    anchor_status = "unknown"
                else:
                    try:
                        anchor_status = "matched" if evidence["quote"] in content.decode("utf-8") else "mismatch"
                    except UnicodeDecodeError:
                        anchor_status = "not_text"
            if gated(case):
                anchor_status = quote_status(evidence["quote"], text_content(content) if content is not None else None)
            statuses = (snapshot_status, file_status, anchor_status)
            entry_status = "blocked" if any(value in statuses for value in ("mismatch", "ambiguous", "too_short")) else "unverified" if any(value in statuses for value in ("missing", "unreadable", "unknown", "not_text")) else "pass"
            if gated(case) and entry_status == "pass":
                pe = packet_map[evidence["evidence_id"]]
                windowed_ok = pe["source_text_status"] == "truncated" and bool(pe.get("excerpt_window", {}).get("quote_anchored"))
                if pe["source_text_status"] != "complete" and not windowed_ok:
                    entry_status = "unverified"
            ev_result = {
                "evidence_id": evidence["evidence_id"], "sha256": evidence["sha256"], "provenance": evidence["provenance"],
                "snapshot_status": snapshot_status, "file_status": file_status, "anchor_status": anchor_status,
                "status": entry_status, "lineage_status": "not_derived",
            }
            if gated(case):
                pe = packet_map[evidence["evidence_id"]]
                windows = pe.get("excerpt_windows") or []
                ev_result.update(
                    kind=evidence["kind"],
                    source_text_status=pe["source_text_status"],
                    unread_content_ack=evidence["unread_content_ack"],
                    excerpt_window_count=len(windows),
                )
                if windows:
                    ev_result["excerpt_windows"] = windows
            result["evidence"].append(ev_result)
        by_registered = {e["evidence_id"]: e for e in case["evidence"]}
        res_by_id = {e["evidence_id"]: e for e in result["evidence"]}
        for evidence in case["evidence"]:
            eid = evidence["evidence_id"]
            parents = evidence.get("derived_from_evidence_ids") or ()
            if not parents:
                continue
            lineage = evidence_lineage(eid, by_registered)
            ev_entry = res_by_id[eid]
            if lineage["cycle_detected"] or lineage["unknown_parents"]:
                lineage_status = "blocked"
                ev_entry["status"] = "blocked"
            else:
                has_blocked = False
                has_unverified = False
                has_unread_binary = False
                for aid in lineage["ancestors"]:
                    anc_res = res_by_id[aid]
                    anc_reg = by_registered[aid]
                    if (
                        anc_res["snapshot_status"] == "mismatch"
                        or anc_res["file_status"] == "mismatch"
                        or anc_res["anchor_status"] in ("mismatch", "ambiguous", "too_short")
                        or anc_res["status"] == "blocked"
                    ):
                        has_blocked = True
                    elif anc_res["snapshot_status"] != "matched" or anc_res["file_status"] != "matched":
                        has_unverified = True
                    else:
                        is_binary_anc = (
                            anc_res.get("source_text_status") == "binary_not_read_by_engine"
                            or anc_reg.get("content_read_status") == "binary_unread"
                        )
                        if is_binary_anc:
                            if anc_reg.get("unread_content_ack") is True:
                                has_unread_binary = True
                            else:
                                has_unverified = True
                        elif anc_res["status"] != "pass":
                            has_unverified = True
                if has_blocked:
                    lineage_status = "blocked"
                    ev_entry["status"] = "blocked"
                elif has_unverified:
                    lineage_status = "unverified"
                    if ev_entry["status"] == "pass":
                        ev_entry["status"] = "unverified"
                elif has_unread_binary:
                    lineage_status = "hash_verified_unread_binary_ancestors"
                else:
                    lineage_status = "verified"
            ev_entry["lineage_status"] = lineage_status
            result["evidence_chains"].append({
                "evidence_id": eid,
                "derived_from_evidence_ids": list(parents),
                "derivation_step": evidence.get("derivation_step"),
                "ancestors": lineage["ancestors"],
                "lineage_status": lineage_status,
                "cycle_detected": lineage["cycle_detected"],
                "unknown_parents": lineage["unknown_parents"],
            })
        if not result["evidence"]:
            result["status"] = "unverified"
        elif any(item["status"] == "blocked" for item in result["evidence"]):
            result["status"] = "blocked"
        elif any(item["status"] == "unverified" for item in result["evidence"]):
            result["status"] = "unverified"
        else:
            result["status"] = "pass"
        effect_checks: dict[str, Any] = {}
        decision_map = {
            d["claim_id"]: d
            for d in (case.get("adjudication", {}).get("decisions") or ())
            if isinstance(d, dict) and d.get("claim_id")
        }
        ev_by_id = packet_map if gated(case) else {e["evidence_id"]: e for e in case["evidence"]}
        for claim in case["claims"]:
            if not claim.get("effect_records"):
                continue
            try:
                effect_checks[claim["id"]] = verify_effect_computations(
                    claim,
                    decision_map.get(claim["id"]),
                    ev_by_id,
                    snapshot_texts={
                        eid: txt
                        for eid, txt in snapshot_texts.items()
                        if not (ev_by_id.get(eid) or {}).get("quote")
                    },
                    snapshot_bytes={
                        eid: raw
                        for eid, raw in snapshot_bytes.items()
                        if not (ev_by_id.get(eid) or {}).get("quote")
                    },
                )
            except ContractError as exc:
                effect_checks[claim["id"]] = {
                    "status": "blocked",
                    "error": exc.code,
                    "message": exc.message,
                    "record_count": len(claim.get("effect_records") or ()),
                }
                result["status"] = "blocked"
        if effect_checks:
            result["effect_checks"] = effect_checks
        dec_by_cid = {}
        if case.get("adjudication"):
            for dec in case["adjudication"].get("decisions", ()):
                dec_by_cid[dec["claim_id"]] = dec
        if any(collect_claim_triggers(c, dec_by_cid.get(c["id"])) for c in case["claims"]):
            downstream = load_downstream_cases(db, case["case_id"])
            ev_map = packet_map if gated(case) else {e["evidence_id"]: e for e in case["evidence"]}
            result["trigger_evaluation"] = evaluate_case_triggers(
                case,
                downstream_cases=downstream,
                verification=result,
                exec_events=self._exec_events(db, case["case_id"]) if gated(case) else [],
                evidence_by_id=ev_map,
            )
        chain_before = self.verify_event_chain(db, case["case_id"])
        if chain_before["status"] == "tampered":
            result["status"] = "blocked"
        if "adjudication" in case:
            result["symmetry_audit"] = audit_underclaim_and_abstention(
                case["adjudication"]["decisions"],
                case["claims"],
                [packet_map[e["evidence_id"]] for e in case["evidence"]] if gated(case) else case["evidence"],
                findings=case.get("reviews"),
                dispositions=case["adjudication"].get("dispositions"),
                exec_events=self._exec_events(db, case["case_id"]) if gated(case) else None,
                is_review=False,
            )
        self._event(db, case["case_id"], "verify", {"status": result["status"], "checked_at": result["checked_at"]})
        chain_after = chain_before if chain_before["status"] == "tampered" else self.verify_event_chain(db, case["case_id"])
        result["event_chain"] = chain_after
        result["event_chain_status"] = chain_after["status"]
        case["verification"] = result
        return result

    @classmethod
    def _get_case(cls, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        fields(payload, {"case_id"}, {"case_id"}, "get_case")
        result = dict(case)
        result["events"] = [{"sequence": row[0], "action": row[1], "recorded_at": row[2], "details": json.loads(row[3])} for row in db.execute("SELECT sequence,action,recorded_at,details FROM events WHERE case_id=? ORDER BY sequence", (case["case_id"],))]
        chain = cls.verify_event_chain(db, case["case_id"])
        result["event_chain"] = chain
        result["event_chain_status"] = chain["status"]
        return result

    def _record_human_decision(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        required = {"case_id", "decision", "responsible_human", "reason"}
        fields(payload, required, required, "record_human_decision")
        event = {
            "decision": enum(payload["decision"], ("accept", "challenge", "defer", "pause"), "decision"),
            "responsible_human": string(payload["responsible_human"], "responsible_human", maximum=200),
            "reason": string(payload["reason"], "reason"), "recorded_at": _now(),
            "identity_basis": "caller_report_not_identity_authentication",
            "scientific_validity": "not_established_by_engine",
        }
        case["human_decisions"].append(event)
        self._event(db, case["case_id"], "record_human_decision", event)
        return {"case_id": case["case_id"], "state": case["state"], "human_decision": event}

    def _render_report(self, case: dict, verification: dict) -> str:
        return render_markdown_report(
            case,
            verification,
            integrity_boundary=INTEGRITY_BOUNDARY,
            packet_text_bytes=PACKET_TEXT_BYTES,
        )

    def _export(self, db: sqlite3.Connection, case: dict, payload: dict) -> dict:
        self._state(case, ("adjudicated", "export_pending"))
        fields(payload, {"case_id", "path"}, {"case_id"}, "export")
        if self._human_holds(case):
            fail("human_hold", "an explicit accept must resolve all reported challenge/defer/pause holds before export")
        default_path = case.get("export", {}).get("relative_path", f"exports/{case['case_id']}.md")
        target = self._path(payload.get("path", default_path))
        if target.suffix.lower() != ".md":
            fail("invalid_export_path", "the rendered report must use a .md extension")
        if case["state"] == "export_pending":
            if str(target) != case["export"]["path"]:
                fail("export_pending", "resume the exact pending export path; do not create another artifact")
            return {"case_id": case["case_id"], "state": "export_pending"}
        if target.exists():
            fail("export_exists", "export never overwrites an existing file")
        verification = self._verify(db, case, {"case_id": case["case_id"]})
        if verification["status"] == "blocked":
            fail("verification_mismatch", "source bytes or quote anchors mismatch; final export is blocked")
        evidence_status = {entry["evidence_id"]: entry["status"] for entry in verification["evidence"]}
        for decision in case["adjudication"]["decisions"]:
            if decision["verdict"] in ("supported", "partially_supported"):
                if any(evidence_status[eid] != "pass" for eid in decision["evidence_ids"]):
                    fail("unverified_support", "positive judgments cannot cite missing/unreadable/unanchored source evidence")
        report = self._render_report(case, verification).encode("utf-8")
        case["state"] = "export_pending"
        case["export"] = {
            "path": str(target), "relative_path": target.relative_to(self.workspace).as_posix(),
            "sha256": _bytes_digest(report), "prepared_at": _now(),
            "verification_digest": _digest(verification["evidence"]),
        }
        db.execute("INSERT INTO export_artifacts(case_id,content) VALUES(?,?)", (case["case_id"], report))
        self._event(db, case["case_id"], "prepare_export", case["export"])
        return {"case_id": case["case_id"], "state": "export_pending"}

    def _materialize_export(self, case_id: str) -> dict:
        """Commit the immutable artifact before I/O; a retry recovers the same bytes."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()[0])
            self._validate_frozen(case)
            self._state(case, ("export_pending", "exported"))
            if case["state"] == "exported":
                return {"case_id": case_id, "state": "exported", **case["export"], "verification": case["verification"]}
            if self._human_holds(case):
                fail("human_hold", "resolve the reported human hold before materializing the pending export")
            verification = self._verify(db, case, {"case_id": case_id})
            if verification["status"] == "blocked":
                fail("verification_mismatch", "source integrity changed before export materialization")
            if _digest(verification["evidence"]) != case["export"]["verification_digest"]:
                fail("export_verification_changed", "restore the source state used by the pending report before retrying")
            report = db.execute("SELECT content FROM export_artifacts WHERE case_id=?", (case_id,)).fetchone()[0]
            if _bytes_digest(report) != case["export"]["sha256"]:
                fail("artifact_mismatch", "the retained report no longer matches its prepared digest")
            target = self._path(case["export"]["relative_path"])
            self._path(case["export"]["relative_path"])
            materialize_file_atomically(target, report, link_fn=os.link, fallback_writer=_write_exclusive_export)
            case["state"] = "exported"
            case["export"]["exported_at"] = _now()
            self._event(db, case_id, "export", case["export"])
            db.execute("UPDATE cases SET document=? WHERE id=?", (_json(case), case_id))
            sync_case_indexes(db, case)
            return {"case_id": case_id, "state": "exported", **case["export"], "verification": verification}
