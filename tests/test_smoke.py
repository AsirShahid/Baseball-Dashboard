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
