#!/usr/bin/env python3
"""Data layer — config, CSV loading, live-fetch, static catalogs and theme tokens."""

import base64
import functools
import html
import io
import json
import logging
import re
from pathlib import Path

try:
    from PIL import Image as _PILImage
    _PIL = True
except ImportError:
    _PIL = False

import requests
import pandas as pd

try:
    import pybaseball as pyb
    _PYBASEBALL = True
except ImportError:
    _PYBASEBALL = False

# ── Config ────────────────────────────────────────────────────────────────────

with open("config.json") as f:
    config = json.load(f)

EXCLUDED_COLS = {"Team", "Season", "Dollars", "Name", "IDfg", "Unnamed: 0"}
PRIORITY_COLS = ["WAR", "wRC+", "SIERA"]

NL_TEAMS = {"ARI", "ATL", "CHC", "CIN", "COL", "LAD", "MIA", "MIL",
            "NYM", "PHI", "PIT", "SDP", "SFG", "STL", "WAS"}
AL_TEAMS = {"BAL", "BOS", "CHW", "CLE", "DET", "HOU", "LAA", "KCR",
            "MIN", "NYY", "OAK", "SEA", "TBR", "TEX", "TOR"}

TEAM_LOGO_MAP = {
    "LAA": "angels",   "BAL": "orioles",  "BOS": "redsox",    "CHW": "whitesox",
    "CLE": "guardians","DET": "tigers",   "KCR": "royals",    "MIN": "twins",
    "NYY": "yankees",  "OAK": "athletics","SEA": "mariners",  "TBR": "rays",
    "TEX": "rangers",  "TOR": "bluejays", "ARI": "diamondbacks","ATL": "braves",
    "CHC": "cubs",     "CIN": "reds",     "COL": "rockies",   "MIA": "marlins",
    "HOU": "astros",   "LAD": "dodgers",  "MIL": "brewers",   "WAS": "nationals",
    "NYM": "mets",     "PHI": "phillies", "PIT": "pirates",   "STL": "cardinals",
    "SDP": "padres",   "SFG": "giants",
}

TEAM_SEASONS   = list(range(config["current_year"], 1997, -1))
PLAYER_SEASONS = list(range(config["current_year"], 1870, -1))
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
    "TOR": "#134A8E", "WAS": "#AB0003",
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
    "TOR": "#1D2D5C", "WAS": "#14225A",
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
    "TOR": "Toronto Blue Jays",    "WAS": "Washington Nationals",
}

TEAM_DIVISION = {
    "ARI": "NL West",   "ATL": "NL East",  "BAL": "AL East",   "BOS": "AL East",
    "CHC": "NL Central","CHW": "AL Central","CIN": "NL Central","CLE": "AL Central",
    "COL": "NL West",   "DET": "AL Central","HOU": "AL West",  "KCR": "AL Central",
    "LAA": "AL West",   "LAD": "NL West",  "MIA": "NL East",   "MIL": "NL Central",
    "MIN": "AL Central","NYM": "NL East",  "NYY": "AL East",   "OAK": "AL West",
    "PHI": "NL East",   "PIT": "NL Central","SDP": "NL West",  "SEA": "AL West",
    "SFG": "NL West",   "STL": "NL Central","TBR": "AL East",  "TEX": "AL West",
    "TOR": "AL East",   "WAS": "NL East",
}

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
    "ERA-", "FIP-", "xFIP-", "tERA", "kwERA", "RA9",
    "GDP", "GIDP", "CS", "E", "BK", "WP", "BS", "L", "HBP",
    "SwStr%", "O-Swing%", "Chase%", "Pitches/Game",
})
# Bad for a pitcher (offense allowed); good for a hitter.
_LOWER_FOR_PITCHERS = frozenset({
    "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "wOBA", "xwOBA", "wRC", "wRC+",
    "wRAA", "BB%", "HR", "R", "ER", "H", "BB", "1B", "2B", "3B", "RBI", "TB",
    "HR/FB", "Barrel%", "HardHit%", "EV", "LD%",
})
# Bad for a hitter (strikeouts); good for a pitcher.
_LOWER_FOR_BATTERS = frozenset({"K%", "SO", "K"})


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

