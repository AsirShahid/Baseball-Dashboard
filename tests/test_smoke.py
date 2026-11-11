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


def _fake_team_load_stats(dir_key, lo, hi=None, group_key="Team", split=False):
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


def test_fmt_stat_negative_decimal():
    from data import fmt_stat
    assert fmt_stat("wOBA", 0.123) == ".123"
    assert fmt_stat("wOBA", -0.123) == "-.123"
    assert fmt_stat("wOBA", float("nan")) == "—"


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


def test_load_stats_range_sums_newly_added_counters():
    """Run-value and batted-ball counters (wRAA, GB) must SUM over a span, not
    get PA-weighted. Regression guard for the COUNTING_STATS omission that read
    them at roughly 1/N of their true total."""
    from data import load_stats
    span = load_stats("team_batting_dir", 2022, 2024)
    seasons = [pd.read_csv(f"team_batting/{y}.csv") for y in (2022, 2023, 2024)]
    checked = 0
    for stat in ("wRAA", "GB", "RAR"):
        if stat not in span.columns or any(stat not in d.columns for d in seasons):
            continue
        want = sum(float(d.loc[d.Team == "LAD", stat].iloc[0]) for d in seasons)
        got = float(span.loc[span.Team == "LAD", stat].iloc[0])
        assert got == pytest.approx(want), stat
        checked += 1
    assert checked, "no newly-added counter present in fixtures to verify"


def test_load_stats_range_recomputes_rate_from_summed_parts():
    """A span's AVG must equal sum(H)/sum(AB), not a PA-weighted average of the
    per-season AVGs (I05/I19)."""
    from data import load_stats
    span = load_stats("team_batting_dir", 2022, 2024)
    seasons = [pd.read_csv(f"team_batting/{y}.csv") for y in (2022, 2023, 2024)]
    h = sum(float(d.loc[d.Team == "LAD", "H"].iloc[0]) for d in seasons)
    ab = sum(float(d.loc[d.Team == "LAD", "AB"].iloc[0]) for d in seasons)
    got = float(span.loc[span.Team == "LAD", "AVG"].iloc[0])
    assert got == pytest.approx(h / ab, rel=1e-6)


def test_load_stats_pitching_range_recomputes_era():
    """Pitching ERA over a span must equal 9*sum(ER)/sum(IP)."""
    from data import load_stats
    span = load_stats("team_pitching_dir", 2022, 2024)
    seasons = [pd.read_csv(f"team_pitching/{y}.csv") for y in (2022, 2023, 2024)]
    er = sum(float(d.loc[d.Team == "LAD", "ER"].iloc[0]) for d in seasons)
    ip = sum(float(d.loc[d.Team == "LAD", "IP"].iloc[0]) for d in seasons)
    got = float(span.loc[span.Team == "LAD", "ERA"].iloc[0])
    assert got == pytest.approx(9 * er / ip, rel=1e-6)


def test_aggregate_team_recomputes_avg_from_sums():
    """aggregate_team must rebuild AVG from summed H/AB, not PA-weight it: a
    high-walk, low-AB hitter otherwise drags the team AVG away from sum(H)/sum(AB)."""
    from fangraphs_api import aggregate_team
    toy = pd.DataFrame({
        "Team": ["A", "A"],
        "PA":  [700, 100],
        "AB":  [600, 50],           # player 2 walks a lot: PA >> AB
        "H":   [180, 25],
        "AVG": [0.300, 0.500],
    })
    agg = aggregate_team(toy, "bat")
    assert agg.H[0] == 205 and agg.AB[0] == 650
    assert agg.AVG[0] == pytest.approx(205 / 650)   # 0.315, not 0.325 (PA-weighted)


def test_load_stats_pct_weight_column_as_stat_does_not_crash():
    """Era-adjusting the weight column itself (PA for batters) must not raise —
    regression for the duplicate weight column that hit a TypeError in
    _aggregate_span (I01)."""
    from data import load_stats_pct
    out = load_stats_pct("team_batting_dir", 2022, 2024, ["PA"])
    assert not out.empty and "PA" in out.columns
    assert "__weight__" not in out.columns          # private weight col dropped
    vals = pd.to_numeric(out["PA"], errors="coerce").dropna()
    assert len(vals) and vals.between(0, 100).all()  # percentile-scaled, finite


def test_current_year_is_dynamic():
    """current_year() tracks the calendar rather than an import-time constant (I09)."""
    import datetime as _dt
    import data
    assert data.current_year() >= _dt.date.today().year
    assert data.current_year() >= data._CURRENT_YEAR_PIN
    assert data.season_list()[0] == data.current_year()
    assert data.season_list()[-1] == 1871


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
    # Unknown / out-of-range player: a message, not a blank panel.
    msg = _player_detail(10 ** 12, SEASON, SEASON, "Batters",
                         "Qualified", "Qualified", "All Teams")
    assert "No qualified seasons in 2024" in " ".join(_texts(msg))


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


def test_modern_team_codes_registered():
    """FanGraphs codes the Nationals WSN (every season) and the Athletics ATH
    from 2025; both must be first-class — colors, logo, division, full name —
    or they render gray, unclickable, and invisible to division filters."""
    from data import (TEAM_COLORS, TEAM_COLOR_ALT, TEAM_LOGO_MAP,
                      TEAM_DIVISION, TEAM_FULL_NAME, team_in_league)
    for code in ("WSN", "ATH"):
        assert code in TEAM_COLORS and code in TEAM_COLOR_ALT
        assert code in TEAM_LOGO_MAP and code in TEAM_FULL_NAME
    assert TEAM_DIVISION["WSN"] == "NL East"
    assert TEAM_DIVISION["ATH"] == "AL West"
    assert team_in_league("ATH", "AL", 2025)
    assert team_in_league("WSN", "NL", 2024)
    # The old AL Senators (WAS) are not the Nationals and predate divisions.
    assert TEAM_FULL_NAME["WAS"] == "Washington Senators"
    assert "WAS" not in TEAM_DIVISION


