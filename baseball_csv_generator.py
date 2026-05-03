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

import pandas as pd
import pybaseball as pyb
import requests
from pybaseball import (
    batting_stats, pitching_stats,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
pyb.cache.disable()

_FG_API = "https://www.fangraphs.com/api/leaders/major-league/data"


def _fetch_team_api(stats: str, year: int) -> pd.DataFrame | None:
    """Fetch team-level stats from the FanGraphs JSON API."""
    params = dict(
        pos="all", stats=stats, lg="all", qual=0,
        type=8, season=year, month=0, season1=year,
        ind=0, team=0, rost=0, age=0,
        filter="", players=0, startdate="", enddate="",
        pageitems=2000, pagenum=1,
    )
    try:
        resp = requests.get(_FG_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None
        df = pd.DataFrame(data)
        # Aggregate to team level: sum counting stats, mean for rate stats
        if "Team" not in df.columns:
            return None
        return df.groupby("Team").sum(numeric_only=True).reset_index()
    except Exception as exc:
        logging.warning("  Team API fetch failed (stats=%s year=%d): %s", stats, year, exc)
        return None


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


def generate_team_csv(stats: str, year: int, directory: str, skip_existing: bool = True) -> None:
    path = Path(directory) / f"{year}.csv"
    if skip_existing and path.exists():
        logging.info("  skip  %s/%d.csv (already exists)", directory, year)
        return
    df = _fetch_team_api(stats, year)
    if df is not None:
        df.to_csv(path)
        logging.info("  saved %s/%d.csv  (%d rows)", directory, year, len(df))
    else:
        logging.warning("  skipped %s/%d.csv — FanGraphs API returned no data", directory, year)


def fetch_years(start, end, config, skip_existing=True):
    delay = config.get("request_delay", 5)
    for year in range(end, start - 1, -1):
        logging.info("── %d ──────────────────────────", year)
        generate_team_csv("bat", year, config["team_batting_dir"],  skip_existing=skip_existing)
        generate_team_csv("pit", year, config["team_pitching_dir"], skip_existing=skip_existing)
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
