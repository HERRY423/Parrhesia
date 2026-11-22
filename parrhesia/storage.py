"""SQLite storage, incremental indexes, event hash-chain, and path-safe I/O. Pure stdlib."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import stat
import tempfile
from typing import Any
import uuid

from .contracts import ContractError, fail, string

MAX_SOURCE_BYTES = 16 * 1024 * 1024
SCHEMA_VERSION = 3
INDEX_MAINTENANCE_REVISION = "1"

_LINK_FALLBACK_ERRNOS = frozenset(
    code
    for code in (
        errno.EPERM,
        errno.EACCES,
        errno.EXDEV,
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOSYS", None),
        errno.EINVAL,
    )
    if code is not None
)
_WINDOWS_LINK_FALLBACK_ERRORS = frozenset({
    1,     # ERROR_INVALID_FUNCTION
    5,     # ERROR_ACCESS_DENIED
    17,    # ERROR_NOT_SAME_DEVICE
    50,    # ERROR_NOT_SUPPORTED
    1314,  # ERROR_PRIVILEGE_NOT_HELD
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def json_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def should_fallback_from_link(exc: OSError) -> bool:
    """Return True when hard-linking failed due to permissions or unsupported filesystem semantics."""
    if isinstance(exc, FileExistsError):
        return False
    if isinstance(exc, PermissionError):
        return True
    if exc.errno in _LINK_FALLBACK_ERRNOS:
        return True
    return getattr(exc, "winerror", None) in _WINDOWS_LINK_FALLBACK_ERRORS


def write_exclusive_export(target: Path, report: bytes) -> None:
    """Atomically create target with O_CREAT|O_EXCL and fsync when hard-linking fails."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(target, flags, 0o644)
    try:
        view = memoryview(report)
        written = 0
        while written < len(report):
            chunk = os.write(fd, view[written:])
            if chunk <= 0:
                raise OSError("short write during export fallback")
            written += chunk
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        target.unlink(missing_ok=True)
        raise
    os.close(fd)


def materialize_file_atomically(
    target: Path,
    report: bytes,
    *,
    link_fn: Any = None,
    fallback_writer: Any = None,
) -> None:
    """Write report bytes exclusively via temp file + hard-link (with O_EXCL fallback)."""
    link_impl = link_fn or os.link
    fallback_impl = fallback_writer or write_exclusive_export
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        if target.exists():
            if not target.is_file() or target.read_bytes() != report:
                fail("export_exists", "existing export differs; it will not be overwritten")
            return
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".parrhesia-export-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(report)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            link_impl(temporary, target)
        except OSError as exc:
            if not should_fallback_from_link(exc):
                raise
            fallback_impl(target, report)
    except FileExistsError:
        fail("export_exists", "another file appeared at the export path; retry to compare against the prepared artifact")
    except OSError as exc:
        fail("export_failed", f"artifact retained for retry; materialization failed: {exc.__class__.__name__}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def reject_link(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        fail("unsafe_path", "symlinks and reparse points are not allowed")


def safe_workspace_path(workspace: Path, relative: Any) -> Path:
    value = string(relative, "path", maximum=2000)
    windows = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if windows.drive or windows.root or normalized.startswith("/") or ":" in value or "\x00" in value:
        fail("unsafe_path", "path must be relative to the workspace")
    if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in parts):
        fail("unsafe_path", "empty, traversal, and ambiguous path components are not allowed")
    if parts[0].casefold() == ".parrhesia":
        fail("unsafe_path", "the internal state directory cannot be a source or export target")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(part.split(".")[0].casefold() in reserved for part in parts):
        fail("unsafe_path", "Windows device names are not allowed")
    current = workspace
    for part in parts:
        current = current / part
        reject_link(current)
    try:
        current.resolve(strict=False).relative_to(workspace)
    except (ValueError, OSError):
        fail("unsafe_path", "path escapes the workspace")
    return current


