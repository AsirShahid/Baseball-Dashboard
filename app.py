#!/usr/bin/env python3
"""Baseball Statistics Dashboard — Plotly Dash with shareable URL state."""

import base64
import functools
import json
import logging
from pathlib import Path
from urllib.parse import urlencode

import dash
from dash import dcc, html, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import flask

try:
    import pybaseball as pyb
    _PYBASEBALL = True
except ImportError:
    _PYBASEBALL = False

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

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

PLOT_BG    = "#0b0f17"
PAPER_BG   = "#0b0f17"
GRID_COLOR = "#1f2630"
AXIS_LINE  = "#2a3340"
ACCENT     = "#7aa2f7"
TEXT_COLOR = "#e6edf3"
MUTED      = "#7d8590"
PANEL_BG   = "#070a10"

RANK_COLORSCALE = "RdYlGn"

TEAM_COLORS = {
    "ARI": "#A71930", "ATL": "#CE1141", "BAL": "#DF4601", "BOS": "#BD3039",
    "CHC": "#0E3386", "CHW": "#27251F", "CIN": "#C6011F", "CLE": "#00385D",
    "COL": "#33006F", "DET": "#0C2340", "HOU": "#EB6E1F", "KCR": "#004687",
    "LAA": "#BA0021", "LAD": "#005A9C", "MIA": "#00A3E0", "MIL": "#12284B",
    "MIN": "#002B5C", "NYM": "#FF5910", "NYY": "#003087", "OAK": "#003831",
    "PHI": "#E81828", "PIT": "#FDB827", "SDP": "#2F241D", "SEA": "#0C2C56",
    "SFG": "#FD5A1E", "STL": "#C41E3A", "TBR": "#092C5C", "TEX": "#003278",
    "TOR": "#134A8E", "WAS": "#AB0003",
}

# ── pybaseball live-fetch mapping ─────────────────────────────────────────────

_DIR_TO_FETCH = {
    config["team_batting_dir"]:      ("team_batting",    {}),
    config["team_pitching_dir"]:     ("team_pitching",   {}),
    config["qualified_batting_dir"]: ("batting_stats",   {}),
    config["all_batting_dir"]:       ("batting_stats",   {"qual": 0}),
    config["qualified_pitching_dir"]:("pitching_stats",  {}),
    config["all_pitching_dir"]:      ("pitching_stats",  {"qual": 0}),
}


def _live_fetch(path: str) -> pd.DataFrame:
    """Fetch a season's data via pybaseball and cache it as CSV."""
    if not _PYBASEBALL:
        return pd.DataFrame()
    p = Path(path)
    parent = p.parent.name
    if parent not in _DIR_TO_FETCH:
        return pd.DataFrame()
    func_name, kwargs = _DIR_TO_FETCH[parent]
    try:
        year = int(p.stem)
    except ValueError:
        return pd.DataFrame()
    try:
        pyb.cache.disable()
        func = getattr(pyb, func_name)
        logging.info("pybaseball: fetching %s(%d, %s)", func_name, year, kwargs)
        df = func(year, **kwargs)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
        logging.info("pybaseball: cached %s", path)
        return df
    except Exception as exc:
        logging.error("pybaseball fetch failed for %s: %s", path, exc)
        return pd.DataFrame()


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
    """Load CSV; auto-fetches via pybaseball if the file doesn't exist."""
    try:
        if Path(path).exists():
            return pd.read_csv(path)
        return _live_fetch(path)
    except Exception:
        return pd.DataFrame()


@functools.lru_cache(maxsize=256)
def seasons_with_data(dir_key: str, stat: str) -> frozenset:
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
                  style={"fontSize": "0.68rem", "letterSpacing": "0.1em",
                         "color": MUTED})


# ── Layout helpers ─────────────────────────────────────────────────────────────

