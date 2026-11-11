"""Site tests on real FanGraphs data for 1955 and 2024 (tests/fixtures, gzip CSVs).

The fixtures are built into a database once per run; no network is used.
"""
from __future__ import annotations

import gzip
import math
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

JUDGE, OHTANI, SOTO, CHISHOLM, SKUBAL = 15640, 19755, 20123, 20454, 22267


@pytest.fixture(scope="session")
def data_root(tmp_path_factory):
    from pipeline import build
    out = tmp_path_factory.mktemp("data")
    build.build(FIXTURES, FIXTURES, out, FIXTURES / "bwar", FIXTURES / "savant")
    return out


@pytest.fixture(scope="session")
def app(data_root):
    from web import create_app
    app = create_app(data_root)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def con(data_root):
    c = sqlite3.connect(data_root / "baseball.sqlite")
    c.row_factory = sqlite3.Row
    return c


def page(client, url, status=200):
    response = client.get(url)
    assert response.status_code == status, (url, response.status_code)
    return response.get_data(as_text=True)


def rows(html):
    return len(re.findall(r'<tr data-name="', html))


# ---------- the build ----------

def test_build_stores_every_season_and_stat(con):
    kinds = dict(con.execute("SELECT kind, COUNT(DISTINCT season) FROM rows GROUP BY kind").fetchall())
    assert kinds == {"bat": 3, "pit": 3, "tbat": 2, "tpit": 2, "sbat": 2, "spit": 2,   # 3 = 1955, 2024, career
                     "lbat": 2, "lpit": 2}                                           # league averages
    stats = {r[0] for r in con.execute("SELECT stat FROM catalog WHERE kind = 'bat'")}
    assert {"wRC+", "WAR", "Barrel%", "O-Swing%", "AVG"} <= stats and "playerid" not in stats
    assert con.execute("SELECT fmt FROM catalog WHERE kind='bat' AND stat='K%'").fetchone()[0] == "pct1"
    assert con.execute("SELECT lower FROM catalog WHERE kind='pit' AND stat='ERA'").fetchone()[0] == 1
    assert con.execute("SELECT counting FROM catalog WHERE kind='bat' AND stat='HR'").fetchone()[0] == 1


def test_innings_are_true_innings(app):
    from web import db
    with app.app_context():
        t = db.table("pit", 2024, 2024, ("IP", "ER", "ERA"))
        i = next(i for i, r in enumerate(t.ident) if r["pid"] == SKUBAL)
        assert t.cols["IP"][i] == pytest.approx(192.0)
        # A notation value like 177.2 must mean 177 2/3.
        from pipeline.build import true_innings
        assert true_innings(np.array([177.2]))[0] == pytest.approx(177 + 2 / 3)


def test_records_and_franchise_codes(con):
    nyy = con.execute("SELECT w, l, league, division FROM team_seasons WHERE season=2024 AND team='NYY'").fetchone()
    assert tuple(nyy) == (94, 68, "AL", "AL East")
    bro = con.execute("SELECT name, league, division FROM team_seasons WHERE season=1955 AND team='BRO'").fetchone()
    assert tuple(bro) == ("Brooklyn Dodgers", "NL", None)
    # The 1955 Milwaukee Braves share FanGraphs' MIL code with the Brewers; teamid splits them.
    assert con.execute("SELECT COUNT(*) FROM team_seasons WHERE season=1955 AND team='MLN'").fetchone()[0] == 1


# ---------- qualifying ----------

def ids(kind, season):
    with gzip.open(FIXTURES / f"qualified_{kind}_stats" / f"{season}.ids.gz", "rt") as h:
        return {int(float(x)) for x in h.read().split()}


@pytest.mark.parametrize("season", [1955, 2024])
def test_qualified_matches_fangraphs_lists(app, season):
    from web import queries
    with app.app_context():
        for kind, name in (("bat", "batting"), ("pit", "pitching")):
            lines, _ = queries.lines_for(kind, season, season, ("WAR",), min_mode="n", min_value=0)
            assert {l["pid"] for l in lines if l["qualified"]} == ids(name, season), (kind, season)


def test_need_is_rounded_like_mlb(app):
    from web import queries
    with app.app_context():
        assert queries.need_for("bat", 2024, 2024, 162) == 502
        assert queries.need_for("bat", 2024, 2024, 60) == 186
        assert queries.need_for("bat", 2024, 2024, 156) == 484
        assert queries.need_for("pit", 2024, 2024, 162) == 162
        # Over a span: FanGraphs' 1,000 PA, or the sum of the season minimums when that is lower
        # (the fixtures hold only 1955 and 2024).
        both = math.floor(3.1 * (queries.season_games(1955) + 162) + 0.5)
        assert queries.need_for("bat", 1955, 2024) == min(1000, both) and both < 1000


