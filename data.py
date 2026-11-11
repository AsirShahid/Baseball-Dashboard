#!/usr/bin/env python3
"""Data layer — config, CSV loading, live-fetch, static catalogs and theme tokens."""

import base64
import contextlib
import fcntl
import functools
import hashlib
import os
import io
import json
import logging
import tempfile
import threading
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
    recompute_rate_stats, true_innings_frame, innings_to_ip, ip_is_notation,
    ip_to_innings,
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

# The current season is derived from today's date so the season lists and the
# live/full-season split never go stale at a year boundary, even for a process
# that keeps running across New Year. config["current_year"] is only a forward
# pin (bump it to pre-load next season early); the live value comes from
# current_year() below, recomputed per call rather than frozen at import.
_CURRENT_YEAR_PIN = int(config.get("current_year", 0))


def current_year() -> int:
    """Latest season the app should offer: the config pin or this calendar
    year, whichever is greater. Recomputed each call so a long-lived process
    picks up the New-Year rollover without a restart."""
    return max(_CURRENT_YEAR_PIN, datetime.today().year)


def season_list() -> list:
    """Descending season list from the current year back to 1871."""
    return list(range(current_year(), 1870, -1))

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

# Import-time snapshot used only to seed the first layout paint; callbacks that
# must survive a New-Year rollover call season_list() for a fresh list.
SEASONS        = season_list()
# Minimum-PA / minimum-IP ladder, copied from FanGraphs' leaderboard filter so
# the same steps work for a single season and for a whole career: fine steps
# up to 250, 50s to 1,000, then 500s to 10,000. Both stats use the same rungs.
MIN_THRESHOLD_LADDER = ([0, 1, 5, 10] + list(range(20, 251, 10))
                        + list(range(300, 1001, 50))
                        + list(range(1500, 10001, 500)))
MIN_PA_LIST    = ["Qualified"] + MIN_THRESHOLD_LADDER
MIN_IP_LIST    = ["Qualified"] + MIN_THRESHOLD_LADDER

# Largest threshold a single season can be judged against (the old top of
# each dropdown). Anything above it can only mean a span total, so per-season
# views judge it against the player's total over the selected range instead.
SEASON_THRESHOLD_CAP = {"PA": 700, "IP": 300}


# Upper bound for a typed threshold (Bonds/Rose territory is ~15,900 PA).
MAX_THRESHOLD = 20_000


def snap_threshold(raw, ladder=MIN_THRESHOLD_LADDER, default="Qualified"):
    """Parse a URL/user threshold: 'Qualified' stays, any whole number from 0 to
    MAX_THRESHOLD is kept as typed (the dropdown accepts custom values, so a
    shared ?min_pa=2750 link must reopen at 2750, not a ladder rung), anything
    else falls back to `default`."""
    if raw == "Qualified":
        return raw
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return default
    if n < 0:
        return default
    return min(n, MAX_THRESHOLD)


def threshold_options(value=None, ladder=MIN_THRESHOLD_LADDER) -> list:
    """Dropdown options: Qualified + the FanGraphs ladder, plus `value` when it
    is a custom number not on the ladder (so a typed or linked 2750 shows)."""
    vals = ["Qualified"] + list(ladder)
    if isinstance(value, int) and value not in ladder:
        vals = ["Qualified"] + sorted(set(ladder) | {value})
    return [{"label": str(v), "value": v} for v in vals]


