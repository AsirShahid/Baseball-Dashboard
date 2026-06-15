#!/usr/bin/env python3
"""Component layer — pure layout builders for the redesigned dashboard."""

from urllib.parse import quote

from dash import html, dcc
import dash_bootstrap_components as dbc

from data import (
    config, opts, MIN_PA_LIST, MIN_IP_LIST, TEAM_PRESETS,
    TEAM_COLORS, TEAM_COLOR_ALT, TEAM_FULL_NAME, TEAM_DIVISION, logo_b64,
)

GRAPH_CONFIG = {
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
    "responsive": True,
}


def svg_uri(markup: str) -> str:
    return "data:image/svg+xml;charset=utf-8," + quote(markup)


_BALL = ('<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
         'viewBox="0 0 24 24" fill="none">'
         '<circle cx="12" cy="12" r="9" stroke="#f5a524" stroke-width="1.4"/>'
         '<path d="M5 8 Q 12 14 19 8" stroke="#f5a524" stroke-width="1.2" fill="none"/>'
         '<path d="M5 16 Q 12 10 19 16" stroke="#f5a524" stroke-width="1.2" fill="none"/>'
         '</svg>')

_LINK = ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
         'viewBox="0 0 24 24" fill="none" stroke="#7d8590" stroke-width="2">'
         '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
         '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.72-1.71"/>'
         '</svg>')


# ── Small shared builders ─────────────────────────────────────────────────────

def sb_label(text):
    return html.Div(text, className="sb-label")


def segmented(group, options, value, small=False):
    """A .seg segmented control. `options` is a list of (value, label)."""
    return html.Div(
        className="seg" + (" seg-sm" if small else ""),
        children=[
            html.Button(label, n_clicks=0,
                        id={"kind": "seg-btn", "group": group, "value": val},
                        className="seg-btn active" if val == value else "seg-btn")
            for val, label in options
        ],
    )


def toggle_row(switch_id, label, hint, value):
    return html.Div(className="tg", children=[
        html.Span(className="tg-text", children=[
            html.Span(label, className="tg-label"),
            html.Span(hint, className="tg-hint") if hint else None,
        ]),
        dbc.Switch(id=switch_id, value=bool(value), className="tg-dbc"),
    ])


def statpicker_row(axis, stat_id, init_stat, type_group=None, type_value=None,
                   clearable=False, placeholder="Select…"):
    head = [html.Span(axis, className="axis-tag")]
    if type_group:
        head.append(segmented(type_group,
                              [("Batting", "Bat"), ("Pitching", "Pit")],
                              type_value, small=True))
    return html.Div(className="axis-row", children=[
        html.Div(className="axis-row-head", children=head),
        dcc.Dropdown(id=stat_id, value=init_stat, clearable=clearable,
                     placeholder=placeholder, className="axis-dd"),
    ])


def rank_legend():
    return html.Div(className="legend", children=[
        html.Div(className="legend-row", children=[
            html.Span("COMPOSITE RANK", className="legend-title"),
            html.Span("avg percentile across axes", className="legend-sub"),
        ]),
        html.Div(className="legend-bar"),
        html.Div(className="legend-scale", children=[
            html.Span(t) for t in ("0", "25", "50", "75", "100")
        ]),
    ])


# ── Top nav ───────────────────────────────────────────────────────────────────

def top_nav():
    return html.Header(className="tn", children=[
        html.Button(className="tn-home", id="nav-home", n_clicks=0, children=[
            html.Img(src=svg_uri(_BALL.format(s=18)), width=18, height=18),
            html.Span("baseball-dashboard", className="tn-wm"),
        ]),
        html.Div(className="tn-right", children=[
            html.Button("about", id="nav-about", className="tn-link", n_clicks=0),
            html.A(["github ", html.Span("↗", style={"opacity": 0.5})],
                   href="https://github.com/AsirShahid/Baseball-Dashboard",
                   target="_blank", className="tn-link"),
            html.Button("☾", id="theme-toggle", className="tn-icon", n_clicks=0,
                        title="Toggle theme"),
        ]),
    ])


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _year_scrubber(init_year):
    first, last = config["start_year"], config["current_year"]
    # A stale/hand-edited URL (?season=2099) must not seed the slider out of
    # range; the data-aware callback clamps later, but clamp up front so the
    # widget never renders an invalid value.
    init_year = max(first, min(last, init_year))
    return html.Div(className="yr", children=[
        html.Div(className="yr-head", children=[
            html.Span("SEASON", className="yr-label"),
            html.Span(str(init_year), id="season-val", className="yr-val"),
        ]),
        dcc.Slider(id="season-slider", min=first, max=last, step=None,
                   value=init_year, marks={}, included=True,
                   className="season-slider"),
        html.Div(className="yr-step", children=[
            html.Button("◂", id="season-prev", n_clicks=0),
            dcc.Input(id="season-input", type="number", value=init_year,
                      min=first, max=last, debounce=True),
            html.Button("▸", id="season-next", n_clicks=0),
        ]),
    ])


