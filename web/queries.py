"""Everything the pages ask the database for."""
from __future__ import annotations

import math
import re

import numpy as np

from pipeline import catalog as cat
from pipeline import teams as T
from pipeline.text import search_key

from . import db

BAT, PIT = "bat", "pit"
PA_RATE, IP_RATE = 3.1, 1.0            # MLB rule 9.22: per game scheduled for his team
SPAN_CUT = {BAT: 1000, PIT: 300}       # FanGraphs' multi-season "qualified" (see NOTES.md)
MODES = {BAT: {k: (title, cols) for k, title, cols in cat.BAT_GROUPS},
         PIT: {k: (title, cols) for k, title, cols in cat.PIT_GROUPS}}
POSITIONS = [("", "All"), ("C", "C"), ("1B", "1B"), ("2B", "2B"), ("3B", "3B"), ("SS", "SS"),
             ("OF", "OF"), ("DH", "DH")]
ROLES = [("", "All"), ("SP", "Starters"), ("RP", "Relievers")]


# ---------- seasons and names ----------

@db.cached
def seasons() -> list[int]:
    return sorted(db.seasons_with(BAT), reverse=True)


def latest_season() -> int:
    return db.latest()


@db.cached
def people() -> dict:
    return {r["pid"]: r for r in db.rows("SELECT * FROM players")}


@db.cached
def team_seasons(season: int) -> dict:
    return {r["team"]: r for r in db.rows("SELECT * FROM team_seasons WHERE season = ?", season)}


@db.cached
def season_games(season: int) -> int:
    """Games on a full schedule that season (the most any club played)."""
    return int(db.scalar("SELECT MAX(g) FROM team_seasons WHERE season = ?", season) or 0)


def span(lo: int, hi: int) -> tuple:
    lo, hi = int(lo), int(hi)
    return (min(lo, hi), max(lo, hi))


def span_label(lo: int, hi: int) -> str:
    if lo == hi:
        return str(lo)
    if lo <= db.first_season() and hi >= db.latest():
        return "All seasons"
    return f"{lo}\u2013{hi}"


# ---------- qualifying ----------

def rule_of(stat: str, kind: str):
    """'q' when the stat needs a qualified player (a rate), None for counts."""
    info = db.catalog(kind).get(stat)
    if info is None or info["counting"] or stat in ("PA", "IP", "Age", "TBF"):
        return None
    return "q"


def need_for(kind: str, lo: int, hi: int, tg=None) -> float:
    """PA (or IP) a player needs to qualify."""
    rate = PA_RATE if kind == BAT else IP_RATE
    if lo == hi:
        games = tg if tg else season_games(lo)
        return math.floor(rate * games + 0.5)   # 502 of 162; matches FanGraphs' lists
    total = sum(season_games(s) for s in range(lo, hi + 1))
    return min(SPAN_CUT[kind], math.floor(rate * total + 0.5))


def qualifying(kind: str, t: db.Table) -> tuple:
    """(needed, have, ok) arrays for a table from db.table."""
    weight = t.cols["PA" if kind == BAT else "IP"]
    have = np.nan_to_num(weight)
    lo, hi = t.seasons
    if lo == hi:
        need = np.array([need_for(kind, lo, hi, r.get("tg")) for r in t.ident], dtype=float)
    else:
        need = np.full(len(t), float(need_for(kind, lo, hi)))
    return need, have, have >= need


# ---------- percentile pools ----------

STINT_KIND = {BAT: "sbat", PIT: "spit"}


@db.cached
def player_groups(kind: str, season: int) -> dict:
    """pid -> league group that season (teams.league_group). A traded player
    counts where he had the most PA (IP for pitchers)."""
    weight = "PA" if kind == BAT else "IP"
    out, best = {}, {}
    for k in (kind, STINT_KIND[kind]):
        t = db.table(k, season, season, (weight,))
        col = t.cols.get(weight)
        for i, r in enumerate(t.ident):
            code = r.get("team") or ""
            if code == T.MULTI_TEAM:
                continue
            w = 0.0 if col is None or np.isnan(col[i]) else float(col[i])
            if r["pid"] not in best or w > best[r["pid"]]:
                best[r["pid"]], out[r["pid"]] = w, T.league_group(code, season)
    return out