def base_layout() -> dict:
    axis = dict(
        gridcolor=GRID_COLOR, gridwidth=1, zeroline=False,
        showline=True, linecolor=AXIS_LINE, linewidth=1,
        tickfont=dict(color=MUTED, size=11),
        title_font=dict(color=TEXT_COLOR, size=13),
        ticks="outside", ticklen=4, tickcolor=AXIS_LINE,
    )
    return dict(
        plot_bgcolor=PLOT_BG, paper_bgcolor=PAPER_BG,
        font=dict(color=TEXT_COLOR, size=13,
                  family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Inter, Roboto, sans-serif"),
        xaxis=axis, yaxis=axis,
        hoverlabel=dict(bgcolor="#0f1620", bordercolor=AXIS_LINE,
                        font_color=TEXT_COLOR, font_size=12),
        margin=dict(l=70, r=30, t=30, b=60),
        title_x=0.5, title_font=dict(size=18, color=TEXT_COLOR),
        transition=dict(duration=350, easing="cubic-in-out"),
    )


def base_layout_3d() -> dict:
    _ax = dict(
        backgroundcolor=PLOT_BG, gridcolor=GRID_COLOR,
        showbackground=True, zerolinecolor=AXIS_LINE,
        tickfont=dict(color=MUTED, size=10),
        title_font=dict(color=TEXT_COLOR, size=12),
    )
    return dict(
        paper_bgcolor=PAPER_BG,
        font=dict(color=TEXT_COLOR, size=12,
                  family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Inter, Roboto, sans-serif"),
        scene=dict(
            bgcolor=PLOT_BG,
            xaxis=dict(**_ax), yaxis=dict(**_ax), zaxis=dict(**_ax),
        ),
        hoverlabel=dict(bgcolor="#0f1620", bordercolor=AXIS_LINE,
                        font_color=TEXT_COLOR, font_size=12),
        margin=dict(l=0, r=0, t=40, b=0),
        title_x=0.5, title_font=dict(size=18, color=TEXT_COLOR),
    )


def colorbar_cfg(title: str) -> dict:
    return dict(
        title=dict(text=title, font=dict(color=TEXT_COLOR, size=11)),
        tickfont=dict(color=TEXT_COLOR, size=10),
        bgcolor="rgba(11,15,23,0.7)", bordercolor=AXIS_LINE, borderwidth=1,
        thickness=14, len=0.65,
        tickvals=[0, 25, 50, 75, 100],
        ticktext=["0", "25", "50", "75", "100"],
    )


def compute_composite_rank(*series: pd.Series) -> pd.Series:
    """Average percentile rank across stat series, returned on a 0–100 scale."""
    ranks = [s.rank(pct=True, na_option="keep") for s in series]
    return pd.concat(ranks, axis=1).mean(axis=1).fillna(0.5) * 100


def add_mean_planes_3d(fig, x_vals, y_vals, z_vals, show_x_plane, show_y_plane):
    """Add semi-transparent mean reference planes to a 3D figure.

    show_x_plane → plane at mean(x), perpendicular to the X axis
    show_y_plane → plane at mean(y), perpendicular to the Y axis
    The Z mean plane is always added (it's the new dimension in 3D mode).
    """
    xlo, xhi = float(x_vals.min()), float(x_vals.max())
    ylo, yhi = float(y_vals.min()), float(y_vals.max())
    zlo, zhi = float(z_vals.min()), float(z_vals.max())
    xpad = (xhi - xlo) * 0.12 or 0.5
    ypad = (yhi - ylo) * 0.12 or 0.5
    zpad = (zhi - zlo) * 0.12 or 0.5
    xlo -= xpad; xhi += xpad
    ylo -= ypad; yhi += ypad
    zlo -= zpad; zhi += zpad

    _plane = dict(
        colorscale=[[0, "rgba(122,162,247,0.18)"], [1, "rgba(122,162,247,0.18)"]],
        showscale=False, hoverinfo="skip", showlegend=False,
    )

    if show_x_plane:
        mx = float(x_vals.mean())
        fig.add_trace(go.Surface(
            x=[[mx, mx], [mx, mx]],
            y=[[ylo, yhi], [ylo, yhi]],
            z=[[zlo, zlo], [zhi, zhi]],
            **_plane,
        ))
    if show_y_plane:
        my = float(y_vals.mean())
        fig.add_trace(go.Surface(
            x=[[xlo, xhi], [xlo, xhi]],
            y=[[my, my], [my, my]],
            z=[[zlo, zlo], [zhi, zhi]],
            **_plane,
        ))
    # Z mean plane always present — it's the axis the user just added
    mz = float(z_vals.mean())
    fig.add_trace(go.Surface(
        x=[[xlo, xhi], [xlo, xhi]],
        y=[[ylo, ylo], [yhi, yhi]],
        z=[[mz, mz], [mz, mz]],
        **_plane,
    ))


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
    "height": "100vh", "overflowY": "auto",
    "padding": "1.5rem 1.1rem",
    "backgroundColor": PANEL_BG,
    "borderRight": f"1px solid {GRID_COLOR}",
    "position": "sticky", "top": 0,
}
CONTENT_STYLE = {
    "minHeight": "100vh", "padding": "1.75rem 2.25rem",
    "backgroundColor": PLOT_BG,
}


def serve_layout():
    p = parse_url_params()

    view      = p.get("view", "Team Stats")
    t_season  = safe_int(p.get("season"), TEAM_SEASONS[0])
    t_season  = t_season if t_season in TEAM_SEASONS else TEAM_SEASONS[0]
    t_display = p.get("display", "Names")
    t_x_type  = p.get("x_type", "Batting")
    t_y_type  = p.get("y_type", "Pitching")
    t_x_stat  = p.get("x_stat", "WAR")
    t_y_stat  = p.get("y_stat", "SIERA")
    show_v    = p.get("show_v", "true") == "true"
    show_h    = p.get("show_h", "true") == "true"
    mean_val  = (["v"] if show_v else []) + (["h"] if show_h else [])
    t_cr      = ["rank"] if p.get("color_rank", "false") == "true" else []
    t_z_type  = p.get("z_type", "Batting")
    t_z_stat  = p.get("z_stat") or None

    p_season  = safe_int(p.get("p_season"), PLAYER_SEASONS[0])
    p_season  = p_season if p_season in PLAYER_SEASONS else PLAYER_SEASONS[0]
    p_type    = p.get("player_type", "Batters")
    p_x_stat  = p.get("p_x_stat", "WAR")
    p_y_stat  = p.get("p_y_stat", "wRC+")
    p_cr      = ["rank"] if p.get("p_color_rank", "false") == "true" else []
    p_z_stat  = p.get("p_z_stat") or None

    raw_pa   = p.get("min_pa", "Qualified")
    p_min_pa = raw_pa if raw_pa == "Qualified" else safe_int(raw_pa, "Qualified")
    raw_ip   = p.get("min_ip", "Qualified")
    p_min_ip = raw_ip if raw_ip == "Qualified" else safe_int(raw_ip, "Qualified")
    p_team   = p.get("team", "All Teams")

    return html.Div([
        dcc.Location(id="url", refresh=False),

        dbc.Row([
            # ── Sidebar ───────────────────────────────────────────────────────
            dbc.Col(html.Div([
                html.Div([
                    html.Span("⚾ ", style={"fontSize": "1.4rem"}),
                    html.Span("Baseball Dashboard",
                              style={"fontWeight": 700, "fontSize": "1.1rem",
                                     "color": "#f0f6fc", "letterSpacing": "-0.01em"}),
                ], className="text-center mb-1"),
                html.P("Statistics Explorer", className="text-center mb-3",
                       style={"color": MUTED, "fontSize": "0.78rem",
                              "letterSpacing": "0.05em"}),

                html.Hr(style={"borderColor": GRID_COLOR, "margin": "0.5rem 0 0.75rem"}),

                make_label("View"),
                dbc.RadioItems(
                    id="view",
                    options=[{"label": "Team Stats",   "value": "Team Stats"},
                             {"label": "Player Stats", "value": "Player Stats"}],
                    value=view, input_class_name="me-2", className="mb-1",
                ),

                html.Hr(style={"borderColor": GRID_COLOR, "margin": "0.75rem 0"}),

                # ── Team Stats controls ───────────────────────────────────────
                html.Div(id="team-controls", children=[
                    make_label("Season"),
                    dcc.Dropdown(id="team-season", options=opts(TEAM_SEASONS),
                                 value=t_season, clearable=False, className="mb-1"),

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

                    html.Hr(style={"borderColor": GRID_COLOR, "margin": "0.6rem 0 0"}),
                    make_label("Color by"),
                    dbc.Checklist(
                        id="team-color-rank",
                        options=[{"label": " Composite rank", "value": "rank"}],
                        value=t_cr, className="mb-1",
                    ),

                    make_label("Z-axis type (3D)"),
                    dbc.RadioItems(id="z-type", options=["Batting", "Pitching"],
                                   value=t_z_type, inline=True,
                                   input_class_name="me-2", className="mb-1"),

                    make_label("Z-axis stat (optional)"),
                    dcc.Dropdown(id="z-stat", value=t_z_stat,
                                 clearable=True, placeholder="None — keep 2D",
                                 className="mb-1"),
                ]),

                # ── Player Stats controls ─────────────────────────────────────
                html.Div(id="player-controls", children=[
                    make_label("Season"),
                    dcc.Dropdown(id="player-season", options=opts(PLAYER_SEASONS),
                                 value=p_season, clearable=False, className="mb-1"),

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
                                     value=p_min_pa, clearable=False, className="mb-1"),
                    ]),

                    html.Div(id="min-ip-div", children=[
                        make_label("Min innings pitched"),
                        dcc.Dropdown(id="min-ip", options=opts(MIN_IP_LIST),
                                     value=p_min_ip, clearable=False, className="mb-1"),
                    ]),

                    make_label("Team filter"),
                    dcc.Dropdown(id="team-filter", value=p_team,
                                 clearable=False, className="mb-1"),

                    html.Hr(style={"borderColor": GRID_COLOR, "margin": "0.6rem 0 0"}),
                    make_label("Color by"),
                    dbc.Checklist(
                        id="player-color-rank",
                        options=[{"label": " Composite rank", "value": "rank"}],
                        value=p_cr, className="mb-1",
                    ),

                    make_label("Z-axis stat (optional)"),
                    dcc.Dropdown(id="p-z-stat", value=p_z_stat,
                                 clearable=True, placeholder="None — keep 2D",
                                 className="mb-1"),
                ]),

                html.Hr(style={"borderColor": GRID_COLOR, "margin": "1rem 0 0.5rem"}),
                html.P([
                    html.I(className="bi bi-link-45deg me-1"),
                    "URL updates automatically — copy to share.",
                ], style={"color": MUTED, "fontSize": "0.74rem"}, className="mb-0"),
                html.P(
                    "Missing data auto-fetches via pybaseball." if _PYBASEBALL
                    else "Install pybaseball for auto-fetch.",
                    style={"color": MUTED, "fontSize": "0.70rem"}, className="mb-0 mt-1",
                ),

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
                         style={"color": MUTED, "fontSize": "0.78rem",
                                "marginTop": "0.5rem"}),
            ], style=CONTENT_STYLE), width=9, className="p-0"),
        ], className="g-0"),

        html.Footer([
            html.Hr(style={"borderColor": GRID_COLOR, "margin": 0}),
            html.P([
                "Data from ",
                html.A("Fangraphs", href="https://www.fangraphs.com/",
                       style={"color": ACCENT, "textDecoration": "none"}),
                " via pybaseball · Visualized with Plotly Dash",
            ], className="text-center mb-0",
               style={"color": MUTED, "fontSize": "0.78rem"}),
        ], className="py-3 px-4", style={"backgroundColor": PANEL_BG}),
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

