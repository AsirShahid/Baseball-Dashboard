#!/usr/bin/env python3
"""Data layer — config, CSV loading, live-fetch, static catalogs and theme tokens."""

import base64
import functools
import io
import json
import logging
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image as _PILImage
    _PIL = True
except ImportError:
    _PIL = False

import pandas as pd

try:
    import pybaseball as pyb
    _PYBASEBALL = True
except ImportError:
    _PYBASEBALL = False

from fangraphs_api import (
    strip_html, fetch_team, atomic_to_csv, split_month, COUNTING_STATS,
)

# ── Config ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent

with open(ROOT / "config.json") as f:
    config = json.load(f)

# Resolve data directories relative to this file so the app reads the same
# folders no matter what CWD it's launched from.
for _k in ("team_batting_dir", "team_pitching_dir",
           "qualified_batting_dir", "qualified_pitching_dir",
           "all_batting_dir", "all_pitching_dir"):
    if _k in config:
        config[_k] = str(ROOT / config[_k])

# Drive the current season from today's date so the season lists and the live/
# full-season split never go stale at a year boundary. config["current_year"]
# acts only as a forward pin (e.g. to pre-load next season early).
config["current_year"] = max(int(config.get("current_year", 0)),
                             datetime.today().year)

# Identity/meta columns that must never appear as plottable stats. The
# 2026-07 FanGraphs-API refresh added the id and name-routing columns.
EXCLUDED_COLS = {"Team", "Season", "Dollars", "Name", "IDfg", "Unnamed: 0",
                 "playerid", "xMLBAMID", "teamid", "playerTeamId",
                 "SeasonMin", "SeasonMax", "Bats", "Throws", "AgeR",
                 "PlayerName", "PlayerNameRoute", "position", "positionDB",
                 "TeamName", "TeamNameAbb"}
PRIORITY_COLS = ["WAR", "wRC+", "SIERA"]

# League membership for the AL/NL filters. Includes defunct/renamed franchise
# codes that appear in the FanGraphs data (BRO = Brooklyn Dodgers, PHA =
# Philadelphia A's, CHI = the pre-1903 Cubs, …). Most 19th-century, Federal
# League and Negro League clubs predate/sit outside the AL–NL structure and
# are left unfiltered. Codes whose league changed over time (MIL, HOU, WAS,
# BAL) are resolved year-aware via _LEAGUE_ERAS below; the sets carry their
# most recent identity as the fallback when no season is in play.
NL_TEAMS = {"ARI", "ATL", "CHC", "CIN", "COL", "LAD", "MIA", "MIL",
            "NYM", "PHI", "PIT", "SDP", "SFG", "STL",
            "BRO", "BSN", "NYG", "MON", "FLA", "WSN", "CHI", "LOU"}
AL_TEAMS = {"BAL", "BOS", "CHW", "CLE", "DET", "HOU", "LAA", "KCR",
            "MIN", "NYY", "OAK", "ATH", "SEA", "TBR", "TEX", "TOR",
            "ANA", "CAL", "KCA", "NYH", "PHA", "SLB", "TBD", "WAS"}

# Franchises whose league changed while keeping the same FanGraphs code.
# Entries are (first, last, league) with inclusive bounds; None = open-ended;
# league None = neither AL nor NL that era (e.g. American Association years).
# First matching entry wins; no match falls back to the sets above.
_LEAGUE_ERAS = {
    # 1901 AL Brewers → (St. Louis from 1902); 1970–97 AL Brewers; NL since.
    "MIL": ((1901, 1901, "AL"), (1970, 1997, "AL"), (None, None, "NL")),
    "HOU": ((2013, None, "AL"), (None, None, "NL")),
    # Senators (AL 1901–71); the 1890s Washington club was NL.
    "WAS": ((1901, 1971, "AL"), (None, 1899, "NL")),
    # 1890s NL Orioles; the 1880s club was American Association (neither).
    "BAL": ((1892, 1899, "NL"), (None, 1891, None), (1901, None, "AL")),
}


