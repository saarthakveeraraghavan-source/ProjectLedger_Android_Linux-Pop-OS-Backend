# Security and privacy

## Implemented controls

- No financial cloud storage, cloud inference provider, advertising analytics, or telemetry client is configured.
- Ollama URLs are restricted to loopback HTTP addresses; HTTP client environment proxy routing is disabled for inference. Cloud model names and remote Ollama model metadata are rejected; local GGUF format is verified before inference. A single inference slot bounds GPU concurrency. Local models return schema-constrained data only; generated SQL/code is never executed.
- Android permits HTTPS only and retains ordinary certificate/hostname verification. The backend launcher binds only loopback and is intended to be exposed through private Tailscale Serve.
- Passwords use Argon2. Sessions are random high-entropy bearer tokens, stored as SHA-256 hashes server-side and encrypted with Keystore on Android. Login throttling is stored in the database. Provisioning/recovery/revocation are audited.
- Every financial/project/workbook operation checks project membership. System administrators must also be members to read project finances. Revoked accounts lose server sessions immediately.
- SQLCipher encrypts Android Room databases with per-server/account random keys. Keystore wraps the keys. A device credential is required for UI access; secure display prevents screenshots. Android backups and transfers are excluded.
- Validated integer paise, strict schemas, parameterized SQL, immutable operation IDs, record versions, transactional audit/outbox changes, and explicit conflict review protect integrity.
- XLSX uploads have compressed/decompressed size/dimension limits and safe XML parsing. Unsupported features are rejected. User spreadsheet text is stored as literal string cells; CSV reports escape formula-leading text. Inference cannot mutate a workbook.
- Runtime folders are private and excluded from Git. No passwords/tokens/release signing keys are hard-coded in source or application resources.

## Offline authorization limit

A disconnected device cannot learn that a user was revoked. It can access securely cached permitted data until its seven-day session expires. Reconnecting checks active account and current project membership before queue transmission. Removed projects are hidden; unsent local financial intent remains encrypted for authorized recovery rather than being silently destroyed. A lost device still needs device-level revocation/wipe policy. Removing server membership cannot remotely erase an offline phone immediately.

The OS screen lock, Keystore, and SQLCipher do not defend against a rooted/unlocked device under full attacker control. Android background workers need to decrypt stored credentials while the device is unlocked; UI credential confirmation is an additional access gate, not a cryptographic per-operation biometric requirement.

## Linux encryption and backups

Linux SQLite/workbook files use an integrated, verified gocryptfs vault in the selected deployment. The secure launcher and database connection guard refuse locked/plaintext fallback, and normal unmount is blocked while the backend holds the vault. See `VAULT.md` and `encrypted-vault-verification.json`. This is filesystem encryption; the SQLite engine itself is not SQLCipher on Linux. Whole-host disk encryption has not been configured by this task. Recovery JSON/CSV exports are deliberately portable and unencrypted; select protected local destinations and restrict access. Do not upload them to third-party storage without a separate intentional decision.

## Networking boundaries

Tailscale uses third-party coordination and may relay WireGuard-encrypted traffic. It receives node/connection metadata; it does not provide total infrastructure independence. See [Tailscale security](https://tailscale.com/security). Tailnet controls should limit users/devices/ports. Application authentication remains required even within the tailnet. Self-hosted Headscale/DERP or manually managed WireGuard are alternatives requiring separate deployment testing. HTTPS certificates may expose hostnames in public certificate-transparency logs.

## Audit evidence and limits

The Python advisory audit was rerun after replacing vulnerable initial dependencies and reports no known findings. The Android runtime inventory was checked against [OSV's package API](https://google.github.io/osv.dev/api/) with no known findings. Reports are saved with package versions; these are point-in-time advisory checks, not a penetration test or a guarantee of security. Gradle dependency SHA-256 metadata detects later artifact changes but uses the initially downloaded TLS-authenticated artifacts as its trust baseline.

Audit logs live in the same SQLite database as records; they are transactional but not tamper-proof against a filesystem/system administrator. There is no external immutable audit service. The deployment should use a dedicated OS account, encrypted storage, least-privilege tailnet policy, controlled backups, and a production signing key before handling a team's only financial copy.
