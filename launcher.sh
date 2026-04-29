#!/usr/bin/env bash
# Start the Baseball Dashboard (Dash) plus background data updaters.
# Ctrl-C cleanly shuts down all child processes.

set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
pids=()

cleanup() {
    trap - INT TERM EXIT
    for pid in "${pids[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

"$PYTHON" live_stats.py &
pids+=($!)

"$PYTHON" baseball_csv_generator.py &
pids+=($!)

"$PYTHON" app.py &
pids+=($!)

wait -n "${pids[@]}"