def team_league(team: str, year=None):
    """'AL', 'NL' or None for a team code, year-aware where membership moved."""
    if year is not None:
        for lo, hi, lg in _LEAGUE_ERAS.get(team, ()):
            if (lo is None or year >= lo) and (hi is None or year <= hi):
                return lg
    if team in AL_TEAMS:
        return "AL"
    if team in NL_TEAMS:
        return "NL"
    return None

# FanGraphs marks a traded player's season row with this Team value. The data
# doesn't say which teams, so league filters treat these players as possibly
# either league rather than silently dropping them.
MULTI_TEAM = "- - -"


def team_display(code, full: bool = False) -> str:
    """Human label for a team code, handling the traded-player sentinel."""
    code = str(code or "").strip()
    if code == MULTI_TEAM:
        return "Multiple teams" if full else "2TM"
    if not code:
        return "—"
    return TEAM_FULL_NAME.get(code, code) if full else code

# FanGraphs codes the Nationals WSN (all seasons) and the Athletics ATH from
# 2025 (post-Oakland); OAK covers 1968–2024 and WAS is the old AL Senators.
TEAM_LOGO_MAP = {
    "LAA": "angels",   "BAL": "orioles",  "BOS": "redsox",    "CHW": "whitesox",
    "CLE": "guardians","DET": "tigers",   "KCR": "royals",    "MIN": "twins",
    "NYY": "yankees",  "OAK": "athletics","SEA": "mariners",  "TBR": "rays",
    "TEX": "rangers",  "TOR": "bluejays", "ARI": "diamondbacks","ATL": "braves",
    "CHC": "cubs",     "CIN": "reds",     "COL": "rockies",   "MIA": "marlins",
    "HOU": "astros",   "LAD": "dodgers",  "MIL": "brewers",   "WSN": "nationals",
    "NYM": "mets",     "PHI": "phillies", "PIT": "pirates",   "STL": "cardinals",
    "SDP": "padres",   "SFG": "giants",   "ATH": "athletics",
}

SEASONS        = list(range(config["current_year"], 1870, -1))
MIN_PA_LIST    = ["Qualified"] + list(range(0, 701, 10))
MIN_IP_LIST    = ["Qualified"] + list(range(0, 301, 10))

TEAM_COLORS = {
    "ARI": "#A71930", "ATL": "#CE1141", "BAL": "#DF4601", "BOS": "#BD3039",
    "CHC": "#0E3386", "CHW": "#27251F", "CIN": "#C6011F", "CLE": "#00385D",
    "COL": "#33006F", "DET": "#0C2340", "HOU": "#EB6E1F", "KCR": "#004687",
    "LAA": "#BA0021", "LAD": "#005A9C", "MIA": "#00A3E0", "MIL": "#12284B",
    "MIN": "#002B5C", "NYM": "#FF5910", "NYY": "#003087", "OAK": "#003831",
    "PHI": "#E81828", "PIT": "#FDB827", "SDP": "#2F241D", "SEA": "#0C2C56",
    "SFG": "#FD5A1E", "STL": "#C41E3A", "TBR": "#092C5C", "TEX": "#003278",
    "TOR": "#134A8E", "WAS": "#AB0003", "WSN": "#AB0003", "ATH": "#003831",
}

# Secondary brand colors — used for the detail-panel header gradient.
TEAM_COLOR_ALT = {
    "ARI": "#E3D4AD", "ATL": "#13274F", "BAL": "#000000", "BOS": "#0C2340",
    "CHC": "#CC3433", "CHW": "#C4CED4", "CIN": "#000000", "CLE": "#E50022",
    "COL": "#C4CED4", "DET": "#FA4616", "HOU": "#002D62", "KCR": "#BD9B60",
    "LAA": "#003263", "LAD": "#A5ACAF", "MIA": "#EF3340", "MIL": "#FFC52F",
    "MIN": "#D31145", "NYM": "#002D72", "NYY": "#E4002C", "OAK": "#EFB21E",
    "PHI": "#002D72", "PIT": "#FDB827", "SDP": "#FFC425", "SEA": "#005C5C",
    "SFG": "#27251F", "STL": "#0C2340", "TBR": "#8FBCE6", "TEX": "#C0111F",
    "TOR": "#1D2D5C", "WAS": "#14225A", "WSN": "#14225A", "ATH": "#EFB21E",
}