def read_regular_source(path: Path) -> bytes:
    try:
        reject_link(path)
        if not path.is_file():
            fail("invalid_source", "evidence must reference a regular file")
        with path.open("rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                fail("invalid_source", "evidence must reference a regular file")
            content = handle.read(MAX_SOURCE_BYTES + 1)
        if len(content) > MAX_SOURCE_BYTES:
            fail("too_large", f"source exceeds {MAX_SOURCE_BYTES} bytes")
        return content
    except OSError as exc:
        fail("source_unreadable", f"cannot read evidence: {exc.__class__.__name__}")


def _supported_database_version(db: sqlite3.Connection) -> int:
    """Reject unknown container formats before interpreting or changing tables."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, SCHEMA_VERSION):
        fail(
            "unsupported_database_version",
            f"Database schema version {version} is unsupported; supported versions are 0, 1, 2, {SCHEMA_VERSION}. "
            "Use a compatible release; this database has not been migrated.",
        )
    return version


@contextmanager
def connect_readonly(state_dir: Path, database: Path):
    """Read one consistent snapshot without initialization, migration or writes."""
    reject_link(state_dir)
    reject_link(database)
    if not database.is_file():
        fail("missing_workspace", "Select an existing Parrhesia workspace with a saved case")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        _supported_database_version(db)
        yield db
    finally:
        db.close()


@contextmanager
def connect_db(state_dir: Path, database: Path):
    reject_link(state_dir)
    reject_link(database)
    db = sqlite3.connect(database, timeout=15)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        _supported_database_version(db)
        with db:
            yield db
            # A live Engine can race a future release between opening its
            # connection and acquiring its transaction. Do not commit writes
            # made against a version that changed during that gap.
            _supported_database_version(db)
    finally:
        db.close()


def record_kind_restriction(db: sqlite3.Connection, case_id: str, evidence: dict[str, Any]) -> None:
    sha = evidence.get("sha256")
    kind_inference = evidence.get("kind_inference")
    kind_val = evidence.get("kind")
    evidence_id = evidence.get("evidence_id")
    if not (sha and kind_inference and kind_val and evidence_id):
        return
    db.execute(
        """
        INSERT OR REPLACE INTO evidence_kind_restrictions(
            case_id, evidence_id, sha256, restricted_kind, kind_inference, artifact_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            evidence_id,
            sha,
            kind_val,
            canonical_json(kind_inference),
            canonical_json(evidence["artifact"]) if "artifact" in evidence else None,
        ),
    )


def _extract_case_links(case: dict[str, Any]) -> set[tuple[str, str]]:
    links: set[tuple[str, str]] = set()
    cid = case.get("case_id")
    for pid in case.get("prior_case_ids") or ():
        if isinstance(pid, str) and pid and pid != cid:
            links.add((pid, "prior_case_ids"))
    sup = case.get("supersedes_case_id")
    if isinstance(sup, str) and sup and sup != cid:
        links.add((sup, "supersedes"))
    for claim in case.get("claims") or ():
        if not isinstance(claim, dict):
            continue
        for lnk in claim.get("prior_claim_links") or ():
            if not isinstance(lnk, dict):
                continue
            pid = lnk.get("prior_case_id")
            if isinstance(pid, str) and pid and pid != cid:
                links.add((pid, "prior_claim_links"))
    return links


def sync_case_indexes(db: sqlite3.Connection, case: dict[str, Any]) -> None:
    """Update normalized summary, link, and evidence index tables for one case."""
    cid = case["case_id"]
    claims = case.get("claims") or []
    claim_ids = [c["id"] for c in claims if isinstance(c, dict) and isinstance(c.get("id"), str)]
    is_adj = 1 if (case.get("state") in ("adjudicated", "export_pending", "exported") and case.get("adjudication")) else 0
    blind_val = case.get("blind")
    blind_int = 1 if blind_val is True else 0 if blind_val is False else None
    db.execute(
        """
        INSERT OR REPLACE INTO case_summaries(
            case_id, question, state, domain, schema_version, gate_version,
            blind, claim_count, created_at, is_adjudicated, claim_ids_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cid,
            case.get("question"),
            case.get("state"),
            case.get("domain", "scientific"),
            case.get("schema_version", 1),
            case.get("gate_version"),
            blind_int,
            len(claims),
            case.get("created_at"),
            is_adj,
            canonical_json(claim_ids),
        ),
    )
    db.execute("DELETE FROM case_links WHERE downstream_case_id=?", (cid,))
    for prior_cid, relation_kind in _extract_case_links(case):
        db.execute(
            "INSERT OR IGNORE INTO case_links(downstream_case_id, prior_case_id, relation_kind) VALUES (?, ?, ?)",
            (cid, prior_cid, relation_kind),
        )
    db.execute("DELETE FROM evidence_index WHERE case_id=?", (cid,))
    for ev in case.get("evidence") or ():
        if not isinstance(ev, dict) or not ev.get("evidence_id"):
            continue
        db.execute(
            """
            INSERT OR REPLACE INTO evidence_index(
                case_id, evidence_id, path, sha256, provenance, has_quote
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                ev["evidence_id"],
                ev.get("path", ""),
                ev.get("sha256", ""),
                ev.get("provenance", "reported"),
                1 if ev.get("quote") else 0,
            ),
        )
    db.execute("DELETE FROM stale_cases WHERE case_id=?", (cid,))


