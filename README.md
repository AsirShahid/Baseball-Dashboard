# Baseball

A fast baseball stats site: every MLB (and other major-league) season from 1871 on, from
FanGraphs' leaderboards. Server-rendered pages, plain CSS and JavaScript, SVG charts; no
front-end framework. Live at [baseball.asir.dev](https://baseball.asir.dev).

## Pages

- **Home**: the Yankees at a glance, hitting and pitching leaders, standings.
- **Standings**: by division (with each season's alignment from 1969), by league before.
- **Players**: hitting or pitching leaderboards for one season or any span, in six views
  (standard, advanced, value, batted ball, plate discipline, Statcast), with team, league
  and position filters and the qualified rule.
- **Teams**: FanGraphs' team totals in the same six views, with records.
- **Player** and **team** pages: career tables with the majors' leaders in bold, per-club
  lines for traded players, a WAR-by-season chart, rosters, franchise history.
- **Compare**: up to four players side by side over any span.
- **Charts**: any stat against any other (about 950 to pick from) for teams or players, in a
  season or a span; season-by-season points and trajectories, era-adjusted percentiles,
  trend line with r², a rotatable 3D mode, team logos, CSV download and shareable links.
  Old share links from the Dash site redirect here.
- **Home-screen app**: installable on phones, and pages you have opened work offline (NOTES.md,
  2026-11-11).

## Qualified

MLB's rule for rate stats: 3.1 plate appearances (hitters) or 1 inning (pitchers) per team
game, rounded to the nearest whole number (502 PA and 162 IP over 162 games). Counting stats
have no minimum. Over several seasons: FanGraphs' 1,000 PA or 300 IP, capped at the sum of
the season minimums. Checked against FanGraphs' own qualified lists for every season
1871-2026: identical in 142 of 156 hitting seasons and 153 of 156 pitching seasons, 18
player-seasons different in all (FanGraphs edge cases with traded players).

## Data

`pipeline/` fetches FanGraphs leaderboards into season CSVs (`all_batting_stats/`,
`all_pitching_stats/`, `team_batting/`, `team_pitching/`, plus per-club lines for traded
players in the data volume) and builds `baseball.sqlite`: a column store with one
compressed float32 array per season and stat, careers precomputed, and a catalog of what
each stat is (name, group, format, direction, counting or rate).

```bash
python -m pipeline.fetch --csv-root . --stints-root data/stints --start 2026 --end 2026
python -m pipeline.build --csv-root . --stints-root data/stints --output data
DATA_ROOT=data flask --app app run
```

The updater (`python -m pipeline.updater`) refreshes the season in progress hourly
(FanGraphs' live split), checks daily in the off-season, refetches every season once a
month for FanGraphs' recalculations, and rebuilds the database when anything changed.

## Deploy

```bash
cd ~/vps-infra/stacks/baseball-dashboard
docker compose build && docker compose up -d --wait
```

Two containers from one image: `baseball-dashboard` (gunicorn, read-only data) and
`baseball-updater`. The Dash site is in `legacy/dash/` with a rollback compose file.

## Tests

`python -m pytest tests -q` builds a database from the 1955 and 2024 fixtures in
`tests/fixtures/` (real FanGraphs data, gzipped) and checks the build, the qualified rule
against FanGraphs' lists, spans, every page, the chart API and old-link redirects.
