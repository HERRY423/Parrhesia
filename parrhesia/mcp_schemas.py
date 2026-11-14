"""Pure-stdlib MCP tool, resource, prompt schemas and actionable repair hints."""
from __future__ import annotations

from typing import Any

from .claims import (
    CARD_FIELDS,
    DESIGN_FIELDS,
    ESTIMAND_FIELDS,
    EXECUTION_FORK_ROLES,
    STAT_FIELDS,
    TYPE_LEVELS,
)
from .contracts import (
    ACTIONS,
    ALTERNATIVE_STATUSES,
    CHECK_NAMES,
    CHECK_STATUSES,
    DOMAINS,
    ORIGINS,
    PROVENANCE,
    ROLES,
    VERDICTS,
)
from .calibration import CALIBRATION_OUTCOMES, CALIBRATION_RESOLUTION_SOURCES, COMPARISON_KINDS, COMPARISON_ASSUMPTIONS
from .effects import (
    EFFECT_BENEFICIAL_POLARITY,
    EFFECT_DIRECTIONS,
    EFFECT_METRICS,
    EFFECT_RECORD_ROLES,
    EFFECT_SCALES,
    INFERENCE_METHODS,
    COUNT_BASES,
)
from .gates import BASES, EVIDENCE_KINDS
from .triggers import (
    CASE_RELATIONS,
    CLAIM_LINEAGE_RELATIONS,
    MAX_PRIOR_CASES,
    MAX_PRIOR_CLAIM_LINKS,
    MAX_REVERSAL_TRIGGERS,
    TRIGGER_EFFECT_FIELDS,
    TRIGGER_EVIDENCE_STATUSES,
    TRIGGER_EXIT_OPERATORS,
    TRIGGER_KINDS,
    TRIGGER_OPERATORS,
)

ACTION_TOOL_NAMES: dict[str, str] = {f"parrhesia_{action}": action for action in ACTIONS}
ALL_EVIDENCE_LEVELS: tuple[str, ...] = tuple(
    dict.fromkeys(level for levels in TYPE_LEVELS.values() for level in levels)
)
CARD_STATUSES: tuple[str, ...] = (
    "reported", "checked", "unknown", "missing", "failed", "not_run", "not_applicable",
)
CONFIDENCE_LEVELS: tuple[str, ...] = ("high", "medium", "low")
DISPOSITION_CHOICES: tuple[str, ...] = ("accepted", "partial", "rejected")
DISPOSITION_RESOLUTIONS: tuple[str, ...] = ("incorporated", "disagreement")
HUMAN_DECISIONS: tuple[str, ...] = ("accept", "challenge", "defer", "pause")
HYPOTHESIS_TIMINGS: tuple[str, ...] = ("reported_prespecified", "exploratory", "unknown")
REVIEW_STATUSES: tuple[str, ...] = ("complete", "needs_split")


def _annotations(*, read_only: bool = False, idempotent: bool = False) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": False,
        "idempotentHint": idempotent,
        "openWorldHint": False,
    }


def _enum(values: tuple[str, ...] | list[str], description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "enum": list(values)}
    if description:
        schema["description"] = description
    return schema


def _str(max_length: int | None = None, description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "minLength": 1}
    if max_length is not None:
        schema["maxLength"] = max_length
    if description:
        schema["description"] = description
    return schema


def _nullable_str(max_length: int | None = None, description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"anyOf": [_str(max_length), {"type": "null"}]}
    if description:
        schema["description"] = description
    return schema


def _id_list(
    *,
    minimum: int = 0,
    maximum: int = 1000,
    description: str | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": _str(200),
        "minItems": minimum,
        "maxItems": maximum,
    }
    if description:
        schema["description"] = description
    return schema


def _obj(
    properties: dict[str, Any],
    required: list[str] | tuple[str, ...] = (),
    *,
    additional_properties: bool = False,
    description: str | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = list(required)
    if description:
        schema["description"] = description
    return schema


def _assessment_schema() -> dict[str, Any]:
    return _obj(
        {
            "status": _enum(CHECK_STATUSES),
            "reason": _str(description="Concrete basis, location, or explicit gap/inapplicability reason."),
            "evidence_ids": _id_list(),
        },
        ["status", "reason", "evidence_ids"],
    )


def _named_assessment_schema() -> dict[str, Any]:
    return _obj(
        {
            "name": _str(),
            **_assessment_schema()["properties"],
        },
        ["name", "status", "reason", "evidence_ids"],
    )


def _design_package_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            _obj(
                {
                    "family": {"type": "string", "enum": [family]},
                    "checks": _obj(
                        {key: _assessment_schema() for key in keys},
                        keys,
                    ),
                },
                ["family", "checks"],
            )
            for family, keys in DESIGN_FIELDS.items()
        ]
    }


def _statistical_report_schema() -> dict[str, Any]:
    return _obj(
        {key: _assessment_schema() for key in STAT_FIELDS},
        STAT_FIELDS,
    )


def _card_schema(kind: str, detail_keys: tuple[str, ...]) -> dict[str, Any]:
    detail_props: dict[str, Any] = {key: _str() for key in detail_keys}
    if kind == "execution":
        detail_props["claim_id"] = _str(200)
        detail_props["run_group"] = _str(200)
        detail_props["fork_role"] = _enum(EXECUTION_FORK_ROLES)
    return _obj(
        {
            "id": _str(200),
            "status": _enum(CARD_STATUSES),
            "reason": _str(),
            "evidence_ids": _id_list(),
            "details": _obj(detail_props, detail_keys),
        },
        ["id", "status", "reason", "evidence_ids", "details"],
    )


def _provenance_cards_schema() -> dict[str, Any]:
    return _obj(
        {
            kind: {
                "type": "array",
                "maxItems": 100,
                "items": _card_schema(kind, detail_keys),
            }
            for kind, detail_keys in CARD_FIELDS.items()
        },
        tuple(CARD_FIELDS),
    )


def _causal_basis_schema() -> dict[str, Any]:
    return _obj(
        {
            "design_family": _enum(tuple(DESIGN_FIELDS)),
            "estimand": _obj({key: _str() for key in ESTIMAND_FIELDS}, ESTIMAND_FIELDS),
            "assumptions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": _named_assessment_schema(),
            },
            "falsification_sensitivity": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": _named_assessment_schema(),
            },
            "assessment": _assessment_schema(),
            "necessity_test": _assessment_schema(),
            "sufficiency_test": _assessment_schema(),
        },
        [
            "design_family",
            "estimand",
            "assumptions",
            "falsification_sensitivity",
            "assessment",
            "necessity_test",
            "sufficiency_test",
        ],
    )


