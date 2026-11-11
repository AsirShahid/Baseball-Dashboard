# Historic team names and leagues

`pipeline/historic_teams.json` gives names and leagues, season by season, for clubs the
modern tables do not cover: the National Association (1871-75), the 19th-century National
League, American Association, Union Association and Players' League, the Federal League
(1914-15) and the Negro Leagues (1920-48). Built 2026-11-11.

1. **1871-1900 and 1914-15:** each FanGraphs team-season is matched to a row of the Lahman
   database's `Teams.csv` by wins, losses and runs scored (greedy best match per season).
   All 431 team-seasons matched; the worst match differs by 4 wins or losses or 40 runs
   (FanGraphs and Lahman disagree slightly on some 19th-century records). Lahman's `name`
   is that season's name (Pittsburg Alleghenys 1882-90, Pirates from 1891).
2. **1920-48:** FanGraphs' Negro League stats come from the Seamheads Negro Leagues
   Database and mostly share its team codes. Each code-season's Seamheads team page gives
   the club's name that season and its league (Negro National League I and II, Eastern
   Colored League, American Negro League, East-West League, Negro Southern League,
   Negro American League, or Independent Clubs).
3. Seamheads has no page for three FanGraphs codes. AC (Bacharach Giants, 1923-29) is filled
   from its Wikipedia infobox (`MANUAL` in build.py). AG and CG (1933, 10 and 1 games) stay
   unnamed: no source ties the codes to a club.
4. Team colors (`pipeline/historic_colors.json`): only colors stated in the club's Wikipedia
   infobox or article (hex from `{{color box}}`, else the named color), never taken from a logo.
5. `python tools/team_names/build.py <scratch> pipeline/historic_teams.json`.

`pipeline/teams.py` uses the file for seasons up to 1900 and for clubs outside the AL and
NL that season; from 1901 the curated `TEAM_NAME_ERAS` and `TEAM_FULL_NAME` win.