def test_league_membership_is_year_aware():
    """Franchises that switched leagues resolve by season: Brewers AL 1970–97,
    Astros NL through 2012, Senators AL 1901–71 (NL in the 1890s)."""
    from data import team_in_league
    assert team_in_league("MIL", "AL", 1980) and not team_in_league("MIL", "NL", 1980)
    assert team_in_league("MIL", "NL", 2024) and not team_in_league("MIL", "AL", 2024)
    assert team_in_league("MIL", "NL", 1955)   # Milwaukee Braves
    assert team_in_league("HOU", "NL", 2005) and not team_in_league("HOU", "AL", 2005)
    assert team_in_league("HOU", "AL", 2024)
    assert team_in_league("WAS", "AL", 1955) and not team_in_league("WAS", "NL", 1955)
    assert team_in_league("WAS", "NL", 1895)
    assert team_in_league("BAL", "NL", 1895) and team_in_league("BAL", "AL", 1955)
    assert not team_in_league("BAL", "AL", 1885)   # American Association years
    # Stable franchises are unaffected, with or without a year.
    assert team_in_league("NYY", "AL", 1927)
    assert team_in_league("MIL", "NL") and team_in_league("HOU", "AL")


def test_al_filter_1955_chart_includes_senators():
    """Chart-level 1955 AL: WAS (Senators) and KCA belong; BRO (NL) does not.
    Before the year-aware fix WAS was treated as the modern NL Nationals."""
    from charts import render_team
    fig, *_ = render_team(1955, False, "Batting", "Pitching", "WAR", "ERA",
                          False, False, False, "Batting", None, "dark", "AL")
    teams = set(fig.data[0].text)
    assert "WAS" in teams and "KCA" in teams
    assert "BRO" not in teams and "MIL" not in teams   # Braves were NL


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
    # Only the final point of each path is labeled, with the team code —
    # but every point carries [Team, Season] customdata so any point on the
    # path click-opens the right detail panel.
    for t in fig.data:
        assert t.text[-1] and not any(t.text[:-1])
        assert all(row[0] == t.text[-1] for row in t.customdata)
        assert [int(row[1]) for row in t.customdata] == [2022, 2023, 2024]


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

    # A search must not shrink the export: the chart still plots everyone
    # (non-matches dimmed), so the export carries a Matched flag instead.
    df, fname = _export_frame("player", SEASON, None, None, None, None, None,
                              None, "All Teams", False, "Batters",
                              "WAR", "wRC+", None, "Qualified", "Qualified",
                              "All Teams", "judge", False)
    assert len(df) > 1 and "Matched" in df.columns
    assert df.loc[df["Matched"], "Name"].str.contains("Judge").all()
    assert int(df["Matched"].sum()) >= 1
    # Nothing to export -> (None, None), not an exception.
    df, fname = _export_frame("player", SEASON, None, None, None, None, None,
                              None, "All Teams", False, "Batters",
                              None, None, None, "Qualified", "Qualified",
                              "All Teams", "", False)
    assert df is None and fname is None


def test_composite_rank_missing_data_is_nan_not_average():
    """An entity with no data on any axis must come out NaN, not a fake
    league-average 50 that seats it mid-leaderboard; an entity missing one
    axis is scored on the axes it has."""
    from charts import compute_composite_rank
    x = pd.Series([1.0, 2.0, np.nan])
    y = pd.Series([2.0, 1.0, np.nan])
    comp = compute_composite_rank((x, True), (y, True))
    assert np.isnan(comp.iloc[2])
    y_part = pd.Series([2.0, np.nan, 1.0])
    comp2 = compute_composite_rank((x, True), (y_part, True))
    assert not np.isnan(comp2.iloc[1])


def test_leaderboard_era_mode_agrees_with_chart():
    """With era-adjusted axes on, the board must rank the same within-season
    percentile frames the chart plots — over a span, aggregate-then-rank on
    raw values can order teams differently."""
    from callbacks import _leaderboard_rows, _player_leaderboard_rows
    from charts import compute_composite_rank, rank_items
    from data import load_stats_pct

    rows, n = _leaderboard_rows([2022, 2024], "Batting", "Pitching", "wRC+",
                                "ERA", "Batting", None, "All Teams", era=True)
    assert len(rows) == 10 and n == 2
    # Recompute #1 straight from the era percentile frames.
    xd = load_stats_pct("team_batting_dir", 2022, 2024, ["wRC+"])
    yd = load_stats_pct("team_pitching_dir", 2022, 2024, ["ERA"])
    xs = pd.Series(xd["wRC+"].values, index=xd["Team"])
    ys = pd.Series(yd["ERA"].values, index=yd["Team"]).reindex(xs.index)
    comp = compute_composite_rank(*rank_items((xs, "wRC+", False),
                                              (ys, "ERA", True)))
    assert rows[0]["team"] == comp.idxmax()

    prows, pn = _player_leaderboard_rows([2022, 2024], "Batters", "WAR",
                                         "wRC+", None, "Qualified",
                                         "Qualified", "All Teams", era=True)
    assert len(prows) == 10 and pn == 2


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


