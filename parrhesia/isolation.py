"""Estimate-first blind dossiers and verifiable isolation receipt grading. Pure stdlib.

This module never fabricates cryptographic enclave guarantees. Instead, it:
  1. Generates per-packet nonces bound to the frozen packet digest.
  2. Builds an 'estimate_first' evidence-only dossier separating raw source evidence
     and quantitative effect records from author-framed claim wording.
  3. Verifies runner-supplied isolation receipts and computes an honest, graded
     `isolation_grade` distinguishing runner-verified subprocess isolation from
     caller-attested isolation, self-reported distinct context_ids, and same-context runs.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
from pathlib import Path
from typing import Any

from .contracts import enum, fail, fields, obj, string
from .storage import canonical_json

BLIND_MODES = ("standard", "estimate_first")
PACKET_STAGES = ("full", "evidence_only")
OS_SANDBOX_MODES = ("standard", "strict_os")
OS_SANDBOX_BACKENDS = ("none", "bwrap", "sandbox-exec")
ISOLATION_GRADES = (
    "subprocess_sealed_isolated",
    "runner_verified_isolated",
    "caller_attested",
    "self_reported_context_only",
    "non_independent",
)
_RUNNER_KEY_FILENAME = "runner.key"

ESTIMATE_FIRST_INSTRUCTIONS = (
    " ESTIMATE-FIRST BLIND PROTOCOL: Step 1 — inspect `evidence_first_dossier` (raw source text, "
    "effect_records, execution receipts, and check status) BEFORE weighing the author's wording, "
    "and independently determine what claim_type × evidence_level + direction the evidence warrants. "
    "Step 2 — compare your independent estimate against `claims`, flagging both unsupported strengthening "
    "(overclaim) and unjustified retreat/hedging (underclaim)."
)

STAGE1_EVIDENCE_ONLY_INSTRUCTIONS = (
    " STAGE 1 BLIND EVIDENCE-ONLY COMMIT: Author claim wording, hypothesis framing, "
    "editorial narrative, and draft manuscript are intentionally withheld in this packet. "
    "Inspect `evidence_first_dossier` and raw `evidence` only, and output a JSON object with "
    "`protocol`: 'estimate_first_stage1_v1', `packet_nonce` matching this packet, and "
    "`claims`: {claim_id: {claim_type, evidence_level, direction, rationale}} BEFORE "
    "seeing Stage 2 author wording."
)

_HEX64_CHARS = frozenset("0123456789abcdef")


def _check_hex64(value: Any, label: str, code: str = "invalid_value") -> str:
    text = string(value, label, maximum=64)
    if len(text) != 64 or any(c not in _HEX64_CHARS for c in text):
        fail(code, f"{label} must be a 64-char lowercase hex SHA-256")
    return text


def _finite_opt_num(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("invalid_type", f"{label} must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        fail("invalid_value", f"{label} must be finite")
    return num


def packet_nonce(packet_id: str, input_digest: str, role: str) -> str:
    """Deterministic per-packet binding nonce derived from frozen identifiers."""
    raw = f"parrhesia-isolation-v1:{packet_id}:{input_digest}:{role}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def build_evidence_first_dossier(
    case: dict[str, Any],
    evidence_entries: list[dict[str, Any]],
    *,
    strip_author_direction: bool = False,
) -> dict[str, Any]:
    """Assemble a de-narrativized dossier of raw evidence, quantitative records, and check ceilings."""
    sources = []
    for ev in evidence_entries:
        sources.append({
            "evidence_id": ev["evidence_id"],
            "kind": ev.get("kind"),
            "provenance": ev.get("provenance"),
            "location": ev.get("location"),
            "quote": ev.get("quote"),
            "source_text_status": ev.get("source_text_status"),
            "source_text": ev.get("source_text"),
            "sha256": ev.get("sha256"),
        })
    quantitative_blocks = []
    for cl in case.get("claims") or ():
        raw_effects = list(cl.get("effect_records") or ())
        if strip_author_direction:
            raw_effects = [
                {k: v for k, v in rec.items() if k != "claim_direction"} if isinstance(rec, dict) else rec
                for rec in raw_effects
            ]
        quantitative_blocks.append({
            "claim_id": cl["id"],
            "evidence_ids": list(cl.get("evidence_ids") or ()),
            "effect_records": raw_effects,
            "checks": cl.get("checks"),
            "design_packages": cl.get("design_packages"),
            "statistical_report": cl.get("statistical_report"),
        })
    return {
        "protocol": "estimate_first_v1",
        "sources": sources,
        "quantitative_and_checks": quantitative_blocks,
        "guidance": "Form an independent judgment of warranted claim_type, evidence_level, and direction from this dossier before comparing against author wording.",
    }


def validate_stage1_estimates(
    payload: Any,
    *,
    claim_ids: set[str] | tuple[str, ...] | list[str] | None = None,
    expected_nonce: str | None = None,
    expected_packet_sha256: str | None = None,
    label: str = "stage1_estimates",
) -> dict[str, Any]:
    """Validate and canonicalize Stage 1 evidence-only blind estimates prior to Stage 2 reveal."""
    from .claims import TYPE_LEVELS

    doc = obj(payload, label)
    required = {"protocol", "claims"}
    allowed = required | {"packet_nonce", "packet_sha256", "summary", "notes"}
    fields(doc, allowed, required, label)

    protocol = string(doc["protocol"], f"{label}.protocol", maximum=64)
    if protocol != "estimate_first_stage1_v1":
        fail("invalid_stage1_estimates", f"{label}.protocol must be 'estimate_first_stage1_v1'")

    normalized: dict[str, Any] = {"protocol": protocol}
    if "packet_nonce" in doc:
        pnonce = string(doc["packet_nonce"], f"{label}.packet_nonce", maximum=128)
        if expected_nonce is not None and pnonce != expected_nonce:
            fail("invalid_isolation_receipt", f"{label}.packet_nonce does not match Stage 1 evidence-only packet")
        normalized["packet_nonce"] = pnonce
    if "packet_sha256" in doc:
        psha = _check_hex64(doc["packet_sha256"], f"{label}.packet_sha256", code="invalid_stage1_estimates")
        if expected_packet_sha256 is not None and psha != expected_packet_sha256:
            fail("invalid_isolation_receipt", f"{label}.packet_sha256 does not match Stage 1 evidence-only packet")
        normalized["packet_sha256"] = psha

    raw_claims = obj(doc["claims"], f"{label}.claims")
    if not raw_claims:
        fail("invalid_stage1_estimates", f"{label}.claims must be non-empty")

    known_ids = set(claim_ids) if claim_ids is not None else None
    norm_claims: dict[str, dict[str, Any]] = {}
    for cid in sorted(raw_claims):
        cid_str = string(cid, f"{label}.claims key", maximum=200)
        if known_ids is not None and cid_str not in known_ids:
            fail("unknown_claim", f"{label}.claims references unknown claim {cid_str!r}")
        entry = obj(raw_claims[cid], f"{label}.claims[{cid_str!r}]")
        item_req = {"claim_type", "evidence_level", "direction", "rationale"}
        item_opt = {"estimate", "ci_low", "ci_high", "scope", "notes"}
        fields(entry, item_req | item_opt, item_req, f"{label}.claims[{cid_str!r}]")

        ctype = enum(entry["claim_type"], tuple(TYPE_LEVELS), f"{label}.claims[{cid_str!r}].claim_type")
        elevel = enum(entry["evidence_level"], TYPE_LEVELS[ctype], f"{label}.claims[{cid_str!r}].evidence_level")
        direction = string(entry["direction"], f"{label}.claims[{cid_str!r}].direction", maximum=100)
        rationale = string(entry["rationale"], f"{label}.claims[{cid_str!r}].rationale", maximum=4000)

        norm_entry: dict[str, Any] = {
            "claim_type": ctype,
            "evidence_level": elevel,
            "direction": direction,
            "rationale": rationale,
        }
        est_num: float | None = None
        lo_num: float | None = None
        hi_num: float | None = None
        if entry.get("estimate") is not None:
            est_num = _finite_opt_num(entry["estimate"], f"{label}.claims[{cid_str!r}].estimate")
            norm_entry["estimate"] = est_num
        has_lo = entry.get("ci_low") is not None
        has_hi = entry.get("ci_high") is not None
        if has_lo != has_hi:
            fail("invalid_stage1_estimates", f"{label}.claims[{cid_str!r}] must supply both ci_low and ci_high or omit both")
        if has_lo and has_hi:
            lo_num = _finite_opt_num(entry["ci_low"], f"{label}.claims[{cid_str!r}].ci_low")
            hi_num = _finite_opt_num(entry["ci_high"], f"{label}.claims[{cid_str!r}].ci_high")
            if lo_num > hi_num:
                fail("invalid_stage1_estimates", f"{label}.claims[{cid_str!r}] requires ci_low <= ci_high")
            if est_num is not None and (lo_num > est_num or est_num > hi_num):
                fail("invalid_stage1_estimates", f"{label}.claims[{cid_str!r}] requires ci_low <= estimate <= ci_high")
            norm_entry["ci_low"] = lo_num
            norm_entry["ci_high"] = hi_num
        if entry.get("scope") is not None:
            norm_entry["scope"] = string(entry["scope"], f"{label}.claims[{cid_str!r}].scope", maximum=1000)
        if entry.get("notes") is not None:
            norm_entry["notes"] = string(entry["notes"], f"{label}.claims[{cid_str!r}].notes", maximum=4000)
        norm_claims[cid_str] = norm_entry

    if known_ids is not None:
        missing = sorted(known_ids - set(norm_claims))
        if missing:
            fail(
                "incomplete_stage1_estimates",
                f"{label}.claims must estimate all dossier claims before Stage 2 reveal (missing: {', '.join(missing)})",
            )

    normalized["claims"] = norm_claims
    if doc.get("summary") is not None:
        normalized["summary"] = string(doc["summary"], f"{label}.summary", maximum=4000)
    if doc.get("notes") is not None:
        normalized["notes"] = string(doc["notes"], f"{label}.notes", maximum=4000)
    return normalized


def ensure_runner_key(workspace: str | Path) -> bytes:
    """Load or atomically create a workspace-local 32-byte HMAC key inside .parrhesia/runner.key.

    Never exposed to isolated child subprocesses, packets, or exported reports.
    """
    state_dir = Path(workspace).resolve() / ".parrhesia"
    state_dir.mkdir(parents=True, exist_ok=True)
    key_path = state_dir / _RUNNER_KEY_FILENAME
    if key_path.is_file():
        raw = key_path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]
    key = os.urandom(32)
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(key_path, flags, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        return key
    except FileExistsError:
        raw = key_path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]
        fail("invalid_isolation_receipt", "Workspace runner key is corrupted")


def read_runner_key(workspace: str | Path) -> bytes | None:
    key_path = Path(workspace).resolve() / ".parrhesia" / _RUNNER_KEY_FILENAME
    if not key_path.is_file():
        return None
    raw = key_path.read_bytes()
    return raw[:32] if len(raw) >= 32 else None


def compute_runner_seal(key: bytes, receipt_fields: dict[str, Any]) -> str:
    """Compute workspace-local HMAC-SHA256 seal binding an isolated subprocess receipt."""
    sealed_payload: dict[str, Any] = {
        "runner": receipt_fields.get("runner"),
        "packet_nonce": receipt_fields.get("packet_nonce"),
        "packet_sha256": receipt_fields.get("packet_sha256"),
        "parent_history_messages": receipt_fields.get("parent_history_messages"),
        "memory_enabled": receipt_fields.get("memory_enabled"),
        "tool_profile": receipt_fields.get("tool_profile"),
        "env_scrubbed": bool(receipt_fields.get("env_scrubbed", False)),
        "isolated_cwd": bool(receipt_fields.get("isolated_cwd", False)),
        "transcript_sha256": receipt_fields.get("transcript_sha256"),
        "exit_status": receipt_fields.get("exit_status"),
    }
    for opt_key in (
        "two_stage_blind",
        "stage1_estimate_sha256",
        "stage1_transcript_sha256",
        "os_sandbox",
        "workspace_untouched",
    ):
        if opt_key in receipt_fields and receipt_fields[opt_key] is not None:
            sealed_payload[opt_key] = receipt_fields[opt_key]
    msg = canonical_json(sealed_payload).encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_runner_seal(workspace: str | Path, receipt_fields: dict[str, Any], seal: str) -> bool:
    key = read_runner_key(workspace)
    if key is None:
        return False
    expected = compute_runner_seal(key, receipt_fields)
    return hmac.compare_digest(expected, seal)


def validate_isolation_receipt(
    receipt: Any,
    *,
    expected_packet_id: str,
    expected_input_digest: str,
    expected_role: str,
    expected_packet_sha256: str | None = None,
    workspace: str | Path | None = None,
    label: str = "isolation_receipt",
) -> dict[str, Any]:
    """Validate an optional runner-generated isolation receipt (nonce, packet SHA-256, and optional HMAC seal)."""
    rec = obj(receipt, label)
    required = {
        "runner",
        "packet_nonce",
        "packet_sha256",
        "parent_history_messages",
        "memory_enabled",
        "tool_profile",
    }
    allowed = required | {
        "transcript_sha256",
        "model_route",
        "env_scrubbed",
        "isolated_cwd",
        "runner_pid",
        "exit_status",
        "runner_seal",
        "two_stage_blind",
        "stage1_estimate_sha256",
        "stage1_transcript_sha256",
        "os_sandbox",
        "workspace_untouched",
    }
    fields(rec, allowed, required, label)
    runner = string(rec["runner"], f"{label}.runner", maximum=200)
    nonce = string(rec["packet_nonce"], f"{label}.packet_nonce", maximum=128)
    pkt_sha = _check_hex64(rec["packet_sha256"], f"{label}.packet_sha256")
    hist = rec["parent_history_messages"]
    if isinstance(hist, bool) or not isinstance(hist, int) or hist < 0:
        fail("invalid_value", f"{label}.parent_history_messages must be a non-negative integer")
    mem = rec["memory_enabled"]
    if type(mem) is not bool:
        fail("invalid_type", f"{label}.memory_enabled must be a boolean")
    profile = string(rec["tool_profile"], f"{label}.tool_profile", maximum=64)
    expected_nonce = packet_nonce(expected_packet_id, expected_input_digest, expected_role)
    if nonce != expected_nonce:
        fail("invalid_isolation_receipt", f"{label}.packet_nonce does not match this role packet")
    if expected_packet_sha256 is not None and pkt_sha != expected_packet_sha256:
        fail("invalid_isolation_receipt", f"{label}.packet_sha256 does not match the canonical frozen role packet")
    out: dict[str, Any] = {
        "runner": runner,
        "packet_nonce": nonce,
        "packet_sha256": pkt_sha,
        "parent_history_messages": hist,
        "memory_enabled": mem,
        "tool_profile": profile,
        "verification_scope": "runner_receipt_verified_not_hardware_enclave",
    }
    if "transcript_sha256" in rec:
        out["transcript_sha256"] = _check_hex64(rec["transcript_sha256"], f"{label}.transcript_sha256")
    if "model_route" in rec:
        out["model_route"] = string(rec["model_route"], f"{label}.model_route", maximum=200)
    for bkey in ("env_scrubbed", "isolated_cwd", "two_stage_blind", "workspace_untouched"):
        if bkey in rec:
            if type(rec[bkey]) is not bool:
                fail("invalid_type", f"{label}.{bkey} must be a boolean")
            out[bkey] = rec[bkey]
    for sha_key in ("stage1_estimate_sha256", "stage1_transcript_sha256"):
        if sha_key in rec:
            out[sha_key] = _check_hex64(rec[sha_key], f"{label}.{sha_key}")
    if "os_sandbox" in rec:
        out["os_sandbox"] = enum(rec["os_sandbox"], OS_SANDBOX_BACKENDS, f"{label}.os_sandbox")
    for ikey in ("runner_pid", "exit_status"):
        if ikey in rec:
            if isinstance(rec[ikey], bool) or not isinstance(rec[ikey], int):
                fail("invalid_type", f"{label}.{ikey} must be an integer")
            out[ikey] = rec[ikey]
    if out.get("two_stage_blind") is True:
        if not out.get("stage1_estimate_sha256") or not out.get("stage1_transcript_sha256"):
            fail(
                "invalid_isolation_receipt",
                f"{label}.two_stage_blind requires both stage1_estimate_sha256 and stage1_transcript_sha256",
            )
    if "runner_seal" in rec:
        seal = string(rec["runner_seal"], f"{label}.runner_seal", maximum=64)
        if len(seal) != 64 or any(c not in _HEX64_CHARS for c in seal):
            fail("invalid_isolation_receipt", f"{label}.runner_seal must be a 64-char lowercase hex HMAC-SHA256")
        if workspace is None or not verify_runner_seal(workspace, out, seal):
            fail("invalid_isolation_receipt", f"{label}.runner_seal failed workspace HMAC verification")
        out["runner_seal"] = seal
        out["runner_seal_verified"] = True
        out["verification_scope"] = "subprocess_hmac_sealed_not_hardware_enclave"
    else:
        out["runner_seal_verified"] = False
    return out


def compute_isolation_grade(
    attestation: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    *,
    expected_profile: str = "review",
) -> dict[str, Any]:
    """Derive honest 5-tier isolation grade and explicit sandbox boundaries from receipt and attestation."""
    if receipt is not None:
        os_sbx = str(receipt.get("os_sandbox") or "none")
        ws_untouched = receipt.get("workspace_untouched") if "workspace_untouched" in receipt else None
        two_stage_ok = bool(
            receipt.get("runner_seal_verified") is True
            and receipt.get("two_stage_blind") is True
            and receipt.get("stage1_estimate_sha256")
            and receipt.get("stage1_transcript_sha256")
        )
        if receipt.get("parent_history_messages") == 0 and receipt.get("memory_enabled") is False:
            profile_ok = receipt.get("tool_profile") in (expected_profile, "review", "adjudication")
            if profile_ok:
                if (
                    receipt.get("runner_seal_verified") is True
                    and receipt.get("env_scrubbed") is True
                    and receipt.get("isolated_cwd") is True
                    and ws_untouched is not False
                ):
                    enforced = [
                        "packet_nonce_bound",
                        "packet_sha256_bound",
                        "parent_history_zero",
                        "memory_disabled",
                        "scrubbed_env_allowlist",
                        "isolated_cwd",
                        "appdata_xdg_sandboxed",
                        "hmac_runner_seal_verified",
                    ]
                    if ws_untouched is True:
                        enforced.append("workspace_snapshot_unchanged")
                    if two_stage_ok:
                        enforced.append("two_stage_evidence_only_commit")
                    if os_sbx in ("bwrap", "sandbox-exec"):
                        enforced.append(f"os_sandbox_{os_sbx}")
                    not_enforced = []
                    if os_sbx not in ("bwrap", "sandbox-exec"):
                        not_enforced.append("no_kernel_fs_or_network_namespace")
                    if not two_stage_ok:
                        not_enforced.append("single_stage_author_framing_present")
                    not_enforced.extend(["separate_model_weights_not_proven", "no_hardware_enclave"])
                    return {
                        "grade": "subprocess_sealed_isolated",
                        "basis": "verified_hmac_runner_seal_scrubbed_env_isolated_cwd_zero_history",
                        "honest_limit": "OS-process isolation with workspace HMAC runner seal; not a hardware enclave or proof of independent model weights.",
                        "two_stage_blind_verified": two_stage_ok,
                        "os_sandbox": os_sbx,
                        "workspace_untouched": ws_untouched,
                        "boundaries": {"enforced": enforced, "not_enforced": not_enforced},
                    }
                enforced = [
                    "packet_nonce_bound",
                    "packet_sha256_bound",
                    "parent_history_zero",
                    "memory_disabled",
                ]
                if receipt.get("env_scrubbed") is True:
                    enforced.append("env_scrubbed")
                if receipt.get("isolated_cwd") is True:
                    enforced.append("isolated_cwd")
                not_enforced = [
                    "no_hmac_runner_seal",
                    "no_kernel_fs_or_network_namespace",
                    "workspace_tamper_unverified" if ws_untouched is not True else "single_stage_author_framing_present",
                    "separate_model_weights_not_proven",
                    "no_hardware_enclave",
                ]
                if ws_untouched is False:
                    not_enforced.insert(0, "workspace_state_mutated_during_execution")
                return {
                    "grade": "runner_verified_isolated",
                    "basis": "valid_packet_nonce_and_zero_history_runner_receipt",
                    "honest_limit": "Host/runner process receipt; not a hardware enclave proof.",
                    "two_stage_blind_verified": False,
                    "os_sandbox": os_sbx,
                    "workspace_untouched": ws_untouched,
                    "boundaries": {"enforced": enforced, "not_enforced": not_enforced},
                }
        return {
            "grade": "non_independent",
            "basis": "runner_receipt_reported_inherited_history_or_enabled_memory",
            "honest_limit": "Runner receipt indicates non-zero parent history or active memory.",
            "two_stage_blind_verified": False,
            "os_sandbox": os_sbx,
            "workspace_untouched": ws_untouched,
            "boundaries": {
                "enforced": ["packet_nonce_generated"],
                "not_enforced": ["context_or_memory_independence_failed", "no_kernel_fs_or_network_namespace", "no_hardware_enclave"],
            },
        }

    if isinstance(attestation, dict):
        hist = str(attestation.get("history_inheritance") or "").strip().casefold()
        mem = str(attestation.get("memory_access") or "").strip().casefold()
        if any(tok in hist for tok in ("inherit", "shared", "same", "full", "yes", "true")) and not any(
            tok in hist for tok in ("none", "no", "false", "zero", "disabled", "fresh", "isolated", "clean")
        ):
            return {
                "grade": "non_independent",
                "basis": "caller_reported_history_inheritance",
                "honest_limit": "Same or inherited drafting context disclosed.",
                "two_stage_blind_verified": False,
                "os_sandbox": "none",
                "workspace_untouched": None,
                "boundaries": {
                    "enforced": ["packet_nonce_generated"],
                    "not_enforced": ["context_or_memory_independence_failed", "no_kernel_fs_or_network_namespace", "no_hardware_enclave"],
                },
            }
        no_hist = any(tok in hist for tok in ("none", "no", "false", "zero", "disabled", "fresh", "isolated", "clean"))
        no_mem = any(tok in mem for tok in ("none", "no", "false", "disabled", "off", "blocked"))
        if no_hist and no_mem:
            return {
                "grade": "caller_attested",
                "basis": "caller_attested_clean_context_and_disabled_memory",
                "honest_limit": "Self-reported attestation only; host runtime did not provide a signed receipt.",
                "two_stage_blind_verified": False,
                "os_sandbox": "none",
                "workspace_untouched": None,
                "boundaries": {
                    "enforced": ["packet_nonce_generated", "distinct_context_id_checked"],
                    "not_enforced": [
                        "no_runner_receipt",
                        "no_hmac_runner_seal",
                        "no_env_or_cwd_isolation",
                        "no_kernel_fs_or_network_namespace",
                        "no_hardware_enclave",
                    ],
                },
            }

    return {
        "grade": "self_reported_context_only",
        "basis": "distinct_context_id_string_only",
        "honest_limit": "Only distinct context_id strings were checked; true context isolation is unverified.",
        "two_stage_blind_verified": False,
        "os_sandbox": "none",
        "workspace_untouched": None,
        "boundaries": {
            "enforced": ["packet_nonce_generated", "distinct_context_id_checked"],
            "not_enforced": [
                "unverified_history_or_memory_isolation",
                "no_runner_receipt",
                "no_hmac_runner_seal",
                "no_env_or_cwd_isolation",
                "no_kernel_fs_or_network_namespace",
                "no_hardware_enclave",
            ],
        },
    }


def packet_content_sha256(packet: dict[str, Any]) -> str:
    """Canonical SHA-256 digest of a serialized role packet (excluding transient nonce field if needed)."""
    return hashlib.sha256(canonical_json(packet).encode("utf-8")).hexdigest()
