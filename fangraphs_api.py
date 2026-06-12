#!/usr/bin/env python3
"""Shared FanGraphs JSON-API client.

Single source of truth for fetching leaderboards, cleaning the HTML markup the
API embeds in Name/Team, aggregating player rows up to team level, and writing
CSVs atomically. Used by data.py (live fetch on cache miss),
baseball_csv_generator.py and live_stats.py.
"""

import html
import logging
import os
import re
import tempfile
from pathlib import Path

import pandas as pd
import requests

FG_API = "https://www.fangraphs.com/api/leaders/major-league/data"
PAGE_SIZE = 2000   # well above any realistic season leaderboard


# ── HTML cleanup ──────────────────────────────────────────────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]*>")


def _clean_text(v):
    if not isinstance(v, str):
        return v
    return html.unescape(_HTML_TAG_RE.sub("", v)).strip()


def strip_html(df: pd.DataFrame) -> pd.DataFrame:
    """FanGraphs' JSON API returns Name/Team as HTML <a> tags. Reduce them to
    plain text so labels render cleanly. Applied to every API response and to
    legacy/hand-edited CSVs on read."""
    for col in ("Name", "Team"):
        if col in df.columns:
            df[col] = df[col].map(_clean_text)
    return df


# ── Team aggregation ──────────────────────────────────────────────────────────

# Counting stats that should be SUMMED across players when aggregating to a
# team. Anything else is treated as a rate stat and weighted-averaged by PA
# (batters) or IP (pitchers).
COUNTING_STATS = frozenset({
    "G", "GS", "WAR", "WPA", "RE24", "REW", "Clutch", "Pulls", "Events",
    "Pitches", "Balls", "Strikes", "Barrels", "Events_pit",
    # Batting counters
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "BB", "IBB",
    "SO", "HBP", "SF", "SH", "GDP", "SB", "CS", "TB",
    # Pitching counters
    "IP", "W", "L", "SV", "BS", "HLD", "ER", "TBF",
})


def aggregate_team(df: pd.DataFrame, stats: str) -> pd.DataFrame:
    """Roll up player rows to one row per team.

    Counting columns are summed; rate columns are weighted-averaged by PA
    (batters) or IP (pitchers). This preserves correct team-level rate stats
    instead of just summing wOBA/AVG/etc. across players.
    """
    # FanGraphs uses "- - -" as the Team value for players who were traded
    # mid-season; aggregating those rows produces a phantom 31st team. Drop
    # them before grouping.
    df = df[~df["Team"].isin(["- - -", "", None])]

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
            if c == weight_col or c in COUNTING_STATS:
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


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_leaderboard(stats: str, qual: str | int, year: int,
                      timeout: int = 30) -> pd.DataFrame | None:
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
        resp = requests.get(FG_API, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            logging.warning("FanGraphs API returned 0 rows (stats=%s qual=%s year=%s)",
                            stats, qual, year)
            return None
        return strip_html(pd.DataFrame(data))
    except Exception as exc:
        logging.warning("FanGraphs API fetch failed (stats=%s qual=%s year=%s): %s",
                        stats, qual, year, exc)
        return None


def fetch_team(stats: str, year: int, timeout: int = 30) -> pd.DataFrame | None:
    """Fetch team-level stats: player leaderboard rolled up via aggregate_team."""
    df = fetch_leaderboard(stats, qual=0, year=year, timeout=timeout)
    if df is None or "Team" not in df.columns:
        return None
    return aggregate_team(df, stats)


# ── Atomic CSV write ──────────────────────────────────────────────────────────

def atomic_to_csv(df: pd.DataFrame, path) -> None:
    """Write a CSV via temp-file + rename so concurrent readers (the dashboard,
    the other updater) never see a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            df.to_csv(f, index=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
