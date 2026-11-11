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

from . import aggregate, catalog, teams
from .text import search_key

log = logging.getLogger("build")
SCHEMA_VERSION = 1
SOURCES = {
    "bat": "all_batting_stats", "pit": "all_pitching_stats",
    "tbat": "team_batting", "tpit": "team_pitching",
    "sbat": "stints_batting", "spit": "stints_pitching",
}
NOTATION_IP = ("IP", "Start-IP", "Relief-IP")
INTERNAL = ("TG",)   # stored but not offered as a stat


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
            "AVG", "OBP", "SLG", "OPS", "ISO", "BABIP", "K%", "BB%", "BB/K"),
    True: ("IP", "TBF", "ER", "H", "HR", "BB", "SO", "ERA", "WHIP", "K/9", "BB/9", "HR/9", "H/9",
           "K%", "BB%", "K-BB%", "K/BB"),
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
    cols = {s: (weights[s] if s in weights else load(s)) for s in _REBUILD_PARTS[pitching] if s in stats}
    _u, _f, agg = aggregate.group_rows(pids, cols, pitching)
    for stat, values in agg.items():
        if stat in cols and not np.isnan(values).all():
            con.execute("INSERT OR REPLACE INTO cols VALUES (?,?,?,?)", (kind, 0, stat, pack(values)))


def build(csv_root: Path, stints_root: Path, output: Path) -> dict:
    started = time.time()
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
                             throws TEXT, first INT, last INT, pa REAL, ip REAL, war REAL, pos TEXT);
        CREATE TABLE team_seasons(season INT, team TEXT, teamid INT, name TEXT, league TEXT,
                                  division TEXT, w INT, l INT, g INT, rs INT, ra INT,
                                  PRIMARY KEY(season, team)) WITHOUT ROWID;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    roots = {k: (stints_root if k.startswith("s") else csv_root) / d for k, d in SOURCES.items()}
    seen = {}         # base -> stat -> [first, last, seasons]
    people: dict = {}
    career_pids: dict = {"bat": [], "pit": []}     # (season, pid array) in insertion order
    team_rows: dict = {}
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
                for i, r in enumerate(ident):
                    p = people.setdefault(r["pid"], {"name": r["name"], "season": -1, "first": season,
                                                     "last": season, "pa": 0.0, "ip": 0.0, "war": 0.0,
                                                     "bats": None, "throws": None, "mlbam": None,
                                                     "pos": {}})
                    if season >= p["season"]:
                        p["name"], p["season"] = r["name"] or p["name"], season
                        p["mlbam"] = r["mlbam"] or p["mlbam"]
                    p["first"], p["last"] = min(p["first"], season), max(p["last"], season)
                    w = 0.0 if np.isnan(weight[i]) else float(weight[i])
                    p["pa" if kind == "bat" else "ip"] += w
                    p["war"] += 0.0 if np.isnan(war[i]) else float(war[i])
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
    con.executemany("INSERT INTO players VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (pid, p["name"], search_key(p["name"]), p["mlbam"], p["bats"], p["throws"], p["first"],
         p["last"], round(p["pa"], 1), round(p["ip"], 2), round(p["war"], 1),
         max(p["pos"], key=p["pos"].get) if p["pos"] else ("P" if p["ip"] > 0 else None))
        for pid, p in people.items() if pid is not None])
    # Team seasons (records from the team pitching rows, runs from both sides).
    con.executemany("INSERT INTO team_seasons VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (season, team, t["teamid"], teams.team_name(team, season), teams.league(team, season),
         teams.division(team, season), t.get(("tpit", "W")), t.get(("tpit", "L")),
         games.get((season, team)) or ((t.get(("tpit", "W")) or 0) + (t.get(("tpit", "L")) or 0)),
         t.get(("tbat", "R")), t.get(("tpit", "R")))
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
