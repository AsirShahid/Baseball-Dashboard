#!/usr/bin/env python3
"""Pull live FanGraphs leaderboards via the JSON API and write them to CSV.

FanGraphs exposes a clean JSON endpoint at /api/leaders/major-league/data that
returns 500+ columns per player — more than the old leaders.aspx HTML table ever
did.  This replaces the brittle BeautifulSoup scraper that broke when FanGraphs
redesigned their front-end.
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
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("live_stats")

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
API_URL     = "https://www.fangraphs.com/api/leaders/major-league/data"
PAGE_SIZE   = 2000   # well above any realistic season leaderboard


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def fetch_api(stats: str, qual: str | int, year: int) -> pd.DataFrame | None:
    """Fetch a player leaderboard from the FanGraphs JSON API.

    stats : "bat" or "pit"
    qual  : "y" for qualified, 0 for all players
    """
    params = dict(
        pos="all", stats=stats, lg="all", qual=qual,
        type=8,           # Dashboard preset — returns 500+ columns
        season=year, month=0, season1=year,
        ind=0, team=0, rost=0, age=0,
        filter="", players=0, startdate="", enddate="",
        pageitems=PAGE_SIZE, pagenum=1,
    )
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            log.warning("API returned 0 rows for stats=%s qual=%s year=%d", stats, qual, year)
            return None
        df = pd.DataFrame(data)
        log.info("  API → %d rows, %d columns", len(df), len(df.columns))
        return df
    except Exception as exc:
        log.error("API fetch failed (stats=%s qual=%s year=%d): %s", stats, qual, year, exc)
        return None


def backfill_null_columns(df: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    """For columns that are entirely null in df, copy values from fallback by Name."""
    if "Name" not in df.columns or "Name" not in fallback.columns:
        return df
    null_cols = [c for c in df.columns if df[c].isnull().all() and c in fallback.columns]
    if not null_cols:
        return df
    log.info("  Backfilling %d null column(s) from pybaseball: %s", len(null_cols), null_cols)
    merged = fallback.set_index("Name")[null_cols]
    df = df.set_index("Name")
    df.update(merged)
    return df.reset_index()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
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
        df = fetch_api(stats, qual, year)

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
