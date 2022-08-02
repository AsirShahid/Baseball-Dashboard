#!/usr/bin/env bash

cd /home/asir/Projects/Python/Baseball-Dashboard/ &&
streamlit run ~/Projects/Python/Baseball-Dashboard/streamlit-dashboard.py &&
python3 ./live_stats.py