TEAM_FULL_NAME = {
    "ARI": "Arizona Diamondbacks", "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",         "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",      "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",     "DET": "Detroit Tigers",
    "HOU": "Houston Astros",       "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",   "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",        "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",      "NYM": "New York Mets",
    "NYY": "New York Yankees",     "OAK": "Oakland Athletics",
    "PHI": "Philadelphia Phillies","PIT": "Pittsburgh Pirates",
    "SDP": "San Diego Padres",     "SEA": "Seattle Mariners",
    "SFG": "San Francisco Giants", "STL": "St. Louis Cardinals",
    "TBR": "Tampa Bay Rays",       "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",    "WSN": "Washington Nationals",
    "WAS": "Washington Senators",  "ATH": "Athletics",
}

TEAM_DIVISION = {
    "ARI": "NL West",   "ATL": "NL East",  "BAL": "AL East",   "BOS": "AL East",
    "CHC": "NL Central","CHW": "AL Central","CIN": "NL Central","CLE": "AL Central",
    "COL": "NL West",   "DET": "AL Central","HOU": "AL West",  "KCR": "AL Central",
    "LAA": "AL West",   "LAD": "NL West",  "MIA": "NL East",   "MIL": "NL Central",
    "MIN": "AL Central","NYM": "NL East",  "NYY": "AL East",   "OAK": "AL West",
    "PHI": "NL East",   "PIT": "NL Central","SDP": "NL West",  "SEA": "AL West",
    "SFG": "NL West",   "STL": "NL Central","TBR": "AL East",  "TEX": "AL West",
    "TOR": "AL East",   "WSN": "NL East",   "ATH": "AL West",
}

# Team-view filter options (the team analogue of the player AL/NL/team filter).
# Leagues use the AL/NL sets (which include historical franchise codes, so the
# league filter still works for old seasons); divisions only match the modern
# 30 via TEAM_DIVISION and are naturally empty for pre-division seasons.
LEAGUE_FILTERS = ["All Teams", "AL", "NL",
                  "AL East", "AL Central", "AL West",
                  "NL East", "NL Central", "NL West"]


def team_in_league(team: str, league, year=None) -> bool:
    """Whether a team code belongs to the selected league/division filter.

    Pass the season (a range's representative year, or the path point's own
    season) so era-dependent codes resolve correctly — Milwaukee was AL in
    1980, Houston was NL in 2005. Divisions stay modern-only: they only exist
    for the current 30 clubs."""
    if league in (None, "", "All Teams"):
        return True
    if league in ("AL", "NL"):
        return team_league(team, year) == league
    return TEAM_DIVISION.get(team) == league

# ── Theme palette (drives Plotly figures so the chart matches the CSS theme) ──

PALETTE = {
    "dark": {
        "plot": "#131822", "paper": "#131822", "grid": "#232b38", "axis": "#2f3947",
        "text": "#e7ecf3", "muted": "#6f7a8e", "accent": "#f5a524",
        "hover_bg": "#1a212d", "hover_border": "#2f3947", "marker_line": "rgba(255,255,255,0.7)",
    },
    "light": {
        "plot": "#ffffff", "paper": "#ffffff", "grid": "#e2e6ee", "axis": "#d3d9e2",
        "text": "#0d1117", "muted": "#757f93", "accent": "#f5a524",
        "hover_bg": "#f4f6fa", "hover_border": "#d3d9e2", "marker_line": "rgba(13,17,23,0.35)",
    },
}

# Composite-rank colorscale — red → amber → green (matches the .legend-bar gradient).
RANK_COLORSCALE = [[0.0, "#e5484d"], [0.5, "#f5a524"], [1.0, "#46a758"]]

# ── Stat direction (for composite-rank percentiles) ──────────────────────────
# Most stats are "higher is better"; these are the exceptions. Direction can
# depend on context — a pitcher's ERA is bad, but K% is good; a hitter's K% is
# bad. So a few sets are keyed by whether the stat describes a pitcher.

