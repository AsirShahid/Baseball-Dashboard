#!/usr/bin/env python3
"""Baseball Statistics Dashboard — Plotly Dash with shareable URL state."""

import base64
import functools
import json
from urllib.parse import urlencode

import dash
from dash import dcc, html, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import flask

# ── Config ────────────────────────────────────────────────────────────────────

with open("config.json") as f:
    config = json.load(f)

EXCLUDED_COLS = {"Team", "Season", "Dollars", "Name", "IDfg", "Unnamed: 0"}
PRIORITY_COLS = ["WAR", "wRC+", "SIERA"]

NL_TEAMS = {"ARI", "ATL", "CHC", "CIN", "COL", "LAD", "MIA", "MIL",
             "NYM", "PHI", "PIT", "SDP", "SFG", "STL", "WAS"}
AL_TEAMS = {"BAL", "BOS", "CHW", "CLE", "DET", "HOU", "LAA", "KCR",
             "MIN", "NYY", "OAK", "SEA", "TBR", "TEX", "TOR"}

TEAM_LOGO_MAP = {
    "LAA": "angels",   "BAL": "orioles",  "BOS": "redsox",    "CHW": "whitesox",
    "CLE": "guardians","DET": "tigers",   "KCR": "royals",    "MIN": "twins",
    "NYY": "yankees",  "OAK": "athletics","SEA": "mariners",  "TBR": "rays",
    "TEX": "rangers",  "TOR": "bluejays", "ARI": "diamondbacks","ATL": "braves",
    "CHC": "cubs",     "CIN": "reds",     "COL": "rockies",   "MIA": "marlins",
    "HOU": "astros",   "LAD": "dodgers",  "MIL": "brewers",   "WAS": "nationals",
    "NYM": "mets",     "PHI": "phillies", "PIT": "pirates",   "STL": "cardinals",
    "SDP": "padres",   "SFG": "giants",
}

TEAM_SEASONS   = list(range(config["current_year"], 1997, -1))
PLAYER_SEASONS = list(range(config["current_year"], 1870, -1))
MIN_PA_LIST    = ["Qualified"] + list(range(0, 701, 10))
MIN_IP_LIST    = ["Qualified"] + list(range(0, 301, 10))

PLOT_BG    = "#0d1117"
PAPER_BG   = "#0d1117"
GRID_COLOR = "#21262d"
ACCENT     = "#58a6ff"
TEXT_COLOR = "#c9d1d9"

# ── Data helpers ──────────────────────────────────────────────────────────────

def process_columns(columns):
    cols = [c for c in columns
            if c not in EXCLUDED_COLS and not str(c).startswith("Unnamed")]
    for col in reversed(PRIORITY_COLS):
        if col in cols:
            cols.remove(col)
            cols.insert(0, col)
    return cols


