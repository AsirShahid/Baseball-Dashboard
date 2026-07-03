#!/usr/bin/env python3
"""Offline smoke tests for the dashboard's data and chart layers.

Everything here runs against CSVs committed to the repo or synthetic frames —
no network access — so CI is deterministic. Network fetch paths
(`fetch=True`) are deliberately not exercised.
"""

import os
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import load_csv, seasons_with_data  # noqa: E402


SEASON = 2024  # ships with the repo


def test_imports_and_layout():
    """The whole app imports and builds a layout (registers all callbacks)."""
    import app
    layout = app.serve_layout()
    assert layout is not None


def test_render_team_aligns_on_team():
    """X and Y come from different CSVs with different row orders; points must
    pair up by Team, not by row position."""
    from charts import render_team
    fig, _eyebrow, _title = render_team(
        SEASON, False, "Batting", "Pitching", "wRC+", "ERA",
        True, True, False, "Batting", None)
    tr = fig.data[0]
    b = pd.read_csv(f"team_batting/{SEASON}.csv")
    p = pd.read_csv(f"team_pitching/{SEASON}.csv")
    merged = b[["Team", "wRC+"]].merge(p[["Team", "ERA"]], on="Team")
    assert len(tr.x) == len(merged)
    i = list(tr.text).index("LAD")
    exp = merged[merged.Team == "LAD"].iloc[0]
    assert tr.x[i] == pytest.approx(exp["wRC+"])
    assert tr.y[i] == pytest.approx(exp["ERA"])


def test_render_team_3d_and_rank():
    from charts import render_team
    fig, *_ = render_team(SEASON, False, "Batting", "Pitching", "wRC+", "ERA",
                          True, True, True, "Batting", "HR")
    assert len(fig.data) >= 1  # scatter + mean planes


def test_render_team_logos_use_data_coords():
    from charts import render_team
    fig, *_ = render_team(SEASON, True, "Batting", "Pitching", "wRC+", "ERA",
                          True, True, False, "Batting", None)
    imgs = fig.layout.images
    assert imgs
    assert imgs[0].xref == "x" and imgs[0].yref == "y"


def test_render_player_no_inf_with_min_pa_zero():
    """WAR/650 with PA=0 rows must not leak inf into the plot."""
    from charts import render_player
    fig, *_ = render_player(SEASON, "Batters", "WAR/650 PAs", "wRC+",
                            0, "Qualified", "All Teams", False, None)
    xs = np.array(fig.data[0].x, dtype=float)
    assert not np.isinf(xs[~np.isnan(xs)]).any()


def test_al_filter_historical_season():
    """1955 uses old franchise codes (BRO, KCA, …); the AL filter should keep
    some players rather than dropping everyone."""
    from charts import render_player
    fig, *_ = render_player(1955, "Batters", "WAR", "AVG",
                            "Qualified", "Qualified", "AL", False, None)
    assert sum(len(t.x) for t in fig.data) > 0


def test_leaderboard_rows():
    from callbacks import _leaderboard_rows
    rows, n = _leaderboard_rows(SEASON, "Batting", "Pitching", "wRC+", "ERA",
                                "Batting", None)
    assert len(rows) == 10 and n == 2
    assert all(0 <= r["pct"] <= 100 for r in rows)


def _fake_team_load_stats(dir_key, lo, hi=None, group_key="Team"):
    """Synthetic team frame with an all-NaN column, for the degenerate-axis
    tests — the shipped CSVs no longer have a naturally all-NaN stat."""
    n = 12
    return pd.DataFrame({
        "Team": [f"T{i:02d}" for i in range(n)],
        "wRC+": np.linspace(80, 120, n),
        "ERA":  np.linspace(3.0, 5.0, n),
        "AllNaN": [np.nan] * n,
    })


def test_leaderboard_drops_all_nan_axis(monkeypatch):
    """An all-NaN axis carries no signal: x/y all-NaN yields an empty board
    (not every team tied at 50), and an all-NaN Z is dropped from the count so
    the leaderboard agrees with the chart on how many axes are live."""
    import callbacks
    from callbacks import _leaderboard_rows
    monkeypatch.setattr(callbacks, "load_stats", _fake_team_load_stats)
    rows, n = _leaderboard_rows(SEASON, "Batting", "Pitching", "AllNaN", "ERA",
                                "Batting", None)
    assert rows == [] and n == 0
    # A valid 2-axis board with an all-NaN Z must stay a 2-axis board.
    rows, n = _leaderboard_rows(SEASON, "Batting", "Pitching", "wRC+", "ERA",
                                "Batting", "AllNaN")
    assert len(rows) == 10 and n == 2