_LOWER_ALWAYS = frozenset({
    "ERA", "FIP", "xFIP", "SIERA", "WHIP", "BB/9", "HR/9", "H/9", "R/9",
    "ERA-", "FIP-", "xFIP-", "tERA", "kwERA",
    "GDP", "GIDP", "CS", "E", "BK", "WP", "BS", "L",
})
# Bad for a pitcher (offense allowed); good for a hitter.
_LOWER_FOR_PITCHERS = frozenset({
    "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "wOBA", "xwOBA", "wRC", "wRC+",
    "wRAA", "BB%", "HR", "R", "ER", "H", "BB", "1B", "2B", "3B", "RBI", "TB",
    "HR/FB", "Barrel%", "HardHit%", "EV", "LD%", "HBP",
})
# Bad for a hitter (whiffs and chases); good for a pitcher.
_LOWER_FOR_BATTERS = frozenset({"K%", "SO", "K", "SwStr%", "O-Swing%"})


def stat_higher_better(stat: str, is_pitching: bool) -> bool:
    """Whether a larger value of `stat` is better, given the batting/pitching
    context. Unknown stats default to higher-is-better."""
    if stat in _LOWER_ALWAYS:
        return False
    if is_pitching and stat in _LOWER_FOR_PITCHERS:
        return False
    if (not is_pitching) and stat in _LOWER_FOR_BATTERS:
        return False
    return True

# Quick-start chart presets. Each axis is (type, real-FanGraphs-column).
TEAM_PRESETS = [
    {"id": "balance",      "name": "Offense vs Pitching",
     "x": ("Pitching", "ERA"),   "y": ("Batting", "wRC+"),  "z": None},
    {"id": "power",        "name": "Power & contact",
     "x": ("Batting", "HardHit%"), "y": ("Batting", "Barrel%"), "z": None},
    {"id": "discipline",   "name": "Plate discipline",
     "x": ("Batting", "K%"),     "y": ("Batting", "BB%"),   "z": None},
    {"id": "stuff",        "name": "Pitcher K-BB",
     "x": ("Pitching", "BB/9"),  "y": ("Pitching", "K/9"),  "z": None},
    {"id": "runprev",      "name": "Run prevention",
     "x": ("Pitching", "FIP"),   "y": ("Pitching", "ERA"),  "z": None},
    {"id": "value",        "name": "Bat vs Arm WAR",
     "x": ("Pitching", "WAR"),   "y": ("Batting", "WAR"),   "z": None},
]

# Player presets — separate lists for batters and pitchers. Axes are bare
# FanGraphs column names (no type prefix, since the player view doesn't have
# batting/pitching axis type selectors).
BATTER_PRESETS = [
    {"id": "p-power",       "name": "Power & contact",
     "x": "HardHit%", "y": "Barrel%"},
    {"id": "p-discipline",  "name": "Plate discipline",
     "x": "K%",      "y": "BB%"},
    {"id": "p-value",       "name": "wRC+ vs WAR",
     "x": "wRC+",    "y": "WAR"},
    {"id": "p-speed",       "name": "Speed & contact",
     "x": "SB",      "y": "AVG"},
    {"id": "p-iso-woba",    "name": "ISO vs wOBA",
     "x": "ISO",     "y": "wOBA"},
]

PITCHER_PRESETS = [
    {"id": "p-stuff",       "name": "Pitcher K-BB",
     "x": "BB/9",    "y": "K/9"},
    {"id": "p-prevention",  "name": "Run prevention",
     "x": "FIP",     "y": "ERA"},
    {"id": "p-value-p",     "name": "SIERA vs WAR",
     "x": "SIERA",   "y": "WAR"},
    {"id": "p-whiff",       "name": "Whiffs & control",
     "x": "BB%",     "y": "K%"},
    {"id": "p-gb",          "name": "Groundball profile",
     "x": "GB%",     "y": "HR/FB"},
]

# ── live-fetch: FanGraphs API for team stats, pybaseball for player stats ─────

