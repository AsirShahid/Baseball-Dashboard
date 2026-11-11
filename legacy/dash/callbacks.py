#!/usr/bin/env python3
"""Callback layer — every Dash callback, registered via register_callbacks(app)."""

import re
import time
from urllib.parse import urlencode

import pandas as pd
from dash import Input, Output, State, MATCH, ALL, no_update, ctx, dcc, html

from data import (
    config, current_year, season_list, span_totals, span_qualified_min,
    threshold_cohort, team_games, threshold_options, snap_threshold,
    QUALIFIED_RATE,
    load_csv, load_stats, load_stats_pct, season_bounds, season_label,
    season_tag, fmt_stat, round_stats,
    process_columns,
    seasons_with_data, opts, stat_higher_better, team_in_league, decade_marks,
    team_display, team_name, team_last_seasons, MULTI_TEAM, TEAM_COLORS,
    TEAM_FULL_NAME, TEAM_PRESETS, BATTER_PRESETS, PITCHER_PRESETS, ramp_color,
)
from charts import (
    render_team, render_player, player_frame, team_frame, playing_time_rule,
    compute_composite_rank, rank_items,
)
from components import (
    leaderboard_cards, detail_body, player_detail_body, player_preset_chips,
    detail_loading, detail_message,
)

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

# Curated stat tiles for the player detail panel (direction is derived from
# stat_higher_better, so no need to hand-annotate higher/lower here). Stats
# missing for a season/player are skipped at render time.
PLAYER_DETAIL_GROUPS = {
    "Batters":  [("Value & power", ["WAR", "wRC+", "OBP", "SLG", "ISO"]),
                 ("Plate skills",  ["BB%", "K%", "Barrel%", "HardHit%"])],
    "Pitchers": [("Run prevention", ["WAR", "ERA", "FIP", "WHIP"]),
                 ("Stuff & control", ["K/9", "BB/9", "K%", "HR/9"])],
}
# Stats for the player trajectory sparklines (read from the same season files
# as the chart's player pool: qualified or all-players).
PLAYER_SPARKS = {
    "Batters":  ["WAR", "wRC+", "OPS"],
    "Pitchers": ["WAR", "ERA", "K/9"],
}
SPARK_MAX_SEASONS = 20      # a career-range trajectory shows at most this many


# ── helpers ───────────────────────────────────────────────────────────────────

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
    df = load_csv(f"{config[dir_key]}/{year}.csv", fetch=fetch, copy=False)
    if df.empty or stat not in df.columns or "Team" not in df.columns:
        return None, df
    row = df[df["Team"] == team]
    if row.empty:
        return None, df
    return row.iloc[0][stat], df


def _team_span_value(dir_key, lo, hi, team, stat):
    """Like _team_value but cumulative over an inclusive season range, so the
    detail panel's percentiles match the (aggregated) chart and leaderboard."""
    df = load_stats(dir_key, lo, hi)
    if df.empty or stat not in df.columns or "Team" not in df.columns:
        return None, df
    row = df[df["Team"] == team]
    if row.empty:
        return None, df
    return row.iloc[0][stat], df


def _spark(stat, dir_key, team, season, years_in=None):
    """One stat's per-season values for a team: the 5 seasons up to `season`,
    or exactly `years_in` when given (a range's own seasons)."""
    years, values = [], []
    for y in (years_in if years_in is not None else range(season - 4, season + 1)):
        # fetch=False: don't fire blocking network requests for missing
        # neighbouring seasons just to draw a sparkline.
        v, _ = _team_value(dir_key, y, team, stat, fetch=False)
        if v is not None and v == v:
            years.append(y)
            values.append(float(v))
    return {"label": stat, "values": values, "years": years,
            "last": fmt_stat(stat, values[-1]) if values else "—"}


def _player_dir(ptype, mpa, mip, lo=None, hi=None) -> str:
    """Season-file directory behind the player pool for these filters (the
    same choice player_frame makes: the qualified files only for "Qualified"
    on a single season; a range uses every player's full totals)."""
    return playing_time_rule(lo, hi, ptype or "Batters", mpa, mip)[0]


def _threshold_hint(season, ptype, mpa, mip, tf, split):
    """FanGraphs-style note under the Min playing time control: what the cut
    means for this span and how many players it leaves."""
    lo, hi = season_bounds(season)
    if lo is None:
        return ""
    ptype = ptype or "Batters"
    per_season = _split_on(split, lo, hi)
    key, col, thr, span_rule = playing_time_rule(lo, hi, ptype, mpa, mip,
                                                 split=per_season)
    val = mpa if ptype == "Batters" else mip
    span = season_label(lo, hi)
    unit = "PA" if col == "PA" else "IP"
    rate = "3.1 PA" if col == "PA" else "1 IP"
    count, noun = None, "players"
    if val == "Qualified" and not span_rule:
        if hi > lo:
            text = [f"Qualified in each season: {rate} per team game."]
            noun = "player-seasons"
        else:
            text = [f"Qualified: {rate} per team game "
                    f"({fmt_stat(col, QUALIFIED_RATE[col] * team_games(lo))} {unit} in {lo})."]
        if tf in (None, "All Teams"):
            count = int(sum(span_totals(key, y, y).shape[0] for y in range(lo, hi + 1)))
    elif val == "Qualified":
        cut = f"{thr:,.0f}"
        text = [f"Qualified over {span}: ", html.B(f"{cut}+ {unit}"),
                " total (FanGraphs' multi-season rule)."]
        if tf in (None, "All Teams"):
            count = len(threshold_cohort(key, lo, hi, thr) or [])
    else:
        n = f"{int(thr):,}"
        if hi <= lo:
            text = [html.B(f"{n}+ {unit}"), f" in {lo}."]
            if tf in (None, "All Teams"):
                tot = span_totals(key, lo, lo)
                count = int((tot["total"] >= thr).sum()) if thr else len(tot)
        elif per_season and not span_rule:
            text = [html.B(f"{n}+ {unit}"), " in each season shown."]
            noun = "player-seasons"
        else:
            text = [html.B(f"{n}+ {unit}"), f" total over {span}."]
            if per_season:
                text.append(" Every season of those players is shown.")
            elif tf in (None, "All Teams"):
                tot = span_totals(key, lo, hi)
                count = int((tot["total"] >= thr).sum()) if thr else len(tot)
    if count is not None:
        text.append(f" {count:,} {noun}.")
    return text


