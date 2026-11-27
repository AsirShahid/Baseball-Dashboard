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

## Team bWAR (2026-11-11)

- The teams table had an empty bWAR column (hidden since the Savant change, which drops empty
  team columns). Team bWAR is now the sum of the club's players' bWAR, one-club players from season
  rows and traded players from their per-club rows, which is how Baseball-Reference totals a team.
  Checked against BR's daily files summed by club: 2024 hitting 589.9 and pitching 409.9 both equal
  BR, every club; all 2,021 team-seasons since 1947 within 0.22 (hitting) and 0.12 (pitching).
- Blank when matched players cover under 95% of the club's PA (IP): 73 of 6,960 team-seasons, all
  Negro League clubs except 1875 BKA and WSO and 1884 St. Paul. Over a span a club with any blank
  season has a blank total (`queries.team_gaps`, keyed like `db.table` by franchise id), on the
  table and the team chart, so a franchise total never silently leaves a season out.
- Matching: `BWar.clubs()` pairs each season's FanGraphs club codes with BR's from players matched
  by MLB id (1890s Chicago CHI = BR CHC, CL87 = CLE), so the same-club checks work; and a fallback on
  BR's player-id stem (`stem("George Pearce") == "pearcge"`, BR's pearcge01 "George Pierce"), only
  for a unique player on that club with agreeing PA/IP. 82 player-seasons gained bWAR, none lost or
  changed; players with career bWAR 23,590 -> 23,627. All 82 pairings checked (renamed players such
  as Bill Banks = BR banksbi01 "Bill Yerrick"; Willie Wells Jr. = BR wellswi01, Memphis 1945-46).
- Schema 6 (rebuild after deploy). New code serves a schema-5 database: the column is simply absent.

## Pinned name column when a table scrolls sideways (2026-11-11)

- Bug (iPad, teams table over a span): highlighted rows (favourite team, and on basketball the
  picked/span seasons) tinted their sticky name cell with a translucent colour, so the columns
  scrolling under it showed through; and only body cells were sticky, so the header cell above the
  names scrolled away and the headings slid out of line.
- Fix: rows set `--tint` (and `--base` where their cells are not on the plain surface: total rows
  raised, group rows bg); a sticky `td.name`/`th.name` paints the tint over that solid base. app.js
  marks the header cell above a pinned column `name`, so it is pinned too. Checked at iPad portrait
  with every wide table scrolled 420px: header pinned and aligned, no translucent pinned cell.

## AL / NL filters count only play in that league (2026-11-11)

- Bugs: the AL/NL filter took a span line's league from its last season, so all-time NL batting was
  led by Babe Ruth (whole career; last season the 1935 Braves), Aaron and Hornsby were AL, and the
  Brewers' 1969-97 AL seasons counted under NL. And every traded player ("- - -") passed both
  filters, so 1943 NL pitchers included Satchel Paige and Bill Byrd (two Negro League clubs).
- Now `db.table(kind, lo, hi, stats, league)` builds each season from that league's play
  (`db._league_season`): clubs in it (`teams.in_league`, also divisions), one-club players there, a
  traded player's season line if all his clubs were there, else his per-club rows with its clubs added
  up (TG = his largest club's games, so 1990 McGee qualifies in the NL on 542 PA at .335 and not in
  the AL). Team W-L (`_records`) and the bWAR gap check take the league too. MLB is unchanged.
- Checked: Brewers AL 2200-2367 (1969-97, Pilots included) + NL 2308-2287 = franchise; Astros NL
  3999-4134 + AL 1178-987; fWAR halves add to the MLB totals; Ruth NL = 1935 BSN 92 PA; fixture test:
  NL batters' PA over 1955-2024 equal NL clubs' PA within 0.2%.
- Not cached per season (one all-time query would add ~150 entries to a 400-entry cache that clears
  when full); `db.table` caches the result. A 72-page sweep: worst 3.9 s uncached, 391 MiB vs 300 MiB
  for the old image, so mem_limit 512m -> 768m.

## Home-screen app and offline use (2026-11-11)

