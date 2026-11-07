"""A fixed synthetic demonstration. This never invokes a model or analyzes research data."""
from __future__ import annotations

import json
from pathlib import Path

from .core import Engine
from .claims import CARD_FIELDS, DESIGN_FIELDS, ESTIMAND_FIELDS, STAT_FIELDS


def run_demo(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("Demo output must be a new directory; existing work is never overwritten")
    output.mkdir(parents=True)
    engine = Engine(output)
    calls = []

    def call(action, payload):
        result = engine.dispatch(action, payload)
        calls.append({"action": action, "payload": payload, "result": result})
        return result

    draft = "T处理通过M通路导致表型改变。A组正向、B组不显著，结果不一致，难以形成贡献。X是否能用于临床判断还需更多研究。"
    case_id = call("create_case", {"question": "演示：如何同时纠正因果越级、埋没异质性贡献和无明确裁决？", "draft": draft, "domain": "scientific", "writer_context_id": "synthetic-writer"})["case_id"]
    raw = "SYNTHETIC FIXTURE — 以下数值全部人为编写，不来自真实分析或研究。\n观察性资料：T与表型相关，调整后差值 0.40，95% CI [0.20, 0.60]；缺少M路径的识别假设与敏感度依据。\n直接交互比较：A-B效应差为0.30，95% CI [0.10, 0.50]；共1个预设形式的演示比较，实际起源为人工构造。\n临床用途：未提供外部患者队列、校准、决策效用或临床验证资料。\n"
    (output / "synthetic-evidence.txt").write_text(raw, encoding="utf-8")
    evidence_id = call("register_evidence", {"case_id": case_id, "path": "synthetic-evidence.txt", "label": "人工构造的流程样例", "kind": "synthetic", "provenance": "synthetic", "quote": "以下数值全部人为编写，不来自真实分析或研究。", "location": "line 1"})["evidence_id"]
    checks = {key: {"status": "unknown", "reason": "仅为人工构造的流程样例，未进行真实科学核验"} for key in ("quality", "batch", "unit", "assumptions", "multiplicity", "leakage", "baseline")}
    claims = [
        {"id": "C1", "text": "T通过M导致表型变化", "claim_type": "causal_effect", "evidence_level": "unidentified", "evidence_ids": [evidence_id], "effect": {"estimate": "差值0.40（虚构）", "uncertainty": "95% CI [0.20, 0.60]（虚构）"}, "scope": "仅人工构造的观察性场景", "origin": "exploratory", "alternatives": [{"explanation": "未测量混杂或反向因果", "status": "not_excluded", "reason": "场景未建立M路径的因果识别依据"}], "checks": checks, "contribution": "限定当前资料可支持的主张类型、类型内等级与范围"},
        {"id": "C2", "text": "组间结果不一致，难以形成结论", "claim_type": "description", "evidence_level": "recorded", "evidence_ids": [evidence_id], "effect": {"estimate": "直接交互效应差0.30（虚构）", "uncertainty": "95% CI [0.10, 0.50]（虚构）"}, "scope": "仅人工构造的A/B条件；共1个直接比较", "origin": "exploratory", "alternatives": [{"explanation": "不同批次造成效应差异", "status": "not_excluded", "reason": "没有提供原始数据核验"}], "checks": checks, "contribution": "组间效应差异可以界定适用条件"},
        {"id": "C3", "text": "X可用于临床判断", "claim_type": "prediction", "evidence_level": "unassessed", "evidence_ids": [], "effect": {"estimate": "UNKNOWN", "uncertainty": "UNKNOWN"}, "scope": "临床用途主张的资料缺口示例", "origin": "unknown", "alternatives": [{"explanation": "样本内表现无法泛化", "status": "not_excluded", "reason": "未提供外部资料"}], "checks": checks, "contribution": "明确当前无法支持临床用途，指出改变该判断的证据"},
    ]
    # Explicitly classify this synthetic fixture; this is not a legacy-record migration.
    def unknown():
        return {"status": "unknown", "reason": "人工构造流程示例；未进行真实科学分析", "evidence_ids": []}

    for claim in claims:
        claim["claim_basis"] = "empirical"
        claim["design_packages"] = [{"family": "observational", "checks": {key: unknown() for key in DESIGN_FIELDS["observational"]}}]
        claim["statistical_report"] = {key: unknown() for key in STAT_FIELDS}
        claim["provenance_cards"] = {kind: [] for kind in CARD_FIELDS}
        claim["provenance_cards"]["execution"] = [{"id": claim["id"] + "-EX", "status": "not_run", "reason": "示例数值为人工编写；并未执行科学分析", "evidence_ids": [], "details": {key: "UNKNOWN" for key in CARD_FIELDS["execution"]}}]
    claims[0]["causal_basis"] = {
        "design_family": "observational", "estimand": {key: "UNKNOWN" for key in ESTIMAND_FIELDS},
        "assumptions": [{"name": "混杂与M路径识别", **unknown()}],
        "falsification_sensitivity": [{"name": "未测量混杂敏感度", **unknown()}],
        "assessment": unknown(), "necessity_test": unknown(), "sufficiency_test": unknown(),
    }
    call("set_ledger", {"case_id": case_id, "claims": claims})
    call("freeze", {"case_id": case_id})
    synthetic_scope = "仅描述人工构造的文本记录，无经验性推断"
    findings = {
        "overclaim": [
            {"id": "O1", "claim_id": "C1", "evidence_ids": [evidence_id], "issue": "人工构造数值不能建立经验性因果或相关证据", "proposed_claim_type": "description", "proposed_evidence_level": "recorded", "proposed_claim_basis": "synthetic", "proposed_scope": synthetic_scope, "proposed_text": "样例文本人为填写了相关差值；没有产生经验性相关或因果证据。", "decision_impact": "只保留合成记录描述，原经验性命题证据不足。"},
            {"id": "O2", "claim_id": "C3", "evidence_ids": [], "issue": "临床用途没有验证资料", "proposed_claim_type": "prediction", "proposed_evidence_level": "unassessed", "proposed_claim_basis": "empirical", "proposed_scope": claims[2]["scope"], "proposed_text": "当前证据不足以支持X用于临床判断。", "decision_impact": "裁为证据不足，不能推荐应用。"},
        ],
        "underclaim": [
            {"id": "U1", "claim_id": "C2", "evidence_ids": [evidence_id], "issue": "可保留可追溯的合成比较记录，但不能当作经验性差异", "proposed_claim_type": "description", "proposed_evidence_level": "recorded", "proposed_claim_basis": "synthetic", "proposed_scope": synthetic_scope, "proposed_text": "样例文本人为填写了交互比较数值；没有产生经验性组间差异证据。", "decision_impact": "恢复样例描述，明确其不能支撑生物学差异。"},
        ],
    }
    packets = {}
    for role in ("overclaim", "underclaim"):
        packets[role] = call("review_packet", {"case_id": case_id, "role": role})
    for role, packet in packets.items():
        call("submit_review", {"case_id": case_id, "role": role, "packet_id": packet["packet_id"], "input_digest": packet["input_digest"], "reviewer": {"context_id": "synthetic-" + role, "model": "FIXTURE_NO_MODEL_CALL"}, "covered_claim_ids": ["C1", "C2", "C3"], "claim_stances": [{"claim_id": c["id"], "stance": "insufficient_evidence", "rationale": "人工构造资料不能支持原经验性主张", "evidence_ids": []} for c in claims], "unread_evidence_ids": [], "findings": findings[role]})
    adjudication = call("adjudication_packet", {"case_id": case_id})
    decisions = []
    for claim in claims:
        finding = next(f for items in findings.values() for f in items if f["claim_id"] == claim["id"])
        synthetic = finding["proposed_claim_basis"] == "synthetic"
        decision = {
            "claim_id": claim["id"], "verdict": "supported" if synthetic else "insufficient_evidence",
            "revised_text": finding["proposed_text"], "evidence_ids": finding["evidence_ids"],
            "rationale": "正向判定仅确认合成文本有该记录；原经验性命题证据不足。" if synthetic else "没有外部患者队列、校准或决策效用资料。",
            "confidence": "medium" if synthetic else "high",
            "confidence_reason": "对合成文本记录的核对，不是对真实效应的置信度。" if synthetic else "当前资料没有建立临床用途；不等于断言X无效。",
            "boundary": synthetic_scope if synthetic else "只针对本案例已提供的资料。",
            "reversal_condition": "若原始样例文本显示该引用或记录不符，则撤回描述；真实效应须另立经验性主张审查。" if synthetic else "提供目标人群的独立验证、校准与决策效用证据后重新裁决。",
        }
        for key in ("claim_type", "evidence_level", "claim_basis", "scope"):
            decision[key] = finding["proposed_" + key]
        decisions.append(decision)
    dispositions = [{"finding_id": f["id"], "claim_id": f["claim_id"], "disposition": "accepted", "resolution": "incorporated", "revised_text_quote": f["proposed_text"], "reason": f["decision_impact"]} for items in findings.values() for f in items]
    call("submit_adjudication", {"case_id": case_id, "adjudication_id": adjudication["adjudication_id"], "input_digest": adjudication["input_digest"], "adjudicator": {"context_id": "synthetic-adjudicator", "model": "FIXTURE_NO_MODEL_CALL"}, "unread_evidence_ids": [], "decisions": decisions, "dispositions": dispositions})
    exported = call("export", {"case_id": case_id})
    # Reopen through a new engine to exercise durable recovery before rendering.
    recovered = Engine(output).dispatch("get_case", {"case_id": case_id})
    (output / "case.json").write_text(json.dumps(recovered, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "workflow-transcript.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
    from .report import render_report
    report = output / "review.html"
    render_report({"demonstration": "SYNTHETIC_NO_MODEL_CALL", "case_id": case_id, "draft": draft, "claims": claims, "decisions": decisions, "findings": findings, "dispositions": dispositions, "verification": exported["verification"], "export": exported, "packets": packets, "gate_version": recovered["gate_version"], "blind": recovered["blind"], "reviews": recovered["reviews"], "evidence": recovered["evidence"], "unread_evidence_ids": recovered["adjudication"]["unread_evidence_ids"]}, report)
    return {"case_id": case_id, "demonstration": "SYNTHETIC_NO_MODEL_CALL", "workspace": str(output), "markdown": exported["path"], "html": str(report), "transcript": str(output / "workflow-transcript.json"), "restart_recovery": True, "scientific_validity": "not_established", "grok_behavior_improvement": "not_measured"}