def test_counts_have_no_minimum_but_rates_do(app):
    from web import queries
    with app.app_context():
        assert queries.rule_of("HR", "bat") is None and queries.rule_of("WAR", "pit") is None
        assert queries.rule_of("AVG", "bat") == "q" and queries.rule_of("ERA", "pit") == "q"
        boards = {b["stat"]: b for b in queries.leaders(2024)["bat"]}
        assert boards["HR"]["rows"][0]["pid"] == JUDGE and boards["HR"]["rows"][0]["HR"] == 58
        assert not boards["HR"]["qualified"] and boards["AVG"]["qualified"]
        assert all(l["qualified"] for l in boards["AVG"]["rows"])


# ---------- spans ----------

def test_span_rebuilds_ratios_from_totals(app):
    from web import db
    with app.app_context():
        one = db.table("bat", 2024, 2024, ("H", "AB", "AVG", "HR", "PA"))
        both = db.table("bat", 1955, 2024, ("H", "AB", "AVG", "HR", "PA", "wRC+"))
        i = next(i for i, r in enumerate(both.ident) if r["pid"] == JUDGE)
        j = next(j for j, r in enumerate(one.ident) if r["pid"] == JUDGE)
        assert both.cols["HR"][i] == one.cols["HR"][j] == 58      # only 2024 in the fixtures
        assert both.cols["AVG"][i] == pytest.approx(both.cols["H"][i] / both.cols["AB"][i])
        # A traded player's span row keeps one line, not one per club.
        assert sum(1 for r in both.ident if r["pid"] == CHISHOLM) == 1


def test_career_rows_match_their_seasons(con, app):
    from web import db
    with app.app_context():
        career = db.table("bat", 1955, 2024, ("HR", "PA"))   # whole history in the fixtures -> season 0
        i = next(i for i, r in enumerate(career.ident) if r["pid"] == SOTO)
        assert career.cols["HR"][i] == 41 and career.ident[i]["team"] == "NYY"


# ---------- pages ----------

ROUTES = ["/", "/standings", "/standings?season=1955", "/players", "/players?kind=pit",
          "/players?mode=statcast", "/players?kind=pit&mode=discipline", "/players?season=1955&to=2024",
          "/players?min=0&team=NYY", "/players?league=AL&pos=SS", "/players?kind=pit&pos=RP&min=20",
          "/teams", "/teams?kind=pit&mode=advanced", "/teams?season=1955&to=2024",
          f"/player/{JUDGE}", f"/player/{OHTANI}", f"/player/{SKUBAL}", f"/player/{CHISHOLM}",
          f"/player/{JUDGE}?bmode=statcast", "/team/NYY", "/team/BRO?season=1955", "/team/NYY?season=1955",
          f"/compare?p={JUDGE},{OHTANI}", "/compare", "/chart", "/about", "/healthz"]


@pytest.mark.parametrize("url", ROUTES)
def test_pages_render(client, url):
    html = page(client, url)
    assert "Traceback" not in html


def test_players_default_is_qualified(client, app):
    from web import queries
    html = page(client, "/players?season=2024")
    assert rows(html) == len(ids("batting", 2024))
    assert '<option value="q" selected>Qualified</option>' in html
    everyone = page(client, "/players?season=2024&min=0")
    assert rows(everyone) > 3 * rows(html)
    assert html.index('data-name="Aaron Judge"') < html.index('data-name="Juan Soto"')   # WAR order


def test_traded_player_shows_both_clubs(client):
    html = page(client, f"/player/{CHISHOLM}")
    assert "2+ teams" in html and 'class="stint child' in html
    assert html.count('/team/NYY?season=2024') >= 1 and html.count('/team/MIA?season=2024') >= 1
    roster = page(client, "/team/NYY?season=2024")
    assert 'data-name="Jazz Chisholm Jr."' in roster and "traded" in roster


def test_player_page_marks_qualified_seasons_and_leads(client):
    html = page(client, f"/player/{JUDGE}")
    assert '<span class="qmark"' in html
    row = html[html.index('data-v="2024"'):]
    row = row[:row.index("</tr>")]
    assert '<td data-v="58.0" class=" lead">58</td>' in row        # 58 HR led the majors
    assert '<td data-v="0.0" class=" lead">' not in row             # 0 CS is not a lead


def test_standings_groups(client):
    html = page(client, "/standings?season=2024")
    for title in ("AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"):
        assert f">{title}</h2>" in html
    old = page(client, "/standings?season=1955")
    assert ">American League</h2>" in old and ">National League</h2>" in old


def test_team_redirects_across_relocation(client):
    response = client.get("/team/LAD?season=1955")
    assert response.status_code == 302 and "/team/BRO?season=1955" in response.headers["Location"]


