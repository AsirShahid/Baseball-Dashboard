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
        return "n", max(0, float(raw))
    except ValueError:
        return "q", 0


MIN_OPTIONS = {"bat": ([0, 1, 10, 25, 50, 100, 150, 200, 250, 300, 400, 502, 600],
                       [1000, 1500, 2000, 3000, 4000, 5000, 7500, 10000]),
               "pit": ([0, 1, 10, 20, 30, 40, 50, 70, 100, 130, 162, 200],
                       [300, 500, 750, 1000, 1500, 2000, 3000])}


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
    short, long_ = MIN_OPTIONS[kind]
    options = short + (long_ if lo != hi else [])
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
    return render_template("player.html", p=info, batting=batting, pitching=pitching, order=order,
                           bmode=bmode, pmode=pmode, modes=queries.MODES)


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
    menus = {k: [[title, [[c["key"], c["name"], c["fmt"], c["better"]] for c in cols]]
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
