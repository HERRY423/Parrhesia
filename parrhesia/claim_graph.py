"""Longitudinal cross-case claim graph DAG construction and active standing computation. Pure stdlib."""
from __future__ import annotations

from typing import Any, Callable

from .contracts import fail

_POSITIVE_VERDICTS = ("supported", "partially_supported")
_STANDING_PRECEDENCE = (
    ("reverses", "reversed"),
    ("refutes", "refuted"),
    ("supersedes", "superseded"),
    ("narrows", "narrowed"),
    ("refines", "refined"),
    ("replicates", "replicated"),
)


def _detect_cycles(adj: dict[str, list[str]]) -> bool:
    state: dict[str, int] = {}

    def _visit(node: str) -> bool:
        st = state.get(node, 0)
        if st == 1:
            return True
        if st == 2:
            return False
        state[node] = 1
        for nxt in adj.get(node, ()):
            if _visit(nxt):
                return True
        state[node] = 2
        return False

    return any(_visit(n) for n in adj if state.get(n, 0) == 0)


def _compute_active_standing(
    node_id: str,
    case_id: str,
    incoming_edges: list[dict[str, Any]],
    superseded_case_ids: set[str],
    dec_by_node: dict[str, dict | None],
) -> str:
    effective_relations: set[str] = set()
    for edge in incoming_edges:
        rel = edge["relation"]
        ds_dec = dec_by_node.get(edge["to_node_id"])
        if edge.get("status") != "effective" or ds_dec is None or ds_dec.get("verdict") not in _POSITIVE_VERDICTS:
            # A failed/inconclusive follow-up attempt does not alter prior standing.
            continue
        effective_relations.add(rel)

    for rel, standing in _STANDING_PRECEDENCE:
        if rel in effective_relations:
            return standing
    if case_id in superseded_case_ids:
        return "superseded"
    return "current"


def adjudication_is_effective(case: dict[str, Any]) -> bool:
    """A pending or held successor is visible in the graph but has no effect."""
    if case.get("state") not in ("adjudicated", "export_pending", "exported") or not case.get("adjudication"):
        return False
    if (case.get("verification") or {}).get("status") == "blocked":
        return False
    for event in reversed(case.get("human_decisions") or ()):
        if event.get("decision") == "accept":
            break
        if event.get("decision") in ("pause", "challenge", "defer"):
            return False
    return True