def test_fetch_team_uses_native_team_split(monkeypatch):
    """fetch_team must request FanGraphs' team leaderboard (team=0,ts) — the
    only split that attributes traded players' production to each club — pass
    the month through, and strip the player-identity junk from team rows."""
    import fangraphs_api as fa
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append((params["team"], params["month"]))
        return _FakeResp([
            {"Team": "NYY", "Name": "<a>Some Player</a>", "Age": 29,
             "PA": 6200, "wOBA": 0.330, "HR": 240},
            {"Team": "BOS", "Name": "<a>Other Player</a>", "Age": 27,
             "PA": 6100, "wOBA": 0.320, "HR": 190},
        ])

    monkeypatch.setattr(fa.requests, "get", fake_get)
    out = fa.fetch_team("bat", 2026, month=fa.LIVE_SPLIT)
    assert seen == [(fa.TEAM_SPLIT, fa.LIVE_SPLIT)]
    assert list(out.Team) == ["NYY", "BOS"]           # rows kept as-is
    assert "Name" not in out.columns and "Age" not in out.columns


def test_fetch_team_falls_back_to_player_aggregation(monkeypatch):
    """When the team split returns nothing, fetch_team must still produce team
    rows by aggregating the player leaderboard (the pre-ts behaviour)."""
    import fangraphs_api as fa
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append(params["team"])
        if params["team"] == fa.TEAM_SPLIT:
            return _FakeResp([])                       # team split empty
        return _FakeResp([
            {"Team": "NYY", "PA": 600, "wOBA": 0.350, "HR": 30},
            {"Team": "NYY", "PA": 400, "wOBA": 0.300, "HR": 10},
        ])

    monkeypatch.setattr(fa.requests, "get", fake_get)
    out = fa.fetch_team("bat", 1905)
    assert fa.TEAM_SPLIT in seen and "0" in seen
    assert list(out.Team) == ["NYY"] and out.HR[0] == 40
    assert out.wOBA[0] == pytest.approx(0.330)         # PA-weighted
    assert list(out.Team) == ["NYY"] and out.HR.iloc[0] == 40  # rolled up


# ── Per-season range view (split) ─────────────────────────────────────────────

def test_team_frame_split_keeps_each_season():
    """Per-season mode: one row per team-season, values straight from that
    season's CSV, not the span roll-up."""
    from charts import team_frame
    df, _is3d, err = team_frame(2019, 2021, "Batting", "Pitching", "wRC+", "ERA",
                                split=True)
    assert err is None
    assert set(df["Season"]) == {2019, 2020, 2021}
    assert not df.duplicated(["Team", "Season"]).any()
    b = pd.read_csv("team_batting/2020.csv")
    p = pd.read_csv("team_pitching/2020.csv")
    row = df[(df.Team == "LAD") & (df.Season == 2020)].iloc[0]
    assert row["_x"] == pytest.approx(b[b.Team == "LAD"]["wRC+"].iloc[0])
    assert row["_y"] == pytest.approx(p[p.Team == "LAD"]["ERA"].iloc[0])
    combined, *_ = team_frame(2019, 2021, "Batting", "Pitching", "wRC+", "ERA")
    assert len(df) == 3 * len(combined)


def test_team_frame_split_single_season_matches_combined():
    from charts import team_frame
    a, *_ = team_frame(2024, 2024, "Batting", "Pitching", "wRC+", "ERA", split=True)
    b, *_ = team_frame(2024, 2024, "Batting", "Pitching", "wRC+", "ERA")
    assert "Season" not in a.columns
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_team_frame_split_era_pctl_in_range():
    from charts import team_frame
    df, *_ = team_frame(2019, 2021, "Batting", "Pitching", "wRC+", "ERA",
                        era=True, split=True)
    assert df["_x"].between(0, 100).all() and df["_y"].between(0, 100).all()
    assert set(df["Season"]) == {2019, 2020, 2021}


def test_render_team_split_labels_and_click_data():
    from charts import render_team
    for logos, rank in ((False, False), (False, True), (True, False)):
        fig, eyebrow, _ = render_team([2019, 2021], logos, "Batting", "Pitching",
                                      "wRC+", "ERA", True, True, rank,
                                      "Batting", None, split=True)
        tr = fig.data[0]
        assert "LAD ’20" in list(tr.text)
        i = list(tr.text).index("LAD ’20")
        assert tr.customdata[i][0] == "LAD" and int(tr.customdata[i][1]) == 2020
        assert "PER SEASON" in eyebrow


def test_render_team_split_ignored_with_trajectory():
    from charts import render_team
    _fig, eyebrow, _ = render_team([2019, 2021], False, "Batting", "Pitching",
                                   "wRC+", "ERA", True, True, False, "Batting",
                                   None, traj=True, split=True)
    assert "TRAJECTORY" in eyebrow and "PER SEASON" not in eyebrow


def test_leaderboard_split_ranks_team_seasons():
    from callbacks import _leaderboard_rows
    rows, n = _leaderboard_rows([2019, 2024], "Batting", "Pitching", "wRC+",
                                "ERA", "Batting", None, split="season")
    assert len(rows) == 10 and n == 2
    for r in rows:
        code, _, yr = r["ref"].partition("|")
        assert 2019 <= int(yr) <= 2024
        assert r["team"] == code and r["name"].startswith(yr + " ")
    # Combined mode still ranks bare team codes.
    rows_c, _ = _leaderboard_rows([2019, 2024], "Batting", "Pitching", "wRC+",
                                  "ERA", "Batting", None, split="combined")
    assert all("|" not in r["ref"] for r in rows_c)