@app.callback(
    Output("x-stat", "options"),
    Output("x-stat", "value"),
    Input("x-type", "value"),
    Input("team-season", "value"),
    State("x-stat", "value"),
)
def update_x_stat(x_type, season, current):
    key = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    df  = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], no_update
    cols    = process_columns(df.columns)
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
    df  = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], no_update
    cols    = process_columns(df.columns)
    new_val = current if current in cols else cols[0]
    return opts(cols), new_val


@app.callback(
    Output("z-stat", "options"),
    Output("z-stat", "value"),
    Input("z-type", "value"),
    Input("team-season", "value"),
    State("z-stat", "value"),
)
def update_z_stat(z_type, season, current):
    key = "team_batting_dir" if z_type == "Batting" else "team_pitching_dir"
    df  = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], None
    cols    = process_columns(df.columns)
    new_val = current if (current and current in cols) else None
    return opts(cols), new_val


@app.callback(
    Output("p-x-stat", "options"),
    Output("p-x-stat", "value"),
    Output("p-y-stat", "options"),
    Output("p-y-stat", "value"),
    Output("p-z-stat", "options"),
    Output("p-z-stat", "value"),
    Input("player-type",   "value"),
    Input("player-season", "value"),
    State("p-x-stat", "value"),
    State("p-y-stat", "value"),
    State("p-z-stat", "value"),
)
def update_player_stats(player_type, season, cur_x, cur_y, cur_z):
    key = ("qualified_batting_dir" if player_type == "Batters"
           else "qualified_pitching_dir")
    df = load_csv(f"{config[key]}/{season}.csv")
    if df.empty:
        return [], no_update, [], no_update, [], None
    if player_type == "Batters" and "WAR" in df.columns and "PA" in df.columns:
        df = df.copy()
        df["WAR/650 PAs"] = (df["WAR"] / df["PA"] * 650).round(2)
    cols  = process_columns(df.columns)
    x_val = cur_x if cur_x in cols else cols[0]
    y_val = cur_y if cur_y in cols else (cols[1] if len(cols) > 1 else cols[0])
    z_val = cur_z if (cur_z and cur_z in cols) else None
    return opts(cols), x_val, opts(cols), y_val, opts(cols), z_val


