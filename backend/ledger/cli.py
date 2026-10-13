import argparse
import getpass
from pathlib import Path
from uuid import uuid4

from .auth import create_user, hasher
from .backup import create_backup, restore_backup, verify_backup
from .config import Settings
from .db import Database, audit
from .workbooks import drain_jobs


def main():
    parser = argparse.ArgumentParser(description='Project Ledger local administration')
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    sub = parser.add_subparsers(dest='command', required=True)
    bootstrap = sub.add_parser('bootstrap')
    bootstrap.add_argument('username')
    recovery = sub.add_parser('recover-account')
    recovery.add_argument('username')
    sub.add_parser('migrate')
    sub.add_parser('workbook-worker')
    for name in ('backup', 'verify-backup', 'restore'):
        command = sub.add_parser(name)
        command.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.command == 'verify-backup':
        print(verify_backup(args.directory))
        return
    if args.command == 'restore':
        print(restore_backup(args.directory, args.data_dir))
        return
    database = Database(Settings(data_dir=args.data_dir.resolve()))
    if args.command in ('bootstrap', 'recover-account'):
        password = getpass.getpass('New password (12+ characters): ')
        if len(password) < 12 or len(password) > 256:
            parser.error('Password must have 12–256 characters')
        if password != getpass.getpass('Repeat password: '):
            parser.error('Passwords differ')
        with database.transaction() as db:
            if args.command == 'bootstrap':
                if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                    parser.error('Bootstrap is only allowed on an empty database')
                print(create_user(db, args.username, password, True))
            else:
                row = db.execute('SELECT id FROM users WHERE username=?', (args.username,)).fetchone()
                if not row:
                    parser.error('Unknown user')
                db.execute('UPDATE users SET password_hash=?,active=1 WHERE id=?', (hasher.hash(password), row[0]))
                db.execute('DELETE FROM sessions WHERE user_id=?', (row[0],))
                audit(db, 'local-console', None, 'account_recovery', after={'user_id': row[0]})
    elif args.command == 'backup':
        print(create_backup(database, args.directory))
    elif args.command == 'workbook-worker':
        drain_jobs(database)
    else:
        print('Schema version 2 verified')


if __name__ == '__main__':
    main()
