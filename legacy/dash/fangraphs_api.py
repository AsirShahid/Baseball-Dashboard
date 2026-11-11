#!/usr/bin/env python3
"""Shared FanGraphs JSON-API client.

Single source of truth for fetching leaderboards, cleaning the HTML markup the
API embeds in Name/Team, aggregating player rows up to team level, and writing
CSVs atomically. Used by data.py (live fetch on cache miss) and
baseball_csv_generator.py.
"""

import html
import logging
import os
import re
import tempfile
from pathlib import Path

import numpy as np
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

# Counting stats that should be SUMMED across players (team roll-up) or across
# seasons (multi-year span). Anything NOT listed here is treated as a rate stat
# and weighted-averaged by PA (batters) or IP (pitchers). Getting this list
# wrong silently corrupts totals: a genuine counter left off the list is
# PA/IP-averaged down to a small fraction of its true sum. When adding a column,
# confirm it is additive (an event count or a cumulative run value), not a rate
# or an index like wRC+/wOBA/ERA.
COUNTING_STATS = frozenset({
    "G", "GS", "WAR", "WPA", "RE24", "REW", "Clutch", "Events",
    "Pitches", "Balls", "Strikes", "Barrels", "Events_pit",
    # Batting counters
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "BB", "IBB",
    "SO", "HBP", "SF", "SH", "GDP", "SB", "CS", "TB",
    # Pitching counters
    "IP", "W", "L", "SV", "BS", "HLD", "ER", "TBF",
    # Batted-ball and contact-quality counts (batting and pitching share these
    # column names). The FanGraphs column is "Pull", not "Pulls".
    "GB", "FB", "LD", "IFFB", "IFH", "BU", "BUH",
    "Pull", "Cent", "Oppo", "Soft", "Med", "Hard", "bipCount", "HardHit",
    "Swords", "CompetitiveSwings", "PH",
    # Cumulative run-value components (in runs). These are season totals, so a
    # span sums them; wRC+/wOBA/FIP are indices/rates and stay OUT of this set.
    "wRAA", "wRC", "RAR", "WAROld", "UBR", "GDPRuns", "wBsR", "BaseRunning",
    "Batting", "Fielding", "Replacement", "Positional", "Pos",
    "Offense", "Defense", "CFraming", "-WPA", "+WPA",
    # Pitching-only counts
    "QS", "CG", "ShO", "WP", "BK", "SD", "MD", "RS", "Games",
})

# Rate stats that a roll-up must REBUILD from summed components rather than
# weight-average. Weight-averaging a ratio by PA/IP drifts away from the ratio
# of the summed parts (a high-walk, low-AB hitter distorts a PA-weighted AVG,
# so the team AVG no longer equals sum(H)/sum(AB)). Rates that need league
# constants (wOBA, wRC+, FIP, xFIP, SIERA) can't be rebuilt from box-score sums
# and are left weight-averaged.
def recompute_rate_stats(df: pd.DataFrame, is_pitching: bool) -> pd.DataFrame:
    """Rewrite classic rate stats from already-summed counting columns.

    Call AFTER counting stats are summed (aggregate_team, or _aggregate_span
    over a season range). Each rate is rewritten only when it is already a
    column and all of its input columns are present, so partial frames and
    unfamiliar schemas pass through untouched. Percentile frames must not be
    passed here (their columns are ranks, not counts)."""
    cols = set(df.columns)

    def c(name):
        return pd.to_numeric(df[name], errors="coerce")

    def nz(series):
        return series.mask(series == 0)

    if is_pitching:
        if "IP" in cols:
            ip = nz(c("IP"))
            if "ERA" in cols and "ER" in cols:
                df["ERA"] = c("ER") * 9 / ip
            if "WHIP" in cols and {"BB", "H"} <= cols:
                df["WHIP"] = (c("BB") + c("H")) / ip
            for out, comp in (("K/9", "SO"), ("BB/9", "BB"), ("HR/9", "HR"), ("H/9", "H")):
                if out in cols and comp in cols:
                    df[out] = c(comp) * 9 / ip
        if "TBF" in cols:
            tbf = nz(c("TBF"))
            if "K%" in cols and "SO" in cols:
                df["K%"] = c("SO") / tbf
            if "BB%" in cols and "BB" in cols:
                df["BB%"] = c("BB") / tbf
    else:
        if "AB" in cols:
            ab = nz(c("AB"))
            if "AVG" in cols and "H" in cols:
                df["AVG"] = c("H") / ab
            if "SLG" in cols and {"1B", "2B", "3B", "HR"} <= cols:
                df["SLG"] = (c("1B") + 2 * c("2B") + 3 * c("3B") + 4 * c("HR")) / ab
            if "ISO" in cols and {"2B", "3B", "HR"} <= cols:
                df["ISO"] = (c("2B") + 2 * c("3B") + 3 * c("HR")) / ab
            if "BABIP" in cols and {"H", "HR", "SO", "SF"} <= cols:
                df["BABIP"] = (c("H") - c("HR")) / nz(c("AB") - c("SO") - c("HR") + c("SF"))
        if "OBP" in cols and {"H", "BB", "HBP", "AB", "SF"} <= cols:
            df["OBP"] = (c("H") + c("BB") + c("HBP")) / nz(c("AB") + c("BB") + c("HBP") + c("SF"))
        if "OPS" in cols and {"OBP", "SLG"} <= cols:
            df["OPS"] = c("OBP") + c("SLG")
        if "PA" in cols:
            pa = nz(c("PA"))
            if "K%" in cols and "SO" in cols:
                df["K%"] = c("SO") / pa
            if "BB%" in cols and "BB" in cols:
                df["BB%"] = c("BB") / pa
    return df