- Installable PWA on phones and tablets: `/manifest.webmanifest` and `/sw.js` come from
  `web/pwa.py`; icons in `web/static/icons/` are rendered from `favicon.svg` by
  `tools/make_icons.py` (rounded tile, maskable full-bleed, 180 px apple-touch-icon).
  The manifest link has `crossorigin="use-credentials"` because a manifest is otherwise
  fetched without cookies, which matters behind a sign-in gateway.
- `web/sw.js` (same file on basketball and baseball; `/sw.js` prepends a CONFIG line with
  this deploy's versioned static files, so every deploy updates phones by itself):
  - Pages: network first, every page that loads is saved (newest 300). With no connection,
    no answer within 8 s, or a 5xx during a restart, the saved copy is served with
    `data-saved` on `<html>` and app.js shows "Offline: saved copy from ...". A page never
    opened shows a grouped list of saved pages instead.
  - The main pages (nav pages plus the favourite team) are refreshed at most hourly while a
    page is open online (app.js posts "warm"), so they are recent when the signal drops.
  - Static files cache first, all stored on install; old versions dropped on activate, with
    an ignoreSearch fallback for pages saved under an older version.
  - Images cache first (newest 800); MLB headshots are fetched with CORS (img.mlbstatic.com
    sends `Access-Control-Allow-Origin: *`) so they are not padded opaque entries.
  - `/api/chart`: network first, saved copy offline. `/api/search` offline searches the
    titles of saved player and team pages ("Saved for offline").
  - Sign-in redirects (`/oauth2/`, opaque redirects) pass through and are never saved.
- Installed app only: returning after 15+ minutes reloads the page when online.
- Checked in Google Chrome at Pixel 7 size against a container of the new image: no
  installability errors (persistent profile), all main pages and static files saved, saved
  copies styled with the banner both with emulated offline and with the server stopped,
  list page for unsaved pages, offline search, banner gone back online, no console errors.
  On production https://baseball.asir.dev the same checks passed (server not stopped).
  Basketball and usage are behind Pocket ID, so production there was checked only through the
  container IP; a real phone install was not tested. iOS keeps a home-screen app's cookies
  apart from Safari's, so the installed app asks for the passkey once.
- Rollback image: `baseball-site:pre-pwa-20261111` (retag as baseball-site:latest and `docker compose up -d --no-build baseball-dashboard`).

## Site mark redrawn (2026-11-11)

- The old mark (a circle with two plain curves) read as a tennis ball. New mark: the same
  circle and line weight as basketball's, seams as circular arcs, 4 square-ended stitches per
  seam, tilted 45 degrees. `tools/make_mark.py` prints the favicon and the header `<svg>`;
  `tools/make_icons.py` renders the app icons from the favicon.
- Chosen from ~20 variants rendered at 16, 32, 64 and 160 px beside the basketball mark: short
  round-capped stitches looked like beads, V-chains like wheat, slanted ones like cracks.
- Rollback image: `baseball-site:pre-logo-20261111`.

## Team G and the teams table's average wRC+ (2026-11-12)

- G on team lines was FanGraphs' team G, which adds up its players' games: the Giants showed
  272,253 all-time and a 2026 club about 2,400. `db._season_table` now gives team kinds TG (the
  club's games, ties included: 1908 Giants 98-56 in 157), so tables, spans and charts agree.
- The teams table's league row showed wRC+ 100 (FanGraphs' league line is 100 by definition, scaled
  to non-pitchers) while every NL franchise was 88-98: team lines include pitchers' hitting. PA-
  weighted, NL clubs averaged 94 before the universal DH (2019: 94; 1973-2021: 93.5), AL clubs 99.6
  after 1973, both about 93 before. `queries.team_league_row` now shows the average club's index
  stats (PA or IP weighted, AL and NL clubs only); player tables keep 100. All-time: NL 94, AL 97,
  MLB 95; 2026 NL 100. A footnote under batting team tables says why.
- Rollback image: `baseball-site:pre-teamg-20261112`.

## Chart: Qualified always means qualified (2026-11-12)

- Bug (Asir, iPad): Players, hitters, 2000-2026 season by season, bWAR vs fWAR, Min PA Qualified said
  "That is 24,168 points". The chart applied the qualified rule only when an axis was a rate stat,
  so two counts (bWAR, fWAR; HR, SB) meant no minimum: every hitter-season, pitchers batting too.
- Now "Qualified" on the chart is the batting- or ERA-title playing time whatever the stats, as the
  players table and FanGraphs use it; a number from the ladder (down to 1) still shows everyone.
  Same query: 3,961 points, 129-166 a season (2020: 142), led by Bonds 2002/2001/2004; combined
  span (1,000 PA): 1,298. Pitchers SV vs SO 2026: 46 qualified, 858 at 1 IP.
- Rollback image: `baseball-site:pre-chartq-20261112`.

## OPS+ from Baseball-Reference; traded players' per-club bWAR fixed (2026-11-17)

- OPS+ is Baseball-Reference's park- and league-adjusted OPS; FanGraphs does not publish it. The
  war_daily_bat file we already fetch has its league side per stint: `TOB_lg` and `TB_lg`, the times
  on base and total bases a park- and league-average hitter would reach in the same PA and AB. OPS+ =
  100 * (OBP / lgOBP + SLG / lgSLG - 1) = 100 * (TOB / TOB_lg + TB / TB_lg - 1). Hidden columns on
  hitter season, per-club and career rows: `TOBlg`, `TBlg` (BR) and `bTOB`, `bTB` (FanGraphs' H + BB +
  HBP and total bases, kept only where the league side matched), so any span is 100 * (sum bTOB / sum
  TOBlg + sum bTB / sum TBlg - 1), Baseball-Reference's career method (`aggregate.rebuild_rates`).
- Checked against Baseball-Reference pages (2026-11-17): careers Ruth 206, Williams 191, Bonds 182,
  Gehrig 179, Hornsby 175, Mantle 172, Cobb 168, Trout 166, Aaron 155, Mays 155, Pujols 145, Judge
  176, A-Rod 140, Jeter 115 (14 of 14); 2026 Judge 140, Trout 131. Against BR's published OPS+ for
  every one-club AL/NL season with 100+ PA (n = 38,435): 99.5% within 1, 99.99% of seasons since 1990 to
  0.01; the misses are 1880s-90s lines where the counts differ (1889 Chicago up to 16).
- Only where FanGraphs and BR agree on the line's PA within max(3, 10%) (`build.PA_SLACK`; BR's PA
  rides along as `brPA` and is never stored). FanGraphs files Harry Moore (1884 WST, 480 PA) under
  Sparrow Morton's MLB id (8 PA): OPS+ 14,652 without the check. Calibrated on all 100+ PA lines: AL/NL
  lines 5-10% apart still match BR (bookkeeping outside OBP and SLG), Negro Leagues lines 3-5% apart
  are already ~8 points off (the two sources record different lines). Coverage: 45,639 of 46,157
  seasons with 100+ PA; 99.7-100% per decade except 1920-48 (93-95%).
