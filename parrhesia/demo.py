"""A fixed synthetic demonstration. This never invokes a model or analyzes research data."""
from __future__ import annotations

import json
from pathlib import Path

from .core import Engine


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
    raw = "SYNTHETIC FIXTURE — 以下数值全部人为编写，不来自真实分析或研究。\n观察性资料：T与表型相关，调整后差值 0.40，95% CI [0.20, 0.60]；没有干预M的实验。\n直接交互比较：A-B效应差为0.30，95% CI [0.10, 0.50]；共1个预设形式的演示比较，实际起源为人工构造。\n临床用途：未提供外部患者队列、校准、决策效用或临床验证资料。\n"
    (output / "synthetic-evidence.txt").write_text(raw, encoding="utf-8")
    evidence_id = call("register_evidence", {"case_id": case_id, "path": "synthetic-evidence.txt", "label": "人工构造的流程样例", "provenance": "synthetic", "quote": "没有干预M的实验", "location": "line 2"})["evidence_id"]
    checks = {key: {"status": "unknown", "reason": "仅为人工构造的流程样例，未进行真实科学核验"} for key in ("quality", "batch", "unit", "assumptions", "multiplicity", "leakage", "baseline")}
    claims = [
        {"id": "C1", "text": "T通过M导致表型变化", "level": "causal", "evidence_ids": [evidence_id], "effect": {"estimate": "差值0.40（虚构）", "uncertainty": "95% CI [0.20, 0.60]（虚构）"}, "scope": "仅人工构造的观察性场景", "origin": "exploratory", "alternatives": [{"explanation": "未测量混杂或反向因果", "status": "not_excluded", "reason": "场景没有干预证据"}], "checks": checks, "contribution": "限定当前资料可支持的主张级别"},
        {"id": "C2", "text": "组间结果不一致，难以形成结论", "level": "descriptive", "evidence_ids": [evidence_id], "effect": {"estimate": "直接交互效应差0.30（虚构）", "uncertainty": "95% CI [0.10, 0.50]（虚构）"}, "scope": "仅人工构造的A/B条件；共1个直接比较", "origin": "exploratory", "alternatives": [{"explanation": "不同批次造成效应差异", "status": "not_excluded", "reason": "没有提供原始数据核验"}], "checks": checks, "contribution": "组间效应差异可以界定适用条件"},
        {"id": "C3", "text": "X可用于临床判断", "level": "predictive", "evidence_ids": [], "effect": {"estimate": "UNKNOWN", "uncertainty": "UNKNOWN"}, "scope": "临床用途主张的资料缺口示例", "origin": "unknown", "alternatives": [{"explanation": "样本内表现无法泛化", "status": "not_excluded", "reason": "未提供外部资料"}], "checks": checks, "contribution": "明确当前无法支持临床用途，指出改变该判断的证据"},
    ]
    call("set_ledger", {"case_id": case_id, "claims": claims})
    call("freeze", {"case_id": case_id})
    findings = {
        "overclaim": [{"id": "O1", "claim_id": "C1", "evidence_ids": [evidence_id], "issue": "观察性关系被写成经由M的因果机制", "proposed_level": "association", "proposed_text": "在给定观察性场景中，T与表型变化相关。", "decision_impact": "收窄为相关；经由M的因果机制不成立为已证结论。"}, {"id": "O2", "claim_id": "C3", "evidence_ids": [], "issue": "临床用途没有验证资料", "proposed_level": "predictive", "proposed_text": "当前证据不足以支持X用于临床判断。", "decision_impact": "裁为证据不足，不能推荐应用。"}],
        "underclaim": [{"id": "U1", "claim_id": "C2", "evidence_ids": [evidence_id], "issue": "直接交互比较支持差异，却被‘不一致’掩盖", "proposed_level": "association", "proposed_text": "该模拟场景包含A/B条件间的效应差异，可用于说明条件依赖的贡献。", "decision_impact": "在保留技术解释未排除的边界下，明确承认已有直接比较结果。"}],
    }
    packets = {}
    for role in ("overclaim", "underclaim"):
        packets[role] = call("review_packet", {"case_id": case_id, "role": role})
    for role, packet in packets.items():
        call("submit_review", {"case_id": case_id, "role": role, "packet_id": packet["packet_id"], "input_digest": packet["input_digest"], "reviewer": {"context_id": "synthetic-" + role, "model": "FIXTURE_NO_MODEL_CALL"}, "covered_claim_ids": ["C1", "C2", "C3"], "findings": findings[role]})
    adjudication = call("adjudication_packet", {"case_id": case_id})
    decisions = [
        {"claim_id": "C1", "verdict": "supported", "level": "association", "revised_text": "在此人工构造的观察性场景中，T与表型变化相关；经由M的因果机制尚无支持。", "rationale": "支持的是收窄后的相关命题；原稿的因果证明不获支持。", "evidence_ids": [evidence_id], "confidence": "medium", "confidence_reason": "对样例内部的文字与证据关系判断；并非真实科研置信度。", "boundary": "仅人工构造场景，不是实际科学结果。", "reversal_condition": "若提供能够识别M作用的适当干预证据，则重新评估机制主张。"},
        {"claim_id": "C2", "verdict": "supported", "level": "association", "revised_text": "在此人工构造的场景中，直接比较支持A/B效应不同，这一差异界定了关系的适用条件。", "rationale": "依据直接交互比较，而非一组显著、另一组不显著。", "evidence_ids": [evidence_id], "confidence": "medium", "confidence_reason": "样例中有直接比较；真实批次与重复结构未核验。", "boundary": "只认可样例中的条件差异，不据此宣称生物机制。", "reversal_condition": "若真实资料中批次调整消除该差异，则不再保留生物学异质性的解释。"},
        {"claim_id": "C3", "verdict": "insufficient_evidence", "level": "predictive", "revised_text": "当前资料不足以支持X用于临床判断。", "rationale": "没有外部患者队列、校准或决策效用资料。", "evidence_ids": [], "confidence": "high", "confidence_reason": "对当前资料未建立临床用途的判断明确；不等于断言X无效。", "boundary": "只针对本案例已提供的资料。", "reversal_condition": "提供目标人群的独立验证、校准与决策效用证据后重新裁决。"},
    ]
    dispositions = [{"finding_id": f["id"], "disposition": "accepted", "reason": f["decision_impact"]} for items in findings.values() for f in items]
    call("submit_adjudication", {"case_id": case_id, "adjudication_id": adjudication["adjudication_id"], "input_digest": adjudication["input_digest"], "adjudicator": {"context_id": "synthetic-adjudicator", "model": "FIXTURE_NO_MODEL_CALL"}, "decisions": decisions, "dispositions": dispositions})
    exported = call("export", {"case_id": case_id})
    # Reopen through a new engine to exercise durable recovery before rendering.
    recovered = Engine(output).dispatch("get_case", {"case_id": case_id})
    (output / "case.json").write_text(json.dumps(recovered, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "workflow-transcript.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
    from .report import render_report
    report = output / "review.html"
    render_report({"case_id": case_id, "draft": draft, "claims": claims, "decisions": decisions, "findings": findings, "dispositions": dispositions, "verification": exported["verification"], "export": exported, "packets": packets}, report)
    return {"case_id": case_id, "demonstration": "SYNTHETIC_NO_MODEL_CALL", "workspace": str(output), "markdown": exported["path"], "html": str(report), "transcript": str(output / "workflow-transcript.json"), "restart_recovery": True, "scientific_validity": "not_established", "grok_behavior_improvement": "not_measured"}
