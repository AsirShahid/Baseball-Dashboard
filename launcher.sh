#!/usr/bin/env bash
# Start the Baseball Dashboard (Dash) along with background data updaters.

cd "$(dirname "$0")"

python app.py &
python live_stats.py &
python baseball_csv_generator.py
