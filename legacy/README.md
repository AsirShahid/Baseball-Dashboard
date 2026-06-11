# Legacy code

Earlier iterations of the dashboard, kept for reference. None of these are run
by `launcher.sh` and their dependencies (streamlit, matplotlib,
beautifulsoup4) are not in `requirements.txt`.

- `baseballdash.py` — first Dash prototype (uses the removed
  `app.run_server` API; will not run under Dash 3).
- `streamlit-dashboard.py` / `streamlit_launcher.sh` — the Streamlit version
  the current app replaced.
- `fangraphs_parser.py` — BeautifulSoup scraper for the retired
  `leaders.aspx` HTML tables, superseded by the FanGraphs JSON API client in
  `fangraphs_api.py`.
