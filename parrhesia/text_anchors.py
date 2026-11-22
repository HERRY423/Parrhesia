"""Text safety, quote validation, excerpt-window parsing, and numeric effect anchoring. Pure stdlib."""
from __future__ import annotations

import hashlib
import re
import unicodedata

MIN_QUOTE_CHARS = 12
MIN_CJK_QUOTE_CHARS = 6

ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[@-Z\\-_]"
)
WINDOW_DELIMITER_LINE_RE = re.compile(r"^<<<PARRHESIA_EXCERPT_WINDOW\b[^\r\n]*>>>$")
BINARY_SIGNATURES = (
    b"%PDF-",
    b"PK\x03\x04",
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"\x1f\x8b",
    b"GIF8",
    b"\x7fELF",
)
QUOTE_STOPWORDS = {
    "this", "that", "with", "from", "were", "have", "been", "only", "text",
    "file", "line", "page", "copyright", "reserved", "rights", "header",
    "footer", "note", "document", "section", "author", "date", "time",
    "version", "status", "some", "more", "than", "into", "upon", "also",
    "such", "when", "what", "where", "which", "while", "there", "their",
    "about", "under", "after", "before",
}
CJK_STOPWORDS = {"以下", "这个", "可以", "进行", "通过", "由于", "因此", "一个", "我们", "没有", "备注", "补充", "说明"}

NONPRIMARY_CLAUSE_RE = re.compile(
    r"\b(?:negative[- ]control|falsification[- ](?:outcome|endpoint|test)|"
    r"secondary[- ](?:endpoint|outcome|analysis|analyses|objective)|"
    r"exploratory[- ](?:endpoint|outcome|analysis|analyses|subgroup)|"
    r"safety[- ](?:endpoint|outcome)|prior[- ](?:work|study|studies|report|reports)|"
    r"previously[- ]reported|background[- ]literature)\b"
    r"|阴性对照|次要终点|次要结局|探索性终点|既往研究",
    re.I,
)
PRIMARY_CLAUSE_OVERRIDE_RE = re.compile(
    r"\bprimary[- ](?:endpoint|outcome|analysis|result|effect|finding|hypothesis)\b|主要终点|主要结局|主要结果",
    re.I,
)
_SAFETY_OR_HOSP_CLAUSE_RE = re.compile(
    r"(?:\b(?:serious\s+)?adverse\s+events?\b|\b(?:treatment[- ]emergent\s+)?aes?\b|"
    r"\btoxicit(?:y|ies)\b|\btolerability\b|\bsafety(?:\s+(?:outcome|endpoint|profile|event|analysis)s?)?\b|"
    r"\bhospitalizations?\b|\bhospitalisations?\b|\brehospitalizations?\b|\breadmissions?\b|\blength\s+of\s+stay\b|"
    r"不良事件|毒性反应|安全性|再住院|住院率|住院时间)",
    re.I,
)
_PRIMARY_EFFICACY_SIGNAL_RE = re.compile(
    r"(?:\b(?:primary|overall|progression[- ]free|disease[- ]free)\s+(?:endpoint|outcome|survival|mortality|efficacy)\b|"
    r"\b(?:mortality|survival|pfs|dfs|mace|remission|efficacy|auroc|auc)\b|"
    r"(?:\b(?:hr|or|rr|rd|beta|delta|auroc|auc)\s*(?:=|of|:)\s*[-+]?\d|\bp\s*[<≤]\s*0\.0\d)|"
    r"主要终点|总生存|无进展生存|死亡率|疗效)",
    re.I,
)
METADATA_LABEL_RE = re.compile(
    r"\b(?:Table|Tab\.?|Fig\.?|Figure|Appendix|Supplementary\s+(?:Table|Figure)|Section|Sec\.?)\s*S?\d+(?:\.\d+)?[a-zA-Z]?\b",
    re.I,
)
ALPHA_LEVEL_RE = re.compile(r"(?:\balpha\b|α)\s*(?:=|<|<=|of|at|:)\s*0?\.\d+", re.I)
DECREASE_POLARITY_RE = re.compile(
    r"\b(?:reduc(?:ed|es|ing|tion)|lower(?:ed|s|ing)?|decreas(?:ed|es|ing)|drop(?:ped|s)?|"
    r"declin(?:ed|es|ing)|shorter|faster|abolish(?:ed|es)?|block(?:ed|s)?|attenuat(?:ed|es)?|fewer)\b"
    r"|\bless\s+(?:risk|mortality|morbidity|death|deaths|pain|bleeding|recurrence|relapse|"
    r"progression|incidence|prevalence|toxicity|burden|harm|harms|error|errors|latency|runtime|hazard)\b"
    r"|下降|降低|减少|缩短|减轻|阻断|抑制",
    re.I,
)
INCREASE_POLARITY_RE = re.compile(
    r"\b(?:increas(?:ed|es|ing)|gain(?:ed|s)?|higher|elevat(?:ed|es|ing)|ris(?:e|en|es|ing))\b"
    r"|升高|增加|提高|上升",
    re.I,
)