# ── Season filter callbacks ────────────────────────────────────────────────────

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
    df   = load_csv(f"{config[key]}/{season}.csv")
    base = [{"label": "All Teams", "value": "All Teams"},
            {"label": "AL",        "value": "AL"},
            {"label": "NL",        "value": "NL"}]
    if df.empty or "Team" not in df.columns:
        return base, "All Teams"
    teams   = sorted(t for t in df["Team"].unique() if t not in ("- - -", ""))
    options = base + opts(teams)
    valid   = {o["value"] for o in options}
    return options, (current if current in valid else "All Teams")


# ── URL sync ──────────────────────────────────────────────────────────────────

@app.callback(
    Output("url", "search"),
    Input("view",              "value"),
    Input("team-season",       "value"),
    Input("display",           "value"),
    Input("x-type",            "value"),
    Input("y-type",            "value"),
    Input("x-stat",            "value"),
    Input("y-stat",            "value"),
    Input("mean-lines",        "value"),
    Input("team-color-rank",   "value"),
    Input("z-type",            "value"),
    Input("z-stat",            "value"),
    Input("player-season",     "value"),
    Input("player-type",       "value"),
    Input("p-x-stat",          "value"),
    Input("p-y-stat",          "value"),
    Input("min-pa",            "value"),
    Input("min-ip",            "value"),
    Input("team-filter",       "value"),
    Input("player-color-rank", "value"),
    Input("p-z-stat",          "value"),
    prevent_initial_call=True,
)
def sync_url(view, t_season, display, x_type, y_type, x_stat, y_stat, mean_lines,
             team_cr, z_type, z_stat,
             p_season, player_type, p_x_stat, p_y_stat, min_pa, min_ip, team,
             player_cr, p_z_stat):
    ml  = mean_lines or []
    tcr = team_cr    or []
    pcr = player_cr  or []
    if view == "Team Stats":
        params = dict(
            view=view, season=t_season,
            display=display or "Names",
            x_type=x_type or "Batting", y_type=y_type or "Pitching",
            x_stat=x_stat or "", y_stat=y_stat or "",
            show_v="true" if "v" in ml else "false",
            show_h="true" if "h" in ml else "false",
            color_rank="true" if "rank" in tcr else "false",
            z_type=z_type or "Batting", z_stat=z_stat or "",
        )
    else:
        params = dict(
            view=view, p_season=p_season,
            player_type=player_type or "Batters",
            p_x_stat=p_x_stat or "", p_y_stat=p_y_stat or "",
            min_pa=min_pa if player_type == "Batters" else "Qualified",
            min_ip=min_ip if player_type == "Pitchers" else "Qualified",
            team=team or "All Teams",
            p_color_rank="true" if "rank" in pcr else "false",
            p_z_stat=p_z_stat or "",
        )
    return "?" + urlencode(params)