def test_search(client):
    found = client.get("/api/search?q=judge").get_json()
    assert found[0]["label"] == "Aaron Judge" and found[0]["url"] == f"/player/{JUDGE}"
    teams = client.get("/api/search?q=yankees").get_json()
    assert any(t["kind"] == "team" and t["code"] == "NYY" for t in teams)


def test_old_share_links_open_the_chart(client):
    response = client.get("/?view=player&player_type=Pitchers&p_x_stat=FIP&p_y_stat=ERA&season=2024&p_trend=true")
    assert response.status_code == 301
    location = response.headers["Location"]
    assert "/chart?" in location and "kind=pit" in location and "x=FIP" in location and "trend=1" in location


# ---------- chart api ----------

def test_chart_players_and_teams(client):
    data = client.get("/api/chart?view=player&kind=bat&x=wRC%2B&y=WAR&season=2024").get_json()
    assert data["count"] == len(ids("batting", 2024)) and data["axes"]["x"]["rule"] == "q"
    counts = client.get("/api/chart?view=player&kind=bat&x=HR&y=SB&season=2024").get_json()
    assert counts["count"] > data["count"]          # two counts: no minimum
    teams = client.get("/api/chart?view=team&x=pit:ERA&y=bat:wRC%2B&season=2024").get_json()
    assert teams["count"] == 30 and teams["axes"]["x"]["better"] is False


def test_chart_split_era_and_3d(client):
    split = client.get("/api/chart?view=player&x=OBP&y=SLG&season=1955&to=2024&split=season").get_json()
    seasons = {r[3] for r in split["rows"]}
    assert seasons == {1955, 2024}
    era = client.get("/api/chart?view=player&x=OBP&y=SLG&season=2024&era=1").get_json()
    xs = [r[5] for r in era["rows"]]
    assert 0 <= min(xs) and max(xs) <= 100 and era["axes"]["x"]["fmt"] == "pctl"
    cube = client.get("/api/chart?view=player&x=wRC%2B&y=WAR&z=SB&season=2024").get_json()
    assert cube["axes"]["z"]["key"] == "SB" and all(r[7] is not None for r in cube["rows"])


def test_chart_says_when_a_stat_has_no_data(client):
    data = client.get("/api/chart?view=player&x=Barrel%25&y=WAR&season=1955").get_json()
    assert "2024" in data["error"]


# ---------- formatting ----------

def test_formats():
    from web.fmt import fmt, ip_notation
    assert fmt(0.2634, "avg") == ".263" and fmt(1.043, "avg") == "1.043"
    assert fmt(0.243, "pct1") == "24.3%" and fmt(192.0, "d1", "IP") == "192.0"
    assert ip_notation(177 + 2 / 3) == "177.2" and fmt(None) == ""
    assert fmt(float("nan"), "d2") == ""


# ---------- follow-ups from the logo chat (2026-11-11) ----------

def test_historic_names_leagues_and_colors():
    from pipeline import teams as T
    assert T.team_name("CPI", 1890) == "Chicago Pirates" and T.league_name("CPI", 1890) == "Players' League"
    assert T.team_name("PIT", 1885) == "Pittsburg Alleghenys" and T.league("PIT", 1885) is None
    assert T.team_name("PIT", 1895) == "Pittsburgh Pirates" and T.league("PIT", 1895) == "NL"
    assert T.team_name("BSN", 1875) == "Boston Red Stockings" and T.league_name("BSN", 1875) == "National Association"
    assert T.team_name("CWH", 1915) == "Chicago Whales" and T.league_name("CWH", 1914) == "Federal League"
    assert T.league_name("HG", 1932) == "East-West League" and T.league_name("HG", 1940) == "Negro National League II"
    assert T.team_name("CLE", 1948) == "Cleveland Indians" and T.team_name("NYY", 2024) == "New York Yankees"
    assert T.color("TRO").lower() == "#1e7b3a" and T.color("NYY") == T.TEAM_COLORS["NYY"]


def test_negro_and_federal_league_logos():
    from pipeline import teams as T
    for code, season in (("HG", 1931), ("KCM", 1942), ("CWH", 1914), ("BEG", 1940), ("SLT", 1915)):
        path = T.logo(code, season)
        assert path and (T.LOGO_DIR / path).is_file(), (code, season, path)
    assert T.logo("HG", 1920) is None            # nothing before the dated logo
    sources = __import__("json").loads((T.LOGO_DIR / "eras" / "historic_sources.json").read_text())
    assert all(v["source_page"].startswith("https://") and v["license"] for v in sources.values())