@functools.lru_cache(maxsize=512)
def load_csv(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


@functools.lru_cache(maxsize=256)
def seasons_with_data(dir_key: str, stat: str) -> frozenset:
    """Return seasons where `stat` has at least one non-null value."""
    from pathlib import Path
    result = set()
    for f in Path(config[dir_key]).glob("*.csv"):
        try:
            df = pd.read_csv(f, usecols=[stat])
            if df[stat].notna().any():
                result.add(int(f.stem))
        except Exception:
            pass
    return frozenset(result)


@functools.lru_cache(maxsize=64)
def logo_b64(team: str) -> str | None:
    name = TEAM_LOGO_MAP.get(team)
    if not name:
        return None
    try:
        with open(f"./Logos/{name}-resizedmatplotlib.png", "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return None


def safe_int(val, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def parse_url_params() -> dict:
    try:
        return dict(flask.request.args)
    except Exception:
        return {}


def opts(values: list) -> list:
    return [{"label": str(v), "value": v} for v in values]


def make_label(text: str):
    return html.P(text, className="text-uppercase fw-semibold mb-1 mt-3",
                  style={"fontSize": "0.7rem", "letterSpacing": "0.08em",
                         "color": "#8b949e"})


def base_layout() -> dict:
    return dict(
        plot_bgcolor=PLOT_BG,
        paper_bgcolor=PAPER_BG,
        font=dict(color=TEXT_COLOR, size=13),
        xaxis=dict(gridcolor=GRID_COLOR, zeroline=False,
                   showline=True, linecolor="#30363d"),
        yaxis=dict(gridcolor=GRID_COLOR, zeroline=False,
                   showline=True, linecolor="#30363d"),
        hoverlabel=dict(bgcolor="#161b22", bordercolor="#30363d",
                        font_color=TEXT_COLOR),
        margin=dict(l=60, r=30, t=60, b=60),
        title_x=0.5,
        title_font=dict(size=18, color=TEXT_COLOR),
    )


# ── App setup ─────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="Baseball Dashboard",
    update_title=None,
)
server = app.server

# ── Layout ────────────────────────────────────────────────────────────────────

SIDEBAR_STYLE = {
    "height": "100vh",
    "overflowY": "auto",
    "padding": "1.25rem 1rem",
    "backgroundColor": "#010409",
    "borderRight": "1px solid #21262d",
    "position": "sticky",
    "top": 0,
}

CONTENT_STYLE = {
    "minHeight": "100vh",
    "padding": "1.5rem 2rem",
    "backgroundColor": "#0d1117",
}


def serve_layout():
    p = parse_url_params()

    view     = p.get("view", "Team Stats")
    t_season = safe_int(p.get("season"), config["current_year"])
    t_season = t_season if t_season in TEAM_SEASONS else TEAM_SEASONS[0]
    t_display = p.get("display", "Names")
    t_x_type  = p.get("x_type", "Batting")
    t_y_type  = p.get("y_type", "Pitching")
    t_x_stat  = p.get("x_stat", "WAR")
    t_y_stat  = p.get("y_stat", "SIERA")
    show_v    = p.get("show_v", "true") == "true"
    show_h    = p.get("show_h", "true") == "true"
    mean_val  = (["v"] if show_v else []) + (["h"] if show_h else [])

    p_season  = safe_int(p.get("p_season"), config["current_year"])
    p_season  = p_season if p_season in PLAYER_SEASONS else PLAYER_SEASONS[0]
    p_type    = p.get("player_type", "Batters")
    p_x_stat  = p.get("p_x_stat", "WAR")
    p_y_stat  = p.get("p_y_stat", "wRC+")

    raw_pa = p.get("min_pa", "Qualified")
    p_min_pa = raw_pa if raw_pa == "Qualified" else safe_int(raw_pa, "Qualified")
    raw_ip = p.get("min_ip", "Qualified")
    p_min_ip = raw_ip if raw_ip == "Qualified" else safe_int(raw_ip, "Qualified")
    p_team   = p.get("team", "All Teams")

    return html.Div([
        dcc.Location(id="url", refresh=False),

        dbc.Row([
            # ── Sidebar ───────────────────────────────────────────────────────
            dbc.Col(html.Div([
                html.Div([
                    html.Span("⚾ ", style={"fontSize": "1.3rem"}),
                    html.Span("Baseball Dashboard",
                              style={"fontWeight": 700, "fontSize": "1.05rem",
                                     "color": "#f0f6fc"}),
                ], className="text-center mb-1"),
                html.P("Statistics Explorer", className="text-center mb-3",
                       style={"color": "#8b949e", "fontSize": "0.8rem"}),

                html.Hr(style={"borderColor": "#21262d",
                               "margin": "0.5rem 0 0.75rem"}),

                make_label("View"),
                dbc.RadioItems(
                    id="view",
                    options=[{"label": "Team Stats",   "value": "Team Stats"},
                             {"label": "Player Stats", "value": "Player Stats"}],
                    value=view,
                    input_class_name="me-2",
                    className="mb-1",
                ),

                html.Hr(style={"borderColor": "#21262d", "margin": "0.75rem 0"}),

                # ── Team Stats controls ───────────────────────────────────────
                html.Div(id="team-controls", children=[
                    make_label("Season"),
                    dcc.Dropdown(id="team-season", options=opts(TEAM_SEASONS),
                                 value=t_season, clearable=False,
                                 className="mb-1"),

                    make_label("Display teams as"),
                    dbc.RadioItems(id="display", options=["Logos", "Names"],
                                   value=t_display, inline=True,
                                   input_class_name="me-2", className="mb-1"),

                    make_label("X-axis type"),
                    dbc.RadioItems(id="x-type", options=["Batting", "Pitching"],
                                   value=t_x_type, inline=True,
                                   input_class_name="me-2", className="mb-1"),

                    make_label("X-axis stat"),
                    dcc.Dropdown(id="x-stat", value=t_x_stat,
                                 clearable=False, className="mb-1"),

                    make_label("Y-axis type"),
                    dbc.RadioItems(id="y-type", options=["Batting", "Pitching"],
                                   value=t_y_type, inline=True,
                                   input_class_name="me-2", className="mb-1"),

                    make_label("Y-axis stat"),
                    dcc.Dropdown(id="y-stat", value=t_y_stat,
                                 clearable=False, className="mb-1"),

                    make_label("Reference lines"),
                    dbc.Checklist(
                        id="mean-lines",
                        options=[{"label": " Vertical mean",   "value": "v"},
                                 {"label": " Horizontal mean", "value": "h"}],
                        value=mean_val, className="mb-1",
                    ),
                ]),

                # ── Player Stats controls ─────────────────────────────────────
                html.Div(id="player-controls", children=[
                    make_label("Season"),
                    dcc.Dropdown(id="player-season", options=opts(PLAYER_SEASONS),
                                 value=p_season, clearable=False,
                                 className="mb-1"),

                    make_label("Stats type"),
                    dbc.RadioItems(id="player-type", options=["Batters", "Pitchers"],
                                   value=p_type, inline=True,
                                   input_class_name="me-2", className="mb-1"),

                    make_label("X-axis stat"),
                    dcc.Dropdown(id="p-x-stat", value=p_x_stat,
                                 clearable=False, className="mb-1"),

                    make_label("Y-axis stat"),
                    dcc.Dropdown(id="p-y-stat", value=p_y_stat,
                                 clearable=False, className="mb-1"),

                    html.Div(id="min-pa-div", children=[
                        make_label("Min plate appearances"),
                        dcc.Dropdown(id="min-pa", options=opts(MIN_PA_LIST),
                                     value=p_min_pa, clearable=False,
                                     className="mb-1"),
                    ]),

                    html.Div(id="min-ip-div", children=[
                        make_label("Min innings pitched"),
                        dcc.Dropdown(id="min-ip", options=opts(MIN_IP_LIST),
                                     value=p_min_ip, clearable=False,
                                     className="mb-1"),
                    ]),

                    make_label("Team filter"),
                    dcc.Dropdown(id="team-filter", value=p_team,
                                 clearable=False, className="mb-1"),
                ]),

                html.Hr(style={"borderColor": "#21262d",
                               "margin": "1rem 0 0.5rem"}),
                html.P([
                    html.I(className="bi bi-link-45deg me-1"),
                    "URL updates automatically — copy to share.",
                ], style={"color": "#8b949e", "fontSize": "0.75rem"},
                   className="mb-0"),

            ], style=SIDEBAR_STYLE), width=3, className="p-0"),

            # ── Main content ──────────────────────────────────────────────────
            dbc.Col(html.Div([
                html.Div(id="chart-header", className="mb-3"),
                dcc.Graph(
                    id="main-graph",
                    config={"displayModeBar": True,
                            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
                            "toImageButtonOptions": {"format": "png", "scale": 2}},
                    style={"height": "78vh"},
                ),
                html.Div(id="data-info",
                         style={"color": "#8b949e", "fontSize": "0.8rem",
                                "marginTop": "0.5rem"}),
            ], style=CONTENT_STYLE), width=9, className="p-0"),
        ], className="g-0"),

        html.Footer([
            html.Hr(style={"borderColor": "#21262d"}),
            html.P([
                "Data from ",
                html.A("Fangraphs", href="https://www.fangraphs.com/",
                       style={"color": ACCENT}),
                " via pybaseball · Visualized with Plotly Dash",
            ], className="text-center mb-0",
               style={"color": "#8b949e", "fontSize": "0.8rem"}),
        ], className="py-2 px-4", style={"backgroundColor": "#010409"}),
    ])


app.layout = serve_layout

# ── Visibility callbacks ───────────────────────────────────────────────────────

@app.callback(
    Output("team-controls",   "style"),
    Output("player-controls", "style"),
    Input("view", "value"),
)
def toggle_view(view):
    if view == "Team Stats":
        return {}, {"display": "none"}
    return {"display": "none"}, {}


@app.callback(
    Output("min-pa-div", "style"),
    Output("min-ip-div", "style"),
    Input("player-type", "value"),
)
def toggle_min_filters(player_type):
    if player_type == "Batters":
        return {}, {"display": "none"}
    return {"display": "none"}, {}


# ── Stat option callbacks ──────────────────────────────────────────────────────
# These update OPTIONS only (not value) to avoid hard circular dependencies.
# If the current value isn't in the new options Dash sets it to None, which
# is fine — the user picks a new stat or filter_*_seasons re-routes them.

@app.callback(
    Output("x-stat", "options"),
    Output("x-stat", "value"),
    Input("x-type", "value"),
    Input("team-season", "value"),
    State("x-stat", "value"),
)
def update_x_stat(x_type, season, current):
    key = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    df = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], no_update
    cols = process_columns(df.columns)
    new_val = current if current in cols else cols[0]
    return opts(cols), new_val


@app.callback(
    Output("y-stat", "options"),
    Output("y-stat", "value"),
    Input("y-type", "value"),
    Input("team-season", "value"),
    State("y-stat", "value"),
)
def update_y_stat(y_type, season, current):
    key = "team_batting_dir" if y_type == "Batting" else "team_pitching_dir"
    df = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], no_update
    cols = process_columns(df.columns)
    new_val = current if current in cols else cols[0]
    return opts(cols), new_val


