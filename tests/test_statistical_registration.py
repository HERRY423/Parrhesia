"""New routing regressions; all checks and reviews are synthetic caller fixtures."""
import hashlib
import json
import unittest
from unittest.mock import patch

import test_claims_v2 as fixtures
from parrhesia.artifacts import inspect_artifact, recognizable_artifact
from parrhesia.contracts import ContractError
from parrhesia.core import Engine
from parrhesia.effects import verify_effect_computations


FAMILIES = (
    ("respiratory-counts.json", {"endpoint": "respiratory", "a": 7, "b": 31, "c": 11, "d": 29}, 31),
    ("renal-outcomes.JSON", {"endpoint": "renal", "treated_events": 9, "treated_n": 53,
                             "control_events": 14, "control_n": 59}, 53),
)


class StatisticalRegistrationTests(unittest.TestCase):
    setUp = fixtures.ClaimsV2Tests.setUp
    tearDown = fixtures.ClaimsV2Tests.tearDown
    register = fixtures.ClaimsV2Tests.register
    assessment = fixtures.ClaimsV2Tests.assessment
    claim = fixtures.ClaimsV2Tests.claim
    save = fixtures.ClaimsV2Tests.save
    reviewed = fixtures.ClaimsV2Tests.reviewed

    def source(self, filename, values):
        raw = json.dumps(values).encode("utf-8")
        (self.root / filename).write_bytes(raw)
        return raw

    def legacy_register(self, filename, values, kind="unknown"):
        raw = self.source(filename, values)
        return self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": filename, "kind": kind,
            "provenance": "reported", "quote": raw.decode(), "location": "L1",
        })

    def fake_record(self, evidence_id, values, count):
        return {"id": "not-a-computed-effect", "endpoint": values["endpoint"],
                "endpoint_role": "secondary", "metric": "mean_diff", "estimate": count,
                "direction": "neutral", "evidence_id": evidence_id}

    def assert_code(self, code, action):
        with self.assertRaises(ContractError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_both_count_families_have_same_registration_and_import_classification(self):
        for filename, values, _ in FAMILIES:
            with self.subTest(filename=filename):
                raw = self.source(filename, values)
                self.assertEqual(recognizable_artifact(raw, filename), "statistics")
                old_route = self.legacy_register(filename, values)
                imported = self.engine.dispatch("import_artifact", {
                    "case_id": self.cid, "path": filename, "artifact_format": "statistics",
                })
                self.assertEqual(old_route["kind"], "unknown")
                self.assertEqual(old_route["artifact"]["format"], "statistics")
                self.assertEqual(old_route["artifact"]["details"], imported["artifact"]["details"])

    def test_both_count_families_reject_kind_upgrade_on_both_routes(self):
        for filename, values, _ in FAMILIES:
            with self.subTest(filename=filename):
                self.source(filename, values)
                self.assert_code("kind_upgrade_forbidden", lambda: self.legacy_register(filename, values, "intervention"))
                self.assert_code("kind_upgrade_forbidden", lambda: self.engine.dispatch("import_artifact", {
                    "case_id": self.cid, "path": filename, "artifact_format": "statistics", "kind": "intervention",
                }))

    def test_invalid_count_values_still_cannot_upgrade_a_statistical_shape(self):
        for filename, values, _ in FAMILIES:
            malformed = {**values, ("a" if "a" in values else "treated_events"): -3}
            with self.subTest(filename=filename):
                self.assert_code("kind_upgrade_forbidden", lambda: self.legacy_register(filename, malformed, "intervention"))

    def test_ordinary_json_with_partial_keys_remains_documentary(self):
        filename = "instrument-labels.json"
        values = {"a": 31, "b": 53, "meaning": "Instrument labels, not a two by two table"}
        raw = self.source(filename, values)
        self.assertIsNone(recognizable_artifact(raw, filename))
        ev = self.legacy_register(filename, values, "observation")
        self.assertNotIn("artifact", ev)

    def test_count_tables_keep_both_formula_and_origin_restrictions(self):
        origins = (({"synthetic": False}, "unknown"), ({"data_origin": "observed"}, "unknown"),
                   ({"synthetic": True}, "synthetic"), ({"data_origin": "simulated"}, "synthetic"))
        for filename, values, count in FAMILIES:
            for origin, expected_kind in origins:
                with self.subTest(filename=filename, origin=origin):
                    raw = self.source(filename, {**values, **origin})
                    self.assertEqual(recognizable_artifact(raw, filename), "statistics")
                    inspected = inspect_artifact(raw, filename, "statistics")
                    self.assertEqual(inspected["kind"], expected_kind)
                    self.assert_code("kind_upgrade_forbidden", lambda: self.legacy_register(filename, {**values, **origin}, "intervention"))
                    ev = self.engine.dispatch("register_evidence", {
                        "case_id": self.cid, "path": filename, "kind": expected_kind,
                        "provenance": "synthetic" if expected_kind == "synthetic" else "reported",
                        "quote": raw.decode(), "location": "L1",
                    })
                    self.assertEqual(ev["artifact"]["format"], "statistics")
                    claim = {"effect_records": [self.fake_record(ev["evidence_id"], values, count)]}
                    self.assert_code("unanchored_effect_record", lambda: verify_effect_computations(
                        claim, {"verdict": "supported", "evidence_ids": [ev["evidence_id"]]},
                        {ev["evidence_id"]: ev}, snapshot_bytes={ev["evidence_id"]: raw},
                    ))

    def test_plain_origin_metadata_stays_metadata(self):
        for i, metadata in enumerate(({"synthetic": True, "unit": "samples"}, {"data_origin": "observed", "unit": "samples"})):
            filename = f"origin-only-{i}.json"
            raw = self.source(filename, metadata)
            self.assertEqual(recognizable_artifact(raw, filename), "dataset_metadata")
            self.assertEqual(inspect_artifact(raw, filename, "dataset_metadata")["kind"], "synthetic" if i == 0 else "unknown")

    def test_renaming_json_counts_cannot_bypass_first_registration(self):
        for i, (_, values, _) in enumerate(FAMILIES):
            filename = "airway-export.txt" if i == 0 else "kidney-export.data"
            with self.subTest(filename=filename):
                raw = self.source(filename, values)
                self.assertEqual(recognizable_artifact(raw, filename), "statistics")
                self.assert_code("kind_upgrade_forbidden", lambda: self.legacy_register(filename, values, "intervention"))
                ev = self.legacy_register(filename, values)
                self.assertEqual(ev["artifact"]["format"], "statistics")
                extracted = self.engine.dispatch("extract_effects", {"case_id": self.cid, "evidence_id": ev["evidence_id"]})
                self.assertEqual({r["metric"] for r in extracted["effect_records"]}, {"risk_diff", "RR", "OR"})

    def test_json_content_sniff_leaves_prose_and_partial_structures_unchanged(self):
        for i, text in enumerate((
            'Results prose: {"a":7,"b":31,"c":11,"d":29} is quoted as an example.',
            '{"a":7,"b":31,"c":11,"d":29} followed by documentary context',
            '{"a":7,"b":31,"note":"Instrument labels only"}',
        )):
            filename = f"prose-{i}.txt"
            self.assertIsNone(recognizable_artifact(text.encode(), filename))

    def test_known_nonstatistical_suffix_cannot_hide_complete_count_json(self):
        _, values, _ = FAMILIES[0]
        for suffix in (".ipynb", ".tsv", ".xml"):
            filename = "misnamed-export" + suffix
            with self.subTest(filename=filename):
                raw = self.source(filename, values)
                self.assertEqual(recognizable_artifact(raw, filename), "statistics")
                self.assert_code("kind_upgrade_forbidden", lambda: self.legacy_register(filename, values, "intervention"))

    def test_bound_synthetic_statistics_cannot_support_an_empirical_positive(self):
        filename, values, _ = FAMILIES[1]
        raw = self.source(filename, {**values, "synthetic": True})
        ev = self.engine.dispatch("register_evidence", {
            "case_id": self.cid, "path": filename, "kind": "synthetic", "provenance": "synthetic",
            "quote": raw.decode(), "location": "L1",
        })
        extracted = self.engine.dispatch("extract_effects", {"case_id": self.cid, "evidence_id": ev["evidence_id"]})
        record = next(r for r in extracted["effect_records"] if r["metric"] == "risk_diff")
        record.update(endpoint_role="secondary", direction="neutral")
        claim = self.claim()
        claim["text"] = "Synthetic fixture: effect 0. Supplemental renal count table."
        claim["evidence_ids"].append(ev["evidence_id"])
        claim["effect_records"] = [record]
        payload = self.reviewed(claim)
        payload["decisions"][0]["evidence_ids"] = claim["evidence_ids"]
        self.assert_code("synthetic_empirical_support", lambda: self.engine.dispatch("submit_adjudication", payload))

    def test_untagged_historical_snapshots_require_formula_binding(self):
        for filename, values, count in FAMILIES:
            raw = self.source(filename, values)
            ev = {"evidence_id": "old", "path": filename, "kind": "intervention",
                  "quote": raw.decode(), "sha256": hashlib.sha256(raw).hexdigest()}
            claim = {"effect_records": [self.fake_record("old", values, count)]}
            with self.subTest(filename=filename):
                self.assert_code("unanchored_effect_record", lambda: verify_effect_computations(
                    claim, {"verdict": "supported", "evidence_ids": ["old"]}, {"old": ev},
                    snapshot_texts={"old": raw.decode()}, snapshot_bytes={"old": raw},
                ))
                result = verify_effect_computations(claim, None, {"old": ev}, snapshot_bytes={"old": raw})
                self.assertFalse(result["checks"][0]["anchored"])

    def test_new_registration_cannot_use_counts_as_a_supplemental_effect(self):
        filename, values, count = FAMILIES[0]
        ev = self.legacy_register(filename, values)
        claim = self.claim()
        claim["evidence_ids"].append(ev["evidence_id"])
        claim["effect_records"] = [self.fake_record(ev["evidence_id"], values, count)]
        payload = self.reviewed(claim)
        self.assert_code("unanchored_effect_record", lambda: self.engine.dispatch("submit_adjudication", payload))

    def test_correct_formula_bound_values_remain_usable_as_supplemental_evidence(self):
        records = []
        claim = self.claim()
        for i, (filename, values, _) in enumerate(FAMILIES):
            ev = self.legacy_register(filename, values)
            extracted = self.engine.dispatch("extract_effects", {"case_id": self.cid, "evidence_id": ev["evidence_id"]})
            record = next(r for r in extracted["effect_records"] if r["metric"] == "risk_diff")
            expected = (values["a"] / (values["a"] + values["b"]) - values["c"] / (values["c"] + values["d"])) if "a" in values else (values["treated_events"] / values["treated_n"] - values["control_events"] / values["control_n"])
            self.assertAlmostEqual(record["estimate"], expected)
            record.update(id=f"computed-{i}", endpoint_role="secondary", direction="neutral")
            records.append(record)
            claim["evidence_ids"].append(ev["evidence_id"])
        claim["effect_records"] = records
        claim["text"] = "Synthetic fixture: effect 0. Supplemental respiratory and renal count tables."
        payload = self.reviewed(claim)
        payload["decisions"][0]["evidence_ids"] = claim["evidence_ids"]
        self.engine.dispatch("submit_adjudication", payload)
        result = self.engine.dispatch("verify", {"case_id": self.cid})
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(c["anchored"] for c in result["effect_checks"]["C1"]["checks"]))
        self.assertEqual(self.engine.dispatch("export", {"case_id": self.cid})["state"], "exported")

    def test_large_historical_unknown_snapshot_still_requires_binding_after_windowing(self):
        filename, values, count = FAMILIES[0]
        raw = self.source(filename, {**values, "notes": "x" * (140 * 1024)})
        quote = '"b": 31, "c": 11'
        with patch("parrhesia.artifacts.recognizable_artifact", return_value=None):
            ev = self.engine.dispatch("register_evidence", {
                "case_id": self.cid, "path": filename, "kind": "unknown",
                "provenance": "reported", "quote": quote, "location": "L1",
            })
        self.assertNotIn("artifact", ev)
        claim = self.claim()
        claim["evidence_ids"].append(ev["evidence_id"])
        claim["effect_records"] = [self.fake_record(ev["evidence_id"], values, count)]
        self.save(claim)
        frozen = self.engine.dispatch("freeze", {"case_id": self.cid})
        for role in ("overclaim", "underclaim"):
            review = self.engine.dispatch("review_packet", {"case_id": self.cid, "role": role})
            self.engine.dispatch("submit_review", {
                "case_id": self.cid, "role": role, "packet_id": review["packet_id"],
                "input_digest": frozen["input_digest"], "reviewer": {"context_id": role, "model": "fixture"},
                "covered_claim_ids": ["C1"], "unread_evidence_ids": [ev["evidence_id"]], "findings": [],
                "claim_stances": [{"claim_id": "C1", "stance": "insufficient_evidence", "rationale": "Synthetic fixture", "evidence_ids": []}],
            })
        packet = self.engine.dispatch("adjudication_packet", {"case_id": self.cid})
        payload = {
            "case_id": self.cid, "adjudication_id": packet["adjudication_id"], "input_digest": packet["input_digest"],
            "adjudicator": {"context_id": "writer", "model": "fixture"}, "unread_evidence_ids": [ev["evidence_id"]],
            "dispositions": [], "decisions": [{
                "claim_id": "C1", "claim_type": "description", "evidence_level": "recorded", "claim_basis": "empirical",
                "scope": claim["scope"], "verdict": "supported", "revised_text": claim["text"], "evidence_ids": [self.ev],
                "rationale": "Synthetic fixture", "confidence": "low", "confidence_reason": "Synthetic fixture",
                "boundary": "No scientific result", "reversal_condition": "Different fixture",
            }],
        }
        derived = next(e for e in packet["evidence"] if e["evidence_id"] == ev["evidence_id"])
        self.assert_code("unanchored_effect_record", lambda: self.engine.dispatch("submit_adjudication", payload))
        self.assertEqual(derived["source_text_status"], "truncated")
        self.assertEqual(derived["snapshot_artifact_format"], "statistics")
        self.assertEqual(derived["snapshot_artifact_basis"], "derived_from_snapshot")
        stored = self.engine.dispatch("get_case", {"case_id": self.cid})
        original = next(e for e in stored["evidence"] if e["evidence_id"] == ev["evidence_id"])
        self.assertNotIn("artifact", original)
        self.assertNotIn("snapshot_artifact_format", original)
        self.assertEqual(original["sha256"], hashlib.sha256(raw).hexdigest())

    def seed_historical_case(self, stage):
        """Recreate old missing classification through public APIs, then reopen the DB."""
        filename, values, count = FAMILIES[1]
        with patch("parrhesia.artifacts.recognizable_artifact", return_value=None):
            ev = self.legacy_register(filename, values, "intervention")
            self.ev = ev["evidence_id"]
            claim = self.claim()
            claim["effect"]["estimate"] = str(count)
            if stage == "frozen":
                self.save(claim)
                self.engine.dispatch("freeze", {"case_id": self.cid})
                payload = None
            else:
                payload = self.reviewed(claim)
                if stage == "adjudicated":
                    self.engine.dispatch("submit_adjudication", payload)
        self.engine = Engine(self.root)
        return payload

    def test_historical_frozen_case_rejects_inconsistent_kind_without_mutating_input(self):
        self.seed_historical_case("frozen")
        before = self.engine.dispatch("get_case", {"case_id": self.cid})
        self.assert_code("artifact_kind_conflict", lambda: self.engine.dispatch("review_packet", {"case_id": self.cid, "role": "overclaim"}))
        after = self.engine.dispatch("get_case", {"case_id": self.cid})
        self.assertEqual(before, after)

    def test_historical_reviewed_case_cannot_adjudicate_with_old_kind(self):
        payload = self.seed_historical_case("reviewed")
        self.assert_code("artifact_kind_conflict", lambda: self.engine.dispatch("submit_adjudication", payload))

    def test_historical_adjudicated_case_cannot_verify_or_export_with_old_kind(self):
        self.seed_historical_case("adjudicated")
        for action in ("verify", "export"):
            with self.subTest(action=action):
                self.assert_code("artifact_kind_conflict", lambda: self.engine.dispatch(action, {"case_id": self.cid}))


if __name__ == "__main__":
    unittest.main()
