"""Run with the backend stopped; migrate the vault DB and verify old rows without printing them."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from ledger.config import Settings
from ledger.db import Database

root = Path(__file__).resolve().parents[1]
plain = root/'.vault/plain'
settings = Settings(data_dir=plain/'data', vault_mount=plain)
tables = ('users', 'projects', 'memberships', 'expenses', 'sessions', 'operations', 'changes', 'audit', 'proposals', 'workbooks', 'workbook_jobs', 'meta', 'login_attempts')
def snapshot():
    fingerprints = {}
    with closing(sqlite3.connect(settings.database)) as db:
        for table in tables:
            columns = 'id,name,budget_minor,categories,archived,version' if table == 'projects' else '*'
            rows = sorted(db.execute(f'SELECT {columns} FROM {table}').fetchall(), key=repr)
            fingerprints[table] = hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()
        version = db.execute('PRAGMA user_version').fetchone()[0]
    return fingerprints, version
before, old_version = snapshot()
database = Database(settings)
try:
    after, new_version = snapshot()
    assert before == after, 'Existing rows changed during migration; retain the pre-upgrade backup'
    with database.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
finally:
    database.close()
report = {'old_schema': old_version, 'new_schema': new_version, 'all_existing_rows_preserved': True,
          'sqlite_integrity': 'ok', 'foreign_keys': 'ok', 'financial_values_and_credentials': 'compared privately; not printed'}
(root/'docs/deployment-migration-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