- BR rows with no WAR stay out, as before. Letting in the 60 that batted moved six Negro Leagues
  players' bWAR through new name collisions (Johnny Taylor 6.8 -> 6.9); they get no OPS+.
- Team OPS+ adds up the club's hitters (one-club from season rows, traded from per-club rows), blank
  under 95% of the club's PA: 3,288 of 3,480 team-seasons. 2024 NYY 115, LAD 120, SEA 102, CHW 76
  equal BR's team pages. League rows are 100.
- Shown in hitter Standard and Advanced tables, the leaders boards, the percentile Value group,
  Compare, and a chart preset "OPS+ vs wRC+" (2026 qualified: 135 hitters, r = 0.987).
- Bug fixed, found while checking OPS+ per club: `BWar.clubs()` learned the FanGraphs -> BR club
  code pairing from the per-club file too, where every player had several clubs, so the only votes
  were odd lines (2022: NYY -> KCR, KCR -> ARI) and real stints swapped. Live since bWAR was added:
  Benintendi 2022 showed KCR 0.55 / NYY 2.30 (BR: 2.30 / 0.55); also Iglesias 2013, Leonys Martin
  2018, Crisp 2016, Smoak 2010, Kazmir 2015. `season_columns` now keeps each season's map and
  `stint_columns` reuses it. 294 per-club lines changed: 155 now equal BR's same-club stint, 139
  pitchers' 0.0 lines moved to the club BR lists, none worse (per-club bWAR = BR same-club stint:
  13,328 of 13,329, was 13,173). Team bWAR changed in 35 team-seasons, all now equal BR's club sums
  (2022 KCR 9.89 -> 11.65, NYY 37.37 -> 35.62; 2013 BOS/DET, 2018 CLE/DET); worst gap since 1950
  1.76 -> 0.22. Season and career bWAR, every FanGraphs column, rows and players are byte-identical
  to the previous database.
