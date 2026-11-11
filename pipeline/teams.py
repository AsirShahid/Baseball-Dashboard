"""Team identities, names, colors, leagues and divisions.

The tables marked "from the Dash site" were copied verbatim from data.py
(commit 6a3c314), where they were researched and tested.
"""
from __future__ import annotations

import json
from pathlib import Path

MULTI_TEAM = "- - -"

# from the Dash site
NL_TEAMS = {"ARI", "ATL", "CHC", "CIN", "COL", "LAD", "MIA", "MIL",
            "NYM", "PHI", "PIT", "SDP", "SFG", "STL",
            "BRO", "BSN", "NYG", "MON", "FLA", "WSN", "CHI", "LOU",
            "MLN", "CI76", "CL79", "DE81", "MI78", "WA86"}

# from the Dash site
AL_TEAMS = {"BAL", "BOS", "CHW", "CLE", "DET", "HOU", "LAA", "KCR",
            "MIN", "NYY", "OAK", "ATH", "SEA", "TBR", "TEX", "TOR",
            "ANA", "CAL", "KCA", "NYH", "PHA", "SLB", "TBD", "WAS",
            "MLA", "SEP", "WSH", "WSA", "BLA"}

# from the Dash site
_LEAGUE_ERAS = {
    # 1901 AL Brewers → (St. Louis from 1902); 1970–97 AL Brewers; NL since.
    "MIL": ((1901, 1901, "AL"), (1970, 1997, "AL"), (None, None, "NL")),
    "HOU": ((2013, None, "AL"), (None, None, "NL")),
    # Senators (AL 1901–71); the 1890s Washington club was NL.
    "WAS": ((1901, 1971, "AL"), (None, 1899, "NL")),
    # 1890s NL Orioles; the 1880s club was American Association (neither).
    "BAL": ((1892, 1899, "NL"), (None, 1891, None), (1901, None, "AL")),
    # Split-off 19th-century clubs (_TEAM_IDENTITY) that moved between the
    # NA / AA / UA (neither) and the NL.
    "BA82": ((1892, 1899, "NL"), (None, None, None)),
    "CL87": ((1889, 1899, "NL"), (None, None, None)),
    "SL75": ((1876, 1877, "NL"), (None, None, None)),
    "SL84": ((1885, 1886, "NL"), (None, None, None)),
    "NY71": ((1876, 1876, "NL"), (None, None, None)),
    "WA91": ((1892, 1899, "NL"), (None, None, None)),
}

# from the Dash site
_TEAM_IDENTITY = {
    # code, FanGraphs teamid → identity code
    ("MIL", 16): "MLN",   ("MIL", 2): "MLA",    ("SEA", 23): "SEP",
    ("WAS", 8): "WSH",    ("WAS", 13): "WSA",   ("BAL", 9): "BLA",
    ("BAL", 1005): "BA72", ("BAL", 1006): "BA82", ("BAL", 1008): "BA84",
    ("BAL", 1007): "BA14", ("CIN", 1028): "CI76", ("CLE", 1020): "CL71",
    ("CLE", 1018): "CL79", ("CLE", 1026): "CL87", ("COL", 1017): "CO83",
    ("COL", 1025): "CO89", ("DET", 1031): "DE81", ("MIL", 1048): "MI78",
    ("MIL", 1049): "MI84", ("MIL", 1047): "MI91", ("NYM", 1053): "NY71",
    ("NYM", 1055): "NY83", ("STL", 1070): "SL75", ("STL", 1072): "SL84",
    ("WAS", 1087): "WA86", ("WAS", 1082): "WA91", ("WSN", 1050): "WS72",
    ("WSN", 1083): "WS73", ("WSN", 1090): "WS84", ("PHA", 1060): "PH82",
    ("PHA", 1062): "PH91",
}

