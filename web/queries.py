"""Everything the pages ask the database for."""
from __future__ import annotations

import math
import re

import numpy as np

from pipeline import aggregate
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
    # Descriptions come from the code when it has one, so wording fixes show
    # without a rebuild; the built catalog covers the rest.
    name = cat.NAMES[stat] if stat in cat.NAMES else info["name"]
    return {"key": stat, "head": cat.head(stat), "name": name, "fmt": "ip" if stat == "IP" else info["fmt"],
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


# ---------- league averages ----------

LEAGUE_KIND = {BAT: "lbat", PIT: "lpit"}


def _is_index(stat: str) -> bool:
    return stat.endswith(("+", "-")) and stat not in ("+WPA", "-WPA")


LEAGUE_ABBR = {
    "National Association": "NA", "American Association": "AA", "Union Association": "UA",
    "Players' League": "PL", "Federal League": "FL", "Negro National League I": "NNL",
    "Negro National League II": "NN2", "Eastern Colored League": "ECL", "American Negro League": "ANL",
    "East-West League": "EWL", "Negro Southern League": "NSL", "Negro American League": "NAL",
    "Negro Leagues": "NeL", "Independent Clubs": "Ind",
}


def league_label(group: str) -> str:
    """'MLB', 'AL', 'NL', or a league's usual abbreviation ('Negro National League II' -> 'NN2')."""
    if group in ("MLB", "AL", "NL"):
        return group
    if group in LEAGUE_ABBR:
        return LEAGUE_ABBR[group]
    words = [w for w in re.split(r"[\s-]+", group) if w and w[0].isalpha()]
    return "".join(w[0].upper() for w in words) or group


def _league_values(cols: dict, idx: int, kind: str, stats) -> dict:
    """Rates only: a league total of home runs means nothing beside a player's."""
    out = {}
    for s in stats:
        c = column(kind, s)
        if c is None or not c["rule"]:
            continue
        col = cols.get(s)
        v = None if col is None or np.isnan(col[idx]) else float(col[idx])
        out[s] = 100.0 if v is not None and _is_index(s) else v
    return out


@db.cached
def league_season(kind: str, season: int, group: str, stats: tuple) -> dict | None:
    t = db.table(LEAGUE_KIND[kind], season, season, stats)
    idx = next((i for i, r in enumerate(t.ident) if r["team"] == group), None)
    return None if idx is None else _league_values(t.cols, idx, kind, stats)


def league_over(kind: str, pairs, stats: tuple) -> dict | None:
    """The league over several (season, league group) pairs, added up like a
    career: a player's league line over the seasons he played. A stat whose data
    starts later (plate discipline in 2002) is the league over those seasons."""
    out = _league_over(kind, pairs, stats)
    seasons = [season for season, _g in pairs]
    if not seasons:
        return out
    later: dict = {}
    for stat, first in partial(kind, stats, min(seasons), max(seasons)).items():
        later.setdefault(first, []).append(stat)
    for first, group in later.items():
        sub = _league_over(kind, tuple(p for p in pairs if p[0] >= first), tuple(group))
        if sub:
            out = dict(out or {})
            out.update({k: v for k, v in sub.items() if k in group})
    return out


def _league_over(kind: str, pairs, stats: tuple) -> dict | None:
    lk = LEAGUE_KIND[kind]
    chunks = []
    for season, group in pairs:
        t = db.table(lk, season, season, stats)
        idx = next((i for i, r in enumerate(t.ident) if r["team"] == group), None)
        if idx is not None:
            chunks.append({s: np.asarray(v[idx:idx + 1], dtype=np.float64) for s, v in t.cols.items()})
    if not chunks:
        return None
    keys = set(chunks[0])
    for chunk in chunks[1:]:
        keys &= set(chunk)
    cols = {s: np.concatenate([c[s] for c in chunks]) for s in keys}
    _u, _f, agg = aggregate.group_rows(np.zeros(len(chunks), dtype=int), cols, db.PITCHING[lk])
    # An index stat (wRC+, ERA+, ...) is 100 for the league in any season that has it.
    for s in stats:
        if _is_index(s) and s in cols and not np.isnan(cols[s]).all():
            agg[s] = np.array([100.0])
    return _league_values(agg, 0, kind, stats)


@db.cached
def league_range(kind: str, lo: int, hi: int, stats: tuple, league: str = "") -> dict | None:
    """The league line over seasons lo..hi for a leaderboard: AL or NL when one is
    picked, else MLB (AL and NL), else the league with the most playing time."""
    t = db.table(LEAGUE_KIND[kind], lo, hi, stats + ("PA" if kind == BAT else "IP",))
    labels = [r["team"] for r in t.ident]
    want = league or ("MLB" if "MLB" in labels else None)
    if want is None and labels:
        weight = t.cols.get("PA" if kind == BAT else "IP")
        want = labels[int(np.nanargmax(weight))] if weight is not None and len(weight) else labels[0]
    if want not in labels:
        return None
    idx = labels.index(want)
    values = _league_values(t.cols, idx, kind, stats)
    values["_label"] = league_label(want)
    values["_name"] = want
    return values


# ---------- leaders ----------

BOARDS = {
    BAT: [("WAR", "fWAR (FanGraphs)"), ("bWAR", "bWAR (Baseball-Reference)"), ("wRC+", "wRC+"), ("HR", "Home runs"), ("AVG", "Batting average"),
          ("OBP", "On-base percentage"), ("SB", "Stolen bases")],
    PIT: [("WAR", "fWAR (FanGraphs)"), ("bWAR", "bWAR (Baseball-Reference)"), ("ERA", "ERA"), ("ERA+", "ERA+"), ("SO", "Strikeouts"), ("FIP", "FIP"),
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


TEAM_ALWAYS = ("G", "PA", "IP")


@db.cached
def team_gaps(kind: str, lo: int, hi: int, stat: str = "bWAR") -> frozenset:
    """Clubs with a season in lo..hi that has no team bWAR (its players matched to
    Baseball-Reference cover under 95% of its PA or IP: some Negro League clubs,
    two 1875 clubs, 1884 St. Paul). Their total over the span would leave those
    seasons out, so it is shown blank instead."""
    gaps = set()
    tkind = TEAM_KIND[kind]
    for season in range(lo, hi + 1):
        col = db.column(tkind, season, stat)
        rows = db.rows("SELECT team, teamid, i FROM rows WHERE kind = ? AND season = ?", tkind, season)
        for r in rows:
            if col is False or np.isnan(col[r["i"]]):
                gaps.add(team_key(r))
    return frozenset(gaps)


def team_key(r) -> object:
    """How a span groups a club's seasons (db.table): its franchise id, else its code."""
    return r.get("teamid") or r.get("team")
TEAM_MODES = {kind: {k: v for k, v in modes.items() if k != "savant"} for kind, modes in MODES.items()}


def team_table(kind, lo, hi, mode, league, sort):
    cols = columns(kind, mode)
    stats = tuple(c["key"] for c in cols) + ("WAR",)
    t = db.table(TEAM_KIND[kind], lo, hi, tuple(dict.fromkeys(stats)))
    # Baseball Savant's stats are per player (a traded player's season is not split
    # by club), so team tables have none: keep only columns with team data.
    cols = [c for c in cols if c["key"] in TEAM_ALWAYS or (c["key"] in t.cols and not np.isnan(t.cols[c["key"]]).all())]
    gaps = team_gaps(kind, lo, hi) if hi > lo and "bWAR" in t.cols else frozenset()
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
        if team_key(r) in gaps:
            line["bWAR"] = None
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

PLAYER_MODES = {BAT: ["standard", "advanced", "value", "battedball", "discipline", "statcast", "savant"],
                PIT: ["standard", "advanced", "value", "battedball", "discipline", "statcast", "savant"]}


@db.cached
def stat_first(kind: str, stat: str) -> int | None:
    """The first season with any data for a stat (columns are stored only for
    seasons that have it): 2002 for FanGraphs plate discipline and batted
    balls, 2015 for Statcast and Savant, 1974 for WPA."""
    row = db.one("SELECT MIN(season) AS s FROM cols WHERE kind = ? AND stat = ? AND season > 0", kind, stat)
    return row["s"] if row else None


def years(lo: int, hi: int) -> str:
    """2002\u201304, 1998\u20132004, or 2003."""
    if lo == hi:
        return str(lo)
    return f"{lo}\u2013{hi % 100:02d}" if lo // 100 == hi // 100 else f"{lo}\u2013{hi}"


def partial(kind: str, stats, lo: int, hi: int) -> dict:
    """{stat: first season} for stats whose data starts inside lo..hi: a line over
    lo..hi has them for the later seasons only (Alomar's 1988-2004 career has
    plate discipline for 2002-04)."""
    out = {}
    for stat in stats:
        first = stat_first(kind, stat)
        if first is not None and lo < first <= hi:
            out[stat] = first
    return out


def partial_notes(kind: str, stats, lo: int, hi: int, have_lo: int | None = None) -> tuple[dict, list]:
    """Labels for a career or span line: ({stat: "2002\u201304"}, [{label, heads, first}])."""
    found = partial(kind, stats, lo, hi)
    labels, notes = {}, {}
    for stat, first in found.items():
        label = years(max(first, have_lo or first), hi)
        labels[stat] = label
        c = column(kind, stat)
        notes.setdefault((first, label), []).append(c["head"] if c else stat)
    return labels, [{"first": f, "label": label, "heads": heads} for (f, label), heads in sorted(notes.items())]


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
    # League averages (rates only): each season's, and the league over his seasons.
    shown = tuple(c["key"] for c in cols)
    pairs = []
    for row in seasons_rows:
        group = player_groups(kind, row["season"]).get(pid, "MLB")
        row["league"] = league_season(kind, row["season"], group, shown)
        row["lg_label"], row["lg_name"] = league_label(group), group
        pairs.append((row["season"], group))
    league_career = league_over(kind, tuple(pairs), shown) if pairs else None
    ages = [r["age"] for r in seasons_rows if r["age"]]
    weight = "PA" if kind == BAT else "IP"
    facts = {"seasons": len(seasons_rows), "qualified": sum(r["qualified"] for r in seasons_rows),
             "ages": (min(ages), max(ages)) if ages else None,
             "weight": (career or {}).get(weight) if career else sum((r["values"].get(weight) or 0) for r in seasons_rows),
             "games": (career or {}).get("G") if career else sum((r["values"].get("G") or 0) for r in seasons_rows)}
    if facts["games"] is None:
        facts["games"] = sum((r["values"].get("G") or 0) for r in seasons_rows)
    labels = {row["lg_label"] for row in seasons_rows}
    cover, notes = ({}, [])
    if len(seasons_rows) > 1:
        lo, hi = seasons_rows[0]["season"], seasons_rows[-1]["season"]
        cover, notes = partial_notes(kind, shown, lo, hi, lo)
    return {"cols": cols, "rows": seasons_rows, "career": career, "facts": facts, "league": league_career,
            "lg_label": labels.pop() if len(labels) == 1 else "League", "pairs": pairs,
            "cover": cover, "cover_notes": notes}


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
    first, last = r.get("first", lo), r.get("last", hi)
    cover, notes = partial_notes(kind, tuple(c["key"] for c in cols), first, last, first)
    return {"lo": lo, "hi": hi, "values": values, "qualified": bool(ok[idx]), "have": float(have[idx]),
            "first": first, "last": last, "n": r.get("n", 1), "cover": cover, "cover_notes": notes}


PCT_STATS = {
    BAT: [("Value", ["WAR", "bWAR", "wRC+", "Offense", "BaseRunning", "Defense"]),
          ("Hitting", ["OBP", "SLG", "ISO", "AVG", "BABIP"]),
          ("Plate skills", ["BB%", "K%", ("Chase%", "O-Swing%"), ("Whiff%", "Contact%")]),
          ("Statcast", ["xwOBA", "EV", "Barrel%", "HardHit%", "Sweet-Spot%", "AvgBatSpeed", "Sprint"])],
    PIT: [("Value", ["WAR", "bWAR", "ERA+", "FIP-", "RA9-Wins"]),
          ("Run prevention", ["ERA", "FIP", "xFIP", "SIERA", "WHIP"]),
          ("Strikeouts and walks", ["K%", "BB%", "K-BB%", ("Whiff%", "SwStr%"), ("Chase%", "O-Swing%")]),
          ("Contact", [("xwOBA", None), "GB%", "HR/9", "Barrel%", "HardHit%", "FBv"])],
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


def _pct_pick(stat, lo: int) -> str:
    """A (Savant stat, FanGraphs stat) pair takes Savant's when the seasons are all
    in the Statcast era (2015 on), so everyone is measured the same way."""
    if isinstance(stat, tuple):
        return stat[0] if lo >= 2015 else stat[1]
    return stat


@db.cached
def percentiles(pid: int, kind: str, lo: int, hi: int | None = None) -> dict | None:
    """His percentile in each stat among the qualified players of his league group
    (AL and NL together; other leagues on their own), the way Baseball Savant
    ranks them (100 = best). Over several seasons, his line for lo..hi against
    everyone's line for the same seasons, qualified by FanGraphs' multi-season
    cut, so every player is measured over the same years."""
    hi = lo if hi is None else hi
    plan = [(title, [p for p in (_pct_pick(stat, lo) for stat in group) if p]) for title, group in PCT_STATS[kind]]
    stats = tuple(s for _g, group in plan for s in group)
    t = db.table(kind, lo, hi, stats)
    idx = next((i for i, r in enumerate(t.ident) if r["pid"] == pid), None)
    if idx is None:
        return None
    def ranked(table, a, b):
        """Who he is ranked against over seasons a..b: qualified, same league group."""
        need, _have, ok = qualifying(kind, table)
        group_of = range_groups(kind, a, b)
        mine = group_of.get(pid, "MLB")
        return need, ok & np.array([group_of.get(r["pid"], "MLB") == mine for r in table.ident]), mine

    need, ok, mine = ranked(t, lo, hi)
    # Stats whose data starts after lo (plate discipline in 2002, Statcast in 2015)
    # cover only the later seasons: rank his line over those seasons against
    # everyone's line over the same seasons.
    later = {}
    for stat, first in (partial(kind, stats, lo, hi) if hi > lo else {}).items():
        later.setdefault(first, []).append(stat)
    sub = {}
    for first, group in later.items():
        t2 = db.table(kind, first, hi, tuple(group))
        i2 = next((i for i, r in enumerate(t2.ident) if r["pid"] == pid), None)
        if i2 is None:
            continue
        need2, ok2, _m = ranked(t2, first, hi)
        r2 = t2.ident[i2]
        note = {"first": first, "label": years(max(first, r2.get("first", first)), min(hi, r2.get("last", hi))),
                "pool": int(ok2.sum()), "need": float(need2[i2]), "qualified": bool(ok2[i2]), "heads": []}
        for stat in group:
            sub[stat] = (t2, i2, ok2, note)
    notes = []
    groups = []
    for title, group in plan:
        rows_out = []
        for stat in group:
            c = column(kind, stat)
            table, i, pool_ok, note = sub.get(stat, (t, idx, ok, None))
            col = table.cols.get(stat)
            if c is None or col is None or np.isnan(col[i]):
                continue
            pool = col[pool_ok & ~np.isnan(col)]
            if len(pool) < 10:
                continue
            v = col[i]
            mine_in = 1 if pool_ok[i] else 0
            below, same_v = (pool < v).sum(), (pool == v).sum()
            share = (below + max(same_v - mine_in, 0) / 2) / max(len(pool) - mine_in, 1)
            pct = round(100 * (share if c["better"] else 1 - share))
            row = {"col": c, "value": float(v), "pct": max(0, min(100, pct))}
            if note is not None:
                row["cover"] = note["label"]
                note["heads"].append(c["head"])
                if note not in notes:
                    notes.append(note)
            rows_out.append(row)
        if rows_out:
            groups.append({"title": title, "rows": rows_out})
    return {"season": lo if lo == hi else None, "lo": lo, "hi": hi, "qualified": bool(ok[idx]),
            "pool": int(ok.sum()), "groups": groups, "need": float(need[idx]),
            "group": "AL and NL" if mine == "MLB" else mine, "cover_notes": notes}


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
