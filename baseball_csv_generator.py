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


# Counting stats that should be SUMMED across players when aggregating to a
# team. Anything else is treated as a rate stat and weighted-averaged by PA
# (batters) or IP (pitchers).
_COUNTING_STATS = frozenset({
    "G", "GS", "WAR", "WPA", "RE24", "REW", "Clutch", "Pulls", "Events",
    "Pitches", "Balls", "Strikes", "Barrels", "Events_pit",
    # Batting counters
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "BB", "IBB",
    "SO", "HBP", "SF", "SH", "GDP", "SB", "CS", "TB",
    # Pitching counters
    "IP", "W", "L", "SV", "BS", "HLD", "ER", "TBF",
})


def _aggregate_team(df: pd.DataFrame, stats: str) -> pd.DataFrame:
    """Roll up player rows to one row per team.

    Counting columns are summed; rate columns are weighted-averaged by PA
    (batters) or IP (pitchers). This preserves correct team-level rate stats
    instead of just summing wOBA/AVG/etc. across players.
    """
    weight_col = "PA" if stats == "bat" else "IP"
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if weight_col not in df.columns:
        return df.groupby("Team")[numeric_cols].sum().reset_index()

    rows = []
    for team, grp in df.groupby("Team"):
        weights = pd.to_numeric(grp[weight_col], errors="coerce").fillna(0)
        total_w = float(weights.sum())
        row = {"Team": team}
        for c in numeric_cols:
            vals = pd.to_numeric(grp[c], errors="coerce")
            if c == weight_col or c in _COUNTING_STATS:
                row[c] = vals.sum(skipna=True)
            elif total_w > 0:
                mask = vals.notna()
                w = weights[mask]
                v = vals[mask]
                wsum = float(w.sum())
                row[c] = (v * w).sum() / wsum if wsum > 0 else vals.mean()
            else:
                row[c] = vals.mean()
        rows.append(row)
    return pd.DataFrame(rows)


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
        if "Team" not in df.columns:
            return None
        return _aggregate_team(df, stats)
    except Exception as exc:
        logging.warning("  Team API fetch failed (stats=%s year=%d): %s", stats, year, exc)
        return None


def load_config():
    with open("config.json") as f:
        return json.load(f)


def create_directories(directories):
    for d in directories:
        Path(d).mkdir(parents=True, exist_ok=True)


def _fetch_players_api(stats: str, qual: str | int, year: int) -> pd.DataFrame | None:
    """Fetch individual player stats from the FanGraphs JSON API."""
    params = dict(
        pos="all", stats=stats, lg="all", qual=qual,
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
        logging.info("  API → %d rows, %d columns", len(df), len(df.columns))
        return df
    except Exception as exc:
        logging.warning("  Players API fetch failed (stats=%s year=%d): %s", stats, year, exc)
        return None


def generate_csv(stats: str, qual: str | int, pyb_fn, year: int, directory: str,
                 skip_existing: bool = True) -> None:
    path = Path(directory) / f"{year}.csv"
    if skip_existing and path.exists():
        logging.info("  skip  %s/%d.csv (already exists)", directory, year)
        return
    df = _fetch_players_api(stats, qual, year)
    if df is None:
        logging.warning("  API failed — falling back to pybaseball")
        try:
            df = pyb_fn(year)
            logging.info("  pybaseball → %d rows", len(df))
        except Exception as exc:
            logging.error("  ERROR fetch/%d — %s", year, exc)
            return
    df.to_csv(path)
    logging.info("  saved %s/%d.csv  (%d rows)", directory, year, len(df))


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