def test_player_frame_split_and_render():
    from charts import player_frame, render_player, OUTLIER_LABELS
    df = player_frame(2019, 2021, "Batters", "Qualified", "Qualified",
                      "All Teams", split=True)
    assert set(df["Season"]) == {2019, 2020, 2021}
    assert df["IDfg"].duplicated().any()          # same player, many seasons
    assert not df.duplicated(["IDfg", "Season"]).any()
    fig, eyebrow, _ = render_player([2019, 2021], "Batters", "WAR", "wRC+",
                                    "Qualified", "Qualified", "All Teams",
                                    False, None, split=True,
                                    label_mode="outliers")
    labels = [t for tr in fig.data for t in tr.text if t]
    assert len(labels) == OUTLIER_LABELS       # per player-season, not per player
    assert all("’" in t for t in labels)
    assert "PER SEASON" in eyebrow
    cd = fig.data[0].customdata[0]
    assert len(cd) >= 3 and 2019 <= int(cd[2]) <= 2021   # [IDfg, _row, Season, …]


def test_player_leaderboard_split_refs():
    from callbacks import _player_leaderboard_rows
    rows, _ = _player_leaderboard_rows([2019, 2021], "Batters", "WAR", "wRC+",
                                       None, "Qualified", "Qualified",
                                       "All Teams", split="season")
    assert rows
    for r in rows:
        idfg, _, yr = r["ref"].partition("|")
        assert int(idfg) and 2019 <= int(yr) <= 2021
        assert r["name"].startswith(yr + " ")


def test_export_split_has_season_rows():
    from callbacks import _export_frame
    out, fname = _export_frame("team", [2019, 2021], "Batting", "Pitching",
                               "wRC+", "ERA", "Batting", None, "All Teams",
                               False, "Batters", None, None, None, "Qualified",
                               "Qualified", "All Teams", "", False,
                               split="season")
    assert "Season" in out.columns and "_per-season" in fname
    assert set(out["Season"]) == {2019, 2020, 2021}
    out_p, fname_p = _export_frame("player", [2019, 2021], "Batting", "Pitching",
                                   None, None, "Batting", None, "All Teams",
                                   False, "Batters", "WAR", "wRC+", None,
                                   "Qualified", "Qualified", "All Teams", "",
                                   False, split="season")
    assert "Season" in out_p.columns and "_per-season" in fname_p



# ── Min PA / IP ladder (FanGraphs steps) and career-scale thresholds ─────────

def test_min_threshold_ladder_matches_fangraphs():
    from data import MIN_PA_LIST, MIN_IP_LIST, snap_threshold
    assert MIN_PA_LIST[0] == "Qualified" and MIN_IP_LIST == MIN_PA_LIST
    nums = MIN_PA_LIST[1:]
    assert nums == sorted(set(nums)) and nums[0] == 0 and nums[-1] == 10000
    for v in (1, 5, 10, 250, 300, 700, 1000, 1500, 3000, 5000, 10000):
        assert v in nums
    assert 260 not in nums and 1050 not in nums      # FanGraphs' coarser steps
    assert snap_threshold("Qualified") == "Qualified"
    # Custom numbers are kept as typed (a shared ?min_pa=2750 reopens at 2750).
    assert snap_threshold("320") == 320 and snap_threshold(3250) == 3250
    assert snap_threshold(25000) == 20000 and snap_threshold("0") == 0
    assert snap_threshold("junk") == "Qualified" and snap_threshold(-5) == "Qualified"


@pytest.fixture
def career_data(tmp_path, monkeypatch):
    """Three synthetic seasons in throwaway all-batting / all-pitching dirs."""
    import data
    bat, pit = tmp_path / "bat", tmp_path / "pit"
    bat.mkdir(); pit.mkdir()
    # id: PA per season (2001, 2002, 2003). Career totals: 1 → 1200, 2 → 1950,
    # 3 → 350, 4 → 950 (just under a 1,000 cut).
    pa = {1: (400, 400, 400), 2: (650, 650, 650), 3: (350, 0, 0), 4: (500, 450, 0)}
    war = {1: 2.0, 2: 6.0, 3: 1.0, 4: 3.0}
    for i, y in enumerate((2001, 2002, 2003)):
        rows = [dict(IDfg=p, Name=f"B{p}", Team="BOS", PA=v[i], WAR=war[p],
                     **{"wRC+": 100 + p}) for p, v in pa.items() if v[i]]
        pd.DataFrame(rows).to_csv(bat / f"{y}.csv", index=False)
    ip = {1: (200, 200, 200), 2: (150, 150, 150)}      # 600 vs 450 career IP
    for i, y in enumerate((2001, 2002, 2003)):
        rows = [dict(IDfg=p, Name=f"P{p}", Team="BOS", IP=v[i], WAR=p, ERA=3.0 + p)
                for p, v in ip.items()]
        pd.DataFrame(rows).to_csv(pit / f"{y}.csv", index=False)
    monkeypatch.setitem(data.config, "all_batting_dir", str(bat))
    monkeypatch.setitem(data.config, "all_pitching_dir", str(pit))


