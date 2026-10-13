"""Conservative XLSX support; no macro/drawing/pivot/external-link round trips."""
import copy
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from defusedxml.ElementTree import fromstring
from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import column_index_from_string, get_column_letter

from .db import audit, encode, expense_record, now
from .models import Expense, Mutation, WorkbookMapping, minor_units
from .service import mutate

FIELDS = {'amount_minor', 'category', 'description', 'expense_date', 'vendor', 'payment_method', 'kind'}
REQUIRED = {'amount_minor', 'category', 'description', 'expense_date'}
META = ('_LedgerId', '_LedgerVersion', '_LedgerStatus')


def file_hash(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def fsync_dir(path):
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    with open(temp, 'w') as handle:
        handle.write(encode(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    fsync_dir(path.parent)


def compatibility(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(x.file_size for x in entries) > 100 * 1024 * 1024:
                raise ValueError('Workbook decompressed size exceeds the safe limit')
            allowed = ('xl/worksheets/', 'xl/tables/', 'xl/theme/', 'xl/_rels/')
            exact = {'[Content_Types].xml', '_rels/.rels', 'docProps/app.xml', 'docProps/core.xml',
                     'xl/workbook.xml', 'xl/styles.xml', 'xl/sharedStrings.xml', 'xl/calcChain.xml'}
            for entry in entries:
                name = entry.filename
                if name not in exact and not name.startswith(allowed):
                    raise ValueError(f'Unsupported workbook part: {name}. Original retained; use a plain XLSX copy.')
                if not name.endswith(('.xml', '.rels')) or entry.flag_bits & 1:
                    raise ValueError('Encrypted or binary workbook parts are unsupported')
                root = fromstring(archive.read(name))
                for element in root.iter():
                    if element.tag.split('}')[-1] in {'extLst', 'drawing', 'legacyDrawing', 'oleObjects', 'pivotTable', 'controls'}:
                        raise ValueError('Workbook extensions/drawings/embedded features cannot be safely preserved')
                    if element.attrib.get('TargetMode') == 'External':
                        raise ValueError('External links are unsupported for automatic synchronization')
            if archive.testzip():
                raise ValueError('Workbook CRC failed')
        wb = load_workbook(path, data_only=False, keep_links=False)
        if any(ws.max_row > 100_000 or ws.max_column > 300 for ws in wb):
            raise ValueError('Workbook sheet size exceeds supported limits')
        return wb
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc


def inspect(path):
    wb = compatibility(path)
    return {'supported': True, 'formula_values_recalculated': False, 'sheets': [
        {'name': ws.title, 'rows': ws.max_row, 'columns': ws.max_column,
         'headers': [{'column': get_column_letter(c.column), 'value': str(c.value or ''), 'format': c.number_format}
                     for c in ws[1]],
         'preview': [[str(c.value or '') for c in row] for row in ws.iter_rows(max_row=min(ws.max_row, 8))],
         'tables': list(ws.tables), 'formula_count': sum(c.data_type == 'f' for row in ws for c in row)} for ws in wb]}


def mapping_columns(ws, mapping):
    if set(mapping.columns) - FIELDS or not REQUIRED <= set(mapping.columns):
        raise HTTPException(422, 'Map amount, category, description, and date; only supported fields are allowed')
    try:
        columns = {k: column_index_from_string(v.upper()) for k, v in mapping.columns.items()}
    except ValueError as exc:
        raise HTTPException(422, 'Columns must be Excel letters such as A or B') from exc
    if len(set(columns.values())) != len(columns) or any(v > ws.max_column for v in columns.values()):
        raise HTTPException(422, 'Columns must be distinct and inside the worksheet')
    if any(ws.cell(mapping.header_row, v).value is None for v in columns.values()):
        raise HTTPException(422, 'Mapped columns need nonempty headers')
    if ws.merged_cells.ranges:
        raise HTTPException(422, 'Linked transaction sheets must not contain merged cells')
    return columns


def import_link(database, user, project_id, mapping):
    from .auth import authorize
    uploads = database.settings.data_dir / 'uploads'
    source = uploads / f'{mapping.upload_id}.xlsx'
    if not source.exists():
        raise HTTPException(404, 'Uploaded workbook missing')
    wb = compatibility(source)
    if mapping.sheet not in wb.sheetnames:
        raise HTTPException(422, 'Worksheet not found')
    ws = wb[mapping.sheet]
    columns = mapping_columns(ws, mapping)
    if any(c.value in META for c in ws[mapping.header_row]):
        raise HTTPException(422, "Workbook already contains Ledger identities; use reconciliation instead of importing it again")
    # Transaction rows must be contiguous. Totals/formulas in mapped financial cells fail closed.
    rows = []
    if not mapping.import_rows and any(ws.cell(r, c).value is not None for r in range(mapping.header_row + 1, ws.max_row + 1) for c in columns.values()):
        raise HTTPException(422, 'Skipping import is only supported for an empty transaction sheet')
    if mapping.import_rows:
        for row_index in range(mapping.header_row + 1, ws.max_row + 1):
            values = {field: ws.cell(row_index, col).value for field, col in columns.items()}
            if all(v is None for v in values.values()):
                continue
            if any(ws.cell(row_index, col).data_type == 'f' for col in columns.values()):
                raise HTTPException(422, f'Row {row_index}: mapped transaction fields cannot be formulas; move totals to another sheet')
            try:
                raw_date = values['expense_date']
                day = raw_date.date() if isinstance(raw_date, datetime) else raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
                kind = values.get('kind') or ('refund' if str(values['amount_minor']).strip().startswith('-') else 'expense')
                raw_amount = str(values['amount_minor']).strip()
                if raw_amount.startswith('-'):
                    if kind != 'refund':
                        raise ValueError('Negative amounts must be mapped as refunds')
                    raw_amount = raw_amount[1:]
                expense = Expense(id=uuid4(), project_id=project_id, amount_minor=minor_units(raw_amount),
                                  category=values['category'], description=values['description'], expense_date=day,
                                  vendor=str(values.get('vendor') or ''), payment_method=values.get('payment_method') or 'unknown', kind=kind)
                rows.append((row_index, expense))
            except Exception as exc:
                raise HTTPException(422, f'Row {row_index}: invalid transaction fields: {exc}') from exc
    directory = database.settings.data_dir / 'workbooks'
    directory.mkdir(exist_ok=True, mode=0o700)
    original = directory / f'{project_id}.original.xlsx'
    target = directory / f'{project_id}.xlsx'
    # Stage metadata in a private temporary file before touching any authoritative records.
    meta_cols = {}
    for header in META:
        col = ws.max_column + 1
        ws.cell(mapping.header_row, col, header)
        meta_cols[header] = col
    for row_index, expense in rows:
        ws.cell(row_index, meta_cols['_LedgerId'], str(expense.id))
        ws.cell(row_index, meta_cols['_LedgerVersion'], 1)
        ws.cell(row_index, meta_cols['_LedgerStatus'], 'active')
    descriptor, temporary = tempfile.mkstemp(suffix='.xlsx', dir=directory)
    os.close(descriptor)
    try:
        wb.save(temporary)
        compatibility(temporary)
        with database.transaction() as db:
            authorize(db, user, project_id, admin=True)
            if db.execute('SELECT 1 FROM workbooks WHERE project_id=?', (project_id,)).fetchone():
                raise HTTPException(409, 'Workbook already linked. Resolve external edits or unlink explicitly before replacing.')
            for _, expense in rows:
                mutate(db, user, Mutation(operation_id=uuid4(), action='create', expense=expense, base_version=0, allow_duplicate=True))
            shutil.copy2(source, original)
            os.chmod(original, 0o600)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
            fsync_dir(directory)
            db.execute('INSERT INTO workbooks VALUES(?,?,?,?,?,?,1)',
                       (project_id, str(target), encode(mapping.model_dump(mode='json')), file_hash(target), 'queued', None))
            db.execute('INSERT OR REPLACE INTO workbook_jobs VALUES(?,?)', (project_id, now()))
            audit(db, user['id'], project_id, 'workbook_import', after={'rows': len(rows), 'sha256': file_hash(source)})
        return {'imported': len(rows), 'status': 'queued'}
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def set_text(cell, value):
    # Explicit string type prevents =, +, -, @ content from becoming formulas.
    cell.value = str(value)
    cell.data_type = 's'


def render_workbook(path, mapping, records, output):
    wb = compatibility(path)
    ws = wb[mapping.sheet]
    cols = mapping_columns(ws, mapping)
    headers = {str(c.value): c.column for c in ws[mapping.header_row] if c.value is not None}
    if not all(header in headers for header in META):
        raise ValueError('Ledger identity columns changed; workbook requires reconciliation')
    index = {}
    for row in range(mapping.header_row + 1, ws.max_row + 1):
        identifier = ws.cell(row, headers['_LedgerId']).value
        if identifier:
            if identifier in index:
                raise ValueError('Duplicate workbook transaction identity')
            index[identifier] = row
    for record in records:
        row = index.get(record['id'])
        if row is None:
            row = max(ws.max_row + 1, mapping.header_row + 1)
            template = row - 1
            if template > mapping.header_row:
                for col in range(1, ws.max_column + 1):
                    src, dst = ws.cell(template, col), ws.cell(row, col)
                    dst._style = copy.copy(src._style)
                    if src.data_type == 'f' and col not in cols.values():
                        dst.value = Translator(src.value, origin=src.coordinate).translate_formula(dst.coordinate)
            index[record['id']] = row
        for field, col in cols.items():
            cell = ws.cell(row, col)
            value = record[field]
            if field == 'amount_minor':
                cell.value = Decimal(value) / Decimal(100)
                cell.number_format = '"₹" #,##0.00'
            elif field == 'expense_date':
                cell.value = date.fromisoformat(value)
                cell.number_format = 'yyyy-mm-dd'
            else:
                set_text(cell, value)
        set_text(ws.cell(row, headers['_LedgerId']), record['id'])
        ws.cell(row, headers['_LedgerVersion'], record['version'])
        set_text(ws.cell(row, headers['_LedgerStatus']), 'void' if record['voided'] else 'active')
        # Voids retain attribution and description but carry zero exported financial impact.
        if record['voided']:
            ws.cell(row, cols['amount_minor'], 0)
        elif record['kind'] == 'refund':
            ws.cell(row, cols['amount_minor'], -Decimal(record['amount_minor']) / Decimal(100))
    for table in ws.tables.values():
        from openpyxl.utils.cell import range_boundaries
        mincol, minrow, maxcol, _ = range_boundaries(table.ref)
        if table.totalsRowCount:
            raise ValueError('Tables with embedded totals require a plain transaction sheet')
        table.ref = f'{get_column_letter(mincol)}{minrow}:{get_column_letter(maxcol)}{ws.max_row}'
    wb.calculation.fullCalcOnLoad = True
    wb.save(output)
    generated = compatibility(output)
    actual = generated[mapping.sheet]
    found = {actual.cell(r, headers['_LedgerId']).value for r in range(mapping.header_row + 1, actual.max_row + 1)}
    if not {r['id'] for r in records} <= found:
        raise ValueError('Generated workbook is missing records')
    actual_rows = {actual.cell(r, headers['_LedgerId']).value: r for r in range(mapping.header_row + 1, actual.max_row + 1)}
    for record in records:
        exported = actual.cell(actual_rows[record['id']], cols['amount_minor']).value
        expected = 0 if record['voided'] else record['amount_minor'] * (-1 if record['kind'] == 'refund' else 1)
        if Decimal(str(exported)) * 100 != expected:
            raise ValueError('Excel cannot safely represent this amount; authoritative expense retained')
    # Verify every original formula outside managed cells survives; values are NOT recalculated here.
    original = compatibility(path)
    for sheet in original:
        for cells in sheet:
            for cell in cells:
                if cell.data_type == 'f' and generated[sheet.title][cell.coordinate].value != cell.value:
                    raise ValueError('Formula preservation verification failed')


def process_job(database, project_id):
    directory = database.settings.data_dir / 'workbooks'
    directory.mkdir(exist_ok=True, mode=0o700)
    lockpath = directory / f'{project_id}.lock'
    journal = directory / f'{project_id}.publish.json'
    with open(lockpath, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        with database.transaction() as db:
            linked = db.execute('SELECT * FROM workbooks WHERE project_id=?', (project_id,)).fetchone()
            if not linked:
                db.execute('DELETE FROM workbook_jobs WHERE project_id=?', (project_id,))
                return True
            path = Path(linked['path'])
            temporary = None
            try:
                expected = linked['expected_hash']
                if journal.exists():
                    pending = json.loads(journal.read_text())
                    if file_hash(path) == pending['new_hash'] and expected == pending['old_hash']:
                        expected = pending['new_hash']
                        db.execute('UPDATE workbooks SET expected_hash=? WHERE project_id=?', (expected, project_id))
                    elif file_hash(path) != expected:
                        raise ValueError('External workbook changes during interrupted export')
                    journal.unlink()
                if file_hash(path) != expected:
                    raise ValueError('External workbook edits detected. Export blocked until explicit reconciliation.')
                if (path.parent / ('~$' + path.name)).exists() or (path.parent / ('.~lock.' + path.name + '#')).exists():
                    raise ValueError('Workbook appears open in Excel/LibreOffice; close it and retry')
                records = [expense_record(r) for r in db.execute('SELECT * FROM expenses WHERE project_id=? ORDER BY created_at,id', (project_id,))]
                descriptor, temporary = tempfile.mkstemp(suffix='.xlsx', dir=directory)
                os.close(descriptor)
                render_workbook(path, WorkbookMapping.model_validate_json(linked['mapping']), records, temporary)
                with open(temporary, 'rb') as candidate:
                    os.fsync(candidate.fileno())
                new_hash = file_hash(temporary)
                backup = directory / f'{project_id}.v{linked["version"]}.{uuid4().hex}.xlsx'
                shutil.copy2(path, backup)
                with open(backup, 'rb') as copyfile:
                    os.fsync(copyfile.fileno())
                if file_hash(path) != expected:
                    raise ValueError('External workbook edit detected before replacement')
                atomic_json(journal, {'old_hash': expected, 'new_hash': new_hash})
                os.replace(temporary, path)
                fsync_dir(directory)
                db.execute('UPDATE workbooks SET expected_hash=?,status=?,error=NULL,version=version+1 WHERE project_id=?', (new_hash, 'synced', project_id))
                db.execute('DELETE FROM workbook_jobs WHERE project_id=?', (project_id,))
                # Keep the journal until DB commit; next job/startup removes or replays it.
                return True
            except Exception as exc:
                db.execute('UPDATE workbooks SET status=?,error=? WHERE project_id=?', ('blocked', str(exc)[:1500], project_id))
                return False
            finally:
                if temporary and Path(temporary).exists():
                    Path(temporary).unlink()


def drain_jobs(database):
    with database.connect() as db:
        jobs = [r[0] for r in db.execute('SELECT project_id FROM workbook_jobs')]
    for project in jobs:
        process_job(database, project)


def reconcile_external(database, user, project_id, reviewed_hash):
    """Adopt reviewed edits only if mapped financial cells exactly match authoritative records.

    Unknown or missing identities and financial differences are reported, never auto-merged.
    The operator must resolve each financial difference through reviewed app/API mutations first.
    """
    from .auth import authorize
    directory = database.settings.data_dir / 'workbooks'
    with open(directory / f'{project_id}.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with database.transaction() as db:
            authorize(db, user, project_id, admin=True)
            linked = db.execute('SELECT * FROM workbooks WHERE project_id=?', (project_id,)).fetchone()
            if not linked:
                raise HTTPException(404, 'No linked workbook')
            path = Path(linked['path'])
            if file_hash(path) != reviewed_hash:
                raise HTTPException(409, 'Workbook changed since inspection; inspect and review again')
            wb = compatibility(path)
            mapping = WorkbookMapping.model_validate_json(linked['mapping'])
            if mapping.sheet not in wb.sheetnames:
                raise HTTPException(422, 'Mapped sheet removed; create a reviewed plain workbook instead')
            ws = wb[mapping.sheet]
            cols = mapping_columns(ws, mapping)
            headers = {str(c.value): c.column for c in ws[mapping.header_row] if c.value is not None}
            if not all(h in headers for h in META):
                raise HTTPException(422, 'Identity columns changed; financial reconciliation required')
            records = {r['id']: expense_record(r) for r in db.execute('SELECT * FROM expenses WHERE project_id=?', (project_id,))}
            seen, differences = set(), []
            for row in range(mapping.header_row + 1, ws.max_row + 1):
                identifier = ws.cell(row, headers['_LedgerId']).value
                if not identifier and all(ws.cell(row, c).value is None for c in cols.values()):
                    continue
                if identifier not in records or identifier in seen:
                    differences.append({'row': row, 'problem': 'Unknown, missing, or duplicate identity'})
                    continue
                seen.add(identifier)
                record = records[identifier]
                for field, col in cols.items():
                    cell = ws.cell(row, col)
                    value = cell.value
                    expected = record[field]
                    if field == 'amount_minor':
                        expected = 0 if record['voided'] else record['amount_minor'] * (-1 if record['kind'] == 'refund' else 1)
                        try:
                            value = Decimal(str(value)) * 100
                            if not value.is_finite() or value != expected:
                                raise ValueError('Amount differs')
                        except Exception:
                            differences.append({'id': identifier, 'field': field, 'expected_minor': expected, 'workbook_value': str(cell.value)})
                        continue
                    if field == 'expense_date':
                        value = value.date().isoformat() if isinstance(value, datetime) else value.isoformat() if isinstance(value, date) else str(value)
                    elif value is None:
                        value = ''
                    if cell.data_type == 'f' or value != expected:
                        differences.append({'id': identifier, 'field': field, 'expected': expected, 'workbook_value': str(value)})
            if differences:
                raise HTTPException(409, {'code': 'external_financial_differences', 'differences': differences})
            # Missing known rows are recreated from database, with explicit report to the operator.
            missing = list(set(records) - seen)
            backup = directory / f'{project_id}.external-reviewed.{uuid4().hex}.xlsx'
            shutil.copy2(path, backup)
            audit(db, user['id'], project_id, 'adopt_reviewed_external_workbook',
                  after={'sha256': reviewed_hash, 'recreated_ids': missing, 'backup': backup.name})
            db.execute('UPDATE workbooks SET expected_hash=?,status=?,error=NULL WHERE project_id=?', (reviewed_hash, 'queued', project_id))
            db.execute('INSERT OR REPLACE INTO workbook_jobs VALUES(?,?)', (project_id, now()))
            journal = directory / f'{project_id}.publish.json'
            journal.unlink(missing_ok=True)
            return {'status': 'queued', 'recreated_ids': missing}