def season_pools(kind: str, season: int, stats: tuple) -> dict:
    """{group: {stat: sorted values}} of the qualified players in each league group
    that season, ignoring any display filter (a group with nobody qualified uses
    everyone who played)."""
    t = db.table(kind, season, season, stats)
    _need, have, ok = qualifying(kind, t)
    groups = player_groups(kind, season)
    member: dict = {}
    for i, r in enumerate(t.ident):
        if have[i] > 0:
            member.setdefault(groups.get(r["pid"], "MLB"), []).append(i)
    out = {}
    for g, idx in member.items():
        idx = np.array(idx)
        use = idx[ok[idx]] if ok[idx].any() else idx
        out[g] = {s: np.sort(t.cols[s][use][~np.isnan(t.cols[s][use])]) for s in stats if s in t.cols}
    return out


# ---------- columns ----------

def column(kind: str, stat: str) -> dict | None:
    info = db.catalog(kind).get(stat)
    if info is None:
        return None
    return {"key": stat, "head": cat.head(stat), "name": info["name"], "fmt": "ip" if stat == "IP" else info["fmt"],
            "better": not info["lower"], "rule": rule_of(stat, kind), "group": info["grp"]}


def columns(kind: str, mode: str) -> list[dict]:
    stats = MODES[kind].get(mode, MODES[kind]["standard"])[1]
    return [c for c in (column(kind, s) for s in stats) if c]


def stat_menu(kind: str) -> list[tuple]:
    """[(group title, [column])] for chart and table menus, common groups first."""
    by_group: dict = {}
    for stat, info in db.catalog(kind).items():
        by_group.setdefault(info["grp"], []).append(column(kind, stat))
    order = {key: i for i, key in enumerate(cat.GROUP_ORDER)}
    out = []
    for grp in sorted(by_group, key=lambda g: order.get(g, 99)):
        cols = by_group[grp]
        if grp in ("standard", "advanced", "value"):
            preferred = [s for _k, _t, c in (cat.BAT_GROUPS if kind == BAT else cat.PIT_GROUPS) for s in c]
            rank = {s: i for i, s in enumerate(dict.fromkeys(preferred))}
            cols.sort(key=lambda c: (rank.get(c["key"], 999), c["key"].lower()))
        else:
            cols.sort(key=lambda c: c["key"].lower())
        out.append((cat.GROUP_TITLES.get(grp, grp.title()), cols))
    return out


# ---------- player tables ----------

def _role(row_cols, i) -> str:
    g, gs = row_cols.get("G"), row_cols.get("GS")
    if g is None or gs is None or np.isnan(g[i]) or not g[i]:
        return ""
    return "SP" if gs[i] >= g[i] / 2 else "RP"


