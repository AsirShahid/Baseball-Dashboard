"""Formatting numbers the way baseball writes them."""
from __future__ import annotations

import math


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def ip_notation(innings) -> str:
    """True innings -> 177.2 (two outs)."""
    v = _num(innings)
    if v is None:
        return ""
    outs = round(v * 3)
    return f"{outs // 3:,}.{outs % 3}"


def fmt(value, kind: str = "d2", stat: str = "") -> str:
    """kind: pct1 (fraction -> 24.3%), avg (.263), d0, d1, d2, ip, s1 (signed)."""
    v = _num(value)
    if v is None:
        return ""
    if stat == "IP" or kind == "ip":
        return ip_notation(v)
    if kind == "pct1":
        return f"{v * 100:.1f}%"
    if kind == "avg":
        text = f"{v:.3f}"
        return text[1:] if text.startswith("0.") else ("-" + text[2:] if text.startswith("-0.") else text)
    if kind == "d0":
        return f"{v:,.0f}"
    if kind == "d1":
        return f"{v:,.1f}"
    if kind == "s1":
        return f"{v:+.1f}"
    if kind == "s0":
        return f"{v:+,.0f}"
    if kind == "p3":   # winning percentage
        text = f"{v:.3f}"
        return text[1:] if text.startswith("0.") else text
    return f"{v:,.2f}"


def sort_value(value) -> str:
    v = _num(value)
    return "" if v is None else repr(round(v, 6))