def strip_window_markers(text):
    if not isinstance(text, str) or not text:
        return ""
    if "<<<PARRHESIA_EXCERPT_WINDOW" not in text:
        return text
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not WINDOW_DELIMITER_LINE_RE.match(line.rstrip("\r\n"))
    )


def _parse_authenticated_windows(ev):
    """Verify sequential chunk headers and SHA-256 slices against ev['excerpt_windows']."""
    if not isinstance(ev, dict) or ev.get("source_text_status") != "truncated":
        return None
    rendered = ev.get("source_text")
    windows = ev.get("excerpt_windows")
    if not isinstance(rendered, str) or not isinstance(windows, list) or not windows:
        return None
    parsed = []
    pos = 0
    total = len(rendered)
    for idx, win in enumerate(windows):
        if not isinstance(win, dict):
            return None
        w_index = win.get("index")
        w_roles = win.get("roles")
        start_char = win.get("start_char")
        end_char = win.get("end_char")
        start_line = win.get("start_line")
        end_line = win.get("end_line")
        total_chars = win.get("total_chars")
        text_sha256 = win.get("text_sha256")
        if (
            type(w_index) is not int
            or w_index != idx + 1
            or not isinstance(w_roles, list)
            or not all(isinstance(r, str) for r in w_roles)
            or type(start_char) is not int
            or type(end_char) is not int
            or type(start_line) is not int
            or type(end_line) is not int
            or type(total_chars) is not int
            or not (0 <= start_char <= end_char <= total_chars)
            or start_line < 1
            or end_line < start_line
            or not isinstance(text_sha256, str)
        ):
            return None
        header = (
            f"<<<PARRHESIA_EXCERPT_WINDOW index={w_index} role={','.join(w_roles)} "
            f"chars={start_char}-{end_char} lines={start_line}-{end_line} of total_chars={total_chars}>>>\n"
        )
        if not rendered.startswith(header, pos):
            return None
        pos += len(header)
        body_len = end_char - start_char
        if pos + body_len > total:
            return None
        body = rendered[pos : pos + body_len]
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != text_sha256:
            return None
        pos += body_len
        if idx + 1 < len(windows):
            if not rendered.startswith("\n", pos):
                return None
            pos += 1
        parsed.append((win, body))
    if pos != total:
        return None
    return parsed


def _authenticated_source_text(ev):
    if not isinstance(ev, dict):
        return ""
    parsed = _parse_authenticated_windows(ev)
    if parsed is not None:
        return "\n".join(body for _, body in parsed)
    raw = ev.get("source_text")
    return raw if isinstance(raw, str) else ""


def strip_terminal_escapes(text):
    if not isinstance(text, str):
        return ""
    cleaned = ANSI_ESCAPE_RE.sub("", text)
    return "".join(c for c in cleaned if c not in "\x07\x08\x0b\x0c\ufeff")


