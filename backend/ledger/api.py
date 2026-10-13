import asyncio
import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field

from .ai import OllamaProvider, interpret, query_plan
from .auth import authenticate, authorize, create_user, digest, hasher, login
from .config import Settings
from .db import Database, audit, encode, expense_record, now, project_budget
from .models import AIRequest, Login, Membership, Mutation, Project, StrictModel, UserCreate, WorkbookMapping
from .service import mutate, summarize
from .workbooks import drain_jobs, file_hash, import_link, inspect, process_job, reconcile_external

security = HTTPBearer(auto_error=False)


class PasswordReset(StrictModel):
    password: str = Field(min_length=12, max_length=256)


class Reconcile(StrictModel):
    reviewed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: bool


class Question(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    reference_date: date


def create_app(settings=None, provider=None):
    settings = settings or Settings()
    database = Database(settings)
    provider = provider or OllamaProvider(settings)

    @asynccontextmanager
    async def lifespan(app):
        async def jobs():
            while True:
                await asyncio.to_thread(drain_jobs, database)
                await asyncio.sleep(30)
        task = asyncio.create_task(jobs())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        database.close()

    app = FastAPI(title='Project Ledger', version='0.2.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.database = database

    @app.middleware('http')
    async def private_headers(request, call_next):
        length = request.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > settings.upload_limit + 1024 * 1024):
            return Response('Request too large', status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def user(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if not credentials:
            raise HTTPException(401, 'Login required')
        with database.connect() as db:
            return authenticate(db, credentials.credentials)

    def administrator(current):
        if not current['administrator']:
            raise HTTPException(403, 'System administrator required')

    @app.get('/health')
    def health():
        return {'status': 'ok', 'protocol': 1}

    @app.post('/auth/login')
    def sign_in(body: Login, request: Request):
        return login(database, body.username, body.password, request.client.host if request.client else 'local')

    @app.post('/auth/logout')
    def logout(current=Depends(user), credentials=Depends(security)):
        with database.transaction() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (digest(credentials.credentials),))
        return {'revoked': True}

    @app.post('/users', status_code=201)
    def provision(body: UserCreate, current=Depends(user)):
        administrator(current)
        with database.transaction() as db:
            try:
                identifier = create_user(db, body.username, body.password, body.administrator)
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, 'Username already exists') from exc
            audit(db, current['id'], None, 'provision_user', after={'id': identifier, 'username': body.username})
        return {'id': identifier, 'username': body.username}

    @app.get('/users')
    def users(current=Depends(user)):
        administrator(current)
        with database.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,username,administrator,active FROM users')]

    @app.post('/users/{identifier}/revoke')
    def revoke(identifier: UUID, current=Depends(user)):
        administrator(current)
        if str(identifier) == current['id']:
            raise HTTPException(409, 'Cannot revoke your own administrator account')
        with database.transaction() as db:
            db.execute('UPDATE users SET active=0 WHERE id=?', (str(identifier),))
            db.execute('DELETE FROM sessions WHERE user_id=?', (str(identifier),))
            audit(db, current['id'], None, 'revoke_user', after={'id': str(identifier)})
        return {'revoked': True}

    @app.post('/users/{identifier}/reset-password')
    def reset(identifier: UUID, body: PasswordReset, current=Depends(user)):
        administrator(current)
        with database.transaction() as db:
            db.execute('UPDATE users SET password_hash=?,active=1 WHERE id=?', (hasher.hash(body.password), str(identifier)))
            db.execute('DELETE FROM sessions WHERE user_id=?', (str(identifier),))
            audit(db, current['id'], None, 'reset_password', after={'id': str(identifier)})
        return {'reset': True}

    @app.put('/projects/{identifier}')
    def save_project(identifier: UUID, body: Project, current=Depends(user)):
        if identifier != body.id:
            raise HTTPException(422, 'Project identity mismatch')
        with database.transaction() as db:
            request_hash = hashlib.sha256(('project:' + encode(body.model_dump(mode='json'))).encode()).hexdigest()
            if body.operation_id:
                prior = db.execute('SELECT * FROM operations WHERE user_id=? AND id=?', (current['id'], str(body.operation_id))).fetchone()
                if prior:
                    authorize(db, current, str(identifier), admin=True)
                    if prior['request_hash'] != request_hash:
                        raise HTTPException(409, 'Project operation identity reused')
                    return json.loads(prior['response'])
            row = db.execute('SELECT * FROM projects WHERE id=?', (str(identifier),)).fetchone()
            if row:
                authorize(db, current, str(identifier), admin=True)
                if body.base_version != row['version']:
                    raise HTTPException(409, {'code': 'project_version_conflict', 'current': dict(row)})
                db.execute('UPDATE projects SET name=?,budget_minor=?,budget_set=?,categories=?,archived=?,version=version+1 WHERE id=?',
                           (body.name, body.budget_minor or 0, body.budget_minor is not None, encode(body.categories), body.archived, str(identifier)))
            else:
                administrator(current)
                if body.base_version != 0:
                    raise HTTPException(409, 'Unknown project version')
                db.execute('INSERT INTO projects(id,name,budget_minor,categories,archived,version,budget_set) VALUES(?,?,?,?,?,1,?)', (str(identifier), body.name, body.budget_minor or 0, encode(body.categories), body.archived, body.budget_minor is not None))
                db.execute('INSERT INTO memberships VALUES(?,?,?)', (str(identifier), current['id'], 'administrator'))
            audit(db, current['id'], str(identifier), 'save_project', dict(row) if row else None, body.model_dump(mode='json'))
            version = db.execute('SELECT version FROM projects WHERE id=?', (str(identifier),)).fetchone()[0]
            result = {'id': str(identifier), 'version': version}
            if body.operation_id:
                db.execute('INSERT INTO operations VALUES(?,?,?,?)', (current['id'], str(body.operation_id), request_hash, encode(result)))
        return result

    @app.put('/projects/{identifier}/members')
    def members(identifier: UUID, body: Membership, current=Depends(user)):
        with database.transaction() as db:
            authorize(db, current, str(identifier), admin=True)
            if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (str(body.user_id),)).fetchone():
                raise HTTPException(404, 'Active user not found')
            old = db.execute('SELECT role FROM memberships WHERE project_id=? AND user_id=?', (str(identifier), str(body.user_id))).fetchone()
            if old and old[0] == 'administrator' and body.role != 'administrator':
                count = db.execute("SELECT COUNT(*) FROM memberships m JOIN users u ON u.id=m.user_id WHERE project_id=? AND role='administrator' AND u.active=1", (str(identifier),)).fetchone()[0]
                if count <= 1:
                    raise HTTPException(409, 'Project must retain an active administrator')
            if body.role == 'removed':
                db.execute('DELETE FROM memberships WHERE project_id=? AND user_id=?', (str(identifier), str(body.user_id)))
            else:
                db.execute('INSERT OR REPLACE INTO memberships VALUES(?,?,?)', (str(identifier), str(body.user_id), body.role))
            audit(db, current['id'], str(identifier), 'membership', after=body.model_dump(mode='json'))
        return {'updated': True}

    @app.get('/projects/{identifier}/members')
    def list_members(identifier: UUID, current=Depends(user)):
        with database.connect() as db:
            authorize(db, current, str(identifier), admin=True)
            return [dict(r) for r in db.execute('SELECT u.id,u.username,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=?', (str(identifier),))]

    @app.post('/sync/mutate')
    def change(body: Mutation, background: BackgroundTasks, current=Depends(user)):
        with database.transaction() as db:
            # Recheck session principal's active state at mutation time.
            if not db.execute('SELECT active FROM users WHERE id=?', (current['id'],)).fetchone()[0]:
                raise HTTPException(401, 'Account revoked')
            result = mutate(db, current, body)
        background.add_task(process_job, database, str(body.expense.project_id))
        return result

    @app.get('/sync/pull')
    def pull(cursor: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000), epoch: str | None = None, current=Depends(user)):
        with database.connect() as db:
            db.execute('BEGIN')
            server_epoch = db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0]
            if epoch and epoch != server_epoch:
                raise HTTPException(409, {'code': 'server_restored', 'epoch': server_epoch})
            projects = [dict(r) for r in db.execute('SELECT p.*,m.role FROM projects p JOIN memberships m ON p.id=m.project_id WHERE m.user_id=?', (current['id'],))]
            for project in projects:
                project['categories'] = json.loads(project['categories'])
                project['archived'] = bool(project['archived'])
                project['budget_minor'] = project_budget(project)
            changes = db.execute('SELECT c.* FROM changes c JOIN memberships m ON c.project_id=m.project_id WHERE m.user_id=? AND c.revision>? ORDER BY c.revision LIMIT ?', (current['id'], cursor, limit)).fetchall()
            high = db.execute('SELECT COALESCE(MAX(revision),0) FROM changes').fetchone()[0]
            next_cursor = changes[-1]['revision'] if len(changes) == limit else high
            # Full authorized snapshots handle newly granted access even when the device cursor is ahead of old changes.
            snapshots = [expense_record(r) for r in db.execute('SELECT e.* FROM expenses e JOIN memberships m ON e.project_id=m.project_id WHERE m.user_id=?', (current['id'],))]
            workbooks = [dict(r) for r in db.execute('SELECT w.project_id,w.status,w.error,w.version FROM workbooks w JOIN memberships m ON w.project_id=m.project_id WHERE m.user_id=?', (current['id'],))]
            return {'epoch': server_epoch, 'cursor': next_cursor, 'has_more': len(changes) == limit,
                    'changes': [json.loads(r['payload']) for r in changes], 'snapshot': snapshots,
                    'projects': projects, 'workbooks': workbooks, 'synced_at': now(), 'session_expires_at': current['expires']}

    @app.get('/projects/{identifier}/analytics')
    def analytics(identifier: UUID, start: date | None = None, end: date | None = None, category: str | None = None,
                  vendor: str | None = None, search: str | None = None, current=Depends(user)):
        with database.connect() as db:
            authorize(db, current, str(identifier))
            records = [expense_record(r) for r in db.execute('SELECT * FROM expenses WHERE project_id=?', (str(identifier),))]
            filtered = [r for r in records if (not start or r['expense_date'] >= start.isoformat()) and (not end or r['expense_date'] <= end.isoformat()) and (not category or r['category'].casefold() == category.casefold()) and (not vendor or r['vendor'].casefold() == vendor.casefold()) and (not search or search.lower() in encode(r).lower())]
            budget = project_budget(db.execute('SELECT budget_minor,budget_set FROM projects WHERE id=?', (str(identifier),)).fetchone())
            overall = summarize(records, budget)
            return {**summarize(filtered, budget), 'transactions': filtered,
                    'remaining_minor': overall['remaining_minor'], 'project_total_minor': overall['total_minor'],
                    'budget_basis': 'all_project_records', 'budget_source_ids': overall['source_ids']}

    @app.post('/projects/{identifier}/ai/interpret')
    def extract(identifier: UUID, body: AIRequest, current=Depends(user)):
        project_id = str(identifier)
        request_hash = hashlib.sha256(encode(body.model_dump(mode='json')).encode()).hexdigest()
        with database.connect() as db:
            authorize(db, current, project_id, write=True)
            previous = db.execute('SELECT * FROM proposals WHERE id=?', (str(body.id),)).fetchone()
            if previous:
                if previous['user_id'] != current['id'] or previous['project_id'] != project_id or previous['request_hash'] != request_hash:
                    raise HTTPException(409, 'AI request identity reused')
                return json.loads(previous['result'])
            project = dict(db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone())
        result = interpret(provider, body, project)
        with database.transaction() as db:
            authorize(db, current, project_id, write=True)
            # Another request may have completed while inference ran; first committed result wins.
            previous = db.execute('SELECT * FROM proposals WHERE id=?', (str(body.id),)).fetchone()
            if previous:
                if previous['request_hash'] != request_hash or previous['user_id'] != current['id'] or previous['project_id'] != project_id:
                    raise HTTPException(409, 'AI request identity reused')
                return json.loads(previous['result'])
            db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,NULL)', (str(body.id), current['id'], project_id, request_hash, body.text, encode(result)))
            for item in result['proposals']:
                db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,NULL)', (item['id'], current['id'], project_id, request_hash, body.text, encode(item)))
        return result

    @app.post('/ai/question')
    def ask_across_projects(body: Question, current=Depends(user)):
        with database.connect() as db:
            projects = db.execute('SELECT p.* FROM projects p JOIN memberships m ON p.id=m.project_id WHERE m.user_id=?', (current['id'],)).fetchall()
            records = [expense_record(r) for r in db.execute('SELECT e.* FROM expenses e JOIN memberships m ON e.project_id=m.project_id WHERE m.user_id=?', (current['id'],))]
        plan = query_plan(provider, body.text, body.reference_date, records)
        calculations = []
        for project in projects:
            data = analytics(UUID(project['id']), plan.start, plan.end, plan.category, plan.vendor, None, current)
            calculations.append({'project_id': project['id'], 'project_name': project['name'], **question_data(data, plan)})
        ranked = sorted(calculations, key=lambda item: item['total_minor'], reverse=True)
        overall_largest = largest_records([r for p in calculations for r in p['transactions']])
        return {'interpretation': plan.model_dump(mode='json'), 'projects': ranked,
                'largest_transactions': overall_largest,
                'basis': 'authorized_database_records', 'total_minor': sum(p['total_minor'] for p in calculations),
                'explanation': 'Projects ranked by deterministic filtered expenditure; inspect source transactions and filters.'}

    @app.post('/projects/{identifier}/ai/question')
    def ask(identifier: UUID, body: Question, current=Depends(user)):
        with database.connect() as db:
            authorize(db, current, str(identifier))
            records = [expense_record(r) for r in db.execute('SELECT * FROM expenses WHERE project_id=?', (str(identifier),))]
        plan = query_plan(provider, body.text, body.reference_date, records)
        data = analytics(identifier, plan.start, plan.end, plan.category, plan.vendor, None, current)
        return {'interpretation': plan.model_dump(mode='json'), 'calculation': question_data(data, plan),
                'explanation': 'All figures are computed from authorized database records; review interpreted filters.'}

    @app.post('/workbooks/inspect')
    async def upload(file: UploadFile, current=Depends(user)):
        if not file.filename or not file.filename.lower().endswith('.xlsx'):
            raise HTTPException(422, 'Only plain .xlsx workbooks are supported')
        identifier = uuid4()
        directory = settings.data_dir / 'uploads'
        directory.mkdir(exist_ok=True, mode=0o700)
        path = directory / f'{identifier}.xlsx'
        size = 0
        try:
            with open(path, 'xb') as target:
                while chunk := await file.read(64 * 1024):
                    size += len(chunk)
                    if size > settings.upload_limit:
                        raise HTTPException(413, 'Workbook exceeds 20 MiB')
                    target.write(chunk)
            path.chmod(0o600)
            result = inspect(path)
            # Owner sidecar guards against reuse of another account's uploaded file.
            path.with_suffix('.owner').write_text(current['id'])
            return {'upload_id': str(identifier), **result}
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.post('/projects/{identifier}/workbook/link')
    def link(identifier: UUID, body: WorkbookMapping, background: BackgroundTasks, current=Depends(user)):
        owner = settings.data_dir / 'uploads' / f'{body.upload_id}.owner'
        if not owner.exists() or owner.read_text() != current['id']:
            raise HTTPException(403, 'Upload belongs to another session account')
        result = import_link(database, current, str(identifier), body)
        background.add_task(process_job, database, str(identifier))
        return result

    @app.get('/projects/{identifier}/workbook/inspect-current')
    def inspect_current(identifier: UUID, current=Depends(user)):
        with database.connect() as db:
            authorize(db, current, str(identifier), admin=True)
            linked = db.execute('SELECT * FROM workbooks WHERE project_id=?', (str(identifier),)).fetchone()
            if not linked:
                raise HTTPException(404, 'No workbook linked')
            return {'sha256': file_hash(linked['path']), **inspect(linked['path'])}

    @app.post('/projects/{identifier}/workbook/reconcile')
    def reconcile(identifier: UUID, body: Reconcile, background: BackgroundTasks, current=Depends(user)):
        if not body.confirmed:
            raise HTTPException(422, 'Explicit review confirmation required')
        result = reconcile_external(database, current, str(identifier), body.reviewed_sha256)
        background.add_task(process_job, database, str(identifier))
        return result

    @app.post('/projects/{identifier}/workbook/retry')
    def retry(identifier: UUID, current=Depends(user)):
        with database.transaction() as db:
            authorize(db, current, str(identifier), admin=True)
            db.execute('INSERT OR REPLACE INTO workbook_jobs VALUES(?,?)', (str(identifier), now()))
        process_job(database, str(identifier))
        with database.connect() as db:
            row = db.execute('SELECT status,error,version FROM workbooks WHERE project_id=?', (str(identifier),)).fetchone()
            return dict(row) if row else {'status': 'unlinked'}

    @app.get('/projects/{identifier}/workbook/download')
    def download(identifier: UUID, current=Depends(user)):
        with database.connect() as db:
            authorize(db, current, str(identifier))
            row = db.execute('SELECT * FROM workbooks WHERE project_id=?', (str(identifier),)).fetchone()
            if not row:
                raise HTTPException(404, 'No linked workbook')
            return FileResponse(row['path'], filename='ProjectLedger.xlsx', media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @app.get('/projects/{identifier}/audit')
    def history(identifier: UUID, current=Depends(user)):
        with database.connect() as db:
            authorize(db, current, str(identifier), admin=True)
            return [dict(r) for r in db.execute('SELECT * FROM audit WHERE project_id=? ORDER BY id DESC LIMIT 1000', (str(identifier),))]

    return app


def largest_records(records):
    expenses = [r for r in records if not r['voided'] and r['kind'] == 'expense']
    highest = max((r['amount_minor'] for r in expenses), default=None)
    return sorted((r for r in expenses if r['amount_minor'] == highest), key=lambda r: (r['expense_date'], r['id']))


def question_data(data, plan):
    data = {**data, 'transactions': [r for r in data['transactions'] if not r['voided']]}
    return {**data, 'largest_transactions': largest_records(data['transactions']) if plan.operation == 'largest' else []}