# from the Dash site
_IDENTITY_NAMES = {
    "BA72": ("Baltimore", 1872, 1874), "BA82": ("Baltimore", 1882, 1899),
    "BA84": ("Baltimore", 1884, 1884), "BA14": ("Baltimore", 1914, 1915),
    "CI76": ("Cincinnati", 1876, 1880), "CL71": ("Cleveland", 1871, 1872),
    "CL79": ("Cleveland", 1879, 1884), "CL87": ("Cleveland", 1887, 1899),
    "CO83": ("Columbus", 1883, 1884), "CO89": ("Columbus", 1889, 1891),
    "DE81": ("Detroit", 1881, 1888), "MI78": ("Milwaukee", 1878, 1878),
    "MI84": ("Milwaukee", 1884, 1884), "MI91": ("Milwaukee", 1891, 1891),
    "NY71": ("New York", 1871, 1876), "NY83": ("New York", 1883, 1887),
    "SL75": ("St. Louis", 1875, 1877), "SL84": ("St. Louis", 1884, 1886),
    "WA86": ("Washington", 1886, 1889), "WA91": ("Washington", 1891, 1899),
    "WS72": ("Washington", 1872, 1872), "WS73": ("Washington", 1873, 1873),
    "WS84": ("Washington", 1884, 1884), "PH82": ("Philadelphia", 1882, 1890),
    "PH91": ("Philadelphia", 1891, 1891),
}

# from the Dash site
TEAM_NAME_ERAS = {
    "CLE": ((1901, "Cleveland Blues"), (1905, "Cleveland Naps"),
            (1915, "Cleveland Indians"), (2022, "Cleveland Guardians")),
    "HOU": ((1962, "Houston Colt .45s"), (1965, "Houston Astros")),
    "BSN": ((1883, "Boston Beaneaters"), (1907, "Boston Doves"),
            (1911, "Boston Rustlers"), (1912, "Boston Braves"),
            (1936, "Boston Bees"), (1941, "Boston Braves")),
    "BRO": ((1899, "Brooklyn Superbas"), (1911, "Brooklyn Dodgers"),
            (1914, "Brooklyn Robins"), (1932, "Brooklyn Dodgers")),
    "CHW": ((1901, "Chicago White Stockings"), (1904, "Chicago White Sox")),
    "BOS": ((1901, "Boston Americans"), (1908, "Boston Red Sox")),
}

# from the Dash site
TEAM_LOGO_MAP = {
    "LAA": "angels",   "BAL": "orioles",  "BOS": "redsox",    "CHW": "whitesox",
    "CLE": "guardians","DET": "tigers",   "KCR": "royals",    "MIN": "twins",
    "NYY": "yankees",  "OAK": "athletics","SEA": "mariners",  "TBR": "rays",
    "TEX": "rangers",  "TOR": "bluejays", "ARI": "diamondbacks","ATL": "braves",
    "CHC": "cubs",     "CIN": "reds",     "COL": "rockies",   "MIA": "marlins",
    "HOU": "astros",   "LAD": "dodgers",  "MIL": "brewers",   "WSN": "nationals",
    "NYM": "mets",     "PHI": "phillies", "PIT": "pirates",   "STL": "cardinals",
    "SDP": "padres",   "SFG": "giants",   "ATH": "athletics",
    # Former identities: period logos from Wikipedia's club articles, the
    # Florida Marlins (1993) and Devil Rays (2001) primaries from
    # sportslogos.net. Fallback only: Logos/eras/manifest.json (dated
    # primaries, TEAM_LOGO_ERAS) covers every one of these codes.
    "MON": "expos",     "FLA": "flmarlins", "TBD": "devilrays",
    "CAL": "calangels", "ANA": "anaangels", "KCA": "kcathletics",
    "PHA": "phathletics","SLB": "browns",   "SEP": "pilots",
    "WSH": "senators",  "WSA": "senators2", "MLN": "milbraves",
    "BSN": "bosbraves", "BRO": "brododgers","NYG": "nygiants",
}

