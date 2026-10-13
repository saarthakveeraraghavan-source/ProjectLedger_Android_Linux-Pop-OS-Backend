# Verification report

Updated: 13 October 2026 (Asia/Kolkata), signed app 0.2.0. This report distinguishes tested code from unverified device/deployment acceptance.

## Executed checks

| Check | Result | Evidence |
|---|---|---|
| Backend financial/auth/sync/AI/workbook/recovery suite | 54 passed; 0 failed | `backend-test-results.xml` |
| Real temporary backend over loopback HTTP | Login/project creation/expense commit/idempotent retry/pull/exact total passed | `http-smoke.json` |
| Android debug APK compilation | Successful | `android/app/build/outputs/apk/debug/app-debug.apk` |
| Signed release build/lint/manifest/signature | Passed; non-debuggable, test activity absent, RSA-3072 / APK v2 | `release-verification.json` |
| Android test APK compilation | Successful | `android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk` |
| Kotlin financial/answer/error unit tests | 10 passed; 0 failed | `android/app/build/test-results/testDebugUnitTest/` |
| Android lint | Passed; dependency-version/style warnings remain | `android/app/build/reports/lint-results-debug.html` |
| Python package advisory audit | No known vulnerabilities after fixes | `dependency-audit.json` |
| Android Maven runtime advisory audit | 122 package coordinates checked; 0 known findings | `android-security-audit.json` |
| Actual local Qwen 2.5 14B amount extraction | 7/7 synthetic cases passed amount checks | `ai-evaluation.json` |
| Revised AI prompt extraction | 7/7 synthetic cases passed | `ai-evaluation-v0.2.json` |
| New category, no budget, largest all-history question with actual local AI | Passed against disposable API dataset; proposals excluded before confirmation | `usability-ai-verification.json` |
| Native calendar/automatic sync/offline checks | 4/4 passed on LAVA LXX504 API 35 | `android-phone-usability.txt` |
| Deployment schema v1 → v2 migration | All existing rows preserved; integrity and foreign keys passed | `deployment-migration-verification.json` |
| Android offline instrumentation | 2/2 passed on LAVA LXX504 API 35; 2/2 passed on AOSP API 35 emulator | `android-phone-tests.txt`, `android-emulator-tests.txt` |
| Private phone-to-Tailscale-to-backend native acceptance | Passed on LAVA phone over private HTTPS/HTTP/1.1 | `android-phone-acceptance.txt`, `phone-acceptance-verification.json` |
| Actual encrypted FUSE vault | Database/workbook/backup/restore/remount/fail-closed/busy-unmount passed | `encrypted-vault-verification.json` |
| Encrypted storage destination guards | 4 passed; locked/outside data, backup, restore refused before writes | `vault-guard-test-results.xml` |

The first lint pass caught a newer API call (`InputStream.readNBytes`) incompatible with the declared minimum API; it was replaced with a bounded stream read and subsequent lint passed. The initial Python dependency audit found advisory issues in older pip/pytest/multipart/Starlette versions; packages were upgraded, pinned, retested, and audited again. Current FastAPI/Starlette emit a test-client deprecation warning for httpx; tests still pass. The first actual model run identified the refund amount but returned the wrong direction; explicit refund guards were added and the second evaluation records refund direction correctly. Evaluation success is based on amounts; it is not a model-quality certification for every other field.

## Backend suite coverage

Exact rupee/paise and lakh/crore conversion; rejection of rounding/nonfinite/negative/invalid values; expense/refund/category/month/budget calculations; audited voids; exact idempotent response replay; conflicting operation-ID reuse; possible duplicate review; independent multi-user entries/ownership; concurrent edits with one explicit conflict; viewer/outsider isolation; revoked accounts; invalid amount/date/category schemas; login throttling; old-history delivery to new members; project-operation retries/conflicting budgets; authorized cross-project calculations; AI proposals excluded before confirmation; proposal replay and single-confirmation enforcement; invented/nonfinancial amounts removed; malformed AI output rejected; refund direction guarded; deterministic AI-question calculations; verified backup/restore with epoch rotation/session invalidation/tamper detection; XLSX import/add/edit/void; formula/style preservation; literal spreadsheet text; external modifications; interrupted replacement; common office lock files; corrupt/unsupported workbooks; invalid mapping rollback; reviewed external nonfinancial adoption and financial-difference rejection.

## Acceptance status

