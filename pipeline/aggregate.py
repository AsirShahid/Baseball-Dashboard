"""Roll season rows up into ranges (careers, spans) and rosters.

Shared by the builder (careers) and the site (any season range). Counting
stats add up; rates are averaged by what they are measured over (plate
appearances, innings, pitches or batted balls); the classic ratios (AVG,
OBP, SLG, ERA, WHIP, K%, ...) are rebuilt from the summed parts, so a
career AVG is hits over at bats, not an average of averages.
"""
from __future__ import annotations

import numpy as np

from . import catalog, savant

def _weights(cols: dict, family: str, pitching: bool, n: int):
    base = cols.get("IP" if pitching else "PA")
    if family in ("Events", "Pitches") and family in cols:
        return cols[family]
    if family == "Pitches" and pitching and "TBF" in cols:
        return cols["TBF"]
    return base if base is not None else np.ones(n, dtype=np.float64)


def group_rows(keys: np.ndarray, cols: dict, pitching: bool, skip=("Age",)):
    """Aggregate rows sharing a key. Returns (unique_keys, first_index, cols)."""
    keys = np.asarray(keys)
    uniq, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    m = len(uniq)
    out = {}
    weight_cache = {}
    for stat, values in cols.items():
        if stat in skip:
            continue
        v = np.asarray(values, dtype=np.float64)
        have = ~np.isnan(v)
        filled = np.where(have, v, 0.0)
        count = np.bincount(inverse, weights=have.astype(np.float64), minlength=m)
        if stat == "maxEV":
            res = np.full(m, -np.inf)
            np.maximum.at(res, inverse, np.where(have, v, -np.inf))
            out[stat] = np.where(count > 0, res, np.nan)
            continue
        if catalog.is_counting(stat) or stat in ("TG", "PA", "IP", "TBF"):
            total = np.bincount(inverse, weights=filled, minlength=m)
            out[stat] = np.where(count > 0, total, np.nan)
            continue
        family = catalog.weight(stat, pitching)
        if family not in weight_cache:
            w = _weights(cols, family, pitching, len(v))
            weight_cache[family] = np.where(np.isnan(w), 0.0, np.asarray(w, dtype=np.float64))
        w = weight_cache[family]
        num = np.bincount(inverse, weights=filled * w, minlength=m)
        den = np.bincount(inverse, weights=have * w, minlength=m)
        plain = np.bincount(inverse, weights=filled, minlength=m) / np.maximum(count, 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            res = np.where(den > 0, num / np.where(den > 0, den, 1), plain)
        out[stat] = np.where(count > 0, res, np.nan)
    rebuild_rates(out, pitching)
    return uniq, first, out


def rebuild_rates(c: dict, pitching: bool) -> None:
    """Rewrite the classic ratios from summed counts, where the parts exist."""
    def g(name):
        return c.get(name)

    def div(a, b):
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)

    def put(name, value):
        if name in c:
            c[name] = value

    # Barrels per PA (per batter faced for pitchers).
    if g("Barrels") is not None and g("TBF" if pitching else "PA") is not None:
        put("Barrel/PA", div(g("Barrels"), g("TBF" if pitching else "PA")))
    # Baseball Savant: every shown stat rebuilt from its counts, as Savant builds
    # its Player and MLB rows; a row with no Savant counts keeps its value.
    if all(g(p) is not None for p in savant.PARTS):
        rebuilt = savant.rates(c, pitching)
        for name, value in rebuilt.items():
            if name in c:
                c[name] = np.where(np.isnan(value), c[name], value)

    if pitching:
        ip, tbf = g("IP"), g("TBF")
        if ip is not None:
            for out, part, scale in (("ERA", "ER", 9), ("K/9", "SO", 9), ("BB/9", "BB", 9),
                                     ("HR/9", "HR", 9), ("H/9", "H", 9)):
                if g(part) is not None:
                    put(out, div(g(part) * scale, ip))
            if g("BB") is not None and g("H") is not None:
                put("WHIP", div(g("BB") + g("H"), ip))
        if tbf is not None:
            if g("SO") is not None:
                put("K%", div(g("SO"), tbf))
            if g("BB") is not None:
                put("BB%", div(g("BB"), tbf))
            if "K%" in c and "BB%" in c:
                put("K-BB%", c["K%"] - c["BB%"])
        if g("SO") is not None and g("BB") is not None:
            put("K/BB", div(g("SO"), g("BB")))
        if g("ERlg") is not None and g("bER") is not None:
            put("ERA+", div(100 * g("ERlg"), g("bER")))      # Baseball-Reference's career ERA+
        return
    ab, pa = g("AB"), g("PA")
    parts = {k: g(k) for k in ("H", "1B", "2B", "3B", "HR", "BB", "HBP", "SF", "SO")}
    # Sacrifice flies were not recorded before 1954 (and HBP is missing in a few
    # early seasons): count them as 0, as FanGraphs does, or every pre-1954 span
    # loses its OBP, OPS and BABIP.
    for k in ("HBP", "SF"):
        if parts[k] is not None:
            parts[k] = np.where(np.isnan(parts[k]), 0.0, parts[k])
    if ab is not None:
        if parts["H"] is not None:
            put("AVG", div(parts["H"], ab))
        if all(parts[k] is not None for k in ("1B", "2B", "3B", "HR")):
            tb = parts["1B"] + 2 * parts["2B"] + 3 * parts["3B"] + 4 * parts["HR"]
            put("SLG", div(tb, ab))
            put("ISO", div(parts["2B"] + 2 * parts["3B"] + 3 * parts["HR"], ab))
        if all(parts[k] is not None for k in ("H", "HR", "SO", "SF")):
            put("BABIP", div(parts["H"] - parts["HR"], ab - parts["SO"] - parts["HR"] + parts["SF"]))
        if all(parts[k] is not None for k in ("H", "BB", "HBP", "SF")):
            put("OBP", div(parts["H"] + parts["BB"] + parts["HBP"],
                           ab + parts["BB"] + parts["HBP"] + parts["SF"]))
        if "OBP" in c and "SLG" in c:
            put("OPS", c["OBP"] + c["SLG"])
    if pa is not None:
        if parts["SO"] is not None:
            put("K%", div(parts["SO"], pa))
        if parts["BB"] is not None:
            put("BB%", div(parts["BB"], pa))
    if parts["BB"] is not None and parts["SO"] is not None:
        put("BB/K", div(parts["BB"], parts["SO"]))