def build_claim_graph(
    cases: list[dict[str, Any]],
    *,
    case_id: str | None = None,
    claim_id: str | None = None,
    collect_triggers_fn: Callable[[dict, dict | None], list[dict]],
) -> dict[str, Any]:
    """Construct the longitudinal cross-case claim graph DAG and verdict/standing trajectories."""
    cases_by_id = {c["case_id"]: c for c in cases}
    if case_id is not None and case_id not in cases_by_id:
        fail("unknown_case", f"case_id '{case_id}' does not exist in this workspace")
    if case_id is not None and claim_id is not None:
        target_claims = {c["id"] for c in cases_by_id[case_id].get("claims", ())}
        if claim_id not in target_claims:
            fail("unknown_claim", f"claim_id '{claim_id}' does not exist in case '{case_id}'")

    ordered_cases = sorted(cases, key=lambda c: (c.get("created_at") or "", c["case_id"]))
    case_edges: list[dict] = []
    downstream_cases_map: dict[str, list[str]] = {c["case_id"]: [] for c in ordered_cases}
    superseded_case_ids: set[str] = set()

    for c in ordered_cases:
        cid = c["case_id"]
        rel = c.get("case_relation")
        seen_parents: set[str] = set()
        for pid in c.get("prior_case_ids") or ():
            if pid in cases_by_id and pid != cid:
                edge_type = rel or "follow_up"
                case_edges.append({"from_case_id": pid, "to_case_id": cid, "edge_type": edge_type})
                downstream_cases_map[pid].append(cid)
                seen_parents.add(pid)
        sup_id = c.get("supersedes_case_id")
        if sup_id and sup_id in cases_by_id and sup_id != cid:
            decisions = (c.get("adjudication") or {}).get("decisions") or []
            effective = adjudication_is_effective(c) and bool(decisions) and all(d.get("verdict") in _POSITIVE_VERDICTS for d in decisions)
            if effective:
                superseded_case_ids.add(sup_id)
            if sup_id not in seen_parents:
                downstream_cases_map[sup_id].append(cid)
            case_edges.append({"from_case_id": sup_id, "to_case_id": cid, "edge_type": "supersedes", "status": "effective" if effective else "pending"})

    dec_by_node: dict[str, dict | None] = {}
    claim_by_node: dict[str, dict] = {}
    for c in ordered_cases:
        cid = c["case_id"]
        decs = {}
        if c.get("adjudication"):
            for dec in c["adjudication"].get("decisions", ()):
                decs[dec["claim_id"]] = dec
        for clm in c.get("claims", ()):
            nid = f"{cid}:{clm['id']}"
            claim_by_node[nid] = clm
            dec_by_node[nid] = decs.get(clm["id"])

    claim_edges: list[dict] = []
    downstream_by_node: dict[str, list[dict]] = {nid: [] for nid in claim_by_node}
    upstream_by_node: dict[str, list[dict]] = {nid: [] for nid in claim_by_node}

    for c in ordered_cases:
        cid = c["case_id"]
        for clm in c.get("claims", ()):
            to_nid = f"{cid}:{clm['id']}"
            to_dec = dec_by_node[to_nid]
            for lnk in clm.get("prior_claim_links") or ():
                from_cid = lnk["prior_case_id"]
                from_clmid = lnk["prior_claim_id"]
                from_nid = f"{from_cid}:{from_clmid}"
                from_clm = claim_by_node.get(from_nid)
                from_dec = dec_by_node.get(from_nid)
                from_type = (from_dec or from_clm or {}).get("claim_type")
                from_level = (from_dec or from_clm or {}).get("evidence_level")
                to_type = (to_dec or clm).get("claim_type")
                to_level = (to_dec or clm).get("evidence_level")
                edge = {
                    "status": "effective" if adjudication_is_effective(c) and to_dec and to_dec.get("verdict") in _POSITIVE_VERDICTS else "pending",
                    "from_case_id": from_cid,
                    "from_claim_id": from_clmid,
                    "to_case_id": cid,
                    "to_claim_id": clm["id"],
                    "from_node_id": from_nid,
                    "to_node_id": to_nid,
                    "relation": lnk["relation"],
                    "reason": lnk["reason"],
                    "triggered_reversal_id": lnk.get("triggered_reversal_id"),
                    "verdict_transition": {
                        "from": from_dec.get("verdict") if from_dec else None,
                        "to": to_dec.get("verdict") if to_dec else None,
                    },
                    "level_transition": {
                        "from": f"{from_type} x {from_level}" if from_type and from_level else from_level,
                        "to": f"{to_type} x {to_level}" if to_type and to_level else to_level,
                    },
                }
                claim_edges.append(edge)
                if from_nid in downstream_by_node:
                    downstream_by_node[from_nid].append(edge)
                if to_nid in upstream_by_node:
                    upstream_by_node[to_nid].append(edge)

    claim_nodes_all: list[dict] = []
    for c in ordered_cases:
        cid = c["case_id"]
        for clm in c.get("claims", ()):
            nid = f"{cid}:{clm['id']}"
            dec = dec_by_node[nid]
            triggers = collect_triggers_fn(clm, dec)
            standing = _compute_active_standing(
                nid,
                cid,
                downstream_by_node.get(nid, ()),
                superseded_case_ids,
                dec_by_node,
            )
            claim_nodes_all.append({
                "node_id": nid,
                "case_id": cid,
                "claim_id": clm["id"],
                "text": (dec or clm).get("revised_text") or clm.get("text"),
                "scope": (dec or clm).get("scope"),
                "claim_type": (dec or clm).get("claim_type"),
                "evidence_level": (dec or clm).get("evidence_level") or clm.get("level"),
                "frozen_claim_type": clm.get("claim_type"),
                "frozen_evidence_level": clm.get("evidence_level") or clm.get("level"),
                "verdict": dec.get("verdict") if dec else None,
                "forecast_probability": dec.get("forecast_probability") if dec else None,
                "trigger_count": len(triggers),
                "prior_links_count": len(clm.get("prior_claim_links") or ()),
                "downstream_links_count": len(downstream_by_node.get(nid, ())),
                "active_standing": standing,
            })

    case_nodes_all = [
        {
            "case_id": c["case_id"],
            "question": c["question"],
            "domain": c["domain"],
            "state": c["state"],
            "schema_version": c.get("schema_version", 1),
            "created_at": c.get("created_at"),
            "prior_case_ids": list(c.get("prior_case_ids") or ()),
            "supersedes_case_id": c.get("supersedes_case_id"),
            "case_relation": c.get("case_relation"),
            "claim_count": len(c.get("claims", ())),
            "downstream_case_ids": sorted(set(downstream_cases_map.get(c["case_id"], ()))),
        }
        for c in ordered_cases
    ]

    if case_id is not None or claim_id is not None:
        seed_claims: set[str] = set()
        seed_cases: set[str] = set()
        if case_id is not None:
            seed_cases.add(case_id)
            if claim_id is not None:
                seed_claims.add(f"{case_id}:{claim_id}")
            else:
                seed_claims.update(
                    f"{case_id}:{clm['id']}" for clm in cases_by_id[case_id].get("claims", ())
                )
        elif claim_id is not None:
            for c in ordered_cases:
                for clm in c.get("claims", ()):
                    if clm["id"] == claim_id:
                        seed_claims.add(f"{c['case_id']}:{claim_id}")
                        seed_cases.add(c["case_id"])

        keep_claims = set(seed_claims)
        claim_undir: dict[str, set[str]] = {n["node_id"]: set() for n in claim_nodes_all}
        for e in claim_edges:
            if e["from_node_id"] in claim_undir and e["to_node_id"] in claim_undir:
                claim_undir[e["from_node_id"]].add(e["to_node_id"])
                claim_undir[e["to_node_id"]].add(e["from_node_id"])
        stack = list(keep_claims)
        while stack:
            cur = stack.pop()
            for nb in claim_undir.get(cur, ()):
                if nb not in keep_claims:
                    keep_claims.add(nb)
                    stack.append(nb)

        keep_cases = set(seed_cases) | {nid.split(":", 1)[0] for nid in keep_claims}
        case_undir: dict[str, set[str]] = {c["case_id"]: set() for c in ordered_cases}
        for ce in case_edges:
            if ce["from_case_id"] in case_undir and ce["to_case_id"] in case_undir:
                case_undir[ce["from_case_id"]].add(ce["to_case_id"])
                case_undir[ce["to_case_id"]].add(ce["from_case_id"])
        cstack = list(keep_cases)
        while cstack:
            cur = cstack.pop()
            for nb in case_undir.get(cur, ()):
                if nb not in keep_cases:
                    keep_cases.add(nb)
                    cstack.append(nb)

        if claim_id is None:
            keep_claims.update(
                n["node_id"] for n in claim_nodes_all if n["case_id"] in keep_cases
            )

        case_nodes = [n for n in case_nodes_all if n["case_id"] in keep_cases]
        case_edges = [e for e in case_edges if e["from_case_id"] in keep_cases and e["to_case_id"] in keep_cases]
        claim_nodes = [n for n in claim_nodes_all if n["node_id"] in keep_claims]
        claim_edges = [e for e in claim_edges if e["from_node_id"] in keep_claims and e["to_node_id"] in keep_claims]
    else:
        case_nodes = case_nodes_all
        claim_nodes = claim_nodes_all

    node_set = {n["node_id"] for n in claim_nodes}
    claim_adj: dict[str, list[str]] = {nid: [] for nid in node_set}
    indegree: dict[str, int] = {nid: 0 for nid in node_set}
    for e in claim_edges:
        if e["from_node_id"] in node_set and e["to_node_id"] in node_set:
            claim_adj[e["from_node_id"]].append(e["to_node_id"])
            indegree[e["to_node_id"]] += 1

    case_adj: dict[str, list[str]] = {n["case_id"]: [] for n in case_nodes}
    for ce in case_edges:
        if ce["from_case_id"] in case_adj and ce["to_case_id"] in case_adj:
            case_adj[ce["from_case_id"]].append(ce["to_case_id"])

    cycle_detected = _detect_cycles(claim_adj) or _detect_cycles(case_adj)

    roots = sorted(nid for nid, deg in indegree.items() if deg == 0)
    if not roots and node_set:
        roots = sorted(node_set)
    chains: list[list[str]] = []

    def _dfs_chains(node: str, path: list[str], seen: set[str]) -> None:
        children = [nxt for nxt in sorted(claim_adj.get(node, ())) if nxt not in seen]
        if not children:
            chains.append(list(path))
            return
        for nxt in children:
            seen.add(nxt)
            path.append(nxt)
            _dfs_chains(nxt, path, seen)
            path.pop()
            seen.remove(nxt)

    for root in roots:
        _dfs_chains(root, [root], {root})

    return {
        "filter": {"case_id": case_id, "claim_id": claim_id},
        "case_nodes": case_nodes,
        "case_edges": case_edges,
        "claim_nodes": claim_nodes,
        "claim_edges": claim_edges,
        "chains": chains,
        "cycle_detected": cycle_detected,
    }
