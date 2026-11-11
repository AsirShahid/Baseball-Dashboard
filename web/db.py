"""Read-only access to baseball.sqlite, with caches that follow the file.

The updater replaces the file by renaming a new one over it; each worker
notices by the file's identity, reopens, and drops its caches.

Stats live in a column store: for each (kind, season, stat) one float32
array aligned with that season's rows. ``table`` loads the columns a page
needs for one season or a range of seasons (rolled up per player or team).
"""
from __future__ import annotations

import functools
import json
import os
import sqlite3
import threading
import zlib
from collections import OrderedDict
from pathlib import Path

import numpy as np

from pipeline import aggregate, savant
from pipeline import teams as T

_local = threading.local()
_lock = threading.Lock()
_cache: dict = {}
_cache_version = None
DATA_ROOT = Path(os.environ.get("DATA_ROOT") or Path(__file__).resolve().parent.parent / "data")
PITCHING = {"pit": True, "tpit": True, "spit": True, "lpit": True,
            "bat": False, "tbat": False, "sbat": False, "lbat": False}


def configure(data_root) -> None:
    global DATA_ROOT
    DATA_ROOT = Path(data_root)
    _local.__dict__.clear()
    _cache.clear()
    _columns.clear()


def db_path() -> Path:
    return DATA_ROOT / "baseball.sqlite"


def version():
    try:
        stat = db_path().stat()
    except OSError:
        return None
    return (stat.st_ino, stat.st_mtime_ns, stat.st_size)


def available() -> bool:
    return version() is not None


def connection() -> sqlite3.Connection:
    current = version()
    if current is None:
        raise FileNotFoundError(f"{db_path()} has not been built yet")
    if getattr(_local, "version", None) != current:
        old = getattr(_local, "con", None)
        if old is not None:
            old.close()
        con = sqlite3.connect(f"file:{db_path()}?mode=ro&immutable=1", uri=True,
                              check_same_thread=False)
        con.row_factory = sqlite3.Row
        _local.con, _local.version = con, current
    return _local.con


def rows(sql: str, *params) -> list[dict]:
    return [dict(row) for row in connection().execute(sql, params)]


def one(sql: str, *params) -> dict | None:
    row = connection().execute(sql, params).fetchone()
    return dict(row) if row else None


def scalar(sql: str, *params):
    row = connection().execute(sql, params).fetchone()
    return row[0] if row else None


def cached(function):
    """Memoize per database version. Arguments must be hashable."""
    @functools.wraps(function)
    def wrapper(*args):
        global _cache_version
        current = version()
        with _lock:
            if current != _cache_version:
                _cache.clear()
                _columns.clear()
                _cache_version = current
            key = (function.__name__, args)
            if key in _cache:
                return _cache[key]
        value = function(*args)
        with _lock:
            if len(_cache) > 400:
                _cache.clear()
            _cache[key] = value
        return value
    return wrapper


@cached
def meta() -> dict:
    return {r["key"]: json.loads(r["value"]) for r in rows("SELECT key, value FROM meta")}


# ---------- column store ----------

_columns: OrderedDict = OrderedDict()
_COLUMN_CACHE = 6000   # arrays (most are a few KB)


def column(kind: str, season: int, stat: str):
    """One stat for one season as float64, or None when FanGraphs has none."""
    key = (kind, season, stat)
    with _lock:
        hit = _columns.get(key)
        if hit is not None:
            _columns.move_to_end(key)
            return hit
    blob = scalar("SELECT data FROM cols WHERE kind = ? AND season = ? AND stat = ?", kind, season, stat)
    value = (np.frombuffer(zlib.decompress(blob), dtype="<f4").astype(np.float64)
             if blob is not None else False)
    with _lock:
        _columns[key] = value
        while len(_columns) > _COLUMN_CACHE:
            _columns.popitem(last=False)
    return value


@cached
def ident(kind: str, season: int) -> list[dict]:
    """Identity rows (pid, team, age, ...) for one kind and season, in column order."""
    return rows("SELECT i, pid, team, teamid, age, pos, tg FROM rows WHERE kind = ? AND season = ? ORDER BY i",
                kind, season)


