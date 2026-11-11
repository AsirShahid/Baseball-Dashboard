"""Baseball-Reference WAR (bWAR), stored beside FanGraphs WAR (fWAR).

Source: Baseball-Reference's public daily WAR files, one row per player,
season and stint:
  https://www.baseball-reference.com/data/war_daily_bat.txt    position-player WAR
                                                              (and pitchers' hitting)
  https://www.baseball-reference.com/data/war_daily_pitch.txt  pitching WAR

The two WARs share a framework and replacement level (1,000 WAR a season) but
differ in method, most of all for pitchers: FanGraphs builds pitching WAR on
FIP, Baseball-Reference on runs allowed adjusted for the team's defense.

Rows are joined to FanGraphs players by MLBAM id (FanGraphs' xMLBAMID, Baseball-
Reference's mlb_ID). Negro Leagues players have no MLBAM id in either file, so a
player without one is matched by name and season, and by team when two players
share a name. A season with several stints is the sum of its stints; a FanGraphs
stint row takes the Baseball-Reference stint for the same club (or the nearest
in plate appearances or innings).

    python -m pipeline.bwar --root /data/bwar     # download (only when changed)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import unicodedata
from email.utils import formatdate
from pathlib import Path

import numpy as np

log = logging.getLogger("bwar")

URLS = {"bat": "https://www.baseball-reference.com/data/war_daily_bat.txt",
        "pit": "https://www.baseball-reference.com/data/war_daily_pitch.txt"}
FILES = {"bat": "war_daily_bat.txt.gz", "pit": "war_daily_pitch.txt.gz"}
USER_AGENT = "baseball.asir.dev (personal stats site; daily WAR file, at most once a day)"
TIMEOUT = (15, 180)


def fetch(root: Path, session=None) -> bool:
    """Download both files when Baseball-Reference has a newer copy. True if changed."""
    import requests
    session = session or requests.Session()
    root.mkdir(parents=True, exist_ok=True)
    meta_path = root / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        meta = {}
    changed = False
    for kind, url in URLS.items():
        headers = {"User-Agent": USER_AGENT}
        if meta.get(kind) and (root / FILES[kind]).exists():
            headers["If-Modified-Since"] = meta[kind]
        response = session.get(url, headers=headers, timeout=TIMEOUT)
        if response.status_code == 304:
            continue
        response.raise_for_status()
        text = response.text
        if not text.startswith("name_common,") or text.count("\n") < 1000:
            raise ValueError(f"{url}: unexpected content")
        tmp = root / (FILES[kind] + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", newline="") as handle:
            handle.write(text)
        tmp.replace(root / FILES[kind])
        meta[kind] = response.headers.get("Last-Modified") or formatdate(usegmt=True)
        changed = True
        log.info("bWAR %s: %d rows", kind, text.count("\n") - 1)
    meta_path.write_text(json.dumps(meta, indent=1))
    return changed


def norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join("".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").split())


class BWar:
    """Baseball-Reference WAR, looked up for FanGraphs rows."""

    def __init__(self, root: Path | None):
        self.stints = {"bat": {}, "pit": {}}     # (kind) -> {(mlbam|name key, year): {player: [(team, weight, war)]}}
        self.loaded = False
        if root is None:
            return
        for kind in ("bat", "pit"):
            path = root / FILES[kind]
            if not path.exists():
                continue
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                self._load(kind, csv.DictReader(handle))
            self.loaded = True

    def _load(self, kind, reader):
        by = self.stints[kind]
        for r in reader:
            war = r.get("WAR")
            if war in (None, "", "NULL"):
                continue
            try:
                year, value = int(r["year_ID"]), float(war)
                weight = float(r["PA"]) if kind == "bat" else float(r["IPouts"]) / 3
            except (TypeError, ValueError):
                continue
            stint = (r["team_ID"], weight, value)
            mlbam = r.get("mlb_ID")
            if mlbam and mlbam != "NULL":
                by.setdefault(("id", mlbam, year), {}).setdefault(r["player_ID"], []).append(stint)
            by.setdefault(("name", norm(r["name_common"]), year), {}).setdefault(r["player_ID"], []).append(stint)

    def _find(self, kind, year, mlbam, name, team):
        by = self.stints[kind]
        if mlbam:
            hit = by.get(("id", str(mlbam), year))
            return next(iter(hit.values())) if hit else None     # an MLBAM id with no row: no bWAR
        if not name or name.startswith("(Unknown)"):
            return None
        hit = by.get(("name", norm(name), year))
        if not hit:
            return None
        if len(hit) == 1:
            return next(iter(hit.values()))
        same_team = [s for s in hit.values() if any(t == team for t, _w, _v in s)]
        return same_team[0] if len(same_team) == 1 else None

    def season_column(self, kind: str, year: int, ident: list) -> np.ndarray | None:
        """bWAR for each row of a FanGraphs season file (bat or pit)."""
        if not self.loaded:
            return None
        out = np.full(len(ident), np.nan, dtype=np.float32)
        for i, r in enumerate(ident):
            stints = self._find(kind, year, r.get("mlbam"), r.get("name"), r.get("team"))
            if stints:
                out[i] = sum(v for _t, _w, v in stints)
        return out

    def stint_column(self, kind: str, year: int, ident: list, weights: np.ndarray) -> np.ndarray | None:
        """bWAR for each row of a FanGraphs stints file: the Baseball-Reference
        stint for the same club, else the nearest in PA (IP for pitchers)."""
        if not self.loaded:
            return None
        base = "pit" if kind == "spit" else "bat"
        out = np.full(len(ident), np.nan, dtype=np.float32)
        rows_by_pid: dict = {}
        for i, r in enumerate(ident):
            rows_by_pid.setdefault(r.get("pid"), []).append(i)
        for _pid, idx in rows_by_pid.items():
            first = ident[idx[0]]
            stints = self._find(base, year, first.get("mlbam"), first.get("name"), None)
            if not stints:
                continue
            if len(idx) == 1 and len(stints) == 1:
                out[idx[0]] = stints[0][2]
                continue
            pairs = []
            for i in idx:
                w = 0.0 if np.isnan(weights[i]) else float(weights[i])
                for k, (team, bw, value) in enumerate(stints):
                    pairs.append(((0 if team == ident[i].get("team") else 1), abs(w - bw), i, k))
            pairs.sort()
            used_i, used_k = set(), set()
            for _same, _gap, i, k in pairs:
                if i in used_i or k in used_k:
                    continue
                used_i.add(i); used_k.add(k)
                out[i] = stints[k][2]
        return out


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args(argv)
    print(json.dumps({"changed": fetch(a.root)}))


if __name__ == "__main__":
    main()
