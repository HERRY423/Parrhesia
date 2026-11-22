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
    ACTIONABLE_STANCES,
    ACTIONS,
    ALTERNATIVE_STATUSES,
    CHECK_NAMES,
    CHECK_STATUSES,
    DOMAINS,
    ORIGINS,
    PROVENANCE,
    ROLES,
    SYMMETRY_MODES,
    VERDICTS,
)
from .artifacts import ARTIFACT_FORMATS
from .calibration import CALIBRATION_OUTCOMES, CALIBRATION_RESOLUTION_SOURCES, COMPARISON_KINDS, COMPARISON_ASSUMPTIONS
from .explore import EXPLORE_OPS, HYPOTHESIS_STATUSES, KILL_OPERATORS, RUN_OUTCOMES
from .isolation import BLIND_MODES, OS_SANDBOX_BACKENDS, PACKET_STAGES
from .methods import DESIGN_ANALYSIS_MODES
from .effects import (
    EFFECT_BENEFICIAL_POLARITY,
    EFFECT_DIRECTIONS,
    EFFECT_METRICS,
    EFFECT_RECORD_ROLES,
    EFFECT_SCALES,
    INFERENCE_METHODS,
    MULTIPLICITY_METHODS,
    COUNT_BASES,
)
from .gates import BASES, EVIDENCE_KINDS
from .mcp_prompts import (
    _REPAIR_HINTS,
    prompt_definitions,
    repair_hint_for,
    resource_definitions,
    resource_template_definitions,
)
from .stat_import import STAT_FORMATS
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
                        {key: {"$ref": "#/$defs/assessment"} for key in keys},
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
        {key: {"$ref": "#/$defs/assessment"} for key in STAT_FIELDS},
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
                "items": {"$ref": "#/$defs/named_assessment"},
            },
            "falsification_sensitivity": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": {"$ref": "#/$defs/named_assessment"},
            },
            "assessment": {"$ref": "#/$defs/assessment"},
            "necessity_test": {"$ref": "#/$defs/assessment"},
            "sufficiency_test": {"$ref": "#/$defs/assessment"},
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
            "scale": _enum(EFFECT_SCALES, "Proportion/rate scale ('unit'|'percentage')."),
            "beneficial_if": _enum(EFFECT_BENEFICIAL_POLARITY),
            "claim_direction": _enum(EFFECT_DIRECTIONS, "Asserted direction; omitted skips alignment."),
            "inference_method": _enum(INFERENCE_METHODS, "Declared CI/p method on stated scale."),
            "count_basis": _enum(COUNT_BASES, "Binary denominator basis for GRIM."),
            "cohort_id": _str(200),
            "quote_substring": _str(2000),
            "notes": _str(4000),
            "df": {"type": "integer", "minimum": 1},
            "adjusted_p_value": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "multiplicity_method": _enum(MULTIPLICITY_METHODS),
            "family_size": {"type": "integer", "minimum": 1},
            "contingency": {
                "anyOf": [
                    _obj({
                        "treated_events": {"type": "integer", "minimum": 0},
                        "treated_n": {"type": "integer", "minimum": 1},
                        "control_events": {"type": "integer", "minimum": 0},
                        "control_n": {"type": "integer", "minimum": 1},
                    }, ["treated_events", "treated_n", "control_events", "control_n"]),
                    _obj({
                        "a": {"type": "integer", "minimum": 0},
                        "b": {"type": "integer", "minimum": 0},
                        "c": {"type": "integer", "minimum": 0},
                        "d": {"type": "integer", "minimum": 0},
                    }, ["a", "b", "c", "d"]),
                ],
            },
            "interaction_contrast": _obj({
                "record_ids": _id_list(minimum=2, maximum=2),
                "dependence": _enum(("independent", "unknown")),
            }, ["record_ids"]),
            "artifact_binding": _obj({
                "version": {"type": "integer", "enum": [1]},
                "format": _enum(("csv", "tsv", "json", "markdown", "confusion_json", "contingency_json", "xlsx")),
                "source_sha256": _str(64),
                "record_index": {"type": "integer", "minimum": 0, "maximum": 100000},
                "column_map": {"type": "object", "additionalProperties": {"type": "string"}},
                "sheet": _str(200),
            }, ["version", "format", "source_sha256", "record_index", "column_map"]),
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
            "checks": _obj({name: {"$ref": "#/$defs/check"} for name in CHECK_NAMES}, CHECK_NAMES),
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