def test_render_team_degenerate_z_falls_back_to_2d(monkeypatch):
    """A Z axis with no team-level data must not force a collapsed 3D plot."""
    import charts
    from charts import render_team
    import plotly.graph_objects as go
    monkeypatch.setattr(charts, "load_stats", _fake_team_load_stats)
    fig, eyebrow, _ = render_team(SEASON, False, "Batting", "Pitching",
                                  "wRC+", "ERA", True, True, False,
                                  "Batting", "AllNaN")
    assert not any(isinstance(t, go.Scatter3d) for t in fig.data)
    assert eyebrow[0] == "2D SCATTER"


def test_load_csv_copy_on_read_and_mtime_invalidation():
    path = f"team_batting/{SEASON}.csv"
    df1 = load_csv(path)
    df1["wRC+"] = -1  # mutate the returned frame
    df2 = load_csv(path)
    assert (df2["wRC+"] != -1).all()  # cache wasn't poisoned
    os.utime(path)  # bump mtime -> cache must refresh
    df3 = load_csv(path)
    assert (df3["wRC+"] != -1).all()


def test_spark_does_not_fetch():
    from callbacks import _spark, _team_value
    # 1850 has no team CSV; fetch=False must return empty without hitting the
    # network (a network attempt would either hang or raise, not return None).
    v, d = _team_value("team_batting_dir", 1850, "LAD", "wRC+", fetch=False)
    assert v is None and d.empty
    s = _spark("wRC+", "team_batting_dir", "LAD", SEASON)
    assert s["years"] == sorted(s["years"])


def test_seasons_with_data_is_cached():
    import time
    t0 = time.time(); a = seasons_with_data("qualified_batting_dir", "wRC+"); t1 = time.time()
    b = seasons_with_data("qualified_batting_dir", "wRC+"); t2 = time.time()
    assert a == b and len(a) > 0
    assert (t2 - t1) < (t1 - t0)  # warm call faster than cold


def test_fmt_val_negative_decimal():
    from callbacks import _fmt_val
    assert _fmt_val(0.123) == ".123"
    assert _fmt_val(-0.123) == "-.123"
    assert _fmt_val(float("nan")) == "—"


def test_aggregate_team_weighted_average():
    from fangraphs_api import aggregate_team, atomic_to_csv
    toy = pd.DataFrame({
        "Team": ["A", "A", "- - -"],
        "PA": [100, 300, 50],
        "wOBA": [0.300, 0.400, 0.500],  # rate -> weighted avg
        "HR": [10, 20, 5],              # counting -> sum
    })
    agg = aggregate_team(toy, "bat")
    assert list(agg.Team) == ["A"]          # phantom traded-team row dropped
    assert agg.wOBA[0] == pytest.approx(0.375)  # (.3*100+.4*300)/400
    assert agg.HR[0] == 30
    assert agg.PA[0] == 400


def test_atomic_to_csv_no_index_column(tmp_path):
    from fangraphs_api import atomic_to_csv
    df = pd.DataFrame({"Team": ["A", "B"], "x": [1, 2]})
    out = tmp_path / "out.csv"
    atomic_to_csv(df, out)
    back = pd.read_csv(out)
    assert "Unnamed: 0" not in back.columns
    assert list(back.Team) == ["A", "B"]


def test_split_month_picks_live_for_current_season():
    from fangraphs_api import split_month, LIVE_SPLIT, FULL_SEASON_SPLIT
    assert split_month(2026, 2026) == LIVE_SPLIT       # in-progress season
    assert split_month(2027, 2026) == LIVE_SPLIT       # future also live (falls back if empty)
    assert split_month(2025, 2026) == FULL_SEASON_SPLIT
    assert split_month(1990, 2026) == FULL_SEASON_SPLIT


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


