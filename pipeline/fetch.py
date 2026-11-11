"""Fetch season CSVs from FanGraphs.

  python -m pipeline.fetch --csv-root DIR --stints-root DIR --start 1871 --end 2026 [--force] [--only stints]

Files: <csv-root>/{all_batting_stats,all_pitching_stats,team_batting,team_pitching}/<season>.csv
and <stints-root>/{stints_batting,stints_pitching}/<season>.csv. Existing files are
skipped unless --force. The in-progress season uses FanGraphs' live split.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
from pathlib import Path

from . import fangraphs

KINDS = {
    "all_batting_stats": ("bat", "0"),
    "all_pitching_stats": ("pit", "0"),
    "team_batting": ("bat", fangraphs.TEAM_ROWS),
    "team_pitching": ("pit", fangraphs.TEAM_ROWS),
    "stints_batting": ("bat", fangraphs.SPLIT_TEAMS),
    "stints_pitching": ("pit", fangraphs.SPLIT_TEAMS),
}
TEAM_DROP = {"Name", "PlayerName", "PlayerNameRoute", "playerid", "position", "positionDB", "Bats",
             "Throws", "Age", "AgeR", "playerTeamId"}


def in_progress(season: int, today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    return season == today.year and dt.date(season, 3, 1) <= today <= dt.date(season, 11, 15)


def fetch_one(name: str, season: int, path: Path, live: bool) -> str:
    stats, team = KINDS[name]
    if name.startswith("stints"):
        rows = fangraphs.traded_stints(stats, season, live)
        if rows is None:
            return "empty"
    else:
        rows = fangraphs.season_rows(stats, season, live, team)
        if rows is None:
            return "empty"
        if team == fangraphs.TEAM_ROWS:
            rows = [{k: v for k, v in row.items() if k not in TEAM_DROP} for row in rows]
    return "changed" if fangraphs.write_csv(rows, path) else "same"


def run(csv_root: Path, stints_root: Path, start: int, end: int, force: bool = False,
        only: set | None = None, delay: float = 2.0, log=logging.getLogger("fetch")) -> dict:
    changed = {}
    for season in range(end, start - 1, -1):
        live = in_progress(season)
        for name in KINDS:
            if only and not any(o in name for o in only):
                continue
            root = stints_root if name.startswith("stints") else csv_root
            path = root / name / f"{season}.csv"
            if path.exists() and not force:
                continue
            result = fetch_one(name, season, path, live)
            log.info("%s %s: %s", name, season, result)
            if result == "changed":
                changed.setdefault(season, []).append(name)
            time.sleep(delay)
    return changed


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--csv-root", type=Path, required=True)
    p.add_argument("--stints-root", type=Path, required=True)
    p.add_argument("--start", type=int, default=dt.date.today().year)
    p.add_argument("--end", type=int, default=dt.date.today().year)
    p.add_argument("--force", action="store_true")
    p.add_argument("--only", action="append", help="substring of the file kind, e.g. stints")
    p.add_argument("--delay", type=float, default=2.0)
    a = p.parse_args(argv)
    run(a.csv_root, a.stints_root, a.start, a.end, a.force, set(a.only or ()), a.delay)


if __name__ == "__main__":
    main()
