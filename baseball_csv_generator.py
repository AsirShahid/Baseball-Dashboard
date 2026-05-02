#!/usr/bin/env python3
"""Fetch baseball stats CSVs from FanGraphs via pybaseball.

Typical usage
-------------
# Fetch only what's missing for 2025 and 2026 (safe to re-run any time):
python baseball_csv_generator.py --start 2025 --end 2026

# Re-download everything from 1998 onward (slow, ~hours):
python baseball_csv_generator.py --start 1998 --force

# Fetch recent data then keep refreshing the current season every 4 hours:
python baseball_csv_generator.py --start 2025 --watch
"""

import argparse
import datetime
import json
import logging
from pathlib import Path
from time import sleep

import pybaseball as pyb
from pybaseball import (
    team_batting, team_pitching, team_fielding,
    batting_stats, pitching_stats,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
pyb.cache.disable()


def load_config():
    with open("config.json") as f:
        return json.load(f)


def create_directories(directories):
    for d in directories:
        Path(d).mkdir(parents=True, exist_ok=True)


def generate_csv(func, year, directory, qual=None, skip_existing=True):
    path = Path(directory) / f"{year}.csv"
    if skip_existing and path.exists():
        logging.info("  skip  %s/%d.csv (already exists)", directory, year)
        return
    try:
        df = func(year) if qual is None else func(year, qual=qual)
        df.to_csv(path)
        logging.info("  saved %s/%d.csv  (%d rows)", directory, year, len(df))
    except Exception as exc:
        logging.error("  ERROR %s/%d — %s", func.__name__, year, exc)


def fetch_years(start, end, config, skip_existing=True):
    delay = config.get("request_delay", 5)
    for year in range(end, start - 1, -1):
        logging.info("── %d ──────────────────────────", year)
        generate_csv(team_batting,   year, config["team_batting_dir"],        skip_existing=skip_existing)
        generate_csv(team_pitching,  year, config["team_pitching_dir"],       skip_existing=skip_existing)
        generate_csv(team_fielding,  year, config["team_fielding_dir"],       skip_existing=skip_existing)
        generate_csv(batting_stats,  year, config["qualified_batting_dir"],   skip_existing=skip_existing)
        generate_csv(pitching_stats, year, config["qualified_pitching_dir"],  skip_existing=skip_existing)
        generate_csv(batting_stats,  year, config["all_batting_dir"],  qual=0, skip_existing=skip_existing)
        generate_csv(pitching_stats, year, config["all_pitching_dir"], qual=0, skip_existing=skip_existing)
        sleep(delay)


if __name__ == "__main__":
    config      = load_config()
    this_year   = datetime.datetime.now().year

    parser = argparse.ArgumentParser(description="Fetch baseball stats via pybaseball")
    parser.add_argument(
        "--start", type=int, default=this_year - 1,
        help="First season to fetch (default: last year)",
    )
    parser.add_argument(
        "--end", type=int, default=this_year,
        help="Last season to fetch (default: current year)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download even when the CSV already exists",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="After the initial fetch, keep refreshing the current season "
             "every update_interval seconds (set in config.json)",
    )
    args = parser.parse_args()

    create_directories([
        config["team_batting_dir"],   config["team_pitching_dir"],
        config["team_fielding_dir"],  config["qualified_batting_dir"],
        config["qualified_pitching_dir"], config["all_batting_dir"],
        config["all_pitching_dir"],
    ])

    logging.info("Fetching seasons %d – %d  (skip_existing=%s)",
                 args.start, args.end, not args.force)
    fetch_years(args.start, args.end, config, skip_existing=not args.force)

    if args.watch:
        interval = config.get("update_interval", 14400)
        logging.info("Watch mode: refreshing current season every %ds", interval)
        while True:
            sleep(interval)
            logging.info("── refresh %d ──", this_year)
            fetch_years(this_year, this_year, config, skip_existing=False)