@app.callback(
    Output("p-x-stat", "options"),
    Output("p-x-stat", "value"),
    Output("p-y-stat", "options"),
    Output("p-y-stat", "value"),
    Input("player-type",   "value"),
    Input("player-season", "value"),
    State("p-x-stat", "value"),
    State("p-y-stat", "value"),
)
def update_player_stats(player_type, season, cur_x, cur_y):
    key = ("qualified_batting_dir" if player_type == "Batters"
           else "qualified_pitching_dir")
    df = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], no_update, [], no_update
    if player_type == "Batters" and "WAR" in df.columns and "PA" in df.columns:
        df = df.copy()
        df["WAR/650 PAs"] = (df["WAR"] / df["PA"] * 650).round(2)
    cols = process_columns(df.columns)
    x_val = cur_x if cur_x in cols else cols[0]
    y_val = cur_y if cur_y in cols else (cols[1] if len(cols) > 1 else cols[0])
    return opts(cols), x_val, opts(cols), y_val


# ── Season filter callbacks ────────────────────────────────────────────────────
# When a stat is chosen, restrict the season dropdown to years that actually
# have non-null data for that stat (e.g. EV → 2015+).
# Circular dependency with update_x_stat/update_player_stats is intentional
# and terminates because no_update is returned when the value didn't change.

