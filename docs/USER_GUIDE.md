# Project Ledger — short user guide

## Start the desktop

The PC, Ollama, and Tailscale must be running for synchronization and AI. After reboot, open a terminal:

```bash
cd /home/saarthak/Projects/ExpenseTracker
ledger/scripts/vault.sh unlock
ledger/scripts/vault.sh run
```

Enter your **vault passphrase** in the unlock prompt. Keep the backend terminal open. Ollama loads `qwen2.5:14b` automatically on the first AI request; you do not need an interactive `ollama run` session. The first response may take longer while the model loads.

On the phone, keep Tailscale connected and open Project Ledger. Unlock using your phone's screen credential. Sign in with server `https://pop-os.tail4722e9.ts.net:8443`, username `administrator`, and your **app password**.

## Daily use

1. **Create/select a project.** A budget is optional: leave “Set a project budget” unchecked. Add a budget later in Settings. Category suggestions are optional and remain editable.
2. **Describe an expense.** Open Pending, type a description such as “Paid Rajesh ₹15000 for electrical wiring yesterday,” and save it. With automatic sync and queued AI processing enabled, the app submits it automatically. Offline text remains safely queued.
3. **Review and confirm.** Check amount, category, description, date, vendor, payment method, and expense/refund type. AI can suggest a new category; you can edit it or type your own. Tap the calendar icon to choose the expense date. Only confirmation changes spending; saving a proposal does not. New categories become shared suggestions when the confirmed expense reaches the server.
4. **Use manual entry offline.** Tap + to enter an expense yourself. Save as draft when you are not ready to count it. Confirmed local expenses affect the local dashboard immediately and synchronize automatically when reachable.
5. **Review History.** Search/filter entries, edit them, or reverse a record with a reason. “Saved on server” confirms server persistence. A sync conflict requires choosing a reviewed version; it does not silently overwrite another user's edit.
6. **Ask questions in Overview.** Type a question before pressing “Calculate using server records.” Examples: “What was the most expensive spending till now?”, “Transportation spending this month,” or “How much budget remains?” Answers use synchronized server records, so an unsynchronized local entry is not included yet. “Till now” covers all dates. An unbudgeted project displays “No budget set.”
7. **Link Excel if wanted.** Settings → Workbook mapping and status → Select and inspect workbook. Review the sheet/column mapping before import. Supported plain XLSX workbooks update after server commits; workbook status is separate from expense status. Advanced features can be rejected to protect the original file.

Automatic synchronization defaults on. Saves request immediate work, the open app retries periodically, and Android WorkManager handles background work/reconnection. Android can delay background work. Use the Sync icon for a manual retry. Disable automatic sync or queued AI processing in Settings if desired. Cached offline sessions last seven days.

## Your passwords and the saved code

| Item | Purpose | Where you use it |
|---|---|---|
| Vault passphrase | Unlocks encrypted desktop storage | `vault.sh unlock` terminal prompt |
| App password (12–256 characters) | Logs into your individual Ledger account | Android login with your username |
| Android PIN/password/pattern | Unlocks protected phone data | Android's device credential prompt |
| Account UUID | Identifies an account; **not a password or recovery key** | Team membership/account administration |

`vault.sh bootstrap administrator` prints the newly created account's UUID after password setup. Its format is `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (hexadecimal characters). **If your saved code has that format, it is the expected account ID.** Keep it as a reference; daily login uses `administrator` and your app password. Team and accounts also shows user IDs, so losing the UUID note does not lock you out.

The supplied `vault.sh init` uses quiet gocryptfs initialization and does not intentionally print a vault master key. If your saved code was explicitly labelled **“master key”**, treat it as a sensitive vault recovery key, keep it separately in protected storage, and never share it or enter it into normal app login. Its exact identity cannot be determined from “alphanumeric code” alone; do not paste the code into chat.

You already initialized and bootstrapped this deployment. **Do not repeat `init` or `bootstrap` to start it.** Use `unlock` and `run`. For account-password recovery, use `vault.sh recover-account administrator` in the terminal while the vault is unlocked; it asks privately for a new password and invalidates old sessions.

## What the app is built with

| Layer | Technology and responsibility |
|---|---|
| Android UI | Kotlin, Jetpack Compose, Material 3, calendar picker |
| Phone storage | Room with SQLCipher encryption; keys/session protected by Android Keystore |
| Networking/sync | OkHttp HTTPS, persistent outbox, UUID idempotency, WorkManager |
| Desktop API | Python, FastAPI, Pydantic validation, individual accounts and project roles |
| Financial authority | SQLite transactions/WAL, exact integer paise, revisions, conflicts, audit |
| Local AI | Ollama + Qwen 2.5 14B; proposals/query plans only, no direct SQL or mutations |
| Excel | openpyxl, compatibility checks, original/versioned backups, verified atomic replacement |
| Security | Tailscale private HTTPS, Argon2 password hashing, gocryptfs desktop vault |

## Storage and identifiers

All paths below are under `/home/saarthak/Projects/ExpenseTracker/ledger`:

| Location / identifier | Meaning |
|---|---|
| `.vault/cipher/` | Encrypted backing files; the physical encrypted copy |
| `.vault/plain/data/ledger.db` | Authoritative database, accessible while the vault is unlocked |
| `.vault/plain/data/workbooks/` | Linked XLSX files, originals, versions, publication journals |
| `.vault/plain/data/uploads/` | Uploaded workbooks inside encrypted storage |
| `.vault/plain/backups/` | Verified, timestamped database/workbook snapshots |
| `.vault/plain/signing/` | Private Android update-signing key; excluded from source/APK delivery |
| `android/`, `backend/`, `scripts/`, `docs/` | Source, tooling, and documentation; not financial runtime data |
| `com.projectledger.production` | Signed Android app package; updates retain its existing data |
| `com.projectledger` | Separate debug/test app package |
| `127.0.0.1:18766` → private HTTPS `:8443` | Local backend port and the existing Tailscale forwarding route |
| User/project/expense/operation/proposal UUIDs | Unique identities; operation IDs prevent duplicate retries |
| Record version / sync revision / server epoch | Detect edits, deliver changes, and stop unsafe replay after restore |

The phone keeps an encrypted cache/outbox in its private app storage, isolated by account and server. Session tokens are secrets; the phone protects them and the server stores token hashes. The system uses no cloud AI or cloud financial storage. Tailscale uses coordination infrastructure and may relay encrypted traffic.

## Back up and stop

```bash
ledger/scripts/vault.sh backup
# Stop the backend with Ctrl+C in its terminal, then:
ledger/scripts/vault.sh lock
```

A snapshot inside the same vault protects against logical mistakes but not loss of that disk. Keep a separate protected copy of the complete locked `cipher` directory, including `gocryptfs.conf`; it also preserves the signing key. Do not copy actively changing ciphertext as a consistent backup. See [RECOVERY.md](RECOVERY.md) for verified restore and device reconciliation. Keep exported phone JSON/CSV on protected storage because those portable exports are unencrypted.
