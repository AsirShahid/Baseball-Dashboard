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

## Era percentiles fixed; fWAR and bWAR (2026-11-11)

- **Era-adjusted percentiles** were mathematically right (single seasons match a hand
  calculation from the raw FanGraphs file; spans are the PA/IP-weighted mean of season
  percentiles) but had a pool bug: the team, position and league filters shrank the pool
  (Judge 2024 OPS 99.6 -> 90.0 with Yankees selected). The pool is now every qualified
  player that season in the player's league group, whatever the filters show.
- **League groups** (`teams.league_group`): AL and NL together ("MLB"), every other league
  on its own (NA, AA, UA, PL, FL, each Negro League). Before, 1920-48 pools mixed AL/NL with
  Negro Leagues clubs (65 of 170 qualified hitters in 1932). Same rule for teams and the
  player-page percentile panel. A traded player counts where he had the most PA/IP.
- The chart's "Best on both axes" used to re-rank the visible points; in era mode it now
  uses the season percentiles.
- **fWAR / bWAR**: FanGraphs' WAR keeps the key `WAR` (links unchanged) but is labelled
  fWAR everywhere (`catalog.HEADS`). bWAR comes from Baseball-Reference's daily WAR files
  (`pipeline/bwar.py`, stored gzipped in `/data/bwar`, fetched once a day with
  If-Modified-Since). Joined by MLBAM id, else name + season (+ club) for Negro Leagues
  players; stints by club, else nearest PA/IP. Coverage 99.4-100% of player-seasons, 96% in
  1920-48. Career bWAR equals Baseball-Reference's totals (Ruth 182.6, Bonds 162.8).
  No team bWAR. Build peak memory 457 MB (was 275). `SCHEMA_VERSION = 3`.

## Chart zoom and touch; player spans (2026-11-11)

- Touch: the chart SVG is `touch-action: none` and `user-select: none`. Before, a touch drag
  scrolled the page (cancelling the 3D rotate) and a long press selected the SVG text, which
  showed as big blue blocks on iPad and could leave the page stuck in selection mode.
- Zoom (2D): drag a box (or Pan mode), pinch, Ctrl/trackpad-pinch wheel, +/- buttons; double-tap
  or Reset shows everything. Points outside the window are not drawn; ticks follow the window.
  New data resets the zoom. 3D: pinch/+/- zoom, and tick values along the three labelled edges.
- `ticks()` returns nothing for an empty or non-finite range (it could loop forever).
- Player pages: tap one season and then another (`?from=&to=`) for a span row in each table
  (`queries.player_span`) and a span option in the percentile panel. Career and span
  percentiles rank his line against everyone's line over the same seasons (FanGraphs'
  multi-season cut, same league group), via `queries.percentiles(pid, kind, lo, hi)`.
- The season number no longer links to that season's leaderboard (it picks the span).
- Photo is 2:3 like MLB's headshots (88x132; phones 64x96). The summary line always has G.

## Standout labels; ERA- on the hitting vs pitching chart (2026-11-11)

- Labels ("Standouts"): `standoutOrder()` in `chart.js` takes candidates in turn from seven lists:
  best on both axes, the loneliest dot on screen (distance to the second-nearest dot), each axis
  leader, furthest above and below the trend, and furthest from the middle. It works in robust
  z-scores of the screen position, so a far outlier counts as far (percentile ranks squash the
  tails). The old rule weighted distance toward the good corner, so labels were mostly
  good-at-both players. Labels are placed down that list until enough fit. 3D labels take the
  best overall and each axis leader in turn. basketball.asir.dev uses the same function.
- Team chart default and the "Offense vs pitching" preset use ERA- instead of ERA. ERA- is park-
  and league-adjusted with 100 as average, like wRC+. FIP- was rejected because FanGraphs has
  no FIP- for Negro League clubs (16 of 32 teams in 1925); ERA- covers every team-season.
- Stat descriptions now come from `pipeline/catalog.NAMES` at run time when present, so wording
  fixes show without a rebuild.
- Rollback image `baseball-site:pre-labels-20261111`.

## ERA+ from Baseball-Reference; accented names; surname fallback (2026-11-11)