@app.callback(
    Output("team-season", "options"),
    Output("team-season", "value"),
    Input("x-stat",  "value"),
    Input("y-stat",  "value"),
    Input("x-type",  "value"),
    Input("y-type",  "value"),
    State("team-season", "value"),
    prevent_initial_call=True,
)
def filter_team_seasons(x_stat, y_stat, x_type, y_type, current):
    valid = set(TEAM_SEASONS)
    for stat, type_ in ((x_stat, x_type), (y_stat, y_type)):
        if stat:
            dir_key = ("team_batting_dir" if type_ == "Batting"
                       else "team_pitching_dir")
            avail = seasons_with_data(dir_key, stat)
            if avail:
                valid &= avail
    filtered = sorted([s for s in TEAM_SEASONS if s in valid], reverse=True)
    if not filtered:
        filtered = list(TEAM_SEASONS)
    value = current if current in filtered else filtered[0]
    # no_update when nothing changed — stops the circular chain
    return opts(filtered), (value if value != current else no_update)


@app.callback(
    Output("player-season", "options"),
    Output("player-season", "value"),
    Input("p-x-stat",    "value"),
    Input("p-y-stat",    "value"),
    Input("player-type", "value"),
    State("player-season", "value"),
    prevent_initial_call=True,
)
def filter_player_seasons(x_stat, y_stat, player_type, current):
    dir_key = ("qualified_batting_dir" if player_type == "Batters"
               else "qualified_pitching_dir")
    valid = set(PLAYER_SEASONS)
    for stat in (x_stat, y_stat):
        if stat:
            avail = seasons_with_data(dir_key, stat)
            if avail:
                valid &= avail
    filtered = sorted([s for s in PLAYER_SEASONS if s in valid], reverse=True)
    if not filtered:
        filtered = list(PLAYER_SEASONS)
    value = current if current in filtered else filtered[0]
    return opts(filtered), (value if value != current else no_update)