def _player_season_rows(idfg, dir_key, years) -> pd.DataFrame:
    """This player's own rows from each season file in `years`, tagged with
    Season. Read-only lookups into the CSV cache (copy=False) and fetch=False,
    so the panel never copies or downloads whole seasons to find one player."""
    rows = []
    for y in years:
        df = load_csv(f"{config[dir_key]}/{y}.csv", fetch=False, copy=False)
        if df.empty or "IDfg" not in df.columns:
            continue
        r = df[df["IDfg"] == idfg]
        if not r.empty:
            rows.append(r.assign(Season=y))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _player_facts(rows, prow, lo, hi, is_pitch, qualified=False):
    """Header facts for the player panel from his own season rows in the
    range: (eyebrow, facts line, primary team code). With the Qualified
    filter the rows (and the range totals) are qualified seasons only, and
    the facts say so — Ruth shows "14 qualified seasons", not a short career."""
    wcol = "IP" if is_pitch else "PA"
    team = str(prow.get("Team", "")).strip()
    eyebrow, facts = [], []
    if not rows.empty:
        w = pd.to_numeric(rows.get(wcol), errors="coerce").fillna(0) \
            if wcol in rows.columns else pd.Series(1.0, index=rows.index)
        # Teams by playing time; FanGraphs' "- - -" rows are traded-season
        # totals, not a team.
        tdf = pd.DataFrame({"t": rows["Team"].astype(str).str.strip(), "w": w})
        tdf = tdf[(tdf["t"] != MULTI_TEAM) & (tdf["t"] != "")]
        tw = tdf.groupby("t")["w"].sum().sort_values(ascending=False)
        if len(tw):
            team = tw.index[0]
            # The club's name in his last season there (Indians, not Guardians).
            ts = rows.loc[rows["Team"].astype(str).str.strip() == team, "Season"]
            label = team_display(team, full=True,
                                 season=int(ts.max()) if len(ts) else hi)
            if len(tw) > 1:
                label += f" +{len(tw) - 1} more"
            eyebrow.append(label)
        elif team == MULTI_TEAM:
            eyebrow.append("Multiple teams")
        if "position" in rows.columns:
            pos = (pd.DataFrame({"p": rows["position"], "w": w}).dropna()
                   .groupby("p")["w"].sum())
            if len(pos):
                eyebrow.append(str(pos.idxmax()))
        hand_col, hand_lbl = ("Throws", "Throws") if is_pitch else ("Bats", "Bats")
        if hand_col in rows.columns:
            h = rows[hand_col].dropna().astype(str).str.strip()
            h = h[h != ""]
            if len(h):
                eyebrow.append(f"{hand_lbl} {h.mode().iloc[0]}")
        yrs = sorted(int(y) for y in rows["Season"].unique())
        facts.append(season_label(yrs[0], yrs[-1]))
        q = "qualified " if qualified else ""
        if len(yrs) > 1:
            facts.append(f"{len(yrs)} {q}seasons")
        elif qualified and hi > lo:
            facts.append("1 qualified season")
        if "Age" in rows.columns:
            ages = pd.to_numeric(rows["Age"], errors="coerce").dropna()
            if len(ages):
                a, b = int(ages.min()), int(ages.max())
                facts.append(f"Age {a}" if a == b else f"Age {a}–{b}")
    else:
        eyebrow.append(team_display(team, full=True))
    for col in ((["IP", "G", "GS"] if is_pitch else ["PA", "G"])):
        v = prow.get(col)
        if v is None or pd.isna(v) or (col == "GS" and float(v) == 0):
            continue                      # relievers: no "0 GS"
        facts.append(f"{fmt_stat(col, v)} {col}")
    return " · ".join(eyebrow), " · ".join(facts), team


