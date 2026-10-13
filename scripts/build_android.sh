#!/usr/bin/env bash
set -euo pipefail
LEDGER_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export JAVA_HOME="${LEDGER_JAVA_HOME:-$LEDGER_ROOT/.tools/jdk}"
export ANDROID_HOME="${LEDGER_ANDROID_HOME:-$LEDGER_ROOT/.tools/sdk}"
export GRADLE_USER_HOME="$LEDGER_ROOT/.tools/gradle-home"
export ANDROID_USER_HOME="$LEDGER_ROOT/.tools/android-user"
export PATH="$JAVA_HOME/bin:$PATH"
cd "$LEDGER_ROOT/android"
"$LEDGER_ROOT/.tools/gradle-8.13/bin/gradle" --no-daemon --max-workers=4 "$@"