# ── Team filter options ────────────────────────────────────────────────────────

@app.callback(
    Output("team-filter", "options"),
    Output("team-filter", "value"),
    Input("player-type",   "value"),
    Input("player-season", "value"),
    State("team-filter",   "value"),
)
def update_team_filter(player_type, season, current):
    key = ("qualified_batting_dir" if player_type == "Batters"
           else "qualified_pitching_dir")
    df = load_csv(f"{config[key]}/{season}.csv")
    base = [{"label": "All Teams", "value": "All Teams"},
            {"label": "AL",        "value": "AL"},
            {"label": "NL",        "value": "NL"}]
    if df.empty or "Team" not in df.columns:
        return base, "All Teams"
    teams = sorted(t for t in df["Team"].unique()
                   if t not in ("- - -", ""))
    options = base + opts(teams)
    valid   = {o["value"] for o in options}
    return options, (current if current in valid else "All Teams")


# ── URL sync ──────────────────────────────────────────────────────────────────

@app.callback(
    Output("url", "search"),
    Input("view",          "value"),
    Input("team-season",   "value"),
    Input("display",       "value"),
    Input("x-type",        "value"),
    Input("y-type",        "value"),
    Input("x-stat",        "value"),
    Input("y-stat",        "value"),
    Input("mean-lines",    "value"),
    Input("player-season", "value"),
    Input("player-type",   "value"),
    Input("p-x-stat",      "value"),
    Input("p-y-stat",      "value"),
    Input("min-pa",        "value"),
    Input("min-ip",        "value"),
    Input("team-filter",   "value"),
    prevent_initial_call=True,
)
def sync_url(view, t_season, display, x_type, y_type, x_stat, y_stat, mean_lines,
             p_season, player_type, p_x_stat, p_y_stat, min_pa, min_ip, team):
    ml = mean_lines or []
    if view == "Team Stats":
        params = dict(view=view, season=t_season,
                      display=display or "Names",
                      x_type=x_type or "Batting",
                      y_type=y_type or "Pitching",
                      x_stat=x_stat or "",
                      y_stat=y_stat or "",
                      show_v="true" if "v" in ml else "false",
                      show_h="true" if "h" in ml else "false")
    else:
        params = dict(view=view, p_season=p_season,
                      player_type=player_type or "Batters",
                      p_x_stat=p_x_stat or "",
                      p_y_stat=p_y_stat or "",
                      min_pa=min_pa if player_type == "Batters" else "Qualified",
                      min_ip=min_ip if player_type == "Pitchers" else "Qualified",
                      team=team or "All Teams")
    return "?" + urlencode(params)


# ── Graph render ──────────────────────────────────────────────────────────────

@app.callback(
    Output("main-graph",   "figure"),
    Output("chart-header", "children"),
    Output("data-info",    "children"),
    Input("view",          "value"),
    Input("team-season",   "value"),
    Input("display",       "value"),
    Input("x-type",        "value"),
    Input("y-type",        "value"),
    Input("x-stat",        "value"),
    Input("y-stat",        "value"),
    Input("mean-lines",    "value"),
    Input("player-season", "value"),
    Input("player-type",   "value"),
    Input("p-x-stat",      "value"),
    Input("p-y-stat",      "value"),
    Input("min-pa",        "value"),
    Input("min-ip",        "value"),
    Input("team-filter",   "value"),
)
def render(view, t_season, display, x_type, y_type, x_stat, y_stat, mean_lines,
           p_season, player_type, p_x_stat, p_y_stat, min_pa, min_ip, team):
    if view == "Team Stats":
        return render_team(t_season, display, x_type, y_type,
                           x_stat, y_stat, mean_lines or [])
    return render_player(p_season, player_type, p_x_stat, p_y_stat,
                         min_pa, min_ip, team)