def sync_stale_cases(db: sqlite3.Connection) -> None:
    """Re-index only cases marked dirty by external SQL writes bypassing Engine."""
    dirty = db.execute("SELECT case_id FROM stale_cases").fetchall()
    if not dirty:
        return
    for (cid,) in dirty:
        row = db.execute("SELECT document FROM cases WHERE id=?", (cid,)).fetchone()
        if row is None:
            db.execute("DELETE FROM case_summaries WHERE case_id=?", (cid,))
            db.execute("DELETE FROM case_links WHERE downstream_case_id=?", (cid,))
            db.execute("DELETE FROM evidence_index WHERE case_id=?", (cid,))
            db.execute("DELETE FROM stale_cases WHERE case_id=?", (cid,))
            continue
        case = json.loads(row[0])
        sync_case_indexes(db, case)


def _install_index_dirty_triggers(db: sqlite3.Connection) -> None:
    """Repair derived caches after direct SQL mutations, including deleted rows.

    sync_case_indexes clears the dirty marker only after all three projections
    have been rebuilt. These triggers never alter the authoritative case JSON.
    """
    for table, column in (
        ("case_summaries", "case_id"),
        ("case_links", "downstream_case_id"),
        ("evidence_index", "case_id"),
    ):
        for action, references in (
            ("insert", ("NEW",)), ("update", ("OLD", "NEW")), ("delete", ("OLD",)),
        ):
            statements = " ".join(
                f"INSERT OR IGNORE INTO stale_cases(case_id) VALUES ({ref}.{column});"
                for ref in references
            )
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_index_{action} "
                f"AFTER {action.upper()} ON {table} BEGIN {statements} END"
            )


