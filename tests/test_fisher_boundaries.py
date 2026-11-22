"""New numeric/resource qualification; original ingestion baselines stay intact."""
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from parrhesia.core import Engine
from parrhesia.stat_import import parse_statistics, verify_artifact_binding


def source(cells):
    return json.dumps(dict(endpoint="response-window", **dict(zip("abcd", cells)))).encode()


def rational_fisher(cells):
    a, b, c, d = cells
    n1, n0, successes = a + b, c + d, a + c
    denominator = math.comb(n1 + n0, successes)
    weights = [math.comb(n1, k) * math.comb(n0, successes - k)
               for k in range(max(0, successes - n0), min(successes, n1) + 1)]
    observed = math.comb(n1, a) * math.comb(n0, c)
    return Fraction(sum(w for w in weights if w <= observed), denominator)


class FisherBoundaryTests(unittest.TestCase):
    def test_small_tables_match_rational_oracle_and_symmetries(self):
        for cells in ((2, 9, 8, 3), (7, 13, 4, 19), (0, 7, 3, 4),
                      (4, 0, 2, 6), (0, 6, 0, 9), (3, 3, 3, 3)):
            a, b, c, d = cells
            expected = float(rational_fisher(cells))
            for reordered in (cells, (c, d, a, b), (b, a, d, c)):
                with self.subTest(cells=reordered):
                    result = parse_statistics(source(reordered), "observed-counts.json", "ev1")
                    self.assertEqual(result["issues"], [])
                    self.assertAlmostEqual(result["effect_records"][0]["p_value"], expected, places=13)

    def test_extreme_nonzero_p_is_retained_when_representable(self):
        cells = (240, 2, 3, 231)
        expected = float(rational_fisher(cells))
        result = parse_statistics(source(cells), "rare-response.json", "ev1")
        self.assertGreater(expected, 0)
        self.assertLess(expected, 1e-100)
        self.assertAlmostEqual(result["effect_records"][0]["p_value"] / expected, 1, places=10)
        self.assertEqual(result["issues"], [])

    def test_underflow_preserves_effects_and_explicit_missing_p(self):
        for cells in ((1400, 0, 0, 1400), (0, 1700, 1690, 10), (520, 0, 0, 520)):
            with self.subTest(cells=cells):
                raw = source(cells)
                result = parse_statistics(raw, "separated-groups.json", "ev1")
                self.assertEqual(result["status"], "parsed_with_issues")
                self.assertTrue(result["effect_records"])
                self.assertTrue(all("p_value" not in r for r in result["effect_records"]))
                issue = next(i for i in result["issues"] if i["code"] == "fisher_p_underflow")
                self.assertLess(issue["log_p_value"], -708)
                expected = rational_fisher(cells)
                self.assertGreater(expected, 0)
                self.assertAlmostEqual(issue["log_p_value"], math.log(expected.numerator) - math.log(expected.denominator), places=9)
                record = result["effect_records"][0]
                evidence = {"sha256": result["source_sha256"], "path": "separated-groups.json"}
                self.assertTrue(verify_artifact_binding(record, evidence, raw.decode())[0])
                forged = copy.deepcopy(record)
                forged["p_value"] = 0.0
                self.assertFalse(verify_artifact_binding(forged, evidence, raw.decode())[0])

    def test_large_counts_bound_work_without_losing_point_estimates(self):
        # Different support shapes: large balanced and large nearly degenerate.
        for cells in ((40_000_000, 30_000_000, 20_000_000, 50_000_000),
                      (1, 80_000_000, 0, 60_000_000)):
            with self.subTest(cells=cells):
                # Bound the test process too, so a regression cannot hang CI.
                code = "import json,sys; from parrhesia.stat_import import parse_statistics; print(json.dumps(parse_statistics(sys.stdin.buffer.read(), 'large-cohort.json', 'ev1')))"
                run = subprocess.run([sys.executable, "-c", code], input=source(cells),
                                     capture_output=True, timeout=5, check=True)
                result = json.loads(run.stdout)
                self.assertEqual(result["status"], "parsed_with_issues")
                self.assertTrue(result["effect_records"])
                self.assertTrue(all("p_value" not in r for r in result["effect_records"]))
                self.assertIn("fisher_work_limit", {i["code"] for i in result["issues"]})
                self.assertAlmostEqual(result["effect_records"][0]["estimate"], cells[0] / sum(cells[:2]) - cells[2] / sum(cells[2:]))

    def test_public_import_extract_propagates_underflow_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "extreme.json").write_bytes(source((1250, 0, 0, 1250)))
            engine = Engine(root)
            cid = engine.dispatch("create_case", {"question": "Numeric boundary qualification", "draft": "Synthetic fixture"})["case_id"]
            imported = engine.dispatch("import_artifact", {"case_id": cid, "path": "extreme.json", "artifact_format": "statistics"})
            self.assertIn("fisher_p_underflow", {i["code"] for i in imported["artifact"]["details"]["issues"]})
            extracted = engine.dispatch("extract_effects", {"case_id": cid, "evidence_id": imported["evidence"]["evidence_id"]})
            self.assertEqual(extracted["status"], "parsed_with_issues")
            self.assertNotIn("p_value", extracted["effect_records"][0])

    def test_work_boundaries_allow_supported_shapes_and_reject_both_limits(self):
        for cells in ((5000, 4999, 5000, 4999), (1, 9999, 2, 9998)):
            with self.subTest(cells=cells):
                result = parse_statistics(source(cells), "within-bounds.json", "ev1")
                self.assertEqual(result["issues"], [])
                self.assertGreater(result["effect_records"][0]["p_value"], 0)
        for cells in ((5000, 5000, 5000, 5000), (1, 10_001, 2, 9999)):
            with self.subTest(cells=cells):
                result = parse_statistics(source(cells), "beyond-bounds.json", "ev1")
                self.assertIn("fisher_work_limit", {i["code"] for i in result["issues"]})
                self.assertNotIn("p_value", result["effect_records"][0])

    def test_large_count_point_estimates_do_not_crash_or_invent_zero(self):
        huge = 10 ** 340
        result = parse_statistics(source((1, 1, 1, huge)), "unbalanced.json", "ev1")
        self.assertEqual([r["metric"] for r in result["effect_records"]], ["risk_diff"])
        self.assertEqual(result["effect_records"][0]["estimate"], 0.5)
        self.assertEqual({i["metric"] for i in result["issues"] if i["code"] == "effect_out_of_range"}, {"RR", "OR"})
        tiny = parse_statistics(source((1, huge, 0, huge)), "tiny-difference.json", "ev1")
        self.assertEqual(tiny["effect_records"], [])
        self.assertIn("effect_underflow", {i["code"] for i in tiny["issues"]})
        balanced = parse_statistics(source((huge, huge, huge, huge)), "balanced.json", "ev1")
        self.assertEqual([r["estimate"] for r in balanced["effect_records"]], [0.0, 1.0, 1.0])
        rare = parse_statistics(source((1, huge, 1, huge)), "rare-both.json", "ev1")
        self.assertEqual([r["estimate"] for r in rare["effect_records"]], [0.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