# ── Chart helpers ─────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = ""):
    return html.Div([
        html.H4(title, className="mb-0", style={"color": "#f0f6fc"}),
        (html.Small(subtitle, style={"color": "#8b949e"}) if subtitle else None),
    ])


def empty_fig(msg: str = "No data"):
    fig = go.Figure()
    fig.update_layout(
        **base_layout(),
        annotations=[dict(text=msg, showarrow=False,
                          font=dict(size=18, color="#8b949e"),
                          xref="paper", yref="paper", x=0.5, y=0.5)],
    )
    return fig


def render_team(season, display, x_type, y_type, x_stat, y_stat, mean_lines):
    if not x_stat or not y_stat:
        return empty_fig("Select stats to view"), page_header("Team Stats"), ""

    x_df = load_csv(f"{config['team_batting_dir' if x_type == 'Batting' else 'team_pitching_dir']}/{season}.csv")
    y_df = load_csv(f"{config['team_batting_dir' if y_type == 'Batting' else 'team_pitching_dir']}/{season}.csv")

    if x_df.empty or y_df.empty:
        return empty_fig(f"No data for {season}"), page_header(f"{season} Team Stats"), ""

    for df in (x_df, y_df):
        if "teamIDfg" in df.columns:
            df.sort_values("teamIDfg", inplace=True)

    if x_stat not in x_df.columns or y_stat not in y_df.columns:
        return (empty_fig("Stat not available for this season"),
                page_header(f"{season} Team Stats"), "")

    x_vals = x_df[x_stat].reset_index(drop=True)
    y_vals = y_df[y_stat].reset_index(drop=True)
    teams  = (x_df["Team"] if "Team" in x_df.columns
              else y_df["Team"]).reset_index(drop=True)

    # Check for actual data (stat might exist as all-NaN column)
    if x_vals.isna().all() or y_vals.isna().all():
        return (empty_fig(f"{x_stat} or {y_stat} has no data for {season}"),
                page_header(f"{season} Team Stats"), "")

    show_v = "v" in mean_lines
    show_h = "h" in mean_lines

    fig = go.Figure()

    if display == "Logos":
        # ── Logos via Plotly layout images, all same size in paper coords ──
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="markers",
            marker=dict(size=1, opacity=0),
            text=teams,
            hovertemplate=(f"<b>%{{text}}</b><br>"
                           f"{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}"
                           "<extra></extra>"),
        ))

        # Convert data coords → paper [0,1] with explicit padded axis range
        x_min, x_max = float(x_vals.min()), float(x_vals.max())
        y_min, y_max = float(y_vals.min()), float(y_vals.max())
        x_pad = (x_max - x_min) * 0.12 or 0.5
        y_pad = (y_max - y_min) * 0.12 or 0.5
        x_lo, x_hi = x_min - x_pad, x_max + x_pad
        y_lo, y_hi = y_min - y_pad, y_max + y_pad

        images = []
        for team, xv, yv in zip(teams, x_vals, y_vals):
            src = logo_b64(str(team))
            if src:
                xp = (float(xv) - x_lo) / (x_hi - x_lo)
                yp = (float(yv) - y_lo) / (y_hi - y_lo)
                images.append(dict(
                    source=src,
                    xref="paper", yref="paper",
                    x=xp, y=yp,
                    # Fixed size in paper coords → consistent on screen
                    sizex=0.07, sizey=0.11,
                    sizing="contain",
                    xanchor="center", yanchor="middle",
                    layer="above",
                ))
        fig.update_layout(
            images=images,
            xaxis_range=[x_lo, x_hi],
            yaxis_range=[y_lo, y_hi],
        )
    else:
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="markers+text",
            text=teams,
            textposition="top center",
            textfont=dict(size=11, color=TEXT_COLOR),
            marker=dict(size=8, color=ACCENT, opacity=0.85),
            hovertemplate=(f"<b>%{{text}}</b><br>"
                           f"{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}"
                           "<extra></extra>"),
        ))

    if show_h:
        mean_y = float(x_vals.mean() if False else y_vals.mean())
        fig.add_hline(y=mean_y, line_dash="dash",
                      line_color="rgba(240,246,252,0.3)",
                      annotation_text=f"Avg: {mean_y:.2f}",
                      annotation_font_color="#8b949e")
    if show_v:
        mean_x = float(x_vals.mean())
        fig.add_vline(x=mean_x, line_dash="dash",
                      line_color="rgba(240,246,252,0.3)",
                      annotation_text=f"Avg: {mean_x:.2f}",
                      annotation_font_color="#8b949e")

    fig.update_layout(
        **base_layout(),
        xaxis_title=f"{x_type}: {x_stat}",
        yaxis_title=f"{y_type}: {y_stat}",
        showlegend=False,
    )

    subtitle = f"{x_type} {x_stat}  ·  {y_type} {y_stat}  ·  {len(teams)} teams"
    return fig, page_header(f"{season} Team Statistics", subtitle), ""


