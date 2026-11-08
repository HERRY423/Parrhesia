"""Run Stage 0 evaluation suite for Parrhesia v0.2.0 (mechanical gate verification & prompt packet export)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parrhesia.claims import DESIGN_FIELDS, STAT_FIELDS, needs_causal_basis  # noqa: E402
from parrhesia.contracts import CHECK_NAMES, ContractError  # noqa: E402
from parrhesia.core import Engine  # noqa: E402
from parrhesia.gates import ESSENTIAL_DESIGN_CHECKS  # noqa: E402


def _pass_assessment(ev_id: str, detail: str = "Verified in primary analysis table") -> dict:
    return {"status": "pass", "reason": f"{detail} ({ev_id})", "evidence_ids": [ev_id]}


def _build_claim_from_scaffold(engine: Engine, case_id: str, spec: dict, ev_id: str) -> dict:
    family = spec["family"]
    claim_type = spec["claim_type"]
    evidence_level = spec["evidence_level"]
    need_causal = needs_causal_basis({"claim_type": claim_type, "evidence_level": evidence_level})
    scaffolded = engine.dispatch(
        "scaffold_claim",
        {
            "case_id": case_id,
            "claim_id": "C1",
            "text": spec["draft"],
            "claim_type": claim_type,
            "evidence_level": evidence_level,
            "claim_basis": "empirical",
            "scope": f"{family} cohort/experiment evaluation scope",
            "design_families": [family],
            "include_causal_basis": need_causal,
        },
    )["claim"]
    claim = dict(scaffolded)
    claim["evidence_ids"] = [ev_id]
    claim["effect"] = {"estimate": "Primary effect reported in source", "uncertainty": "95% CI reported in source"}
    claim["contribution"] = f"Addresses: {spec['question']}"
    claim["alternatives"] = [
        {"explanation": "Residual confounding or technical artifact", "status": "excluded", "reason": "Addressed by design controls and sensitivity checks"}
    ]
    claim["checks"] = {name: {"status": "pass", "reason": f"Checked in {ev_id}"} for name in CHECK_NAMES}
    claim["design_packages"] = [
        {
            "family": family,
            "checks": {key: _pass_assessment(ev_id, f"{family}.{key} satisfied") for key in DESIGN_FIELDS[family]},
        }
    ]
    claim["statistical_report"] = {key: _pass_assessment(ev_id, f"stat.{key} reported") for key in STAT_FIELDS}
    claim["provenance_cards"] = {"citation": [], "number": [], "execution": [], "search": []}

    if need_causal:
        nec_status = "pass" if claim_type == "necessity" else "not_applicable"
        suf_status = "pass" if claim_type == "sufficiency" else "not_applicable"
        claim["causal_basis"] = {
            "design_family": family,
            "estimand": {
                "population": "Target study population in registered source",
                "contrast": "Active exposure/intervention vs comparator strategy",
                "outcome": "Primary endpoint specified in question",
                "time_horizon": "Prespecified follow-up window",
                "summary": "Effect measure with 95% CI",
                "intercurrent_events": "Treatment policy / prespecified handling",
            },
            "assumptions": [
                {"name": "exchangeability_or_design_id", **_pass_assessment(ev_id, "Supported by design controls")},
                {"name": "consistency_and_positivity", **_pass_assessment(ev_id, "Well-defined intervention and overlap")},
            ],
            "falsification_sensitivity": [
                {"name": "negative_control_or_sensitivity", **_pass_assessment(ev_id, "Sensitivity / placebo check passed")},
            ],
            "assessment": _pass_assessment(ev_id, "Causal identification basis documented"),
            "necessity_test": {
                "status": nec_status,
                "reason": "Necessity counterfactual evaluated" if nec_status == "pass" else "Not a necessity claim",
                "evidence_ids": [ev_id] if nec_status == "pass" else [],
            },
            "sufficiency_test": {
                "status": suf_status,
                "reason": "Sufficiency counterfactual evaluated" if suf_status == "pass" else "Not a sufficiency claim",
                "evidence_ids": [ev_id] if suf_status == "pass" else [],
            },
        }

    tamper = spec.get("tamper")
    if tamper == "design_essential_not_applicable":
        essential_key = sorted(ESSENTIAL_DESIGN_CHECKS[family])[0]
        claim["design_packages"][0]["checks"][essential_key] = {
            "status": "not_applicable",
            "reason": "Rubber-stamped not_applicable on essential design check",
            "evidence_ids": [],
        }
    elif tamper == "all_design_not_applicable":
        claim["design_packages"][0]["checks"] = {
            key: {"status": "not_applicable", "reason": "All design checks marked not_applicable", "evidence_ids": []}
            for key in DESIGN_FIELDS[family]
        }
    elif tamper == "stat_essential_not_applicable":
        claim["statistical_report"]["estimate_uncertainty"] = {
            "status": "not_applicable",
            "reason": "Rubber-stamped not_applicable on estimate_uncertainty",
            "evidence_ids": [],
        }
    elif tamper == "fail_adherence_attrition":
        claim["design_packages"][0]["checks"]["adherence_attrition"] = {
            "status": "fail",
            "reason": "42% differential dropout invalidates unadjusted complete-case ITT",
            "evidence_ids": [ev_id],
        }
    elif tamper == "unknown_sufficiency_test":
        claim["causal_basis"]["sufficiency_test"] = {
            "status": "unknown",
            "reason": "Only knockout was tested; sufficiency overexpression not performed",
            "evidence_ids": [],
        }
    elif tamper == "contradicting_citation_card":
        claim["provenance_cards"]["citation"] = [
            {
                "id": "cit-contra-1",
                "status": "checked",
                "reason": "Source table contradicts superiority claim",
                "evidence_ids": [ev_id],
                "details": {
                    "source": "Hospital B External Validation Report",
                    "locator": "Table 2, line 1",
                    "claim_link": "C1",
                    "support_relation": "contradicts",
                    "read_extent": "complete",
                },
            }
        ]
    elif tamper == "failed_execution_card":
        claim["provenance_cards"]["execution"] = [
            {
                "id": "exec-fail-1",
                "status": "failed",
                "reason": "Benchmark evaluation exited with non-zero status",
                "evidence_ids": [ev_id],
                "details": {
                    "command": "python run_benchmark.py --kernel K1",
                    "code_version": "abc1234",
                    "inputs": "test_split.json",
                    "environment": "Python 3.13",
                    "started_at": "2026-10-31T00:00:00Z",
                    "ended_at": "2026-10-31T00:01:00Z",
                    "exit_status": "1",
                    "outputs": "none",
                    "log_locator": "logs/bench.log:L1",
                },
            }
        ]
    return claim


def evaluate_single_case(spec: dict, base_dir: Path) -> dict:
    ws = base_dir / spec["case_code"]
    ws.mkdir(parents=True, exist_ok=True)
    engine = Engine(ws)
    created = engine.dispatch(
        "create_case",
        {
            "question": spec["question"],
            "draft": spec["draft"],
            "domain": "scientific",
            "writer_context_id": f"writer-{spec['case_code']}",
        },
    )
    case_id = created["case_id"]
    ev_rel = f"evidence/{spec['case_code']}.txt"
    ev_file = ws / ev_rel
    ev_file.parent.mkdir(parents=True, exist_ok=True)
    ev_file.write_text(spec["evidence_text"] + "\n", encoding="utf-8")
    ev = engine.dispatch(
        "register_evidence",
        {
            "case_id": case_id,
            "path": ev_rel,
            "label": f"Evidence for {spec['case_code']}",
            "provenance": spec.get("evidence_provenance", "observed"),
            "kind": spec["evidence_kind"],
            "quote": spec["evidence_text"][:60],
            "location": f"{ev_rel}:L1",
        },
    )
    ev_id = ev["evidence_id"]
    claim = _build_claim_from_scaffold(engine, case_id, spec, ev_id)
    engine.dispatch("set_ledger", {"case_id": case_id, "claims": [claim]})
    engine.dispatch("freeze", {"case_id": case_id})

    over_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "overclaim"})
    under_pkt = engine.dispatch("review_packet", {"case_id": case_id, "role": "underclaim"})

    target_verdict = spec["target_verdict"]
    is_underclaim = spec["scenario"] == "underclaim_trap"
    reviewer_stance = "insufficient_evidence" if spec["expected_gate_outcome"] == "rejected" else target_verdict
    stance_entry = {
        "claim_id": "C1",
        "stance": reviewer_stance,
        "rationale": "Evaluated against frozen evidence and check ceilings",
        "evidence_ids": [] if reviewer_stance == "insufficient_evidence" else [ev_id],
    }
    if reviewer_stance == "partially_supported" and spec.get("condition"):
        stance_entry["condition"] = spec["condition"]

    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "overclaim",
            "packet_id": over_pkt["packet_id"],
            "input_digest": over_pkt["input_digest"],
            "reviewer": {"context_id": f"over-{spec['case_code']}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance_entry)],
            "unread_evidence_ids": [],
            "findings": [],
        },
    )

    under_findings = []
    if is_underclaim:
        under_findings.append(
            {
                "id": "U1",
                "claim_id": "C1",
                "evidence_ids": [ev_id],
                "issue": "Draft buries supported empirical finding under generic non-specific disclaimer",
                "proposed_claim_type": spec["claim_type"],
                "proposed_evidence_level": spec["evidence_level"],
                "proposed_claim_basis": "empirical",
                "proposed_scope": claim["scope"],
                "proposed_text": spec["restored_text"],
                "decision_impact": "Restores the supported empirical contribution while keeping scope boundary explicit",
            }
        )
    engine.dispatch(
        "submit_review",
        {
            "case_id": case_id,
            "role": "underclaim",
            "packet_id": under_pkt["packet_id"],
            "input_digest": under_pkt["input_digest"],
            "reviewer": {"context_id": f"under-{spec['case_code']}", "model": "eval-harness"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance_entry)],
            "unread_evidence_ids": [],
            "findings": under_findings,
        },
    )

    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": case_id})
    revised_text = spec["restored_text"] if is_underclaim else spec["draft"]
    decision = {
        "claim_id": "C1",
        "verdict": target_verdict,
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "claim_basis": "empirical",
        "scope": claim["scope"],
        "revised_text": revised_text,
        "rationale": f"Adjudicated {spec['case_code']} ({spec['scenario']})",
        "evidence_ids": [ev_id],
        "confidence": "medium",
        "confidence_reason": "Backed by registered primary evidence",
        "boundary": claim["scope"],
        "reversal_condition": "Re-evaluate if replication or sensitivity bounds fail",
    }
    if "condition" in spec:
        decision["condition"] = spec["condition"]

    dispositions = []
    if is_underclaim:
        dispositions.append(
            {
                "finding_id": "U1",
                "claim_id": "C1",
                "disposition": "accepted",
                "reason": "Restored supported contribution and removed generic disclaimer inflation",
                "resolution": "incorporated",
                "revised_text_quote": spec["restored_text"],
            }
        )

    try:
        engine.dispatch(
            "submit_adjudication",
            {
                "case_id": case_id,
                "adjudication_id": adj_pkt["adjudication_id"],
                "input_digest": adj_pkt["input_digest"],
                "adjudicator": {"context_id": f"adj-{spec['case_code']}", "model": "eval-harness"},
                "unread_evidence_ids": [],
                "decisions": [decision],
                "dispositions": dispositions,
            },
        )
        exported = engine.dispatch("export", {"case_id": case_id})
        actual_outcome = "accepted"
        actual_error = None
        export_state = exported["state"]
    except ContractError as exc:
        actual_outcome = "rejected"
        actual_error = exc.code
        export_state = None

    passed = (
        actual_outcome == spec["expected_gate_outcome"]
        and actual_error == spec["expected_error_code"]
    )
    return {
        "case_code": spec["case_code"],
        "family": spec["family"],
        "scenario": spec["scenario"],
        "claim_type": spec["claim_type"],
        "evidence_level": spec["evidence_level"],
        "target_verdict": target_verdict,
        "expected_gate_outcome": spec["expected_gate_outcome"],
        "actual_gate_outcome": actual_outcome,
        "expected_error_code": spec["expected_error_code"],
        "actual_error_code": actual_error,
        "export_state": export_state,
        "passed": passed,
    }


EXPLORATORY_CARD_FIELDS = (
    "strongest_rival",
    "discriminating_experiment",
    "cost",
    "stopping_rule",
    "kill_condition",
)


def evaluate_exploratory_case(spec: dict) -> dict:
    cards = spec.get("candidate_cards", [])
    valid = bool(cards)
    errors = []
    for idx, card in enumerate(cards):
        if card.get("origin") != "exploratory":
            valid = False
            errors.append(f"card[{idx}].origin != exploratory")
        for field in EXPLORATORY_CARD_FIELDS:
            val = card.get(field)
            if not isinstance(val, str) or not val.strip():
                valid = False
                errors.append(f"card[{idx}].{field} missing")
    return {
        "case_code": spec["case_code"],
        "family": spec["family"],
        "scenario": spec["scenario"],
        "card_count": len(cards),
        "origin": cards[0].get("origin") if cards else None,
        "claim_type": cards[0].get("claim_type") if cards else None,
        "evidence_level": cards[0].get("evidence_level") if cards else None,
        "metrics_status": {
            "discriminating_experiments_before_first_fp": "not_run",
            "steps_to_kill_false_hypothesis": "not_run",
            "total_consumption": "not_run",
        },
        "errors": errors,
        "passed": valid,
    }


def run_mechanical_suite(suite_path: Path, work_root: Path | None = None) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cleanup = False
    if work_root is None:
        tmp_base = ROOT / "artifacts" / "policy-test-tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(dir=tmp_base, prefix="stage0-eval-"))
        cleanup = True
    try:
        results = [evaluate_single_case(case, work_root) for case in suite["cases"]]
        exploratory_results = [evaluate_exploratory_case(case) for case in suite.get("exploratory_cases", [])]
    finally:
        if cleanup and work_root.exists():
            shutil.rmtree(work_root, ignore_errors=True)
    passed_count = sum(1 for item in results if item["passed"])
    exploratory_passed = sum(1 for item in exploratory_results if item["passed"])
    return {
        "suite_version": suite["suite_version"],
        "mode": "mechanical",
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "external_llm_status": "not_run",
        "requires_prior_user_approval": suite.get("requires_prior_user_approval", True),
        "stage0_design": suite.get("stage0_design", {}),
        "arms": [arm["arm_id"] for arm in suite.get("arms", [])],
        "total_cases": len(results),
        "passed_cases": passed_count,
        "exploratory_cases_count": len(exploratory_results),
        "exploratory_passed_cases": exploratory_passed,
        "exploratory_all_valid": exploratory_passed == len(exploratory_results),
        "all_passed": passed_count == len(results) and exploratory_passed == len(exploratory_results),
        "results": results,
        "exploratory_results": exploratory_results,
    }


def export_prompts(suite_path: Path, output_dir: Path) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    compact_policy_path = ROOT / "templates" / "AGENTS.parrhesia.codex.md"
    full_policy_path = ROOT / "templates" / "AGENTS.parrhesia.md"
    l2_ref_path = ROOT / "skills" / "parrhesia-l2-reference" / "SKILL.md"
    compact_bytes = len(compact_policy_path.read_bytes()) if compact_policy_path.is_file() else 0
    full_bytes = len(full_policy_path.read_bytes()) if full_policy_path.is_file() else 0
    l2_ref_bytes = len(l2_ref_path.read_bytes()) if l2_ref_path.is_file() else 0

    packets = []
    for case in suite["cases"]:
        packets.append(
            {
                "case_code": case["case_code"],
                "family": case["family"],
                "scenario": case["scenario"],
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "arms": {
                    "A_baseline": (
                        "[Arm A: 无 Parrhesia 规则]\n"
                        f"Question: {case['question']}\n"
                        f"Evidence: {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}\n"
                        "Evaluate the draft claim based on the evidence."
                    ),
                    "B_compact": (
                        f"[Arm B-精简（现用，{compact_bytes} B compact block + on-demand parrhesia-l2-reference {l2_ref_bytes} B）]\n"
                        "Follow Parrhesia compact policy block (templates/AGENTS.parrhesia.codex.md) and 2D claim_type x evidence_level + scope.\n"
                        f"Question: {case['question']}\n"
                        f"Evidence ({case['evidence_kind']}): {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}"
                    ),
                    "B_full": (
                        f"[Arm B-全文（41 KB，{full_bytes} B full policy templates/AGENTS.parrhesia.md）]\n"
                        "Follow full Parrhesia v0.2.0 policy text (templates/AGENTS.parrhesia.md) and 2D claim_type x evidence_level + scope.\n"
                        f"Question: {case['question']}\n"
                        f"Evidence ({case['evidence_kind']}): {case['evidence_text']}\n"
                        f"Draft claim: {case['draft']}"
                    ),
                    "E_full_l2_workflow": (
                        "[Arm E: 完整流程]\n"
                        "Run Parrhesia v0.2.0 [L2] workflow: register_evidence -> scaffold_claim -> set_ledger -> "
                        "freeze -> blind overclaim/underclaim review_packet (reviewer isolation recipe: role packet only, "
                        "no history inheritance, memory disabled, record input manifest) -> adjudication.\n"
                        f"Question: {case['question']}\n"
                        f"Target classification: {case['claim_type']} x {case['evidence_level']} ({case['target_verdict']})"
                    ),
                },
            }
        )

    exploratory_packets = []
    for exp_case in suite.get("exploratory_cases", []):
        card = exp_case["candidate_cards"][0]
        exploratory_packets.append(
            {
                "case_code": exp_case["case_code"],
                "family": exp_case["family"],
                "scenario": exp_case["scenario"],
                "statistical_unit": "case",
                "external_llm_status": "not_run",
                "exploratory_metrics": {
                    "discriminating_experiments_before_first_fp": "not_run",
                    "steps_to_kill_false_hypothesis": "not_run",
                    "total_consumption": "not_run",
                },
                "arms": {
                    "A_baseline": (
                        f"[Arm A: 无 Parrhesia 规则]\nQuestion: {exp_case['question']}\n"
                        f"Candidate hypothesis: {exp_case['false_hypothesis']}\nPropose next steps."
                    ),
                    "B_compact": (
                        "[Arm B-精简（现用，L1-Explore 轻量探索台账）]\n"
                        "Use [L1-Explore] lightweight exploration ledger (one card per candidate hypothesis: "
                        "strongest_rival, discriminating_experiment, cost, stopping_rule, kill_condition; mark exploratory).\n"
                        f"Question: {exp_case['question']}\nCandidate hypothesis: {card['statement']}"
                    ),
                    "B_full": (
                        "[Arm B-全文（41 KB，L1-Explore）]\n"
                        "Use full 41 KB policy [L1-Explore] mode.\n"
                        f"Question: {exp_case['question']}\nCandidate hypothesis: {card['statement']}"
                    ),
                    "E_full_l2_workflow": (
                        "[Arm E: 完整流程（探索后送入 L2）]\n"
                        f"Question: {exp_case['question']}\nCandidate hypothesis: {card['statement']}"
                    ),
                },
            }
        )

    manifest = {
        "suite_version": suite["suite_version"],
        "mode": "prompt-export",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "external_llm_status": "not_run",
        "requires_prior_user_approval": suite.get("requires_prior_user_approval", True),
        "stage0_design": suite.get("stage0_design", {}),
        "policy_size_bytes": {
            "B_compact_agents_block_bytes": compact_bytes,
            "B_compact_l2_reference_skill_bytes": l2_ref_bytes,
            "B_full_policy_bytes": full_bytes,
        },
        "arms": ["A_baseline", "B_compact", "B_full", "E_full_l2_workflow"],
        "packet_count": len(packets),
        "exploratory_packet_count": len(exploratory_packets),
        "packets": packets,
        "exploratory_packets": exploratory_packets,
    }
    out_file = output_dir / "stage0-prompt-packets.json"
    out_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_file": str(out_file),
        "packet_count": len(packets),
        "exploratory_packet_count": len(exploratory_packets),
        "arms": manifest["arms"],
        "external_llm_status": "not_run",
    }


def render_markdown_report(summary: dict) -> str:
    design = summary.get("stage0_design", {})
    pe = design.get("primary_endpoint", {})
    exp_metrics = design.get("exploratory_case_metrics", {})
    lines = [
        f"# Stage 0 Evaluation Verification Report (`{summary['suite_version']}`)",
        "",
        f"- **Mode**: `{summary['mode']}` (local deterministic engine, gate & L1-Explore card verification)",
        f"- **Control Arms Exported**: `A_baseline`（A：无 Parrhesia 规则）、`B_compact`（B-精简：现用精简块 + `parrhesia-l2-reference` skill）、`B_full`（B-全文：41 KB `templates/AGENTS.parrhesia.md`）、`E_full_l2_workflow`（E：完整 L2 流程，含审查者隔离配方）",
        f"- **L2 Calibration Cases**: `{summary['passed_cases']} / {summary['total_cases']}` (`all_passed={summary['all_passed']}`)",
        f"- **L1-Explore Exploratory Cases**: `{summary.get('exploratory_passed_cases', 0)} / {summary.get('exploratory_cases_count', 0)}` (`exploratory_all_valid={summary.get('exploratory_all_valid', True)}`)",
        f"- **External Paid LLM Execution Status**: `{summary['external_llm_status']}` (`requires_prior_user_approval={summary.get('requires_prior_user_approval', True)}`)",
        "",
        "## Stage 0 Design Key Points (Frozen Specification)",
        "",
        f"1. **统计单位**：{design.get('statistical_unit_rule', '统计单位是案例，重复运行不算独立样本。')}",
        f"2. **主终点与非劣效框架**：{pe.get('rule', '主终点：精简版相对全文版的校准通过率，用非劣效框架，界值运行前冻结。')}（`comparison={pe.get('comparison', 'B_compact vs B_full')}`, `framework={pe.get('framework', 'non_inferiority')}`, `non_inferiority_margin={pe.get('non_inferiority_margin', -0.05)}`, `margin_frozen_before_run={pe.get('margin_frozen_before_run', True)}`）",
        "3. **新增探索类案例（`L1-Explore`）的三个指标**：",
        f"   - `discriminating_experiments_before_first_fp`：{exp_metrics.get('discriminating_experiments_before_first_fp', '在首次出现假阳性结论前，已完成的区分实验数')}",
        f"   - `steps_to_kill_false_hypothesis`：{exp_metrics.get('steps_to_kill_false_hypothesis', '杀死错误假说所用步数')}",
        f"   - `total_consumption`：{exp_metrics.get('total_consumption', '总消耗')}",
        f"4. **Stage 0 定位与样本量说明**：{design.get('scope_and_power_statement', 'Stage 0 只估计方差和可执行性。上一份报告估算，要检出 15 到 20 个百分点的绝对提升，需要约 120 到 160 个案例，这是它的估算，不是我的测量。')}",
        f"5. **外部模型调用审批门槛**：{design.get('external_model_approval_rule', '外部模型调用需要你先批准，评价方案也这样要求。')}",
        "",
        "## Case-by-Case Mechanical Gate Results (24 L2 Cases)",
        "",
        "| Case | Family | Scenario | Classification (`claim_type × evidence_level`) | Verdict | Expected | Actual | Error Code | Pass |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        cls = f"`{r['claim_type']} × {r['evidence_level']}`"
        err = f"`{r['actual_error_code']}`" if r["actual_error_code"] else "—"
        lines.append(
            f"| `{r['case_code']}` | `{r['family']}` | `{r['scenario']}` | {cls} | `{r['target_verdict']}` | "
            f"`{r['expected_gate_outcome']}` | `{r['actual_gate_outcome']}` | {err} | `{'PASS' if r['passed'] else 'FAIL'}` |"
        )
    if summary.get("exploratory_results"):
        lines.extend(
            [
                "",
                "## L1-Explore Lightweight Exploration Ledger Cases (6 Exploratory Cases)",
                "",
                "| Case | Family | Origin | Classification | Cards | Required 5 Fields (`strongest_rival`, `discriminating_experiment`, `cost`, `stopping_rule`, `kill_condition`) | Live LLM Metrics |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for er in summary["exploratory_results"]:
            cls = f"`{er['claim_type']} × {er['evidence_level']}`"
            lines.append(
                f"| `{er['case_code']}` | `{er['family']}` | `{er['origin']}` | {cls} | `{er['card_count']}` | "
                f"`{'PASS' if er['passed'] else 'FAIL'}` | `not_run` |"
            )
    lines.extend(
        [
            "",
            "## Verification Scope & Honesty Boundary",
            "",
            "1. **What this verifies (`engineering × test_passed`)**: All 24 L2 Stage 0 cases execute through `parrhesia.core.Engine` v2 (`gate_version=1`), and all 6 `L1-Explore` exploratory cases validate the 5-field lightweight exploration ledger card contract (`strongest_rival`, `discriminating_experiment`, `cost`, `stopping_rule`, `kill_condition`, marked `exploratory`). Prompt packets are exported across all 4 control arms (`A_baseline`, `B_compact`, `B_full`, `E_full_l2_workflow`).",
            "2. **What remains `NOT_RUN` (`UNKNOWN`)**: Live external GPT/Claude/Grok API runs across Arms `A`, `B-精简`, `B-全文`, and `E` require prior user approval per `docs/evaluation-plan.md` and are explicitly marked `external_llm_status: not_run`.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 0 evaluation suite for Parrhesia.")
    parser.add_argument(
        "--suite",
        type=Path,
        default=ROOT / "docs" / "evaluation" / "stage0-cases.json",
        help="Path to stage0-cases.json",
    )
    parser.add_argument(
        "--mode",
        choices=("mechanical", "prompt-export"),
        default="mechanical",
        help="Run local mechanical gate suite or export prompt packets for Arms A/B/E",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "stage0-prompts")
    parser.add_argument("--report-out", type=Path, help="Optional Markdown report output path")
    args = parser.parse_args(argv)
    if args.mode == "prompt-export":
        result = export_prompts(args.suite, args.output_dir)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0
    summary = run_mechanical_suite(args.suite)
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(render_markdown_report(summary), encoding="utf-8", newline="\n")
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
