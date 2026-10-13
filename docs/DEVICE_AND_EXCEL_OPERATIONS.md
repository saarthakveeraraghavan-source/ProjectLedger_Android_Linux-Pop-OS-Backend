# Phone removal, backend reset, another phone, and Excel

These are operator instructions. Publishing the source does not delete apps or reset data. The existing README and daily-use guide remain unchanged.

## Remove the phone apps

First synchronize confirmed records. If changes are still pending, export device records/pending changes from Settings before uninstalling; those local records will otherwise be lost.

Use Android Settings → Apps → Project Ledger → Uninstall, or long-press its icon → App info → Uninstall. Development left two separate Ledger packages on the test phone:

- `com.projectledger.production`: the signed app and its real local cache.
- `com.projectledger`: the isolated debug app and synthetic test data.
- `com.projectledger.test`: the instrumentation helper, which has no normal launcher icon.

For an attached phone with authorized USB debugging, these commands remove only those packages (run them yourself only when ready):

```bash
cd /home/saarthak/Projects/ExpenseTracker/ledger
.tools/sdk/platform-tools/adb uninstall com.projectledger.production
.tools/sdk/platform-tools/adb uninstall com.projectledger
.tools/sdk/platform-tools/adb uninstall com.projectledger.test
```

If multiple devices are connected, add `-s DEVICE_SERIAL` immediately after `adb`. Uninstalling the phone apps does not delete the desktop database or linked workbooks. Tailscale is a separate app and does not need uninstalling.

## Restart versus reset the backend

**Restart without deleting anything:** stop the backend with Ctrl+C in its terminal, then run:

```bash
cd /home/saarthak/Projects/ExpenseTracker
ledger/scripts/vault.sh unlock
ledger/scripts/vault.sh run
```

Only one backend can listen on port 18766. If it was started by Codex and you have no backend terminal, ask Codex to stop that process, or identify the Ledger process with `pgrep -af 'uvicorn ledger.api'` and send `kill -INT PID` to that verified Ledger PID. Do not stop Ollama, Tailscale, or unrelated applications to restart Ledger.

**Start a fresh backend with no accounts/projects/expenses:** preserve the current data as an encrypted archive. This affects all phones using this backend.

1. Export pending phone changes and make a verified backup with `ledger/scripts/vault.sh backup` while the vault is unlocked.
2. Stop the backend and verify that its Ledger process has exited. Keep the vault unlocked.
3. From `/home/saarthak/Projects/ExpenseTracker`, run:

```bash
ledger/scripts/vault.sh status
umask 077
LEDGER_RESET_ARCHIVE="ledger/.vault/plain/reset-archive/data-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p ledger/.vault/plain/reset-archive
mv -T --no-clobber ledger/.vault/plain/data "$LEDGER_RESET_ARCHIVE"
ledger/scripts/vault.sh bootstrap administrator
ledger/scripts/vault.sh run
```

The old database, accounts, workbooks, and uploads remain in the archive inside the encrypted vault. Existing backups and the Android signing key remain intact. Bootstrap asks for a new app password; it does not change your vault passphrase. Do **not** run `vault.sh init` again or delete `.vault/cipher` to reset application data.

4. After preserving unsynchronized device data, clear the old phone app's storage or uninstall/reinstall it, then sign into the new backend. A new server epoch deliberately prevents blind replay of old queues. Old accounts/projects do not exist in the fresh database; create them again. For recovery instead of a fresh start, follow [RECOVERY.md](RECOVERY.md).

Do not delete the archived original until you have checked the fresh deployment and decided that you no longer need recovery. The commands above archive rather than permanently erase finances.

## Install on another phone and use this PC

1. Copy `artifacts/ProjectLedger-signed.apk` from this checkout to the other phone (USB/local file transfer is sufficient). Open it and allow installation from that trusted file source when Android prompts. Android 8/API 26+ and a secure phone screen lock are required.
2. Install/sign into Tailscale on the new phone using an approved identity in the same tailnet. The network policy must permit access to this PC on HTTPS 8443.
3. Keep the PC on, with its vault unlocked, Ledger backend running, and Ollama/Tailscale available. The model loads automatically on the first AI request.
4. Open Ledger, pass its Android screen-lock prompt, and enter `https://pop-os.tail4722e9.ts.net:8443`.
5. For your own replacement phone, use the existing `administrator` username/app password. For a teammate, provision an individual account in Settings → Team and accounts, then grant its user ID an editor/viewer/project-administrator role for each intended project. The account UUID is not a login password.
6. Sign in online and synchronize. Authorized records and projects are downloaded from the PC; unsynchronized records from an old phone are not automatically transferred.

The signed package is `com.projectledger.production`. Future updates must use the same protected signing key. You do not need a new backend, new vault, or copied desktop database for another phone.

## Add/import an Excel workbook

1. Prepare a plain `.xlsx` with a transaction worksheet and a header row. Required fields are expense date, category, amount in rupees, and description; vendor, payment method, and expense/refund kind are optional.
2. Copy it to the phone, open the intended project, and choose Settings → Workbook mapping and status → Select and inspect workbook.
3. Select the transaction worksheet and header row. Enter the matching Excel column letters. For the supplied example layout: date A, category B, amount C, description D, vendor E, payment F, kind G. Clear optional mappings if those columns are absent.
4. Review the existing rows before tapping Confirm mapping, import and link. Linking imports them into authoritative project records; it is not just an attachment. New categories from reviewed rows can be added during import.
5. Check workbook status. Confirmed server changes automatically update the linked workbook. Manual local saves, server commits, and workbook publication are separate states.

Only supported plain XLSX layouts are accepted. `.xls` and CSV are not workbook-import formats. Advanced features can be rejected rather than stripped. Put summary formulas outside mapped transaction cells; preserve the source original. See [WORKBOOKS.md](WORKBOOKS.md) for the exact scope.

## Export for Excel

**On the phone:** Settings → Export local financial report (CSV), choose a protected destination, and open/import that CSV in Excel or LibreOffice. This report contains locally available records and statuses, which can include unsynchronized changes. It is CSV, not a native `.xlsx` file.

**For the linked native XLSX:** synchronize and wait for workbook status to become synced. While the vault is unlocked, copy the current managed file from:

```text
/home/saarthak/Projects/ExpenseTracker/ledger/.vault/plain/data/workbooks/PROJECT_UUID.xlsx
```

Choose the current `PROJECT_UUID.xlsx`, rather than its original/versioned backup. Copy it to protected local storage or the new phone. The backend also has an authenticated `/projects/PROJECT_UUID/workbook/download` endpoint; the current phone UI does not yet offer a one-tap XLSX download button. If no workbook is linked, use the CSV export or link a supported workbook first.

Excel/LibreOffice can refresh preserved formulas when opened; the backend does not claim to recalculate them. Editing an exported copy does not automatically import those edits back into Ledger. External edits to the managed workbook block automatic replacement until reviewed reconciliation.
