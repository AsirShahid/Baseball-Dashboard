"""Build baseball.sqlite from the FanGraphs season CSVs.

  python -m pipeline.build --csv-root DIR --stints-root DIR --output DIR

Layout (column store: one compressed float32 array per season and stat, so a
chart or table reads only the columns it shows):

  rows(kind, season, i, pid, team, teamid, age, pos, tg)   one row per player or team season
  cols(kind, season, stat, data)                          zlib(float32[len(rows)]), NaN = missing
  catalog(kind, stat, ...)                                 what each stat is (see catalog.py)
  players(pid, name, key, ...), team_seasons(season, team, ...), meta(key, value)

kind: bat, pit (players), tbat, tpit (teams), sbat, spit (per-club rows of
traded players). Season 0 holds each player's career. IP is stored as true
innings (FanGraphs writes 177.2 for 177 2/3).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import logging
import os
import sqlite3
import time
import zlib
from pathlib import Path

import numpy as np

from . import aggregate, bwar, catalog, savant, teams
from .text import search_key

log = logging.getLogger("build")
SCHEMA_VERSION = 6
SOURCES = {
    "bat": "all_batting_stats", "pit": "all_pitching_stats",
    "tbat": "team_batting", "tpit": "team_pitching",
    "sbat": "stints_batting", "spit": "stints_pitching",
}
NOTATION_IP = ("IP", "Start-IP", "Relief-IP")
# Stored but not offered as stats: TG, ERA+'s parts (ERlg, bER) and the Baseball
# Savant counts its rates are rebuilt from.
INTERNAL = ("TG", "ERlg", "bER") + savant.PARTS


def pack(values: np.ndarray) -> bytes:
    return zlib.compress(np.asarray(values, dtype="<f4").tobytes(), 6)


def unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(zlib.decompress(blob), dtype="<f4")


def _float(text):
    if text is None or text == "":
        return np.nan
    try:
        return float(text)
    except ValueError:
        return None   # not numeric


def true_innings(values: np.ndarray) -> np.ndarray:
    whole = np.floor(values)
    return whole + np.round((values - whole) * 10) / 3


def read_season(path: Path, kind: str):
    """(identity rows, {stat: float64 array}) for one season file."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as handle:
        records = list(csv.DictReader(handle))
    if not records:
        return [], {}
    pitching = kind in ("pit", "tpit", "spit")
    ident = []
    for r in records:
        team = teams.recode(r.get("Team"), r.get("teamid"))
        row = {"team": team, "teamid": _int(r.get("teamid"))}
        if kind not in ("tbat", "tpit"):
            row.update(pid=_int(r.get("playerid")), name=(r.get("PlayerName") or r.get("Name") or "").strip(),
                       age=_int(r.get("Age")), pos=(r.get("position") or "").strip() or None,
                       hand=(r.get("Throws") if pitching else r.get("Bats")) or None,
                       mlbam=_int(r.get("xMLBAMID")), tg=_int(r.get("TG")))
        ident.append(row)
    columns = {}
    for key in records[0].keys():
        if key in catalog.NOT_STATS and key not in INTERNAL:
            continue
        if key.startswith("Unnamed") or not key:
            continue
        values = np.empty(len(records))
        numeric = True
        for i, r in enumerate(records):
            v = _float(r.get(key))
            if v is None:
                numeric = False
                break
            values[i] = v
        if not numeric:
            continue
        if key in NOTATION_IP:
            values = true_innings(values)
        columns[key] = values.astype(np.float32)
    return ident, columns


def _int(text):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