# Keyed by bare directory name: config values are absolute after the resolve
# above, but _live_fetch matches on Path(path).parent.name.
_TEAM_DIRS   = {Path(config["team_batting_dir"]).name: "bat",
                Path(config["team_pitching_dir"]).name: "pit"}
_PLAYER_DIRS = {
    Path(config["qualified_batting_dir"]).name:  ("batting_stats",  {}),
    Path(config["all_batting_dir"]).name:        ("batting_stats",  {"qual": 0}),
    Path(config["qualified_pitching_dir"]).name: ("pitching_stats", {}),
    Path(config["all_pitching_dir"]).name:       ("pitching_stats", {"qual": 0}),
}


def _live_fetch(path: str) -> pd.DataFrame:
    """Fetch a season's data and cache it as CSV."""
    p = Path(path)
    parent = p.parent.name
    try:
        year = int(p.stem)
    except ValueError:
        return pd.DataFrame()

    if parent in _TEAM_DIRS:
        df = fetch_team(_TEAM_DIRS[parent], year,
                        month=split_month(year, config["current_year"]))
        if df is not None:
            atomic_to_csv(df, path)
            logging.info("FanGraphs team API: cached %s", path)
            return df
        return pd.DataFrame()

    if not _PYBASEBALL or parent not in _PLAYER_DIRS:
        return pd.DataFrame()
    func_name, kwargs = _PLAYER_DIRS[parent]
    try:
        pyb.cache.disable()
        func = getattr(pyb, func_name)
        logging.info("pybaseball: fetching %s(%d, %s)", func_name, year, kwargs)
        df = func(year, **kwargs)
        atomic_to_csv(df, path)
        logging.info("pybaseball: cached %s", path)
        return df
    except Exception as exc:
        logging.error("pybaseball fetch failed for %s: %s", path, exc)
        return pd.DataFrame()


# ── Data helpers ──────────────────────────────────────────────────────────────

def process_columns(columns):
    cols = [c for c in columns
            if c not in EXCLUDED_COLS and not str(c).startswith("Unnamed")]
    for col in reversed(PRIORITY_COLS):
        if col in cols:
            cols.remove(col)
            cols.insert(0, col)
    return cols


# CSV cache, keyed by path and invalidated by file mtime so the dashboard
# picks up files rewritten by the background updater. Failures and empty
# fetches are NOT cached, so a transient network error doesn't blank a season
# until restart. Entries are copies-on-read: callers may mutate freely.
_CSV_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_CSV_CACHE_MAX = 512


def _normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Give the player id column its canonical name.

    pybaseball frames call it IDfg; CSVs written straight from the FanGraphs
    API (the 2026-07 refresh onward) call it playerid. Everything downstream —
    span aggregation, click-to-detail, leaderboard refs — keys on IDfg, so
    normalise at the single load point."""
    if "playerid" in df.columns and "IDfg" not in df.columns:
        return df.rename(columns={"playerid": "IDfg"})
    return df


def load_csv(path: str, fetch: bool = True) -> pd.DataFrame:
    """Load CSV; auto-fetches the season live if the file doesn't exist
    (unless fetch=False)."""
    try:
        p = Path(path)
        if p.exists():
            mtime = p.stat().st_mtime
            cached = _CSV_CACHE.get(path)
            if cached and cached[0] == mtime:
                return cached[1].copy()
            df = _normalize_ids(strip_html(pd.read_csv(path)))
            if not df.empty:
                if len(_CSV_CACHE) >= _CSV_CACHE_MAX:
                    _CSV_CACHE.pop(next(iter(_CSV_CACHE)))
                _CSV_CACHE[path] = (mtime, df)
            return df.copy()
        if not fetch:
            return pd.DataFrame()
        return _normalize_ids(strip_html(_live_fetch(path)))
    except Exception as exc:
        logging.warning("load_csv failed for %s: %s", path, exc)
        return pd.DataFrame()


# ── Multi-season range aggregation ────────────────────────────────────────────

def season_bounds(value) -> tuple:
    """Normalise a season control value to an inclusive (lo, hi) int pair.

    Accepts either a single year (int/str) or a [lo, hi] range from the
    RangeSlider, so every caller can treat the control uniformly. Returns
    (None, None) when the value can't be parsed."""
    if isinstance(value, (list, tuple)):
        ys = [int(v) for v in value if v is not None]
        return (min(ys), max(ys)) if ys else (None, None)
    try:
        v = int(value)
        return v, v
    except (TypeError, ValueError):
        return None, None