# FanGraphs' multi-season "Qualified" (measured against their leaderboard API,
# 2026-11-10): a flat 1,000 PA for batters and 300 IP for pitchers over any
# range of 2+ seasons, judged on the player's full totals. FanGraphs applies it
# even when the range cannot reach it (2020–21 qualifies nobody); here the cut
# is also capped at the sum of the single-season minimums (3.1 PA / 1 IP per
# team game), so short or shortened spans still show their regulars.
QUALIFIED_SPAN_CAP = {"PA": 1000, "IP": 300}
QUALIFIED_RATE = {"PA": 3.1, "IP": 1.0}

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
    # Former MLB identities that FanGraphs keeps under their own codes.
    "BSN": "Boston Braves",        "BRO": "Brooklyn Dodgers",
    "NYG": "New York Giants",      "NYH": "New York Highlanders",
    "PHA": "Philadelphia Athletics", "SLB": "St. Louis Browns",
    "KCA": "Kansas City Athletics", "CAL": "California Angels",
    "ANA": "Anaheim Angels",       "MON": "Montreal Expos",
    "FLA": "Florida Marlins",      "TBD": "Tampa Bay Devil Rays",
    # Federal League (1914–15).
    "BKF": "Brooklyn Tip-Tops",    "CWH": "Chicago Whales",
    "KCP": "Kansas City Packers",  "PRB": "Pittsburgh Rebels",
    "SLT": "St. Louis Terriers",   "NWK": "Newark Peppers",
    # Negro Leagues (MLB-recognized 1920–48); clubs with 4+ seasons in the data.
    "HG":  "Homestead Grays",      "KCM": "Kansas City Monarchs",
    "CAG": "Chicago American Giants", "BEG": "Baltimore Elite Giants",
    "NE":  "Newark Eagles",        "PC":  "Pittsburgh Crawfords",
    "PS":  "Philadelphia Stars",   "NYC": "New York Cubans",
    "NBY": "New York Black Yankees", "BBB": "Birmingham Black Barons",
    "MRS": "Memphis Red Sox",      "CBE": "Cleveland Buckeyes",
    "CIC": "Cincinnati-Indianapolis Clowns", "IC": "Indianapolis Clowns",
    "HIL": "Hilldale",             "DS":  "Detroit Stars",
    "SLS": "St. Louis Stars",      "ABC": "Indianapolis ABCs",
    "BBS": "Baltimore Black Sox",  "NLG": "Lincoln Giants",
    "CSE": "Cuban Stars (East)",   "CSW": "Cuban Stars (West)",
    "AC":  "Bacharach Giants",     "BRG": "Brooklyn Royal Giants",
    "HBG": "Harrisburg Giants",    "NEG": "Nashville Elite Giants",
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


# ── Display precision ────────────────────────────────────────────────────────
# FanGraphs CSVs store every stat at full float precision (wRC+ 219.7835722…)
# and percentages as fractions (K% 0.2429), and range roll-ups produce long
# weighted means. Everything shown to the user is formatted per stat, following
# FanGraphs' own leaderboard conventions: WAR 1 decimal, wRC+ whole, AVG/OBP
# 3 decimals, ERA/FIP 2 decimals, K%/BB% as a 1-decimal percent.

_DEC3 = frozenset({
    "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "wOBA", "xwOBA", "xBA", "xSLG",
    "xAVG", "xOBP", "xOPS", "xISO", "wLeague",
})
_DEC1 = frozenset({
    "WAR", "WAR/650 PAs", "WAROld", "RAR", "Off", "Def", "BsR", "Batting",
    "Fielding", "Positional", "Replacement", "Offense", "Defense",
    "BaseRunning", "Base Running", "wRAA", "UBR", "wSB", "wGDP", "Spd", "EV",
    "LA", "maxEV", "Dollars", "IP", "CFraming", "FRM", "Age", "wBsR", "GDPRuns",
})
# COUNTING_STATS (summed over a span) also lists run values and WPA parts;
# those keep decimals, so only true event counts default to whole numbers.
_DEC0 = (COUNTING_STATS - _DEC1
         - {"WPA", "-WPA", "+WPA", "RE24", "REW", "Clutch", "Pos"}) | frozenset({
    "wRC", "Season", "Pulls", "Barrels", "Events",
})


def stat_precision(stat: str, era: bool = False) -> tuple:
    """(kind, decimals) for displaying `stat`. kind is "pct" for stats stored
    as fractions and shown as percents (K% 0.2429 → 24.3%), "num" otherwise.
    era=True means the value is a within-season percentile (0–100) rather
    than the raw stat, shown as a whole number."""
    s = str(stat or "")
    if era:
        return "num", 0
    if s.endswith(("+", "-")) and s not in ("+WPA", "-WPA"):
        return "num", 0                     # index stats: wRC+, ERA-, K%+, Stuff+
    if "%" in s or s == "HR/FB":
        return "pct", 1
    if s in _DEC3:
        return "num", 3
    if s in _DEC1:
        return "num", 1
    if s in _DEC0:
        return "num", 0
    return "num", 2                         # ERA, FIP, WHIP, K/9, WPA, pitch values


def stat_d3(stat: str, era: bool = False) -> str:
    """d3-format spec (for Plotly hovertemplates/hover_data) for `stat`."""
    kind, n = stat_precision(stat, era)
    if kind == "pct":
        return f".{n}%"
    return ",.0f" if n == 0 else f".{n}f"