def _effect_record_schema() -> dict[str, Any]:
    return _obj(
        {
            "id": _str(200),
            "endpoint": _str(500),
            "endpoint_role": _enum(EFFECT_RECORD_ROLES),
            "metric": _enum(EFFECT_METRICS),
            "estimate": {"type": "number"},
            "direction": _enum(EFFECT_DIRECTIONS),
            "evidence_id": _str(200),
            "null_value": {"type": "number"},
            "ci_level": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.95},
            "ci_low": {"type": "number"},
            "ci_high": {"type": "number"},
            "p_value": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "n": {"type": "integer", "minimum": 1},
            "events": {"type": "integer", "minimum": 0},
            "decimals": {"type": "integer", "minimum": 0, "maximum": 8},
            "scale": _enum(EFFECT_SCALES, "Scale for proportion/rate metrics ('unit' or 'percentage')."),
            "beneficial_if": _enum(EFFECT_BENEFICIAL_POLARITY),
            "claim_direction": _enum(EFFECT_DIRECTIONS, "Direction asserted by the proposition; missing means alignment is unassessed."),
            "inference_method": _enum(INFERENCE_METHODS, "Wald declarations mean matching unadjusted two-sided CI and test on the stated scale; otherwise unassessed."),
            "count_basis": _enum(COUNT_BASES, "unweighted_binary asserts that n is the exact binomial denominator; otherwise no GRIM/count hard check."),
            "quote_substring": _str(2000),
            "notes": _str(4000),
        },
        ["id", "endpoint", "endpoint_role", "metric", "estimate", "direction", "evidence_id"],
    )


def _prior_claim_link_schema() -> dict[str, Any]:
    return _obj(
        {
            "prior_case_id": _str(200),
            "prior_claim_id": _str(200),
            "relation": _enum(CLAIM_LINEAGE_RELATIONS),
            "reason": _str(2000),
            "triggered_reversal_id": _str(200),
        },
        ["prior_case_id", "prior_claim_id", "relation", "reason"],
    )


def _reversal_trigger_schema() -> dict[str, Any]:
    return _obj(
        {
            "id": _str(200),
            "description": _str(1000),
            "kind": _enum(TRIGGER_KINDS),
            "target_verdict": _enum(VERDICTS),
            "target_claim_type": _enum(tuple(TYPE_LEVELS)),
            "target_evidence_level": _enum(ALL_EVIDENCE_LEVELS),
            "target_scope": _str(1000),
            "metric": _enum(EFFECT_METRICS),
            "field": _enum(TRIGGER_EFFECT_FIELDS),
            "operator": _enum(TRIGGER_OPERATORS),
            "endpoint": _str(200),
            "endpoint_role": _enum(EFFECT_RECORD_ROLES),
            "threshold": {"type": "number"},
            "band_low": {"type": "number"},
            "band_high": {"type": "number"},
            "null_value": {"type": "number"},
            "target_check": _str(200),
            "target_statuses": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": _enum(CHECK_STATUSES),
            },
            "trigger_on": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": _enum(TRIGGER_EVIDENCE_STATUSES),
            },
            "evidence_id": _str(200),
            "exit_operator": _enum(TRIGGER_EXIT_OPERATORS),
            "exit_status": {"type": "integer"},
            "fork_role": _enum(EXECUTION_FORK_ROLES),
            "target_verdicts": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": _enum(VERDICTS),
            },
            "relations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 7,
                "items": _enum(CLAIM_LINEAGE_RELATIONS),
            },
        },
        ["id", "description", "kind", "target_verdict"],
    )


def _claim_schema() -> dict[str, Any]:
    seven_check = _obj(
        {"status": _enum(CHECK_STATUSES), "reason": _str()},
        ["status", "reason"],
    )
    alternative = _obj(
        {
            "explanation": _str(),
            "status": _enum(ALTERNATIVE_STATUSES),
            "reason": _str(),
        },
        ["explanation", "status", "reason"],
    )
    return _obj(
        {
            "id": _str(200),
            "text": _str(),
            "claim_type": _enum(tuple(TYPE_LEVELS)),
            "evidence_level": _enum(ALL_EVIDENCE_LEVELS),
            "claim_basis": _enum(BASES),
            "evidence_ids": _id_list(),
            "effect": _obj({"estimate": _str(), "uncertainty": _str()}, ["estimate", "uncertainty"]),
            "scope": _str(),
            "origin": _enum(ORIGINS),
            "contribution": _str(),
            "hypothesis_id": _nullable_str(200),
            "best_current_explanation": _nullable_str(),
            "discriminating_test": _nullable_str(),
            "alternatives": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": alternative,
                "description": "1-3 competing explanations (required with min 1 in scientific domain).",
            },
            "checks": _obj({name: seven_check for name in CHECK_NAMES}, CHECK_NAMES),
            "design_packages": {
                "type": "array",
                "minItems": 0,
                "maxItems": 9,
                "items": _design_package_schema(),
            },
            "statistical_report": _statistical_report_schema(),
            "provenance_cards": _provenance_cards_schema(),
            "causal_basis": _causal_basis_schema(),
            "effect_records": {
                "type": "array",
                "minItems": 0,
                "maxItems": 50,
                "items": _effect_record_schema(),
            },
            "prior_claim_links": {
                "type": "array",
                "minItems": 0,
                "maxItems": MAX_PRIOR_CLAIM_LINKS,
                "items": _prior_claim_link_schema(),
            },
            "reversal_triggers": {
                "type": "array",
                "minItems": 0,
                "maxItems": MAX_REVERSAL_TRIGGERS,
                "items": _reversal_trigger_schema(),
            },
        },
        [
            "id",
            "text",
            "claim_type",
            "evidence_level",
            "claim_basis",
            "evidence_ids",
            "effect",
            "scope",
            "origin",
            "contribution",
            "checks",
            "design_packages",
            "statistical_report",
            "provenance_cards",
        ],
    )


def _identity_schema() -> dict[str, Any]:
    return _obj(
        {"context_id": _str(200), "model": _str(200)},
        ["context_id", "model"],
    )


def _isolation_attestation_schema() -> dict[str, Any]:
    return _obj(
        {
            "history_inheritance": _str(200),
            "memory_access": _str(200),
            "host_surface": _str(200),
        },
        description="Caller-reported isolation metadata (not independently verified by the engine).",
    )


def _finding_schema() -> dict[str, Any]:
    return _obj(
        {
            "id": _str(200),
            "claim_id": _str(200),
            "evidence_ids": _id_list(),
            "issue": _str(),
            "proposed_claim_type": _enum(tuple(TYPE_LEVELS)),
            "proposed_evidence_level": _enum(ALL_EVIDENCE_LEVELS),
            "proposed_scope": _str(),
            "proposed_claim_basis": _enum(BASES),
            "proposed_text": _str(),
            "decision_impact": _str(),
        },
        [
            "id",
            "claim_id",
            "evidence_ids",
            "issue",
            "proposed_claim_type",
            "proposed_evidence_level",
            "proposed_scope",
            "proposed_claim_basis",
            "proposed_text",
            "decision_impact",
        ],
    )