def test_career_threshold_judged_on_span_total(career_data):
    from charts import player_frame
    # Aggregate view: summed PA >= 1000 keeps players 1 and 2, nobody else.
    agg = player_frame(2001, 2003, "Batters", 1000, "Qualified", "All Teams")
    assert dict(zip(agg["IDfg"], agg["PA"])) == {1: 1200, 2: 1950}
    # Per-season rows: every season of the cohort, none of anyone else.
    per = player_frame(2001, 2003, "Batters", 1000, "Qualified", "All Teams",
                       split=True)
    assert sorted(per["IDfg"]) == [1, 1, 1, 2, 2, 2]
    # Era-adjusted: percentile pool per season is the cohort itself.
    era = player_frame(2001, 2003, "Batters", 1000, "Qualified", "All Teams",
                       pct_stats=["WAR"])
    assert set(era["IDfg"]) == {1, 2}
    assert era.set_index("IDfg").loc[2, "WAR"] == 100.0
    assert era.set_index("IDfg").loc[1, "WAR"] == 50.0
    # Trajectory-style single-season call still uses the whole-range cohort.
    one = player_frame(2002, 2002, "Batters", 1000, "Qualified", "All Teams",
                       cohort_span=(2001, 2003))
    assert sorted(one["IDfg"]) == [1, 2]
    # ...whereas one season on its own cannot reach 1,000 PA.
    assert player_frame(2002, 2002, "Batters", 1000, "Qualified", "All Teams").empty
    # Pitchers use IP the same way (500 > the 300-IP single-season cap).
    pit = player_frame(2001, 2003, "Pitchers", "Qualified", 500, "All Teams",
                       split=True)
    assert sorted(pit["IDfg"]) == [1, 1, 1]


def test_season_scale_threshold_still_per_season(career_data):
    """At or below the single-season cap the threshold keeps judging each
    season's row (unchanged behaviour)."""
    from charts import player_frame
    per = player_frame(2001, 2003, "Batters", 600, "Qualified", "All Teams",
                       split=True)
    assert sorted(per["IDfg"]) == [2, 2, 2]


def test_player_trajectory_with_career_threshold(career_data):
    from charts import render_player
    fig, eyebrow, _ = render_player([2001, 2003], "Batters", "WAR", "wRC+",
                                    1000, "Qualified", "All Teams",
                                    False, None, False, False, "dark",
                                    traj=True)
    assert eyebrow[0] == "TRAJECTORY"
    assert {t.name for t in fig.data} == {"B1", "B2"}
# ── Display precision ────────────────────────────────────────────────────────

@pytest.mark.parametrize("stat,val,want", [
    ("WAR", 11.331730310881184, "11.3"),
    ("wRC+", 219.7835722854021, "220"),
    ("AVG", 0.2630362542364565, ".263"),
    ("OPS", 1.0592, "1.059"),
    ("K%", 0.242897727, "24.3%"),
    ("HR/FB", 0.2142, "21.4%"),
    ("ERA", 2.380863175718908, "2.38"),
    ("SIERA", 4.091316543596715, "4.09"),
    ("PA", 6073.0, "6,073"),
    ("IP", 177.2, "177.2"),
    ("ERA-", 87.4, "87"),
    ("K%+", 112.6, "113"),
    ("WAR/650 PAs", 7.456, "7.5"),
    ("WPA", 6.17204475402832, "6.17"),
    ("EV", 96.23058925128535, "96.2"),
])
def test_fmt_stat_precision(stat, val, want):
    from data import fmt_stat
    assert fmt_stat(stat, val) == want


def test_fmt_stat_era_and_missing():
    from data import fmt_stat
    assert fmt_stat("K%", 73.6, era=True) == "74"   # percentile, not a percent
    assert fmt_stat("WAR", float("nan")) == "—"
    assert fmt_stat("WAR", None) == "—"


def test_player_hover_is_formatted():
    """Plotly Express hover must carry per-stat formats, never a bare %{x}."""
    from charts import render_player
    fig, *_ = render_player([2019, 2021], "Batters", "WAR", "wRC+", "Qualified",
                            "Qualified", "All Teams", False, None)
    ht = fig.data[0].hovertemplate
    assert "%{x:.1f}" in ht and "%{y:,.0f}" in ht
    assert "%{x}" not in ht and "%{y}" not in ht


def test_team_hover_and_mean_labels_formatted():
    from charts import render_team
    fig, *_ = render_team([2019, 2021], False, "Batting", "Batting", "AVG", "K%",
                          True, True, False, "Batting", None)
    ht = fig.data[0].hovertemplate
    assert "%{x:.3f}" in ht and "%{y:.1%}" in ht
    labels = [a.text for a in fig.layout.annotations]
    assert any(t.startswith("avg .2") for t in labels)       # AVG .2xx
    assert any(t.startswith("avg ") and t.endswith("%") for t in labels)
    assert fig.layout.yaxis.tickformat == ".0%"


def test_export_rounded_to_display_precision():
    from callbacks import _export_frame
    out, _ = _export_frame("player", [2019, 2021], "Batting", "Pitching", None,
                           None, "Batting", None, "All Teams", False, "Batters",
                           "WAR", "wRC+", None, "Qualified", "Qualified",
                           "All Teams", "", False)
    assert (out["WAR"].dropna() == out["WAR"].dropna().round(1)).all()
    assert (out["wRC+"].dropna() == out["wRC+"].dropna().round(0)).all()
    out_t, _ = _export_frame("team", 2024, "Batting", "Batting", "AVG", "K%",
                             "Batting", None, "All Teams", False, "Batters",
                             None, None, None, "Qualified", "Qualified",
                             "All Teams", "", False)
    k = out_t["K% (Batting)"]
    assert (k == k.round(3)).all() and k.between(0, 1).all()   # fraction, 1-dp %


@pytest.mark.parametrize("n,want", [(1, "st"), (2, "nd"), (3, "rd"), (4, "th"),
                                    (11, "th"), (12, "th"), (13, "th"),
                                    (21, "st"), (73, "rd"), (91, "st"),
                                    (92, "nd"), (100, "th")])
def test_ordinal_suffix(n, want):
    from components import ordinal_suffix
    assert ordinal_suffix(n) == want


