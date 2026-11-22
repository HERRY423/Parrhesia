"""Integration and security tests for Moat 3 (Living Lineage Synthesis) & Moat 4 (Subprocess Isolated Runner)."""
from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from statistics import NormalDist
from unittest.mock import patch

from parrhesia.cli import main as cli_main
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.isolated_runner import _wrap_os_sandbox_cmd, run_isolated_dual_review, run_isolated_subprocess
from parrhesia.isolation import packet_content_sha256
from parrhesia.report import render_synthesis_report


def _adjudicate_hr_case(
    eng: Engine,
    ws: Path,
    *,
    filename: str,
    file_text: str,
    quote: str,
    hr: float,
    ci_low: float,
    ci_high: float,
    p_value: float,
    verdict: str,
    claim_text: str,
    prior_case_ids: list[str] | None = None,
    case_relation: str | None = None,
    prior_claim_links: list[dict] | None = None,
    reversal_triggers: list[dict] | None = None,
    endpoint: str = "1-year relapse",
    ci_level: float | None = 0.95,
    estimand_overrides: dict | None = None,
    cohort_id: str | None = None,
    n: int | None = None,
    parent_source: tuple[str, str] | None = None,
) -> str:
    """Helper creating, reviewing, and effectively adjudicating a gated v2 HR case."""
    (ws / filename).write_text(file_text, encoding="utf-8")
    create_req: dict = {
        "question": "Does treatment X reduce 1-year relapse hazard?",
        "draft": claim_text,
        "domain": "scientific",
        "writer_context_id": f"writer-{filename}",
    }
    if prior_case_ids:
        create_req["prior_case_ids"] = prior_case_ids
    if case_relation:
        create_req["case_relation"] = case_relation
    cid = eng.dispatch("create_case", create_req)["case_id"]
    reg_req: dict = {
        "case_id": cid, "path": filename, "kind": "intervention",
        "provenance": "observed", "quote": quote, "location": "line 1",
    }
    if parent_source is not None:
        pname, ptext = parent_source
        (ws / pname).write_text(ptext, encoding="utf-8")
        p_ev = eng.dispatch("register_evidence", {
            "case_id": cid, "path": pname, "kind": "intervention",
            "provenance": "observed", "quote": ptext.strip().splitlines()[0], "location": "line 1",
        })["evidence_id"]
        reg_req["derived_from_evidence_ids"] = [p_ev]
        reg_req["derivation_step"] = "Derived cohort analysis table"
    ev = eng.dispatch("register_evidence", reg_req)["evidence_id"]

    interval_label = f"{ci_level:.0%} CI" if ci_level is not None else "CI"
    direction = "benefit" if ci_high < 1.0 else ("harm" if ci_low > 1.0 else "null")
    claim_req: dict = {
        "case_id": cid, "claim_id": "C1", "text": claim_text,
        "claim_type": "causal_effect",
        "evidence_level": "identified_under_assumptions" if verdict != "unsupported" else "unidentified",
        "claim_basis": "empirical",
        "scope": f"Randomized cohort ({filename})",
        "evidence_ids": [ev],
        "design_families": ["randomized"],
        "effect": {"estimate": f"HR = {hr:.2f}", "uncertainty": f"{interval_label} {ci_low:.2f} to {ci_high:.2f}"},
        "contribution": f"Evaluates treatment X hazard ratio in {filename}.",
        "alternatives": [{
            "explanation": "Sampling variance or differential attrition",
            "status": "excluded",
            "reason": "Complete ITT follow-up in randomized cohort.",
        }],
        "effect_records": [{
            "id": "e1", "endpoint": endpoint, "endpoint_role": "primary",
            "metric": "HR", "estimate": hr, "ci_low": ci_low, "ci_high": ci_high,
            **({"ci_level": ci_level} if ci_level is not None else {}),
            **({"cohort_id": cohort_id} if cohort_id is not None else {}),
            **({"n": n} if n is not None else {}),
            "p_value": p_value, "direction": direction, "beneficial_if": "below_null",
            "evidence_id": ev,
        }],
        "checks_overrides": {
            "quality": {"status": "pass", "reason": "Complete outcome adjudication verified."},
            "batch": {"status": "pass", "reason": "Stratified randomization across centers."},
            "unit": {"status": "pass", "reason": "Patient-level independent units."},
            "assumptions": {"status": "pass", "reason": "Proportional hazards verified."},
            "multiplicity": {"status": "pass", "reason": "Single prespecified primary endpoint."},
            "leakage": {"status": "not_applicable", "reason": "Randomized trial, not predictive ML."},
            "baseline": {"status": "pass", "reason": "Placebo-controlled concurrent comparator."},
            "design.randomized.randomization_concealment": {"status": "pass", "reason": "Central concealed randomization.", "evidence_ids": [ev]},
            "design.randomized.analysis_population": {"status": "pass", "reason": "ITT analysis population.", "evidence_ids": [ev]},
            "design.randomized.adherence_attrition": {"status": "pass", "reason": "Minimal attrition <2%.", "evidence_ids": [ev]},
            "design.randomized.interference": {"status": "pass", "reason": "No cross-arm contamination.", "evidence_ids": [ev]},
            "design.randomized.harms": {"status": "pass", "reason": "Adverse events monitored.", "evidence_ids": [ev]},
            "statistics.units_sample_size": {"status": "pass", "reason": "Patient-level randomized sample.", "evidence_ids": [ev]},
            "statistics.estimand_scale": {"status": "pass", "reason": "ITT hazard ratio at 1 year.", "evidence_ids": [ev]},
            "statistics.estimate_uncertainty": {"status": "pass", "reason": f"HR {hr:.2f} ({interval_label} {ci_low:.2f}-{ci_high:.2f}).", "evidence_ids": [ev]},
            "statistics.model_assumptions": {"status": "pass", "reason": "Cox PH checked.", "evidence_ids": [ev]},
            "statistics.missingness_exclusions": {"status": "pass", "reason": "Complete ITT capture.", "evidence_ids": [ev]},
            "statistics.multiplicity_selection": {"status": "pass", "reason": "Single primary endpoint.", "evidence_ids": [ev]},
            "statistics.comparisons_baselines": {"status": "pass", "reason": "Concurrent randomized control arm.", "evidence_ids": [ev]},
            "statistics.robustness_limits": {"status": "pass", "reason": "Sensitivity analyses consistent.", "evidence_ids": [ev]},
        },
        "causal_basis": {
            "design_family": "randomized",
            "estimand": {
                "population": "Adult patients in randomized trial",
                "contrast": "Treatment X vs standard placebo",
                "outcome": "1-year relapse hazard",
                "time_horizon": "12 months",
                "summary": "Hazard ratio (ITT)",
                "intercurrent_events": "Treatment policy strategy",
                **(estimand_overrides or {}),
            },
            "assumptions": [{"name": "exchangeability", "status": "pass", "reason": "Concealed 1:1 randomization.", "evidence_ids": [ev]}],
            "falsification_sensitivity": [{"name": "censoring_sensitivity", "status": "pass", "reason": "Tipping-point censoring check consistent.", "evidence_ids": [ev]}],
            "assessment": {"status": "pass", "reason": "Randomized causal identification satisfied.", "evidence_ids": [ev]},
            "necessity_test": {"status": "not_applicable", "reason": "Average causal effect only.", "evidence_ids": []},
            "sufficiency_test": {"status": "not_applicable", "reason": "Average causal effect only.", "evidence_ids": []},
        },
    }
    if prior_claim_links:
        claim_req["prior_claim_links"] = prior_claim_links
    if reversal_triggers:
        claim_req["reversal_triggers"] = reversal_triggers

    eng.dispatch("upsert_claim", claim_req)
    eng.dispatch("freeze", {"case_id": cid})
    over = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
    under = eng.dispatch("review_packet", {"case_id": cid, "role": "underclaim"})
    stance = {
        "claim_id": "C1", "stance": verdict,
        "rationale": f"Randomized cohort {filename} yields HR={hr:.2f} ({interval_label} {ci_low:.2f}-{ci_high:.2f}, p={p_value:.4g}).",
        "evidence_ids": [ev],
    }
    for role, pkt in (("overclaim", over), ("underclaim", under)):
        eng.dispatch("submit_review", {
            "case_id": cid, "role": role,
            "packet_id": pkt["packet_id"], "input_digest": pkt["input_digest"],
            "reviewer": {"context_id": f"{role}-{filename}", "model": "test-model"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [dict(stance)],
            "unread_evidence_ids": [], "findings": [],
        })
    adj = eng.dispatch("adjudication_packet", {"case_id": cid})
    dec = {
        "claim_id": "C1", "verdict": verdict,
        "claim_type": "causal_effect",
        "evidence_level": "identified_under_assumptions" if verdict != "unsupported" else "unidentified",
        "claim_basis": "empirical",
        "scope": f"Randomized cohort ({filename})",
        "revised_text": claim_text,
        "rationale": f"Randomized cohort {filename} reports HR={hr:.2f} ({interval_label} {ci_low:.2f}-{ci_high:.2f}, p={p_value:.4g}).",
        "evidence_ids": [ev],
        "confidence": "high",
        "confidence_reason": "Concealed randomized trial with complete ITT follow-up.",
        "boundary": "Applies to studied adult patient population over 12 months.",
        "reversal_condition": "Independent trial yields HR 95% CI crossing 1.0 or point HR >= 1.0.",
    }
    eng.dispatch("submit_adjudication", {
        "case_id": cid,
        "adjudication_id": adj["adjudication_id"],
        "input_digest": adj["input_digest"],
        "adjudicator": {"context_id": f"adj-{filename}", "model": "test-model"},
        "unread_evidence_ids": [],
        "decisions": [dec],
        "dispositions": [],
    })
    return cid


class Moats3And4Tests(unittest.TestCase):
    def test_synthesis_separates_endpoints_estimands_and_unlinked_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            quote = "HR = 0.90 (95% CI 0.78 to 1.03, p=0.13)."

            def add(label, endpoint="12-month recurrence", **kwargs):
                return _adjudicate_hr_case(
                    engine, root, filename=f"{label}.txt", file_text=f"{label}: {quote}\n", quote=quote,
                    hr=0.90, ci_low=0.78, ci_high=1.03, p_value=0.13,
                    verdict="unsupported", claim_text=f"{endpoint} fixture {label}", endpoint=endpoint, **kwargs,
                )

            original = add("recurrence", reversal_triggers=[{
                "id": "T_NULL", "description": "Replicated HR 95% CI crosses 1.0.",
                "kind": "effect_metric", "metric": "HR", "field": "estimate",
                "operator": "crosses_null", "target_verdict": "unsupported",
            }])
            link = {"prior_case_ids": [original], "case_relation": "replication"}
            add("adverse-events", endpoint="30-day first adverse event", **link)
            add("different-contrast", estimand_overrides={"contrast": "Treatment X vs active control"}, **link)
            add("unlinked-same-endpoint")
            missing = add("unknown-coverage", ci_level=None, **link)

            result = engine.dispatch("analyze_design", {"mode": "lineage_synthesis"})
            self.assertEqual(result["living_status"], "insufficient_independent_studies")
            self.assertEqual(result["independent_pooled_case_count"], 0)
            self.assertEqual(result["triggered_ancestors"], [])
            groups = result["metric_syntheses"]
            self.assertEqual(len(groups), 4)
            self.assertEqual({g["endpoint"] for g in groups}, {"12-month recurrence", "30-day first adverse event"})
            self.assertTrue(all(g["independent_study_count"] == 1 and g["meta_analysis"] is None for g in groups))
            self.assertIn(
                {"case_id": missing, "claim_id": "C1", "record_id": "e1",
                 "reason": "missing_source_confidence_interval_or_level"},
                result["excluded_ineligible"],
            )

    def test_synthesis_carries_input_and_output_coverage_through_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)

            def add(label, coverage, parent=None):
                quote = f"HR = 0.90 ({coverage:.0%} CI 0.78 to 1.03, p=0.213)."
                return _adjudicate_hr_case(
                    engine, root, filename=f"{label}.txt", file_text=f"{label}: {quote}\n", quote=quote,
                    hr=0.90, ci_low=0.78, ci_high=1.03, p_value=0.213, ci_level=coverage,
                    verdict="unsupported", claim_text=f"12-month recurrence fixture {label}",
                    prior_case_ids=[parent] if parent else None, case_relation="replication" if parent else None,
                    prior_claim_links=[{"prior_case_id": parent, "prior_claim_id": "C1", "relation": "replicates",
                                       "reason": "Independent fixture measures the same recurrence outcome."}] if parent else None,
                )

            first = add("first", 0.90)
            second = add("second", 0.90, first)
            query = {"mode": "lineage_synthesis", "case_id": first, "claim_id": "C1"}
            result = engine.dispatch("analyze_design", query)
            group = result["metric_syntheses"][0]
            re = group["meta_analysis"]["random_effects"]
            normal = NormalDist()
            width = math.log(1.03) - math.log(0.78)

            def expected(levels, output_level):
                weights = [(2 * normal.inv_cdf((1 + level) / 2) / width) ** 2 for level in levels]
                delta = normal.inv_cdf((1 + output_level) / 2) / math.sqrt(sum(weights))
                return 0.90 * math.exp(-delta), 0.90 * math.exp(delta)

            lower, upper = expected([0.90, 0.90], 0.95)
            self.assertAlmostEqual(re["ci_low"], lower, places=6)
            self.assertAlmostEqual(re["ci_high"], upper, places=6)
            self.assertFalse(re["excludes_null"])
            self.assertEqual(result["living_status"], "pooled_inconclusive")

            add("third", 0.95, second)
            mixed = engine.dispatch("analyze_design", {**query, "ci_level": 0.80})["metric_syntheses"][0]
            self.assertEqual([s["ci_level"] for s in mixed["studies"]], [0.90, 0.90, 0.95])
            self.assertEqual([s["ci_level"] for s in mixed["cumulative_trajectory"]], [0.90, 0.80, 0.80])
            for idx, step in enumerate(mixed["cumulative_trajectory"][1:], 2):
                lower, upper = expected([0.90, 0.90, 0.95][:idx], 0.80)
                self.assertAlmostEqual(step["ci_low"], lower, places=6)
                self.assertAlmostEqual(step["ci_high"], upper, places=6)

    # ------------------------------------------------------------------
    # Moat 3: Living Cross-Case Synthesis & Deduplication Guard
    # ------------------------------------------------------------------
    def test_living_lineage_synthesis_convergent_replication_and_deduplication_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            cohort_a_text = "Randomized Cohort A (N=300): HR = 0.72 (95% CI 0.58 to 0.89, p = 0.0025).\n"
            cohort_b_text = "Independent Randomized Cohort B (N=340): HR = 0.76 (95% CI 0.62 to 0.93, p = 0.0078).\n"

            c1 = _adjudicate_hr_case(
                eng, ws,
                filename="cohort_a.txt", file_text=cohort_a_text,
                quote="HR = 0.72 (95% CI 0.58 to 0.89, p = 0.0025).",
                hr=0.72, ci_low=0.58, ci_high=0.89, p_value=0.0025,
                verdict="supported",
                claim_text="Treatment X reduces 1-year relapse hazard in Cohort A (HR 0.72, 95% CI 0.58 to 0.89).",
            )
            # Case 2: Reanalysis of Cohort A -> excluded via case_relation="reanalysis"
            c2 = _adjudicate_hr_case(
                eng, ws,
                filename="cohort_a_reanalysis.txt",
                file_text="Reanalysis of Cohort A (N=300): HR = 0.73 (95% CI 0.59 to 0.90, p = 0.0031).\n",
                quote="HR = 0.73 (95% CI 0.59 to 0.90, p = 0.0031).",
                hr=0.73, ci_low=0.59, ci_high=0.90, p_value=0.0031,
                verdict="supported",
                claim_text="Reanalysis of Cohort A confirms HR 0.73 (95% CI 0.59 to 0.90).",
                prior_case_ids=[c1], case_relation="reanalysis",
                prior_claim_links=[{"prior_case_id": c1, "prior_claim_id": "C1", "relation": "refines", "reason": "Alternative covariate specification on Cohort A."}],
            )
            # Case 3: Identical bytes (SHA-256 duplicate!) claiming to be a replication -> excluded by SHA-256 guard!
            c3 = _adjudicate_hr_case(
                eng, ws,
                filename="cohort_a_copy.txt", file_text=cohort_a_text,
                quote="HR = 0.72 (95% CI 0.58 to 0.89, p = 0.0025).",
                hr=0.72, ci_low=0.58, ci_high=0.89, p_value=0.0025,
                verdict="supported",
                claim_text="Duplicate copy of Cohort A reports HR 0.72 (95% CI 0.58 to 0.89).",
                prior_case_ids=[c1], case_relation="replication",
                prior_claim_links=[{"prior_case_id": c1, "prior_claim_id": "C1", "relation": "replicates", "reason": "Submitted with duplicate file bytes."}],
            )
            # Case 4: Truly independent Cohort B
            c4 = _adjudicate_hr_case(
                eng, ws,
                filename="cohort_b.txt", file_text=cohort_b_text,
                quote="HR = 0.76 (95% CI 0.62 to 0.93, p = 0.0078).",
                hr=0.76, ci_low=0.62, ci_high=0.93, p_value=0.0078,
                verdict="supported",
                claim_text="Independent Cohort B replicates relapse reduction (HR 0.76, 95% CI 0.62 to 0.93).",
                prior_case_ids=[c1], case_relation="replication",
                prior_claim_links=[{"prior_case_id": c1, "prior_claim_id": "C1", "relation": "replicates", "reason": "Independent multicenter cohort B replicates primary hazard reduction."}],
            )

            syn = eng.dispatch("analyze_design", {"mode": "lineage_synthesis", "case_id": c4})
            self.assertEqual(syn["independent_pooled_case_count"], 2)
            self.assertEqual(set(syn["independent_pooled_case_ids"]), {c1, c4})
            self.assertEqual(syn["living_status"], "replicated_consistent")
            self.assertEqual(syn["deduplication_guard"]["excluded_non_independent_count"], 2)
            self.assertTrue(
                any(item.get("case_id") == c3 and item.get("overlapping_prior_case_id") == c1
                    for item in syn["deduplication_guard"]["excluded_non_independent"])
            )
            ms = syn["metric_syntheses"][0]
            self.assertEqual(ms["metric"], "HR")
            self.assertEqual(ms["trajectory_pattern"], "convergent_replication")
            self.assertEqual(ms["meta_analysis"]["i2_percent"], 0.0)
            self.assertAlmostEqual(ms["meta_analysis"]["random_effects"]["estimate"], 0.74, delta=0.015)

            # claim_graph(include_synthesis=True) embeds living_synthesis seamlessly
            graph_plain = eng.dispatch("claim_graph", {"case_id": c4})
            self.assertNotIn("living_synthesis", graph_plain)
            graph_syn = eng.dispatch("claim_graph", {"case_id": c4, "include_synthesis": True})
            self.assertEqual(graph_syn["living_synthesis"]["living_status"], "replicated_consistent")

            # Proactive case_audit automatically attaches lineage_synthesis_summary
            audit = eng.dispatch("analyze_design", {"mode": "case_audit", "case_id": c4})
            self.assertIn("lineage_synthesis_summary", audit)
            self.assertEqual(audit["lineage_synthesis_summary"]["independent_pooled_case_count"], 2)
            self.assertEqual(audit["lineage_synthesis_summary"]["living_status"], "replicated_consistent")

    def test_living_synthesis_ancestor_reversal_trigger_cascade_preserves_immutability(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            c1 = _adjudicate_hr_case(
                eng, ws,
                filename="pilot.txt",
                file_text="Pilot RCT (N=120): HR = 0.60 (95% CI 0.45 to 0.80, p = 0.0005).\n",
                quote="HR = 0.60 (95% CI 0.45 to 0.80, p = 0.0005).",
                hr=0.60, ci_low=0.45, ci_high=0.80, p_value=0.0005,
                verdict="supported",
                claim_text="Pilot trial shows HR 0.60 (95% CI 0.45 to 0.80) for 1-year relapse.",
                reversal_triggers=[{
                    "id": "T_NULL",
                    "description": "Independent replication or pooled HR 95% CI crosses 1.0.",
                    "kind": "effect_metric",
                    "metric": "HR",
                    "field": "estimate",
                    "operator": "crosses_null",
                    "target_verdict": "unsupported",
                }],
            )
            before_c1 = eng.dispatch("get_case", {"case_id": c1})

            # Independent large failed replication whose HR crosses null (1.04, 95% CI 0.88-1.23)
            c2 = _adjudicate_hr_case(
                eng, ws,
                filename="large_rep.txt",
                file_text="Large Multicenter Replication (N=800): HR = 1.04 (95% CI 0.88 to 1.23, p = 0.64), refuting prior pilot.\n",
                quote="HR = 1.04 (95% CI 0.88 to 1.23, p = 0.64), refuting prior pilot.",
                hr=1.04, ci_low=0.88, ci_high=1.23, p_value=0.64,
                verdict="unsupported",
                claim_text="Large multicenter replication fails to reproduce benefit (HR 1.04, 95% CI 0.88 to 1.23).",
                prior_case_ids=[c1], case_relation="replication",
            )

            syn = eng.dispatch("analyze_design", {"mode": "lineage_synthesis", "case_id": c1})
            self.assertEqual(syn["living_status"], "contested_or_reversed")
            self.assertGreaterEqual(syn["triggered_ancestor_count"], 1)
            fired_ids = {t["trigger_id"] for t in syn["triggered_ancestors"]}
            self.assertIn("T_NULL", fired_ids)
            self.assertTrue(any(a["action_kind"] == "record_formal_lineage_reversal" for a in syn["living_next_actions"]))

            # Frozen ancestor case digests are strictly unchanged
            after_c1 = eng.dispatch("get_case", {"case_id": c1})
            self.assertEqual(before_c1["input_digest"], after_c1["input_digest"])
            self.assertEqual(before_c1["adjudication_digest"], after_c1["adjudication_digest"])

    # ------------------------------------------------------------------
    # Moat 4: OS Subprocess Isolation Runner, Env Scrubbing, HMAC Seal & Reports
    # ------------------------------------------------------------------
    def test_subprocess_isolated_runner_scrubs_env_isolates_cwd_seals_hmac_and_renders_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            (ws / "ext.txt").write_text(
                "External cohort (N=120): AUROC = 0.84 (95% CI 0.77 to 0.90, calibration slope = 0.96).\n",
                encoding="utf-8",
            )
            cid = eng.dispatch("create_case", {
                "question": "Does the risk model generalize externally?",
                "draft": "SECRET_DRAFT_NOT_VISIBLE_IN_BLIND_SANDBOX",
                "domain": "scientific",
                "blind": True,
                "blind_mode": "estimate_first",
                "writer_context_id": "writer-main",
            })["case_id"]
            ev = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "ext.txt", "kind": "prediction_external",
                "provenance": "observed",
                "quote": "AUROC = 0.84 (95% CI 0.77 to 0.90, calibration slope = 0.96).",
                "location": "line 1",
            })["evidence_id"]
            eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C1",
                "text": "Model achieves AUROC 0.84 (95% CI 0.77 to 0.90) in external cohort N=120.",
                "claim_type": "prediction", "evidence_level": "externally_validated",
                "claim_basis": "empirical", "scope": "External cohort N=120",
                "evidence_ids": [ev], "design_families": ["prediction"],
                "effect": {"estimate": "AUROC 0.84", "uncertainty": "95% CI 0.77 to 0.90"},
                "contribution": "External discrimination verified.",
                "alternatives": [{"explanation": "Leakage", "status": "excluded", "reason": "Independent external hospital cohort."}],
                "effect_records": [{
                    "id": "e1", "endpoint": "1-year recurrence", "endpoint_role": "primary",
                    "metric": "AUROC", "estimate": 0.84, "ci_low": 0.77, "ci_high": 0.90,
                    "n": 120, "null_value": 0.50, "direction": "higher_better", "claim_direction": "higher_better",
                    "beneficial_if": "above_null", "evidence_id": ev,
                }],
                "checks_overrides": {
                    "quality": {"status": "pass", "reason": "Complete external cohort follow-up."},
                    "batch": {"status": "pass", "reason": "Locked preprocessing."},
                    "unit": {"status": "pass", "reason": "120 unique patients."},
                    "assumptions": {"status": "pass", "reason": "Calibration slope 0.96."},
                    "multiplicity": {"status": "pass", "reason": "Single primary endpoint."},
                    "leakage": {"status": "pass", "reason": "Frozen model weights."},
                    "baseline": {"status": "pass", "reason": "Exceeds 0.50 chance baseline."},
                    "design.prediction.target_horizon": {"status": "pass", "reason": "1-year horizon.", "evidence_ids": [ev]},
                    "design.prediction.splits_leakage": {"status": "pass", "reason": "Zero patient overlap.", "evidence_ids": [ev]},
                    "design.prediction.calibration_discrimination": {"status": "pass", "reason": "AUROC 0.84, slope 0.96.", "evidence_ids": [ev]},
                    "design.prediction.validation_shift": {"status": "pass", "reason": "External site.", "evidence_ids": [ev]},
                    "design.prediction.utility": {"status": "not_applicable", "reason": "Utility reserved for prospective study.", "evidence_ids": []},
                    "statistics.units_sample_size": {"status": "pass", "reason": "N=120 patients.", "evidence_ids": [ev]},
                    "statistics.estimand_scale": {"status": "pass", "reason": "External AUROC.", "evidence_ids": [ev]},
                    "statistics.estimate_uncertainty": {"status": "pass", "reason": "AUROC 0.84 (95% CI 0.77-0.90).", "evidence_ids": [ev]},
                    "statistics.model_assumptions": {"status": "pass", "reason": "Slope 0.96.", "evidence_ids": [ev]},
                    "statistics.missingness_exclusions": {"status": "pass", "reason": "Complete follow-up.", "evidence_ids": [ev]},
                    "statistics.multiplicity_selection": {"status": "pass", "reason": "Single endpoint.", "evidence_ids": [ev]},
                    "statistics.comparisons_baselines": {"status": "pass", "reason": "Above 0.50.", "evidence_ids": [ev]},
                    "statistics.robustness_limits": {"status": "pass", "reason": "External site tested.", "evidence_ids": [ev]},
                },
            })
            eng.dispatch("freeze", {"case_id": cid})

            # Write a standalone reviewer/adjudicator adapter outside sandbox that asserts physical isolation!
            adapter = Path(tmp) / "isolated_adapter.py"
            adapter.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "assert os.environ.get('PARRHESIA_TEST_SECRET_TOKEN') is None, 'Secret leaked into child env!'\n"
                "assert os.environ.get('PARRHESIA_ISOLATED_RUNNER') == '1'\n"
                "assert os.environ.get('PARRHESIA_MEMORY_ENABLED') == 'false'\n"
                "cwd_entries = {p.name for p in Path.cwd().iterdir()}\n"
                "assert cwd_entries <= {'packet.json', 'instructions.txt', 'tmp', 'home'}, f'Unexpected sandbox files: {cwd_entries}'\n"
                "assert not (Path.cwd() / '.parrhesia').exists()\n"
                "pkt = json.loads(Path(os.environ['PARRHESIA_PACKET_PATH']).read_text(encoding='utf-8'))\n"
                "role = os.environ['PARRHESIA_ROLE']\n"
                "ev_id = pkt['evidence'][0]['evidence_id']\n"
                "if role in ('overclaim', 'underclaim'):\n"
                "    assert pkt['draft'] is None, 'Blind packet leaked draft!'\n"
                "    assert 'evidence_first_dossier' in pkt\n"
                "    assert 'computable_diagnostics' in pkt\n"
                "    out = {\n"
                "        'reviewer': {'context_id': f'iso-child-{role}', 'model': 'local-isolated-adapter'},\n"
                "        'covered_claim_ids': ['C1'],\n"
                "        'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'External cohort N=120 achieves AUROC 0.84 (95% CI 0.77-0.90) with all checks passing.', 'evidence_ids': [ev_id]}],\n"
                "        'unread_evidence_ids': [],\n"
                "        'findings': [],\n"
                "    }\n"
                "else:\n"
                "    out = {\n"
                "        'adjudicator': {'context_id': 'iso-child-adj', 'model': 'local-isolated-adapter'},\n"
                "        'unread_evidence_ids': [],\n"
                "        'dispositions': [],\n"
                "        'decisions': [{\n"
                "            'claim_id': 'C1', 'verdict': 'supported', 'claim_type': 'prediction',\n"
                "            'evidence_level': 'externally_validated', 'claim_basis': 'empirical',\n"
                "            'scope': 'External cohort N=120',\n"
                "            'revised_text': 'Model achieves AUROC 0.84 (95% CI 0.77 to 0.90) in external cohort N=120.',\n"
                "            'rationale': 'Both isolated reviews and frozen evidence confirm external AUROC 0.84 (95% CI 0.77-0.90).',\n"
                "            'evidence_ids': [ev_id], 'confidence': 'high', 'confidence_reason': 'Anchored external cohort.',\n"
                "            'boundary': 'Clinical decision utility requires prospective study.',\n"
                "            'reversal_condition': 'Second external cohort AUROC drops below 0.70.',\n"
                "            'actionable_stance': 'adopt_within_scope',\n"
                "        }],\n"
                "    }\n"
                "print(json.dumps(out))\n",
                encoding="utf-8",
            )

            prev_secret = os.environ.get("PARRHESIA_TEST_SECRET_TOKEN")
            os.environ["PARRHESIA_TEST_SECRET_TOKEN"] = "TOP_SECRET_PARENT_SESSION"
            try:
                for role in ("overclaim", "underclaim"):
                    res = run_isolated_subprocess(
                        ws, cid, role, [sys.executable, "-X", "utf8", str(adapter)],
                        auto_submit=True,
                    )
                    self.assertEqual(res["termination_status"], "completed", msg=res)
                    self.assertTrue(res["submitted"], msg=res)
                    self.assertEqual(res["isolation_grade"]["grade"], "subprocess_sealed_isolated")
                    self.assertTrue(res["isolation_receipt"]["env_scrubbed"])
                    self.assertTrue(res["isolation_receipt"]["isolated_cwd"])
                    self.assertEqual(len(res["isolation_receipt"]["runner_seal"]), 64)

                # Build adjudication packet then run isolated adjudicator via CLI `run-isolated --auto-submit`
                eng.dispatch("adjudication_packet", {"case_id": cid})
                buf_adj = io.BytesIO()
                with patch.object(sys, "stdout", type("S", (), {"buffer": buf_adj})()):
                    rc = cli_main([
                        "run-isolated", "--workspace", str(ws), "--case-id", cid, "--role", "adjudication",
                        "--auto-submit", "--", sys.executable, "-X", "utf8", str(adapter),
                    ])
                self.assertEqual(rc, 0)
                cli_out = json.loads(buf_adj.getvalue().decode("utf-8"))
                self.assertEqual(cli_out["isolation_grade"]["grade"], "subprocess_sealed_isolated")
            finally:
                if prev_secret is None:
                    os.environ.pop("PARRHESIA_TEST_SECRET_TOKEN", None)
                else:
                    os.environ["PARRHESIA_TEST_SECRET_TOKEN"] = prev_secret

            case_doc = eng.dispatch("get_case", {"case_id": cid})
            self.assertEqual(case_doc["state"], "adjudicated")
            self.assertEqual(case_doc["reviews"]["overclaim"]["isolation_grade"]["grade"], "subprocess_sealed_isolated")
            self.assertEqual(case_doc["reviews"]["underclaim"]["isolation_grade"]["grade"], "subprocess_sealed_isolated")
            self.assertEqual(case_doc["adjudication"]["isolation_grade"]["grade"], "subprocess_sealed_isolated")

            # Export Markdown & HTML reports and verify isolation_grade & transcript_sha256 render cleanly
            exp = eng.dispatch("export", {"case_id": cid})
            md = Path(exp["path"]).read_text(encoding="utf-8")
            self.assertIn("subprocess\\_sealed\\_isolated", md)
            self.assertIn("runner\\_seal\\_verified", md)
            self.assertIn(case_doc["reviews"]["overclaim"]["isolation_receipt"]["transcript_sha256"], md)

            buf_html = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_html})()):
                rc_html = cli_main(["report", "--workspace", str(ws), "--case-id", cid, "--output", "reports/iso.html"])
            self.assertEqual(rc_html, 0)
            html = (ws / "reports" / "iso.html").read_text(encoding="utf-8")
            self.assertIn("subprocess_sealed_isolated", html)
            self.assertIn(case_doc["reviews"]["overclaim"]["isolation_receipt"]["transcript_sha256"], html)

    def test_tampered_packet_sha256_forged_seal_and_timeout_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            (ws / "d.txt").write_text("Observation record N=50 measured value = 42.1 (SD 3.2).\n", encoding="utf-8")
            cid = eng.dispatch("create_case", {"question": "What was observed?", "draft": "Draft."})["case_id"]
            ev = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "d.txt", "kind": "observation", "provenance": "observed",
                "quote": "Observation record N=50 measured value = 42.1 (SD 3.2).", "location": "line 1",
            })["evidence_id"]
            eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C1", "text": "Observed value was 42.1.",
                "claim_type": "description", "evidence_level": "recorded",
                "scope": "Observed sample N=50", "evidence_ids": [ev],
                "design_families": ["observational"], "alternatives": ["Recording error"],
            })
            eng.dispatch("freeze", {"case_id": cid})
            over = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
            real_sha = packet_content_sha256(over)
            base_review = {
                "case_id": cid, "role": "overclaim",
                "packet_id": over["packet_id"], "input_digest": over["input_digest"],
                "reviewer": {"context_id": "over-sec", "model": "test-model"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Literal quote anchors 42.1.", "evidence_ids": [ev]}],
                "unread_evidence_ids": [], "findings": [],
            }

            # 1. Tampered packet_sha256 rejected even with valid packet_nonce
            with self.assertRaises(ContractError) as ctx_sha:
                eng.dispatch("submit_review", {
                    **base_review,
                    "isolation_receipt": {
                        "runner": "manual-runner",
                        "packet_nonce": over["packet_nonce"],
                        "packet_sha256": "f" * 64,
                        "parent_history_messages": 0,
                        "memory_enabled": False,
                        "tool_profile": "review",
                    },
                })
            self.assertEqual(ctx_sha.exception.code, "invalid_isolation_receipt")

            # 2. Forged HMAC runner_seal rejected even with valid nonce + packet_sha256
            with self.assertRaises(ContractError) as ctx_seal:
                eng.dispatch("submit_review", {
                    **base_review,
                    "isolation_receipt": {
                        "runner": "forged-runner",
                        "packet_nonce": over["packet_nonce"],
                        "packet_sha256": real_sha,
                        "parent_history_messages": 0,
                        "memory_enabled": False,
                        "tool_profile": "review",
                        "env_scrubbed": True,
                        "isolated_cwd": True,
                        "runner_seal": "a" * 64,
                    },
                })
            self.assertEqual(ctx_seal.exception.code, "invalid_isolation_receipt")

            # 3. Unsealed valid receipt remains accepted as runner_verified_isolated (backward-compatible)
            ok = eng.dispatch("submit_review", {
                **base_review,
                "isolation_receipt": {
                    "runner": "manual-runner",
                    "packet_nonce": over["packet_nonce"],
                    "packet_sha256": real_sha,
                    "parent_history_messages": 0,
                    "memory_enabled": False,
                    "tool_profile": "review",
                },
            })
            self.assertEqual(ok["review"]["isolation_grade"]["grade"], "runner_verified_isolated")
            self.assertFalse(ok["review"]["isolation_receipt"]["runner_seal_verified"])

            # 4. Timeout handling returns exit 124 cleanly
            timeout_res = run_isolated_subprocess(
                ws, cid, "underclaim",
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.3,
            )
            self.assertEqual(timeout_res["termination_status"], "timed_out")
            self.assertIsNone(timeout_res["exit_status"])
            self.assertFalse(timeout_res["submitted"])

    def test_allow_env_passthrough_while_unallowed_secret_stays_scrubbed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            (ws / "d.txt").write_text("Observation record N=50 measured value = 42.1 (SD 3.2).\n", encoding="utf-8")
            cid = eng.dispatch("create_case", {"question": "What was observed?", "draft": "Draft."})["case_id"]
            ev = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "d.txt", "kind": "observation", "provenance": "observed",
                "quote": "Observation record N=50 measured value = 42.1 (SD 3.2).", "location": "line 1",
            })["evidence_id"]
            eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C1", "text": "Observed value was 42.1.",
                "claim_type": "description", "evidence_level": "recorded",
                "scope": "Observed sample N=50", "evidence_ids": [ev],
                "design_families": ["observational"], "alternatives": ["Recording error"],
            })
            eng.dispatch("freeze", {"case_id": cid})

            adapter = Path(tmp) / "env_probe_adapter.py"
            adapter.write_text(
                "import json, os\n"
                "assert os.environ.get('PARRHESIA_ALLOWED_FLAG') == 'yes_allowed'\n"
                "assert os.environ.get('PARRHESIA_SECRET_NO_LEAK') is None\n"
                "assert os.environ.get('PARRHESIA_MEMORY_ENABLED') == 'false'\n"
                "pkt = json.loads(open(os.environ['PARRHESIA_PACKET_PATH'], encoding='utf-8').read())\n"
                "ev_id = pkt['evidence'][0]['evidence_id']\n"
                "role = os.environ['PARRHESIA_ROLE']\n"
                "print(json.dumps({\n"
                "    'reviewer': {'context_id': f'env-{role}', 'model': 'env-test'},\n"
                "    'covered_claim_ids': ['C1'],\n"
                "    'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'Literal quote anchors 42.1.', 'evidence_ids': [ev_id]}],\n"
                "    'unread_evidence_ids': [],\n"
                "    'findings': [],\n"
                "}))\n",
                encoding="utf-8",
            )
            prev_allow = os.environ.get("PARRHESIA_ALLOWED_FLAG")
            prev_sec = os.environ.get("PARRHESIA_SECRET_NO_LEAK")
            prev_mem = os.environ.get("PARRHESIA_MEMORY_ENABLED")
            os.environ["PARRHESIA_ALLOWED_FLAG"] = "yes_allowed"
            os.environ["PARRHESIA_SECRET_NO_LEAK"] = "must_not_pass"
            os.environ["PARRHESIA_MEMORY_ENABLED"] = "true"
            try:
                res = run_isolated_subprocess(
                    ws, cid, "overclaim",
                    [sys.executable, "-X", "utf8", str(adapter)],
                    allow_env=["PARRHESIA_ALLOWED_FLAG", "PARRHESIA_MEMORY_ENABLED"],
                    auto_submit=True,
                )
            finally:
                if prev_allow is None:
                    os.environ.pop("PARRHESIA_ALLOWED_FLAG", None)
                else:
                    os.environ["PARRHESIA_ALLOWED_FLAG"] = prev_allow
                if prev_sec is None:
                    os.environ.pop("PARRHESIA_SECRET_NO_LEAK", None)
                else:
                    os.environ["PARRHESIA_SECRET_NO_LEAK"] = prev_sec
                if prev_mem is None:
                    os.environ.pop("PARRHESIA_MEMORY_ENABLED", None)
                else:
                    os.environ["PARRHESIA_MEMORY_ENABLED"] = prev_mem
            self.assertTrue(res["submitted"], msg=res)
            self.assertEqual(res["isolation_grade"]["grade"], "subprocess_sealed_isolated")

    def _build_frozen_prediction_case(self, ws: Path, draft_text: str = "Initial draft text.") -> tuple[Engine, str, str]:
        eng = Engine(ws)
        (ws / "ext.txt").write_text(
            "External cohort (N=120): AUROC = 0.84 (95% CI 0.77 to 0.90, calibration slope = 0.96).\n",
            encoding="utf-8",
        )
        cid = eng.dispatch("create_case", {
            "question": "Does the risk model generalize externally?",
            "draft": draft_text,
            "domain": "scientific",
            "blind": True,
            "blind_mode": "estimate_first",
            "writer_context_id": "writer-dual",
        })["case_id"]
        ev = eng.dispatch("register_evidence", {
            "case_id": cid, "path": "ext.txt", "kind": "prediction_external",
            "provenance": "observed",
            "quote": "AUROC = 0.84 (95% CI 0.77 to 0.90, calibration slope = 0.96).",
            "location": "line 1",
        })["evidence_id"]
        eng.dispatch("upsert_claim", {
            "case_id": cid, "claim_id": "C1",
            "text": "Model achieves AUROC 0.84 (95% CI 0.77 to 0.90) in external cohort N=120.",
            "claim_type": "prediction", "evidence_level": "externally_validated",
            "claim_basis": "empirical", "scope": "External cohort N=120",
            "evidence_ids": [ev], "design_families": ["prediction"],
            "effect": {"estimate": "AUROC 0.84", "uncertainty": "95% CI 0.77 to 0.90"},
            "contribution": "External discrimination verified.",
            "alternatives": [{"explanation": "Leakage", "status": "excluded", "reason": "Independent external hospital cohort."}],
            "effect_records": [{
                "id": "e1", "endpoint": "1-year recurrence", "endpoint_role": "primary",
                "metric": "AUROC", "estimate": 0.84, "ci_low": 0.77, "ci_high": 0.90,
                "n": 120, "null_value": 0.50, "direction": "higher_better", "claim_direction": "higher_better",
                "beneficial_if": "above_null", "evidence_id": ev,
            }],
            "checks_overrides": {
                "quality": {"status": "pass", "reason": "Complete external cohort follow-up."},
                "batch": {"status": "pass", "reason": "Locked preprocessing."},
                "unit": {"status": "pass", "reason": "120 unique patients."},
                "assumptions": {"status": "pass", "reason": "Calibration slope 0.96."},
                "multiplicity": {"status": "pass", "reason": "Single primary endpoint."},
                "leakage": {"status": "pass", "reason": "Frozen model weights."},
                "baseline": {"status": "pass", "reason": "Exceeds 0.50 chance baseline."},
                "design.prediction.target_horizon": {"status": "pass", "reason": "1-year horizon.", "evidence_ids": [ev]},
                "design.prediction.splits_leakage": {"status": "pass", "reason": "Zero patient overlap.", "evidence_ids": [ev]},
                "design.prediction.calibration_discrimination": {"status": "pass", "reason": "AUROC 0.84, slope 0.96.", "evidence_ids": [ev]},
                "design.prediction.validation_shift": {"status": "pass", "reason": "External site.", "evidence_ids": [ev]},
                "design.prediction.utility": {"status": "not_applicable", "reason": "Utility reserved for prospective study.", "evidence_ids": []},
                "statistics.units_sample_size": {"status": "pass", "reason": "N=120 patients.", "evidence_ids": [ev]},
                "statistics.estimand_scale": {"status": "pass", "reason": "External AUROC.", "evidence_ids": [ev]},
                "statistics.estimate_uncertainty": {"status": "pass", "reason": "AUROC 0.84 (95% CI 0.77-0.90).", "evidence_ids": [ev]},
                "statistics.model_assumptions": {"status": "pass", "reason": "Slope 0.96.", "evidence_ids": [ev]},
                "statistics.missingness_exclusions": {"status": "pass", "reason": "Complete follow-up.", "evidence_ids": [ev]},
                "statistics.multiplicity_selection": {"status": "pass", "reason": "Single endpoint.", "evidence_ids": [ev]},
                "statistics.comparisons_baselines": {"status": "pass", "reason": "Above 0.50.", "evidence_ids": [ev]},
                "statistics.robustness_limits": {"status": "pass", "reason": "External site tested.", "evidence_ids": [ev]},
            },
        })
        eng.dispatch("freeze", {"case_id": cid})
        return eng, cid, ev

    def _write_dual_adapter(self, path: Path) -> None:
        path.write_text(
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "mode = sys.argv[1] if len(sys.argv) > 1 else 'complete'\n"
            "marker = sys.argv[2] if len(sys.argv) > 2 else ''\n"
            "role = os.environ['PARRHESIA_ROLE']\n"
            "assert os.environ.get('PARRHESIA_ISOLATED_RUNNER') == '1'\n"
            "assert not (Path.cwd() / '.parrhesia').exists()\n"
            "pkt = json.loads(Path(os.environ['PARRHESIA_PACKET_PATH']).read_text(encoding='utf-8'))\n"
            "ev_id = pkt['evidence'][0]['evidence_id']\n"
            "if role in ('overclaim', 'underclaim'):\n"
            "    if mode == 'fail_underclaim' and role == 'underclaim':\n"
            "        sys.stderr.write('simulated underclaim failure')\n"
            "        sys.exit(2)\n"
            "    if mode == 'timeout_underclaim' and role == 'underclaim':\n"
            "        time.sleep(5)\n"
            "    out = {\n"
            "        'reviewer': {'context_id': f'dual-{role}', 'model': f'model-{role}'},\n"
            "        'covered_claim_ids': ['C1'],\n"
            "        'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'External cohort N=120 achieves AUROC 0.84 (95% CI 0.77-0.90) with passing checks.', 'evidence_ids': [ev_id]}],\n"
            "        'unread_evidence_ids': [],\n"
            "        'findings': [],\n"
            "        'review_status': 'needs_split' if (mode == 'needs_split' and role == 'overclaim') else 'complete',\n"
            "    }\n"
            "else:\n"
            "    if marker:\n"
            "        Path(marker).write_text('ADJUDICATOR_INVOKED', encoding='utf-8')\n"
            "    out = {\n"
            "        'adjudicator': {'context_id': 'dual-adjudicator', 'model': 'model-adj'},\n"
            "        'unread_evidence_ids': [],\n"
            "        'dispositions': [],\n"
            "        'decisions': [{\n"
            "            'claim_id': 'C1', 'verdict': 'supported', 'claim_type': 'prediction',\n"
            "            'evidence_level': 'externally_validated', 'claim_basis': 'empirical',\n"
            "            'scope': 'External cohort N=120',\n"
            "            'revised_text': 'Model achieves AUROC 0.84 (95% CI 0.77 to 0.90) in external cohort N=120.',\n"
            "            'rationale': 'Parallel isolated reviews and external evidence confirm AUROC 0.84 (95% CI 0.77-0.90).',\n"
            "            'evidence_ids': [ev_id], 'confidence': 'high', 'confidence_reason': 'Anchored external cohort.',\n"
            "            'boundary': 'Prospective clinical utility remains untested.',\n"
            "            'reversal_condition': 'Independent external cohort AUROC drops below 0.70.',\n"
            "            'actionable_stance': 'adopt_within_scope',\n"
            "        }],\n"
            "    }\n"
            "print(json.dumps(out))\n",
            encoding="utf-8",
        )

    def test_run_isolated_dual_review_parallel_needs_split_and_atomic_failure(self):
        # 1. Full parallel execution + isolated adjudication + auto_export via CLI
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws_happy"
            ws.mkdir()
            eng, cid, _ = self._build_frozen_prediction_case(ws)
            adapter = Path(tmp) / "dual_adapter.py"
            self._write_dual_adapter(adapter)

            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main([
                    "run-dual-review", "--workspace", str(ws), "--case-id", cid,
                    "--overclaim-model-route", "route-over",
                    "--underclaim-model-route", "route-under",
                    "--adjudicator-model-route", "route-adj",
                    "--run-adjudication", "--auto-export",
                    "--", sys.executable, "-X", "utf8", str(adapter), "complete",
                ])
            self.assertEqual(rc, 0)
            res = json.loads(buf.getvalue().decode("utf-8"))
            self.assertEqual(res["status"], "exported")
            self.assertEqual(res["state"], "exported")
            audit = res["isolation_audit_summary"]
            self.assertTrue(audit["parallel_execution"])
            for rname, expected_route in (("overclaim", "route-over"), ("underclaim", "route-under"), ("adjudication", "route-adj")):
                rinfo = audit["roles"][rname]
                self.assertEqual(rinfo["grade"], "subprocess_sealed_isolated", msg=rinfo)
                self.assertTrue(rinfo["runner_seal_verified"])
                self.assertTrue(rinfo["env_scrubbed"])
                self.assertTrue(rinfo["isolated_cwd"])
                self.assertEqual(rinfo["model_route"], expected_route)
            self.assertNotEqual(
                res["reviews"]["overclaim"]["packet_nonce"],
                res["reviews"]["underclaim"]["packet_nonce"],
            )
            self.assertNotEqual(
                res["reviews"]["overclaim"]["transcript_sha256"],
                res["reviews"]["underclaim"]["transcript_sha256"],
            )
            md_text = Path(res["export"]["path"]).read_text(encoding="utf-8")
            self.assertIn("adjudication\\_isolation\\_grade", md_text)
            self.assertIn("subprocess\\_sealed\\_isolated", md_text)

        # 2. ready_for_adjudication (no adjudicator cmd) & needs_split halt
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws_ready"
            ws.mkdir()
            eng, cid, _ = self._build_frozen_prediction_case(ws)
            adapter = Path(tmp) / "dual_adapter.py"
            self._write_dual_adapter(adapter)
            ready = run_isolated_dual_review(
                ws, cid,
                overclaim_cmd=[sys.executable, "-X", "utf8", str(adapter), "complete"],
                underclaim_cmd=[sys.executable, "-X", "utf8", str(adapter), "complete"],
            )
            self.assertEqual(ready["status"], "ready_for_adjudication")
            self.assertEqual(ready["state"], "reviewed")
            self.assertTrue(ready["adjudication_id"].startswith("adj_"))

            ws_split = Path(tmp) / "ws_split"
            ws_split.mkdir()
            eng_s, cid_s, _ = self._build_frozen_prediction_case(ws_split)
            adj_marker = Path(tmp) / "adj_should_not_exist.txt"
            buf_s = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_s})()):
                rc_s = cli_main([
                    "run-dual-review", "--workspace", str(ws_split), "--case-id", cid_s,
                    "--run-adjudication",
                    "--", sys.executable, "-X", "utf8", str(adapter), "needs_split", str(adj_marker),
                ])
            self.assertEqual(rc_s, 0)
            split_res = json.loads(buf_s.getvalue().decode("utf-8"))
            self.assertEqual(split_res["status"], "review_blocked_needs_split")
            self.assertEqual(split_res["state"], "review_blocked")
            self.assertIsNone(split_res["adjudication"])
            self.assertFalse(adj_marker.exists(), "Adjudicator must not launch after needs_split")

        # 3. Atomic failure safety (child failure or timeout leaves case cleanly frozen with 0 committed reviews)
        with tempfile.TemporaryDirectory() as tmp:
            adapter = Path(tmp) / "dual_adapter.py"
            self._write_dual_adapter(adapter)

            ws_fail = Path(tmp) / "ws_fail"
            ws_fail.mkdir()
            eng_f, cid_f, _ = self._build_frozen_prediction_case(ws_fail)
            buf_f = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_f})()):
                rc_f = cli_main([
                    "run-dual-review", "--workspace", str(ws_fail), "--case-id", cid_f,
                    "--", sys.executable, "-X", "utf8", str(adapter), "fail_underclaim",
                ])
            self.assertEqual(rc_f, 1)
            fail_res = json.loads(buf_f.getvalue().decode("utf-8"))
            self.assertEqual(fail_res["status"], "review_failed")
            self.assertEqual(fail_res["submitted_roles"], [])
            doc_f = eng_f.dispatch("get_case", {"case_id": cid_f})
            self.assertEqual(doc_f["state"], "frozen")
            self.assertEqual(doc_f["reviews"], {})

            ws_to = Path(tmp) / "ws_to"
            ws_to.mkdir()
            eng_t, cid_t, _ = self._build_frozen_prediction_case(ws_to)
            buf_t = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_t})()):
                rc_t = cli_main([
                    "run-dual-review", "--workspace", str(ws_to), "--case-id", cid_t,
                    "--timeout", "0.3",
                    "--", sys.executable, "-X", "utf8", str(adapter), "timeout_underclaim",
                ])
            self.assertEqual(rc_t, 124)
            to_res = json.loads(buf_t.getvalue().decode("utf-8"))
            self.assertEqual(to_res["status"], "review_failed")
            self.assertEqual(to_res["reviews"]["underclaim"]["termination_status"], "timed_out")
            self.assertEqual(eng_t.dispatch("get_case", {"case_id": cid_t})["state"], "frozen")

    def test_render_synthesis_report_readonly_svg_escaping_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with self.assertRaises(ContractError) as ctx_empty:
                render_synthesis_report(empty, "reports/syn.html")
            self.assertEqual(ctx_empty.exception.code, "missing_workspace")
            self.assertEqual(list(empty.iterdir()), [])

            ws = Path(tmp) / "ws_syn"
            ws.mkdir()
            eng = Engine(ws)
            c1 = _adjudicate_hr_case(
                eng, ws,
                filename="pilot.txt",
                file_text="Pilot RCT <script>alert(1)</script> (N=120): HR = 0.60 (95% CI 0.45 to 0.80, p = 0.0005).\n",
                quote="HR = 0.60 (95% CI 0.45 to 0.80, p = 0.0005).",
                hr=0.60, ci_low=0.45, ci_high=0.80, p_value=0.0005,
                verdict="supported",
                claim_text="Pilot trial <script>alert(1)</script> shows HR 0.60 (95% CI 0.45 to 0.80).",
                endpoint="1-year relapse <script>alert(1)</script>",
                reversal_triggers=[{
                    "id": "T_NULL",
                    "description": "Independent replication or pooled HR 95% CI crosses 1.0.",
                    "kind": "effect_metric",
                    "metric": "HR",
                    "field": "estimate",
                    "operator": "crosses_null",
                    "target_verdict": "unsupported",
                }],
            )
            c2 = _adjudicate_hr_case(
                eng, ws,
                filename="rep.txt",
                file_text="Large Replication (N=800): HR = 1.04 (95% CI 0.88 to 1.23, p = 0.64).\n",
                quote="HR = 1.04 (95% CI 0.88 to 1.23, p = 0.64).",
                hr=1.04, ci_low=0.88, ci_high=1.23, p_value=0.64,
                verdict="unsupported",
                claim_text="Large replication fails to reproduce benefit (HR 1.04, 95% CI 0.88 to 1.23).",
                endpoint="1-year relapse <script>alert(1)</script>",
                prior_case_ids=[c1], case_relation="replication",
            )
            # Duplicate bytes -> excluded by deduplication guard
            _adjudicate_hr_case(
                eng, ws,
                filename="pilot_dup.txt",
                file_text="Pilot RCT <script>alert(1)</script> (N=120): HR = 0.60 (95% CI 0.45 to 0.80, p = 0.0005).\n",
                quote="HR = 0.60 (95% CI 0.45 to 0.80, p = 0.0005).",
                hr=0.60, ci_low=0.45, ci_high=0.80, p_value=0.0005,
                verdict="supported",
                claim_text="Duplicate copy reports HR 0.60 (95% CI 0.45 to 0.80).",
                endpoint="1-year relapse <script>alert(1)</script>",
                prior_case_ids=[c1], case_relation="replication",
            )

            db_before = eng.database.read_bytes()

            # 1. JSON-only CLI synthesize matches analyze_design(mode="lineage_synthesis")
            buf_json = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_json})()):
                rc_json = cli_main(["synthesize", "--workspace", str(ws)])
            self.assertEqual(rc_json, 0)
            syn_cli = json.loads(buf_json.getvalue().decode("utf-8"))
            self.assertFalse(syn_cli["case_mutated"])
            syn_mcp = eng.dispatch("analyze_design", {"mode": "lineage_synthesis"})
            self.assertEqual(syn_cli["living_status"], syn_mcp["living_status"])
            self.assertEqual(syn_cli["independent_pooled_case_count"], 2)

            # 2. Offline HTML synthesis with SVG forest plot & strict XSS escaping
            buf_html = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_html})()):
                rc_html = cli_main([
                    "synthesize", "--workspace", str(ws),
                    "--output", "reports/living.html",
                ])
            self.assertEqual(rc_html, 0)
            html_res = json.loads(buf_html.getvalue().decode("utf-8"))
            self.assertFalse(html_res["case_mutated"])
            html = Path(html_res["path"]).read_text(encoding="utf-8")
            self.assertIn("<svg viewBox=", html)
            self.assertIn("Null (1)", html)
            self.assertIn("T_NULL", html)
            self.assertIn("non_independent", html)
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

            # SQLite DB bytes must be byte-for-byte untouched by read-only synthesis
            self.assertEqual(eng.database.read_bytes(), db_before)

            # 3. Overwriting existing synthesis HTML is refused
            with self.assertRaises(ContractError) as ctx_dup:
                render_synthesis_report(ws, "reports/living.html")
            self.assertEqual(ctx_dup.exception.code, "export_exists")

            # 4. Tampering with a frozen case rejects synthesis cleanly
            with eng._connect() as db:
                raw_doc = db.execute("SELECT document FROM cases WHERE id=?", (c1,)).fetchone()[0]
                altered = json.loads(raw_doc)
                altered["draft"] = "TAMPERED_AFTER_FREEZE"
                db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(altered), c1))
            with self.assertRaises(ContractError) as ctx_tamper:
                render_synthesis_report(ws, "reports/tampered.html")
            self.assertEqual(ctx_tamper.exception.code, "frozen_integrity_error")
            self.assertFalse((ws / "reports" / "tampered.html").exists())

    def test_two_stage_estimate_first_commit_reveal_and_stage1_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng, cid, ev = self._build_frozen_prediction_case(
                ws, draft_text="Overstated draft claiming broad causal efficacy.",
            )

            # 1. Stage 1 packet strips question, draft, hypotheses, claim text/type/level/scope, and claim_direction
            s1_pkt = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim", "stage": "evidence_only"})
            full_pkt = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
            self.assertEqual(s1_pkt["stage"], "evidence_only")
            self.assertNotIn("stage", full_pkt)
            self.assertIsNone(s1_pkt["question"])
            self.assertIsNone(s1_pkt["draft"])
            self.assertEqual(s1_pkt["hypotheses"], [])
            self.assertNotIn("text", s1_pkt["claims"][0])
            self.assertNotIn("claim_type", s1_pkt["claims"][0])
            self.assertNotIn("claim_direction", s1_pkt["evidence_first_dossier"]["quantitative_and_checks"][0]["effect_records"][0])
            self.assertIn("text", full_pkt["claims"][0])
            self.assertEqual(full_pkt["evidence_first_dossier"]["quantitative_and_checks"][0]["effect_records"][0]["claim_direction"], "higher_better")

            # Stage 1 packet_nonce cannot satisfy Stage 2 submit_review
            with self.assertRaises(ContractError) as ctx_s1_nonce:
                eng.dispatch("submit_review", {
                    "case_id": cid, "role": "overclaim",
                    "packet_id": s1_pkt["packet_id"], "input_digest": s1_pkt["input_digest"],
                    "reviewer": {"context_id": "s1-replay", "model": "test"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "AUROC 0.84 anchored.", "evidence_ids": [ev]}],
                    "unread_evidence_ids": [], "findings": [],
                    "isolation_receipt": {
                        "runner": "replay",
                        "packet_nonce": s1_pkt["packet_nonce"],
                        "packet_sha256": packet_content_sha256(s1_pkt),
                        "parent_history_messages": 0,
                        "memory_enabled": False,
                        "tool_profile": "review",
                    },
                })
            self.assertEqual(ctx_s1_nonce.exception.code, "invalid_isolation_receipt")

            # CLI isolate-packet --stage evidence_only works cleanly
            buf_iso = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_iso})()):
                rc_iso = cli_main([
                    "isolate-packet", "--workspace", str(ws), "--case-id", cid,
                    "--role", "underclaim", "--stage", "evidence_only",
                ])
            self.assertEqual(rc_iso, 0)
            iso_bundle = json.loads(buf_iso.getvalue().decode("utf-8"))
            self.assertEqual(iso_bundle["stage"], "evidence_only")
            self.assertNotIn("text", iso_bundle["packet"]["claims"][0])

            # 2. Two-stage isolated dual review + adjudication + export
            adapter = ws / "two_stage_adapter.py"
            adapter.write_text(
                "import hashlib, json, os\n"
                "from pathlib import Path\n"
                "pkt = json.loads(Path(os.environ['PARRHESIA_PACKET_PATH']).read_text(encoding='utf-8'))\n"
                "role = os.environ['PARRHESIA_ROLE']\n"
                "stage = os.environ['PARRHESIA_PACKET_STAGE']\n"
                "ev_id = pkt['evidence'][0]['evidence_id']\n"
                "if role in ('overclaim', 'underclaim') and stage == 'evidence_only':\n"
                "    assert os.environ.get('PARRHESIA_TWO_STAGE_BLIND') == '1'\n"
                "    assert pkt['question'] is None and pkt['draft'] is None\n"
                "    assert 'text' not in pkt['claims'][0]\n"
                "    assert 'claim_direction' not in pkt['evidence_first_dossier']['quantitative_and_checks'][0]['effect_records'][0]\n"
                "    print(json.dumps({\n"
                "        'protocol': 'estimate_first_stage1_v1',\n"
                "        'packet_nonce': pkt['packet_nonce'],\n"
                "        'packet_sha256': os.environ['PARRHESIA_PACKET_SHA256'],\n"
                "        'claims': {\n"
                "            'C1': {\n"
                "                'claim_type': 'prediction', 'evidence_level': 'externally_validated',\n"
                "                'direction': 'higher_better', 'estimate': 0.84, 'ci_low': 0.77, 'ci_high': 0.90,\n"
                "                'rationale': 'External validation N=120 achieves AUROC 0.84 (95% CI 0.77-0.90).',\n"
                "            }\n"
                "        },\n"
                "    }))\n"
                "elif role in ('overclaim', 'underclaim'):\n"
                "    s1_raw = json.loads(Path(os.environ['PARRHESIA_STAGE1_ESTIMATES_PATH']).read_text(encoding='utf-8'))\n"
                "    s1_dig = hashlib.sha256(json.dumps(s1_raw, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()\n"
                "    assert s1_dig == os.environ['PARRHESIA_STAGE1_ESTIMATE_SHA256']\n"
                "    assert 'text' in pkt['claims'][0]\n"
                "    print(json.dumps({\n"
                "        'reviewer': {'context_id': f'ts-{role}', 'model': 'two-stage-local'},\n"
                "        'covered_claim_ids': ['C1'],\n"
                "        'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'Matches locked Stage 1 external AUROC 0.84 (95% CI 0.77-0.90).', 'evidence_ids': [ev_id]}],\n"
                "        'unread_evidence_ids': [], 'findings': [],\n"
                "    }))\n"
                "else:\n"
                "    print(json.dumps({\n"
                "        'adjudicator': {'context_id': 'ts-adj', 'model': 'two-stage-local'},\n"
                "        'unread_evidence_ids': [], 'dispositions': [],\n"
                "        'decisions': [{\n"
                "            'claim_id': 'C1', 'verdict': 'supported', 'claim_type': 'prediction',\n"
                "            'evidence_level': 'externally_validated', 'claim_basis': 'empirical',\n"
                "            'scope': 'External cohort N=120', 'revised_text': 'Model achieves AUROC 0.84 (95% CI 0.77 to 0.90) externally (N=120).',\n"
                "            'rationale': 'Stage 1 blind estimate and Stage 2 review agree on external AUROC 0.84 (95% CI 0.77-0.90).',\n"
                "            'evidence_ids': [ev_id], 'confidence': 'high', 'confidence_reason': 'Anchored external cohort.',\n"
                "            'boundary': 'Clinical net utility awaits prospective study.',\n"
                "            'reversal_condition': 'External AUROC drops below 0.70 in independent multi-site sample.',\n"
                "            'actionable_stance': 'adopt_within_scope',\n"
                "        }],\n"
                "    }))\n",
                encoding="utf-8",
            )
            dual = run_isolated_dual_review(
                ws, cid,
                overclaim_cmd=[sys.executable, "-X", "utf8", str(adapter)],
                underclaim_cmd=[sys.executable, "-X", "utf8", str(adapter)],
                adjudicator_cmd=[sys.executable, "-X", "utf8", str(adapter)],
                two_stage_blind=True,
                auto_export=True,
            )
            self.assertEqual(dual["status"], "exported", msg=dual)
            self.assertTrue(dual["isolation_audit_summary"]["two_stage_blind"])
            over_audit = dual["isolation_audit_summary"]["roles"]["overclaim"]
            self.assertTrue(over_audit["two_stage_blind"])
            self.assertEqual(len(over_audit["stage1_estimate_sha256"]), 64)
            self.assertEqual(len(over_audit["stage1_transcript_sha256"]), 64)
            self.assertTrue(over_audit["workspace_untouched"])
            self.assertIn("two_stage_evidence_only_commit", over_audit["boundaries"]["enforced"])
            self.assertIn("no_kernel_fs_or_network_namespace", over_audit["boundaries"]["not_enforced"])

            case_doc = eng.dispatch("get_case", {"case_id": cid})
            over_rev = case_doc["reviews"]["overclaim"]
            self.assertTrue(over_rev["isolation_grade"]["two_stage_blind_verified"])
            md = Path(dual["export"]["path"]).read_text(encoding="utf-8")
            self.assertIn("two\\_stage\\_blind", md)
            self.assertIn(over_audit["stage1_estimate_sha256"], md)
            self.assertIn("no\\_kernel\\_fs\\_or\\_network\\_namespace", md)

            buf_html = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf_html})()):
                rc_h = cli_main(["report", "--workspace", str(ws), "--case-id", cid, "--output", "reports/two-stage.html"])
            self.assertEqual(rc_h, 0)
            html = (ws / "reports" / "two-stage.html").read_text(encoding="utf-8")
            self.assertIn("two_stage_blind", html)
            self.assertIn("isolation_boundaries", html)

            # 3. Tampering with sealed two_stage_blind receipt fails workspace HMAC verification
            eng2, cid2, _ = self._build_frozen_prediction_case(ws, draft_text="Second case draft.")
            adapter.unlink()  # keep clean; reuse fresh one-shot submission script outside ws? write in Path(tmp)
            s_adapter = Path(tmp) / "s_adapter.py"
            s_adapter.write_text(
                "import json, os\n"
                "from pathlib import Path\n"
                "pkt = json.loads(Path(os.environ['PARRHESIA_PACKET_PATH']).read_text(encoding='utf-8'))\n"
                "role = os.environ['PARRHESIA_ROLE']\n"
                "stage = os.environ['PARRHESIA_PACKET_STAGE']\n"
                "ev_id = pkt['evidence'][0]['evidence_id']\n"
                "if stage == 'evidence_only':\n"
                "    print(json.dumps({'protocol': 'estimate_first_stage1_v1', 'packet_nonce': pkt['packet_nonce'], 'claims': {'C1': {'claim_type': 'prediction', 'evidence_level': 'externally_validated', 'direction': 'higher_better', 'rationale': 'External AUROC 0.84 anchored.'}}}))\n"
                "else:\n"
                "    print(json.dumps({'reviewer': {'context_id': f'ts2-{role}', 'model': 'm'}, 'covered_claim_ids': ['C1'], 'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'AUROC 0.84 (95% CI 0.77-0.90) anchored.', 'evidence_ids': [ev_id]}], 'unread_evidence_ids': [], 'findings': []}))\n",
                encoding="utf-8",
            )
            single_res = run_isolated_subprocess(
                ws, cid2, "overclaim", [sys.executable, "-X", "utf8", str(s_adapter)],
                two_stage_blind=True, auto_submit=False,
            )
            self.assertEqual(single_res["termination_status"], "completed", msg=single_res)
            bad_sub = dict(single_res["submission_payload"])
            bad_rec = dict(bad_sub["isolation_receipt"])
            bad_rec["stage1_estimate_sha256"] = "0" * 64
            bad_sub["isolation_receipt"] = bad_rec
            with self.assertRaises(ContractError) as ctx_bad_seal:
                eng2.dispatch("submit_review", bad_sub)
            self.assertEqual(ctx_bad_seal.exception.code, "invalid_isolation_receipt")

    def test_subprocess_containment_env_redirection_offline_tamper_and_strict_os(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            eng, cid, _ = self._build_frozen_prediction_case(ws)
            probe = Path(tmp) / "containment_probe.py"
            probe.write_text(
                "import json, os, stat\n"
                "from pathlib import Path\n"
                "home = Path(os.environ['HOME']).resolve()\n"
                "for key in ('APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):\n"
                "    val = Path(os.environ[key]).resolve()\n"
                "    assert val == home or home in val.parents, f'{key} escaped sandbox: {val}'\n"
                "assert os.environ.get('LD_PRELOAD') is None\n"
                "assert os.environ.get('PARRHESIA_RUNNER_KEY') is None\n"
                "assert os.environ.get('PARRHESIA_ALLOWED_FLAG') == 'ok_flag'\n"
                "assert os.environ.get('HTTP_PROXY') == 'http://127.0.0.1:9'\n"
                "assert os.environ.get('HTTPS_PROXY') == 'http://127.0.0.1:9'\n"
                "assert os.environ.get('PARRHESIA_OFFLINE_ENV') == '1'\n"
                "assert os.environ.get('HF_HUB_OFFLINE') == '1'\n"
                "pkt_path = Path(os.environ['PARRHESIA_PACKET_PATH'])\n"
                "assert (pkt_path.stat().st_mode & stat.S_IWRITE) == 0\n"
                "pkt = json.loads(pkt_path.read_text(encoding='utf-8'))\n"
                "ev_id = pkt['evidence'][0]['evidence_id']\n"
                "print(json.dumps({\n"
                "    'reviewer': {'context_id': 'contain-over', 'model': 'm'},\n"
                "    'covered_claim_ids': ['C1'],\n"
                "    'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'AUROC 0.84 (95% CI 0.77-0.90) verified.', 'evidence_ids': [ev_id]}],\n"
                "    'unread_evidence_ids': [], 'findings': [],\n"
                "}))\n",
                encoding="utf-8",
            )
            env_backup = {k: os.environ.get(k) for k in ("LD_PRELOAD", "PYTHONPATH", "APPDATA", "PARRHESIA_ALLOWED_FLAG", "TEST_WS_DIR")}
            os.environ["LD_PRELOAD"] = "/tmp/fake.so"
            os.environ["PYTHONPATH"] = "/tmp/fake_py"
            os.environ["APPDATA"] = "/tmp/host_appdata"
            os.environ["PARRHESIA_ALLOWED_FLAG"] = "ok_flag"
            os.environ["TEST_WS_DIR"] = str(ws)
            try:
                res = run_isolated_subprocess(
                    ws, cid, "overclaim",
                    [sys.executable, "-X", "utf8", str(probe)],
                    allow_env=["PARRHESIA_ALLOWED_FLAG", "LD_PRELOAD", "PYTHONPATH", "APPDATA", "PARRHESIA_RUNNER_KEY"],
                    offline_env=True,
                    auto_submit=True,
                )
                self.assertTrue(res["submitted"], msg=res)
                self.assertTrue(res["workspace_untouched"])

                # 2. Tampering with .parrhesia/runner.key triggers sandbox_boundary_violation
                tamper_script = Path(tmp) / "tamper.py"
                tamper_script.write_text(
                    "import json, os\n"
                    "from pathlib import Path\n"
                    "pkt = json.loads(Path(os.environ['PARRHESIA_PACKET_PATH']).read_text(encoding='utf-8'))\n"
                    "(Path(os.environ['TEST_WS_DIR']) / '.parrhesia' / 'runner.key').write_bytes(b'X' * 32)\n"
                    "print(json.dumps({'reviewer': {'context_id': 'tamp-u', 'model': 'm'}, 'covered_claim_ids': ['C1'], 'claim_stances': [{'claim_id': 'C1', 'stance': 'supported', 'rationale': 'AUROC 0.84 anchored.', 'evidence_ids': [pkt['evidence'][0]['evidence_id']]}], 'unread_evidence_ids': [], 'findings': []}))\n",
                    encoding="utf-8",
                )
                tamper_res = run_isolated_subprocess(
                    ws, cid, "underclaim",
                    [sys.executable, "-X", "utf8", str(tamper_script)],
                    allow_env=["TEST_WS_DIR"],
                    auto_submit=True,
                )
                self.assertEqual(tamper_res["termination_status"], "sandbox_boundary_violation")
                self.assertEqual(tamper_res["error"], "sandbox_boundary_violation")
                self.assertFalse(tamper_res["workspace_untouched"])
                self.assertFalse(tamper_res["submitted"])
                self.assertNotIn("isolation_receipt", tamper_res)
            finally:
                for k, v in env_backup.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            # 3. strict_os fails loudly with sandbox_unavailable when unavailable, and wraps bwrap/sandbox-exec when present
            with patch("parrhesia.isolated_runner._detect_os_sandbox_backend", return_value=None):
                with self.assertRaises(ContractError) as ctx_sbx:
                    run_isolated_subprocess(ws, cid, "underclaim", [sys.executable, "-c", "pass"], sandbox_mode="strict_os")
                self.assertEqual(ctx_sbx.exception.code, "sandbox_unavailable")
            bwrap_cmd = _wrap_os_sandbox_cmd(["python", "r.py"], sandbox_dir=Path("/tmp/sbx"), backend="bwrap", offline_env=True)
            self.assertEqual(bwrap_cmd[:3], ["bwrap", "--ro-bind", "/"])
            self.assertIn("--unshare-net", bwrap_cmd)
            sb_cmd = _wrap_os_sandbox_cmd(["python", "r.py"], sandbox_dir=Path("/tmp/sbx"), backend="sandbox-exec", offline_env=True)
            self.assertEqual(sb_cmd[0], "sandbox-exec")
            self.assertIn("(deny network*)", sb_cmd[2])

    def test_semantic_cohort_deduplication_three_layers_and_html_rendering(self):
        # Layer 1: ancestor_evidence_sha256, explicit_cohort_id, registry_or_accession_id, shared_source_doi vs distinct cohort_id override
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            raw_content = "patient_id,hr,ci\n1,0.72,0.58-0.90\n"
            c1 = _adjudicate_hr_case(
                eng, ws,
                filename="c1_ukb.txt",
                file_text="Cohort UKB wave 1 NCT01234567 and doi:10.1000/mainpaper showed HR = 0.72 (95% CI 0.58 to 0.90, p=0.004).\n",
                quote="Cohort UKB wave 1 NCT01234567 and doi:10.1000/mainpaper showed HR = 0.72 (95% CI 0.58 to 0.90, p=0.004).",
                hr=0.72, ci_low=0.58, ci_high=0.90, p_value=0.004, verdict="supported",
                claim_text="Treatment X reduces hazard (HR = 0.72, 95% CI 0.58-0.90).",
                cohort_id="ukb-wave1", n=200,
                parent_source=("shared_raw.txt", raw_content),
            )
            c_indep = _adjudicate_hr_case(
                eng, ws,
                filename="c2_finn.txt",
                file_text="Independent FinnGen replication HR = 0.75 (95% CI 0.60 to 0.94, p=0.011).\n",
                quote="Independent FinnGen replication HR = 0.75 (95% CI 0.60 to 0.94, p=0.011).",
                hr=0.75, ci_low=0.60, ci_high=0.94, p_value=0.011, verdict="supported",
                claim_text="FinnGen confirms hazard reduction (HR = 0.75, 95% CI 0.60-0.94).",
                cohort_id="finngen-r9", n=180,
                prior_case_ids=[c1], case_relation="replication",
            )
            c_anc = _adjudicate_hr_case(
                eng, ws,
                filename="c3_anc.txt",
                file_text="Re-derived table from upstream raw extract HR = 0.71 (95% CI 0.56 to 0.89, p=0.003).\n",
                quote="Re-derived table from upstream raw extract HR = 0.71 (95% CI 0.56 to 0.89, p=0.003).",
                hr=0.71, ci_low=0.56, ci_high=0.89, p_value=0.003, verdict="supported",
                claim_text="Derived extract shows HR = 0.71 (95% CI 0.56-0.89).",
                n=210,
                parent_source=("shared_raw_copy.txt", raw_content),
                prior_case_ids=[c1], case_relation="replication",
            )
            c_cid = _adjudicate_hr_case(
                eng, ws,
                filename="c4_cid.txt",
                file_text="Follow-up extract labeled same cohort HR = 0.73 (95% CI 0.59 to 0.91, p=0.005).\n",
                quote="Follow-up extract labeled same cohort HR = 0.73 (95% CI 0.59 to 0.91, p=0.005).",
                hr=0.73, ci_low=0.59, ci_high=0.91, p_value=0.005, verdict="supported",
                claim_text="Same cohort_id shows HR = 0.73 (95% CI 0.59-0.91).",
                cohort_id="  UKB-Wave1 ", n=205,
                prior_case_ids=[c1], case_relation="replication",
            )
            c_reg = _adjudicate_hr_case(
                eng, ws,
                filename="c5_reg.txt",
                file_text="Secondary report citing NCT01234567 without explicit cohort label HR = 0.74 (95% CI 0.57 to 0.96, p=0.02).\n",
                quote="Secondary report citing NCT01234567 without explicit cohort label HR = 0.74 (95% CI 0.57 to 0.96, p=0.02).",
                hr=0.74, ci_low=0.57, ci_high=0.96, p_value=0.02, verdict="supported",
                claim_text="Trial report NCT01234567 shows HR = 0.74 (95% CI 0.57-0.96).",
                n=195,
                prior_case_ids=[c1], case_relation="replication",
            )
            c_doi = _adjudicate_hr_case(
                eng, ws,
                filename="c6_doi.txt",
                file_text="Another table from doi:10.1000/mainpaper without cohort_id HR = 0.70 (95% CI 0.54 to 0.91, p=0.008).\n",
                quote="Another table from doi:10.1000/mainpaper without cohort_id HR = 0.70 (95% CI 0.54 to 0.91, p=0.008).",
                hr=0.70, ci_low=0.54, ci_high=0.91, p_value=0.008, verdict="supported",
                claim_text="Table from doi:10.1000/mainpaper gives HR = 0.70 (95% CI 0.54-0.91).",
                n=190,
                prior_case_ids=[c1], case_relation="replication",
            )
            c_override = _adjudicate_hr_case(
                eng, ws,
                filename="c7_override.txt",
                file_text="AllOfUs validation arm reported inside doi:10.1000/mainpaper HR = 0.78 (95% CI 0.63 to 0.97, p=0.025).\n",
                quote="AllOfUs validation arm reported inside doi:10.1000/mainpaper HR = 0.78 (95% CI 0.63 to 0.97, p=0.025).",
                hr=0.78, ci_low=0.63, ci_high=0.97, p_value=0.025, verdict="supported",
                claim_text="Distinct explicit cohort in shared paper DOI yields HR = 0.78 (95% CI 0.63-0.97).",
                cohort_id="allofus-v2", n=220,
                prior_case_ids=[c1], case_relation="replication",
            )
            syn = eng.dispatch("analyze_design", {"mode": "lineage_synthesis"})
            self.assertEqual(syn["independent_pooled_case_ids"], sorted([c1, c_indep, c_override]))
            mechs = {e["case_id"]: e["overlap_mechanism"] for e in syn["deduplication_guard"]["excluded_non_independent"]}
            self.assertEqual(mechs[c_anc], "ancestor_evidence_sha256")
            self.assertEqual(mechs[c_cid], "explicit_cohort_id")
            self.assertEqual(mechs[c_reg], "registry_or_accession_id")
            self.assertEqual(mechs[c_doi], "shared_source_doi")
            self.assertEqual(syn["independence_basis"], "declared_comparison_links_lineage_hashes_and_explicit_distinct_cohort_ids_verified")

        # Layer 2: suspected numerical clone & high shingle overlap -> blocks replicated_consistent + renders HTML
        with tempfile.TemporaryDirectory() as tmp2:
            ws2 = Path(tmp2)
            eng2 = Engine(ws2)
            prose = (
                "Multicenter hospitalized severe viral pneumonia randomized clinical trial conducted across "
                "sixteen tertiary intensive care units measuring thirty day all cause mortality benefit"
            )
            b1 = _adjudicate_hr_case(
                eng2, ws2,
                filename="s1.txt",
                file_text=f"{prose} showed HR = 0.72 (95% CI 0.68 to 0.76, p=0.0001).\n",
                quote=f"{prose} showed HR = 0.72 (95% CI 0.68 to 0.76, p=0.0001).",
                hr=0.72, ci_low=0.68, ci_high=0.76, p_value=0.0001, verdict="supported",
                claim_text="Trial 1 reduces mortality (HR = 0.72, 95% CI 0.68-0.76).",
                n=1200,
            )
            _adjudicate_hr_case(
                eng2, ws2,
                filename="s2.txt",
                file_text="Distinct independent hospital wording yet identical statistical summary HR = 0.72 (95% CI 0.68 to 0.76, p=0.0001).\n",
                quote="Distinct independent hospital wording yet identical statistical summary HR = 0.72 (95% CI 0.68 to 0.76, p=0.0001).",
                hr=0.72, ci_low=0.68, ci_high=0.76, p_value=0.0001, verdict="supported",
                claim_text="Trial 2 clone reduces mortality (HR = 0.72, 95% CI 0.68-0.76).",
                n=1200, prior_case_ids=[b1], case_relation="replication",
            )
            _adjudicate_hr_case(
                eng2, ws2,
                filename="s3.txt",
                file_text=f"{prose} observed HR = 0.74 (95% CI 0.70 to 0.78, p=0.0002).\n",
                quote=f"{prose} observed HR = 0.74 (95% CI 0.70 to 0.78, p=0.0002).",
                hr=0.74, ci_low=0.70, ci_high=0.78, p_value=0.0002, verdict="supported",
                claim_text="Trial 3 near-duplicate prose shows HR = 0.74 (95% CI 0.70-0.78).",
                n=1350, prior_case_ids=[b1], case_relation="replication",
            )
            syn2 = eng2.dispatch("analyze_design", {"mode": "lineage_synthesis"})
            self.assertEqual(syn2["living_status"], "suspected_duplicate_cohort_review_needed")
            signals = {item["signal"] for item in syn2["deduplication_guard"]["suspected_cohort_overlaps"]}
            self.assertEqual(signals, {"exact_sample_and_effect_clone", "high_text_shingle_overlap"})
            self.assertIn("verify_cohort_independence", {a["action_kind"] for a in syn2["living_next_actions"]})

            rep = render_synthesis_report(ws2, "reports/suspects.html")
            html2 = Path(rep["path"]).read_text(encoding="utf-8")
            self.assertIn("suspected_cohort_overlap", html2)
            self.assertIn("Suspected Cohort Overlaps", html2)
            self.assertIn("3-Layer Cohort Deduplication", html2)


if __name__ == "__main__":
    unittest.main()
