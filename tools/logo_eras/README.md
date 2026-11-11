# Dated team logos (Logos/eras)

How `Logos/eras/*.png` and `manifest.json` were built (2026-11-11). Run from a
scratch directory with a `wt/` checkout of this repo next to the scripts:

1. `scrape_teams.py`: the 30 franchise pages on sportslogos.net (primary-logo
   history, cap logos) into `teams.json` / `html/`.
2. `scrape_former.py`: former-name pages (Highlanders, Naps, Expos, Colt .45s,
   Boston/Milwaukee Braves, Brooklyn, NY Giants, Senators, Browns, A's, ...)
   into `pages.json`.
3. `spans.json`: each team code's seasons in our data, after
   `apply_team_identity` (built in the app image from team_batting).
4. `fetch_eras.py`: selects each code's eras (clipped to its seasons), fetches
   every logo's view page for the full PNG (`full.json`, `raw/`).
5. `process.py`: cleans each image, saves 256 px palette PNGs and writes the
   manifest. Decisions encoded there:
   - Every era uses the club's own primary, including Cleveland's and the
     Braves' Native American logos (the first version swapped in cap
     letters; reverted 2026-11-11). `SUB` can still swap an era for a cap
     logo; it is empty.
   - `white_bg.json`: logos drawn on white paper whose enclosed white is
     background (reviewed one by one); other logos keep their white.
   - Very dark logos get a light outline (dark theme); white cap letters a
     stroke in the cap colour (light theme).
