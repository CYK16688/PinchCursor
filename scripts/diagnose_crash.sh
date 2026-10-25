#!/usr/bin/env bash
# Launch the app with malloc stack logging, so the next crash can name the
# free() that corrupted the heap instead of only where the damage was noticed.
#
#   ./scripts/diagnose_crash.sh          # uses dist/PinchCursor.app
#
# Reproduce the crash, then read the newest report:
#   ls -t ~/Library/Logs/DiagnosticReports | head -1
#   malloc_history <pid from the report> <address from "Abort Cause">
#
# `open --env` keeps LaunchServices as the parent, so the app keeps the TCC
# identity it has when the user launches it from Finder.
set -euo pipefail

cd "$(dirname "$0")/.."
APP_PATH="${1:-dist/PinchCursor.app}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "no app at $APP_PATH — build it first" >&2
  exit 1
fi

open --env MallocStackLogging=1 --env MallocStackLoggingNoCompact=1 -n "$APP_PATH"
echo "launched with MallocStackLogging=1: $APP_PATH"
