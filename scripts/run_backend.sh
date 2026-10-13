#!/usr/bin/env bash
set -euo pipefail
LEDGER_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER_PYTHON="${LEDGER_PYTHON:-$LEDGER_ROOT/../.venv/bin/python}"
export PYTHONPATH="$LEDGER_ROOT/backend"
export LEDGER_VAULT_MOUNT="${LEDGER_VAULT_MOUNT:-$LEDGER_ROOT/.vault/plain}"
export LEDGER_DATA_DIR="${LEDGER_DATA_DIR:-$LEDGER_VAULT_MOUNT/data}"
umask 077
cd "$LEDGER_ROOT"
exec "$LEDGER_PYTHON" -m uvicorn ledger.api:create_app --factory --host 127.0.0.1 --port "${LEDGER_PORT:-18765}" --workers 1 --no-access-log --limit-concurrency 32