# from the Dash site
TEAM_COLORS = {
    "ARI": "#A71930", "ATL": "#CE1141", "BAL": "#DF4601", "BOS": "#BD3039",
    "CHC": "#0E3386", "CHW": "#27251F", "CIN": "#C6011F", "CLE": "#00385D",
    "COL": "#33006F", "DET": "#0C2340", "HOU": "#EB6E1F", "KCR": "#004687",
    "LAA": "#BA0021", "LAD": "#005A9C", "MIA": "#00A3E0", "MIL": "#12284B",
    "MIN": "#002B5C", "NYM": "#FF5910", "NYY": "#003087", "OAK": "#003831",
    "PHI": "#E81828", "PIT": "#FDB827", "SDP": "#2F241D", "SEA": "#0C2C56",
    "SFG": "#FD5A1E", "STL": "#C41E3A", "TBR": "#092C5C", "TEX": "#003278",
    "TOR": "#134A8E", "WAS": "#AB0003", "WSN": "#AB0003", "ATH": "#003831",
    "MON": "#003087", "FLA": "#00A3AD", "TBD": "#00573F", "CAL": "#BA0021",
    "ANA": "#BA0021", "KCA": "#006341", "PHA": "#003087", "SLB": "#6E3B1E",
    "SEP": "#002D72", "WSH": "#AB0003", "WSA": "#AB0003", "MLN": "#13274F",
    "BSN": "#13274F", "BRO": "#005A9C", "NYG": "#FD5A1E", "NYH": "#0C2340",
    "MLA": "#12284B", "BLA": "#DF4601",
}

# from the Dash site
TEAM_COLOR_ALT = {
    "ARI": "#E3D4AD", "ATL": "#13274F", "BAL": "#000000", "BOS": "#0C2340",
    "CHC": "#CC3433", "CHW": "#C4CED4", "CIN": "#000000", "CLE": "#E50022",
    "COL": "#C4CED4", "DET": "#FA4616", "HOU": "#002D62", "KCR": "#BD9B60",
    "LAA": "#003263", "LAD": "#A5ACAF", "MIA": "#EF3340", "MIL": "#FFC52F",
    "MIN": "#D31145", "NYM": "#002D72", "NYY": "#E4002C", "OAK": "#EFB21E",
    "PHI": "#002D72", "PIT": "#FDB827", "SDP": "#FFC425", "SEA": "#005C5C",
    "SFG": "#27251F", "STL": "#0C2340", "TBR": "#8FBCE6", "TEX": "#C0111F",
    "TOR": "#1D2D5C", "WAS": "#14225A", "WSN": "#14225A", "ATH": "#EFB21E",
    "MON": "#E4002B", "FLA": "#000000", "TBD": "#4B2E83", "CAL": "#003263",
    "ANA": "#1D2D5C", "KCA": "#FFC52F", "PHA": "#A2AAAD", "SLB": "#F47A00",
    "SEP": "#FFC72C", "WSH": "#14225A", "WSA": "#14225A", "MLN": "#CE1141",
    "BSN": "#CE1141", "BRO": "#EF3E42", "NYG": "#000000", "NYH": "#A2AAAD",
    "MLA": "#FFC52F", "BLA": "#000000",
}

# from the Dash site
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
    "MLN": "Milwaukee Braves",     "SEP": "Seattle Pilots",
    "WSH": "Washington Senators",  "WSA": "Washington Senators (1961–71)",
    "MLA": "Milwaukee Brewers (1901)", "BLA": "Baltimore Orioles (1901–02)",
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

# from the Dash site
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

TEAM_FULL_NAME.update({
    code: f"{city} ({lo})" if lo == hi else f"{city} ({lo}\u2013{hi})"
    for code, (city, lo, hi) in _IDENTITY_NAMES.items()})
_IDENTITY_CODES = frozenset(code for code, _ in _TEAM_IDENTITY)


def recode(code: str, teamid) -> str:
    """FanGraphs reuses some codes for different franchises (MIL = the 1950s
    Braves and the Brewers); its teamid tells them apart."""
    code = str(code or "").strip()
    if code in _IDENTITY_CODES:
        try:
            return _TEAM_IDENTITY.get((code, int(float(teamid))), code)
        except (TypeError, ValueError):
            return code
    return code


def team_name(code: str, season=None) -> str:
    """The club's name in `season` (its last name when None)."""
    code = str(code)
    if code == MULTI_TEAM:
        return "Multiple teams"
    eras = TEAM_NAME_ERAS.get(code)
    if eras and season is not None:
        pick = None
        for first, name in eras:
            if first <= int(season):
                pick = name
        if pick:
            return pick
    return TEAM_FULL_NAME.get(code, code)


