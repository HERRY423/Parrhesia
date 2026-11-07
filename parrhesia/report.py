"""Offline, read-only review report. All caller text is HTML-escaped."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
from . import __version__
from .claims import describe
from .gates import ceiling


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


def render_report(data: dict, target: Path) -> None:
    cards = []
    dispositions = {item["finding_id"]: item for item in data["dispositions"]}
    claims = {item["id"]: item for item in data["claims"]}
    for item in data["decisions"]:
        claim = claims[item["claim_id"]]
        reviews = []
        for role, review in data.get("reviews", {}).items():
            for stance in review.get("claim_stances", []):
                if stance["claim_id"] == item["claim_id"]:
                    reviews.append('<div class="finding"><span>' + text(role) + ' · 原命题立场</span><table>' + ''.join(structured(stance)) + '</table></div>')
        for role, findings in data["findings"].items():
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
        for key in ('design_packages', 'statistical_report', 'causal_basis', 'provenance_cards'):
            if key in claim:
                claim_details[key] = claim[key]
        if claim.get('best_current_explanation'):
            claim_details['best_current_explanation'] = claim['best_current_explanation']
        if claim.get('discriminating_test'):
            claim_details['discriminating_test'] = claim['discriminating_test']
        basis_label = ' · ' + text(item['claim_basis']) if 'claim_basis' in item else ''
        cards.append(f'''<article class="claim" data-verdict="{text(item['verdict'])}">
          <div class="claim-top"><span class="id">{text(item['claim_id'])}</span><span class="badge {text(item['verdict'])}">{LABELS[item['verdict']]}</span><span class="level">{text(describe(item))}{basis_label}</span></div>
          <h2>{text(item['revised_text'])}</h2><p class="original">原主张：{text(claim['text'])}</p>
          <dl><dt>判断依据</dt><dd>{text(item['rationale'])}</dd>{condition}<dt>成立边界</dt><dd>{text(item['boundary'])}</dd><dt>改判条件</dt><dd>{text(item['reversal_condition'])}</dd></dl>
          <details><summary>审查意见与裁决理由</summary>{''.join(reviews)}<p>置信度：{text(item['confidence'])} · {text(item['confidence_reason'])}</p></details>
          <details><summary>原主张分类、设计、统计报告与溯源卡（提交者记录）</summary><p>{text(describe(claim))}</p><table>{''.join(structured(claim_details))}</table></details>
        </article>''')
    input_manifests = {
        role: {
            "packet_id": rev.get("packet_id", "UNKNOWN"),
            "input_digest": rev.get("input_digest", "UNKNOWN"),
            "blind": data.get("blind", "UNKNOWN"),
            "covered_claim_ids": rev.get("covered_claim_ids", []),
            "unread_evidence_ids": rev.get("unread_evidence_ids", []),
            "history_inheritance": "none_role_packet_only",
            "memory_access": "disabled_or_not_used_caller_reported",
        }
        for role, rev in data.get("reviews", {}).items()
    }
    audit = text(json.dumps({"verification": data["verification"], "export": data["export"], "gate_version": data.get("gate_version", "LEGACY_OR_NOT_SUPPLIED"), "blind": data.get("blind", "UNKNOWN"), "reviewer_input_manifests": input_manifests, "reviews": data.get("reviews", {}), "evidence": data.get("evidence", []), "adjudication_unread_evidence_ids": data.get("unread_evidence_ids", "NOT_SUPPLIED")}, ensure_ascii=False, indent=2))
    synthetic = data.get("demonstration") == "SYNTHETIC_NO_MODEL_CALL"
    notice = "<strong>人工构造的工程演示</strong> · 全部数值与审查意见为预置样例；没有调用 Grok，没有运行科学分析，也没有测量插件改善效果。这是离线只读报告。" if synthetic else "<strong>提交者记录</strong> · 本报告展示冻结资料与模型裁决；结构校验不证明数据真实、执行发生、科学有效性或用户接受。"
    notice += "<br>门控：" + ("gate_version=1；案例级盲审=" + text(data.get("blind", "UNKNOWN")) if data.get("gate_version") == 1 else "历史记录或未提供门控版本；不能视为通过当前门控。")
    review_boundary = "核对的是保存内容、文件版本和引用锚点。内容一致不等于数据真实、分析正确或科学结论成立。审查上下文在本演示中仅为合成标记，不代表真实的独立模型审查。" if synthetic else "核对的是保存内容、文件版本和引用锚点。上下文标识与核对状态为提交者记录，不能据此证明独立审查、科学有效性或实际收益。"
    html = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Parrhesia · 结论审查</title><style>
    :root{color-scheme:light;--ink:#173331;--muted:#596b68;--line:#d8dfd8;--paper:#f4f5ee;--green:#c9ebdb}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.7 system-ui,'Microsoft YaHei',sans-serif}header{border-bottom:1px solid var(--line);padding:22px 5vw;display:flex;align-items:center;justify-content:space-between;gap:20px}header strong{font:600 25px Georgia,serif;letter-spacing:-1px}.subtitle{font-size:12px;color:var(--muted)}main{max-width:1150px;margin:auto;padding:46px 28px 70px}.eyebrow{font-size:12px;letter-spacing:2px;color:#526b60}h1{font-size:38px;line-height:1.3;letter-spacing:-1px;margin:12px 0 14px}.intro{max-width:740px;color:var(--muted);font-size:17px}.notice{margin:26px 0;border:1px solid #d3bc87;background:#fff5d9;padding:14px 18px;border-radius:10px}.flow{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:28px 0}.step{border-top:3px solid #95bca8;padding:13px 12px;background:#e8ede5}.step b{font-size:12px;display:block;color:#587264}.step span{font-size:14px}.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin:32px 0 18px}button{cursor:pointer;background:transparent;border:1px solid var(--line);border-radius:25px;padding:8px 17px;color:var(--ink);font:inherit;font-size:13px}button[aria-pressed=true]{background:var(--ink);color:white;border-color:var(--ink)}button:focus-visible,summary:focus-visible{outline:3px solid #db944d;outline-offset:4px}.claim{padding:26px 30px;border:1px solid var(--line);background:#fffef9;border-radius:14px;margin-bottom:17px}.claim-top{display:flex;gap:12px;align-items:center}.id{font-family:ui-monospace,monospace;color:var(--muted);font-size:13px}.badge{padding:3px 12px;border-radius:6px;background:#e6eadf;font-size:12px}.supported{background:var(--green)}.partially_supported{background:#e0e9d5}.insufficient_evidence{background:#f4e4bf}.unsupported{background:#f0d4c7}.level{font-size:12px;color:var(--muted)}h2{font-size:21px;line-height:1.6;margin:17px 0 10px}.original{color:#75817a;font-size:13px;border-left:2px solid #cdd4ca;padding-left:12px}dl{display:grid;grid-template-columns:90px 1fr;gap:10px 16px;margin:22px 0}dt{font-size:13px;color:var(--muted)}dd{margin:0}details{border-top:1px solid #e7e9e1;padding:13px 0 0;margin-top:13px}summary{cursor:pointer;font-size:13px;color:#3c6555}.finding{margin:15px 0;padding:13px 17px;background:#f1f4ed;border-radius:8px}.finding span{font-size:12px;color:#527166}.finding p{margin:7px 0}.finding small{color:var(--muted)}pre{font:12px/1.7 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#edf0e9;padding:16px;border-radius:8px}.audit{margin-top:36px}.audit h2{font-size:20px}footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:22px;margin-top:35px}a{color:var(--ink)}[hidden]{display:none!important}@media(max-width:650px){main{padding:28px 16px}h1{font-size:29px}.flow{grid-template-columns:1fr 1fr}.claim{padding:20px}dl{grid-template-columns:1fr;gap:3px}dd{margin-bottom:12px}.subtitle{max-width:140px}}
    table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);text-align:left;vertical-align:top;padding:8px;overflow-wrap:anywhere}th{width:35%}.claim-top{flex-wrap:wrap}</style></head><body><header><strong>Parrhesia<span style="color:#688e76">.</span></strong><span class="subtitle">有依据地表态 · 可追溯地改判</span></header><main><div class="eyebrow">REVIEW RECORD / 结论记录</div><h1>每一种错误，交给对应环节检查。</h1><p class="intro">双向审查可以挑战结论，裁决负责明确判断。最终保留的不是最强的语气，而是当前证据能够支持的最清楚的表述。</p><aside class="notice">''' + notice + '''</aside><div class="flow"><div class="step"><b>01 / FREEZE</b><span>初稿与结论台账</span></div><div class="step"><b>02 / PARALLEL</b><span>夸大审查</span></div><div class="step"><b>03 / PARALLEL</b><span>低估与防御审查</span></div><div class="step"><b>04 / ADJUDICATE</b><span>逐条裁决</span></div><div class="step"><b>05 / TRACE</b><span>来源核对与导出</span></div></div><div class="toolbar" role="group" aria-label="按判定筛选"><button data-filter="all" aria-pressed="true">全部结论</button><button data-filter="supported" aria-pressed="false">支持</button><button data-filter="partially_supported" aria-pressed="false">条件性支持</button><button data-filter="insufficient_evidence" aria-pressed="false">证据不足</button></div><div id="claims">''' + ''.join(cards) + '''</div><section class="audit"><h2>来源核对与审查边界</h2><p>''' + review_boundary + '''</p><details><summary>查看完整来源核对记录</summary><pre>''' + audit + '''</pre></details><details><summary>查看原始初稿</summary><p>''' + text(data['draft']) + '''</p></details></section><footer>Case ''' + text(data['case_id']) + ''' · Parrhesia ''' + text(__version__) + ''' pilot<br>报告由裁决记录生成。需要挑战或更改结论时，返回宿主中的持久案例；本页面不修改案例状态。</footer></main><script>document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('.claim').forEach(card=>{card.hidden=button.dataset.filter!=='all'&&card.dataset.verdict!==button.dataset.filter;});}));</script></body></html>'''
    with target.open("x", encoding="utf-8") as stream:
        stream.write(html)
