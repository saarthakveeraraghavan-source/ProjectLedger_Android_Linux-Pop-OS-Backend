import contextlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, administrator INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, until TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, budget_minor INTEGER NOT NULL CHECK(budget_minor>=0),
 categories TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
 budget_set INTEGER NOT NULL DEFAULT 1 CHECK(budget_set IN (0,1)));
CREATE TABLE IF NOT EXISTS memberships(project_id TEXT REFERENCES projects(id), user_id TEXT REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('administrator','editor','viewer')), PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS expenses(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 payload TEXT NOT NULL, version INTEGER NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, voided INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS operations(user_id TEXT NOT NULL REFERENCES users(id), id TEXT NOT NULL,
 request_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(user_id,id));
CREATE TABLE IF NOT EXISTS changes(revision INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id),
 expense_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
 project_id TEXT, action TEXT NOT NULL, before_json TEXT, after_json TEXT);
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), project_id TEXT NOT NULL REFERENCES projects(id),
 request_hash TEXT NOT NULL, original TEXT NOT NULL, result TEXT NOT NULL, confirmed TEXT);
CREATE TABLE IF NOT EXISTS workbooks(project_id TEXT PRIMARY KEY REFERENCES projects(id), path TEXT NOT NULL,
 mapping TEXT NOT NULL, expected_hash TEXT NOT NULL, status TEXT NOT NULL, error TEXT, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS workbook_jobs(project_id TEXT PRIMARY KEY REFERENCES projects(id), queued_at TEXT NOT NULL);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class Database:
    def __init__(self, settings):
        self.settings = settings
        settings.verify_storage()
        self._storage_fd = os.open(settings.data_dir, os.O_RDONLY | os.O_DIRECTORY) if settings.vault_mount else None
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError("Database is newer than this server; restore compatible code")
            if version == 1:
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('ALTER TABLE projects ADD COLUMN budget_set INTEGER NOT NULL DEFAULT 1 CHECK(budget_set IN (0,1))')
                    db.execute('PRAGMA user_version=2')
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            db.executescript(SCHEMA)
            db.execute('PRAGMA user_version=2')
            db.execute("INSERT OR IGNORE INTO meta VALUES('epoch',?)", (str(uuid4()),))
        os.chmod(settings.database, 0o600)

    def close(self):
        if self._storage_fd is not None:
            os.close(self._storage_fd)
            self._storage_fd = None

    @contextlib.contextmanager
    def connect(self):
        self.settings.verify_storage()
        db = sqlite3.connect(self.settings.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise


def audit(db, actor, project, action, before=None, after=None):
    db.execute("INSERT INTO audit(at,actor,project_id,action,before_json,after_json) VALUES(?,?,?,?,?,?)",
               (now(), actor, project, action, encode(before) if before is not None else None,
                encode(after) if after is not None else None))


def expense_record(row):
    return {**json.loads(row["payload"]), "version": row["version"], "owner_id": row["owner_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "voided": bool(row["voided"])}


def project_budget(row):
    return row['budget_minor'] if row['budget_set'] else None
