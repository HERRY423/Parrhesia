"""Non-blocking anti-underclaim, false-abstention, and over-hedging symmetry audit. Pure stdlib."""
from __future__ import annotations

import re

from .claims import TYPE_LEVELS, validate_support
from .contracts import ContractError
from .effects import verify_effect_computations
from .text_anchors import _claimed_effect_tokens, _strip_nonprimary_clauses, effect_numbers_anchored


_PRELIMINARY_ONLY_CONDITION_RE = re.compile(
    r"(?:"
    r"\b(?:preliminary|tentative|provisional)\s+"
    r"(?:scope|finding|result|evidence|estimate|conclusion|support)s?\s+only\b"
    r"|\b(?:preliminary|tentative|provisional)\s+only\b"
    r"|仅(?:为|作)?(?:初步|暂定)(?:结果|结论|范围|证据|支持)"
    r")",
    re.I,
)
_GENERIC_DEFER_CLAUSE_RE = re.compile(
    r"(?:"
    r"\b(?:preliminary|tentative|provisional)\b.*\b(?:pending|awaiting|until)\b"
    r"|\b(?:pending|awaiting)\s+"
    r"(?:broader|further|additional|larger|future|independent|external|multi[- ]?center|confirmatory)\s+"
    r"(?:(?:multi[- ]?center|external|independent|larger|clinical|prospective|broader|further|additional)\s+)*"
    r"(?:confirmation|validation|verification|replication|trials?|studies|evidence)\b"
    r"|\bsubject\s+to\s+"
    r"(?:further|additional|future|broader|larger|independent|external|multi[- ]?center|confirmatory)\s+"
    r"(?:(?:multi[- ]?center|external|independent|larger|clinical|prospective)\s+)*"
    r"(?:confirmation|validation|verification|replication|trials?|studies)\b"
    r"|(?:初步|暂定)(?:结果|结论|范围|支持)?(?:，|,|\s)*(?:尚待|待|有待)(?:进一步|更多|更大规模|多中心|外部)?(?:确认|验证|研究|试验)"
    r"|(?:尚待|有待|需待)(?:进一步|更多|更大规模|多中心|外部)(?:确认|验证|研究|试验)"
    r")",
    re.I,
)


def _iter_claim_check_records(claim):
    if not isinstance(claim, dict):
        return
    checks = claim.get("checks")
    if isinstance(checks, dict):
        for key, val in checks.items():
            if key in ("design", "statistics") and isinstance(val, dict):
                for rec in val.values():
                    if isinstance(rec, dict):
                        yield rec, True
            elif isinstance(val, dict):
                yield val, False

    design_packages = claim.get("design_packages")
    if isinstance(design_packages, (list, tuple)):
        for pkg in design_packages:
            if not isinstance(pkg, dict):
                continue
            pkg_checks = pkg.get("checks")
            if isinstance(pkg_checks, dict):
                for rec in pkg_checks.values():
                    if isinstance(rec, dict):
                        yield rec, True
    elif isinstance(design_packages, dict):
        for val in design_packages.values():
            if not isinstance(val, dict):
                continue
            if "checks" in val and isinstance(val["checks"], dict) and set(val.keys()) <= {"family", "checks"}:
                for rec in val["checks"].values():
                    if isinstance(rec, dict):
                        yield rec, True
            else:
                for rec in val.values():
                    if isinstance(rec, dict):
                        yield rec, True

    stat_report = claim.get("statistical_report")
    if isinstance(stat_report, dict):
        for rec in stat_report.values():
            if isinstance(rec, dict):
                yield rec, True

    causal_basis = claim.get("causal_basis")
    if isinstance(causal_basis, dict):
        claim_type = claim.get("claim_type")
        single_keys = ["assessment"]
        if claim_type in ("necessity", None):
            single_keys.append("necessity_test")
        if claim_type in ("sufficiency", None):
            single_keys.append("sufficiency_test")
        for key in single_keys:
            rec = causal_basis.get(key)
            if isinstance(rec, dict):
                yield rec, True
        for list_key in ("assumptions", "falsification_sensitivity"):
            entries = causal_basis.get(list_key)
            if isinstance(entries, (list, tuple)):
                for rec in entries:
                    if isinstance(rec, dict):
                        yield rec, True


def _extract_reviewer_stances(findings):
    stances_by_claim = {}
    if not isinstance(findings, dict):
        return stances_by_claim
    for block in findings.values():
        if not isinstance(block, dict):
            continue
        stances = block.get("claim_stances")
        if not isinstance(stances, list):
            continue
        for st in stances:
            if not isinstance(st, dict):
                continue
            cid = st.get("claim_id")
            val = st.get("stance")
            if _is_valid_audit_id(cid) and isinstance(val, str) and val:
                stances_by_claim.setdefault(cid, []).append(val)
    return stances_by_claim


