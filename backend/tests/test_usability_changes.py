import json
import sqlite3
from uuid import uuid4

from conftest import mutation
from ledger.config import Settings
from ledger.db import Database


def test_project_without_budget_and_categories(env):
    identifier = str(uuid4())
    url = '/projects/' + identifier
    assert env['client'].put(url, headers=env['tokens']['admin'], json={'id': identifier, 'name': 'Unbudgeted'}).status_code == 200
    project = next(p for p in env['client'].get('/sync/pull', headers=env['tokens']['admin']).json()['projects'] if p['id'] == identifier)
    assert project['budget_minor'] is None and project['categories'] == []
    result = env['client'].get(url+'/analytics', headers=env['tokens']['admin']).json()
    assert result['remaining_minor'] is None and result['total_minor'] == 0


def test_new_category_added_only_on_confirmed_commit(env):
    env['provider'].result = json.loads(json.dumps(env['provider'].result))
    env['provider'].result['expenses'][0] = {**env['provider'].result['expenses'][0], 'category': 'Site security'}
    before = env['client'].get('/sync/pull', headers=env['tokens']['admin']).json()['projects'][0]
    proposal = env['client'].post('/projects/'+env['project']+'/ai/interpret', headers=env['tokens']['editor'], json={
        'id': str(uuid4()), 'text': 'Paid Rajesh ₹15000 for site security yesterday', 'reference_date': '2026-10-13'}).json()['proposals'][0]
    assert proposal['category'] == 'Site security'
    unconfirmed = env['client'].get('/sync/pull', headers=env['tokens']['admin']).json()
    assert 'Site security' not in unconfirmed['projects'][0]['categories'] and not unconfirmed['snapshot']
    body = mutation(env, expense_changes={'category': 'Site security', 'source_proposal_id': proposal['id']})
    first = env['client'].post('/sync/mutate', headers=env['tokens']['editor'], json=body)
    assert first.status_code == 200
    assert env['client'].post('/sync/mutate', headers=env['tokens']['editor'], json=body).json() == first.json()
    after = env['client'].get('/sync/pull', headers=env['tokens']['admin']).json()['projects'][0]
    assert after['categories'].count('Site security') == 1 and after['version'] == before['version'] + 1


def test_largest_expense_ignores_hallucinated_category_and_today(env):
    for amount, kind in [(10000, 'expense'), (20000, 'expense'), (999999, 'refund')]:
        assert env['client'].post('/sync/mutate', headers=env['tokens']['editor'], json=mutation(env, expense_changes={'amount_minor': amount, 'kind': kind})).status_code == 200
    env['provider'].result = {'operation': 'transactions', 'category': 'expense', 'vendor': None, 'start': '2026-10-13', 'end': '2026-10-13'}
    response = env['client'].post('/projects/'+env['project']+'/ai/question', headers=env['tokens']['editor'], json={
        'text': 'What was the most expensive spending till now?', 'reference_date': '2026-10-13'})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer['interpretation'] == {'operation': 'largest', 'category': None, 'vendor': None, 'start': None, 'end': None}
    assert len(answer['calculation']['largest_transactions']) == 1
    assert answer['calculation']['largest_transactions'][0]['amount_minor'] == 20000


def test_cross_project_largest_preserves_authorization(env):
    assert env['client'].post('/sync/mutate', headers=env['tokens']['editor'], json=mutation(env)).status_code == 200
    env['provider'].result = {'operation': 'largest'}
    for account, count in [('editor', 1), ('outsider', 0)]:
        response = env['client'].post('/ai/question', headers=env['tokens'][account], json={'text': 'Largest expense ever?', 'reference_date': '2026-10-13'})
        assert response.status_code == 200
        assert len(response.json()['largest_transactions']) == count


def test_explicit_date_and_category_are_retained(env):
    assert env['client'].post('/sync/mutate', headers=env['tokens']['editor'], json=mutation(env)).status_code == 200
    env['provider'].result = {'operation': 'total', 'category': 'Transportation', 'start': '2026-10-01', 'end': '2026-10-31'}
    response = env['client'].post('/projects/'+env['project']+'/ai/question', headers=env['tokens']['editor'], json={'text': 'Transportation spending this month', 'reference_date': '2026-10-13'})
    assert response.status_code == 200
    assert response.json()['interpretation']['category'] == 'Transportation'
    assert response.json()['calculation']['total_minor'] == 300000


def test_v1_budget_migration_preserves_values_and_epoch(tmp_path):
    settings = Settings(data_dir=tmp_path/'data')
    with sqlite3.connect(settings.database) as db:
        db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT INTO meta VALUES('epoch','original'); CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,budget_minor INTEGER NOT NULL,categories TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1); PRAGMA user_version=1;")
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?)', ('p', 'Existing', 12345, json.dumps(['Cement']), 0, 7))
    migrated = Database(settings)
    with migrated.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        project = dict(db.execute('SELECT * FROM projects').fetchone())
        assert project['budget_minor'] == 12345 and project['budget_set'] == 1 and project['version'] == 7
        assert db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0] == 'original'
    migrated.close()