def fmt_stat(stat: str, v, era: bool = False) -> str:
    """Format one value of `stat` for display: '.263', '24.3%', '6.4', '144'.
    Missing/non-numeric values render as an em dash."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    kind, n = stat_precision(stat, era)
    if kind == "pct":
        return f"{v * 100:.{n}f}%"
    if n == 0:
        return f"{v:,.0f}"
    out = f"{v:,.{n}f}"                     # 5,553.0 IP
    if n == 3 and abs(v) < 1:               # baseball style: .263, not 0.263
        out = out.replace("0.", ".", 1)
    return out


def round_stats(df: pd.DataFrame, cols, era: bool = False) -> pd.DataFrame:
    """Round stat columns to their display precision for the CSV export.
    Percent stats keep their fraction scale (as FanGraphs exports them), at
    the precision of a 1-decimal percent."""
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            continue
        kind, n = stat_precision(c, era)
        vals = pd.to_numeric(df[c], errors="coerce")
        df[c] = vals.round(n + 2 if kind == "pct" else n)
    return df

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


# Single-flight gate: only one live fetch runs at a time per process. A request
# that arrives while a fetch is already in flight returns empty immediately
# instead of blocking a gunicorn worker, so a burst of cache-miss requests (a
# shared link seeding an uncached season, an attacker scrubbing into the past)
# cannot pile up and exhaust the worker pool. The --watch generator and later
# requests backfill whatever a skipped fetch missed.
_FETCH_GATE = threading.Lock()
# Cap on how long a request-path fetch may hold a worker; well under the
# gunicorn timeout so a slow FanGraphs can't tie a worker up for minutes.
_LIVE_FETCH_TIMEOUT = 8


def _live_fetch(path: str) -> pd.DataFrame:
    """Fetch a season's data and cache it as CSV.

    Guarded by a process-wide single-flight lock and a short network timeout so
    it cannot be used to exhaust the gunicorn worker pool: when another fetch
    already holds the gate this returns an empty frame rather than blocking."""
    p = Path(path)
    parent = p.parent.name
    try:
        year = int(p.stem)
    except ValueError:
        return pd.DataFrame()
    if parent not in _TEAM_DIRS and (not _PYBASEBALL or parent not in _PLAYER_DIRS):
        return pd.DataFrame()

    if not _FETCH_GATE.acquire(blocking=False):
        logging.info("live-fetch gate busy; skipping %s (backfilled later)", path)
        return pd.DataFrame()
    try:
        if parent in _TEAM_DIRS:
            df = fetch_team(_TEAM_DIRS[parent], year,
                            month=split_month(year, current_year()),
                            timeout=_LIVE_FETCH_TIMEOUT)
            if df is not None:
                atomic_to_csv(df, path)
                logging.info("FanGraphs team API: cached %s", path)
                return df
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
    finally:
        _FETCH_GATE.release()


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
# Bounded by bytes as well as entries: one all-players season is ~6 MB in
# memory, so 512 of them could reach ~3 GB in a single worker. Two workers
# plus the watcher share a 1.5 GB container.
_CSV_CACHE_BYTES = 128_000_000
_CSV_BYTES: dict[str, int] = {}


# Identifier-like float columns stay float64 (exact up to 2**53); every stat
# column is stored as float32, which halves the CSV cache, every roll-up and
# every per-request copy. float32 keeps ~7 significant digits, far beyond any
# displayed precision (AVG .3, WAR .1). The VPS froze from RAM exhaustion on
# 2026-10-28, so the container's 1.5 GB limit is a hard budget, not a default.
_KEEP_FLOAT64 = frozenset({"IDfg", "xMLBAMID", "Season", "SeasonMin", "SeasonMax",
                           "teamid", "playerTeamId", "playerid"})


def _float32(df: pd.DataFrame) -> pd.DataFrame:
    """Stat columns to float32 in one block operation (assigning column by
    column cost ~0.1 s per 475-column season file)."""
    cols = [c for c in df.select_dtypes(include="float64").columns
            if c not in _KEEP_FLOAT64]
    if not cols:
        return df
    order = list(df.columns)
    out = pd.concat([df.drop(columns=cols), df[cols].astype("float32")], axis=1)
    return out[order]


def _csv_cache_put(path: str, mtime: float, df: pd.DataFrame) -> None:
    nbytes = int(df.memory_usage(deep=True).sum())
    _CSV_CACHE.pop(path, None)
    _CSV_BYTES.pop(path, None)
    if nbytes > _CSV_CACHE_BYTES:
        return
    while _CSV_CACHE and (len(_CSV_CACHE) >= _CSV_CACHE_MAX
                          or sum(_CSV_BYTES.values()) + nbytes > _CSV_CACHE_BYTES):
        old = next(iter(_CSV_CACHE))
        _CSV_CACHE.pop(old, None)
        _CSV_BYTES.pop(old, None)
    _CSV_CACHE[path] = (mtime, df)
    _CSV_BYTES[path] = nbytes


def _normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Give the player id column its canonical name.

    pybaseball frames call it IDfg; CSVs written straight from the FanGraphs
    API (the 2026-07 refresh onward) call it playerid. Everything downstream —
    span aggregation, click-to-detail, leaderboard refs — keys on IDfg, so
    normalise at the single load point."""
    if "playerid" in df.columns and "IDfg" not in df.columns:
        return df.rename(columns={"playerid": "IDfg"})
    return df


