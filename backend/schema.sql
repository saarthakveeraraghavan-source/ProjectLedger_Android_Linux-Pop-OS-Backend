CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, administrator INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, until TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, budget_minor INTEGER NOT NULL CHECK(budget_minor>=0),
 categories TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
 budget_set INTEGER NOT NULL DEFAULT 1 CHECK(budget_set IN (0,1)));
CREATE TABLE IF NOT EXISTS memberships(project_id TEXT REFERENCES projects(id), user_id TEXT REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('administrator','editor','viewer')), PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS expenses(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 payload TEXT NOT NULL, version INTEGER NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, voided INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS operations(user_id TEXT NOT NULL REFERENCES users(id), id TEXT NOT NULL,
 request_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(user_id,id));
CREATE TABLE IF NOT EXISTS changes(revision INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id),
 expense_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
 project_id TEXT, action TEXT NOT NULL, before_json TEXT, after_json TEXT);
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), project_id TEXT NOT NULL REFERENCES projects(id),
 request_hash TEXT NOT NULL, original TEXT NOT NULL, result TEXT NOT NULL, confirmed TEXT);
CREATE TABLE IF NOT EXISTS workbooks(project_id TEXT PRIMARY KEY REFERENCES projects(id), path TEXT NOT NULL,
 mapping TEXT NOT NULL, expected_hash TEXT NOT NULL, status TEXT NOT NULL, error TEXT, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS workbook_jobs(project_id TEXT PRIMARY KEY REFERENCES projects(id), queued_at TEXT NOT NULL);
PRAGMA user_version=2;