# ── Graph render ──────────────────────────────────────────────────────────────

@app.callback(
    Output("main-graph",   "figure"),
    Output("chart-header", "children"),
    Output("data-info",    "children"),
    Input("view",              "value"),
    Input("team-season",       "value"),
    Input("display",           "value"),
    Input("x-type",            "value"),
    Input("y-type",            "value"),
    Input("x-stat",            "value"),
    Input("y-stat",            "value"),
    Input("mean-lines",        "value"),
    Input("team-color-rank",   "value"),
    Input("z-type",            "value"),
    Input("z-stat",            "value"),
    Input("player-season",     "value"),
    Input("player-type",       "value"),
    Input("p-x-stat",          "value"),
    Input("p-y-stat",          "value"),
    Input("min-pa",            "value"),
    Input("min-ip",            "value"),
    Input("team-filter",       "value"),
    Input("player-color-rank", "value"),
    Input("p-z-stat",          "value"),
)
def render(view, t_season, display, x_type, y_type, x_stat, y_stat, mean_lines,
           team_cr, z_type, z_stat,
           p_season, player_type, p_x_stat, p_y_stat, min_pa, min_ip, team,
           player_cr, p_z_stat):
    if view == "Team Stats":
        return render_team(
            t_season, display, x_type, y_type, x_stat, y_stat,
            mean_lines or [],
            "rank" in (team_cr or []),
            z_type or "Batting", z_stat,
        )
    return render_player(
        p_season, player_type, p_x_stat, p_y_stat,
        min_pa, min_ip, team,
        "rank" in (player_cr or []),
        p_z_stat,
    )


