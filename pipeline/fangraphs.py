"""Lean FanGraphs leaderboard client (requests + csv, no pandas).

Writes the same season CSVs the Dash site used (one row per player or team,
the "Dashboard" preset of ~470-540 columns, HTML stripped from Name/Team), so
the files already on disk and the ones fetched from now on look alike.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import tempfile
import time
from pathlib import Path

import requests

API = "https://www.fangraphs.com/api/leaders/major-league/data"
PAGE_SIZE = 4000
FULL_SEASON = 0      # standard full-season split (the only one for past seasons)
LIVE_SEASON = 33     # "Live Stats - Full Season": includes today's games, current season only
TEAM_ROWS = "0,ts"   # one row per team
SPLIT_TEAMS = "0,to" # one row per player per team (traded players split by club)
MULTI_TEAM = "- - -"
_TAG = re.compile(r"<[^>]*>")
log = logging.getLogger("fangraphs")
_session = requests.Session()
_session.headers["User-Agent"] = "baseball.asir.dev data refresh (personal site)"


def _clean(value):
    if isinstance(value, str) and "<" in value:
        return _TAG.sub("", value).strip()
    return value


def leaderboard(stats: str, season: int, month: int = FULL_SEASON, team: str = "0",
                timeout: int = 60, retries: int = 3) -> list[dict] | None:
    """Rows of one FanGraphs leaderboard, or None when it is empty or fails."""
    params = dict(pos="all", stats=stats, lg="all", qual=0, type=8, season=season, month=month,
                  season1=season, ind=0, team=team, rost=0, age=0, filter="", players=0,
                  startdate="", enddate="", pageitems=PAGE_SIZE, pagenum=1)
    for attempt in range(retries):
        try:
            resp = _session.get(API, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json().get("data") or []
            if len(data) >= PAGE_SIZE:
                log.warning("%s %s hit the page size; rows may be missing", stats, season)
            return [{k: _clean(v) for k, v in row.items()} for row in data] or None
        except Exception as exc:  # network, HTTP, JSON
            log.warning("FanGraphs %s %s team=%s month=%s failed (%s), try %d",
                        stats, season, team, month, exc, attempt + 1)
            time.sleep(5 * (attempt + 1))
    return None


def season_rows(stats: str, season: int, live: bool, team: str = "0") -> list[dict] | None:
    rows = leaderboard(stats, season, LIVE_SEASON if live else FULL_SEASON, team)
    if rows is None and live:   # the live split is empty once a season is over
        rows = leaderboard(stats, season, FULL_SEASON, team)
    return rows


def write_csv(rows: list[dict], path: Path, columns: list[str] | None = None) -> bool:
    """Atomically write rows; skip the write (keep the mtime) when nothing changed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})
    text = buf.getvalue()
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", newline="") as handle:
        handle.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return True


def traded_stints(stats: str, season: int, live: bool) -> list[dict] | None:
    """Per-club rows for players who played for more than one team that season.

    FanGraphs' normal leaderboard gives a traded player one combined row with
    Team "- - -"; the split-teams view has a row per club. Only the players
    with more than one club are kept (everyone else's single row is already in
    the season file)."""
    rows = season_rows(stats, season, live, SPLIT_TEAMS)
    if rows is None:
        return None
    count: dict = {}
    for row in rows:
        count[row.get("playerid")] = count.get(row.get("playerid"), 0) + 1
    return [row for row in rows if count.get(row.get("playerid"), 0) > 1]