- ERA+ is Baseball-Reference's stat; FanGraphs does not publish it. Its parts are in the
  war_daily_pitch file we already fetch for bWAR: `ER_lg` (earned runs a park- and
  league-average pitcher allows in the same innings) and `ERA_plus`. ER = 100 * ER_lg / ERA+
  (a blank ERA+ is a stint with 0 ER). Hidden columns `ERlg` and `bER` (INTERNAL) are stored on
  pitcher season, stint and career rows; ERA+ = 100 * sum(ERlg) / sum(bER) for any span or
  career, as Baseball-Reference computes careers. Checked against Baseball-Reference: Rivera
  career 205, Pedro 154, Walter Johnson 147, Grove 148, Skubal career 138; Pedro 2000 291,
  Gibson 1968 258, Maddux 1994 271 and 1995 260, Gooden 1985 229, Skubal 2024 174. BR's ER
  equals FanGraphs ER for every pitcher in 1955, 1999 and 2024 (half of 1873 differs).
- Team ERA+ adds up the team's pitchers (one-club pitchers from season rows, traded ones from
  their per-club rows); blank when matched pitchers threw under 95% of the team's innings.
  Coverage 3,437 of 3,480 team-seasons (all of 1949+; 774 of 809 in 1920-48).
- Team chart default and "Offense vs pitching" now use ERA+ (higher is better, like wRC+).
  ERA+ is in pitcher Standard and Advanced tables, the leaders boards and the percentile panel.
- BR's files encode accented names twice ("GÃ³mez"); `bwar.fix_text` repairs them (9,893 rows).
- Name fallback for players without an MLBAM id whose full name does not match: the only
  player with his surname on that club that season, and only if PA (IP) agree within 35% (or 3).
  Catches "(Unknown) Latimer"/"Latimer", "Lewis"/"Lucius Hampton". Without the PA check it took
  namesakes (a 4-PA "(Unknown) Day" matched a 287-PA player).
- Players with bWAR: 23,590 of 23,767 (was 23,118). Schema 4; new code also serves a schema-3
  database (checked), so the 2-minute rebuild after deploy is safe. Rollback: tag
  `baseball-site:pre-eraplus-20261111` as `baseball-site:latest` and `docker compose up -d`; its
  updater sees schema 4 and rebuilds the database to schema 3 by itself.

## Average lines on 3D charts (2026-11-11)

- The 3D view ignored "Average lines" (never implemented). Now each axis's average is a plane
  through the cube: dashed outline, faint fill, "avg <stat> <value>" at the middle of its
  outermost edge that is clear of other text. Rotates with the cube.
- Also ignored in 3D before: Plain color (now plain), and Trend line, Team logos and
  Trajectories, which are now greyed out in 3D with the note "2D charts only".
- 3D text no longer collides: tick values, axis titles and average labels reserve space; names
  go right, left, above or below their dot and never cover another named dot; text is kept
  inside the chart (phones were cutting off axis titles). The cube is a bit smaller on phones.

## Baseball Savant stats and league-average rows (2026-11-11)

- Source: Savant's custom leaderboard CSV (`pipeline/savant.py`), one file per season and type,
  2015 on, min=0 (every player), joined to FanGraphs players by MLBAM id. The updater fetches the
  current season once a day and every season once a month (24 files, ~35 s). Files live in
  `/data/savant`; a failed download keeps the old files and never stops the FanGraphs refresh.
