# Notes

## 2026-11-11: Dash site replaced

The Dash/Plotly scatter explorer (tag `dash-final-baseball`, code in `legacy/dash/`) was
replaced by a Flask site built like the basketball site (basketball.asir.dev): the same
dark theme, orange accent and Geist font, server-rendered tables and pages, an SVG chart
explorer, and a pipeline that builds one SQLite file.

- **Kept from the Dash site:** the FanGraphs data and fetch parameters, team identity
  recoding (shared codes like MIL split by teamid), name eras, league eras, colors, the
  dated logos (`Logos/eras/manifest.json`), counting-stat list, span rules (counts add;
  AVG/OBP/SLG/ERA/WHIP/K%/BB% rebuilt from totals; other rates weighted), FanGraphs'
  multi-season qualified cut, and every chart feature: season ranges, season-by-season
  points, trajectories, era-adjusted percentiles, trend line, composite-rank coloring,
  mean lines, 3D (now a dependency-free rotatable SVG), logos, CSV export, shareable links.
  Old share links (`/?view=...&x_stat=...`) redirect to `/chart` with the same settings.
- **New:** home page (Yankees card, leaders, standings), standings by division with
  each season's alignment, players and teams tables in six views for any span, player
  pages (career table, majors' leaders in bold, qualified marks, per-club lines for traded
  players, WAR by season), team pages (summary with ranks, rosters including traded
  players, franchise history), compare, search.
- **Traded players:** FanGraphs' normal leaderboards give one combined row ("- - -").
  The split-teams view (`team=0,to`) is fetched too, keeping only players with more than
  one club, so rosters and player pages show each stint. Backfilled 1871-2026.
- **Qualified:** single season `round(3.1 x TG)` PA or `TG` IP, where TG is FanGraphs'
  team games for the player. Rounding half up matches FanGraphs best (142/156 hitting
  seasons identical vs 118 for an exact `PA >= 3.1 x TG` and 123 for rounding down; 502 PA
  at 162 games always qualifies on FanGraphs). Rates need it; counts never do (tables
  list qualified players in Qualified mode because every view has rate columns; the chart
  applies it when either axis is a rate; home leader boards per stat).
- **Data no longer refreshed:** `qualified_batting_stats/` and `qualified_pitching_stats/`
  (the new site derives qualified players). They stay on disk for the rollback image.
- **Storage:** `baseball.sqlite` is a column store (one zlib float32 array per kind,
  season and stat), about 100 MB for 1871-2026, so a page reads only its columns. Careers
  are precomputed as season 0. Float32 is enough for display; sums run in float64.

Rollback:

```bash
docker rm -f baseball-updater baseball-dashboard
docker compose -p baseball-dashboard -f legacy/dash/docker-compose.rollback.yml up -d
```

Leftover images to remove by hand when convenient (the agent cannot run `docker rmi`):
the many `baseball-dashboard-baseball-dashboard:*` tags from earlier Dash work,
`baseball-site-base:dev`, `baseball-site:candidate`.

## Follow-ups from the logo chat (2026-11-11)

The Dash-era session (`20261110_213200_37868ebc`) left three open suggestions for
clubs with no logo (code squares) and several Dash features; all are in the Flask site:

- **Names and leagues by season** for 1871-1900, the Federal League and the Negro
  Leagues: `pipeline/historic_teams.json` (Lahman `Teams.csv` matched on W-L-R for
  431 team-seasons; Seamheads team pages for 344 Negro League team-seasons; AC from
  Wikipedia). `teams.team_name`/`league_name` use it; standings group by the real
  league (Players' League, Eastern Colored League, ...). Hover shows "CPI · Players' League".
  How to rebuild: `tools/team_names/README.md`.
- **Colors**: `pipeline/historic_colors.json`, only colors stated in Wikipedia
  infoboxes (27 clubs). Code squares and table chips use them.
- **Logos**: 15 Negro and Federal League logos from Wikipedia/Commons, each checked by
  eye; provenance and licenses in `Logos/eras/historic_sources.json`, script
  `tools/logo_eras/historic.py`. 707 code-square team-seasons became 595.
- **Min PA/IP**: FanGraphs' 62-option ladder for seasons and spans, plus "Other
  number..." for any value; hint line under the filters.
- **Player pages**: percentile ranks (Savant-style, vs that season's qualified players,
  default = latest qualified season) and a career facts line.
- **CSV export** rounds to the displayed precision.
- **Bug fixed**: spans entirely before 1954 lost OBP/OPS/BABIP (no SF recorded); missing
  SF/HBP now count as 0, as on FanGraphs (Ruth .474/.690/1.164).
- `SCHEMA_VERSION = 2` (team_seasons.lg_name): the updater rebuilds the DB on start.