# ── Chart helpers ─────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = ""):
    return html.Div([
        html.H4(title, className="mb-1",
                style={"color": "#f0f6fc", "fontWeight": 600,
                       "letterSpacing": "-0.01em"}),
        (html.Small(subtitle, style={"color": MUTED, "fontSize": "0.82rem"})
         if subtitle else None),
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


# ── Team render ───────────────────────────────────────────────────────────────

def render_team(season, display, x_type, y_type, x_stat, y_stat, mean_lines,
                use_color_rank, z_type, z_stat):
    if not x_stat or not y_stat:
        return empty_fig("Select stats to view"), page_header("Team Stats"), ""

    xkey = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    ykey = "team_batting_dir" if y_type == "Batting" else "team_pitching_dir"
    x_df = load_csv(f"{config[xkey]}/{season}.csv")
    y_df = load_csv(f"{config[ykey]}/{season}.csv")

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

    if x_vals.isna().all() or y_vals.isna().all():
        return (empty_fig(f"{x_stat} or {y_stat} has no data for {season}"),
                page_header(f"{season} Team Stats"), "")

    # 3D: load Z data
    z_vals = None
    is_3d  = False
    if z_stat:
        zkey  = "team_batting_dir" if z_type == "Batting" else "team_pitching_dir"
        z_df  = load_csv(f"{config[zkey]}/{season}.csv")
        if not z_df.empty and z_stat in z_df.columns:
            if "teamIDfg" in z_df.columns:
                z_df.sort_values("teamIDfg", inplace=True)
            _z = z_df[z_stat].reset_index(drop=True)
            if not _z.isna().all():
                z_vals = _z
                is_3d  = True

    # Composite rank (0–100)
    rank_score = None
    if use_color_rank:
        rank_score = compute_composite_rank(
            x_vals, y_vals, *([z_vals] if z_vals is not None else [])
        ).round(1)

    show_v = "v" in mean_lines
    show_h = "h" in mean_lines

    fig = go.Figure()

    if is_3d:
        # ── 3D scatter ──────────────────────────────────────────────────────
        if use_color_rank:
            marker = dict(
                size=8, color=rank_score,
                colorscale=RANK_COLORSCALE, cmin=0, cmax=100,
                showscale=True, colorbar=colorbar_cfg("Composite<br>Rank"),
                opacity=0.95, line=dict(color="rgba(255,255,255,0.7)", width=1),
            )
        else:
            marker = dict(
                size=8,
                color=[TEAM_COLORS.get(str(t), ACCENT) for t in teams],
                opacity=0.95, line=dict(color="rgba(255,255,255,0.7)", width=1),
            )
        hover_rank = "<br>Composite rank: %{customdata:.1f}" if use_color_rank else ""
        fig.add_trace(go.Scatter3d(
            x=x_vals, y=y_vals, z=z_vals,
            mode="markers+text",
            text=teams, textposition="top center",
            textfont=dict(size=10, color=TEXT_COLOR),
            marker=marker,
            customdata=rank_score if use_color_rank else None,
            hovertemplate=(
                f"<b>%{{text}}</b><br>"
                f"{x_type} {x_stat}: %{{x:.2f}}<br>"
                f"{y_type} {y_stat}: %{{y:.2f}}<br>"
                f"{z_type} {z_stat}: %{{z:.2f}}"
                + hover_rank + "<extra></extra>"
            ),
        ))
        add_mean_planes_3d(fig, x_vals, y_vals, z_vals, show_v, show_h)
        layout = base_layout_3d()
        layout["scene"]["xaxis"]["title"] = f"{x_type}: {x_stat}"
        layout["scene"]["yaxis"]["title"] = f"{y_type}: {y_stat}"
        layout["scene"]["zaxis"]["title"] = f"{z_type}: {z_stat}"
        fig.update_layout(**layout, showlegend=False)

    elif display == "Logos" and not use_color_rank:
        # ── 2D logos ─────────────────────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="markers",
            marker=dict(size=1, opacity=0),
            text=teams,
            hovertemplate=(f"<b>%{{text}}</b><br>"
                           f"{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}"
                           "<extra></extra>"),
        ))
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
                images.append(dict(
                    source=src, xref="paper", yref="paper",
                    x=(float(xv) - x_lo) / (x_hi - x_lo),
                    y=(float(yv) - y_lo) / (y_hi - y_lo),
                    sizex=0.07, sizey=0.11, sizing="contain",
                    xanchor="center", yanchor="middle", layer="above",
                ))
        fig.update_layout(images=images,
                          xaxis_range=[x_lo, x_hi],
                          yaxis_range=[y_lo, y_hi])

    else:
        # ── 2D markers (names or logos+rank override) ─────────────────────────
        if use_color_rank:
            marker = dict(
                size=14, color=rank_score,
                colorscale=RANK_COLORSCALE, cmin=0, cmax=100,
                showscale=True, colorbar=colorbar_cfg("Composite<br>Rank"),
                opacity=0.95, line=dict(color="rgba(255,255,255,0.85)", width=1.5),
            )
        else:
            marker = dict(
                size=14,
                color=[TEAM_COLORS.get(str(t), ACCENT) for t in teams],
                opacity=0.95, line=dict(color="rgba(255,255,255,0.85)", width=1.5),
            )
        hover_rank = "<br>Composite rank: %{customdata:.1f}" if use_color_rank else ""
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="markers+text",
            text=teams, textposition="top center",
            textfont=dict(size=11, color=TEXT_COLOR,
                          family="Inter, -apple-system, sans-serif"),
            marker=marker,
            customdata=rank_score if use_color_rank else None,
            hovertemplate=(
                f"<b>%{{text}}</b><br>"
                f"{x_type} {x_stat}: %{{x:.2f}}<br>"
                f"{y_type} {y_stat}: %{{y:.2f}}"
                + hover_rank + "<extra></extra>"
            ),
        ))

    if show_h:
        mean_y = float(y_vals.mean())
        fig.add_hline(y=mean_y, line_dash="dot",
                      line_color="rgba(122,162,247,0.45)", line_width=1.5,
                      annotation_text=f"avg {mean_y:.2f}",
                      annotation_position="top right",
                      annotation_font=dict(color=MUTED, size=11))
    if show_v:
        mean_x = float(x_vals.mean())
        fig.add_vline(x=mean_x, line_dash="dot",
                      line_color="rgba(122,162,247,0.45)", line_width=1.5,
                      annotation_text=f"avg {mean_x:.2f}",
                      annotation_position="top right",
                      annotation_font=dict(color=MUTED, size=11))

    if not is_3d:
        fig.update_layout(
            **base_layout(),
            xaxis_title=f"{x_type}: {x_stat}",
            yaxis_title=f"{y_type}: {y_stat}",
            showlegend=False,
        )

    parts = [f"{x_type} {x_stat}", f"{y_type} {y_stat}"]
    if is_3d:
        parts.append(f"{z_type} {z_stat}")
    parts.append(f"{len(teams)} teams")
    if use_color_rank:
        parts.append("colored by composite rank")
    subtitle = "  ·  ".join(parts)
    return fig, page_header(f"{season} Team Statistics", subtitle), ""


