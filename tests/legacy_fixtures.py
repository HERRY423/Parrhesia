"""Seed historical v1 database fixtures; production cannot create ungated cases."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import uuid


def seed_legacy_case(engine, payload):
    assert payload["schema_version"] == 1
    case = {
        "case_id": "legacy_" + uuid.uuid4().hex, "schema_version": 1,
        "state": "draft", "created_at": datetime.now(timezone.utc).isoformat(),
        "question": payload["question"], "draft": payload["draft"],
        "domain": payload.get("domain", "scientific"),
        "writer_context_id": payload.get("writer_context_id"),
        "evidence": [], "hypotheses": [], "claims": [], "reviews": {}, "human_decisions": [],
        "scientific_validity": "not_established_by_engine",
    }
    with closing(sqlite3.connect(engine.database)) as db:
        db.execute("INSERT INTO cases(id,document) VALUES(?,?)", (case["case_id"], json.dumps(case)))
        db.commit()
    return case
