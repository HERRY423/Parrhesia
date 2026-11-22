"""Offline, read-only review report. All caller text is HTML-escaped."""
from __future__ import annotations

from html import escape
import hashlib
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from . import __version__
from .claims import describe
from .contracts import CHECK_NAMES, ROLES, fail
from .gates import ceiling, gated


LABELS = {
    "supported": "支持", "partially_supported": "条件性支持", "unsupported": "不支持", "insufficient_evidence": "证据不足",
    "descriptive": "描述性观察", "association": "相关", "predictive": "可预测", "mechanistic": "机制线索", "causal": "因果",
    "test_passed": "测试通过", "host_accepted": "宿主验收", "user_impact": "用户效果",
    "accepted": "采纳", "partial": "部分采纳", "rejected": "驳回",
}


def text(value) -> str:
    return escape(str(value), quote=True)


def structured(value, path=""):
    rows = []
    if isinstance(value, dict):
        for key, child in value.items():
            rows.extend(structured(child, f"{path}.{key}" if path else key))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            rows.extend(structured(child, f"{path}[{index}]"))
    else:
        rows.append(f"<tr><th>{text(path)}</th><td>{text(value)}</td></tr>")
    return rows


def render_case_report(workspace: str | Path, case_id: str, output: str) -> dict:
    """Render a saved adjudication locally without re-verifying or editing the case."""
    from .core import Engine
    from .storage import safe_workspace_path
    root = Path(workspace).resolve(strict=True)
    case = Engine.read_case_snapshot(root, case_id)
    if case["state"] not in ("adjudicated", "export_pending", "exported") or not case.get("adjudication"):
        fail("case_not_adjudicated", "HTML reports require a saved adjudication; draft claims are not decisions")
    if case.get("event_chain_status") == "tampered":
        fail("event_chain_tampered", "Saved event history failed integrity checks; no report was written")
    target = safe_workspace_path(root, output)
    if target.suffix.lower() not in (".html", ".htm"):
        fail("invalid_value", "Report output must be a workspace-relative .html or .htm path")
    if target.exists():
        fail("export_exists", "Report output already exists; choose a new path")
    snapshot = {
        "case_id": case_id, "case_state": case["state"],
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_sha256": hashlib.sha256(json.dumps(case, ensure_ascii=False, sort_keys=True,
                                                 separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "verification_basis": "saved_record_only; source files were not re-verified by this render",
        "scientific_validity": "not_established_by_rendering",
    }
    data = {**case, "report_snapshot": snapshot}
    if not case.get("verification"):
        data["verification"] = {"status": "not_run", "scope": "No saved verification record"}
    target.parent.mkdir(parents=True, exist_ok=True)
    render_report(data, target)
    return {"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "snapshot": snapshot, "case_mutated": False}


def render_report(data: dict, target: Path) -> None:
    cards = []
    adjudication = data.get("adjudication") or {}
    decisions_list = data["decisions"] if "decisions" in data else adjudication.get("decisions", [])
    dispositions_list = data["dispositions"] if "dispositions" in data else adjudication.get("dispositions", [])
    reviews_map = data.get("reviews", {})
    findings_map = data["findings"] if "findings" in data else {
        role: rev.get("findings", []) for role, rev in reviews_map.items()
    }
    dispositions = {item["finding_id"]: item for item in dispositions_list}
    claims = {item["id"]: item for item in data["claims"]}
    verification_data = data.get("verification") or {}
    trig_by_claim = {
        te["claim_id"]: te
        for te in ((verification_data.get("trigger_evaluation") or {}).get("claim_evaluations") or ())
    }
    cal_outcomes = data.get("calibration_outcomes") or []
    for item in decisions_list:
        claim = claims[item["claim_id"]]
        reviews = []
        for role, review in reviews_map.items():
            for stance in review.get("claim_stances", []):
                if stance["claim_id"] == item["claim_id"]:
                    reviews.append('<div class="finding"><span>' + text(role) + ' · 原命题立场</span><table>' + ''.join(structured(stance)) + '</table></div>')
        for role, findings in findings_map.items():
            for finding in findings:
                if finding["claim_id"] != item["claim_id"]:
                    continue
                disp = dispositions[finding["id"]]
                disposition_condition = f'<p><strong>采纳条件：</strong>{text(disp["condition"])}</p>' if disp.get("condition") else ""
                if "resolution" in disp:
                    disposition_condition += '<table>' + ''.join(structured({key: disp[key] for key in ('claim_id', 'resolution', 'revised_text_quote', 'disagreement') if key in disp})) + '</table>'
                reviews.append(f'<div class="finding"><span>{"夸大审查" if role == "overclaim" else "低估审查"} · {text(finding["id"])} · {LABELS[disp["disposition"]]}</span><p>{text(finding["issue"])}</p><small>{text(disp["reason"])}</small>{disposition_condition}</div>')
        condition = f'<dt>成立条件</dt><dd>{text(item["condition"])}</dd>' if item.get("condition") else ""
        claim_details = {'effect': claim['effect'], 'checks': claim['checks'], 'alternatives': claim['alternatives']}
        if "claim_basis" in claim:
            claim_details.update(original_claim_basis=claim['claim_basis'], decided_claim_basis=item['claim_basis'], check_ceiling=ceiling(claim, item['claim_type']))
        for key in ('design_packages', 'statistical_report', 'causal_basis', 'provenance_cards', 'effect_records', 'prior_claim_links', 'reversal_triggers'):
            if key in claim:
                claim_details[key] = claim[key]
        if 'reversal_triggers' in item:
            claim_details['decision_reversal_triggers'] = item['reversal_triggers']
        if 'forecast_probability' in item:
            claim_details['forecast_probability'] = item['forecast_probability']
        for extra_dec_key in ('actionable_stance', 'abstention_justification', 'evidence_dominance'):
            if extra_dec_key in item:
                claim_details[extra_dec_key] = item[extra_dec_key]
        eff_check = (verification_data.get('effect_checks') or {}).get(item['claim_id'])
        if eff_check:
            claim_details['effect_checks'] = eff_check
        trig_eval = trig_by_claim.get(item['claim_id'])
        if trig_eval:
            claim_details['trigger_evaluation'] = trig_eval
        claim_cal = [co for co in cal_outcomes if co.get('claim_id') == item['claim_id']]
        if claim_cal:
            claim_details['calibration_outcomes'] = claim_cal
        if claim.get('best_current_explanation'):
            claim_details['best_current_explanation'] = claim['best_current_explanation']
        if claim.get('discriminating_test'):
            claim_details['discriminating_test'] = claim['discriminating_test']
        basis_label = ' · ' + text(item['claim_basis']) if 'claim_basis' in item else ''
        prob_label = f' · 预测概率：{text(item["forecast_probability"])}' if 'forecast_probability' in item else ''
        cards.append(f'''<article class="claim" data-verdict="{text(item['verdict'])}">
          <div class="claim-top"><span class="id">{text(item['claim_id'])}</span><span class="badge {text(item['verdict'])}">{LABELS[item['verdict']]}</span><span class="level">{text(describe(item))}{basis_label}</span></div>
          <h2>{text(item['revised_text'])}</h2><p class="original">原主张：{text(claim['text'])}</p>
          <dl><dt>判断依据</dt><dd>{text(item['rationale'])}</dd>{condition}<dt>成立边界</dt><dd>{text(item['boundary'])}</dd><dt>改判条件</dt><dd>{text(item['reversal_condition'])}</dd></dl>
          <details><summary>审查意见与裁决理由</summary>{''.join(reviews)}<p>置信度：{text(item['confidence'])} · {text(item['confidence_reason'])}{prob_label}</p></details>
          <details><summary>原主张分类、设计、统计报告与溯源卡（提交者记录）</summary><p>{text(describe(claim))}</p><table>{''.join(structured(claim_details))}</table></details>
        </article>''')
    def _isolation_manifest_extra(record: dict) -> dict:
        extra = {}
        ig = record.get("isolation_grade")
        if isinstance(ig, dict) and ig.get("grade"):
            extra["isolation_grade"] = ig["grade"]
            extra["isolation_basis"] = ig.get("basis", "UNKNOWN")
            if isinstance(ig.get("boundaries"), dict):
                extra["isolation_boundaries"] = ig["boundaries"]
        rec = record.get("isolation_receipt")
        if isinstance(rec, dict):
            extra["runner_seal_verified"] = bool(rec.get("runner_seal_verified", False))
            if rec.get("transcript_sha256"):
                extra["transcript_sha256"] = rec["transcript_sha256"]
            for bkey in ("env_scrubbed", "isolated_cwd", "two_stage_blind", "workspace_untouched"):
                if bkey in rec:
                    extra[bkey] = bool(rec[bkey])
            for skey in ("stage1_estimate_sha256", "stage1_transcript_sha256", "os_sandbox"):
                if rec.get(skey):
                    extra[skey] = rec[skey]
        return extra

    input_manifests = {
        role: {
            "packet_id": rev.get("packet_id", "UNKNOWN"),
            "input_digest": rev.get("input_digest", "UNKNOWN"),
            "blind": data.get("blind", "UNKNOWN"),
            "covered_claim_ids": rev.get("covered_claim_ids", []),
            "unread_evidence_ids": rev.get("unread_evidence_ids", []),
            "history_inheritance": (rev.get("isolation_attestation") or {}).get("history_inheritance", "UNKNOWN"),
            "memory_access": (rev.get("isolation_attestation") or {}).get("memory_access", "UNKNOWN"),
            "host_surface": (rev.get("isolation_attestation") or {}).get("host_surface", "UNKNOWN"),
            **_isolation_manifest_extra(rev),
        }
        for role, rev in data.get("reviews", {}).items()
    }
    adj_att = adjudication.get("isolation_attestation") or data.get("adjudication_isolation_attestation") or {}
    adjudication_manifest = {
        "history_inheritance": adj_att.get("history_inheritance", "UNKNOWN"),
        "memory_access": adj_att.get("memory_access", "UNKNOWN"),
        "host_surface": adj_att.get("host_surface", "UNKNOWN"),
    }
    adjudication_iso_extra = _isolation_manifest_extra(adjudication)
    symmetry_audit = data.get("symmetry_audit") or verification_data.get("symmetry_audit") or {
        "non_blocking": True,
        "severity": "advisory",
        "status": "not_run",
        "flag_count": None,
        "flags": [],
    }
    evidence_chains = verification_data.get("evidence_chains", [])
    audit_payload = {
        "verification": verification_data,
        "evidence_chains": evidence_chains,
        "symmetry_audit": symmetry_audit,
        "export": data.get("export", {}),
        "gate_version": data.get("gate_version", "LEGACY_OR_NOT_SUPPLIED"),
        "blind": data.get("blind", "UNKNOWN"),
        "reviewer_input_manifests": input_manifests,
        "adjudication_isolation_attestation": adjudication_manifest,
        **({"adjudication_isolation_grade": adjudication_iso_extra} if adjudication_iso_extra else {}),
        "reviews": reviews_map,
        "evidence": data.get("evidence", []),
        "adjudication_unread_evidence_ids": adjudication.get("unread_evidence_ids", data.get("unread_evidence_ids", "NOT_SUPPLIED")),
        "report_snapshot": data.get("report_snapshot"),
        "human_decisions": data.get("human_decisions", []),
        "event_chain": data.get("event_chain", {"status": "not_supplied"}),
        "events": data.get("events", []),
        "adjudication": adjudication,
    }
    for lineage_key in ("prior_case_ids", "supersedes_case_id", "case_relation", "calibration_outcomes"):
        if lineage_key in data:
            audit_payload[lineage_key] = data[lineage_key]
    audit = text(json.dumps(audit_payload, ensure_ascii=False, indent=2))
    sym_flags = symmetry_audit.get("flags") or []
    sym_lex = symmetry_audit.get("lexical_advisories") or []
    sym_parts = [
        f'<div class="finding"><span>{text(f.get("hook_code"))} · {text(f.get("claim_id"))} · non_blocking=true</span>'
        f'<p>{text(f.get("message"))}</p>'
        f'<small>observed={text(f.get("observed_verdict"))} · candidate={text(f.get("advisory_candidate_verdict") or "n/a")}/{text(f.get("advisory_candidate_level") or "n/a")}</small></div>'
        for f in sym_flags
    ]
    sym_parts.extend(
        f'<div class="finding"><span>{text(a.get("hook_code"))}{" (" + text(a.get("detail_code")) + ")" if a.get("detail_code") else ""} · {text(a.get("claim_id"))} · non_blocking=true</span>'
        f'<p>{text(a.get("message"))}</p></div>'
        for a in sym_lex
    )
    if sym_parts:
        sym_html = "".join(sym_parts)
    elif symmetry_audit.get("status") == "not_run":
        sym_html = '<p>没有已保存的对称性审计结果（not_run）；不能据此判断是否存在低估或假弃权。</p>'
    else:
        sym_html = '<p>未触发低估、假弃权或词法提示（flag_count=0, lexical_advisory_count=0；仅作参考，不阻断审查或导出）。</p>'
    ev_verify_map = {e.get("evidence_id"): e for e in verification_data.get("evidence", []) if isinstance(e, dict)}
    lineage_rows = []
    for ev in data.get("evidence", []):
        if not isinstance(ev, dict):
            continue
        eid = ev.get("evidence_id")
        ver_ev = ev_verify_map.get(eid, {})
        if ev.get("derived_from_evidence_ids") or ver_ev.get("excerpt_window_count"):
            lineage_rows.append({
                "evidence_id": eid,
                "derived_from_evidence_ids": ev.get("derived_from_evidence_ids", []),
                "derivation_step": ev.get("derivation_step", ""),
                "lineage_status": ver_ev.get("lineage_status", "unknown"),
                "excerpt_window_count": ver_ev.get("excerpt_window_count", 0),
                "excerpt_windows": ver_ev.get("excerpt_windows", []),
            })
    lineage_html = (
        '<table>' + ''.join(structured(lineage_rows)) + '</table>'
        if lineage_rows
        else '<p>无派生谱系或分窗摘录记录。</p>'
    )
    synthetic = data.get("demonstration") == "SYNTHETIC_NO_MODEL_CALL"
    notice = "<strong>人工构造的工程演示</strong> · 全部数值与审查意见为预置样例；没有调用 Grok，没有运行科学分析，也没有测量插件改善效果。这是离线只读报告。" if synthetic else "<strong>提交者记录</strong> · 本报告展示冻结资料与已保存裁定；结构校验不证明数据真实、执行发生、科学有效性或用户接受。"
    if data.get("report_snapshot"):
        notice += "<br>案例状态：" + text(data["report_snapshot"]["case_state"]) + "；生成时间：" + text(data["report_snapshot"]["rendered_at"])
        notice += "<br>核对状态来自已保存记录；生成本页没有重新核验源文件，也没有登记用户接受。"
    notice += "<br>门控：" + ("gate_version=1；案例级盲审=" + text(data.get("blind", "UNKNOWN")) if data.get("gate_version") == 1 else "历史记录或未提供门控版本；不能视为通过当前门控。")
    review_boundary = "核对的是保存内容、文件版本和引用锚点。内容一致不等于数据真实、分析正确或科学结论成立。审查上下文在本演示中仅为合成标记，不代表真实的独立模型审查。" if synthetic else "核对的是保存内容、文件版本和引用锚点。上下文标识与核对状态为提交者记录，不能据此证明独立审查、科学有效性或实际收益。"
    html = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Parrhesia · 结论审查</title><style>
    :root{color-scheme:light;--ink:#173331;--muted:#596b68;--line:#d8dfd8;--paper:#f4f5ee;--green:#c9ebdb}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.7 system-ui,'Microsoft YaHei',sans-serif}header{border-bottom:1px solid var(--line);padding:22px 5vw;display:flex;align-items:center;justify-content:space-between;gap:20px}header strong{font:600 25px Georgia,serif;letter-spacing:-1px}.subtitle{font-size:12px;color:var(--muted)}main{max-width:1150px;margin:auto;padding:46px 28px 70px}.eyebrow{font-size:12px;letter-spacing:2px;color:#526b60}h1{font-size:38px;line-height:1.3;letter-spacing:-1px;margin:12px 0 14px}.intro{max-width:740px;color:var(--muted);font-size:17px}.notice{margin:26px 0;border:1px solid #d3bc87;background:#fff5d9;padding:14px 18px;border-radius:10px}.flow{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:28px 0}.step{border-top:3px solid #95bca8;padding:13px 12px;background:#e8ede5}.step b{font-size:12px;display:block;color:#587264}.step span{font-size:14px}.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin:32px 0 18px}button{cursor:pointer;background:transparent;border:1px solid var(--line);border-radius:25px;padding:8px 17px;color:var(--ink);font:inherit;font-size:13px}button[aria-pressed=true]{background:var(--ink);color:white;border-color:var(--ink)}button:focus-visible,summary:focus-visible{outline:3px solid #db944d;outline-offset:4px}.claim{padding:26px 30px;border:1px solid var(--line);background:#fffef9;border-radius:14px;margin-bottom:17px}.claim-top{display:flex;gap:12px;align-items:center}.id{font-family:ui-monospace,monospace;color:var(--muted);font-size:13px}.badge{padding:3px 12px;border-radius:6px;background:#e6eadf;font-size:12px}.supported{background:var(--green)}.partially_supported{background:#e0e9d5}.insufficient_evidence{background:#f4e4bf}.unsupported{background:#f0d4c7}.level{font-size:12px;color:var(--muted)}h2{font-size:21px;line-height:1.6;margin:17px 0 10px}.original{color:#75817a;font-size:13px;border-left:2px solid #cdd4ca;padding-left:12px}dl{display:grid;grid-template-columns:90px 1fr;gap:10px 16px;margin:22px 0}dt{font-size:13px;color:var(--muted)}dd{margin:0}details{border-top:1px solid #e7e9e1;padding:13px 0 0;margin-top:13px}summary{cursor:pointer;font-size:13px;color:#3c6555}.finding{margin:15px 0;padding:13px 17px;background:#f1f4ed;border-radius:8px}.finding span{font-size:12px;color:#527166}.finding p{margin:7px 0}.finding small{color:var(--muted)}pre{font:12px/1.7 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#edf0e9;padding:16px;border-radius:8px}.audit{margin-top:36px}.audit h2{font-size:20px}footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:22px;margin-top:35px}a{color:var(--ink)}[hidden]{display:none!important}@media(max-width:650px){main{padding:28px 16px}h1{font-size:29px}.flow{grid-template-columns:1fr 1fr}.claim{padding:20px}dl{grid-template-columns:1fr;gap:3px}dd{margin-bottom:12px}.subtitle{max-width:140px}}
    table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);text-align:left;vertical-align:top;padding:8px;overflow-wrap:anywhere}th{width:35%}.claim-top{flex-wrap:wrap}</style></head><body><header><strong>Parrhesia<span style="color:#688e76">.</span></strong><span class="subtitle">有依据地表态 · 可追溯地改判</span></header><main><div class="eyebrow">REVIEW RECORD / 结论记录</div><h1>每一种错误，交给对应环节检查。</h1><p class="intro">双向审查可以挑战结论，裁决负责明确判断。最终保留的不是最强的语气，而是当前证据能够支持的最清楚的表述。</p><aside class="notice">''' + notice + '''</aside><div class="flow"><div class="step"><b>01 / FREEZE</b><span>初稿与结论台账</span></div><div class="step"><b>02 / PARALLEL</b><span>夸大审查</span></div><div class="step"><b>03 / PARALLEL</b><span>低估与防御审查</span></div><div class="step"><b>04 / ADJUDICATE</b><span>逐条裁决</span></div><div class="step"><b>05 / TRACE</b><span>来源核对与导出</span></div></div><div class="toolbar" role="group" aria-label="按判定筛选"><button data-filter="all" aria-pressed="true">全部结论</button><button data-filter="supported" aria-pressed="false">支持</button><button data-filter="partially_supported" aria-pressed="false">条件性支持</button><button data-filter="insufficient_evidence" aria-pressed="false">证据不足</button></div><div id="claims">''' + ''.join(cards) + '''</div><section class="audit"><h2>Non-blocking Advisory / 非强制性反低估审计提示</h2><p>以下对称性审计提示均为非强制参考（non_blocking=true），不会阻断双审、裁决或导出。</p>''' + sym_html + '''<details><summary>派生证据谱系与分窗摘录（Evidence Lineage &amp; Excerpt Windows）</summary>''' + lineage_html + '''</details></section><section class="audit"><h2>来源核对与审查边界</h2><p>''' + review_boundary + '''</p><details><summary>查看完整来源核对记录</summary><pre>''' + audit + '''</pre></details><details><summary>查看原始初稿</summary><p>''' + text(data['draft']) + '''</p></details></section><footer>Case ''' + text(data['case_id']) + ''' · Parrhesia ''' + text(__version__) + ''' pilot<br>报告由裁决记录生成。需要挑战或更改结论时，返回宿主中的持久案例；本页面不修改案例状态。</footer></main><script>document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('.claim').forEach(card=>{card.hidden=button.dataset.filter!=='all'&&card.dataset.verdict!==button.dataset.filter;});}));</script></body></html>'''
    with target.open("x", encoding="utf-8") as stream:
        stream.write(html)


def escape_markdown(value) -> str:
    """Render submitted strings literally; no executable HTML or remote image embeds."""
    text_val = str(value).replace("\r\n", "\n").replace("\r", "\n")
    for char in "\\`*_{}[]<>()!#|":
        text_val = text_val.replace(char, "\\" + char)
    return text_val.replace("\n", "  \n")


def structured_markdown(value, path: str = "") -> list[str]:
    """Flatten structured records as escaped, readable key/value rows."""
    rows = ["| Field | Value |", "|---|---|"] if not path else []
    if isinstance(value, dict):
        for key, child in value.items():
            rows.extend(structured_markdown(child, f"{path}.{key}" if path else key))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            rows.extend(structured_markdown(child, f"{path}[{index}]"))
    else:
        rows.append(f"| {escape_markdown(path)} | {escape_markdown(value)} |")
    return rows


def render_markdown_report(
    case: dict,
    verification: dict,
    *,
    integrity_boundary: str,
    packet_text_bytes: int,
) -> str:
    """Render an adjudicated workspace case into a traceable Markdown report."""
    lines = [
        "# Parrhesia adjudicated report", "", f"Case: {escape_markdown(case['case_id'])}", "",
        f"Question: {escape_markdown(case['question'])}", "",
        f"Revision: `{case['revision_id']}` · Input SHA-256: `{case['input_digest']}`", "",
        f"Content integrity / traceability: **{verification['status']}** (checked {escape_markdown(verification['checked_at'])}).", "",
        f"SQLite event chain: **{verification.get('event_chain_status', 'unknown')}** (events={(verification.get('event_chain') or {}).get('event_count', 0)}, broken={(verification.get('event_chain') or {}).get('broken_sequences', [])}).", "",
        f"**Evidence boundary:** {integrity_boundary}", "",
        "Review separation is packet-level and context identities are caller-reported. Scientific validity: **not established by this engine**.", "",
        "## Final decisions", "",
    ]
    claims = {claim["id"]: claim for claim in case["claims"]}
    lines[0:0] = ["[L2]", ""]
    lines.extend([f"Mechanical gates: {'gate_version=1; blind=' + str(case['blind']) if gated(case) else 'LEGACY_UNGATED — not certified against current gates'}", ""])
    if case.get("prior_case_ids") or case.get("supersedes_case_id") or case.get("case_relation"):
        lines.extend([
            "Longitudinal case lineage (registrant-reported):",
            f"- prior_case_ids: {', '.join(escape_markdown(p) for p in (case.get('prior_case_ids') or ())) or 'none'}; "
            f"case_relation: {escape_markdown(case.get('case_relation') or 'not supplied')}; "
            f"supersedes_case_id: {escape_markdown(case.get('supersedes_case_id') or 'none')}.",
            "",
        ])
    trig_by_claim = {
        te["claim_id"]: te
        for te in ((verification.get("trigger_evaluation") or {}).get("claim_evaluations") or ())
    }
    cal_outcomes = case.get("calibration_outcomes") or []
    for decision in case["adjudication"]["decisions"]:
        claim = claims[decision["claim_id"]]
        lines.extend([
            f"### {escape_markdown(claim['id'])}: {decision['verdict']} / {escape_markdown(describe(decision))}", "",
            f"Original claim ({escape_markdown(describe(claim))}): {escape_markdown(claim['text'])}", "",
            "Revised claim (the verdict below evaluates this wording):", "",
            escape_markdown(decision["revised_text"]), "",
            f"Judgment: {decision['verdict']}. Reason: {escape_markdown(decision['rationale'])}", "",
            f"Confidence: {decision['confidence']} — {escape_markdown(decision['confidence_reason'])}", "",
        ])
        if "forecast_probability" in decision:
            lines.extend([f"Forecast probability: {decision['forecast_probability']}", ""])
        lines.extend([
            f"Boundary: {escape_markdown(decision['boundary'])}", "",
            f"Change this judgment if: {escape_markdown(decision['reversal_condition'])}", "",
        ])
        if "condition" in decision:
            lines.extend([f"Condition: {escape_markdown(decision['condition'])}", ""])
        if "actionable_stance" in decision:
            lines.extend([f"Actionable stance: `{decision['actionable_stance']}`", ""])
        if "abstention_justification" in decision:
            lines.extend(["Abstention / downgrade justification:", ""])
            lines.extend(structured_markdown(decision["abstention_justification"]))
            lines.append("")
        if "evidence_dominance" in decision:
            lines.extend(["Evidence dominance assessment:", ""])
            lines.extend(structured_markdown(decision["evidence_dominance"]))
            lines.append("")
        if gated(case):
            lines.extend([f"Claim basis: {decision['claim_basis']} (original: {claim['claim_basis']}); labels are registrant-reported.", ""])
            lines.extend(structured_markdown({"check_ceiling": ceiling(claim, decision["claim_type"])}))
            lines.append("")
        if case.get("schema_version", 1) == 2:
            for key in ("design_packages", "statistical_report", "causal_basis", "provenance_cards", "effect_records", "prior_claim_links", "reversal_triggers"):
                if key in claim:
                    lines.extend([f"{key} (registrant-reported, not verified by the engine):", ""])
                    lines.extend(structured_markdown(claim[key]))
                    lines.append("")
            if "reversal_triggers" in decision:
                lines.extend(["decision.reversal_triggers (adjudicator-reported):", ""])
                lines.extend(structured_markdown(decision["reversal_triggers"]))
                lines.append("")
            eff_check = (verification.get("effect_checks") or {}).get(claim["id"])
            if eff_check:
                lines.extend(["effect_checks (computable verification):", ""])
                lines.extend(structured_markdown(eff_check))
                lines.append("")
            trig_eval = trig_by_claim.get(claim["id"])
            if trig_eval:
                lines.extend(["trigger_evaluation (computable verification):", ""])
                lines.extend(structured_markdown(trig_eval))
                lines.append("")
            claim_cal = [co for co in cal_outcomes if co.get("claim_id") == claim["id"]]
            if claim_cal:
                lines.extend(["calibration_outcomes (post-adjudication records):", ""])
                lines.extend(structured_markdown(claim_cal))
                lines.append("")
        lines.extend([
            f"Evidence cited: {', '.join(escape_markdown(item) for item in decision['evidence_ids']) or 'NONE — explicit evidence gap'}", "",
            f"Original ledger estimate: {escape_markdown(claim['effect']['estimate'])}. Uncertainty: {escape_markdown(claim['effect']['uncertainty'])}", "",
            f"Original scope: {escape_markdown(claim['scope'])}", "",
            f"Origin: {claim['origin']} (hypothesis: {escape_markdown(claim.get('hypothesis_id') or 'not supplied')}; historical timing is not certified).", "",
            f"Ledger contribution (registrant assessment): {escape_markdown(claim['contribution'])}", "",
        ])
        if claim.get("best_current_explanation"):
            lines.extend([f"Best current explanation: {escape_markdown(claim['best_current_explanation'])}", ""])
        if claim.get("discriminating_test"):
            lines.extend([f"Discriminating test: {escape_markdown(claim['discriminating_test'])}", ""])
        lines.extend(["Alternative explanations:", ""])
        for alternative in claim["alternatives"]:
            lines.append(f"- {escape_markdown(alternative['explanation'])}: {alternative['status']} — {escape_markdown(alternative['reason'])}")
        if not claim["alternatives"]:
            lines.append("None registered (general engineering claim).")
        lines.extend(["", "Scientific checks (caller-reported; fail/unknown remain visible):", ""])
        for name in CHECK_NAMES:
            check = claim["checks"][name]
            lines.append(f"- {name}: **{check['status']}** — {escape_markdown(check['reason'])}")
        lines.append("")
    lines.extend(["## Review findings and adjudicator dispositions", ""])
    findings = {finding["id"]: (role, finding) for role, review in case["reviews"].items() for finding in review["findings"]}
    if not findings:
        lines.extend(["Both reviewers submitted complete claim coverage with no findings. This is not an independent validation certificate.", ""])
    for disposition in case["adjudication"]["dispositions"]:
        role, finding = findings[disposition["finding_id"]]
        lines.extend([
            f"- {escape_markdown(finding['id'])} ({role}, {escape_markdown(finding['claim_id'])}): **{disposition['disposition']}** — {escape_markdown(disposition['reason'])}",
            f"  Issue: {escape_markdown(finding['issue'])}. Decision impact: {escape_markdown(finding['decision_impact'])}",
            f"  Proposed wording ({escape_markdown(describe(finding, 'proposed_', 'proposed_scope'))}): {escape_markdown(finding['proposed_text'])}",
        ])
        if "condition" in disposition:
            lines.append(f"  Condition: {escape_markdown(disposition['condition'])}")
        if gated(case):
            lines.append("")
            lines.extend(structured_markdown({key: disposition[key] for key in ("claim_id", "resolution", "revised_text_quote", "disagreement") if key in disposition}))
            lines.append("")
    lines.extend(["", "## Source snapshots and verification", ""])
    by_id = {entry["evidence_id"]: entry for entry in verification["evidence"]}
    for evidence in case["evidence"]:
        status = by_id[evidence["evidence_id"]]
        lines.extend([
            f"- {escape_markdown(evidence['evidence_id'])}: {escape_markdown(evidence['label'])}; provenance **{evidence['provenance']}** (registrant-reported).",
            f"  Path: {escape_markdown(evidence['path'])}; SHA-256 `{evidence['sha256']}`; captured {escape_markdown(evidence['captured_at'])}.",
            f"  Snapshot: {status['snapshot_status']}; current file: {status['file_status']}; quote anchor: {status['anchor_status']}; traceability: **{status['status']}**.",
        ])
        if evidence["quote"]:
            lines.append(f"  Exact registered quote: {escape_markdown(evidence['quote'])}")
        if evidence["location"]:
            lines.append(f"  Reported location (not parsed): {escape_markdown(evidence['location'])}")
        if gated(case):
            lines.append(f"  Kind: {evidence['kind']}; source_text_status: {status['source_text_status']}; unread_content_ack: {evidence['unread_content_ack']}.")
        if evidence.get("derived_from_evidence_ids") or status.get("lineage_status", "not_derived") != "not_derived":
            lines.append(
                f"  Derived lineage: status={status.get('lineage_status', 'not_derived')}; "
                f"parents={', '.join(escape_markdown(p) for p in evidence.get('derived_from_evidence_ids') or ()) or 'NONE'}; "
                f"step={escape_markdown(evidence.get('derivation_step') or '')}."
            )
        if status.get("excerpt_window_count"):
            lines.append(f"  Chunked excerpt windows: {status['excerpt_window_count']} window(s) (budget <= {packet_text_bytes} UTF-8 bytes).")
            for win in status.get("excerpt_windows") or ():
                lines.append(
                    f"    - window {win['index']} [{','.join(win['roles'])}]: chars {win['start_char']}-{win['end_char']}, "
                    f"lines {win['start_line']}-{win['end_line']}, sha256=`{win['text_sha256'][:12]}`"
                )
    if not case["evidence"]:
        lines.append("No sources registered; evidence remains explicitly unverified.")
    if verification.get("evidence_chains"):
        lines.extend(["", "### Derived evidence chains", ""])
        for chain in verification["evidence_chains"]:
            lines.append(
                f"- {escape_markdown(chain['evidence_id'])} <- [{', '.join(escape_markdown(p) for p in chain['derived_from_evidence_ids'])}]: "
                f"**{chain['lineage_status']}** (ancestors={', '.join(escape_markdown(a) for a in chain['ancestors']) or 'none'}; "
                f"step={escape_markdown(chain.get('derivation_step') or '')})."
            )
    lines.extend(["", "## Hypothesis log", ""])
    for hypothesis in case["hypotheses"]:
        lines.append(f"- {escape_markdown(hypothesis['hypothesis_id'])}: {escape_markdown(hypothesis['statement'])}; logged {escape_markdown(hypothesis['recorded_at'])}; timing {hypothesis['timing_basis']}; source {escape_markdown(hypothesis['source_evidence_id'] or 'not supplied')}.")
    if not case["hypotheses"]:
        lines.append("No hypothesis timing records supplied.")
    lines.extend(["", "## Review provenance (caller-reported)", ""])
    for role in ROLES:
        review = case["reviews"][role]
        lines.append(f"- {role}: context {escape_markdown(review['reviewer']['context_id'])}; model {escape_markdown(review['reviewer']['model'])}; {review['review_status']}; {len(review['covered_claim_ids'])} claims covered.")
        if gated(case):
            att = review.get("isolation_attestation") or {}
            manifest = {
                "packet_id": review["packet_id"],
                "input_digest": review["input_digest"],
                "blind": case["blind"],
                "covered_claim_ids": review["covered_claim_ids"],
                "registered_evidence_ids": [e["evidence_id"] for e in case["evidence"]],
                "unread_evidence_ids": review["unread_evidence_ids"],
                "history_inheritance": att.get("history_inheritance", "UNKNOWN"),
                "memory_access": att.get("memory_access", "UNKNOWN"),
                "host_surface": att.get("host_surface", "UNKNOWN"),
            }
            if isinstance(review.get("isolation_grade"), dict) and review["isolation_grade"].get("grade"):
                manifest["isolation_grade"] = review["isolation_grade"]["grade"]
                if isinstance(review["isolation_grade"].get("boundaries"), dict):
                    manifest["isolation_boundaries"] = review["isolation_grade"]["boundaries"]
            if isinstance(review.get("isolation_receipt"), dict):
                rec = review["isolation_receipt"]
                manifest["runner_seal_verified"] = bool(rec.get("runner_seal_verified", False))
                if rec.get("transcript_sha256"):
                    manifest["transcript_sha256"] = rec["transcript_sha256"]
                for bkey in ("env_scrubbed", "isolated_cwd", "two_stage_blind", "workspace_untouched"):
                    if bkey in rec:
                        manifest[bkey] = bool(rec[bkey])
                for skey in ("stage1_estimate_sha256", "stage1_transcript_sha256", "os_sandbox"):
                    if rec.get(skey):
                        manifest[skey] = rec[skey]
            lines.append("")
            lines.extend(structured_markdown({
                "input_manifest": manifest,
                "claim_stances": review["claim_stances"],
                "unread_evidence_ids": review["unread_evidence_ids"],
            }))
            lines.append("")
    if gated(case):
        adj_att = case["adjudication"].get("isolation_attestation") or {}
        adj_manifest = {
            "history_inheritance": adj_att.get("history_inheritance", "UNKNOWN"),
            "memory_access": adj_att.get("memory_access", "UNKNOWN"),
            "host_surface": adj_att.get("host_surface", "UNKNOWN"),
        }
        adj_payload: dict = {
            "adjudication_unread_evidence_ids": case["adjudication"]["unread_evidence_ids"],
            "adjudication_isolation_attestation": adj_manifest,
        }
        adj_iso_extra: dict = {}
        if isinstance(case["adjudication"].get("isolation_grade"), dict) and case["adjudication"]["isolation_grade"].get("grade"):
            adj_iso_extra["isolation_grade"] = case["adjudication"]["isolation_grade"]["grade"]
            adj_iso_extra["isolation_basis"] = case["adjudication"]["isolation_grade"].get("basis", "UNKNOWN")
            if isinstance(case["adjudication"]["isolation_grade"].get("boundaries"), dict):
                adj_iso_extra["isolation_boundaries"] = case["adjudication"]["isolation_grade"]["boundaries"]
        if isinstance(case["adjudication"].get("isolation_receipt"), dict):
            arec = case["adjudication"]["isolation_receipt"]
            adj_iso_extra["runner_seal_verified"] = bool(arec.get("runner_seal_verified", False))
            if arec.get("transcript_sha256"):
                adj_iso_extra["transcript_sha256"] = arec["transcript_sha256"]
            for bkey in ("env_scrubbed", "isolated_cwd", "two_stage_blind", "workspace_untouched"):
                if bkey in arec:
                    adj_iso_extra[bkey] = bool(arec[bkey])
            for skey in ("stage1_estimate_sha256", "stage1_transcript_sha256", "os_sandbox"):
                if arec.get(skey):
                    adj_iso_extra[skey] = arec[skey]
        if adj_iso_extra:
            adj_payload["adjudication_isolation_grade"] = adj_iso_extra
        lines.extend(structured_markdown(adj_payload))
        lines.append("")
    adjudicator = case["adjudication"]["adjudicator"]
    lines.append(f"- Adjudicator: context {escape_markdown(adjudicator['context_id'])}; model {escape_markdown(adjudicator['model'])}.")
    if case["writer_context_id"] is None:
        lines.append("- Writer context was not supplied; reviewer separation from the writer is UNKNOWN.")
    sym = verification.get("symmetry_audit") or case.get("symmetry_audit") or {
        "non_blocking": True, "severity": "advisory", "flag_count": 0, "flags": [],
        "lexical_advisory_count": 0, "lexical_advisories": [],
    }
    lines.extend([
        "",
        "## Non-blocking Advisory / 非强制性反低估审计提示",
        "",
        "Advisory symmetry audit flags below are strictly non-blocking (`non_blocking=true`, `severity=advisory`) and never block review, adjudication, or export.",
        "",
    ])
    if not sym.get("flags"):
        lines.append("- No underclaim or false-abstention advisory flags emitted (`flag_count=0`).")
    else:
        for flag in sym["flags"]:
            lines.append(
                f"- [{escape_markdown(flag['hook_code'])}] {escape_markdown(flag['claim_id'])}: "
                f"observed={escape_markdown(flag.get('observed_verdict'))}; "
                f"candidate={escape_markdown(flag.get('advisory_candidate_verdict') or 'n/a')}/{escape_markdown(flag.get('advisory_candidate_level') or 'n/a')} — "
                f"{escape_markdown(flag['message'])}"
            )
    lex_advisories = sym.get("lexical_advisories") or []
    if not lex_advisories:
        lines.append("- No non-blocking lexical cue advisories emitted (`lexical_advisory_count=0`).")
    else:
        for adv in lex_advisories:
            detail = f" ({escape_markdown(adv['detail_code'])})" if adv.get("detail_code") else ""
            lines.append(
                f"- [{escape_markdown(adv['hook_code'])}{detail}] {escape_markdown(adv.get('claim_id'))}: "
                f"{escape_markdown(adv['message'])}"
            )
    lines.extend(["", "## Reported human decisions", ""])
    for event in case["human_decisions"]:
        lines.append(f"- {escape_markdown(event['recorded_at'])}: {event['decision']} by {escape_markdown(event['responsible_human'])} — {escape_markdown(event['reason'])} (caller-reported identity).")
    if not case["human_decisions"]:
        lines.append("No human acceptance has been recorded.")
    lines.extend(["", "Human acceptance, if reported, does not certify scientific validity. This is a local pilot artifact, not evidence of changed Grok behavior.", ""])
    return "\n".join(lines)


def _synthesis_forest_svg(ms: dict) -> str:
    """Render a deterministic offline SVG forest plot for one metric_syntheses group."""
    scale = ms.get("scale", "linear")
    studies = ms.get("studies") or []
    meta = ms.get("meta_analysis")
    if not studies:
        return ""
    null_val = float(studies[0].get("null_value", 1.0 if scale == "log" else 0.0))

    def _tx(v: float) -> float:
        return math.log(v) if scale == "log" else float(v)

    x_null = _tx(null_val)
    rows_plot: list[tuple[str, float, float, float, str, bool]] = []
    xs: list[float] = [x_null]
    for st in studies:
        est, lo, hi = float(st["estimate"]), float(st["ci_low"]), float(st["ci_high"])
        rows_plot.append((
            f"{st['case_id']} · {st['claim_id']}",
            _tx(est),
            _tx(lo),
            _tx(hi),
            f"{est:.3f} [{lo:.3f}, {hi:.3f}]",
            False,
        ))
        xs.extend([_tx(lo), _tx(hi)])
    if isinstance(meta, dict) and isinstance(meta.get("random_effects"), dict):
        re_b = meta["random_effects"]
        est, lo, hi = float(re_b["estimate"]), float(re_b["ci_low"]), float(re_b["ci_high"])
        rows_plot.append((
            f"Pooled RE (DL, I²={meta.get('i2_percent', 0.0):.1f}%)",
            _tx(est),
            _tx(lo),
            _tx(hi),
            f"{est:.3f} [{lo:.3f}, {hi:.3f}]",
            True,
        ))
        xs.extend([_tx(lo), _tx(hi)])
        pi_lo = meta.get("prediction_interval_low")
        pi_hi = meta.get("prediction_interval_high")
        if isinstance(pi_lo, (int, float)) and isinstance(pi_hi, (int, float)):
            xs.extend([_tx(float(pi_lo)), _tx(float(pi_hi))])

    lo_x, hi_x = min(xs), max(xs)
    span = hi_x - lo_x
    if span <= 1e-9:
        span = 1.0
        lo_x -= 0.5
        hi_x += 0.5
    pad = span * 0.12
    lo_x -= pad
    hi_x += pad
    span = hi_x - lo_x

    plot_left, plot_right = 240.0, 560.0
    text_right = 576.0
    row_h = 28
    top_pad = 24
    height = top_pad + len(rows_plot) * row_h + 36

    def _px(xval: float) -> float:
        return plot_left + ((xval - lo_x) / span) * (plot_right - plot_left)

    svg = [
        f'<svg viewBox="0 0 760 {height}" width="100%" role="img" aria-label="Forest plot for {text(ms.get("metric"))}">',
        '<rect x="0" y="0" width="760" height="' + str(height) + '" fill="#fcfdf9" stroke="#d8dfd8"/>',
    ]
    null_px = _px(x_null)
    svg.append(
        f'<line x1="{null_px:.1f}" y1="16" x2="{null_px:.1f}" y2="{height - 24}" '
        f'stroke="#8c6d46" stroke-width="1.5" stroke-dasharray="4,4"/>'
    )
    svg.append(
        f'<text x="{null_px:.1f}" y="{height - 8}" font-size="11" text-anchor="middle" fill="#6b5638">'
        f'Null ({text(f"{null_val:g}")})</text>'
    )
    for idx, (label, est_x, lo_val_x, hi_val_x, fmt_val, is_pooled) in enumerate(rows_plot):
        cy = top_pad + idx * row_h + 12
        x1, xm, x2 = _px(lo_val_x), _px(est_x), _px(hi_val_x)
        short_lbl = label if len(label) <= 32 else label[:29] + "..."
        weight_style = ' font-weight="700"' if is_pooled else ""
        color = "#1b5e4c" if is_pooled else "#2a4742"
        svg.append(f'<text x="14" y="{cy + 4}" font-size="12" fill="#173331"{weight_style}>{text(short_lbl)}</text>')
        if is_pooled:
            svg.append(
                f'<polygon points="{x1:.1f},{cy} {xm:.1f},{cy - 7} {x2:.1f},{cy} {xm:.1f},{cy + 7}" '
                f'fill="{color}" opacity="0.88"/>'
            )
        else:
            svg.append(f'<line x1="{x1:.1f}" y1="{cy}" x2="{x2:.1f}" y2="{cy}" stroke="{color}" stroke-width="2"/>')
            svg.append(f'<rect x="{xm - 4:.1f}" y="{cy - 4}" width="8" height="8" fill="{color}"/>')
        svg.append(
            f'<text x="{text_right:.1f}" y="{cy + 4}" font-size="11.5" font-family="ui-monospace,monospace" '
            f'fill="#173331"{weight_style}>{text(fmt_val)}</text>'
        )
    svg.append("</svg>")
    return "".join(svg)


def render_synthesis_report(
    workspace: str | Path,
    output: str | None = None,
    *,
    case_id: str | None = None,
    claim_id: str | None = None,
    metric: str | None = None,
    alpha: float = 0.05,
    ci_level: float = 0.95,
) -> dict:
    """Compute a strictly read-only Living Evidence Synthesis and optionally render offline HTML."""
    from .core import Engine
    from .storage import safe_workspace_path
    from .synthesis import synthesize_claim_lineage

    for nm, val in (("alpha", alpha), ("ci_level", ci_level)):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not (0.0 < float(val) < 1.0):
            fail("invalid_value", f"{nm} must lie in (0, 1)")

    cases = Engine.read_workspace_cases_snapshot(workspace)
    root = Path(workspace).resolve(strict=True)
    syn = synthesize_claim_lineage(
        cases,
        case_id=case_id,
        claim_id=claim_id,
        metric_filter=metric,
        alpha=float(alpha),
        ci_level=float(ci_level),
    )
    if output is None:
        return {**syn, "case_mutated": False}

    target = safe_workspace_path(root, output)
    if target.suffix.lower() not in (".html", ".htm"):
        fail("invalid_value", "Synthesis output must be a workspace-relative .html or .htm path")
    if target.exists():
        fail("export_exists", "Synthesis output already exists; choose a new path")

    metric_blocks = []
    for ms in syn.get("metric_syntheses") or ():
        meta = ms.get("meta_analysis")
        svg_plot = _synthesis_forest_svg(ms)
        if isinstance(meta, dict):
            re_b = meta["random_effects"]
            fe_b = meta["fixed_effect"]
            coverage = f"{100 * meta['ci_level']:g}%"
            pi_lo = meta.get("prediction_interval_low")
            pi_hi = meta.get("prediction_interval_high")
            pi_str = (
                f"[{pi_lo:.3f}, {pi_hi:.3f}] (crosses_null={meta.get('prediction_interval_crosses_null')})"
                if isinstance(pi_lo, (int, float)) and isinstance(pi_hi, (int, float))
                else "n/a (k < 3)"
            )
            re_est = f"{re_b['estimate']:.4f}"
            re_lo = f"{re_b['ci_low']:.4f}"
            re_hi = f"{re_b['ci_high']:.4f}"
            re_p = f"{re_b['p_value']:.4g}"
            fe_est = f"{fe_b['estimate']:.4f}"
            q_str = f"{meta['cochran_q']:.3f}"
            i2_str = f"{meta['i2_percent']:.1f}"
            tau2_str = f"{meta['tau2']:.4f}"
            meta_html = (
                f"<p><strong>Random-effects (DL):</strong> {text(re_est)} "
                f"({text(coverage)} CI [{text(re_lo)}, {text(re_hi)}], p={text(re_p)}) · "
                f"<strong>Fixed-effect (IV):</strong> {text(fe_est)} · "
                f"<strong>Q={text(q_str)}</strong>, <strong>I²={text(i2_str)}%</strong>, "
                f"<strong>τ²={text(tau2_str)}</strong> · "
                f"<strong>{text(coverage)} Prediction Interval:</strong> {text(pi_str)}</p>"
            )
        else:
            meta_html = "<p>Single independent study — meta-analysis requires at least 2 independent cases.</p>"
        cum_tr_parts: list[str] = []
        for step in ms.get("cumulative_trajectory") or ():
            s_est = f"{step['estimate']:.4f}"
            s_lo = f"{step['ci_low']:.4f}"
            s_hi = f"{step['ci_high']:.4f}"
            s_i2 = f"{step.get('i2_percent', 0.0):.1f}"
            s_coverage = f"{100 * step['ci_level']:g}%"
            cum_tr_parts.append(
                f"<tr><td>{text(step['step'])}</td><td>{text(step['added_case_id'])}</td><td>{text(step['k_studies'])}</td>"
                f"<td>{text(s_est)} [{text(s_lo)}, {text(s_hi)}] ({text(s_coverage)})</td>"
                f"<td>{text(s_i2)}%</td></tr>"
            )
        cum_rows = "".join(cum_tr_parts)
        metric_blocks.append(
            f'<article class="card"><div class="card-top"><h2>{text(ms["endpoint"])} · {text(ms["metric"])} ({text(ms["scale"])} scale)</h2>'
            f'<span class="pill">{text(ms["trajectory_pattern"])}</span></div>'
            f'{meta_html}<div class="svg-wrap">{svg_plot}</div>'
            f'<details open><summary>Chronological Cumulative Pooling Trajectory</summary>'
            f'<table><thead><tr><th>Step</th><th>Added Case</th><th>k</th><th>Cumulative Est [CI]</th><th>I²</th></tr></thead>'
            f'<tbody>{cum_rows}</tbody></table></details></article>'
        )
    if not metric_blocks:
        metric_blocks.append('<article class="card"><p>No eligible pooled empirical effect metrics matched the scope filter.</p></article>')

    dedup = syn.get("deduplication_guard") or {}
    dedup_rows = []
    for key_lbl, grp in (
        ("non_independent", dedup.get("excluded_non_independent") or ()),
        ("suspected_cohort_overlap", dedup.get("suspected_cohort_overlaps") or ()),
        ("synthetic", dedup.get("excluded_synthetic") or ()),
        ("non_effective", dedup.get("excluded_non_effective") or ()),
        ("ineligible_comparison", syn.get("excluded_ineligible") or ()),
    ):
        for entry in grp:
            overlap_ref = (
                entry.get("overlapping_prior_case_id")
                or entry.get("suspected_prior_case_id")
                or entry.get("case_relation")
                or entry.get("state")
                or "—"
            )
            reason_txt = entry.get("reason") or entry.get("detail") or entry.get("record_id") or key_lbl
            dedup_rows.append(
                f"<tr><td>{text(key_lbl)}</td><td>{text(entry.get('case_id'))}</td>"
                f"<td>{text(overlap_ref)}</td>"
                f"<td>{text(reason_txt)}</td></tr>"
            )
    dedup_html = (
        '<table><thead><tr><th>Category</th><th>Case</th><th>Overlap / Relation</th><th>Reason</th></tr></thead><tbody>'
        + "".join(dedup_rows) + "</tbody></table>"
        if dedup_rows
        else "<p>No cases or records excluded by the deduplication guard.</p>"
    )

    trig_list = syn.get("triggered_ancestors") or ()
    trig_html = (
        '<table><thead><tr><th>Ancestor</th><th>Trigger</th><th>Fired By</th><th>Target Verdict</th><th>Detail</th></tr></thead><tbody>'
        + "".join(
            f"<tr><td>{text(t['ancestor_case_id'])}:{text(t['ancestor_claim_id'])}</td><td>{text(t['trigger_id'])} ({text(t['trigger_kind'])})</td>"
            f"<td>{text(t['fired_by'])} {text(t.get('source_case_id') or '')}</td><td>{text(t['target_verdict'])}</td><td>{text(t.get('detail') or '')}</td></tr>"
            for t in trig_list
        )
        + "</tbody></table>"
        if trig_list
        else "<p>No ancestor reversal triggers fired.</p>"
    )

    act_html = (
        "<ul>"
        + "".join(
            f"<li><strong>[{text(a['priority'])}] {text(a['action_kind'])}</strong>: {text(a['reason'])} — {text(a['decision_impact'])}</li>"
            for a in (syn.get("living_next_actions") or ())
        )
        + "</ul>"
        if syn.get("living_next_actions")
        else "<p>No additional living synthesis actions recommended.</p>"
    )

    rendered_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw_json = text(json.dumps(syn, ensure_ascii=False, indent=2))
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<title>Parrhesia · Living Evidence Synthesis</title><style>'
        ':root{--ink:#173331;--muted:#596b68;--line:#d8dfd8;--paper:#f4f5ee;--accent:#1b5e4c}*{box-sizing:border-box}'
        'body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}'
        'header{border-bottom:1px solid var(--line);padding:20px 5vw;display:flex;justify-content:space-between;align-items:center}'
        'header strong{font:600 24px Georgia,serif}main{max-width:1100px;margin:auto;padding:36px 24px 64px}'
        '.notice{border:1px solid #d3bc87;background:#fff5d9;padding:14px 18px;border-radius:10px;margin:18px 0}'
        '.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}'
        '.kpi{background:#fffef9;border:1px solid var(--line);border-radius:10px;padding:12px 14px}'
        '.kpi b{display:block;font-size:12px;color:var(--muted)}.kpi span{font-size:18px;font-weight:600}'
        '.card{background:#fffef9;border:1px solid var(--line);border-radius:14px;padding:22px 24px;margin:18px 0}'
        '.card-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}'
        '.pill{background:#e1ece6;color:var(--accent);padding:3px 10px;border-radius:14px;font-size:12px;font-weight:600}'
        '.svg-wrap{margin:14px 0;overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}'
        'th,td{border-bottom:1px solid var(--line);text-align:left;padding:7px 8px;vertical-align:top}'
        'pre{font:12px/1.6 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#edf0e9;padding:14px;border-radius:8px}'
        '</style></head><body><header><strong>Parrhesia<span style="color:#688e76">.</span></strong>'
        '<span>Living Evidence Synthesis / 活体跨案综合（只读快照）</span></header><main>'
        '<h1>Living Cross-Case Evidence Synthesis</h1>'
        f'<aside class="notice"><strong>Read-Only Diagnostic Snapshot</strong> · 生成时间：{text(rendered_at)} · '
        f'scientific_validity={text(syn["scientific_validity"])} · 不篡改任何已冻结历史案例或摘要。</aside>'
        '<div class="kpis">'
        f'<div class="kpi"><b>Living Status</b><span>{text(syn["living_status"])}</span></div>'
        f'<div class="kpi"><b>Scoped Cases</b><span>{text(syn["scoped_case_count"])}</span></div>'
        f'<div class="kpi"><b>Independent Pooled Cases</b><span>{text(syn["independent_pooled_case_count"])}</span></div>'
        f'<div class="kpi"><b>Fired Ancestor Triggers</b><span>{text(syn["triggered_ancestor_count"])}</span></div>'
        f'<div class="kpi"><b>Excluded Non-Independent</b><span>{text(dedup.get("excluded_non_independent_count", 0))}</span></div>'
        f'<div class="kpi"><b>Suspected Cohort Overlaps</b><span>{text(dedup.get("suspected_cohort_overlap_count", 0))}</span></div>'
        '</div>'
        + "".join(metric_blocks)
        + '<section class="card"><h2>3-Layer Cohort Deduplication &amp; Independence Guard</h2>' + dedup_html + '</section>'
        + '<section class="card"><h2>Ancestor Reversal-Trigger Cascade</h2>' + trig_html + '</section>'
        + '<section class="card"><h2>Living Next Actions</h2>' + act_html + '</section>'
        + f'<section class="card"><details><summary>Raw Synthesis Snapshot JSON</summary><pre>{raw_json}</pre></details></section>'
        + f'<footer>Parrhesia {text(__version__)} · Read-only workspace synthesis.</footer></main></body></html>'
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(html)
    return {
        "path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "living_status": syn["living_status"],
        "independent_pooled_case_count": syn["independent_pooled_case_count"],
        "triggered_ancestor_count": syn["triggered_ancestor_count"],
        "case_mutated": False,
        "synthesis": syn,
    }
