"""What each FanGraphs column is: name, group, format, direction, how it adds up.

The builder stores this per column in the ``catalog`` table, so the site
never guesses. Columns not named here still get a group from their prefix
and a format from their name, so a new FanGraphs column shows up on its own.
"""
from __future__ import annotations

import re

# Identity and bookkeeping columns: not stats.
NOT_STATS = {
    "Name", "Team", "Season", "Bats", "Throws", "xMLBAMID", "AgeR", "SeasonMin", "SeasonMax",
    "PlayerNameRoute", "PlayerName", "positionDB", "position", "playerid", "TeamName",
    "TeamNameAbb", "teamid", "playerTeamId", "Q", "TG", "TPA", "TIP", "Dollars",
}

# Columns that add up over a season range or a roster (event counts and run
# values). Everything else is a rate and is averaged or rebuilt. From the Dash
# site's fangraphs_api.COUNTING_STATS, plus the pitching value splits.
COUNTING = frozenset({
    "G", "GS", "WAR", "bWAR", "WPA", "RE24", "REW", "Clutch", "Events", "Pitches", "Balls", "Strikes",
    "Barrels", "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "BB", "IBB", "SO", "HBP",
    "SF", "SH", "GDP", "SB", "CS", "TB", "IP", "W", "L", "SV", "BS", "HLD", "ER", "TBF", "GB",
    "FB", "LD", "IFFB", "IFH", "BU", "BUH", "Pull", "Cent", "Oppo", "Soft", "Med", "Hard",
    "bipCount", "HardHit", "Swords", "CompetitiveSwings", "PH", "wRAA", "wRC", "RAR", "WAROld",
    "UBR", "GDPRuns", "wBsR", "BaseRunning", "Batting", "Fielding", "Replacement", "Positional",
    "Offense", "Defense", "CFraming", "-WPA", "+WPA", "QS", "CG", "ShO", "WP", "BK", "SD", "MD",
    "RS", "Games", "Pulls", "Starting", "Relieving", "Start-IP", "Relief-IP", "RA9-Wins",
    "LOB-Wins", "BIP-Wins", "BS-Wins", "XBR", "BReview", "BOverturned", "PReview",
    "POverturned", "CReview", "COverturned", "AsCReview", "AsCOverturned", "wBReview",
    "wPReview", "wCReview", "wAsCReview", "Pos",
})
_PITCH_VALUE = re.compile(r"^(pfx|pi)?w[A-Z]{2}$|^w(FB|SL|CT|CB|CH|SF|KN)$")

