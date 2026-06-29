#!/usr/bin/env python3
"""Chart layer — theme-aware Plotly layouts and the team/player scatter renderers."""

from dash import html
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import pandas as pd

from data import (
    load_stats, stat_higher_better, season_bounds, season_label, team_in_league,
    TEAM_COLORS, NL_TEAMS, AL_TEAMS, PALETTE, RANK_COLORSCALE,
    logo_b64, logo_aspect,
)

RANK_COLORS = [c for _, c in RANK_COLORSCALE]   # flat list for plotly express
MEAN_LINE = "rgba(245,165,36,0.55)"             # amber reference line

# Dot-size range (pixels) when a third stat is mapped to marker size.
TEAM_SIZE_RANGE   = (8, 28)
PLAYER_SIZE_RANGE = (5, 22)


def _axis_dir(stat, is_pitching):
    """Return 'reversed' for lower-is-better stats, None otherwise.

    When reversed, Plotly flips the axis so up/right = good. Raw values
    are unchanged — only the visual direction flips.
    """
    return "reversed" if not stat_higher_better(stat, is_pitching) else None


def _size_array(values: pd.Series, stat: str, is_pitching: bool,
                size_range: tuple[float, float]) -> np.ndarray:
    """Map a stat series to marker sizes in *size_range*.

    For higher-is-better stats the largest value gets the biggest dot.
    For lower-is-better stats (e.g. ERA) the relationship is inverted so
    "better" always means bigger.
    """
    lo, hi = size_range
    v = values.astype(float)
    vmin, vmax = v.min(), v.max()
    span = vmax - vmin
    if span == 0:
        return np.full(len(v), (lo + hi) / 2)
    normed = (v - vmin) / span
    if not stat_higher_better(stat, is_pitching):
        normed = 1.0 - normed
    return lo + normed * (hi - lo)


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


# ── Topbar title builders ─────────────────────────────────────────────────────

def _eyebrow(view: str, label, has_size: bool):
    dot = html.Span("·", className="dot")
    return [("SIZE-MAPPED" if has_size else "SCATTER"), dot,
            ("PLAYERS" if view == "player" else "TEAMS"), dot, str(label)]


def _title(y_label: str, x_label: str, z_label: str | None = None):
    out = [html.Span(y_label, className="ax"),
           html.Span("vs", className="vs"),
           html.Span(x_label, className="ax")]
    if z_label:
        out += [html.Span("sized by", className="vs"),
                html.Span(z_label, className="ax")]
    return out


def _err(msg: str, theme: str):
    return empty_fig(msg, theme), ["—"], [html.Span(msg, className="ax")]


# ── Team render ───────────────────────────────────────────────────────────────

