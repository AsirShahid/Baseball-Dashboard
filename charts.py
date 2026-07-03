#!/usr/bin/env python3
"""Chart layer — theme-aware Plotly layouts and the team/player scatter renderers."""

from dash import html
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from data import (
    load_stats, load_stats_pct, pct_within_season, stat_higher_better,
    season_bounds, season_label, team_in_league,
    TEAM_COLORS, MULTI_TEAM, PALETTE, RANK_COLORSCALE,
    logo_b64, logo_aspect,
)

RANK_COLORS = [c for _, c in RANK_COLORSCALE]   # flat list for plotly express
MEAN_LINE = "rgba(245,165,36,0.55)"             # amber reference line
MEAN_PLANE = "rgba(245,165,36,0.16)"            # amber reference plane
TREND_LINE = "rgba(99,140,245,0.85)"            # blue OLS fit line
TRAJ_COLORS = px.colors.qualitative.Bold        # player-trajectory color cycle
DIM_OPACITY = 0.15                              # non-matching points in a search
OUTLIER_LABELS = 12                             # points labeled in Outliers mode


def _axis_dir(stat, is_pitching):
    """Return 'reversed' for lower-is-better stats, None otherwise.

    When reversed, Plotly flips the axis so up/right = good. Raw values
    are unchanged — only the visual direction flips.
    """
    return "reversed" if not stat_higher_better(stat, is_pitching) else None


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


def add_trendline(fig, x_vals, y_vals, theme: str = "dark"):
    """Add a dashed OLS fit line and an r² badge to a 2D figure.

    Silently does nothing when there are fewer than 3 paired points or an
    axis is constant (no meaningful fit)."""
    x = pd.to_numeric(pd.Series(x_vals), errors="coerce")
    y = pd.to_numeric(pd.Series(y_vals), errors="coerce")
    mask = x.notna() & y.notna()
    x, y = x[mask].astype(float), y[mask].astype(float)
    if len(x) < 3 or float(x.std()) == 0.0 or float(y.std()) == 0.0:
        return
    slope, intercept = np.polyfit(x, y, 1)
    r = float(np.corrcoef(x, y)[0, 1])
    xs = [float(x.min()), float(x.max())]
    c = PALETTE[theme]
    fig.add_trace(go.Scatter(
        x=xs, y=[slope * v + intercept for v in xs], mode="lines",
        line=dict(color=TREND_LINE, width=1.5, dash="dash"),
        hoverinfo="skip", showlegend=False, name="trend",
    ))
    fig.add_annotation(
        xref="paper", yref="paper", x=0.02, y=0.98, showarrow=False,
        text=f"r² = {r * r:.2f}", align="left",
        font=dict(size=12, color=c["text"]),
        bgcolor=c["hover_bg"], bordercolor=c["hover_border"], borderwidth=1,
        borderpad=4,
    )


def _short_name(name):
    parts = str(name).split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) >= 2 else name


def outlier_index(df: pd.DataFrame, stats, n: int = OUTLIER_LABELS):
    """Index labels of the `n` most extreme rows across the given stat columns.

    Extremity is the max absolute z-score across axes, so a point that is
    ordinary on one axis but far out on the other still gets labeled."""
    score = None
    for s in stats:
        if not s or s not in df.columns:
            continue
        v = pd.to_numeric(df[s], errors="coerce")
        sd = float(v.std() or 0)
        if sd == 0.0:
            continue
        z = ((v - v.mean()) / sd).abs()
        score = z if score is None else pd.concat([score, z], axis=1).max(axis=1)
    if score is None:
        return set()
    return set(score.nlargest(n).index)


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

def _eyebrow(view: str, label, is_3d: bool, traj: bool = False, era: bool = False):
    dot = html.Span("·", className="dot")
    mode = "TRAJECTORY" if traj else ("3D SCATTER" if is_3d else "2D SCATTER")
    out = [mode, dot, ("PLAYERS" if view == "player" else "TEAMS"), dot, str(label)]
    if era:
        out += [dot, "ERA-ADJUSTED"]
    return out


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

