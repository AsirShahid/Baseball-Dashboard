#!/usr/bin/env python3
"""Pull live FanGraphs leaderboards on a loop and write them to CSV.

Backfills any all-null columns from pybaseball, since FanGraphs occasionally
omits stats from the HTML that the API still returns.
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
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("live_stats")

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
LEADERBOARD_TABLE_ID = "LeaderBoard1_dg1_ctl00"

# Build the giant `type=c,...` query string once.
_STAT_IDS_BAT = "c,-1," + ",".join(str(i) for i in range(3, 319))
_STAT_IDS_PIT = "c,-1," + ",".join(str(i) for i in range(3, 333))


def fangraphs_url(stats: str, qual: str, type_ids: str, year: int) -> str:
    return (
        "https://www.fangraphs.com/leaders.aspx"
        f"?pos=all&stats={stats}&lg=all&qual={qual}&type={type_ids}"
        f"&season={year}&month=33&season1={year}&ind=0&team=0&rost=0"
        "&age=0&filter=&players=0&startdate=&enddate=&page=1_5000"
    )


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def fetch_leaderboard(url: str, timeout: int = 30) -> pd.DataFrame | None:
    """Fetch a FanGraphs leaderboard page and return its main table as a DataFrame."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("Request failed: %s", e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": LEADERBOARD_TABLE_ID})
    if table is None:
        log.error("Leaderboard table not found at %s", url)
        return None

    try:
        df = pd.read_html(str(table))[0]
    except ValueError as e:
        log.error("Failed to parse leaderboard table: %s", e)
        return None

    # Flatten MultiIndex columns ("Header", "Stat") -> "Stat"
    df.columns = [c[1] if isinstance(c, tuple) else c for c in df.columns]

    # Drop pagination footer row and the leading row-number column
    if len(df) > 0:
        df = df.iloc[:-1]
    df = df.drop(df.columns[0], axis=1)

    # Strip "%" from percentage columns and coerce to float
    for col in df.columns:
        series = df[col]
        if series.dtype == object and series.astype(str).str.contains("%").any():
            df[col] = series.astype(str).str.replace("%", "", regex=False).astype(float)

    return df.reset_index(drop=True)


def backfill_null_columns(df: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    """For columns that are entirely null in df, copy values from fallback by Name."""
    if "Name" not in df.columns or "Name" not in fallback.columns:
        return df
    null_cols = [c for c in df.columns if df[c].isnull().all() and c in fallback.columns]
    if not null_cols:
        return df
    log.info("Backfilling %d column(s) from pybaseball: %s", len(null_cols), null_cols)
    fallback_indexed = fallback.set_index("Name")[null_cols]
    df = df.set_index("Name")
    df.update(fallback_indexed)
    return df.reset_index()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("Wrote %d rows -> %s", len(df), path)


def update_once(year: int, config: dict) -> None:
    targets = [
        ("qualified batting",  "bat", "y", _STAT_IDS_BAT, config["qualified_batting_dir"], pyb.batting_stats),
        ("qualified pitching", "pit", "y", _STAT_IDS_PIT, config["qualified_pitching_dir"], pyb.pitching_stats),
        ("all batting",        "bat", "0", _STAT_IDS_BAT, config["all_batting_dir"],       lambda y: pyb.batting_stats(y, qual=0)),
        ("all pitching",       "pit", "0", _STAT_IDS_PIT, config["all_pitching_dir"],      lambda y: pyb.pitching_stats(y, qual=0)),
    ]

    for label, stats, qual, type_ids, out_dir, pyb_fn in targets:
        log.info("Fetching %s leaderboard for %d", label, year)
        df = fetch_leaderboard(fangraphs_url(stats, qual, type_ids, year))

        if df is None:
            log.warning("HTML scrape failed for %s %d — falling back to pybaseball", label, year)
            try:
                df = pyb_fn(year)
                log.info("pybaseball succeeded for %s %d (%d rows)", label, year, len(df))
            except Exception as e:
                log.error("pybaseball also failed for %s %d: %s", label, year, e)
                continue
        else:
            try:
                fallback = pyb_fn(year)
                df = backfill_null_columns(df, fallback)
            except Exception as e:
                log.warning("pybaseball backfill failed for %s: %s", label, e)

        write_csv(df, Path(out_dir) / f"{year}.csv")


def install_signal_handlers() -> None:
    def shutdown(signum, _frame):
        log.info("Received signal %d, exiting.", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)


def main() -> None:
    install_signal_handlers()
    config = load_config()
    interval = int(config.get("update_interval", 3600))

    while True:
        year = datetime.datetime.now().year
        try:
            update_once(year, config)
        except Exception:
            log.exception("Update cycle failed; will retry after interval")
        log.info("Sleeping %ds", interval)
        sleep(interval)


if __name__ == "__main__":
    main()