def _player_detail(idfg, lo, hi, ptype, mpa, mip, tf):
    """Build the player detail panel: percentile tiles vs the current player
    pool (same filters as the chart), a composite badge, the player's own
    seasons/teams/position in the header, and per-season sparklines."""
    dir_key = _player_dir(ptype, mpa, mip, lo, hi)
    pool = player_frame(lo, hi, ptype, mpa, mip, tf)
    prow = pool[pool["IDfg"] == idfg] if "IDfg" in pool.columns else pool.iloc[0:0]
    if prow.empty:
        # The clicked player can sit outside the filtered pool (e.g. an active
        # team filter, or a min-PA threshold). Fall back to the unfiltered
        # all-teams pool so the panel still renders the player in context.
        dir_key = _player_dir(ptype, "Qualified", "Qualified", lo, hi)
        pool = player_frame(lo, hi, ptype, "Qualified", "Qualified", "All Teams")
        prow = pool[pool["IDfg"] == idfg] if "IDfg" in pool.columns else pool.iloc[0:0]
    if prow.empty:
        # Typically: the panel stayed open while the slider moved to seasons
        # this player never played (the panel re-renders on slider changes).
        return detail_message(f"No {'qualified ' if dir_key.startswith('qualified') else ''}"
                              f"seasons in {season_label(lo, hi)}",
                              title="Player")
    prow = prow.iloc[0]
    name = str(prow.get("Name", "—"))
    is_pitch = (ptype == "Pitchers")

    # Only scan the seasons this player actually appears in (the roll-up
    # carries _first/_last), not all 156 when the slider spans 1871–2026.
    first = int(prow["_first"]) if pd.notna(prow.get("_first")) else lo
    last = int(prow["_last"]) if pd.notna(prow.get("_last")) else hi
    rows = _player_season_rows(idfg, dir_key, range(max(lo, first), min(hi, last) + 1))
    eyebrow, facts, team = _player_facts(rows, prow, lo, hi, is_pitch,
                                         qualified=dir_key.startswith("qualified"))

    groups, all_pcts = [], []
    for gname, stats in PLAYER_DETAIL_GROUPS.get(ptype, []):
        tiles = []
        for stat in stats:
            if stat not in pool.columns:
                continue
            v = prow.get(stat)
            if v is None or (isinstance(v, float) and v != v):
                continue
            hib = stat_higher_better(stat, is_pitch)
            pct = _pct(pool[stat], v, hib)
            all_pcts.append(pct)
            tiles.append({"label": stat, "value": fmt_stat(stat, v), "pct": pct,
                          "ramp": ramp_color(pct / 100)})
        if tiles:
            groups.append({"name": gname, "tiles": tiles})
    composite = int(round(sum(all_pcts) / len(all_pcts))) if all_pcts else 50

    # Trajectory: across a range, the player's own seasons in it (most recent
    # SPARK_MAX_SEASONS); for a single season, the 5 seasons leading up to it.
    if hi > lo:
        spark_rows = rows
        if not rows.empty:
            keep = sorted(rows["Season"].unique())[-SPARK_MAX_SEASONS:]
            spark_rows = rows[rows["Season"].isin(keep)]
    else:
        spark_rows = _player_season_rows(idfg, dir_key, range(hi - 4, hi + 1))
    sparks = []
    for stat in PLAYER_SPARKS.get(ptype, []):
        years, values = [], []
        if not spark_rows.empty and stat in spark_rows.columns:
            for y, v in spark_rows.sort_values("Season")[["Season", stat]].values:
                if pd.notna(v):
                    years.append(int(y))
                    values.append(float(v))
        sparks.append({"label": stat, "values": values, "years": years,
                       "last": fmt_stat(stat, values[-1]) if values else "—"})
    yrs = sorted({y for sp in sparks for y in sp["years"]})
    if hi > lo:
        spark_title = (f"TRAJECTORY · {season_label(yrs[0], yrs[-1])}"
                       if len(yrs) > 1 else "TRAJECTORY")
    else:
        spark_title = "5-YEAR TRAJECTORY"
    foot = ("Percentiles vs. the players matching your filters, "
            f"{season_label(lo, hi)}"
            + (" (range totals)." if hi > lo else "."))
    return player_detail_body(name, team, eyebrow, facts, composite, sparks,
                              groups, spark_title=spark_title, foot=foot)


def _split_on(split, lo, hi) -> bool:
    """Per-season range view is in effect: the toggle is on *and* the slider
    spans more than one season (a single season is the same either way)."""
    return split == "season" and lo is not None and hi is not None and hi > lo


def _leaderboard_rows(season, xt, yt, xs, ys, zt, zs, league="All Teams",
                      era=False, split=None):
    lo, hi = season_bounds(season)
    if lo is None:
        return [], 0
    per_season = _split_on(split, lo, hi)

    def _load(typ, stat):
        if not stat:
            return None
        key = "team_batting_dir" if typ == "Batting" else "team_pitching_dir"
        # Era-adjusted mode ranks the same within-season percentiles the chart
        # plots, so the board and the chart agree over multi-season spans.
        df = (load_stats_pct(key, lo, hi, [stat], split=per_season) if era
              else load_stats(key, lo, hi, split=per_season))
        if df.empty or stat not in df.columns or "Team" not in df.columns:
            return None
        # Index by team (by "TEAM|season" per-season) so axes loaded from
        # different CSVs (batting vs pitching) align by entity, not by row
        # position.
        idx = df["Team"].astype(str)
        if per_season:
            idx = idx + "|" + df["Season"].astype(int).astype(str)
        s = pd.Series(df[stat].values, index=idx)
        # Restrict to the league/division so the board ranks within the same
        # set of teams the chart shows (year-aware: judged at the range end
        # like team_frame, or in the row's own season per-season).
        if league not in (None, "", "All Teams"):
            if per_season:
                s = s[[team_in_league(k.split("|")[0], league,
                                      int(k.split("|")[1])) for k in s.index]]
            else:
                s = s[[team_in_league(t, league, hi) for t in s.index]]
        # An all-NaN axis carries no signal; drop it so it neither produces a
        # meaningless all-50 ranking (x/y) nor inflates the axis count (z) —
        # mirroring render_team, which won't plot or count an empty axis.
        if s.empty or s.isna().all():
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
    comp = compute_composite_rank(*items).dropna()
    rows = sorted(
        ({"team": str(t), "score": float(s)} for t, s in comp.items()),
        key=lambda r: r["score"], reverse=True,
    )
    out = []
    # Names as of the row's season, or the club's last season in the range.
    last = team_last_seasons(lo, hi) if hi > lo else {}
    for i, r in enumerate(rows[:10]):
        pct = int(round(r["score"]))
        code, _, yr = r["team"].partition("|")
        name = team_name(code, int(yr) if yr else last.get(code, hi))
        out.append({"rank": i + 1, "team": code, "ref": r["team"],
                    "name": f"{yr} {name}" if yr else name,
                    "pct": pct, "color": TEAM_COLORS.get(code, "#7d8590"),
                    "ramp": ramp_color(pct / 100)})
    return out, len(items)