def team_frame(lo, hi, x_type, y_type, x_stat, y_stat, z_type=None, z_stat=None,
               league="All Teams", era=False):
    """One-row-per-team frame behind the team scatter (and the CSV export):
    columns Team, _x, _y and — when a usable Z axis exists — _z.

    Returns (df, is_3d, err); err is an error message when df is unusable.
    With era=True each axis is the team's within-season percentile (0–100),
    PA/IP-weight-averaged across the span, instead of the raw stat."""
    span = season_label(lo, hi)
    xkey = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    ykey = "team_batting_dir" if y_type == "Batting" else "team_pitching_dir"
    if era:
        x_df = load_stats_pct(xkey, lo, hi, [x_stat])
        y_df = load_stats_pct(ykey, lo, hi, [y_stat])
    else:
        x_df = load_stats(xkey, lo, hi)
        y_df = load_stats(ykey, lo, hi)

    if x_df.empty or y_df.empty:
        return None, False, f"No data for {span}"
    if "Team" not in x_df.columns or "Team" not in y_df.columns:
        return None, False, f"No team data for {span}"
    if x_stat not in x_df.columns or y_stat not in y_df.columns:
        return None, False, "Stat not available for this season"

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
        z_df = (load_stats_pct(zkey, lo, hi, [z_stat]) if era
                else load_stats(zkey, lo, hi))
        if (not z_df.empty and "Team" in z_df.columns
                and z_stat in z_df.columns):
            merged_z = pd.merge(
                merged, z_df[["Team", z_stat]].rename(columns={z_stat: "_z"}),
                on="Team",
            )
            # Need at least two real Z values for a meaningful third axis;
            # a single point collapses the scatter and the mean plane to a
            # line, so fall back to 2D instead.
            if merged_z["_z"].notna().sum() >= 2:
                merged = merged_z
                is_3d = True

    # League/division filter (team analogue of the player AL/NL/team filter).
    # Filter before means/ranks so a within-league view averages and ranks only
    # the teams shown. A span row blends seasons, so membership is judged at
    # the range's end year (the franchise's identity where the span lands).
    if league not in (None, "", "All Teams"):
        merged = merged[merged["Team"].map(
            lambda t: team_in_league(str(t), league, hi))]
        if merged.empty:
            return None, False, f"No {league} teams for {span}"

    if merged.empty:
        return None, False, f"No data for {span}"
    return merged, is_3d, None


def render_team(season, show_logos, x_type, y_type, x_stat, y_stat,
                show_v, show_h, use_color_rank, z_type, z_stat, theme="dark",
                league="All Teams", show_trend=False, era=False, traj=False):
    c = PALETTE[theme]
    if not x_stat or not y_stat:
        return _err("Select stats to view", theme)

    lo, hi = season_bounds(season)
    if lo is None:
        return _err("Select a season", theme)
    span = season_label(lo, hi)

    # Trajectory mode draws one point per season instead of one aggregate
    # point per team — only meaningful across a multi-season range.
    if traj and hi > lo:
        return _render_team_traj(lo, hi, x_type, y_type, x_stat, y_stat,
                                 theme, league, era)

    merged, is_3d, err = team_frame(lo, hi, x_type, y_type, x_stat, y_stat,
                                    z_type, z_stat, league, era)
    if err:
        return _err(err, theme)
    x_vals = merged["_x"]
    y_vals = merged["_y"]
    z_vals = merged["_z"] if is_3d else None
    teams  = merged["Team"]

    if x_vals.isna().all() or y_vals.isna().all():
        return _err(f"{x_stat} or {y_stat} has no data for {span}", theme)

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
        sfx = " (era pctl)" if era else ""
        layout = base_layout_3d(theme)
        layout["scene"]["xaxis"]["title"] = f"{x_type}: {x_stat}{sfx}"
        layout["scene"]["yaxis"]["title"] = f"{y_type}: {y_stat}{sfx}"
        layout["scene"]["zaxis"]["title"] = f"{z_type}: {z_stat}{sfx}"
        # Reverse axes for lower-is-better stats so up-right-forward = good
        x_dir = _axis_dir(x_stat, x_type == "Pitching")
        y_dir = _axis_dir(y_stat, y_type == "Pitching")
        z_dir = _axis_dir(z_stat, z_type == "Pitching")
        if x_dir:
            layout["scene"]["xaxis"]["autorange"] = x_dir
        if y_dir:
            layout["scene"]["yaxis"]["autorange"] = y_dir
        if z_dir:
            layout["scene"]["zaxis"]["autorange"] = z_dir
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
        # Box (0.07 × 0.11 of the data range) is tuned for a square logo. Size
        # each team's box to its logo's native aspect while holding the box
        # *area* constant, so banner-shaped logos (Braves, Reds) and tall ones
        # (Pirates, Angels) render with the same visible area as square ones
        # instead of getting letterboxed.
        for team, xv, yv in zip(teams, x_vals, y_vals):
            src = logo_b64(str(team))
            if src:
                # Anchored in data coordinates so logos track zoom/pan.
                k = (logo_aspect(str(team)) or 1.0) ** 0.5
                images.append(dict(
                    source=src, xref="x", yref="y",
                    x=float(xv), y=float(yv),
                    sizex=(x_hi - x_lo) * 0.07 * k,
                    sizey=(y_hi - y_lo) * 0.11 / k,
                    sizing="contain",
                    xanchor="center", yanchor="middle", layer="above",
                ))
        # Reverse a logo axis by flipping its padded range (rather than
        # autorange="reversed", which would discard the padding and clip the
        # edge logos).
        x_dir = _axis_dir(x_stat, x_type == "Pitching")
        y_dir = _axis_dir(y_stat, y_type == "Pitching")
        fig.update_layout(
            images=images,
            xaxis_range=[x_hi, x_lo] if x_dir else [x_lo, x_hi],
            yaxis_range=[y_hi, y_lo] if y_dir else [y_lo, y_hi])

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
        if show_trend:
            add_trendline(fig, x_vals, y_vals, theme)
        sfx = " (era pctl)" if era else ""
        fig.update_layout(**base_layout(theme),
                          xaxis_title=f"{x_type}: {x_stat}{sfx}",
                          yaxis_title=f"{y_type}: {y_stat}{sfx}", showlegend=False)
        # Reverse axes for lower-is-better stats so up-right = good.
        # (Logo mode already encodes direction in its flipped padded range.)
        if not (show_logos and not use_color_rank):
            x_dir = _axis_dir(x_stat, x_type == "Pitching")
            y_dir = _axis_dir(y_stat, y_type == "Pitching")
            if x_dir:
                fig.update_xaxes(autorange=x_dir)
            if y_dir:
                fig.update_yaxes(autorange=y_dir)

    eyebrow = _eyebrow("team", span, is_3d, era=era)
    title = _title(f"{y_stat}", f"{x_stat}", z_stat if is_3d else None)
    return fig, eyebrow, title


