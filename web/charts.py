"""The chart explorer's data, presets and old-link translation, and Compare."""
from __future__ import annotations

import numpy as np

from pipeline import teams as T

from . import db, queries

PRESETS = {
    "team": [
        ("Offense vs pitching", "pit:ERA-", "bat:wRC+"), ("Power and contact", "bat:HardHit%", "bat:Barrel%"),
        ("Plate discipline", "bat:K%", "bat:BB%"), ("Strikeouts and walks", "pit:BB%", "pit:K%"),
        ("Run prevention", "pit:FIP", "pit:ERA"), ("Hitting vs pitching fWAR", "pit:WAR", "bat:WAR"),
    ],
    "bat": [
        ("wRC+ vs fWAR", "wRC+", "WAR"), ("fWAR vs bWAR", "bWAR", "WAR"), ("Power and contact", "HardHit%", "Barrel%"),
        ("Plate discipline", "K%", "BB%"), ("Speed and contact", "SB", "AVG"),
        ("Expected vs actual", "xwOBA", "wOBA"), ("Chase and whiff", "O-Swing%", "SwStr%"),
    ],
    "pit": [
        ("Strikeouts and walks", "BB%", "K%"), ("Run prevention", "FIP", "ERA"),
        ("SIERA vs fWAR", "SIERA", "WAR"), ("fWAR vs bWAR", "bWAR", "WAR"), ("Groundballs and homers", "GB%", "HR/FB"),
        ("Velocity and whiffs", "FBv", "SwStr%"), ("Luck", "BABIP", "LOB%"),
    ],
}
DEFAULTS = {"team": ("pit:ERA-", "bat:wRC+"), "bat": ("wRC+", "WAR"), "pit": ("FIP", "ERA")}


def team_colors() -> dict:
    """Team colors, lightened where a dark color would vanish on the dark page."""
    out = {}
    for code, hexcolor in {**T.HISTORIC_COLORS, **T.TEAM_COLORS}.items():
        n = int(hexcolor[1:], 16)
        rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
        lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
        mix = 0.5 if lum < 0.35 else 0.15
        out[code] = "rgb(%d,%d,%d)" % tuple(round(c + (255 - c) * mix) for c in rgb)
    return out


def legacy_args(args) -> dict:
    """Old Dash share links (/?view=...&x_stat=...) -> /chart parameters."""
    view = "player" if str(args.get("view", "team")).lower().startswith("player") else "team"
    out = {"view": view}
    if args.get("season"):
        out["season"] = args.get("season")
    if args.get("season_end") and args.get("season_end") != args.get("season"):
        out["to"] = args.get("season_end")
    if view == "team":
        for axis in ("x", "y", "z"):
            stat = args.get(f"{axis}_stat")
            if stat:
                prefix = "pit" if str(args.get(f"{axis}_type", "Batting")).lower().startswith("pit") else "bat"
                out[axis] = f"{prefix}:{stat}"
        flags = {"color_rank": "rank", "logos": "logos", "trend": "trend", "era": "era", "traj": "path"}
        lg = args.get("league", "")
        if lg and lg != "All Teams":
            out["league"] = lg
    else:
        out["kind"] = "pit" if str(args.get("player_type", "")).lower().startswith("pitch") else "bat"
        for axis in ("x", "y", "z"):
            if args.get(f"p_{axis}_stat"):
                out[axis] = args.get(f"p_{axis}_stat")
        flags = {"p_color_rank": "rank", "p_trend": "trend", "p_era": "era", "p_traj": "path"}
        threshold = args.get("min_ip" if out["kind"] == "pit" else "min_pa")
        if threshold and threshold != "Qualified":
            out["min"] = threshold
        if args.get("team") and args.get("team") != "All Teams":
            out["team"] = args.get("team")
        if args.get("find"):
            out["find"] = args.get("find")
        if args.get("p_labels") in ("none", "all"):
            out["labels"] = {"none": "none", "all": "all"}[args.get("p_labels")]
    for old, new in flags.items():
        if args.get(old) == "true":
            out[new] = "1"
    if args.get("split") == "season":
        out["split"] = "season"
    return out