def lines_for(kind: str, lo: int, hi: int, stats: tuple, *, min_mode="q", min_value=0,
              team="", league="", pos="", rule_stats=None) -> tuple[list[dict], dict]:
    """Player rows for a table or chart, filtered. Returns (lines, info)."""
    stats = tuple(dict.fromkeys(stats))
    extra = ("G", "GS") if kind == PIT else ("G",)
    t = db.table(kind, lo, hi, tuple(dict.fromkeys(stats + extra)))
    need, have, ok = qualifying(kind, t)
    names = people()
    unit = "PA" if kind == BAT else "IP"
    ruled = [s for s in (rule_stats if rule_stats is not None else stats) if rule_of(s, kind)]
    lines = []
    for i, r in enumerate(t.ident):
        p = names.get(r["pid"])
        if p is None:
            continue
        code = r.get("team") or ""
        if team and code != team:
            continue
        season = r.get("last") or lo
        if league and T.league(code, season) != league:
            if not (code == T.MULTI_TEAM and league in ("AL", "NL")):
                continue
        position = r.get("pos") or p.get("pos") or ""
        if pos and kind == BAT and not _pos_match(position, pos):
            continue
        role = _role(t.cols, i) if kind == PIT else ""
        if pos and kind == PIT and role != pos:
            continue
        if min_mode == "n" and have[i] < min_value:
            continue
        line = {"pid": r["pid"], "name": p["name"], "team": code, "age": r.get("age"),
                "pos": role or _short_pos(position), "first": r.get("first", lo), "last": r.get("last", hi),
                "seasons_n": r.get("n", 1), "season": season, "need": need[i], "have": have[i],
                "qualified": bool(ok[i]), "fails": {}}
        for s in t.cols:
            v = t.cols[s][i]
            line[s] = None if np.isnan(v) else float(v)
        if not ok[i] and ruled:   # rates need him qualified; counts alone do not
            line["fails"]["q"] = (f"Not qualified: {_amount(have[i], unit)} of "
                                  f"{_amount(need[i], unit)} {unit}")
        lines.append(line)
    info = {"unit": unit, "need": need_for(kind, lo, hi) if len(t) else 0, "total": len(lines)}
    return lines, info


def _amount(v, unit):
    return f"{v:,.1f}".rstrip("0").rstrip(".") if unit == "IP" else f"{v:,.0f}"


def _pos_match(position: str, want: str) -> bool:
    parts = set(re.split(r"[/-]", position or ""))
    if want == "OF":
        return bool(parts & {"OF", "LF", "CF", "RF"})
    return want in parts


def _short_pos(position: str) -> str:
    return (position or "").split("/")[0]


def player_table(kind, lo, hi, mode, min_mode, min_value, team, league, pos, sort):
    cols = columns(kind, mode)
    stats = tuple(c["key"] for c in cols) + ("WAR",)
    lines, info = lines_for(kind, lo, hi, stats, min_mode=min_mode, min_value=min_value,
                            team=team, league=league, pos=pos,
                            rule_stats=tuple(c["key"] for c in cols))
    if min_mode == "q":
        lines = [l for l in lines if l["qualified"] or not any(c["rule"] for c in cols)]
    sort = sort if any(c["key"] == sort for c in cols) or sort in ("WAR",) else ("WAR" if "WAR" in stats else cols[0]["key"])
    better = next((c["better"] for c in cols if c["key"] == sort), True)
    lines.sort(key=lambda l: _sort_key(l.get(sort), better, l["fails"] and sort_rule(cols, sort)))
    return lines, cols, sort, info


def sort_rule(cols, key):
    return next((c["rule"] for c in cols if c["key"] == key), None)


def _sort_key(value, better, short=False):
    if value is None or short:
        return (1, 0)
    return (0, -value if better else value)


# ---------- leaders ----------

BOARDS = {
    BAT: [("WAR", "fWAR (FanGraphs)"), ("bWAR", "bWAR (Baseball-Reference)"), ("wRC+", "wRC+"), ("HR", "Home runs"), ("AVG", "Batting average"),
          ("OBP", "On-base percentage"), ("SB", "Stolen bases")],
    PIT: [("WAR", "fWAR (FanGraphs)"), ("bWAR", "bWAR (Baseball-Reference)"), ("ERA", "ERA"), ("SO", "Strikeouts"), ("FIP", "FIP"),
          ("K-BB%", "K-BB%"), ("SV", "Saves")],
}