def _is_ungrounded_or_hedged_condition(record, _g):
    cond_text = str(record.get("condition") or "").strip()
    if not _g.substantive_reason(cond_text):
        return True
    rec_hedge_text = " ".join(
        str(record.get(k) or "") for k in ("condition", "rationale", "revised_text", "reversal_condition")
    )
    if _g.BOILERPLATE_OVERHEDGING_RE.search(rec_hedge_text):
        return True
    if _PRELIMINARY_ONLY_CONDITION_RE.search(cond_text):
        return True
    clauses = [c.strip() for c in re.split(r"[;.；。]+", cond_text) if c.strip()]
    if clauses and all(_GENERIC_DEFER_CLAUSE_RE.search(c) for c in clauses):
        return True
    rev_cond = str(record.get("reversal_condition") or "").strip()
    if rev_cond and _g.is_vacuous_reversal_condition(rev_cond):
        return True
    return False


def _has_contradicting_card(claim):
    from . import gates as _g

    cards_by_kind = claim.get("provenance_cards") or {}
    if not isinstance(cards_by_kind, dict):
        return False
    for cards in cards_by_kind.values():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            status = str(card.get("status") or "").strip().lower()
            if status in ("fail", "failed", "contradicted", "refuted"):
                return True
            details = card.get("details") or {}
            if not isinstance(details, dict):
                continue
            if _g.is_contradicting_relation(details.get("support_relation")) or _g.is_contradicting_relation(details.get("relation")):
                return True
            detail_text = " ".join(str(v) for v in details.values() if v is not None)
            cleaned_detail = _strip_nonprimary_clauses(detail_text)
            cleaned_detail = _g._REJECTED_NULL_RE.sub(" ", cleaned_detail)
            cleaned_detail = _g._PRIOR_LITERATURE_CONTRAST_RE.sub(" ", cleaned_detail).lower()
            norm = re.sub(r"[\s_\-]+", " ", cleaned_detail).strip()
            norm = _g._REJECTED_NULL_RE.sub(" ", norm)
            norm = _g._PRIOR_LITERATURE_CONTRAST_RE.sub(" ", norm)
            for safe in _g.NON_CONTRADICTING_NEGATIONS:
                norm = norm.replace(safe, " ")
            norm = re.sub(r"\s+", " ", norm).strip()
            if any(phrase in norm for phrase in _g.NULL_OR_REFUTING_EVIDENCE_PHRASES):
                return True
    return False


def _has_failed_check(claim):
    from . import gates as _g

    for rec, require_ev in _iter_claim_check_records(claim):
        if rec.get("status") == "fail" or _g.effective_status(rec, require_evidence=require_ev) == "fail":
            return True
    return False


def _has_contradicting_effect_record(claim):
    from .effects import PRIMARY_EFFECT_ROLES, _record_alpha, _record_crosses_null

    for rec in claim.get("effect_records") or ():
        if not isinstance(rec, dict):
            continue
        if rec.get("endpoint_role") not in PRIMARY_EFFECT_ROLES:
            continue
        if rec.get("direction") == "null":
            return True
        if rec.get("claim_direction") and rec.get("direction") and rec["claim_direction"] != rec["direction"]:
            return True
        try:
            if _record_crosses_null(rec):
                return True
        except Exception:
            pass
        if rec.get("ci_low") is None and rec.get("p_value") is not None:
            try:
                if float(rec["p_value"]) >= _record_alpha(rec):
                    return True
            except (TypeError, ValueError):
                pass
    return False


_EXPLICIT_REFUTE_RE = re.compile(
    r"\b(?:refut(?:es?|ed|ing)|contradict(?:s|ed|ing)?|disprov(?:es?|ed|ing)|falsif(?:y|ies|ied|ying)|overturn(?:s|ed|ing)?)\b"
    r"|推翻|证伪|反驳|否定",
    re.I,
)
_RATIO_CI_RE = re.compile(
    r"\b(?:HR|OR|RR|IRR)\b[^.;\n]{0,45}?(?:CI|confidence\s+interval)[^0-9\n]{0,12}(\d+(?:\.\d+)?)\s*(?:to|-|–|,)\s*(\d+(?:\.\d+)?)",
    re.I,
)
_NONPRIMARY_NULL_CONTEXT_RE = re.compile(
    r"\b(?:placebo|negative[- ]control|pre[- ]?trend|parallel\s+trend|safety|adverse|secondary|hospitalization|falsification|equivalence|tost|non[- ]?inferior)\b"
    r"|阴性对照|安慰剂|次要|安全性|不良事件|等效|非劣",
    re.I,
)
_DIAGNOSTIC_TEST_PREFIX_RE = re.compile(
    r"\b(?:mccrary|egger|asymmetry|funnel|schoenfeld|proportional\s+hazards?|pre[- ]?trend|parallel\s+trends?|"
    r"hausman|sargan|hansen|overidentif\w*|shapiro|hosmer|calibration|balance|heterogeneity|cochran|"
    r"goodness[- ]of[- ]fit|manipulation|bandwidth|sensitivity|diagnostic|placebo|negative[- ]control)\b"
    r"|密度检验|平行趋势|对称性|发表偏倚|异质性|校准检验|平衡性检验|敏感度检验|诊断检验",
    re.I,
)
_EXPLICIT_P_EQ_RE = re.compile(r"\bp\s*=\s*(0?\.\d+)\b", re.I)


