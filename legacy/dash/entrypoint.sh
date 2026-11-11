#!/usr/bin/env bash
set -e
cd /app
# Background data updater: keeps the current season fresh (and, since the
# watcher recomputes the year each cycle, rolls over to the new season on its
# own across New Year).
python baseball_csv_generator.py --watch &
# --preload shares the imported app across workers (copy-on-write). The CSV and
# span caches fill lazily per worker after the fork, though, and a warm worker
# measured ~0.5 GB (2026-11-10), so the default is 2 workers to stay inside the
# compose mem_limit (1.5 GB); raise WEB_CONCURRENCY only with more memory.
# --max-requests recycles workers to cap per-process CSV-cache growth. --timeout
# sits well above the 8s request-path fetch cap and the ~16 s cold build of a
# full-history all-players span, but low enough that a hung worker is replaced.
exec gunicorn app:server -b 0.0.0.0:8050 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --preload \
    --timeout 60 \
    --graceful-timeout 30 \
    --max-requests 2000 \
    --max-requests-jitter 200
