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
    batting_stats, pitching_stats,
)

from fangraphs_api import fetch_leaderboard, fetch_team, atomic_to_csv

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
pyb.cache.disable()


def load_config():
    with open("config.json") as f:
        return json.load(f)


def create_directories(directories):
    for d in directories:
        Path(d).mkdir(parents=True, exist_ok=True)


def generate_csv(stats: str, qual: str | int, pyb_fn, year: int, directory: str,
                 skip_existing: bool = True) -> None:
    path = Path(directory) / f"{year}.csv"
    if skip_existing and path.exists():
        logging.info("  skip  %s/%d.csv (already exists)", directory, year)
        return
    df = fetch_leaderboard(stats, qual, year)
    if df is not None:
        logging.info("  API → %d rows, %d columns", len(df), len(df.columns))
    else:
        logging.warning("  API failed — falling back to pybaseball")
        try:
            df = pyb_fn(year)
            logging.info("  pybaseball → %d rows", len(df))
        except Exception as exc:
            logging.error("  ERROR fetch/%d — %s", year, exc)
            return
    atomic_to_csv(df, path)
    logging.info("  saved %s/%d.csv  (%d rows)", directory, year, len(df))


def generate_team_csv(stats: str, year: int, directory: str, skip_existing: bool = True) -> None:
    path = Path(directory) / f"{year}.csv"
    if skip_existing and path.exists():
        logging.info("  skip  %s/%d.csv (already exists)", directory, year)
        return
    df = fetch_team(stats, year)
    if df is not None:
        atomic_to_csv(df, path)
        logging.info("  saved %s/%d.csv  (%d rows)", directory, year, len(df))
    else:
        logging.warning("  skipped %s/%d.csv — FanGraphs API returned no data", directory, year)


def fetch_years(start, end, config, skip_existing=True):
    delay = config.get("request_delay", 5)
    for year in range(end, start - 1, -1):
        logging.info("── %d ──────────────────────────", year)
        generate_team_csv("bat", year, config["team_batting_dir"],  skip_existing=skip_existing)
        generate_team_csv("pit", year, config["team_pitching_dir"], skip_existing=skip_existing)
        generate_csv("bat", "y", batting_stats,  year, config["qualified_batting_dir"],  skip_existing=skip_existing)
        generate_csv("pit", "y", pitching_stats, year, config["qualified_pitching_dir"], skip_existing=skip_existing)
        generate_csv("bat",  0,  lambda y: batting_stats(y, qual=0),  year, config["all_batting_dir"],  skip_existing=skip_existing)
        generate_csv("pit",  0,  lambda y: pitching_stats(y, qual=0), year, config["all_pitching_dir"], skip_existing=skip_existing)
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
        config["qualified_batting_dir"],
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