_REBUILD_PARTS = {
    False: ("PA", "AB", "H", "1B", "2B", "3B", "HR", "BB", "HBP", "SF", "SO",
            "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "K%", "BB%", "BB/K", "Barrels", "Barrel/PA")
    + savant.PARTS + savant.SHOWN + savant.PITCHER_SHOWN,
    True: ("IP", "TBF", "ER", "H", "HR", "BB", "SO", "ERA", "WHIP", "K/9", "BB/9", "HR/9", "H/9",
           "K%", "BB%", "K-BB%", "K/BB", "ERlg", "bER", "ERA+", "Barrels", "Barrel/PA")
    + savant.PARTS + savant.SHOWN + savant.PITCHER_SHOWN,
}


def _careers(con, kind: str, parts, stats) -> None:
    """Season-0 rows: each player's whole career, rolled up like any span."""
    pitching = kind == "pit"
    pids = np.concatenate([p for _s, p in parts])

    def load(stat):
        chunks = []
        for season, p in parts:
            blob = con.execute("SELECT data FROM cols WHERE kind=? AND season=? AND stat=?",
                               (kind, season, stat)).fetchone()
            chunks.append(unpack(blob[0]).astype(np.float64) if blob else np.full(len(p), np.nan))
        return np.concatenate(chunks)

    weights = {s: load(s) for s in ("PA", "IP", "TBF", "Events", "Pitches")}
    uniq, _first, _ = aggregate.group_rows(pids, {}, pitching)
    con.executemany("INSERT INTO rows VALUES (?,?,?,?,?,?,?,?,?)", [
        (kind, 0, i, int(pid), None, None, None, None, None) for i, pid in enumerate(uniq)])
    for stat in stats:
        cols = dict(weights)
        if stat not in cols:
            cols[stat] = load(stat)
        _u, _f, agg = aggregate.group_rows(pids, cols, pitching)
        values = agg.get(stat)
        if values is not None and not np.isnan(values).all():
            con.execute("INSERT INTO cols VALUES (?,?,?,?)", (kind, 0, stat, pack(values)))
    # Ratios rebuilt from the summed parts replace the weighted averages.
    cols = {s: (weights[s] if s in weights else load(s)) for s in _REBUILD_PARTS[pitching]
            if s in stats or s in INTERNAL}
    _u, _f, agg = aggregate.group_rows(pids, cols, pitching)
    for stat, values in agg.items():
        if stat in cols and not np.isnan(values).all():
            con.execute("INSERT OR REPLACE INTO cols VALUES (?,?,?,?)", (kind, 0, stat, pack(values)))


def _collect_era_parts(kind, season, ident, columns, era_parts, traded, stint_parts) -> None:
    """Team ERA+ adds up its pitchers' parts: one-club pitchers from the season
    rows, traded ones from their per-club rows."""
    erlg, ber, ip = columns["ERlg"], columns["bER"], columns.get("IP")
    if ip is None:
        return
    for i, r in enumerate(ident):
        if np.isnan(erlg[i]) or np.isnan(ber[i]) or np.isnan(ip[i]):
            if kind == "pit" and r["team"] == "- - -":
                traded.setdefault(season, set()).add(r.get("pid"))
            continue
        if kind == "pit":
            if r["team"] == "- - -":
                traded.setdefault(season, set()).add(r.get("pid"))
                continue
            acc = era_parts.setdefault((season, r["team"]), [0.0, 0.0, 0.0])
            acc[0] += float(erlg[i]); acc[1] += float(ber[i]); acc[2] += float(ip[i])
        elif kind == "spit":
            stint_parts.setdefault(season, []).append((r.get("pid"), r["team"], float(erlg[i]), float(ber[i]),
                                                        float(ip[i])))


def _collect_team_bwar(kind, season, ident, columns, war_parts, war_traded, war_stints) -> None:
    """Team bWAR adds up its players' (Baseball-Reference's team totals are the
    same sum): one-club players from the season rows, traded ones from their
    per-club rows, with the PA (IP) each covers."""
    base = "pit" if kind in ("pit", "spit") else "bat"
    war, weight = columns.get("bWAR"), columns.get("IP" if base == "pit" else "PA")
    if war is None or weight is None:
        return
    for i, r in enumerate(ident):
        if kind in ("bat", "pit") and r["team"] == "- - -":
            war_traded.setdefault((base, season), set()).add(r.get("pid"))
            continue
        if np.isnan(war[i]) or np.isnan(weight[i]):
            continue
        if kind in ("bat", "pit"):
            acc = war_parts.setdefault((base, season, r["team"]), [0.0, 0.0])
            acc[0] += float(war[i]); acc[1] += float(weight[i])
        else:
            war_stints.setdefault((base, season), []).append((r.get("pid"), r["team"], float(war[i]), float(weight[i])))


def _team_bwar(con, war_parts, war_traded, war_stints, cover: float = 0.95) -> None:
    """bWAR for each team season (hitting and pitching), blank when the players
    matched to Baseball-Reference cover under 95% of its PA (IP)."""
    for (base, season), rows in war_stints.items():
        moved = war_traded.get((base, season), set())
        for pid, team, war, weight in rows:
            if pid in moved:
                acc = war_parts.setdefault((base, season, team), [0.0, 0.0])
                acc[0] += war; acc[1] += weight
    for base, tkind, unit in (("bat", "tbat", "PA"), ("pit", "tpit", "IP")):
        for (season,) in con.execute("SELECT DISTINCT season FROM rows WHERE kind = ? AND season > 0", (tkind,)).fetchall():
            clubs = [t for (t,) in con.execute("SELECT team FROM rows WHERE kind = ? AND season = ? ORDER BY i",
                                               (tkind, season))]
            blob = con.execute("SELECT data FROM cols WHERE kind = ? AND season = ? AND stat = ?",
                               (tkind, season, unit)).fetchone()
            if not blob:
                continue
            total = unpack(blob[0])
            values = np.full(len(clubs), np.nan, dtype=np.float32)
            for i, club in enumerate(clubs):
                acc = war_parts.get((base, season, club))
                if acc and total[i] > 0 and acc[1] >= cover * float(total[i]):
                    values[i] = acc[0]
            if not np.isnan(values).all():
                con.execute("INSERT OR REPLACE INTO cols VALUES (?,?,?,?)", (tkind, season, "bWAR", pack(values)))


def _team_era_plus(con, era_parts, traded, stint_parts, cover: float = 0.95) -> None:
    """ERA+ for each team season, from its pitchers' Baseball-Reference parts.
    Left blank when the matched pitchers threw under 95% of the team's innings."""
    for season, rows in stint_parts.items():
        moved = traded.get(season, set())
        for pid, team, erlg, ber, ip in rows:
            if pid in moved:
                acc = era_parts.setdefault((season, team), [0.0, 0.0, 0.0])
                acc[0] += erlg; acc[1] += ber; acc[2] += ip
    seasons = [s for (s,) in con.execute("SELECT DISTINCT season FROM rows WHERE kind = 'tpit'")]
    for season in seasons:
        teams_ = [t for (t,) in con.execute("SELECT team FROM rows WHERE kind = 'tpit' AND season = ? ORDER BY i",
                                            (season,))]
        blob = con.execute("SELECT data FROM cols WHERE kind = 'tpit' AND season = ? AND stat = 'IP'",
                           (season,)).fetchone()
        if not blob:
            continue
        team_ip = unpack(blob[0])
        erlg = np.full(len(teams_), np.nan, dtype=np.float32)
        ber = np.full(len(teams_), np.nan, dtype=np.float32)
        for i, team in enumerate(teams_):
            acc = era_parts.get((season, team))
            if acc and team_ip[i] > 0 and acc[2] >= cover * float(team_ip[i]):
                erlg[i], ber[i] = acc[0], acc[1]
        if np.isnan(erlg).all():
            continue
        for stat, values in (("ERlg", erlg), ("bER", ber), ("ERA+", bwar.era_plus(erlg, ber).astype(np.float32))):
            con.execute("INSERT OR REPLACE INTO cols VALUES (?,?,?,?)", ("tpit", season, stat, pack(values)))


def _league_rows(con, sv) -> int:
    """League averages for every season, one row per league group (the AL and NL
    together as "MLB", plus "AL" and "NL" alone, and every other league): the
    league's clubs added up like any roster, so rates are the league's own
    (FanGraphs team files), and Baseball Savant's stats from every player's counts
    (MLB only, 2015 on). Index stats (wRC+, ERA-, ERA+, ...) are 100 by definition."""
    written = 0
    for base, tkind in (("bat", "tbat"), ("pit", "tpit")):
        pitching = base == "pit"
        lkind = "l" + base
        seasons = [s for (s,) in con.execute("SELECT DISTINCT season FROM rows WHERE kind = ? ORDER BY season", (tkind,))]
        for season in seasons:
            clubs = [t for (t,) in con.execute("SELECT team FROM rows WHERE kind = ? AND season = ? ORDER BY i",
                                               (tkind, season))]
            cols = {stat: unpack(blob).astype(np.float64)
                    for stat, blob in con.execute("SELECT stat, data FROM cols WHERE kind = ? AND season = ?",
                                                  (tkind, season))}
            if not clubs or not cols:
                continue
            group = [teams.league_group(c, season) for c in clubs]
            league = [teams.league(c, season) for c in clubs]
            # Each club once in its group, and AL and NL clubs once more in their own league.
            keys, picks = [], []
            for i, g in enumerate(group):
                keys.append(g); picks.append(i)
                if g == "MLB" and league[i] in ("AL", "NL"):
                    keys.append(league[i]); picks.append(i)
            idx = np.array(picks)
            uniq, _first, agg = aggregate.group_rows(np.array(keys), {k: v[idx] for k, v in cols.items()}, pitching)
            labels = [str(u) for u in uniq]
            parts = sv.league_parts(base, season) if sv is not None else None
            if parts and "MLB" in labels:
                j = labels.index("MLB")
                for k, v in parts.items():
                    agg.setdefault(k, np.full(len(labels), np.nan))[j] = v
                shown = savant.rates({k: np.array([v]) for k, v in parts.items()}, pitching)
                for k in savant.SHOWN + savant.PITCHER_SHOWN:
                    if k in shown:
                        agg.setdefault(k, np.full(len(labels), np.nan))[j] = shown[k][0]
            for stat in list(agg):
                if (stat.endswith(("+", "-")) and stat not in ("+WPA", "-WPA")):
                    agg[stat] = np.where(np.isnan(agg[stat]), np.nan, 100.0)
            con.executemany("INSERT INTO rows VALUES (?,?,?,?,?,?,?,?,?)", [
                (lkind, season, i, None, label, None, None, None, None) for i, label in enumerate(labels)])
            con.executemany("INSERT INTO cols VALUES (?,?,?,?)", [
                (lkind, season, stat, pack(np.asarray(values, dtype=np.float32))) for stat, values in agg.items()
                if not np.isnan(np.asarray(values, dtype=np.float64)).all()])
            written += len(labels)
    return written


def build(csv_root: Path, stints_root: Path, output: Path, bwar_root: Path | None = None,
          savant_root: Path | None = None) -> dict:
    started = time.time()
    # Baseball-Reference WAR files live beside the database (pipeline/bwar.py).
    bw = bwar.BWar(bwar_root if bwar_root is not None else output / "bwar")
    # Baseball Savant season files, also beside the database (pipeline/savant.py).
    sv = savant.Savant(savant_root if savant_root is not None else output / "savant")
    output.mkdir(parents=True, exist_ok=True)
    tmp = output / "baseball.sqlite.tmp"
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("""
        PRAGMA page_size = 16384; PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
        CREATE TABLE rows(kind TEXT, season INT, i INT, pid INT, team TEXT, teamid INT, age INT,
                          pos TEXT, tg INT, PRIMARY KEY(kind, season, i)) WITHOUT ROWID;
        CREATE TABLE cols(kind TEXT, season INT, stat TEXT, data BLOB, PRIMARY KEY(kind, season, stat));
        CREATE TABLE catalog(kind TEXT, stat TEXT, name TEXT, grp TEXT, fmt TEXT, lower INT,
                             counting INT, weight TEXT, first INT, last INT, seasons INT,
                             PRIMARY KEY(kind, stat)) WITHOUT ROWID;
        CREATE TABLE players(pid INTEGER PRIMARY KEY, name TEXT, key TEXT, mlbam INT, bats TEXT,
                             throws TEXT, first INT, last INT, pa REAL, ip REAL, war REAL, pos TEXT,
                             bwar REAL);
        CREATE TABLE team_seasons(season INT, team TEXT, teamid INT, name TEXT, league TEXT,
                                  division TEXT, w INT, l INT, g INT, rs INT, ra INT, lg_name TEXT,
                                  PRIMARY KEY(season, team)) WITHOUT ROWID;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    roots = {k: (stints_root if k.startswith("s") else csv_root) / d for k, d in SOURCES.items()}
    seen = {}         # base -> stat -> [first, last, seasons]
    people: dict = {}
    career_pids: dict = {"bat": [], "pit": []}     # (season, pid array) in insertion order
    team_rows: dict = {}
    era_parts: dict = {}     # (season, team) -> [ERlg, bER, IP covered]
    traded: dict = {}        # season -> pids on more than one club (FanGraphs team "- - -")
    stint_parts: dict = {}   # season -> [(pid, team, ERlg, bER, IP)]
    war_parts: dict = {}     # (bat|pit, season, team) -> [bWAR, PA or IP covered]
    war_traded: dict = {}    # (bat|pit, season) -> pids on more than one club
    war_stints: dict = {}    # (bat|pit, season) -> [(pid, team, bWAR, PA or IP)]
    games: dict = {}
    hundred = set()
    newest = 0.0
    seasons_seen = {}
    # One file at a time, so memory stays near one season's worth.
    for kind, folder in roots.items():
        files = sorted(list(folder.glob("*.csv")) + list(folder.glob("*.csv.gz"))) if folder.exists() else []
        base = "pit" if kind in ("pit", "tpit", "spit") else "bat"
        for path in files:
            stem = path.name.split(".")[0]
            if not stem.isdigit():
                continue
            season = int(stem)
            newest = max(newest, path.stat().st_mtime)
            ident, columns = read_season(path, kind)
            if not ident:
                continue
            seasons_seen.setdefault(kind, set()).add(season)
            if kind in ("bat", "pit"):
                extra = bw.season_columns(kind, season, ident, columns.get("PA" if kind == "bat" else "IP"))
            elif kind in ("sbat", "spit"):
                extra = bw.stint_columns(kind, season, ident, columns.get("PA" if kind == "sbat" else "IP",
                                                                         np.full(len(ident), np.nan)))
            else:
                extra = {}
            for stat, values in extra.items():
                if not np.isnan(values).all():
                    columns[stat] = values
            if kind in ("bat", "pit") and sv.loaded:
                for stat, values in sv.season_columns(kind, season, ident).items():
                    if not np.isnan(values).all():
                        columns[stat] = values
            per = "TBF" if kind in ("pit", "spit", "tpit") else "PA"
            if "Barrels" in columns and per in columns:
                denominator = columns[per]
                with np.errstate(invalid="ignore", divide="ignore"):
                    columns["Barrel/PA"] = np.where(denominator > 0, columns["Barrels"] / np.where(denominator > 0, denominator, 1),
                                                    np.nan).astype(np.float32)
            if kind in ("bat", "pit", "sbat", "spit") and "bWAR" in columns:
                _collect_team_bwar(kind, season, ident, columns, war_parts, war_traded, war_stints)
            if "ERlg" in columns and "bER" in columns:
                columns["ERA+"] = bwar.era_plus(columns["ERlg"], columns["bER"]).astype(np.float32)
                _collect_era_parts(kind, season, ident, columns, era_parts, traded, stint_parts)
            for stat in list(columns):
                # FanGraphs stores percentages as fractions; guard against a column in 0-100.
                if catalog.fmt(stat) == "pct1":
                    v = np.abs(columns[stat][~np.isnan(columns[stat])])
                    v = v[v != 0]
                    if len(v) >= 5 and float(np.median(v)) > 1.0:
                        columns[stat] = columns[stat] / np.float32(100)
                        hundred.add((base, stat))
            con.executemany("INSERT INTO rows VALUES (?,?,?,?,?,?,?,?,?)", [
                (kind, season, i, r.get("pid"), r["team"], r["teamid"], r.get("age"), r.get("pos"), r.get("tg"))
                for i, r in enumerate(ident)])
            con.executemany("INSERT INTO cols VALUES (?,?,?,?)", [
                (kind, season, stat, pack(values)) for stat, values in columns.items()
                if not np.isnan(values).all()])
            if kind in ("bat", "pit", "tbat", "tpit"):
                for stat, values in columns.items():
                    if stat in INTERNAL or np.isnan(values).all():
                        continue
                    entry = seen.setdefault(base, {}).setdefault(stat, [season, season, set()])
                    entry[0], entry[1] = min(entry[0], season), max(entry[1], season)
                    entry[2].add(season)
            if kind in ("bat", "pit"):
                weight = columns.get("PA" if kind == "bat" else "IP", np.zeros(len(ident)))
                war = columns.get("WAR", np.zeros(len(ident)))
                bwar_col = columns.get("bWAR", np.full(len(ident), np.nan))
                for i, r in enumerate(ident):
                    p = people.setdefault(r["pid"], {"name": r["name"], "season": -1, "first": season,
                                                     "last": season, "pa": 0.0, "ip": 0.0, "war": 0.0,
                                                     "bwar": None,
                                                     "bats": None, "throws": None, "mlbam": None,
                                                     "pos": {}})
                    if season >= p["season"]:
                        p["name"], p["season"] = r["name"] or p["name"], season
                        p["mlbam"] = r["mlbam"] or p["mlbam"]
                    p["first"], p["last"] = min(p["first"], season), max(p["last"], season)
                    w = 0.0 if np.isnan(weight[i]) else float(weight[i])
                    p["pa" if kind == "bat" else "ip"] += w
                    p["war"] += 0.0 if np.isnan(war[i]) else float(war[i])
                    if not np.isnan(bwar_col[i]):
                        p["bwar"] = (p["bwar"] or 0.0) + float(bwar_col[i])
                    hand = "bats" if kind == "bat" else "throws"
                    p[hand] = r["hand"] or p[hand]
                    if r["pos"] and kind == "bat":
                        p["pos"][r["pos"]] = p["pos"].get(r["pos"], 0) + w
                    if r.get("tg"):
                        games[(season, r["team"])] = max(games.get((season, r["team"]), 0), r["tg"])
                career_pids[kind].append((season, np.array([r["pid"] for r in ident])))
            if kind in ("tbat", "tpit"):
                for i, r in enumerate(ident):
                    t = team_rows.setdefault((season, r["team"]), {"teamid": r["teamid"]})
                    for stat in ("W", "L", "R"):
                        if stat in columns and not np.isnan(columns[stat][i]):
                            t[(kind, stat)] = int(round(columns[stat][i]))
            del ident, columns
    _team_era_plus(con, era_parts, traded, stint_parts)
    _team_bwar(con, war_parts, war_traded, war_stints)
    league_rows = _league_rows(con, sv if sv.loaded else None)
    if hundred:
        log.info("percent columns stored as 0-100: %s", sorted(s for _, s in hundred))
    # Careers (season 0), one stat at a time from the stored columns.
    for kind, parts in career_pids.items():
        if parts:
            _careers(con, kind, parts, sorted(seen.get(kind, {})))
    # Catalog.
    for base, stats in seen.items():
        pitching = base == "pit"
        con.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            (base, stat, catalog.describe(stat), catalog.group(stat, pitching), catalog.fmt(stat),
             int(catalog.lower_is_better(stat, pitching)), int(catalog.is_counting(stat)),
             catalog.weight(stat, pitching), first, last, len(years))
            for stat, (first, last, years) in stats.items()])
    # Players.
    con.executemany("INSERT INTO players VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (pid, p["name"], search_key(p["name"]), p["mlbam"], p["bats"], p["throws"], p["first"],
         p["last"], round(p["pa"], 1), round(p["ip"], 2), round(p["war"], 1),
         max(p["pos"], key=p["pos"].get) if p["pos"] else ("P" if p["ip"] > 0 else None),
         None if p["bwar"] is None else round(p["bwar"], 1))
        for pid, p in people.items() if pid is not None])
    # Team seasons (records from the team pitching rows, runs from both sides).
    con.executemany("INSERT INTO team_seasons VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (season, team, t["teamid"], teams.team_name(team, season), teams.league(team, season),
         teams.division(team, season), t.get(("tpit", "W")), t.get(("tpit", "L")),
         games.get((season, team)) or ((t.get(("tpit", "W")) or 0) + (t.get(("tpit", "L")) or 0)),
         t.get(("tbat", "R")), t.get(("tpit", "R")), teams.league_name(team, season))
        for (season, team), t in team_rows.items() if team != teams.MULTI_TEAM])
    latest = max(seasons_seen.get("bat", {0}))
    meta = {"schema": SCHEMA_VERSION, "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "data_through": dt.datetime.fromtimestamp(newest, dt.timezone.utc).isoformat(timespec="seconds") if newest else "",
            "latest": latest, "first": min(seasons_seen.get("bat", {0})),
            "percent_0_100": sorted(f"{b}:{s}" for b, s in hundred)}
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.execute("CREATE INDEX rows_pid ON rows(pid, kind, season)")
    con.execute("CREATE INDEX rows_team ON rows(team, season)")
    con.execute("CREATE INDEX players_key ON players(key)")
    con.commit()
    check = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.execute("ANALYZE")
    con.close()
    if check != "ok":
        raise RuntimeError(f"integrity check failed: {check}")
    os.chmod(tmp, 0o644)
    os.replace(tmp, output / "baseball.sqlite")
    summary = {"seconds": round(time.time() - started, 1), "players": len(people),
               "files": sum(len(v) for v in seasons_seen.values()), "latest": latest,
               "size_mb": round((output / "baseball.sqlite").stat().st_size / 1e6, 1)}
    log.info("built %s", summary)
    return summary


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--csv-root", type=Path, required=True)
    p.add_argument("--stints-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    print(json.dumps(build(a.csv_root, a.stints_root, a.output)))


if __name__ == "__main__":
    main()