def _player_leaderboard_rows(season, ptype, pxs, pys, pzs, min_pa, min_ip,
                             team, era=False, split=None):
    """Top-10 players by composite rank across the selected axes — the player
    analogue of _leaderboard_rows. Ranks the exact frame the scatter plots
    (player_frame, era percentiles included), so a multi-season range yields
    a cumulative leaderboard that agrees with the chart."""
    lo, hi = season_bounds(season)
    if lo is None or not pxs or not pys:
        return [], 0
    per_season = _split_on(split, lo, hi)
    df = player_frame(lo, hi, ptype, min_pa, min_ip, team,
                      pct_stats=[pxs, pys, pzs] if era else None,
                      split=per_season)
    if df.empty or pxs not in df.columns or pys not in df.columns:
        return [], 0
    if df[pxs].isna().all() or df[pys].isna().all():
        return [], 0

    is_pitch = (ptype == "Pitchers")
    zser = df[pzs] if (pzs and pzs in df.columns and df[pzs].notna().sum() >= 2) else None
    items = rank_items((df[pxs], pxs, is_pitch),
                       (df[pys], pys, is_pitch),
                       (zser, pzs, is_pitch))
    comp = compute_composite_rank(*items).round(1).dropna()

    order = comp.sort_values(ascending=False).index[:10]
    out = []
    for i, idx in enumerate(order):
        row = df.loc[idx]
        tm = str(row.get("Team", "")).strip()
        pct = int(round(float(comp.loc[idx])))
        ref = str(int(row["IDfg"])) if "IDfg" in df.columns else str(row.get("Name", ""))
        name = str(row.get("Name", "—"))
        if per_season:
            # "IDfg|season" so a click opens that player-season's panel.
            ref = f"{ref}|{int(row['Season'])}"
            name = f"{int(row['Season'])} {name}"
        out.append({"rank": i + 1, "team": team_display(tm), "ref": ref,
                    "name": name,
                    "pct": pct, "color": TEAM_COLORS.get(tm, "#7d8590"),
                    "ramp": ramp_color(pct / 100)})
    return out, len(items)


def _fname_part(s) -> str:
    """Make a stat/span safe for a filename (K/9 → K-9, 2019–2024 → 2019-2024)."""
    return (str(s).replace("/", "-").replace("–", "-").replace("%", "pct")
            .replace("+", "plus").replace(" ", "_"))


