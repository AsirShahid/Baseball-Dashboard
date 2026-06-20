#!/usr/bin/env bash
set -e
cd /app
python baseball_csv_generator.py --watch &
exec gunicorn app:server -b 0.0.0.0:8050 -w 2 --timeout 120
