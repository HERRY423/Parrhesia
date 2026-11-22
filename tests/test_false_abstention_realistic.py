"""Regression suite preventing false abstention and overblocking on realistic scientific passages."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

import test_gates as fixtures
from parrhesia.claims import CARD_FIELDS, scaffold_claim_template
from parrhesia.cli import main as cli_main
from parrhesia.contracts import ContractError
from parrhesia.gates import (
    audit_underclaim_and_abstention,
    collect_lexical_advisories,
    contradictory_evidence_kind,
    contradictory_positive_evidence_text,
)


class RealisticFalseAbstentionTests(unittest.TestCase):
    setUp = fixtures.GateTests.setUp
    tearDown = fixtures.GateTests.tearDown
    register = fixtures.GateTests.register
    assessment = fixtures.GateTests.assessment
    claim = fixtures.GateTests.claim
    save = fixtures.GateTests.save
    reviewed = fixtures.GateTests.reviewed
    error = fixtures.GateTests.error
    review_payload = fixtures.GateTests.review_payload

    def _build_claim(
        self,
        claim_type,
        evidence_level,
        family,
        *,
        domain="scientific",
        claim_basis="empirical",
        slug="case",
    ):
        payload = {
            "claim_id": "C1",
            "text": f"Positive claim for {slug}",
            "scope": f"Evidenced study population and protocol for {slug}",
            "claim_type": claim_type,
            "evidence_level": evidence_level,
            "claim_basis": claim_basis,
            "domain": domain,
        }
        if domain == "scientific":
            payload["design_families"] = [family]
        claim = scaffold_claim_template(payload)
        pass_rec = {"status": "pass", "reason": f"Verified directly from primary evidence in {slug}", "evidence_ids": [self.ev]}
        claim["origin"] = "unknown"
        claim["contribution"] = f"Establishes {claim_type} finding in {slug}"
        claim["evidence_ids"] = [self.ev]
        claim["alternatives"] = [
            {
                "explanation": "Sampling variation or unmeasured residual bias accounts for result",
                "status": "excluded",
                "reason": f"Assessed directly against sensitivity and interval estimates in {slug}",
            }
        ]
        for k in list(claim["checks"]):
            claim["checks"][k] = {"status": "pass", "reason": f"Verified {k} in {slug}"}
        for dp in claim["design_packages"]:
            for ck in list(dp["checks"]):
                dp["checks"][ck] = dict(pass_rec)
        for sk in list(claim["statistical_report"]):
            claim["statistical_report"][sk] = dict(pass_rec)
        if "causal_basis" in claim:
            cb = claim["causal_basis"]
            cb["estimand"] = {k: f"{k} verified in {slug}" for k in cb["estimand"]}
            cb["assumptions"] = [{"name": "Conditional exchangeability / identification", **pass_rec}]
            cb["falsification_sensitivity"] = [{"name": "Sensitivity and negative control check", **pass_rec}]
            for k in ("assessment", "necessity_test", "sufficiency_test"):
                cb[k] = dict(pass_rec)
        claim["provenance_cards"] = {
            card_kind: [
                {
                    "id": f"C1-{card_kind}-1",
                    "status": "checked",
                    "reason": f"Verified {card_kind} against registered evidence {self.ev}",
                    "evidence_ids": [self.ev],
                    "details": {
                        **{dk: f"verified-{dk}-{slug}" for dk in detail_keys},
                        **({"support_relation": "supports"} if card_kind == "citation" else {}),
                        **({"exit_status": "0"} if card_kind == "execution" else {}),
                    },
                }
            ]
            for card_kind, detail_keys in CARD_FIELDS.items()
        }
        return claim

    def _run_e2e_positive(
        self,
        *,
        slug,
        claim_type,
        evidence_level,
        family,
        evidence_kind,
        evidence_text,
        quote,
        claim_text,
        estimate,
        uncertainty,
        domain="scientific",
        claim_basis="empirical",
        verdict="supported",
        condition=None,
        check_overrides=None,
    ):
        self.cid = self.engine.dispatch(
            "create_case",
            {
                "question": f"Does evidence support {slug}?",
                "draft": claim_text,
                "domain": domain,
                "writer_context_id": f"writer-{slug}",
            },
        )["case_id"]
        rel_path = f"{slug}.txt"
        (self.root / rel_path).write_text(evidence_text + "\n", encoding="utf-8")
        self.ev = self.engine.dispatch(
            "register_evidence",
            {
                "case_id": self.cid,
                "path": rel_path,
                "provenance": "observed",
                "kind": evidence_kind,
                "quote": quote,
                "location": f"{rel_path}:L1",
            },
        )["evidence_id"]

        claim = self._build_claim(
            claim_type,
            evidence_level,
            family,
            domain=domain,
            claim_basis=claim_basis,
            slug=slug,
        )
        claim["text"] = claim_text
        claim["effect"] = {"estimate": estimate, "uncertainty": uncertainty}
        if condition:
            claim["scope"] = condition
        if check_overrides:
            for k, v in check_overrides.items():
                if k in claim["checks"]:
                    claim["checks"][k] = {"status": "pass", "reason": v}
                elif k in claim["statistical_report"]:
                    claim["statistical_report"][k] = {"status": "pass", "reason": v, "evidence_ids": [self.ev]}

        self.save(claim)
        frozen = self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            pkt = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            stance = {
                "claim_id": "C1",
                "stance": verdict,
                "rationale": f"Verified primary evidence in {slug}",
                "evidence_ids": [self.ev],
            }
            if condition:
                stance["condition"] = condition
            self.engine.dispatch(
                "submit_review",
                {
                    "case_id": self.cid,
                    "role": role,
                    "packet_id": pkt["packet_id"],
                    "input_digest": frozen["input_digest"],
                    "reviewer": {"context_id": f"{role}-{slug}", "model": "fixture"},
                    "covered_claim_ids": ["C1"],
                    "claim_stances": [stance],
                    "unread_evidence_ids": [],
                    "findings": [],
                },
            )
        apkt = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        decision = {
            "claim_id": "C1",
            "claim_basis": claim_basis,
            "claim_type": claim_type,
            "evidence_level": evidence_level,
            "scope": claim["scope"],
            "verdict": verdict,
            "revised_text": claim_text,
            "rationale": f"Calibrated {verdict} anchored to primary evidence in {slug}",
            "evidence_ids": [self.ev],
            "confidence": "high",
            "confidence_reason": f"Quantitative anchors match {slug}",
            "boundary": claim["scope"],
            "reversal_condition": f"Null replication or primary bias reversal in {slug}",
        }
        if condition:
            decision["condition"] = condition
        adj = self.engine.dispatch(
            "submit_adjudication",
            {
                "case_id": self.cid,
                "adjudication_id": apkt["adjudication_id"],
                "input_digest": apkt["input_digest"],
                "adjudicator": {"context_id": f"adj-{slug}", "model": "fixture"},
                "unread_evidence_ids": [],
                "dispositions": [],
                "decisions": [decision],
            },
        )
        ver = self.engine.dispatch("verify", {"case_id": self.cid})
        exp = self.engine.dispatch("export", {"case_id": self.cid})
        return adj, ver, exp, claim

    def test_six_core_false_obstruction_probes_and_anti_abstention_audit(self):
        probes = [
            {
                "slug": "probe1_or_1_08_substring",
                "claim_type": "association",
                "evidence_level": "adjusted",
                "family": "observational",
                "evidence_kind": "observation",
                "evidence_text": (
                    "Multivariable cohort analysis (N=1,840 adults): biomarker B2 showed adjusted "
                    "OR = 1.08 (95% CI 1.02 to 1.15, p = 0.008) for 1-year kidney progression."
                ),
                "quote": "adjusted OR = 1.08 (95% CI 1.02 to 1.15, p = 0.008) for 1-year kidney progression.",
                "claim_text": "Biomarker B2 is associated with 1-year kidney progression (adjusted OR = 1.08, 95% CI 1.02 to 1.15).",
                "estimate": "OR = 1.08",
                "uncertainty": "95% CI 1.02 to 1.15",
            },
            {
                "slug": "probe2_rejected_null_hr_1_0",
                "claim_type": "causal_effect",
                "evidence_level": "identified_under_assumptions",
                "family": "randomized",
                "evidence_kind": "intervention",
                "evidence_text": (
                    "Multicenter randomized trial (N=620): the null hypothesis of no effect (HR = 1.0) "
                    "was rejected (p = 0.002); observed HR = 0.71 (95% CI 0.56 to 0.90) for mortality."
                ),
                "quote": "observed HR = 0.71 (95% CI 0.56 to 0.90) for mortality.",
                "claim_text": "Randomized therapy reduces mortality (HR = 0.71, 95% CI 0.56 to 0.90).",
                "estimate": "HR = 0.71",
                "uncertainty": "95% CI 0.56 to 0.90",
            },
            {
                "slug": "probe3_untagged_hospitalization_null",
                "claim_type": "causal_effect",
                "evidence_level": "identified_under_assumptions",
                "family": "randomized",
                "evidence_kind": "intervention",
                "evidence_text": (
                    "Randomized controlled trial (N=780): primary endpoint 90-day mortality decreased "
                    "(HR = 0.72, 95% CI 0.58 to 0.89); all-cause hospitalization showed no significant "
                    "difference between arms (p = 0.72)."
                ),
                "quote": "primary endpoint 90-day mortality decreased (HR = 0.72, 95% CI 0.58 to 0.89)",
                "claim_text": "Randomized intervention decreases 90-day mortality (HR = 0.72, 95% CI 0.58 to 0.89).",
                "estimate": "HR = 0.72",
                "uncertainty": "95% CI 0.58 to 0.89",
            },
            {
                "slug": "probe4_ae_safety_null",
                "claim_type": "causal_effect",
                "evidence_level": "identified_under_assumptions",
                "family": "randomized",
                "evidence_kind": "intervention",
                "evidence_text": (
                    "Phase 3 randomized trial (N=510): progression-free survival improved "
                    "(HR = 0.68, 95% CI 0.54 to 0.85); no significant difference in grade 3-4 adverse events "
                    "or tolerability outcomes (p = 0.84)."
                ),
                "quote": "progression-free survival improved (HR = 0.68, 95% CI 0.54 to 0.85)",
                "claim_text": "Randomized treatment improves PFS (HR = 0.68, 95% CI 0.54 to 0.85).",
                "estimate": "HR = 0.68",
                "uncertainty": "95% CI 0.54 to 0.85",
            },
            {
                "slug": "probe5_discussion_inconsistent_with_prior",
                "claim_type": "causal_effect",
                "evidence_level": "identified_under_assumptions",
                "family": "randomized",
                "evidence_kind": "intervention",
                "evidence_text": (
                    "Double-blind RCT (N=490): therapy reduced 6-month mortality (HR = 0.71, 95% CI 0.57 to 0.88), "
                    "inconsistent with prior small uncontrolled reports."
                ),
                "quote": "therapy reduced 6-month mortality (HR = 0.71, 95% CI 0.57 to 0.88)",
                "claim_text": "Double-blind RCT reduces 6-month mortality (HR = 0.71, 95% CI 0.57 to 0.88).",
                "estimate": "HR = 0.71",
                "uncertainty": "95% CI 0.57 to 0.88",
            },
            {
                "slug": "probe6_background_prior_obs_and_cv",
                "claim_type": "prediction",
                "evidence_level": "externally_validated",
                "family": "prediction",
                "evidence_kind": "prediction_external",
                "evidence_text": (
                    "Following internal 5-fold cross-validation in our derivation cohort, independent external "
                    "validation across two external hospital networks (N=610) yielded AUROC = 0.84 "
                    "(95% CI 0.79 to 0.89)."
                ),
                "quote": "independent external validation across two external hospital networks (N=610) yielded AUROC = 0.84 (95% CI 0.79 to 0.89).",
                "claim_text": "Across two external hospitals (N=610), risk model achieves AUROC = 0.84 (95% CI 0.79 to 0.89).",
                "estimate": "AUROC = 0.84",
                "uncertainty": "95% CI 0.79 to 0.89",
            },
        ]

        for p in probes:
            ev_dict = {
                "evidence_id": "EV1",
                "kind": p["evidence_kind"],
                "provenance": "observed",
                "source_text_status": "complete",
                "source_text": p["evidence_text"],
                "quote": p["quote"],
                "location": f"{p['slug']}.txt:L1",
            }
            self.assertIsNone(contradictory_positive_evidence_text(ev_dict), msg=f"False text hit on {p['slug']}")
            self.assertIsNone(contradictory_evidence_kind(ev_dict), msg=f"False kind hit on {p['slug']}")

            adj, ver, exp, claim = self._run_e2e_positive(**p)
            self.assertEqual(adj["state"], "adjudicated", msg=p["slug"])
            self.assertEqual(ver["status"], "pass", msg=p["slug"])
            self.assertEqual(exp["state"], "exported", msg=p["slug"])
            self.assertEqual(adj["symmetry_audit"]["flag_count"], 0, msg=p["slug"])
            self.assertEqual(adj["symmetry_audit"]["lexical_advisory_count"], 0, msg=p["slug"])

            # Verify false abstention on the exact same clean positive probe is STILL surfaced by symmetry_audit!
            over_hedge = {
                "claim_id": "C1",
                "claim_type": p["claim_type"],
                "evidence_level": p["evidence_level"],
                "claim_basis": "empirical",
                "scope": claim["scope"],
                "verdict": "insufficient_evidence",
                "revised_text": "Evidence insufficient pending further studies.",
                "rationale": "Conservative abstention",
                "evidence_ids": [],
                "boundary": claim["scope"],
                "reversal_condition": "Additional studies",
            }
            sym = audit_underclaim_and_abstention([over_hedge], [claim], [{**ev_dict, "evidence_id": self.ev}])
            self.assertIn("possible_false_abstention", {f["hook_code"] for f in sym["flags"]}, msg=p["slug"])

    def test_twenty_six_realistic_positive_passages_zero_overblocking(self):
        cases = [
            # 1-5: Observational & decimal OR/HR/RR values near 1.0 + prior background
            dict(
                slug="real01_or_1_05_cohort", claim_type="association", evidence_level="adjusted",
                family="observational", evidence_kind="observation",
                evidence_text="Prospective registry (N=12,400): ambient PM2.5 exposure associated with adjusted OR = 1.05 (95% CI 1.02 to 1.09) per 10 ug/m3.",
                quote="adjusted OR = 1.05 (95% CI 1.02 to 1.09) per 10 ug/m3.",
                claim_text="Ambient PM2.5 associates with event risk (adjusted OR = 1.05, 95% CI 1.02 to 1.09).",
                estimate="OR = 1.05", uncertainty="95% CI 1.02 to 1.09",
            ),
            dict(
                slug="real02_hr_1_09_registry", claim_type="association", evidence_level="robust_association",
                family="observational", evidence_kind="observation",
                evidence_text="Multi-site EHR cohort (N=8,200): elevated ferritin associated with HR = 1.09 (95% CI 1.03 to 1.16); sensitivity analyses omitted auxiliary subgroup plots for brevity.",
                quote="elevated ferritin associated with HR = 1.09 (95% CI 1.03 to 1.16)",
                claim_text="Elevated ferritin associates robustly with outcome (HR = 1.09, 95% CI 1.03 to 1.16).",
                estimate="HR = 1.09", uncertainty="95% CI 1.03 to 1.16",
            ),
            dict(
                slug="real03_rr_1_04_meta", claim_type="synthesis", evidence_level="synthesized_with_uncertainty",
                family="evidence_synthesis", evidence_kind="systematic_review",
                evidence_text="Systematic review of 18 cohorts (N=94,000): pooled RR = 1.04 (95% CI 1.01 to 1.07, I^2 = 12%); secondary laboratory results omitted from main summary.",
                quote="pooled RR = 1.04 (95% CI 1.01 to 1.07, I^2 = 12%)",
                claim_text="Meta-analysis shows pooled RR = 1.04 (95% CI 1.01 to 1.07) across 18 cohorts.",
                estimate="RR = 1.04", uncertainty="95% CI 1.01 to 1.07",
            ),
            dict(
                slug="real04_cjk_observational", claim_type="association", evidence_level="adjusted",
                family="observational", evidence_kind="observation",
                evidence_text="多中心回顾性队列（N=2,150）：校正后暴露组风险比 HR = 1.28（95% CI 1.11 至 1.47）；探索性亚组差异未见统计学意义。",
                quote="校正后暴露组风险比 HR = 1.28（95% CI 1.11 至 1.47）",
                claim_text="队列研究显示暴露组风险升高（校正 HR = 1.28，95% CI 1.11 至 1.47）。",
                estimate="HR = 1.28", uncertainty="95% CI 1.11 至 1.47",
            ),
            dict(
                slug="real05_tte_conditional_obs", claim_type="causal_effect", evidence_level="sensitivity_supported",
                family="observational", evidence_kind="observation", verdict="partially_supported",
                condition="Holds under conditional exchangeability given measured covariates and E-value >= 2.15.",
                evidence_text="Target trial emulation (N=3,400): treatment T reduced 1-year readmissions RD = -4.6% (95% CI -7.1% to -2.1%), E-value = 2.15.",
                quote="reduced 1-year readmissions RD = -4.6% (95% CI -7.1% to -2.1%), E-value = 2.15.",
                claim_text="Target trial emulation conditionally supports RD = -4.6% (95% CI -7.1% to -2.1%).",
                estimate="RD = -4.6%", uncertainty="95% CI -7.1% to -2.1%",
            ),
            # 6-11: Interventional RCTs & quasi-experiments with rejected nulls, background obs mentions, safety/hosp nulls
            dict(
                slug="real06_rct_null_rejected_prior_obs", claim_type="causal_effect", evidence_level="sensitivity_supported",
                family="randomized", evidence_kind="intervention",
                evidence_text="Earlier observational studies had residual confounding; in this double-blind multicenter RCT (N=840), the null hypothesis (HR = 1.0) was rejected with HR = 0.74 (95% CI 0.61 to 0.90).",
                quote="double-blind multicenter RCT (N=840), the null hypothesis (HR = 1.0) was rejected with HR = 0.74 (95% CI 0.61 to 0.90).",
                claim_text="Multicenter RCT reduces hazard HR = 0.74 (95% CI 0.61 to 0.90).",
                estimate="HR = 0.74", uncertainty="95% CI 0.61 to 0.90",
            ),
            dict(
                slug="real07_rct_double_blind_safety_null", claim_type="causal_effect", evidence_level="identified_under_assumptions",
                family="randomized", evidence_kind="intervention",
                evidence_text="Double-blind placebo-controlled trial (N=520): primary efficacy score improved delta = -3.8 points (95% CI -5.4 to -2.2); serious adverse events showed no significant difference (p = 0.91).",
                quote="primary efficacy score improved delta = -3.8 points (95% CI -5.4 to -2.2)",
                claim_text="Intervention improves efficacy score by delta = -3.8 points (95% CI -5.4 to -2.2).",
                estimate="delta = -3.8", uncertainty="95% CI -5.4 to -2.2",
            ),
            dict(
                slug="real08_rct_hosp_null_pfs_pos", claim_type="causal_effect", evidence_level="identified_under_assumptions",
                family="randomized", evidence_kind="intervention",
                evidence_text="Phase 3 randomized trial (N=900): primary progression-free survival improved (HR = 0.66, 95% CI 0.55 to 0.79); rehospitalizations did not differ significantly (p = 0.68).",
                quote="primary progression-free survival improved (HR = 0.66, 95% CI 0.55 to 0.79)",
                claim_text="Phase 3 trial improves PFS (HR = 0.66, 95% CI 0.55 to 0.79).",
                estimate="HR = 0.66", uncertainty="95% CI 0.55 to 0.79",
            ),
            dict(
                slug="real09_rct_inconsistent_prior_small", claim_type="causal_effect", evidence_level="identified_under_assumptions",
                family="randomized", evidence_kind="intervention",
                evidence_text="Randomized trial (N=720) showed reduced mortality (OR = 0.72, 95% CI 0.58 to 0.89), discordant with earlier uncontrolled case-series reports.",
                quote="reduced mortality (OR = 0.72, 95% CI 0.58 to 0.89)",
                claim_text="Randomized trial reduces mortality (OR = 0.72, 95% CI 0.58 to 0.89).",
                estimate="OR = 0.72", uncertainty="95% CI 0.58 to 0.89",
            ),
            dict(
                slug="real10_qe_did_parallel_trends", claim_type="causal_effect", evidence_level="sensitivity_supported",
                family="quasi_experimental", evidence_kind="quasi_experiment",
                evidence_text="Difference-in-differences staggered rollout across 42 municipalities (N=18,000): ED visits fell -6.2% (95% CI -8.8% to -3.6%); pre-policy event-study falsification leads p = 0.77.",
                quote="ED visits fell -6.2% (95% CI -8.8% to -3.6%); pre-policy event-study falsification leads p = 0.77.",
                claim_text="Policy rollout reduced ED visits by -6.2% (95% CI -8.8% to -3.6%).",
                estimate="-6.2%", uncertainty="95% CI -8.8% to -3.6%",
            ),
            dict(
                slug="real11_cjk_rct_rejected_null", claim_type="causal_effect", evidence_level="identified_under_assumptions",
                family="randomized", evidence_kind="intervention",
                evidence_text="随机双盲临床试验（N=460）：拒绝零假设，主要终点事件发生率下降 RR = 0.69（95% CI 0.54 至 0.88）；不良事件发生率组间无显著差异。",
                quote="主要终点事件发生率下降 RR = 0.69（95% CI 0.54 至 0.88）",
                claim_text="临床试验显著降低终点风险 RR = 0.69（95% CI 0.54 至 0.88）。",
                estimate="RR = 0.69", uncertainty="95% CI 0.54 至 0.88",
            ),
            # 12-16: Prediction internal, external, prospective (with natural future work caveats)
            dict(
                slug="real12_pred_internal", claim_type="prediction", evidence_level="internally_validated",
                family="prediction", evidence_kind="prediction_internal",
                evidence_text="Nested 10-fold internal cross-validation (N=1,120): AUROC = 0.83 (95% CI 0.79 to 0.87), calibration slope 0.98.",
                quote="Nested 10-fold internal cross-validation (N=1,120): AUROC = 0.83 (95% CI 0.79 to 0.87)",
                claim_text="Internal validation achieves AUROC = 0.83 (95% CI 0.79 to 0.87).",
                estimate="AUROC = 0.83", uncertainty="95% CI 0.79 to 0.87",
            ),
            dict(
                slug="real13_pred_external_test_set", claim_type="prediction", evidence_level="externally_validated",
                family="prediction", evidence_kind="prediction_external",
                evidence_text="After internal 5-fold cross-validation, evaluation on an independent external dataset (N=690) achieved AUROC = 0.85 (95% CI 0.81 to 0.89); additional multicenter external validation is planned.",
                quote="independent external dataset (N=690) achieved AUROC = 0.85 (95% CI 0.81 to 0.89)",
                claim_text="Independent external dataset validation yields AUROC = 0.85 (95% CI 0.81 to 0.89).",
                estimate="AUROC = 0.85", uncertainty="95% CI 0.81 to 0.89",
            ),
            dict(
                slug="real14_pred_external_geographic", claim_type="prediction", evidence_level="externally_validated",
                family="prediction", evidence_kind="prediction_external",
                evidence_text="Geographic validation across 3 independent cohorts (N=1,400) confirmed AUROC = 0.81 (95% CI 0.78 to 0.84) with Brier 0.14.",
                quote="Geographic validation across 3 independent cohorts (N=1,400) confirmed AUROC = 0.81 (95% CI 0.78 to 0.84)",
                claim_text="Geographic external validation yields AUROC = 0.81 (95% CI 0.78 to 0.84).",
                estimate="AUROC = 0.81", uncertainty="95% CI 0.78 to 0.84",
            ),
            dict(
                slug="real15_pred_prospective", claim_type="prediction", evidence_level="prospectively_evaluated",
                family="prediction", evidence_kind="prediction_prospective",
                evidence_text="Prospective multi-ward implementation cohort (N=950) following retrospective model development yielded AUROC = 0.86 (95% CI 0.82 to 0.90); additional future prospective rollout is planned.",
                quote="Prospective multi-ward implementation cohort (N=950) following retrospective model development yielded AUROC = 0.86 (95% CI 0.82 to 0.90)",
                claim_text="Prospective clinical evaluation shows AUROC = 0.86 (95% CI 0.82 to 0.90).",
                estimate="AUROC = 0.86", uncertainty="95% CI 0.82 to 0.90",
            ),
            dict(
                slug="real16_pred_cjk_ext", claim_type="prediction", evidence_level="externally_validated",
                family="prediction", evidence_kind="prediction_external",
                evidence_text="先完成内部交叉验证后，独立医院外部验证队列（N=580）测得 AUROC = 0.82（95% CI 0.77 至 0.87）。",
                quote="独立医院外部验证队列（N=580）测得 AUROC = 0.82（95% CI 0.77 至 0.87）",
                claim_text="外部验证队列模型区分度为 AUROC = 0.82（95% CI 0.77 至 0.87）。",
                estimate="AUROC = 0.82", uncertainty="95% CI 0.77 至 0.87",
            ),
            # 17-20: Mechanism, necessity, sufficiency, synthesis
            dict(
                slug="real17_mech_component", claim_type="mechanism", evidence_level="component_tested",
                family="mechanism", evidence_kind="mechanistic_assay",
                evidence_text="Biochemical kinase assay across 6 replicates shows ligand K_d = 12.4 nM (SD 1.8 nM) blocking phosphorylation by 78%; off-target panel showed no effect on ERK1/2.",
                quote="ligand K_d = 12.4 nM (SD 1.8 nM) blocking phosphorylation by 78%",
                claim_text="Ligand inhibits target phosphorylation by 78% (K_d = 12.4 nM, SD 1.8 nM).",
                estimate="78% inhibition", uncertainty="SD 1.8 nM",
            ),
            dict(
                slug="real18_necessity_crispr", claim_type="necessity", evidence_level="counterfactual_supported",
                family="mechanism", evidence_kind="intervention",
                evidence_text="CRISPR knockout + rescue experiment (n=6 biological replicates): pathway deletion abolished response (-91.0%, 95% CI -96.0% to -86.0%), rescued by wild-type re-expression; cell viability did not differ.",
                quote="pathway deletion abolished response (-91.0%, 95% CI -96.0% to -86.0%)",
                claim_text="Target gene is counterfactually necessary for response (-91.0%, 95% CI -96.0% to -86.0%).",
                estimate="-91.0%", uncertainty="95% CI -96.0% to -86.0%",
            ),
            dict(
                slug="real19_sufficiency_gain", claim_type="sufficiency", evidence_level="bounded_test",
                family="mechanism", evidence_kind="intervention",
                evidence_text="Inducible perturbation assay (n=8 wells): targeted expression induction increased reporter activity by +3.4 fold (95% CI +2.8 to +4.0 fold) in serum-free medium.",
                quote="targeted expression induction increased reporter activity by +3.4 fold (95% CI +2.8 to +4.0 fold)",
                claim_text="Targeted factor induction suffices to elevate reporter activity +3.4 fold (95% CI +2.8 to +4.0 fold).",
                estimate="+3.4 fold", uncertainty="95% CI +2.8 to +4.0 fold",
            ),
            dict(
                slug="real20_synth_crit_appraised", claim_type="synthesis", evidence_level="critically_appraised",
                family="evidence_synthesis", evidence_kind="systematic_review",
                evidence_text="Critically appraised systematic review (14 studies, RoB-2 assessed): pooled sensitivity = 0.89 (95% CI 0.84 to 0.93); exploratory narrative subgroups had no difference.",
                quote="pooled sensitivity = 0.89 (95% CI 0.84 to 0.93)",
                claim_text="Critically appraised synthesis estimates sensitivity = 0.89 (95% CI 0.84 to 0.93).",
                estimate="0.89", uncertainty="95% CI 0.84 to 0.93",
            ),
            # 21-26: Theory, qualitative, computational, engineering, description
            dict(
                slug="real21_theory_proved", claim_type="theory", evidence_level="proved_under_assumptions",
                family="theory", evidence_kind="theoretical_proof", claim_basis="formal",
                evidence_text="Theorem 2 proof (Appendix A): under L-smoothness and strong convexity mu > 0, iterates satisfy linear rate (1 - mu/L)^k for step eta = 1/L, inconsistent with prior heuristic step bounds.",
                quote="iterates satisfy linear rate (1 - mu/L)^k for step eta = 1/L",
                claim_text="Theorem 2 establishes linear convergence factor (1 - mu/L)^k under L-smooth strong convexity.",
                estimate="linear rate (1 - mu/L)^k", uncertainty="exact under assumptions",
            ),
            dict(
                slug="real22_qual_triangulated", claim_type="qualitative", evidence_level="triangulated",
                family="qualitative", evidence_kind="qualitative_material",
                evidence_text="Triangulated fieldwork across 24 ICU clinicians and 180 EHR shift logs: 82% of checklist skips occurred during concurrent medication-pass lockouts rather than staff attitude.",
                quote="82% of checklist skips occurred during concurrent medication-pass lockouts rather than staff attitude.",
                claim_text="Triangulated field data attributes 82% of checklist skips to concurrent EHR lockouts.",
                estimate="82% lockout overlap", uncertainty="24 interviews / 180 logs",
            ),
            dict(
                slug="real23_comp_reproduced", claim_type="computational", evidence_level="reproduced",
                family="ml", evidence_kind="benchmark_replication",
                evidence_text="Replicated across 5 random seeds (exit_status=0): macro-F1 = 0.884 +/- 0.006 on held-out test split, rejecting the random-baseline null hypothesis.",
                quote="macro-F1 = 0.884 +/- 0.006 on held-out test split",
                claim_text="Model achieves reproduced macro-F1 = 0.884 (+/- 0.006) across 5 seeds.",
                estimate="macro-F1 = 0.884", uncertainty="+/- 0.006 across 5 seeds",
            ),
            dict(
                slug="real24_comp_external", claim_type="computational", evidence_level="externally_evaluated",
                family="ml", evidence_kind="benchmark_external",
                evidence_text="Independent external benchmark suite (N=14,500 held-out examples): accuracy = 91.4% (95% CI 90.9% to 91.9%), +4.2% over baseline.",
                quote="accuracy = 91.4% (95% CI 90.9% to 91.9%), +4.2% over baseline.",
                claim_text="External benchmark evaluation reaches accuracy = 91.4% (95% CI 90.9% to 91.9%).",
                estimate="91.4%", uncertainty="95% CI 90.9% to 91.9%",
            ),
            dict(
                slug="real25_eng_user_impact", claim_type="engineering", evidence_level="user_impact",
                family="ml", evidence_kind="user_outcome", domain="general",
                evidence_text="14-day production A/B telemetry (N=12,000 active sessions): p95 latency fell -21.5% (95% CI -24.0% to -19.0%); secondary outcome crash rate showed no significant difference.",
                quote="p95 latency fell -21.5% (95% CI -24.0% to -19.0%)",
                claim_text="Production rollout reduced p95 latency by -21.5% (95% CI -24.0% to -19.0%).",
                estimate="-21.5%", uncertainty="95% CI -24.0% to -19.0%",
            ),
            dict(
                slug="real26_desc_replicated", claim_type="description", evidence_level="replicated",
                family="observational", evidence_kind="observation",
                evidence_text="Replicated clinical surveillance across 3 hospitals (N=4,100 encounters): baseline 30-day incidence was 14.2% (95% CI 13.1% to 15.3%).",
                quote="baseline 30-day incidence was 14.2% (95% CI 13.1% to 15.3%).",
                claim_text="Replicated 30-day surveillance incidence is 14.2% (95% CI 13.1% to 15.3%).",
                estimate="14.2%", uncertainty="95% CI 13.1% to 15.3%",
            ),
        ]

        self.assertGreaterEqual(len(cases), 25)
        for cfg in cases:
            # Handle necessity/sufficiency design/causal checks + general domain differences cleanly
            adj, ver, exp, _ = self._run_e2e_positive(**cfg)
            self.assertEqual(adj["state"], "adjudicated", msg=cfg["slug"])
            self.assertEqual(ver["status"], "pass", msg=cfg["slug"])
            self.assertEqual(exp["state"], "exported", msg=cfg["slug"])
            self.assertEqual(adj["symmetry_audit"]["flag_count"], 0, msg=cfg["slug"])
            self.assertEqual(adj["symmetry_audit"]["lexical_advisory_count"], 0, msg=cfg["slug"])

    def test_multi_fork_nonwhitelist_multiplicity_method_succeeds_with_advisory_not_block(self):
        # Structural multiplicity passes (checks.multiplicity + evidenced multiplicity_selection),
        # while novel method "Simes closed-testing procedure" lacks old whitelist keywords:
        # must SUCCEED non-blockingly and emit possible_unadjusted_multiplicity_text advisory!
        self.cid = self.engine.dispatch(
            "create_case",
            {"question": "Does Simes multiplicity pass?", "draft": "Benchmark macro-F1 = 0.89 across 2 runs.", "writer_context_id": "writer-by"},
        )["case_id"]
        exec_outs = []
        for idx in (1, 2):
            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main([
                    "record-exec", "--workspace", str(self.root),
                    "--case-id", self.cid, "--claim-id", "C1", "--card-id", f"ex-by-{idx}",
                    "--", sys.executable, "-c", "print('macro-F1 = 0.89 across runs')",
                ])
            self.assertEqual(rc, 0)
            exec_outs.append(json.loads(buf.getvalue().decode("utf-8")))

        ev1, ev2 = exec_outs[0]["evidence"]["evidence_id"], exec_outs[1]["evidence"]["evidence_id"]
        # Separate benchmark source: receipts alone cannot establish benchmark kind.
        (self.root / "benchmark-forks.txt").write_text("Benchmark macro-F1 = 0.89 across 2 runs. Simes closed-testing procedure.", encoding="utf-8")
        bench = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "benchmark-forks.txt", "kind": "benchmark", "provenance": "reported",
            "quote": "Benchmark macro-F1 = 0.89 across 2 runs.", "location": "L1",
        })["evidence_id"]
        self.ev = bench
        claim = self.claim("computational", "benchmark_measured", "ml")
        claim["text"] = "Model reaches macro-F1 = 0.89 under Simes closed-testing procedure."
        claim["effect"] = {"estimate": "macro-F1 = 0.89", "uncertainty": "2 runs controlled"}
        claim["evidence_ids"] = [bench, ev1, ev2]
        claim["checks"]["multiplicity"] = {"status": "pass", "reason": "Applied Simes closed-testing step-up procedure across 2 executions"}
        claim["statistical_report"]["multiplicity_selection"] = {
            "status": "pass",
            "reason": "Applied Simes closed-testing step-up procedure across both executions",
            "evidence_ids": [bench, ev1, ev2],
        }
        claim["provenance_cards"]["execution"] = [exec_outs[0]["execution_card"], exec_outs[1]["execution_card"]]
        self.save(claim)
        fr = self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            pkt = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            rev = self.engine.dispatch("submit_review", {
                "case_id": self.cid, "role": role, "packet_id": pkt["packet_id"],
                "input_digest": fr["input_digest"], "reviewer": {"context_id": f"{role}-by", "model": "fixture"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Simes control verified", "evidence_ids": [bench, ev1, ev2]}],
                "unread_evidence_ids": [], "findings": [],
            })
            self.assertEqual(rev["symmetry_audit"]["flag_count"], 0)
            self.assertIn(
                ("possible_unadjusted_multiplicity_text", "missing_multiplicity_marker_text"),
                {(a["hook_code"], a["detail_code"]) for a in rev["symmetry_audit"]["lexical_advisories"]},
            )
        apkt = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        adj = self.engine.dispatch("submit_adjudication", {
            "case_id": self.cid, "adjudication_id": apkt["adjudication_id"],
            "input_digest": apkt["input_digest"], "adjudicator": {"context_id": "adj-by", "model": "fixture"},
            "unread_evidence_ids": [], "dispositions": [],
            "decisions": [{
                "claim_id": "C1", "claim_basis": "empirical", "claim_type": "computational",
                "evidence_level": "benchmark_measured", "scope": claim["scope"], "verdict": "supported",
                "revised_text": claim["text"], "rationale": "Simes closed-testing adjusted",
                "evidence_ids": [bench, ev1, ev2], "confidence": "high", "confidence_reason": "Both runs reported",
                "boundary": claim["scope"], "reversal_condition": "Unadjusted inflation",
            }],
        })
        self.assertEqual(adj["state"], "adjudicated")
        self.assertEqual(adj["symmetry_audit"]["flag_count"], 0)
        self.assertIn(
            ("possible_unadjusted_multiplicity_text", "missing_multiplicity_marker_text"),
            {(a["hook_code"], a["detail_code"]) for a in adj["symmetry_audit"]["lexical_advisories"]},
        )
        exp = self.engine.dispatch("export", {"case_id": self.cid})
        self.assertEqual(exp["state"], "exported")
        self.assertIn("possible\\_unadjusted\\_multiplicity\\_text", Path(exp["path"]).read_text(encoding="utf-8"))

    def test_structural_numeric_and_sqlite_hard_gates_remain_strictly_blocking(self):
        # 1. Numeric-only null (HR = 1.00) contradicting claimed HR = 1.62 still fails with unanchored_effect_estimate
        self.cid = self.engine.dispatch("create_case", {"question": "Numeric null?", "draft": "D", "writer_context_id": "w-num"})["case_id"]
        (self.root / "null1.txt").write_text("Observational study (N=420): adjusted HR = 1.00 (95% CI 0.82 to 1.22, p = 0.88).\n", encoding="utf-8")
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "null1.txt", "provenance": "observed", "kind": "observation",
            "quote": "Observational study (N=420): adjusted HR = 1.00 (95% CI 0.82 to 1.22, p = 0.88).", "location": "line 1",
        })["evidence_id"]
        c_num = self.claim("association", "adjusted", "observational")
        c_num["text"] = "Cohort shows HR = 1.62 (95% CI 1.21 to 2.16)."
        c_num["effect"] = {"estimate": "HR = 1.62", "uncertainty": "95% CI 1.21 to 2.16"}
        p_num = self.reviewed(c_num)
        p_num["decisions"][0]["revised_text"] = c_num["text"]
        self.error("unanchored_effect_estimate", "submit_adjudication", p_num)

        # 2. Failed critical check blocks ceiling
        self.cid = self.engine.dispatch("create_case", {"question": "Failed check?", "draft": "D", "writer_context_id": "w-fail"})["case_id"]
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "null1.txt", "provenance": "observed", "kind": "observation",
            "quote": "Observational study (N=420): adjusted HR = 1.00 (95% CI 0.82 to 1.22, p = 0.88).", "location": "line 1",
        })["evidence_id"]
        c_fail = self.claim("association", "adjusted", "observational")
        c_fail["design_packages"][0]["checks"]["confounding_selection"] = {"status": "fail", "reason": "Unmeasured confounding", "evidence_ids": []}
        c_fail["text"] = "Cohort shows HR = 1.00 (95% CI 0.82 to 1.22)."
        c_fail["effect"] = {"estimate": "HR = 1.00", "uncertainty": "95% CI 0.82 to 1.22"}
        p_fail = self.reviewed(c_fail)
        p_fail["decisions"][0]["revised_text"] = c_fail["text"]
        self.error("critical_check_ceiling", "submit_adjudication", p_fail)

        # 3. Synthetic provenance blocks empirical positive
        self.cid = self.engine.dispatch("create_case", {"question": "Synthetic prov?", "draft": "D", "writer_context_id": "w-syn"})["case_id"]
        (self.root / "syn.txt").write_text("Simulated cohort HR = 1.62 (95% CI 1.21 to 2.16).\n", encoding="utf-8")
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "syn.txt", "provenance": "synthetic", "kind": "synthetic",
            "quote": "Simulated cohort HR = 1.62 (95% CI 1.21 to 2.16).", "location": "line 1",
        })["evidence_id"]
        c_syn = self.claim("association", "adjusted", "observational")
        c_syn["text"] = "Cohort HR = 1.62 (95% CI 1.21 to 2.16)."
        p_syn = self.reviewed(c_syn)
        p_syn["decisions"][0]["revised_text"] = c_syn["text"]
        self.error("synthetic_empirical_support", "submit_adjudication", p_syn)

        # 4a. SQLite record-exec omission of a recorded fork still fails with selective_execution_omission
        self.cid = self.engine.dispatch("create_case", {"question": "SQLite fork omission?", "draft": "D", "writer_context_id": "w-omit"})["case_id"]
        omit_outs = []
        for idx in (1, 2):
            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main([
                    "record-exec", "--workspace", str(self.root),
                    "--case-id", self.cid, "--claim-id", "C1", "--card-id", f"ex-o-{idx}",
                    "--", sys.executable, "-c", f"print('run={idx} acc=0.88')",
                ])
            self.assertEqual(rc, 0)
            omit_outs.append(json.loads(buf.getvalue().decode("utf-8")))
        (self.root / "benchmark-omission.txt").write_text("Benchmark acc=0.88 across runs, independent result fixture.", encoding="utf-8")
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "benchmark-omission.txt", "kind": "benchmark", "provenance": "reported",
            "quote": "Benchmark acc=0.88 across runs, independent result fixture.", "location": "L1",
        })["evidence_id"]
        c_omit = self.claim("computational", "benchmark_measured", "ml")
        c_omit["evidence_ids"].append(omit_outs[0]["evidence"]["evidence_id"])
        c_omit["text"] = "Run acc=0.88."
        c_omit["effect"] = {"estimate": "acc=0.88", "uncertainty": "1 reported run"}
        c_omit["provenance_cards"]["execution"] = [omit_outs[0]["execution_card"]]
        p_omit = self.reviewed(c_omit)
        p_omit["decisions"][0]["revised_text"] = c_omit["text"]
        self.error("selective_execution_omission", "submit_adjudication", p_omit)

        # 4b. SQLite record-exec multi-fork with uncited multiplicity evidence fails with unadjusted_execution_multiplicity
        self.cid = self.engine.dispatch("create_case", {"question": "SQLite multi-fork?", "draft": "D", "writer_context_id": "w-fork"})["case_id"]
        outs = []
        for idx in (1, 2):
            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main([
                    "record-exec", "--workspace", str(self.root),
                    "--case-id", self.cid, "--claim-id", "C1", "--card-id", f"ex-h-{idx}",
                    "--", sys.executable, "-c", f"print('run={idx} acc=0.88')",
                ])
            self.assertEqual(rc, 0)
            outs.append(json.loads(buf.getvalue().decode("utf-8")))
        ev1, ev2 = outs[0]["evidence"]["evidence_id"], outs[1]["evidence"]["evidence_id"]
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "benchmark-omission.txt", "kind": "benchmark", "provenance": "reported",
            "quote": "Benchmark acc=0.88 across runs, independent result fixture.", "location": "L1",
        })["evidence_id"]
        c_fork = self.claim("computational", "benchmark_measured", "ml")
        c_fork["text"] = "Run acc=0.88."
        c_fork["effect"] = {"estimate": "acc=0.88", "uncertainty": "2 runs"}
        c_fork["evidence_ids"] = [self.ev, ev1, ev2]
        c_fork["checks"]["multiplicity"] = {"status": "pass", "reason": "Bonferroni correction across 2 executions"}
        c_fork["statistical_report"]["multiplicity_selection"] = {
            "status": "pass",
            "reason": "Bonferroni multiplicity control across both recorded executions",
            "evidence_ids": [ev1, ev2],
        }
        c_fork["provenance_cards"]["execution"] = [outs[0]["execution_card"], outs[1]["execution_card"]]
        p_fork = self.reviewed(c_fork)
        p_fork["decisions"][0]["revised_text"] = c_fork["text"]
        p_fork["decisions"][0]["evidence_ids"] = [self.ev, ev1]
        self.error("unadjusted_execution_multiplicity", "submit_adjudication", p_fork)

        # 4c. SQLite record-exec multi-fork without checks.multiplicity='pass' on description x measurement_checked also fails unadjusted_execution_multiplicity
        self.cid = self.engine.dispatch("create_case", {"question": "SQLite multi-fork check?", "draft": "D", "writer_context_id": "w-fork2"})["case_id"]
        outs2 = []
        for idx in (1, 2):
            buf = io.BytesIO()
            with patch.object(sys, "stdout", type("S", (), {"buffer": buf})()):
                rc = cli_main([
                    "record-exec", "--workspace", str(self.root),
                    "--case-id", self.cid, "--claim-id", "C1", "--card-id", f"ex-d-{idx}",
                    "--", sys.executable, "-c", f"print('run={idx} acc=0.88')",
                ])
            self.assertEqual(rc, 0)
            outs2.append(json.loads(buf.getvalue().decode("utf-8")))
        d_ev1, d_ev2 = outs2[0]["evidence"]["evidence_id"], outs2[1]["evidence"]["evidence_id"]
        self.ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": "benchmark-omission.txt", "kind": "benchmark", "provenance": "reported",
            "quote": "Benchmark acc=0.88 across runs, independent result fixture.", "location": "L1",
        })["evidence_id"]
        c_desc = self.claim("description", "measurement_checked", "ml")
        c_desc["text"] = "Measured run acc=0.88."
        c_desc["effect"] = {"estimate": "acc=0.88", "uncertainty": "2 runs"}
        c_desc["evidence_ids"] = [self.ev, d_ev1, d_ev2]
        c_desc["checks"]["multiplicity"] = {"status": "unknown", "reason": "Multiplicity adjustment status not evaluated across runs"}
        c_desc["statistical_report"]["multiplicity_selection"] = {
            "status": "unknown",
            "reason": "Multiplicity evidence not linked",
            "evidence_ids": [],
        }
        c_desc["provenance_cards"]["execution"] = [outs2[0]["execution_card"], outs2[1]["execution_card"]]
        p_desc = self.reviewed(c_desc)
        p_desc["decisions"][0]["revised_text"] = c_desc["text"]
        p_desc["decisions"][0]["evidence_ids"] = [self.ev, d_ev1, d_ev2]
        self.error("unadjusted_execution_multiplicity", "submit_adjudication", p_desc)


if __name__ == "__main__":
    unittest.main()
