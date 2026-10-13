import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException

from .db import audit, now

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(db, username, password, administrator=False):
    identifier = str(uuid4())
    db.execute("INSERT INTO users(id,username,password_hash,administrator) VALUES(?,?,?,?)",
               (identifier, username, hasher.hash(password), int(administrator)))
    return identifier


def login(database, username, password, client):
    key = digest(client + ":" + username.lower())
    with database.transaction() as db:
        attempt = db.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
        if attempt and attempt["until"] > now() and attempt["count"] >= 8:
            raise HTTPException(429, "Too many attempts; retry in 15 minutes")
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        try:
            valid = hasher.verify(user["password_hash"] if user else DUMMY_HASH, password)
        except VerificationError:
            valid = False
        if not valid or not user or not user["active"]:
            count = attempt["count"] + 1 if attempt and attempt["until"] > now() else 1
            until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            db.execute("INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)", (key, count, until))
            failure = True
        else:
            failure = False
            db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
            token = secrets.token_urlsafe(48)
            expires = (datetime.now(timezone.utc) + timedelta(hours=database.settings.session_hours)).isoformat()
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), user["id"], expires))
            audit(db, user["id"], None, "login")
    if failure:
        raise HTTPException(401, "Invalid credentials")
    return {"token": token, "user_id": user["id"], "username": user["username"],
            "administrator": bool(user["administrator"]), "expires_at": expires}


def authenticate(db, token):
    user = db.execute("SELECT u.*,s.expires FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.hash=?",
                      (digest(token),)).fetchone()
    if not user or not user["active"] or user["expires"] <= now():
        raise HTTPException(401, "Session expired or revoked")
    return dict(user)


def authorize(db, user, project_id, write=False, admin=False):
    active = db.execute('SELECT active FROM users WHERE id=?', (user['id'],)).fetchone()
    if not active or not active[0]:
        raise HTTPException(401, 'Account revoked')
    row = db.execute("SELECT role FROM memberships WHERE project_id=? AND user_id=?", (project_id, user["id"])).fetchone()
    if not row or (admin and row[0] != "administrator") or (write and row[0] == "viewer"):
        raise HTTPException(403, "Project permission denied")
    return row[0]
