#!/usr/bin/env python3
"""Chart layer — theme-aware Plotly layouts and the team/player scatter renderers."""

from dash import html
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from data import (
    config, load_csv, process_columns, stat_higher_better,
    TEAM_COLORS, NL_TEAMS, AL_TEAMS, PALETTE, RANK_COLORSCALE, logo_b64,
)

RANK_COLORS = [c for _, c in RANK_COLORSCALE]   # flat list for plotly express
MEAN_LINE = "rgba(245,165,36,0.55)"             # amber reference line
MEAN_PLANE = "rgba(245,165,36,0.16)"            # amber reference plane


# ── Theme-aware layout helpers ────────────────────────────────────────────────

def base_layout(theme: str = "dark") -> dict:
    c = PALETTE[theme]
    axis = dict(
        gridcolor=c["grid"], gridwidth=1, zeroline=False,
        showline=True, linecolor=c["axis"], linewidth=1,
        tickfont=dict(color=c["muted"], size=11),
        title_font=dict(color=c["text"], size=13),
        ticks="outside", ticklen=4, tickcolor=c["axis"],
    )
    return dict(
        plot_bgcolor=c["plot"], paper_bgcolor=c["paper"],
        font=dict(color=c["text"], size=13,
                  family="Geist, ui-sans-serif, system-ui, -apple-system, sans-serif"),
        xaxis=axis, yaxis=axis,
        hoverlabel=dict(bgcolor=c["hover_bg"], bordercolor=c["hover_border"],
                        font_color=c["text"], font_size=12),
        margin=dict(l=70, r=30, t=24, b=56),
    )


def base_layout_3d(theme: str = "dark") -> dict:
    c = PALETTE[theme]
    _ax = dict(
        backgroundcolor=c["plot"], gridcolor=c["grid"],
        showbackground=True, zerolinecolor=c["axis"],
        tickfont=dict(color=c["muted"], size=10),
        title_font=dict(color=c["text"], size=12),
    )
    return dict(
        paper_bgcolor=c["paper"],
        font=dict(color=c["text"], size=12,
                  family="Geist, ui-sans-serif, system-ui, -apple-system, sans-serif"),
        scene=dict(
            bgcolor=c["plot"],
            xaxis=dict(**_ax), yaxis=dict(**_ax), zaxis=dict(**_ax),
        ),
        hoverlabel=dict(bgcolor=c["hover_bg"], bordercolor=c["hover_border"],
                        font_color=c["text"], font_size=12),
        margin=dict(l=0, r=0, t=24, b=0),
    )


def colorbar_cfg(title: str, theme: str = "dark") -> dict:
    c = PALETTE[theme]
    return dict(
        title=dict(text=title, font=dict(color=c["text"], size=11)),
        tickfont=dict(color=c["text"], size=10),
        bgcolor=c["plot"], bordercolor=c["axis"], borderwidth=1,
        thickness=14, len=0.65,
        tickvals=[0, 25, 50, 75, 100],
        ticktext=["0", "25", "50", "75", "100"],
    )


def empty_fig(msg: str = "No data", theme: str = "dark"):
    c = PALETTE[theme]
    fig = go.Figure()
    fig.update_layout(
        **base_layout(theme),
        annotations=[dict(text=msg, showarrow=False,
                          font=dict(size=16, color=c["muted"]),
                          xref="paper", yref="paper", x=0.5, y=0.5)],
    )
    return fig


def compute_composite_rank(*items) -> pd.Series:
    """Composite 0–100 percentile across (series, higher_is_better) pairs.

    Each axis is ranked, and axes where lower is better (e.g. ERA) are
    inverted, so a higher composite always means better.
    """
    ranks = []
    for series, higher in items:
        r = series.rank(pct=True, na_option="keep")
        ranks.append(r if higher else 1.0 - r)
    return pd.concat(ranks, axis=1).mean(axis=1).fillna(0.5) * 100


def rank_items(*axes):
    """Build compute_composite_rank args from (series, stat, is_pitching)
    triples, skipping axes whose series is None (e.g. no Z axis)."""
    return [(series, stat_higher_better(stat, is_pitching))
            for series, stat, is_pitching in axes if series is not None]