def text_content(content):
    if content.startswith(BINARY_SIGNATURES) or b"\x00" in content:
        return None
    try:
        value = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    value = strip_terminal_escapes(value)
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        return None
    return value


def _is_cjk_char(ch):
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def quote_length(value):
    total = 0
    for c in value:
        if c.isspace() or unicodedata.category(c)[0] in "CM":
            continue
        total += 2 if _is_cjk_char(c) else 1
    return total


def quote_status(quote, source):
    if quote is None:
        return "not_supplied"
    clean_quote = strip_terminal_escapes(quote)
    if quote_length(clean_quote) < MIN_QUOTE_CHARS:
        return "too_short"
    if source is None:
        return "not_text"
    first = source.find(clean_quote)
    if first < 0:
        return "mismatch"
    if source.find(clean_quote, first + 1) >= 0:
        return "ambiguous"
    return "matched"


def _authenticated_quote_status(quote, ev):
    parsed = _parse_authenticated_windows(ev)
    if parsed is None:
        return quote_status(quote, ev.get("source_text") if isinstance(ev, dict) else ev)
    if quote is None:
        return "not_supplied"
    clean_quote = strip_terminal_escapes(quote)
    if quote_length(clean_quote) < MIN_QUOTE_CHARS:
        return "too_short"
    total_hits = 0
    for _, body in parsed:
        first = body.find(clean_quote)
        if first >= 0:
            total_hits += 1
            if total_hits > 1 or body.find(clean_quote, first + 1) >= 0:
                return "ambiguous"
    if total_hits == 0:
        return "mismatch"
    return "matched"


def _split_clauses(raw):
    if not isinstance(raw, str) or not raw:
        return []
    clauses = []
    buf = []
    depth = 0
    n = len(raw)
    for idx, ch in enumerate(raw):
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth > 0:
            depth -= 1
        is_sep = ch in "\n;；。" or (depth == 0 and ch in ",，")
        if not is_sep and ch == ".":
            prev_is_d = idx > 0 and raw[idx - 1].isdigit()
            next_is_d = idx + 1 < n and raw[idx + 1].isdigit()
            if not (prev_is_d and next_is_d):
                is_sep = True
        if is_sep:
            part = "".join(buf).strip()
            if part:
                clauses.append(part)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        clauses.append(tail)
    return clauses


def _strip_nonprimary_clauses(raw):
    clauses = _split_clauses(raw)
    if not clauses:
        return raw or ""
    kept = [
        cl for cl in clauses
        if not (NONPRIMARY_CLAUSE_RE.search(cl) and not PRIMARY_CLAUSE_OVERRIDE_RE.search(cl))
    ]
    if not kept:
        return raw or ""
    if len(kept) >= 2 and any(
        _PRIMARY_EFFICACY_SIGNAL_RE.search(cl) and not _SAFETY_OR_HOSP_CLAUSE_RE.search(cl)
        for cl in kept
    ):
        primary_filtered = [
            cl for cl in kept
            if not (_SAFETY_OR_HOSP_CLAUSE_RE.search(cl) and not PRIMARY_CLAUSE_OVERRIDE_RE.search(cl))
        ]
        if primary_filtered:
            kept = primary_filtered
    return "; ".join(kept)


def _mask_metadata_noise(text):
    if not isinstance(text, str) or not text:
        return ""
    cleaned = METADATA_LABEL_RE.sub(" ", text)
    cleaned = ALPHA_LEVEL_RE.sub(" ", cleaned)
    return cleaned


def _clause_bounds(text, pos):
    left = 0
    for idx in range(pos - 1, -1, -1):
        ch = text[idx]
        if ch in "\n;；。" or (ch == "." and not (idx > 0 and idx + 1 < len(text) and text[idx - 1].isdigit() and text[idx + 1].isdigit())):
            left = idx + 1
            break
    right = len(text)
    for idx in range(pos, len(text)):
        ch = text[idx]
        if ch in "\n;；。" or (ch == "." and not (idx > 0 and idx + 1 < len(text) and text[idx - 1].isdigit() and text[idx + 1].isdigit())):
            right = idx
            break
    return text[left:right]