def _export_frame(view, season, xt, yt, xs, ys, zt, zs, league, era,
                  ptype, pxs, pys, pzs, mpa, mip, tf, find, p_era, split=None):
    """(DataFrame, filename) of exactly what the current chart plots — same
    frame builders, same filters — plus the composite rank column. Returns
    (None, None) when there is nothing to export. Per-season mode exports one
    row per team/player-season with a Season column."""
    lo, hi = season_bounds(season)
    if lo is None:
        return None, None
    span = season_label(lo, hi)
    per_season = _split_on(split, lo, hi)
    ps_sfx = "_per-season" if per_season else ""

    if view == "player":
        if not pxs or not pys:
            return None, None
        stats = [s for s in (pxs, pys, pzs) if s]
        df = player_frame(lo, hi, ptype, mpa, mip, tf,
                          pct_stats=stats if p_era else None, split=per_season)
        if df.empty or pxs not in df.columns or pys not in df.columns:
            return None, None
        is_pitch = (ptype == "Pitchers")
        id_cols = ("Name", "Team", "IDfg") + (("Season",) if per_season else ())
        keep = [c for c in id_cols + ("PA", "IP") if c in df.columns]
        out = df[keep + [s for s in stats if s in df.columns]].copy()
        # Display precision (WAR 1 dp, wRC+ whole…) instead of raw CSV floats.
        out = round_stats(out, [c for c in ("PA", "IP") if c in out.columns])
        out = round_stats(out, [s for s in stats if s in out.columns],
                          era=p_era)
        items = rank_items(
            (df[pxs], pxs, is_pitch), (df[pys], pys, is_pitch),
            (df[pzs] if (pzs and pzs in df.columns) else None, pzs, is_pitch))
        out["Composite Rank"] = compute_composite_rank(*items).round(1).values
        # The chart plots everyone even mid-search (non-matches dim, they
        # don't vanish); the export mirrors that and flags the matches.
        find = (find or "").strip()
        if find:
            out["Matched"] = df["Name"].astype(str).str.contains(
                find, case=False, regex=False).values
        out = out.sort_values("Composite Rank", ascending=False)
        fname = (f"players_{_fname_part(span)}{ps_sfx}_{_fname_part(pys)}"
                 f"_vs_{_fname_part(pxs)}{'_era-pctl' if p_era else ''}.csv")
        return out, fname

    if not xs or not ys:
        return None, None
    merged, is_3d, err = team_frame(lo, hi, xt, yt, xs, ys, zt, zs,
                                    league or "All Teams", era,
                                    split=per_season)
    if err or merged is None:
        return None, None
    items = rank_items(
        (merged["_x"], xs, xt == "Pitching"), (merged["_y"], ys, yt == "Pitching"),
        (merged["_z"] if is_3d else None, zs, zt == "Pitching"))
    out = merged.copy()
    # Display precision per stat before the generic _x/_y names are replaced.
    for col, st in (("_x", xs), ("_y", ys), ("_z", zs)):
        if col in out.columns:
            out[col] = round_stats(out[[col]].rename(columns={col: st}),
                                   [st], era=era)[st].values
    out = out.rename(columns={
        "_x": f"{xs} ({xt})", "_y": f"{ys} ({yt})",
        **({"_z": f"{zs} ({zt})"} if is_3d else {}),
    })
    out["Composite Rank"] = compute_composite_rank(*items).round(1).values
    out = out.sort_values("Composite Rank", ascending=False)
    fname = (f"teams_{_fname_part(span)}{ps_sfx}_{_fname_part(ys)}"
             f"_vs_{_fname_part(xs)}{'_era-pctl' if era else ''}.csv")
    return out, fname


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

    def _typed_options(search, value):
        """Ladder + current value + a typed number (e.g. 2750), so any
        threshold can be picked, not only the FanGraphs rungs."""
        cur = value if isinstance(value, int) else None
        opts_ = threshold_options(cur)
        digits = re.sub(r"[,\s]", "", str(search or ""))
        if digits.isdigit():
            n = snap_threshold(digits)
            if isinstance(n, int) and all(o["value"] != n for o in opts_):
                opts_ = [opts_[0]] + sorted(opts_[1:] + [{"label": str(n), "value": n}],
                                            key=lambda o: o["value"])
        return opts_

    @app.callback(
        Output("min-pa", "options"),
        Input("min-pa", "search_value"), Input("min-pa", "value"),
    )
    def min_pa_options(search, value):
        return _typed_options(search, value)

    @app.callback(
        Output("min-ip", "options"),
        Input("min-ip", "search_value"), Input("min-ip", "value"),
    )
    def min_ip_options(search, value):
        return _typed_options(search, value)

    @app.callback(
        Output("min-pa-hint", "children"), Output("min-ip-hint", "children"),
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"),
        Input({"kind": "seg-store", "group": "split"}, "data"),
    )
    def playing_time_hint(season, ptype, mpa, mip, tf, split):
        hint = _threshold_hint(season, ptype, mpa, mip, tf, split)
        return (hint, no_update) if (ptype or "Batters") == "Batters" else (no_update, hint)

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

    # Trajectory mode draws season paths: mean lines, trend fit, rank
    # coloring, logos and the Z axis don't apply there. Disable (dim) those
    # controls while it's active so they don't read as broken no-ops.
    @app.callback(
        Output("tg-vmean", "disabled"), Output("tg-hmean", "disabled"),
        Output("tg-trend", "disabled"), Output("tg-team-rank", "disabled"),
        Output("tg-logos", "disabled"), Output("z-stat", "disabled"),
        Input("tg-traj", "value"), Input("season-slider", "value"),
    )
    def gray_team_controls_in_traj(traj, season):
        lo, hi = season_bounds(season)
        # A single-season "trajectory" falls back to the normal scatter, so
        # the controls stay live there.
        off = bool(traj) and lo is not None and hi > lo
        return (off,) * 6

    @app.callback(
        Output("tg-player-vmean", "disabled"),
        Output("tg-player-hmean", "disabled"),
        Output("tg-player-trend", "disabled"),
        Output("tg-player-rank", "disabled"),
        Output("p-z-stat", "disabled"),
        Input("tg-player-traj", "value"), Input("season-slider", "value"),
    )
    def gray_player_controls_in_traj(traj, season):
        lo, hi = season_bounds(season)
        off = bool(traj) and lo is not None and hi > lo
        return (off,) * 5

    # ---- stat option lists ----
    def _team_stat(stat_type, season, current, fallback_idx=0, allow_none=False):
        key = "team_batting_dir" if stat_type == "Batting" else "team_pitching_dir"
        # Column set comes from one season (the range's upper year); columns are
        # stable across the span, so listing options off the latest is enough.
        _, hi = season_bounds(season)
        df = load_csv(f"{config[key]}/{hi or current_year()}.csv")
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
        _, hi = season_bounds(season)
        df = load_csv(f"{config[key]}/{hi or current_year()}.csv")
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
        _, hi = season_bounds(season)
        df = load_csv(f"{config[key]}/{hi or current_year()}.csv")
        base = [{"label": "All Teams", "value": "All Teams"},
                {"label": "AL", "value": "AL"}, {"label": "NL", "value": "NL"}]
        if df.empty or "Team" not in df.columns:
            return base, "All Teams"
        teams = sorted(t for t in df["Team"].unique() if t not in (MULTI_TEAM, ""))
        options = base + opts(teams)
        if (df["Team"] == MULTI_TEAM).any():
            options.append({"label": "Multiple teams (traded)",
                            "value": MULTI_TEAM})
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
            seasons = season_list()
            dk = ("qualified_batting_dir" if ptype == "Batters"
                  else "qualified_pitching_dir")
            valid = set(seasons)
            for stat in (pxs, pys):
                if stat:
                    av = seasons_with_data(dk, stat)
                    if av:
                        valid &= av
        else:
            seasons = season_list()
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
        # Preserve the current [lo, hi] window, clamped into the data-aware
        # range; fall back to the latest single season.
        lo, hi = season_bounds(cur)
        if lo is None:
            lo = hi = mx
        lo = max(mn, min(mx, lo))
        hi = max(mn, min(mx, hi))
        if hi < lo:
            lo, hi = hi, lo
        return mn, mx, decade_marks(mn, mx), [lo, hi]

    @app.callback(
        Output("season-slider", "value", allow_duplicate=True),
        Input("season-from", "value"), Input("season-to", "value"),
        State("season-slider", "value"),
        State("season-slider", "min"), State("season-slider", "max"),
        prevent_initial_call=True,
    )
    def season_range_input(frm, to, cur, mn, mx):
        clo, chi = season_bounds(cur)
        if clo is None:
            clo = chi = mx

        def _clamp(v, fallback):
            try:
                return max(mn, min(mx, int(v)))
            except (TypeError, ValueError):
                return fallback

        lo, hi = _clamp(frm, clo), _clamp(to, chi)
        if hi < lo:
            lo, hi = hi, lo
        return [lo, hi] if [lo, hi] != [clo, chi] else no_update

    @app.callback(
        Output("split-row", "style"),
        Input("season-slider", "value"),
    )
    def toggle_split_row(season):
        # Combined vs per-season only means something across 2+ seasons.
        lo, hi = season_bounds(season)
        return {} if (lo is not None and hi > lo) else {"display": "none"}

    @app.callback(
        Output("season-val", "children"),
        Output("season-from", "value"), Output("season-to", "value"),
        Input("season-slider", "value"),
    )
    def season_display(value):
        lo, hi = season_bounds(value)
        if lo is None:
            return "", None, None
        return season_label(lo, hi), lo, hi

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

    # ---- player presets ----
    @app.callback(
        Output("player-presets-container", "children"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
    )
    def swap_player_presets(ptype):
        """Rebuild player preset chips when toggling Batters ↔ Pitchers."""
        return [player_preset_chips(ptype)]

    @app.callback(
        Output("p-x-stat", "value", allow_duplicate=True),
        Output("p-y-stat", "value", allow_duplicate=True),
        Input({"kind": "player-preset", "id": ALL}, "n_clicks"),
        State({"kind": "seg-store", "group": "ptype"}, "data"),
        prevent_initial_call=True,
    )
    def apply_player_preset(clicks, ptype):
        if not clicks or not any(clicks):
            return no_update, no_update
        pid = ctx.triggered_id["id"]
        presets = PITCHER_PRESETS if ptype == "Pitchers" else BATTER_PRESETS
        preset = next((p for p in presets if p["id"] == pid), None)
        if not preset:
            return no_update, no_update
        return preset["x"], preset["y"]

    @app.callback(
        Output({"kind": "player-preset", "id": ALL}, "className"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        State({"kind": "player-preset", "id": ALL}, "id"),
    )
    def style_player_preset_chips(xs, ys, ptype, ids):
        presets = PITCHER_PRESETS if ptype == "Pitchers" else BATTER_PRESETS
        out = []
        for pid in ids:
            p = next((q for q in presets if q["id"] == pid["id"]), None)
            active = bool(p and p["x"] == xs and p["y"] == ys)
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
        Input("tg-trend", "value"), Input("tg-era", "value"),
        Input("tg-traj", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input("p-z-stat", "value"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"), Input("tg-player-rank", "value"),
        Input("tg-player-vmean", "value"), Input("tg-player-hmean", "value"),
        Input("tg-player-trend", "value"), Input("tg-player-era", "value"),
        Input("tg-player-traj", "value"), Input("player-find", "value"),
        Input({"kind": "seg-store", "group": "plabels"}, "data"),
        Input("team-league", "value"),
        Input({"kind": "seg-store", "group": "split"}, "data"),
        prevent_initial_call=True,
    )
    def sync_url(view, season, xt, yt, zt, xs, ys, zs, vm, hm, tr, lg,
                 trend, era, traj,
                 ptype, pxs, pys, pzs, mpa, mip, tf, pr, pvm, phm,
                 ptrend, pera, ptraj, find, plabels, league, split):
        lo, hi = season_bounds(season)
        season_q = "" if lo is None else lo
        season_end_q = "" if lo is None else hi
        if view == "player":
            params = dict(view="player", season=season_q, season_end=season_end_q,
                          player_type=ptype or "Batters",
                          p_x_stat=pxs or "", p_y_stat=pys or "",
                          p_z_stat=pzs or "", min_pa=mpa, min_ip=mip,
                          team=tf or "All Teams",
                          p_color_rank=str(bool(pr)).lower(),
                          p_show_v=str(bool(pvm)).lower(),
                          p_show_h=str(bool(phm)).lower(),
                          p_trend=str(bool(ptrend)).lower(),
                          p_era=str(bool(pera)).lower(),
                          p_traj=str(bool(ptraj)).lower(),
                          find=(find or "").strip(),
                          p_labels=plabels or "all")
        else:
            params = dict(view="team", season=season_q, season_end=season_end_q,
                          x_type=xt or "Batting", y_type=yt or "Pitching",
                          z_type=zt or "Batting",
                          x_stat=xs or "", y_stat=ys or "", z_stat=zs or "",
                          show_v=str(bool(vm)).lower(),
                          show_h=str(bool(hm)).lower(),
                          color_rank=str(bool(tr)).lower(),
                          logos=str(bool(lg)).lower(),
                          trend=str(bool(trend)).lower(),
                          era=str(bool(era)).lower(),
                          traj=str(bool(traj)).lower(),
                          league=league or "All Teams")
        # Per-season range view; omitted when off so existing links are
        # unchanged (absent → combined).
        if split == "season":
            params["split"] = "season"
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
        Input("tg-trend", "value"), Input("tg-era", "value"),
        Input("tg-traj", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input("p-z-stat", "value"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"), Input("tg-player-rank", "value"),
        Input("tg-player-vmean", "value"), Input("tg-player-hmean", "value"),
        Input("tg-player-trend", "value"), Input("tg-player-era", "value"),
        Input("tg-player-traj", "value"), Input("player-find", "value"),
        Input({"kind": "seg-store", "group": "plabels"}, "data"),
        Input("team-league", "value"),
        Input("theme-store", "data"),
        Input({"kind": "seg-store", "group": "split"}, "data"),
    )
    def render(view, season, xt, yt, zt, xs, ys, zs, vm, hm, tr, lg,
               trend, era, traj,
               ptype, pxs, pys, pzs, mpa, mip, tf, pr, pvm, phm,
               ptrend, pera, ptraj, find, plabels, league, theme, split):
        theme = theme or "dark"
        per_season = (split == "season")
        if view == "player":
            return render_player(season, ptype, pxs, pys, mpa, mip, tf,
                                 bool(pr), pzs, bool(pvm), bool(phm), theme,
                                 show_trend=bool(ptrend), era=bool(pera),
                                 traj=bool(ptraj), find=find or "",
                                 label_mode=plabels or "all",
                                 split=per_season)
        return render_team(season, bool(lg), xt, yt, xs, ys,
                           bool(vm), bool(hm), bool(tr), zt, zs, theme,
                           league or "All Teams", show_trend=bool(trend),
                           era=bool(era), traj=bool(traj), split=per_season)

    @app.callback(
        Output("leaderboard", "children"), Output("leaderboard", "style"),
        Input({"kind": "seg-store", "group": "view"}, "data"),
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "xtype"}, "data"),
        Input({"kind": "seg-store", "group": "ytype"}, "data"),
        Input({"kind": "seg-store", "group": "ztype"}, "data"),
        Input("x-stat", "value"), Input("y-stat", "value"), Input("z-stat", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("p-x-stat", "value"), Input("p-y-stat", "value"),
        Input("p-z-stat", "value"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"), Input("team-league", "value"),
        Input("tg-era", "value"), Input("tg-player-era", "value"),
        Input({"kind": "seg-store", "group": "split"}, "data"),
    )
    def update_leaderboard(view, season, xt, yt, zt, xs, ys, zs,
                           ptype, pxs, pys, pzs, mpa, mip, tf, league,
                           era, pera, split):
        if view == "player":
            rows, n = _player_leaderboard_rows(season, ptype, pxs, pys, pzs,
                                               mpa, mip, tf, era=bool(pera),
                                               split=split)
        else:
            rows, n = _leaderboard_rows(season, xt, yt, xs, ys, zt, zs,
                                        league or "All Teams", era=bool(era),
                                        split=split)
        if not rows:
            return [], {"display": "none"}
        return leaderboard_cards(rows, n), {}

    # ---- CSV export of the current view ----
    @app.callback(
        Output("csv-download", "data"),
        Input("csv-export-btn", "n_clicks"),
        State({"kind": "seg-store", "group": "view"}, "data"),
        State("season-slider", "value"),
        State({"kind": "seg-store", "group": "xtype"}, "data"),
        State({"kind": "seg-store", "group": "ytype"}, "data"),
        State({"kind": "seg-store", "group": "ztype"}, "data"),
        State("x-stat", "value"), State("y-stat", "value"),
        State("z-stat", "value"),
        State("team-league", "value"), State("tg-era", "value"),
        State({"kind": "seg-store", "group": "ptype"}, "data"),
        State("p-x-stat", "value"), State("p-y-stat", "value"),
        State("p-z-stat", "value"),
        State("min-pa", "value"), State("min-ip", "value"),
        State("team-filter", "value"), State("player-find", "value"),
        State("tg-player-era", "value"),
        State({"kind": "seg-store", "group": "split"}, "data"),
        prevent_initial_call=True,
    )
    def export_csv(n, view, season, xt, yt, zt, xs, ys, zs, league, era,
                   ptype, pxs, pys, pzs, mpa, mip, tf, find, pera, split):
        if not n:
            return no_update
        df, fname = _export_frame(view, season, xt, yt, xs, ys, zt, zs,
                                  league, bool(era), ptype or "Batters",
                                  pxs, pys, pzs, mpa, mip, tf or "All Teams",
                                  find, bool(pera), split=split)
        if df is None:
            return no_update
        return dcc.send_data_frame(df.to_csv, fname, index=False)

    # ---- detail panel (teams and players) ----
    @app.callback(
        Output("detail-overlay", "style"),
        Output("detail-store", "data"),
        Output("detail-body", "children", allow_duplicate=True),
        Input("main-graph", "clickData"),
        Input({"kind": "lb-card", "ref": ALL, "rank": ALL}, "n_clicks"),
        Input("detail-close", "n_clicks"),
        State({"kind": "seg-store", "group": "view"}, "data"),
        State({"kind": "seg-store", "group": "split"}, "data"),
        State("season-slider", "value"),
        prevent_initial_call=True,
    )
    def open_detail(click, lb_clicks, _close, view, split, season):
        nothing = (no_update, no_update, no_update)
        trig = ctx.triggered_id
        if trig == "detail-close":
            # Clear the store (not no_update) so a closed panel renders nothing
            # and render_detail — which now also listens to the season and
            # filters — stops rebuilding a hidden panel on every slider move.
            return {"display": "none"}, None, no_update

        def opened(store, label=None):
            # The overlay opens with a loading placeholder in the same
            # response, so the previously opened team/player never shows while
            # render_detail builds the new one. The nonce makes the store
            # change (and render_detail fire) even when re-opening the same
            # entity after the placeholder replaced its body.
            store = dict(store, n=time.time_ns())
            if label is None and store.get("type") == "team":
                label = team_name(store.get("team"), store.get("season"))
            return {}, store, detail_loading(label)

        # Store {"type":"team","team":abbr} or {"type":"player","idfg":N};
        # render_detail branches on the type. Per-season entries add "season"
        # so the panel shows that one season instead of the slider's range.
        per_season = _split_on(split, *season_bounds(season))
        if isinstance(trig, dict) and trig.get("kind") == "lb-card":
            if not any(lb_clicks or []):
                return nothing
            ref, _, yr = str(trig["ref"]).partition("|")
            if view == "player":
                try:
                    store = {"type": "player", "idfg": int(ref)}
                except (TypeError, ValueError):
                    return nothing
                if yr:
                    store["season"] = int(yr)
                return opened(store)
            store = {"type": "team", "team": ref}
            if yr:
                store["season"] = int(yr)
            return opened(store)
        if trig == "main-graph":
            if not click:
                return nothing
            try:
                pt = click["points"][0]
            except (KeyError, IndexError, TypeError):
                return nothing
            if view == "player":
                cd = pt.get("customdata")
                try:
                    store = {"type": "player", "idfg": int(cd[0])}
                    # Per-season scatter points carry [IDfg, _row, Season].
                    if per_season and len(cd) >= 3:
                        store["season"] = int(cd[2])
                except (TypeError, ValueError, IndexError):
                    return nothing
                return opened(store, pt.get("hovertext"))
            cd = pt.get("customdata")
            # Per-season team points carry [Team, Season, rank]; their text
            # label ("LAD ’22") isn't a bare team code.
            if (per_season and isinstance(cd, (list, tuple)) and len(cd) >= 3
                    and isinstance(cd[0], str)
                    and re.fullmatch(r"[A-Z0-9]{2,4}", cd[0])):
                try:
                    return opened({"type": "team", "team": cd[0],
                                   "season": int(cd[1])})
                except (TypeError, ValueError):
                    return nothing
            abbr = pt.get("text")
            if not abbr:
                # Trajectory paths label only their final point; the team code
                # rides in customdata[0] so mid-path clicks work too. (In
                # rank-color mode customdata is a scalar score — skip it.)
                if isinstance(cd, (list, tuple)) and cd:
                    abbr = cd[0]
            # Any FanGraphs team code opens its panel — historical clubs (MON,
            # BRO, HG…) included, not just the 30 current ones with colors.
            if not (isinstance(abbr, str) and re.fullmatch(r"[A-Z0-9]{2,4}", abbr)):
                return nothing
            return opened({"type": "team", "team": abbr})
        return nothing

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
        Output("p-x-stat", "value", allow_duplicate=True),
        Output("detail-overlay", "style", allow_duplicate=True),
        Input({"kind": "pdt-stat", "stat": ALL}, "n_clicks"),
        State({"kind": "seg-store", "group": "view"}, "data"),
        prevent_initial_call=True,
    )
    def pick_player_detail_stat(clicks, view):
        """Clicking a tile in the player panel sets it as the X axis (parity
        with the team panel's stat → axis behaviour) and closes the panel."""
        if not clicks or not any(clicks) or view != "player":
            return no_update, no_update
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update, no_update
        return trig["stat"], {"display": "none"}

    @app.callback(
        Output("detail-body", "children"),
        Input("detail-store", "data"),
        # Season/filters are Inputs, not State, so an open panel refreshes when
        # the context changes underneath it (drag the season slider while a team
        # is open) instead of showing stale numbers. When the panel is closed
        # open_detail clears detail-store to None, so this no-ops (see below).
        Input("season-slider", "value"),
        Input({"kind": "seg-store", "group": "ptype"}, "data"),
        Input("min-pa", "value"), Input("min-ip", "value"),
        Input("team-filter", "value"),
    )
    def render_detail(store, season, ptype, mpa, mip, tf):
        if not store:
            return None
        lo, hi = season_bounds(season)
        if lo is None:
            lo = hi = current_year()
        if isinstance(store, dict) and store.get("season"):
            # A per-season point/card: show that one season.
            lo = hi = int(store["season"])
        if isinstance(store, dict) and store.get("type") == "player":
            return _player_detail(store["idfg"], lo, hi, ptype or "Batters",
                                  mpa, mip, tf or "All Teams")
        team = store.get("team") if isinstance(store, dict) else store
        if not team:
            return None
        groups, all_pcts = [], []
        for gname, gtype, dir_key, stats in DETAIL_GROUPS:
            tiles = []
            for stat, hib in stats:
                v, df = _team_span_value(dir_key, lo, hi, team, stat)
                if v is None or df.empty or stat not in df.columns:
                    continue
                pct = _pct(df[stat], v, hib)
                all_pcts.append(pct)
                tiles.append({"label": stat, "type": gtype,
                              "value": fmt_stat(stat, v), "pct": pct,
                              "ramp": ramp_color(pct / 100)})
            if tiles:
                groups.append({"name": gname, "tiles": tiles})
        composite = int(round(sum(all_pcts) / len(all_pcts))) if all_pcts else 50
        # The team's own seasons inside the range (a franchise that folded or
        # moved — MON 1969–2004 — doesn't span the whole slider).
        seasons = []
        for y in range(lo, hi + 1):
            df = load_csv(f"{config['team_batting_dir']}/{y}.csv",
                          fetch=False, copy=False)
            if not df.empty and "Team" in df.columns and (df["Team"] == team).any():
                seasons.append(y)
        if hi > lo and seasons:
            span = season_label(seasons[0], seasons[-1])
            eyebrow = (f"{span} · {len(seasons)} SEASONS" if len(seasons) > 1
                       else f"{span} SEASON")
            spark_years = seasons[-SPARK_MAX_SEASONS:]
            sparks = [_spark(s, dk, team, hi, years_in=spark_years)
                      for s, dk in SPARK_STATS]
            sp_yrs = sorted({y for sp in sparks for y in sp["years"]})
            spark_title = (f"TRAJECTORY · {season_label(sp_yrs[0], sp_yrs[-1])}"
                           if len(sp_yrs) > 1 else "TRAJECTORY")
            foot = (f"Percentiles vs. all teams, {season_label(lo, hi)} "
                    "(range totals).")
        else:
            eyebrow = f"{season_label(lo, hi)} SEASON"
            sparks = [_spark(s, dk, team, hi) for s, dk in SPARK_STATS]
            spark_title = "5-YEAR TRAJECTORY"
            foot = None
        return detail_body(team, eyebrow, composite, sparks, groups,
                           spark_title=spark_title, foot=foot,
                           logo_season=seasons[-1] if seasons else hi)
