"""Stable, dependency-free contract primitives for Parrhesia's pilot API."""
from __future__ import annotations

from typing import Any

SCIENTIFIC_LEVELS = ("descriptive", "association", "predictive", "mechanistic", "causal")
ENGINEERING_LEVELS = ("test_passed", "host_accepted", "user_impact")
LEVELS = (*SCIENTIFIC_LEVELS, *ENGINEERING_LEVELS)
VERDICTS = ("supported", "partially_supported", "unsupported", "insufficient_evidence")
ROLES = ("overclaim", "underclaim")
CHECK_NAMES = ("quality", "batch", "unit", "assumptions", "multiplicity", "leakage", "baseline")
CHECK_STATUSES = ("pass", "fail", "unknown", "not_applicable")
ALTERNATIVE_STATUSES = ("excluded", "partially_excluded", "not_excluded")
PROVENANCE = ("reported", "observed", "synthetic")
ORIGINS = ("prespecified", "exploratory", "unknown")
ACTIONS = (
    "create_case", "register_evidence", "register_hypothesis", "set_ledger",
    "freeze", "review_packet", "submit_review", "adjudication_packet",
    "submit_adjudication", "verify", "get_case", "export", "record_human_decision",
)


class ContractError(ValueError):
    """An expected, user-correctable input or lifecycle error."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def fail(code: str, message: str) -> None:
    raise ContractError(code, message)


def obj(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        fail("invalid_type", f"{name} must be an object")
    return value


def string(value: Any, name: str, *, optional: bool = False, maximum: int = 200_000) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        fail("invalid_value", f"{name} must be a nonempty string")
    if len(value) > maximum:
        fail("too_large", f"{name} exceeds {maximum} characters")
    return value


def enum(value: Any, choices: tuple[str, ...], name: str) -> str:
    if value not in choices or not isinstance(value, str):
        fail("invalid_value", f"{name} must be one of {', '.join(choices)}")
    return value


def array(value: Any, name: str, *, minimum: int = 0, maximum: int = 1000) -> list:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail("invalid_value", f"{name} must be an array of {minimum} to {maximum} items")
    return value


def fields(value: dict, allowed: set[str], required: set[str], name: str) -> None:
    missing, extra = required - value.keys(), value.keys() - allowed
    if missing:
        fail("missing_field", f"{name} is missing: {', '.join(sorted(missing))}")
    if extra:
        fail("unknown_field", f"{name} has unsupported fields: {', '.join(sorted(extra))}")


def ids(value: Any, name: str, *, minimum: int = 0) -> list[str]:
    result = [string(item, name, maximum=200) for item in array(value, name, minimum=minimum)]
    if len(result) != len(set(result)):
        fail("duplicate_id", f"{name} contains duplicate IDs")
    return result