def _extract_signed_tokens(text, reduction_hint=False):
    if not isinstance(text, str) or not text:
        return []
    norm = text.replace("\u2212", "-")
    tokens = []
    for m in re.finditer(r"(?<![A-Za-z])(\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z])", norm):
        start = m.start()
        val = float(m.group(1).replace(",", ""))
        sign = None
        if start > 0 and norm[start - 1] in "+-":
            prev = norm[start - 2] if start >= 2 else " "
            if not prev.isdigit() and prev != "%":
                sign = norm[start - 1]
        prefix = norm[max(0, start - 20):start]
        is_pval = bool(re.search(r"(?:\bp\b(?:\s*-?\s*value)?|pval)\s*(?:=|<|>|<=|>=|:|\bof\b)\s*[+-]?$", prefix, re.I))
        clause = _clause_bounds(norm, start)
        has_inc = bool(INCREASE_POLARITY_RE.search(clause))
        has_red = bool(DECREASE_POLARITY_RE.search(clause)) or (reduction_hint and sign is None and not has_inc)
        has_inc = has_inc and not has_red
        tokens.append({
            "val": val,
            "sign": sign,
            "is_pval": is_pval,
            "reduction": has_red,
            "increase": has_inc,
            "start": start,
        })
    return tokens


def _extract_floats(text):
    return [tok["val"] for tok in _extract_signed_tokens(text)]


def _claimed_effect_tokens(claim, decision):
    tokens = []
    est_text = str(claim.get("effect", {}).get("estimate") or "")
    unc_text = str(claim.get("effect", {}).get("uncertainty") or "")
    rev_text = str(decision.get("revised_text") or claim.get("text") or "")
    rev_primary = _strip_nonprimary_clauses(rev_text)
    claim_has_red = bool(DECREASE_POLARITY_RE.search(est_text) or DECREASE_POLARITY_RE.search(rev_primary))
    for tok in _extract_signed_tokens(est_text, reduction_hint=claim_has_red):
        if tok["val"] != 0.0 or tok["sign"] is not None:
            tokens.append(tok)
    for m in re.finditer(r"(?:95%|90%|99%)\s*CI\s*(\[[^\]]+\]|[^\n;)]*)", unc_text, re.I):
        tokens.extend(_extract_signed_tokens(m.group(1), reduction_hint=claim_has_red))
    for m in re.finditer(r"(?:95%|90%|99%)\s*CI\s*(\[[^\]]+\]|[^\n;)]*)", rev_text, re.I):
        clause = _clause_bounds(rev_text, m.start())
        tokens.extend(_extract_signed_tokens(m.group(1), reduction_hint=bool(DECREASE_POLARITY_RE.search(clause))))
    rev_norm = rev_text.replace("\u2212", "-")
    metric_patterns = (
        r"\b(?:HR|OR|RR|RD|ATT|LATE|AUROC|AUC|F1|macro-F1|O/E|slope|Brier|delta|difference|effect|estimate|gain)\b"
        r"\s*(?:=|:|\bis\b|\bof\b|\bwas\b|达|为)?\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z])",
        r"\b(?:by|reduction|reduced|reduces|improves|improved|increased|increases|blocks|abolishes|lowers|lowered|decreased|decreases|gain)\s+"
        r"(?:[\w\-]+\s+){0,4}?(?:by\s+|of\s+)?([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:%|percentage points|points|mmHg|days|minutes)\b",
        r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*%\s*(?:reduction|increase|improvement|drop|gain|decrease)",
        r"(?:^|[\s(=,:\[;])([+-]\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z])",
    )
    for pat in metric_patterns:
        for m in re.finditer(pat, rev_norm, re.I):
            raw_num = m.group(1)
            sign = raw_num[0] if raw_num[0] in "+-" else None
            val = float((raw_num[1:] if sign else raw_num).replace(",", ""))
            clause = _clause_bounds(rev_norm, m.start(1))
            has_red = bool(DECREASE_POLARITY_RE.search(clause))
            has_inc = bool(INCREASE_POLARITY_RE.search(clause)) and not has_red
            tokens.append({
                "val": val,
                "sign": sign,
                "is_pval": False,
                "reduction": has_red,
                "increase": has_inc,
            })
    seen = set()
    unique = []
    for tok in tokens:
        key = (round(tok["val"], 6), tok["sign"], tok["is_pval"], tok["reduction"], tok["increase"])
        if key not in seen:
            seen.add(key)
            unique.append(tok)
    return unique