@db.cached
def leaders(season: int, lo: int | None = None, top: int = 5) -> dict:
    lo = lo or season
    out = {}
    for kind, boards in BOARDS.items():
        stats = tuple(s for s, _ in boards)
        lines, info = lines_for(kind, lo, season, stats, min_mode="n", min_value=1)
        result = []
        for stat, title in boards:
            c = column(kind, stat)
            if c is None:
                continue
            pool = [l for l in lines if l.get(stat) is not None and (not c["rule"] or l["qualified"])]
            pool.sort(key=lambda l: -l[stat] if c["better"] else l[stat])
            if pool:
                result.append({"stat": stat, "title": title, "col": c, "rows": pool[:top],
                               "qualified": bool(c["rule"])})
        out[kind] = result
    return out


# ---------- teams and standings ----------

TEAM_KIND = {BAT: "tbat", PIT: "tpit"}


@db.cached
def standings(season: int) -> list[dict]:
    """Groups of team records: divisions from 1969, leagues before, other leagues last."""
    ts = team_seasons(season)
    war = _team_war(season)
    rows = []
    for code, r in ts.items():
        if r["w"] is None or r["l"] is None:
            continue
        g = r["w"] + r["l"]
        rs, ra = r["rs"] or 0, r["ra"] or 0
        pyth = rs ** 1.83 / (rs ** 1.83 + ra ** 1.83) if rs + ra else None
        rows.append({**r, "pct": r["w"] / g if g else 0, "diff": rs - ra, "games": g,
                     "pyth_w": round(pyth * g) if pyth is not None else None,
                     "war": war.get(code), "logo": T.logo(code, season)})
    groups: dict = {}
    for r in rows:
        if r["division"]:
            title = r["division"]
        else:
            title = r.get("lg_name") or T.league_name(code, season)
        groups.setdefault(title, []).append(r)
    order = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"] + T.LEAGUE_ORDER
    out = []
    for title in sorted(groups, key=lambda t: (order.index(t) if t in order else 99, t)):
        members = sorted(groups[title], key=lambda r: (-r["pct"], -r["w"]))
        top = members[0]
        for r in members:
            r["gb"] = ((top["w"] - r["w"]) + (r["l"] - top["l"])) / 2
        out.append({"title": title, "rows": members,
                    "league": "AL" if title.startswith(("AL", "American League")) else
                              "NL" if title.startswith(("NL", "National League")) else ""})
    return out


@db.cached
def _team_war(season: int) -> dict:
    out = {}
    for kind in ("tbat", "tpit"):
        t = db.table(kind, season, season, ("WAR",))
        for i, r in enumerate(t.ident):
            v = t.cols["WAR"][i]
            if not np.isnan(v):
                out[r["team"]] = out.get(r["team"], 0.0) + float(v)
    return out


def team_table(kind, lo, hi, mode, league, sort):
    cols = columns(kind, mode)
    stats = tuple(c["key"] for c in cols) + ("WAR",)
    t = db.table(TEAM_KIND[kind], lo, hi, tuple(dict.fromkeys(stats)))
    lines = []
    for i, r in enumerate(t.ident):
        code = r["team"]
        season = r.get("last") or hi
        if league and T.league(code, season) != league:
            continue
        line = {"team": code, "season": season, "name": T.team_name(code, season),
                "logo": T.logo(code, season), "teamid": r.get("teamid")}
        for s in t.cols:
            v = t.cols[s][i]
            line[s] = None if np.isnan(v) else float(v)
        rec = _record(r.get("teamid"), code, lo, hi)
        line.update(rec)
        lines.append(line)
    sort = sort if any(c["key"] == sort for c in cols) or sort in ("WAR", "w", "pct") else "WAR"
    better = next((c["better"] for c in cols if c["key"] == sort), True)
    lines.sort(key=lambda l: _sort_key(l.get(sort), better))
    return lines, cols, sort


@db.cached
def _records(lo: int, hi: int) -> dict:
    out = {}
    for r in db.rows("SELECT teamid, team, SUM(w) AS w, SUM(l) AS l, SUM(rs) AS rs, SUM(ra) AS ra "
                     "FROM team_seasons WHERE season BETWEEN ? AND ? GROUP BY teamid, team", lo, hi):
        key = r["teamid"] if lo != hi else r["team"]
        have = out.setdefault(key, {"w": 0, "l": 0, "rs": 0, "ra": 0})
        for k in have:
            have[k] += r[k] or 0
    return out