def test_minimum_ladder_matches_fangraphs(client):
    from web import views
    assert len(views.LADDER) + 1 == 62 and views.LADDER[-1] == 10000
    html = page(client, "/players?kind=bat&season=2024&min=2750")
    assert 'value="2750" selected' in html and "Other number" in html
    assert "At least 2,750 PA." in html
    span = page(client, "/players?kind=bat&season=1955&to=2024&min=2750")
    assert "At least 2,750 PA over 1955&ndash;2024." in span
    html = page(client, "/players?kind=bat&season=2024")
    assert "Qualified: 502+ PA (3.1 per team game)." in html


def test_player_percentiles(app, client):
    from web import queries
    with app.app_context():
        p = queries.percentiles(JUDGE, "bat", 2024)
    assert p["qualified"] and p["pool"] > 100
    by = {r["col"]["key"]: r["pct"] for g in p["groups"] for r in g["rows"]}
    assert by["WAR"] >= 99 and by["wRC+"] >= 99 and 20 < by["K%"] < 50   # 24.3% K: below average, lower is better
    with app.app_context():
        s = queries.percentiles(SKUBAL, "pit", 2024)
    by = {r["col"]["key"]: r["pct"] for g in s["groups"] for r in g["rows"]}
    assert by["ERA"] >= 95 and by["K%"] >= 90
    html = page(client, f"/player/{JUDGE}")
    assert "Percentile ranks" in html and "qualified AL and NL hitters in 2024" in html


def test_pre_1954_spans_keep_obp():
    """No sacrifice flies before 1954: Ruth's 1920-21 OBP is (H+BB+HBP)/(AB+BB+HBP)."""
    from pipeline import aggregate
    cols = {"AB": np.array([458.0, 540.0]), "PA": np.array([616.0, 693.0]), "H": np.array([172.0, 204.0]),
            "1B": np.array([73.0, 85.0]), "2B": np.array([36.0, 44.0]), "3B": np.array([9.0, 16.0]),
            "HR": np.array([54.0, 59.0]), "BB": np.array([150.0, 145.0]), "HBP": np.array([3.0, 4.0]),
            "SF": np.array([np.nan, np.nan]), "SO": np.array([80.0, 81.0]),
            "OBP": np.array([0.532, 0.512]), "SLG": np.array([0.847, 0.846]), "OPS": np.array([1.379, 1.358]),
            "BABIP": np.array([0.366, 0.373])}
    _keys, _first, out = aggregate.group_rows(np.array([1, 1]), cols, pitching=False)
    assert math.isclose(out["OBP"][0], (376 + 295 + 7) / (998 + 295 + 7), rel_tol=1e-9)
    assert not np.isnan(out["OPS"][0]) and not np.isnan(out["BABIP"][0])


# ---------- era-adjusted percentiles ----------

def _chart(client, **kw):
    from urllib.parse import urlencode
    data = client.get("/api/chart?" + urlencode(kw)).get_json()
    assert "error" not in data, data
    return [dict(zip(data["fields"], r)) for r in data["rows"]]


def test_era_percentile_matches_hand_calculation(client, app):
    from web import queries
    rows = _chart(client, view="player", kind="bat", x="OPS", y="WAR", season=2024, era=1)
    judge = next(r for r in rows if r["id"] == JUDGE)
    with app.app_context():
        lines, _ = queries.lines_for("bat", 2024, 2024, ("OPS",), min_mode="n", min_value=1)
    pool = np.sort([l["OPS"] for l in lines if l["qualified"]])
    mine = next(l["OPS"] for l in lines if l["pid"] == JUDGE)
    want = (np.searchsorted(pool, mine, "left") + np.searchsorted(pool, mine, "right")) / 2 / len(pool) * 100
    assert math.isclose(judge["x"], want, abs_tol=1e-3)


def test_era_filters_do_not_change_the_pool(client):
    base = {r["id"]: r["x"] for r in _chart(client, view="player", kind="bat", x="OPS", y="WAR", season=2024, era=1)}
    for f in ({"team": "NYY"}, {"pos": "OF"}, {"league": "AL"}):
        rows = _chart(client, view="player", kind="bat", x="OPS", y="WAR", season=2024, era=1, **f)
        assert rows and all(math.isclose(r["x"], base[r["id"]], abs_tol=1e-6) for r in rows if r["id"] in base), f


def test_era_span_is_weighted_mean_of_seasons(client):
    split = _chart(client, view="player", kind="bat", x="OPS", y="WAR", season=1955, to=2024, era=1, split="season", min=0)
    comb = _chart(client, view="player", kind="bat", x="OPS", y="WAR", season=1955, to=2024, era=1, min=0)
    for pid in {r["id"] for r in comb}:
        seasons = [r for r in split if r["id"] == pid and r["x"] is not None]
        if not seasons:
            continue
        want = sum(r["x"] * r["w"] for r in seasons) / sum(r["w"] for r in seasons)
        got = next(r["x"] for r in comb if r["id"] == pid)
        assert math.isclose(got, want, abs_tol=0.01), pid