def _scoped_primary_numeric_null(ev, focus_text: str) -> bool:
    from .text_advisories import scoped_evidence_clauses

    for clause in scoped_evidence_clauses(ev, focus_text):
        if _NONPRIMARY_NULL_CONTEXT_RE.search(clause):
            continue
        for m in _RATIO_CI_RE.finditer(clause):
            try:
                lo, hi = float(m.group(1)), float(m.group(2))
            except ValueError:
                continue
            if lo <= 1.0 <= hi:
                return True
        for pm in _EXPLICIT_P_EQ_RE.finditer(clause):
            try:
                pv = float(pm.group(1))
            except ValueError:
                continue
            if pv < 0.05:
                continue
            # Diagnostic / assumption tests (McCrary, Egger/asymmetry, Schoenfeld, pre-trend, etc.)
            # pass when p >= 0.05 and are never primary-effect null contradictions.
            local_prefix = clause[max(0, pm.start() - 50):pm.start()]
            local_seg = re.split(r"[,;()\[\]:]", local_prefix)[-1]
            if _DIAGNOSTIC_TEST_PREFIX_RE.search(local_seg):
                continue
            return True
    return False


def _has_failed_check_or_contradiction(claim, candidate_evs, *, check_numeric_mismatch=False):
    from . import gates as _g

    if _has_failed_check(claim) or _has_contradicting_card(claim) or _has_contradicting_effect_record(claim):
        return True
    if check_numeric_mismatch and candidate_evs and _claimed_effect_tokens(claim, claim):
        ev_ids = [e.get("evidence_id") for e in candidate_evs if e.get("evidence_id")]
        if ev_ids and not effect_numbers_anchored(claim, {**claim, "evidence_ids": ev_ids}, candidate_evs):
            return True
    focus = claim.get("text", "")
    for ev in candidate_evs:
        if _g.contradictory_positive_evidence_text(ev, include_outcome_stripped=False, focus_text=focus):
            return True
        if _scoped_primary_numeric_null(ev, focus):
            return True
        raw_ev_text = " ".join(str(ev.get(k) or "") for k in ("quote", "source_text")).lower()
        for safe in _g.NON_CONTRADICTING_NEGATIONS:
            raw_ev_text = raw_ev_text.replace(safe, " ")
        if _EXPLICIT_REFUTE_RE.search(raw_ev_text):
            return True
    return False


def _passes_positive_candidate(
    claim,
    record,
    candidate_refs,
    by_evidence,
    exec_events=None,
    *,
    verdict="supported",
    claim_type=None,
    evidence_level=None,
    claim_basis=None,
    scope=None,
    revised_text=None,
):
    from . import gates as _g

    c_type = claim_type or record.get("claim_type") or claim.get("claim_type")
    c_level = evidence_level or record.get("evidence_level") or claim.get("evidence_level")
    c_basis = claim_basis or record.get("claim_basis") or claim.get("claim_basis")
    c_scope = scope or record.get("scope") or claim.get("scope")
    if c_type not in TYPE_LEVELS or c_level not in TYPE_LEVELS[c_type] or c_basis not in _g.BASES:
        return False
    if not candidate_refs or not all(ref in by_evidence for ref in candidate_refs):
        return False
    candidate = {
        **claim,
        "claim_id": claim.get("id") or claim.get("claim_id") or record.get("claim_id"),
        "claim_type": c_type,
        "evidence_level": c_level,
        "claim_basis": c_basis,
        "scope": c_scope or claim.get("scope") or "",
        "verdict": verdict,
        "evidence_ids": list(candidate_refs),
        "revised_text": revised_text or record.get("revised_text") or claim.get("text") or "",
    }
    if verdict == "partially_supported":
        cond = record.get("condition") or c_scope or claim.get("scope") or "Bounded to evidenced scope"
        candidate["condition"] = cond
    try:
        _g.validate_basis(candidate)
        validate_support(candidate, claim)
        _g.validate_mechanical(candidate, claim, by_evidence, exec_events=exec_events)
    except (ContractError, KeyError, TypeError, ValueError):
        return False
    return True


