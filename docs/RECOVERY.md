# Backup and disaster recovery

## Create and verify a backup

From the workspace root:

```bash
ledger/scripts/vault.sh backup
# Replace SNAPSHOT with the new timestamp printed by the command:
PYTHONPATH=ledger/backend .venv/bin/python -m ledger.cli verify-backup ledger/.vault/plain/backups/SNAPSHOT
```

Use a new destination for every backup. The command prevents writes/export publication while SQLite's online backup API creates a consistent database snapshot. It verifies database integrity, foreign keys, financial payload identities/versions, and hashes. Linked workbooks, original/versioned workbook copies, and outstanding publication journals are included in the manifest. Merely copying an open `.db` file is not the implemented backup mechanism. Store backups on protected encrypted media, including a separate local/offline copy for physical disk failure. No automatic retention deletion is implemented; schedule backups intentionally and verify available storage.

## Restore safely

1. Stop the backend and take a final backup of recoverable live data. Export unsynchronized phone records before changing server state.
2. Verify the selected backup.
3. Restore into a **new directory**, never over running data:

```bash
LEDGER_VAULT_MOUNT=/home/saarthak/Projects/ExpenseTracker/ledger/.vault/plain PYTHONPATH=ledger/backend .venv/bin/python -m ledger.cli --data-dir ledger/.vault/plain/data-restored restore ledger/.vault/plain/backups/SNAPSHOT
```

4. Point `LEDGER_DATA_DIR` at that directory and start the same compatible backend version.
5. The restore rewrites workbook paths, retains expected workbook hashes/external-edit protection, queues exports, rotates the server epoch, and revokes all old sessions.
6. Sign phones in again. A phone with an old epoch pauses queued writes before transmission. Preserve/export its local records and queue. Compare the export with the restored server snapshot using transaction IDs and versions. Recover missing intended records through reviewed creates; apply updates against reviewed current versions. Never blindly replay an old acknowledged history after a restore.
7. After reconciliation, use a fresh device/server cache (retain the exported original first), sign in, and pull a complete authorized snapshot. Existing conflicting old caches deliberately remain paused; automatic device rebase after disaster recovery is not yet implemented.

The current automated suite verifies an actual expense dataset backup/restore, tamper detection, session invalidation, epoch rotation, and safe refusal to overwrite a destination. It does not prove recovery after physical hardware/power failure. Do an operator-run restore drill on separate storage before production deployment.

## Schema changes and rollback

Backend schema v2 is created/migrated with `ledger.cli migrate`; unknown newer versions are rejected. Android's Room schema is exported and no destructive migration fallback is configured. Future schema upgrades must add explicit tested migrations, take a verified pre-upgrade backup, and use matching app/server versions. To roll back, stop writes and restore the pre-upgrade backup into a new encrypted directory with compatible code; rotate/reconcile devices as above. There is no claim that arbitrary future migrations can be reversed automatically.

## Failure handling

| Failure | Preserved data | Recovery |
|---|---|---|
| Desktop/Tailscale offline | Android records and immutable outbox | Reconnect; same operation UUID retries |
| AI unavailable/invalid | Original queued description | Retry local inference or enter manually |
| HTTP timeout after commit | Original local operation plus server idempotency response | Retry without changing payload/UUID |
| Concurrent edit | Server version and local intent/queue | Explicit record conflict review |
| Workbook write/lock/low storage | Authoritative expense and original workbook | Free space/close workbook; retry |
| External workbook change | Modified external workbook, server records | Reviewed reconciliation; no silent overwrite |
| Backup hash/integrity failure | Existing data untouched | Use another verified backup |
| Session revoked/expired | Encrypted device data retained | Reauthenticate/recover through administrator |
| Restored server epoch | All queued device intent retained | Export and review before fresh cache |

The tested v1 → v2 migration adds budget presence without changing existing financial values, accounts, sessions, or epoch. The deployment was backed up beforehand and every existing row was compared privately afterward. Android Room remains schema v1 because project metadata is stored as JSON.
