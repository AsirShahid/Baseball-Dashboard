# Baseball Dashboard

An interactive web application for visualizing baseball statistics. Build custom scatter plots — 2D or 3D — across hundreds of FanGraphs batting and pitching metrics for every team and player season from 1871 to present.

![wRC+ vs Barrel%](https://baseball.asir.dev/media/76f6cdc028d8719192f44385fbb26a5efabe730796a3aa741c7bc351.png)

## Features

- **Team and player views** — scatter any two (or three) stats against each other
- **Composite leaderboards** — a top-10 board for both teams *and* players, ranked by average percentile across the selected axes
- **Multi-season ranges** — drag the two-handled season slider to span several years (e.g. 2019–2026); counting stats (WAR, HR) are summed and rate stats (wRC+, ERA) are PA/IP-weighted, so the chart and leaderboard show one cumulative point per team/player
- **3D scatter plots** — add a Z-axis stat to switch to an interactive 3D chart
- **Composite rank coloring** — color-code markers by average percentile rank across all selected axes (red → yellow → green)
- **Mean reference lines / planes** — toggle average lines in 2D or semi-transparent planes in 3D
- **Team logos or colored markers** — display teams as logos or team-colored dots
- **Season filtering** — the slider only offers seasons where the chosen stat actually has data (e.g. Exit Velocity only appears from 2015 onward)
- **Shareable URLs** — every control is encoded in the URL so you can copy and share a specific view
- **Auto-fetch via pybaseball** — if a season's CSV is missing the app fetches it live on first access

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

## Updating data

Historical CSVs ship with the repo. To fetch a specific range of seasons:

```bash
source .venv/bin/activate

# Fetch 2025 and 2026 (skips seasons already on disk)
python baseball_csv_generator.py --start 2025 --end 2026

# Re-download a specific range regardless of what's cached
python baseball_csv_generator.py --start 2020 --end 2026 --force

# Fetch missing seasons then keep the current season refreshing every 4 h
python baseball_csv_generator.py --start 2025 --watch
```

`launcher.sh` automatically runs the generator in `--watch` mode in the background, so the current season stays up to date while the dashboard is running. The dashboard re-reads a CSV whenever the file changes on disk, so refreshed data shows up without a restart.

### Live split vs. recalculations

The fetcher uses FanGraphs' **"Live Stats — Full Season"** split (`month=33`) for the in-progress season, so the current year includes the day's games in real time. Completed seasons use the standard full-season split (`month=0`), which is the only one FanGraphs serves for past years; a live-split request for a finished season automatically falls back to it.

Completed seasons are nearly static, but FanGraphs periodically revises them (WAR, wOBA/wRC+ constants, park factors). The **`.github/workflows/data-refresh.yml`** workflow re-downloads everything with `--force` on the 1st of each month and commits any changes, so those recalculations don't get missed. It can also be triggered manually (Actions → "Data refresh" → Run workflow) with a custom season range. If you'd rather run the bulk refresh on your own server (a single, politer IP toward FanGraphs), the equivalent is a monthly cron of `python baseball_csv_generator.py --start 1871 --force`.

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