def _is_valid_audit_id(val):
    return isinstance(val, (str, int)) and not isinstance(val, bool) and bool(val)


def _normalize_audit_inputs(records, claims, evidence, findings, dispositions):
    if isinstance(claims, dict):
        by_claim = {cid: c for cid, c in claims.items() if _is_valid_audit_id(cid) and isinstance(c, dict)}
    else:
        by_claim = {}
        for c in claims or ():
            if isinstance(c, dict):
                cid = c.get("id") or c.get("claim_id")
                if _is_valid_audit_id(cid):
                    by_claim[cid] = c
    if isinstance(evidence, dict):
        by_evidence = {eid: e for eid, e in evidence.items() if _is_valid_audit_id(eid) and isinstance(e, dict)}
    else:
        by_evidence = {
            e["evidence_id"]: e
            for e in (evidence or ())
            if isinstance(e, dict) and _is_valid_audit_id(e.get("evidence_id"))
        }
    findings_list = []
    if isinstance(findings, dict):
        for role, block in findings.items():
            items = block.get("findings") if isinstance(block, dict) else block
            if isinstance(items, list):
                for f in items:
                    if isinstance(f, dict):
                        findings_list.append({**f, "role": f.get("role", role)})
    elif isinstance(findings, list):
        findings_list = [f for f in findings if isinstance(f, dict)]
    disp_by_finding = {
        d["finding_id"]: d
        for d in (dispositions or ())
        if isinstance(d, dict) and _is_valid_audit_id(d.get("finding_id"))
    }
    records_list = [r for r in (records.values() if isinstance(records, dict) else (records or ())) if isinstance(r, dict)]
    return by_claim, by_evidence, findings_list, disp_by_finding, records_list