| Scenario | Verified portion | Remaining |
|---|---|---|
| A: normal AI entry | Local provider, proposals, human-gated API commit | Native confirmation action and private network passed; human UI usability review remains |
| B: offline expenses | Native durable implementation and unit calculations | Persistence across Room close/reopen and viewer permissions passed; process-termination/reboot/UI drill remains |
| C: deferred AI | Durable queue code and server proposal idempotency | Native queued interpretation and explicit confirmation passed; physical outage/restart drill remains |
| D: automatic Excel | Backend import/add/edit/void/preservation/failure tests | Phone-originated update passed with exact final net and formula preservation |
| E: multiple users | Server independent entries/ownership/access tested | Two accounts/native repositories on phone passed; two-physical-device drill remains |
| F: concurrent edits | Server conflict detection and client resolution implementation | Native concurrent offline edits and explicit conflict resolution passed; human conflict UI drill remains |
| G: financial analysis | Exact database calculations and authorized filter plans | Native deterministic question passed; human chart/filter usability review remains |
| H: failure recovery | Idempotency/write failure/lock/retry tests | Physical device restart, low storage, power-loss drills |
| I: access control | Backend project/account isolation and revocation tested | Native viewer denial/revocation with queued intent retention passed |
| J: data recovery | Actual database backup/restore/integrity tested | Actual phone-generated dataset restored with integrity passed; operator/device disaster drill remains |

The signed deployment build and functioning tested backend do not yet establish that all production-v1 acceptance criteria are satisfied. See `KNOWN_LIMITATIONS.md` for the remaining release gates.

The first on-device test run exposed JUnit method signatures inferred as non-void. The test signatures were corrected, rebuilt, and both tests passed on the physical phone and emulator. Existing HTTPS 443 forwarding points at port 8765, occupied by an unrelated process, and was preserved. The operator created a separate private 8443 route to port 18766.

A real private phone call found a project `archived` wire-type mismatch (SQLite 0/1 versus Kotlin Boolean). The server response was corrected and a regression test added. Financial calls use bounded short deadlines, with longer deadlines for local inference. A regression test verifies that a category filter does not change the true remaining project budget.

Device locking correctly prevented Keystore access during one run. A debug-only verification activity holds a window keep-screen-on flag during instrumentation, with no global phone-settings change, and closes afterward. Repeated HTTP/2 response-header stalls were resolved by using HTTPS HTTP/1.1; TLS and hostname validation remain enabled.

The final private native flow passed in 20.963 seconds using HTTPS HTTP/1.1, with no network retry reported in that run. It exercised offline manual edits, deferred local AI, explicit proposal confirmation, automatic workbook publishing, separate team accounts, concurrent edits/conflict resolution, refunds/voids, viewer permissions, revocation with retained queue, and deterministic questions. The exported workbook net was verified as INR 17,400.01 with the summary formula preserved. A backup of that synthetic dataset restored successfully with four records and SQLite integrity intact. Its temporary backend was stopped before the separate operator-owned deployment was started.

A temporary real gocryptfs vault passed database/workbook/backup/restore/remount checks, refused plaintext fallback, and refused normal unmount while active. The test exposed and corrected unclosed native SQLite backup connections; explicit closing contexts now release them safely. The operator initialized the deployment vault and administrator account privately. The signed release key is inside that vault. The release APK was signature-verified, installed beside the debug app on LAVA LXX504, and launched. The backend runs on loopback 18766; private HTTPS health returned `status=ok`, and a new authenticated session was observed without reading credentials or tokens. An initial administrator database backup was created and verified inside the vault. No startup service was installed.

The latest complete backend suite passed all 54 tests. The native phone tests selected a calendar date through touch input, checked immediate sync notification and durable WorkManager scheduling, retained queued AI text, preserved encrypted offline expenses, and enforced viewer permissions. Synthetic tests use the separate debug package.

The revised live inference test initially returned invalid JSON. The provider now inlines local schema definitions and explicitly requests filled JSON data in the prompt as well as passing the schema in `format`, while retaining strict validation. Updated model checks passed. [Ollama's guidance](https://docs.ollama.com/capabilities/structured-outputs) recommends also including the schema in the prompt. Calendar automation initially targeted an off-screen day; the final test selected a visible day and verified its date.

The reported 422 error did not include its original request payload. Empty/oversized questions are now disabled, and validation errors identify the field without echoing supplied input. The supplied largest-expense question returned HTTP 200 with an all-history result in the actual local-model API test. This does not claim every possible malformed question succeeds.
