"""Release regression probes: interrupted migration, cache recovery, future formats."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from parrhesia.core import Engine
from parrhesia.contracts import ContractError
from parrhesia import storage

class StorageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="storage-recovery-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def workspace(self, name):
        root = self.root / name
        root.mkdir()
        engine = Engine(root)
        ids = []
        for index in range(3):
            payload = {"question": f"Migration fixture {index}", "draft": "Unassessed engineering fixture", "domain": "general"}
            if ids:
                payload.update(prior_case_ids=[ids[-1]], case_relation="follow_up")
            cid = engine.dispatch("create_case", payload)["case_id"]
            ids.append(cid)
            source = f"record-{index}.txt"
            quote = f"Traceable source statement for migration fixture {index}."
            (root / source).write_text(quote, encoding="utf-8")
            engine.dispatch("register_evidence", {
                "case_id": cid, "path": source, "quote": quote, "location": "L1",
                "provenance": "reported", "kind": "unknown",
            })
        return root, engine.database, ids

    def authoritative_rows(self, path):
        with closing(sqlite3.connect(path)) as db:
            return {
                table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("cases", "events", "evidence_snapshots", "export_artifacts")
            }

    def old_shape(self, path, version=2):
        with closing(sqlite3.connect(path)) as db:
            # Same shape construction used by the original V2 migration test.
            triggers = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
            for name in triggers:
                db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
            for name in ("case_summaries", "case_links", "evidence_index", "stale_cases", "storage_metadata"):
                db.execute("DROP TABLE IF EXISTS " + name)
            db.execute(f"PRAGMA user_version={version}")
            db.commit()

    def assert_consistent(self, root, path, ids):
        engine = Engine(root)
        self.assertEqual([r["case_id"] for r in engine.list_cases()], ids)
        with closing(sqlite3.connect(path)) as db:
            cases = [json.loads(r[0]) for r in db.execute("SELECT document FROM cases ORDER BY rowid")]
            summaries = db.execute("SELECT case_id,question,state,claim_count FROM case_summaries ORDER BY case_id").fetchall()
            self.assertEqual(summaries, sorted((c["case_id"], c["question"], c["state"], len(c["claims"])) for c in cases))
            links = db.execute("SELECT downstream_case_id,prior_case_id,relation_kind FROM case_links ORDER BY 1,2,3").fetchall()
            self.assertEqual(links, sorted((ids[i], ids[i - 1], "prior_case_ids") for i in (1, 2)))
            evidence = db.execute("SELECT case_id,evidence_id,path,sha256,provenance,has_quote FROM evidence_index ORDER BY 1,2").fetchall()
            expected = sorted((c["case_id"], e["evidence_id"], e["path"], e["sha256"], e["provenance"], 1) for c in cases for e in c["evidence"])
            self.assertEqual(evidence, expected)
            self.assertEqual(db.execute("SELECT count(*) FROM stale_cases").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], storage.SCHEMA_VERSION)
            self.assertEqual(Engine.verify_event_chain(db)["status"], "verified")
        graph = engine.dispatch("claim_graph", {"case_id": ids[-1]})
        self.assertEqual({r["case_id"] for r in graph["case_nodes"]}, set(ids))

    def test_first_middle_and_last_backfill_failures_rollback_and_restart(self):
        for position in (1, 2, 3):
            with self.subTest(failure_after_case=position):
                root, path, ids = self.workspace(f"atomic-{position}")
                self.old_shape(path)
                original_bytes = path.read_bytes()
                original_rows = self.authoritative_rows(path)
                real_sync = storage.sync_case_indexes
                calls = 0

                def failing_sync(db, case):
                    nonlocal calls
                    calls += 1
                    real_sync(db, case)
                    if calls == position:
                        raise sqlite3.OperationalError("injected interruption after index backfill")

                with patch("parrhesia.storage.sync_case_indexes", side_effect=failing_sync):
                    with self.assertRaises(sqlite3.OperationalError):
                        Engine(root)
                self.assertEqual(path.read_bytes(), original_bytes, "Failed migration changed the original database")
                self.assertEqual(self.authoritative_rows(path), original_rows)
                self.assert_consistent(root, path, ids)
                self.assertEqual(self.authoritative_rows(path), original_rows)

    def test_preexisting_partial_v2_and_v3_indexes_are_rebuilt_without_known_ids(self):
        for version, all_empty in ((2, False), (3, False), (3, True)):
            with self.subTest(version=version, all_empty=all_empty):
                root, path, ids = self.workspace(f"partial-{version}-{all_empty}")
                original_rows = self.authoritative_rows(path)
                with closing(sqlite3.connect(path)) as db:
                    db.execute("DROP TABLE IF EXISTS storage_metadata")
                    # Simulate an old interrupted build: tables exist, no dirty marks.
                    if all_empty:
                        db.execute("DELETE FROM case_summaries")
                    else:
                        db.execute("DELETE FROM case_summaries WHERE case_id=?", (ids[1],))
                    db.execute("DELETE FROM case_links")
                    db.execute("DELETE FROM evidence_index")
                    db.execute("DELETE FROM stale_cases")
                    db.execute(f"PRAGMA user_version={version}")
                    db.commit()
                self.assert_consistent(root, path, ids)
                self.assertEqual(self.authoritative_rows(path), original_rows)

    def test_secondary_index_damage_is_repaired_when_summaries_still_exist(self):
        root, path, ids = self.workspace("secondary-indexes")
        original_rows = self.authoritative_rows(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("DELETE FROM case_links WHERE downstream_case_id=?", (ids[2],))
            db.execute("UPDATE evidence_index SET path='wrong-path.txt' WHERE case_id=?", (ids[1],))
            db.execute("UPDATE case_summaries SET question='wrong summary' WHERE case_id=?", (ids[0],))
            db.commit()
        self.assert_consistent(root, path, ids)
        self.assertEqual(self.authoritative_rows(path), original_rows)

    def test_partial_index_repair_is_itself_atomic(self):
        root, path, ids = self.workspace("repair-interrupted")
        with closing(sqlite3.connect(path)) as db:
            db.execute("DROP TABLE IF EXISTS storage_metadata")
            db.execute("DELETE FROM case_summaries WHERE case_id=?", (ids[1],))
            db.execute("DELETE FROM case_links")
            db.execute("DELETE FROM evidence_index")
            db.execute("DELETE FROM stale_cases")
            db.commit()
        original_bytes = path.read_bytes()
        real_sync = storage.sync_case_indexes
        calls = 0

        def fail_midway(db, case):
            nonlocal calls
            calls += 1
            real_sync(db, case)
            if calls == 2:
                raise sqlite3.OperationalError("injected interruption during index repair")

        with patch("parrhesia.storage.sync_case_indexes", side_effect=fail_midway):
            with self.assertRaises(sqlite3.OperationalError):
                Engine(root)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assert_consistent(root, path, ids)

    def test_supported_versions_preserve_authoritative_content(self):
        for version in (0, 1, 2, 3):
            with self.subTest(version=version):
                root, path, ids = self.workspace(f"supported-{version}")
                if version < 3:
                    self.old_shape(path, version)
                original = self.authoritative_rows(path)
                self.assert_consistent(root, path, ids)
                self.assertEqual(self.authoritative_rows(path), original)

    def test_current_healthy_restart_does_not_reparse_or_backfill_every_case(self):
        root, path, ids = self.workspace("healthy-restart")
        with patch("parrhesia.storage.sync_case_indexes", side_effect=AssertionError("unexpected full backfill")):
            engine = Engine(root)
            self.assertEqual(len(engine.list_cases()), len(ids))

    def test_unknown_versions_reject_before_writes_even_when_tables_are_absent(self):
        for version in (-1, storage.SCHEMA_VERSION + 1, 99):
            for old_shape in (False, True):
                with self.subTest(version=version, old_shape=old_shape):
                    root, path, _ = self.workspace(f"unknown-{version}-{old_shape}")
                    if old_shape:
                        self.old_shape(path)
                    with closing(sqlite3.connect(path)) as db:
                        db.execute(f"PRAGMA user_version={version}")
                        db.commit()
                    before = path.read_bytes()
                    with self.assertRaises(ContractError) as raised:
                        Engine(root)
                    self.assertEqual(raised.exception.code, "unsupported_database_version")
                    self.assertEqual(path.read_bytes(), before)

    def test_existing_engine_and_readonly_snapshot_reject_unknown_version(self):
        root, path, ids = self.workspace("already-open")
        engine = Engine(root)
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA user_version=99")
            db.commit()
        original = path.read_bytes()
        for call in (
            lambda: engine.dispatch("get_case", {"case_id": ids[0]}),
            lambda: Engine.read_case_snapshot(root, ids[0]),
        ):
            with self.assertRaises(ContractError) as raised:
                call()
            self.assertEqual(raised.exception.code, "unsupported_database_version")
            self.assertEqual(path.read_bytes(), original)

    def test_repair_restores_missing_kind_restrictions_without_replacing_history(self):
        root, path, ids = self.workspace("restriction-history")
        with closing(sqlite3.connect(path)) as db:
            for cid in ids[:2]:
                case = json.loads(db.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone()[0])
                case["evidence"][0]["kind_inference"] = {"format": "fixture-current"}
                db.execute("UPDATE cases SET document=? WHERE id=?", (json.dumps(case), cid))
                if cid == ids[0]:
                    evidence = case["evidence"][0]
                    db.execute(
                        "INSERT INTO evidence_kind_restrictions VALUES (?,?,?,?,?,?)",
                        (cid, evidence["evidence_id"], evidence["sha256"], "unknown", '{"format":"fixture-historical"}', '{"historical":"retain"}'),
                    )
            historical = db.execute("SELECT * FROM evidence_kind_restrictions WHERE case_id=?", (ids[0],)).fetchall()
            db.execute("DROP TABLE storage_metadata")
            db.commit()
        original_rows = self.authoritative_rows(path)
        self.assert_consistent(root, path, ids)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT * FROM evidence_kind_restrictions WHERE case_id=?", (ids[0],)).fetchall(), historical)
            restored = db.execute("SELECT restricted_kind,kind_inference FROM evidence_kind_restrictions WHERE case_id=?", (ids[1],)).fetchone()
            self.assertEqual(restored[0], "unknown")
            self.assertEqual(json.loads(restored[1]), {"format": "fixture-current"})
        self.assertEqual(self.authoritative_rows(path), original_rows)

    def test_future_version_changed_before_writer_transaction_rolls_back(self):
        root, path, _ = self.workspace("version-race")
        engine = Engine(root)
        original_rows = self.authoritative_rows(path)
        real_check = storage._supported_database_version
        upgraded_bytes = []

        def upgrade_after_check(db):
            version = real_check(db)
            if not upgraded_bytes:
                with closing(sqlite3.connect(path)) as future:
                    future.execute("PRAGMA user_version=99")
                    future.commit()
                upgraded_bytes.append(path.read_bytes())
            return version

        with patch("parrhesia.storage._supported_database_version", side_effect=upgrade_after_check):
            with self.assertRaises(ContractError) as raised:
                engine.dispatch("create_case", {"question": "Must not persist", "draft": "Future format"})
        self.assertEqual(raised.exception.code, "unsupported_database_version")
        self.assertEqual(path.read_bytes(), upgraded_bytes[0])
        self.assertEqual(self.authoritative_rows(path), original_rows)


if __name__ == "__main__":
    unittest.main()