# ── live-fetch: FanGraphs API for team stats, pybaseball for player stats ─────

_FG_API = "https://www.fangraphs.com/api/leaders/major-league/data"

_TEAM_DIRS   = {config["team_batting_dir"]: "bat", config["team_pitching_dir"]: "pit"}
_PLAYER_DIRS = {
    config["qualified_batting_dir"]: ("batting_stats",   {}),
    config["all_batting_dir"]:       ("batting_stats",   {"qual": 0}),
    config["qualified_pitching_dir"]:("pitching_stats",  {}),
    config["all_pitching_dir"]:      ("pitching_stats",  {"qual": 0}),
}


def _fetch_team_fg(stats: str, year: int) -> pd.DataFrame | None:
    params = dict(
        pos="all", stats=stats, lg="all", qual=0, type=8,
        season=year, month=0, season1=year, ind=0, team=0, rost=0, age=0,
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
        return df.groupby("Team").sum(numeric_only=True).reset_index()
    except Exception as exc:
        logging.warning("FanGraphs team API failed (stats=%s year=%d): %s", stats, year, exc)
        return None


def _live_fetch(path: str) -> pd.DataFrame:
    """Fetch a season's data and cache it as CSV."""
    p = Path(path)
    parent = p.parent.name
    try:
        year = int(p.stem)
    except ValueError:
        return pd.DataFrame()

    if parent in _TEAM_DIRS:
        df = _fetch_team_fg(_TEAM_DIRS[parent], year)
        if df is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path)
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
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
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


_HTML_TAG_RE = re.compile(r"<[^>]*>")


def _clean_text(v):
    if not isinstance(v, str):
        return v
    return html.unescape(_HTML_TAG_RE.sub("", v)).strip()


def _strip_html(df: pd.DataFrame) -> pd.DataFrame:
    """FanGraphs' JSON API returns Name/Team as HTML <a> tags. Reduce them to
    plain text so labels render cleanly (affects API-sourced 2025+ CSVs)."""
    for col in ("Name", "Team"):
        if col in df.columns:
            df[col] = df[col].map(_clean_text)
    return df


@functools.lru_cache(maxsize=512)
def load_csv(path: str) -> pd.DataFrame:
    """Load CSV; auto-fetches via pybaseball if the file doesn't exist."""
    try:
        if Path(path).exists():
            df = pd.read_csv(path)
        else:
            df = _live_fetch(path)
        return _strip_html(df)
    except Exception:
        return pd.DataFrame()


def seasons_with_data(dir_key: str, stat: str) -> frozenset:
    result = set()
    for f in Path(config[dir_key]).glob("*.csv"):
        try:
            df = pd.read_csv(f, usecols=[stat])
            if df[stat].notna().any():
                result.add(int(f.stem))
        except Exception:
            pass
    return frozenset(result)


_LOGO_SIZE = 160  # all logos normalised to this square (px) before encoding


@functools.lru_cache(maxsize=64)
def logo_b64(team: str) -> str | None:
    name = TEAM_LOGO_MAP.get(team)
    if not name:
        return None
    path = f"./Logos/{name}-resizedmatplotlib.png"
    try:
        if _PIL:
            with _PILImage.open(path) as img:
                img = img.convert("RGBA")
                img.thumbnail((_LOGO_SIZE, _LOGO_SIZE), _PILImage.LANCZOS)
                canvas = _PILImage.new("RGBA", (_LOGO_SIZE, _LOGO_SIZE), (0, 0, 0, 0))
                canvas.paste(img,
                             (((_LOGO_SIZE - img.width) // 2),
                              ((_LOGO_SIZE - img.height) // 2)),
                             img)
            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
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