# ── Player panel + span cache ─────────────────────────────────────────────────

def test_span_cache_hits_and_invalidates():
    import data
    from data import load_stats
    data._SPAN_CACHE.clear()
    a = load_stats("qualified_batting_dir", 2019, 2021, group_key="IDfg")
    assert len(data._SPAN_CACHE) == 1
    a["WAR"] = -999.0                         # caller mutation must not leak
    b = load_stats("qualified_batting_dir", 2019, 2021, group_key="IDfg")
    assert (b["WAR"] != -999.0).all()
    # Touching a season file changes the key → rebuilt, not served stale.
    f = os.path.join(data.config["qualified_batting_dir"], "2020.csv")
    st = os.stat(f)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    try:
        load_stats("qualified_batting_dir", 2019, 2021, group_key="IDfg")
        assert len(data._SPAN_CACHE) == 2
    finally:
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_span_rollup_carries_first_last_and_position():
    from data import load_stats
    df = load_stats("qualified_batting_dir", 2019, 2024, group_key="IDfg")
    assert {"_first", "_last", "position", "Bats"} <= set(df.columns)
    assert df["_first"].between(2019, 2024).all()
    assert (df["_first"] <= df["_last"]).all()


def _retired_qualified_batter():
    """A 2019 qualified batter absent from the 2023 and 2024 qualified files."""
    q19 = load_csv("qualified_batting_stats/2019.csv", fetch=False)
    later = set(load_csv("qualified_batting_stats/2023.csv", fetch=False)["IDfg"]) | \
        set(load_csv("qualified_batting_stats/2024.csv", fetch=False)["IDfg"])
    row = q19[~q19["IDfg"].isin(later)].sort_values("PA", ascending=False).iloc[0]
    return int(row["IDfg"]), str(row["Name"])


def _texts(node, out=None):
    """All string children in a Dash component tree."""
    out = [] if out is None else out
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, (list, tuple)):
        for n in node:
            _texts(n, out)
    elif hasattr(node, "children"):
        _texts(node.children, out)
    return out


def test_player_panel_header_shows_player_not_slider_range():
    from callbacks import _player_detail
    idfg, name = _retired_qualified_batter()
    body = _player_detail(idfg, 2019, 2024, "Batters", "Qualified",
                          "Qualified", "All Teams")
    txt = " | ".join(_texts(body))
    assert name in txt
    assert "Bats " in txt                     # handedness in the eyebrow
    assert " PA" in txt and "Age " in txt      # facts line
    # A range with "Qualified" uses full totals (FanGraphs' 1,000 PA rule),
    # so the facts count every season, not only qualified ones.
    assert "qualified season" not in txt and " seasons" in txt
    # The header's season span is the player's own (ends before 2023), and the
    # trajectory covers his seasons rather than an empty 2020–2024 window.
    assert "TRAJECTORY · 2019–" in txt
    assert "2019–2024 · " not in txt.split("TRAJECTORY")[0]


def test_player_panel_single_season_keeps_5yr_trajectory():
    from callbacks import _player_detail
    q = load_csv("qualified_batting_stats/2024.csv", fetch=False)
    idfg = int(q.sort_values("WAR", ascending=False)["IDfg"].iloc[0])
    txt = " | ".join(_texts(_player_detail(idfg, 2024, 2024, "Batters",
                                           "Qualified", "Qualified", "All Teams")))
    assert "5-YEAR TRAJECTORY" in txt and "2024" in txt


def test_detail_loading_placeholder():
    from components import detail_loading
    txt = " | ".join(_texts(detail_loading("Buck Leonard")))
    assert "Loading" in txt and "Buck Leonard" in txt


def test_historical_team_names():
    from data import team_display
    assert team_display("HG", full=True) == "Homestead Grays"
    assert team_display("MON", full=True) == "Montreal Expos"
    assert team_display("ZZZ", full=True) == "ZZZ"          # unknown → code


def test_team_panel_range_uses_team_seasons():
    """Over a range, the team header shows the team's own seasons and the
    trajectory covers them, not the slider bounds."""
    import app  # registers callbacks
    from callbacks import _spark, SPARK_STATS
    from components import detail_body
    sp = [_spark(s, dk, "LAD", 2024, years_in=[2019, 2020, 2021])
          for s, dk in SPARK_STATS]
    assert all(x["years"] == [2019, 2020, 2021] for x in sp if x["values"])
    txt = " | ".join(_texts(detail_body("LAD", "2019–2021 · 3 SEASONS", 70, sp, [],
                                        spark_title="TRAJECTORY · 2019–2021",
                                        foot="Percentiles vs. all teams, 2019–2021 (range totals).")))
    assert "2019–2021 · 3 SEASONS" in txt and "TRAJECTORY · 2019–2021" in txt
    assert "range totals" in txt


def test_span_cache_respects_byte_budget(monkeypatch):
    import data
    from data import load_stats
    data._SPAN_CACHE.clear()
    load_stats("qualified_batting_dir", 2019, 2021, group_key="IDfg")
    one = sum(b for _, b in data._SPAN_CACHE.values())
    assert one > 0
    # Budget fits one roll-up: the next span evicts the first.
    monkeypatch.setattr(data, "_SPAN_CACHE_BYTES", int(one * 1.5))
    load_stats("qualified_batting_dir", 2020, 2022, group_key="IDfg")
    assert len(data._SPAN_CACHE) == 1
    assert sum(b for _, b in data._SPAN_CACHE.values()) <= data._SPAN_CACHE_BYTES
    # Larger than the whole budget → served but not cached.
    monkeypatch.setattr(data, "_SPAN_CACHE_BYTES", 10)
    data._SPAN_CACHE.clear()
    df = load_stats("qualified_batting_dir", 2019, 2021, group_key="IDfg")
    assert not df.empty and len(data._SPAN_CACHE) == 0