def league(code: str, season: int):
    """'AL', 'NL' or None (another league: NA, AA, UA, PL, FL, Negro Leagues)."""
    for lo, hi, lg in _LEAGUE_ERAS.get(code, ()):
        if (lo is None or season >= lo) and (hi is None or season <= hi):
            return lg
    if code in AL_TEAMS and season >= 1901:
        return "AL"
    if code in NL_TEAMS and season >= 1876:
        return "NL"
    return None


def other_leagues(season: int) -> str:
    """What the teams outside the AL and NL played in that season."""
    names = []
    if season <= 1875:
        names.append("National Association")
    if 1882 <= season <= 1891:
        names.append("American Association")
    if season == 1884:
        names.append("Union Association")
    if season == 1890:
        names.append("Players' League")
    if 1914 <= season <= 1915:
        names.append("Federal League")
    if 1920 <= season <= 1948:
        names.append("Negro Leagues")
    return " and ".join(names) or "Other leagues"


# Division membership since divisions began (1969), in FanGraphs codes.
_DIVISIONS = (
    # (first, last, division, codes)
    (1969, 1993, "AL East", ("BAL", "BOS", "CLE", "DET", "NYY", "WSA", "TOR")),
    (1969, 1993, "AL West", ("CAL", "CHW", "KCR", "MIN", "OAK", "SEP", "SEA", "TEX")),
    (1969, 1993, "NL East", ("CHC", "MON", "NYM", "PHI", "PIT", "STL", "FLA")),
    (1969, 1993, "NL West", ("ATL", "CIN", "HOU", "LAD", "SDP", "SFG", "COL")),
    (1994, 2012, "AL East", ("BAL", "BOS", "NYY", "TOR", "TBD", "TBR")),
    (1994, 2012, "AL Central", ("CHW", "CLE", "KCR", "MIN")),
    (1994, 2012, "AL West", ("CAL", "ANA", "LAA", "OAK", "SEA", "TEX")),
    (1994, 2012, "NL East", ("ATL", "FLA", "MIA", "MON", "WSN", "NYM", "PHI")),
    (1994, 2012, "NL Central", ("CHC", "CIN", "HOU", "PIT", "STL")),
    (1994, 2012, "NL West", ("ARI", "COL", "LAD", "SDP", "SFG")),
)


def division(code: str, season: int):
    """'AL East' etc. for 1969 on, or None before divisions existed."""
    if season < 1969:
        return None
    if season >= 2013:
        return TEAM_DIVISION.get("ATH" if code == "OAK" else code)
    if code == "MIL":                     # Brewers: AL West 1970-71, AL East 1972-93,
        if season <= 1971:                # AL Central 1994-97, NL Central 1998-2012
            return "AL West"
        return "AL East" if season <= 1993 else ("AL Central" if season <= 1997 else "NL Central")
    if code == "DET" and season >= 1994:
        return "AL East" if season <= 1997 else "AL Central"
    if code == "CLE" and season >= 1994:
        return "AL Central"
    for first, last, name, codes in _DIVISIONS:
        if first <= season <= last and code in codes:
            return name
    return None


ROOT = Path(__file__).resolve().parent.parent
LOGO_DIR = ROOT / "Logos"


def _logo_eras() -> dict:
    try:
        raw = json.loads((LOGO_DIR / "eras" / "manifest.json").read_text())
    except (OSError, ValueError):
        return {}
    return {code: sorted((int(a), None if b is None else int(b), str(f)) for a, b, f in rows)
            for code, rows in raw.items()}


LOGO_ERAS = _logo_eras()


def logo(code: str, season=None) -> str | None:
    """Path of the club's logo in `season`, relative to Logos/, or None."""
    eras = LOGO_ERAS.get(str(code))
    if eras:
        if season is None:
            return eras[-1][2]
        pick = None
        for first, _last, name in eras:
            if first <= int(season):
                pick = name
        return pick
    name = TEAM_LOGO_MAP.get(str(code))
    return f"{name}-resizedmatplotlib.png" if name else None


def color(code: str) -> str:
    return TEAM_COLORS.get(str(code), "#64748b")
