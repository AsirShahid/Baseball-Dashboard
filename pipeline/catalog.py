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
    "G", "GS", "WAR", "bWAR", "ERlg", "bER", "TOBlg", "TBlg", "bTOB", "bTB",
    # Baseball Savant counts (pipeline/savant.PARTS)
    "svPA", "svAB", "svPit", "svIZ", "svOZ", "svIZSw", "svOZSw", "svIZCon", "svOZCon", "svWhiff", "svEdge",
    "svMB", "svMBSw", "svBBE", "svSweet", "svXWcon", "svXH", "svXTB", "svXW", "svSpW", "svSpSum",
    "WPA", "RE24", "REW", "Clutch", "Events", "Pitches", "Balls", "Strikes",
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
    "xERA": "Expected ERA (Statcast)", "ERA-": "ERA minus: ERA adjusted for park and league (100 is league average, lower is better)",
    "FIP-": "FIP minus: FIP adjusted for park and league (100 is league average, lower is better)",
    "ERA+": "ERA+: Baseball-Reference's ERA adjusted for park and league (100 is league average, higher is better)",
    "OPS+": "OPS+: Baseball-Reference's OPS adjusted for park and league (100 is league average)",
    "Barrel/PA": "Barrels per plate appearance (Statcast)",
    "Sweet-Spot%": "Launch angle sweet-spot rate: batted balls at 8 to 32 degrees (Baseball Savant)",
    "xwOBAcon": "Expected wOBA on contact: batted balls only (Baseball Savant)",
    "svZone%": "Zone%: pitches in the strike zone, Statcast's zone (Baseball Savant)",
    "svZ-Swing%": "Zone swing rate: swings at pitches in the zone (Baseball Savant)",
    "svZ-Contact%": "Zone contact rate: contact on swings at pitches in the zone (Baseball Savant)",
    "Chase%": "Chase rate: swings at pitches outside the zone (Baseball Savant)",
    "ChaseContact%": "Chase contact rate: contact on swings outside the zone (Baseball Savant)",
    "Edge%": "Edge rate: pitches on the edges of the zone (Baseball Savant)",
    "svSwing%": "Swing rate: swings per pitch (Baseball Savant)",
    "Whiff%": "Whiff rate: misses per swing (Baseball Savant)",
    "Meatball%": "Meatball rate: pitches down the middle (Baseball Savant)",
    "MeatballSwing%": "Meatball swing rate: swings at pitches down the middle (Baseball Savant)",
    "Sprint": "Sprint speed: feet per second in the fastest one-second window of a run (Baseball Savant)",
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
                              "SB", "CS", "AVG", "OBP", "SLG", "OPS", "OPS+", "wRC+", "WAR", "bWAR"]),
    ("advanced", "Advanced", ["PA", "BB%", "K%", "BB/K", "ISO", "BABIP", "AVG", "OBP", "SLG",
                              "wOBA", "xwOBA", "OPS+", "wRC+", "Spd", "wBsR"]),
    ("value", "Value", ["PA", "Batting", "BaseRunning", "Fielding", "Positional", "Offense",
                        "Defense", "RAR", "WAR", "bWAR", "WPA", "RE24", "Clutch"]),
    ("battedball", "Batted ball", ["PA", "GB/FB", "LD%", "GB%", "FB%", "IFFB%", "HR/FB", "Pull%",
                                   "Cent%", "Oppo%", "Soft%", "Med%", "Hard%"]),
    ("discipline", "Plate discipline", ["PA", "O-Swing%", "Z-Swing%", "Swing%", "O-Contact%",
                                        "Z-Contact%", "Contact%", "Zone%", "F-Strike%", "SwStr%",
                                        "CStr%"]),
    ("statcast", "Statcast", ["PA", "Events", "Barrel%", "Barrel/PA", "EV", "EV90", "maxEV", "LA",
                              "Sweet-Spot%", "HardHit%", "xAVG", "xSLG", "xwOBA", "xwOBAcon",
                              "AvgBatSpeed", "SquaredUpSwing%", "Sprint"]),
    ("savant", "Savant discipline", ["PA", "Pitches", "svZone%", "svZ-Swing%", "svZ-Contact%", "Chase%",
                                     "ChaseContact%", "Edge%", "svSwing%", "Whiff%", "Meatball%",
                                     "MeatballSwing%"]),
]
PIT_GROUPS = [
    ("standard", "Standard", ["W", "L", "ERA", "ERA+", "G", "GS", "SV", "HLD", "IP", "H", "R", "ER",
                              "HR", "BB", "SO", "WHIP", "FIP", "WAR", "bWAR"]),
    ("advanced", "Advanced", ["IP", "K/9", "BB/9", "HR/9", "K%", "BB%", "K-BB%", "AVG", "BABIP",
                              "LOB%", "ERA+", "ERA-", "FIP-", "FIP", "xFIP", "SIERA"]),
    ("value", "Value", ["IP", "RA9-Wins", "LOB-Wins", "BIP-Wins", "RAR", "WAR", "bWAR", "WPA", "RE24",
                        "gmLI", "SD", "MD"]),
    ("battedball", "Batted ball", ["IP", "GB/FB", "LD%", "GB%", "FB%", "IFFB%", "HR/FB",
                                   "Pull%", "Cent%", "Oppo%", "Soft%", "Med%", "Hard%"]),
    ("discipline", "Plate discipline", ["IP", "O-Swing%", "Z-Swing%", "Swing%", "O-Contact%",
                                        "Z-Contact%", "Contact%", "Zone%", "F-Strike%", "SwStr%",
                                        "CStr%"]),
    ("statcast", "Statcast", ["IP", "Events", "Barrel%", "Barrel/PA", "EV", "maxEV", "LA", "Sweet-Spot%",
                              "HardHit%", "xAVG", "xSLG", "xwOBA", "xwOBAcon", "xERA", "FBv",
                              "pb_stuff", "pb_command", "pb_overall"]),
    ("savant", "Savant discipline", ["IP", "Pitches", "svZone%", "svZ-Swing%", "svZ-Contact%", "Chase%",
                                     "ChaseContact%", "Edge%", "svSwing%", "Whiff%", "Meatball%",
                                     "MeatballSwing%"]),
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
    "Barrel/PA", "Sweet-Spot%", "xwOBAcon", "svZ-Contact%", "ChaseContact%", "Meatball%", "MeatballSwing%",
})
_LOWER_FOR_BATTERS = frozenset({"K%", "SO", "SwStr%", "O-Swing%", "CStr%", "C+SwStr%", "Soft%",
                                "IFFB%", "GDP", "Chase%", "Whiff%"})

