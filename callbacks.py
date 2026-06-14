#!/usr/bin/env python3
"""Callback layer — every Dash callback, registered via register_callbacks(app)."""

from urllib.parse import urlencode

import pandas as pd
from dash import Input, Output, State, MATCH, ALL, no_update, ctx

from data import (
    config, load_csv, process_columns, seasons_with_data, opts,
    TEAM_SEASONS, PLAYER_SEASONS, TEAM_COLORS,
    TEAM_FULL_NAME, TEAM_PRESETS, ramp_color,
)
from charts import render_team, render_player, compute_composite_rank, rank_items
from components import leaderboard_cards, detail_body

# Curated, direction-aware stats for the team detail panel.
# Each entry: (stat, higher_is_better)
DETAIL_GROUPS = [
    ("Hitting",  "Batting",  "team_batting_dir",
     [("wOBA", True), ("wRC+", True), ("OPS", True), ("ISO", True)]),
    ("Pitching", "Pitching", "team_pitching_dir",
     [("ERA", False), ("FIP", False), ("WHIP", False), ("K/9", True)]),
]
SPARK_STATS = [("wRC+", "team_batting_dir"),
               ("ERA",  "team_pitching_dir"),
               ("WAR",  "team_batting_dir")]


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_val(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    if abs(v) < 1:
        s = f"{v:.3f}"
        return s.replace("0.", ".", 1) if s.startswith(("0.", "-0.")) else s
    if abs(v) < 10:
        return f"{v:.2f}"
    return f"{v:.0f}"


def _pct(series, value, higher_better) -> int:
    s = series.dropna()
    if s.empty or value is None or (isinstance(value, float) and value != value):
        return 50
    if higher_better:
        frac = (s <= value).sum() / len(s)
    else:
        frac = (s >= value).sum() / len(s)
    return int(round(frac * 100))


def _team_value(dir_key, year, team, stat, fetch=True):
    df = load_csv(f"{config[dir_key]}/{year}.csv", fetch=fetch)
    if df.empty or stat not in df.columns or "Team" not in df.columns:
        return None, df
    row = df[df["Team"] == team]
    if row.empty:
        return None, df
    return row.iloc[0][stat], df


def _spark(stat, dir_key, team, season):
    years, values = [], []
    for y in range(season - 4, season + 1):
        # fetch=False: don't fire blocking network requests for missing
        # neighbouring seasons just to draw a sparkline.
        v, _ = _team_value(dir_key, y, team, stat, fetch=False)
        if v is not None and v == v:
            years.append(y)
            values.append(float(v))
    return {"label": stat, "values": values, "years": years,
            "last": _fmt_val(values[-1]) if values else "—"}


def _leaderboard_rows(season, xt, yt, xs, ys, zt, zs):
    def _load(typ, stat):
        if not stat:
            return None
        key = "team_batting_dir" if typ == "Batting" else "team_pitching_dir"
        df = load_csv(f"{config[key]}/{season}.csv")
        if df.empty or stat not in df.columns or "Team" not in df.columns:
            return None
        # Index by team so axes loaded from different CSVs (batting vs
        # pitching) align by team, not by row position.
        s = pd.Series(df[stat].values, index=df["Team"].astype(str))
        # An all-NaN axis carries no signal; drop it so it neither produces a
        # meaningless all-50 ranking (x/y) nor inflates the axis count (z) —
        # mirroring render_team, which won't plot or count an empty axis.
        if s.isna().all():
            return None
        return s

    xv = _load(xt, xs)
    yv = _load(yt, ys)
    if xv is None or yv is None:
        return [], 0
    zv = _load(zt, zs) if zs else None
    items = rank_items((xv, xs, xt == "Pitching"),
                       (yv, ys, yt == "Pitching"),
                       (zv, zs, zt == "Pitching"))
    comp = compute_composite_rank(*items)
    rows = sorted(
        ({"team": str(t), "score": float(s)} for t, s in comp.items()),
        key=lambda r: r["score"], reverse=True,
    )
    out = []
    for i, r in enumerate(rows[:10]):
        pct = int(round(r["score"]))
        out.append({"rank": i + 1, "team": r["team"],
                    "name": TEAM_FULL_NAME.get(r["team"], r["team"]),
                    "pct": pct, "color": TEAM_COLORS.get(r["team"], "#7d8590"),
                    "ramp": ramp_color(pct / 100)})
    return out, len(items)


def _decade_marks(mn, mx):
    span = max(1, mx - mn)
    step = 10 if span <= 35 else (20 if span <= 90 else 30)
    marks = {mn: {"label": str(mn)}, mx: {"label": str(mx)}}
    start = ((mn // step) + 1) * step
    for y in range(start, mx, step):
        if (y - mn) > step * 0.5 and (mx - y) > step * 0.5:
            marks[y] = "’" + f"{y % 100:02d}"
    return marks


# ── registration ──────────────────────────────────────────────────────────────

def register_callbacks(app):

    # ---- segmented controls (generic, all groups) ----
    @app.callback(
        Output({"kind": "seg-store", "group": MATCH}, "data"),
        Input({"kind": "seg-btn", "group": MATCH, "value": ALL}, "n_clicks"),
        State({"kind": "seg-store", "group": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _seg_set(_clicks, cur):
        trig = ctx.triggered_id
        return trig["value"] if trig else cur

    @app.callback(
        Output({"kind": "seg-btn", "group": MATCH, "value": ALL}, "className"),
        Input({"kind": "seg-store", "group": MATCH}, "data"),
        State({"kind": "seg-btn", "group": MATCH, "value": ALL}, "id"),
    )
    def _seg_style(value, ids):
        return ["seg-btn active" if i["value"] == value else "seg-btn"
                for i in ids]

    # ---- screen routing ----
    @app.callback(
        Output("screen-dashboard", "style"),
        Output("screen-about", "style"),
        Input("nav-about", "n_clicks"),
        Input("nav-back", "n_clicks"),
        Input("nav-home", "n_clicks"),
        prevent_initial_call=True,
    )
    def route(_a, _b, _h):
        if ctx.triggered_id == "nav-about":
            return {"display": "none"}, {}
        return {}, {"display": "none"}

    # ---- theme ----
    @app.callback(
        Output("theme-store", "data"),
        Input("theme-toggle", "n_clicks"),
        Input("theme-toggle-about", "n_clicks"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )
    def flip_theme(_n1, _n2, cur):
        return "light" if (cur or "dark") == "dark" else "dark"

    app.clientside_callback(
        """function(theme){
             var t = theme || 'dark';
             document.documentElement.setAttribute('data-theme', t);
             var icon = (t === 'dark') ? '☼' : '☾';
             return [icon, icon];
        }""",
        Output("theme-toggle", "children"),
        Output("theme-toggle-about", "children"),
        Input("theme-store", "data"),
    )

    # ---- view / sub-control visibility ----
    @app.callback(
        Output("team-axes", "style"), Output("player-axes", "style"),
        Output("team-extra", "style"), Output("player-extra", "style"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
    )
    def toggle_view(view):
        show, hide = {}, {"display": "none"}
        if view == "player":
            return hide, show, hide, show
        return show, hide, show, hide

    @app.callback(
        Output("min-pa-div", "style"), Output("min-ip-div", "style"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
    )
    def toggle_min_filters(ptype):
        if ptype == "Pitchers":
            return {"display": "none"}, {}
        return {}, {"display": "none"}

    @app.callback(
        Output("rank-legend", "style"),
        Input("tg-team-rank", "value"),
        Input("tg-player-rank", "value"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
    )
    def toggle_legend(team_rank, player_rank, view):
        on = ((view == "team" and team_rank) or
              (view == "player" and player_rank))
        return {} if on else {"display": "none"}

    # ---- stat option lists ----
    def _team_stat(stat_type, season, current, fallback_idx=0, allow_none=False):
        key = "team_batting_dir" if stat_type == "Batting" else "team_pitching_dir"
        df = load_csv(f"{config[key]}/{season or config['current_year']}.csv")
        if df.empty:
            return [], (None if allow_none else no_update)
        cols = process_columns(df.columns)
        if not cols:
            return [], (None if allow_none else no_update)
        if allow_none:
            val = current if (current and current in cols) else None
        else:
            val = current if current in cols else cols[min(fallback_idx, len(cols) - 1)]
        return opts(cols), val

    @app.callback(
        Output("x-stat", "options"), Output("x-stat", "value"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        State("season-slider", "value"), State("x-stat", "value"),
    )
    def update_x_stat(xtype, season, current):
        return _team_stat(xtype, season, current, 0)

    @app.callback(
        Output("y-stat", "options"), Output("y-stat", "value"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        State("season-slider", "value"), State("y-stat", "value"),
    )
    def update_y_stat(ytype, season, current):
        return _team_stat(ytype, season, current, 1)

    @app.callback(
        Output("z-stat", "options"), Output("z-stat", "value"),
        Input({"kind": "seg-store", "group": "ztype"}, "data"),
        State("season-slider", "value"), State("z-stat", "value"),
    )
    def update_z_stat(ztype, season, current):
        return _team_stat(ztype, season, current, allow_none=True)

    @app.callback(
        Output("p-x-stat", "options"), Output("p-x-stat", "value"),
        Output("p-y-stat", "options"), Output("p-y-stat", "value"),
        Output("p-z-stat", "options"), Output("p-z-stat", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        State("season-slider", "value"),
        State("p-x-stat", "value"), State("p-y-stat", "value"),
        State("p-z-stat", "value"),
    )
    def update_player_stats(ptype, season, cx, cy, cz):
        key = ("qualified_batting_dir" if ptype == "Batters"
               else "qualified_pitching_dir")
        df = load_csv(f"{config[key]}/{season or config['current_year']}.csv")
        if df.empty:
            return [], no_update, [], no_update, [], None
        if ptype == "Batters" and "WAR" in df.columns and "PA" in df.columns:
            df = df.copy()
            pa = df["PA"].where(df["PA"] > 0)
            df["WAR/650 PAs"] = (df["WAR"] / pa * 650).round(2)
        cols = process_columns(df.columns)
        if not cols:
            return [], no_update, [], no_update, [], None
        xv = cx if cx in cols else cols[0]
        yv = cy if cy in cols else (cols[1] if len(cols) > 1 else cols[0])
        zv = cz if (cz and cz in cols) else None
        return opts(cols), xv, opts(cols), yv, opts(cols), zv

    @app.callback(
        Output("team-filter", "options"), Output("team-filter", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
        State("team-filter", "value"),
    )
    def update_team_filter(ptype, season, view, current):
        if view != "player":
            return no_update, no_update
        key = ("qualified_batting_dir" if ptype == "Batters"
               else "qualified_pitching_dir")
        df = load_csv(f"{config[key]}/{season or config['current_year']}.csv")
        base = [{"label": "All Teams", "value": "All Teams"},
                {"label": "AL", "value": "AL"}, {"label": "NL", "value": "NL"}]
        if df.empty or "Team" not in df.columns:
            return base, "All Teams"
        teams = sorted(t for t in df["Team"].unique() if t not in ("- - -", ""))
        options = base + opts(teams)
        valid = {o["value"] for o in options}
        return options, (current if current in valid else "All Teams")

    # ---- season scrubber ----
    @app.callback(
        Output("season-slider", "min"), Output("season-slider", "max"),
        Output("season-slider", "marks"), Output("season-slider", "value"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
        Input("x-stat", "value"), Input("y-stat", "value"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        State("season-slider", "value"),
    )
    def update_season_slider(view, xs, ys, xt, yt, pxs, pys, ptype, cur):
        if view == "player":
            seasons = PLAYER_SEASONS
            dk = ("qualified_batting_dir" if ptype == "Batters"
                  else "qualified_pitching_dir")
            valid = set(seasons)
            for stat in (pxs, pys):
                if stat:
                    av = seasons_with_data(dk, stat)
                    if av:
                        valid &= av
        else:
            seasons = TEAM_SEASONS
            valid = set(seasons)
            for stat, typ in ((xs, xt), (ys, yt)):
                if stat:
                    dk = ("team_batting_dir" if typ == "Batting"
                          else "team_pitching_dir")
                    av = seasons_with_data(dk, stat)
                    if av:
                        valid &= av
        years = sorted(y for y in seasons if y in valid) or sorted(seasons)
        mn, mx = years[0], years[-1]
        value = cur if (cur and mn <= cur <= mx) else mx
        return mn, mx, _decade_marks(mn, mx), value

    @app.callback(
        Output("season-slider", "value", allow_duplicate=True),
        Input("season-prev", "n_clicks"),
        Input("season-next", "n_clicks"),
        Input("season-input", "value"),
        State("season-slider", "value"),
        State("season-slider", "min"), State("season-slider", "max"),
        prevent_initial_call=True,
    )
    def season_control(_p, _n, inp, cur, mn, mx):
        trig = ctx.triggered_id
        cur = cur or mx
        if trig == "season-prev":
            return max(mn, cur - 1)
        if trig == "season-next":
            return min(mx, cur + 1)
        if trig == "season-input" and inp is not None:
            try:
                v = max(mn, min(mx, int(inp)))
            except (TypeError, ValueError):
                return no_update
            return v if v != cur else no_update
        return no_update

    @app.callback(
        Output("season-val", "children"), Output("season-input", "value"),
        Input("season-slider", "value"),
    )
    def season_display(value):
        return str(value or ""), value

    # ---- presets ----
    @app.callback(
        Output({"kind": "seg-store", "group": "xtype"}, "data",
               allow_duplicate=True),
        Output({"kind": "seg-store", "group": "ytype"}, "data",
               allow_duplicate=True),
        Output({"kind": "seg-store", "group": "ztype"}, "data",
               allow_duplicate=True),
        Output("x-stat", "value", allow_duplicate=True),
        Output("y-stat", "value", allow_duplicate=True),
        Output("z-stat", "value", allow_duplicate=True),
        Input({"kind": "preset", "id": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def apply_preset(clicks):
        if not clicks or not any(clicks):
            return (no_update,) * 6
        pid = ctx.triggered_id["id"]
        preset = next((p for p in TEAM_PRESETS if p["id"] == pid), None)
        if not preset:
            return (no_update,) * 6
        xt, xs = preset["x"]
        yt, ys = preset["y"]
        if preset["z"]:
            zt, zs = preset["z"]
        else:
            zt, zs = no_update, None
        return xt, yt, zt, xs, ys, zs

    @app.callback(
        Output({"kind": "preset", "id": ALL}, "className"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        Input("x-stat", "value"), Input("y-stat", "value"),
        Input("z-stat", "value"),
        State({"kind": "preset", "id": ALL}, "id"),
    )
    def style_preset_chips(xt, yt, xs, ys, zs, ids):
        out = []
        for pid in ids:
            p = next((q for q in TEAM_PRESETS if q["id"] == pid["id"]), None)
            active = bool(p and p["x"] == (xt, xs) and p["y"] == (yt, ys)
                          and (p["z"][1] if p["z"] else None) == zs)
            out.append("chip active" if active else "chip")
        return out

    # ---- URL sync + share chip ----
    @app.callback(
        Output("url", "search"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        Input({"kind": "seg-store", "group": "ztype"}, "data"),
        Input("x-stat", "value"), Input("y-stat", "value"), Input("z-stat", "value"),
        Input("tg-vmean", "value"), Input("tg-hmean", "value"),
        Input("tg-team-rank", "value"), Input("tg-logos", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input("p-z-stat", "value"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"), Input("tg-player-rank", "value"),
        prevent_initial_call=True,
    )
    def sync_url(view, season, xt, yt, zt, xs, ys, zs, vm, hm, tr, lg,
                 ptype, pxs, pys, pzs, mpa, mip, tf, pr):
        if view == "player":
            params = dict(view="player", season=season or "",
                          player_type=ptype or "Batters",
                          p_x_stat=pxs or "", p_y_stat=pys or "",
                          p_z_stat=pzs or "", min_pa=mpa, min_ip=mip,
                          team=tf or "All Teams",
                          p_color_rank=str(bool(pr)).lower())
        else:
            params = dict(view="team", season=season or "",
                          x_type=xt or "Batting", y_type=yt or "Pitching",
                          z_type=zt or "Batting",
                          x_stat=xs or "", y_stat=ys or "", z_stat=zs or "",
                          show_v=str(bool(vm)).lower(),
                          show_h=str(bool(hm)).lower(),
                          color_rank=str(bool(tr)).lower(),
                          logos=str(bool(lg)).lower())
        return "?" + urlencode(params)

    app.clientside_callback(
        "function(_s){ return window.location.href; }",
        Output("share-url", "children"),
        Input("url", "search"),
    )

    app.clientside_callback(
        """function(n){
             if(!n){ return 'COPY'; }
             try {
               var p = navigator.clipboard.writeText(window.location.href);
               if (p && p.catch) { p.catch(function(){}); }
             } catch(e){}
             setTimeout(function(){
               var el = document.getElementById('share-copy-label');
               if(el){ el.textContent = 'COPY'; }
             }, 1400);
             return 'COPIED';
        }""",
        Output("share-copy-label", "children"),
        Input("share-copy-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    # ---- chart + leaderboard ----
    @app.callback(
        Output("main-graph", "figure"),
        Output("chart-eyebrow", "children"),
        Output("chart-title", "children"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        Input({"kind": "seg-store", "group": "ztype"}, "data"),
        Input("x-stat", "value"), Input("y-stat", "value"), Input("z-stat", "value"),
        Input("tg-vmean", "value"), Input("tg-hmean", "value"),
        Input("tg-team-rank", "value"), Input("tg-logos", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input("p-z-stat", "value"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"), Input("tg-player-rank", "value"),
        Input("theme-store", "data"),
    )
    def render(view, season, xt, yt, zt, xs, ys, zs, vm, hm, tr, lg,
               ptype, pxs, pys, pzs, mpa, mip, tf, pr, theme):
        theme = theme or "dark"
        if view == "player":
            return render_player(season, ptype, pxs, pys, mpa, mip, tf,
                                  bool(pr), pzs, theme)
        return render_team(season, bool(lg), xt, yt, xs, ys,
                            bool(vm), bool(hm), bool(tr), zt, zs, theme)

    @app.callback(
        Output("leaderboard", "children"), Output("leaderboard", "style"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        Input({"kind": "seg-store", "group": "ztype"}, "data"),
        Input("x-stat", "value"), Input("y-stat", "value"), Input("z-stat", "value"),
    )
    def update_leaderboard(view, season, xt, yt, zt, xs, ys, zs):
        if view != "team":
            return [], {"display": "none"}
        rows, n = _leaderboard_rows(season, xt, yt, xs, ys, zt, zs)
        if not rows:
            return [], {"display": "none"}
        return leaderboard_cards(rows, n), {}

    # ---- team detail panel ----
    @app.callback(
        Output("detail-overlay", "style"),
        Output("detail-store", "data"),
        Input("main-graph", "clickData"),
        Input({"kind": "lb-card", "team": ALL}, "n_clicks"),
        Input("detail-close", "n_clicks"),
        State({"kind": "seg-store", "group": "view"}, "data"),
        prevent_initial_call=True,
    )
    def open_detail(click, lb_clicks, _close, view):
        hidden = {"display": "none"}
        trig = ctx.triggered_id
        if trig == "detail-close":
            return hidden, no_update
        if isinstance(trig, dict) and trig.get("kind") == "lb-card":
            if not any(lb_clicks or []):
                return no_update, no_update
            return {}, trig["team"]
        if trig == "main-graph":
            if view != "team" or not click:
                return no_update, no_update
            try:
                abbr = click["points"][0]["text"]
            except (KeyError, IndexError, TypeError):
                return no_update, no_update
            if abbr not in TEAM_COLORS:
                return no_update, no_update
            return {}, abbr
        return no_update, no_update

    @app.callback(
        Output({"kind": "seg-store", "group": "xtype"}, "data",
               allow_duplicate=True),
        Output("x-stat", "value", allow_duplicate=True),
        Output("detail-overlay", "style", allow_duplicate=True),
        Input({"kind": "dt-stat", "stat": ALL, "type": ALL}, "n_clicks"),
        State({"kind": "seg-store", "group": "view"}, "data"),
        prevent_initial_call=True,
    )
    def pick_detail_stat(clicks, view):
        if not clicks or not any(clicks) or view != "team":
            return no_update, no_update, no_update
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update, no_update, no_update
        return trig["type"], trig["stat"], {"display": "none"}

    @app.callback(
        Output("detail-body", "children"),
        Input("detail-store", "data"),
        State("season-slider", "value"),
    )
    def render_detail(team, season):
        if not team:
            return None
        season = season or config["current_year"]
        groups, all_pcts = [], []
        for gname, gtype, dir_key, stats in DETAIL_GROUPS:
            tiles = []
            for stat, hib in stats:
                v, df = _team_value(dir_key, season, team, stat)
                if v is None or df.empty or stat not in df.columns:
                    continue
                pct = _pct(df[stat], v, hib)
                all_pcts.append(pct)
                tiles.append({"label": stat, "type": gtype,
                              "value": _fmt_val(v), "pct": pct,
                              "ramp": ramp_color(pct / 100)})
            if tiles:
                groups.append({"name": gname, "tiles": tiles})
        composite = int(round(sum(all_pcts) / len(all_pcts))) if all_pcts else 50
        sparks = [_spark(s, dk, team, season) for s, dk in SPARK_STATS]
        return detail_body(team, season, composite, sparks, groups)
