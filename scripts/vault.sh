#!/usr/bin/env bash
set -euo pipefail
LEDGER_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER_CIPHER="$LEDGER_ROOT/.vault/cipher"
LEDGER_PLAIN="$LEDGER_ROOT/.vault/plain"
LEDGER_GCRYPT="$LEDGER_ROOT/.tools/gocryptfs/gocryptfs"
LEDGER_PYTHON="$LEDGER_ROOT/../.venv/bin/python"
export PYTHONPATH="$LEDGER_ROOT/backend"
export LEDGER_VAULT_MOUNT="$LEDGER_PLAIN"
export LEDGER_DATA_DIR="$LEDGER_PLAIN/data"
umask 077
mkdir -p "$LEDGER_CIPHER" "$LEDGER_PLAIN"
chmod 700 "$LEDGER_ROOT/.vault" "$LEDGER_CIPHER" "$LEDGER_PLAIN"
case "${1:-status}" in
  init)
    if [[ -e "$LEDGER_CIPHER/gocryptfs.conf" ]]; then
      echo 'Vault already initialized. Use unlock; it will not be overwritten.' >&2
      exit 1
    fi
    echo 'Choose a strong vault passphrase in this terminal. Store it separately; it is not saved by this script.'
    "$LEDGER_GCRYPT" -q -init "$LEDGER_CIPHER"
    "$0" unlock
    ;;
  unlock)
    if mountpoint -q "$LEDGER_PLAIN"; then echo 'Vault already unlocked.'; exit 0; fi
    "$LEDGER_GCRYPT" -q -nosyslog -noexec "$LEDGER_CIPHER" "$LEDGER_PLAIN"
    "$LEDGER_PYTHON" -c 'from ledger.config import Settings; s=Settings(); s.verify_storage(); print("Encrypted vault unlocked and verified.")'
    ;;
  lock)
    # Ordinary unmount refuses a busy filesystem. No lazy or forced unmount is used.
    if ! mountpoint -q "$LEDGER_PLAIN"; then echo 'Vault is already locked.'; exit 0; fi
    fusermount3 -u "$LEDGER_PLAIN"
    echo 'Vault locked.'
    ;;
  status)
    "$LEDGER_PYTHON" -c 'from ledger.config import verify_vault; import os; from pathlib import Path; verify_vault(Path(os.environ["LEDGER_VAULT_MOUNT"])); print("Vault unlocked (fuse.gocryptfs).")'
    ;;
  bootstrap)
    "$LEDGER_PYTHON" -m ledger.cli --data-dir "$LEDGER_DATA_DIR" bootstrap "${2:-administrator}"
    ;;
  recover-account)
    "$LEDGER_PYTHON" -m ledger.cli --data-dir "$LEDGER_DATA_DIR" recover-account "${2:-administrator}"
    ;;
  backup)
    "$LEDGER_PYTHON" -m ledger.cli --data-dir "$LEDGER_DATA_DIR" backup "$LEDGER_PLAIN/backups/$(date -u +%Y%m%dT%H%M%SZ)"
    ;;
  run)
    export LEDGER_PORT="${LEDGER_PORT:-18766}"
    exec "$LEDGER_ROOT/scripts/run_backend.sh"
    ;;
  *) echo 'Usage: vault.sh init|unlock|lock|status|bootstrap [username]|recover-account [username]|backup|run' >&2; exit 2 ;;
esac
