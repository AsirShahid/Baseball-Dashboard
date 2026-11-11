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
import re
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


def _num(text) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return float("nan")


# What each Baseball-Reference stint carries, after (team, weight):
#   bWAR, ERlg (earned runs a park- and league-average pitcher allows in the
#   same innings) and bER (earned runs, as ERA+ = 100 * ER_lg / ER).
FIELDS = {"bat": ("bWAR",), "pit": ("bWAR", "ERlg", "bER")}


def fix_text(name: str) -> str:
    """Baseball-Reference's files store accented names encoded twice
    ("GÃ³mez" for "Gómez"); undo it, or those players never match by name."""
    if name and ("\u00c3" in name or "\u00c2" in name):
        for enc in ("latin-1", "cp1252"):
            try:
                return name.encode(enc).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    return name


def norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join("".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").split())


def stem(name: str) -> str:
    """Baseball-Reference's player id without its number: the first five letters
    of the surname and two of the first name ("George Pearce" -> "pearcge", BR's
    pearcge01, listed as "George Pierce"). Ids keep the spelling a player was first
    entered under, so they still match where the two sources now spell him apart."""
    words = [re.sub(r"[^a-z]", "", w) for w in norm(name.replace("(Unknown)", "")).split()]
    words = [w for w in words if w and w not in ("jr", "sr", "ii", "iii")]
    if len(words) < 2:
        return ""
    return words[-1][:5] + words[0][:2]


def _agree(theirs: float, mine: float) -> bool:
    return abs(theirs - mine) <= max(3.0, 0.35 * max(theirs, mine))


class BWar:
    """Baseball-Reference WAR, looked up for FanGraphs rows."""

    def __init__(self, root: Path | None):
        self.stints = {"bat": {}, "pit": {}}     # (kind) -> {(mlbam|name key, year): {player: [(team, weight, war)]}}
        self.rosters = {"bat": {}, "pit": {}}    # (kind) -> {(year, team): {surname: {player}}}
        self.by_player = {"bat": {}, "pit": {}}  # (kind) -> {(player, year): [stint]}
        self.stems = {"bat": {}, "pit": {}}      # (kind) -> {(year, id stem): {player}}
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
            try:
                year = int(r["year_ID"])
                weight = float(r["PA"]) if kind == "bat" else float(r["IPouts"]) / 3
            except (TypeError, ValueError):
                continue
            values = [_num(r.get("WAR"))]
            if kind == "pit":
                erlg, plus = _num(r.get("ER_lg")), _num(r.get("ERA_plus"))
                # ERA+ is blank for a stint with no earned runs (it would be infinite).
                ber = 100 * erlg / plus if plus > 0 else (0.0 if weight > 0 and erlg == erlg else float("nan"))
                values += [erlg, ber]
            if all(v != v for v in values):
                continue
            stint = (r["team_ID"], weight, *values)
            name = norm(fix_text(r["name_common"]))
            self.by_player[kind].setdefault((r["player_ID"], year), []).append(stint)
            self.stems[kind].setdefault((year, r["player_ID"][:-2]), set()).add(r["player_ID"])
            if name:
                self.rosters[kind].setdefault((year, r["team_ID"]), {}).setdefault(name.split()[-1], set()).add(r["player_ID"])
            mlbam = r.get("mlb_ID")
            if mlbam and mlbam != "NULL":
                by.setdefault(("id", mlbam, year), {}).setdefault(r["player_ID"], []).append(stint)
            by.setdefault(("name", norm(fix_text(r["name_common"])), year), {}).setdefault(r["player_ID"], []).append(stint)

    def clubs(self, kind: str, year: int, ident: list) -> dict:
        """FanGraphs club code -> Baseball-Reference's for one season ("CHI" is BR's
        "CHC" in the 1890s, "CL87" its "CLE"), learned from the players both list
        under one MLB id and one club."""
        votes: dict = {}
        by = self.stints[kind]
        for r in ident:
            team, mlbam = r.get("team"), r.get("mlbam")
            if not mlbam or not team or team == "- - -":
                continue
            hit = by.get(("id", str(mlbam), year))
            if hit and len(hit) == 1:
                stints = next(iter(hit.values()))
                if len(stints) == 1:
                    votes.setdefault(team, {}).setdefault(stints[0][0], 0)
                    votes[team][stints[0][0]] += 1
        return {team: max(counts, key=counts.get) for team, counts in votes.items()}

    def _find(self, kind, year, mlbam, name, team, weight=None):
        by = self.stints[kind]
        if mlbam:
            hit = by.get(("id", str(mlbam), year))
            return next(iter(hit.values())) if hit else None     # an MLBAM id with no row: no bWAR
        if not name:
            return None
        hit = by.get(("name", norm(name), year)) if not name.startswith("(Unknown)") else None
        if not hit:
            # Spellings differ between the sources for some early and Negro League
            # players ("(Unknown) Latimer" / "Latimer", "Lewis" / "Lucius Hampton",
            # "George Pearce" / "George Pierce"). Accept the only player on that club
            # that year with his surname, or else with his Baseball-Reference id stem,
            # and only when his PA (IP) agree, so a namesake is not taken.
            words = norm(name.replace("(Unknown)", "")).split()
            if not words or not team or team == "- - -" or weight is None or weight != weight:
                return None
            for same in (self.rosters[kind].get((year, team), {}).get(words[-1], set()),
                         {p for p in self.stems[kind].get((year, stem(name)), set())
                          if any(st[0] == team for st in self.by_player[kind].get((p, year), []))}):
                if len(same) != 1:
                    continue
                stints = self.by_player[kind].get((next(iter(same)), year)) or []
                if stints and _agree(sum(st[1] for st in stints), weight):
                    return stints
            return None
        if len(hit) == 1:
            return next(iter(hit.values()))
        same_team = [s for s in hit.values() if any(st[0] == team for st in s)]
        return same_team[0] if len(same_team) == 1 else None

    def season_columns(self, kind: str, year: int, ident: list, weights=None) -> dict:
        """bWAR (and for pitchers ERlg and bER) for each row of a FanGraphs season
        file; weights (PA, or IP for pitchers) let a surname-only match be checked."""
        if not self.loaded:
            return {}
        fields = FIELDS[kind]
        out = {f: np.full(len(ident), np.nan, dtype=np.float32) for f in fields}
        clubs = self.clubs(kind, year, ident)
        for i, r in enumerate(ident):
            w = None if weights is None else float(weights[i])
            team = clubs.get(r.get("team"), r.get("team"))
            stints = self._find(kind, year, r.get("mlbam"), r.get("name"), team, w)
            if not stints:
                continue
            for k, f in enumerate(fields):
                vals = [st[2 + k] for st in stints if st[2 + k] == st[2 + k]]
                if vals:
                    out[f][i] = sum(vals)
        return out

    def season_column(self, kind: str, year: int, ident: list) -> np.ndarray | None:
        return self.season_columns(kind, year, ident).get("bWAR")

    def stint_columns(self, kind: str, year: int, ident: list, weights: np.ndarray) -> dict:
        """The same for each row of a FanGraphs stints file: the Baseball-Reference
        stint for the same club, else the nearest in PA (IP for pitchers)."""
        if not self.loaded:
            return {}
        base = "pit" if kind == "spit" else "bat"
        fields = FIELDS[base]
        out = {f: np.full(len(ident), np.nan, dtype=np.float32) for f in fields}

        def put(i, stint):
            for k, f in enumerate(fields):
                out[f][i] = stint[2 + k]
        rows_by_pid: dict = {}
        for i, r in enumerate(ident):
            rows_by_pid.setdefault(r.get("pid"), []).append(i)
        clubs = self.clubs(base, year, ident)
        for _pid, idx in rows_by_pid.items():
            first = ident[idx[0]]
            stints = self._find(base, year, first.get("mlbam"), first.get("name"), None)
            if not stints and len(idx) == 1:          # one club: the name fallbacks can use it
                w = None if np.isnan(weights[idx[0]]) else float(weights[idx[0]])
                stints = self._find(base, year, None, first.get("name"),
                                    clubs.get(first.get("team"), first.get("team")), w)
            if not stints:
                continue
            if len(idx) == 1 and len(stints) == 1:
                put(idx[0], stints[0])
                continue
            pairs = []
            for i in idx:
                w = 0.0 if np.isnan(weights[i]) else float(weights[i])
                for k, stint in enumerate(stints):
                    club = clubs.get(ident[i].get("team"), ident[i].get("team"))
                    pairs.append(((0 if stint[0] == club else 1), abs(w - stint[1]), i, k))
            pairs.sort()
            used_i, used_k = set(), set()
            for _same, _gap, i, k in pairs:
                if i in used_i or k in used_k:
                    continue
                used_i.add(i); used_k.add(k)
                put(i, stints[k])
        return out

    def stint_column(self, kind: str, year: int, ident: list, weights: np.ndarray) -> np.ndarray | None:
        return self.stint_columns(kind, year, ident, weights).get("bWAR")


def era_plus(erlg, ber):
    """ERA+ from its parts: 100 * league-average earned runs / earned runs."""
    erlg, ber = np.asarray(erlg, dtype=np.float64), np.asarray(ber, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ber > 0, 100 * erlg / np.where(ber > 0, ber, 1), np.nan)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args(argv)
    print(json.dumps({"changed": fetch(a.root)}))


if __name__ == "__main__":
    main()