def chart_state(args) -> dict:
    view = "player" if args.get("view") == "player" else "team"
    kind = "pit" if args.get("kind") == "pit" else "bat"
    key = "team" if view == "team" else kind
    x, y = DEFAULTS[key]
    return {"view": view, "kind": kind, "x": args.get("x", x), "y": args.get("y", y), "z": args.get("z", ""),
            "season": args.get("season", ""), "to": args.get("to", ""), "split": args.get("split", ""),
            "path": args.get("path", ""), "era": args.get("era", ""), "trend": args.get("trend", ""),
            "rank": args.get("rank", ""), "logos": args.get("logos", "1" if view == "team" else ""),
            "mean": args.get("mean", "1"), "min": args.get("min", "q"), "team": args.get("team", ""),
            "league": args.get("league", ""), "pos": args.get("pos", ""), "find": args.get("find", ""),
            "labels": args.get("labels", "standouts")}


def _axis(view: str, kind: str, raw: str):
    """(kind, stat, column) for an axis value, or None."""
    if not raw:
        return None
    if view == "team":
        k, _, stat = raw.partition(":")
        if k not in ("bat", "pit") or not stat:
            k, stat = "bat", raw
    else:
        k, stat = kind, raw
    col = queries.column(k, stat)
    return (k, stat, col) if col else None


def _int(args, name, default, low, high):
    try:
        return max(low, min(high, int(args.get(name, default))))
    except (TypeError, ValueError):
        return default


def _percentiles(values: np.ndarray, pool: np.ndarray, better: bool) -> np.ndarray:
    """Each value's percentile (0-100, 100 = best) within the pool."""
    ref = np.sort(pool[~np.isnan(pool)])
    out = np.full(len(values), np.nan)
    if len(ref) == 0:
        return out
    ok = ~np.isnan(values)
    below = np.searchsorted(ref, values[ok], side="left")
    above = np.searchsorted(ref, values[ok], side="right")
    pct = (below + above) / 2 / len(ref) * 100
    out[ok] = pct if better else 100 - pct
    return out


@db.cached
def cached_payload(items: tuple) -> dict:
    return chart_payload({k: v for k, v in items if v != ""})


def chart_payload(args) -> dict:
    view = "player" if args.get("view") == "player" else "team"
    kind = "pit" if args.get("kind") == "pit" else "bat"
    latest, first = queries.latest_season(), db.first_season()
    lo = _int(args, "season", latest, first, latest)
    hi = _int(args, "to", lo, first, latest)
    lo, hi = queries.span(lo, hi)
    split = args.get("split") == "season" or args.get("path") == "1"
    era = args.get("era") == "1"
    axes = {}
    for a in ("x", "y", "z"):
        got = _axis(view, kind, args.get(a, ""))
        if got:
            axes[a] = got
    if "x" not in axes or "y" not in axes:
        return {"error": "Pick two stats."}
    # Which seasons each axis has data for (Statcast starts in 2015, and so on).
    have = {a: db.catalog(k).get(stat) for a, (k, stat, _c) in axes.items()}
    notes = []
    for a, info in have.items():
        if info and (info["first"] > hi or info["last"] < lo):
            return {"error": f"{axes[a][1]} has data for {info['first']}\u2013{info['last']} only."}
        if info and info["first"] > lo:
            notes.append(f"{axes[a][1]} starts in {info['first']}.")
    seasons_list = [(s, s) for s in range(lo, hi + 1)] if (split or era) else [(lo, hi)]
    if view == "team":
        rows = _team_rows(axes, seasons_list, args, era)
    else:
        rows = _player_rows(kind, axes, seasons_list, args, era)
    if era and not split and lo != hi and view == "team":
        rows = _combine_era(rows)
    rows = [r for r in rows if r["x"] is not None and r["y"] is not None and ("z" not in axes or r["z"] is not None)]
    if len(rows) > 20000:
        return {"error": f"That is {len(rows):,} points, more than the chart can draw well. "
                         "Narrow the seasons or raise the minimum."}
    out_axes = {}
    for a, (k, stat, c) in axes.items():
        out_axes[a] = {"key": stat, "kind": k, "label": (("Hitting " if k == "bat" else "Pitching ") + c["head"])
                       if view == "team" else c["head"], "name": c["name"],
                       "fmt": "pctl" if era else c["fmt"], "better": c["better"], "rule": c["rule"]}
    fields = ["id", "name", "team", "season", "logo", "x", "y", "z", "w", "first", "last", "lg"]
    return {"view": view, "kind": kind, "lo": lo, "hi": hi, "split": split, "era": era,
            "axes": out_axes, "fields": fields,
            "rows": [[r.get(f) for f in fields] for r in rows], "count": len(rows),
            "label": queries.span_label(lo, hi), "notes": notes,
            "qualified": args.get("min", "q") == "q" and any(c["rule"] for _k, _s, c in axes.values()),
            "need": _need_text(view, kind, lo, lo if split else hi, args,
                               any(c["rule"] for _k, _s, c in axes.values()))}