# ── Innings-pitched notation ──────────────────────────────────────────────────
# FanGraphs writes IP in baseball notation: 177.2 means 177⅔ innings (the digit
# after the point counts outs). Summing those as decimals drifts (.2 + .2 = .4,
# not 1.1), and 9·ER/IP is then off by up to ~0.3%, so roll-ups convert to true
# innings, sum, rebuild the rates, and convert the total back to notation.

def ip_is_notation(ip) -> bool:
    """True when every value's tenths digit is 0, 1 or 2 (notation, not decimal)."""
    v = pd.to_numeric(pd.Series(ip), errors="coerce").dropna()
    if v.empty:
        return False
    tenths = ((v - np.floor(v)) * 10).round(6)
    return bool(tenths.isin([0, 1, 2]).all())


def ip_to_innings(ip) -> pd.Series:
    """Baseball-notation IP → true innings (177.2 → 177.667)."""
    v = pd.to_numeric(pd.Series(ip), errors="coerce")
    whole = np.floor(v)
    return whole + ((v - whole) * 10).round() / 3


def innings_to_ip(inn) -> pd.Series:
    """True innings → baseball-notation IP (177.667 → 177.2)."""
    v = pd.to_numeric(pd.Series(inn), errors="coerce")
    outs = (v * 3).round()
    return np.floor(outs / 3) + (outs % 3) / 10