def test_league_groups():
    from pipeline import teams as T
    assert T.league_group("NYY", 1932) == T.league_group("BRO", 1932) == "MLB"
    assert T.league_group("HG", 1932) == "East-West League"
    assert T.league_group("CWH", 1915) == "Federal League"
    assert T.league_group("CPI", 1890) == "Players' League" and T.league_group("BSN", 1890) == "MLB"


# ---------- fWAR and bWAR ----------

def test_bwar_matches_baseball_reference(app, con):
    from web import db
    with app.app_context():
        t = db.table("bat", 2024, 2024, ("WAR", "bWAR"))
        idx = {r["pid"]: i for i, r in enumerate(t.ident)}
        assert math.isclose(t.cols["bWAR"][idx[JUDGE]], 10.90, abs_tol=0.005)
        assert math.isclose(t.cols["bWAR"][idx[CHISHOLM]], 1.40 + 1.52, abs_tol=0.005)   # two stints summed
        assert abs(t.cols["WAR"][idx[JUDGE]] - t.cols["bWAR"][idx[JUDGE]]) > 0.05          # two different stats
        p = db.table("pit", 2024, 2024, ("bWAR",))
        assert math.isclose(p.cols["bWAR"][[r["pid"] for r in p.ident].index(SKUBAL)], 6.66, abs_tol=0.005)
        s = db.table("sbat", 2024, 2024, ("bWAR",))
        stints = {r["team"]: s.cols["bWAR"][i] for i, r in enumerate(s.ident) if r["pid"] == CHISHOLM}
        assert math.isclose(stints["MIA"], 1.40, abs_tol=0.005) and math.isclose(stints["NYY"], 1.52, abs_tol=0.005)
    share = con.execute("SELECT COUNT(*) FROM players WHERE bwar IS NOT NULL").fetchone()[0] / \
        con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert share > 0.95


def test_war_is_labelled_fwar(client):
    html = page(client, "/players?kind=bat&season=2024")
    assert ">fWAR<" in html and ">bWAR<" in html
    player = page(client, f"/player/{JUDGE}")
    assert "career fWAR" in player and "10.9</b> bWAR" in player
    assert "fWAR and bWAR" in page(client, "/about")
    data = client.get("/api/chart?view=player&kind=bat&x=bWAR&y=WAR&season=2024").get_json()
    assert data["axes"]["y"]["label"] == "fWAR" and data["axes"]["x"]["label"] == "bWAR"


# ---------- player page: spans, career percentiles, summary ----------

def test_player_span_row_and_percentiles(client, app):
    from web import queries
    html = page(client, f"/player/{JUDGE}?from=1955&to=2024&bmode=advanced")
    assert 'class="total spanrow fixed"' in html and ">Clear</a>" in html
    assert 'button type="button" class="yr" data-season="2024"' in html
    assert '<option value="span" selected>' in html               # the span drives the percentile panel
    with app.app_context():
        span = queries.player_span(JUDGE, "bat", "standard", 2024, 2024)
        season = queries.percentiles(JUDGE, "bat", 2024)
        same = queries.percentiles(JUDGE, "bat", 2024, 2024)
        both = queries.percentiles(JUDGE, "bat", 1955, 2024)   # the fixtures hold 1955 and 2024 only
    assert span["values"]["HR"] == 58 and span["qualified"]
    assert season == same
    assert both["season"] is None and (both["lo"], both["hi"]) == (1955, 2024)
    assert both["need"] == 1000 or both["need"] < 1000          # FanGraphs' multi-season cut
    html = page(client, f"/player/{JUDGE}?pseason=career")
    assert '<option value="career" selected>Career</option>' in html and "qualified line over the same seasons" in html


def test_player_summary_counts_games_in_every_mode(client):
    html = page(client, f"/player/{JUDGE}?bmode=advanced")
    assert "PA · 0 G" not in html and re.search(r"PA · \d{2,3} G", html)


def test_team_chart_defaults_to_adjusted_pitching(client):
    from web import charts
    assert charts.DEFAULTS["team"] == ("pit:ERA+", "bat:wRC+")       # both park and league adjusted, 100 = average
    data = client.get("/api/chart?view=team&x=pit:ERA%2B&y=bat:wRC%2B&season=2024").get_json()
    assert data["axes"]["x"]["better"] is True