def _record(teamid, code, lo, hi) -> dict:
    rec = _records(lo, hi).get(teamid if lo != hi else code) or {}
    w, l = rec.get("w"), rec.get("l")
    return {"w": w, "l": l, "pct": (w / (w + l)) if w is not None and (w + l) else None,
            "rs": rec.get("rs"), "ra": rec.get("ra")}


# ---------- search ----------

@db.cached
def _search_index():
    ppl = sorted(people().values(), key=lambda p: -(p["war"] or 0))
    names = [(p["key"], p) for p in ppl]
    teams = {}
    for r in db.rows("SELECT team, name, season FROM team_seasons ORDER BY season"):
        teams[r["team"]] = r
    return names, list(teams.values())


def search(q: str, limit: int = 12) -> list[dict]:
    key = search_key(q)
    if not key:
        return []
    names, teams = _search_index()
    out = []
    for t in teams:
        if key in search_key(t["name"]) or key == t["team"].lower():
            out.append({"kind": "team", "label": t["name"], "url": f"/team/{t['team']}?season={t['season']}",
                        "sub": f"{t['team']} · last {t['season']}" , "code": t["team"],
                        "logo": logo_url(t["team"], t["season"])})
    starts, contains = [], []
    words = key.split()
    for k, p in names:
        if k.startswith(key) or any(w.startswith(key) for w in k.split()):
            starts.append(p)
        elif all(w in k for w in words):
            contains.append(p)
        if len(starts) >= limit:
            break
    for p in (starts + contains)[:limit]:
        out.append({"kind": "player", "label": p["name"], "url": f"/player/{p['pid']}", "pid": p["pid"],
                    "sub": f"{p['first']}\u2013{p['last']}" if p["first"] != p["last"] else str(p["first"])})
    return out[:limit + 3]


def logo_url(code, season=None):
    path = T.logo(code, season)
    return f"/logos/{path}" if path else None


# ---------- player page ----------

PLAYER_MODES = {BAT: ["standard", "advanced", "value", "battedball", "discipline", "statcast"],
                PIT: ["standard", "advanced", "value", "battedball", "discipline", "statcast"]}


def _row_values(kind, season, i, stats):
    out = {}
    for s in stats:
        col = db.column(kind, season, s)
        out[s] = None if col is False or np.isnan(col[i]) else float(col[i])
    return out


@db.cached
def season_best(kind: str, season: int, stat: str):
    """The majors' best value of a stat that season (qualified players for rates)."""
    c = column(kind, stat)
    col = db.column(kind, season, stat)
    if c is None or col is False:
        return None
    values = col.copy()
    if c["rule"]:
        t = db.table(kind, season, season, (stat,))
        _need, _have, ok = qualifying(kind, t)
        values = np.where(ok, values, np.nan)
    if np.isnan(values).all():
        return None
    return float(np.nanmax(values) if c["better"] else np.nanmin(values))


