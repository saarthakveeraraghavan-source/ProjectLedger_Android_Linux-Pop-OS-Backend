"""Actual temporary FUSE vault/database/workbook/backup test; never uses a production passphrase."""
import json
import os
import secrets
import subprocess
import tempfile
import shutil
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from ledger.auth import create_user
from ledger.backup import create_backup, restore_backup
from ledger.config import Settings, verify_vault
from ledger.db import Database
from ledger.models import Expense, Mutation, WorkbookMapping
from ledger.service import mutate
from ledger.workbooks import import_link, process_job

root=Path(__file__).resolve().parents[1]
gocryptfs=root/'.tools/gocryptfs/gocryptfs'
directory=tempfile.mkdtemp(prefix='encrypted-vault-test-',dir=root/'.tools')
if True:
    base=Path(directory);cipher=base/'cipher';plain=base/'plain';password=base/'test-password'
    cipher.mkdir(mode=0o700);plain.mkdir(mode=0o700)
    password.write_text(secrets.token_urlsafe(64));password.chmod(0o600)
    subprocess.run([str(gocryptfs),'-q','-init','-passfile',str(password),str(cipher)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([str(gocryptfs),'-q','-nosyslog','-noexec','-passfile',str(password),str(cipher),str(plain)],check=True)
    database=None;restored_db=None
    try:
        verify_vault(plain)
        settings=Settings(data_dir=plain/'data',vault_mount=plain)
        database=Database(settings)
        project=str(uuid4())
        with database.transaction() as db:
            user_id=create_user(db,'vault-test',secrets.token_urlsafe(32),True)
            db.execute('INSERT INTO projects(id,name,budget_minor,categories,archived,version) VALUES(?,?,?,?,?,1)',(project,'Vault fixture',10000000,json.dumps(['Transportation']),0))
            db.execute('INSERT INTO memberships VALUES(?,?,?)',(project,user_id,'administrator'))
        user={'id':user_id,'administrator':True}
        expense=Expense(id=uuid4(),project_id=project,amount_minor=1500025,category='Transportation',description='Vault synthetic transport Chennai',expense_date='2026-10-12')
        with database.transaction() as db:
            mutate(db,user,Mutation(operation_id=uuid4(),action='create',expense=expense,base_version=0))
        uploads=settings.data_dir/'uploads';uploads.mkdir()
        upload=uuid4();wb=Workbook();ws=wb.active;ws.title='Expenses';ws.append(['Date','Category','Amount','Description'])
        wb.save(uploads/f'{upload}.xlsx')
        import_link(database,user,project,WorkbookMapping(upload_id=upload,sheet='Expenses',header_row=1,columns={'expense_date':'A','category':'B','amount_minor':'C','description':'D'},import_rows=False))
        assert process_job(database,project)
        backup=create_backup(database,plain/'backups'/'v1')
        restored=restore_backup(backup,plain/'restored')
        restored_db=Database(Settings(data_dir=restored,vault_mount=plain))
        with restored_db.connect() as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert json.loads(db.execute('SELECT payload FROM expenses').fetchone()[0])['amount_minor']==1500025
        # A live backend guard holds the encrypted filesystem busy; ordinary unmount must fail.
        blocked=subprocess.run(['fusermount3','-u',str(plain)],capture_output=True,text=True)
        assert blocked.returncode!=0,'Active data guard did not block unmount'
        restored_db.close();restored_db=None;database.close();database=None
        subprocess.run(['fusermount3','-u',str(plain)],check=True)
        assert not list(plain.iterdir())
        plaintext_found=False
        for file in cipher.rglob('*'):
            if file.is_file() and b'Vault synthetic transport Chennai' in file.read_bytes():plaintext_found=True
        assert not plaintext_found
        try:
            Settings(data_dir=plain/'data',vault_mount=plain)
        except RuntimeError: pass
        else:raise AssertionError('Locked vault fallback was not rejected')
        subprocess.run([str(gocryptfs),'-q','-nosyslog','-noexec','-passfile',str(password),str(cipher),str(plain)],check=True)
        reopened=Database(Settings(data_dir=plain/'data',vault_mount=plain))
        with reopened.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0]==1
        reopened.close()
        report={'gocryptfs':'2.6.1','actual_fuse_mount':True,'exact_amount_minor':1500025,'sqlite_integrity':'ok',
                'workbook_publication':'passed','backup_restore':'passed','busy_unmount_refused':True,
                'plaintext_marker_absent_from_ciphertext':True,'locked_startup_refused':True,'remount_persistence':'passed',
                'credentials':'temporary synthetic key only; production passphrase not created'}
        (root/'docs/encrypted-vault-verification.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report))
    finally:
        if restored_db:restored_db.close()
        if database:database.close()
        if os.path.ismount(plain):subprocess.run(['fusermount3','-u',str(plain)],check=True)
        if not os.path.ismount(plain):shutil.rmtree(base)