def test_era_plus_from_baseball_reference(app, con):
    """ERA+ = 100 * ER_lg / ER from Baseball-Reference's WAR file; teams add up
    their pitchers' parts. Skubal 2024 is 174 on his Baseball-Reference page."""
    from web import db
    with app.app_context():
        p = db.table("pit", 2024, 2024, ("ERA+", "ERA"))
        i = [r["pid"] for r in p.ident].index(SKUBAL)
        assert math.isclose(p.cols["ERA+"][i], 173.52, abs_tol=0.01)
        career = db.table("pit", 1871, 2026, ("ERA+",))
        j = [r["pid"] for r in career.ident].index(SKUBAL)
        assert math.isclose(career.cols["ERA+"][j], 173.52, abs_tol=0.01)    # one season in the fixtures
        t = db.table("tpit", 2024, 2024, ("ERA+", "ERA-"))
        by = {r["team"]: k for k, r in enumerate(t.ident)}
        assert math.isclose(t.cols["ERA+"][by["DET"]], 114.9, abs_tol=0.1)
        both = [(t.cols["ERA+"][k], t.cols["ERA-"][k]) for k in range(len(t.ident)) if not np.isnan(t.cols["ERA+"][k])]
        assert len(both) == 30
        assert all(abs(plus - 10000 / minus) < 12 for plus, minus in both)    # close to FanGraphs, different park factors
    assert con.execute("SELECT name, lower FROM catalog WHERE kind='pit' AND stat='ERA+'").fetchone()[1] == 0
    assert con.execute("SELECT COUNT(*) FROM catalog WHERE stat IN ('ERlg', 'bER')").fetchone()[0] == 0


def test_bwar_names_with_accents_are_repaired():
    from pipeline import bwar
    assert bwar.fix_text("David G\u00c3\u00b3mez") == "David G\u00f3mez"
    assert bwar.fix_text("Ra\u00c3\u00bal \u00c3\u0081lvarez") == "Ra\u00fal \u00c1lvarez"
    assert bwar.fix_text("Jos\u00e9 Abreu") == "Jos\u00e9 Abreu"           # already right: unchanged
    assert bwar.norm(bwar.fix_text("Juan Padr\u00c3\u00b3n")) == bwar.norm("Juan Padr\u00f3n")


def test_bwar_surname_fallback_stays_within_the_club():
    from pipeline import bwar
    b = bwar.BWar(None)
    b.loaded = True
    rows = [{"name_common": "Latimer", "year_ID": "1921", "team_ID": "ABC", "player_ID": "lat01", "mlb_ID": "818555",
             "IPouts": "173", "WAR": "0.4", "ER_lg": "30.0", "ERA_plus": "120"},
            {"name_common": "John Smith", "year_ID": "1921", "team_ID": "ABC", "player_ID": "smi01", "mlb_ID": "1",
             "IPouts": "30", "WAR": "0.1", "ER_lg": "5.0", "ERA_plus": "100"},
            {"name_common": "Joe Smith", "year_ID": "1921", "team_ID": "ABC", "player_ID": "smi02", "mlb_ID": "2",
             "IPouts": "30", "WAR": "0.1", "ER_lg": "5.0", "ERA_plus": "100"}]
    b._load("pit", rows)
    hit = b._find("pit", 1921, None, "(Unknown) Latimer", "ABC", 57.0)
    assert hit and abs(hit[0][2] - 0.4) < 1e-9 and abs(hit[0][4] - 25.0) < 1e-9     # bER = 100 * 30 / 120
    assert b._find("pit", 1921, None, "(Unknown) Latimer", "COB", 57.0) is None      # another club: no match
    assert b._find("pit", 1921, None, "(Unknown) Latimer", "ABC", 5.0) is None       # 5 IP vs 57.2: a namesake
    assert b._find("pit", 1921, None, "(Unknown) Latimer", "ABC") is None            # no innings to check
    assert b._find("pit", 1921, None, "(Unknown) Smith", "ABC", 10.0) is None        # two Smiths: ambiguous


# ---------- Baseball Savant and league averages ----------

def test_savant_stats_match_savant(app):
    """Judge 2024 on baseballsavant.com: Chase% 22.0... values come straight from
    Savant's CSV; spans are rebuilt from counts, so one season equals itself."""
    from web import db
    with app.app_context():
        t = db.table("bat", 2024, 2024, ("Chase%", "Whiff%", "Sweet-Spot%", "xwOBAcon", "svZone%", "Sprint", "Barrel/PA"))
        i = [r["pid"] for r in t.ident].index(JUDGE)
        assert t.cols["Chase%"][i] > 0 and abs(t.cols["Chase%"][i] - 0.2) < 0.06
        assert 0.25 < t.cols["Whiff%"][i] < 0.40 and t.cols["xwOBAcon"][i] > 0.5 and 26 < t.cols["Sprint"][i] < 29
        span = db.table("bat", 1955, 2024, ("Chase%", "Whiff%", "xwOBAcon"))
        j = [r["pid"] for r in span.ident].index(JUDGE)
        for stat in ("Chase%", "Whiff%", "xwOBAcon"):
            assert abs(span.cols[stat][j] - t.cols[stat][i]) < 1e-4      # rebuilt from counts: same season, same value
        p = db.table("pit", 2024, 2024, ("xwOBA", "Whiff%", "Chase%"))
        k = [r["pid"] for r in p.ident].index(SKUBAL)
        assert 0.2 < p.cols["xwOBA"][k] < 0.3 and p.cols["Whiff%"][k] > 0.25