def preset_chips(active):
    return html.Div(className="presets", children=[
        html.Button(className="chip active" if p["id"] == active else "chip",
                    id={"kind": "preset", "id": p["id"]}, n_clicks=0,
                    children=[html.Span(className="chip-dot"), p["name"]])
        for p in TEAM_PRESETS
    ])


def sidebar(init):
    team_axes = html.Div(id="team-axes", children=[
        html.Div(className="sb-section", children=[
            sb_label("AXES"),
            html.Div(className="picker-stack", children=[
                statpicker_row("X", "x-stat", init["x_stat"],
                               type_group="xtype", type_value=init["x_type"]),
                statpicker_row("Y", "y-stat", init["y_stat"],
                               type_group="ytype", type_value=init["y_type"]),
                statpicker_row("Z", "z-stat", init["z_stat"],
                               type_group="ztype", type_value=init["z_type"],
                               clearable=True, placeholder="None — keep 2D"),
            ]),
        ]),
    ])

    player_axes = html.Div(id="player-axes", children=[
        html.Div(className="sb-section", children=[
            sb_label("AXES"),
            html.Div(className="picker-stack", children=[
                statpicker_row("X", "p-x-stat", init["p_x_stat"]),
                statpicker_row("Y", "p-y-stat", init["p_y_stat"]),
                statpicker_row("Z", "p-z-stat", init["p_z_stat"],
                               clearable=True, placeholder="None — keep 2D"),
            ]),
        ]),
    ])

    team_extra = html.Div(id="team-extra", children=[
        html.Div(className="sb-section", children=[
            sb_label("PRESETS"),
            preset_chips(init["preset"]),
        ]),
        html.Div(className="sb-section", children=[
            sb_label("DISPLAY"),
            html.Div(className="toggle-stack", children=[
                toggle_row("tg-vmean", "Vertical mean", "Dashed line at x̄",
                           init["show_v"]),
                toggle_row("tg-hmean", "Horizontal mean", "Dashed line at ȳ",
                           init["show_h"]),
                toggle_row("tg-team-rank", "Composite rank color",
                           "Red → green percentile", init["color_rank"]),
                toggle_row("tg-logos", "Team logos", "Otherwise colored dots",
                           init["logos"]),
            ]),
        ]),
    ])

    player_extra = html.Div(id="player-extra", children=[
        html.Div(className="sb-section", children=[
            sb_label("PLAYER FILTERS"),
            html.Div(id="min-pa-div", children=[
                html.Div("Min plate appearances", className="field-label"),
                dcc.Dropdown(id="min-pa", options=opts(MIN_PA_LIST),
                             value=init["min_pa"], clearable=False),
            ]),
            html.Div(id="min-ip-div", children=[
                html.Div("Min innings pitched", className="field-label"),
                dcc.Dropdown(id="min-ip", options=opts(MIN_IP_LIST),
                             value=init["min_ip"], clearable=False),
            ]),
            html.Div("Team", className="field-label"),
            dcc.Dropdown(id="team-filter", value=init["team"], clearable=False),
        ]),
        html.Div(className="sb-section", children=[
            sb_label("DISPLAY"),
            html.Div(className="toggle-stack", children=[
                toggle_row("tg-player-rank", "Composite rank color",
                           "Red → green percentile", init["p_color_rank"]),
            ]),
        ]),
    ])

    return html.Aside(className="sidebar", children=[
        html.Div(className="sb-section", children=[
            sb_label("VIEW"),
            segmented("view", [("team", "Teams"), ("player", "Players")],
                      init["view"]),
        ]),
        team_axes,
        player_axes,
        html.Div(className="sb-section", children=[_year_scrubber(init["season"])]),
        team_extra,
        player_extra,
        html.Div(id="rank-legend", className="sb-section",
                 children=[rank_legend()], style={"display": "none"}),
    ])


# ── Main area ─────────────────────────────────────────────────────────────────