- Schema 7. Build ~107 s, peak 569 MB (updater limit 768 MB). New code serves a schema-6 database
  (20 page types return 200, OPS+ simply absent), so the rebuild after deploy is safe.
- Also deployed with this: ad3cb58 (service worker /oauth2/ navigation fix, committed 11-16).
- Rollback: tag `baseball-site:pre-opsplus-20261117` as `baseball-site:latest`, `docker compose up -d`;
  its updater sees schema 7 and rebuilds to schema 6.

## Full offline copy (2026-11-22)

Asir asked for both sports sites to work fully offline. Saving pages cannot do that
(27,000 player and team pages before any tab, filter, span, compare or chart), so a
device keeps the database and runs the site's own code on it.

- What a device holds: `baseball.sqlite` (111 MB), this repo's `app.py`, `web/` and
  `pipeline/` (app.zip), the logos, Pyodide 314.0.8 (Python 3.14 as WebAssembly) with
  numpy, Flask and its dependencies (18 MB), and this season's 1,472 player photos (23 MB).
  Measured in Chromium, Firefox and WebKit: 162 to 166 MB on the device, a 115 MB
  download plus the photos.
- Server, `web/offline.py` (same file on basketball): `/offline/manifest.json`,
  `/offline/chunk/<sha256>`, `/offline/rt/<version>/<file>`. Every file is cut into
  256 KB pieces named by SHA-256, gzipped when that is smaller. A device downloads the
  pieces it lacks, so an interrupted download resumes and a refresh costs only the
  pieces that changed. The pieces are built under `OFFLINE_ROOT` (default
  `/tmp/offline-pack/<site>` in the container, about 90 MB) by a separate small process
  the manifest route starts when the database or code changed (about 15 s). The runtime is
  fetched into `web/offline_rt/` when the image is built (`python web/offline.py
  fetch-runtime`, every file pinned by SHA-256); it is not in git.
- Access: the site is public, so the copy is offered only to a device holding
  `OFFLINE_KEY` (in `.env` beside docker-compose.yml, not in git; sent as `X-Offline-Key`).
  Without the variable the three routes answer 404 and About shows no card. A device gets
  the key once from `https://baseball.asir.dev/about?offline_key=<key>` (kept in
  localStorage, removed from the address). Other visitors see one quiet "Offline copy"
  line on About; opening it gives a key field, which is how an installed home-screen app
  (no address bar) is unlocked. If the key is changed, the card on a device with the old
  one asks for the new one.
- Device, `web/static/offline/` (same files on basketball):
  - `ui.js`: the "Offline copy" card on About (Download, Pause, Update, Remove) and a check
    on every other page at most every 20 minutes. An update under 40 MB, or any update on a
    connection the browser reports as Wi-Fi, downloads by itself; a larger one waits for a tap.
  - `sync.js` (worker): downloads and verifies pieces into the browser's private file system
    (`offline/chunks/<sha256>`), Pyodide into a cache, then the photos into the `photos-v1`
    cache. When the pieces are complete it records the manifest in the `meta-v1` cache;
    that record is what "this device has a copy" means. Old pieces are deleted afterwards.
  - `engine.js` (module worker): starts Pyodide, mounts the pieces as read-only files under
    `/data` (read on demand, 48 MB kept in memory), unpacks the code into `/app`, calls
    `create_app()` and answers requests through Flask's test client.
  - `shell.js`: the page shown with no connection. It starts the engine once and runs the
    site in a full-size frame; the window's address and title follow the frame.
