import hashlib
import json
from fastapi import HTTPException

from .auth import authorize
from .db import audit, encode, expense_record, now


def mutate(db, user, mutation):
    expense = mutation.expense.model_dump(mode="json")
    project_id, identifier = expense["project_id"], expense["id"]
    authorize(db, user, project_id, write=True)
    request_hash = hashlib.sha256(encode(mutation.model_dump(mode="json")).encode()).hexdigest()
    previous = db.execute("SELECT * FROM operations WHERE user_id=? AND id=?", (user["id"], str(mutation.operation_id))).fetchone()
    if previous:
        if previous["request_hash"] != request_hash:
            raise HTTPException(409, {"code": "idempotency_key_reused"})
        return json.loads(previous["response"])
    project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if project["archived"]:
        raise HTTPException(409, {"code": "project_archived"})
    row = db.execute("SELECT * FROM expenses WHERE id=?", (identifier,)).fetchone()
    if row and row["project_id"] != project_id:
        raise HTTPException(409, {"code": "identifier_unavailable"})
    if (mutation.action == "create" and (row or mutation.base_version != 0)) or (
            mutation.action != "create" and (not row or row["version"] != mutation.base_version or row["voided"])):
        raise HTTPException(409, {"code": "version_conflict", "current": expense_record(row) if row else None})
    if mutation.action == "void" and not mutation.reason.strip():
        raise HTTPException(422, "A reason is required to void an expense")
    if mutation.action == "create" and not mutation.allow_duplicate:
        for candidate in db.execute("SELECT * FROM expenses WHERE project_id=? AND voided=0", (project_id,)):
            payload = json.loads(candidate["payload"])
            keys = ("amount_minor", "expense_date", "vendor", "description", "kind")
            if all(payload[k] == expense[k] for k in keys):
                raise HTTPException(409, {"code": "possible_duplicate", "current": expense_record(candidate)})
    if mutation.action == "create" and expense["source_proposal_id"]:
        proposal = db.execute("SELECT * FROM proposals WHERE id=? AND user_id=?",
                              (expense["source_proposal_id"], user["id"])).fetchone()
        if not proposal or proposal["confirmed"] or 'proposals' in json.loads(proposal['result']):
            raise HTTPException(409, {"code": "proposal_unavailable_or_confirmed"})
        authorize(db, user, proposal["project_id"], write=True)
        db.execute("UPDATE proposals SET confirmed=? WHERE id=?", (identifier, expense["source_proposal_id"]))
    timestamp = now()
    categories = json.loads(project['categories'])
    if mutation.action != 'void' and expense['category'] not in categories:
        if len(categories) >= 100:
            raise HTTPException(422, 'This project has 100 categories; ask an administrator to consolidate them')
        categories.append(expense['category'])
        db.execute('UPDATE projects SET categories=?,version=version+1 WHERE id=?', (encode(categories), project_id))
        audit(db, user['id'], project_id, 'add_category', after={'category': expense['category'], 'expense_id': identifier})
    if mutation.action == "create":
        db.execute("INSERT INTO expenses VALUES(?,?,?,?,?,?,?,0)",
                   (identifier, project_id, encode(expense), 1, user["id"], timestamp, timestamp))
    elif mutation.action == "update":
        db.execute("UPDATE expenses SET payload=?,version=version+1,updated_at=? WHERE id=?",
                   (encode(expense), timestamp, identifier))
    else:
        db.execute("UPDATE expenses SET voided=1,version=version+1,updated_at=? WHERE id=?", (timestamp, identifier))
    updated = expense_record(db.execute("SELECT * FROM expenses WHERE id=?", (identifier,)).fetchone())
    revision = db.execute("INSERT INTO changes(project_id,expense_id,payload) VALUES(?,?,?)",
                          (project_id, identifier, encode(updated))).lastrowid
    audit(db, user["id"], project_id, mutation.action, expense_record(row) if row else None,
          {"record": updated, "reason": mutation.reason, "duplicate_override": mutation.allow_duplicate})
    db.execute("INSERT OR REPLACE INTO workbook_jobs VALUES(?,?)", (project_id, timestamp))
    response = {"record": updated, "revision": revision, "workbook_status": "queued"}
    db.execute("INSERT INTO operations VALUES(?,?,?,?)", (user["id"], str(mutation.operation_id), request_hash, encode(response)))
    return response


def summarize(records, budget):
    categories, months, vendors = {}, {}, {}
    sources = []
    total = 0
    for record in records:
        if record["voided"]:
            continue
        value = record["amount_minor"] * (-1 if record["kind"] == "refund" else 1)
        total += value
        sources.append(record["id"])
        for group, key in ((categories, record["category"]), (months, record["expense_date"][:7]), (vendors, record["vendor"] or "Unknown")):
            group[key] = group.get(key, 0) + value
    return {"currency": "INR", "total_minor": total, "budget_minor": budget, "remaining_minor": budget - total if budget is not None else None,
            "categories": categories, "months": months, "vendors": vendors, "source_ids": sources,
            "calculated_at": now(), "basis": "authoritative_database"}