- New stats: Sweet-Spot%, xwOBAcon, Sprint (hitters), pitchers' xAVG/xSLG/xwOBA, Barrel/PA
  (from FanGraphs' Barrels), and a "Savant discipline" table: Zone%, Z-Swing%, Z-Contact%,
  Chase%, Chase contact, Edge%, Swing%, Whiff%, Meatball%, Meatball swing%. Savant's Zone% and
  Chase% use Statcast's zone; FanGraphs' Zone% and O-Swing% (BIS zone) stay in Plate discipline,
  so the Savant ones are stored as `svZone%`, `svZ-Swing%`, ... and shown as Zone%, Z-Swing%.
- Each rate is stored with its counts (hidden `sv*` columns: pitches in/out of zone, swings,
  contact, whiffs, batted balls, ...) and rebuilt from summed counts for spans and careers.
  Checked: Judge 2026 matches his Savant page on all 16 stats; Judge career (2016-2026) matches
  Savant's "Player" row on all 14 checked (Zone 45.2, Chase 22.3, Whiff 33.4, xwOBA .436, ...).
- League rows: kinds `lbat`/`lpit`, one row per season per league group ("MLB" = AL+NL, plus
  "AL", "NL", and each other league), built by adding up FanGraphs' team rows (so a rate is the
  league's own) and, for MLB 2015+, every Savant player's counts. Index stats (wRC+, ERA+, ERA-,
  ...) are 100. Counting stats are left blank. 1927 MLB: .284/.345/.393.
- Savant's own "MLB" row on a player page is the league pooled over 2015 to now (checked against
  Judge's page: 14 of 15 stats within rounding), whatever seasons the player played. Here, the
  league row under Career is the league over his seasons in his league group, the span row's is
  over the span, and "League average under every season" (saved per device) adds one under each
  season. Leaderboards pin the league line for the seasons shown (AL or NL when picked).
- Percentile panel: Chase% and Whiff% replace O-Swing% and Contact% (hitters) and SwStr% and
  O-Swing% (pitchers), and Sweet-Spot%, Sprint and pitchers' xwOBA are added, when every season
  ranked is 2015 or later; earlier seasons keep the FanGraphs stats.
- Team tables have no Savant stats (Savant does not split a traded player's season by club), so
  the Savant mode is not offered there and empty columns are dropped.
- Sorting a player table keeps each season's club and league rows under it (class `child`).
- Schema 5. New code serves a schema-4 database (checked: player, board, team, chart pages all
  200), so the rebuild after deploy is safe. Build: ~102 s, peak 499 MB (updater limit 768 MB).
  Rollback: tag `baseball-site:pre-savant-20261111` as `baseball-site:latest`, `docker compose up -d`.

## Searchable stat pickers on the chart (2026-11-11)

- The Flask rewrite replaced the Dash explorer's searchable, clearable dropdowns with native
  selects: no "x" to drop the Depth stat, and no typing to find a stat (iPad shows a scroll wheel).
- `web/static/statpick.js` (same file on both sites) puts a button over each `<select
  data-statpick>`: tap opens a panel with a focused "Type to search stats" box over the grouped
  list; typing filters by abbreviation, key, full name and group (every word must match; exact
  and prefix matches first); arrows and Enter, or tap a row. `data-clear` adds an "x" that picks
  the "" option in one tap. The select stays in the page, hidden, and keeps the value; setting
  `.value` from code or rebuilding the options re-renders the button, so chart.js is unchanged.
- The search box is 16px so iOS does not zoom when it focuses; the list refits when the on-screen
  keyboard resizes the visual viewport. Checked with simulated touch in Chromium at iPad and
  phone sizes, not on a real iPad.

## Retired players open on Career; stats that start mid-career are labelled (2026-11-11)

- The percentile panel opened on a player's latest qualified season, so a retired player showed his
  last, usually worst, year (Alomar: 2003, wRC+ 81, 10th percentile). Now a player whose last season
  is before the latest season in the data opens on Career; active players still open on their
  latest qualified season, and a span or an explicit `pseason` still wins.
- Stats whose data starts after a player's first season (FanGraphs plate discipline and batted
  balls 2002, Statcast and Savant 2015, bat speed 2023, WPA 1974, pitchers' K%/BB% 1916; the first
  season is `MIN(season)` in `cols`, which holds only seasons with data) cover the later seasons
  only. Career and span percentiles rank those stats over those seasons, against everyone's line
  qualified over the same seasons (Alomar's O-Swing%: his 2002-04 against the 243 hitters qualified
  over 2002-04; before, against the 792 qualified over 1988-2004), with "2002-04 only" under the
  stat and a note giving the pool. Career and span rows mark those cells with a dagger and a
  footnote under the table, and the league row under Career fills them over the same seasons
  (it was blank, because the league line dropped stats missing from its first seasons).