def _claim_stance_schema() -> dict[str, Any]:
    return _obj(
        {
            "claim_id": _str(200),
            "stance": _enum(VERDICTS),
            "rationale": _str(),
            "evidence_ids": _id_list(),
            "condition": _str(),
        },
        ["claim_id", "stance", "rationale", "evidence_ids"],
    )


def _decision_schema() -> dict[str, Any]:
    return _obj(
        {
            "claim_id": _str(200),
            "verdict": _enum(VERDICTS),
            "claim_type": _enum(tuple(TYPE_LEVELS)),
            "evidence_level": _enum(ALL_EVIDENCE_LEVELS),
            "claim_basis": _enum(BASES),
            "scope": _str(),
            "revised_text": _str(),
            "rationale": _str(),
            "evidence_ids": _id_list(),
            "confidence": _enum(CONFIDENCE_LEVELS),
            "confidence_reason": _str(),
            "boundary": _str(),
            "reversal_condition": _str(),
            "condition": _str(),
            "forecast_probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reversal_triggers": {
                "type": "array",
                "minItems": 0,
                "maxItems": MAX_REVERSAL_TRIGGERS,
                "items": _reversal_trigger_schema(),
            },
        },
        [
            "claim_id",
            "verdict",
            "claim_type",
            "evidence_level",
            "claim_basis",
            "scope",
            "revised_text",
            "rationale",
            "evidence_ids",
            "confidence",
            "confidence_reason",
            "boundary",
            "reversal_condition",
        ],
    )


def _disposition_schema() -> dict[str, Any]:
    return _obj(
        {
            "finding_id": _str(200),
            "claim_id": _str(200),
            "disposition": _enum(DISPOSITION_CHOICES),
            "reason": _str(),
            "resolution": _enum(DISPOSITION_RESOLUTIONS),
            "condition": _str(),
            "revised_text_quote": _str(),
            "disagreement": _str(),
        },
        ["finding_id", "claim_id", "disposition", "reason", "resolution"],
    )


def _packet_output_schema(*, adjudication: bool = False) -> dict[str, Any]:
    props: dict[str, Any] = {
        "input_digest": {"type": "string"},
        "created_at": {"type": "string"},
        "case_id": {"type": "string"},
        "question": {"type": "string"},
        "domain": _enum(DOMAINS),
        "draft": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "claims": {"type": "array", "items": {"type": "object"}},
        "evidence": {"type": "array", "items": {"type": "object"}},
        "hypotheses": {"type": "array", "items": {"type": "object"}},
        "schema_version": {"type": "integer"},
        "gate_version": {"type": "integer"},
        "blind": {"type": "boolean"},
        "revision_id": {"type": "string"},
        "instructions": {"type": "string"},
        "integrity_boundary": {"type": "string"},
        "check_ceilings": {"type": "object"},
    }
    if adjudication:
        props["adjudication_id"] = {"type": "string"}
        props["reviews"] = {"type": "object"}
        required = [
            "adjudication_id", "input_digest", "created_at", "case_id",
            "question", "domain", "draft", "claims", "evidence", "hypotheses",
            "revision_id", "reviews", "integrity_boundary", "instructions",
        ]
    else:
        props["packet_id"] = {"type": "string"}
        props["role"] = _enum(ROLES)
        props["independence"] = {"type": "string"}
        required = [
            "packet_id", "role", "created_at", "input_digest", "case_id",
            "question", "domain", "draft", "claims", "evidence", "hypotheses",
            "revision_id", "instructions", "independence", "integrity_boundary",
        ]
    return _obj(props, required, additional_properties=True)


