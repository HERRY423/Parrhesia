"""Living cross-case evidence synthesis, deduplication guard, and reversal-trigger cascade. Pure stdlib.

Never mutates frozen cases or historical digests. Operates strictly read-only across a
workspace's longitudinal claim graph to:
  1. Extract independent empirical primary/benchmark effect records from effective cases,
     excluding synthetic records, reanalyses/corrections, and duplicate evidence snapshots.
  2. Run DerSimonian-Laird random-effects & fixed-effect meta-analysis within
     linked, compatible comparisons, including Cochran's Q, I^2, tau^2, and
     Student-t 95% prediction intervals.
  3. Track chronological cumulative pooling trajectories to detect convergent replication,
     winner's-curse attenuation (decline effect), heterogeneous divergence, or sign reversal.
  4. Evaluate ancestor claims' executable `reversal_triggers` against both downstream cases
     and the living pooled estimate, surfacing update alerts without mutating history.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Any

from .claim_graph import adjudication_is_effective
from .claims import ESTIMAND_FIELDS
from .contracts import fail, fields, string
from .effects import DIFFERENCE_METRICS, PRIMARY_EFFECT_ROLES, RATIO_METRICS
from .methods import _compute_interaction_heterogeneity
from .triggers import build_claim_graph, collect_claim_triggers, evaluate_case_triggers

_NON_INDEPENDENT_CASE_RELATIONS = ("reanalysis", "correction")
_COMPARISON_LINKS = ("replicates", "refutes", "reverses")
_UNKNOWN_SCOPE = {"", "unknown", "na", "n/a", "not_identifiable"}

_TRIAL_REGISTRY_RE = re.compile(
    r"\b(?:NCT\d{8}|ISRCTN\d{8}|EudraCT\s*\d{4}-\d{6}-\d{2}|ChiCTR(?:\d{8,14}|-[A-Za-z]{2,4}-\d{6,10})|ACTRN\d{14}|CRD\d{11})\b",
    re.IGNORECASE,
)
_ACCESSION_RE = re.compile(
    r"\b(?:GSE\d{3,}|PRJNA\d{4,}|PRJEB\d{4,}|SRP\d{5,}|phs\d{6}(?:\.v\d+)?|EGAS\d{11}|E-MTAB-\d{3,}|TCGA-[A-Za-z0-9]{2,8}|MIMIC-(?:III|IV))\b",
    re.IGNORECASE,
)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_ALPHA_TOKEN_RE = re.compile(r"[a-z\u4e00-\u9fff]{3,}")
_BOILERPLATE_STAT_TOKENS = frozenset({
    "and", "the", "for", "with", "from", "into", "that", "this", "were", "was",
    "are", "not", "all", "cohort", "study", "group", "arm", "ci", "hr", "rr",
    "or", "sd", "se", "df", "auc", "auroc", "pval", "null", "vs", "per",
})


def _scale_for_metric(metric: str) -> str | None:
    if metric in RATIO_METRICS:
        return "log"
    if metric in DIFFERENCE_METRICS:
        return "linear"
    return None


def _normalize_cohort_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    norm = " ".join(value.split()).casefold()
    return norm or None


def _evidence_lineage_hashes(case: dict[str, Any], claim: dict[str, Any], rec: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    """Return (direct_hashes, ancestor_hashes, visited_eids) by traversing derived_from_evidence_ids."""
    by_eid = {e.get("evidence_id"): e for e in (case.get("evidence") or ()) if isinstance(e, dict)}
    direct_hashes: set[str] = set()
    ancestor_hashes: set[str] = set()
    ev_ids = [rec.get("evidence_id")] if rec.get("evidence_id") else list(claim.get("evidence_ids") or ())
    seen_eids: set[str] = set()
    pending_ancestors: list[str] = []

    for eid in ev_ids:
        if not isinstance(eid, str) or eid in seen_eids:
            continue
        seen_eids.add(eid)
        entry = by_eid.get(eid)
        if entry:
            if isinstance(entry.get("sha256"), str):
                direct_hashes.add(entry["sha256"])
            for parent_eid in entry.get("derived_from_evidence_ids") or ():
                if isinstance(parent_eid, str) and parent_eid not in seen_eids:
                    pending_ancestors.append(parent_eid)

    binding = rec.get("artifact_binding")
    if isinstance(binding, dict) and isinstance(binding.get("source_sha256"), str):
        direct_hashes.add(binding["source_sha256"])

    while pending_ancestors:
        peid = pending_ancestors.pop()
        if peid in seen_eids:
            continue
        seen_eids.add(peid)
        pentry = by_eid.get(peid)
        if not pentry:
            continue
        if isinstance(pentry.get("sha256"), str):
            ancestor_hashes.add(pentry["sha256"])
        for gp_eid in pentry.get("derived_from_evidence_ids") or ():
            if isinstance(gp_eid, str) and gp_eid not in seen_eids:
                pending_ancestors.append(gp_eid)

    return direct_hashes, ancestor_hashes, seen_eids


def _extract_cohort_identifiers(
    case: dict[str, Any],
    claim: dict[str, Any],
    rec: dict[str, Any],
    lineage_eids: set[str],
) -> tuple[set[str], set[str]]:
    """Extract standardized (registry_or_accession_ids, source_dois) from case, claim, record, and lineage evidence."""
    texts: list[str] = []
    for key in ("cohort_id", "quote_substring", "notes", "endpoint"):
        val = rec.get(key)
        if isinstance(val, str) and val:
            texts.append(val)
    for key in ("scope", "text"):
        val = claim.get(key)
        if isinstance(val, str) and val:
            texts.append(val)
    by_eid = {e.get("evidence_id"): e for e in (case.get("evidence") or ()) if isinstance(e, dict)}
    for eid in lineage_eids:
        ev = by_eid.get(eid)
        if not ev:
            continue
        for key in ("quote", "location", "path", "provenance"):
            val = ev.get(key)
            if isinstance(val, str) and val:
                texts.append(val)

    blob = "\n".join(texts)
    reg_ids: set[str] = set()
    for match in _TRIAL_REGISTRY_RE.findall(blob):
        tok = re.sub(r"\s+", "", match).upper()
        reg_ids.add(tok)
    for match in _ACCESSION_RE.findall(blob):
        tok = re.sub(r"\.v\d+$", "", match.strip(), flags=re.IGNORECASE)
        reg_ids.add(tok.upper())

    dois: set[str] = set()
    for match in _DOI_RE.findall(blob):
        cleaned = match.rstrip(".,;:)]>").casefold()
        if cleaned:
            dois.add(f"doi:{cleaned}")
    return reg_ids, dois


def _quote_text_for_record(case: dict[str, Any], rec: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(rec.get("quote_substring"), str) and rec["quote_substring"].strip():
        parts.append(rec["quote_substring"].strip())
    by_eid = {e.get("evidence_id"): e for e in (case.get("evidence") or ()) if isinstance(e, dict)}
    ev = by_eid.get(rec.get("evidence_id"))
    if ev and isinstance(ev.get("quote"), str) and ev["quote"].strip():
        q = ev["quote"].strip()
        if q not in parts:
            parts.append(q)
    return " ".join(parts)


def _semantic_shingles(text: str) -> tuple[list[str], set[tuple[str, str, str]]]:
    tokens = [
        tok for tok in _ALPHA_TOKEN_RE.findall(text.casefold())
        if tok not in _BOILERPLATE_STAT_TOKENS
    ]
    if len(tokens) < 10:
        return tokens, set()
    shingles = {(tokens[i], tokens[i + 1], tokens[i + 2]) for i in range(len(tokens) - 2)}
    return tokens, shingles


def _check_suspected_cohort_overlap(study: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any] | None:
    """Layer 2 screen: flag quantitative clones or high-shingle quote duplicates for manual verification."""
    n_cur = study.get("n")
    n_prev = prior.get("n")
    if (
        isinstance(n_cur, int)
        and isinstance(n_prev, int)
        and n_cur >= 20
        and n_cur == n_prev
        and round(study["estimate"], 4) == round(prior["estimate"], 4)
        and round(study["ci_low"], 4) == round(prior["ci_low"], 4)
        and round(study["ci_high"], 4) == round(prior["ci_high"], 4)
    ):
        return {
            "case_id": study["case_id"],
            "claim_id": study["claim_id"],
            "record_id": study["record_id"],
            "suspected_prior_case_id": prior["case_id"],
            "suspected_prior_record_id": prior["record_id"],
            "signal": "exact_sample_and_effect_clone",
            "detail": (
                f"Identical n={n_cur} and point/CI bounds ({study['estimate']}, "
                f"[{study['ci_low']}, {study['ci_high']}]) match prior case '{prior['case_id']}'."
            ),
        }

    # If both declared distinct explicit cohort_id values, skip fuzzy text shingle warnings.
    c_cur = study.get("cohort_id")
    c_prev = prior.get("cohort_id")
    if c_cur is not None and c_prev is not None and c_cur != c_prev:
        return None

    sh_cur = study.get("quote_shingles") or set()
    sh_prev = prior.get("quote_shingles") or set()
    if len(sh_cur) >= 8 and len(sh_prev) >= 8:
        union_n = len(sh_cur | sh_prev)
        jacc = len(sh_cur & sh_prev) / union_n if union_n else 0.0
        if jacc >= 0.65:
            return {
                "case_id": study["case_id"],
                "claim_id": study["claim_id"],
                "record_id": study["record_id"],
                "suspected_prior_case_id": prior["case_id"],
                "suspected_prior_record_id": prior["record_id"],
                "signal": "high_text_shingle_overlap",
                "jaccard_similarity": round(jacc, 4),
                "detail": (
                    f"Evidence quote 3-gram Jaccard={jacc:.2f} (>=0.65) overlaps prior case "
                    f"'{prior['case_id']}' without distinct cohort_id."
                ),
            }
    return None


def _is_synthetic_record(case: dict[str, Any], claim: dict[str, Any], rec: dict[str, Any]) -> bool:
    if claim.get("claim_basis") == "synthetic":
        return True
    by_eid = {e.get("evidence_id"): e for e in (case.get("evidence") or ()) if isinstance(e, dict)}
    eid = rec.get("evidence_id")
    if eid and eid in by_eid:
        ev = by_eid[eid]
        if ev.get("provenance") == "synthetic" or ev.get("kind") == "synthetic":
            return True
    return False


def _scope_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _comparison_scope(claim: dict, decision: dict) -> tuple[str, ...]:
    claim_type = decision.get("claim_type") or claim.get("claim_type")
    if claim_type in ("causal_effect", "necessity", "sufficiency"):
        estimand = (claim.get("causal_basis") or {}).get("estimand") or {}
        return tuple(_scope_text(estimand.get(field, "")) for field in ESTIMAND_FIELDS)
    return (_scope_text(decision.get("scope") or claim.get("scope") or ""),)


def _linked_groups(studies: list[dict], graph: dict):
    """Connect compatible claim observations only via declared comparison links."""
    nodes_by_case = defaultdict(set)
    by_node = defaultdict(set)
    for study in studies:
        nid = study["node_id"]
        by_node[nid]
        nodes_by_case[study["case_id"]].add(nid)

    explicit_pairs = set()
    for edge in graph["claim_edges"]:
        left, right = edge["from_node_id"], edge["to_node_id"]
        explicit_pairs.add((edge["from_case_id"], edge["to_case_id"]))
        if edge["relation"] in _COMPARISON_LINKS and left in by_node and right in by_node:
            by_node[left].add(right)
            by_node[right].add(left)
    for edge in graph["case_edges"]:
        pair = edge["from_case_id"], edge["to_case_id"]
        if edge["edge_type"] != "replication" or pair in explicit_pairs:
            continue
        parents, successors = (nodes_by_case.get(case_id, ()) for case_id in pair)
        if len(parents) == len(successors) == 1:
            left, right = next(iter(parents)), next(iter(successors))
            by_node[left].add(right)
            by_node[right].add(left)

    visited = set()
    for nid in by_node:
        if nid in visited:
            continue
        component = {nid}
        pending = [nid]
        while pending:
            node = pending.pop()
            remaining = by_node[node] - component
            component.update(remaining)
            pending.extend(remaining)
        visited.update(component)
        yield [study for study in studies if study["node_id"] in component]


def _pool(studies: list[dict], scale: str, null_val: float, alpha: float, ci_level: float) -> dict:
    return _compute_interaction_heterogeneity({
        "mode": "interaction_heterogeneity",
        "scale": scale,
        "alpha": alpha,
        "ci_level": ci_level,
        "null_value": null_val,
        "studies": [
            {"id": f"study-{index}", **{k: s[k] for k in ("estimate", "ci_low", "ci_high", "ci_level", "df") if k in s}}
            for index, s in enumerate(studies, 1)
        ],
    })


def _trajectory_pattern(
    studies: list[dict[str, Any]],
    meta_res: dict[str, Any],
    scale: str,
    null_val: float,
    alpha: float,
    ci_level: float,
) -> tuple[str, list[dict[str, Any]]]:
    """Build chronological cumulative RE trajectory and classify temporal drift."""
    x_null = math.log(null_val) if scale == "log" else null_val

    def _dist_from_null(val: float) -> float:
        return abs((math.log(val) if scale == "log" else val) - x_null)

    def _sign_vs_null(val: float) -> int:
        d = (math.log(val) if scale == "log" else val) - x_null
        if abs(d) < 1e-12:
            return 0
        return 1 if d > 0 else -1

    cumulative: list[dict[str, Any]] = []
    first = studies[0]
    cumulative.append({
        "step": 1,
        "added_case_id": first["case_id"],
        "k_studies": 1,
        "estimate": first["estimate"],
        "ci_low": first["ci_low"],
        "ci_high": first["ci_high"],
        "ci_level": first["ci_level"],
        "i2_percent": 0.0,
    })
    for k in range(2, len(studies) + 1):
        m = meta_res if k == len(studies) else _pool(studies[:k], scale, null_val, alpha, ci_level)
        re_block = m["random_effects"]
        cumulative.append({
            "step": k,
            "added_case_id": studies[k - 1]["case_id"],
            "k_studies": k,
            "estimate": re_block["estimate"],
            "ci_low": re_block["ci_low"],
            "ci_high": re_block["ci_high"],
            "ci_level": ci_level,
            "i2_percent": m["i2_percent"],
            "excludes_null": re_block["excludes_null"],
        })

    init_est = first["estimate"]
    final_re = meta_res["random_effects"]
    final_est = final_re["estimate"]
    init_dist = _dist_from_null(init_est)
    final_dist = _dist_from_null(final_est)
    init_sign = _sign_vs_null(init_est)
    final_sign = _sign_vs_null(final_est)

    if init_sign != 0 and final_sign != 0 and init_sign != final_sign:
        return "sign_reversal_or_nullified", cumulative
    if not final_re["excludes_null"]:
        return "pooled_interval_includes_null", cumulative
    if init_dist > 1e-9 and final_dist < 0.65 * init_dist:
        return "attenuating_decline_effect", cumulative
    if meta_res["i2_percent"] >= 50.0 or meta_res.get("prediction_interval_crosses_null") is True:
        return "heterogeneous_divergence", cumulative
    return "convergent_replication", cumulative


def synthesize_claim_lineage(
    cases: list[dict[str, Any]],
    *,
    case_id: str | None = None,
    claim_id: str | None = None,
    metric_filter: str | None = None,
    alpha: float = 0.05,
    ci_level: float = 0.95,
) -> dict[str, Any]:
    """Perform read-only living synthesis and reversal-trigger cascade across a workspace's claim lineage."""
    graph = build_claim_graph(cases, case_id=case_id, claim_id=claim_id)
    keep_case_ids = {n["case_id"] for n in graph["case_nodes"]}
    keep_node_ids = {n["node_id"] for n in graph["claim_nodes"]}
    standing_by_node = {n["node_id"]: n["active_standing"] for n in graph["claim_nodes"]}

    scoped_cases = sorted(
        [c for c in cases if c["case_id"] in keep_case_ids],
        key=lambda c: (c.get("created_at") or "", c["case_id"]),
    )

    excluded_non_effective: list[dict[str, Any]] = []
    excluded_synthetic: list[dict[str, Any]] = []
    excluded_non_independent: list[dict[str, Any]] = []
    excluded_ineligible: list[dict[str, Any]] = []
    grouped_studies: dict[tuple, list[dict[str, Any]]] = {}
    included_case_ids: set[str] = set()

    for case in scoped_cases:
        cid = case["case_id"]
        if not adjudication_is_effective(case):
            excluded_non_effective.append({"case_id": cid, "state": case.get("state"), "reason": "adjudication_not_effective"})
            continue

        rel = case.get("case_relation")
        if rel in _NON_INDEPENDENT_CASE_RELATIONS:
            excluded_non_independent.append({
                "case_id": cid,
                "case_relation": rel,
                "reason": f"Excluded from independent study pooling because case_relation='{rel}' reanalyzes prior data.",
            })
            continue

        dec_by_cid = {
            d["claim_id"]: d
            for d in ((case.get("adjudication") or {}).get("decisions") or ())
            if isinstance(d, dict) and d.get("claim_id")
        }

        for clm in case.get("claims") or ():
            nid = f"{cid}:{clm['id']}"
            if nid not in keep_node_ids:
                continue
            standing = standing_by_node.get(nid, "current")
            if standing in ("superseded",):
                continue
            dec = dec_by_cid.get(clm["id"]) or {}
            claim_type = dec.get("claim_type") or clm.get("claim_type")
            scope = _comparison_scope(clm, dec)
            for rec in clm.get("effect_records") or ():
                if not isinstance(rec, dict):
                    continue
                if rec.get("endpoint_role") not in PRIMARY_EFFECT_ROLES:
                    continue
                metric = rec.get("metric")
                if not isinstance(metric, str):
                    continue
                if metric_filter and metric != metric_filter:
                    continue
                scale = _scale_for_metric(metric)
                if scale is None:
                    continue
                origin = {"case_id": cid, "claim_id": clm["id"], "record_id": rec.get("id")}
                if _is_synthetic_record(case, clm, rec):
                    excluded_synthetic.append(origin)
                    continue

                endpoint = _scope_text(rec.get("endpoint") or "")
                if endpoint in _UNKNOWN_SCOPE or any(part in _UNKNOWN_SCOPE for part in scope):
                    excluded_ineligible.append({**origin, "reason": "unresolved_comparison_scope"})
                    continue
                if any(rec.get(k) is None for k in ("ci_low", "ci_high", "ci_level")):
                    excluded_ineligible.append({**origin, "reason": "missing_source_confidence_interval_or_level"})
                    continue

                est = float(rec["estimate"])
                lo = float(rec["ci_low"])
                hi = float(rec["ci_high"])
                null_val = float(rec.get("null_value", 1.0 if scale == "log" else 0.0))
                if hi <= lo or (scale == "log" and min(est, lo, hi, null_val) <= 0.0):
                    excluded_ineligible.append({**origin, "reason": "invalid_interval_on_working_scale"})
                    continue
                method = rec.get("inference_method", "unknown")
                compatible_methods = ("unknown", "log_wald") if scale == "log" else ("unknown", "wald", "student_t")
                if method not in compatible_methods or (method == "student_t" and rec.get("df") is None):
                    excluded_ineligible.append({**origin, "reason": "unsupported_source_interval_method"})
                    continue
                direct_hashes, ancestor_hashes, lineage_eids = _evidence_lineage_hashes(case, clm, rec)
                ev_hashes = direct_hashes | ancestor_hashes
                if not ev_hashes:
                    excluded_ineligible.append({**origin, "reason": "no_evidence_snapshot_binding"})
                    continue

                reg_ids, dois = _extract_cohort_identifiers(case, clm, rec, lineage_eids)
                cohort_id_norm = _normalize_cohort_id(rec.get("cohort_id"))
                _, quote_shingles = _semantic_shingles(_quote_text_for_record(case, rec))

                key = (metric, scale, endpoint, rec["endpoint_role"], rec.get("scale", "unit"), null_val,
                       claim_type, scope, rec.get("beneficial_if", ""))
                grouped_studies.setdefault(key, []).append({
                    **origin,
                    "id": f"{cid}:{clm['id']}:{rec.get('id', 'r')}",
                    "node_id": nid,
                    "direct_hashes": sorted(direct_hashes),
                    "ancestor_hashes": sorted(ancestor_hashes),
                    "evidence_hashes": sorted(ev_hashes),
                    "cohort_id": cohort_id_norm,
                    "registry_ids": sorted(reg_ids),
                    "source_dois": sorted(dois),
                    "quote_shingles": quote_shingles,
                    "endpoint": rec.get("endpoint"),
                    "verdict": dec.get("verdict"),
                    "active_standing": standing,
                    "estimate": est,
                    "ci_low": lo,
                    "ci_high": hi,
                    "ci_level": rec["ci_level"],
                    "interval_method": "working_normal_approximation" if method == "unknown" else method,
                    **({"df": rec["df"]} if method == "student_t" else {}),
                    "n": rec.get("n"),
                    "null_value": null_val,
                })

    metric_syntheses: list[dict[str, Any]] = []
    pooled_by_case = defaultdict(lambda: defaultdict(list))
    compatible_records = defaultdict(lambda: defaultdict(set))
    suspected_cohort_overlaps: list[dict[str, Any]] = []
    seen_suspect_pairs: set[tuple[str, str, str, str]] = set()
    for (metric, scale, _, role, reported_scale, null_val, claim_type, scope, _), candidates in sorted(grouped_studies.items()):
        for linked in _linked_groups(candidates, graph):
            studies: list[dict[str, Any]] = []
            included_studies_raw: list[dict[str, Any]] = []
            seen_cases: set[str] = set()
            seen_direct_hashes: dict[str, str] = {}
            seen_all_hashes: dict[str, str] = {}
            seen_cohorts: dict[str, str] = {}
            seen_registries: dict[str, dict[str, Any]] = {}
            seen_dois: dict[str, dict[str, Any]] = {}

            for study in linked:
                cid = study["case_id"]
                omitted_base = {k: study[k] for k in ("case_id", "claim_id", "record_id")}
                if cid in seen_cases:
                    excluded_non_independent.append({
                        **omitted_base,
                        "overlap_mechanism": "same_case",
                        "reason": "A compatible comparison already has a primary observation from this case.",
                    })
                    continue

                direct_hit = next((seen_direct_hashes[h] for h in study["direct_hashes"] if h in seen_direct_hashes), None)
                if direct_hit is not None:
                    excluded_non_independent.append({
                        **omitted_base,
                        "overlapping_prior_case_id": direct_hit,
                        "overlap_mechanism": "direct_evidence_sha256",
                        "reason": "Evidence snapshot SHA-256 duplicates an included observation.",
                    })
                    continue

                anc_hit = next((seen_all_hashes[h] for h in study["evidence_hashes"] if h in seen_all_hashes), None)
                if anc_hit is not None:
                    excluded_non_independent.append({
                        **omitted_base,
                        "overlapping_prior_case_id": anc_hit,
                        "overlap_mechanism": "ancestor_evidence_sha256",
                        "reason": "Derived evidence traces via derived_from_evidence_ids to an ancestor SHA-256 shared with an included observation.",
                    })
                    continue

                cur_cohort = study.get("cohort_id")
                if cur_cohort is not None and cur_cohort in seen_cohorts:
                    excluded_non_independent.append({
                        **omitted_base,
                        "overlapping_prior_case_id": seen_cohorts[cur_cohort],
                        "overlap_mechanism": "explicit_cohort_id",
                        "cohort_identifier": cur_cohort,
                        "reason": f"Explicit cohort_id '{cur_cohort}' duplicates an included cohort observation.",
                    })
                    continue

                reg_match = next(((tok, seen_registries[tok]) for tok in study["registry_ids"] if tok in seen_registries), None)
                if reg_match is not None:
                    tok, prior_meta = reg_match
                    prior_cohort = prior_meta.get("cohort_id")
                    if not (cur_cohort is not None and prior_cohort is not None and cur_cohort != prior_cohort):
                        excluded_non_independent.append({
                            **omitted_base,
                            "overlapping_prior_case_id": prior_meta["case_id"],
                            "overlap_mechanism": "registry_or_accession_id",
                            "cohort_identifier": tok,
                            "reason": f"Shared registry/accession cohort identifier '{tok}' duplicates an included observation.",
                        })
                        continue

                doi_match = next(((tok, seen_dois[tok]) for tok in study["source_dois"] if tok in seen_dois), None)
                if doi_match is not None:
                    tok, prior_meta = doi_match
                    prior_cohort = prior_meta.get("cohort_id")
                    if not (cur_cohort is not None and prior_cohort is not None and cur_cohort != prior_cohort):
                        excluded_non_independent.append({
                            **omitted_base,
                            "overlapping_prior_case_id": prior_meta["case_id"],
                            "overlap_mechanism": "shared_source_doi",
                            "cohort_identifier": tok,
                            "reason": f"Shared source DOI '{tok}' without distinct explicit cohort_id values duplicates an included observation.",
                        })
                        continue

                for prior_study in included_studies_raw:
                    suspect = _check_suspected_cohort_overlap(study, prior_study)
                    if suspect is not None:
                        skey = (study["case_id"], str(study.get("record_id")), prior_study["case_id"], suspect["signal"])
                        if skey not in seen_suspect_pairs:
                            seen_suspect_pairs.add(skey)
                            suspected_cohort_overlaps.append(suspect)

                included_studies_raw.append(study)
                studies.append({k: v for k, v in study.items() if k != "quote_shingles"})
                seen_cases.add(cid)
                for h in study["direct_hashes"]:
                    seen_direct_hashes.setdefault(h, cid)
                for h in study["evidence_hashes"]:
                    seen_all_hashes.setdefault(h, cid)
                if cur_cohort is not None:
                    seen_cohorts.setdefault(cur_cohort, cid)
                for tok in study["registry_ids"]:
                    seen_registries.setdefault(tok, {"case_id": cid, "cohort_id": cur_cohort})
                for tok in study["source_dois"]:
                    seen_dois.setdefault(tok, {"case_id": cid, "cohort_id": cur_cohort})
            if not studies:
                continue

            for study in studies:
                for peer in studies:
                    if study is not peer:
                        compatible_records[study["node_id"]][peer["case_id"]].add(peer["record_id"])

            cs = {
                "metric": metric,
                "scale": scale,
                "reported_scale": reported_scale,
                "endpoint": studies[0]["endpoint"],
                "endpoint_role": role,
                "claim_type": claim_type,
                "comparison_scope": dict(zip(ESTIMAND_FIELDS, scope)) if len(scope) > 1 else {"scope": scope[0]},
                "null_value": null_val,
                "independent_study_count": len(studies),
                "studies": studies,
                "meta_analysis": None,
                "trajectory_pattern": "single_study_unreplicated",
                "cumulative_trajectory": [
                    {
                        "step": 1,
                        "added_case_id": studies[0]["case_id"],
                        "k_studies": 1,
                        "estimate": studies[0]["estimate"],
                        "ci_low": studies[0]["ci_low"],
                        "ci_high": studies[0]["ci_high"],
                        "ci_level": studies[0]["ci_level"],
                        "i2_percent": 0.0,
                    }
                ],
            }
            if len(studies) >= 2:
                meta = _pool(studies, scale, null_val, alpha, ci_level)
                pattern, cumulative = _trajectory_pattern(studies, meta, scale, null_val, alpha, ci_level)
                cs.update(meta_analysis=meta, trajectory_pattern=pattern, cumulative_trajectory=cumulative)
                re_block = meta["random_effects"]
                pooled = {
                    "id": f"pooled_{metric}",
                    "endpoint": cs["endpoint"],
                    "endpoint_role": role,
                    "metric": metric,
                    "estimate": re_block["estimate"],
                    "ci_low": re_block["ci_low"],
                    "ci_high": re_block["ci_high"],
                    "ci_level": ci_level,
                    "p_value": re_block["p_value"],
                    "null_value": null_val,
                }
                for study in studies:
                    included_case_ids.add(study["case_id"])
                    pooled_by_case[study["case_id"]][study["claim_id"]].append(pooled)
            metric_syntheses.append(cs)

    # Evaluate ancestor reversal triggers against downstream effective cases AND the living pooled estimate.
    effective_cases = [c for c in scoped_cases if adjudication_is_effective(c)]
    triggered_ancestors: list[dict[str, Any]] = []
    seen_fired_keys: set[tuple[str, str, str, str]] = set()
    for idx, anc in enumerate(effective_cases):
        has_trigs = any(
            collect_claim_triggers(cl, next((d for d in ((anc.get("adjudication") or {}).get("decisions") or ()) if d.get("claim_id") == cl["id"]), None))
            for cl in (anc.get("claims") or ())
        )
        if not has_trigs:
            continue
        downstream_eff = [d for d in effective_cases[idx + 1:] if anc["case_id"] in (d.get("prior_case_ids") or ()) or d.get("supersedes_case_id") == anc["case_id"]]
        for ds in downstream_eff:
            scoped_records = {
                cl["id"]: compatible_records.get(f"{anc['case_id']}:{cl['id']}", {}).get(ds["case_id"], set())
                for cl in anc["claims"]
            }
            ev_res = evaluate_case_triggers(anc, against_case=ds, against_effect_record_ids=scoped_records)
            for ce in ev_res["claim_evaluations"]:
                for tr in ce["triggers"]:
                    if tr["fired"]:
                        key = (anc["case_id"], ce["claim_id"], tr["id"], ds["case_id"])
                        if key not in seen_fired_keys:
                            seen_fired_keys.add(key)
                            triggered_ancestors.append({
                                "ancestor_case_id": anc["case_id"],
                                "ancestor_claim_id": ce["claim_id"],
                                "trigger_id": tr["id"],
                                "trigger_kind": tr["kind"],
                                "target_verdict": tr["target_verdict"],
                                "fired_by": "downstream_case",
                                "source_case_id": ds["case_id"],
                                "detail": tr.get("detail"),
                                "standing_alert": "ancestor_reversal_trigger_fired_update_needed",
                            })
        pooled_claims = pooled_by_case.get(anc["case_id"])
        if pooled_claims:
            pool_eval = evaluate_case_triggers(anc, observations={
                "claims": {clmid: {"effect_records": records} for clmid, records in pooled_claims.items()},
            })
            for ce in pool_eval["claim_evaluations"]:
                for tr in ce["triggers"]:
                    if tr["fired"]:
                        key = (anc["case_id"], ce["claim_id"], tr["id"], "living_pooled_meta")
                        if key not in seen_fired_keys:
                            seen_fired_keys.add(key)
                            triggered_ancestors.append({
                                "ancestor_case_id": anc["case_id"],
                                "ancestor_claim_id": ce["claim_id"],
                                "trigger_id": tr["id"],
                                "trigger_kind": tr["kind"],
                                "target_verdict": tr["target_verdict"],
                                "fired_by": "living_pooled_meta",
                                "source_case_id": None,
                                "detail": tr.get("detail"),
                                "standing_alert": "ancestor_reversal_trigger_fired_by_pooled_meta",
                            })

    # Determine overall living status & next actions
    pooled_groups = [ms for ms in metric_syntheses if ms["independent_study_count"] >= 2 and ms["meta_analysis"] is not None]
    any_reversed_standing = any(n["active_standing"] in ("reversed", "refuted") for n in graph["claim_nodes"])
    next_actions: list[dict[str, Any]] = []

    if triggered_ancestors:
        for ta in triggered_ancestors[:4]:
            next_actions.append({
                "priority": "high",
                "action_kind": "record_formal_lineage_reversal",
                "reason": f"Trigger '{ta['trigger_id']}' on {ta['ancestor_case_id']}:{ta['ancestor_claim_id']} fired via {ta['fired_by']}.",
                "decision_impact": (
                    f"Create a follow-up case linking prior_claim_links(prior_case_id='{ta['ancestor_case_id']}', "
                    f"prior_claim_id='{ta['ancestor_claim_id']}', relation='reverses', triggered_reversal_id='{ta['trigger_id']}') "
                    "to formally update active standing without mutating frozen history."
                ),
            })

    if not pooled_groups:
        living_status = "contested_or_reversed" if (any_reversed_standing or triggered_ancestors) else "insufficient_independent_studies"
        if excluded_non_independent:
            next_actions.append({
                "priority": "medium",
                "action_kind": "acquire_independent_cohort_replication",
                "reason": f"{len(excluded_non_independent)} follow-up record(s) were reanalyses or SHA-256 duplicate datasets and excluded from independent pooling.",
                "decision_impact": "Do not treat same-dataset reanalyses as independent replications.",
            })
    else:
        any_nullified = any(ms["trajectory_pattern"] == "sign_reversal_or_nullified" for ms in pooled_groups)
        any_hetero = any(ms["trajectory_pattern"] in ("heterogeneous_divergence", "attenuating_decline_effect") for ms in pooled_groups)
        if any_reversed_standing or triggered_ancestors or any_nullified:
            living_status = "contested_or_reversed"
        elif any(ms["trajectory_pattern"] == "pooled_interval_includes_null" for ms in pooled_groups):
            living_status = "pooled_inconclusive"
        elif any_hetero:
            living_status = "pooled_positive_but_heterogeneous"
            next_actions.append({
                "priority": "medium",
                "action_kind": "scope_generalizability_and_test_effect_modifiers",
                "reason": "Living pooled RE excludes null, but cross-study heterogeneity (I^2/PI) or attenuation is present.",
                "decision_impact": "Retain average effect while scoping transferability and investigating study-level modifiers.",
            })
        elif suspected_cohort_overlaps:
            living_status = "suspected_duplicate_cohort_review_needed"
        else:
            living_status = "replicated_consistent"
            next_actions.append({
                "priority": "low",
                "action_kind": "retain_replicated_conclusion",
                "reason": f"Consistent random-effects pooling across {len(included_case_ids)} independent cases with low heterogeneity.",
                "decision_impact": "Avoid underclaiming replicated multi-study findings; maintain active monitoring triggers.",
            })

    if suspected_cohort_overlaps:
        next_actions.append({
            "priority": "high",
            "action_kind": "verify_cohort_independence",
            "reason": f"{len(suspected_cohort_overlaps)} pooled study pair(s) triggered suspected semantic/numerical cohort overlap.",
            "decision_impact": "Verify cohort independence or supply explicit distinct `cohort_id` / `case_relation='reanalysis'` before treating replication as independent.",
        })

    if suspected_cohort_overlaps:
        independence_basis = "declared_comparison_links_lineage_hashes_and_cohort_ids_checked; suspected_cohort_overlap_flagged"
    elif pooled_groups and all(
        all(s.get("cohort_id") for s in ms["studies"])
        and len({s.get("cohort_id") for s in ms["studies"]}) == len(ms["studies"])
        for ms in pooled_groups
    ):
        independence_basis = "declared_comparison_links_lineage_hashes_and_explicit_distinct_cohort_ids_verified"
    else:
        independence_basis = "declared_comparison_links_lineage_hashes_and_registry_doi_screened; unlabelled_subcohort_overlap_not_proven_absent"

    return {
        "mode": "lineage_synthesis",
        "filter": {"case_id": case_id, "claim_id": claim_id, "metric": metric_filter},
        "scoped_case_count": len(scoped_cases),
        "independent_pooled_case_count": len(included_case_ids),
        "independent_pooled_case_ids": sorted(included_case_ids),
        "living_status": living_status,
        "metric_syntheses": metric_syntheses,
        "triggered_ancestors": triggered_ancestors,
        "triggered_ancestor_count": len(triggered_ancestors),
        "independence_basis": independence_basis,
        "excluded_ineligible": excluded_ineligible,
        "deduplication_guard": {
            "excluded_non_effective_count": len(excluded_non_effective),
            "excluded_non_effective": excluded_non_effective,
            "excluded_synthetic_count": len(excluded_synthetic),
            "excluded_synthetic": excluded_synthetic,
            "excluded_non_independent_count": len(excluded_non_independent),
            "excluded_non_independent": excluded_non_independent,
            "suspected_cohort_overlap_count": len(suspected_cohort_overlaps),
            "suspected_cohort_overlaps": suspected_cohort_overlaps,
        },
        "living_next_actions": next_actions,
        "scientific_validity": "computable_diagnostic_only_not_empirical_proof",
    }


def dispatch_lineage_synthesis(cases: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    """Validate analyze_design(mode='lineage_synthesis') arguments and run living synthesis."""
    fields(
        payload,
        {"mode", "case_id", "claim_id", "metric", "alpha", "ci_level"},
        {"mode"},
        "analyze_design.lineage_synthesis",
    )
    cid = string(payload["case_id"], "case_id", maximum=200) if "case_id" in payload else None
    clmid = string(payload["claim_id"], "claim_id", maximum=200) if "claim_id" in payload else None
    metric = string(payload["metric"], "metric", maximum=64) if "metric" in payload else None
    alpha = payload.get("alpha", 0.05)
    ci_level = payload.get("ci_level", 0.95)
    for nm, val in (("alpha", alpha), ("ci_level", ci_level)):
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not (0.0 < float(val) < 1.0):
            fail("invalid_value", f"{nm} must lie in (0, 1)")
    return synthesize_claim_lineage(
        cases,
        case_id=cid,
        claim_id=clmid,
        metric_filter=metric,
        alpha=float(alpha),
        ci_level=float(ci_level),
    )
