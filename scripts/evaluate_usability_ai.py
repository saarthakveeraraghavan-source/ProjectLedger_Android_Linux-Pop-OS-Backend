"""Exercise revised AI/category/question endpoints with local Ollama and disposable data."""
import json
import tempfile
import httpx
from unittest.mock import patch
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from ledger.api import create_app
from ledger.auth import create_user
from ledger.config import Settings
from ledger.ai import OllamaProvider

root = Path(__file__).resolve().parents[1]
report = {'model': 'qwen2.5:14b', 'data': 'synthetic disposable only', 'checks': {}}
with tempfile.TemporaryDirectory(prefix='ledger-usability-ai-') as directory:
    settings = Settings(data_dir=Path(directory))
    class RecordingProvider(OllamaProvider):
        output = None
        failure = None
        response_info = None
        def structured(self, *args):
            try:
                real_client = httpx.Client
                def inspect_response(response):
                    if response.request.url.path == '/api/chat':
                        response.read()
                        payload = response.json()
                        content = payload.get('message', {}).get('content', '')
                        self.response_info = {'done_reason': payload.get('done_reason'), 'eval_count': payload.get('eval_count'), 'content_length': len(content), 'content_sample': repr(content[:200])}
                def client(**kwargs):
                    return real_client(event_hooks={'response': [inspect_response]}, **kwargs)
                with patch('ledger.ai.httpx.Client', side_effect=client):
                    self.output = super().structured(*args)
                return self.output
            except Exception as error:
                self.failure = repr(error.__cause__)
                raise
    provider = RecordingProvider(settings)
    app = create_app(settings, provider)
    password = str(uuid4()) + str(uuid4())
    with app.state.database.transaction() as db:
        create_user(db, 'fixture', password, True)
    with TestClient(app) as client:
        session = client.post('/auth/login', json={'username': 'fixture', 'password': password})
        session.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + session.json()['token']
        identifier = str(uuid4())
        client.put('/projects/'+identifier, json={'id': identifier, 'name': 'Synthetic unbudgeted project'}).raise_for_status()
        proposal = client.post('/projects/'+identifier+'/ai/interpret', json={'id': str(uuid4()), 'text': 'Paid ₹4500 for land surveying today.', 'reference_date': date.today().isoformat()})
        if proposal.status_code != 200:
            raise RuntimeError(f'Synthetic interpretation failed: {proposal.json()}; provider failure: {provider.failure}; response metadata: {provider.response_info}; synthetic model output: {provider.output}')
        item = proposal.json()['proposals'][0]
        assert item['amount_minor'] == 450000 and item['category'] and item['description']
        assert client.get('/projects/'+identifier+'/analytics').json()['total_minor'] == 0
        assert client.get('/sync/pull').json()['projects'][0]['categories'] == []
        report['checks']['unconfirmed_new_category_and_expense_not_committed'] = True
        # Simulate explicit review in this synthetic test; real phone entries still require confirmation.
        expense = {'id': str(uuid4()), 'project_id': identifier, 'amount_minor': item['amount_minor'], 'category': item['category'],
                   'description': item['description'], 'expense_date': item['expense_date'], 'kind': item['kind'], 'source_proposal_id': item['id']}
        client.post('/sync/mutate', json={'operation_id': str(uuid4()), 'action': 'create', 'expense': expense, 'base_version': 0}).raise_for_status()
        historical = {**expense, 'id': str(uuid4()), 'amount_minor': 999900, 'expense_date': '2026-09-01', 'source_proposal_id': None, 'description': 'Older surveying contract'}
        client.post('/sync/mutate', json={'operation_id': str(uuid4()), 'action': 'create', 'expense': historical, 'base_version': 0}).raise_for_status()
        answer = client.post('/projects/'+identifier+'/ai/question', json={'text': 'What was the most expensive spending till now?', 'reference_date': date.today().isoformat()})
        answer.raise_for_status()
        assert answer.json()['interpretation']['operation'] == 'largest'
        assert answer.json()['interpretation']['start'] is None and answer.json()['interpretation']['category'] is None
        assert answer.json()['calculation']['largest_transactions'][0]['id'] == historical['id']
        assert answer.json()['calculation']['remaining_minor'] is None
        report['checks'].update(new_category_confirmed=True, largest_expense_from_all_history=True, optional_budget=True)
        report['proposal'] = {k: item[k] for k in ('amount_minor', 'category', 'description')}
(root/'docs/usability-ai-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