def render_team(season, show_logos, x_type, y_type, x_stat, y_stat,
                show_v, show_h, use_color_rank, z_type, z_stat, theme="dark",
                league="All Teams"):
    c = PALETTE[theme]
    if not x_stat or not y_stat:
        return _err("Select stats to view", theme)

    lo, hi = season_bounds(season)
    if lo is None:
        return _err("Select a season", theme)
    span = season_label(lo, hi)

    xkey = "team_batting_dir" if x_type == "Batting" else "team_pitching_dir"
    ykey = "team_batting_dir" if y_type == "Batting" else "team_pitching_dir"
    x_df = load_stats(xkey, lo, hi)
    y_df = load_stats(ykey, lo, hi)

    if x_df.empty or y_df.empty:
        return _err(f"No data for {span}", theme)
    if "Team" not in x_df.columns or "Team" not in y_df.columns:
        return _err(f"No team data for {span}", theme)
    if x_stat not in x_df.columns or y_stat not in y_df.columns:
        return _err("Stat not available for this season", theme)

    merged = pd.merge(
        x_df[["Team", x_stat]].rename(columns={x_stat: "_x"}),
        y_df[["Team", y_stat]].rename(columns={y_stat: "_y"}),
        on="Team",
    )

    has_size = False
    if z_stat:
        zkey = "team_batting_dir" if z_type == "Batting" else "team_pitching_dir"
        z_df = load_stats(zkey, lo, hi)
        if (not z_df.empty and "Team" in z_df.columns
                and z_stat in z_df.columns):
            merged_z = pd.merge(
                merged, z_df[["Team", z_stat]].rename(columns={z_stat: "_z"}),
                on="Team",
            )
            if merged_z["_z"].notna().sum() >= 2:
                merged = merged_z
                has_size = True

    if league not in (None, "", "All Teams"):
        merged = merged[merged["Team"].map(lambda t: team_in_league(str(t), league))]
        if merged.empty:
            return _err(f"No {league} teams for {span}", theme)

    if merged.empty:
        return _err(f"No data for {span}", theme)
    x_vals = merged["_x"]
    y_vals = merged["_y"]
    z_vals = merged["_z"] if has_size else None
    teams  = merged["Team"]

    if x_vals.isna().all() or y_vals.isna().all():
        return _err(f"{x_stat} or {y_stat} has no data for {span}", theme)

    rank_score = None
    if use_color_rank:
        items = rank_items((x_vals, x_stat, x_type == "Pitching"),
                           (y_vals, y_stat, y_type == "Pitching"),
                           (z_vals, z_stat, z_type == "Pitching"))
        rank_score = compute_composite_rank(*items).round(1)

    sizes = None
    if has_size:
        sizes = _size_array(z_vals, z_stat, z_type == "Pitching", TEAM_SIZE_RANGE)

    fig = go.Figure()

    if show_logos and not use_color_rank:
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="markers",
            marker=dict(size=18, opacity=0),
            text=teams,
            hovertemplate=(f"<b>%{{text}}</b><br>{x_type} {x_stat}: %{{x:.2f}}<br>"
                           f"{y_type} {y_stat}: %{{y:.2f}}"
                           + (f"<br>{z_type} {z_stat}: %{{customdata:.2f}}" if has_size else "")
                           + "<extra></extra>"),
            customdata=z_vals if has_size else None,
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
                k = (logo_aspect(str(team)) or 1.0) ** 0.5
                images.append(dict(
                    source=src, xref="x", yref="y",
                    x=float(xv), y=float(yv),
                    sizex=(x_hi - x_lo) * 0.07 * k,
                    sizey=(y_hi - y_lo) * 0.11 / k,
                    sizing="contain",
                    xanchor="center", yanchor="middle", layer="above",
                ))
        x_dir = _axis_dir(x_stat, x_type == "Pitching")
        y_dir = _axis_dir(y_stat, y_type == "Pitching")
        fig.update_layout(
            images=images,
            xaxis_range=[x_hi, x_lo] if x_dir else [x_lo, x_hi],
            yaxis_range=[y_hi, y_lo] if y_dir else [y_lo, y_hi])

    else:
        base_size = 14
        if use_color_rank:
            marker = dict(size=sizes if sizes is not None else base_size,
                          color=rank_score, colorscale=RANK_COLORSCALE,
                          cmin=0, cmax=100, showscale=True,
                          colorbar=colorbar_cfg("Composite<br>Rank", theme),
                          opacity=0.95, line=dict(color=c["marker_line"], width=1.5))
        else:
            marker = dict(size=sizes if sizes is not None else base_size,
                          color=[TEAM_COLORS.get(str(t), c["accent"]) for t in teams],
                          opacity=0.95, line=dict(color=c["marker_line"], width=1.5))
        cdata = None
        hover_parts = (f"<b>%{{text}}</b><br>{x_type} {x_stat}: %{{x:.2f}}<br>"
                        f"{y_type} {y_stat}: %{{y:.2f}}")
        if has_size and use_color_rank:
            cdata = list(zip(z_vals, rank_score))
            hover_parts += (f"<br>{z_type} {z_stat}: %{{customdata[0]:.2f}}"
                            "<br>Composite rank: %{customdata[1]:.1f}")
        elif has_size:
            cdata = z_vals
            hover_parts += f"<br>{z_type} {z_stat}: %{{customdata:.2f}}"
        elif use_color_rank:
            cdata = rank_score
            hover_parts += "<br>Composite rank: %{customdata:.1f}"
        hover_parts += "<extra></extra>"
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="markers+text",
            text=teams, textposition="top center",
            textfont=dict(size=11, color=c["text"], family="Geist, sans-serif"),
            marker=marker, customdata=cdata,
            hovertemplate=hover_parts,
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

    fig.update_layout(**base_layout(theme),
                      xaxis_title=f"{x_type}: {x_stat}",
                      yaxis_title=f"{y_type}: {y_stat}", showlegend=False)
    if not (show_logos and not use_color_rank):
        x_dir = _axis_dir(x_stat, x_type == "Pitching")
        y_dir = _axis_dir(y_stat, y_type == "Pitching")
        if x_dir:
            fig.update_xaxes(autorange=x_dir)
        if y_dir:
            fig.update_yaxes(autorange=y_dir)

    eyebrow = _eyebrow("team", span, has_size)
    title = _title(f"{y_stat}", f"{x_stat}", z_stat if has_size else None)
    return fig, eyebrow, title


# ── Player render ─────────────────────────────────────────────────────────────

