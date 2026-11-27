"""Stat ranges for the players and teams tables: ?f=HR:30:,K%::20,ERA:2.5:3.5.

Each part keeps rows whose value, as the table shows it (K% 24.3, AVG .300, IP 150.1 for
150 1/3), is at least the first number and at most the second; either end may be empty.
Any stat in the catalog works (on Teams, any the team lines have); one the view does not
show is added as a column. Under
Qualified a rate stat also needs the player qualified, as for the leaders. Same idea and
same URL as basketball.asir.dev.
"""
from __future__ import annotations

import math

from . import db, queries

MAX = 8


def _number(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def _plain(value: float) -> str:
    return f"{value:g}" if abs(value) < 1e6 else f"{value:.0f}"


def _rate(value: float) -> str:
    """.290, as baseball writes AVG and PCT."""
    text = f"{value:.3f}"
    return text[1:] if text.startswith("0.") else ("-" + text[2:] if text.startswith("-0.") else text)


def innings(typed: float) -> float:
    """150.1 typed as innings is 150 1/3, as box scores write it."""
    whole = math.floor(typed)
    tenth = round((typed - whole) * 10, 6)
    return whole + tenth / 3 if tenth in (1, 2) else typed


def shown(value, fmt: str):
    """A value in the units and rounding the table shows."""
    if value is None:
        return None
    if fmt == "pct1":
        return round(value * 100, 1)
    if fmt in ("avg", "p3"):
        return round(value, 3)
    if fmt in ("d0", "s0"):
        return round(value)
    if fmt in ("d1", "s1"):
        return round(value, 1)
    if fmt == "ip":
        return round(value * 3) / 3
    return round(value, 2)


def columns_for(kind: str, team: bool = False) -> dict:
    """stat -> column, in the order of the stat menu, with its group title."""
    return _columns_for(kind, bool(team))


@db.cached
def _columns_for(kind: str, team: bool) -> dict:      # db.cached takes positional arguments only
    out = {}
    if team:    # the record columns every team table shows
        for key, head, name, fmt, better in (("pct", "PCT", "Winning percentage", "p3", True),
                                             ("w", "W", "Wins", "d0", True), ("l", "L", "Losses", "d0", False)):
            out[key] = {"key": key, "head": head, "name": name, "fmt": fmt, "better": better, "rule": None,
                        "group": "record", "title": "Record"}
    # Teams: only stats the team lines have. Baseball Savant's (Chase%, xwOBAcon, ...) are per
    # player, not split by club, so team tables never show them (queries.team_table).
    held = _team_stats(queries.TEAM_KIND[kind]) if team else None
    for title, cols in queries.stat_menu(kind):
        for column in cols:
            if column and (held is None or column["key"] in held):
                out[column["key"]] = dict(column, title=title)
    return out


@db.cached
def _team_stats(kind: str) -> frozenset:
    return frozenset(r["stat"] for r in db.rows("SELECT DISTINCT stat FROM cols WHERE kind = ?", kind))


def groups_for(kind: str, team: bool = False) -> list[tuple[str, list[dict]]]:
    out: dict = {}
    for column in columns_for(kind, team).values():
        out.setdefault(column["title"], []).append(column)
    return list(out.items())


def parse(raw: str | None, columns: dict) -> list[dict]:
    """'HR:30:,K%::20' -> [{key, lo, hi, column, part}]. Bad parts are dropped, reversed
    ends swapped, a stat named twice keeps the last; at most MAX."""
    found: dict = {}
    for part in (raw or "").split(","):
        bits = part.strip().split(":")
        if len(bits) != 3 or bits[0] not in columns:
            continue
        lo, hi = _number(bits[1]), _number(bits[2])
        if lo is None and hi is None:
            continue
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        key = bits[0]
        found.pop(key, None)
        found[key] = {"key": key, "lo": lo, "hi": hi, "column": columns[key],
                      "part": f"{key}:{'' if lo is None else _plain(lo)}:{'' if hi is None else _plain(hi)}"}
    return list(found.values())[-MAX:]


def text(flt: dict) -> str:
    """'HR ≥ 30', 'K% ≤ 20', 'ERA 2.5–3.5', 'AVG .270–.300'."""
    name, lo, hi = flt["column"]["head"], flt["lo"], flt["hi"]
    show = _rate if flt["column"]["fmt"] in ("avg", "p3") else _plain
    if lo is not None and hi is not None:
        return f"{name} {show(lo)}\u2013{show(hi)}"
    if lo is not None:
        return f"{name} \u2265 {show(lo)}"
    return f"{name} \u2264 {show(hi)}"


def passes(line: dict, flt: dict, qualified: bool = False) -> bool:
    column = flt["column"]
    if qualified and column.get("rule") and column["rule"] in line.get("fails", {}):
        return False
    value = shown(line.get(flt["key"]), column["fmt"])
    if value is None:
        return False
    lo, hi = flt["lo"], flt["hi"]
    if column["fmt"] == "ip":
        lo = None if lo is None else innings(lo)
        hi = None if hi is None else innings(hi)
    eps = 1e-9
    return (lo is None or value >= lo - eps) and (hi is None or value <= hi + eps)


def apply(raw: str | None, kind: str, cols: list[dict], team: bool = False) -> tuple[list[dict], list[dict]]:
    """(ranges, the view's columns plus one for each ranged stat it lacks). Each range
    gets its chip text and the parameter without it."""
    ranges = parse(raw, columns_for(kind, team))
    own = {c["key"] for c in cols} | ({"pct", "w", "l"} if team else set())
    cols = cols + [r["column"] for r in ranges if r["key"] not in own]
    for flt in ranges:
        flt["text"] = text(flt)
        flt["rest"] = ",".join(other["part"] for other in ranges if other is not flt)
    return ranges, cols