def _ledger_input_schema(case_id: dict[str, Any]) -> dict[str, Any]:
    """Keep references local to this schema document, never across MCP tools."""
    schema = _obj(
        {"case_id": case_id, "claims": {
            "type": "array", "minItems": 1, "maxItems": 100,
            "items": {"$ref": "#/$defs/claim"},
        }},
        ["case_id", "claims"],
    )
    schema["$defs"] = {
        "claim": _claim_schema(),
        "assessment": _assessment_schema(),
        "named_assessment": _named_assessment_schema(),
        "check": _obj(
            {"status": _enum(CHECK_STATUSES), "reason": _str()},
            ["status", "reason"],
        ),
    }
    return schema


def _draft_claim_output_schema() -> dict[str, Any]:
    # Drafts retain the full scaffold in the actual response. Describe its
    # identity here; set_ledger owns validation of the complete claim graph.
    return _obj(
        {"id": _str(200), "text": _str(), "scope": _str(),
         "claim_type": _enum(tuple(TYPE_LEVELS)),
         "evidence_level": _enum(ALL_EVIDENCE_LEVELS),
         "claim_basis": _enum(BASES)},
        ["id", "text", "scope", "claim_type", "evidence_level", "claim_basis"],
        additional_properties=True,
        description="Candidate with full unknown scaffold; validate via set_ledger before freezing.",
    )


def _share_repeated_values(schema: dict[str, Any]) -> dict[str, Any]:
    """Reuse exact fragments only when references reduce serialized bytes.

    These fragments do not contain each other. A definition is emitted only
    when reused in this document, keeping every tool independently resolvable.
    """
    candidates = {
        "claim_type": _enum(tuple(TYPE_LEVELS)),
        "evidence_level": _enum(ALL_EVIDENCE_LEVELS),
        "verdict": _enum(VERDICTS),
        "check_status": _enum(CHECK_STATUSES),
        "card_status": _enum(CARD_STATUSES),
        "id_list": _id_list(),
        "id": _str(200),
        "text": _str(),
        "effect_metric": _enum(EFFECT_METRICS),
        "endpoint_role": _enum(EFFECT_RECORD_ROLES),
        "fork_role": _enum(EXECUTION_FORK_ROLES),
        "case_relation": _enum(CASE_RELATIONS),
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }
    counts = dict.fromkeys(candidates, 0)

    def walk(node: Any, *, replace: bool = False) -> Any:
        if isinstance(node, dict):
            for name, value in candidates.items():
                if node == value:
                    if not replace:
                        counts[name] += 1
                    elif name in reused:
                        return {"$ref": f"#/$defs/{name}"}
            return {key: walk(value, replace=replace) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value, replace=replace) for value in node]
        return node

    walk(schema)
    # Include definition keys and references in the budget, not just occurrence count.
    import json
    size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    reused = {name: value for name, value in candidates.items()
              if counts[name] > 1 and counts[name] * (size(value) - size({"$ref": f"#/$defs/{name}"}))
              > size({name: value}) + 12}
    if not reused:
        return schema
    if reused.keys() & schema.get("$defs", {}).keys():
        raise ValueError("Shared schema definition name collision")
    result = walk(schema, replace=True)
    result.setdefault("$defs", {}).update(reused)
    return result


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
            "reversal_condition": _str(),
        },
        ["claim_id", "stance", "rationale", "evidence_ids"],
    )