# name, description (for titles and chart axes)
NAMES = {
    "G": "Games", "GS": "Games started", "PA": "Plate appearances", "AB": "At bats", "H": "Hits",
    "1B": "Singles", "2B": "Doubles", "3B": "Triples", "HR": "Home runs", "R": "Runs",
    "RBI": "Runs batted in", "BB": "Walks", "IBB": "Intentional walks", "SO": "Strikeouts",
    "HBP": "Hit by pitch", "SF": "Sacrifice flies", "SH": "Sacrifice bunts",
    "GDP": "Grounded into double plays", "SB": "Stolen bases", "CS": "Caught stealing",
    "AVG": "Batting average", "OBP": "On-base percentage", "SLG": "Slugging percentage",
    "OPS": "On-base plus slugging", "ISO": "Isolated power (SLG minus AVG)",
    "BABIP": "Batting average on balls in play", "BB%": "Walk rate", "K%": "Strikeout rate",
    "BB/K": "Walks per strikeout", "wOBA": "Weighted on-base average",
    "xwOBA": "Expected wOBA (Statcast)", "xAVG": "Expected batting average (Statcast)",
    "xSLG": "Expected slugging (Statcast)", "wRAA": "Weighted runs above average",
    "wRC": "Weighted runs created",
    "wRC+": "Weighted runs created plus (100 is league average, park-adjusted)",
    "Spd": "Speed score", "UBR": "Ultimate base running (runs)", "wSB": "Stolen base runs",
    "wBsR": "Base running runs", "GDPRuns": "Double-play avoidance runs", "WAR": "fWAR: FanGraphs wins above replacement (pitchers from FIP)",
    "bWAR": "bWAR: Baseball-Reference wins above replacement (pitchers from runs allowed)",
    "RAR": "Runs above replacement", "Batting": "Batting runs", "BaseRunning": "Base running runs",
    "Fielding": "Fielding runs", "Positional": "Positional adjustment (runs)",
    "Offense": "Offensive runs above average", "Defense": "Defensive runs above average",
    "Replacement": "Replacement-level runs", "wLeague": "League adjustment (runs)",
    "CFraming": "Catcher framing runs", "WPA": "Win probability added", "-WPA": "Negative WPA",
    "+WPA": "Positive WPA", "RE24": "Run expectancy over the 24 base-out states",
    "REW": "Run expectancy wins", "pLI": "Average leverage index", "phLI": "Leverage when pinch hitting",
    "WPA/LI": "Context-neutral wins", "Clutch": "Clutch score",
    "GB/FB": "Ground balls per fly ball", "LD%": "Line-drive rate", "GB%": "Ground-ball rate",
    "FB%": "Fly-ball rate", "IFFB%": "Infield fly-ball rate", "HR/FB": "Home runs per fly ball",
    "IFH%": "Infield-hit rate", "BUH%": "Bunt-hit rate", "TTO%": "Three true outcomes rate (BB, K, HR)",
    "Pull%": "Pull rate", "Cent%": "Center rate", "Oppo%": "Opposite-field rate",
    "Soft%": "Soft-contact rate", "Med%": "Medium-contact rate", "Hard%": "Hard-contact rate",
    "O-Swing%": "Swing rate at pitches outside the zone", "Z-Swing%": "Swing rate at pitches in the zone",
    "Swing%": "Swing rate", "O-Contact%": "Contact rate on swings outside the zone",
    "Z-Contact%": "Contact rate on swings in the zone", "Contact%": "Contact rate",
    "Zone%": "Share of pitches in the zone", "F-Strike%": "First-pitch strike rate",
    "SwStr%": "Swinging-strike rate", "CStr%": "Called-strike rate",
    "C+SwStr%": "Called plus swinging strike rate", "EV": "Average exit velocity (mph)",
    "LA": "Average launch angle (degrees)", "Barrels": "Barrels", "Barrel%": "Barrel rate",
    "maxEV": "Hardest-hit ball (mph)", "HardHit": "Hard-hit balls (95+ mph)",
    "HardHit%": "Hard-hit rate (95+ mph)", "EV90": "90th-percentile exit velocity (mph)",
    "Events": "Batted-ball events (Statcast)", "AvgBatSpeed": "Average bat speed (mph)",
    "FastSwing%": "Fast-swing rate (75+ mph)", "SwingLength": "Swing length (feet)",
    "SquaredUpContact%": "Squared-up rate per contact", "SquaredUpSwing%": "Squared-up rate per swing",
    "BlastContact%": "Blast rate per contact", "BlastSwing%": "Blast rate per swing",
    "Age": "Age", "W": "Wins", "L": "Losses", "ERA": "Earned run average", "QS": "Quality starts",
    "CG": "Complete games", "ShO": "Shutouts", "SV": "Saves", "BS": "Blown saves", "HLD": "Holds",
    "IP": "Innings pitched", "TBF": "Batters faced", "ER": "Earned runs", "WP": "Wild pitches",
    "BK": "Balks", "K/9": "Strikeouts per 9 innings", "BB/9": "Walks per 9 innings",
    "K/BB": "Strikeouts per walk", "H/9": "Hits per 9 innings", "HR/9": "Home runs per 9 innings",
    "WHIP": "Walks plus hits per inning", "LOB%": "Left-on-base rate",
    "FIP": "Fielding independent pitching", "xFIP": "Expected FIP (league-average HR/FB)",
    "SIERA": "Skill-interactive ERA", "kwERA": "Strikeout-walk ERA", "tERA": "True ERA",
    "xERA": "Expected ERA (Statcast)", "ERA-": "ERA minus (100 is league average, lower is better)",
    "FIP-": "FIP minus (100 is league average, lower is better)",
    "xFIP-": "xFIP minus (100 is league average, lower is better)", "K-BB%": "Strikeout rate minus walk rate",
    "E-F": "ERA minus FIP", "RS": "Run support", "RS/9": "Run support per 9 innings",
    "RA9-Wins": "FanGraphs WAR from runs allowed instead of FIP (RA9-WAR)", "LOB-Wins": "Strand-rate wins",
    "BIP-Wins": "Balls-in-play wins", "BS-Wins": "Sequencing wins", "Starting": "Value as a starter (runs)",
    "Relieving": "Value as a reliever (runs)", "Start-IP": "Innings as a starter",
    "Relief-IP": "Innings as a reliever", "gmLI": "Leverage entering games", "inLI": "Leverage entering innings",
    "exLI": "Leverage when exiting", "SD": "Shutdowns", "MD": "Meltdowns", "FBv": "Fastball velocity (mph)",
    "SLv": "Slider velocity (mph)", "CTv": "Cutter velocity (mph)", "CBv": "Curveball velocity (mph)",
    "CHv": "Changeup velocity (mph)", "SFv": "Splitter velocity (mph)", "KNv": "Knuckleball velocity (mph)",
    "FB%1": "Fastball rate", "SL%": "Slider rate", "CT%": "Cutter rate", "CB%": "Curveball rate",
    "CH%": "Changeup rate", "SF%": "Splitter rate", "KN%": "Knuckleball rate",
    "wFB": "Fastball runs", "wSL": "Slider runs", "wCT": "Cutter runs", "wCB": "Curveball runs",
    "wCH": "Changeup runs", "wSF": "Splitter runs", "wKN": "Knuckleball runs",
    "wFB/C": "Fastball runs per 100", "wSL/C": "Slider runs per 100", "wCT/C": "Cutter runs per 100",
    "wCB/C": "Curveball runs per 100", "wCH/C": "Changeup runs per 100", "wSF/C": "Splitter runs per 100",
    "wKN/C": "Knuckleball runs per 100", "pb_overall": "PitchingBot overall grade",
    "pb_stuff": "PitchingBot stuff grade", "pb_command": "PitchingBot command grade",
    "pb_ERA": "PitchingBot ERA", "pb_xRV100": "PitchingBot expected runs per 100 pitches",
    "Pitches": "Pitches", "Balls": "Balls", "Strikes": "Strikes", "Pos": "Positional adjustment (runs)",
    "GB": "Ground balls", "FB": "Fly balls", "LD": "Line drives", "IFFB": "Infield fly balls",
    "IFH": "Infield hits", "BU": "Bunts", "BUH": "Bunt hits",
}