def _render_team_traj(lo, hi, x_type, y_type, x_stat, y_stat, theme, league, era):
    """Trajectory view: one point per season per team, joined by a path.

    Markers grow with the season so direction is readable without animation;
    only the final (latest) point carries the team label."""
    c = PALETTE[theme]
    span = season_label(lo, hi)
    xkey = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    ykey = "team_batting_dir" if y_type == "Batting" else "team_pitching_dir"

    frames = []
    for y in range(lo, hi + 1):
        x_df = load_stats(xkey, y)
        y_df = load_stats(ykey, y)
        if (x_df.empty or y_df.empty or "Team" not in x_df.columns
                or "Team" not in y_df.columns
                or x_stat not in x_df.columns or y_stat not in y_df.columns):
            continue
        if era:
            x_df = pct_within_season(x_df, [x_stat])
            y_df = pct_within_season(y_df, [y_stat])
        m = pd.merge(
            x_df[["Team", x_stat]].rename(columns={x_stat: "_x"}),
            y_df[["Team", y_stat]].rename(columns={y_stat: "_y"}),
            on="Team",
        )
        m["Season"] = y
        frames.append(m)
    if not frames:
        return _err(f"No data for {span}", theme)
    traj = pd.concat(frames, ignore_index=True)
    # Judge league membership per point's own season, so a franchise that
    # switched leagues mid-span (MIL '97→'98) tracks its actual league.
    if league not in (None, "", "All Teams"):
        traj = traj[[team_in_league(str(t), league, int(s))
                     for t, s in zip(traj["Team"], traj["Season"])]]
    traj = traj.dropna(subset=["_x", "_y"])
    if traj.empty:
        return _err(f"No data for {span}", theme)

    sfx = " (era pctl)" if era else ""
    fig = go.Figure()
    for team, grp in traj.groupby("Team"):
        grp = grp.sort_values("Season")
        color = TEAM_COLORS.get(str(team), c["accent"])
        n = len(grp)
        fig.add_trace(go.Scatter(
            x=grp["_x"], y=grp["_y"], mode="lines+markers+text",
            text=[""] * (n - 1) + [str(team)], textposition="top center",
            textfont=dict(size=11, color=c["text"], family="Geist, sans-serif"),
            customdata=grp["Season"],
            line=dict(color=color, width=1.5),
            marker=dict(size=np.linspace(5, 11, n), color=color, opacity=0.9,
                        line=dict(color=c["marker_line"], width=1)),
            hovertemplate=(f"<b>{team}</b> %{{customdata}}<br>"
                           f"{x_type} {x_stat}{sfx}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}{sfx}: %{{y:.2f}}<extra></extra>"),
        ))
    fig.update_layout(**base_layout(theme),
                      xaxis_title=f"{x_type}: {x_stat}{sfx}",
                      yaxis_title=f"{y_type}: {y_stat}{sfx}", showlegend=False)
    x_dir = _axis_dir(x_stat, x_type == "Pitching")
    y_dir = _axis_dir(y_stat, y_type == "Pitching")
    if x_dir:
        fig.update_xaxes(autorange=x_dir)
    if y_dir:
        fig.update_yaxes(autorange=y_dir)

    eyebrow = _eyebrow("team", span, False, traj=True, era=era)
    title = _title(f"{y_stat}", f"{x_stat}")
    return fig, eyebrow, title


