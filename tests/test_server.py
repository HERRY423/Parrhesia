from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from parrhesia.claims import TYPE_LEVELS
from parrhesia.contracts import (
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
from parrhesia.effects import (
    EFFECT_BENEFICIAL_POLARITY,
    EFFECT_DIRECTIONS,
    EFFECT_METRICS,
    EFFECT_RECORD_ROLES,
    EFFECT_SCALES,
)


ROOT = Path(__file__).resolve().parents[1]


def request(method: str, params: dict | None = None, id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


INITIALIZE = request(
    "initialize",
    {
        "protocolVersion": "2025-11-25",
        "clientInfo": {"name": "integration-test", "version": "1"},
        "capabilities": {},
    },
)


def _expand_local_refs(schema: dict) -> dict:
    """Resolve the acyclic local refs used by tool schemas; fail on unknown refs.

    This is a test helper, not a replacement for a full JSON Schema validator.
    """
    def expand(node, stack=()):
        if isinstance(node, list):
            return [expand(item, stack) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if set(node) != {"$ref"} or not ref.startswith("#/$defs/") or ref in stack:
                raise AssertionError(f"Unsupported or recursive schema reference: {ref}")
            target = schema
            for part in ref[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            return expand(target, (*stack, ref))
        return {key: expand(value, stack) for key, value in node.items() if key != "$defs"}
    return expand(schema)


def _assert_valid_against_schema(
    testcase: unittest.TestCase,
    value: object,
    schema: dict,
    path: str = "root",
) -> None:
    if "$defs" in schema:
        schema = _expand_local_refs(schema)
    # Never silently accept a reference that the test validator failed to resolve.
    testcase.assertNotIn("$ref", schema, f"{path} has an unresolved schema reference")
    if "anyOf" in schema:
        errors: list[str] = []
        for branch in schema["anyOf"]:
            try:
                _assert_valid_against_schema(testcase, value, branch, path)
                return
            except AssertionError as exc:
                errors.append(str(exc))
        testcase.fail(f"{path} did not match anyOf branches: {errors}")

    if "oneOf" in schema:
        matches = 0
        errors = []
        for branch in schema["oneOf"]:
            try:
                _assert_valid_against_schema(testcase, value, branch, path)
                matches += 1
            except AssertionError as exc:
                errors.append(str(exc))
        testcase.assertEqual(
            matches,
            1,
            f"{path} expected exactly 1 oneOf match, got {matches}: {errors}",
        )
        return

    if "enum" in schema:
        testcase.assertIn(value, schema["enum"], f"{path} value {value!r} not in enum {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type == "object":
        testcase.assertIsInstance(value, dict, f"{path} expected object, got {type(value).__name__}")
        assert isinstance(value, dict)
        for req_key in schema.get("required", []):
            testcase.assertIn(req_key, value, f"{path} missing required property {req_key!r}")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _assert_valid_against_schema(testcase, item, props[key], f"{path}.{key}")
            elif additional is False:
                testcase.fail(f"{path} unexpected property {key!r} with additionalProperties=False")
            elif isinstance(additional, dict):
                _assert_valid_against_schema(testcase, item, additional, f"{path}.{key}")
    elif expected_type == "array":
        testcase.assertIsInstance(value, list, f"{path} expected array, got {type(value).__name__}")
        assert isinstance(value, list)
        if "minItems" in schema:
            testcase.assertGreaterEqual(len(value), schema["minItems"], f"{path} below minItems")
        if "maxItems" in schema:
            testcase.assertLessEqual(len(value), schema["maxItems"], f"{path} above maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _assert_valid_against_schema(testcase, item, item_schema, f"{path}[{idx}]")
    elif expected_type == "string":
        testcase.assertIsInstance(value, str, f"{path} expected string, got {type(value).__name__}")
        assert isinstance(value, str)
        if "minLength" in schema:
            testcase.assertGreaterEqual(len(value), schema["minLength"], f"{path} below minLength")
        if "maxLength" in schema:
            testcase.assertLessEqual(len(value), schema["maxLength"], f"{path} above maxLength")
    elif expected_type == "integer":
        testcase.assertTrue(
            isinstance(value, int) and not isinstance(value, bool),
            f"{path} expected integer, got {type(value).__name__}",
        )
        assert isinstance(value, int)
        if "minimum" in schema:
            testcase.assertGreaterEqual(value, schema["minimum"], f"{path} below minimum")
        if "maximum" in schema:
            testcase.assertLessEqual(value, schema["maximum"], f"{path} above maximum")
    elif expected_type == "number":
        testcase.assertTrue(
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{path} expected number, got {type(value).__name__}",
        )
        assert isinstance(value, (int, float))
        if "minimum" in schema:
            testcase.assertGreaterEqual(value, schema["minimum"], f"{path} below minimum")
        if "maximum" in schema:
            testcase.assertLessEqual(value, schema["maximum"], f"{path} above maximum")
        if "exclusiveMinimum" in schema:
            testcase.assertGreater(value, schema["exclusiveMinimum"], f"{path} not > exclusiveMinimum")
        if "exclusiveMaximum" in schema:
            testcase.assertLess(value, schema["exclusiveMaximum"], f"{path} not < exclusiveMaximum")
    elif expected_type == "boolean":
        testcase.assertIsInstance(value, bool, f"{path} expected boolean, got {type(value).__name__}")
    elif expected_type == "null":
        testcase.assertIsNone(value, f"{path} expected null, got {type(value).__name__}")


class MCPTests(unittest.TestCase):
    def exchange(self, workspace: str | Path, messages: list[dict | str]) -> list[dict]:
        source = (
            "\n".join(
                json.dumps(m, ensure_ascii=False) if not isinstance(m, str) else m
                for m in messages
            )
            + "\n"
        )
        result = subprocess.run(
            [sys.executable, "-m", "parrhesia", "serve", "--workspace", str(workspace)],
            input=source.encode("utf-8"),
            cwd=ROOT,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return [json.loads(line) for line in result.stdout.splitlines()]

    def _populate_claim_from_scaffold(
        self,
        scaffold: dict,
        *,
        ev_efficacy: str,
        ev_protocol: str,
        hypothesis_id: str,
    ) -> dict:
        claim = dict(scaffold)
        claim["text"] = "Treatment X lowers mortality hazard in adult Stage III patients (HR 0.72)."
        claim["scope"] = "Adult Stage III patients in phase 2 trial"
        claim["origin"] = "prespecified"
        claim["hypothesis_id"] = hypothesis_id
        claim["contribution"] = "Quantifies overall survival benefit and safety event rate."
        claim["evidence_ids"] = [ev_efficacy, ev_protocol]
        claim["effect"] = {"estimate": "HR 0.72", "uncertainty": "95% CI 0.56 to 0.93, p = 0.012"}
        claim["best_current_explanation"] = (
            "Treatment X reduces mortality risk relative to standard care in Stage III patients."
        )
        claim["discriminating_test"] = (
            "Confirmatory multi-center phase 3 randomized trial with blinded central event review."
        )
        claim["alternatives"] = [
            {
                "explanation": "Chance imbalance in baseline prognostic covariates.",
                "status": "partially_excluded",
                "reason": "Stratified randomization achieved balanced baseline covariates in trial.md.",
            }
        ]
        claim["checks"] = {
            name: {
                "status": "pass",
                "reason": f"Verified {name} against trial.md Section 2.1 and protocol.md Section 3.2.",
            }
            for name in CHECK_NAMES
        }
        claim["design_packages"] = [
            {
                "family": pkg["family"],
                "checks": {
                    key: {
                        "status": "pass",
                        "reason": f"Trial report confirms {key} compliance.",
                        "evidence_ids": [ev_efficacy],
                    }
                    for key in pkg["checks"]
                },
            }
            for pkg in scaffold["design_packages"]
        ]
        claim["statistical_report"] = {
            key: {
                "status": "pass",
                "reason": f"Trial statistical section reports {key} details.",
                "evidence_ids": [ev_efficacy],
            }
            for key in scaffold["statistical_report"]
        }
        cards: dict[str, list[dict]] = {}
        for kind, entries in scaffold["provenance_cards"].items():
            if kind in ("citation", "number"):
                template = entries[0]
                cards[kind] = [
                    {
                        "id": f"card-{kind}-1",
                        "status": "checked",
                        "reason": f"Verified {kind} card directly against trial.md Section 2.1, Table 1, L3.",
                        "evidence_ids": [ev_efficacy],
                        "details": {
                            key: (
                                "Section 2.1, Table 1, L3"
                                if key == "locator"
                                else f"HR 0.72 (95% CI 0.56-0.93, p=0.012); 12/80 (15.0%) verified ({key})."
                            )
                            for key in template["details"]
                        },
                    }
                ]
            else:
                cards[kind] = []
        claim["provenance_cards"] = cards
        claim["effect_records"] = [
            {
                "id": "eff-os-hr",
                "inference_method": "log_wald",
                "claim_direction": "benefit",
                "endpoint": "Overall survival",
                "endpoint_role": "primary",
                "metric": "HR",
                "estimate": 0.72,
                "null_value": 1.0,
                "ci_level": 0.95,
                "ci_low": 0.56,
                "ci_high": 0.93,
                "p_value": 0.012,
                "direction": "benefit",
                "beneficial_if": "below_null",
                "evidence_id": ev_efficacy,
                "quote_substring": "HR 0.72 (95% CI 0.56 to 0.93, p = 0.012)",
            },
            {
                "id": "eff-sae-prop",
                "count_basis": "unweighted_binary",
                "endpoint": "Serious adverse events",
                "endpoint_role": "safety",
                "metric": "proportion",
                "estimate": 15.0,
                "events": 12,
                "n": 80,
                "decimals": 1,
                "scale": "percentage",
                "direction": "harm",
                "evidence_id": ev_efficacy,
                "quote_substring": "12/80 (15.0%)",
            },
        ]
        return claim

    def test_real_process_handshake_contract_and_utf8(self):
        with tempfile.TemporaryDirectory() as workspace:
            responses = self.exchange(
                workspace,
                [
                    INITIALIZE,
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    request("tools/list", id=2),
                    request("tools/call", {"name": "parrhesia_contract"}, 3),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_workflow",
                            "arguments": {
                                "action": "create_case",
                                "payload": {
                                    "question": "这项证据支持什么？",
                                    "draft": "中文草稿",
                                },
                            },
                        },
                        4,
                    ),
                ],
            )
            self.assertEqual(len(responses), 4)
            self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(len(responses[1]["result"]["tools"]), 28)
            self.assertIn("submit_adjudication", responses[2]["result"]["structuredContent"]["contract"])
            self.assertFalse(responses[3]["result"]["isError"])
            case_id = responses[3]["result"]["structuredContent"]["case_id"]
            restart = self.exchange(
                workspace,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_workflow",
                            "arguments": {"action": "get_case", "payload": {"case_id": case_id}},
                        },
                        2,
                    ),
                ],
            )
            self.assertIn("中文草稿", json.dumps(restart[1], ensure_ascii=False))

    def test_invalid_frames_do_not_kill_process_or_mutate(self):
        with tempfile.TemporaryDirectory() as workspace:
            responses = self.exchange(
                workspace,
                [
                    "invalid-json",
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_workflow",
                            "arguments": {"action": "not-an-action", "payload": {}},
                        },
                        2,
                    ),
                    {
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": "parrhesia_select_workspace", "arguments": {"path": "C:/"}},
                    },
                    request("tools/call", {"name": "parrhesia_contract"}, 3),
                ],
            )
            self.assertEqual(responses[0]["error"]["code"], -32700)
            self.assertTrue(responses[2]["result"]["isError"])
            err_payload = json.loads(responses[2]["result"]["content"][0]["text"])
            self.assertEqual(err_payload["error"], "invalid_value")
            self.assertIn("repair_hint", err_payload)
            self.assertFalse(err_payload["repair_hint"].startswith("[not-an-action]"))
            self.assertEqual(
                Path(responses[3]["result"]["structuredContent"]["workspace"]),
                Path(workspace).resolve(),
            )

    def test_legacy_creation_rejected_over_mcp_without_poisoning_next_request(self):
        with tempfile.TemporaryDirectory() as workspace:
            def create(payload: dict, number: int) -> dict:
                return request(
                    "tools/call",
                    {
                        "name": "parrhesia_workflow",
                        "arguments": {"action": "create_case", "payload": payload},
                    },
                    number,
                )

            responses = self.exchange(
                workspace,
                [
                    INITIALIZE,
                    create({"question": "Legacy bypass", "draft": "Fixture", "schema_version": 1}, 2),
                    create({"question": "Current case", "draft": "Fixture"}, 3),
                ],
            )
            self.assertTrue(responses[1]["result"]["isError"])
            err_payload = json.loads(responses[1]["result"]["content"][0]["text"])
            self.assertEqual(err_payload["error"], "legacy_creation_disabled")
            self.assertIn("schema_version=2", err_payload["repair_hint"])
            current = responses[2]["result"]["structuredContent"]
            self.assertEqual(current["schema_version"], 2)
            self.assertEqual(current["gate_version"], 1)
            with closing(sqlite3.connect(Path(workspace) / ".parrhesia/state.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM cases").fetchone()[0], 1)

    def test_workspace_selection_and_error_boundaries(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            responses = self.exchange(
                first,
                [
                    request("tools/list"),
                    INITIALIZE,
                    request(
                        "tools/call",
                        {"name": "parrhesia_select_workspace", "arguments": {"path": "relative"}},
                        2,
                    ),
                    request(
                        "tools/call",
                        {"name": "parrhesia_select_workspace", "arguments": {"path": second}},
                        3,
                    ),
                    request("resources/read", {"uri": "parrhesia://contract"}, 4),
                    request("tools/call", {"name": "unknown"}, 5),
                ],
            )
            self.assertEqual(responses[0]["error"]["code"], -32002)
            self.assertTrue(responses[2]["result"]["isError"])
            err_payload = json.loads(responses[2]["result"]["content"][0]["text"])
            self.assertEqual(err_payload["error"], "invalid_workspace")
            self.assertIn("repair_hint", err_payload)
            self.assertEqual(
                Path(responses[3]["result"]["structuredContent"]["workspace"]),
                Path(second).resolve(),
            )
            self.assertIn("Lifecycle", responses[4]["result"]["contents"][0]["text"])
            self.assertEqual(responses[5]["error"]["code"], -32602)

    def test_tool_schemas_annotations_and_capabilities(self):
        with tempfile.TemporaryDirectory() as workspace:
            responses = self.exchange(
                workspace,
                [
                    INITIALIZE,
                    request("tools/list", id=2),
                    request("resources/list", id=3),
                    request("resources/templates/list", id=4),
                    request("prompts/list", id=5),
                ],
            )
            init_res = responses[0]["result"]
            self.assertEqual(set(init_res["capabilities"]), {"tools", "resources", "prompts"})

            tools = {tool["name"]: tool for tool in responses[1]["result"]["tools"]}
            expected_names = {
                "parrhesia_contract",
                "parrhesia_select_workspace",
                "parrhesia_workflow",
                "parrhesia_validate",
                *(f"parrhesia_{action}" for action in ACTIONS),
            }
            self.assertEqual(len(tools), 28)
            self.assertEqual(set(tools), expected_names)

            readonly_expected = {
                "parrhesia_draft_manuscript",
                "parrhesia_extract_effects",
                "parrhesia_analyze_design",
                "parrhesia_contract",
                "parrhesia_validate",
                "parrhesia_scaffold_claim",
                "parrhesia_review_packet",
                "parrhesia_get_case",
                "parrhesia_claim_graph",
                "parrhesia_evaluate_triggers",
                "parrhesia_calibration_report",
            }
            for name, tool in tools.items():
                self.assertIn("inputSchema", tool)
                self.assertIn("outputSchema", tool)
                self.assertEqual(tool["inputSchema"]["type"], "object")
                self.assertEqual(tool["outputSchema"]["type"], "object")
                ann = tool["annotations"]
                self.assertEqual(
                    set(ann),
                    {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"},
                )
                self.assertIs(ann["destructiveHint"], False, name)
                self.assertIs(ann["openWorldHint"], False, name)
                self.assertIs(ann["readOnlyHint"], name in readonly_expected, name)

            # Verify nested typed structures & live enums from contracts/claims/effects.
            set_ledger_props = _expand_local_refs(tools["parrhesia_set_ledger"]["inputSchema"])["properties"]
            claim_schema = set_ledger_props["claims"]["items"]
            for field in (
                "design_packages",
                "statistical_report",
                "provenance_cards",
                "causal_basis",
                "effect_records",
                "prior_claim_links",
                "reversal_triggers",
            ):
                self.assertIn(field, claim_schema["properties"])
            self.assertEqual(claim_schema["properties"]["claim_type"]["enum"], list(TYPE_LEVELS))
            self.assertEqual(claim_schema["properties"]["origin"]["enum"], list(ORIGINS))
            self.assertEqual(
                claim_schema["properties"]["alternatives"]["items"]["properties"]["status"]["enum"],
                list(ALTERNATIVE_STATUSES),
            )
            self.assertEqual(
                set(claim_schema["properties"]["checks"]["properties"]),
                set(CHECK_NAMES),
            )
            for check_prop in claim_schema["properties"]["checks"]["properties"].values():
                self.assertEqual(check_prop["properties"]["status"]["enum"], list(CHECK_STATUSES))

            eff_props = claim_schema["properties"]["effect_records"]["items"]["properties"]
            self.assertEqual(eff_props["endpoint_role"]["enum"], list(EFFECT_RECORD_ROLES))
            self.assertEqual(eff_props["metric"]["enum"], list(EFFECT_METRICS))
            self.assertEqual(eff_props["direction"]["enum"], list(EFFECT_DIRECTIONS))
            self.assertEqual(eff_props["beneficial_if"]["enum"], list(EFFECT_BENEFICIAL_POLARITY))
            self.assertEqual(eff_props["scale"]["enum"], list(EFFECT_SCALES))

            create_props = tools["parrhesia_create_case"]["inputSchema"]["properties"]
            self.assertEqual(create_props["domain"]["enum"], list(DOMAINS))
            for lk in ("prior_case_ids", "supersedes_case_id", "case_relation"):
                self.assertIn(lk, create_props)
            reg_ev_props = tools["parrhesia_register_evidence"]["inputSchema"]["properties"]
            self.assertEqual(reg_ev_props["provenance"]["enum"], list(PROVENANCE))
            rev_pkt_props = tools["parrhesia_review_packet"]["inputSchema"]["properties"]
            self.assertEqual(rev_pkt_props["role"]["enum"], list(ROLES))
            adj_props = _expand_local_refs(tools["parrhesia_submit_adjudication"]["inputSchema"])["properties"]
            self.assertEqual(
                adj_props["decisions"]["items"]["properties"]["verdict"]["enum"],
                list(VERDICTS),
            )
            self.assertIn("forecast_probability", adj_props["decisions"]["items"]["properties"])
            self.assertIn("reversal_triggers", adj_props["decisions"]["items"]["properties"])
            self.assertIn("isolation_attestation", adj_props)
            self.assertIn("dispositions", adj_props)
            self.assertEqual(
                tools["parrhesia_validate"]["inputSchema"]["properties"]["action"]["enum"],
                list(ACTIONS),
            )
            self.assertEqual(
                tools["parrhesia_workflow"]["inputSchema"]["properties"]["action"]["enum"],
                list(ACTIONS),
            )

            res_uris = [item["uri"] for item in responses[2]["result"]["resources"]]
            self.assertEqual(
                res_uris,
                [
                    "parrhesia://contract",
                    "parrhesia://cases",
                    "parrhesia://claim-graph",
                    "parrhesia://calibration",
                ],
            )
            tpl_uris = [item["uriTemplate"] for item in responses[3]["result"]["resourceTemplates"]]
            self.assertEqual(
                tpl_uris,
                [
                    "parrhesia://contract/{section}",
                    "parrhesia://cases",
                    "parrhesia://claim-graph",
                    "parrhesia://calibration",
                    "parrhesia://cases/{case_id}",
                    "parrhesia://cases/{case_id}/ceilings",
                    "parrhesia://cases/{case_id}/triggers",
                    "parrhesia://cases/{case_id}/packet/{role}",
                ],
            )
            prompt_names = [item["name"] for item in responses[4]["result"]["prompts"]]
            self.assertEqual(
                prompt_names,
                [
                    "parrhesia_review_overclaim",
                    "parrhesia_review_underclaim",
                    "parrhesia_adjudicate",
                ],
            )

    def test_parrhesia_validate_dry_run_and_zero_mutation(self):
        with tempfile.TemporaryDirectory() as workspace:
            ws = Path(workspace)
            (ws / "trial.md").write_text(
                "Trial hazard ratio HR 0.72 (95% CI 0.56 to 0.93, p = 0.012); SAE in 12/80 (15.0%).\n",
                encoding="utf-8",
            )
            (ws / "protocol.md").write_text(
                "Prespecified primary overall survival hazard ratio prior to unblinding.\n",
                encoding="utf-8",
            )
            setup = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request("tools/list", id=2),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {
                                "action": "create_case",
                                "payload": {"question": "Valid?", "draft": "Draft text"},
                            },
                        },
                        3,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {
                                "action": "create_case",
                                "payload": {"question": "Legacy", "draft": "Draft", "schema_version": 1},
                            },
                        },
                        4,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {"action": "not-an-action", "payload": {}},
                        },
                        5,
                    ),
                ],
            )
            tools = {tool["name"]: tool for tool in setup[1]["result"]["tools"]}
            validate_schema = tools["parrhesia_validate"]["outputSchema"]

            self.assertFalse(setup[2]["result"]["isError"])
            valid_create = setup[2]["result"]["structuredContent"]
            _assert_valid_against_schema(self, valid_create, validate_schema, "validate_valid")
            self.assertTrue(valid_create["valid"])
            self.assertTrue(valid_create["dry_run"])
            self.assertEqual(valid_create["action"], "create_case")
            self.assertIn("preview", valid_create)

            # Invalid payload returns isError=False with valid=False and repair_hint!
            self.assertFalse(setup[3]["result"]["isError"])
            invalid_create = setup[3]["result"]["structuredContent"]
            _assert_valid_against_schema(self, invalid_create, validate_schema, "validate_invalid")
            self.assertFalse(invalid_create["valid"])
            self.assertTrue(invalid_create["dry_run"])
            self.assertEqual(invalid_create["error"], "legacy_creation_disabled")
            self.assertIn("schema_version=2", invalid_create["repair_hint"])

            # Invalid action enum on parrhesia_validate still returns isError=True with repair_hint.
            self.assertTrue(setup[4]["result"]["isError"])
            invalid_action_err = json.loads(setup[4]["result"]["content"][0]["text"])
            self.assertEqual(invalid_action_err["error"], "invalid_value")
            self.assertFalse(invalid_action_err["repair_hint"].startswith("[not-an-action]"))

            # Confirm zero cases were created by dry-run validations.
            with closing(sqlite3.connect(ws / ".parrhesia/state.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM cases").fetchone()[0], 0)

            # Now create a real case, register evidence/hypothesis, scaffold claim, and dry-run invalid effect_records.
            prep = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_create_case",
                            "arguments": {"question": "Survival?", "draft": "Draft text"},
                        },
                        2,
                    ),
                ],
            )
            case_id = prep[1]["result"]["structuredContent"]["case_id"]
            ev_res = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "trial.md",
                                "kind": "intervention",
                                "provenance": "observed",
                                "quote": "HR 0.72 (95% CI 0.56 to 0.93, p = 0.012); SAE in 12/80 (15.0%).",
                                "location": "Table 1, L1",
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "protocol.md",
                                "kind": "observation",
                                "provenance": "observed",
                                "quote": "Prespecified primary overall survival hazard ratio prior to unblinding.",
                                "location": "Protocol L1",
                            },
                        },
                        3,
                    ),
                ],
            )
            ev_trial = ev_res[1]["result"]["structuredContent"]["evidence_id"]
            ev_proto = ev_res[2]["result"]["structuredContent"]["evidence_id"]
            hyp_res = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_hypothesis",
                            "arguments": {
                                "case_id": case_id,
                                "statement": "Treatment X lowers hazard",
                                "timing_basis": "reported_prespecified",
                                "source_evidence_id": ev_proto,
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_scaffold_claim",
                            "arguments": {
                                "case_id": case_id,
                                "claim_id": "c1",
                                "claim_type": "association",
                                "evidence_level": "adjusted",
                                "claim_basis": "empirical",
                                "design_families": ["randomized"],
                                "include_effect_records": True,
                            },
                        },
                        3,
                    ),
                ],
            )
            hyp_id = hyp_res[1]["result"]["structuredContent"]["hypothesis_id"]
            scaffold = hyp_res[2]["result"]["structuredContent"]["claim"]
            base_claim = self._populate_claim_from_scaffold(
                scaffold,
                ev_efficacy=ev_trial,
                ev_protocol=ev_proto,
                hypothesis_id=hyp_id,
            )

            # Test dry-run validation of valid vs bad effect_records.
            bad_interval = json.loads(json.dumps(base_claim))
            bad_interval["effect_records"][0]["ci_low"] = 0.95

            bad_p_ci = json.loads(json.dumps(base_claim))
            bad_p_ci["effect_records"][0]["p_value"] = 0.42

            bad_grim = json.loads(json.dumps(base_claim))
            bad_grim["effect_records"][1]["estimate"] = 15.1
            bad_grim["effect_records"][1].pop("events", None)

            val_checks = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {
                                "action": "set_ledger",
                                "payload": {"case_id": case_id, "claims": [base_claim]},
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {
                                "action": "set_ledger",
                                "payload": {"case_id": case_id, "claims": [bad_interval]},
                            },
                        },
                        3,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {
                                "action": "set_ledger",
                                "payload": {"case_id": case_id, "claims": [bad_p_ci]},
                            },
                        },
                        4,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_validate",
                            "arguments": {
                                "action": "set_ledger",
                                "payload": {"case_id": case_id, "claims": [bad_grim]},
                            },
                        },
                        5,
                    ),
                ],
            )
            self.assertTrue(val_checks[1]["result"]["structuredContent"]["valid"], val_checks[1])

            for idx, expected_code in (
                (2, "effect_interval_inconsistent"),
                (3, "effect_pvalue_ci_mismatch"),
                (4, "effect_grim_inconsistent"),
            ):
                self.assertFalse(val_checks[idx]["result"]["isError"], val_checks[idx])
                body = val_checks[idx]["result"]["structuredContent"]
                _assert_valid_against_schema(self, body, validate_schema, f"val_err_{expected_code}")
                self.assertFalse(body["valid"], body)
                self.assertEqual(body["error"], expected_code, body)
                self.assertTrue(body["repair_hint"], body)

            # Verify case still has zero claims and zero spurious events from dry-run validations.
            after_case = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request("tools/call", {"name": "parrhesia_get_case", "arguments": {"case_id": case_id}}, 2),
                ],
            )[1]["result"]["structuredContent"]
            self.assertEqual(after_case["state"], "draft")
            self.assertEqual(after_case["claims"], [])
            event_actions = [ev["action"] for ev in after_case["events"]]
            self.assertNotIn("set_ledger", event_actions)

    def test_typed_end_to_end_workflow_with_effects_resources_and_prompts(self):
        with tempfile.TemporaryDirectory() as workspace:
            ws = Path(workspace)
            trial_text = (
                "# Phase 2 Randomized Trial Results\n\n"
                "In adult Stage III patients (N = 160), overall survival HR 0.72 (95% CI 0.56 to 0.93, p = 0.012) "
                "favoring Treatment X, with serious adverse events in 12/80 (15.0%) patients.\n"
            )
            trial_quote = (
                "overall survival HR 0.72 (95% CI 0.56 to 0.93, p = 0.012) "
                "favoring Treatment X, with serious adverse events in 12/80 (15.0%) patients."
            )
            proto_text = (
                "# Prespecified Protocol\n\n"
                "Primary endpoint overall survival hazard ratio for Treatment X versus standard care prespecified before database lock.\n"
            )
            proto_quote = (
                "Primary endpoint overall survival hazard ratio for Treatment X versus standard care prespecified before database lock."
            )
            (ws / "trial.md").write_text(trial_text, encoding="utf-8")
            (ws / "protocol.md").write_text(proto_text, encoding="utf-8")

            # Batch 1: list tools, create case, register evidence/hypothesis, scaffold claim.
            b1 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request("tools/list", id=2),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_create_case",
                            "arguments": {
                                "question": "Does Treatment X improve overall survival in Stage III patients?",
                                "draft": "Treatment X lowers mortality hazard (HR 0.72) with 15.0% serious adverse events.",
                                "domain": "scientific",
                                "writer_context_id": "writer-ctx-1",
                                "schema_version": 2,
                                "blind": True,
                            },
                        },
                        3,
                    ),
                ],
            )
            tools = {tool["name"]: tool for tool in b1[1]["result"]["tools"]}
            create_out = b1[2]["result"]["structuredContent"]
            _assert_valid_against_schema(self, create_out, tools["parrhesia_create_case"]["outputSchema"], "create_case")
            case_id = create_out["case_id"]

            b2 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "trial.md",
                                "kind": "intervention",
                                "provenance": "observed",
                                "label": "Phase 2 RCT report",
                                "quote": trial_quote,
                                "location": "Section 2.1, Table 1, L3",
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "protocol.md",
                                "kind": "observation",
                                "provenance": "observed",
                                "label": "Prespecified trial protocol",
                                "quote": proto_quote,
                                "location": "Protocol Section 3.2, L3",
                            },
                        },
                        3,
                    ),
                ],
            )
            ev_trial_out = b2[1]["result"]["structuredContent"]
            ev_proto_out = b2[2]["result"]["structuredContent"]
            _assert_valid_against_schema(self, ev_trial_out, tools["parrhesia_register_evidence"]["outputSchema"], "register_ev_1")
            _assert_valid_against_schema(self, ev_proto_out, tools["parrhesia_register_evidence"]["outputSchema"], "register_ev_2")
            ev_trial = ev_trial_out["evidence_id"]
            ev_proto = ev_proto_out["evidence_id"]

            b3 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_hypothesis",
                            "arguments": {
                                "case_id": case_id,
                                "statement": "Treatment X reduces mortality hazard versus standard care.",
                                "timing_basis": "reported_prespecified",
                                "source_evidence_id": ev_proto,
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_scaffold_claim",
                            "arguments": {
                                "case_id": case_id,
                                "claim_id": "c1",
                                "claim_type": "association",
                                "evidence_level": "adjusted",
                                "claim_basis": "empirical",
                                "design_families": ["randomized"],
                                "include_effect_records": True,
                            },
                        },
                        3,
                    ),
                ],
            )
            hyp_out = b3[1]["result"]["structuredContent"]
            scaf_out = b3[2]["result"]["structuredContent"]
            _assert_valid_against_schema(self, hyp_out, tools["parrhesia_register_hypothesis"]["outputSchema"], "register_hyp")
            _assert_valid_against_schema(self, scaf_out, tools["parrhesia_scaffold_claim"]["outputSchema"], "scaffold_claim")

            claim = self._populate_claim_from_scaffold(
                scaf_out["claim"],
                ev_efficacy=ev_trial,
                ev_protocol=ev_proto,
                hypothesis_id=hyp_out["hypothesis_id"],
            )

            # Set ledger, inspect dynamic resources before freeze, and freeze.
            b4 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_set_ledger",
                            "arguments": {"case_id": case_id, "claims": [claim]},
                        },
                        2,
                    ),
                    request("resources/read", {"uri": "parrhesia://cases"}, 3),
                    request("resources/read", {"uri": f"parrhesia://cases/{case_id}"}, 4),
                    request("resources/read", {"uri": f"parrhesia://cases/{case_id}/ceilings"}, 5),
                    request("resources/read", {"uri": f"parrhesia://cases/{case_id}/packet/overclaim"}, 6),
                    request("resources/read", {"uri": "parrhesia://cases/missing-case"}, 7),
                    request("resources/read", {"uri": f"parrhesia://cases/{case_id}/packet/bogus"}, 8),
                    request("tools/call", {"name": "parrhesia_freeze", "arguments": {"case_id": case_id}}, 9),
                ],
            )
            ledger_out = b4[1]["result"]["structuredContent"]
            _assert_valid_against_schema(self, ledger_out, tools["parrhesia_set_ledger"]["outputSchema"], "set_ledger")
            cases_doc = json.loads(b4[2]["result"]["contents"][0]["text"])
            self.assertEqual(cases_doc["count"], 1)
            self.assertEqual(cases_doc["cases"][0]["case_id"], case_id)
            case_res_doc = json.loads(b4[3]["result"]["contents"][0]["text"])
            self.assertEqual(case_res_doc["case_id"], case_id)
            ceilings_doc = json.loads(b4[4]["result"]["contents"][0]["text"])
            self.assertEqual(ceilings_doc["case_id"], case_id)
            self.assertEqual(ceilings_doc["effect_record_counts"]["c1"], 2)
            # Packet before freeze -> -32002; missing case -> -32002; invalid role -> -32602.
            self.assertEqual(b4[5]["error"]["code"], -32002)
            self.assertEqual(b4[6]["error"]["code"], -32002)
            self.assertEqual(b4[7]["error"]["code"], -32602)

            freeze_out = b4[8]["result"]["structuredContent"]
            _assert_valid_against_schema(self, freeze_out, tools["parrhesia_freeze"]["outputSchema"], "freeze")

            # Fetch prompts (no-arg + live isolated case_id), packets, and verify blind isolation.
            b5 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request("prompts/get", {"name": "parrhesia_review_overclaim"}, 2),
                    request(
                        "prompts/get",
                        {"name": "parrhesia_review_overclaim", "arguments": {"case_id": case_id}},
                        3,
                    ),
                    request(
                        "prompts/get",
                        {"name": "parrhesia_review_underclaim", "arguments": {"case_id": case_id}},
                        4,
                    ),
                    request(
                        "prompts/get",
                        {"name": "parrhesia_adjudicate", "arguments": {"case_id": case_id}},
                        5,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_review_packet",
                            "arguments": {"case_id": case_id, "role": "overclaim"},
                        },
                        6,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_review_packet",
                            "arguments": {"case_id": case_id, "role": "underclaim"},
                        },
                        7,
                    ),
                    request("resources/read", {"uri": f"parrhesia://cases/{case_id}/packet/overclaim"}, 8),
                ],
            )
            prompt_noarg = b5[1]["result"]
            self.assertEqual(prompt_noarg["messages"][0]["role"], "user")
            prompt_over = b5[2]["result"]
            self.assertEqual(prompt_over["messages"][0]["role"], "user")
            prompt_over_text = prompt_over["messages"][0]["content"]["text"]
            self.assertIn(case_id, prompt_over_text)
            # Blind isolation check: draft is hidden (null) in injected isolated review packet.
            self.assertIn('"draft": null', prompt_over_text)
            self.assertEqual(b5[3]["result"]["messages"][0]["role"], "user")
            # Adjudication packet is not built yet -> -32002.
            self.assertEqual(b5[4]["error"]["code"], -32002)

            over_pkt = b5[5]["result"]["structuredContent"]
            under_pkt = b5[6]["result"]["structuredContent"]
            _assert_valid_against_schema(self, over_pkt, tools["parrhesia_review_packet"]["outputSchema"], "over_pkt")
            _assert_valid_against_schema(self, under_pkt, tools["parrhesia_review_packet"]["outputSchema"], "under_pkt")
            self.assertIsNone(over_pkt["draft"])
            self.assertEqual(json.loads(b5[7]["result"]["contents"][0]["text"])["packet_id"], over_pkt["packet_id"])

            # Submit both reviews and obtain adjudication packet.
            proposed_text = (
                "In this phase 2 trial of adult Stage III patients (N=160), Treatment X was associated "
                "with lower mortality hazard (HR 0.72, 95% CI 0.56 to 0.93, p = 0.012), pending confirmatory phase 3 validation."
            )
            b6 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_submit_review",
                            "arguments": {
                                "case_id": case_id,
                                "role": "overclaim",
                                "packet_id": over_pkt["packet_id"],
                                "input_digest": over_pkt["input_digest"],
                                "reviewer": {"context_id": "over-ctx-1", "model": "test-model"},
                                "covered_claim_ids": ["c1"],
                                "findings": [
                                    {
                                        "id": "f1",
                                        "claim_id": "c1",
                                        "evidence_ids": [ev_trial, ev_proto],
                                        "issue": "Make single phase 2 trial boundary explicit by noting pending confirmatory phase 3 validation.",
                                        "proposed_claim_type": "association",
                                        "proposed_evidence_level": "adjusted",
                                        "proposed_scope": "Adult Stage III patients in phase 2 trial",
                                        "proposed_claim_basis": "empirical",
                                        "proposed_text": proposed_text,
                                        "decision_impact": "Clarifies confirmatory phase 3 status without weakening internal HR.",
                                    }
                                ],
                                "claim_stances": [
                                    {
                                        "claim_id": "c1",
                                        "stance": "supported",
                                        "rationale": "Trial report HR 0.72 and prespecified protocol checks support association x adjusted.",
                                        "evidence_ids": [ev_trial, ev_proto],
                                    }
                                ],
                                "unread_evidence_ids": [],
                                "review_status": "complete",
                                "isolation_attestation": {
                                    "history_inheritance": "none",
                                    "memory_access": "disabled",
                                    "host_surface": "mcp_test",
                                },
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_submit_review",
                            "arguments": {
                                "case_id": case_id,
                                "role": "underclaim",
                                "packet_id": under_pkt["packet_id"],
                                "input_digest": under_pkt["input_digest"],
                                "reviewer": {"context_id": "under-ctx-1", "model": "test-model"},
                                "covered_claim_ids": ["c1"],
                                "findings": [],
                                "claim_stances": [
                                    {
                                        "claim_id": "c1",
                                        "stance": "supported",
                                        "rationale": "Prespecified HR 0.72 CI 0.56-0.93 supports the claimed survival association.",
                                        "evidence_ids": [ev_trial, ev_proto],
                                    }
                                ],
                                "unread_evidence_ids": [],
                                "review_status": "complete",
                                "isolation_attestation": {
                                    "history_inheritance": "none",
                                    "memory_access": "disabled",
                                    "host_surface": "mcp_test",
                                },
                            },
                        },
                        3,
                    ),
                    request(
                        "tools/call",
                        {"name": "parrhesia_adjudication_packet", "arguments": {"case_id": case_id}},
                        4,
                    ),
                ],
            )
            sub_over = b6[1]["result"]["structuredContent"]
            sub_under = b6[2]["result"]["structuredContent"]
            adj_pkt = b6[3]["result"]["structuredContent"]
            _assert_valid_against_schema(self, sub_over, tools["parrhesia_submit_review"]["outputSchema"], "sub_over")
            _assert_valid_against_schema(self, sub_under, tools["parrhesia_submit_review"]["outputSchema"], "sub_under")
            _assert_valid_against_schema(self, adj_pkt, tools["parrhesia_adjudication_packet"]["outputSchema"], "adj_pkt")

            # Prompt + resource read for adjudication packet should now succeed.
            b7 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "prompts/get",
                        {"name": "parrhesia_adjudicate", "arguments": {"case_id": case_id}},
                        2,
                    ),
                    request("resources/read", {"uri": f"parrhesia://cases/{case_id}/packet/adjudication"}, 3),
                ],
            )
            adj_prompt = b7[1]["result"]
            self.assertEqual(adj_prompt["messages"][0]["role"], "user")
            self.assertIn(adj_pkt["adjudication_id"], adj_prompt["messages"][0]["content"]["text"])
            self.assertEqual(
                json.loads(b7[2]["result"]["contents"][0]["text"])["adjudication_id"],
                adj_pkt["adjudication_id"],
            )

            # Submit adjudication, verify, human decision, export, and read back full case.
            revised_text = proposed_text
            b8 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_submit_adjudication",
                            "arguments": {
                                "case_id": case_id,
                                "adjudication_id": adj_pkt["adjudication_id"],
                                "input_digest": adj_pkt["input_digest"],
                                "adjudicator": {"context_id": "adj-ctx-1", "model": "test-model"},
                                "decisions": [
                                    {
                                        "claim_id": "c1",
                                        "verdict": "supported",
                                        "claim_type": "association",
                                        "evidence_level": "adjusted",
                                        "claim_basis": "empirical",
                                        "scope": "Adult Stage III patients in phase 2 trial",
                                        "revised_text": revised_text,
                                        "rationale": (
                                            "Passing randomized_trial checks, statistical_report checks, protocol card, "
                                            "and HR 0.72 (95% CI 0.56 to 0.93, p = 0.012) support association x adjusted."
                                        ),
                                        "evidence_ids": [ev_trial, ev_proto],
                                        "confidence": "high",
                                        "confidence_reason": "Primary HR effect and protocol prespecification verified directly.",
                                        "boundary": "Applies to adult Stage III phase 2 population prior to phase 3 confirmation.",
                                        "reversal_condition": "Confirmatory phase 3 trial shows HR >= 1.0 or primary efficacy failure.",
                                    }
                                ],
                                "dispositions": [
                                    {
                                        "finding_id": "f1",
                                        "claim_id": "c1",
                                        "disposition": "accepted",
                                        "reason": "Adopted explicit confirmatory phase 3 caveat in scope and revised_text.",
                                        "resolution": "incorporated",
                                        "revised_text_quote": "pending confirmatory phase 3 validation",
                                    }
                                ],
                                "unread_evidence_ids": [],
                                "isolation_attestation": {
                                    "history_inheritance": "packets_only",
                                    "memory_access": "disabled",
                                    "host_surface": "mcp_test",
                                },
                            },
                        },
                        2,
                    ),
                    request("tools/call", {"name": "parrhesia_verify", "arguments": {"case_id": case_id}}, 3),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_record_human_decision",
                            "arguments": {
                                "case_id": case_id,
                                "decision": "accept",
                                "responsible_human": "Dr. Reviewer",
                                "reason": "Verified evidence anchors, effect checks, and report scope.",
                            },
                        },
                        4,
                    ),
                    request(
                        "tools/call",
                        {"name": "parrhesia_export", "arguments": {"case_id": case_id, "path": "exports/report.md"}},
                        5,
                    ),
                    request("tools/call", {"name": "parrhesia_get_case", "arguments": {"case_id": case_id}}, 6),
                ],
            )
            for idx in range(1, 6):
                self.assertFalse(b8[idx]["result"]["isError"], b8[idx]["result"])
            sub_adj = b8[1]["result"]["structuredContent"]
            verify_out = b8[2]["result"]["structuredContent"]
            human_out = b8[3]["result"]["structuredContent"]
            export_out = b8[4]["result"]["structuredContent"]
            get_out = b8[5]["result"]["structuredContent"]

            _assert_valid_against_schema(self, sub_adj, tools["parrhesia_submit_adjudication"]["outputSchema"], "sub_adj")
            _assert_valid_against_schema(self, verify_out, tools["parrhesia_verify"]["outputSchema"], "verify")
            _assert_valid_against_schema(self, human_out, tools["parrhesia_record_human_decision"]["outputSchema"], "human_decision")
            _assert_valid_against_schema(self, export_out, tools["parrhesia_export"]["outputSchema"], "export")
            _assert_valid_against_schema(self, get_out, tools["parrhesia_get_case"]["outputSchema"], "get_case")

            self.assertEqual(verify_out["status"], "pass")
            self.assertEqual(verify_out["event_chain_status"], "verified")
            self.assertIn("effect_checks", verify_out)
            self.assertEqual(get_out["state"], "exported")
            export_text = (ws / "exports" / "report.md").read_text(encoding="utf-8")
            self.assertIn("HR 0.72", export_text)

            # Backward-compatibility sanity check for parrhesia_workflow read action.
            compat = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_workflow",
                            "arguments": {"action": "get_case", "payload": {"case_id": case_id}},
                        },
                        2,
                    ),
                ],
            )
            self.assertFalse(compat[1]["result"]["isError"])
            self.assertEqual(compat[1]["result"]["structuredContent"]["state"], "exported")

    def _assert_adjudication_repair_hint(
        self,
        setup_fn,
        expected_code: str,
        hint_needle: str,
        *,
        check_invalid_state: bool = False,
    ) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            ws = Path(workspace)
            trial_quote = (
                "Treatment X overall survival HR 0.72 (95% CI 0.56 to 0.93, p = 0.012) in Stage III patients; "
                "null HR 1.05 (95% CI 0.85 to 1.30, p = 0.65)."
            )
            proto_quote = (
                "Treatment X overall survival prespecified primary endpoint protocol for Stage III patients prior to lock."
            )
            (ws / "trial.md").write_text(trial_quote + "\n", encoding="utf-8")
            (ws / "protocol.md").write_text(proto_quote + "\n", encoding="utf-8")
            (ws / "run.py").write_text("print('ok')\n", encoding="utf-8")

            prep = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_create_case",
                            "arguments": {"question": "Hints?", "draft": "Draft text"},
                        },
                        2,
                    ),
                ],
            )
            case_id = prep[1]["result"]["structuredContent"]["case_id"]
            ev_res = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "trial.md",
                                "kind": "intervention",
                                "provenance": "observed",
                                "quote": trial_quote,
                                "location": "Table 1, L1",
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "protocol.md",
                                "kind": "observation",
                                "provenance": "observed",
                                "quote": proto_quote,
                                "location": "Protocol L1",
                            },
                        },
                        3,
                    ),
                ],
            )
            ev_trial = ev_res[1]["result"]["structuredContent"]["evidence_id"]
            ev_proto = ev_res[2]["result"]["structuredContent"]["evidence_id"]
            meta = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_hypothesis",
                            "arguments": {
                                "case_id": case_id,
                                "statement": "Treatment X overall survival in Stage III patients",
                                "timing_basis": "reported_prespecified",
                                "source_evidence_id": ev_proto,
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_scaffold_claim",
                            "arguments": {
                                "case_id": case_id,
                                "claim_id": "c1",
                                "claim_type": "association",
                                "evidence_level": "adjusted",
                                "claim_basis": "empirical",
                                "design_families": ["randomized"],
                                "include_effect_records": True,
                            },
                        },
                        3,
                    ),
                ],
            )
            hyp_id = meta[1]["result"]["structuredContent"]["hypothesis_id"]
            claim = self._populate_claim_from_scaffold(
                meta[2]["result"]["structuredContent"]["claim"],
                ev_efficacy=ev_trial,
                ev_protocol=ev_proto,
                hypothesis_id=hyp_id,
            )
            claim["text"] = "Treatment X overall survival hazard ratio HR 0.72 (95% CI 0.56 to 0.93) in Stage III patients."
            claim["effect_records"] = []
            setup_fn(ws, case_id, ev_trial, claim)

            flow = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {"name": "parrhesia_set_ledger", "arguments": {"case_id": case_id, "claims": [claim]}},
                        2,
                    ),
                    request("tools/call", {"name": "parrhesia_freeze", "arguments": {"case_id": case_id}}, 3),
                    request(
                        "tools/call",
                        {"name": "parrhesia_review_packet", "arguments": {"case_id": case_id, "role": "overclaim"}},
                        4,
                    ),
                    request(
                        "tools/call",
                        {"name": "parrhesia_review_packet", "arguments": {"case_id": case_id, "role": "underclaim"}},
                        5,
                    ),
                ],
            )
            self.assertFalse(flow[1]["result"]["isError"], flow[1])
            self.assertFalse(flow[2]["result"]["isError"], flow[2])
            over_pkt = flow[3]["result"]["structuredContent"]
            under_pkt = flow[4]["result"]["structuredContent"]

            rev_flow = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_submit_review",
                            "arguments": {
                                "case_id": case_id,
                                "role": "overclaim",
                                "packet_id": over_pkt["packet_id"],
                                "input_digest": over_pkt["input_digest"],
                                "reviewer": {"context_id": "over-h-1", "model": "test-model"},
                                "covered_claim_ids": ["c1"],
                                "findings": [],
                                "claim_stances": [
                                    {
                                        "claim_id": "c1",
                                        "stance": "insufficient_evidence",
                                        "rationale": "Pending adjudicator check.",
                                        "evidence_ids": [ev_trial, ev_proto],
                                    }
                                ],
                                "unread_evidence_ids": [],
                                "review_status": "complete",
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_submit_review",
                            "arguments": {
                                "case_id": case_id,
                                "role": "underclaim",
                                "packet_id": under_pkt["packet_id"],
                                "input_digest": under_pkt["input_digest"],
                                "reviewer": {"context_id": "under-h-1", "model": "test-model"},
                                "covered_claim_ids": ["c1"],
                                "findings": [],
                                "claim_stances": [
                                    {
                                        "claim_id": "c1",
                                        "stance": "insufficient_evidence",
                                        "rationale": "Pending adjudicator check.",
                                        "evidence_ids": [ev_trial, ev_proto],
                                    }
                                ],
                                "unread_evidence_ids": [],
                                "review_status": "complete",
                            },
                        },
                        3,
                    ),
                    request("tools/call", {"name": "parrhesia_adjudication_packet", "arguments": {"case_id": case_id}}, 4),
                ],
            )
            adj_pkt = rev_flow[3]["result"]["structuredContent"]
            adj_payload = {
                "case_id": case_id,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": "adj-h-1", "model": "test-model"},
                "decisions": [
                    {
                        "claim_id": "c1",
                        "verdict": "supported",
                        "claim_type": "association",
                        "evidence_level": "adjusted",
                        "claim_basis": "empirical",
                        "scope": "Adult Stage III patients",
                        "revised_text": (
                            "Treatment X overall survival hazard ratio HR 0.72 "
                            "(95% CI 0.56 to 0.93, p = 0.012) in Stage III patients."
                        ),
                        "rationale": "Trial report HR and prespecified protocol checks support association.",
                        "evidence_ids": [ev_trial, ev_proto],
                        "confidence": "high",
                        "confidence_reason": "Verified primary outcome.",
                        "boundary": "Adult Stage III population.",
                        "reversal_condition": "Phase 3 trial fails.",
                    }
                ],
                "dispositions": [],
                "unread_evidence_ids": [],
            }
            calls = [
                INITIALIZE,
                request(
                    "tools/call",
                    {
                        "name": "parrhesia_validate",
                        "arguments": {"action": "submit_adjudication", "payload": adj_payload},
                    },
                    2,
                ),
                request("tools/call", {"name": "parrhesia_submit_adjudication", "arguments": adj_payload}, 3),
            ]
            if check_invalid_state:
                calls.append(
                    request(
                        "tools/call",
                        {"name": "parrhesia_set_ledger", "arguments": {"case_id": case_id, "claims": [claim]}},
                        4,
                    )
                )
            res = self.exchange(ws, calls)
            self.assertFalse(res[1]["result"]["isError"])
            val_body = res[1]["result"]["structuredContent"]
            self.assertFalse(val_body["valid"], val_body)
            self.assertEqual(val_body["error"], expected_code, val_body)
            self.assertIn(hint_needle, val_body["repair_hint"])

            self.assertTrue(res[2]["result"]["isError"], res[2])
            mut_err = json.loads(res[2]["result"]["content"][0]["text"])
            self.assertEqual(mut_err["error"], expected_code, mut_err)
            self.assertIn(hint_needle, mut_err["repair_hint"])

            if check_invalid_state:
                self.assertTrue(res[3]["result"]["isError"])
                state_err = json.loads(res[3]["result"]["content"][0]["text"])
                self.assertEqual(state_err["error"], "invalid_state")
                self.assertIn("state='draft'", state_err["repair_hint"])

    def test_repair_hints_on_contract_errors(self):
        with tempfile.TemporaryDirectory() as workspace:
            ws = Path(workspace)
            (ws / "trial.md").write_text(
                "Overall survival HR 0.72 (95% CI 0.56 to 0.93, p = 0.012); SAE in 12/80 (15.0%).\n",
                encoding="utf-8",
            )
            (ws / "protocol.md").write_text(
                "Prespecified primary endpoint protocol text prior to lock.\n",
                encoding="utf-8",
            )
            b1 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_create_case",
                            "arguments": {"question": "Hints?", "draft": "Draft text"},
                        },
                        2,
                    ),
                ],
            )
            case_id = b1[1]["result"]["structuredContent"]["case_id"]

            # Trigger missing_field (with [set_ledger] prefix), human_paused, missing_ledger,
            # effect_pvalue_ci_mismatch, and effect_grim_inconsistent on mutating tools.
            b2 = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {"name": "parrhesia_set_ledger", "arguments": {"case_id": case_id, "claims": [{}]}},
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_record_human_decision",
                            "arguments": {
                                "case_id": case_id,
                                "decision": "pause",
                                "responsible_human": "Lead PI",
                                "reason": "Check pause repair hint.",
                            },
                        },
                        3,
                    ),
                    request("tools/call", {"name": "parrhesia_freeze", "arguments": {"case_id": case_id}}, 4),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_record_human_decision",
                            "arguments": {
                                "case_id": case_id,
                                "decision": "accept",
                                "responsible_human": "Lead PI",
                                "reason": "Resume draft.",
                            },
                        },
                        5,
                    ),
                    request("tools/call", {"name": "parrhesia_freeze", "arguments": {"case_id": case_id}}, 6),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "trial.md",
                                "kind": "intervention",
                                "provenance": "observed",
                                "quote": "Overall survival HR 0.72 (95% CI 0.56 to 0.93, p = 0.012); SAE in 12/80 (15.0%).",
                                "location": "L1",
                            },
                        },
                        7,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_evidence",
                            "arguments": {
                                "case_id": case_id,
                                "path": "protocol.md",
                                "kind": "observation",
                                "provenance": "observed",
                                "quote": "Prespecified primary endpoint protocol text prior to lock.",
                                "location": "L1",
                            },
                        },
                        8,
                    ),
                ],
            )
            missing_err = json.loads(b2[1]["result"]["content"][0]["text"])
            self.assertTrue(b2[1]["result"]["isError"])
            self.assertEqual(missing_err["error"], "missing_field")
            self.assertTrue(missing_err["repair_hint"].startswith("[set_ledger]"))

            paused_err = json.loads(b2[3]["result"]["content"][0]["text"])
            self.assertTrue(b2[3]["result"]["isError"])
            self.assertEqual(paused_err["error"], "human_paused")
            self.assertIn("parrhesia_record_human_decision", paused_err["repair_hint"])

            missing_ledger_err = json.loads(b2[5]["result"]["content"][0]["text"])
            self.assertEqual(missing_ledger_err["error"], "missing_ledger")
            self.assertIn("parrhesia_set_ledger", missing_ledger_err["repair_hint"])

            ev_trial = b2[6]["result"]["structuredContent"]["evidence_id"]
            ev_proto = b2[7]["result"]["structuredContent"]["evidence_id"]
            meta = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_register_hypothesis",
                            "arguments": {
                                "case_id": case_id,
                                "statement": "Effects check",
                                "timing_basis": "reported_prespecified",
                                "source_evidence_id": ev_proto,
                            },
                        },
                        2,
                    ),
                    request(
                        "tools/call",
                        {
                            "name": "parrhesia_scaffold_claim",
                            "arguments": {
                                "case_id": case_id,
                                "claim_id": "c1",
                                "claim_type": "association",
                                "evidence_level": "adjusted",
                                "claim_basis": "empirical",
                                "design_families": ["randomized"],
                                "include_effect_records": True,
                            },
                        },
                        3,
                    ),
                ],
            )
            base = self._populate_claim_from_scaffold(
                meta[2]["result"]["structuredContent"]["claim"],
                ev_efficacy=ev_trial,
                ev_protocol=ev_proto,
                hypothesis_id=meta[1]["result"]["structuredContent"]["hypothesis_id"],
            )
            bad_pci = json.loads(json.dumps(base))
            bad_pci["effect_records"][0]["p_value"] = 0.42
            bad_grim = json.loads(json.dumps(base))
            bad_grim["effect_records"][1]["estimate"] = 15.1
            bad_grim["effect_records"][1].pop("events", None)

            mut_fx = self.exchange(
                ws,
                [
                    INITIALIZE,
                    request(
                        "tools/call",
                        {"name": "parrhesia_set_ledger", "arguments": {"case_id": case_id, "claims": [bad_pci]}},
                        2,
                    ),
                    request(
                        "tools/call",
                        {"name": "parrhesia_set_ledger", "arguments": {"case_id": case_id, "claims": [bad_grim]}},
                        3,
                    ),
                ],
            )
            self.assertTrue(mut_fx[1]["result"]["isError"])
            pci_err = json.loads(mut_fx[1]["result"]["content"][0]["text"])
            self.assertEqual(pci_err["error"], "effect_pvalue_ci_mismatch")
            self.assertIn("p_value", pci_err["repair_hint"])

            self.assertTrue(mut_fx[2]["result"]["isError"])
            grim_err = json.loads(mut_fx[2]["result"]["content"][0]["text"])
            self.assertEqual(grim_err["error"], "effect_grim_inconsistent")
            self.assertIn("integer count k/n", grim_err["repair_hint"])

        def setup_omission(ws: Path, case_id: str, _ev_trial: str, _claim: dict) -> None:
            exec_res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "parrhesia",
                    "record-exec",
                    "--workspace",
                    str(ws),
                    "--case-id",
                    case_id,
                    "--claim-id",
                    "c1",
                    "--fork-role",
                    "exploratory",
                    "--log-path",
                    "exports/run.log",
                    "--",
                    sys.executable,
                    "run.py",
                ],
                cwd=ROOT,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(exec_res.returncode, 0, exec_res.stderr.decode("utf-8", errors="replace"))

        def setup_null(ws: Path, case_id: str, ev_trial: str, claim: dict) -> None:
            claim["effect_records"] = [
                {
                    "id": "e1",
                    "endpoint": "Overall survival",
                    "endpoint_role": "primary",
                    "metric": "HR",
                    "estimate": 1.05,
                    "null_value": 1.0,
                    "ci_level": 0.95,
                    "ci_low": 0.85,
                    "ci_high": 1.30,
                    "p_value": 0.65,
                    "direction": "null",
                    "claim_direction": "benefit",
                    "beneficial_if": "below_null",
                    "evidence_id": ev_trial,
                    "quote_substring": "null HR 1.05 (95% CI 0.85 to 1.30, p = 0.65)",
                }
            ]

        def setup_unanchored(ws: Path, case_id: str, ev_trial: str, claim: dict) -> None:
            claim["effect_records"] = [
                {
                    "id": "e1",
                    "endpoint": "Overall survival",
                    "endpoint_role": "primary",
                    "metric": "HR",
                    "estimate": 0.71,
                    "null_value": 1.0,
                    "ci_level": 0.95,
                    "ci_low": 0.56,
                    "ci_high": 0.93,
                    "p_value": 0.012,
                    "direction": "benefit",
                    "beneficial_if": "below_null",
                    "evidence_id": ev_trial,
                    "quote_substring": "Treatment X overall survival HR 0.72 (95% CI 0.56 to 0.93, p = 0.012)",
                }
            ]

        self._assert_adjudication_repair_hint(
            setup_omission,
            "selective_execution_omission",
            "provenance_cards.execution",
            check_invalid_state=True,
        )
        self._assert_adjudication_repair_hint(
            setup_null,
            "primary_effect_crosses_null",
            "insufficient_evidence",
        )
        self._assert_adjudication_repair_hint(
            setup_unanchored,
            "unanchored_effect_record",
            "quote or snapshot",
        )

    def test_p2_longitudinal_triggers_and_calibration_mcp_e2e(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "study1.md").write_text(
                "Primary cohort HR 0.72 (95% CI 0.56 to 0.93, p = 0.012).\n",
                encoding="utf-8",
            )
            (workspace / "study2.md").write_text(
                "Independent follow-up HR 1.32 (95% CI 1.08 to 1.62, p = 0.007).\n",
                encoding="utf-8",
            )
            # Create and adjudicate prior case via Engine for concise setup, then exercise MCP tools & resources
            from parrhesia.core import Engine
            from parrhesia.contracts import CHECK_NAMES
            from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS

            eng = Engine(workspace)
            def _mk_claim(cid, ev, quote, est, ci_low, ci_high, pval, direction, *, triggers=None, links=None):
                c = {
                    "id": cid,
                    "text": quote,
                    "claim_type": "association",
                    "evidence_level": "adjusted",
                    "claim_basis": "empirical",
                    "scope": "Adult ICU cohort",
                    "evidence_ids": [ev],
                    "effect": {"estimate": f"HR {est}", "uncertainty": f"95% CI {ci_low} to {ci_high}, p = {pval}"},
                    "origin": "unknown",
                    "contribution": "Primary hazard analysis",
                    "alternatives": [{"explanation": "Residual confounding", "status": "not_excluded", "reason": "Adjusted baseline covariates evaluated."}],
                    "checks": {n: {"status": "pass", "reason": "Verified against study methods table."} for n in CHECK_NAMES},
                    "design_packages": [{"family": "observational", "checks": {k: {"status": "pass", "reason": "Verified cohort criteria.", "evidence_ids": [ev]} for k in DESIGN_FIELDS["observational"]}}],
                    "statistical_report": {k: {"status": "pass", "reason": "Verified statistical table.", "evidence_ids": [ev]} for k in STAT_FIELDS},
                    "provenance_cards": {k: [] for k in CARD_FIELDS},
                    "effect_records": [{
                        "id": f"E_{cid}", "endpoint": "Mortality", "endpoint_role": "primary", "metric": "HR",
                        "estimate": est, "ci_low": ci_low, "ci_high": ci_high, "ci_level": 0.95, "p_value": pval,
                        "direction": direction, "evidence_id": ev,
                    }],
                }
                if triggers is not None:
                    c["reversal_triggers"] = triggers
                if links is not None:
                    c["prior_claim_links"] = links
                return c

            c1 = eng.dispatch("create_case", {"question": "Initial benefit?", "draft": "Draft 1", "writer_context_id": "w1"})["case_id"]
            ev1 = eng.dispatch("register_evidence", {
                "case_id": c1, "path": "study1.md", "provenance": "observed", "kind": "observation",
                "quote": "Primary cohort HR 0.72 (95% CI 0.56 to 0.93, p = 0.012).", "location": "Table 1",
            })["evidence_id"]
            cl1 = _mk_claim(
                "C1", ev1, "Primary cohort HR 0.72 (95% CI 0.56 to 0.93, p = 0.012).", 0.72, 0.56, 0.93, 0.012, "benefit",
                triggers=[
                    {
                        "id": "T_GT1", "description": "Hazard rises above 1.0 on replication", "kind": "effect_metric",
                        "metric": "HR", "endpoint_role": "primary", "field": "estimate", "operator": "gt", "threshold": 1.0,
                        "target_verdict": "unsupported",
                    },
                    {
                        "id": "T_REP_REV", "description": "Reversed by downstream replication", "kind": "replication_verdict",
                        "target_verdicts": ["supported"], "relations": ["reverses"], "target_verdict": "unsupported",
                    },
                ],
            )
            eng.dispatch("set_ledger", {"case_id": c1, "claims": [cl1]})
            fr1 = eng.dispatch("freeze", {"case_id": c1})
            for role in ("overclaim", "underclaim"):
                pkt = eng.dispatch("review_packet", {"case_id": c1, "role": role})
                eng.dispatch("submit_review", {
                    "case_id": c1, "role": role, "packet_id": pkt["packet_id"], "input_digest": fr1["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Anchored", "evidence_ids": [ev1]}],
                    "unread_evidence_ids": [], "findings": [],
                })
            ap1 = eng.dispatch("adjudication_packet", {"case_id": c1})
            eng.dispatch("submit_adjudication", {
                "case_id": c1, "adjudication_id": ap1["adjudication_id"], "input_digest": ap1["input_digest"],
                "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                "decisions": [{
                    "claim_id": "C1", "claim_type": "association", "evidence_level": "adjusted", "claim_basis": "empirical",
                    "scope": "Adult ICU cohort", "verdict": "supported",
                    "revised_text": cl1["text"], "rationale": "Primary endpoint excludes null.", "evidence_ids": [ev1],
                    "confidence": "high", "confidence_reason": "Substantive effect.", "forecast_probability": 0.85,
                    "boundary": "Adult ICU cohort only.", "reversal_condition": "Follow-up HR > 1.0.",
                }],
            })

            c2 = eng.dispatch("create_case", {
                "question": "Replication check?", "draft": "Draft 2", "writer_context_id": "w2",
                "prior_case_ids": [c1], "case_relation": "replication",
            })["case_id"]
            ev2 = eng.dispatch("register_evidence", {
                "case_id": c2, "path": "study2.md", "provenance": "observed", "kind": "observation",
                "quote": "Independent follow-up HR 1.32 (95% CI 1.08 to 1.62, p = 0.007).", "location": "Table 1",
            })["evidence_id"]
            cl2 = _mk_claim(
                "C1", ev2, "Independent follow-up HR 1.32 (95% CI 1.08 to 1.62, p = 0.007).", 1.32, 1.08, 1.62, 0.007, "higher_better",
                links=[{
                    "prior_case_id": c1, "prior_claim_id": "C1", "relation": "reverses",
                    "triggered_reversal_id": "T_GT1",
                    "reason": "Independent follow-up hazard HR 1.32 > 1.0 reverses original C1.",
                }],
            )
            eng.dispatch("set_ledger", {"case_id": c2, "claims": [cl2]})
            fr2 = eng.dispatch("freeze", {"case_id": c2})
            for role in ("overclaim", "underclaim"):
                pkt = eng.dispatch("review_packet", {"case_id": c2, "role": role})
                eng.dispatch("submit_review", {
                    "case_id": c2, "role": role, "packet_id": pkt["packet_id"], "input_digest": fr2["input_digest"],
                    "reviewer": {"context_id": role, "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Anchored", "evidence_ids": [ev2]}],
                    "unread_evidence_ids": [], "findings": [],
                })
            ap2 = eng.dispatch("adjudication_packet", {"case_id": c2})
            eng.dispatch("submit_adjudication", {
                "case_id": c2, "adjudication_id": ap2["adjudication_id"], "input_digest": ap2["input_digest"],
                "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
                "decisions": [{
                    "claim_id": "C1", "claim_type": "association", "evidence_level": "adjusted", "claim_basis": "empirical",
                    "scope": "Adult ICU cohort", "verdict": "supported",
                    "revised_text": cl2["text"], "rationale": "Follow-up demonstrates HR > 1.0.", "evidence_ids": [ev2],
                    "confidence": "high", "confidence_reason": "Clear HR > 1.0.", "forecast_probability": 0.90,
                    "boundary": "Adult ICU cohort only.", "reversal_condition": "Subsequent meta-analysis reverses.",
                }],
            })

            responses = self.exchange(
                workspace,
                [
                    INITIALIZE,
                    request("tools/call", {"name": "parrhesia_claim_graph", "arguments": {"case_id": c1}}, 1),
                    request("tools/call", {"name": "parrhesia_evaluate_triggers", "arguments": {"case_id": c1, "against_case_id": c2}}, 2),
                    request("tools/call", {
                        "name": "parrhesia_record_calibration_outcome",
                        "arguments": {
                            "case_id": c1, "claim_id": "C1", "outcome": "refuted",
                            "resolution_source": "follow_up_case", "follow_up_case_id": c2, "follow_up_claim_id": "C1",
                            "effect_record_id": "E_C1",
                            "metric": "HR", "observed_estimate": 1.32, "observed_ci_low": 1.08, "observed_ci_high": 1.62,
                            "reason": "Reversed by independent follow-up trial.",
                        },
                    }, 3),
                    request("tools/call", {"name": "parrhesia_calibration_report", "arguments": {"domain": "scientific"}}, 4),
                    request("resources/read", {"uri": "parrhesia://claim-graph"}, 5),
                    request("resources/read", {"uri": "parrhesia://calibration"}, 6),
                    request("resources/read", {"uri": f"parrhesia://cases/{c1}/triggers"}, 7),
                ],
            )
            graph = responses[1]["result"]["structuredContent"]
            standing = {n["node_id"]: n["active_standing"] for n in graph["claim_nodes"]}
            self.assertEqual(standing[f"{c1}:C1"], "reversed")

            trig_eval = responses[2]["result"]["structuredContent"]
            self.assertEqual(trig_eval["fired_count"], 2)
            self.assertEqual(trig_eval["fired_trigger_ids"], ["C1:T_GT1", "C1:T_REP_REV"])

            cal_rec = responses[3]["result"]["structuredContent"]
            self.assertEqual(cal_rec["calibration_outcome_count"], 1)

            cal_rep = responses[4]["result"]["structuredContent"]
            self.assertEqual(cal_rep["summary"]["explicit_resolved_count"], 1)
            self.assertEqual(cal_rep["interval_calibration"]["covered_count"], 0)
            self.assertAlmostEqual(cal_rep["decision_calibration"]["trigger_calibration"]["trigger_precision"], 1.0, places=6)

            res_graph = json.loads(responses[5]["result"]["contents"][0]["text"])
            self.assertFalse(res_graph["cycle_detected"])
            res_cal = json.loads(responses[6]["result"]["contents"][0]["text"])
            self.assertEqual(res_cal["summary"]["total_adjudicated_claims"], 2)
            res_trig = json.loads(responses[7]["result"]["contents"][0]["text"])
            self.assertEqual(res_trig["fired_count"], 1)
            self.assertEqual(res_trig["fired_trigger_ids"], ["C1:T_REP_REV"])


if __name__ == "__main__":
    unittest.main()