def test_league_rows(app, con):
    from web import queries
    with app.app_context():
        lg = queries.league_season("bat", 2024, "MLB", ("AVG", "K%", "wRC+", "HR", "Chase%", "Whiff%", "EV"))
        assert lg["wRC+"] == 100 and "HR" not in lg                         # index stats are 100; counts are not shown
        assert 0.23 < lg["AVG"] < 0.26 and 0.20 < lg["K%"] < 0.25
        assert 0.26 < lg["Chase%"] < 0.31 and 0.23 < lg["Whiff%"] < 0.28 and 87 < lg["EV"] < 90
        al = queries.league_season("bat", 2024, "AL", ("AVG",))
        assert al and abs(al["AVG"] - lg["AVG"]) < 0.01
        assert queries.league_season("bat", 1955, "MLB", ("AVG",))["AVG"] > 0.24
        pit = queries.league_season("pit", 2024, "MLB", ("ERA", "ERA+", "xwOBA"))
        assert 3.5 < pit["ERA"] < 4.5 and pit["ERA+"] == 100 and 0.29 < pit["xwOBA"] < 0.34
        both = queries.league_over("bat", ((1955, "MLB"), (2024, "MLB")), ("AVG", "K%", "wRC+"))
        assert both["wRC+"] == 100
        assert lg["K%"] > both["K%"] > queries.league_season("bat", 1955, "MLB", ("K%",))["K%"]
        assert queries.league_label("Negro National League II") == "NN2" and queries.league_label("Negro Leagues") != "NL"
    hidden = [r[0] for r in con.execute("SELECT stat FROM catalog WHERE stat GLOB 'sv[A-Z]*'")]
    assert hidden and all(stat.endswith("%") for stat in hidden)            # the counts are never offered


def test_league_rows_on_pages(client):
    html = page(client, f"/player/{JUDGE}?bmode=savant")          # one season in the fixtures: one MLB row
    assert html.count('class="lgrow fixed"') == 1 and 'lgrow child every' not in html
    assert ">Chase%<" in html and ">Whiff%<" in html and ">28.5%<" in html      # 2024 MLB chase rate
    board = page(client, "/players?kind=bat&season=2024&mode=statcast")
    assert 'class="lgrow fixed"' in board and "MLB average" in board
    teams = page(client, "/teams?kind=pit&season=2024")
    assert "MLB average" in teams


def test_savant_percentiles_only_in_statcast_era(app):
    from web import queries
    with app.app_context():
        now = queries.percentiles(JUDGE, "bat", 2024)
        keys = {r["col"]["key"] for g in now["groups"] for r in g["rows"]}
        assert "Chase%" in keys and "O-Swing%" not in keys
        assert queries._pct_pick(("Chase%", "O-Swing%"), 2014) == "O-Swing%"


def test_team_tables_have_no_savant_columns(client):
    html = page(client, "/teams?kind=bat&season=2024&mode=statcast")
    assert "mode=savant" not in html and "xwOBAcon" not in html and ">Barrel%<" in html
    assert "Chase%" not in page(client, "/teams?kind=bat&season=2024&mode=savant")      # falls back to standard


def test_chart_stat_pickers_are_searchable(client):
    html = page(client, "/chart")
    assert "statpick.js" in html and html.index("statpick.js") < html.index("chart.js")
    assert '<select id="c-x" data-statpick>' in html and '<select id="c-z" data-statpick data-clear>' in html
    assert client.get("/static/statpick.js").status_code == 200


# ---------- stats that start mid-career (plate discipline 2002, Statcast 2015) ----------