@db.cached
def player(pid: int, kind: str, mode: str) -> dict | None:
    cols = columns(kind, mode)
    # G and PA/IP always, so the summary line has them in every table mode.
    stats = tuple(dict.fromkeys(tuple(c["key"] for c in cols) + ("WAR", "G", "PA" if kind == BAT else "IP")))
    found = db.rows("SELECT kind, season, i, team, age, pos, tg FROM rows WHERE pid = ? AND kind IN (?, ?) "
                    "ORDER BY season, kind", pid, kind, "s" + kind)
    if not found:
        return None
    seasons_rows, career = [], None
    stints: dict = {}
    for r in found:
        if r["kind"] == "s" + kind:
            stints.setdefault(r["season"], []).append(r)
    for r in found:
        if r["kind"] != kind:
            continue
        values = _row_values(kind, r["season"], r["i"], stats)
        if r["season"] == 0:
            career = values
            continue
        t = db.table(kind, r["season"], r["season"], ("PA" if kind == BAT else "IP",))
        need = need_for(kind, r["season"], r["season"], r["tg"])
        have = values.get("PA" if kind == BAT else "IP") or 0
        row = {"season": r["season"], "team": r["team"], "age": r["age"], "pos": r["pos"],
               "values": values, "qualified": have >= need, "need": need, "stints": [], "led": set()}
        for c in cols:
            v = values.get(c["key"])
            if v is None or (c["rule"] and not row["qualified"]):
                continue
            if not c["rule"] and not c["better"]:   # fewest caught stealing is not a lead
                continue
            best = season_best(kind, r["season"], c["key"])
            if best is not None and abs(v - best) < 1e-6 and c["key"] not in ("G", "PA", "AB", "IP", "TBF", "GS"):
                row["led"].add(c["key"])
        for s in stints.get(r["season"], []):
            row["stints"].append({"team": s["team"], "values": _row_values("s" + kind, s["season"], s["i"], stats)})
        seasons_rows.append(row)
        del t
    ages = [r["age"] for r in seasons_rows if r["age"]]
    weight = "PA" if kind == BAT else "IP"
    facts = {"seasons": len(seasons_rows), "qualified": sum(r["qualified"] for r in seasons_rows),
             "ages": (min(ages), max(ages)) if ages else None,
             "weight": (career or {}).get(weight) if career else sum((r["values"].get(weight) or 0) for r in seasons_rows),
             "games": (career or {}).get("G") if career else sum((r["values"].get("G") or 0) for r in seasons_rows)}
    if facts["games"] is None:
        facts["games"] = sum((r["values"].get("G") or 0) for r in seasons_rows)
    return {"cols": cols, "rows": seasons_rows, "career": career, "facts": facts}


def player_span(pid: int, kind: str, mode: str, lo: int, hi: int) -> dict | None:
    """His line over seasons lo..hi, rolled up like any span (counts add up,
    ratios are rebuilt from the summed parts)."""
    cols = columns(kind, mode)
    weight = "PA" if kind == BAT else "IP"
    stats = tuple(dict.fromkeys(tuple(c["key"] for c in cols) + ("WAR", "G", weight)))
    t = db.table(kind, lo, hi, stats)
    idx = next((i for i, r in enumerate(t.ident) if r["pid"] == pid), None)
    if idx is None:
        return None
    _need, have, ok = qualifying(kind, t)
    values = {s: (None if np.isnan(t.cols[s][idx]) else float(t.cols[s][idx])) for s in stats if s in t.cols}
    r = t.ident[idx]
    return {"lo": lo, "hi": hi, "values": values, "qualified": bool(ok[idx]), "have": float(have[idx]),
            "first": r.get("first", lo), "last": r.get("last", hi), "n": r.get("n", 1)}


PCT_STATS = {
    BAT: [("Value", ["WAR", "bWAR", "wRC+", "Offense", "BaseRunning", "Defense"]),
          ("Hitting", ["OBP", "SLG", "ISO", "AVG", "BABIP"]),
          ("Plate skills", ["BB%", "K%", "O-Swing%", "Contact%"]),
          ("Statcast", ["xwOBA", "EV", "Barrel%", "HardHit%", "AvgBatSpeed"])],
    PIT: [("Value", ["WAR", "bWAR", "ERA-", "FIP-", "RA9-Wins"]),
          ("Run prevention", ["ERA", "FIP", "xFIP", "SIERA", "WHIP"]),
          ("Strikeouts and walks", ["K%", "BB%", "K-BB%", "SwStr%", "O-Swing%"]),
          ("Contact", ["GB%", "HR/9", "Barrel%", "HardHit%", "FBv"])],
}