def _share_chip():
    return html.Button(className="share-chip", id="share-copy-btn", n_clicks=0,
                       children=[
        html.Img(src=svg_uri(_LINK), width=12, height=12),
        html.Span("", id="share-url", className="share-url"),
        html.Span("COPY", id="share-copy-label", className="share-copy"),
    ])


def main_area():
    return html.Main(className="main", children=[
        html.Header(className="topbar", children=[
            html.Div(className="title-block", children=[
                html.Div(id="chart-eyebrow", className="title-eyebrow"),
                html.H1(id="chart-title", className="chart-title"),
            ]),
            html.Div(className="top-right", children=[_share_chip()]),
        ]),
        html.Div(className="chart-card", children=[
            dcc.Loading(type="circle", color="#f5a524", children=[
                html.Div(className="chart-wrap", children=[
                    dcc.Graph(id="main-graph", config=GRAPH_CONFIG,
                              style={"height": "100%", "width": "100%"}),
                ]),
            ]),
        ]),
        html.Div(id="leaderboard", className="leaderboard"),
    ])


# ── Screens ───────────────────────────────────────────────────────────────────

def dashboard_view(init):
    return html.Div(id="screen-dashboard", children=[
        top_nav(),
        html.Div(className="db", children=[sidebar(init), main_area()]),
        html.Div(id="detail-overlay", className="detail-overlay",
                 style={"display": "none"}, children=[
            html.Div(className="detail-panel", children=[
                html.Button("✕", id="detail-close", className="dt-close",
                            n_clicks=0),
                html.Div(id="detail-body"),
            ]),
        ]),
    ])


def about_view():
    return html.Div(id="screen-about", style={"display": "none"}, children=[
        html.Div(className="about", children=[
            html.Header(className="ab-nav", children=[
                html.Button([html.Span("←", className="ab-arrow"),
                             " back to charts"],
                            id="nav-back", className="ab-back", n_clicks=0),
                html.Div(className="ab-right", children=[
                    html.Button("☾", id="theme-toggle-about", className="tn-icon",
                                n_clicks=0, title="Toggle theme"),
                ]),
            ]),
            html.Main(className="ab-body", children=[
                html.Div(className="ab-mark", children=[
                    html.Img(src=svg_uri(_BALL.format(s=28)), width=28, height=28),
                ]),
                html.P(className="ab-p", children=[
                    html.Span("baseball-dashboard", className="ab-name"),
                    " is an interactive explorer for a century and a half of "
                    "baseball statistics.",
                ]),
                html.P("Pick a stat for the x-axis and another for the y-axis — "
                       "optionally a third for the z — and it draws the dots. "
                       "Every team and player season from 1871 to today.",
                       className="ab-p"),
                html.P(className="ab-p ab-dim", children=[
                    "Stats come from FanGraphs via pybaseball. The chart is "
                    "Plotly inside a Dash app. Source on ",
                    html.A("github",
                           href="https://github.com/AsirShahid/Baseball-Dashboard",
                           target="_blank", className="ab-link"),
                    " if you want to run it locally or send a pull request.",
                ]),
                html.P("— asir", className="ab-p ab-dim"),
            ]),
        ]),
    ])


# ── Leaderboard + detail builders (called from callbacks) ─────────────────────

def leaderboard_cards(rows, axis_count):
    """`rows` = list of dicts: rank, team, name, pct, color, ramp."""
    return [
        html.Div(className="lb-head", children=[
            html.Span("COMPOSITE LEADERBOARD", className="lb-title"),
            html.Span(f"avg percentile across {axis_count} "
                      f"{'axis' if axis_count == 1 else 'axes'}",
                      className="lb-sub"),
        ]),
        html.Div(className="lb-strip", children=[
            html.Button(className="lb-card", n_clicks=0,
                        id={"kind": "lb-card", "team": r["team"]}, children=[
                html.Span(f"{r['rank']:02d}", className="lb-rank"),
                html.Span(r["team"], className="lb-mono",
                          style={"background": r["color"]}),
                html.Span(r["name"], className="lb-name"),
                html.Span(className="lb-pct", style={"color": r["ramp"]}, children=[
                    str(r["pct"]),
                    html.Span("th", style={"opacity": 0.5, "fontSize": "0.7em"}),
                ]),
            ])
            for r in rows
        ]),
    ]


