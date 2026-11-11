#!/usr/bin/env python3
"""Baseball Statistics Dashboard — Plotly Dash app with a shareable URL state.

Entry point. Data lives in data.py, Plotly rendering in charts.py, layout
builders in components.py, and every callback in callbacks.py.
"""

import logging
import os
from urllib.parse import urlparse, parse_qs

import dash
from dash import dcc, html
import flask

from data import safe_int, snap_threshold, config, current_year, _release_memory
from components import dashboard_view, about_view
from callbacks import register_callbacks

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="baseball-dashboard",
    update_title=None,
    # Without this, phones render the ~980px desktop layout zoomed out and
    # the responsive CSS below 760px never applies.
    meta_tags=[{"name": "viewport",
                "content": "width=device-width, initial-scale=1"}],
)
server = app.server


@server.after_request
def _return_heap(resp):
    # Big callbacks leave freed pandas buffers in glibc's heap; trimming after
    # each request keeps a worker's RSS near its live data (~1 ms).
    _release_memory()
    return resp

app.index_string = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap">
    {%css%}
</head>
<body>
    {%app_entry%}
    <footer>
        {%config%}
        {%scripts%}
        {%renderer%}
    </footer>
</body>
</html>"""


def parse_url_params() -> dict:
    """Read query params for initial control state.

    The Dash client fetches /_dash-layout without the page's query string, so
    fall back to the Referer header (the page URL that triggered the fetch).
    """
    try:
        args = {k: v for k, v in flask.request.args.items()}
        if args:
            return args
        ref = flask.request.referrer
        if ref:
            return {k: v[0] for k, v in parse_qs(urlparse(ref).query).items()}
    except Exception:
        pass
    return {}


def serve_layout():
    """Build the full layout, seeding control state from URL query params."""
    p = parse_url_params()

    view = "player" if str(p.get("view", "team")).lower().startswith("player") \
        else "team"
    season = safe_int(p.get("season") or p.get("p_season"),
                      current_year())
    # season_end seeds the upper handle of the range slider; absent → single
    # season (end == start), preserving the old single-year share links.
    season_end = safe_int(p.get("season_end"), season)
    if season_end < season:
        season, season_end = season_end, season

    x_type = p.get("x_type", "Batting")
    y_type = p.get("y_type", "Pitching")
    z_type = p.get("z_type", "Batting")
    x_stat = p.get("x_stat", "WAR")
    y_stat = p.get("y_stat", "SIERA")
    z_stat = p.get("z_stat") or None
    show_v = p.get("show_v", "true") == "true"
    show_h = p.get("show_h", "true") == "true"
    color_rank = p.get("color_rank", "false") == "true"
    logos = p.get("logos", "false") == "true"

    player_type = "Pitchers" if str(p.get("player_type", "Batters")).lower() \
        .startswith("pitch") else "Batters"
    p_x_stat = p.get("p_x_stat", "WAR")
    p_y_stat = p.get("p_y_stat", "wRC+")
    p_z_stat = p.get("p_z_stat") or None
    p_show_v = p.get("p_show_v", "true") == "true"
    p_show_h = p.get("p_show_h", "true") == "true"

    min_pa = snap_threshold(p.get("min_pa", "Qualified"))
    min_ip = snap_threshold(p.get("min_ip", "Qualified"))

    # Range view: "season" = one point per team/player-season; anything else
    # (or absent, as in older share links) = the cumulative combined view.
    split = "season" if str(p.get("split", "")).lower() == "season" else "combined"

    p_labels = str(p.get("p_labels", "all")).lower()
    if p_labels not in ("all", "outliers", "none"):
        p_labels = "all"

    init = dict(
        view=view, season=season, season_end=season_end, split=split,
        x_type=x_type, y_type=y_type, z_type=z_type,
        x_stat=x_stat, y_stat=y_stat, z_stat=z_stat,
        show_v=show_v, show_h=show_h, color_rank=color_rank, logos=logos,
        show_trend=p.get("trend", "false") == "true",
        era=p.get("era", "false") == "true",
        traj=p.get("traj", "false") == "true",
        player_type=player_type, p_x_stat=p_x_stat, p_y_stat=p_y_stat,
        p_z_stat=p_z_stat, min_pa=min_pa, min_ip=min_ip,
        team=p.get("team", "All Teams"),
        league=p.get("league", "All Teams"),
        p_color_rank=p.get("p_color_rank", "false") == "true",
        p_show_v=p_show_v, p_show_h=p_show_h,
        p_show_trend=p.get("p_trend", "false") == "true",
        p_era=p.get("p_era", "false") == "true",
        p_traj=p.get("p_traj", "false") == "true",
        find=p.get("find", ""),
        p_labels=p_labels,
    )

    def seg_store(group, value):
        return dcc.Store(id={"kind": "seg-store", "group": group}, data=value)

    return html.Div(className="app", children=[
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="theme-store", storage_type="local", data="dark"),
        dcc.Store(id="detail-store"),
        seg_store("view", view),
        seg_store("xtype", x_type),
        seg_store("ytype", y_type),
        seg_store("ztype", z_type),
        seg_store("ptype", player_type),
        seg_store("plabels", p_labels),
        seg_store("split", split),
        dashboard_view(init),
        about_view(),
    ])


app.layout = serve_layout
register_callbacks(app)


if __name__ == "__main__":
    # Debug mode exposes the Werkzeug interactive debugger (arbitrary code
    # execution), so it is opt-in and the default bind is loopback only.
    # Set HOST=0.0.0.0 to serve on the network, DASH_DEBUG=1 while developing.
    debug = os.environ.get("DASH_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8050")))