def season_label(lo, hi) -> str:
    """'2024' for a single season, '2019–2026' for a range."""
    return str(lo) if lo == hi else f"{lo}–{hi}"


def season_tag(season, lo, hi) -> str:
    """Short per-season point label: ’22 when the range sits inside one
    century (unambiguous), the full year otherwise (1922 vs 2022)."""
    s = int(season)
    return f"’{s % 100:02d}" if int(lo) // 100 == int(hi) // 100 else str(s)


def decade_marks(mn: int, mx: int) -> dict:
    """Slider mark labels: endpoints in full, decades between as ’90-style.

    Used both to seed the layout's slider (so the first paint shows real
    years, not Dash's auto-abbreviated '2k' marks) and by the data-aware
    slider callback."""
    span = max(1, mx - mn)
    step = 10 if span <= 35 else (20 if span <= 90 else 30)
    marks = {mn: {"label": str(mn)}, mx: {"label": str(mx)}}
    start = ((mn // step) + 1) * step
    for y in range(start, mx, step):
        if (y - mn) > step * 0.5 and (mx - y) > step * 0.5:
            marks[y] = "’" + f"{y % 100:02d}"
    return marks


def _weight_col_for(dir_key: str) -> str:
    """Weight column for rate-stat averaging: IP for pitching, PA otherwise."""
    return "IP" if "pitching" in dir_key else "PA"


def _aggregate_span(df: pd.DataFrame, group_key: str, weight_col: str,
                    display_cols: list, rate_cols: frozenset = frozenset()
                    ) -> pd.DataFrame:
    """Roll multiple season rows per entity into one row spanning the range.

    Counting columns (COUNTING_STATS, plus the weight column) are summed; every
    other numeric column is a rate and is weighted-averaged by the weight column
    (PA for batters, IP for pitchers) so a span's wRC+/ERA stay meaningful
    instead of being naively summed. Mirrors fangraphs_api.aggregate_team, but
    keyed on any identity column (Team for teams, IDfg for players) and carrying
    display columns (Name/Team) from each entity's largest-weight season.
    Columns in `rate_cols` are always weight-averaged, even when their name is
    a counting stat — used for percentile-converted columns, where summing
    would be meaningless.

    Fully vectorised: the player CSVs run to ~300 columns and a span of a few
    seasons has hundreds of entities, so a per-group Python loop takes tens of
    seconds where this takes tens of milliseconds."""
    numeric_cols = [c for c in df.select_dtypes(include="number").columns
                    if c != group_key]
    has_weight = weight_col in df.columns
    g = df[group_key]
    count_cols = [c for c in numeric_cols
                  if c not in rate_cols and (c == weight_col or c in COUNTING_STATS)]
    avg_cols = [c for c in numeric_cols if c not in count_cols]

    parts = []
    if count_cols:
        parts.append(df[count_cols].groupby(g).sum())
    if avg_cols:
        vals = df[avg_cols]
        plain_mean = vals.groupby(g).mean()
        if has_weight:
            w = pd.to_numeric(df[weight_col], errors="coerce").fillna(0)
            # Per-column weighted mean over the rows where that column has a
            # value; groups whose weights are all 0 (or whose values are all
            # NaN) fall back to the plain mean.
            num = vals.mul(w, axis=0).groupby(g).sum(min_count=1)
            den = vals.notna().mul(w, axis=0).groupby(g).sum()
            parts.append((num / den).where(den > 0, plain_mean))
        else:
            parts.append(plain_mean)

    if display_cols and len(df):
        # Representative row per entity: its largest-weight season (or the
        # last row when there is no weight column).
        if has_weight:
            w = pd.to_numeric(df[weight_col], errors="coerce").fillna(0)
            rep_idx = w.groupby(g).idxmax()
        else:
            rep_idx = df.index.to_series().groupby(g).last()
        present = [d for d in display_cols if d in df.columns]
        if present:
            disp = df.loc[rep_idx.values, present]
            disp.index = rep_idx.index
            parts.append(disp)

    if not parts:
        return pd.DataFrame({group_key: sorted(g.unique())})
    out = pd.concat(parts, axis=1)
    order = ([c for c in numeric_cols if c in out.columns]
             + [d for d in display_cols if d in out.columns])
    out = out[order].reset_index()
    # groupby names the index after the grouping series; make sure the id
    # column carries the expected name even if the input series was unnamed.
    return out.rename(columns={out.columns[0]: group_key})


def _season_rows(frames_by_year) -> pd.DataFrame:
    """Stack (year, frame) pairs into one frame of entity-season rows, stamping
    each row's Season (overwriting the CSV's own Season column, which carries
    the same value) so per-season views can key on (entity, Season)."""
    frames = [df.assign(Season=y) for y, df in frames_by_year if not df.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_stats(dir_key: str, lo, hi=None, group_key: str = "Team",
               split: bool = False) -> pd.DataFrame:
    """Load one entity-per-row frame for a season or an inclusive season range.

    For a single season (hi is None or hi == lo) this is just the season CSV, so
    the common case stays as cheap as before. For a range it concatenates the
    seasons and rolls them up per entity via _aggregate_span — summing counting
    stats and weight-averaging rate stats — so the chart and leaderboard show one
    cumulative point per team/player across the span.

    With split=True the range is *not* rolled up: every entity-season stays its
    own row, tagged with a Season column (the "per season" range view)."""
    lo, _ = season_bounds(lo if hi is None else [lo, hi])
    if lo is None:
        return pd.DataFrame()
    hi = lo if hi is None else int(hi)
    if split:
        return _season_rows((y, load_csv(f"{config[dir_key]}/{y}.csv"))
                            for y in range(lo, max(lo, hi) + 1))
    if hi <= lo:
        return load_csv(f"{config[dir_key]}/{lo}.csv")
    frames = [df for y in range(lo, hi + 1)
              if not (df := load_csv(f"{config[dir_key]}/{y}.csv")).empty]
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    combined = pd.concat(frames, ignore_index=True)
    if group_key not in combined.columns:
        return frames[-1]
    display = ["Name", "Team"] if group_key != "Team" else []
    return _aggregate_span(combined, group_key, _weight_col_for(dir_key), display)


def pct_within_season(df: pd.DataFrame, stats) -> pd.DataFrame:
    """Replace each stat column with its percentile rank (0–100) within `df`.

    The percentile keeps the raw stat's direction (a high ERA ranks high), so
    downstream direction handling — axis reversal, composite ranks — applies
    unchanged. Returns a copy; non-numeric and missing values stay NaN."""
    df = df.copy()
    for s in stats:
        if s in df.columns:
            df[s] = pd.to_numeric(df[s], errors="coerce").rank(pct=True) * 100
    return df


def load_stats_pct(dir_key: str, lo, hi, stats, group_key: str = "Team",
                   season_prep=None, split: bool = False) -> pd.DataFrame:
    """Era-adjusted variant of load_stats: percentiles instead of raw values.

    Each stat in `stats` is converted to its percentile rank within each
    season's pool (so a 1968 OBP is measured against 1968, not pooled with
    2000), then the seasons roll up per entity as a PA/IP-weighted average of
    those percentiles. `season_prep` runs on each season's frame before
    ranking (derived columns, per-season qualification filters) so the
    percentile pool matches the filters in play. Only the identity, weight,
    display and stat columns survive — this frame is for plotting, not as a
    general stat table. With split=True the seasons are not rolled up: each
    entity-season keeps its own percentile row, tagged with Season."""
    lo, hi = season_bounds(lo if hi is None else [lo, hi])
    if lo is None:
        return pd.DataFrame()
    stats = [s for s in stats if s]
    weight_col = _weight_col_for(dir_key)
    display = ["Name", "Team"] if group_key != "Team" else []
    keep = [group_key, weight_col] + display + stats
    frames = []
    for y in range(lo, hi + 1):
        df = load_csv(f"{config[dir_key]}/{y}.csv")
        if df.empty:
            continue
        if season_prep is not None:
            df = season_prep(df)
        if df.empty or group_key not in df.columns:
            continue
        df = pct_within_season(df, stats)
        frames.append((y, df[[c for c in keep if c in df.columns]]))
    if not frames:
        return pd.DataFrame()
    if split:
        return _season_rows(frames)
    combined = pd.concat([f for _, f in frames], ignore_index=True)
    return _aggregate_span(combined, group_key, weight_col, display,
                           rate_cols=frozenset(stats))


# Per-file cache of which columns contain any data, so seasons_with_data
# doesn't re-parse ~150 CSVs on every slider/axis change.
_FILE_COLS_CACHE: dict[str, tuple[float, frozenset]] = {}


def _nonnull_cols(f: Path) -> frozenset:
    key = str(f)
    mtime = f.stat().st_mtime
    cached = _FILE_COLS_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        df = pd.read_csv(f)
        cols = frozenset(c for c in df.columns if df[c].notna().any())
    except Exception as exc:
        logging.warning("could not read columns from %s: %s", f, exc)
        cols = frozenset()
    _FILE_COLS_CACHE[key] = (mtime, cols)
    return cols


def seasons_with_data(dir_key: str, stat: str) -> frozenset:
    result = set()
    for f in Path(config[dir_key]).glob("*.csv"):
        try:
            year = int(f.stem)
        except ValueError:
            continue
        if stat in _nonnull_cols(f):
            result.add(year)
    return frozenset(result)


_LOGO_SIZE = 160  # all logos normalised to this square (px) before encoding


@functools.lru_cache(maxsize=64)
def logo_b64(team: str) -> str | None:
    """Logo as a PNG data URI, at native aspect (not padded to a square)."""
    name = TEAM_LOGO_MAP.get(team)
    if not name:
        return None
    path = ROOT / "Logos" / f"{name}-resizedmatplotlib.png"
    try:
        if _PIL:
            with _PILImage.open(path) as img:
                img = img.convert("RGBA")
                img.thumbnail((_LOGO_SIZE, _LOGO_SIZE), _PILImage.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return ("data:image/png;base64,"
                        + base64.b64encode(buf.getvalue()).decode())
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return None


@functools.lru_cache(maxsize=64)
def logo_aspect(team: str) -> float | None:
    """Native aspect ratio (width / height) of a team's logo, or None.

    Used by the chart renderer to size each logo's box so banner-shaped
    logos (Braves, Reds) and tall ones (Pirates, Angels) all occupy a
    similar visible area instead of getting letterboxed into a square.
    """
    name = TEAM_LOGO_MAP.get(team)
    if not name:
        return None
    try:
        if _PIL:
            with _PILImage.open(ROOT / "Logos" / f"{name}-resizedmatplotlib.png") as img:
                w, h = img.size
                # Require both dims; a 0 would make `aspect or 1.0` silently
                # fall back to square and hide a corrupt image.
                return w / h if (w and h) else None
    except Exception:
        return None
    return None


def safe_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def opts(values: list) -> list:
    return [{"label": str(v), "value": v} for v in values]


_RAMP_STOPS = [(0.0, (229, 72, 77)), (0.5, (245, 165, 36)), (1.0, (70, 167, 88))]


def ramp_color(t: float) -> str:
    """Map 0..1 → red → amber → green (matches the .legend-bar gradient)."""
    t = max(0.0, min(1.0, float(t)))
    for i in range(len(_RAMP_STOPS) - 1):
        a, c1 = _RAMP_STOPS[i]
        b, c2 = _RAMP_STOPS[i + 1]
        if t <= b:
            k = (t - a) / (b - a) if b > a else 0.0
            rgb = tuple(round(c1[j] + (c2[j] - c1[j]) * k) for j in range(3))
            return "#%02x%02x%02x" % rgb
    return "#46a758"
