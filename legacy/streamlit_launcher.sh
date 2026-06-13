#!/usr/bin/env bash

cd /home/asir/Projects/Python/Baseball-Dashboard/ &
streamlit run ~/Projects/Python/Baseball-Dashboard/streamlit-dashboard.py &
./live_stats.py &
./baseball_csv_generator.py