def load_csv(path: str, fetch: bool = True, copy: bool = True,
             cache: bool = True) -> pd.DataFrame:
    """Load CSV; auto-fetches the season live if the file doesn't exist
    (unless fetch=False). copy=False returns the cached frame itself — only
    for read-only lookups (filtering a row out of it), never mutate it.
    cache=False reads through without adding the file to the cache (used by
    the streamed full-history roll-ups, which would otherwise evict
    everything else)."""
    try:
        p = Path(path)
        if p.exists():
            mtime = p.stat().st_mtime
            cached = _CSV_CACHE.get(path)
            if cached and cached[0] == mtime:
                return cached[1].copy() if copy else cached[1]
            df = _float32(_normalize_ids(strip_html(pd.read_csv(path))))
            if not df.empty and cache:
                _csv_cache_put(path, mtime, df)
                return df.copy() if copy else df
            return df
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

    if "Season" in df.columns and group_key != "Season" and len(df):
        # First/last season each entity appears in the span (the rolled-up
        # "Season" column is a meaningless weighted mean of years).
        yrs = pd.to_numeric(df["Season"], errors="coerce").groupby(g)
        parts.append(pd.DataFrame({"_first": yrs.min(), "_last": yrs.max()}))

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
             + [c for c in ("_first", "_last") if c in out.columns]
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


# Rolled-up multi-season frames, keyed on the span and the mtimes of every
# season file in it (so a data refresh invalidates). The chart, leaderboard,
# CSV export and detail panel all ask for the same roll-up; rebuilding it for
# 1871–2026 (156 CSVs × ~470 columns) took ~1.5 s per call. Bounded by bytes,
# not entries: a full-history qualified roll-up is ~16 MB but the all-players
# one is ~89 MB, and each gunicorn worker (already ~0.5 GB with its CSV cache)
# holds its own copy inside a 1.5 GB container.
_SPAN_CACHE: dict = {}                 # key -> (frame, nbytes), oldest first
_SPAN_CACHE_BYTES = 64_000_000


def _span_key(dir_key, lo, hi, group_key):
    d = Path(config[dir_key])
    sig = []
    for y in range(lo, hi + 1):
        try:
            sig.append((d / f"{y}.csv").stat().st_mtime_ns)
        except OSError:
            sig.append(None)
    return (dir_key, str(d), lo, hi, group_key, tuple(sig))


def _span_cache_put(key, df) -> None:
    """Insert a roll-up, evicting the oldest entries to stay under the byte
    budget (a frame bigger than the whole budget is simply not cached)."""
    nbytes = int(df.memory_usage(deep=True).sum())
    _SPAN_CACHE.pop(key, None)
    if nbytes > _SPAN_CACHE_BYTES:
        return
    while _SPAN_CACHE and (sum(b for _, b in _SPAN_CACHE.values())
                           + nbytes > _SPAN_CACHE_BYTES):
        _SPAN_CACHE.pop(next(iter(_SPAN_CACHE)))
    _SPAN_CACHE[key] = (df, nbytes)


# Player spans with more season rows than this (per the light index) are rolled
# up in chunks: all players over 1871–2026 is ~109k rows × 475 columns
# (~465 MB in float64), and concatenating that and weighting it in one go
# needs 2–3× more, which OOM-killed workers in the 1.5 GB container. Smaller
# pools (qualified players, team spans, a few seasons) stay on the exact
# one-shot path.
_STREAM_ROWS = 8_000
# Player spans bigger than this are built under the cross-worker lock, so two
# workers never hold the same large build in memory at once (the second one
# then loads the first one's result from the disk cache).
_LOCK_ROWS = 2_000
_STREAM_CHUNK_ROWS = 8_000
_HEAVY_LOCK_PATH = Path(tempfile.gettempdir()) / "baseball-dashboard-span.lock"