def test_fetch_leaderboard_falls_back_when_live_split_empty(monkeypatch):
    """A live-split request that returns nothing must retry on the full-season
    split (so an out-of-season live request still yields data)."""
    import fangraphs_api as fa
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append(params["month"])
        if params["month"] == fa.FULL_SEASON_SPLIT:
            return _FakeResp([{"Name": "X", "Team": "NYY", "wRC+": 100}])
        return _FakeResp([])  # live split empty

    monkeypatch.setattr(fa.requests, "get", fake_get)
    df = fa.fetch_leaderboard("bat", "y", 2026, month=fa.LIVE_SPLIT)
    assert df is not None and len(df) == 1
    assert seen == [fa.LIVE_SPLIT, fa.FULL_SEASON_SPLIT]  # tried live, then fell back


def test_fetch_leaderboard_no_fallback_on_full_season(monkeypatch):
    """A full-season request that's empty should not loop back on itself."""
    import fangraphs_api as fa
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append(params["month"])
        return _FakeResp([])

    monkeypatch.setattr(fa.requests, "get", fake_get)
    df = fa.fetch_leaderboard("bat", "y", 1990)  # defaults to FULL_SEASON_SPLIT
    assert df is None
    assert seen == [fa.FULL_SEASON_SPLIT]  # exactly one request, no retry


def test_season_bounds_and_label():
    from data import season_bounds, season_label
    assert season_bounds(2024) == (2024, 2024)
    assert season_bounds([2026, 2019]) == (2019, 2026)   # order-insensitive
    assert season_bounds(None) == (None, None)
    assert season_label(2024, 2024) == "2024"
    lbl = season_label(2019, 2026)
    assert "2019" in lbl and "2026" in lbl


def test_load_stats_single_season_is_csv_fast_path():
    """A single-season load must be byte-identical to reading the CSV — the
    range machinery must not perturb the common case."""
    from data import load_stats
    span = load_stats("team_batting_dir", SEASON, SEASON)
    csv = pd.read_csv(f"team_batting/{SEASON}.csv")
    assert len(span) == len(csv)
    assert "LAD" in set(span["Team"].astype(str))


def test_load_stats_range_sums_counting_and_weights_rates():
    """Over a span: WAR (counting) sums; wRC+ (rate) is PA-weighted, not summed."""
    from data import load_stats
    span = load_stats("team_batting_dir", 2022, 2024)
    assert span["Team"].is_unique                      # one row per team
    seasons = [pd.read_csv(f"team_batting/{y}.csv") for y in (2022, 2023, 2024)]
    war_sum = sum(float(d.loc[d.Team == "LAD", "WAR"].iloc[0]) for d in seasons)
    got_war = float(span.loc[span.Team == "LAD", "WAR"].iloc[0])
    assert got_war == pytest.approx(war_sum)           # counting summed
    wrc = float(span.loc[span.Team == "LAD", "wRC+"].iloc[0])
    assert 50 < wrc < 200                              # rate stays banded, not summed


def test_load_stats_range_aggregates_players_by_idfg():
    """Player spans roll up by IDfg, so a player appears once with summed PA."""
    from data import load_stats
    span = load_stats("qualified_batting_dir", 2022, 2024, group_key="IDfg")
    assert span["IDfg"].is_unique
    assert {"Name", "Team", "PA", "WAR"} <= set(span.columns)


def test_render_team_range_one_point_per_team():
    from charts import render_team
    fig, eyebrow, _ = render_team([2022, 2024], False, "Batting", "Pitching",
                                  "WAR", "ERA", False, False, False, "Batting", None)
    tr = fig.data[0]
    assert len(set(tr.text)) == len(tr.text)           # no duplicate teams
    flat = "".join(str(x) for x in eyebrow)
    assert "2022" in flat and "2024" in flat


def test_player_leaderboard_single_and_range():
    from callbacks import _player_leaderboard_rows
    rows, n = _player_leaderboard_rows(SEASON, "Batters", "WAR", "wRC+", None,
                                       "Qualified", "Qualified", "All Teams")
    assert len(rows) == 10 and n == 2
    assert all(0 <= r["pct"] <= 100 for r in rows)
    # 3-axis: a valid Z lifts the axis count to 3
    _, n3 = _player_leaderboard_rows(SEASON, "Batters", "WAR", "wRC+", "HR",
                                     "Qualified", "Qualified", "All Teams")
    assert n3 == 3
    # Multi-season cumulative board still returns a top-10
    rrows, rn = _player_leaderboard_rows([2022, 2024], "Batters", "WAR", "wRC+",
                                         None, "Qualified", "Qualified", "All Teams")
    assert len(rrows) == 10 and rn == 2


