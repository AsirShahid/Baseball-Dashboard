"""Build pipeline/historic_teams.json: names and leagues for clubs outside the
modern AL and NL tables, season by season.

Inputs (made in a scratch folder, see README.md):
  lahman_match.json  FanGraphs code-season -> Lahman Teams.csv row (1871-1900, 1914-15),
                     matched on wins, losses and runs (every team-season matched, cost <= 4)
  seamheads.json     FanGraphs code-season -> Seamheads Negro Leagues Database page (1920-48)

Output: {"CODE": [[first, last, name, league], ...]} with consecutive seasons merged.
"""
import json
import sys
from pathlib import Path

LAHMAN_LEAGUES = {"NA": "National Association", "NL": "National League", "AA": "American Association",
                  "UA": "Union Association", "PL": "Players' League", "FL": "Federal League",
                  "AL": "American League"}


# Clubs Seamheads has no page for under FanGraphs' code, from the club's
# Wikipedia infobox (league field).
MANUAL = {
    # https://en.wikipedia.org/wiki/Bacharach_Giants: ECL 1923-1928, ANL 1929
    ("AC", y): ("Bacharach Giants", "Eastern Colored League" if y <= 1928 else "American Negro League")
    for y in range(1923, 1930)
}


def main(scratch: Path, out: Path):
    seasons = dict(MANUAL)
    for key, row in json.loads((scratch / "lahman_match.json").read_text()).items():
        code, year = key.split(":")
        seasons[(code, int(year))] = (row["name"], LAHMAN_LEAGUES.get(row["lg"], row["lg"]))
    for key, row in json.loads((scratch / "seamheads.json").read_text()).items():
        code, year = key.split(":")
        if row.get("name") and (code, int(year)) not in MANUAL:
            seasons[(code, int(year))] = (row["name"], row.get("league") or "Independent Clubs")
    merged = {}
    for (code, year), (name, league) in sorted(seasons.items()):
        runs = merged.setdefault(code, [])
        if runs and runs[-1][2] == name and runs[-1][3] == league and runs[-1][1] == year - 1:
            runs[-1][1] = year
        else:
            runs.append([year, year, name, league])
    out.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    print(len(merged), "codes,", len(seasons), "team-seasons ->", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