def render_player(season, player_type, x_stat, y_stat, min_pa, min_ip, team):
    if not x_stat or not y_stat:
        return empty_fig("Select stats to view"), page_header("Player Stats"), ""

    is_batter = (player_type == "Batters")
    min_val, col = (min_pa, "PA") if is_batter else (min_ip, "IP")
    use_qualified = (min_val == "Qualified")
    q_key   = "qualified_batting_dir"  if is_batter else "qualified_pitching_dir"
    all_key = "all_batting_dir"        if is_batter else "all_pitching_dir"

    df = load_csv(f"{config[q_key if use_qualified else all_key]}/{season}.csv")
    if df.empty:
        return empty_fig(f"No data for {season}"), page_header(f"{season} {player_type}"), ""

    df = df.copy()
    if is_batter and "WAR" in df.columns and "PA" in df.columns:
        df["WAR/650 PAs"] = (df["WAR"] / df["PA"] * 650).round(2)

    if not use_qualified and col in df.columns:
        try:
            df = df[df[col] >= int(min_val)]
        except (TypeError, ValueError):
            pass

    if   team == "NL":        df = df[df["Team"].isin(NL_TEAMS)]
    elif team == "AL":        df = df[df["Team"].isin(AL_TEAMS)]
    elif team not in (None, "All Teams"):
        df = df[df["Team"] == team]

    if df.empty:
        return (empty_fig("No players match the selected filters"),
                page_header(f"{season} {player_type}"),
                "Try relaxing the filters.")

    if x_stat not in df.columns or y_stat not in df.columns:
        return empty_fig("Stat not available"), page_header(f"{season} {player_type}"), ""

    if df[x_stat].isna().all() or df[y_stat].isna().all():
        return (empty_fig(f"{x_stat} or {y_stat} has no data for {season}"),
                page_header(f"{season} {player_type}"), "")

    def fmt(name):
        parts = str(name).split()
        return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) >= 2 else name

    df["Label"] = df["Name"].apply(fmt)
    use_color   = team in (None, "All Teams", "AL", "NL")

    fig = px.scatter(
        df, x=x_stat, y=y_stat,
        text="Label",
        hover_name="Name",
        hover_data={x_stat: True, y_stat: True, "Team": True, "Label": False},
        color=("Team" if use_color else None),
        template="plotly_dark",
    )
    fig.update_traces(
        mode="markers+text",
        textposition="top center",
        textfont=dict(size=9, color=TEXT_COLOR),
        marker=dict(size=7, opacity=0.85),
    )
    fig.update_layout(
        **base_layout(),
        xaxis_title=x_stat,
        yaxis_title=y_stat,
        showlegend=use_color and team in ("AL", "NL"),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#21262d",
                    borderwidth=1),
    )

    min_info = ("Qualified" if use_qualified else f"min {col} ≥ {min_val}")
    subtitle = f"{x_stat}  ·  {y_stat}  ·  {len(df)} players  ·  {min_info}"
    return (fig,
            page_header(f"{season} {player_type}", subtitle),
            f"Team filter: {team or 'All Teams'}")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