def _sparkline(values, w=200, h=56):
    if not values:
        return ""
    mn, mx = min(values), max(values)
    span = (mx - mn) or 1
    pts = []
    n = len(values)
    for i, v in enumerate(values):
        x = (i / (n - 1) if n > 1 else 0.5) * (w - 16) + 8
        y = h - 8 - ((v - mn) / span) * (h - 18)
        pts.append((x, y))
    path = " ".join(f"{'M' if i == 0 else 'L'} {x:.1f} {y:.1f}"
                    for i, (x, y) in enumerate(pts))
    lx, ly = pts[-1]
    fx, _ = pts[0]
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3 if i == n - 1 else 1.6}" '
        f'fill="#f5a524"/>'
        for i, (x, y) in enumerate(pts))
    return svg_uri(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<path d="{path} L {lx:.1f} {h} L {fx:.1f} {h} Z" fill="#f5a524" '
        f'opacity="0.10"/>'
        f'<path d="{path}" fill="none" stroke="#f5a524" stroke-width="1.6"/>'
        f'{dots}</svg>')


def detail_body(team, year, composite, sparks, groups):
    """Build the slide-in team detail panel.
    sparks = [{label, values, years, last}]; groups = [{name, tiles:[...] }].
    tiles = [{label, value, pct, ramp}]."""
    color = TEAM_COLORS.get(team, "#f5a524")
    alt = TEAM_COLOR_ALT.get(team, "#0a0d12")
    head = html.Div(className="dt-head", style={
        "background": f"linear-gradient(135deg, {color} 0%, {alt} 100%)"}, children=[
        html.Div(className="dt-mono-big", children=[
            html.Img(src=logo_b64(team) or "",
                     style={"height": "72px", "width": "72px",
                            "objectFit": "contain"}) if logo_b64(team)
            else html.Div(team, className="lb-mono",
                          style={"background": color, "width": 56, "height": 56,
                                 "fontSize": 18}),
        ]),
        html.Div(className="dt-name-block", children=[
            html.Div(f"{TEAM_DIVISION.get(team,'')} · {year} SEASON",
                     className="dt-eyebrow"),
            html.H2(TEAM_FULL_NAME.get(team, team), className="dt-name"),
            html.Div(className="dt-sub", children=[
                "Composite ",
                html.Span([str(composite),
                           html.Span("th", style={"opacity": 0.55,
                                                  "fontSize": "0.7em"})],
                          className="dt-rank-badge"),
            ]),
        ]),
    ])

    spark_section = html.Div(className="dt-section", children=[
        html.Div(className="dt-section-head", children=[
            html.Span("5-YEAR TRAJECTORY", className="dt-section-title"),
        ]),
        html.Div(className="dt-spark-row", children=[
            html.Div(className="spark", children=[
                html.Div(className="spark-head", children=[
                    html.Span(s["label"], className="spark-label"),
                    html.Span(s["last"], className="spark-val"),
                ]),
                html.Img(src=_sparkline(s["values"]),
                         style={"width": "100%", "height": "48px"}),
                html.Div(className="spark-years", children=[
                    html.Span(str(s["years"][0]) if s["years"] else ""),
                    html.Span(str(s["years"][-1]) if s["years"] else ""),
                ]),
            ]) for s in sparks if s["values"]
        ]),
    ])

    stat_sections = [
        html.Div(className="dt-section", children=[
            html.Div(className="dt-section-head", children=[
                html.Span(g["name"].upper(), className="dt-section-title"),
            ]),
            html.Div(className="dt-statgrid", children=[
                html.Button(className="dt-stat", n_clicks=0,
                            id={"kind": "dt-stat", "stat": t["label"],
                                "type": t["type"]}, children=[
                    html.Div(className="dt-stat-head", children=[
                        html.Span(t["label"], className="dt-stat-label"),
                        html.Span([str(t["pct"]),
                                   html.Span("th", style={"opacity": 0.5})],
                                  className="dt-stat-pct",
                                  style={"color": t["ramp"]}),
                    ]),
                    html.Div(t["value"], className="dt-stat-val"),
                    html.Div(className="dt-stat-bar", children=[
                        html.Div(className="dt-stat-bar-fill",
                                 style={"width": f"{t['pct']}%",
                                        "background": t["ramp"]}),
                        html.Div(className="dt-stat-bar-mean"),
                    ]),
                ])
                for t in g["tiles"]
            ]),
        ])
        for g in groups
    ]

    return [head, spark_section] + stat_sections + [
        html.Div("Stats shown vs. all teams that season.", className="dt-foot"),
    ]
