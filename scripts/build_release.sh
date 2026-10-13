#!/usr/bin/env bash
set -euo pipefail
LEDGER_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$LEDGER_ROOT/backend"
"$LEDGER_ROOT/../.venv/bin/python" -c 'from pathlib import Path; from ledger.config import verify_vault; import sys; verify_vault(Path(sys.argv[1]))' "$LEDGER_ROOT/.vault/plain"
export LEDGER_SIGNING_PROPERTIES="$LEDGER_ROOT/.vault/plain/signing/signing.properties"
if [[ ! -f "$LEDGER_SIGNING_PROPERTIES" ]]; then
  echo 'Prepare the protected release key first: PYTHONPATH=ledger/backend .venv/bin/python ledger/scripts/prepare_release_key.py' >&2
  exit 1
fi
"$LEDGER_ROOT/scripts/build_android.sh" :app:assembleRelease :app:lintRelease
