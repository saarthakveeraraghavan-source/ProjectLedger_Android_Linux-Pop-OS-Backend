from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from ledger.models import minor_units
from conftest import mutation


@pytest.mark.parametrize('text,expected', [('₹3,000',300000),('1.5 lakh',15000000),('2 crore',2000000000),('0.01',1),('INR 12,500.25',1250025)])
def test_exact_money(text, expected):
    assert minor_units(text) == expected


@pytest.mark.parametrize('text', ['NaN', 'Infinity', '-1', '0', '0.001', '1e999', 'abc'])
def test_invalid_money(text):
    with pytest.raises(ValueError):
        minor_units(text)


def send(env, body, who='editor'):
    return env['client'].post('/sync/mutate', json=body, headers=env['tokens'][who])


def test_idempotent_uncertain_acknowledgment(env):
    body = mutation(env)
    first = send(env, body)
    second = send(env, body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    data = env['client'].get('/projects/'+env['project']+'/analytics', headers=env['tokens']['viewer']).json()
    assert data['total_minor'] == 300000 and len(data['source_ids']) == 1
    body['expense']['amount_minor'] += 1
    assert send(env, body).json()['detail']['code'] == 'idempotency_key_reused'


def test_refund_void_budget_and_audit(env):
    body = mutation(env)
    assert send(env, body).status_code == 200
    refund = mutation(env, expense_changes={'amount_minor': 50000, 'kind': 'refund', 'description': 'Transport refund'})
    assert send(env, refund).status_code == 200
    data = env['client'].get('/projects/'+env['project']+'/analytics', headers=env['tokens']['viewer']).json()
    assert data['total_minor'] == 250000 and data['remaining_minor'] == 99750000
    assert data['categories']['Transportation'] == 250000
    void = {**body, 'operation_id': str(uuid4()), 'action': 'void', 'base_version': 1}
    assert send(env, void).status_code == 422
    void['reason'] = 'Entered wrong project'
    assert send(env, void).status_code == 200
    data = env['client'].get('/projects/'+env['project']+'/analytics', headers=env['tokens']['viewer']).json()
    assert data['total_minor'] == -50000
    assert send(env, void).status_code == 200
    history = env['client'].get('/projects/'+env['project']+'/audit', headers=env['tokens']['admin']).json()
    assert any(r['action'] == 'void' for r in history)


def test_concurrent_edit_conflict_retains_winner(env):
    body = mutation(env)
    assert send(env, body).status_code == 200
    a = {**body, 'operation_id': str(uuid4()), 'action': 'update', 'base_version': 1,
         'expense': {**body['expense'], 'amount_minor': 400000}}
    b = {**a, 'operation_id': str(uuid4()), 'expense': {**a['expense'], 'amount_minor': 500000}}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda pair: send(env,*pair), [(a,'editor'),(b,'admin')]))
    assert sorted(r.status_code for r in results) == [200,409]
    conflict = next(r for r in results if r.status_code == 409).json()['detail']
    assert conflict['code'] == 'version_conflict' and conflict['current']['version'] == 2


def test_multiuser_independent_entries(env):
    a = mutation(env)
    b = mutation(env, expense_changes={'description': 'More transport', 'amount_minor': 1})
    assert send(env,a).status_code == 200
    assert send(env,b,'admin').status_code == 200
    data = env['client'].get('/sync/pull',headers=env['tokens']['editor']).json()
    assert len(data['snapshot']) == 2
    assert {r['owner_id'] for r in data['snapshot']} == {env['users']['editor'],env['users']['admin']}
    assert len(data['changes']) == 2
    assert env['client'].get('/sync/pull',params={'cursor':data['cursor']},headers=env['tokens']['editor']).json()['changes'] == []


def test_duplicate_warning_explicit_override(env):
    a=mutation(env)
    assert send(env,a).status_code==200
    b={**a,'operation_id':str(uuid4()),'expense':{**a['expense'],'id':str(uuid4())}}
    assert send(env,b).json()['detail']['code']=='possible_duplicate'
    b['allow_duplicate']=True
    assert send(env,b).status_code==200