def _need_text(view, kind, lo, hi, args, rated=True):
    if view == "team":
        return ""
    if not rated and args.get("min", "q") == "q":
        return "No minimum: both stats are counts"
    if args.get("min", "q") == "q":
        n = queries.need_for(kind, lo, hi)
        unit = "PA" if kind == "bat" else "IP"
        return f"Qualified: {n:,} {unit}" + (" per season" if lo == hi else "")
    return f"At least {args.get('min')} {'PA' if kind == 'bat' else 'IP'}"


def _clean(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 5)


def _player_rows(kind, axes, seasons_list, args, era):
    """Points for the player view. With era on, every season is ranked against
    that season's qualified players, and the minimum is applied afterwards
    (per season when split, to the span's totals when combined)."""
    min_raw = args.get("min", "q")
    min_mode, min_value = ("q", 0) if min_raw == "q" else ("n", float(min_raw) if _num(min_raw) else 0)
    stats = tuple(dict.fromkeys(s for _k, s, _c in axes.values()))
    rated = any(c["rule"] for _k, _s, c in axes.values())
    split = len(seasons_list) > 1 and args.get("split") == "season" or args.get("path") == "1"
    out = []
    for lo, hi in seasons_list:
        lines, _info = queries.lines_for(kind, lo, hi, stats, min_mode="n", min_value=0 if lo != hi else 1,
                                         team=args.get("team", ""), league=args.get("league", ""),
                                         pos=args.get("pos", ""))
        if era:
            # The pool is every qualified player in his league group that season,
            # whatever the team, league or position filter shows.
            pools = queries.season_pools(kind, lo, stats)
            group_of = queries.player_groups(kind, lo)
            for a, (_k, stat, c) in axes.items():
                for g in {group_of.get(l["pid"], "MLB") for l in lines}:
                    members = [l for l in lines if group_of.get(l["pid"], "MLB") == g]
                    pool = pools.get(g, {}).get(stat, np.array([]))
                    mine = np.array([l.get(stat) if l.get(stat) is not None else np.nan for l in members])
                    pct = _percentiles(mine, pool, c["better"])
                    for l, p in zip(members, pct):
                        l["_" + a] = None if np.isnan(p) else float(p)
        for l in lines:
            if min_mode == "q":
                ok = l["qualified"] or not rated
            else:
                ok = (l["have"] or 0) >= min_value
            if (not era or split or lo == hi and len(seasons_list) == 1) and not ok:
                continue
            row = {"id": l["pid"], "name": l["name"], "team": l["team"], "season": lo if lo == hi else None,
                   "first": l.get("first"), "last": l.get("last"),
                   "w": _clean(l.get("PA" if kind == "bat" else "IP")),
                   "logo": queries.logo_url(l["team"], l.get("season")) if l["team"] != T.MULTI_TEAM else None}
            for a, (_k, stat, _c) in axes.items():
                row[a] = _clean(l.get("_" + a) if era else l.get(stat))
            out.append(row)
    if era and not split and len(seasons_list) > 1:
        lo, hi = seasons_list[0][0], seasons_list[-1][1]
        out = _combine_era(out)
        if min_mode == "q" and rated:
            need = queries.need_for(kind, lo, hi)
            out = [r for r in out if (r.get("w") or 0) >= need]
        elif min_mode == "n":
            out = [r for r in out if (r.get("w") or 0) >= min_value]
    return out