# ── Player render ─────────────────────────────────────────────────────────────

def render_player(season, player_type, x_stat, y_stat, min_pa, min_ip, team,
                  use_color_rank, z_stat):
    if not x_stat or not y_stat:
        return empty_fig("Select stats to view"), page_header("Player Stats"), ""

    is_batter    = (player_type == "Batters")
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

    if   team == "NL":                   df = df[df["Team"].isin(NL_TEAMS)]
    elif team == "AL":                   df = df[df["Team"].isin(AL_TEAMS)]
    elif team not in (None, "All Teams"):df = df[df["Team"] == team]

    if df.empty:
        return (empty_fig("No players match the selected filters"),
                page_header(f"{season} {player_type}"), "Try relaxing the filters.")

    if x_stat not in df.columns or y_stat not in df.columns:
        return empty_fig("Stat not available"), page_header(f"{season} {player_type}"), ""

    if df[x_stat].isna().all() or df[y_stat].isna().all():
        return (empty_fig(f"{x_stat} or {y_stat} has no data for {season}"),
                page_header(f"{season} {player_type}"), "")

    def fmt(name):
        parts = str(name).split()
        return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) >= 2 else name

    df["Label"]  = df["Name"].apply(fmt)
    use_team_clr = team in (None, "All Teams", "AL", "NL")

    is_3d = bool(z_stat) and z_stat in df.columns and not df[z_stat].isna().all()

    # Composite rank column
    if use_color_rank:
        rank_series = [df[x_stat], df[y_stat]]
        if is_3d:
            rank_series.append(df[z_stat])
        df["Composite Rank"] = compute_composite_rank(*rank_series).round(1).values

    # Determine color column
    if use_color_rank:
        color_col = "Composite Rank"
        c_map, c_scale, c_range = None, RANK_COLORSCALE, [0, 100]
    elif use_team_clr:
        color_col = "Team"
        c_map, c_scale, c_range = TEAM_COLORS, None, None
    else:
        color_col = None
        c_map, c_scale, c_range = None, None, None

    h_data_base = {x_stat: True, y_stat: True, "Team": True, "Label": False}
    if use_color_rank:
        h_data_base["Composite Rank"] = True

    if is_3d:
        h_data_base[z_stat] = True
        fig = px.scatter_3d(
            df, x=x_stat, y=y_stat, z=z_stat,
            text="Label", hover_name="Name",
            hover_data=h_data_base,
            color=color_col,
            color_discrete_map=c_map,
            color_continuous_scale=c_scale,
            range_color=c_range,
            template="plotly_dark",
        )
        fig.update_traces(
            mode="markers+text", textposition="top center",
            textfont=dict(size=9, color=TEXT_COLOR),
            marker=dict(size=5, opacity=0.9,
                        line=dict(color="rgba(255,255,255,0.4)", width=0.5)),
        )
        add_mean_planes_3d(fig,
            df[x_stat].dropna(), df[y_stat].dropna(), df[z_stat].dropna(),
            show_x_plane=True, show_y_plane=True,
        )
        layout = base_layout_3d()
        layout["scene"]["xaxis"]["title"] = x_stat
        layout["scene"]["yaxis"]["title"] = y_stat
        layout["scene"]["zaxis"]["title"] = z_stat
        fig.update_layout(**layout,
                          showlegend=(use_team_clr and not use_color_rank
                                      and team in ("AL", "NL")))
        if use_color_rank:
            fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank"))
    else:
        fig = px.scatter(
            df, x=x_stat, y=y_stat,
            text="Label", hover_name="Name",
            hover_data=h_data_base,
            color=color_col,
            color_discrete_map=c_map,
            color_continuous_scale=c_scale,
            range_color=c_range,
            template="plotly_dark",
        )
        fig.update_traces(
            mode="markers+text", textposition="top center",
            textfont=dict(size=10, color=TEXT_COLOR,
                          family="Inter, -apple-system, sans-serif"),
            marker=dict(size=10, opacity=0.92,
                        line=dict(color="rgba(255,255,255,0.6)", width=0.8)),
        )
        fig.update_layout(
            **base_layout(),
            xaxis_title=x_stat, yaxis_title=y_stat,
            showlegend=(use_team_clr and not use_color_rank and team in ("AL", "NL")),
            legend=dict(bgcolor="rgba(11,15,23,0.7)", bordercolor=AXIS_LINE,
                        borderwidth=1, font=dict(color=TEXT_COLOR, size=11),
                        itemsizing="constant"),
        )
        if use_color_rank:
            fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank"))

    min_info = "Qualified" if use_qualified else f"min {col} ≥ {min_val}"
    parts    = [x_stat, y_stat]
    if is_3d:
        parts.append(z_stat)
    parts   += [f"{len(df)} players", min_info]
    if use_color_rank:
        parts.append("colored by composite rank")
    subtitle = "  ·  ".join(parts)
    return (fig,
            page_header(f"{season} {player_type}", subtitle),
            f"Team filter: {team or 'All Teams'}")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