# Display groups, in menu order. Table modes on the Players and Teams pages use
# the "columns" lists; the chart menu lists every stat under its group.
BAT_GROUPS = [
    ("standard", "Standard", ["G", "PA", "AB", "H", "2B", "3B", "HR", "R", "RBI", "BB", "SO",
                              "SB", "CS", "AVG", "OBP", "SLG", "OPS", "wRC+", "WAR", "bWAR"]),
    ("advanced", "Advanced", ["PA", "BB%", "K%", "BB/K", "ISO", "BABIP", "AVG", "OBP", "SLG",
                              "wOBA", "xwOBA", "wRC+", "Spd", "wBsR"]),
    ("value", "Value", ["PA", "Batting", "BaseRunning", "Fielding", "Positional", "Offense",
                        "Defense", "RAR", "WAR", "bWAR", "WPA", "RE24", "Clutch"]),
    ("battedball", "Batted ball", ["PA", "GB/FB", "LD%", "GB%", "FB%", "IFFB%", "HR/FB", "Pull%",
                                   "Cent%", "Oppo%", "Soft%", "Med%", "Hard%"]),
    ("discipline", "Plate discipline", ["PA", "O-Swing%", "Z-Swing%", "Swing%", "O-Contact%",
                                        "Z-Contact%", "Contact%", "Zone%", "F-Strike%", "SwStr%",
                                        "CStr%"]),
    ("statcast", "Statcast", ["PA", "Events", "EV", "EV90", "maxEV", "LA", "Barrel%", "HardHit%",
                              "xAVG", "xSLG", "xwOBA", "AvgBatSpeed", "SquaredUpSwing%"]),
]
PIT_GROUPS = [
    ("standard", "Standard", ["W", "L", "ERA", "G", "GS", "SV", "HLD", "IP", "H", "R", "ER",
                              "HR", "BB", "SO", "WHIP", "FIP", "WAR", "bWAR"]),
    ("advanced", "Advanced", ["IP", "K/9", "BB/9", "HR/9", "K%", "BB%", "K-BB%", "AVG", "BABIP",
                              "LOB%", "ERA-", "FIP-", "FIP", "xFIP", "SIERA"]),
    ("value", "Value", ["IP", "RA9-Wins", "LOB-Wins", "BIP-Wins", "RAR", "WAR", "bWAR", "WPA", "RE24",
                        "gmLI", "SD", "MD"]),
    ("battedball", "Batted ball", ["IP", "GB/FB", "LD%", "GB%", "FB%", "IFFB%", "HR/FB",
                                   "Pull%", "Cent%", "Oppo%", "Soft%", "Med%", "Hard%"]),
    ("discipline", "Plate discipline", ["IP", "O-Swing%", "Z-Swing%", "Swing%", "O-Contact%",
                                        "Z-Contact%", "Contact%", "Zone%", "F-Strike%", "SwStr%",
                                        "CStr%"]),
    ("statcast", "Statcast", ["IP", "Events", "EV", "maxEV", "LA", "Barrel%", "HardHit%", "xERA",
                              "FBv", "pb_stuff", "pb_command", "pb_overall"]),
]