def test_render_player_single_z_value_stays_2d():
    """A Z axis with <2 real values must fall back to 2D (parity with teams)."""
    from charts import render_player, player_frame
    import plotly.graph_objects as go
    # Find a specific team whose qualified roster that season is a single player,
    # so any per-player Z column has <2 non-null values.
    df = player_frame(SEASON, SEASON, "Batters", "Qualified", "Qualified", "All Teams")
    counts = df["Team"].value_counts()
    solo = counts[counts == 1]
    if solo.empty:
        pytest.skip("no single-player team this season")
    team = solo.index[0]
    fig, eyebrow, _ = render_player(SEASON, "Batters", "WAR", "wRC+",
                                    "Qualified", "Qualified", team, False, "HR")
    assert not any(isinstance(t, go.Scatter3d) for t in fig.data)
    assert eyebrow[0] == "2D SCATTER"


def test_player_detail_panel_builds():
    """Clicking a player builds a detail panel: tiles + composite + sparklines,
    for batters and pitchers, single season and range."""
    from callbacks import _player_detail, _player_leaderboard_rows
    rows, _ = _player_leaderboard_rows(SEASON, "Batters", "WAR", "wRC+", None,
                                       "Qualified", "Qualified", "All Teams")
    idfg = int(rows[0]["ref"])
    body = _player_detail(idfg, SEASON, SEASON, "Batters",
                          "Qualified", "Qualified", "All Teams")
    assert body is not None and len(body) >= 3          # head + sparks + tiles
    # Multi-season range still resolves the same player
    assert _player_detail(idfg, 2022, SEASON, "Batters",
                          "Qualified", "Qualified", "All Teams") is not None
    # A player outside an active team filter still renders (fallback pool)
    assert _player_detail(idfg, SEASON, SEASON, "Batters",
                          "Qualified", "Qualified", "BOS") is not None
    # Unknown id → no panel
    assert _player_detail(10 ** 12, SEASON, SEASON, "Batters",
                          "Qualified", "Qualified", "All Teams") is None


def test_player_point_carries_idfg_for_detail():
    """The scatter must tag each point with its IDfg (customdata[0]) so a click
    can open the right player's panel even when two players share a name."""
    from charts import render_player, player_frame
    import numpy as np
    fig, *_ = render_player(SEASON, "Batters", "WAR", "wRC+",
                            "Qualified", "Qualified", "All Teams", False, None)
    pool = player_frame(SEASON, SEASON, "Batters", "Qualified", "Qualified",
                        "All Teams")
    valid = set(int(x) for x in pool["IDfg"])
    seen = set()
    for tr in fig.data:
        if getattr(tr, "customdata", None) is None:
            continue
        for r in tr.customdata:
            seen.add(int(r[0]))
    assert seen and seen <= valid


def test_team_league_filter_chart_and_leaderboard():
    """The team-view league/division filter must restrict both the scatter and
    the leaderboard to the selected teams (parity with the player team filter)."""
    from charts import render_team
    from callbacks import _leaderboard_rows
    from data import AL_TEAMS, NL_TEAMS

    fig, *_ = render_team(SEASON, False, "Batting", "Pitching", "WAR", "ERA",
                          True, True, False, "Batting", None, "dark", "AL")
    chart_teams = list(fig.data[0].text)
    assert chart_teams and all(t in AL_TEAMS for t in chart_teams)

    # A division narrows further to exactly that division's clubs.
    fig2, *_ = render_team(SEASON, False, "Batting", "Pitching", "WAR", "ERA",
                           True, True, False, "Batting", None, "dark", "AL East")
    assert set(fig2.data[0].text) == {"BAL", "BOS", "NYY", "TBR", "TOR"}

    # Leaderboard ranks within the league only.
    rows, n = _leaderboard_rows(SEASON, "Batting", "Pitching", "WAR", "ERA",
                                "Batting", None, "NL")
    assert rows and all(r["team"] in NL_TEAMS for r in rows)
    # Default is unchanged (all 30 → a full top-10).
    rows_all, _ = _leaderboard_rows(SEASON, "Batting", "Pitching", "WAR", "ERA",
                                    "Batting", None, "All Teams")
    assert len(rows_all) == 10