def player_frame(lo, hi, player_type, min_pa, min_ip, team):
    """Filtered player frame for a season or range — the single source of truth
    shared by the scatter and the leaderboard so they never rank different rows.

    Adds the derived 'WAR/650 PAs' column for batters, applies the min PA/IP
    threshold (against the span's summed PA/IP when a range is selected), and
    applies the league/team filter. Returns an empty frame on no data."""
    is_batter    = (player_type == "Batters")
    min_val, col = (min_pa, "PA") if is_batter else (min_ip, "IP")
    use_qualified = (min_val == "Qualified")
    q_key   = "qualified_batting_dir"  if is_batter else "qualified_pitching_dir"
    all_key = "all_batting_dir"        if is_batter else "all_pitching_dir"

    df = load_stats(q_key if use_qualified else all_key, lo, hi, group_key="IDfg")
    if df.empty:
        return df
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
    return df


def render_player(season, player_type, x_stat, y_stat, min_pa, min_ip, team,
                  use_color_rank, z_stat, show_v=True, show_h=True, theme="dark"):
    c = PALETTE[theme]
    if not x_stat or not y_stat:
        return _err("Select stats to view", theme)

    lo, hi = season_bounds(season)
    if lo is None:
        return _err("Select a season", theme)
    span = season_label(lo, hi)

    df = player_frame(lo, hi, player_type, min_pa, min_ip, team)
    if df.empty:
        return _err(f"No data for {span}", theme)
    if x_stat not in df.columns or y_stat not in df.columns:
        return _err("Stat not available", theme)
    if df[x_stat].isna().all() or df[y_stat].isna().all():
        return _err(f"{x_stat} or {y_stat} has no data for {span}", theme)

    def fmt(name):
        parts = str(name).split()
        return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) >= 2 else name

    df["Label"]  = df["Name"].apply(fmt)
    use_team_clr = team in (None, "All Teams", "AL", "NL")
    is_pitch = (player_type == "Pitchers")
    has_size = bool(z_stat) and z_stat in df.columns and df[z_stat].notna().sum() >= 2

    if use_color_rank:
        items = rank_items((df[x_stat], x_stat, is_pitch),
                           (df[y_stat], y_stat, is_pitch),
                           (df[z_stat] if has_size else None, z_stat, is_pitch))
        df["Composite Rank"] = compute_composite_rank(*items).round(1).values

    if use_color_rank:
        color_col, c_map, c_scale, c_range = "Composite Rank", None, RANK_COLORS, [0, 100]
    elif use_team_clr:
        color_col, c_map, c_scale, c_range = "Team", TEAM_COLORS, None, None
    else:
        color_col, c_map, c_scale, c_range = None, None, None, None

    h_data = {x_stat: True, y_stat: True, "Team": True, "Label": False}
    if has_size:
        h_data[z_stat] = True
        h_data["_dot_size"] = False
    if use_color_rank:
        h_data["Composite Rank"] = True

    cdata = ["IDfg"] if "IDfg" in df.columns else None

    tmpl = "plotly_dark" if theme == "dark" else "plotly_white"

    sizes = None
    if has_size:
        sizes = _size_array(df[z_stat], z_stat, is_pitch, PLAYER_SIZE_RANGE)
        df["_dot_size"] = sizes

    fig = px.scatter(df, x=x_stat, y=y_stat, text="Label", hover_name="Name",
                     hover_data=h_data, custom_data=cdata, color=color_col,
                     color_discrete_map=c_map,
                     color_continuous_scale=c_scale, range_color=c_range,
                     size="_dot_size" if has_size else None,
                     size_max=int(PLAYER_SIZE_RANGE[1]) if has_size else None,
                     template=tmpl)
    base_marker_size = 10 if not has_size else None
    fig.update_traces(mode="markers+text", textposition="top center",
                      textfont=dict(size=10, color=c["text"], family="Geist, sans-serif"),
                      marker=dict(opacity=0.92,
                                  line=dict(color=c["marker_line"], width=0.8),
                                  **({"size": base_marker_size} if base_marker_size else {})))
    fig.update_layout(**base_layout(theme), xaxis_title=x_stat, yaxis_title=y_stat,
                      showlegend=(use_team_clr and not use_color_rank
                                  and team in ("AL", "NL")),
                      legend=dict(bgcolor=c["plot"], bordercolor=c["axis"],
                                  borderwidth=1, font=dict(color=c["text"], size=11),
                                  itemsizing="constant"))
    if use_color_rank:
        fig.update_layout(coloraxis_colorbar=colorbar_cfg("Composite<br>Rank", theme))
    x_dir = _axis_dir(x_stat, is_pitch)
    y_dir = _axis_dir(y_stat, is_pitch)
    if x_dir:
        fig.update_xaxes(autorange=x_dir)
    if y_dir:
        fig.update_yaxes(autorange=y_dir)

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

    eyebrow = _eyebrow("player", span, has_size)
    title = _title(f"{y_stat}", f"{x_stat}", z_stat if has_size else None)
    return fig, eyebrow, title