# ── Player render ─────────────────────────────────────────────────────────────

def _add_war_rate(df, is_batter):
    """Derived 'WAR/650 PAs' column for batters (NaN where PA is 0, not inf)."""
    if is_batter and "WAR" in df.columns and "PA" in df.columns:
        df = df.copy()
        pa = df["PA"].where(df["PA"] > 0)
        df["WAR/650 PAs"] = (df["WAR"] / pa * 650).round(2)
    return df


def player_frame(lo, hi, player_type, min_pa, min_ip, team, pct_stats=None):
    """Filtered player frame for a season or range — the single source of truth
    shared by the scatter and the leaderboard so they never rank different rows.

    Adds the derived 'WAR/650 PAs' column for batters, applies the min PA/IP
    threshold (against the span's summed PA/IP when a range is selected), and
    applies the league/team filter. Returns an empty frame on no data.

    With pct_stats set (era-adjusted mode) the named stat columns come back as
    within-season percentiles (0–100) weight-averaged across the span; derived
    columns and the min PA/IP threshold then apply per season, before ranking,
    so each season's percentile pool matches the filters in play."""
    is_batter    = (player_type == "Batters")
    min_val, col = (min_pa, "PA") if is_batter else (min_ip, "IP")
    use_qualified = (min_val == "Qualified")
    q_key   = "qualified_batting_dir"  if is_batter else "qualified_pitching_dir"
    all_key = "all_batting_dir"        if is_batter else "all_pitching_dir"
    key = q_key if use_qualified else all_key

    if pct_stats:
        def _prep(season_df):
            season_df = _add_war_rate(season_df, is_batter)
            if not use_qualified and col in season_df.columns:
                try:
                    season_df = season_df[season_df[col] >= int(min_val)]
                except (TypeError, ValueError):
                    pass
            return season_df

        stats = list(dict.fromkeys(s for s in pct_stats if s))
        df = load_stats_pct(key, lo, hi, stats, group_key="IDfg",
                            season_prep=_prep)
        if df.empty:
            return df
    else:
        df = load_stats(key, lo, hi, group_key="IDfg")
        if df.empty:
            return df
        df = _add_war_rate(df, is_batter)
        if not use_qualified and col in df.columns:
            try:
                df = df[df[col] >= int(min_val)]
            except (TypeError, ValueError):
                pass

    # Traded players carry the MULTI_TEAM sentinel instead of a team code.
    # The data doesn't say which league(s) they played in, so the AL/NL
    # filters keep them (possibly-either-league) rather than silently
    # dropping a dozen qualified players a season. A specific team filter
    # still excludes them; MULTI_TEAM itself is offered as a dropdown choice.
    # League membership is year-aware (judged at the range's end year), so
    # 2005 Astros hitters are NL and 1980 Brewers are AL.
    if team in ("AL", "NL"):
        df = df[df["Team"].map(
            lambda t: str(t) == MULTI_TEAM or team_in_league(str(t), team, hi))]
    elif team not in (None, "All Teams"):
        df = df[df["Team"] == team]
    return df


