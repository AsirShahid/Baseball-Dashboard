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


def test_leaderboard_drops_all_nan_axis():
    """An all-NaN axis carries no signal: x/y all-NaN yields an empty board
    (not 30 teams tied at 50), and an all-NaN Z is dropped from the count so
    the leaderboard agrees with the chart on how many axes are live."""
    from callbacks import _leaderboard_rows
    # 'xwOBA' has no team-level data (all NaN) in the shipped CSVs.
    rows, n = _leaderboard_rows(SEASON, "Batting", "Pitching", "xwOBA", "ERA",
                                "Batting", None)
    assert rows == [] and n == 0
    # A valid 2-axis board with an all-NaN Z must stay a 2-axis board.
    rows, n = _leaderboard_rows(SEASON, "Batting", "Pitching", "wRC+", "ERA",
                                "Batting", "xwOBA")
    assert len(rows) == 10 and n == 2


def test_render_team_degenerate_z_falls_back_to_2d():
    """A Z axis with no team-level data must not force a collapsed 3D plot."""
    from charts import render_team
    import plotly.graph_objects as go
    fig, eyebrow, _ = render_team(SEASON, False, "Batting", "Pitching",
                                  "wRC+", "ERA", True, True, False,
                                  "Batting", "xwOBA")
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


def test_backfill_skips_duplicate_names():
    from live_stats import backfill_null_columns
    df = pd.DataFrame({"Name": ["Will Smith", "Will Smith", "Aaron Judge"],
                       "X": [None, None, None]})
    fb = pd.DataFrame({"Name": ["Will Smith", "Will Smith", "Aaron Judge"],
                       "X": [1, 2, 3]})
    out = backfill_null_columns(df, fb)
    assert out.loc[out.Name == "Aaron Judge", "X"].iloc[0] == 3
    assert out.loc[out.Name == "Will Smith", "X"].isna().all()


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