def _action_specs() -> list[dict[str, Any]]:
    case_id_prop = _str(200, "Target case ID in the active workspace.")
    return [
        {
            "name": "parrhesia_create_case",
            "description": "Create a new v2 claim-review case in draft state inside the active workspace.",
            "inputSchema": _obj(
                {
                    "question": _str(200_000),
                    "draft": _str(1_000_000),
                    "domain": _enum(DOMAINS, "Case domain ('scientific' default or 'general')."),
                    "writer_context_id": _nullable_str(200),
                    "schema_version": {"type": "integer", "enum": [2], "default": 2},
                    "blind": {"type": "boolean", "default": True},
                    "prior_case_ids": _id_list(minimum=0, maximum=MAX_PRIOR_CASES, description="Optional prior case IDs in the workspace linked to this follow-up case."),
                    "supersedes_case_id": _str(200, "Optional prior case ID superseded by this case."),
                    "case_relation": _enum(CASE_RELATIONS, "Optional longitudinal case relation."),
                },
                ["question", "draft"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "created_at": {"type": "string"},
                    "schema_version": {"type": "integer"},
                    "gate_version": {"type": "integer"},
                    "blind": {"type": "boolean"},
                    "prior_case_ids": _id_list(minimum=0, maximum=MAX_PRIOR_CASES),
                    "supersedes_case_id": {"type": "string"},
                    "case_relation": _enum(CASE_RELATIONS),
                },
                ["case_id", "state", "created_at", "schema_version"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_register_evidence",
            "description": "Snapshot a workspace-relative regular file, hash its bytes, and validate optional verbatim quote anchors.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "path": _str(2000, "Workspace-relative file path (no symlinks, traversal, or .parrhesia)."),
                    "kind": _enum(EVIDENCE_KINDS),
                    "provenance": _enum(PROVENANCE),
                    "label": _str(),
                    "quote": _nullable_str(),
                    "location": _nullable_str(),
                    "unread_content_ack": {"type": "boolean", "default": False},
                    "excerpt_anchors": {
                        "type": "array",
                        "items": _str(),
                        "minItems": 1,
                        "maxItems": 8,
                    },
                    "derived_from_evidence_ids": _id_list(),
                    "derivation_step": _str(2000),
                },
                ["case_id", "path", "provenance", "kind"],
            ),
            "outputSchema": _obj(
                {
                    "evidence_id": {"type": "string"},
                    "path": {"type": "string"},
                    "label": {"type": "string"},
                    "provenance": _enum(PROVENANCE),
                    "provenance_basis": {"type": "string"},
                    "quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "location": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "sha256": {"type": "string"},
                    "size": {"type": "integer"},
                    "captured_at": {"type": "string"},
                    "kind": _enum(EVIDENCE_KINDS),
                    "content_read_status": {"type": "string"},
                    "unread_content_ack": {"type": "boolean"},
                    "excerpt_anchors": {"type": "array", "items": {"type": "string"}},
                    "derived_from_evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "derivation_step": {"type": "string"},
                },
                ["evidence_id", "path", "label", "provenance", "provenance_basis", "sha256", "size", "captured_at"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_register_hypothesis",
            "description": "Log a hypothesis statement and self-reported timing basis in a draft case.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "statement": _str(),
                    "timing_basis": _enum(HYPOTHESIS_TIMINGS),
                    "source_evidence_id": _nullable_str(200),
                },
                ["case_id", "statement", "timing_basis"],
            ),
            "outputSchema": _obj(
                {
                    "hypothesis_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "timing_basis": _enum(HYPOTHESIS_TIMINGS),
                    "source_evidence_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "recorded_at": {"type": "string"},
                    "timing_verification": {"type": "string"},
                },
                ["hypothesis_id", "statement", "timing_basis", "source_evidence_id", "recorded_at", "timing_verification"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_scaffold_claim",
            "description": "Read-only helper generating a schema-valid v2 claim template and check_ceilings preview.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "claim_id": _str(200),
                    "text": _str(),
                    "scope": _str(),
                    "domain": _enum(DOMAINS),
                    "claim_type": _enum(tuple(TYPE_LEVELS)),
                    "evidence_level": _enum(ALL_EVIDENCE_LEVELS),
                    "claim_basis": _enum(BASES),
                    "design_families": {
                        "type": "array",
                        "items": _enum(tuple(DESIGN_FIELDS)),
                        "minItems": 0,
                        "maxItems": 9,
                    },
                    "include_causal_basis": {"type": "boolean"},
                    "include_effect_records": {"type": "boolean"},
                    "include_reversal_triggers": {"type": "boolean"},
                    "include_prior_claim_links": {"type": "boolean"},
                },
            ),
            "outputSchema": _obj(
                {
                    "claim": {"type": "object"},
                    "check_ceilings": {"type": "object"},
                    "case_id": {"type": "string"},
                },
                ["claim", "check_ceilings"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_set_ledger",
            "description": "Set the draft case claim ledger (1-100 v2 claims including design_packages, statistical_report, provenance_cards, and optional effect_records).",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "claims": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 100,
                        "items": _claim_schema(),
                    },
                },
                ["case_id", "claims"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "claim_count": {"type": "integer"},
                },
                ["case_id", "state", "claim_count"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_freeze",
            "description": "Freeze the draft case, evidence, hypotheses, and claim ledger into an immutable revision and generate both isolated reviewer packets.",
            "inputSchema": _obj({"case_id": case_id_prop}, ["case_id"]),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "revision_id": {"type": "string"},
                    "input_digest": {"type": "string"},
                    "packet_ids": _obj(
                        {role: {"type": "string"} for role in ROLES},
                        ROLES,
                    ),
                },
                ["case_id", "state", "revision_id", "input_digest", "packet_ids"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_review_packet",
            "description": "Read the frozen, role-isolated review packet for 'overclaim' or 'underclaim'. Respects case-level blind filtering.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "role": _enum(ROLES),
                    "blind": {"type": "boolean", "description": "Legacy v1 only; rejected on gated v2 cases."},
                },
                ["case_id", "role"],
            ),
            "outputSchema": _packet_output_schema(adjudication=False),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_submit_review",
            "description": "Submit a final, immutable role review (0-3 findings, per-claim stances, unread evidence acknowledgment, and optional isolation_attestation).",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "role": _enum(ROLES),
                    "packet_id": _str(200),
                    "input_digest": _str(200),
                    "reviewer": _identity_schema(),
                    "covered_claim_ids": _id_list(),
                    "findings": {
                        "type": "array",
                        "minItems": 0,
                        "maxItems": 3,
                        "items": _finding_schema(),
                    },
                    "claim_stances": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 100,
                        "items": _claim_stance_schema(),
                    },
                    "unread_evidence_ids": _id_list(),
                    "review_status": _enum(REVIEW_STATUSES),
                    "isolation_attestation": _isolation_attestation_schema(),
                },
                [
                    "case_id",
                    "role",
                    "packet_id",
                    "input_digest",
                    "reviewer",
                    "covered_claim_ids",
                    "findings",
                    "claim_stances",
                    "unread_evidence_ids",
                ],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "review": {"type": "object"},
                    "symmetry_audit": {"type": "object"},
                },
                ["case_id", "state", "review", "symmetry_audit"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_adjudication_packet",
            "description": "Create (on first call) and retrieve the adjudication packet binding the frozen case and both reviews.",
            "inputSchema": _obj({"case_id": case_id_prop}, ["case_id"]),
            "outputSchema": _packet_output_schema(adjudication=True),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_submit_adjudication",
            "description": "Submit explicit claim decisions, finding dispositions, unread evidence acknowledgments, and optional isolation_attestation.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "adjudication_id": _str(200),
                    "input_digest": _str(200),
                    "adjudicator": _identity_schema(),
                    "decisions": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 100,
                        "items": _decision_schema(),
                    },
                    "dispositions": {
                        "type": "array",
                        "minItems": 0,
                        "maxItems": 6,
                        "items": _disposition_schema(),
                    },
                    "unread_evidence_ids": _id_list(),
                    "isolation_attestation": _isolation_attestation_schema(),
                },
                [
                    "case_id",
                    "adjudication_id",
                    "input_digest",
                    "adjudicator",
                    "decisions",
                    "dispositions",
                    "unread_evidence_ids",
                ],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "adjudication": {"type": "object"},
                    "symmetry_audit": {"type": "object"},
                },
                ["case_id", "state", "adjudication", "symmetry_audit"],
                additional_properties=True,
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_verify",
            "description": "Verify evidence snapshot hashes, workspace files, quote anchors, lineage, event hash chain, and effect records; records a durable verify event in SQLite.",
            "inputSchema": _obj({"case_id": case_id_prop}, ["case_id"]),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "checked_at": {"type": "string"},
                    "status": _enum(("pass", "unverified", "blocked")),
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "evidence_chains": {"type": "array", "items": {"type": "object"}},
                    "scientific_validity": {"type": "string"},
                    "scope": {"type": "string"},
                    "symmetry_audit": {"type": "object"},
                    "event_chain": {"type": "object"},
                    "event_chain_status": {"type": "string"},
                    "effect_checks": {"type": "object"},
                },
                ["case_id", "checked_at", "status", "evidence", "evidence_chains", "scientific_validity", "scope", "event_chain", "event_chain_status"],
                additional_properties=True,
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_get_case",
            "description": "Read-only author/operator audit view of a case document, its SQLite event log, and event chain status (never route to isolated reviewers).",
            "inputSchema": _obj({"case_id": case_id_prop}, ["case_id"]),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "schema_version": {"type": "integer"},
                    "state": {"type": "string"},
                    "created_at": {"type": "string"},
                    "question": {"type": "string"},
                    "draft": {"type": "string"},
                    "domain": _enum(DOMAINS),
                    "writer_context_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "hypotheses": {"type": "array", "items": {"type": "object"}},
                    "claims": {"type": "array", "items": {"type": "object"}},
                    "reviews": {"type": "object"},
                    "human_decisions": {"type": "array", "items": {"type": "object"}},
                    "scientific_validity": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "object"}},
                    "event_chain": {"type": "object"},
                    "event_chain_status": {"type": "string"},
                },
                ["case_id", "state", "question", "draft", "domain", "evidence", "hypotheses", "claims", "reviews", "human_decisions", "events", "event_chain", "event_chain_status"],
                additional_properties=True,
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_export",
            "description": "Verify evidence and event chain integrity and atomically materialize an immutable Markdown adjudication report.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "path": _str(2000, "Optional workspace-relative .md path (defaults to exports/<case_id>.md); never overwrites."),
                },
                ["case_id"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "path": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "sha256": {"type": "string"},
                    "prepared_at": {"type": "string"},
                    "verification_digest": {"type": "string"},
                    "exported_at": {"type": "string"},
                    "verification": {"type": "object"},
                },
                ["case_id", "state", "path", "relative_path", "sha256", "prepared_at", "verification_digest", "exported_at", "verification"],
                additional_properties=True,
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_record_human_decision",
            "description": "Append an explicit human decision event ('accept', 'challenge', 'defer', or 'pause') to the case log.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "decision": _enum(HUMAN_DECISIONS),
                    "responsible_human": _str(200),
                    "reason": _str(),
                },
                ["case_id", "decision", "responsible_human", "reason"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "human_decision": _obj(
                        {
                            "decision": _enum(HUMAN_DECISIONS),
                            "responsible_human": {"type": "string"},
                            "reason": {"type": "string"},
                            "recorded_at": {"type": "string"},
                            "identity_basis": {"type": "string"},
                            "scientific_validity": {"type": "string"},
                        },
                        ["decision", "responsible_human", "reason", "recorded_at", "identity_basis", "scientific_validity"],
                    ),
                },
                ["case_id", "state", "human_decision"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_claim_graph",
            "description": "Read-only query constructing the longitudinal cross-case claim graph DAG, verdict trajectories, and active standing.",
            "inputSchema": _obj(
                {
                    "case_id": _str(200),
                    "claim_id": _str(200),
                },
            ),
            "outputSchema": _obj(
                {
                    "filter": {"type": "object"},
                    "case_nodes": {"type": "array", "items": {"type": "object"}},
                    "case_edges": {"type": "array", "items": {"type": "object"}},
                    "claim_nodes": {"type": "array", "items": {"type": "object"}},
                    "claim_edges": {"type": "array", "items": {"type": "object"}},
                    "chains": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                    "cycle_detected": {"type": "boolean"},
                },
                ["filter", "case_nodes", "case_edges", "claim_nodes", "claim_edges", "chains", "cycle_detected"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_evaluate_triggers",
            "description": "Read-only deterministic evaluation of a case's executable reversal triggers against another case, inline observations, or live workspace state.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "against_case_id": _str(200),
                    "observations": {"type": "object", "additionalProperties": True},
                },
                ["case_id"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "evaluation_mode": {"type": "string"},
                    "against_case_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "total_triggers": {"type": "integer"},
                    "fired_count": {"type": "integer"},
                    "unfired_count": {"type": "integer"},
                    "pending_data_count": {"type": "integer"},
                    "fired_trigger_ids": {"type": "array", "items": {"type": "string"}},
                    "claim_evaluations": {"type": "array", "items": {"type": "object"}},
                },
                [
                    "case_id",
                    "evaluation_mode",
                    "against_case_id",
                    "total_triggers",
                    "fired_count",
                    "unfired_count",
                    "pending_data_count",
                    "fired_trigger_ids",
                    "claim_evaluations",
                ],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_record_calibration_outcome",
            "description": "Append an immutable post-adjudication calibration outcome event for a claim without rewriting frozen input or adjudication digests.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "claim_id": _str(200),
                    "outcome": _enum(CALIBRATION_OUTCOMES),
                    "outcome_score": {"anyOf": [{"type": "number", "minimum": 0.0, "maximum": 1.0}, {"type": "null"}]},
                    "resolution_source": _enum(CALIBRATION_RESOLUTION_SOURCES),
                    "follow_up_case_id": _str(200),
                    "follow_up_claim_id": _str(200),
                    "evidence_id": _str(200),
                    "observed_estimate": {"type": "number"},
                    "observed_ci_low": {"type": "number"},
                    "observed_ci_high": {"type": "number"},
                    "effect_record_id": _str(200, "Original effect record identifying the endpoint for an observed estimate."),
                    "comparison_kind": _enum(COMPARISON_KINDS),
                    "comparison_assumption": _enum(COMPARISON_ASSUMPTIONS),
                    "estimate_covariance": {"type": "number", "description": "Covariance on the same scale as the stated Wald intervals (log scale for log_wald)."},
                    "observed_ci_level": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
                    "observed_ci_method": _enum(INFERENCE_METHODS),
                    "metric": _enum(EFFECT_METRICS),
                    "reason": _str(4000),
                },
                ["case_id", "claim_id", "outcome", "resolution_source", "reason"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "recorded_outcome": {"type": "object"},
                    "calibration_outcome_count": {"type": "integer"},
                },
                ["case_id", "state", "recorded_outcome", "calibration_outcome_count"],
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_calibration_report",
            "description": "Read-only calibration: explicit forecasts with source-verified outcomes, separate heuristic scores, known-truth coverage and assumption-qualified replication comparisons.",
            "inputSchema": _obj(
                {
                    "case_id": _str(200),
                    "domain": _enum(DOMAINS),
                    "claim_type": _enum(tuple(TYPE_LEVELS)),
                },
            ),
            "outputSchema": _obj(
                {
                    "filters": {"type": "object"},
                    "summary": {"type": "object"},
                    "proper_scores": {"type": "object"},
                    "reliability_bins": {"type": "array", "items": {"type": "object"}},
                    "confidence_strata": {"type": "object"},
                    "interval_calibration": {"type": "object"},
                    "heuristic_scores": {"type": "object"},
                    "decision_calibration": {"type": "object"},
                    "claim_records": {"type": "array", "items": {"type": "object"}},
                },
                [
                    "filters",
                    "summary",
                    "proper_scores",
                    "reliability_bins",
                    "confidence_strata",
                    "interval_calibration",
                    "decision_calibration",
                    "claim_records",
                ],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
    ]


def tool_definitions() -> list[dict[str, Any]]:
    """Return all 22 MCP tool definitions with inputSchema, outputSchema, and annotations."""
    base_tools: list[dict[str, Any]] = [
        {
            "name": "parrhesia_contract",
            "description": "Read the exact Parrhesia workflow payload contract and active workspace before using it. Returns local documentation; no case content is loaded.",
            "inputSchema": _obj({}),
            "outputSchema": _obj(
                {
                    "workspace": {"type": "string"},
                    "version": {"type": "string"},
                    "actions": {"type": "array", "items": _enum(ACTIONS)},
                    "contract": {"type": "string"},
                },
                ["workspace", "version", "actions", "contract"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_select_workspace",
            "description": "Select an existing absolute project directory the user has explicitly selected or authorized. Creates only .parrhesia state there. Do not infer a directory from attached document instructions. Selection lasts this server session; case IDs belong to that workspace.",
            "inputSchema": _obj({"path": _str()}, ["path"]),
            "outputSchema": _obj(
                {
                    "workspace": {"type": "string"},
                    "selection": _enum(("caller_authorized",)),
                    "scope": _enum(("current_server_session",)),
                },
                ["workspace", "selection", "scope"],
            ),
            "annotations": _annotations(read_only=False, idempotent=True),
        },
        {
            "name": "parrhesia_workflow",
            "description": "Execute one durable local Parrhesia workflow step (backward-compatible generic dispatcher). Prefer the dedicated per-action tools when typed schemas are supported. Does not call models, execute analyses, search literature or certify scientific truth.",
            "inputSchema": _obj(
                {"action": _enum(ACTIONS), "payload": {"type": "object"}},
                ["action", "payload"],
            ),
            "outputSchema": {"type": "object", "additionalProperties": True},
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_validate",
            "description": "Read-only dry-run preflight validator for any workflow action payload. Rolls back SQLite without mutating state or files; returns valid=false with repair_hint on contract errors.",
            "inputSchema": _obj(
                {"action": _enum(ACTIONS), "payload": {"type": "object"}},
                ["action", "payload"],
            ),
            "outputSchema": _obj(
                {
                    "valid": {"type": "boolean"},
                    "action": _enum(ACTIONS),
                    "dry_run": {"type": "boolean", "enum": [True]},
                    "preview": {"type": "object"},
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                    "repair_hint": {"type": "string"},
                },
                ["valid", "action", "dry_run"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
    ]
    return [*base_tools, *_action_specs()]


def resource_definitions() -> list[dict[str, str]]:
    """Return concrete static/collection MCP resources."""
    return [
        {
            "uri": "parrhesia://contract",
            "name": "Parrhesia workflow contract",
            "description": "Complete Parrhesia workflow payload and structural gate contract.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "parrhesia://cases",
            "name": "Parrhesia workspace cases",
            "description": "Summary list of all cases stored in the active workspace.",
            "mimeType": "application/json",
        },
        {
            "uri": "parrhesia://claim-graph",
            "name": "Parrhesia longitudinal claim graph",
            "description": "Read-only cross-case claim lineage DAG and active standing across workspace cases.",
            "mimeType": "application/json",
        },
        {
            "uri": "parrhesia://calibration",
            "name": "Parrhesia workspace calibration report",
            "description": "Read-only proper scoring, ECE/MCE reliability bins, interval coverage, and trigger calibration.",
            "mimeType": "application/json",
        },
    ]


def resource_template_definitions() -> list[dict[str, str]]:
    """Return dynamic MCP resource URI templates."""
    return [
        {
            "uriTemplate": "parrhesia://cases",
            "name": "Workspace case list",
            "description": "Summary list of all cases stored in the active workspace.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://claim-graph",
            "name": "Longitudinal claim graph",
            "description": "Cross-case claim lineage DAG and verdict/standing trajectories.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://calibration",
            "name": "Workspace calibration report",
            "description": "Measurable calibration metrics across adjudicated cases and outcomes.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}",
            "name": "Case audit document",
            "description": "Read-only durable case state, claims, reviews, adjudication, and event chain.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}/ceilings",
            "name": "Case claim check ceilings",
            "description": "Read-only type-local check ceilings and effect_records summary per claim.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}/triggers",
            "name": "Case executable reversal triggers",
            "description": "Read-only evaluation of a case's structured reversal triggers against live workspace state.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "parrhesia://cases/{case_id}/packet/{role}",
            "name": "Isolated role packet",
            "description": "Read-only isolated packet for role in overclaim, underclaim, or adjudication.",
            "mimeType": "application/json",
        },
    ]


def prompt_definitions() -> list[dict[str, Any]]:
    """Return MCP prompt definitions for isolated review and adjudication roles."""
    case_arg = {
        "name": "case_id",
        "description": "Optional frozen/reviewed case ID to inject the live isolated role packet.",
        "required": False,
    }
    return [
        {
            "name": "parrhesia_review_overclaim",
            "description": "Overclaim reviewer instructions and optional live isolated overclaim packet.",
            "arguments": [case_arg],
        },
        {
            "name": "parrhesia_review_underclaim",
            "description": "Underclaim reviewer instructions and optional live isolated underclaim packet.",
            "arguments": [case_arg],
        },
        {
            "name": "parrhesia_adjudicate",
            "description": "Adjudicator instructions and optional live adjudication packet (requires built packet).",
            "arguments": [case_arg],
        },
    ]


_REPAIR_HINTS: dict[str, str] = {
    "invalid_state": (
        "Check the case's current state via parrhesia_get_case or parrhesia://cases/{case_id}. "
        "Draft edits require state='draft' (create a new case via parrhesia_create_case if already frozen); "
        "adjudication requires state='reviewed' (both overclaim and underclaim reviews submitted); "
        "export requires state='adjudicated' or 'export_pending'."
    ),
    "missing_field": (
        "Add every missing required field listed in the error message. Call parrhesia_scaffold_claim for a full v2 claim template, "
        "or inspect this tool's inputSchema / parrhesia_contract."
    ),
    "unknown_field": (
        "Remove the unsupported fields named in the error message; inspect this tool's inputSchema or parrhesia_contract for exact allowed keys."
    ),
    "invalid_type": (
        "Fix the field data type reported in the error message (for numeric effect_records fields, pass JSON numbers rather than strings or booleans)."
    ),
    "invalid_value": (
        "Replace the rejected value with a non-empty string or an allowed enum value defined in this tool's inputSchema / parrhesia_contract."
    ),
    "invalid_json": "Ensure the JSON payload contains only finite numbers (no NaN or Infinity) and valid JSON values.",
    "too_large": "Shorten oversized fields or register large artifacts as separate files within documented size limits.",
    "duplicate_id": (
        "Ensure all IDs in the submitted array (claim.id, finding.id, provenance card id, effect_record.id, or design_packages.family) are unique."
    ),
    "invalid_request": (
        "Check tool arguments against its inputSchema: parrhesia_contract accepts {}, "
        "parrhesia_select_workspace requires an existing absolute directory 'path', and action tools require valid typed fields."
    ),
    "invalid_workspace": "Pass an existing absolute directory path in parrhesia_select_workspace.",
    "unknown_case": (
        "Verify case_id against parrhesia://cases, switch to the correct project directory via parrhesia_select_workspace, "
        "or create a new case with parrhesia_create_case."
    ),
    "legacy_creation_disabled": "Omit schema_version or set schema_version=2 on parrhesia_create_case; schema_version=1 creation is disabled.",
    "unsupported_contract_version": "Create a new v2 case via parrhesia_create_case; unsupported stored schema/gate versions cannot be upgraded in place.",
    "case_level_blind": "Omit 'blind' when calling parrhesia_review_packet; case blindness is frozen at parrhesia_create_case.",
    "human_paused": (
        "A human 'pause' hold is active. Call parrhesia_record_human_decision with decision='accept', "
        "responsible_human, and reason before performing workflow mutations."
    ),
    "human_hold": (
        "An active human hold ('challenge', 'defer', or 'pause') blocks export. "
        "Record an explicit parrhesia_record_human_decision with decision='accept' before retrying export."
    ),
    "missing_ledger": "Call parrhesia_set_ledger with 1 to 100 schema-valid claims before calling parrhesia_freeze.",
    "missing_packet": "Call parrhesia_adjudication_packet with case_id first to build the packet and obtain adjudication_id and input_digest.",
    "stale_packet": (
        "Re-read the packet via parrhesia_review_packet or parrhesia_adjudication_packet and supply its exact packet_id/adjudication_id and input_digest."
    ),
    "duplicate_review": "Each role ('overclaim' and 'underclaim') can submit only once per case; create a new case to revise.",
    "context_reuse": (
        "Use a distinct reviewer/adjudicator context_id that does not match writer_context_id or the other reviewer's context_id."
    ),
    "unsafe_path": (
        "Pass a workspace-relative regular file path using forward slashes with no '..', drive letters, symlinks/reparse points, or '.parrhesia' components."
    ),
    "invalid_source": "Point 'path' to an existing regular file inside the workspace (not a directory or symlink).",
    "source_unreadable": "Verify the target file exists and is readable within the workspace.",
    "invalid_quote": (
        "Provide an exact, unique UTF-8 substring from the source file with at least 12 visible non-whitespace units (>= 6 CJK characters)."
    ),
    "conflicting_provenance": "When evidence kind is 'synthetic', set provenance='synthetic'.",
    "unread_ack_required": (
        "Inspect source_text_status for every evidence entry in the packet and include all IDs where source_text_status != 'complete' in unread_evidence_ids "
        "(or set unread_content_ack=true when registering binary files)."
    ),
    "unread_positive_evidence": (
        "Positive citations require readable text or a quote-anchored >128 KiB window; register a unique quote on the text source "
        "or cite a readable verified summary derived via derived_from_evidence_ids."
    ),
    "unanchored_positive_evidence": (
        "Register both a unique verbatim quote (>= 12 visible non-whitespace units) and a concrete non-placeholder location (e.g. 'Table 2, L14-L18') on the cited evidence."
    ),
    "unlinked_evidence_quote": (
        "Register a quote on the cited evidence that shares quantitative figures, domain terminology, or checked provenance-card locators with the claim."
    ),
    "unanchored_effect_estimate": (
        "Ensure the numeric estimates and confidence intervals stated in claim.effect and revised_text appear literally in the cited evidence quote or snapshot window."
    ),
    "unanchored_effect_record": (
        "Verify that every effect_record's estimate (and ci_low, ci_high, p_value, or quote_substring when provided) appears literally in the referenced evidence_id's "
        "registered quote or snapshot text, or register a quote/excerpt_anchors window containing those numbers."
    ),
    "primary_effect_crosses_null": (
        "The primary/benchmark interval includes null and cannot establish the explicitly asserted claim_direction. "
        "Use insufficient_evidence for an unestablished directional claim; a descriptive null result is different from a directional effect or equivalence. Do not change metadata merely to bypass the check."
    ),
    "effect_direction_mismatch": (
        "Align effect_record.direction ('benefit'/'harm') with estimate relative to null_value and beneficial_if ('below_null'/'above_null'), "
        "and any explicitly declared claim_direction. A supported harm proposition is valid; do not relabel harm as benefit."
    ),
    "effect_interval_inconsistent": "Provide both ci_low and ci_high (or omit both) and ensure ci_low <= estimate <= ci_high.",
    "invalid_ratio_effect": "Ratio metrics (HR, OR, RR, IRR) require strictly positive estimate > 0, ci_low > 0, ci_high > 0, and null_value > 0.",
    "effect_pvalue_ci_mismatch": (
        "Check p_value against the explicitly declared matching two-sided Wald/log-Wald CI/test pair, including scale, null and rounding. "
        "Use the actual source method; unsupported/unknown methods are recorded as unassessed, never silently verified."
    ),
    "effect_granularity_mismatch": (
        "Verify events, n, scale ('unit' vs 'percentage'), and decimals so estimate matches events/n (multiplied by 100 when scale='percentage')."
    ),
    "effect_grim_inconsistent": (
        "Check estimate, n, scale, and decimals: no integer count k/n reproduces the reported proportion at the specified decimal precision."
    ),
    "uncited_primary_effect": (
        "Include the evidence_id(s) backing the supporting primary/benchmark effect_records inside decision.evidence_ids."
    ),
    "selective_execution_omission": (
        "Account for every SQLite record_exec run for this case/claim inside claim.provenance_cards.execution with its registered evidence_id, "
        "exit_status, and fork_role rather than omitting runs or leaving cards as 'not_run'."
    ),
    "unadjusted_execution_multiplicity": (
        "Multiple execution forks exist; set statistical_report.multiplicity_selection and checks.multiplicity to 'pass' with substantive reasons "
        "and cite their backing evidence_ids in the positive decision."
    ),
    "critical_check_ceiling": (
        "Read parrhesia://cases/{case_id}/ceilings to inspect blocked levels. Either downgrade evidence_level/verdict to an allowed level, "
        "or supply evidenced passing design/statistical checks and valid provenance_cards in a new case."
    ),
    "uncited_check_evidence": (
        "Add all evidence_ids cited by required passing design_packages and statistical_report checks into decision.evidence_ids (or stance.evidence_ids)."
    ),
    "uncited_checked_card": (
        "Add the evidence_ids from every provenance card with status='checked' into decision.evidence_ids (or stance.evidence_ids)."
    ),
    "missing_card_evidence": (
        "Supply at least one registered evidence_id on every provenance card marked status='checked', or change its status to 'reported' or 'unknown'."
    ),
    "missing_causal_basis": (
        "Include a complete causal_basis record (design_family, estimand, assumptions, falsification_sensitivity, assessment, necessity_test, sufficiency_test) "
        "for causal_effect, necessity, sufficiency, or mechanism x causal_chain_tested claims."
    ),
    "missing_design": "Ensure causal_basis.design_family matches one of the families registered in claim.design_packages.",
    "causal_identification_gap": (
        "For positive causal verdicts, fill concrete non-placeholder estimand fields and set causal_basis assessment, assumptions, required falsification_sensitivity, "
        "and matching necessity/sufficiency tests to 'pass' with substantive reasons and cited evidence_ids."
    ),
    "missing_causal_citation": "Include every evidence_id referenced by causal_basis assessments in decision.evidence_ids (or stance.evidence_ids).",
    "unsupported_evidence_level": (
        "Levels 'unassessed', 'unidentified', and 'conjectured' cannot receive 'supported' or 'partially_supported'; record 'insufficient_evidence' or 'unsupported'."
    ),
    "basis_mismatch": (
        "Reserve claim_basis='formal' exclusively for claim_type='theory', and limit positive claim_basis='synthetic' claims to description or computational."
    ),
    "basis_revision_required": "When changing claim_basis in a positive decision, update both revised_text and scope to reflect the new basis.",
    "synthetic_empirical_support": (
        "Evidence with provenance='synthetic' or kind='synthetic' (including derived ancestors) cannot support empirical/formal positives; "
        "cite non-synthetic evidence or reclassify within synthetic bounds."
    ),
    "synthetic_ceiling": "Positive synthetic decisions are capped at description x recorded or computational x benchmark_measured.",
    "incompatible_evidence_kind": (
        "Cite evidence whose registered kind supports the chosen claim_type x evidence_level (observational evidence supports causal_effect only via "
        "partially_supported with an explicit condition, complete causal_basis, and passing observational checks)."
    ),
    "invalid_lineage": "Remove circular derived_from_evidence_ids links so evidence derivation forms an acyclic DAG.",
    "unknown_reference": "Reference only registered evidence_ids belonging to this case (and to the specific claim when required).",
    "unknown_evidence": "Register the referenced source via parrhesia_register_evidence before linking it.",
    "unknown_hypothesis": "Register the hypothesis via parrhesia_register_hypothesis before linking its hypothesis_id in set_ledger.",
    "unknown_claim": "Reference only claim IDs defined in the frozen ledger (inspect parrhesia://cases/{case_id}).",
    "unknown_finding": "Reference only finding IDs submitted by the overclaim/underclaim reviews.",
    "missing_timing_source": (
        "Register the protocol/preregistration source via parrhesia_register_evidence, register a reported_prespecified hypothesis citing it, "
        "and link that hypothesis_id on the prespecified claim."
    ),
    "conflicting_origin": "An exploratory claim cannot link to a reported_prespecified hypothesis; either mark origin='prespecified' or register an exploratory hypothesis.",
    "incomplete_coverage": "List every frozen claim ID exactly once in covered_claim_ids.",
    "incomplete_stances": "Provide exactly one claim_stances entry for every frozen claim ID.",
    "missing_stance_condition": "Provide a concrete, non-placeholder 'condition' whenever stance='partially_supported', and avoid placeholder condition text.",
    "incomplete_decisions": "Provide exactly one decision entry for every frozen claim ID.",
    "incomplete_dispositions": "Provide exactly one disposition entry for every finding submitted across both reviews.",
    "invalid_condition": "Supply a concrete, non-placeholder 'condition' whenever verdict='partially_supported' or disposition='partial'.",
    "finding_decision_mismatch": "Set disposition.claim_id to match finding.claim_id and the corresponding decision.claim_id.",
    "missing_disagreement": "Provide a substantive non-empty 'disagreement' explanation when resolution='disagreement'.",
    "contradictory_resolution": (
        "Use resolution='disagreement' with 'disagreement' (and no revised_text_quote) when rejecting or declining a finding; "
        "omit 'disagreement' when resolution='incorporated'."
    ),
    "finding_not_incorporated": (
        "For resolution='incorporated', revise decision.revised_text to adopt the finding's issue-linked replacement terms and quote a unique >=12-unit substring "
        "present in both proposed_text and revised_text (not original.text), or switch to resolution='disagreement' with explicit explanation."
    ),
    "export_exists": "Choose a new workspace-relative .md path that does not already exist; parrhesia_export never overwrites files.",
    "export_pending": "Retry parrhesia_export using the exact relative path already recorded for the pending export.",
    "invalid_export_path": "Supply a workspace-relative export path ending with '.md' outside '.parrhesia'.",
    "export_failed": "Retry parrhesia_export with the same path once filesystem permissions/availability are restored.",
    "export_verification_changed": "Restore the source files matching the pending export's verification snapshot before retrying parrhesia_export.",
    "verification_mismatch": (
        "Run parrhesia_verify to inspect snapshot/file/anchor/event_chain mismatches; resolve tampered or modified sources before exporting."
    ),
    "unverified_support": (
        "Run parrhesia_verify: every evidence_id cited by a supported or partially_supported decision must have verification status='pass'."
    ),
    "frozen_integrity_error": "The frozen case document no longer matches input_digest; do not modify .parrhesia/state.sqlite3 directly.",
    "review_integrity_error": "Stored review content no longer matches its recorded digest; inspect state integrity via parrhesia_verify.",
    "adjudication_integrity_error": "Stored adjudication content no longer matches its recorded digest; inspect state integrity via parrhesia_verify.",
    "snapshot_mismatch": "Stored evidence snapshot bytes do not match the registered sha256; inspect integrity via parrhesia_verify.",
    "artifact_mismatch": "Prepared export bytes do not match the recorded export digest; inspect integrity via parrhesia_verify.",
    "unlinked_prior_case": (
        "Add every prior_case_id referenced in claim.prior_claim_links to case.prior_case_ids when creating the follow-up case "
        "via parrhesia_create_case."
    ),
    "unknown_prior_claim": (
        "Ensure prior_claim_id (or follow_up_claim_id) exists inside the target prior_case_id / follow_up_case_id; inspect the prior case via parrhesia_get_case."
    ),
    "unknown_reversal_trigger": (
        "Reference an actual trigger ID defined in the prior claim's or prior decision's reversal_triggers when setting triggered_reversal_id."
    ),
    "self_triggering_reversal_condition": (
        "One or more reversal_triggers already fired on the frozen evidence, effect_records, or checks in conflict with the decision. "
        "Update the verdict/evidence_level to match the trigger's target_verdict/target_evidence_level (or withdraw the contradicted positive claim)."
    ),
    "contradictory_claim_lineage_transition": (
        "A claim declaring relation='reverses' or 'refutes' cannot adjudicate the exact same 'supported' wording, scope, and classification as the prior claim. "
        "Revise the claim text/scope/verdict to reflect the actual reversal or refutation."
    ),
    "untriggered_reversal_link": (
        "When linking via triggered_reversal_id, the referenced prior trigger must actually fire on the follow-up claim's data or verdict. "
        "Preflight with parrhesia_evaluate_triggers or remove triggered_reversal_id if the trigger did not fire."
    ),
    "invalid_calibration_outcome": (
        "Ensure outcome_score is omitted/null for outcome='inconclusive' and within [0.0, 1.0] otherwise, include follow_up_case_id when resolution_source='follow_up_case', "
        "and supply observed_ci_low <= observed_estimate <= observed_ci_high when providing observed CIs."
    ),
}


def repair_hint_for(code: str, message: str = "", *, action: str | None = None) -> str:
    """Return an actionable repair instruction for a ContractError or argument error."""
    base = _REPAIR_HINTS.get(code)
    if base:
        if action and code in ("missing_field", "unknown_field", "invalid_value", "invalid_type"):
            return f"[{action}] {base}"
        return base
    suffix = f" for action '{action}'" if action else ""
    detail = f" ({message})" if message else ""
    return f"Review the input schema and workflow contract{suffix} and correct the rejected value{detail}."