def initialize_database(state_dir: Path, database: Path) -> None:
    """Migrate and repair indexes atomically; never infer completion from a table.

    sqlite3's connection context manager alone does not start a transaction for
    DDL. An explicit write transaction covers DDL, backfill and version markers,
    and serializes concurrent openers before they inspect migration state.
    """
    with connect_db(state_dir, database) as db:
        db.execute("BEGIN IMMEDIATE")
        version = _supported_database_version(db)
        existing_tables = {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        db.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY, document TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS evidence_snapshots (
                case_id TEXT NOT NULL, evidence_id TEXT NOT NULL, content BLOB NOT NULL,
                PRIMARY KEY(case_id, evidence_id),
                FOREIGN KEY(case_id) REFERENCES cases(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL, action TEXT NOT NULL,
                recorded_at TEXT NOT NULL, details TEXT NOT NULL,
                prev_event_hash TEXT,
                event_hash TEXT,
                FOREIGN KEY(case_id) REFERENCES cases(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS export_artifacts (
                case_id TEXT PRIMARY KEY, content BLOB NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS explorations (
                id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS explore_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                explore_id TEXT NOT NULL,
                action TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                details TEXT NOT NULL,
                prev_event_hash TEXT,
                event_hash TEXT,
                FOREIGN KEY(explore_id) REFERENCES explorations(id) ON DELETE CASCADE
            )
        """)
        has_kind_restrictions = "evidence_kind_restrictions" in existing_tables
        db.execute("""
            CREATE TABLE IF NOT EXISTS evidence_kind_restrictions (
                case_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                restricted_kind TEXT NOT NULL,
                kind_inference TEXT NOT NULL,
                artifact_json TEXT,
                PRIMARY KEY(case_id, evidence_id),
                FOREIGN KEY(case_id) REFERENCES cases(id)
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_evidence_kind_restrictions_sha256
            ON evidence_kind_restrictions(sha256)
        """)
        event_cols = {row[1] for row in db.execute("PRAGMA table_info(events)")}
        if "prev_event_hash" not in event_cols:
            db.execute("ALTER TABLE events ADD COLUMN prev_event_hash TEXT")
        if "event_hash" not in event_cols:
            db.execute("ALTER TABLE events ADD COLUMN event_hash TEXT")

        db.execute("""
            CREATE TABLE IF NOT EXISTS case_summaries (
                case_id TEXT PRIMARY KEY,
                question TEXT,
                state TEXT,
                domain TEXT,
                schema_version INTEGER,
                gate_version INTEGER,
                blind INTEGER,
                claim_count INTEGER,
                created_at TEXT,
                is_adjudicated INTEGER NOT NULL DEFAULT 0,
                claim_ids_json TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS case_links (
                downstream_case_id TEXT NOT NULL,
                prior_case_id TEXT NOT NULL,
                relation_kind TEXT NOT NULL,
                PRIMARY KEY(downstream_case_id, prior_case_id, relation_kind),
                FOREIGN KEY(downstream_case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_case_links_prior ON case_links(prior_case_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_case_links_downstream ON case_links(downstream_case_id)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS evidence_index (
                case_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                provenance TEXT NOT NULL,
                has_quote INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(case_id, evidence_id),
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_evidence_index_evidence_id ON evidence_index(evidence_id)")
        db.execute("CREATE TABLE IF NOT EXISTS stale_cases (case_id TEXT PRIMARY KEY)")
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cases_after_insert AFTER INSERT ON cases
            BEGIN
                INSERT OR IGNORE INTO stale_cases(case_id) VALUES (NEW.id);
            END
        """)
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cases_after_update AFTER UPDATE OF document ON cases
            BEGIN
                INSERT OR IGNORE INTO stale_cases(case_id) VALUES (NEW.id);
            END
        """)
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cases_after_delete AFTER DELETE ON cases
            BEGIN
                INSERT OR IGNORE INTO stale_cases(case_id) VALUES (OLD.id);
            END
        """)
        db.execute("CREATE TABLE IF NOT EXISTS storage_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        _install_index_dirty_triggers(db)
        maintenance = db.execute(
            "SELECT value FROM storage_metadata WHERE key='index_maintenance_revision'"
        ).fetchone()
        # Old V3 databases may already have been marked migrated despite a
        # failed backfill. Absence of this completion marker forces one repair,
        # even when every index table exists and user_version is already 3.
        needs_rebuild = (
            version < SCHEMA_VERSION
            or not has_kind_restrictions
            or not {"case_summaries", "case_links", "evidence_index", "stale_cases"} <= existing_tables
            or maintenance != (INDEX_MAINTENANCE_REVISION,)
            or db.execute(
                "SELECT 1 FROM cases c LEFT JOIN case_summaries s ON s.case_id=c.id "
                "WHERE s.case_id IS NULL LIMIT 1"
            ).fetchone() is not None
        )
        if needs_rebuild:
            for table in ("case_links", "evidence_index", "case_summaries", "stale_cases"):
                db.execute(f"DELETE FROM {table}")
            for case_id, document_text in db.execute("SELECT id, document FROM cases ORDER BY rowid ASC"):
                case = json.loads(document_text)
                if case.get("case_id") != case_id:
                    fail("case_integrity_error", "Stored case identity differs from its database key")
                sync_case_indexes(db, case)
                # Restore missing restrictions too, but never replace historical
                # restriction records as part of rebuilding disposable caches.
                for item in case.get("evidence", []):
                    if db.execute(
                        "SELECT 1 FROM evidence_kind_restrictions WHERE case_id=? AND evidence_id=?",
                        (case_id, item.get("evidence_id")),
                    ).fetchone() is None:
                        record_kind_restriction(db, case_id, item)
            db.execute(
                "INSERT OR REPLACE INTO storage_metadata(key,value) VALUES ('index_maintenance_revision',?)",
                (INDEX_MAINTENANCE_REVISION,),
            )
        else:
            sync_stale_cases(db)
        if version != SCHEMA_VERSION:
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def list_case_summaries(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return ordered metadata summaries without parsing full case JSON blobs."""
    sync_stale_cases(db)
    rows = db.execute(
        """
        SELECT s.case_id, s.question, s.state, s.domain, s.schema_version,
               s.gate_version, s.blind, s.claim_count, s.created_at
        FROM case_summaries s
        JOIN cases c ON c.id = s.case_id
        ORDER BY c.rowid ASC
        """
    ).fetchall()
    summaries = []
    for cid, question, state, domain, schema_version, gate_version, blind_int, claim_count, created_at in rows:
        summaries.append({
            "case_id": cid,
            "question": question,
            "state": state,
            "domain": domain,
            "schema_version": schema_version,
            "gate_version": gate_version,
            "blind": None if blind_int is None else bool(blind_int),
            "claim_count": claim_count,
            "created_at": created_at,
        })
    return summaries


def load_all_cases_by_id(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = db.execute("SELECT id, document FROM cases ORDER BY rowid ASC").fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}


def load_cases_for_ids(db: sqlite3.Connection, case_ids: set[str] | list[str]) -> dict[str, dict[str, Any]]:
    ordered_ids = [cid for cid in dict.fromkeys(case_ids) if cid]
    if not ordered_ids:
        return {}
    result: dict[str, dict[str, Any]] = {}
    # Chunk IN queries well below SQLite's parameter ceiling.
    for start in range(0, len(ordered_ids), 400):
        chunk = ordered_ids[start:start + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows = db.execute(
            f"SELECT id, document FROM cases WHERE id IN ({placeholders}) ORDER BY rowid ASC",
            tuple(chunk),
        ).fetchall()
        for row_id, raw_doc in rows:
            result[row_id] = json.loads(raw_doc)
    return result


def load_connected_component_cases(
    db: sqlite3.Connection,
    *,
    case_id: str | None = None,
    claim_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch only the case connected component(s) needed by claim_graph."""
    sync_stale_cases(db)
    if case_id is None and claim_id is None:
        return list(load_all_cases_by_id(db).values())
    seeds: set[str] = set()
    if case_id is not None:
        exists = db.execute("SELECT 1 FROM case_summaries WHERE case_id=?", (case_id,)).fetchone()
        if exists is None:
            return []
        seeds.add(case_id)
    elif claim_id is not None:
        rows = db.execute(
            "SELECT DISTINCT s.case_id FROM case_summaries s, json_each(s.claim_ids_json) WHERE json_each.value = ?",
            (claim_id,),
        ).fetchall()
        seeds.update(row[0] for row in rows)
        if not seeds:
            return []

    component: set[str] = set(seeds)
    frontier = list(seeds)
    while frontier:
        placeholders = ",".join("?" for _ in frontier)
        params = tuple(frontier) + tuple(frontier)
        rows = db.execute(
            f"""
            SELECT prior_case_id AS neighbor FROM case_links WHERE downstream_case_id IN ({placeholders})
            UNION
            SELECT downstream_case_id AS neighbor FROM case_links WHERE prior_case_id IN ({placeholders})
            """,
            params,
        ).fetchall()
        next_frontier: list[str] = []
        for (nb,) in rows:
            if nb and nb not in component:
                if db.execute("SELECT 1 FROM case_summaries WHERE case_id=?", (nb,)).fetchone():
                    component.add(nb)
                    next_frontier.append(nb)
        frontier = next_frontier
    return list(load_cases_for_ids(db, component).values())


def load_downstream_cases(db: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    """Load only cases with explicit downstream links pointing to case_id."""
    sync_stale_cases(db)
    rows = db.execute(
        """
        SELECT c.document
        FROM case_links l
        JOIN cases c ON c.id = l.downstream_case_id
        WHERE l.prior_case_id = ?
        GROUP BY c.id
        ORDER BY c.rowid ASC
        """,
        (case_id,),
    ).fetchall()
    return [json.loads(row[0]) for row in rows]


def lookup_evidence_case_ids(db: sqlite3.Connection, evidence_id: str) -> list[str]:
    sync_stale_cases(db)
    rows = db.execute("SELECT DISTINCT case_id FROM evidence_index WHERE evidence_id=?", (evidence_id,)).fetchall()
    return [row[0] for row in rows]


def load_calibration_relevant_cases(
    db: sqlite3.Connection,
    *,
    case_id: str | None = None,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    """Load only adjudicated cases (with optional filter) and their linked follow-ups/outcome sources."""
    sync_stale_cases(db)
    if case_id is not None:
        exists = db.execute("SELECT 1 FROM case_summaries WHERE case_id=?", (case_id,)).fetchone()
        if exists is None:
            return []
        seed_ids = {case_id}
    else:
        sql = "SELECT case_id FROM case_summaries WHERE is_adjudicated = 1"
        params: tuple[Any, ...] = ()
        if domain is not None:
            sql += " AND domain = ?"
            params = (domain,)
        rows = db.execute(sql, params).fetchall()
        seed_ids = {row[0] for row in rows}
        if not seed_ids:
            return []

    target_ids: set[str] = set(seed_ids)
    # Include downstream cases referencing any seed case.
    placeholders = ",".join("?" for _ in seed_ids)
    for (ds_cid,) in db.execute(
        f"SELECT DISTINCT downstream_case_id FROM case_links WHERE prior_case_id IN ({placeholders})",
        tuple(seed_ids),
    ).fetchall():
        target_ids.add(ds_cid)

    cases_map = load_cases_for_ids(db, target_ids)
    # Also resolve explicit follow_up_case_id / evidence_id cited by recorded calibration outcomes.
    extra_ids: set[str] = set()
    for c in cases_map.values():
        for co in c.get("calibration_outcomes") or ():
            if not isinstance(co, dict):
                continue
            fu_cid = co.get("follow_up_case_id")
            if isinstance(fu_cid, str) and fu_cid and fu_cid not in cases_map:
                extra_ids.add(fu_cid)
            ev_id = co.get("evidence_id")
            if isinstance(ev_id, str) and ev_id:
                for owner_cid in lookup_evidence_case_ids(db, ev_id):
                    if owner_cid not in cases_map:
                        extra_ids.add(owner_cid)
    if extra_ids:
        cases_map.update(load_cases_for_ids(db, extra_ids))
    return list(cases_map.values())


def append_event(db: sqlite3.Connection, case_id: str, action: str, details: dict[str, Any]) -> None:
    details_norm = json.loads(canonical_json(details))
    last_row = db.execute("SELECT sequence, event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
    if last_row is None:
        next_seq = 1
        prev_hash = "GENESIS"
    else:
        last_seq = int(last_row[0])
        next_seq = last_seq + 1
        prev_hash = last_row[1] if last_row[1] is not None else f"LEGACY_MIGRATED:{last_seq}"
    recorded_at = utc_now()
    event_hash = json_digest({
        "prev_event_hash": prev_hash,
        "sequence": next_seq,
        "case_id": case_id,
        "action": action,
        "recorded_at": recorded_at,
        "details": details_norm,
    })
    db.execute(
        "INSERT INTO events(sequence,case_id,action,recorded_at,details,prev_event_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
        (next_seq, case_id, action, recorded_at, canonical_json(details_norm), prev_hash, event_hash),
    )


def verify_event_chain(db: sqlite3.Connection, case_id: str | None = None) -> dict[str, Any]:
    """Verify contiguity and SHA-256 chain links across the events log."""
    rows = db.execute(
        "SELECT sequence, case_id, action, recorded_at, details, prev_event_hash, event_hash "
        "FROM events ORDER BY sequence ASC, rowid ASC"
    ).fetchall()
    broken: list[int] = []
    expected_seq = 1
    prev_expected_hash = "GENESIS"
    saw_hashed = False
    last_legacy_seq: int | None = None

    for seq, row_case, action, recorded_at, details_str, prev_hash, row_hash in rows:
        seq_broken = False
        if seq != expected_seq:
            seq_broken = True
        if prev_hash is None and row_hash is None:
            if saw_hashed:
                seq_broken = True
            else:
                last_legacy_seq = seq
        elif prev_hash is None or row_hash is None:
            seq_broken = True
            saw_hashed = True
        else:
            expected_prev = (
                f"LEGACY_MIGRATED:{last_legacy_seq}"
                if (not saw_hashed and last_legacy_seq is not None)
                else prev_expected_hash
            )
            saw_hashed = True
            if prev_hash != expected_prev:
                seq_broken = True
            try:
                parsed_details = json.loads(details_str)
                calc_hash = json_digest({
                    "prev_event_hash": prev_hash,
                    "sequence": seq,
                    "case_id": row_case,
                    "action": action,
                    "recorded_at": recorded_at,
                    "details": parsed_details,
                })
                if calc_hash != row_hash:
                    seq_broken = True
            except (ValueError, TypeError):
                seq_broken = True
            prev_expected_hash = row_hash
        if seq_broken and seq not in broken:
            broken.append(seq)
        expected_seq = seq + 1

    scoped = [r for r in rows if case_id is None or r[1] == case_id]
    event_count = len(scoped)
    hashed_event_count = sum(1 for r in scoped if r[6] is not None)
    legacy_unhashed_count = sum(1 for r in scoped if r[5] is None and r[6] is None)
    head_event_hash = next((r[6] for r in reversed(scoped) if r[6] is not None), None)

    if broken:
        status = "tampered"
    elif hashed_event_count > 0 and legacy_unhashed_count == 0:
        status = "verified"
    elif hashed_event_count > 0 and legacy_unhashed_count > 0:
        status = "partial_legacy_verified"
    elif legacy_unhashed_count > 0:
        status = "legacy_unhashed"
    else:
        status = "verified"

    return {
        "status": status,
        "event_count": event_count,
        "hashed_event_count": hashed_event_count,
        "legacy_unhashed_count": legacy_unhashed_count,
        "broken_sequences": broken,
        "head_event_hash": head_event_hash,
    }