@db.cached
def range_groups(kind: str, lo: int, hi: int) -> dict:
    """pid -> league group over seasons lo..hi: where he had the most PA (IP)."""
    if lo == hi:
        return player_groups(kind, lo)
    weight = "PA" if kind == BAT else "IP"
    tally: dict = {}
    for season in range(lo, hi + 1):
        groups = player_groups(kind, season)
        t = db.table(kind, season, season, (weight,))
        col = t.cols.get(weight)
        for i, r in enumerate(t.ident):
            w = 0.0 if col is None or np.isnan(col[i]) else float(col[i])
            g = groups.get(r["pid"], "MLB")
            tally.setdefault(r["pid"], {}).setdefault(g, 0.0)
            tally[r["pid"]][g] += w
    return {pid: max(by, key=by.get) for pid, by in tally.items()}


@db.cached
def percentiles(pid: int, kind: str, lo: int, hi: int | None = None) -> dict | None:
    """His percentile in each stat among the qualified players of his league group
    (AL and NL together; other leagues on their own), the way Baseball Savant
    ranks them (100 = best). Over several seasons, his line for lo..hi against
    everyone's line for the same seasons, qualified by FanGraphs' multi-season
    cut, so every player is measured over the same years."""
    hi = lo if hi is None else hi
    stats = tuple(s for _g, group in PCT_STATS[kind] for s in group)
    t = db.table(kind, lo, hi, stats)
    idx = next((i for i, r in enumerate(t.ident) if r["pid"] == pid), None)
    if idx is None:
        return None
    need, _have, ok = qualifying(kind, t)
    group_of = range_groups(kind, lo, hi)
    mine = group_of.get(pid, "MLB")
    same = np.array([group_of.get(r["pid"], "MLB") == mine for r in t.ident])
    ok = ok & same
    groups = []
    for title, group in PCT_STATS[kind]:
        rows_out = []
        for stat in group:
            c = column(kind, stat)
            col = t.cols.get(stat)
            if c is None or col is None or np.isnan(col[idx]):
                continue
            pool = col[ok & ~np.isnan(col)]
            if len(pool) < 10:
                continue
            v = col[idx]
            below, same_v = (pool < v).sum(), (pool == v).sum()
            share = (below + max(same_v - (1 if ok[idx] else 0), 0) / 2) / max(len(pool) - (1 if ok[idx] else 0), 1)
            pct = round(100 * (share if c["better"] else 1 - share))
            rows_out.append({"col": c, "value": float(v), "pct": max(0, min(100, pct))})
        if rows_out:
            groups.append({"title": title, "rows": rows_out})
    return {"season": lo if lo == hi else None, "lo": lo, "hi": hi, "qualified": bool(ok[idx]),
            "pool": int(ok.sum()), "groups": groups, "need": float(need[idx]),
            "group": "AL and NL" if mine == "MLB" else mine}


@db.cached
def player_info(pid: int) -> dict | None:
    p = people().get(pid)
    if p is None:
        return None
    has = {r["kind"]: r["n"] for r in db.rows("SELECT kind, COUNT(*) AS n FROM rows WHERE pid = ? AND season > 0 "
                                               "GROUP BY kind", pid)}
    teams_played = db.rows("SELECT team, MIN(season) AS a, MAX(season) AS b FROM rows WHERE pid = ? "
                           "AND kind IN ('bat','pit','sbat','spit') AND season > 0 AND team != ? "
                           "GROUP BY team ORDER BY a", pid, T.MULTI_TEAM)
    war_by_season: dict = {}
    for kind in (BAT, PIT):
        for r in db.rows("SELECT season, i FROM rows WHERE pid = ? AND kind = ? AND season > 0", pid, kind):
            col = db.column(kind, r["season"], "WAR")
            if col is not False and not np.isnan(col[r["i"]]):
                war_by_season.setdefault(r["season"], {})[kind] = float(col[r["i"]])
    # Pitchers bat too (pre-DH); call him a pitcher when pitching is most of his value.
    bat_pa, pit_ip = p["pa"] or 0, p["ip"] or 0
    primary = PIT if pit_ip * 4.3 > bat_pa else BAT   # batters faced vs plate appearances
    return {**p, "has_bat": bool(has.get("bat")) and bat_pa > 0, "has_pit": bool(has.get("pit")) and pit_ip > 0,
            "teams": teams_played, "war_seasons": war_by_season, "primary": primary,
            "war_bat": {y: v["bat"] for y, v in war_by_season.items() if "bat" in v},
            "war_pit": {y: v["pit"] for y, v in war_by_season.items() if "pit" in v},
            "two_way": bat_pa >= 300 and pit_ip >= 100}


