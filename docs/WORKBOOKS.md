# Workbook compatibility and synchronization

The database is authoritative. A workbook is a linked, maintained representation; its synchronization state is independent of Android/server acknowledgment.

## Supported import

Upload a plain `.xlsx` through Android Settings → Workbook mapping or `/workbooks/inspect`. The inspector reports sheets, headers, formats, previews, tables, and formula counts. Select sheet/header/column mappings and explicitly confirm import. Amount, category, description, and ISO/Excel date are required; vendor, payment method, and direction are optional. Categories must be configured in the target project before import. Imported rows are attributed to the importing administrator and recorded in the audit trail.

The supported transaction sheet has a header row, normal rectangular transaction rows, and no merged cells. Mapped transaction fields must contain literal values. Put subtotal/summary formulas on another sheet or in unmapped columns. Embedded table totals are unsupported for automatic updates. Currency is INR; a negative imported amount is a refund, and an explicit incompatible direction is rejected. Import is all-or-nothing: a bad row or mapping does not commit a subset. Duplicate override on import is explicit/audited because legitimate historical spreadsheets can contain identical payments; inspect the source first.

Original upload and a read-only-named original backup are kept locally. The linked workbook lives under `LEDGER_DATA_DIR/workbooks/PROJECT_UUID.xlsx`; edit this managed copy if using external spreadsheet software. Editing the original source elsewhere does not magically synchronize it. Re-upload is not bidirectional merge. Linked imports cannot be repeated for the same project or reuse already managed identity columns.

## Conservative compatibility checks

OOXML parts, decompressed size, CRCs, XML safety, dimensions, and external relationships are inspected before loading. Macros, drawings/shapes/charts, images, pivots, OLE/embedded controls, external links, unsupported parts, and extension lists are rejected. The original is not rewritten when a file is rejected. Ordinary formulas, cell styles, sheets, and simple tables are supported and tested. Complex vendor extensions can be rejected even if Excel opens them; this is deliberate compatibility scope, not a promise to support all XLSX features.

[openpyxl's documentation](https://openpyxl.readthedocs.io/en/3.1/tutorial.html) warns that it cannot round-trip all Excel features. No macro or shape preservation claim is made here. Create a reviewed plain XLSX transaction copy for unsupported source files.

## Automatic updates

Financial mutation and durable workbook job are committed in one SQLite transaction. The worker regenerates mapped cells from current authoritative records, preserving IDs, versions, status, formulas outside mapped cells, existing styles, and translated row formulas. A refund is exported as a negative numeric amount. A void retains its row and metadata but sets amount to zero. `_LedgerId`, `_LedgerVersion`, and `_LedgerStatus` are reserved columns.

The candidate is written on the same filesystem, reopened, checked for record identities, verified for amount representation, and checked against original formulas. The original linked file is backed up with a version and unique suffix. A publication journal records old/new hashes before atomic replacement, and both file and directory are fsynced. Journal replay handles a crash after file replacement but before the database commits the new workbook hash. Only verified replacements clear the job. Failures leave the database transaction intact and status `blocked`; retries run every 30 seconds and on explicit request. The worker uses an advisory lock and detects common Excel/LibreOffice lock files.

Excel itself uses numeric precision limits. If a generated value cannot round-trip to the exact expected paise, publishing is blocked rather than rounding the database record. Formulas are preserved but **not evaluated or recalculated** by openpyxl. The file requests recalculation when opened in Excel/LibreOffice; cached formula results may remain stale until then. The app's totals always use the database.

## External edits

A changed SHA-256 blocks automatic publishing. Do not remove the check or blindly accept a new hash.

1. Preserve an external copy and close spreadsheet software.
2. Inspect the current managed workbook in the app or `/projects/ID/workbook/inspect-current`; note the returned hash and preview.
3. Review mapped financial differences against server records. Apply intended financial changes through the app/API with normal permissions, confirmation, and version checks. Unknown/missing/duplicate row identities cannot be adopted automatically.
4. Explicitly confirm reconciliation with the reviewed hash. `/workbook/reconcile` requires every present mapped financial cell to match authoritative data. A difference returns a detailed HTTP 409 report without overwriting the workbook.
5. Supported edits to other cells, formulas, and formatting are backed up, adopted, audited, and used for the next export. Known missing rows are reported and recreated from the database. New external expenses must first become reviewed app records; raw external rows without Ledger IDs are rejected.

This is a reviewed reconciliation workflow, not a general bidirectional merge engine. A noncooperating external writer that ignores locks can still race the short final hash-check/replacement interval. Keep the workbook closed during publishing/reconciliation; file locks are advisory on Linux. The current suite injects interrupted writes and detects external changes but does not simulate real power loss or every spreadsheet vendor's locking behavior.