def render_player(season, player_type, x_stat, y_stat, min_pa, min_ip, team,
                  use_color_rank, z_stat, show_v=True, show_h=True, theme="dark",
                  show_trend=False, era=False, traj=False, find="",
                  label_mode="all"):
    c = PALETTE[theme]
    if not x_stat or not y_stat:
        return _err("Select stats to view", theme)

    lo, hi = season_bounds(season)
    if lo is None:
        return _err("Select a season", theme)
    span = season_label(lo, hi)

    # Trajectory mode draws one point per season instead of one aggregate
    # point per player — only meaningful across a multi-season range.
    if traj and hi > lo:
        return _render_player_traj(lo, hi, player_type, x_stat, y_stat,
                                   min_pa, min_ip, team, theme, era, find)

    df = player_frame(lo, hi, player_type, min_pa, min_ip, team,
                      pct_stats=[x_stat, y_stat, z_stat] if era else None)
    if df.empty:
        return _err(f"No data for {span}", theme)
    if x_stat not in df.columns or y_stat not in df.columns:
        return _err("Stat not available", theme)
    if df[x_stat].isna().all() or df[y_stat].isna().all():
        return _err(f"{x_stat} or {y_stat} has no data for {span}", theme)

    df = df.copy()
    df["Label"]  = df["Name"].apply(_short_name)
    use_team_clr = team in (None, "All Teams", "AL", "NL")
    # Need at least two real Z values for a meaningful third axis; a single
    # point collapses the scatter and the mean plane to a line, so stay 2D.
    # (Mirrors the guard in render_team.)
    is_3d = bool(z_stat) and z_stat in df.columns and df[z_stat].notna().sum() >= 2

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

    # IDfg rides along as customdata[0] (Plotly Express prepends custom_data
    # ahead of hover_data and rewrites the hovertemplate indices to match) so a
    # point click can identify the exact player for the detail panel — robust to
    # duplicate names. Unused by the hovertemplate itself.
    cdata = ["IDfg"] if "IDfg" in df.columns else None

    tmpl = "plotly_dark" if theme == "dark" else "plotly_white"

    if is_3d:
        h_data[z_stat] = True
        fig = px.scatter_3d(df, x=x_stat, y=y_stat, z=z_stat, text="Label",
                            hover_name="Name", hover_data=h_data, custom_data=cdata,
                            color=color_col,
                            color_discrete_map=c_map, color_continuous_scale=c_scale,
                            range_color=c_range, template=tmpl)
        fig.update_traces(mode="markers+text", textposition="top center",
                          textfont=dict(size=9, color=c["text"]),
                          marker=dict(size=5, opacity=0.9,
                                      line=dict(color=c["marker_line"], width=0.5)))
        add_mean_planes_3d(fig, df[x_stat].dropna(), df[y_stat].dropna(),
                           df[z_stat].dropna(), show_x_plane=show_v, show_y_plane=show_h)
        sfx = " (era pctl)" if era else ""
        layout = base_layout_3d(theme)
        layout["scene"]["xaxis"]["title"] = x_stat + sfx
        layout["scene"]["yaxis"]["title"] = y_stat + sfx
        layout["scene"]["zaxis"]["title"] = z_stat + sfx
        # Reverse axes for lower-is-better stats
        is_pitch = (player_type == "Pitchers")
        for ax, stat in [("xaxis", x_stat), ("yaxis", y_stat), ("zaxis", z_stat)]:
            d = _axis_dir(stat, is_pitch)
            if d:
                layout["scene"][ax]["autorange"] = d
        fig.update_layout(**layout,
                          showlegend=(use_team_clr and not use_color_rank
                                      and team in ("AL", "NL")))
        if use_color_rank:
            fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank", theme))
    else:
        fig = px.scatter(df, x=x_stat, y=y_stat, text="Label", hover_name="Name",
                         hover_data=h_data, custom_data=cdata, color=color_col,
                         color_discrete_map=c_map,
                         color_continuous_scale=c_scale, range_color=c_range, template=tmpl)
        fig.update_traces(mode="markers+text", textposition="top center",
                          textfont=dict(size=10, color=c["text"], family="Geist, sans-serif"),
                          marker=dict(size=10, opacity=0.92,
                                      line=dict(color=c["marker_line"], width=0.8)))
        sfx = " (era pctl)" if era else ""
        fig.update_layout(**base_layout(theme), xaxis_title=x_stat + sfx,
                          yaxis_title=y_stat + sfx,
                          showlegend=(use_team_clr and not use_color_rank
                                      and team in ("AL", "NL")),
                          legend=dict(bgcolor=c["plot"], bordercolor=c["axis"],
                                      borderwidth=1, font=dict(color=c["text"], size=11),
                                      itemsizing="constant"))
        if use_color_rank:
            fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank", theme))
        # Reverse axes for lower-is-better stats so up-right = good
        is_pitch = (player_type == "Pitchers")
        x_dir = _axis_dir(x_stat, is_pitch)
        y_dir = _axis_dir(y_stat, is_pitch)
        if x_dir:
            fig.update_xaxes(autorange=x_dir)
        if y_dir:
            fig.update_yaxes(autorange=y_dir)

    # Search highlight + label modes. px splits points across traces (one per
    # team when colored by team), so per-point arrays are rebuilt per trace
    # from its customdata (IDfg rides in column 0).
    matched_ids = set()
    find = (find or "").strip()
    if find and "IDfg" in df.columns:
        m = df["Name"].astype(str).str.contains(find, case=False, regex=False)
        matched_ids = {int(i) for i in df.loc[m, "IDfg"].dropna()}
    label_ids = None                              # None → label every point
    if label_mode == "none":
        label_ids = set()
    elif label_mode == "outliers" and "IDfg" in df.columns:
        idx = outlier_index(df, [x_stat, y_stat, z_stat if is_3d else None])
        label_ids = {int(i) for i in df.loc[sorted(idx), "IDfg"].dropna()}
    if "IDfg" in df.columns and (matched_ids or label_ids is not None):
        base_size, hi_size = (5, 9) if is_3d else (10, 16)
        for tr in fig.data:
            cd = getattr(tr, "customdata", None)
            if cd is None or not len(cd):
                continue
            ids = [int(r[0]) for r in cd]
            # A matched player is always labeled, whatever the label mode.
            tr.text = [t if (i in matched_ids or label_ids is None
                             or i in label_ids) else ""
                       for t, i in zip(tr.text, ids)]
            if matched_ids:
                tr.marker.size = [hi_size if i in matched_ids else base_size
                                  for i in ids]
                if not is_3d:
                    # Scatter3d only takes a scalar opacity, so dimming the
                    # non-matches is 2D-only; 3D still gets size + label.
                    tr.marker.opacity = [1.0 if i in matched_ids
                                         else DIM_OPACITY for i in ids]
    if find and not matched_ids:
        fig.add_annotation(
            xref="paper", yref="paper", x=0.02, y=0.02, showarrow=False,
            text=f"no player matching “{find}”",
            font=dict(size=11, color=c["muted"]))

    # Mean reference lines — 2D only (3D already uses mean planes)
    if not is_3d:
        if show_trend:
            add_trendline(fig, df[x_stat], df[y_stat], theme)
        x_vals = df[x_stat].dropna()
        y_vals = df[y_stat].dropna()
        if show_h and not y_vals.empty:
            mean_y = float(y_vals.mean())
            fig.add_hline(y=mean_y, line_dash="dot", line_color=MEAN_LINE,
                          line_width=1.5,
                          annotation_text=f"avg {mean_y:.2f}",
                          annotation_position="top right",
                          annotation_font=dict(color=c["muted"], size=11))
        if show_v and not x_vals.empty:
            mean_x = float(x_vals.mean())
            fig.add_vline(x=mean_x, line_dash="dot", line_color=MEAN_LINE,
                          line_width=1.5,
                          annotation_text=f"avg {mean_x:.2f}",
                          annotation_position="top right",
                          annotation_font=dict(color=c["muted"], size=11))

    eyebrow = _eyebrow("player", span, is_3d, era=era)
    title = _title(f"{y_stat}", f"{x_stat}", z_stat if is_3d else None)
    return fig, eyebrow, title


