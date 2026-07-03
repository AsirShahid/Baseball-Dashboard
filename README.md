# Baseball Dashboard

An interactive web application for visualizing baseball statistics. Build custom scatter plots — 2D or 3D — across hundreds of FanGraphs batting and pitching metrics for every team and player season from 1871 to present.

![wRC+ vs Barrel%](https://baseball.asir.dev/media/76f6cdc028d8719192f44385fbb26a5efabe730796a3aa741c7bc351.png)

## Features

- **Team and player views** — scatter any two (or three) stats against each other
- **Find player** — type a name to spotlight matching players: they get a bigger, labeled marker while everyone else dims
- **Composite leaderboards** — a top-10 board for both teams *and* players, ranked by average percentile across the selected axes
- **Multi-season ranges** — drag the two-handled season slider to span several years (e.g. 2019–2026); counting stats (WAR, HR) are summed and rate stats (wRC+, ERA) are PA/IP-weighted, so the chart and leaderboard show one cumulative point per team/player
- **Season trajectories** — flip a multi-season range from one aggregate point into a path through stat space, one point per season: team rebuilds and player aging curves at a glance (players show your search matches, or the span's top 10)
- **Era-adjusted axes** — replace raw values with each season's percentile (PA/IP-weighted across the span), so a 1968 OBP is measured against 1968 pitching, not pooled with the steroid era
- **Trend line** — toggle an OLS fit with its r², to see how strongly the two stats actually relate
- **Label modes** — label all players, only the outliers (the ~12 most extreme points), or none
- **3D scatter plots** — add a Z-axis stat to switch to an interactive 3D chart
- **Composite rank coloring** — color-code markers by average percentile rank across all selected axes (red → yellow → green)
- **Mean reference lines / planes** — toggle average lines in 2D or semi-transparent planes in 3D
- **Team logos or colored markers** — display teams as logos or team-colored dots
- **Season filtering** — the slider only offers seasons where the chosen stat actually has data (e.g. Exit Velocity only appears from 2015 onward)
- **CSV export** — download exactly what the chart is plotting (axes, filters, composite ranks) with one click
- **Shareable URLs** — every control is encoded in the URL so you can copy and share a specific view
- **Auto-fetch** — if a season's CSV is missing the app fetches it live on first access

## Quick start

```bash
git clone https://github.com/AsirShahid/Baseball-Dashboard.git
cd Baseball-Dashboard
./launcher.sh
```

`launcher.sh` creates a `.venv/` virtual environment and installs all dependencies automatically on first run, then starts the dashboard at **http://localhost:8050**.

> **Note:** On Arch Linux and other systems that enforce PEP 668 (`externally-managed-environment`), using a venv is required. `launcher.sh` handles this for you.

## Manual setup

If you prefer to manage things yourself:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Data

Season CSVs are **not** stored in git — they live on the machine that runs the
dashboard (a `data-refresh` GitHub Action used to commit them monthly, but
350 MB of CSVs made the repo balloon). The app fetches any missing season from
FanGraphs on first access, and `launcher.sh` / the Docker entrypoint run the
generator in `--watch` mode so the current season stays fresh. To backfill the
full history in one go (recommended on a new install — on-demand fetches are
slow the first time someone scrubs deep into the past):

```bash
source .venv/bin/activate

# One-time full-history backfill (~900 polite requests, takes a while)
python baseball_csv_generator.py --start 1871

# Fetch a specific range (skips seasons already on disk)
python baseball_csv_generator.py --start 2025 --end 2026

# Re-download a range regardless of what's cached
python baseball_csv_generator.py --start 2020 --end 2026 --force

# Fetch missing seasons then keep the current season refreshing every 4 h
python baseball_csv_generator.py --start 2025 --watch
```

The dashboard re-reads a CSV whenever the file changes on disk, so refreshed
data shows up without a restart.

### Live split vs. recalculations

The fetcher uses FanGraphs' **"Live Stats — Full Season"** split (`month=33`) for the in-progress season, so the current year includes the day's games in real time. Completed seasons use the standard full-season split (`month=0`), which is the only one FanGraphs serves for past years; a live-split request for a finished season automatically falls back to it.

Completed seasons are nearly static, but FanGraphs periodically revises them (WAR, wOBA/wRC+ constants, park factors). To pick those recalculations up, run a monthly cron on the server:

```cron
0 6 1 * *  cd /path/to/Baseball-Dashboard && .venv/bin/python baseball_csv_generator.py --start 1871 --force
```

(Under Docker: `docker compose exec baseball-dashboard python baseball_csv_generator.py --start 1871 --force`.)

### Migrating an existing deployment

If your checkout predates the CSVs leaving git, **pulling this change deletes
the tracked CSVs from the working tree** (git removes files deleted upstream).
Stash the data aside first, then restore it:

```bash
mkdir -p /tmp/bb-data && cp -a team_* qualified_* all_* /tmp/bb-data/
git pull
cp -a /tmp/bb-data/* .
```

The directories are gitignored afterwards, so the restored files stay put.

### Tests

`tests/fixtures/` carries a small frozen snapshot of the seasons the test
suite exercises, so `pytest` (and CI) runs offline and deterministically —
it's copied into the data directories on first run, never overwriting real
data.

## Configuration

Edit `config.json` to change:

| Key | Default | Description |
|---|---|---|
| `current_year` | `2026` | Latest season shown in dropdowns |
| `update_interval` | `14400` | Seconds between live-data refreshes (watch mode) |
| `request_delay` | `5` | Seconds between pybaseball requests |
| `*_dir` keys | various | Directories where CSVs are stored |

Environment variables for `app.py` / `launcher.sh`:

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address — set `0.0.0.0` to serve on the network |
| `PORT` | `8050` | Listen port |
| `DASH_DEBUG` | off | Set `1` to enable the dev reloader and Werkzeug debugger (never in production — the debugger allows code execution) |

## Data sources

Stats are sourced from [FanGraphs](https://www.fangraphs.com/) via [pybaseball](https://pypi.org/project/pybaseball/). Charts are built with [Plotly](https://plotly.com/python/) inside a [Dash](https://dash.plotly.com/) app.

## License

MIT