@cached
def seasons_with(kind: str) -> tuple:
    return tuple(r["season"] for r in rows("SELECT DISTINCT season FROM rows WHERE kind = ? AND season > 0 "
                                           "ORDER BY season", kind))


class Table:
    """Rows plus stat arrays. ``ident`` is a list of dicts; ``cols`` maps stat -> array."""

    def __init__(self, ident, cols, seasons):
        self.ident, self.cols, self.seasons = ident, cols, seasons

    def __len__(self):
        return len(self.ident)

    def get(self, stat):
        return self.cols.get(stat)


def _season_table(kind: str, season: int, stats: tuple) -> Table:
    who = ident(kind, season)
    cols = {}
    for stat in stats:
        values = column(kind, season, stat)
        cols[stat] = values if values is not False else np.full(len(who), np.nan)
    for r in who:
        r["season"] = season
    return Table([dict(r) for r in who], cols, (season, season))


def _subset(t: Table, keep: list) -> Table:
    idx = np.asarray(keep, dtype=int)
    return Table([t.ident[i] for i in idx], {s: v[idx] for s, v in t.cols.items()}, t.seasons)


def _league_season(kind: str, season: int, stats: tuple, which: str) -> Table:
    """One season of play in one league (AL, NL or a division): its clubs, and its
    players' lines there. A player traded within the league keeps his season line;
    one traded across leagues counts only his stints with its clubs (his per-club
    rows added up), the way a league's own leaderboard counts him."""
    t = _season_table(kind, season, stats)
    if kind not in ("bat", "pit"):
        return _subset(t, [i for i, r in enumerate(t.ident) if T.in_league(r["team"], season, which)])
    clubs = ident("s" + kind, season)
    stints: dict = {}
    for j, r in enumerate(clubs):
        stints.setdefault(r["pid"], []).append(j)
    keep, split = [], []
    for i, r in enumerate(t.ident):
        if r["team"] != T.MULTI_TEAM:
            if T.in_league(r["team"], season, which):
                keep.append(i)
            continue
        mine = stints.get(r["pid"], [])
        inside = [j for j in mine if T.in_league(clubs[j]["team"], season, which)]
        if inside and len(inside) == len(mine):
            keep.append(i)
        elif inside:
            split.append((i, inside))
    out = _subset(t, keep)
    if not split:
        return out
    st = _season_table("s" + kind, season, stats)
    rows = [j for _, inside in split for j in inside]
    key = np.array([n for n, (_, inside) in enumerate(split) for _ in inside])
    _uniq, _first, agg = aggregate.group_rows(key, {s: st.cols[s][rows] for s in stats}, PITCHING[kind])
    who = []
    for n, (i, inside) in enumerate(split):
        r = dict(t.ident[i])
        r["team"] = clubs[inside[0]]["team"] if len(inside) == 1 else T.MULTI_TEAM
        if "TG" in agg:   # his clubs' games, not their sum: qualifying is per season
            agg["TG"][n] = max(st.cols["TG"][j] for j in inside)
        r["tg"] = agg["TG"][n] if "TG" in agg else r.get("tg")
        who.append(r)
    cols = {s: np.concatenate([out.cols[s], agg.get(s, np.full(len(split), np.nan))]) for s in stats}
    return Table(out.ident + who, cols, out.seasons)


def _roll_up(kind: str, parts: list, need: tuple, lo: int, hi: int) -> Table:
    if not parts:
        return Table([], {s: np.zeros(0) for s in need}, (lo, hi))
    who = [r for p in parts for r in p.ident]
    cols = {s: np.concatenate([p.cols[s] for p in parts]) for s in need}
    key = np.array([(r["pid"] if r["pid"] is not None else hash(r["team"])) for r in who])
    if kind in ("tbat", "tpit"):
        key = np.array([r["teamid"] or hash(r["team"]) for r in who])
    if not len(key):
        return Table([], {s: np.zeros(0) for s in need}, (lo, hi))
    uniq, first, agg = aggregate.group_rows(key, cols, PITCHING[kind])
    # Representative identity: the row from each key's last season in the range.
    last = {}
    for i, r in enumerate(who):
        k = key[i]
        if k not in last or r["season"] >= who[last[k]]["season"]:
            last[k] = i
    seasons_of = {}
    for i, r in enumerate(who):
        span = seasons_of.setdefault(key[i], [r["season"], r["season"], 0])
        span[0], span[1], span[2] = min(span[0], r["season"]), max(span[1], r["season"]), span[2] + 1
    out_ident = []
    for k in uniq:
        r = dict(who[last[k]])
        r["first"], r["last"], r["n"] = seasons_of[k]
        out_ident.append(r)
    return Table(out_ident, agg, (lo, hi))