def audit_underclaim_and_abstention(records, claims, evidence, findings=None, dispositions=None, exec_events=None, *, is_review=False):
    """Non-blocking advisory symmetry audit flagging potential false abstention or over-hedging.

    Never raises ContractError and never blocks review, adjudication, or export.
    """
    from . import gates as _g

    flags = []
    lexical_advisories = []
    seen_lexical = set()
    by_claim, by_evidence, findings_list, disp_by_finding, records_list = _normalize_audit_inputs(
        records, claims, evidence, findings, dispositions
    )
    reviewer_stances = _extract_reviewer_stances(findings)
    by_record = {r.get("claim_id"): r for r in records_list if _is_valid_audit_id(r.get("claim_id"))}

    for record in records_list:
        try:
            cid = record.get("claim_id")
            if not _is_valid_audit_id(cid):
                continue
            claim = by_claim.get(cid)
            if not claim:
                continue
            if is_review or ("stance" in record and "verdict" not in record):
                observed_verdict = record.get("stance")
            else:
                observed_verdict = record.get("verdict")
            if not isinstance(observed_verdict, str) or not observed_verdict:
                continue

            for adv in _g.collect_lexical_advisories(record, claim, by_evidence, exec_events=exec_events):
                adv_key = (
                    adv.get("claim_id"),
                    adv.get("hook_code"),
                    adv.get("detail_code"),
                    tuple(adv.get("evidence_ids") or ()),
                )
                if adv_key not in seen_lexical:
                    seen_lexical.add(adv_key)
                    lexical_advisories.append(adv)

            raw_eids = record.get("evidence_ids")
            claim_eids = claim.get("evidence_ids")
            raw_refs = [r for r in (raw_eids if isinstance(raw_eids, (list, tuple)) else ()) if _is_valid_audit_id(r)]
            claim_refs = [r for r in (claim_eids if isinstance(claim_eids, (list, tuple)) else ()) if _is_valid_audit_id(r)]
            probe_refs = list(dict.fromkeys([*raw_refs, *claim_refs]))
            pos_refs = raw_refs if raw_refs else claim_refs
            probe_evs = [by_evidence[r] for r in probe_refs if r in by_evidence]
            has_blocker = _g._has_failed_check_or_contradiction(
                claim,
                probe_evs,
                check_numeric_mismatch=(observed_verdict == "unsupported"),
            )

            frozen_type = claim.get("claim_type")
            frozen_level = claim.get("evidence_level")
            cur_type = record.get("claim_type") or frozen_type
            cur_level = record.get("evidence_level") or frozen_level
            level_downgraded = False
            if (
                not is_review
                and cur_type == frozen_type
                and isinstance(cur_type, str)
                and cur_type in TYPE_LEVELS
                and frozen_level in TYPE_LEVELS[cur_type]
                and cur_level in TYPE_LEVELS[cur_type]
            ):
                level_downgraded = TYPE_LEVELS[cur_type].index(cur_level) < TYPE_LEVELS[cur_type].index(frozen_level)

            has_overclaim_justification = False
            for f in findings_list:
                if f.get("claim_id") != cid:
                    continue
                role = f.get("role")
                fid_rec = f.get("id")
                disp = disp_by_finding.get(fid_rec) if _is_valid_audit_id(fid_rec) else None
                if role == "overclaim":
                    if is_review or (disp and disp.get("disposition") in ("accepted", "partial")):
                        has_overclaim_justification = True
                        break
                elif role is None and disp and disp.get("disposition") in ("accepted", "partial"):
                    if (
                        isinstance(frozen_type, str)
                        and frozen_type in TYPE_LEVELS
                        and f.get("proposed_evidence_level") in TYPE_LEVELS[frozen_type]
                        and frozen_level in TYPE_LEVELS[frozen_type]
                    ):
                        if TYPE_LEVELS[frozen_type].index(f["proposed_evidence_level"]) <= TYPE_LEVELS[frozen_type].index(frozen_level):
                            has_overclaim_justification = True
                            break

            if observed_verdict == "insufficient_evidence" and claim_refs and not has_blocker and not has_overclaim_justification:
                cand_verdict = None
                for trial_verdict in ("supported", "partially_supported"):
                    if _passes_positive_candidate(
                        claim, record, probe_refs, by_evidence, exec_events,
                        verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                        claim_basis=claim.get("claim_basis"), scope=claim.get("scope"), revised_text=claim.get("text"),
                    ):
                        cand_verdict = trial_verdict
                        break
                if cand_verdict is not None:
                    flags.append({
                        "claim_id": cid,
                        "hook_code": "possible_false_abstention",
                        "severity": "advisory",
                        "non_blocking": True,
                        "observed_verdict": observed_verdict,
                        "advisory_candidate_verdict": cand_verdict,
                        "advisory_candidate_level": frozen_level,
                        "message": f"Claim '{cid}' received 'insufficient_evidence' despite nonempty evidence {probe_refs} clearing support and mechanical gates for {frozen_type} x {frozen_level} ({cand_verdict}).",
                        "evidence_ids": probe_refs,
                    })

            if observed_verdict in _g.POSITIVE and not has_blocker and not has_overclaim_justification:
                cand_verdict = None
                cand_level = None
                if observed_verdict == "partially_supported":
                    ungrounded_or_hedged = _is_ungrounded_or_hedged_condition(record, _g)
                    rev_stances = reviewer_stances.get(cid) or []
                    unilateral_verdict_downgrade = (
                        not is_review
                        and bool(rev_stances)
                        and all(st == "supported" for st in rev_stances)
                    )
                    if level_downgraded and _passes_positive_candidate(
                        claim, record, pos_refs, by_evidence, exec_events,
                        verdict="supported", claim_type=frozen_type, evidence_level=frozen_level,
                        claim_basis=claim.get("claim_basis"), scope=claim.get("scope"),
                    ):
                        cand_verdict, cand_level = "supported", frozen_level
                    elif (level_downgraded or ungrounded_or_hedged or unilateral_verdict_downgrade) and _passes_positive_candidate(
                        claim, record, pos_refs, by_evidence, exec_events,
                        verdict="supported", claim_type=cur_type, evidence_level=cur_level,
                    ):
                        cand_verdict, cand_level = "supported", cur_level
                if cand_verdict is None and level_downgraded:
                    try:
                        frozen_allowed = frozen_level in _g.ceiling(claim, frozen_type)["allowed_levels"]
                    except (ContractError, KeyError, TypeError, ValueError):
                        frozen_allowed = False
                    if frozen_allowed and _passes_positive_candidate(
                        claim, record, pos_refs, by_evidence, exec_events,
                        verdict=observed_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                        claim_basis=record.get("claim_basis") or claim.get("claim_basis"),
                        scope=record.get("scope") or claim.get("scope"),
                    ):
                        cand_verdict, cand_level = observed_verdict, frozen_level
                if cand_verdict is not None:
                    flags.append({
                        "claim_id": cid,
                        "hook_code": "possible_unjustified_downgrade",
                        "severity": "advisory",
                        "non_blocking": True,
                        "observed_verdict": observed_verdict,
                        "advisory_candidate_verdict": cand_verdict,
                        "advisory_candidate_level": cand_level,
                        "message": f"Claim '{cid}' was downgraded to {observed_verdict} ({cur_type} x {cur_level}) without failed checks or accepted overclaim justification; {cand_verdict} at {cand_level} clears mechanical gates.",
                        "evidence_ids": pos_refs,
                    })

            emitted_effect_underclaim = False
            if observed_verdict == "unsupported" and claim.get("effect_records"):
                try:
                    eff_probe = verify_effect_computations(claim, {**record, "verdict": "unsupported"}, by_evidence)
                except ContractError:
                    eff_probe = None
                eff_adv = eff_probe.get("underclaim_advisory") if eff_probe else None
                if eff_adv and not (_has_failed_check(claim) or _has_contradicting_card(claim)):
                    prim_refs = [eid for eid in (eff_adv.get("primary_evidence_ids") or ()) if _is_valid_audit_id(eid) and eid in by_evidence]
                    prim_evs = [by_evidence[eid] for eid in prim_refs]
                    if prim_evs and not any(
                        _g.contradictory_positive_evidence_text(ev, include_outcome_stripped=False, focus_text=claim.get("text", ""))
                        for ev in prim_evs
                    ):
                        cand_verdict = None
                        cand_level = None
                        for trial_verdict in ("supported", "partially_supported"):
                            if _passes_positive_candidate(
                                claim, record, prim_refs, by_evidence, exec_events,
                                verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                                claim_basis=claim.get("claim_basis"), scope=claim.get("scope"), revised_text=claim.get("text"),
                            ):
                                cand_verdict, cand_level = trial_verdict, frozen_level
                                break
                        flags.append({
                            "claim_id": cid,
                            "hook_code": "unsupported_despite_beneficial_primary_effect",
                            "severity": "advisory",
                            "non_blocking": True,
                            "observed_verdict": observed_verdict,
                            "advisory_candidate_verdict": cand_verdict or "insufficient_evidence",
                            "advisory_candidate_level": cand_level,
                            "message": eff_adv["message"],
                            "evidence_ids": prim_refs,
                            "primary_record_ids": eff_adv["primary_record_ids"],
                        })
                        emitted_effect_underclaim = True

            if observed_verdict == "unsupported" and not has_blocker and not emitted_effect_underclaim:
                cand_verdict = None
                cand_level = None
                for trial_verdict in ("supported", "partially_supported"):
                    if _passes_positive_candidate(
                        claim, record, probe_refs, by_evidence, exec_events,
                        verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                        claim_basis=claim.get("claim_basis"), scope=claim.get("scope"), revised_text=claim.get("text"),
                    ):
                        cand_verdict, cand_level = trial_verdict, frozen_level
                        break
                flags.append({
                    "claim_id": cid,
                    "hook_code": "unsupported_without_counterevidence",
                    "severity": "advisory",
                    "non_blocking": True,
                    "observed_verdict": observed_verdict,
                    "advisory_candidate_verdict": cand_verdict or "insufficient_evidence",
                    "advisory_candidate_level": cand_level,
                    "message": f"Claim '{cid}' was marked 'unsupported' without failed checks, contradicting provenance cards, or null/refuting evidence text.",
                    "evidence_ids": probe_refs,
                })

            if (observed_verdict == "insufficient_evidence" or observed_verdict == "partially_supported" or level_downgraded) and not has_blocker:
                rec_text = " ".join(str(record.get(k) or "") for k in ("rationale", "revised_text", "boundary", "condition", "reversal_condition"))
                rev_cond_raw = str(record.get("reversal_condition") or "").strip()
                has_vacuous_rev = bool(rev_cond_raw and _g.is_vacuous_reversal_condition(rev_cond_raw))
                if (_g.BOILERPLATE_OVERHEDGING_RE.search(rec_text) or has_vacuous_rev) and probe_evs:
                    rec_rev = str(record.get("revised_text") or "")
                    claim_rev = str(claim.get("text") or "")
                    if observed_verdict == "insufficient_evidence":
                        rec_text_nums = bool(_claimed_effect_tokens({**claim, "effect": {}}, {"revised_text": rec_rev}))
                        claim_text_nums = bool(_claimed_effect_tokens({**claim, "effect": {}}, {"revised_text": claim_rev}))
                        if rec_text_nums and not claim_text_nums:
                            cand_revs = [r for r in dict.fromkeys((rec_rev, claim_rev)) if r]
                        elif claim_text_nums:
                            cand_revs = [claim_rev]
                        else:
                            cand_revs = [r for r in dict.fromkeys((claim_rev, rec_rev)) if r]
                    else:
                        cand_revs = [rec_rev or claim_rev]
                    cand_verdict = None
                    for probe_rev in cand_revs:
                        probe_dec = {**claim, **record, "verdict": "supported", "revised_text": probe_rev}
                        has_claimed_nums = bool(_claimed_effect_tokens(claim, probe_dec) or _claimed_effect_tokens(claim, claim))
                        if not (has_claimed_nums and effect_numbers_anchored(claim, probe_dec, probe_evs)):
                            continue
                        for trial_verdict in ("supported", "partially_supported"):
                            if _passes_positive_candidate(
                                claim, record, probe_refs, by_evidence, exec_events,
                                verdict=trial_verdict, claim_type=frozen_type, evidence_level=frozen_level,
                                claim_basis=claim.get("claim_basis"), scope=claim.get("scope"), revised_text=probe_rev,
                            ):
                                cand_verdict = trial_verdict
                                break
                        if cand_verdict is not None:
                            break
                    if cand_verdict is not None:
                        flags.append({
                            "claim_id": cid,
                            "hook_code": "possible_boilerplate_overhedging",
                            "severity": "advisory",
                            "non_blocking": True,
                            "observed_verdict": observed_verdict,
                            "advisory_candidate_verdict": cand_verdict,
                            "advisory_candidate_level": frozen_level,
                            "message": f"Claim '{cid}' uses generic over-hedging boilerplate despite anchored quantitative estimates and no failed checks.",
                            "evidence_ids": probe_refs,
                        })

            # Contrastive wording can express a valid limitation on a different outcome.
            dom = record.get("evidence_dominance")
            dom_status = dom.get("asymmetry_status") if isinstance(dom, dict) else None
            rev_body = f"{record.get('revised_text') or ''} {record.get('rationale') or ''}"
            contradicts_dominance = dom_status == "dominant" and observed_verdict == "insufficient_evidence"
            asserts_balance = dom_status not in ("balanced_unresolved", "genuinely_unresolved") and _g.FALSE_BALANCE_RE.search(rev_body)
            if (
                observed_verdict in ("supported", "insufficient_evidence", "partially_supported")
                and not has_blocker
                and (contradicts_dominance or asserts_balance)
            ):
                if _passes_positive_candidate(
                    claim, record, probe_refs, by_evidence, exec_events,
                    verdict="supported", claim_type=frozen_type, evidence_level=frozen_level,
                    claim_basis=claim.get("claim_basis"), scope=claim.get("scope"), revised_text=claim.get("text"),
                ):
                    flags.append({
                        "claim_id": cid,
                        "hook_code": "false_balance_without_asymmetry_justification",
                        "severity": "advisory",
                        "non_blocking": True,
                        "observed_verdict": observed_verdict,
                        "advisory_candidate_verdict": "supported",
                        "advisory_candidate_level": frozen_level,
                        "message": f"Claim '{cid}' asserts evidentiary parity or retreats from declared dominance despite clearing positive gates without counterevidence.",
                        "evidence_ids": probe_refs,
                    })
        except ContractError:
            continue

    for f in findings_list:
        try:
            fid = f.get("id")
            if not _is_valid_audit_id(fid):
                continue
            disp = disp_by_finding.get(fid)
            if not disp or (disp.get("disposition") != "rejected" and disp.get("resolution") != "disagreement"):
                continue
            role = f.get("role")
            if role is not None and role != "underclaim":
                continue
            cid_f = f.get("claim_id")
            if not _is_valid_audit_id(cid_f):
                continue
            claim_f = by_claim.get(cid_f)
            if not claim_f:
                continue
            dec_f = by_record.get(cid_f, {})
            cand_type = f.get("proposed_claim_type") or claim_f.get("claim_type")
            cand_level = f.get("proposed_evidence_level") or claim_f.get("evidence_level")
            if role is None:
                cur_f_type = dec_f.get("claim_type") or claim_f.get("claim_type")
                cur_f_level = dec_f.get("evidence_level") or claim_f.get("evidence_level")
                if (
                    cand_type == cur_f_type
                    and isinstance(cand_type, str)
                    and cand_type in TYPE_LEVELS
                    and cand_level in TYPE_LEVELS[cand_type]
                    and cur_f_level in TYPE_LEVELS[cand_type]
                    and TYPE_LEVELS[cand_type].index(cand_level) <= TYPE_LEVELS[cand_type].index(cur_f_level)
                    and dec_f.get("verdict") in _g.POSITIVE
                ):
                    continue
            raw_f_eids = f.get("evidence_ids") or claim_f.get("evidence_ids")
            f_refs = [r for r in (raw_f_eids if isinstance(raw_f_eids, (list, tuple)) else ()) if _is_valid_audit_id(r)]
            f_evs = [by_evidence[r] for r in f_refs if r in by_evidence]
            if _g._has_failed_check_or_contradiction(claim_f, f_evs):
                continue
            cand_basis = f.get("proposed_claim_basis") or dec_f.get("claim_basis") or claim_f.get("claim_basis")
            cand_scope = f.get("proposed_scope") or dec_f.get("scope") or claim_f.get("scope")
            cand_verdict = None
            for trial_verdict in ("supported", "partially_supported"):
                if _passes_positive_candidate(
                    claim_f, dec_f, f_refs, by_evidence, exec_events,
                    verdict=trial_verdict, claim_type=cand_type, evidence_level=cand_level,
                    claim_basis=cand_basis, scope=cand_scope,
                    revised_text=f.get("proposed_text") or dec_f.get("revised_text") or claim_f.get("text"),
                ):
                    cand_verdict = trial_verdict
                    break
            if cand_verdict is not None:
                flags.append({
                    "claim_id": cid_f,
                    "finding_id": fid,
                    "hook_code": "rejected_underclaim_finding_advisory",
                    "severity": "advisory",
                    "non_blocking": True,
                    "observed_verdict": dec_f.get("verdict") or dec_f.get("stance"),
                    "advisory_candidate_verdict": cand_verdict,
                    "advisory_candidate_level": cand_level,
                    "message": f"Rejected underclaim finding '{fid}' on claim '{cid_f}' proposes {cand_type} x {cand_level} ({cand_verdict}), which clears support and mechanical gates.",
                    "evidence_ids": f_refs,
                })
        except ContractError:
            continue
    return {
        "non_blocking": True,
        "severity": "advisory",
        "is_review": bool(is_review),
        "flag_count": len(flags),
        "flags": flags,
        "lexical_advisory_count": len(lexical_advisories),
        "lexical_advisories": lexical_advisories,
    }