# ── IP notation ───────────────────────────────────────────────────────────────

def test_ip_notation_roundtrip():
    from fangraphs_api import ip_to_innings, innings_to_ip, ip_is_notation
    ip = pd.Series([177.2, 192.0, 186.1, 0.1])
    inn = ip_to_innings(ip)
    assert inn.tolist() == pytest.approx([177 + 2 / 3, 192.0, 186 + 1 / 3, 1 / 3])
    assert innings_to_ip(inn).tolist() == pytest.approx(ip.tolist())
    assert innings_to_ip(pd.Series([177 + 2 / 3 + 1 / 3])).tolist() == [178.0]
    assert ip_is_notation(ip) and not ip_is_notation(pd.Series([1363.6, 1105.7]))


def test_aggregate_team_sums_true_innings():
    """Two pitchers at 10.2 and 5.2 IP pitched 16.1 innings (16⅓), not 15.4,
    and ERA is rebuilt on true innings."""
    from fangraphs_api import aggregate_team
    toy = pd.DataFrame({"Team": ["A", "A"], "IP": [10.2, 5.2], "ER": [4, 2],
                        "ERA": [3.38, 3.18]})
    agg = aggregate_team(toy, "pit")
    assert agg.IP[0] == pytest.approx(16.1)
    assert agg.ERA[0] == pytest.approx(9 * 6 / (16 + 1 / 3))


# ── Memory-bounded full-history roll-ups ─────────────────────────────────────

def _span_frames(dir_key, lo, hi):
    from data import load_csv, config
    return [load_csv(f"{config[dir_key]}/{y}.csv", fetch=False) for y in range(lo, hi + 1)]


def test_chunked_rollup_matches_exact():
    """The streamed aggregator must reproduce _aggregate_span (to float32
    precision), including display columns, _first/_last and column order,
    even when every chunk is tiny."""
    from data import _aggregate_span, _aggregate_span_chunked, PLAYER_DISPLAY_COLS
    frames = [f for f in _span_frames("qualified_batting_dir", 2019, 2024) if not f.empty]
    exact = _aggregate_span(pd.concat(frames, ignore_index=True), "IDfg", "PA",
                            PLAYER_DISPLAY_COLS)
    chunked = _aggregate_span_chunked(iter(frames), "IDfg", "PA",
                                      PLAYER_DISPLAY_COLS, chunk_rows=50)
    assert list(chunked.columns) == list(exact.columns)
    a = exact.set_index("IDfg").sort_index()
    b = chunked.set_index("IDfg").sort_index()
    assert list(a.index) == list(b.index)
    num = a.select_dtypes("number").columns
    pd.testing.assert_frame_equal(a[num], b[num].astype(a[num].dtypes.to_dict()),
                                  check_exact=False, rtol=1e-5, atol=1e-6)
    for c in ("Name", "Team", "position", "Bats"):
        if c in a.columns:
            assert (a[c].fillna("") == b[c].fillna("")).all(), c


def test_load_stats_streams_large_spans(monkeypatch):
    """Spans over the disk threshold take the streamed path (no CSV caching)
    and agree with the exact path, rate rebuild included."""
    import data
    from data import load_stats
    data._SPAN_CACHE.clear()
    exact = load_stats("qualified_batting_dir", 2019, 2024, group_key="IDfg")
    data._SPAN_CACHE.clear()
    monkeypatch.setattr(data, "_STREAM_ROWS", 1)
    before = dict(data._CSV_CACHE)
    data._CSV_CACHE.clear(); data._CSV_BYTES.clear()
    streamed = load_stats("qualified_batting_dir", 2019, 2024, group_key="IDfg")
    assert not data._CSV_CACHE                      # read through, not cached
    data._CSV_CACHE.update(before)
    a = exact.set_index("IDfg").sort_index()
    b = streamed.set_index("IDfg").sort_index()
    for c in ("PA", "WAR", "AVG", "OBP", "wRC+", "_first", "_last"):
        assert b[c].values == pytest.approx(a[c].values, rel=1e-5, nan_ok=True), c


def test_csv_cache_byte_budget(monkeypatch):
    import data
    from data import load_csv
    data._CSV_CACHE.clear(); data._CSV_BYTES.clear()
    load_csv(f"{data.config['qualified_batting_dir']}/2019.csv", fetch=False)
    one = sum(data._CSV_BYTES.values())
    monkeypatch.setattr(data, "_CSV_CACHE_BYTES", int(one * 1.5))
    load_csv(f"{data.config['qualified_batting_dir']}/2020.csv", fetch=False)
    assert len(data._CSV_CACHE) == 1
    assert sum(data._CSV_BYTES.values()) <= data._CSV_CACHE_BYTES
    data._CSV_CACHE.clear(); data._CSV_BYTES.clear()


# ── FanGraphs playing-time rules ─────────────────────────────────────────────

def test_span_qualified_min_matches_fangraphs():
    from data import span_qualified_min, team_games
    # Single season: 3.1 PA / 1 IP per team game.
    assert span_qualified_min("PA", 2024, 2024) == pytest.approx(3.1 * team_games(2024))
    assert span_qualified_min("IP", 2024, 2024) == pytest.approx(team_games(2024))
    # Any normal range: FanGraphs' flat 1,000 PA / 300 IP.
    assert span_qualified_min("PA", 2021, 2024) == 1000
    assert span_qualified_min("IP", 2022, 2024) == 300
    # 2020 (60 games) + 2021: capped at the summed single-season minimums
    # instead of FanGraphs' empty board.
    two = span_qualified_min("PA", 2020, 2021)
    assert two == pytest.approx(3.1 * (team_games(2020) + team_games(2021)))
    assert two < 1000


