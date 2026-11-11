"""Keep the data fresh: fetch from FanGraphs, rebuild baseball.sqlite when it changed.

  python -m pipeline.updater --csv-root /csv --stints-root /data/stints --output /data [--once]

Loop:
- the season in progress (March to mid-November): its six files every hour,
  using FanGraphs' live split (today's games included);
- otherwise: the latest season once a day (a new season appears on its own);
- on the 2nd of each month: every season again, to pick up FanGraphs'
  recalculations (WAR, park factors, wOBA constants);
- Baseball-Reference's daily WAR files (bWAR) once a day, downloaded only when
  they changed;
- a rebuild whenever a file changed, or when the database is missing or
  older than the code's schema.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sqlite3
import time
from pathlib import Path

from . import build, bwar, fetch

log = logging.getLogger("updater")


def db_schema(output: Path):
    try:
        con = sqlite3.connect(f"file:{output / 'baseball.sqlite'}?mode=ro", uri=True)
        value = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        con.close()
        return json.loads(value[0]) if value else None
    except sqlite3.Error:
        return None


def state_file(output: Path) -> Path:
    return output / "updater-state.json"


def load_state(output: Path) -> dict:
    try:
        return json.loads(state_file(output).read_text())
    except (OSError, ValueError):
        return {}


def save_state(output: Path, state: dict) -> None:
    tmp = state_file(output).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(state_file(output))


def cycle(csv_root: Path, stints_root: Path, output: Path, now: dt.datetime | None = None,
          delay: float = 2.0) -> dict:
    now = now or dt.datetime.now()
    state = load_state(output)
    year = now.year
    changed = {}
    month_key = now.strftime("%Y-%m")
    if now.day >= 2 and state.get("full_refresh") != month_key:
        log.info("monthly refresh of every season")
        changed.update(fetch.run(csv_root, stints_root, 1871, year, force=True, delay=delay))
        state["full_refresh"] = month_key
    else:
        changed.update(fetch.run(csv_root, stints_root, year - 1 if now.month < 3 else year, year,
                                 force=True, delay=delay))
    # Baseball-Reference's WAR files, at most once a day (a 304 when unchanged).
    today = now.strftime("%Y-%m-%d")
    if state.get("bwar_checked") != today:
        try:
            if bwar.fetch(output / "bwar"):
                changed["bwar"] = ["war_daily"]
            state["bwar_checked"] = today
        except Exception:   # never let a second source stop the FanGraphs refresh
            log.exception("bWAR download failed; keeping the previous files")
    need = bool(changed) or db_schema(output) != build.SCHEMA_VERSION
    if need:
        log.info("rebuilding (changed: %s)", {k: len(v) for k, v in changed.items()} or "schema")
        summary = build.build(csv_root, stints_root, output)
        state["last_build"] = {"at": now.isoformat(timespec="seconds"), **summary}
    state["last_check"] = now.isoformat(timespec="seconds")
    save_state(output, state)
    return changed


def wait_seconds(now: dt.datetime) -> int:
    in_season = fetch.in_progress(now.year, now.date())
    return 3600 if in_season else 86400


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--csv-root", type=Path, required=True)
    p.add_argument("--stints-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    if db_schema(a.output) != build.SCHEMA_VERSION:
        try:
            bwar.fetch(a.output / "bwar")
        except Exception:
            log.exception("bWAR download failed; building without it")
        build.build(a.csv_root, a.stints_root, a.output)
    while True:
        try:
            cycle(a.csv_root, a.stints_root, a.output)
        except Exception:
            log.exception("update cycle failed; will retry")
        if a.once:
            return
        time.sleep(wait_seconds(dt.datetime.now()))


if __name__ == "__main__":
    main()