def _num(text):
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def _team_rows(axes, seasons_list, args, era):
    league = args.get("league", "")
    out = []
    for lo, hi in seasons_list:
        by_team: dict = {}
        for a, (k, stat, c) in axes.items():
            t = db.table(queries.TEAM_KIND[k], lo, hi, (stat, "PA" if k == "bat" else "IP"))
            col = t.cols[stat]
            pct = None
            if era:   # each club against the clubs of its league group that season
                pct = np.full(len(col), np.nan)
                group = np.array([T.league_group(r["team"], lo) for r in t.ident])
                for g in set(group):
                    m = group == g
                    pct[m] = _percentiles(col[m], col[m], c["better"])
            for i, r in enumerate(t.ident):
                key = r["teamid"] if lo != hi else r["team"]
                row = by_team.setdefault(key, {"team": r["team"], "season": r.get("last") or lo,
                                               "first": r.get("first", lo), "last": r.get("last", hi)})
                v = pct[i] if era else col[i]
                row[a] = _clean(v)
                if k == "bat":
                    row["w"] = _clean(t.cols["PA"][i])
        for key, row in by_team.items():
            code, season = row["team"], row["season"]
            if league and T.league(code, season) != league and T.division(code, season) != league:
                continue
            out.append({"id": key if isinstance(key, int) else code, "name": T.team_name(code, season),
                        "lg": T.league_name(code, season),
                        "team": code, "season": lo if lo == hi else None, "first": row["first"],
                        "last": row["last"], "logo": queries.logo_url(code, season), "w": row.get("w"),
                        **{a: row.get(a) for a in axes}})
    return out


def _combine_era(rows):
    """Season percentiles -> one point per player or team, weighted by PA (or IP)."""
    groups: dict = {}
    for r in rows:
        g = groups.setdefault(r["id"], {**r, "_n": {}, "_d": {}, "first": r["season"], "last": r["season"]})
        w = r.get("w") or 1.0
        for a in ("x", "y", "z"):
            if r.get(a) is not None:
                g["_n"][a] = g["_n"].get(a, 0.0) + r[a] * w
                g["_d"][a] = g["_d"].get(a, 0.0) + w
        g["_w"] = g.get("_w", 0.0) + (r.get("w") or 0.0)
        if (r["season"] or 0) >= (g["last"] or 0):
            g.update(team=r["team"], logo=r["logo"], name=r["name"], last=r["season"], lg=r.get("lg"))
        g["first"] = min(g["first"], r["season"])
    out = []
    for g in groups.values():
        row = {k: v for k, v in g.items() if not k.startswith("_")}
        for a in ("x", "y", "z"):
            row[a] = round(g["_n"][a] / g["_d"][a], 2) if g["_d"].get(a) else None
        row["season"] = None
        row["w"] = round(g.get("_w", 0.0), 1)
        out.append(row)
    return out


# ---------- compare ----------

COMPARE_STATS = {
    "bat": ["G", "PA", "HR", "R", "RBI", "SB", "AVG", "OBP", "SLG", "OPS", "BB%", "K%", "ISO", "wOBA",
            "wRC+", "Batting", "BaseRunning", "Fielding", "WAR", "bWAR"],
    "pit": ["W", "L", "G", "GS", "SV", "IP", "SO", "ERA", "WHIP", "K%", "BB%", "K-BB%", "HR/9", "FIP",
            "xFIP", "SIERA", "ERA-", "WAR", "bWAR"],
}


def compare(pids, kind, lo, hi) -> dict:
    stats = tuple(COMPARE_STATS[kind])
    t = db.table(kind, lo, hi, stats)
    index = {r["pid"]: i for i, r in enumerate(t.ident)}
    people = queries.people()
    players, values = [], {s: [] for s in stats}
    for pid in pids:
        p = people.get(pid)
        if p is None:
            continue
        i = index.get(pid)
        players.append({"pid": pid, "name": p["name"], "mlbam": p["mlbam"],
                        "span": f"{t.ident[i].get('first', lo)}\u2013{t.ident[i].get('last', hi)}" if i is not None and lo != hi else str(lo),
                        "team": t.ident[i]["team"] if i is not None else None, "missing": i is None})
        for s in stats:
            v = t.cols[s][i] if i is not None else np.nan
            values[s].append(None if np.isnan(v) else float(v))
    rows = []
    for s in stats:
        c = queries.column(kind, s)
        if c is None:
            continue
        vals = values[s]
        present = [v for v in vals if v is not None]
        best = (max(present) if c["better"] else min(present)) if len(present) > 1 else None
        rows.append({"col": c, "values": vals, "best": best})
    return {"players": players, "rows": rows}
