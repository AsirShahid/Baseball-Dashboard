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