def test_authorization_revocation_project_isolation(env):
    body=mutation(env)
    assert send(env,body,'viewer').status_code==403
    assert send(env,body,'outsider').status_code==403
    assert env['client'].get('/projects/'+env['project']+'/analytics',headers=env['tokens']['outsider']).status_code==403
    assert env['client'].get('/sync/pull',headers=env['tokens']['outsider']).json()['snapshot']==[]
    assert env['client'].post('/users/'+env['users']['editor']+'/revoke',headers=env['tokens']['admin']).status_code==200
    assert send(env,body).status_code==401
    assert env['client'].post('/auth/login',json={'username':'editor','password':'correct-horse-battery'}).status_code==401


def test_amount_schema_date_and_category(env):
    for field,value in [('amount_minor',1.25),('amount_minor',True),('expense_date','2026-02-30'),('category','')]:
        body=mutation(env,expense_changes={field:value})
        assert send(env,body).status_code==422


def test_login_rate_limit(env):
    for _ in range(8):
        assert env['client'].post('/auth/login',json={'username':'bad','password':'wrong'}).status_code==401
    assert env['client'].post('/auth/login',json={'username':'bad','password':'wrong'}).status_code==429


def test_new_membership_includes_old_history(env):
    assert send(env,mutation(env)).status_code==200
    cursor=env['client'].get('/sync/pull',headers=env['tokens']['outsider']).json()['cursor']
    assert env['client'].put('/projects/'+env['project']+'/members',headers=env['tokens']['admin'],json={'user_id':env['users']['outsider'],'role':'viewer'}).status_code==200
    data=env['client'].get('/sync/pull',params={'cursor':cursor},headers=env['tokens']['outsider']).json()
    assert len(data['snapshot'])==1


def test_project_operation_retry_and_conflicting_budget(env):
    project=env['client'].get('/sync/pull',headers=env['tokens']['admin']).json()['projects'][0]
    body={'operation_id':str(uuid4()),'id':project['id'],'name':project['name'],'budget_minor':123456,
          'categories':project['categories'],'base_version':1}
    url='/projects/'+env['project']
    first=env['client'].put(url,headers=env['tokens']['admin'],json=body)
    assert first.status_code==200
    assert env['client'].put(url,headers=env['tokens']['admin'],json=body).json()==first.json()
    body['operation_id']=str(uuid4()); body['budget_minor']=999
    assert env['client'].put(url,headers=env['tokens']['admin'],json=body).status_code==409


def test_cross_project_financial_query_is_authorized(env):
    assert send(env,mutation(env)).status_code==200
    env['provider'].result={'operation':'categories','category':'Transportation'}
    result=env['client'].post('/ai/question',headers=env['tokens']['editor'],json={'text':'Which project has highest transportation expenditure?','reference_date':'2026-10-12'})
    assert result.status_code==200 and result.json()['total_minor']==300000
    assert len(result.json()['projects'])==1
    result=env['client'].post('/ai/question',headers=env['tokens']['outsider'],json={'text':'All spending','reference_date':'2026-10-12'})
    assert result.status_code==200 and result.json()['projects']==[]


def test_sync_project_wire_types_match_android_contract(env):
    result=env['client'].get('/sync/pull',headers=env['tokens']['admin'])
    assert result.status_code==200
    project=result.json()['projects'][0]
    assert type(project['archived']) is bool
    assert type(project['budget_minor']) is int
    assert type(project['version']) is int
    assert isinstance(project['categories'],list)


def test_filtered_summary_does_not_overstate_remaining_project_budget(env):
    assert send(env,mutation(env)).status_code==200
    assert send(env,mutation(env,expense_changes={'category':'Cement','amount_minor':100000,'description':'Cement purchase'})).status_code==200
    result=env['client'].get('/projects/'+env['project']+'/analytics',params={'category':'Transportation'},headers=env['tokens']['editor']).json()
    assert result['total_minor']==300000
    assert result['project_total_minor']==400000
    assert result['remaining_minor']==99600000
    assert len(result['budget_source_ids'])==2 and len(result['source_ids'])==1