_ENFORCED_HOOK_ERRORS = {
    "possible_boilerplate_overhedging": ("unjustified_overhedging", False),
    "false_balance_without_asymmetry_justification": ("false_balance_neutrality", False),
    "unsupported_despite_beneficial_primary_effect": ("unjustified_underclaim", True),
    "unsupported_without_counterevidence": ("unjustified_underclaim", True),
    "possible_false_abstention": ("unjustified_abstention", True),
    "possible_unjustified_downgrade": ("unjustified_downgrade", True),
}


def enforce_symmetry_adjudication(
    decisions,
    claims,
    evidence,
    findings=None,
    dispositions=None,
    exec_events=None,
    *,
    symmetry_mode: str = "enforced",
):
    """Run symmetry audit before locking adjudication; enforce symmetric burden of proof when mode='enforced'.

    Never forces a false positive verdict: legitimate abstention, downgrade, or unsupported
    verdicts remain allowed whenever the adjudicator provides a concrete, non-boilerplate
    `abstention_justification` naming specific unmodeled blocking_gaps or counterevidence_ids.
    """
    from .contracts import fail

    sym_audit = audit_underclaim_and_abstention(
        decisions,
        claims,
        evidence,
        findings=findings,
        dispositions=dispositions,
        exec_events=exec_events,
        is_review=False,
    )
    sym_audit["symmetry_mode"] = symmetry_mode
    if symmetry_mode != "enforced":
        return sym_audit

    dec_by_cid = {
        d.get("claim_id"): d
        for d in (decisions or ())
        if isinstance(d, dict) and d.get("claim_id")
    }
    rebuttals_accepted = []
    blocking_challenges = []
    for flag in sym_audit["flags"]:
        hook = flag.get("hook_code")
        spec = _ENFORCED_HOOK_ERRORS.get(hook)
        if spec is None:
            continue
        err_code, rebuttable = spec
        cid = flag.get("claim_id")
        dec = dec_by_cid.get(cid) or {}
        just = dec.get("abstention_justification")
        if rebuttable and isinstance(just, dict) and just.get("blocking_gaps") and just.get("reason"):
            flag["rebutted"] = True
            flag["rebuttal_gaps"] = list(just["blocking_gaps"])
            rebuttals_accepted.append({"claim_id": cid, "hook_code": hook, "blocking_gaps": list(just["blocking_gaps"])})
        else:
            flag["rebutted"] = False
            flag["non_blocking"] = False
            flag["severity"] = "blocking"
            blocking_challenges.append((err_code, flag))

    sym_audit["non_blocking"] = len(blocking_challenges) == 0
    sym_audit["rebuttals_accepted"] = rebuttals_accepted
    if blocking_challenges:
        err_code, first_flag = blocking_challenges[0]
        all_hooks = [f["hook_code"] for _, f in blocking_challenges]
        fail(
            err_code,
            f"Symmetric adjudication gate blocked ({', '.join(all_hooks)}): {first_flag['message']} "
            "Either restore the evidenced verdict/level or supply concrete `abstention_justification` "
            "(blocking_gaps + reason) without generic boilerplate.",
        )
    return sym_audit