def add_mean_planes_3d(fig, x_vals, y_vals, z_vals, show_x_plane, show_y_plane):
    """Add semi-transparent amber mean reference planes to a 3D figure.

    The x/y planes follow the 2D vertical/horizontal-mean toggles; the z plane
    is always drawn because there is no third toggle in the UI."""
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
        colorscale=[[0, MEAN_PLANE], [1, MEAN_PLANE]],
        showscale=False, hoverinfo="skip", showlegend=False,
    )
    if show_x_plane:
        mx = float(x_vals.mean())
        fig.add_trace(go.Surface(x=[[mx, mx], [mx, mx]], y=[[ylo, yhi], [ylo, yhi]],
                                 z=[[zlo, zlo], [zhi, zhi]], **_plane))
    if show_y_plane:
        my = float(y_vals.mean())
        fig.add_trace(go.Surface(x=[[xlo, xhi], [xlo, xhi]], y=[[my, my], [my, my]],
                                 z=[[zlo, zlo], [zhi, zhi]], **_plane))
    mz = float(z_vals.mean())
    fig.add_trace(go.Surface(x=[[xlo, xhi], [xlo, xhi]], y=[[ylo, ylo], [yhi, yhi]],
                             z=[[mz, mz], [mz, mz]], **_plane))


# ── Topbar title builders ─────────────────────────────────────────────────────

def _eyebrow(view: str, year, is_3d: bool):
    dot = html.Span("·", className="dot")
    return [("3D SCATTER" if is_3d else "2D SCATTER"), dot,
            ("PLAYERS" if view == "player" else "TEAMS"), dot, str(year)]


def _title(y_label: str, x_label: str, z_label: str | None = None):
    out = [html.Span(y_label, className="ax"),
           html.Span("vs", className="vs"),
           html.Span(x_label, className="ax")]
    if z_label:
        out += [html.Span("·", className="vs"), html.Span(z_label, className="ax")]
    return out


def _err(msg: str, theme: str):
    return empty_fig(msg, theme), ["—"], [html.Span(msg, className="ax")]


# ── Team render ───────────────────────────────────────────────────────────────

