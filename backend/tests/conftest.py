from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from ledger.api import create_app
from ledger.auth import create_user
from ledger.config import Settings


class StubAI:
    result = {'expenses': [{'amount': '15000', 'category': 'Electrical', 'vendor': 'Rajesh',
                           'description': 'Electrical wiring', 'expense_date': '2026-10-11', 'kind': 'expense', 'payment_method': 'unknown'}],
              'warnings': [], 'needs_clarification': False}
    def structured(self, system, text, schema):
        return self.result


@pytest.fixture
def env(tmp_path):
    provider = StubAI()
    app = create_app(Settings(data_dir=tmp_path / 'data'), provider)
    with app.state.database.transaction() as db:
        admin = create_user(db, 'admin', 'correct-horse-battery', True)
        editor = create_user(db, 'editor', 'correct-horse-battery')
        viewer = create_user(db, 'viewer', 'correct-horse-battery')
        outsider = create_user(db, 'outsider', 'correct-horse-battery')
    with TestClient(app) as client:
        tokens = {}
        for name in ('admin', 'editor', 'viewer', 'outsider'):
            response = client.post('/auth/login', json={'username': name, 'password': 'correct-horse-battery'})
            assert response.status_code == 200
            tokens[name] = {'Authorization': 'Bearer ' + response.json()['token']}
        project = str(uuid4())
        response = client.put('/projects/' + project, headers=tokens['admin'], json={
            'id': project, 'name': 'Main building', 'budget_minor': 100_000_000,
            'categories': ['Electrical', 'Transportation', 'Cement', 'Labour', 'Miscellaneous']})
        assert response.status_code == 200
        for identifier, role in ((editor, 'editor'), (viewer, 'viewer')):
            assert client.put('/projects/' + project + '/members', headers=tokens['admin'], json={'user_id': identifier, 'role': role}).status_code == 200
        yield {'app': app, 'client': client, 'tokens': tokens, 'project': project, 'provider': provider,
               'users': {'admin': admin, 'editor': editor, 'viewer': viewer, 'outsider': outsider}}


def mutation(env, **changes):
    expense = {'id': str(uuid4()), 'project_id': env['project'], 'amount_minor': 300000, 'category': 'Transportation',
               'description': 'Cement transport Chennai to site', 'expense_date': '2026-10-12', 'vendor': 'Rajesh',
               'payment_method': 'upi', 'kind': 'expense'}
    expense.update(changes.pop('expense_changes', {}))
    return {'operation_id': str(uuid4()), 'action': 'create', 'expense': expense, 'base_version': 0, **changes}
