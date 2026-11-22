"""Prepare a local author-burden pilot and summarize explicit observations; never call models."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

ARMS = ("B_compact", "S_prefill_single", "E_manual", "E_prefill")
METRICS = ("active_seconds", "form_seconds", "corrections", "handoffs", "input_tokens", "output_tokens", "cost_usd", "serious_evidence_errors")
BEHAVIORAL_FLAGS = ("overclaim_error", "underclaim_error", "false_abstention", "hollow_neutrality")
INTEGER_METRICS = {"corrections", "handoffs", "input_tokens", "output_tokens", "serious_evidence_errors"}
STATUSES = {"not_run", "completed", "failed", "cancelled", "timed_out"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def prepare(output: Path, cases: int = 12, seed: int = 20261117, benchmark: Path | None = None) -> dict:
    benchmark_cases = None
    benchmark_sha = None
    if benchmark is not None:
        raw_bench = benchmark.read_bytes()
        benchmark_sha = hashlib.sha256(raw_bench).hexdigest()
        bench_doc = json.loads(raw_bench.decode("utf-8"))
        benchmark_cases = bench_doc.get("cases") or []
        cases = len(benchmark_cases)
    if not 4 <= cases <= 48 or cases % 4:
        raise ValueError("Planned case count must be a multiple of 4 between 4 and 48")
    protocol = {
        "version": "author-impact-pilot-v1",
        "status": "materials_hydrated_awaiting_model_approval" if benchmark_cases else "draft_materials_and_thresholds_pending",
        "purpose": "Distinguish evidence-quality benefit from data-entry and cross-context burden",
        "planned_cases": cases, "arms": list(ARMS), "seed": seed,
        "unit": "source_case; repeated model calls are not independent cases",
        "comparisons": {"E_prefill_vs_E_manual": "prefill burden with the same review workflow",
                        "E_prefill_vs_S_prefill_single": "extra cross-context workflow value",
                        "S_prefill_single_vs_B_compact": "structured ingestion and ledger value"},
        "budgets": {"per_call_usd_max": 0.10, "task_usd_max": 1.00, "tokens_per_arm": None,
                    "wall_seconds_per_arm": None, "active_seconds_per_arm": None, "enforceable_provider_cap": "unknown"},
        "stop_rules": ["no external calls from these preparation tools", "do not execute until materials, route, hard cap and historical spending are checked",
                       "stop at frozen case/time/token/cost caps; retain failures and cancellations", "no sample extension after viewing outcomes"],
        "decision_thresholds": (
            {"quality_noninferiority_margin": -0.05, "minimum_active_time_reduction_seconds": 30,
             "maximum_serious_error_increase": 0.0, "maximum_false_abstention_increase": 0.05}
            if benchmark_cases
            else {"quality_noninferiority_margin": None, "minimum_active_time_reduction_seconds": None, "maximum_serious_error_increase": None}
        ),
        "readiness": {
            "materials": f"hydrated:{benchmark.name} ({benchmark_sha[:12]})" if benchmark_cases else "not_selected",
            "author_assignment": "not_run", "model_route": "unknown", "blinded_assessors": "not_selected", "confirmatory_power": "not_established",
        },
        "measurement_rules": ["time includes preparation, correction, context handoffs and final repair; waiting time recorded separately",
                              "record assigned denominator and every failure; unknown metrics remain null, never zero",
                              "blind scorers see normalized final claims and original evidence, not treatment or debug traces",
                              "different isolated writers per source-case treatment; an author must not see the same source case in multiple arms",
                              "balance author and period across treatments; cluster final inference by source case and author",
                              "use the same verified model/version, materials and aggregate budgets; count all review/adjudication calls",
                              "case and record hashes identify inputs; caller reports do not authenticate identity or time"]}
    rng = random.Random(seed)
    base_order = list(ARMS)
    rng.shuffle(base_order)
    rotations = list(range(4)) * (cases // 4)
    rng.shuffle(rotations)
    assignments = []
    for index, rotation in enumerate(rotations, 1):
        order = base_order[rotation:] + base_order[:rotation]
        src_case = benchmark_cases[index - 1] if benchmark_cases else None
        cid = src_case["case_code"] if src_case else f"P{index:03d}"
        mat_sha = digest(src_case) if src_case else None
        for position, arm in enumerate(order, 1):
            row = {"run_id": f"{cid}-{arm}", "case_id": cid, "arm": arm,
                   "planned_order": position, "material_sha256": mat_sha,
                   "author_id": None, "status": "not_run"}
            if src_case is not None:
                row["trap_category"] = src_case["trap_category"]
                row["family"] = src_case["family"]
            assignments.append(row)
    protocol["assignments_sha256"] = digest(assignments)
    plan_digest = digest(protocol)
    for assignment in assignments:
        assignment["plan_digest"] = plan_digest
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write("protocol.json", {**protocol, "plan_digest": plan_digest})
    (output / "assignments.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in assignments), encoding="utf-8")
    write("observation-template.json", {"plan_digest": plan_digest, "run_id": assignments[0]["run_id"], "status": "not_run",
                                       "material_sha256": assignments[0]["material_sha256"], "model_route": None, "author_id": None, "allocated_tokens": None,
                                       "isolated_context": None, "scorer_blinded": None, "quality_pass": None,
                                       **{f: None for f in BEHAVIORAL_FLAGS},
                                       **{m: None for m in METRICS}, "failed_step": None, "reason": None,
                                       "measurement_basis": "caller_reported; attach raw timestamps and host receipts separately"})
    (output / "BLINDED-RUBRIC.md").write_text(
        "# Blinded outcome scoring\n\nScore original evidence against normalized final claims. Hide arm, runtime traces and costs until scoring is locked.\n\n"
        "Joint quality pass requires supported contribution retained, no unsupported strengthening, explicit verdict/boundary, and no serious evidence error.\n"
        "Record overclaim, underclaim, contribution retention, evidence errors and completeness separately before the joint judgment.\n"
        "Missing outputs are non-delivery, not zero-quality observed outputs. Report them in the assigned denominator.\n"
        "Missing gold standard or unresolved scorer disagreement remains unknown. No adjudicator may grade their own treatment output.\n", encoding="utf-8")
    prompts = {
        "B_compact": "Use compact rules and the same native tools to assess 3-5 core claims from the supplied material. Produce final claims, evidence, verdicts, boundaries and reversal conditions. No required Parrhesia ledger or role orchestration.",
        "S_prefill_single": "Use the same source material, ingestion and prefill tools to assemble a ledger. In one context assess overclaim and underclaim and produce final claims. Label review non-independent; do not forge separate reviewer identities or bypass engine gates. Do not submit a full dual-review adjudication.",
        "E_manual": "Use the full L2 workflow on the same 3-5 claims. Assemble nested ledger fields manually from the supplied source snapshots; use separate review packets and a separate adjudication context. Count all preparation, correction and handoff work.",
        "E_prefill": "Use the full L2 workflow on the same 3-5 claims, with explicit source-bound prefill selections. Inspect omitted and invalid rows and preserve unknowns. Use separate review packets and a separate adjudication context. Count all preparation, correction and handoff work.",
    }
    (output / "prompts").mkdir()
    for arm, prompt in prompts.items():
        (output / "prompts" / f"{arm}.md").write_text(prompt + "\n\nPreparation only: material, verified model route and equal total budgets must be supplied before execution.\n", encoding="utf-8")
    return {"status": protocol["status"], "plan_digest": plan_digest, "planned_cases": cases, "planned_runs": len(assignments), "observed_runs": 0, "external_llm_status": "not_run"}


def summarize(plan: Path, observations: Path | None = None) -> dict:
    protocol = json.loads((plan / "protocol.json").read_text(encoding="utf-8"))
    plan_digest = protocol.pop("plan_digest")
    if digest(protocol) != plan_digest:
        raise ValueError("Plan changed; do not pool observations across revised plans")
    assignments = [json.loads(line) for line in (plan / "assignments.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assigned = {r["run_id"]: r for r in assignments}
    if len(assigned) != len(assignments) or len(assignments) != protocol["planned_cases"] * len(ARMS):
        raise ValueError("Assignment denominator changed or contains duplicate run IDs")
    if any(r["plan_digest"] != plan_digest or r["arm"] not in ARMS for r in assignments):
        raise ValueError("Assignment is not bound to this plan")
    if digest([{k: v for k, v in r.items() if k != "plan_digest"} for r in assignments]) != protocol["assignments_sha256"]:
        raise ValueError("Assignment content changed after preparation")
    rows = [] if observations is None else [json.loads(line) for line in observations.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen = set()
    for row in rows:
        if row.get("run_id") not in assigned or row["run_id"] in seen or row.get("plan_digest") != plan_digest:
            raise ValueError("Unknown/duplicate run or mismatched plan digest")
        seen.add(row["run_id"])
        if row.get("status") not in STATUSES:
            raise ValueError("Unsupported run status")
        expected_material = assigned[row["run_id"]]["material_sha256"]
        reported_material = row.get("material_sha256")
        if expected_material is not None and (
            reported_material is not None or row["status"] == "completed"
        ) and reported_material != expected_material:
            raise ValueError("Observation material digest does not match the assigned case")
        for key in METRICS:
            value = row.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key in INTEGER_METRICS and not isinstance(value, int))):
                raise ValueError(f"Invalid nonnegative metric: {key}")
        for key in ("quality_pass", "isolated_context", "scorer_blinded", *BEHAVIORAL_FLAGS):
            if row.get(key) is not None and not isinstance(row[key], bool):
                raise ValueError(f"Expected true/false/null: {key}")
        if row["status"] != "completed" and row.get("quality_pass") is not None:
            raise ValueError("Uncompleted run cannot be graded as a completed output")
        if row["status"] == "not_run" and any(row.get(k) is not None for k in (*METRICS, "quality_pass", *BEHAVIORAL_FLAGS)):
            raise ValueError("Unrun observations must keep measurement fields null")
        if row.get("quality_pass") is True and (row.get("serious_evidence_errors") or 0) > 0:
            raise ValueError("A serious evidence error contradicts a joint quality pass")
    by_run = {r["run_id"]: r for r in rows}
    arms = {}
    for arm in ARMS:
        planned = [r for r in assignments if r["arm"] == arm]
        received = [by_run[r["run_id"]] for r in planned if r["run_id"] in by_run]
        statuses = Counter(r["status"] for r in received)
        graded = [r for r in received if r["status"] == "completed" and r.get("quality_pass") is not None and r.get("scorer_blinded") is True]
        behavioral_rates = {}
        for flag in BEHAVIORAL_FLAGS:
            known_flag = [r[flag] for r in graded if r.get(flag) is not None]
            behavioral_rates[flag] = sum(known_flag) / len(known_flag) if known_flag else None
        arms[arm] = {"assigned": len(planned), "received": len(received), "missing_records": len(planned) - len(received),
                     "statuses": dict(statuses), "blinded_quality_scored": len(graded),
                     "observed_quality_pass_rate": sum(r["quality_pass"] for r in graded) / len(graded) if graded else None,
                     "behavioral_rates": behavioral_rates,
                     "metrics": {}}
        for key in METRICS:
            known = [r[key] for r in received if r.get(key) is not None]
            arms[arm]["metrics"][key] = {"known_n": len(known), "unknown_of_assigned": len(planned) - len(known),
                                        "observed_sum": sum(known) if known else None,
                                        "observed_mean": statistics.mean(known) if known else None}
    observed_runs = sum(row["status"] != "not_run" for row in rows)
    return {"plan_digest": plan_digest, "status": "observations_recorded" if observed_runs else "not_run", "observed_runs": observed_runs, "arms": arms,
            "source_observations_sha256": hashlib.sha256(observations.read_bytes()).hexdigest() if observations else None,
            "comparative_inference": "not_established; model, source, author allocation, isolation and frozen thresholds need audit",
            "host_accepted": "not_established_by_caller_records", "user_impact": "not_established_by_summary"}


def dry_run_benchmark(benchmark: Path) -> dict:
    """Deterministic zero-LLM verification of realistic-science-pilot-v1 using compact ledger, methods, and enforced symmetry."""
    import sys
    import tempfile

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from parrhesia.contracts import ContractError
    from parrhesia.core import Engine
    from parrhesia.isolation import packet_content_sha256

    bench = json.loads(benchmark.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory(prefix="parrhesia-realistic-dryrun-") as tmp:
        root = Path(tmp)
        for item in bench["cases"]:
            ws = root / item["case_code"]
            ws.mkdir()
            engine = Engine(ws)
            design_out = engine.dispatch("analyze_design", item["design_probe"]) if "design_probe" in item else None
            created = engine.dispatch("create_case", {
                "question": item["question"],
                "draft": item["draft"],
                "domain": item["domain"],
                "writer_context_id": f"writer-{item['case_code']}",
                "blind": True,
                "blind_mode": "estimate_first",
                "symmetry_mode": "enforced",
            })
            cid = created["case_id"]
            ev_path = f"{item['case_code']}.txt"
            (ws / ev_path).write_text(item["evidence_text"] + "\n", encoding="utf-8")
            ev = engine.dispatch("register_evidence", {
                "case_id": cid, "path": ev_path, "kind": item["evidence_kind"],
                "provenance": "observed", "quote": item["evidence_text"], "location": f"{ev_path}:L1",
            })
            ev_id = ev["evidence_id"]
            upsert_req = {
                "case_id": cid, "claim_id": "C1", "text": item["draft"],
                "claim_type": item["claim_type"], "evidence_level": item["evidence_level"],
                "scope": f"Studied cohort for {item['case_code']}", "evidence_ids": [ev_id],
                "contribution": item["title"],
                "alternatives": ["Unmeasured residual confounding or sampling artifact"],
            }
            if "effect_record" in item:
                upsert_req["effect_records"] = [{**item["effect_record"], "evidence_id": ev_id}]
            up = engine.dispatch("upsert_claim", upsert_req)
            engine.dispatch("freeze", {"case_id": cid})
            over_pkt = engine.dispatch("review_packet", {"case_id": cid, "role": "overclaim"})
            under_pkt = engine.dispatch("review_packet", {"case_id": cid, "role": "underclaim"})
            has_dossier = "evidence_first_dossier" in over_pkt and "packet_nonce" in over_pkt

            # Verify runner isolation receipt grading on overclaim review
            over_sha = packet_content_sha256(over_pkt)
            rev_over = engine.dispatch("submit_review", {
                "case_id": cid, "role": "overclaim", "packet_id": over_pkt["packet_id"],
                "input_digest": over_pkt["input_digest"],
                "reviewer": {"context_id": f"over-{item['case_code']}", "model": "dry-run-harness"},
                "covered_claim_ids": ["C1"],
                "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": f"Dry-run check on {item['case_code']}", "evidence_ids": []}],
                "unread_evidence_ids": [], "findings": [],
                "isolation_receipt": {
                    "runner": "dry-run-harness", "packet_nonce": over_pkt["packet_nonce"],
                    "packet_sha256": over_sha, "parent_history_messages": 0,
                    "memory_enabled": False, "tool_profile": "review",
                },
            })
            probe_ok = True
            if item["case_code"] == "RSP-03":
                probe_ok = design_out["robustness_band"] == "fragile_to_weak_confounding"
            elif item["case_code"] == "RSP-04":
                probe_ok = design_out["pseudoreplication_risk"] == "high"
            elif item["case_code"] == "RSP-05":
                probe_ok = design_out["classification"] == "underpowered_inconclusive"
            elif item["case_code"] == "RSP-07":
                probe_ok = design_out["asymmetry_status"] == "dominant"
            elif item["case_code"] == "RSP-09":
                probe_ok = design_out["robustness_band"] == "robust_against_moderate_confounding"
            elif item["case_code"] == "RSP-10":
                probe_ok = design_out["classification"] == "equivalent_supported"

            results.append({
                "case_code": item["case_code"],
                "trap_category": item["trap_category"],
                "estimate_first_dossier_built": has_dossier,
                "isolation_grade": rev_over["review"]["isolation_grade"]["grade"],
                "ceiling_diff_blockers": up["ceiling_diff"]["blocker_count"],
                "design_probe_ok": probe_ok,
                "passed": has_dossier and rev_over["review"]["isolation_grade"]["grade"] == "runner_verified_isolated" and probe_ok,
            })
    return {
        "mode": "dry_run_mechanical",
        "benchmark_version": bench["benchmark_version"],
        "total_cases": len(results),
        "passed_cases": sum(1 for r in results if r["passed"]),
        "all_passed": all(r["passed"] for r in results),
        "external_llm_status": "not_run",
        "user_impact": "not_run",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--cases", type=int, default=12)
    prep.add_argument("--seed", type=int, default=20261117)
    prep.add_argument("--benchmark", type=Path, default=None)
    summ = commands.add_parser("summarize")
    summ.add_argument("--plan", type=Path, required=True)
    summ.add_argument("--observations", type=Path)
    dry = commands.add_parser("dry-run")
    dry.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.output, args.cases, args.seed, benchmark=args.benchmark)
        elif args.command == "summarize":
            result = summarize(args.plan, args.observations)
        else:
            result = dry_run_benchmark(args.benchmark)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