def _render_player_traj(lo, hi, player_type, x_stat, y_stat, min_pa, min_ip,
                        team, theme, era, find):
    """Player trajectory view: one point per season per player, joined by a
    path (an aging curve through stat space).

    Hundreds of paths would be unreadable, so the entity set is bounded: a
    search query plots every matching player (capped), otherwise the span's
    top 10 by composite rank across the two axes — the same players the
    leaderboard shows."""
    c = PALETTE[theme]
    span = season_label(lo, hi)
    pool = player_frame(lo, hi, player_type, min_pa, min_ip, team)
    if pool.empty or "IDfg" not in pool.columns:
        return _err(f"No data for {span}", theme)
    if x_stat not in pool.columns or y_stat not in pool.columns:
        return _err("Stat not available", theme)

    find = (find or "").strip()
    if find:
        m = pool["Name"].astype(str).str.contains(find, case=False, regex=False)
        chosen = pool.loc[m]
        if chosen.empty:
            return _err(f"No player matching “{find}” for {span}", theme)
        # Cap at the color cycle; keep the biggest samples when over.
        wcol = "PA" if player_type == "Batters" else "IP"
        if len(chosen) > len(TRAJ_COLORS) and wcol in chosen.columns:
            chosen = chosen.nlargest(len(TRAJ_COLORS), wcol)
        chosen = chosen.head(len(TRAJ_COLORS))
    else:
        is_pitch = (player_type == "Pitchers")
        items = rank_items((pool[x_stat], x_stat, is_pitch),
                           (pool[y_stat], y_stat, is_pitch),
                           (None, None, is_pitch))
        comp = compute_composite_rank(*items)
        chosen = pool.loc[comp.sort_values(ascending=False).index[:10]]
    names = {int(r["IDfg"]): str(r["Name"])
             for _, r in chosen.iterrows() if pd.notna(r["IDfg"])}
    if not names:
        return _err(f"No data for {span}", theme)

    frames = []
    for y in range(lo, hi + 1):
        season_df = player_frame(y, y, player_type, min_pa, min_ip, team)
        if season_df.empty or "IDfg" not in season_df.columns:
            continue
        if x_stat not in season_df.columns or y_stat not in season_df.columns:
            continue
        if era:
            season_df = pct_within_season(season_df, [x_stat, y_stat])
        rows = season_df[season_df["IDfg"].isin(names)]
        if rows.empty:
            continue
        rows = rows[["IDfg", x_stat, y_stat]].copy()
        rows["Season"] = y
        frames.append(rows)
    if not frames:
        return _err(f"No data for {span}", theme)
    traj = pd.concat(frames, ignore_index=True).dropna(subset=[x_stat, y_stat])
    if traj.empty:
        return _err(f"No data for {span}", theme)

    sfx = " (era pctl)" if era else ""
    fig = go.Figure()
    for k, (idfg, grp) in enumerate(traj.groupby("IDfg")):
        grp = grp.sort_values("Season")
        name = names.get(int(idfg), "—")
        color = TRAJ_COLORS[k % len(TRAJ_COLORS)]
        n = len(grp)
        fig.add_trace(go.Scatter(
            x=grp[x_stat], y=grp[y_stat], mode="lines+markers+text",
            text=[""] * (n - 1) + [_short_name(name)],
            textposition="top center",
            textfont=dict(size=10, color=c["text"], family="Geist, sans-serif"),
            name=_short_name(name),
            # [IDfg, Season] per point: clicks open the right detail panel,
            # hover shows the season.
            customdata=grp.assign(_i=int(idfg))[["_i", "Season"]].values,
            line=dict(color=color, width=1.5),
            marker=dict(size=np.linspace(5, 11, n), color=color, opacity=0.9,
                        line=dict(color=c["marker_line"], width=0.8)),
            hovertemplate=(f"<b>{name}</b> %{{customdata[1]}}<br>"
                           f"{x_stat}{sfx}: %{{x:.2f}}<br>"
                           f"{y_stat}{sfx}: %{{y:.2f}}<extra></extra>"),
        ))
    fig.update_layout(**base_layout(theme), xaxis_title=x_stat + sfx,
                      yaxis_title=y_stat + sfx,
                      showlegend=True,
                      legend=dict(bgcolor=c["plot"], bordercolor=c["axis"],
                                  borderwidth=1,
                                  font=dict(color=c["text"], size=11),
                                  itemsizing="constant"))
    is_pitch = (player_type == "Pitchers")
    x_dir = _axis_dir(x_stat, is_pitch)
    y_dir = _axis_dir(y_stat, is_pitch)
    if x_dir:
        fig.update_xaxes(autorange=x_dir)
    if y_dir:
        fig.update_yaxes(autorange=y_dir)

    eyebrow = _eyebrow("player", span, False, traj=True, era=era)
    title = _title(f"{y_stat}", f"{x_stat}")
    return fig, eyebrow, title
