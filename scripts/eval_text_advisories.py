"""Local, synthetic qualification of nonblocking text advisories (not a blind test)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parrhesia.gates import collect_lexical_advisories

DEFAULT_SUITE = ROOT / "docs/evaluation/text-advisory-cases-v1.json"


def evaluate(suite_path=DEFAULT_SUITE):
    raw = Path(suite_path).read_bytes()
    suite = json.loads(raw)
    rows = []
    for spec in suite["cases"]:
        evidence = {
            "evidence_id": "E1", "source_text": spec["source"],
            "source_text_status": "complete", "quote": spec.get("quote", spec["source"]),
            "kind": spec.get("kind", "intervention"), "provenance": spec.get("provenance", "observed"),
        }
        claim = {"id": "C1", "text": spec["claim"], "evidence_ids": ["E1"]}
        record = {"claim_id": "C1", "verdict": "supported", "revised_text": spec["claim"], "evidence_ids": ["E1"]}
        advisories = collect_lexical_advisories(record, claim, [evidence])
        codes = sorted({a["hook_code"] for a in advisories})
        rows.append({
            "id": spec["id"], "family": spec["family"], "expected": sorted(spec["expected"]),
            "actual": codes, "passed": codes == sorted(spec["expected"]),
            "advisories": advisories,
        })
    controls = [r for r in rows if not r["expected"]]
    targets = [r for r in rows if r["expected"]]
    return {
        "version": suite["version"], "status": suite["status"],
        "suite_sha256": hashlib.sha256(raw).hexdigest(),
        "summary": {
            "total": len(rows), "passed": sum(r["passed"] for r in rows),
            "controls": len(controls), "false_advisories": sum(bool(r["actual"]) for r in controls),
            "targets": len(targets), "targets_matched": sum(r["passed"] for r in targets),
            "all_passed": all(r["passed"] for r in rows),
        }, "results": rows,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
