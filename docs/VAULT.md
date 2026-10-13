# Isolated encrypted vault

The selected deployment uses a signed, project-local gocryptfs 2.6.1 binary and the host's existing FUSE support. No disk partitions, system packages, fstab entries, or unrelated services are changed. The binary signature was verified against the maintainer's published fingerprint; see `vault-tool-verification.json` and the [official signed-release instructions](https://nuetzlich.net/gocryptfs/releases/).

## Initialize and unlock

Run these commands yourself in a terminal, keeping both secrets out of chat/logs:

```bash
/home/saarthak/Projects/ExpenseTracker/ledger/scripts/vault.sh init
/home/saarthak/Projects/ExpenseTracker/ledger/scripts/vault.sh bootstrap administrator
```

The first command asks for a vault passphrase, confirms it, and then unlocks the mount. The second asks for the application's initial administrator password (12+ characters). They are independent secrets. Choose strong passwords and retain them in a protected place. The scripts do not store the vault passphrase or print the master key. Existing vault configurations and accounts are never overwritten by initialization/bootstrap.

The encrypted backing files live in `ledger/.vault/cipher`. The decrypted view is `ledger/.vault/plain`, visible only while unlocked. Both are private and excluded from Git/source packages. Data is in `plain/data`, snapshots in `plain/backups`, and release signing material in `plain/signing`.

## Run and lock

```bash
ledger/scripts/vault.sh status
ledger/scripts/vault.sh run
# Stop the backend with Ctrl+C before locking.
ledger/scripts/vault.sh backup
ledger/scripts/vault.sh lock
# After reboot or a deliberate lock:
ledger/scripts/vault.sh unlock
ledger/scripts/vault.sh run
```

The secure launcher refuses to start on a locked or unexpected mount, before creating a database. Every database connection verifies the mount again. A live database instance holds a directory descriptor inside the encrypted filesystem, so an ordinary unmount is refused while the backend is using it. The lock helper never uses forced/lazy unmount. Never force-unmount an active vault yourself.

The helper runs on loopback port 18766 by default, matching the private HTTPS 8443 route you created for verification. The unrelated application on port 8765 and its 443 forwarding rule are preserved. The phone's server address for this route is `https://pop-os.tail4722e9.ts.net:8443`.

## Backups and recovery

Database/workbook snapshots created by `vault.sh backup` are inside the encrypted view and verified normally. For a separate protected copy, stop the backend, lock the vault, then copy the complete `cipher` directory, including `gocryptfs.conf`, to separate local/offline media. Do not copy actively changing encrypted backing files and call that a consistent backup. The isolated vault protects file names/content while locked; it does not protect against an attacker controlling your unlocked account or server process. File sizes/timestamps and memory can remain observable.

Losing the vault passphrase and recovery material can make the encrypted data unrecoverable. Keep an independent protected copy of the vault configuration and encryption credentials. Do not keep a plaintext passphrase next to the encrypted backing directory.

## Verified actual filesystem behavior

`test_encrypted_vault.py` used a generated disposable passphrase and a temporary real FUSE mount. It committed an exact 1,500,025-paise expense, published a workbook, created/restored a verified backup, refused a busy unmount, locked successfully after connections were closed, found no plaintext description marker in the ciphertext, refused locked startup, and recovered the original expense after remount. The production passphrase was not generated or observed by this test.

The test found an important resource-lifetime issue: native SQLite backup/restore connections were not closed by the SQLite transaction context alone. They now use explicit closing contexts, enabling safe normal unmount after completion. This is included in the final regression and vault verification.

## Reproduce tooling

```bash
python3 ledger/scripts/install_vault_tool.py
PYTHONPATH=ledger/backend .venv/bin/python ledger/scripts/test_encrypted_vault.py
```

The installer uses a project-only public-key home/keyring and pinned fingerprint. It verifies the signature before extracting/executing the tool. Run filesystem tests in a host context with FUSE access; the sandbox hides `/dev/fuse`.
