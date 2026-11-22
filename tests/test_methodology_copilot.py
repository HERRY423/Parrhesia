"""Mathematical accuracy and proactive integration tests for Moat 2 (Computable Methodology Co-Pilot)."""
from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.methods import _chi2_sf, analyze_design


class MethodologyCopilotTests(unittest.TestCase):
    def test_dominance_needs_observed_units_and_a_discriminating_test(self):
        for units, passed in ((0, False), (0, True), (100, False)):
            with self.subTest(units=units, passed=passed), tempfile.TemporaryDirectory() as temp:
                result = Engine(Path(temp)).dispatch("analyze_design", {
                    "mode": "evidence_dominance",
                    "hypotheses": [
                        {"id": "H1", "statement": "Planned randomized comparison", "design_tier": "randomized",
                         "independent_units": units, "fatal_flaws": 0, "direct_test_passed": passed},
                        {"id": "H2", "statement": "Competing observational comparison", "design_tier": "observational_adjusted",
                         "independent_units": 0, "fatal_flaws": 0},
                    ],
                })
                self.assertEqual(result["asymmetry_status"], "genuinely_unresolved")
                self.assertIsNone(result["favored_hypothesis_id"])
                self.assertNotIn("strictly dominates", result["anti_neutrality_directive"])
                if units == 0:
                    self.assertEqual(result["weight_margin"], 0)

    def test_prediction_utility_from_counts_preserves_unknown_stage_and_scoped_result(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Engine(Path(temp)).dispatch("analyze_design", {
                "mode": "prediction_utility_audit", "threshold_probability": 0.30,
                "confusion": {"tp": 10, "fp": 60, "tn": 30, "fn": 0},
            })
        self.assertEqual(result["validation_stage"], "unknown")
        self.assertAlmostEqual(result["decision_curve_utility"]["delta_net_benefit_vs_best_default"], -0.157143)
        self.assertIn("for the supplied inputs", result["guidance"])
        self.assertIn("Actual clinical outcomes after deployment require separate evidence", result["guidance"])

    # ------------------------------------------------------------------
    # 1. Exact special-function math verification
    # ------------------------------------------------------------------
    def test_chi2_sf_matches_exact_analytical_quantiles(self):
        # Critical values at p = 0.05 for df = 1, 2, 4, 10 and p = 0.001 for df = 10
        self.assertAlmostEqual(_chi2_sf(3.8414588, 1), 0.05, places=6)
        self.assertAlmostEqual(_chi2_sf(5.9914645, 2), math.exp(-5.9914645 / 2.0), places=9)
        self.assertAlmostEqual(_chi2_sf(5.9914645, 2), 0.05, places=6)
        self.assertAlmostEqual(_chi2_sf(9.4877290, 4), 0.05, places=6)
        self.assertAlmostEqual(_chi2_sf(18.307038, 10), 0.05, places=6)
        self.assertAlmostEqual(_chi2_sf(29.588298, 10), 0.001, places=5)
        self.assertEqual(_chi2_sf(0.0, 3), 1.0)

    # ------------------------------------------------------------------
    # 2. Multiplicity audit (Bonferroni, Sidak, Holm-Bonferroni, BH-FDR)
    # ------------------------------------------------------------------
    def test_multiplicity_audit_holm_bh_sidak_and_fork_inflation(self):
        res = analyze_design({
            "mode": "multiplicity_audit",
            "alpha": 0.05,
            "p_values": [
                {"id": "p1", "p_value": 0.005, "role": "primary"},
                {"id": "p2", "p_value": 0.015, "role": "secondary"},
                {"id": "p3", "p_value": 0.04, "role": "subgroup"},
                {"id": "p4", "p_value": 0.20, "role": "exploratory"},
            ],
        })
        self.assertEqual(res["effective_family_size"], 4)
        self.assertAlmostEqual(res["global_null_fwer_at_alpha"], 1.0 - 0.95 ** 4, places=5)
        by_id = {r["id"]: r for r in res["adjusted_tests"]}
        self.assertAlmostEqual(by_id["p1"]["holm_p"], 0.02, places=6)
        self.assertAlmostEqual(by_id["p2"]["holm_p"], 0.045, places=6)
        self.assertAlmostEqual(by_id["p3"]["holm_p"], 0.08, places=6)
        self.assertAlmostEqual(by_id["p1"]["bh_fdr_q"], 0.02, places=6)
        self.assertAlmostEqual(by_id["p2"]["bh_fdr_q"], 0.03, places=6)
        self.assertAlmostEqual(by_id["p3"]["bh_fdr_q"], 0.04 * 4 / 3, places=5)
        self.assertEqual(by_id["p1"]["status"], "survives_fwer")
        self.assertEqual(by_id["p2"]["status"], "survives_fwer")
        self.assertEqual(by_id["p3"]["status"], "fails_multiplicity")
        self.assertEqual(by_id["p4"]["status"], "not_nominally_significant")
        self.assertFalse(res["cherry_picking_risk"])

        # Exploratory fork inflation turns nominal p=0.02 into cherry_picking_risk
        forked = analyze_design({
            "mode": "multiplicity_audit",
            "p_values": [{"id": "best_seed", "p_value": 0.02, "role": "primary"}],
            "prior_exploratory_forks": 9,
        })
        self.assertEqual(forked["effective_family_size"], 10)
        self.assertTrue(forked["cherry_picking_risk"])
        self.assertAlmostEqual(forked["adjusted_tests"][0]["holm_p"], 0.20, places=6)
        self.assertEqual(forked["adjusted_tests"][0]["status"], "fails_multiplicity")

    # ------------------------------------------------------------------
    # 3. Interaction & Heterogeneity (Gelman-Stern + DerSimonian-Laird)
    # ------------------------------------------------------------------
    def test_interaction_heterogeneity_gelman_stern_and_meta_analysis(self):
        # Classic Gelman-Stern sig vs non-sig illusion
        illusion = analyze_design({
            "mode": "interaction_heterogeneity",
            "scale": "linear",
            "group_a": {"label": "Subgroup A", "estimate": 0.45, "se": 0.20},
            "group_b": {"label": "Subgroup B", "estimate": 0.25, "se": 0.20},
        })
        self.assertTrue(illusion["group_a"]["significant"])
        self.assertFalse(illusion["group_b"]["significant"])
        self.assertTrue(illusion["sig_vs_nonsig_illusion"])
        self.assertEqual(illusion["classification"], "sig_vs_nonsig_illusion")
        self.assertAlmostEqual(illusion["interaction_se_working"], math.sqrt(0.08), places=5)
        self.assertGreater(illusion["interaction_p_value"], 0.40)

        # Genuine log-scale subgroup interaction
        real_int = analyze_design({
            "mode": "interaction_heterogeneity",
            "scale": "log",
            "group_a": {"label": "Biomarker+", "estimate": 0.55, "ci_low": 0.42, "ci_high": 0.72},
            "group_b": {"label": "Biomarker-", "estimate": 1.05, "ci_low": 0.85, "ci_high": 1.30},
        })
        self.assertEqual(real_int["classification"], "interaction_supported")
        self.assertFalse(real_int["sig_vs_nonsig_illusion"])
        self.assertLess(real_int["interaction_p_value"], 0.001)
        self.assertLess(real_int["interaction_contrast"], 0.60)

        # DerSimonian-Laird heterogeneous meta-analysis: pooled sig, PI crosses null
        meta_het = analyze_design({
            "mode": "interaction_heterogeneity",
            "scale": "log",
            "studies": [
                {"id": "S1", "estimate": 0.50, "ci_low": 0.39, "ci_high": 0.64},
                {"id": "S2", "estimate": 0.68, "ci_low": 0.56, "ci_high": 0.83},
                {"id": "S3", "estimate": 0.82, "ci_low": 0.69, "ci_high": 0.97},
                {"id": "S4", "estimate": 1.06, "ci_low": 0.88, "ci_high": 1.28},
            ],
        })
        self.assertEqual(meta_het["analysis_type"], "dersimonian_laird_meta")
        self.assertGreater(meta_het["i2_percent"], 60.0)
        self.assertGreater(meta_het["tau2"], 0.0)
        self.assertLess(meta_het["q_p_value"], 0.01)
        self.assertTrue(meta_het["random_effects"]["excludes_null"])
        self.assertTrue(meta_het["prediction_interval_crosses_null"])
        self.assertEqual(meta_het["classification"], "pooled_sig_but_prediction_interval_crosses_null")

        # Homogeneous consistent studies -> anti-underclaim confirmation
        meta_hom = analyze_design({
            "mode": "interaction_heterogeneity",
            "scale": "log",
            "studies": [
                {"id": "S1", "estimate": 0.74, "ci_low": 0.62, "ci_high": 0.88},
                {"id": "S2", "estimate": 0.76, "ci_low": 0.64, "ci_high": 0.90},
                {"id": "S3", "estimate": 0.78, "ci_low": 0.66, "ci_high": 0.92},
                {"id": "S4", "estimate": 0.75, "ci_low": 0.63, "ci_high": 0.89},
            ],
        })
        self.assertEqual(meta_hom["i2_percent"], 0.0)
        self.assertEqual(meta_hom["tau2"], 0.0)
        self.assertEqual(meta_hom["classification"], "homogeneous_consistent_effect")

    # ------------------------------------------------------------------
    # 4. Prediction Utility Audit (EPV/Shrinkage + Vickers Net Benefit)
    # ------------------------------------------------------------------
    def test_prediction_utility_audit_epv_shrinkage_and_vickers_net_benefit(self):
        # Closed-form Vickers Net Benefit check
        res = analyze_design({
            "mode": "prediction_utility_audit",
            "validation_stage": "development",
            "events": 40,
            "non_events": 160,
            "candidate_predictors": 10,
            "model_chi2": 25.0,
            "threshold_probability": 0.20,
            "confusion": {"tp": 45, "fp": 15, "tn": 135, "fn": 5},
        })
        self.assertAlmostEqual(res["sample_adequacy"]["epv"], 4.0, places=4)
        self.assertEqual(res["sample_adequacy"]["epv_risk"], "high_overfitting_risk")
        self.assertAlmostEqual(res["sample_adequacy"]["van_houwelingen_shrinkage"], 0.60, places=4)
        self.assertFalse(res["sample_adequacy"]["shrinkage_adequate"])

        dca = res["decision_curve_utility"]
        self.assertAlmostEqual(dca["net_benefit_model"], 0.20625, places=6)
        self.assertAlmostEqual(dca["net_benefit_treat_all"], 0.0625, places=6)
        self.assertAlmostEqual(dca["delta_net_benefit_vs_best_default"], 0.14375, places=6)
        self.assertAlmostEqual(dca["interventions_avoided_per_100"], 57.5, places=2)
        self.assertEqual(dca["utility_classification"], "positive_net_benefit_over_defaults")

        # Harmful threshold where model loses to treat-none
        harmful = analyze_design({
            "mode": "prediction_utility_audit",
            "threshold_probability": 0.60,
            "prevalence": 0.15,
            "sensitivity": 0.60,
            "specificity": 0.70,
        })
        self.assertEqual(harmful["decision_curve_utility"]["utility_classification"], "harmful_net_benefit_below_defaults")
        self.assertLess(harmful["decision_curve_utility"]["delta_net_benefit_vs_best_default"], 0.0)

    # ------------------------------------------------------------------
    # 5. Attrition Bounds (Manski worst-case & tipping-point sensitivity)
    # ------------------------------------------------------------------
    def test_attrition_bounds_manski_and_tipping_point(self):
        # Severe differential dropout flips complete-case benefit (CC: 15/80=18.75% vs 22/52=42.31%, p<0.005)
        # Manski worst case: (15+10)/90=27.8% vs 22/90=24.4% -> RD_worst = +3.3% > 0!
        fragile = analyze_design({
            "mode": "attrition_bounds",
            "beneficial_if": "lower_event_rate",
            "treated": {"events": 15, "analyzed": 80, "missing": 10},
            "control": {"events": 22, "analyzed": 52, "missing": 38},
        })
        self.assertLess(fragile["complete_case"]["risk_difference"], -0.20)
        self.assertLess(fragile["complete_case"]["p_value"], 0.005)
        self.assertFalse(fragile["manski_bounds"]["survives_worst_case_sign"])
        self.assertGreater(fragile["manski_bounds"]["worst_case_rd"], 0.0)
        self.assertEqual(fragile["attrition_robustness"], "fragile_severe_or_differential_attrition")

        # Modest attrition where even Manski worst-case CI remains strictly beneficial (anti-over-defensiveness)
        robust = analyze_design({
            "mode": "attrition_bounds",
            "beneficial_if": "lower_event_rate",
            "treated": {"events": 8, "analyzed": 97, "missing": 3},
            "control": {"events": 40, "analyzed": 96, "missing": 4},
        })
        self.assertTrue(robust["manski_bounds"]["survives_worst_case_sign"])
        self.assertTrue(robust["manski_bounds"]["survives_worst_case_ci"])
        self.assertLess(robust["manski_bounds"]["worst_case_rd"], -0.25)
        self.assertEqual(robust["attrition_robustness"], "robust_survives_manski_worst_case")

    # ------------------------------------------------------------------
    # 6. Proactive Co-Pilot Integration: explore -> upsert_claim -> case_audit -> blind-safe packets
    # ------------------------------------------------------------------
    def test_proactive_copilot_across_explore_upsert_case_audit_and_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)

            # Step 1: L1-Explore with 5 exploratory forks -> copilot_guidance flags FWER inflation
            exp = eng.dispatch("explore", {
                "op": "init",
                "question": "Does observational exposure X cause relapse, and does model M predict 1-year recurrence?",
                "domain": "scientific",
            })
            exp_id = exp["exploration"]["explore_id"]
            eng.dispatch("explore", {
                "op": "upsert_hypothesis",
                "explore_id": exp_id,
                "hypothesis": {
                    "hypothesis_id": "H1",
                    "statement": "Exposure X increases relapse hazard in observational cohort.",
                    "claim_type": "causal_effect",
                    "evidence_level": "identified_under_assumptions",
                    "strongest_rival": "Unmeasured baseline severity confounding drives HR=1.18.",
                    "discriminating_experiment": "Negative-control outcome and propensity-score sensitivity.",
                    "cost": "1 week observational reanalysis.",
                    "stopping_rule": "Stop after negative-control and E-value sensitivity complete.",
                    "kill_condition": "E-value CI limit drops below 1.25 or negative-control HR excludes 1.0.",
                },
            })
            run = eng.dispatch("explore", {
                "op": "log_run",
                "explore_id": exp_id,
                "hypothesis_id": "H1",
                "summary": "Tested 5 covariate adjustment specifications before selecting HR=1.18 (p=0.025).",
                "outcome_status": "completed",
                "fork_count_delta": 5,
            })
            self.assertIn("copilot_guidance", run)
            self.assertGreater(run["copilot_guidance"]["global_null_fwer_at_alpha"], 0.22)
            self.assertAlmostEqual(run["copilot_guidance"]["bonferroni_alpha"], 0.01, places=5)

            lock = eng.dispatch("explore", {
                "op": "lock_plan",
                "explore_id": exp_id,
                "hypothesis_id": "H1",
                "estimand": "ATT of exposure X on 1-year relapse hazard.",
                "primary_endpoint": "1-year relapse hazard ratio (HR).",
                "analysis_unit": "Independent patients (N=400).",
                "sample_size_plan": "N=400 patients, 140 events.",
                "exclusion_rules": "Exclude prior relapse before baseline.",
                "multiplicity_strategy": "Disclose 5 prior exploratory forks; Holm-Bonferroni correction.",
                "negative_controls": "Accidental trauma hospitalization negative control.",
                "kill_criteria": "Adjusted HR 95% CI crosses 1.0 or negative-control p < 0.05.",
            })
            self.assertIn("copilot_guidance", lock)

            promoted = eng.dispatch("explore", {
                "op": "promote_to_case",
                "explore_id": exp_id,
                "hypothesis_id": "H1",
                "plan_id": lock["plan"]["plan_id"],
                "blind_mode": "estimate_first",
                "draft": "SECRET_DRAFT_NARRATIVE_MUST_NOT_LEAK_INTO_DIAGNOSTICS",
            })
            cid = promoted["case_id"]

            # Register quantitative evidence files
            (ws / "obs.txt").write_text("Observational cohort (N=400): HR = 1.18 (95% CI 1.02 to 1.36, p = 0.025).\n", encoding="utf-8")
            (ws / "null.txt").write_text("Pilot trial (N=60): mean_diff = 0.02 (95% CI -0.18 to 0.22, p = 0.84).\n", encoding="utf-8")
            (ws / "pred.txt").write_text("External cohort (N=120, 42 events): AUROC = 0.84 (95% CI 0.77 to 0.90).\n", encoding="utf-8")
            ev_obs = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "obs.txt", "kind": "observation", "provenance": "observed",
                "quote": "HR = 1.18 (95% CI 1.02 to 1.36, p = 0.025).", "location": "line 1",
            })["evidence_id"]
            ev_null = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "null.txt", "kind": "intervention", "provenance": "observed",
                "quote": "mean_diff = 0.02 (95% CI -0.18 to 0.22, p = 0.84).", "location": "line 1",
            })["evidence_id"]
            ev_pred = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "pred.txt", "kind": "prediction_external", "provenance": "observed",
                "quote": "AUROC = 0.84 (95% CI 0.77 to 0.90).", "location": "line 1",
            })["evidence_id"]

            # Step 2: Upsert 3 claims -> proactive copilot_diagnostics fires immediately on each
            u1 = eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C1",
                "text": "Exposure X causally increases relapse hazard (HR 1.18, 95% CI 1.02-1.36).",
                "claim_type": "causal_effect", "evidence_level": "identified_under_assumptions",
                "scope": "Observational cohort N=400", "evidence_ids": [ev_obs],
                "design_families": ["observational"],
                "best_current_explanation": "SECRET_AUTHOR_EXPLANATION_MUST_NOT_LEAK",
                "discriminating_test": "SECRET_AUTHOR_TEST_HR_BELOW_1.05",
                "alternatives": ["Unmeasured severity confounding"],
                "effect_records": [{
                    "id": "r1", "endpoint": "1-year relapse", "endpoint_role": "primary",
                    "metric": "HR", "estimate": 1.18, "ci_low": 1.02, "ci_high": 1.36, "p_value": 0.025,
                    "direction": "harm", "evidence_id": ev_obs,
                }],
            })
            c1_codes = {a["code"] for a in u1["copilot_diagnostics"]["advisories"]}
            self.assertIn("fragile_observational_causal", c1_codes)
            self.assertIn("e_value", u1["copilot_diagnostics"]["probes"])

            u2 = eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C2",
                "text": "Pilot intervention showed no difference (mean_diff 0.02, 95% CI -0.18 to 0.22).",
                "claim_type": "causal_effect", "evidence_level": "identified_under_assumptions",
                "scope": "Pilot trial N=60", "evidence_ids": [ev_null],
                "design_families": ["randomized"],
                "alternatives": ["Insufficient statistical power"],
                "effect_records": [{
                    "id": "r2", "endpoint": "symptom score", "endpoint_role": "primary",
                    "metric": "mean_diff", "estimate": 0.02, "ci_low": -0.18, "ci_high": 0.22, "p_value": 0.84,
                    "direction": "null", "evidence_id": ev_null,
                }],
            })
            c2_codes = {a["code"] for a in u2["copilot_diagnostics"]["advisories"]}
            self.assertIn("null_effect_implied_equivalence_margin", c2_codes)
            self.assertIn("implied_tost_margins", u2["copilot_diagnostics"]["probes"])

            u3 = eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C3",
                "text": "Model M discriminates 1-year recurrence in external cohort (AUROC 0.84, 95% CI 0.77-0.90).",
                "claim_type": "prediction", "evidence_level": "externally_validated",
                "scope": "External hospital cohort N=120", "evidence_ids": [ev_pred],
                "design_families": ["prediction"],
                "alternatives": ["Cohort overlap leakage"],
                "effect_records": [{
                    "id": "r3", "endpoint": "1-year recurrence", "endpoint_role": "primary",
                    "metric": "AUROC", "estimate": 0.84, "ci_low": 0.77, "ci_high": 0.90, "n": 120, "events": 42,
                    "direction": "higher_better", "evidence_id": ev_pred,
                }],
            })
            c3_codes = {a["code"] for a in u3["copilot_diagnostics"]["advisories"]}
            self.assertIn("prediction_discrimination_vs_utility_split", c3_codes)

            # Step 3: Live case_audit auto-links explore_id (5 prior forks!) and audits all 3 claims read-only
            audit = eng.dispatch("analyze_design", {"mode": "case_audit", "case_id": cid})
            self.assertEqual(audit["linked_explore_id"], exp_id)
            self.assertEqual(audit["prior_exploratory_forks"], 5)
            self.assertEqual(audit["audited_claim_count"], 3)
            self.assertGreaterEqual(audit["risk_summary"]["overclaim_risk"], 3)  # fragile causal + multiplicity erosion + null!=equiv
            self.assertGreaterEqual(audit["risk_summary"]["underclaim_risk"], 1)  # external prediction anti-underclaim
            c1_audit = next(ca for ca in audit["claim_audits"] if ca["claim_id"] == "C1")
            c1_audit_codes = {a["code"] for a in c1_audit["advisories"]}
            self.assertIn("primary_effect_eroded_by_multiplicity", c1_audit_codes)
            self.assertIn("fragile_observational_causal", c1_audit_codes)
            self.assertGreater(len(audit["next_discriminating_actions"]), 0)

            # Single-claim filter works and unknown claim raises cleanly
            single = eng.dispatch("analyze_design", {"mode": "case_audit", "case_id": cid, "claim_id": "C2"})
            self.assertEqual(single["audited_claim_count"], 1)
            with self.assertRaises(ContractError) as bad_cid:
                eng.dispatch("analyze_design", {"mode": "case_audit", "case_id": cid, "claim_id": "MISSING"})
            self.assertEqual(bad_cid.exception.code, "unknown_claim")

            # Step 4: Freeze -> blind-safe computable_diagnostics attached to review_packet & dossier
            eng.dispatch("freeze", {"case_id": cid})
            over_pkt = eng.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
            self.assertIn("computable_diagnostics", over_pkt)
            self.assertTrue(over_pkt["computable_diagnostics"]["blind_safe"])
            self.assertIn("computable_diagnostics", over_pkt["evidence_first_dossier"])
            diag_blob = str(over_pkt["computable_diagnostics"])
            self.assertNotIn("SECRET_DRAFT_NARRATIVE_MUST_NOT_LEAK_INTO_DIAGNOSTICS", diag_blob)
            self.assertNotIn("SECRET_AUTHOR_EXPLANATION_MUST_NOT_LEAK", diag_blob)
            self.assertNotIn("SECRET_AUTHOR_TEST_HR_BELOW_1.05", diag_blob)

            # Step 5: Submit reviews -> adjudication_packet also carries computable_diagnostics
            under_pkt = eng.dispatch("review_packet", {"case_id": cid, "role": "underclaim"})
            stances = [
                {"claim_id": cid_k, "stance": "insufficient_evidence", "rationale": f"Checks remain unknown on {cid_k} pending full verification.", "evidence_ids": []}
                for cid_k in ("C1", "C2", "C3")
            ]
            for role, pkt in (("overclaim", over_pkt), ("underclaim", under_pkt)):
                eng.dispatch("submit_review", {
                    "case_id": cid, "role": role,
                    "packet_id": pkt["packet_id"], "input_digest": pkt["input_digest"],
                    "reviewer": {"context_id": f"{role}-ctx", "model": "test-model"},
                    "covered_claim_ids": ["C1", "C2", "C3"],
                    "claim_stances": stances,
                    "unread_evidence_ids": [], "findings": [],
                })
            adj_pkt = eng.dispatch("adjudication_packet", {"case_id": cid})
            self.assertIn("computable_diagnostics", adj_pkt)
            self.assertEqual(len(adj_pkt["computable_diagnostics"]["claims"]), 3)

    def test_proactive_subgroup_illusion_probe_and_mcp_schema_roundtrip(self):
        from parrhesia.server import Server

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws)
            (ws / "subgroups.txt").write_text(
                "Subgroup A: mean_diff = 0.45 (95% CI 0.06 to 0.84); "
                "Subgroup B: mean_diff = 0.25 (95% CI -0.14 to 0.64).\n",
                encoding="utf-8",
            )
            cid = eng.dispatch("create_case", {"question": "Does treatment differ between subgroups A and B?", "draft": "Draft."})["case_id"]
            ev = eng.dispatch("register_evidence", {
                "case_id": cid, "path": "subgroups.txt", "kind": "intervention", "provenance": "observed",
                "quote": "Subgroup A: mean_diff = 0.45 (95% CI 0.06 to 0.84);", "location": "line 1",
            })["evidence_id"]

            up = eng.dispatch("upsert_claim", {
                "case_id": cid, "claim_id": "C_SUB",
                "text": "Treatment effect differs between Subgroup A and Subgroup B.",
                "claim_type": "causal_effect", "evidence_level": "identified_under_assumptions",
                "scope": "Subgroup comparison A vs B", "evidence_ids": [ev],
                "design_families": ["randomized"],
                "alternatives": ["Sampling variance across subgroups"],
                "effect_records": [
                    {
                        "id": "sub_a", "endpoint": "Subgroup A", "endpoint_role": "secondary",
                        "metric": "mean_diff", "estimate": 0.45, "ci_low": 0.06, "ci_high": 0.84,
                        "direction": "benefit", "evidence_id": ev,
                    },
                    {
                        "id": "sub_b", "endpoint": "Subgroup B", "endpoint_role": "secondary",
                        "metric": "mean_diff", "estimate": 0.25, "ci_low": -0.14, "ci_high": 0.64,
                        "direction": "null", "evidence_id": ev,
                    },
                ],
            })
            codes = {a["code"] for a in up["copilot_diagnostics"]["advisories"]}
            self.assertIn("subgroup_sig_vs_nonsig_illusion", codes)

            # Verify MCP tool call over Server for case_audit and new statistical modes
            srv = Server(ws, tool_profile="explore")
            srv.handle({
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
            })
            resp = srv.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "parrhesia_analyze_design", "arguments": {"mode": "case_audit", "case_id": cid}},
            })
            self.assertFalse(resp["result"]["isError"])
            sc = resp["result"]["structuredContent"]
            self.assertEqual(sc["mode"], "case_audit")
            self.assertEqual(sc["audited_claim_count"], 1)
            self.assertGreaterEqual(sc["risk_summary"]["overclaim_risk"], 1)


if __name__ == "__main__":
    unittest.main()