def _claimed_effect_numbers(claim, decision):
    return [tok["val"] for tok in _claimed_effect_tokens(claim, decision)]


def _val_close(target_val, src_val):
    tol = 0.5 if target_val >= 10.0 and float(target_val).is_integer() else 0.05
    return abs(target_val - src_val) <= tol


def _number_matches_source(target_val, source_floats):
    return any(_val_close(target_val, src_val) for src_val in source_floats)


def _token_matches_source(claimed, source_tokens):
    if claimed["is_pval"]:
        return any(_val_close(claimed["val"], s["val"]) for s in source_tokens)
    cands = [s for s in source_tokens if not s["is_pval"] and _val_close(claimed["val"], s["val"])]
    if not cands:
        return False
    if claimed["val"] == 0.0 and claimed["sign"] is None:
        return True
    if claimed["sign"] == "-":
        return any(s["sign"] == "-" or (s["sign"] is None and s["reduction"]) for s in cands)
    if claimed["sign"] == "+" or (claimed["sign"] is None and claimed["increase"]):
        return any(s["sign"] in ("+", None) and not s["reduction"] for s in cands)
    if claimed["reduction"]:
        return any(s["sign"] == "-" or (s["sign"] is None and not s["increase"]) for s in cands)
    return any(s["sign"] in ("+", None) and not s["reduction"] for s in cands)


def _priority_text_for_evidence(ev, linked_locators):
    chunks = []
    quote = str(ev.get("quote") or "")
    if quote:
        chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(quote)))
    parsed = _parse_authenticated_windows(ev)
    if parsed is not None:
        if quote:
            for _, body in parsed:
                pos = body.find(quote)
                if pos >= 0:
                    win_slice = body[max(0, pos - 120):min(len(body), pos + len(quote) + 300)]
                    chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(win_slice)))
                    break
        if linked_locators:
            line_map = {}
            for win, body in parsed:
                cur_line = win["start_line"]
                for ln in body.split("\n"):
                    if cur_line <= win["end_line"]:
                        line_map[cur_line] = ln.rstrip("\r")
                    cur_line += 1
            for loc in linked_locators:
                for m in re.finditer(r"(?:line|:L)\s*(\d+)", loc, re.I):
                    line_no = int(m.group(1))
                    if line_no in line_map:
                        chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(line_map[line_no])))
    else:
        src_raw = str(ev.get("source_text") or "")
        if quote and src_raw:
            pos = src_raw.find(quote)
            if pos >= 0:
                win = src_raw[max(0, pos - 120):min(len(src_raw), pos + len(quote) + 300)]
                chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(win)))
        if linked_locators and src_raw:
            lines = src_raw.split("\n")
            for loc in linked_locators:
                for m in re.finditer(r"(?:line|:L)\s*(\d+)", loc, re.I):
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(lines):
                        chunks.append(_mask_metadata_noise(_strip_nonprimary_clauses(lines[idx].rstrip("\r"))))
    return "\n".join(c for c in chunks if c)


