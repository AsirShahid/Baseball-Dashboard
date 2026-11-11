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
    build.build(FIXTURES, FIXTURES, out)
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
    assert kinds == {"bat": 3, "pit": 3, "tbat": 2, "tpit": 2, "sbat": 2, "spit": 2}   # 3 = 1955, 2024, career
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
    assert "2+ teams" in html and 'class="stint fixed"' in html
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
