"""Long tables a page at a time: ?page=, ?per= (rows a page), ?sort= with ?dir=, ?find=.

A table with more rows than one page is sorted and searched here, across all its pages
(app.js sends a header tap or Enter in "Find a player" to the server); one that fits a
page still sorts and filters in the browser at once. The same file runs on
basketball.asir.dev and baseball.asir.dev.
"""
from __future__ import annotations

import math

from flask import request

from pipeline.text import search_key

PER_PAGE = (50, 100, 200, 500, 1000)
DEFAULT_PER = 200


def find(lines: list[dict]) -> tuple[list[dict], str]:
    """Rows whose name has every typed word (accents and case ignored), and the text."""
    text = (request.args.get("find") or "").strip()
    words = search_key(text).split()
    if not words:
        return lines, ""
    return [line for line in lines if all(word in search_key(line.get("name") or "") for word in words)], text


def direction(default_desc: bool) -> bool:
    """True for high to low: ?dir=asc|desc, else the column's own direction."""
    asked = request.args.get("dir")
    return default_desc if asked not in ("asc", "desc") else asked == "desc"


def ordered(lines: list[dict], key: str, desc: bool, short=None, text: bool = False) -> list[dict]:
    """Sorted by one column; rows without a value (or short(line) true: not qualified for
    it) go last either way. Ties keep their order."""
    short = short or (lambda line: False)
    if text:
        have = [line for line in lines if line.get(key) not in (None, "") and not short(line)]
        ids = {id(line) for line in have}
        rest = [line for line in lines if id(line) not in ids]
        have.sort(key=lambda line: search_key(str(line.get(key))), reverse=desc)
        return have + rest
    have = [line for line in lines if isinstance(line.get(key), (int, float)) and not short(line)]
    ids = {id(line) for line in have}
    rest = [line for line in lines if id(line) not in ids]
    have.sort(key=lambda line: line[key], reverse=desc)
    return have + rest


def page(lines: list[dict]) -> dict:
    """One page of the rows: {rows, page, pages, per, start, total}."""
    try:
        per = int(request.args.get("per") or DEFAULT_PER)
    except ValueError:
        per = DEFAULT_PER
    per = per if per in PER_PAGE else DEFAULT_PER
    total = len(lines)
    pages = max(1, math.ceil(total / per))
    try:
        number = int(request.args.get("page") or 1)
    except ValueError:
        number = 1
    number = min(max(number, 1), pages)
    start = (number - 1) * per
    return {"rows": lines[start:start + per], "page": number, "pages": pages, "per": per,
            "start": start, "total": total, "options": PER_PAGE}