@contextlib.contextmanager
def _heavy_build_lock():
    """Cross-worker lock: only one gunicorn worker builds a streamed roll-up at
    a time (the chart and leaderboard callbacks ask for the same span at once,
    often on different workers)."""
    with open(_HEAVY_LOCK_PATH, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _aggregate_span_chunked(frames, group_key: str, weight_col: str,
                            display_cols: list,
                            chunk_rows: int = _STREAM_CHUNK_ROWS) -> pd.DataFrame:
    """Memory-bounded equivalent of _aggregate_span for very large spans.

    Same semantics — counting columns summed, everything else weight-averaged
    (plain mean where an entity's weight is 0), _first/_last season, display
    columns from the largest-weight season — but built from per-entity partial
    sums accumulated chunk by chunk in float32, so peak memory is one chunk plus
    the accumulators instead of the whole concatenated history."""
    acc: dict = {}
    col_order: list = []
    rep = first = last = None
    buf, nrows = [], 0

    def add(name, part):
        part = part.astype("float32")
        acc[name] = part if name not in acc else acc[name].add(part, fill_value=0)

    def flush():
        nonlocal rep, first, last, buf, nrows
        if not buf:
            return
        df = pd.concat(buf, ignore_index=True)
        buf, nrows = [], 0
        g = df[group_key]
        numeric = [c for c in df.select_dtypes(include="number").columns
                   if c != group_key]
        col_order.extend(c for c in numeric if c not in col_order)
        cc = [c for c in numeric if c == weight_col or c in COUNTING_STATS]
        ac = [c for c in numeric if c not in cc]
        has_w = weight_col in df.columns
        w = (pd.to_numeric(df[weight_col], errors="coerce").fillna(0) if has_w
             else pd.Series(0.0, index=df.index))
        if cc:
            add("cnt", df[cc].groupby(g).sum())
        if ac:
            vals = df[ac]
            if has_w:
                add("vw", vals.mul(w, axis=0).groupby(g).sum())
                add("w", vals.notna().mul(w, axis=0).groupby(g).sum())
            else:
                # Plain means only without a weight column. With one, an
                # entity whose weight is 0 (no PA/IP) has no meaningful rate:
                # NaN here, vs. a mean of undefined per-season rates in
                # _aggregate_span — and two fewer span-sized accumulators.
                add("v", vals.groupby(g).sum())
                add("n", vals.notna().groupby(g).sum())
        if "Season" in df.columns:
            yrs = pd.to_numeric(df["Season"], errors="coerce").groupby(g)
            f, l = yrs.min(), yrs.max()
            first = f if first is None else pd.concat([first, f], axis=1).min(axis=1)
            last = l if last is None else pd.concat([last, l], axis=1).max(axis=1)
        present = [d for d in display_cols if d in df.columns]
        if present:
            idx = w.groupby(g).idxmax()
            r = df.loc[idx.values, present].copy()
            r.index = idx.index
            r["_w"] = w.loc[idx.values].values
            if rep is None:
                rep = r
            else:
                both = rep.reindex(rep.index.union(r.index))
                new = r.reindex(both.index)
                # Earlier seasons win ties, matching idxmax's first occurrence.
                take = new["_w"].notna() & (both["_w"].isna() | (new["_w"] > both["_w"]))
                both.loc[take] = new.loc[take]
                rep = both

    for df in frames:
        if df.empty or group_key not in df.columns:
            continue
        buf.append(df)
        nrows += len(df)
        if nrows >= chunk_rows:
            flush()
    flush()
    if not acc:
        return pd.DataFrame()

    parts = []
    if "cnt" in acc:
        parts.append(acc["cnt"].fillna(0))
    if "w" in acc:
        vw, wt = acc["vw"], acc["w"]
        parts.append((vw / wt).where(wt > 0))
    elif "v" in acc:
        v, n = acc["v"], acc["n"]
        parts.append((v / n).where(n > 0))
    if first is not None:
        parts.append(pd.DataFrame({"_first": first, "_last": last}))
    if rep is not None:
        parts.append(rep.drop(columns="_w"))
    out = pd.concat(parts, axis=1)
    order = ([c for c in col_order if c in out.columns]
             + [c for c in ("_first", "_last") if c in out.columns]
             + [d for d in display_cols if d in out.columns])
    out = out[order]
    out.index.name = group_key
    return out.reset_index()


# ── Shared on-disk cache ─────────────────────────────────────────────────────
# Each gunicorn worker has its own memory, so without this the chart and the
# leaderboard (often served by different workers) each rebuilt the same
# full-history roll-up. Roll-ups and the light per-season index are pickled
# here, keyed on every input file's mtime, so one worker builds and the other
# loads in well under a second. Container-private /tmp; pruned to a byte budget.
_DISK_CACHE = Path(tempfile.gettempdir()) / "baseball-dashboard-cache"
_DISK_CACHE_BYTES = 300_000_000          # host disk is shared and tight


def _disk_path(kind: str, key) -> Path:
    h = hashlib.sha1(repr(key).encode()).hexdigest()[:24]
    return _DISK_CACHE / kind / f"{h}.pkl"


def _disk_get(kind: str, key):
    p = _disk_path(kind, key)
    try:
        df = pd.read_pickle(p)
        os.utime(p)                          # LRU: touch on use
        return df
    except Exception:
        return None


def _disk_put(kind: str, key, df: pd.DataFrame) -> None:
    p = _disk_path(kind, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        df.to_pickle(tmp)
        os.replace(tmp, p)
        files = sorted(_DISK_CACHE.glob("*/*.pkl"), key=lambda q: q.stat().st_mtime)
        total = sum(q.stat().st_size for q in files)
        while files and total > _DISK_CACHE_BYTES:
            old = files.pop(0)
            total -= old.stat().st_size
            old.unlink(missing_ok=True)
    except Exception as exc:
        logging.warning("disk cache write failed (%s): %s", kind, exc)


# Light per-season index: just the columns needed to decide who is in a
# player pool (id, playing time, games, team). Reading these for 156 seasons is
# a few MB, versus ~465 MB for the full all-players history.
_INDEX_COLS = frozenset({"IDfg", "playerid", "PA", "IP", "G", "GS", "Team"})
_INDEX: dict = {}


def _season_index(path) -> pd.DataFrame:
    path = str(path)
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        return pd.DataFrame()
    hit = _INDEX.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    key = (path, mtime)
    df = _disk_get("index", key)
    if df is None:
        cached = _CSV_CACHE.get(path)
        try:
            if cached:
                df = cached[1][[c for c in cached[1].columns if c in _INDEX_COLS]].copy()
            else:
                df = pd.read_csv(path, usecols=lambda c: c in _INDEX_COLS)
            df = _normalize_ids(df)
        except Exception as exc:
            logging.warning("index read failed for %s: %s", path, exc)
            return pd.DataFrame()
        _disk_put("index", key, df)
    _INDEX[path] = (mtime, df)
    return df


_TOTALS: dict = {}


def span_totals(dir_key: str, lo: int, hi: int) -> pd.DataFrame:
    """Per-player playing time over lo..hi from the light index: columns
    total (PA, or true innings for IP) and rows (season rows in the span),
    indexed by IDfg."""
    key = _span_key(dir_key, lo, hi, "totals")
    hit = _TOTALS.get(key)
    if hit is not None:
        return hit
    wcol = _weight_col_for(dir_key)
    parts = []
    for y in range(lo, hi + 1):
        idx = _season_index(Path(config[dir_key]) / f"{y}.csv")
        if idx.empty or "IDfg" not in idx.columns or wcol not in idx.columns:
            continue
        w = pd.to_numeric(idx[wcol], errors="coerce").fillna(0)
        if wcol == "IP" and ip_is_notation(w):
            w = ip_to_innings(w).fillna(0)
        parts.append(pd.DataFrame({"IDfg": idx["IDfg"].values, "w": w.values}))
    if not parts:
        out = pd.DataFrame({"total": [], "rows": []})
    else:
        g = pd.concat(parts, ignore_index=True).groupby("IDfg")["w"]
        out = pd.DataFrame({"total": g.sum(), "rows": g.size()})
    if len(_TOTALS) > 64:
        _TOTALS.pop(next(iter(_TOTALS)))
    _TOTALS[key] = out
    return out


_TEAM_GAMES: dict = {}


def team_games(year: int) -> float:
    """Games per team in a season (mean W+L of the team pitching file; 162 if
    unknown). 60 in 2020, ~154 before 1961, far fewer in the 1870s."""
    path = f"{config['team_pitching_dir']}/{year}.csv"
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        mtime = None
    hit = _TEAM_GAMES.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    g = _team_games_uncached(path)
    _TEAM_GAMES[path] = (mtime, g)
    return g


def _team_games_uncached(path) -> float:
    tp = load_csv(path, fetch=False, copy=False)
    if not tp.empty and {"W", "L"} <= set(tp.columns):
        g = (pd.to_numeric(tp["W"], errors="coerce")
             + pd.to_numeric(tp["L"], errors="coerce")).mean()
        if g == g and g > 0:
            return float(g)
    return 162.0


def span_qualified_min(col: str, lo: int, hi: int) -> float:
    """Playing-time cut for "Qualified" over lo..hi (col "PA" or "IP"): one
    season → 3.1 PA / 1 IP per team game; a range → FanGraphs' 1,000 PA /
    300 IP, capped at the sum of the single-season minimums."""
    single = sum(QUALIFIED_RATE[col] * team_games(y) for y in range(lo, hi + 1))
    return single if hi <= lo else min(float(QUALIFIED_SPAN_CAP[col]), single)


def threshold_cohort(dir_key: str, lo: int, hi: int, thr) -> set | None:
    """IDfg of players whose span total reaches `thr`; None means no cut."""
    if thr is None or float(thr) <= 0:
        return None
    tot = span_totals(dir_key, lo, hi)
    return set(tot.index[tot["total"] >= float(thr) - 1e-9])


# Per-player descriptive columns carried from each entity's largest-weight
# season through a range roll-up (they're strings, not stats).
PLAYER_DISPLAY_COLS = ["Name", "Team", "position", "Bats", "Throws"]


def season_row_count(dir_key: str, lo: int, hi: int, col=None, thr=None,
                     ids=None) -> int:
    """Rows the per-season view would plot (from the light index): every
    season row, or only rows with `col` >= thr, or only players in `ids`."""
    n = 0
    for y in range(lo, hi + 1):
        idx = _season_index(Path(config[dir_key]) / f"{y}.csv")
        if idx.empty:
            continue
        m = pd.Series(True, index=idx.index)
        if ids is not None and "IDfg" in idx.columns:
            m &= idx["IDfg"].isin(ids)
        if thr is not None and col in idx.columns:
            v = pd.to_numeric(idx[col], errors="coerce")
            if col == "IP" and ip_is_notation(v):
                v = ip_to_innings(v)
            m &= v >= float(thr)
        n += int(m.sum())
    return n


def load_stats(dir_key: str, lo, hi=None, group_key: str = "Team",
               split: bool = False, min_total=None, row_filter=None) -> pd.DataFrame:
    """Load one entity-per-row frame for a season or an inclusive season range.

    For a single season (hi is None or hi == lo) this is just the season CSV, so
    the common case stays as cheap as before. For a range it concatenates the
    seasons and rolls them up per entity via _aggregate_span — summing counting
    stats and weight-averaging rate stats — so the chart and leaderboard show one
    cumulative point per team/player across the span.

    With split=True the range is *not* rolled up: every entity-season stays its
    own row, tagged with a Season column (the "per season" range view).

    min_total (players only): keep only players whose PA/IP over the span
    reaches it. The cohort comes from the light index first, so a career cut
    over 1871–2026 reads and rolls up only the qualifying players' rows.

    row_filter (split only): applied to each season before stacking, so a
    long per-season view never holds every player-season at once."""
    lo, _ = season_bounds(lo if hi is None else [lo, hi])
    if lo is None:
        return pd.DataFrame()
    hi = lo if hi is None else int(hi)
    if split:
        # Per-season rows over a range: no live fetch either (see below).
        def seasons():
            for y in range(lo, max(lo, hi) + 1):
                df = load_csv(f"{config[dir_key]}/{y}.csv", fetch=(hi <= lo),
                              copy=False, cache=(hi - lo) < 20)
                if row_filter is not None and not df.empty:
                    df = row_filter(df)
                yield y, df
        return _season_rows(seasons())
    if hi <= lo:
        return load_csv(f"{config[dir_key]}/{lo}.csv")
    ids = None
    if group_key == "IDfg" and min_total is not None:
        ids = threshold_cohort(dir_key, lo, hi, min_total)
        if ids is not None and not ids:
            return pd.DataFrame()
    thr_key = round(float(min_total), 3) if ids is not None else None
    key = _span_key(dir_key, lo, hi, group_key) + (thr_key,)
    hit = _SPAN_CACHE.get(key)
    if hit is not None:
        return hit[0].copy()
    rows = 0
    if group_key == "IDfg":
        tot = span_totals(dir_key, lo, hi)
        rows = int(tot["rows"].sum() if ids is None
                   else tot.loc[tot.index.isin(ids), "rows"].sum())
    if rows > _LOCK_ROWS:
        with _heavy_build_lock():            # one worker builds; others wait
            out = _build_span(dir_key, lo, hi, group_key, key, ids,
                              stream=rows > _STREAM_ROWS)
        _release_memory()
        return out
    return _build_span(dir_key, lo, hi, group_key, key, ids, stream=False)


def _release_memory() -> None:
    """Hand freed heap back to the OS after a big build. pandas' transient
    arrays otherwise stay in glibc's arenas and a worker's RSS ratchets up
    build after build until the container limit kills it."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _build_span(dir_key, lo, hi, group_key, key, ids, stream) -> pd.DataFrame:
    """Roll up lo..hi (optionally only `ids`), via the memory/disk caches.

    stream=True: season files are read through without filling the CSV cache
    and aggregated in chunks (_aggregate_span_chunked); otherwise the exact
    one-shot _aggregate_span."""
    hit = _SPAN_CACHE.get(key)
    if hit is not None:
        return hit[0].copy()
    out = _disk_get("span", key)
    if out is not None:
        _span_cache_put(key, out)
        return out.copy()
    display = PLAYER_DISPLAY_COLS if group_key != "Team" else []
    notation = []

    # A multi-season range never triggers a live fetch: looping fetch over a
    # wide uncached span (e.g. 1871–2026) would block a worker for the whole
    # range. Missing seasons are left to the single-season view and the --watch
    # backfill; the range shows whatever is already cached.
    def frames():
        for y in range(lo, hi + 1):
            df = load_csv(f"{config[dir_key]}/{y}.csv", fetch=False,
                          copy=not stream, cache=not stream)
            if df.empty:
                continue
            if ids is not None and "IDfg" in df.columns:
                df = df[df["IDfg"].isin(ids)]
                if df.empty:
                    continue
            # IP in baseball notation (177.2 = 177⅔) is summed, weighted and
            # turned into ERA/WHIP/K/9 as true innings; back to notation below.
            n = "IP" in df.columns and ip_is_notation(df["IP"])
            notation.append(n)
            yield true_innings_frame(df) if n else df

    weight = _weight_col_for(dir_key)
    if stream:
        out = _aggregate_span_chunked(frames(), group_key, weight, display)
    else:
        fs = list(frames())
        if not fs:
            return pd.DataFrame()
        combined = pd.concat(fs, ignore_index=True)
        if group_key not in combined.columns:
            return fs[-1]
        out = _aggregate_span(combined, group_key, weight, display)
    if out.empty:
        return out
    # Rebuild ratio stats from the summed counting parts (AVG = ΣH/ΣAB, etc.)
    # instead of leaving the PA/IP-weighted average the roll-up produced.
    out = recompute_rate_stats(out, is_pitching="pitching" in dir_key)
    if "IP" in out.columns and notation and all(notation):
        out["IP"] = innings_to_ip(out["IP"]).values
    out = _float32(out)
    _span_cache_put(key, out)
    _disk_put("span", key, out)
    return out.copy()


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
    display = PLAYER_DISPLAY_COLS if group_key != "Team" else []
    # Weight the span by a PRIVATE copy of the raw weight column. If the user
    # era-adjusts PA/IP itself, weight_col also appears in `stats`, and
    # pct_within_season would overwrite it with percentiles (weighting by
    # rank, not innings). A private name also prevents a duplicate weight
    # column in `keep`, which raised a TypeError in _aggregate_span (the
    # era-axis-on-PA/IP render crash).
    WT = "__weight__"
    keep = list(dict.fromkeys([group_key, WT, weight_col] + display + stats))
    single = (lo == hi)
    frames = []
    for y in range(lo, hi + 1):
        # Range loads never live-fetch (see load_stats); a single-season
        # era view still may.
        df = load_csv(f"{config[dir_key]}/{y}.csv", fetch=single)
        if df.empty:
            continue
        if season_prep is not None:
            df = season_prep(df)
        if df.empty or group_key not in df.columns:
            continue
        df = df.copy()
        df[WT] = (pd.to_numeric(true_innings_frame(df[[weight_col]])[weight_col],
                                errors="coerce")
                  if weight_col in df.columns else 0.0)
        df = pct_within_season(df, stats)
        frames.append((y, df[[c for c in keep if c in df.columns]]))
    if not frames:
        return pd.DataFrame()
    if split:
        return _season_rows(frames).drop(columns=[WT], errors="ignore")
    combined = pd.concat([f for _, f in frames], ignore_index=True)
    out = _aggregate_span(combined, group_key, WT, display,
                          rate_cols=frozenset(stats))
    return out.drop(columns=[WT], errors="ignore")


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