_LOWER_ALWAYS = frozenset({
    "ERA", "FIP", "xFIP", "SIERA", "WHIP", "BB/9", "HR/9", "H/9", "R/9", "ERA-", "FIP-",
    "xFIP-", "tERA", "kwERA", "xERA", "pb_ERA", "GDP", "CS", "E", "BK", "WP", "BS", "L", "MD",
})
_LOWER_FOR_PITCHERS = frozenset({
    "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "wOBA", "xwOBA", "wRC", "wRC+", "wRAA", "BB%",
    "HR", "R", "ER", "H", "BB", "1B", "2B", "3B", "RBI", "TB", "HR/FB", "Barrel%", "HardHit%",
    "EV", "EV90", "maxEV", "Barrels", "HardHit", "LD%", "HBP", "Hard%", "xAVG", "xSLG", "IBB",
    "Contact%", "Z-Contact%", "O-Contact%",
})
_LOWER_FOR_BATTERS = frozenset({"K%", "SO", "SwStr%", "O-Swing%", "CStr%", "C+SwStr%", "Soft%",
                                "IFFB%", "GDP"})

_DEC3 = frozenset({"AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "wOBA", "xwOBA", "xAVG", "xSLG"})
_DEC1 = frozenset({
    "WAR", "bWAR", "RAR", "Off", "Def", "BsR", "Batting", "Fielding", "Positional", "Replacement",
    "Offense", "Defense", "BaseRunning", "wRAA", "UBR", "wSB", "wGDP", "Spd", "EV", "EV90", "LA",
    "maxEV", "IP", "CFraming", "wBsR", "GDPRuns", "wLeague", "RA9-Wins", "LOB-Wins", "BIP-Wins",
    "BS-Wins", "Starting", "Relieving", "Start-IP", "Relief-IP", "AvgBatSpeed", "SwingLength",
    "FBv", "SLv", "CTv", "CBv", "CHv", "SFv", "KNv", "Pos", "Age", "pb_stuff", "pb_command",
    "pb_overall",
})
_KEEP_DECIMALS = {"WPA", "-WPA", "+WPA", "RE24", "REW", "Clutch", "wFB", "wSL", "wCT", "wCB",
                  "wCH", "wSF", "wKN"}


def is_counting(stat: str) -> bool:
    return stat in COUNTING or bool(_PITCH_VALUE.match(stat))


def fmt(stat: str) -> str:
    """'pct1' (fraction shown as a 1-decimal percent), 'avg' (.263), 'd0'..'d2'."""
    if stat.endswith(("+", "-")) and stat not in ("+WPA", "-WPA"):
        return "d0"                     # index stats: wRC+, ERA-, K%+
    if "%" in stat or stat == "HR/FB":
        return "pct1"
    if stat in _DEC3:
        return "avg"
    if stat in _DEC1:
        return "d1"
    if is_counting(stat) and stat not in _KEEP_DECIMALS and not _PITCH_VALUE.match(stat):
        return "d0"
    if stat in ("Events", "Barrels", "HardHit"):
        return "d0"
    return "d2"


def lower_is_better(stat: str, pitching: bool) -> bool:
    if stat in _LOWER_ALWAYS:
        return True
    return stat in (_LOWER_FOR_PITCHERS if pitching else _LOWER_FOR_BATTERS)


def weight(stat: str, pitching: bool) -> str:
    """What a rate is averaged by over a range of seasons or a roster."""
    if stat in ("EV", "LA", "Barrel%", "HardHit%", "EV90", "xAVG", "xSLG", "xwOBA", "xERA"):
        return "Events"
    if (stat.startswith(("pfx", "pi", "sc", "sp_", "pb_")) or stat.endswith(("v", "/C"))
            or stat in ("O-Swing%", "Z-Swing%", "Swing%", "O-Contact%", "Z-Contact%", "Contact%",
                        "Zone%", "F-Strike%", "SwStr%", "CStr%", "C+SwStr%", "FB%1", "SL%", "CT%",
                        "CB%", "CH%", "SF%", "KN%", "XX%", "PO%", "AvgBatSpeed", "FastSwing%",
                        "SwingLength", "SquaredUpContact%", "SquaredUpSwing%", "BlastContact%",
                        "BlastSwing%", "Tilt", "AttackAngle", "AttackDirection", "IdealAttackAngle%")):
        return "Pitches"
    return "IP" if pitching else "PA"


def group(stat: str, pitching: bool) -> str:
    for key, _title, columns in (PIT_GROUPS if pitching else BAT_GROUPS):
        if stat in columns and stat not in ("PA", "IP"):
            return key
    if stat.startswith("pfx"):
        return "pitchfx"
    if stat.startswith("pi"):
        return "pitchinfo"
    if stat.startswith(("sp_", "pb_")):
        return "stuff"
    if stat.startswith("sc") or stat in ("Tilt", "AttackAngle", "AttackDirection", "IdealAttackAngle%",
                                         "DepthInBox", "DistanceOffPlate", "FastSwing%", "SwingLength",
                                         "SquaredUpContact%", "BlastContact%", "BlastSwing%",
                                         "Barrels", "HardHit", "Swords", "CompetitiveSwings"):
        return "statcast"
    if re.search(r"(Review|Overturned|Correct%)$", stat) or stat in (
            "PPTV", "CPTV", "BPTV", "DSV", "DGV", "BTV", "rPPTV", "rCPTV", "rBPTV", "rDSV", "rDGV",
            "rBTV", "EBV", "ESV", "rFTeamV", "rBTeamV", "rTV"):
        return "umpire"
    if stat.endswith("+") or stat.endswith("-"):
        return "plus"
    if stat in ("FB%1", "SL%", "CT%", "CB%", "CH%", "SF%", "KN%", "XX%", "PO%") or stat.endswith(("v", "/C")) \
            or _PITCH_VALUE.match(stat):
        return "pitchtypes"
    if stat in ("Pull", "Cent", "Oppo", "Soft", "Med", "Hard", "GB", "FB", "LD", "IFFB", "IFH", "BU",
                "BUH", "bipCount", "IFH%", "BUH%", "TTO%", "Pulls"):
        return "battedball"
    if stat in ("WPA", "-WPA", "+WPA", "RE24", "REW", "pLI", "phLI", "PH", "WPA/LI", "Clutch",
                "gmLI", "inLI", "exLI", "Starting", "Relieving", "Start-IP", "Relief-IP", "WAROld",
                "Dollars", "CFraming", "wLeague", "Replacement", "UBR", "GDPRuns", "XBR", "Games"):
        return "value"
    return "standard" if is_counting(stat) else "advanced"


GROUP_TITLES = {
    "standard": "Standard", "advanced": "Advanced", "value": "Value", "battedball": "Batted ball",
    "discipline": "Plate discipline", "statcast": "Statcast", "plus": "Plus stats (100 = average)",
    "pitchtypes": "Pitch types", "stuff": "Stuff+ and PitchingBot", "pitchfx": "PITCHf/x",
    "pitchinfo": "Pitch Info", "umpire": "Umpires and replay",
}
GROUP_ORDER = list(GROUP_TITLES)


# Column heads that differ from the stat key. The key stays "WAR" so old links
# keep working; on screen it is always fWAR, next to Baseball-Reference's bWAR.
HEADS = {"WAR": "fWAR"}


def head(stat: str) -> str:
    return HEADS.get(stat, stat)


def describe(stat: str) -> str:
    if stat in NAMES:
        return NAMES[stat]
    if stat.endswith("+") and stat[:-1] in NAMES:
        return f"{NAMES[stat[:-1]]}, indexed (100 is league average)"
    return stat