def true_innings_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of `df` with a notation IP column converted to true innings, so it
    can be summed and used as a weight. Non-notation IP passes through."""
    if "IP" in df.columns and ip_is_notation(df["IP"]):
        df = df.copy()
        df["IP"] = ip_to_innings(df["IP"]).values
    return df


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
    notation = "IP" in df.columns and ip_is_notation(df["IP"])
    if notation:
        df = true_innings_frame(df)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if weight_col not in df.columns:
        summed = df.groupby("Team")[numeric_cols].sum().reset_index()
        out = recompute_rate_stats(summed, stats == "pit")
        if notation:
            out["IP"] = innings_to_ip(out["IP"]).values
        return out

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
    # Rebuild ratios (AVG, ERA, ...) from the summed parts so they stay
    # consistent with sum(H)/sum(AB) instead of a PA/IP-weighted average.
    out = recompute_rate_stats(pd.DataFrame(rows), stats == "pit")
    if notation and "IP" in out.columns:
        out["IP"] = innings_to_ip(out["IP"]).values
    return out


# ── Fetchers ──────────────────────────────────────────────────────────────────

# FanGraphs "split" codes (the `month` query param). 0 is the standard
# full-season leaderboard and works for every season. 33 is the
# "Live Stats - Full Season" split, which folds in the current day's
# in-progress games — but only returns data for the season in progress
# (it's empty for completed/historical seasons).
FULL_SEASON_SPLIT = 0
LIVE_SPLIT = 33


def split_month(year: int, current_year: int) -> int:
    """Choose the FanGraphs split for `year`: the live, today-inclusive split
    for the in-progress season, the standard full-season split otherwise.

    The live split is empty for past seasons, so fetch_leaderboard falls back
    to the full-season split when it returns nothing."""
    return LIVE_SPLIT if year >= current_year else FULL_SEASON_SPLIT


def _request_leaderboard(stats, qual, year, month, timeout,
                         startdate="", enddate="", stat_type=8,
                         team="0") -> pd.DataFrame | None:
    params = dict(
        pos="all", stats=stats, lg="all", qual=qual,
        type=stat_type,   # 8 = Dashboard preset (500+ columns)
        season=year, month=month, season1=year,
        ind=0, team=team, rost=0, age=0,
        filter="", players=0, startdate=startdate, enddate=enddate,
        pageitems=PAGE_SIZE, pagenum=1,
    )
    try:
        resp = requests.get(FG_API, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None
        if len(data) >= PAGE_SIZE:
            logging.warning("FanGraphs response hit PAGE_SIZE=%d (stats=%s year=%s); "
                            "data may be truncated", PAGE_SIZE, stats, year)
        return strip_html(pd.DataFrame(data))
    except Exception as exc:
        logging.warning("FanGraphs API fetch failed (stats=%s qual=%s year=%s month=%s): %s",
                        stats, qual, year, month, exc)
        return None


def fetch_leaderboard(stats: str, qual: str | int, year: int,
                      month: int = FULL_SEASON_SPLIT,
                      timeout: int = 30, startdate: str = "", enddate: str = "",
                      stat_type: int = 8, team: str = "0") -> pd.DataFrame | None:
    """Fetch a leaderboard from the FanGraphs JSON API.

    stats     : "bat" or "pit"
    qual      : "y" for qualified, 0 for all players
    month     : FanGraphs split code (see FULL_SEASON_SPLIT / LIVE_SPLIT). Pass
                1000 with startdate/enddate for a custom date range.
    startdate/enddate : "YYYY-MM-DD" bounds for the month=1000 custom-range split.
    stat_type : FanGraphs column preset (8 = Dashboard).
    team      : "0" for the player leaderboard, TEAM_SPLIT ("0,ts") for one
                row per team.

    The live split is empty outside the in-progress season, so a live request
    that returns nothing falls back to the full-season split. That fallback is
    scoped to the live split only — a custom date range (month=1000) must not
    silently collapse into a whole-season pull.
    """
    df = _request_leaderboard(stats, qual, year, month, timeout,
                              startdate, enddate, stat_type, team)
    if df is None and month == LIVE_SPLIT:
        logging.info("Live split empty for %s (stats=%s); falling back to full-season",
                     year, stats)
        df = _request_leaderboard(stats, qual, year, FULL_SEASON_SPLIT, timeout,
                                  startdate, enddate, stat_type, team)
    if df is None:
        logging.warning("FanGraphs API returned no data (stats=%s qual=%s year=%s)",
                        stats, qual, year)
    return df


# FanGraphs "team" query param value that returns one row per team, with
# FanGraphs' own team aggregation — traded players' production is attributed
# to each club they played for, which a roll-up of the player leaderboard
# cannot do (their rows carry only the '- - -' sentinel).
TEAM_SPLIT = "0,ts"

# Player-identity fields that leak into team-mode rows (FanGraphs fills Name
# with an arbitrary player link); meaningless at team level, so drop them.
_TEAM_DROP_COLS = ["Name", "PlayerName", "PlayerNameRoute", "playerid",
                   "position", "positionDB", "Bats", "Throws", "Age", "AgeR",
                   "playerTeamId"]


def fetch_team(stats: str, year: int, month: int = FULL_SEASON_SPLIT,
               timeout: int = 30) -> pd.DataFrame | None:
    """Fetch team-level stats via FanGraphs' native team leaderboard.

    Falls back to rolling up the player leaderboard with aggregate_team when
    the team split returns nothing — that path drops traded players (their
    rows don't say which teams they played for), so it undercounts, but stale
    team data beats no team data."""
    df = fetch_leaderboard(stats, qual=0, year=year, month=month,
                           timeout=timeout, team=TEAM_SPLIT)
    if df is not None and "Team" in df.columns:
        return df.drop(columns=[c for c in _TEAM_DROP_COLS if c in df.columns])
    logging.warning("FanGraphs team split empty for %s (stats=%s); "
                    "falling back to player-row aggregation", year, stats)
    df = fetch_leaderboard(stats, qual=0, year=year, month=month, timeout=timeout)
    if df is None or "Team" not in df.columns:
        return None
    return aggregate_team(df, stats)


# ── Atomic CSV write ──────────────────────────────────────────────────────────

def atomic_to_csv(df: pd.DataFrame, path) -> bool:
    """Write a CSV via temp-file + rename so concurrent readers (the dashboard,
    the other updater) never see a half-written file.

    Skips the write when the file already holds exactly this content, so the
    4-hourly refresh of a finished season keeps its mtime — the dashboard's
    roll-up caches are keyed on mtimes and would otherwise all rebuild.
    Returns True when the file changed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = df.to_csv(index=False)
    try:
        if path.exists() and path.read_text() == text:
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
