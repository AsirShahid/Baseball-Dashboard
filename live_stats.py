#!/usr/bin/env python3
"""Pull live FanGraphs leaderboards via the JSON API and write them to CSV.

FanGraphs exposes a clean JSON endpoint at /api/leaders/major-league/data that
returns 500+ columns per player — more than the old leaders.aspx HTML table ever
did.  This replaces the brittle BeautifulSoup scraper that broke when FanGraphs
redesigned their front-end.

Note: `baseball_csv_generator.py --watch` (what launcher.sh runs) refreshes the
same player CSVs plus the team CSVs, so don't run both at once — this script
remains for callers who only want the player leaderboards updated.
"""

import datetime
import json
import logging
import signal
import sys
from pathlib import Path
from time import sleep

import pandas as pd
import pybaseball as pyb

from fangraphs_api import fetch_leaderboard, atomic_to_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("live_stats")

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def backfill_null_columns(df: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    """For columns that are entirely null in df, copy values from fallback by Name.

    Names shared by more than one player (in either frame) are skipped — they
    can't be matched unambiguously."""
    if "Name" not in df.columns or "Name" not in fallback.columns:
        return df
    null_cols = [c for c in df.columns if df[c].isnull().all() and c in fallback.columns]
    if not null_cols:
        return df
    log.info("  Backfilling %d null column(s) from pybaseball: %s", len(null_cols), null_cols)
    unique = fallback[~fallback["Name"].duplicated(keep=False)]
    ambiguous = df["Name"].duplicated(keep=False)
    for c in null_cols:
        df[c] = df["Name"].where(~ambiguous).map(unique.set_index("Name")[c])
    return df


def write_csv(df: pd.DataFrame, path: Path) -> None:
    atomic_to_csv(df, path)
    log.info("  Saved %d rows → %s", len(df), path)


def update_once(year: int, config: dict) -> None:
    targets = [
        ("qualified batting",  "bat", "y", config["qualified_batting_dir"],  pyb.batting_stats),
        ("qualified pitching", "pit", "y", config["qualified_pitching_dir"], pyb.pitching_stats),
        ("all batting",        "bat",  0,  config["all_batting_dir"],        lambda y: pyb.batting_stats(y, qual=0)),
        ("all pitching",       "pit",  0,  config["all_pitching_dir"],       lambda y: pyb.pitching_stats(y, qual=0)),
    ]

    for label, stats, qual, out_dir, pyb_fn in targets:
        log.info("Fetching %s for %d …", label, year)
        df = fetch_leaderboard(stats, qual, year)

        if df is None:
            log.warning("  API failed — falling back to pybaseball")
            try:
                df = pyb_fn(year)
                log.info("  pybaseball → %d rows", len(df))
            except Exception as exc:
                log.error("  pybaseball also failed: %s", exc)
                continue
        else:
            # Opportunistic backfill for any columns the API left null
            try:
                fallback = pyb_fn(year)
                df = backfill_null_columns(df, fallback)
            except Exception as exc:
                log.warning("  pybaseball backfill skipped: %s", exc)

        write_csv(df, Path(out_dir) / f"{year}.csv")


def install_signal_handlers() -> None:
    def shutdown(signum, _frame):
        log.info("Received signal %d, exiting.", signum)
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)


def main() -> None:
    install_signal_handlers()
    config   = load_config()
    interval = int(config.get("update_interval", 3600))

    while True:
        year = datetime.datetime.now().year
        log.info("── update cycle for %d ──────────────────────────", year)
        try:
            update_once(year, config)
        except Exception:
            log.exception("Update cycle failed; will retry after interval")
        log.info("Sleeping %ds …", interval)
        sleep(interval)


if __name__ == "__main__":
    main()