def test_partial_coverage_labels_and_ranks(app):
    from web import queries
    with app.app_context():
        assert queries.years(2002, 2004) == "2002\u201304" and queries.years(1998, 2004) == "1998\u20132004"
        assert queries.stat_first("bat", "EV") == 2024 and queries.stat_first("bat", "AVG") == 1955   # fixtures
        assert queries.partial("bat", ("EV", "AVG", "K%"), 1955, 2024) == {"EV": 2024}
        assert queries.partial("bat", ("EV",), 2024, 2024) == {}
        # Over 1955-2024 his EV covers 2024 only and ranks against everyone's 2024 EV.
        span = queries.percentiles(JUDGE, "bat", 1955, 2024)
        one = queries.percentiles(JUDGE, "bat", 2024)
        ev = {r["col"]["key"]: r for g in span["groups"] for r in g["rows"]}["EV"]
        ev1 = {r["col"]["key"]: r for g in one["groups"] for r in g["rows"]}["EV"]
        assert ev["cover"] == "2024" and ev["pct"] == ev1["pct"]
        assert span["cover_notes"] and span["cover_notes"][0]["first"] == 2024 and "EV" in span["cover_notes"][0]["heads"]
        later = queries.partial("bat", [r["col"]["key"] for g in span["groups"] for r in g["rows"]], 1955, 2024)
        assert all(("cover" in r) == (r["col"]["key"] in later) for g in span["groups"] for r in g["rows"])
        # The league line over 1955 and 2024 keeps EV (2024's) instead of dropping it.
        lg = queries.league_over("bat", ((1955, "MLB"), (2024, "MLB")), ("EV", "AVG"))
        assert lg["EV"] == queries.league_season("bat", 2024, "MLB", ("EV",))["EV"] and lg["AVG"]


def test_team_bwar_adds_up_its_players(app, client):
    """Team bWAR = its players' bWAR (traded players by club), as Baseball-Reference
    totals it; 2024 Dodgers hitting 38.2 and Braves pitching 26.1 on BR."""
    from web import db
    with app.app_context():
        for kind in ("bat", "pit"):
            t = db.table("t" + kind, 2024, 2024, ("bWAR",))
            by = {r["team"]: float(t.cols["bWAR"][k]) for k, r in enumerate(t.ident)}
            assert len(by) == 30 and not any(np.isnan(v) for v in by.values())
            p = db.table(kind, 2024, 2024, ("bWAR",))
            assert math.isclose(sum(by.values()), float(np.nansum(p.cols["bWAR"])), abs_tol=0.5)
        hit = db.table("tbat", 2024, 2024, ("bWAR",))
        lad = [float(hit.cols["bWAR"][k]) for k, r in enumerate(hit.ident) if r["team"] == "LAD"][0]
        assert math.isclose(lad, 38.2, abs_tol=0.15)
    html = page(client, "/teams?kind=bat&season=2024")
    assert ">bWAR<" in html


def test_bwar_id_stem_and_club_codes():
    from pipeline import bwar
    assert bwar.stem("George Pearce") == "pearcge"        # BR pearcge01, listed as "George Pierce"
    assert bwar.stem("Ken Griffey Jr.") == "griffke" and bwar.stem("(Unknown) Latimer") == ""
    b = bwar.BWar(None)
    b.stints["pit"] = {("id", "1", 1899): {"x01": [("CHC", 300.0, 2.0, 100.0, 90.0)]}}
    clubs = b.clubs("pit", 1899, [{"team": "CHI", "mlbam": 1}, {"team": "- - -", "mlbam": 1}])
    assert clubs == {"CHI": "CHC"}


def test_league_filter_counts_only_play_in_that_league(app, client):
    """AL or NL shows only play in that league: a player traded across leagues
    counts his stints there; one traded within a league keeps his season line."""
    from web import db, queries
    from pipeline import teams as T
    assert T.in_league("MIL", 1997, "AL") and T.in_league("MIL", 1998, "NL")
    assert T.in_league("HOU", 2012, "NL") and T.in_league("HOU", 2013, "AL")
    assert not T.in_league("KCM", 1943, "NL") and not T.in_league("KCM", 1943, "AL")
    with app.app_context():
        def line(lg, name):
            lines, _ = queries.lines_for("bat", 2024, 2024, ("PA", "AVG"), min_mode="n", min_value=1, league=lg)
            return next((l for l in lines if l["name"] == name), None)
        whole = line("", "Isaac Paredes")           # TBR then CHC: 641 PA
        al, nl = line("AL", "Isaac Paredes"), line("NL", "Isaac Paredes")
        assert whole["team"] == T.MULTI_TEAM and whole["PA"] == 641
        assert (al["team"], al["PA"]) == ("TBR", 429) and (nl["team"], nl["PA"]) == ("CHC", 212)
        assert line("NL", "Randy Arozarena") is None  # TBR then SEA: AL only
        aro = line("AL", "Randy Arozarena")
        assert aro["team"] == T.MULTI_TEAM and aro["PA"] == line("", "Randy Arozarena")["PA"]
        # Over a span the league-only table still adds up every NL club's batters.
        nl_t = db.table("bat", 1955, 2024, ("PA",), "NL")
        nl_teams = db.table("tbat", 1955, 2024, ("PA",), "NL")
        assert math.isclose(float(np.nansum(nl_t.cols["PA"])), float(np.nansum(nl_teams.cols["PA"])), rel_tol=0.002)
    assert "NL play only" in page(client, "/players?league=NL")
    assert "NL seasons only" in page(client, "/teams?league=NL&season=1955&to=2024")
