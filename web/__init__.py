"""The site: a small Flask app that renders plain HTML from baseball.sqlite."""

from __future__ import annotations

import gzip
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, send_from_directory
from markupsafe import Markup

from pipeline import teams as T

from . import db, fmt, queries, svg

ROOT = Path(__file__).resolve().parent
NAV = [
    ("site.home", "Home"), ("site.standings", "Standings"), ("site.players", "Players"),
    ("site.teams", "Teams"), ("site.compare", "Compare"), ("site.chart", "Charts"),
]
_COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml", "text/csv")


def _asset_version() -> str:
    newest = max((path.stat().st_mtime_ns for path in (ROOT / "static").rglob("*") if path.is_file()),
                 default=0)
    return format(newest // 1_000_000, "x")


def create_app(data_root=None) -> Flask:
    app = Flask(__name__, static_folder=str(ROOT / "static"), template_folder=str(ROOT / "templates"))
    if data_root or os.environ.get("DATA_ROOT"):
        db.configure(data_root or os.environ["DATA_ROOT"])
    app.config["FAVORITE_TEAM"] = os.environ.get("FAVORITE_TEAM", "NYY")
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    version = _asset_version()

    def asset(name: str) -> str:
        return f"/static/{name}?v={version}"

    def url_with(**changes) -> str:
        """The current URL with some query parameters replaced or removed."""
        args = {key: value for key, value in request.args.items()}
        for key, value in changes.items():
            if value is None or value == "":
                args.pop(key, None)
            else:
                args[key] = value
        query = "&".join(f"{key}={_quote(value)}" for key, value in args.items())
        return request.path + ("?" + query if query else "")

    def stamp(value) -> str:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value or "")
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo("America/New_York")).strftime("%b %-d, %Y, %-I:%M %p ET")

    def ordinal(value) -> str:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return ""
        tail = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
        return f"{number}{tail}"

    def logo_url(code, season=None):
        return queries.logo_url(code, season)

    def headshot(mlbam, width=120) -> str:
        if not mlbam:
            return ""
        return ("https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/"
                f"w_{width * 2},q_auto:best/v1/people/{mlbam}/headshot/67/current")

    def ramp(pct) -> str:
        """0-100 percentile -> red, orange, green (the chart's percentile colors)."""
        stops = ((229, 72, 77), (249, 115, 22), (70, 167, 88))
        t = max(0.0, min(1.0, float(pct or 0) / 100))
        i = 0 if t < 0.5 else 1
        k = (t - i * 0.5) / 0.5
        return "rgb(%d,%d,%d)" % tuple(round(a + (b - a) * k) for a, b in zip(stops[i], stops[i + 1]))

    app.jinja_env.filters.update(f=fmt.fmt, sv=fmt.sort_value, ordinal=ordinal, stamp=stamp,
                                 ip=fmt.ip_notation, ramp=ramp)
    app.jinja_env.globals.update(
        asset=asset, url_with=url_with, NAV=NAV, svg=svg, logo_url=logo_url, headshot=headshot,
        team_name=T.team_name, team_color=T.color, MULTI_TEAM=T.MULTI_TEAM, span_label=queries.span_label,
        has_endpoint=lambda name: name in app.view_functions,
    )

    from .views import bp
    app.register_blueprint(bp)

    @app.route("/logos/<path:name>")
    def logos(name):
        response = send_from_directory(T.LOGO_DIR, name, max_age=86400 * 30)
        return response

    @app.context_processor
    def shared():
        if not db.available():
            return {"seasons": [], "latest": 0, "favorite": app.config["FAVORITE_TEAM"]}
        return {"seasons": queries.seasons(), "latest": queries.latest_season(),
                "favorite": app.config["FAVORITE_TEAM"]}

    @app.after_request
    def finish(response):
        if request.path.startswith("/static/"):
            if request.args.get("v"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif not request.path.startswith("/logos/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        accepts = "gzip" in request.headers.get("Accept-Encoding", "")
        kind = response.mimetype or ""
        if (accepts and response.status_code == 200 and "Content-Encoding" not in response.headers
                and kind.startswith(_COMPRESSIBLE)):
            response.direct_passthrough = False
            body = response.get_data()
            if len(body) > 800:
                response.set_data(gzip.compress(body, 6))
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Vary"] = "Accept-Encoding"
        return response

    @app.errorhandler(404)
    def missing(_error):
        return render_template("message.html", title="Not found",
                               text="That page does not exist."), 404

    return app


def _quote(value) -> str:
    from urllib.parse import quote
    return quote(str(value), safe=",")


__all__ = ["create_app", "Markup"]