_DEC3 = frozenset({"AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "wOBA", "xwOBA", "xAVG", "xSLG", "xwOBAcon"})
_DEC1 = frozenset({
    "WAR", "bWAR", "RAR", "Off", "Def", "BsR", "Sprint", "Batting", "Fielding", "Positional", "Replacement",
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
    if "%" in stat or stat in ("HR/FB", "Barrel/PA"):
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
    if stat in ("EV", "LA", "Barrel%", "HardHit%", "EV90", "xAVG", "xSLG", "xwOBA", "xERA", "Sweet-Spot%",
                "xwOBAcon"):
        return "Events"
    if stat in ("svZone%", "svZ-Swing%", "svZ-Contact%", "Chase%", "ChaseContact%", "Edge%", "svSwing%",
                "Whiff%", "Meatball%", "MeatballSwing%"):
        return "Pitches"
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
    "discipline": "Plate discipline", "statcast": "Statcast", "savant": "Savant discipline",
    "plus": "Plus stats (100 = average)",
    "pitchtypes": "Pitch types", "stuff": "Stuff+ and PitchingBot", "pitchfx": "PITCHf/x",
    "pitchinfo": "Pitch Info", "umpire": "Umpires and replay",
}
GROUP_ORDER = list(GROUP_TITLES)


# Column heads that differ from the stat key. The key stays "WAR" so old links
# keep working; on screen it is always fWAR, next to Baseball-Reference's bWAR.
HEADS = {"WAR": "fWAR", "svZone%": "Zone%", "svZ-Swing%": "Z-Swing%", "svZ-Contact%": "Z-Contact%",
         "ChaseContact%": "Chase Con%", "svSwing%": "Swing%", "MeatballSwing%": "Meatball Sw%"}


def head(stat: str) -> str:
    return HEADS.get(stat, stat)


# ---------- descriptions for the columns NAMES does not list ----------
# Every FanGraphs column needs words, not a repeat of its code. The stat picker
# shows one nowrap line that ends in an ellipsis, so each text opens with the
# meaning and keeps source and caveats for the tail. The pitch-type families
# (pfx, pi, sp_, pb_) and the Statcast zone columns are generated from their code
# patterns; one-offs are in EXTRA. Meanings were checked against FanGraphs' library
# and blog posts, MLB's Statcast glossary and the stored data (CU% = CUO% + CV%,
# SL% = SLO% + ST%, scH + scS + scC + scW = 100%, rTV = rBTeamV + rFTeamV).

# Pitch codes: (label, what a pitch of that type is called in "share of ..."). pfx =
# MLB's pitch classification (the PITCHf/x-era codes); pi = Pitch Info's.
PFX_TYPES = {
    "FA": ("Four-seam fastball", "four-seam fastballs"), "SI": ("Sinker", "sinkers"),
    "FC": ("Cutter", "cutters"), "FS": ("Splitter", "splitters"), "FO": ("Forkball", "forkballs"),
    "SL": ("Slider incl. sweepers", "sliders and sweepers"),
    "SLO": ("Slider excl. sweepers", "sliders other than sweepers"),
    "ST": ("Sweeper", "sweepers"),
    "CU": ("Curveball incl. slurves", "curveballs and slurves"),
    "CUO": ("Curveball excl. slurves", "curveballs other than slurves"),
    "CV": ("Slurve", "slurves"),
    "KC": ("Knuckle curve", "knuckle curves"), "CH": ("Changeup", "changeups"),
    "EP": ("Eephus", "eephus pitches"), "SC": ("Screwball", "screwballs"),
    "KN": ("Knuckleball", "knuckleballs"), "UN": ("Unidentified type", "unidentified pitches"),
}
PI_TYPES = {
    "FA": ("Fastball", "fastballs"), "SI": ("Sinker", "sinkers"), "FC": ("Cutter", "cutters"),
    "SL": ("Slider", "sliders"), "CU": ("Curveball", "curveballs"),
    "CS": ("Slow curve", "slow curves"), "SB": ("Screwball", "screwballs"),
    "FS": ("Splitter", "splitters"), "CH": ("Changeup", "changeups"),
    "KN": ("Knuckleball", "knuckleballs"), "XX": ("Unidentified type", "unidentified pitches"),
}
# Stuff+ / PitchingBot pitch codes (FF is the four-seamer).
SP_TYPES = {
    "FF": "Four-seam fastball", "SI": "Sinker", "FC": "Cutter", "FS": "Splitter", "FO": "Forkball",
    "SL": "Slider", "CU": "Curveball", "KC": "Knuckle curve", "CH": "Changeup",
}
_PFX_DISC = {
    "Swing%": "Swing rate: share of pitches swung at",
    "Contact%": "Contact rate: share of swings that made contact",
    "Zone%": "Zone rate: share of pitches in the strike zone",
    "O-Swing%": "Swing rate at pitches outside the zone",
    "Z-Swing%": "Swing rate at pitches in the zone",
    "O-Contact%": "Contact rate on swings outside the zone",
    "Z-Contact%": "Contact rate on swings in the zone",
}
_SRC = {"pfx": "PITCHf/x", "pi": "Pitch Info"}

# Statcast attack zones, from the pitch's location.
_SC_ZONES = {
    "H": ("Heart", "down the middle of the zone"),
    "S": ("Shadow", "on the edges of the zone, inside or out"),
    "SI": ("Shadow-in", "on the inside edge of the strike zone"),
    "SO": ("Shadow-out", "just off the edge of the strike zone"),
    "C": ("Chase", "off the plate, beyond the shadow"),
    "W": ("Waste", "far outside the zone"),
    "Z": ("In-zone", "inside the strike zone"),
    "O": ("Out-of-zone", "outside the strike zone"),
}

EXTRA = {
    # Rule violations (FanGraphs tracks the pitch clock and the other 2023 rule changes).
    "PPTV": "Pitcher pitch timer violations: too slow to start the delivery (automatic ball)",
    "CPTV": "Catcher pitch timer violations: catcher not set in time (automatic ball)",
    "BPTV": "Batter pitch timer violations: not ready in the box in time (automatic strike)",
    "BTV": "Batter timeout violations: too many timeouts in a plate appearance (automatic strike)",
    "DGV": "Disengagement violations: too many pickoff throws or step-offs (a balk)",
    "DSV": "Defensive shift violations: fielders illegally positioned for the pitch",
    "EBV": "Extra balls: balls awarded by violations (pitcher and catcher timer, shift); FanGraphs: Total Balls by Violation",
    "ESV": "Extra strikes: strikes awarded by violations (batter timer and timeout); FanGraphs: Total Strikes by Violation",
    "rPPTV": "Pitcher pitch timer violation runs: run value to this player, positive helps him (FanGraphs: wPPTV)",
    "rCPTV": "Catcher pitch timer violation runs: run value to this player, positive helps him (FanGraphs: wCPTV)",
    "rBPTV": "Batter pitch timer violation runs: run value to this player, positive helps him (FanGraphs: wBPTV)",
    "rBTV": "Batter timeout violation runs: run value to this player, positive helps him (FanGraphs: wBTV)",
    "rDGV": "Disengagement violation runs: run value to this player, positive helps him (FanGraphs: wDGV)",
    "rDSV": "Defensive shift violation runs: run value to this player, positive helps him (FanGraphs: wDSV)",
    "rFTeamV": "Fielding-team violation runs: pitcher and catcher timer, disengagement and shift, valued for this player (FanGraphs: wTeamV on pitchers, wOppTeamV on hitters)",
    "rBTeamV": "Batting-team violation runs: batter timer and timeout violations, valued for this player (FanGraphs: wOppTeamV on pitchers, wTeamV on hitters)",
    "rTV": "Total violation runs: fielding-team plus batting-team violations, valued for this player (FanGraphs: wNetPitV, wNetBatV)",
    # 2026 ABS (automated ball-strike) challenges.
    "BReview": "Batter ABS challenges: ball-strike reviews initiated by the batter (FanGraphs: B-Rvw)",
    "PReview": "Pitcher ABS challenges: ball-strike reviews initiated by the pitcher (FanGraphs: P-Rvw)",
    "CReview": "Catcher ABS challenges while this player bats: reviews initiated by the catcher (FanGraphs: C-Rvw)",
    "AsCReview": "ABS challenges this player made as a catcher (FanGraphs: AsC-Rvw)",
    "BOverturned": "Batter ABS challenges that overturned the call (FanGraphs: B-OvrTrn)",
    "POverturned": "Pitcher ABS challenges that overturned the call (FanGraphs: P-OvrTrn)",
    "COverturned": "Catcher ABS challenges that overturned the call, while this player bats (FanGraphs: C-OvrTrn)",
    "AsCOverturned": "ABS challenges this player won as a catcher (FanGraphs: AsC-Ovrtrn)",
    "BCorrect%": "Batter ABS challenge success rate: share that overturned the call",
    "PCorrect%": "Pitcher ABS challenge success rate: share that overturned the call",
    "CCorrect%": "Catcher ABS challenge success rate: share that overturned the call",
    "AsCCorrect%": "ABS challenge success rate while catching: share that overturned the call",
    "wBReview": "Batter challenge runs: run value of batter reviews, original call vs overturned call (FanGraphs: wB-Rvw)",
    "wPReview": "Pitcher challenge runs: run value of pitcher reviews, original call vs overturned call (FanGraphs: wP-Rvw)",
    "wCReview": "Catcher challenge runs while this player bats: run value of the catcher's reviews, negative if they cost him (FanGraphs: wC-Rvw)",
    "wAsCReview": "Challenge runs as a catcher: run value of his own reviews, original call vs overturned call (FanGraphs: wAsC-Rvw)",
    # Statcast bat tracking and positioning (MLB's Statcast glossary).
    "AttackAngle": "Attack angle: vertical angle of the bat's path at contact, in degrees (Statcast)",
    "AttackDirection": "Attack direction: horizontal angle of the bat's path at contact, degrees from straight to center (Statcast)",
    "IdealAttackAngle%": "Ideal attack angle rate: share of competitive swings at 5 to 20 degrees (Statcast)",
    "Tilt": "Swing tilt: vertical angle of the bat path vs the ground, degrees (0 flat, 90 vertical; Statcast)",
    "DepthInBox": "Depth in box: how far forward or back in the batter's box he stands, inches (Statcast)",
    "DistanceOffPlate": "Distance off plate: how far from the plate he stands, inches (Statcast)",
    "Swords": "Swords: awkward whiffs, slow incomplete swings by a fooled hitter (Statcast)",
    "CompetitiveSwings": "Competitive swings: his fastest 90% of swings plus 60+ mph swings with 90+ mph exit velocity (Statcast)",
    "Barrels": "Barrels: batted balls with the exit velocity and launch angle that usually give a .500 average and 1.500 slugging (Statcast)",
    # Batted-ball counts and rate variants.
    "Pull": "Pulled batted balls (count)", "Cent": "Batted balls hit to center (count)",
    "Oppo": "Batted balls hit to the opposite field (count)", "Soft": "Soft-contact batted balls (count)",
    "Med": "Medium-contact batted balls (count)", "Hard": "Hard-contact batted balls (count)",
    "bipCount": "Balls in play: the batted balls behind the batted-ball rates",
    "HRFB%+": "Home runs per fly ball, indexed to the league (100 is average)",
    "PO%": "Pitchout rate: share of pitches that were pitchouts",
    "XX%": "Unidentified-pitch rate: share of pitches with no pitch type",
    # Value, usage and bookkeeping columns.
    "Age": "Age during the season",
    "Pitches": "Pitches seen by a hitter or thrown by a pitcher",
    "Balls": "Pitches that were balls", "Strikes": "Pitches that were strikes (called, swinging, fouled or in play)",
    "PH": "Pinch-hit appearances",
    "XBR": "Extra-base running runs: run value of extra bases taken on hits (baserunning, from 2016)",
    "WAROld": "Old WAR: FanGraphs' previous WAR calculation, kept next to the current fWAR",
    "Games": "Games pitched: the sample behind gmLI (leverage entering games)",
    "Pulls": "Times pulled from a game: the sample behind exLI (leverage when exiting)",
    "pfxPace": "Pace: average seconds between pitches (PITCHf/x)",
    "piPace": "Pace: average seconds between pitches (Pitch Info)",
    # Stuff+ and PitchingBot (FanGraphs library: Stuff+, Location+, Pitching+ primer).
    "sp_stuff": "Stuff+: pitch quality from release point, velocity, movement and spin alone (100 is average)",
    "sp_location": "Location+: pitch quality from location, adjusted for count and pitch type (100 is average)",
    "sp_pitching": "Pitching+: Stuff+ and Location+ combined (100 is average)",
    "pb_overall": "PitchingBot overall grade: stuff and command together (20-80, 50 is average)",
    "pb_stuff": "PitchingBot stuff grade: movement and velocity of the pitch (20-80, 50 is average)",
    "pb_command": "PitchingBot command grade: where the pitch was placed (20-80, 50 is average)",
}


def _family(stat: str) -> str | None:
    """Words for the code-pattern columns: pitch types, Statcast zones, Stuff+."""
    m = re.fullmatch(r"(pfx|pi)(.+)", stat)
    if m:
        pre, rest = m.groups()
        src = _SRC[pre]
        types = PFX_TYPES if pre == "pfx" else PI_TYPES
        if rest in _PFX_DISC:
            return f"{_PFX_DISC[rest]} ({src})"
        t = r"(" + "|".join(sorted(types, key=len, reverse=True)) + r")"
        hit = re.fullmatch(t + r"(%|-X|-Z)", rest)
        if hit:
            code, suffix = hit.groups()
            label, many = types[code]
            if suffix == "%":
                return f"{label} usage: share of pitches that were {many} ({src})"
            if suffix == "-X":
                return f"{label} horizontal movement: inches of sideways break ({src})"
            return f"{label} vertical movement: inches of rise against a spinless pitch ({src})"
        hit = re.fullmatch(r"(aa|sp|v|w)" + t + r"(/C)?", rest)
        if hit:
            kind, code, per = hit.groups()
            label, many = types[code]
            if kind == "v":
                return f"{label} velocity: average speed in mph ({src})"
            if kind == "aa":
                return f"{label} arm angle: degrees at release, 0 sidearm to 90 overhead (from 2020)"
            if kind == "sp":
                return f"{label} spin rate: average rpm (MLB tracking)"
            if per:
                return f"{label} pitch value per 100: runs above average per 100 pitches ({src})"
            return f"{label} pitch value: runs above average on {many} ({src})"
        return None
    m = re.fullmatch(r"sc(H|SI|SO|S|C|W|Z|O)-(Zone%|Swing%|Contact%)", stat)
    if m:
        zone, metric = m.groups()
        title, area = _SC_ZONES[zone]
        if metric == "Zone%":
            return f"{title} rate: share of pitches thrown {area} (Statcast)"
        if metric == "Swing%":
            return f"{title} swing rate: swings at pitches {area} (Statcast)"
        return f"{title} contact rate: contact on swings at pitches {area} (Statcast)"
    m = re.fullmatch(r"sp_([slp])_(\w+)", stat)
    if m and m.group(2) in SP_TYPES:
        which = {"s": "Stuff+", "l": "Location+", "p": "Pitching+"}[m.group(1)]
        what = {"Stuff+": "physical quality of this pitch type", "Location+": "placement quality of this pitch type",
                "Pitching+": "Stuff+ and Location+ combined for this pitch type"}[which]
        return f"{SP_TYPES[m.group(2)]} {which}: {what} (100 is average)"
    m = re.fullmatch(r"pb_([sco])_(\w+)", stat)
    if m and m.group(2) in SP_TYPES:
        which = {"s": "stuff", "c": "command", "o": "overall"}[m.group(1)]
        return f"PitchingBot {SP_TYPES[m.group(2)].lower()} {which} grade (20-80, 50 is average)"
    return None


def describe(stat: str) -> str:
    """One line of words for a column. EXTRA outranks NAMES (it replaces the bare
    restatements such as "Barrels": "Barrels"); the code-pattern families come last."""
    if stat in EXTRA:
        return EXTRA[stat]
    if stat in NAMES:
        return NAMES[stat]
    words = _family(stat)
    if words:
        return words
    if stat.endswith("+") and stat[:-1] in NAMES:
        return f"{NAMES[stat[:-1]]}, indexed (100 is league average)"
    return stat