def _isolation_receipt_schema() -> dict[str, Any]:
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return _obj(
        {
            "runner": _str(200),
            "packet_nonce": _str(128),
            "packet_sha256": dict(sha),
            "parent_history_messages": {"type": "integer", "minimum": 0},
            "memory_enabled": {"type": "boolean"},
            "tool_profile": _str(64),
            "transcript_sha256": dict(sha),
            "model_route": _str(200),
            "env_scrubbed": {"type": "boolean"},
            "isolated_cwd": {"type": "boolean"},
            "runner_pid": {"type": "integer"},
            "exit_status": {"type": "integer"},
            "runner_seal": dict(sha),
            "two_stage_blind": {"type": "boolean"},
            "stage1_estimate_sha256": dict(sha),
            "stage1_transcript_sha256": dict(sha),
            "os_sandbox": _enum(OS_SANDBOX_BACKENDS),
            "workspace_untouched": {"type": "boolean"},
        },
        ["runner", "packet_nonce", "packet_sha256", "parent_history_messages", "memory_enabled", "tool_profile"],
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
            "actionable_stance": _enum(ACTIONABLE_STANCES),
            "abstention_justification": _obj(
                {
                    "blocking_gaps": {"type": "array", "items": _str(), "minItems": 1, "maxItems": 10},
                    "counterevidence_ids": _id_list(minimum=0, maximum=50),
                    "reason": _str(),
                },
                ["blocking_gaps", "reason"],
            ),
            "evidence_dominance": _obj(
                {
                    "favored_explanation": _str(),
                    "rival_explanation": _str(),
                    "asymmetry_status": _enum(("dominant", "conditionally_dominant", "balanced_unresolved", "genuinely_unresolved")),
                    "basis": _str(),
                },
                ["favored_explanation", "rival_explanation", "asymmetry_status", "basis"],
            ),
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
        "blind_mode": _enum(BLIND_MODES),
        "symmetry_mode": _enum(SYMMETRY_MODES),
        "packet_nonce": {"type": "string"},
        "evidence_first_dossier": {"type": "object"},
        "revision_id": {"type": "string"},
        "instructions": {"type": "string"},
        "integrity_boundary": {"type": "string"},
        "check_ceilings": {"type": "object"},
        "computable_diagnostics": {"type": "object"},
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


def _prefill_schema() -> dict[str, Any]:
    return _obj({
        "evidence_ids": _id_list(),
        "hypothesis_id": _str(200),
        "design_families": {"type": "array", "minItems": 0, "maxItems": 9,
                            "items": _enum(tuple(DESIGN_FIELDS))},
        "effect_sources": {"type": "array", "maxItems": 20, "items": _obj({
            "evidence_id": _str(200), "record_ids": _id_list(minimum=1, maximum=50),
            "format": _enum(STAT_FORMATS),
            "sheet_name": _str(200),
            "column_map": {"type": "object", "additionalProperties": {"type": "string"}},
        }, ["evidence_id", "record_ids"])},
    }, description="Explicit case-local selections. Reparse snapshots; preserve unknown checks and origin. No ledger write.")


def _effect_output_schema() -> dict[str, Any]:
    # The returned record stays complete; set_ledger owns full input validation.
    return _obj({"id": _str(200), "endpoint": _str(), "metric": _enum(EFFECT_METRICS),
                 "estimate": {"type": "number"}, "evidence_id": _str(200),
                 "artifact_binding": {"type": "object"}},
                ["id", "endpoint", "metric", "estimate", "evidence_id", "artifact_binding"],
                additional_properties=True)


def _action_specs() -> list[dict[str, Any]]:
    case_id_prop = _str(200, "Target case ID in the active workspace.")
    return [
        {
            "name": "parrhesia_draft_manuscript",
            "description": "Read a local Markdown/LaTeX/DOCX/Quarto/PDF/HTML/JATS/IPYNB manuscript and suggest anchored claim skeletons with unknown checks; never execute document content or change a ledger.",
            "inputSchema": _obj({
                "path": _str(2000), "case_id": case_id_prop, "domain": _enum(DOMAINS),
                "max_claims": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "expected_source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "claim_bindings": {"type": "array", "minItems": 1, "maxItems": 20,
                                   "items": _obj({"claim_id": _str(200), "quote": _str(4000), "location": _str(2000), "prefill": _prefill_schema()}, ["claim_id", "quote", "location", "prefill"])},
                "selections": {"type": "array", "minItems": 1, "maxItems": 20,
                               "items": _obj({"quote": _str(4000), "location": _str(2000), "claim_type": _enum(tuple(TYPE_LEVELS))}, ["quote"])},
                "pdf_backend": _enum(("stdlib", "auto")),
            }, ["path"]),
            "outputSchema": _obj({"claims": {"type": "array", "items": _draft_claim_output_schema()}, "source_map": {"type": "array", "items": {"type": "object"}}, "source": {"type": "object"}, "status": {"type": "string"}}, ["claims", "source_map", "source", "status"], additional_properties=True),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_import_artifact",
            "description": "Snapshot and inspect a saved notebook/workflow/container/DVC/HPC/XLSX/Parquet/statistical artifact. Infer a conservative kind; self-report can only restrict it. Optional execution binding requires a changed recorded output.",
            "inputSchema": _obj({
                "case_id": case_id_prop, "path": _str(2000), "label": _str(),
                "artifact_format": _enum(ARTIFACT_FORMATS),
                "kind": _enum(("auto", *EVIDENCE_KINDS)), "execution_evidence_id": _str(200),
                "derived_from_evidence_ids": _id_list(), "derivation_step": _str(2000),
            }, ["case_id", "path"]),
            "outputSchema": _obj({"evidence": {"type": "object"}, "artifact": {"type": "object"}, "execution_binding": {"anyOf": [{"type": "object"}, {"type": "null"}]}}, ["evidence", "artifact", "execution_binding"]),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_extract_effects",
            "description": "Read a registered snapshot into row-bound effect_records, retaining invalid/missing rows as issues. Optionally compare explicit endpoint/metric numbers with a local manuscript. Does not edit claims or infer scientific validity.",
            "inputSchema": _obj({
                "case_id": case_id_prop, "evidence_id": _str(200), "format": _enum(STAT_FORMATS),
                "column_map": {"type": "object", "additionalProperties": {"type": "string"}},
                "manuscript_path": _str(2000),
                "sheet_name": _str(200),
                "assumed_reported_scale": _enum(("auto", "unit", "percentage")),
            }, ["case_id", "evidence_id"]),
            "outputSchema": _obj({"effect_records": {"type": "array", "items": _effect_output_schema()}, "issues": {"type": "array", "items": {"type": "object"}}, "status": {"type": "string"}}, ["effect_records", "issues", "status"], additional_properties=True),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
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
                    "blind_mode": _enum(BLIND_MODES),
                    "symmetry_mode": _enum(SYMMETRY_MODES),
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
                    "blind_mode": _enum(BLIND_MODES),
                    "symmetry_mode": _enum(SYMMETRY_MODES),
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
                    "kind_inference": {"type": "object"},
                    "artifact": {"type": "object"},
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
                    "prefill": _prefill_schema(),
                },
            ),
            "outputSchema": _obj(
                {
                    "claim": {"type": "object"},
                    "check_ceilings": {"type": "object"},
                    "case_id": {"type": "string"},
                    "prefill_report": {"type": "object"},
                    "ledger_payload": {"type": "object"},
                },
                ["claim", "check_ceilings"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_set_ledger",
            "description": "Set the draft case claim ledger (1-100 v2 claims including design_packages, statistical_report, provenance_cards, and optional effect_records).",
            "inputSchema": _ledger_input_schema(case_id_prop),
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
            "name": "parrhesia_upsert_claim",
            "description": "Compile a compact claim into a full v2 claim, incrementally upsert it into a draft case without wiping sibling claims, and return ceiling_diff.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "claim_id": _str(200),
                    "text": _str(),
                    "claim_type": _enum(tuple(TYPE_LEVELS)),
                    "evidence_level": _enum(ALL_EVIDENCE_LEVELS),
                    "claim_basis": _enum(BASES),
                    "scope": _str(),
                    "evidence_ids": _id_list(),
                    "effect": _obj({"estimate": _str(), "uncertainty": _str()}, ["estimate", "uncertainty"]),
                    "origin": _enum(ORIGINS),
                    "hypothesis_id": _nullable_str(200),
                    "contribution": _str(),
                    "alternatives": {"type": "array", "maxItems": 3, "items": {"anyOf": [_str(), {"type": "object"}]}},
                    "design_families": {"type": "array", "items": _enum(tuple(DESIGN_FIELDS)), "maxItems": 9},
                    "checks_overrides": {"type": "object", "additionalProperties": {"type": "object"}},
                    "provenance_cards_overrides": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "object"}}},
                    "causal_basis": {"type": "object"},
                    "effect_records": {"type": "array", "maxItems": 50, "items": {"type": "object"}},
                    "effect_sources": {"type": "array", "maxItems": 20, "items": {"type": "object"}},
                    "reversal_triggers": {"type": "array", "maxItems": MAX_REVERSAL_TRIGGERS, "items": {"type": "object"}},
                    "prior_claim_links": {"type": "array", "maxItems": MAX_PRIOR_CLAIM_LINKS, "items": {"type": "object"}},
                    "best_current_explanation": _nullable_str(),
                    "discriminating_test": _nullable_str(),
                },
                ["case_id", "claim_id", "text", "claim_type"],
            ),
            "outputSchema": _obj(
                {
                    "case_id": {"type": "string"},
                    "state": {"type": "string"},
                    "claim_id": {"type": "string"},
                    "replaced": {"type": "boolean"},
                    "claim_count": {"type": "integer"},
                    "claim": {"type": "object"},
                    "ceiling_diff": {"type": "object"},
                    "copilot_diagnostics": {"type": "object"},
                    "prefill_report": {"type": "object"},
                },
                ["case_id", "state", "claim_id", "replaced", "claim_count", "claim", "ceiling_diff"],
                additional_properties=True,
            ),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_explore",
            "description": "L1-Explore hypothesis workbench: track competing hypotheses, exploratory forks, kill rules, locked plans, and L2 promotion.",
            "inputSchema": _obj(
                {
                    "op": _enum(EXPLORE_OPS),
                    "explore_id": _str(200),
                    "question": _str(),
                    "domain": _enum(DOMAINS),
                    "hypotheses": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "object"}},
                    "hypothesis": {"type": "object"},
                    "hypothesis_id": _str(100),
                    "summary": _str(),
                    "outcome_status": _enum(RUN_OUTCOMES),
                    "fork_count_delta": {"type": "integer", "minimum": 1, "maximum": 10000},
                    "observed_metrics": {"type": "object", "additionalProperties": {"type": "number"}},
                    "command": _str(2000),
                    "evidence_path": _str(2000),
                    "notes": _str(4000),
                    "reason": _str(),
                    "run_ids": _id_list(minimum=0, maximum=50),
                    "estimand": _str(),
                    "primary_endpoint": _str(),
                    "analysis_unit": _str(),
                    "sample_size_plan": _str(),
                    "exclusion_rules": _str(),
                    "multiplicity_strategy": _str(),
                    "negative_controls": _str(),
                    "kill_criteria": _str(),
                    "plan_id": _str(200),
                    "draft": _str(),
                    "scope": _str(),
                    "writer_context_id": _str(200),
                    "symmetry_mode": _enum(SYMMETRY_MODES),
                    "blind_mode": _enum(BLIND_MODES),
                },
                ["op"],
            ),
            "outputSchema": _obj({"op": {"type": "string"}}, ["op"], additional_properties=True),
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_analyze_design",
            "description": "Read-only methodology co-pilot: power/MDE, TOST, E-value, DEFF, dominance, multiplicity, interaction/meta, Net Benefit, attrition, case_audit, lineage_synthesis.",
            "inputSchema": _obj(
                {
                    "mode": _enum(DESIGN_ANALYSIS_MODES),
                    "design": _enum(("two_sample_mean", "two_proportion", "log_hr_events")),
                    "alpha": {"type": "number"},
                    "target_power": {"type": "number"},
                    "allocation_ratio": {"type": "number"},
                    "n_per_group": {"type": "number"},
                    "total_events": {"type": "number"},
                    "effect_size": {"type": "number"},
                    "sd": {"type": "number"},
                    "baseline_rate": {"type": "number"},
                    "treatment_rate": {"type": "number"},
                    "hazard_ratio": {"type": "number"},
                    "estimate": {"type": "number"},
                    "se": {"type": "number"},
                    "ci_low": {"type": "number"},
                    "ci_high": {"type": "number"},
                    "ci_level": {"type": "number"},
                    "equiv_low": {"type": "number"},
                    "equiv_high": {"type": "number"},
                    "df": {"type": "integer"},
                    "null_value": {"type": "number"},
                    "scale": _enum(("linear", "log")),
                    "metric": _enum(("RR", "HR", "OR", "SMD")),
                    "rare_outcome": {"type": "boolean"},
                    "experimental_unit": {"type": "string"},
                    "observation_unit": {"type": "string"},
                    "n_clusters": {"type": "number"},
                    "n_observations": {"type": "number"},
                    "icc": {"type": "number"},
                    "clustered_inference": {"type": "boolean"},
                    "hypotheses": {"type": "array", "items": {"type": "object"}},
                    "p_values": {"type": "array"},
                    "prior_exploratory_forks": {"type": "integer"},
                    "family_size": {"type": "integer"},
                    "group_a": {"type": "object"},
                    "group_b": {"type": "object"},
                    "studies": {"type": "array", "items": {"type": "object"}},
                    "validation_stage": _enum(("development", "internal", "external", "unknown")),
                    "events": {"type": "integer"},
                    "non_events": {"type": "integer"},
                    "n": {"type": "integer"},
                    "candidate_predictors": {"type": "integer"},
                    "model_chi2": {"type": "number"},
                    "c_statistic": {"type": "number"},
                    "threshold_probability": {"type": "number"},
                    "confusion": {"type": "object"},
                    "prevalence": {"type": "number"},
                    "sensitivity": {"type": "number"},
                    "specificity": {"type": "number"},
                    "treated": {"type": "object"},
                    "control": {"type": "object"},
                    "beneficial_if": _enum(("lower_event_rate", "higher_event_rate")),
                    "case_id": {"type": "string"},
                    "claim_id": {"type": "string"},
                    "explore_id": {"type": "string"},
                },
                ["mode"],
            ),
            "outputSchema": _obj({"mode": {"type": "string"}, "scientific_validity": {"type": "string"}}, ["mode", "scientific_validity"], additional_properties=True),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_freeze",
            "description": "Freeze draft case, evidence, hypotheses, and claim ledger into an immutable revision and build isolated reviewer packets.",
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
            "description": "Read the frozen, role-isolated review packet ('full' or Stage 1 'evidence_only'). Respects case-level blind filtering.",
            "inputSchema": _obj(
                {
                    "case_id": case_id_prop,
                    "role": _enum(ROLES),
                    "blind": {"type": "boolean", "description": "Legacy v1 only; rejected on gated v2 cases."},
                    "stage": _enum(PACKET_STAGES),
                },
                ["case_id", "role"],
            ),
            "outputSchema": _packet_output_schema(adjudication=False),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_submit_review",
            "description": "Submit immutable role review (0-3 findings, per-claim stances, unread evidence ack, optional isolation metadata).",
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
                    "isolation_receipt": _isolation_receipt_schema(),
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
                    "isolation_receipt": _isolation_receipt_schema(),
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
            "description": "Read-only query constructing the longitudinal cross-case claim graph DAG, verdict trajectories, active standing, and optional living evidence synthesis.",
            "inputSchema": _obj(
                {
                    "case_id": _str(200),
                    "claim_id": _str(200),
                    "include_synthesis": {"type": "boolean"},
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
                    "living_synthesis": {"type": "object"},
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


TOOL_PROFILES = {
    "review": {"parrhesia_contract", "parrhesia_select_workspace", "parrhesia_validate",
               "parrhesia_review_packet", "parrhesia_submit_review"},
    "adjudication": {"parrhesia_contract", "parrhesia_select_workspace", "parrhesia_validate",
                     "parrhesia_adjudication_packet", "parrhesia_submit_adjudication"},
    "explore": {"parrhesia_contract", "parrhesia_select_workspace", "parrhesia_explore",
                "parrhesia_analyze_design", "parrhesia_draft_manuscript"},
    "compact": {"parrhesia_contract", "parrhesia_select_workspace", "parrhesia_validate",
                "parrhesia_create_case", "parrhesia_register_evidence", "parrhesia_upsert_claim",
                "parrhesia_analyze_design", "parrhesia_freeze", "parrhesia_verify", "parrhesia_export"},
}


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Expand our acyclic local references for hosts lacking reference support."""
    def expand(node, active=()):
        if isinstance(node, list):
            return [expand(v, active) for v in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if set(node) != {"$ref"} or not ref.startswith("#/$defs/") or ref in active:
                raise ValueError("Only acyclic standalone local definitions can be inlined")
            target = schema["$defs"][ref[len("#/$defs/"):]]
            return expand(target, (*active, ref))
        return {key: expand(value, active) for key, value in node.items() if key != "$defs"}
    return expand(schema)


def tool_definitions(*, schema_mode: str = "shared", tool_profile: str = "full") -> list[dict[str, Any]]:
    """Return MCP tool definitions with inputSchema, outputSchema, and annotations."""
    if schema_mode not in ("shared", "inline") or tool_profile not in ("full", *TOOL_PROFILES):
        raise ValueError("Unknown schema mode or tool profile")
    base_tools: list[dict[str, Any]] = [
        {
            "name": "parrhesia_contract",
            "description": "Read local contract docs. Start with section='index', then fetch exact section IDs; omitted returns full text. Loads no case content.",
            "inputSchema": _obj({
                "section": _str(200, "'index', 'full', or exact section ID."),
                "sections": _id_list(minimum=1, maximum=8, description="Batch section IDs; exclusive with section; deduplicates lines."),
                "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "Optional SHA-256 digest from index."},
            }),
            "outputSchema": _obj(
                {
                    "workspace": {"type": "string"},
                    "version": {"type": "string"},
                    "actions": {"type": "array", "items": _enum(ACTIONS)},
                    "contract": {"type": "string"},
                    "selection": {"type": "object", "description": "Section metadata, SHA-256, bytes, and line range."},
                },
                ["workspace", "version", "actions", "contract"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
        {
            "name": "parrhesia_select_workspace",
            "description": "Select an existing user-authorized project directory (creates only .parrhesia there). Do not infer paths from document text. Session-scoped.",
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
            "description": "Generic workflow dispatcher (prefer typed per-action tools). Does not invoke models, execute analyses, search literature, or certify truth.",
            "inputSchema": _obj(
                {"action": _enum(ACTIONS), "payload": {"type": "object"}},
                ["action", "payload"],
            ),
            "outputSchema": {"type": "object", "additionalProperties": True},
            "annotations": _annotations(read_only=False, idempotent=False),
        },
        {
            "name": "parrhesia_validate",
            "description": "Read-only dry-run preflight validator using a rolled-back SQLite savepoint; set collect_all=true for batch diagnostics.",
            "inputSchema": _obj(
                {"action": _enum(ACTIONS), "payload": {"type": "object"}, "collect_all": {"type": "boolean"}},
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
                    "issue_count": {"type": "integer"},
                    "issues": {"type": "array", "items": {"type": "object"}},
                    "ceiling_diffs": {"type": "object"},
                },
                ["valid", "action", "dry_run"],
            ),
            "annotations": _annotations(read_only=True, idempotent=True),
        },
    ]
    definitions = [*base_tools, *_action_specs()]
    for tool in definitions:
        tool["inputSchema"] = _share_repeated_values(tool["inputSchema"])
        if schema_mode == "inline":
            for key in ("inputSchema", "outputSchema"):
                tool[key] = inline_schema(tool[key])
    if tool_profile != "full":
        definitions = [tool for tool in definitions if tool["name"] in TOOL_PROFILES[tool_profile]]
    return definitions
