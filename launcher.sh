#!/usr/bin/env bash
# Start the Baseball Dashboard and background data updaters.
# Ctrl-C cleanly shuts down all child processes.

set -euo pipefail
cd "$(dirname "$0")"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV="${VENV:-.venv}"
if [ ! -f "$VENV/bin/python" ]; then
    echo "First run: creating virtual environment at $VENV/ ..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r requirements.txt
    echo "Dependencies installed."
fi
PYTHON="$VENV/bin/python"

# ── Graceful shutdown ─────────────────────────────────────────────────────────
pids=()
cleanup() {
    trap - INT TERM EXIT
    echo ""
    echo "Shutting down..."
    for pid in "${pids[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# ── Launch processes ──────────────────────────────────────────────────────────
echo "Starting CSV data updater (watch mode)..."
# --watch: fetches any missing seasons on startup, then refreshes the current
# season every update_interval seconds (default 4 h, set in config.json).
# This covers both team and player CSVs — live_stats.py is not needed here
# (running both would double-fetch and race on the same files).
"$PYTHON" baseball_csv_generator.py --watch &
pids+=($!)

echo "Starting dashboard at http://localhost:${PORT:-8050} ..."
# Loopback-only and debug off by default; export HOST=0.0.0.0 to serve on the
# network, DASH_DEBUG=1 for the dev reloader/debugger.
"$PYTHON" app.py &
pids+=($!)

# Wait for any child to exit unexpectedly, then shut down everything.
# (Bare `wait -n` waits for any child; passing pids needs bash >= 5.1.)
wait -n
