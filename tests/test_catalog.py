"""Every FanGraphs column in the stat picker has words, not a repeat of its code.

tests/fixtures/stat_codes.txt lists the 579 distinct columns in the built catalog
(batting and pitching) on 2026-11-27. A column FanGraphs adds later is not listed
here; the build logs it ("columns with no description") so it gets words in
pipeline/catalog.py (EXTRA or a family in _family).
"""
import re
from pathlib import Path

from pipeline import catalog

CODES = Path(__file__).parent.joinpath("fixtures", "stat_codes.txt").read_text().split()


def test_every_catalog_column_has_a_description():
    bare = [s for s in CODES if catalog.describe(s) == s]
    assert not bare, f"no description for {bare}"


def test_no_description_just_repeats_its_code():
    for s in CODES:
        words = re.sub(r"[^a-z0-9]", "", catalog.describe(s).lower())
        assert words != re.sub(r"[^a-z0-9]", "", s.lower()), s


def test_pitch_type_family_examples():
    d = catalog.describe
    assert d("pfxKN-Z").startswith("Knuckleball vertical movement")
    assert d("pfxwSLO/C").startswith("Slider excl. sweepers pitch value per 100")
    assert d("piwSB").startswith("Screwball pitch value")
    assert d("piCS%").startswith("Slow curve usage")
    assert d("pfxaaFA").startswith("Four-seam fastball arm angle")
    assert d("pfxspCU").startswith("Curveball incl. slurves spin rate")


def test_statcast_zone_family_examples():
    d = catalog.describe
    assert d("scH-Swing%").startswith("Heart swing rate")
    assert d("scSO-Contact%").startswith("Shadow-out contact rate")
    assert d("scW-Zone%").startswith("Waste rate")


def test_rule_violation_and_challenge_examples():
    d = catalog.describe
    assert d("rPPTV").startswith("Pitcher pitch timer violation runs")
    assert d("DSV").startswith("Defensive shift violations")
    assert d("AsCReview").startswith("ABS challenges this player made as a catcher")
    assert "Total Balls by Violation" in d("EBV") and "shift" in d("EBV")


def test_stuff_and_pitchingbot_examples():
    d = catalog.describe
    assert d("sp_l_FF").startswith("Four-seam fastball Location+")
    assert d("pb_c_KC").startswith("PitchingBot knuckle curve command grade")
