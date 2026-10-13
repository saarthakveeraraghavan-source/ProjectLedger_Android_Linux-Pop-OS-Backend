"""Real loopback HTTP smoke; synthetic data, temporary server, automatic cleanup."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from ledger.auth import create_user
from ledger.config import Settings
from ledger.db import Database

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ledger-http-smoke-') as temporary:
    settings=Settings(data_dir=Path(temporary))
    database=Database(settings)
    password=str(uuid4())+str(uuid4())
    with database.transaction() as db:
        create_user(db,'test-admin',password,True)
    environment={**os.environ,'LEDGER_DATA_DIR':temporary,'PYTHONPATH':str(root/'backend')}
    process=subprocess.Popen([str(root.parent/'.venv/bin/python'),'-m','uvicorn','ledger.api:create_app','--factory','--host','127.0.0.1','--port','18765','--no-access-log'],env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url='http://127.0.0.1:18765',timeout=10,trust_env=False) as client:
            for _ in range(50):
                try:
                    if client.get('/health').status_code==200: break
                except httpx.HTTPError: pass
                time.sleep(0.1)
            else: raise RuntimeError('Server did not become ready')
            session=client.post('/auth/login',json={'username':'test-admin','password':password}); session.raise_for_status()
            client.headers['Authorization']='Bearer '+session.json()['token']
            project=str(uuid4())
            result=client.put('/projects/'+project,json={'id':project,'name':'Smoke construction','budget_minor':10000000,'categories':['Cement']});result.raise_for_status()
            expense={'id':str(uuid4()),'project_id':project,'amount_minor':1250025,'category':'Cement','description':'Synthetic cement purchase','expense_date':'2026-10-12'}
            operation={'operation_id':str(uuid4()),'action':'create','expense':expense,'base_version':0}
            first=client.post('/sync/mutate',json=operation);first.raise_for_status()
            second=client.post('/sync/mutate',json=operation);second.raise_for_status();assert first.json()==second.json()
            analytics=client.get('/projects/'+project+'/analytics');analytics.raise_for_status();assert analytics.json()['total_minor']==1250025
            assert len(client.get('/sync/pull').json()['snapshot'])==1
            report={'transport':'actual_loopback_http','login':True,'project_creation':True,'expense_commit':True,'idempotent_retry':True,'exact_total_minor':1250025,'pull':True}
            (root/'docs/http-smoke.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report))
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait()
