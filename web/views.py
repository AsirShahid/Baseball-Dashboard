"""Page routes."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for

from pipeline import teams as T

from . import charts, db, queries

bp = Blueprint("site", __name__)
KINDS = {"bat": "Batting", "pit": "Pitching"}


@bp.before_request
def need_database():
    if request.endpoint in ("site.health",):
        return None
    if not db.available():
        return render_template("message.html", title="Building the database",
                               text="The stats database is being built. Try again in a few minutes."), 503
    return None


@bp.route("/healthz")
def health():
    return {"ok": db.available(), "latest": db.latest() if db.available() else None}


def _int(name: str, default: int, low: int = 0, high: int = 100_000) -> int:
    try:
        return max(low, min(high, int(request.args.get(name, default))))
    except (TypeError, ValueError):
        return default


def _choice(name: str, options, default):
    value = request.args.get(name, default)
    return value if value in options else default


def _span():
    """(lo, hi) from ?season= and ?to= (or ?span=career)."""
    latest = queries.latest_season()
    first = db.first_season()
    if request.args.get("span") == "career":
        return first, latest
    lo = _int("season", latest, first, latest)
    hi = _int("to", lo, first, latest)
    return queries.span(lo, hi)


def _kind():
    return _choice("kind", KINDS, "bat")


def _min(kind):
    """('q', 0) for Qualified, else ('n', number)."""
    raw = request.args.get("min", "q")
    if raw == "q":
        return "q", 0
    try:
        value = max(0.0, min(20000.0, float(raw)))
        return "n", int(value) if value.is_integer() else value
    except ValueError:
        return "q", 0


# FanGraphs' minimum PA/IP ladder, the same for both and for seasons and spans
# (with "Qualified", 62 options): fine steps to 250, 50s to 1,000, 500s to 10,000.
LADDER = [0, 1, 5, 10] + list(range(20, 251, 10)) + list(range(300, 1001, 50)) + list(range(1500, 10001, 500))


def min_options(kind: str, span: bool, value=None) -> list:
    options = list(LADDER)
    if value is not None and value not in options:
        options = sorted(set(options) | {value})
    return options


@bp.route("/")
def home():
    if any(key in request.args for key in ("view", "x_stat", "p_x_stat", "season_end", "x_type",
                                           "player_type")):
        return redirect(url_for("site.chart", **charts.legacy_args(request.args)), 301)
    season = _int("season", queries.latest_season(), db.first_season(), queries.latest_season())
    fav_code = current_app.config["FAVORITE_TEAM"]
    fav = queries.team_page(fav_code, season, "standard", "standard") if fav_code else None
    return render_template("home.html", season=season, leaders=queries.leaders(season),
                           standings=queries.standings(season), fav=fav, meta=db.meta())


@bp.route("/standings")
def standings():
    season = _int("season", queries.latest_season(), db.first_season(), queries.latest_season())
    return render_template("standings.html", season=season, groups=queries.standings(season),
                           other=T.other_leagues(season))


@bp.route("/players")
def players():
    kind = _kind()
    lo, hi = _span()
    mode = _choice("mode", queries.MODES[kind], "standard")
    min_mode, min_value = _min(kind)
    team = request.args.get("team", "")
    league = _choice("league", ("", "AL", "NL"), "")
    pos = request.args.get("pos", "")
    lines, cols, sort, info = queries.player_table(kind, lo, hi, mode, min_mode, min_value, team, league,
                                                   pos, request.args.get("sort", ""))
    shown = int(min_value) if min_mode == "n" and float(min_value).is_integer() else min_value
    options = min_options(kind, lo != hi, shown if min_mode == "n" else None)
    clubs = sorted({(code, r["name"]) for s in range(lo, hi + 1)
                    for code, r in queries.team_seasons(s).items()}, key=lambda x: x[1])
    return render_template("players.html", kind=kind, lo=lo, hi=hi, mode=mode, modes=queries.MODES[kind],
                           lines=lines, cols=cols, sort=sort, info=info, min_mode=min_mode,
                           min_value=min_value, min_options=options, team=team, league=league, pos=pos,
                           positions=queries.POSITIONS if kind == "bat" else queries.ROLES, clubs=clubs,
                           kinds=KINDS)


@bp.route("/teams")
def teams():
    kind = _kind()
    lo, hi = _span()
    mode = _choice("mode", queries.MODES[kind], "standard")
    league = _choice("league", ("", "AL", "NL"), "")
    lines, cols, sort = queries.team_table(kind, lo, hi, mode, league, request.args.get("sort", ""))
    return render_template("teams.html", kind=kind, lo=lo, hi=hi, mode=mode, modes=queries.MODES[kind],
                           lines=lines, cols=cols, sort=sort, league=league, kinds=KINDS)


@bp.route("/player/<int:pid>")
def player(pid: int):
    info = queries.player_info(pid)
    if info is None:
        abort(404)
    bmode = _choice("bmode", queries.MODES["bat"], "standard")
    pmode = _choice("pmode", queries.MODES["pit"], "standard")
    batting = queries.player(pid, "bat", bmode) if info["has_bat"] else None
    pitching = queries.player(pid, "pit", pmode) if info["has_pit"] else None
    order = ["pit", "bat"] if info["primary"] == "pit" else ["bat", "pit"]
    main = pitching if info["primary"] == "pit" and pitching else (batting or pitching)
    pkind = "pit" if main is pitching else "bat"
    # A span of his seasons, picked by tapping two seasons in a table (?from=&to=).
    played = sorted({r["season"] for t in (batting, pitching) if t for r in t["rows"]})
    span = None
    lo_raw, hi_raw = request.args.get("from", ""), request.args.get("to", "")
    if played and lo_raw.isdigit() and hi_raw.isdigit():
        lo, hi = sorted((int(lo_raw), int(hi_raw)))
        lo, hi = max(lo, played[0]), min(hi, played[-1])
        if lo <= hi:
            span = (lo, hi)
    span_rows = {}
    if span:
        for kind, table, mode in (("bat", batting, bmode), ("pit", pitching, pmode)):
            if table:
                span_rows[kind] = queries.player_span(pid, kind, mode, span[0], span[1])
    pct_seasons = [r["season"] for r in reversed(main["rows"])] if main else []
    qualified = [r["season"] for r in reversed(main["rows"]) if r["qualified"]] if main else []
    choice = request.args.get("pseason", "")
    if not choice:
        choice = "span" if span else str(qualified[0] if qualified else (pct_seasons[0] if pct_seasons else ""))
    pct = None
    if pct_seasons:
        seasons = sorted(pct_seasons)
        if choice == "career":
            pct = queries.percentiles(pid, pkind, seasons[0], seasons[-1])
            if pct:
                pct = {**pct, "label": "Career"}
        elif choice == "span" and span:
            pct = queries.percentiles(pid, pkind, span[0], span[1])
            if pct:
                pct = {**pct, "label": f"{span[0]}\u2013{span[1]}"}
        if pct is None:
            season = int(choice) if choice.isdigit() and int(choice) in pct_seasons else pct_seasons[0]
            choice = str(season)
            pct = queries.percentiles(pid, pkind, season)
    return render_template("player.html", p=info, batting=batting, pitching=pitching, order=order,
                           bmode=bmode, pmode=pmode, modes=queries.MODES, main=main, pkind=pkind,
                           pct=pct, pct_seasons=pct_seasons, pchoice=choice, span=span, span_rows=span_rows)


@bp.route("/team/<code>")
def team(code: str):
    code = code.upper() if code.upper() in T.TEAM_FULL_NAME or len(code) <= 3 else code
    season = request.args.get("season")
    rows = db.rows("SELECT season, team, teamid FROM team_seasons WHERE team = ? ORDER BY season DESC", code)
    if not rows:
        abort(404)
    if season is None:
        season = rows[0]["season"]
    else:
        try:
            season = int(season)
        except ValueError:
            abort(404)
        if not any(r["season"] == season for r in rows):
            # Same franchise under another code that season (Brooklyn -> Los Angeles).
            other = db.one("SELECT team FROM team_seasons WHERE teamid = ? AND season = ?", rows[0]["teamid"], season)
            if other:
                return redirect(url_for("site.team", code=other["team"], season=season))
            season = rows[0]["season"]
    bmode = _choice("bmode", queries.MODES["bat"], "standard")
    pmode = _choice("pmode", queries.MODES["pit"], "standard")
    page = queries.team_page(code, season, bmode, pmode)
    if page is None:
        abort(404)
    return render_template("team.html", t=page, season=season, bmode=bmode, pmode=pmode,
                           modes=queries.MODES, seasons_here=[r["season"] for r in rows])


@bp.route("/compare")
def compare():
    pids = []
    for part in request.args.get("p", "").split(","):
        if part.strip().isdigit() and int(part) not in pids:
            pids.append(int(part))
    pids = pids[:4]
    kind = _kind()
    lo, hi = _span() if request.args.get("season") or request.args.get("span") else (db.first_season(), queries.latest_season())
    data = charts.compare(pids, kind, lo, hi) if pids else None
    return render_template("compare.html", pids=pids, kind=kind, lo=lo, hi=hi, data=data, kinds=KINDS)


@bp.route("/chart")
def chart():
    menus = {k: [[title, [[c["key"], c["name"], c["fmt"], c["better"], c["head"]] for c in cols]]
                 for title, cols in queries.stat_menu(k)] for k in ("bat", "pit")}
    latest = queries.latest_season()
    teams_now = sorted(((code, r["name"]) for code, r in queries.team_seasons(latest).items()),
                       key=lambda x: x[1])
    return render_template("chart.html", state=charts.chart_state(request.args), menus=menus,
                           presets=charts.PRESETS, teams_now=teams_now, colors=charts.team_colors())


@bp.route("/api/chart")
def chart_data():
    keys = ("view", "kind", "x", "y", "z", "season", "to", "split", "path", "era", "min", "team", "league", "pos")
    return jsonify(charts.cached_payload(tuple((k, request.args.get(k, "")) for k in keys)))


@bp.route("/api/search")
def search():
    return jsonify(queries.search(request.args.get("q", "")[:60]))


@bp.route("/about")
def about():
    return render_template("about.html", meta=db.meta())
