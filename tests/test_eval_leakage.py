import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER_PATH = REPO_ROOT / "scripts" / "check-eval-leakage.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_eval_leakage", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EvalLeakageCheckerTests(unittest.TestCase):
    def test_synthetic_injected_leakage_triggers_strict_failure(self) -> None:
        checker = _load_checker()
        lexicon = checker.extract_gates_lexicon()

        # 1. Exact phrase leak inside heldout_realistic_controls
        suite_exact = {
            "heldout_realistic_controls": [
                {
                    "case_code": "CTRL-LEAK-1",
                    "question": "Does treatment X improve 1-year survival?",
                    "evidence_text": "Multicenter RCT showed null primary effect (p = 0.89).",
                    "draft": "Treatment X improved survival.",
                }
            ],
            "heldout_adversarial_paraphrases": [
                {
                    "case_code": "PARA-CLEAN-1",
                    "question": "Does assay B detect toxicity?",
                    "evidence_text": "Laboratory assay detected severe hepatotoxicity in 14 of 20 replicates.",
                    "draft": "Assay B is completely benign.",
                }
            ],
        }
        rep_exact = checker.scan_stage0_suite(suite_exact, lexicon)
        self.assertFalse(rep_exact["strict_passed"])
        self.assertGreaterEqual(rep_exact["heldout_overlap_count"], 1)

        # 2. Word 3-gram + regex leak inside heldout_adversarial_paraphrases
        suite_ngram = {
            "heldout_realistic_controls": [
                {
                    "case_code": "CTRL-CLEAN-1",
                    "question": "Does therapy Z lower 90-day mortality?",
                    "evidence_text": "Randomized multicenter cohort (N=640): mortality HR = 0.68 (95% CI 0.52 to 0.89).",
                    "draft": "Therapy Z reduces 90-day mortality in this trial.",
                }
            ],
            "heldout_adversarial_paraphrases": [
                {
                    "case_code": "PARA-LEAK-NGRAM",
                    "question": "Does regimen Q reduce events?",
                    "evidence_text": "The primary endpoint table remains incomplete; see enrollment baseline.",
                    "draft": "Regimen Q lowered events by 35%.",
                },
                {
                    "case_code": "PARA-LEAK-REGEX",
                    "question": "Does regimen R reduce strokes?",
                    "evidence_text": "Single-arm audit with no randomization reported 12% bleeding.",
                    "draft": "Regimen R causes fewer strokes.",
                },
            ],
        }
        rep_ngram = checker.scan_stage0_suite(suite_ngram, lexicon)
        self.assertFalse(rep_ngram["strict_passed"])
        self.assertGreaterEqual(rep_ngram["heldout_overlap_count"], 2)

        # 3. CLI --strict returns non-zero on injected suite & prompt-export answer leak
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            suite_file = tmp_path / "suite.json"
            prompt_file = tmp_path / "prompts.json"
            suite_file.write_text(json.dumps(suite_ngram), encoding="utf-8")
            prompt_file.write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "case_code": "M01",
                                "arms": {
                                    "B_compact": "=== POLICY ===\nPolicy rules.\n=== CASE ===\nDraft claim.\nTarget classification: unsupported"
                                },
                            }
                        ],
                        "heldout_adversarial_paraphrase_packets": [
                            {
                                "case_code": "PARA-01",
                                "arms": {
                                    "A_baseline": "Evaluate draft: baseline registration only without outcome reported."
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            exit_code = checker.main(
                [
                    "--suite",
                    str(suite_file),
                    "--prompt-export",
                    str(prompt_file),
                    "--strict",
                ]
            )
            self.assertEqual(exit_code, 1)

            pe_report = checker.scan_prompt_export(
                json.loads(prompt_file.read_text(encoding="utf-8")), lexicon
            )
            self.assertFalse(pe_report["strict_passed"])
            self.assertEqual(pe_report["answer_leak_count"], 1)
            self.assertGreaterEqual(pe_report["heldout_prompt_overlap_count"], 1)

    def test_synthetic_clean_zero_overlap_passes_strict(self) -> None:
        checker = _load_checker()
        clean_suite = {
            "heldout_realistic_controls": [
                {
                    "case_code": "CTRL-CLEAN",
                    "question": "Does compound A lower 12-month stroke risk in randomized patients?",
                    "evidence_text": (
                        "Multicenter masked trial (N=820): primary stroke reduction reached HR = 0.72 "
                        "(95% CI 0.56 to 0.92, p = 0.008), while secondary safety rash showed OR = 1.08 "
                        "(95% CI 0.89 to 1.31)."
                    ),
                    "draft": "In 820 randomized patients, compound A reduced 12-month stroke (HR = 0.72).",
                }
            ],
            "heldout_adversarial_paraphrases": [
                {
                    "case_code": "PARA-CLEAN",
                    "question": "Does compound B prevent acute kidney injury?",
                    "evidence_text": (
                        "Follow-up laboratory creatinine outcomes failed to separate between treatment "
                        "and placebo sleeves (RR = 1.01, 95% CI 0.88 to 1.16, p = 0.89)."
                    ),
                    "draft": "Compound B sharply lowers acute kidney injury (RR = 0.62, 95% CI 0.45 to 0.85).",
                }
            ],
        }
        clean_prompts = {
            "packets": [
                {
                    "case_code": "M01",
                    "arms": {
                        "B_compact": (
                            "=== POLICY ===\n"
                            "Calibrate claims accurately without overclaiming.\n"
                            "=== CASE ===\n"
                            "Question: Does B1 predict outcome?\n"
                            "Evidence: Multicenter prospective set N=500 AUROC 0.82.\n"
                            "Draft claim: Model predicts outcome externally."
                        )
                    },
                }
            ],
            "heldout_realistic_control_packets": [
                {
                    "case_code": "CTRL-CLEAN",
                    "arms": {
                        "A_baseline": clean_suite["heldout_realistic_controls"][0]["evidence_text"]
                    },
                }
            ],
            "heldout_adversarial_paraphrase_packets": [
                {
                    "case_code": "PARA-CLEAN",
                    "arms": {
                        "B_compact": (
                            "=== POLICY ===\n"
                            "Avoid phrases like does not support when unjustified.\n"
                            "=== CASE ===\n"
                            + clean_suite["heldout_adversarial_paraphrases"][0]["evidence_text"]
                        )
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            suite_file = tmp_path / "clean_suite.json"
            prompt_file = tmp_path / "clean_prompts.json"
            suite_file.write_text(json.dumps(clean_suite), encoding="utf-8")
            prompt_file.write_text(json.dumps(clean_prompts), encoding="utf-8")

            exit_code = checker.main(
                [
                    "--suite",
                    str(suite_file),
                    "--prompt-export",
                    str(prompt_file),
                    "--strict",
                ]
            )
            self.assertEqual(exit_code, 0)

    def test_repo_stage0_heldout_has_zero_leakage(self) -> None:
        checker = _load_checker()
        report = checker.run_leakage_audit()
        suite_audit = report["suite_audit"]
        self.assertTrue(
            suite_audit["strict_passed"],
            msg=f"Repo Stage 0 held-out leakage or missing held-out groups: {json.dumps(suite_audit, ensure_ascii=False)}",
        )
        self.assertEqual(suite_audit["heldout_overlap_count"], 0)
        groups = suite_audit["heldout_groups"]
        realistic_count = sum(
            v["item_count"] for k, v in groups.items() if "realistic_controls" in k
        )
        paraphrase_count = sum(
            v["item_count"] for k, v in groups.items() if "adversarial_paraphrases" in k
        )
        self.assertGreaterEqual(realistic_count, 20)
        self.assertGreaterEqual(paraphrase_count, 10)


if __name__ == "__main__":
    unittest.main()
