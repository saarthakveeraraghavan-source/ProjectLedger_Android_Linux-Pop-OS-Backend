import json
from contextlib import closing
import os
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from .db import now
from .config import verify_vault_destination
from .workbooks import atomic_json, compatibility, file_hash, fsync_dir


def create_backup(database, destination):
    destination = Path(destination).resolve()
    verify_vault_destination(destination, database.settings.vault_mount)
    if destination.exists():
        raise ValueError('Use a new versioned backup directory')
    destination.mkdir(parents=True, mode=0o700)
    files = {}
    # Prevent financial writes/export publication while taking a database snapshot and workbook copies.
    with database.transaction() as locked:
        with database.connect() as source:
            with closing(sqlite3.connect(destination / 'ledger.db')) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup database integrity failed')
        os.chmod(destination / 'ledger.db', 0o600)
        for linked in locked.execute('SELECT * FROM workbooks'):
            source = Path(linked['path'])
            name = f'workbooks/{source.name}'
            (destination / 'workbooks').mkdir(exist_ok=True, mode=0o700)
            shutil.copy2(source, destination / name)
            compatibility(destination / name)
            files[name] = file_hash(destination / name)
        workbook_dir = database.settings.data_dir / 'workbooks'
        if workbook_dir.exists():
            for source in workbook_dir.iterdir():
                if source.is_file() and (source.suffix == '.xlsx' or source.name.endswith('.publish.json')):
                    name = 'workbooks/' + source.name
                    if name not in files:
                        (destination / 'workbooks').mkdir(exist_ok=True, mode=0o700)
                        shutil.copy2(source, destination / name)
                        files[name] = file_hash(destination / name)
        files['ledger.db'] = file_hash(destination / 'ledger.db')
        atomic_json(destination / 'manifest.json', {'format': 1, 'created_at': now(), 'files': files})
    verify_backup(destination)
    return destination


def verify_backup(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['format'] != 1 or 'ledger.db' not in manifest['files']:
        raise ValueError('Unsupported backup')
    for name, expected in manifest['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or file_hash(path) != expected:
            raise ValueError('Backup hash mismatch or unsafe path')
    with closing(sqlite3.connect(f'file:{directory / "ledger.db"}?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Backup integrity failed')
        from .models import Expense
        db.row_factory = sqlite3.Row
        for row in db.execute('SELECT * FROM expenses'):
            expense = Expense.model_validate_json(row['payload'])
            if str(expense.id) != row['id'] or str(expense.project_id) != row['project_id'] or row['version'] < 1:
                raise ValueError('Backup financial record identity/version failed')
    return manifest


def restore_backup(directory, destination):
    directory, destination = Path(directory).resolve(), Path(destination).resolve()
    vault = os.environ.get('LEDGER_VAULT_MOUNT')
    verify_vault_destination(destination, Path(vault) if vault else None)
    manifest = verify_backup(directory)
    if destination.exists():
        raise ValueError('Restore only to a NEW directory, never over live data')
    destination.mkdir(parents=True, mode=0o700)
    for name in manifest['files']:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(directory / name, target)
        target.chmod(0o600)
    with closing(sqlite3.connect(destination / 'ledger.db')) as db:
        for project, oldpath, expected in db.execute('SELECT project_id,path,expected_hash FROM workbooks').fetchall():
            target = destination / 'workbooks' / Path(oldpath).name
            db.execute('UPDATE workbooks SET path=?,status=? WHERE project_id=?', (str(target), 'queued', project))
            db.execute('INSERT OR REPLACE INTO workbook_jobs VALUES(?,?)', (project, now()))
        db.execute("UPDATE meta SET value=? WHERE key='epoch'", (str(uuid4()),))
        db.execute('DELETE FROM sessions')
        db.commit()
    fsync_dir(destination)
    return destination