def effect_numbers_anchored(claim, decision, cited_evidence):
    claimed_tokens = _claimed_effect_tokens(claim, decision)
    if not claimed_tokens:
        return True
    decision_refs = set(decision.get("evidence_ids") or ())
    linked_num_cards = [
        c for c in claim.get("provenance_cards", {}).get("number", [])
        if isinstance(c, dict)
        and c.get("status") in ("reported", "checked")
        and (set(c.get("evidence_ids") or ()) & decision_refs)
    ]
    linked_locators = [
        str(c.get("details", {}).get("locator") or "")
        for c in linked_num_cards
        if isinstance(c.get("details"), dict)
    ]
    priority_tokens = []
    source_tokens = []
    for ev in cited_evidence:
        p_text = _priority_text_for_evidence(ev, linked_locators)
        if p_text:
            priority_tokens.extend(_extract_signed_tokens(p_text))
        s_clean = _mask_metadata_noise(_strip_nonprimary_clauses(_authenticated_source_text(ev)))
        q_clean = _mask_metadata_noise(_strip_nonprimary_clauses(str(ev.get("quote") or "")))
        if s_clean:
            source_tokens.extend(_extract_signed_tokens(s_clean))
        if q_clean:
            source_tokens.extend(_extract_signed_tokens(q_clean))
    if not source_tokens and not priority_tokens:
        return False
    all_source = priority_tokens + source_tokens
    for card in linked_num_cards:
        if card.get("status") != "checked" or not isinstance(card.get("details"), dict):
            continue
        card_text = " ".join(str(card["details"].get(k) or "") for k in ("value", "uncertainty"))
        for ctok in _extract_signed_tokens(_mask_metadata_noise(card_text)):
            if _token_matches_source(ctok, all_source):
                priority_tokens.append(ctok)
    for tok in claimed_tokens:
        has_priority_mag = any(
            (tok["is_pval"] or not s["is_pval"]) and _val_close(tok["val"], s["val"])
            for s in priority_tokens
        )
        if has_priority_mag:
            if not _token_matches_source(tok, priority_tokens):
                return False
        elif not _token_matches_source(tok, all_source):
            return False
    return True


def quote_links_to_claim(ev, claim, decision):
    quote = ev.get("quote") or ""
    ev_id = ev.get("evidence_id")
    parts = [
        claim.get("text", ""),
        decision.get("revised_text", ""),
        claim.get("scope", ""),
        decision.get("scope", ""),
        claim.get("contribution", ""),
        claim.get("effect", {}).get("estimate", ""),
        claim.get("effect", {}).get("uncertainty", ""),
    ]
    for cards in claim.get("provenance_cards", {}).values():
        for card in cards:
            if card.get("status") == "checked" and (not ev_id or ev_id in card.get("evidence_ids", [])):
                parts.extend(str(v) for v in card.get("details", {}).values())
    target = " ".join(str(p) for p in parts if p)
    q_nums = set(re.findall(r"\d+(?:\.\d+)?", quote))
    t_nums = set(re.findall(r"\d+(?:\.\d+)?", target))
    if q_nums & t_nums:
        return True
    q_words = {w for w in re.findall(r"[a-zA-Z]{4,}", quote.lower()) if w not in QUOTE_STOPWORDS}
    t_words = {w for w in re.findall(r"[a-zA-Z]{4,}", target.lower()) if w not in QUOTE_STOPWORDS}
    if q_words & t_words or ({w[:5] for w in q_words if len(w) >= 5} & {w[:5] for w in t_words if len(w) >= 5}):
        return True
    q_cjk = "".join(c for c in quote if "\u4e00" <= c <= "\u9fff")
    t_cjk = "".join(c for c in target if "\u4e00" <= c <= "\u9fff")
    q_bigrams = {q_cjk[i:i + 2] for i in range(len(q_cjk) - 1)} - CJK_STOPWORDS
    t_bigrams = {t_cjk[i:i + 2] for i in range(len(t_cjk) - 1)} - CJK_STOPWORDS
    return bool(q_bigrams & t_bigrams)