def test_team_in_league_helper():
    from data import team_in_league
    assert team_in_league("NYY", "AL") and not team_in_league("NYY", "NL")
    assert team_in_league("LAD", "NL West") and not team_in_league("LAD", "AL West")
    assert team_in_league("NYY", "All Teams") and team_in_league("ANY", None)


# ── New-feature tests: id normalisation, era percentiles, trend, search,
#    label modes, trajectories, CSV export ──────────────────────────────────

def test_playerid_normalized_to_idfg():
    """CSVs written straight from the FanGraphs API use `playerid`; the loader
    must present it as IDfg (which all click/detail/aggregation code keys on)."""
    df = load_csv(f"qualified_batting_stats/{SEASON}.csv")
    assert "IDfg" in df.columns and "playerid" not in df.columns


def test_meta_columns_excluded_from_stat_options():
    from data import process_columns
    df = load_csv(f"qualified_batting_stats/{SEASON}.csv")
    cols = set(process_columns(df.columns))
    assert not cols & {"IDfg", "playerid", "xMLBAMID", "teamid",
                       "playerTeamId", "PlayerNameRoute", "TeamNameAbb"}


def test_pct_within_season_direction_and_bounds():
    from data import pct_within_season
    df = pd.DataFrame({"Team": ["A", "B", "C", "D"],
                       "ERA": [2.0, 3.0, 4.0, 5.0]})
    out = pct_within_season(df, ["ERA"])
    # Percentile keeps raw direction: the highest ERA ranks highest.
    assert out["ERA"].iloc[3] == 100.0 and out["ERA"].iloc[0] == 25.0


def test_load_stats_pct_averages_percentiles_not_sums(monkeypatch):
    """Era-adjusted spans must weight-average within-season percentiles — even
    for counting stats like HR, which the raw span aggregation would sum."""
    import data as data_mod
    seasons = {
        2001: pd.DataFrame({"Team": ["A", "B"], "PA": [100, 100],
                            "HR": [60, 20]}),
        2002: pd.DataFrame({"Team": ["A", "B"], "PA": [100, 100],
                            "HR": [10, 40]}),
    }

    def fake_load_csv(path, fetch=True):
        for y, df in seasons.items():
            if f"{y}.csv" in str(path):
                return df.copy()
        return pd.DataFrame()

    monkeypatch.setattr(data_mod, "load_csv", fake_load_csv)
    out = data_mod.load_stats_pct("team_batting_dir", 2001, 2002, ["HR"])
    a = float(out.loc[out.Team == "A", "HR"].iloc[0])
    # A is the HR leader in 2001 (100th pctl) and trailer in 2002 (50th pctl
    # of 2): equal PA -> mean of 100 and 50, never 60+10=70 raw or a sum of
    # percentiles (200).
    assert a == pytest.approx(75.0)
    assert float(out.loc[out.Team == "B", "HR"].iloc[0]) == pytest.approx(75.0)


def test_team_frame_era_bounds():
    from charts import team_frame
    df, is_3d, err = team_frame(2019, SEASON, "Batting", "Pitching",
                                "wRC+", "ERA", era=True)
    assert err is None and not is_3d
    for col in ("_x", "_y"):
        v = df[col].dropna()
        assert (v >= 0).all() and (v <= 100).all()


def test_render_team_trendline():
    from charts import render_team
    fig, *_ = render_team(SEASON, False, "Batting", "Pitching", "wRC+", "ERA",
                          False, False, False, "Batting", None, "dark",
                          "All Teams", True)
    assert any(t.mode == "lines" and t.name == "trend" for t in fig.data)
    assert any("r²" in (a.text or "") for a in fig.layout.annotations)


def test_render_player_trendline():
    from charts import render_player
    fig, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                            "Qualified", "All Teams", False, None,
                            False, False, "dark", show_trend=True)
    assert any(t.mode == "lines" and t.name == "trend" for t in fig.data)