- `web/sw.js`: with a copy on the device and no connection (or no answer in 5 s, or a
  5xx), a page opens in the shell; pages, `/api/search`, `/api/chart` and logos requested
  inside it are rendered by the engine and marked `data-local` ("Offline copy: data as of
  ..."). A page the server sent after it last confirmed the copy as current is still
  preferred, since it may be newer. Online, pages come from the server as before.
  Without a copy nothing changes: saved pages and the offline list.
- Firefox: navigation preload is now off there. With it on, an unreachable server gave
  "Problem loading page" instead of the saved page (the failed preload fails the
  navigation), so offline use on Firefox for Android did not work with a poor connection.
  Chrome and Safari keep preload.
- Safari books 1 MB against the site's storage allowance for every file written through
  a sync access handle until the next launch (501 MB shown for 138 MB). `sync.js` writes
  with `createWritable()` where it exists (162 MB shown) and falls back to the handle.
  A private window in Safari has no file storage; the card says so.
- Updates: the updater rebuilds the whole database once a day even in November, but the
  build is repeatable. A rebuild from the same files differed from production's in 1 of
  424 pieces (the build time), and one with 40 players' 2026 WAR and Offense changed
  differed in 7 (1.1 MB to download). So a daily refresh costs a device about 1 MB.
- Speed, measured on this server: first page with no connection 8 to 17 s (Python starting),
  then 0.1 to 2.6 s per page. The all-time career table takes about 6 s.
- Stays online only: nothing on this site. A photo of a player who did not play this
  season shows only if it was seen before.
- Tests: `tests/test_offline.py` (pieces rebuild every file byte for byte, the key, the
  code bundle holds no secrets, and the engine's pages equal the server's byte for byte
  through `tests/test_offline.mjs` under Node), `tests/test_sw.js` (the worker's routing).
  `tools/offline_browser.py <url> --key K --browser chromium|firefox|webkit` downloads the
  copy in a real browser, cuts the connection with a relay it controls and uses the site:
  31 of 31 checks in each of the three browsers. Not tested on the real phone or iPad.
- Live since 2026-11-22 18:52 UTC (commit bc167f6). On https://baseball.asir.dev in Chromium
  and on the production container in Firefox and WebKit the browser check passed 29 of 29.
  The quiet "Offline copy" line with the key field went live at 20:17 UTC (commit 68b67a5):
  31 of 31 on https://baseball.asir.dev in Chromium. Firefox and WebKit were not rerun on
  that build (only `ui.js` and `app.css` differ from the one they passed). The copy's
  version did not change, so a device that already had it downloaded nothing again.
- Rollback images: `baseball-site:pre-offline-20261122` (before the feature) and
  `baseball-site:offline-20261122-first` (the first deploy, without the key field). Removing `OFFLINE_KEY` from `.env`
  and recreating the container switches the feature off without a rollback.

## 2026-11-26: Find in Teams view finds a player's clubs (parity with basketball.asir.dev)

Asir's basketball report (Teams chart, "Brunson" in Find: every logo faded, no word why) applied
here too: "Judge" in the Teams view faded all 30 clubs.

- `queries.chart_find` + `/api/chart/find?q=&season=&to=`: players whose name matches (search
  index order, career WAR), with their clubs in the span as `[season, code, franchise id]` from
  `rows` (kinds bat, pit, sbat, spit; a traded season counts each club, e.g. Soto 2022 WSN and
  SDP). 23 ms on the live data.
- `chart.js`: when no club name matches, the best-known match who played in the span lights his
  clubs (one season: season and code; a span: franchise id; season by season: each team-season).
  A line under Find says what was found ("Juan Soto: WSN, SDP, NYY, NYM. Also Gregory Soto, ...:
  type more of the name.") with "Show players"; in Players view it says when no one on the
  chart matches (the minimum or a filter), or when the matches are outside the zoom.
- Test: `test_team_chart_find_lights_up_a_players_clubs`; `pytest tests -q`: 86 passed
  (`uv run --no-project --with-requirements requirements.txt --with pytest python -m pytest tests -q`).
- Checked on a candidate on the live data at 412, 450 and 1440 px: Judge lights NYY; Soto over
  2020-2026 lights WSN, SDP, NYY, NYM; season by season the eight exact team-seasons; no console
  errors or sideways scroll.
- Rollback: tag `baseball-site:pre-findnote-20261126` as `baseball-site:latest`, then
  `docker compose up -d --no-deps --no-build baseball-dashboard` from `vps-infra/stacks/baseball-dashboard`.

## 2026-11-27: offline shell no longer spins for ever when its frame is sent elsewhere (parity with basketball)

Found on basketball.asir.dev (phone report): with the gateway session expired, the shell's frame
followed the sign-in redirect to id.asir.dev, which refuses frames, and the shell waited for ever
on "Starting the site...". Baseball has no gateway, but `web/sw.js` and
`web/static/offline/shell.js` are the same files on both sites, so the change is here too:
- `framed()`: a redirect for the frame while online is not followed in the frame; the frame gets
  a page that loads the address in the whole window (`leaveShell`). `page()` then waits for the
  server for 30 s instead of opening the shell again.
- `shell.js`: a frame on a page the shell cannot read reloads the window once, then says so with
  Try again instead of looping.
- Tests: `tests/test_sw.js`; `tools/shell_signin_browser.py .` (real Chromium with a fake gateway
  that refuses frames: passes here, fails on the old files). `pytest tests -q`: 86 passed.
- basketball's NOTES.md (same date) has the cause from the server logs.
- Deployed 2026-11-27 17:15:06 UTC (12:15 PM ET): `docker compose build baseball-dashboard`, then `up -d --no-deps
  --no-build baseball-dashboard` from `vps-infra/stacks/baseball-dashboard`; the updater was left running.
  Public https://baseball.asir.dev serves the new `/sw.js` and `shell.js`.
- Rollback: `docker tag baseball-site:pre-shellfix-20261127 baseball-site:latest`, then `docker compose up -d --no-deps --no-build
  baseball-dashboard` from the same folder.
- On the public site after the deploy: `tools/offline_browser.py https://baseball.asir.dev --direct
  --key <OFFLINE_KEY> --site baseball --browser chromium`, 31 of 31. The public https address needs
  `--direct`: without it the relay speaks plain TCP to port 80 and the first reference page has no
  `main.page`. `tools/offline_browser.py` also no longer fails when About is not network-idle in 15 s
  (same file as basketball).

## 2026-11-27: stat ranges on Players and Teams (parity with basketball.asir.dev)

Asir asked for basketball's "at least / at most / between" filter here too, on both tables.
- `?f=stat:lo:hi,...` (e.g. `/players?f=HR:30:,K%25::20`, `/players?kind=pit&f=ERA::3,IP:150:`,
  `/teams?f=pct:.55:`), `web/ranges.py`. Any catalog stat for that kind (462 batting, 533
  pitching); on Teams only stats the team lines have (`_team_stats`: every stat stored for
  `tbat`/`tpit`, which leaves out Savant's per-player Chase%, Whiff%, xwOBAcon...), plus W, L, PCT.
- Values in the table's units and rounding: K% 24.3, AVG .300, ERA 3.25; IP as box scores write
  it (150.1 = 150 1/3, `ranges.innings`). Chips read "HR ≥ 30", "AVG .270–.300".
- A stat the view lacks becomes a column (and gets its league-average cell). Under Qualified a
  rate stat in a range also needs the player qualified. Switching Batting/Pitching drops the ranges
  (the same key means different things, e.g. K%). Ranges survive span, team, league, position.
- `queries.player_table` / `team_table` take `cols` and `keep`; UI is basketball's (macro
  `m.stat_ranges`, app.js block with baseball's number hints, CSS block). The picker lists every
  stat, which adds about 34 KB to the Players page (186 to 220 KB uncompressed).
- Tests: `test_stat_ranges_on_players`, `test_stat_ranges_on_teams`; `pytest tests -q`: 88 passed.
  Playwright on a candidate with the live data, batting, pitching (ERA at most) and Teams at 412 and
  1440 px: 60 of 60.

## 2026-11-27: season range menus no longer move the other year (phone report)

Asir: changing the first year of the range moved the second year too. Cause: `m.span_picker`'s
first menu set only `?season=`; with one season shown there is no `?to=`, so `_span()` took the
second year from the first (2026 to 2026, pick 2021 as first: 2021 to 2021). Picking a last year
before the first also swapped the two (`queries.span`).
- Now each menu writes both years (`.spanpick[data-lo]` in app.js): the other end stays where it
  is, and only a pick past it moves it along (first 2026 with 2015-2020 shown gives 2026 to 2026).
  Players, Teams and Compare use the macro. The chart's menus follow the same rule (they swapped
  the ends when a pick crossed).
- Checked in Chromium at 412 px: on the live site picking 2021 as the first year showed 2021 to
  2021; on the fix 2021 to 2026, then the second year changes alone, then a first year past the
  second moves it along, on all three pages and the chart. `pytest tests -q`: 88 passed.
- Deployed 2026-11-27 18:07:25 UTC (12:07 PM CT); on the public site picking 2021 now gives 2021 to 2026.
  Rollback: `docker tag baseball-site:pre-spanfix-20261127 baseball-site:latest`, then `docker compose up -d
  --no-deps --no-build baseball-dashboard` from `vps-infra/stacks/baseball-dashboard`. Pushed (CI green on 91451d9).

## 2026-11-27: stat picker explains every column (not the code twice)

Asir: many picker entries (`pfxKN-Z pfxKN-Z`, `rBTV rBTV`, `piwFS piwFS`) repeated the acronym as their
description. 350 of 579 distinct columns had no words (`catalog.describe` fell back to the code).
- `pipeline/catalog.py`: `describe` now covers all 579. Code-pattern families are generated in
  `_family` (PITCHf/x `pfx` and Pitch Info `pi` usage, movement, velocity, arm angle, spin, pitch value; Statcast
  `sc` zones H/S/SI/SO/C/W/Z/O; Stuff+ `sp_`, PitchingBot `pb_`); one-offs are in `EXTRA` (rule violations,
  2026 ABS challenges, bat tracking, batted-ball counts). `EXTRA` outranks `NAMES`.
- Meanings are from FanGraphs' rule-violation post (2023-04-13), the Stuff+/Location+/Pitching+ primer, MLB's
  Statcast glossary (attack direction, tilt, ideal attack angle, swords) and Baseball Savant's bat-tracking page
  (competitive swings), plus the stored data: CU% = CUO% + CV%, SL% = SLO% + ST% (CV is a slurve, ST a sweeper),
  scH + scS + scC + scW = 100%, scS = scSI + scSO, rTV = rBTeamV + rFTeamV, ESV = BPTV + BTV, `aa` is arm angle
  (nonzero from 2020, submariner Tyler Rogers -64), `sp` is spin rpm. Not documented by FanGraphs, so inferred:
  CV = slurve, EBV/ESV, XBR (baserunning, from 2016), the sign wording of rXTV and wXReview.
- `web/queries.column` reads `describe` (no rebuild needed); `pipeline/build.py` logs any column that ends up
  with no description, so a column FanGraphs adds later is flagged instead of shown twice.
- `web/static/app.css`: picker rows stack (code and group on one line, explanation wrapped beneath); the
  one-line ellipsis cut every explanation at about 30 characters on a phone.
- `tests/test_catalog.py` + `tests/fixtures/stat_codes.txt` (the 579 columns). `pytest tests -q`: 94 passed. Deployed 2026-11-27 (live image holds this commit); checked on the public site at 412 px and 1104 px in Chromium.
- Rollback: `docker tag baseball-site:pre-describe-20261127 baseball-site:latest`, then `docker compose up -d
  --no-deps --no-build baseball-dashboard` from `vps-infra/stacks/baseball-dashboard`.