def render_team(season, show_logos, x_type, y_type, x_stat, y_stat,
                show_v, show_h, use_color_rank, z_type, z_stat, theme="dark"):
    c = PALETTE[theme]
    if not x_stat or not y_stat:
        return _err("Select stats to view", theme)

    xkey = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    ykey = "team_batting_dir" if y_type == "Batting" else "team_pitching_dir"
    x_df = load_csv(f"{config[xkey]}/{season}.csv")
    y_df = load_csv(f"{config[ykey]}/{season}.csv")

    if x_df.empty or y_df.empty:
        return _err(f"No data for {season}", theme)
    if "Team" not in x_df.columns or "Team" not in y_df.columns:
        return _err(f"No team data for {season}", theme)
    if x_stat not in x_df.columns or y_stat not in y_df.columns:
        return _err("Stat not available for this season", theme)

    # Join axes on Team so values loaded from different CSVs (batting vs
    # pitching, possibly stored in different row orders) pair up by team
    # rather than by row position.
    merged = pd.merge(
        x_df[["Team", x_stat]].rename(columns={x_stat: "_x"}),
        y_df[["Team", y_stat]].rename(columns={y_stat: "_y"}),
        on="Team",
    )

    # 3D: load Z data
    is_3d = False
    if z_stat:
        zkey = "team_batting_dir" if z_type == "Batting" else "team_pitching_dir"
        z_df = load_csv(f"{config[zkey]}/{season}.csv")
        if (not z_df.empty and "Team" in z_df.columns
                and z_stat in z_df.columns and not z_df[z_stat].isna().all()):
            merged = pd.merge(
                merged, z_df[["Team", z_stat]].rename(columns={z_stat: "_z"}),
                on="Team",
            )
            is_3d = True

    if merged.empty:
        return _err(f"No data for {season}", theme)
    x_vals = merged["_x"]
    y_vals = merged["_y"]
    z_vals = merged["_z"] if is_3d else None
    teams  = merged["Team"]

    if x_vals.isna().all() or y_vals.isna().all():
        return _err(f"{x_stat} or {y_stat} has no data for {season}", theme)

    rank_score = None
    if use_color_rank:
        items = rank_items((x_vals, x_stat, x_type == "Pitching"),
                           (y_vals, y_stat, y_type == "Pitching"),
                           (z_vals, z_stat, z_type == "Pitching"))
        rank_score = compute_composite_rank(*items).round(1)

    fig = go.Figure()

    if is_3d:
        if use_color_rank:
            marker = dict(size=8, color=rank_score, colorscale=RANK_COLORSCALE,
                          cmin=0, cmax=100, showscale=True,
                          colorbar=colorbar_cfg("Composite<br>Rank", theme),
                          opacity=0.95, line=dict(color=c["marker_line"], width=1))
        else:
            marker = dict(size=8,
                          color=[TEAM_COLORS.get(str(t), c["accent"]) for t in teams],
                          opacity=0.95, line=dict(color=c["marker_line"], width=1))
        hover_rank = "<br>Composite rank: %{customdata:.1f}" if use_color_rank else ""
        fig.add_trace(go.Scatter3d(
            x=x_vals, y=y_vals, z=z_vals, mode="markers+text",
            text=teams, textposition="top center",
            textfont=dict(size=10, color=c["text"]), marker=marker,
            customdata=rank_score if use_color_rank else None,
            hovertemplate=(f"<b>%{{text}}</b><br>{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}<br>"
                           f"{z_type} {z_stat}: %{{z:.2f}}" + hover_rank + "<extra></extra>"),
        ))
        add_mean_planes_3d(fig, x_vals, y_vals, z_vals, show_v, show_h)
        layout = base_layout_3d(theme)
        layout["scene"]["xaxis"]["title"] = f"{x_type}: {x_stat}"
        layout["scene"]["yaxis"]["title"] = f"{y_type}: {y_stat}"
        layout["scene"]["zaxis"]["title"] = f"{z_type}: {z_stat}"
        fig.update_layout(**layout, showlegend=False)

    elif show_logos and not use_color_rank:
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="markers",
            marker=dict(size=18, opacity=0),   # invisible but clickable hit target
            text=teams,
            hovertemplate=(f"<b>%{{text}}</b><br>{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}<extra></extra>"),
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
                # Anchored in data coordinates so logos track zoom/pan.
                images.append(dict(
                    source=src, xref="x", yref="y",
                    x=float(xv), y=float(yv),
                    sizex=(x_hi - x_lo) * 0.07, sizey=(y_hi - y_lo) * 0.11,
                    sizing="contain",
                    xanchor="center", yanchor="middle", layer="above",
                ))
        fig.update_layout(images=images,
                          xaxis_range=[x_lo, x_hi], yaxis_range=[y_lo, y_hi])

    else:
        if use_color_rank:
            marker = dict(size=14, color=rank_score, colorscale=RANK_COLORSCALE,
                          cmin=0, cmax=100, showscale=True,
                          colorbar=colorbar_cfg("Composite<br>Rank", theme),
                          opacity=0.95, line=dict(color=c["marker_line"], width=1.5))
        else:
            marker = dict(size=14,
                          color=[TEAM_COLORS.get(str(t), c["accent"]) for t in teams],
                          opacity=0.95, line=dict(color=c["marker_line"], width=1.5))
        hover_rank = "<br>Composite rank: %{customdata:.1f}" if use_color_rank else ""
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="markers+text",
            text=teams, textposition="top center",
            textfont=dict(size=11, color=c["text"], family="Geist, sans-serif"),
            marker=marker, customdata=rank_score if use_color_rank else None,
            hovertemplate=(f"<b>%{{text}}</b><br>{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}" + hover_rank + "<extra></extra>"),
        ))

    if show_h:
        mean_y = float(y_vals.mean())
        fig.add_hline(y=mean_y, line_dash="dot", line_color=MEAN_LINE, line_width=1.5,
                      annotation_text=f"avg {mean_y:.2f}", annotation_position="top right",
                      annotation_font=dict(color=c["muted"], size=11))
    if show_v:
        mean_x = float(x_vals.mean())
        fig.add_vline(x=mean_x, line_dash="dot", line_color=MEAN_LINE, line_width=1.5,
                      annotation_text=f"avg {mean_x:.2f}", annotation_position="top right",
                      annotation_font=dict(color=c["muted"], size=11))

    if not is_3d:
        fig.update_layout(**base_layout(theme),
                          xaxis_title=f"{x_type}: {x_stat}",
                          yaxis_title=f"{y_type}: {y_stat}", showlegend=False)

    eyebrow = _eyebrow("team", season, is_3d)
    title = _title(f"{y_stat}", f"{x_stat}", z_stat if is_3d else None)
    return fig, eyebrow, title


# ── Player render ─────────────────────────────────────────────────────────────