def test_player_search_highlights_and_dims():
    from charts import render_player, DIM_OPACITY
    fig, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                            "Qualified", "All Teams", False, None,
                            False, False, "dark", find="judge")
    hi_sizes, opacities, matched_labels = [], [], []
    for tr in fig.data:
        if getattr(tr, "customdata", None) is None:
            continue
        sizes = tr.marker.size
        if hasattr(sizes, "__len__"):
            hi_sizes += [s for s in sizes if s > 10]
            opacities += list(tr.marker.opacity)
            matched_labels += [t for t, s in zip(tr.text, sizes) if s > 10]
    assert hi_sizes                      # the match got a bigger marker
    assert DIM_OPACITY in opacities      # everyone else got dimmed
    assert any("Judge" in t for t in matched_labels)


def test_player_search_no_match_annotates():
    from charts import render_player
    fig, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                            "Qualified", "All Teams", False, None,
                            False, False, "dark", find="zzzznobody")
    assert any("no player matching" in (a.text or "")
               for a in fig.layout.annotations)


def _label_count(fig):
    return sum(1 for tr in fig.data
               if tr.text is not None and not isinstance(tr.text, str)
               for t in tr.text if t)


def test_player_label_modes():
    from charts import render_player, OUTLIER_LABELS
    common = dict(show_v=False, show_h=False, theme="dark")
    fig_all, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                                "Qualified", "All Teams", False, None,
                                label_mode="all", **common)
    fig_out, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                                "Qualified", "All Teams", False, None,
                                label_mode="outliers", **common)
    fig_none, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                                 "Qualified", "All Teams", False, None,
                                 label_mode="none", **common)
    n_all, n_out, n_none = map(_label_count, (fig_all, fig_out, fig_none))
    assert n_none == 0
    assert 0 < n_out <= OUTLIER_LABELS
    assert n_out < n_all


def test_label_mode_none_still_labels_search_match():
    from charts import render_player
    fig, *_ = render_player(SEASON, "Batters", "WAR", "wRC+", "Qualified",
                            "Qualified", "All Teams", False, None,
                            False, False, "dark", find="judge",
                            label_mode="none")
    assert _label_count(fig) >= 1


def test_team_trajectory_one_trace_per_team():
    from charts import render_team
    fig, eyebrow, _ = render_team([2022, 2024], False, "Batting", "Pitching",
                                  "wRC+", "ERA", False, False, False,
                                  "Batting", None, "dark", "All Teams",
                                  False, False, True)
    assert eyebrow[0] == "TRAJECTORY"
    assert len(fig.data) == 30
    assert all(len(t.x) == 3 for t in fig.data)
    # Only the final point of each path is labeled, with the team code.
    for t in fig.data:
        assert t.text[-1] and not any(t.text[:-1])


def test_team_trajectory_single_season_falls_back():
    """traj=True over a single season has nothing to connect — stay a scatter."""
    from charts import render_team
    fig, eyebrow, _ = render_team(SEASON, False, "Batting", "Pitching",
                                  "wRC+", "ERA", False, False, False,
                                  "Batting", None, "dark", "All Teams",
                                  False, False, True)
    assert eyebrow[0] == "2D SCATTER"


def test_player_trajectory_top10_and_search():
    from charts import render_player
    fig, eyebrow, _ = render_player([2022, 2024], "Batters", "WAR", "wRC+",
                                    "Qualified", "Qualified", "All Teams",
                                    False, None, False, False, "dark",
                                    traj=True)
    assert eyebrow[0] == "TRAJECTORY"
    assert 0 < len(fig.data) <= 10
    # Points carry [IDfg, Season] so clicks still open the detail panel.
    assert len(fig.data[0].customdata[0]) == 2
    fig2, *_ = render_player([2022, 2024], "Batters", "WAR", "wRC+",
                             "Qualified", "Qualified", "All Teams",
                             False, None, False, False, "dark",
                             traj=True, find="judge")
    assert len(fig2.data) >= 1
    assert all("Judge" in t.name for t in fig2.data)