# ---------- team page ----------

TEAM_SUMMARY = {BAT: ["R", "HR", "SB", "AVG", "OBP", "SLG", "wRC+", "WAR"],
                PIT: ["ERA", "FIP", "K%", "BB%", "WHIP", "WAR"]}


@db.cached
def team_page(code: str, season: int, bmode: str, pmode: str) -> dict | None:
    ts = team_seasons(season).get(code)
    if ts is None:
        return None
    out = {"code": code, "season": season, "info": ts, "logo": T.logo(code, season)}
    # Place in its division or league.
    for group in standings(season):
        for i, r in enumerate(group["rows"]):
            if r["team"] == code:
                out["place"], out["group"], out["record"] = i + 1, group["title"], r
    # Team stats with the club's rank that season.
    summary = {}
    for kind, stats in TEAM_SUMMARY.items():
        t = db.table(TEAM_KIND[kind], season, season, tuple(stats))
        idx = next((i for i, r in enumerate(t.ident) if r["team"] == code), None)
        if idx is None:
            continue
        for s in stats:
            c = column(kind, s)
            if c is None:
                continue
            col = t.cols[s]
            v = col[idx]
            if np.isnan(v):
                continue
            order = np.sort(col[~np.isnan(col)])
            rank = int((order > v).sum() + 1) if c["better"] else int((order < v).sum() + 1)
            summary.setdefault(kind, []).append({"col": c, "value": float(v), "rank": rank, "of": len(order)})
    out["summary"] = summary
    # Rosters: his rows for the club, including traded players' stints.
    rosters = {}
    for kind, mode in ((BAT, bmode), (PIT, pmode)):
        cols = columns(kind, mode)
        stats = tuple(dict.fromkeys(tuple(c["key"] for c in cols) + ("WAR", "PA" if kind == BAT else "IP")))
        lines = []
        for k in (kind, "s" + kind):
            t = db.table(k, season, season, stats)
            for i, r in enumerate(t.ident):
                if r["team"] != code or r["pid"] is None:
                    continue
                p = people().get(r["pid"])
                line = {"pid": r["pid"], "name": p["name"] if p else str(r["pid"]), "age": r["age"],
                        "pos": _short_pos(r["pos"] or ""), "traded": k.startswith("s")}
                for s in t.cols:
                    v = t.cols[s][i]
                    line[s] = None if np.isnan(v) else float(v)
                weight = line.get("PA" if kind == BAT else "IP") or 0
                if weight <= 0:
                    continue
                lines.append(line)
        lines.sort(key=lambda l: -(l.get("PA" if kind == BAT else "IP") or 0))
        rosters[kind] = {"cols": cols, "lines": lines}
    out["rosters"] = rosters
    out["history"] = franchise_history(ts["teamid"])
    return out


@db.cached
def franchise_history(teamid) -> list[dict]:
    rows = db.rows("SELECT * FROM team_seasons WHERE teamid = ? ORDER BY season DESC", teamid)
    for r in rows:
        g = (r["w"] or 0) + (r["l"] or 0)
        r["pct"] = r["w"] / g if g else None
        r["war"] = _team_war(r["season"]).get(r["team"])
        r["logo"] = T.logo(r["team"], r["season"])
    return rows
