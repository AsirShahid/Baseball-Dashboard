"""Baseball Savant (Statcast) season stats, stored beside FanGraphs' columns.

Source: Savant's custom leaderboard CSV, one file per season (2015 on, the
Statcast era) for hitters and one for pitchers, every player with a plate
appearance (min=0):
  https://baseballsavant.mlb.com/leaderboard/custom?year=2024&type=batter&min=0&selections=...&csv=true

Rows join FanGraphs players by MLBAM id (FanGraphs' xMLBAMID, Savant's
player_id). Savant gives rates and a few counts; every rate here is stored with
the counts it is built from (zone pitches, swings, whiffs, batted balls, ...),
so a span, a career or the whole league is rebuilt exactly, the way Savant
computes its own "Player" and "MLB" rows. Savant's MLB row on a player page is
the league over 2015 to now; this site shows each season's league instead.

    python -m pipeline.savant --root /data/savant     # download what is missing or stale
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("savant")

FIRST = 2015
KINDS = {"bat": "batter", "pit": "pitcher"}
SELECTIONS = (
    "pa", "ab", "batted_ball", "pitch_count", "barrel", "exit_velocity_avg", "launch_angle_avg",
    "sweet_spot_percent", "hard_hit_percent", "xba", "xslg", "woba", "xwoba", "xwobacon",
    "in_zone", "out_zone", "in_zone_swing", "out_zone_swing", "swing_percent", "whiff_percent",
    "oz_swing_percent", "oz_contact_percent", "iz_contact_percent", "z_swing_percent",
    "edge_percent", "meatball_percent", "meatball_swing_percent", "sprint_speed",
    "k_percent", "bb_percent",
)
URL = ("https://baseballsavant.mlb.com/leaderboard/custom?year={year}&type={type}&filter=&min=0"
       "&selections={sel}&chart=false&x=pa&y=pa&r=no&chartType=beeswarm&sort=pa&sortDir=desc&csv=true")
USER_AGENT = "baseball.asir.dev (personal stats site; Savant season CSVs, at most once a day)"
TIMEOUT = (15, 120)
STALE_HOURS = 20

# Shown stats (Savant's names; keys prefixed "sv" where FanGraphs has a stat of the
# same name with another definition, e.g. its Zone% uses Baseball Info Solutions' zone).
SHOWN = ("Sweet-Spot%", "xwOBAcon", "svZone%", "svZ-Swing%", "svZ-Contact%", "Chase%", "ChaseContact%",
         "Edge%", "svSwing%", "Whiff%", "Meatball%", "MeatballSwing%", "Sprint")
PITCHER_SHOWN = ("xAVG", "xSLG", "xwOBA")      # FanGraphs has these for hitters only
# Counts each shown stat is rebuilt from (stored, never offered as stats).
PARTS = ("svPA", "svAB", "svPit", "svIZ", "svOZ", "svIZSw", "svOZSw", "svIZCon", "svOZCon", "svWhiff",
         "svEdge", "svMB", "svMBSw", "svBBE", "svSweet", "svXWcon", "svXH", "svXTB", "svXW", "svSpW", "svSpSum")


def _num(text) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return float("nan")


def _z(x):
    return 0.0 if x != x else x


def parts_of(r: dict) -> dict:
    """The counts for one Savant row (a NaN rate with no denominator counts as 0)."""
    g = lambda k: _num(r.get(k))
    pa, ab, pit, bbe = g("pa"), g("ab"), g("pitch_count"), g("batted_ball")
    iz, oz, izsw, ozsw = g("in_zone"), g("out_zone"), g("in_zone_swing"), g("out_zone_swing")
    swings = _z(izsw) + _z(ozsw)
    pct = lambda k: g(k) / 100
    mb = _z(pct("meatball_percent")) * _z(pit)
    sprint = g("sprint_speed")
    return {
        "svPA": _z(pa), "svAB": _z(ab), "svPit": _z(pit), "svIZ": _z(iz), "svOZ": _z(oz),
        "svIZSw": _z(izsw), "svOZSw": _z(ozsw),
        "svIZCon": _z(pct("iz_contact_percent")) * _z(izsw), "svOZCon": _z(pct("oz_contact_percent")) * _z(ozsw),
        "svWhiff": _z(pct("whiff_percent")) * swings, "svEdge": _z(pct("edge_percent")) * _z(pit),
        "svMB": mb, "svMBSw": _z(pct("meatball_swing_percent")) * mb,
        "svBBE": _z(bbe), "svSweet": _z(pct("sweet_spot_percent")) * _z(bbe),
        "svXWcon": _z(g("xwobacon")) * _z(bbe), "svXH": _z(g("xba")) * _z(ab), "svXTB": _z(g("xslg")) * _z(ab),
        "svXW": _z(g("xwoba")) * _z(pa),
        "svSpW": _z(pa) if sprint == sprint else 0.0, "svSpSum": sprint * _z(pa) if sprint == sprint else 0.0,
    }


def rates(c: dict, pitching: bool) -> dict:
    """Shown stats from summed parts (arrays or floats); NaN where a denominator is 0."""
    def div(a, b):
        a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)
    swings = np.asarray(c["svIZSw"]) + np.asarray(c["svOZSw"])
    out = {
        "Sweet-Spot%": div(c["svSweet"], c["svBBE"]), "xwOBAcon": div(c["svXWcon"], c["svBBE"]),
        "svZone%": div(c["svIZ"], c["svPit"]), "svZ-Swing%": div(c["svIZSw"], c["svIZ"]),
        "svZ-Contact%": div(c["svIZCon"], c["svIZSw"]), "Chase%": div(c["svOZSw"], c["svOZ"]),
        "ChaseContact%": div(c["svOZCon"], c["svOZSw"]), "Edge%": div(c["svEdge"], c["svPit"]),
        "svSwing%": div(swings, c["svPit"]), "Whiff%": div(c["svWhiff"], swings),
        "Meatball%": div(c["svMB"], c["svPit"]), "MeatballSwing%": div(c["svMBSw"], c["svMB"]),
        "xAVG": div(c["svXH"], c["svAB"]), "xSLG": div(c["svXTB"], c["svAB"]), "xwOBA": div(c["svXW"], c["svPA"]),
    }
    if not pitching:
        out["Sprint"] = div(c["svSpSum"], c["svSpW"])
    return out


def path_for(root: Path, kind: str, year: int) -> Path:
    return root / f"{kind}-{year}.csv.gz"


def fetch(root: Path, now: dt.datetime | None = None, session=None, delay: float = 1.0) -> bool:
    """Download each season that is missing, the current season when its copy is
    older than 20 hours, and every season once a month (Savant revises its
    expected stats now and then). True if any file changed."""
    import requests
    session = session or requests.Session()
    now = now or dt.datetime.now()
    root.mkdir(parents=True, exist_ok=True)
    meta_path = root / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        meta = {}
    month = now.strftime("%Y-%m")
    full = meta.get("full") != month
    changed = False
    for year in range(FIRST, now.year + 1):
        for kind, kind_name in KINDS.items():
            path = path_for(root, kind, year)
            age = (time.time() - path.stat().st_mtime) / 3600 if path.exists() else float("inf")
            current = year >= now.year - (1 if now.month < 3 else 0)
            if path.exists() and not full and not (current and age > STALE_HOURS):
                continue
            url = URL.format(year=year, type=kind_name, sel=",".join(SELECTIONS))
            response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            response.raise_for_status()
            text = response.content.decode("utf-8-sig")
            header = text.split("\n", 1)[0]
            if "player_id" not in header or "out_zone_swing" not in header:
                raise ValueError(f"{url}: unexpected content")
            rows = text.count("\n")
            if rows < (2 if year == now.year else 200):
                raise ValueError(f"{url}: only {rows} rows")
            old = gzip.open(path, "rt", encoding="utf-8").read() if path.exists() else None
            if old != text:
                tmp = path.with_suffix(".tmp")
                with gzip.open(tmp, "wt", encoding="utf-8", newline="") as handle:
                    handle.write(text)
                tmp.replace(path)
                changed = True
            else:
                path.touch()
            time.sleep(delay)
    if full:
        meta["full"] = month
    meta_path.write_text(json.dumps(meta))
    return changed


class Savant:
    """Savant rows by kind, season and MLBAM id."""

    def __init__(self, root: Path | None):
        self.rows: dict = {"bat": {}, "pit": {}}
        if root is None or not root.exists():
            return
        for kind in KINDS:
            for path in sorted(root.glob(f"{kind}-*.csv.gz")):
                try:
                    year = int(path.name.split("-")[1].split(".")[0])
                except ValueError:
                    continue
                with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                    self.rows[kind][year] = {r["player_id"]: r for r in csv.DictReader(handle) if r.get("player_id")}

    @property
    def loaded(self) -> bool:
        return any(self.rows[k] for k in self.rows)

    def season_columns(self, kind: str, year: int, ident: list) -> dict:
        """Shown stats and their counts for each row of a FanGraphs season file."""
        by_id = self.rows.get(kind, {}).get(year)
        if not by_id:
            return {}
        pitching = kind == "pit"
        n = len(ident)
        parts = {p: np.zeros(n) for p in PARTS}
        found = np.zeros(n, dtype=bool)
        for i, r in enumerate(ident):
            row = by_id.get(str(r.get("mlbam") or ""))
            if row is None:
                continue
            found[i] = True
            for k, v in parts_of(row).items():
                parts[k][i] = v
        if not found.any():
            return {}
        shown = rates(parts, pitching)
        keep = SHOWN + (PITCHER_SHOWN if pitching else ())
        out = {k: np.where(found, shown[k], np.nan).astype(np.float32) for k in keep if k in shown}
        out.update({k: np.where(found, v, np.nan).astype(np.float32) for k, v in parts.items()})
        return out

    def league_parts(self, kind: str, year: int) -> dict | None:
        """Every player's counts added up: the league for that season (AL and NL)."""
        by_id = self.rows.get(kind, {}).get(year)
        if not by_id:
            return None
        total = {p: 0.0 for p in PARTS}
        for row in by_id.values():
            for k, v in parts_of(row).items():
                total[k] += v
        return total


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args(argv)
    print(json.dumps({"changed": fetch(a.root)}))


if __name__ == "__main__":
    main()