def test_range_qualified_uses_full_totals(career_data, monkeypatch):
    """Qualified over a range keeps players with 1,000+ PA on their full
    totals — including seasons they did not qualify in."""
    import data
    from charts import player_frame
    monkeypatch.setattr(data, "team_games", lambda y: 162.0)
    agg = player_frame(2001, 2003, "Batters", "Qualified", "Qualified", "All Teams")
    assert dict(zip(agg["IDfg"], agg["PA"])) == {1: 1200, 2: 1950}
    # Per-season view keeps per-season qualification (FanGraphs' Split Seasons).
    per = player_frame(2001, 2003, "Pitchers", "Qualified", "Qualified", "All Teams",
                       split=True)
    assert per.empty or "IDfg" in per.columns


def test_restricted_rollup_equals_filtered_full_rollup(career_data):
    """Rolling up only the cohort's rows gives the same numbers as rolling up
    everyone and filtering afterwards."""
    import data
    from data import load_stats
    full = load_stats("all_batting_dir", 2001, 2003, group_key="IDfg")
    cut = load_stats("all_batting_dir", 2001, 2003, group_key="IDfg", min_total=1000)
    want = full[full["PA"] >= 1000].set_index("IDfg").sort_index()
    got = cut.set_index("IDfg").sort_index()
    assert list(got.index) == list(want.index) == [1, 2]
    for c in ("PA", "WAR", "wRC+"):
        assert got[c].values == pytest.approx(want[c].values), c


def test_span_rollup_disk_cache_shared(career_data):
    """A second worker (empty memory cache) loads the roll-up from disk."""
    import data
    from data import load_stats
    a = load_stats("all_batting_dir", 2001, 2003, group_key="IDfg")
    data._SPAN_CACHE.clear()
    calls = []
    real = data._aggregate_span
    data._aggregate_span = lambda *a_, **k: calls.append(1) or real(*a_, **k)
    try:
        b = load_stats("all_batting_dir", 2001, 2003, group_key="IDfg")
    finally:
        data._aggregate_span = real
    assert not calls                                # served from disk
    assert b["PA"].tolist() == a["PA"].tolist()


def test_typed_threshold_options():
    import app  # registers callbacks
    from data import threshold_options, MIN_THRESHOLD_LADDER
    vals = [o["value"] for o in threshold_options(2750)]
    assert vals[0] == "Qualified" and 2750 in vals and vals[1:] == sorted(vals[1:])
    assert [o["value"] for o in threshold_options("Qualified")][1:] == MIN_THRESHOLD_LADDER
    assert threshold_options(3000)[-1]["label"] == "10000"   # plain labels, as FanGraphs


def test_threshold_hint_text():
    import app  # registers callbacks
    from callbacks import _threshold_hint
    def txt(*a):
        return "".join(x if isinstance(x, str) else x.children for x in _threshold_hint(*a))
    one = txt(2024, "Batters", "Qualified", "Qualified", "All Teams", "combined")
    assert "3.1 PA per team game" in one and "players." in one
    rng = txt([2019, 2024], "Batters", "Qualified", "Qualified", "All Teams", "combined")
    assert "1,000+ PA" in rng and "FanGraphs" in rng
    car = txt([2019, 2024], "Batters", 3000, "Qualified", "All Teams", "combined")
    assert "3,000+ PA" in car and "total over 2019–2024" in car
    per = txt([2019, 2024], "Batters", 300, "Qualified", "All Teams", "season")
    assert "in each season" in per


def test_atomic_to_csv_skips_unchanged(tmp_path):
    """Rewriting identical content keeps the mtime (caches stay valid)."""
    import os
    from fangraphs_api import atomic_to_csv
    p = tmp_path / "x.csv"
    df = pd.DataFrame({"a": [1, 2], "b": [0.5, 0.25]})
    assert atomic_to_csv(df, p) is True
    os.utime(p, ns=(1, 1_000_000_000))
    assert atomic_to_csv(df, p) is False and os.stat(p).st_mtime_ns == 1_000_000_000
    assert atomic_to_csv(df.assign(a=[1, 3]), p) is True


def test_float32_keeps_ids_and_order():
    from data import _float32
    df = pd.DataFrame({"Name": ["a"], "IDfg": [1015737.0], "WAR": [1.25], "PA": [500.0]})
    out = _float32(df.copy())
    assert list(out.columns) == list(df.columns)
    assert out["IDfg"].dtype == "float64" and out["WAR"].dtype == "float32"


def test_per_season_view_refuses_huge_pools(career_data, monkeypatch):
    import charts
    from charts import player_frame, render_player
    monkeypatch.setattr(charts, "MAX_SEASON_POINTS", 5)
    df = player_frame(2001, 2003, "Batters", 0, "Qualified", "All Teams", split=True)
    assert df.empty and df.attrs["too_many"] == 9
    _fig, _eb, title = render_player([2001, 2003], "Batters", "WAR", "wRC+", 0,
                                     "Qualified", "All Teams", False, None,
                                     split=True)
    assert "too many to plot" in str(title)
    # A cut that leaves few rows still plots, filtered season by season.
    ok = player_frame(2001, 2003, "Batters", 600, "Qualified", "All Teams", split=True)
    assert sorted(ok["IDfg"]) == [2, 2, 2]

