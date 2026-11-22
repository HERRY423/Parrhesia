"""Tests for SQLite events SHA-256 hash chain, v1 migration, and Engine dry-run/read helpers."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from parrhesia.claims import CARD_FIELDS, DESIGN_FIELDS, STAT_FIELDS
from parrhesia.contracts import CHECK_NAMES, ContractError
from parrhesia.core import Engine


def _setup_adjudicated_case(root: Path, *, export_pending: bool = False):
    (root / "source.txt").write_text("Primary result: OR 0.65 (95% CI 0.48 to 0.88, p=0.005).\n", encoding="utf-8")
    engine = Engine(root)
    cid = engine.dispatch("create_case", {"question": "Chain test?", "draft": "Draft text", "writer_context_id": "writer"})["case_id"]
    ev = engine.dispatch("register_evidence", {
        "case_id": cid, "path": "source.txt", "provenance": "observed", "kind": "observation",
        "quote": "Primary result: OR 0.65 (95% CI 0.48 to 0.88, p=0.005).", "location": "line 1",
    })["evidence_id"]
    claim = {
        "id": "C1", "text": "OR 0.65 (95% CI 0.48-0.88, p=0.005)", "claim_type": "association",
        "evidence_level": "adjusted", "claim_basis": "empirical", "scope": "Test cohort",
        "evidence_ids": [ev], "effect": {"estimate": "OR 0.65", "uncertainty": "95% CI 0.48-0.88, p=0.005"},
        "origin": "unknown", "contribution": "Chain verification fixture",
        "alternatives": [{"explanation": "Chance", "status": "not_excluded", "reason": "Observational"}],
        "checks": {name: {"status": "pass", "reason": "Verified against source cohort survival documentation and methods"} for name in CHECK_NAMES},
        "design_packages": [{"family": "observational", "checks": {k: {"status": "pass", "reason": "Verified observational cohort design criteria in registered source", "evidence_ids": [ev]} for k in DESIGN_FIELDS["observational"]}}],
        "statistical_report": {k: {"status": "pass", "reason": "Verified statistical reporting criteria in registered source table", "evidence_ids": [ev]} for k in STAT_FIELDS},
        "provenance_cards": {k: [] for k in CARD_FIELDS},
    }
    engine.dispatch("set_ledger", {"case_id": cid, "claims": [claim]})
    frozen = engine.dispatch("freeze", {"case_id": cid})
    for role in ("overclaim", "underclaim"):
        pkt = engine.dispatch("review_packet", {"case_id": cid, "role": role})
        engine.dispatch("submit_review", {
            "case_id": cid, "role": role, "packet_id": pkt["packet_id"], "input_digest": frozen["input_digest"],
            "reviewer": {"context_id": role, "model": "fixture"},
            "covered_claim_ids": ["C1"],
            "claim_stances": [{"claim_id": "C1", "stance": "supported", "rationale": "Anchored", "evidence_ids": [ev]}],
            "unread_evidence_ids": [], "findings": [],
        })
    adj_pkt = engine.dispatch("adjudication_packet", {"case_id": cid})
    engine.dispatch("submit_adjudication", {
        "case_id": cid, "adjudication_id": adj_pkt["adjudication_id"], "input_digest": adj_pkt["input_digest"],
        "adjudicator": {"context_id": "adj", "model": "fixture"}, "unread_evidence_ids": [], "dispositions": [],
        "decisions": [{
            "claim_id": "C1", "claim_type": "association", "evidence_level": "adjusted", "claim_basis": "empirical",
            "scope": "Test cohort", "verdict": "supported",
            "revised_text": "Cohort OR 0.65 (95% CI 0.48-0.88, p=0.005).",
            "rationale": "Supported by anchored quote.", "evidence_ids": [ev],
            "confidence": "medium", "confidence_reason": "Single cohort", "boundary": "Studied cohort",
            "reversal_condition": "Replication flips direction",
        }],
    })
    engine.dispatch("record_human_decision", {"case_id": cid, "decision": "accept", "responsible_human": "lead", "reason": "OK"})
    if export_pending:
        # Prepare export_pending row inside DB without invoking _materialize_export
        with engine._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone()[0])
            res = engine._export(db, case, {"case_id": cid, "path": "exports/out.md"})
            db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case, sort_keys=True), cid))
            assert res["state"] == "export_pending"
    return engine, cid


class EventChainTests(unittest.TestCase):
    def test_fresh_db_hash_chain_verify_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine, cid = _setup_adjudicated_case(root)
            engine.record_execution_event(cid, {"command": "pytest", "claim_id": "C1"})

            with closing(sqlite3.connect(engine.database)) as db:
                ver_num = db.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(ver_num, 3)
                chain = Engine.verify_event_chain(db, cid)
                self.assertEqual(chain["status"], "verified")
                self.assertEqual(chain["broken_sequences"], [])
                self.assertGreater(chain["event_count"], 5)
                self.assertEqual(chain["hashed_event_count"], chain["event_count"])
                self.assertEqual(chain["legacy_unhashed_count"], 0)
                first_prev = db.execute("SELECT prev_event_hash FROM events ORDER BY sequence ASC LIMIT 1").fetchone()[0]
                self.assertEqual(first_prev, "GENESIS")

            got = engine.dispatch("get_case", {"case_id": cid})
            self.assertEqual(got["event_chain_status"], "verified")
            ver = engine.dispatch("verify", {"case_id": cid})
            self.assertEqual(ver["status"], "pass")
            self.assertEqual(ver["event_chain_status"], "verified")

            # Tamper: edit an interior event's details
            with closing(sqlite3.connect(engine.database)) as db:
                db.execute("UPDATE events SET details = ? WHERE sequence = 2", ('{"tampered":true}',))
                db.commit()
                tampered_chain = Engine.verify_event_chain(db, cid)
                self.assertEqual(tampered_chain["status"], "tampered")
                self.assertIn(2, tampered_chain["broken_sequences"])

            ver_bad = engine.dispatch("verify", {"case_id": cid})
            self.assertEqual(ver_bad["status"], "blocked")
            self.assertEqual(ver_bad["event_chain_status"], "tampered")
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("export", {"case_id": cid})
            self.assertEqual(cm.exception.code, "verification_mismatch")

    def test_deleted_interior_row_and_materialize_export_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine, cid = _setup_adjudicated_case(root, export_pending=True)

            # Delete interior row sequence=2
            with closing(sqlite3.connect(engine.database)) as db:
                db.execute("DELETE FROM events WHERE sequence = 2")
                db.commit()
                chain = Engine.verify_event_chain(db, cid)
                self.assertEqual(chain["status"], "tampered")
                self.assertTrue(chain["broken_sequences"])

            with self.assertRaises(ContractError) as cm:
                engine._materialize_export(cid)
            self.assertEqual(cm.exception.code, "verification_mismatch")
            self.assertFalse((root / "exports/out.md").exists())

    def test_v1_database_migration_preserves_legacy_rows_and_chains_new_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".parrhesia"
            state_dir.mkdir(parents=True, exist_ok=True)
            db_path = state_dir / "state.sqlite3"
            (root / "src.txt").write_text("Legacy source text content 123456.\n", encoding="utf-8")

            legacy_case = {
                "case_id": "case_legacy_1",
                "schema_version": 2,
                "gate_version": 1,
                "blind": False,
                "state": "draft",
                "created_at": "2025-01-01T00:00:00Z",
                "question": "Legacy?",
                "draft": "Legacy draft",
                "domain": "scientific",
                "writer_context_id": "writer",
                "evidence": [],
                "hypotheses": [],
                "claims": [],
                "reviews": {},
                "human_decisions": [],
                "scientific_validity": "not_established_by_engine",
            }
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript("""
                    CREATE TABLE cases (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                    CREATE TABLE evidence_snapshots (case_id TEXT NOT NULL, evidence_id TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(case_id, evidence_id));
                    CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, action TEXT NOT NULL, recorded_at TEXT NOT NULL, details TEXT NOT NULL);
                    CREATE TABLE export_artifacts (case_id TEXT PRIMARY KEY, content BLOB NOT NULL);
                    PRAGMA user_version = 1;
                """)
                db.execute("INSERT INTO cases(id,document) VALUES(?,?)", ("case_legacy_1", json.dumps(legacy_case)))
                db.execute("INSERT INTO events(sequence,case_id,action,recorded_at,details) VALUES(1,?,?,?,?)", ("case_legacy_1", "create_case", "2025-01-01T00:00:00Z", '{"domain":"scientific"}'))
                db.execute("INSERT INTO events(sequence,case_id,action,recorded_at,details) VALUES(2,?,?,?,?)", ("case_legacy_1", "note", "2025-01-01T00:01:00Z", '{"msg":"legacy"}'))
                db.commit()

            engine = Engine(root)
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
                cols = {row[1] for row in db.execute("PRAGMA table_info(events)")}
                self.assertIn("prev_event_hash", cols)
                self.assertIn("event_hash", cols)

            got = engine.dispatch("get_case", {"case_id": "case_legacy_1"})
            self.assertEqual(got["event_chain_status"], "legacy_unhashed")
            self.assertEqual(got["event_chain"]["legacy_unhashed_count"], 2)
            self.assertEqual(got["event_chain"]["hashed_event_count"], 0)

            # New event continues contiguously after last legacy seq=2 via LEGACY_MIGRATED:2
            engine.dispatch("register_evidence", {
                "case_id": "case_legacy_1", "path": "src.txt", "provenance": "observed", "kind": "observation",
                "quote": "Legacy source text content 123456.", "location": "line 1",
            })
            with closing(sqlite3.connect(db_path)) as db:
                row3 = db.execute("SELECT sequence, prev_event_hash, event_hash FROM events WHERE sequence=3").fetchone()
                self.assertEqual(row3[0], 3)
                self.assertEqual(row3[1], "LEGACY_MIGRATED:2")
                self.assertIsNotNone(row3[2])
                chain = Engine.verify_event_chain(db, "case_legacy_1")
                self.assertEqual(chain["status"], "partial_legacy_verified")
                self.assertEqual(chain["legacy_unhashed_count"], 2)
                self.assertEqual(chain["hashed_event_count"], 1)

    def test_engine_validate_action_list_cases_get_ceilings_and_get_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            # validate_action create_case must roll back cleanly (0 persisted cases)
            dry_create = engine.validate_action("create_case", {"question": "Dry?", "draft": "Dry draft"})
            self.assertTrue(dry_create["valid"])
            self.assertTrue(dry_create["dry_run"])
            self.assertEqual(engine.list_cases(), [])

            engine, cid = _setup_adjudicated_case(root)
            cases = engine.list_cases()
            self.assertEqual(len(cases), 1)
            self.assertEqual(set(cases[0].keys()), {"case_id", "question", "state", "domain", "schema_version", "gate_version", "blind", "claim_count", "created_at"})
            self.assertEqual(cases[0]["case_id"], cid)
            self.assertEqual(cases[0]["claim_count"], 1)

            ceilings = engine.get_ceilings(cid)
            self.assertIn("C1", ceilings["check_ceilings"])
            self.assertEqual(ceilings["effect_record_counts"]["C1"], 0)

            pkt_over = engine.get_packet(cid, "overclaim")
            self.assertEqual(pkt_over["role"], "overclaim")
            pkt_adj = engine.get_packet(cid, "adjudication")
            self.assertIn("adjudication_id", pkt_adj)

            # Dry-run export leaves filesystem untouched and state unchanged at adjudicated
            before_state = engine.dispatch("get_case", {"case_id": cid})["state"]
            dry_exp = engine.validate_action("export", {"case_id": cid, "path": "exports/dry.md"})
            self.assertTrue(dry_exp["valid"])
            self.assertEqual(dry_exp["preview"]["state"], "export_pending")
            self.assertFalse((root / "exports/dry.md").exists())
            self.assertEqual(engine.dispatch("get_case", {"case_id": cid})["state"], before_state)

            # New draft case raises missing_packet on get_packet
            cid2 = engine.dispatch("create_case", {"question": "Draft?", "draft": "Text"})["case_id"]
            with self.assertRaises(ContractError) as cm:
                engine.get_packet(cid2, "overclaim")
            self.assertEqual(cm.exception.code, "missing_packet")

    def test_legacy_db_backfills_evidence_kind_restrictions_and_preserves_chain(self):
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".parrhesia"
            state_dir.mkdir(parents=True, exist_ok=True)
            db_path = state_dir / "state.sqlite3"
            payload_bytes = b'{"rules": {"fit": {"runtime": 1.2}}, "total_runtime": 1.2}\n'
            (root / "copied_legacy.txt").write_bytes(payload_bytes)
            sha = hashlib.sha256(payload_bytes).hexdigest()

            legacy_case = {
                "case_id": "case_legacy_restricted",
                "schema_version": 2,
                "gate_version": 2,
                "blind": False,
                "state": "draft",
                "created_at": "2025-01-01T00:00:00Z",
                "question": "Legacy restricted?",
                "draft": "Legacy draft",
                "domain": "scientific",
                "writer_context_id": "writer",
                "evidence": [
                    {
                        "evidence_id": "ev_legacy_1",
                        "path": "stats.json",
                        "sha256": sha,
                        "provenance": "observed",
                        "kind": "unknown",
                        "kind_inference": {
                            "inferred_kind": "unknown",
                            "basis": "artifact_structure_with_conservative_restrictions",
                            "format": "snakemake_stats",
                        },
                        "artifact": {"format": "snakemake_stats", "kind": "unknown"},
                    }
                ],
                "hypotheses": [],
                "claims": [],
                "reviews": {},
                "human_decisions": [],
                "scientific_validity": "not_established_by_engine",
            }
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript("""
                    CREATE TABLE cases (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                    CREATE TABLE evidence_snapshots (case_id TEXT NOT NULL, evidence_id TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(case_id, evidence_id));
                    CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, action TEXT NOT NULL, recorded_at TEXT NOT NULL, details TEXT NOT NULL);
                    CREATE TABLE export_artifacts (case_id TEXT PRIMARY KEY, content BLOB NOT NULL);
                    PRAGMA user_version = 1;
                """)
                db.execute("INSERT INTO cases(id,document) VALUES(?,?)", ("case_legacy_restricted", json.dumps(legacy_case)))
                db.execute("INSERT INTO events(sequence,case_id,action,recorded_at,details) VALUES(1,?,?,?,?)", ("case_legacy_restricted", "create_case", "2025-01-01T00:00:00Z", '{"domain":"scientific"}'))
                db.commit()

            engine = Engine(root)
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
                rows = db.execute(
                    "SELECT case_id, evidence_id, sha256, restricted_kind FROM evidence_kind_restrictions WHERE sha256=?",
                    (sha,),
                ).fetchall()
                self.assertEqual(rows, [("case_legacy_restricted", "ev_legacy_1", sha, "unknown")])
                idx = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_evidence_kind_restrictions_sha256'"
                ).fetchone()
                self.assertIsNotNone(idx)
                self.assertEqual(
                    Engine.verify_event_chain(db, "case_legacy_restricted")["status"],
                    "legacy_unhashed",
                )

            # New case registering a copy of the legacy restricted artifact cannot upgrade kind.
            cid_new = engine.dispatch("create_case", {"question": "Copy check?", "draft": "Draft"})["case_id"]
            with self.assertRaises(ContractError) as cm:
                engine.dispatch("register_evidence", {
                    "case_id": cid_new, "path": "copied_legacy.txt", "provenance": "observed",
                    "kind": "observation", "quote": '"total_runtime": 1.2', "location": "L1",
                })
            self.assertEqual(cm.exception.code, "kind_upgrade_forbidden")

            reg = engine.dispatch("register_evidence", {
                "case_id": cid_new, "path": "copied_legacy.txt", "provenance": "observed",
                "kind": "unknown", "quote": '"total_runtime": 1.2', "location": "L1",
            })
            self.assertEqual(reg["kind"], "unknown")
            self.assertEqual(reg["kind_inference"]["format"], "snakemake_stats")
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(Engine.verify_event_chain(db, cid_new)["status"], "verified")

    def test_v2_database_migration_builds_v3_indexes_and_preserves_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "obs.txt").write_text("Primary cohort accuracy measured 0.88 on 120 samples.\n", encoding="utf-8")
            eng1 = Engine(root)
            c_parent = eng1.dispatch("create_case", {"question": "Parent q", "draft": "Parent draft"})["case_id"]
            eng1.dispatch("register_evidence", {
                "case_id": c_parent, "path": "obs.txt", "provenance": "observed",
                "kind": "observation", "quote": "Primary cohort accuracy measured 0.88", "location": "L1",
            })
            c_child = eng1.dispatch("create_case", {
                "question": "Child q", "draft": "Child draft", "prior_case_ids": [c_parent], "case_relation": "follow_up",
            })["case_id"]

            db_path = root / ".parrhesia" / "state.sqlite3"
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript("""
                    DROP TRIGGER trg_cases_after_insert;
                    DROP TRIGGER trg_cases_after_update;
                    DROP TRIGGER trg_cases_after_delete;
                    DROP TABLE case_summaries;
                    DROP TABLE case_links;
                    DROP TABLE evidence_index;
                    DROP TABLE stale_cases;
                    PRAGMA user_version = 2;
                """)

            eng2 = Engine(root)
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
                triggers = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}
                self.assertTrue({"trg_cases_after_insert", "trg_cases_after_update", "trg_cases_after_delete"} <= triggers)
                link_rows = db.execute("SELECT downstream_case_id, prior_case_id FROM case_links").fetchall()
                self.assertEqual(link_rows, [(c_child, c_parent)])
                self.assertEqual(Engine.verify_event_chain(db, c_child)["status"], "verified")

            listed = eng2.list_cases()
            self.assertEqual([c["case_id"] for c in listed], [c_parent, c_child])
            graph = eng2.dispatch("claim_graph", {"case_id": c_child})
            self.assertEqual(len(graph["case_nodes"]), 2)

    def test_raw_sql_case_mutation_marks_stale_and_recovers_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = Engine(root)
            c1 = engine.dispatch("create_case", {"question": "Original Q1", "draft": "D1"})["case_id"]
            c2 = engine.dispatch("create_case", {"question": "Original Q2", "draft": "D2"})["case_id"]
            db_path = root / ".parrhesia" / "state.sqlite3"

            raw_doc = json.dumps({
                "case_id": "case_raw_sql", "question": "Raw SQL question", "draft": "Raw draft",
                "domain": "scientific", "schema_version": 2, "gate_version": 1, "blind": True,
                "state": "draft", "claims": [], "evidence": [], "created_at": "2026-01-01T00:00:00Z",
            })
            with closing(sqlite3.connect(db_path)) as db:
                row = db.execute("SELECT document FROM cases WHERE id=?", (c1,)).fetchone()
                doc1 = json.loads(row[0])
                doc1["question"] = "Mutated via raw SQL"
                db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(doc1), c1))
                db.execute("INSERT INTO cases(id, document) VALUES (?, ?)", ("case_raw_sql", raw_doc))
                db.execute("DELETE FROM cases WHERE id=?", (c2,))
                db.commit()
                dirty = {r[0] for r in db.execute("SELECT case_id FROM stale_cases").fetchall()}
                self.assertEqual(dirty, {c1, "case_raw_sql", c2})

            listed = engine.list_cases()
            self.assertEqual({c["case_id"]: c["question"] for c in listed}, {
                c1: "Mutated via raw SQL",
                "case_raw_sql": "Raw SQL question",
            })
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute("SELECT case_id FROM stale_cases").fetchall(), [])

    def test_indexed_queries_skip_unrelated_case_json_and_disk_rehashing(self):
        from unittest import mock
        import parrhesia.storage as st
        import parrhesia.core as core_mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "parent.txt").write_text("Parent experiment value 0.72 across cohort.\n", encoding="utf-8")
            (root / "unrelated.txt").write_text("UNRELATED_DISK_FILE_CONTENT\n", encoding="utf-8")
            (root / "calib.txt").write_text("External replication result: OR 0.68 (95% CI 0.50 to 0.92, p=0.01).\n", encoding="utf-8")
            engine, c_adj = _setup_adjudicated_case(root)

            c_unrel = engine.dispatch("create_case", {
                "question": "UNRELATED_SENTINEL_QUESTION",
                "draft": "UNRELATED_DRAFT_BODY_NEVER_DESERIALIZED",
            })["case_id"]
            engine.dispatch("register_evidence", {
                "case_id": c_unrel, "path": "unrelated.txt", "provenance": "observed",
                "kind": "observation", "quote": "UNRELATED_DISK_FILE_CONTENT", "location": "L1",
            })
            c_calib = engine.dispatch("create_case", {"question": "External replication source", "draft": "Calibration host"})["case_id"]
            ev_calib = engine.dispatch("register_evidence", {
                "case_id": c_calib, "path": "calib.txt", "provenance": "observed",
                "kind": "observation", "quote": "External replication result: OR 0.68", "location": "L1",
            })["evidence_id"]
            engine.dispatch("record_calibration_outcome", {
                "case_id": c_adj, "claim_id": "C1", "outcome": "replicated",
                "resolution_source": "external_evidence", "evidence_id": ev_calib,
                "reason": "Independent replication cohort confirms direction and interval overlap.",
            })

            c_parent = engine.dispatch("create_case", {"question": "Parent hypothesis", "draft": "Parent"})["case_id"]
            engine.dispatch("register_evidence", {
                "case_id": c_parent, "path": "parent.txt", "provenance": "observed",
                "kind": "observation", "quote": "Parent experiment value 0.72", "location": "L1",
            })
            c_child = engine.dispatch("create_case", {
                "question": "Followup", "draft": "Followup", "prior_case_ids": [c_parent], "case_relation": "follow_up",
            })["case_id"]

            seen_blobs: list[str] = []
            real_loads = json.loads

            def spy_loads(s, *args, **kwargs):
                if isinstance(s, str):
                    seen_blobs.append(s)
                return real_loads(s, *args, **kwargs)

            read_paths: list[str] = []
            real_read = engine._read_source

            def spy_read(path):
                read_paths.append(path.name)
                return real_read(path)

            with (
                mock.patch.object(st.json, "loads", side_effect=spy_loads),
                mock.patch.object(core_mod.json, "loads", side_effect=spy_loads),
                mock.patch.object(engine, "_read_source", side_effect=spy_read),
            ):
                listed = engine.list_cases()
                self.assertGreaterEqual(len(listed), 5)
                engine.dispatch("claim_graph", {"case_id": c_child})
                engine.dispatch("evaluate_triggers", {"case_id": c_parent})
                cal = engine.dispatch("calibration_report", {})

            self.assertEqual(cal["summary"]["total_adjudicated_claims"], 1)
            self.assertEqual(cal["summary"]["resolved_claim_count"], 1)
            self.assertFalse(any("UNRELATED_DRAFT_BODY_NEVER_DESERIALIZED" in blob for blob in seen_blobs))
            # source.txt belongs to c_adj but is uncited by calibration_outcomes; only calib.txt needs disk hashing.
            self.assertEqual(read_paths, ["calib.txt"])
            self.assertNotIn("unrelated.txt", read_paths)
            self.assertNotIn("source.txt", read_paths)


if __name__ == "__main__":
    unittest.main()
