# Project Ledger

Native Android expense management with a private Linux backend, local Ollama interpretation, exact INR accounting, and managed Excel synchronization.

Start with the [short user guide](docs/USER_GUIDE.md) for daily use, credentials, storage locations, and identifiers.

**Current status: signed deployment build with remaining acceptance checks.** The signed APK is installed on the connected phone; the backend runs from an operator-initialized encrypted vault over private Tailscale HTTPS. Backend integration, native phone acceptance, local model evaluation, and encrypted backup/restore are verified. See [verification report](docs/VERIFICATION.md) for evidence and remaining device/deployment work.

## Contents

- `android/`: Kotlin, Material 3 Compose, encrypted Room, Keystore, WorkManager.
- `backend/`: FastAPI, SQLite WAL, Argon2 authentication, versioned records, audit, Ollama, conservative XLSX import/update, backups.
- `scripts/`: isolated toolchain, builds, real HTTP smoke test, model and package evaluation.
- `examples/`: synthetic construction workbook and descriptions.
- `docs/`: installation, security, synchronization, workbook compatibility, recovery, verification.

## Start the backend

From `/home/saarthak/Projects/ExpenseTracker` in this checkout:

```bash
# The existing environment is project-local; no system packages were installed.
.venv/bin/python -m pip install -r ledger/backend/requirements.lock
# Fresh deployment only; this checkout is already initialized:
# ledger/scripts/vault.sh init
# ledger/scripts/vault.sh bootstrap administrator
ledger/scripts/vault.sh unlock
ledger/scripts/vault.sh run
```

Vault initialization and administrator bootstrap ask for passwords only in your terminal. The secure launcher refuses a locked vault and binds **only `127.0.0.1:18766`**. See [encrypted vault operations](docs/VAULT.md). The API schema is included as `backend/openapi.json`; hosted Swagger/Redoc pages are disabled to avoid external CDN requests.

Expose it privately using an existing authenticated Tailscale installation, after checking its current Serve configuration:

```bash
tailscale serve status
tailscale serve --bg --https=8443 http://127.0.0.1:18766
```

Use the HTTPS tailnet URL and port returned by Serve in Android. Do not use Funnel. See [installation](docs/INSTALLATION.md) before modifying networking or deploying to a team.

## Build Android

```bash
ledger/scripts/build_android.sh :app:assembleDebug :app:assembleDebugAndroidTest :app:testDebugUnitTest :app:lintDebug
```

Output: `ledger/android/app/build/outputs/apk/debug/app-debug.apk`. Android 8.0/API 26 or later and a secure device screen lock are required. After first online login, manual entries, drafts, edits, reversals, history, filters, dashboards, reports, and deferred AI text are stored on the device. Offline sessions expire after seven days. User-configured automatic sync runs through WorkManager; it does not require a continuously running application.

For the protected release key already prepared in this checkout, unlock the vault and run `ledger/scripts/build_release.sh`. The delivered signed APK is `ledger/artifacts/ProjectLedger-signed.apk`, package `com.projectledger.production`. Release updates must use the same protected key. The private HTTPS address here is `https://pop-os.tail4722e9.ts.net:8443`.

## Test

```bash
.venv/bin/python -m pytest ledger/backend/tests -q
PYTHONPATH=ledger/backend .venv/bin/python ledger/scripts/backend_smoke.py
PYTHONPATH=ledger/backend .venv/bin/python ledger/scripts/evaluate_ai.py --output ledger/docs/ai-evaluation.json
ledger/scripts/build_android.sh :app:testDebugUnitTest :app:lintDebug
# Requires an attached Android test device or a running emulator:
ledger/scripts/build_android.sh :app:connectedDebugAndroidTest
```

The model evaluation sends only synthetic fixtures to the existing local model. Security audits submit dependency coordinates only. Financial data is never sent to a cloud inference or storage service by this application.

Financial authority is the database. Excel is a maintained representation with its own visible status. A committed transaction remains valid if the workbook fails to update. AI proposals never affect totals until a person confirms them.