def render_player(season, player_type, x_stat, y_stat, min_pa, min_ip, team,
                  use_color_rank, z_stat, theme="dark"):
    c = PALETTE[theme]
    if not x_stat or not y_stat:
        return _err("Select stats to view", theme)

    is_batter    = (player_type == "Batters")
    min_val, col = (min_pa, "PA") if is_batter else (min_ip, "IP")
    use_qualified = (min_val == "Qualified")
    q_key   = "qualified_batting_dir"  if is_batter else "qualified_pitching_dir"
    all_key = "all_batting_dir"        if is_batter else "all_pitching_dir"

    df = load_csv(f"{config[q_key if use_qualified else all_key]}/{season}.csv")
    if df.empty:
        return _err(f"No data for {season}", theme)

    df = df.copy()
    if is_batter and "WAR" in df.columns and "PA" in df.columns:
        # PA can be 0 in the qual=0 data; leave those rows NaN instead of inf.
        pa = df["PA"].where(df["PA"] > 0)
        df["WAR/650 PAs"] = (df["WAR"] / pa * 650).round(2)

    if not use_qualified and col in df.columns:
        try:
            df = df[df[col] >= int(min_val)]
        except (TypeError, ValueError):
            pass

    if   team == "NL":                    df = df[df["Team"].isin(NL_TEAMS)]
    elif team == "AL":                    df = df[df["Team"].isin(AL_TEAMS)]
    elif team not in (None, "All Teams"): df = df[df["Team"] == team]

    if df.empty:
        return _err("No players match the selected filters", theme)
    if x_stat not in df.columns or y_stat not in df.columns:
        return _err("Stat not available", theme)
    if df[x_stat].isna().all() or df[y_stat].isna().all():
        return _err(f"{x_stat} or {y_stat} has no data for {season}", theme)

    def fmt(name):
        parts = str(name).split()
        return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) >= 2 else name

    df["Label"]  = df["Name"].apply(fmt)
    use_team_clr = team in (None, "All Teams", "AL", "NL")
    is_3d = bool(z_stat) and z_stat in df.columns and not df[z_stat].isna().all()

    if use_color_rank:
        is_pitch = (player_type == "Pitchers")
        items = rank_items((df[x_stat], x_stat, is_pitch),
                           (df[y_stat], y_stat, is_pitch),
                           (df[z_stat] if is_3d else None, z_stat, is_pitch))
        df["Composite Rank"] = compute_composite_rank(*items).round(1).values

    if use_color_rank:
        color_col, c_map, c_scale, c_range = "Composite Rank", None, RANK_COLORS, [0, 100]
    elif use_team_clr:
        color_col, c_map, c_scale, c_range = "Team", TEAM_COLORS, None, None
    else:
        color_col, c_map, c_scale, c_range = None, None, None, None

    h_data = {x_stat: True, y_stat: True, "Team": True, "Label": False}
    if use_color_rank:
        h_data["Composite Rank"] = True

    tmpl = "plotly_dark" if theme == "dark" else "plotly_white"

    if is_3d:
        h_data[z_stat] = True
        fig = px.scatter_3d(df, x=x_stat, y=y_stat, z=z_stat, text="Label",
                            hover_name="Name", hover_data=h_data, color=color_col,
                            color_discrete_map=c_map, color_continuous_scale=c_scale,
                            range_color=c_range, template=tmpl)
        fig.update_traces(mode="markers+text", textposition="top center",
                          textfont=dict(size=9, color=c["text"]),
                          marker=dict(size=5, opacity=0.9,
                                      line=dict(color=c["marker_line"], width=0.5)))
        add_mean_planes_3d(fig, df[x_stat].dropna(), df[y_stat].dropna(),
                           df[z_stat].dropna(), show_x_plane=True, show_y_plane=True)
        layout = base_layout_3d(theme)
        layout["scene"]["xaxis"]["title"] = x_stat
        layout["scene"]["yaxis"]["title"] = y_stat
        layout["scene"]["zaxis"]["title"] = z_stat
        fig.update_layout(**layout,
                          showlegend=(use_team_clr and not use_color_rank
                                      and team in ("AL", "NL")))
        if use_color_rank:
            fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank", theme))
    else:
        fig = px.scatter(df, x=x_stat, y=y_stat, text="Label", hover_name="Name",
                         hover_data=h_data, color=color_col, color_discrete_map=c_map,
                         color_continuous_scale=c_scale, range_color=c_range, template=tmpl)
        fig.update_traces(mode="markers+text", textposition="top center",
                          textfont=dict(size=10, color=c["text"], family="Geist, sans-serif"),
                          marker=dict(size=10, opacity=0.92,
                                      line=dict(color=c["marker_line"], width=0.8)))
        fig.update_layout(**base_layout(theme), xaxis_title=x_stat, yaxis_title=y_stat,
                          showlegend=(use_team_clr and not use_color_rank
                                      and team in ("AL", "NL")),
                          legend=dict(bgcolor=c["plot"], bordercolor=c["axis"],
                                      borderwidth=1, font=dict(color=c["text"], size=11),
                                      itemsizing="constant"))
        if use_color_rank:
            fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank", theme))

    eyebrow = _eyebrow("player", season, is_3d)
    title = _title(f"{y_stat}", f"{x_stat}", z_stat if is_3d else None)
    return fig, eyebrow, title