def test_export_frame_team_and_player():
    from callbacks import _export_frame
    df, fname = _export_frame("team", [2022, 2024], "Batting", "Pitching",
                              "wRC+", "ERA", "Batting", None, "All Teams",
                              False, "Batters", None, None, None,
                              "Qualified", "Qualified", "All Teams", "", False)
    assert len(df) == 30 and "Composite Rank" in df.columns
    assert fname.startswith("teams_2022-2024") and fname.endswith(".csv")
    # Board is sorted best-first.
    assert df["Composite Rank"].is_monotonic_decreasing

    df, fname = _export_frame("player", SEASON, None, None, None, None, None,
                              None, "All Teams", False, "Batters",
                              "WAR", "wRC+", None, "Qualified", "Qualified",
                              "All Teams", "judge", False)
    assert len(df) == 1 and df["Name"].iloc[0] == "Aaron Judge"
    # Nothing to export -> (None, None), not an exception.
    df, fname = _export_frame("player", SEASON, None, None, None, None, None,
                              None, "All Teams", False, "Batters",
                              None, None, None, "Qualified", "Qualified",
                              "All Teams", "", False)
    assert df is None and fname is None


def test_render_player_era_adjusted_axis():
    from charts import render_player
    fig, eyebrow, _ = render_player([2019, 2024], "Batters", "OBP", "HR",
                                    "Qualified", "Qualified", "All Teams",
                                    False, None, False, False, "dark",
                                    era=True)
    flat = "".join(str(x) for x in eyebrow)
    assert "ERA-ADJUSTED" in flat
    assert "(era pctl)" in fig.layout.xaxis.title.text


# ── Traded players, seeded slider marks ──────────────────────────────────────

def test_traded_players_kept_in_league_filters():
    """FanGraphs marks traded players' seasons '- - -'. The AL/NL filters must
    keep them (league unknown ≠ not in this league); a concrete team filter
    still excludes them; the sentinel itself works as a team filter."""
    from charts import player_frame
    from data import MULTI_TEAM
    al = player_frame(SEASON, SEASON, "Batters", "Qualified", "Qualified", "AL")
    nl = player_frame(SEASON, SEASON, "Batters", "Qualified", "Qualified", "NL")
    assert (al["Team"] == MULTI_TEAM).any()
    assert (nl["Team"] == MULTI_TEAM).any()
    only = player_frame(SEASON, SEASON, "Batters", "Qualified", "Qualified",
                        MULTI_TEAM)
    assert len(only) and (only["Team"] == MULTI_TEAM).all()
    nyy = player_frame(SEASON, SEASON, "Batters", "Qualified", "Qualified",
                       "NYY")
    assert len(nyy) and not (nyy["Team"] == MULTI_TEAM).any()


def test_team_display_handles_traded():
    from data import team_display, MULTI_TEAM
    assert team_display(MULTI_TEAM) == "2TM"
    assert team_display(MULTI_TEAM, full=True) == "Multiple teams"
    assert team_display("LAD") == "LAD"
    assert team_display("LAD", full=True) == "Los Angeles Dodgers"
    assert team_display("") == "—"


def test_season_slider_seeded_marks_and_per_year_step():
    """The layout must ship real year marks (no flash of Dash's auto '2k'
    labels before the callback runs) and a step of 1 so dragging can land on
    any year, not just the decade marks."""
    from components import _year_scrubber
    from data import config
    slider = _year_scrubber(2024, 2024).children[1]
    assert slider.step == 1
    assert slider.marks
    first = config["start_year"]
    assert str(first) in str(slider.marks[first])
    assert all("2k" not in str(v) for v in slider.marks.values())


def test_fetch_team_passes_month_through(monkeypatch):
    """Live split selection must reach the team roll-up too."""
    import fangraphs_api as fa
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append(params["month"])
        return _FakeResp([
            {"Team": "NYY", "PA": 600, "wOBA": 0.350, "HR": 30},
            {"Team": "NYY", "PA": 400, "wOBA": 0.300, "HR": 10},
        ])

    monkeypatch.setattr(fa.requests, "get", fake_get)
    out = fa.fetch_team("bat", 2026, month=fa.LIVE_SPLIT)
    assert seen == [fa.LIVE_SPLIT]
    assert list(out.Team) == ["NYY"] and out.HR.iloc[0] == 40  # rolled up