@cached
def table(kind: str, lo: int, hi: int, stats: tuple, league: str = "") -> Table:
    """One row per player (or team) over seasons lo..hi; one season when lo == hi.

    Ranges roll up per player: counts add, rates are averaged by what they
    are measured over, and AVG/OBP/SLG/ERA/WHIP/K%/BB% are rebuilt from the
    summed parts. A player's team over a range is his team in his last
    season in it (or "- - -" for a traded player).

    With `league` (AL, NL or a division) only play in it counts: a club's seasons
    in it, a player's seasons and stints with its clubs (_league_season)."""
    weight = "IP" if PITCHING[kind] else "PA"
    extra = _SAVANT_PARTS if any(s in _SAVANT_REBUILT for s in stats) else ()
    need = tuple(dict.fromkeys(stats + (weight, "TG") + _PARTS[PITCHING[kind]] + extra))
    if league:
        years = [s for s in seasons_with(kind) if lo <= s <= hi]
        parts = [_league_season(kind, s, need, league) for s in years]
        if lo == hi:
            return parts[0] if parts else Table([], {s: np.zeros(0) for s in need}, (lo, hi))
        return _roll_up(kind, parts, need, lo, hi)
    if lo == hi:
        t = _season_table(kind, lo, need)
        return Table(t.ident, {s: t.cols[s] for s in need}, t.seasons)
    if kind in ("bat", "pit") and lo <= first_season() and hi >= latest():
        t = _season_table(kind, 0, need)
        _fill_careers(kind, t)
        return Table(t.ident, t.cols, (lo, hi))
    years = [s for s in seasons_with(kind) if lo <= s <= hi]
    return _roll_up(kind, [_season_table(kind, s, need) for s in years], need, lo, hi)


# Baseball Savant stats are rebuilt from their counts over a span (pipeline/savant.py).
_SAVANT_REBUILT = frozenset(savant.SHOWN + savant.PITCHER_SHOWN + ("Barrel/PA",))
_SAVANT_PARTS = savant.PARTS + ("Barrels",)

_PARTS = {
    False: ("AB", "H", "1B", "2B", "3B", "HR", "BB", "HBP", "SF", "SO", "Events", "Pitches"),
    True: ("TBF", "ER", "H", "HR", "BB", "SO", "Events", "Pitches", "ERlg", "bER"),
}


def _fill_careers(kind: str, t: Table) -> None:
    """Career rows carry no team or age; add each player's last team and span."""
    span = career_spans(kind)
    for r in t.ident:
        info = span.get(r["pid"])
        if info:
            r["first"], r["last"], r["n"], r["team"] = info


@cached
def career_spans(kind: str) -> dict:
    out = {}
    for r in rows("SELECT pid, MIN(season) AS a, MAX(season) AS b, COUNT(*) AS n FROM rows "
                  "WHERE kind = ? AND season > 0 GROUP BY pid", kind):
        out[r["pid"]] = [r["a"], r["b"], r["n"], None]
    for r in rows("SELECT r.pid, r.team FROM rows r JOIN (SELECT pid, MAX(season) AS s FROM rows "
                  "WHERE kind = ? AND season > 0 GROUP BY pid) last ON r.pid = last.pid "
                  "AND r.season = last.s WHERE r.kind = ?", kind, kind):
        if r["pid"] in out:
            out[r["pid"]][3] = r["team"]
    return out


@cached
def latest() -> int:
    return int(meta().get("latest") or 0)


@cached
def first_season() -> int:
    return int(meta().get("first") or 1871)


@cached
def catalog(kind: str) -> dict:
    """stat -> catalog row, for 'bat' or 'pit'."""
    base = "pit" if PITCHING.get(kind, kind == "pit") else "bat"
    return {r["stat"]: r for r in rows("SELECT * FROM catalog WHERE kind = ?", base)}
