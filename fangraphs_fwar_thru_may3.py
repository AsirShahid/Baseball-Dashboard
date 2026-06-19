"""
fangraphs_fwar_thru_may3.py
----------------------------
Downloads FanGraphs batting fWAR leaderboard data for every season
from 2010 through the current year, each filtered to March 1 – May 3
of that season (mimicking the "through May 3" cutoff).

Output: fwar_thru_may3.csv  (one row per player-season)

Requirements:
    pip install requests pandas
"""

import time
import requests
import pandas as pd
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
START_YEAR  = 2010
END_YEAR    = datetime.today().year   # inclusive
START_MD    = "03-01"                 # March 1
END_MD      = "05-03"                 # May  3
QUAL        = "y"                     # FanGraphs qualified default (≈ ~1 PA/team game)
STAT_TYPE   = 8                       # Dashboard / fWAR columns
OUTPUT_FILE = "fwar_thru_may3.csv"
SLEEP_SEC   = 1.5                     # polite crawl delay between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.fangraphs.com/",
    "Accept": "application/json, text/plain, */*",
}

API_URL = "https://www.fangraphs.com/api/leaders/major-league/data"

# ── Fetch one season ──────────────────────────────────────────────────────────
def fetch_season(year: int) -> pd.DataFrame:
    start_date = f"{year}-{START_MD}"
    end_date   = f"{year}-{END_MD}"

    params = {
        "pos":       "all",
        "stats":     "bat",
        "lg":        "all",
        "qual":      QUAL,
        "season":    year,
        "season1":   year,
        "ind":       0,
        "type":      STAT_TYPE,
        "month":     1000,          # custom date range
        "startdate": start_date,
        "enddate":   end_date,
        "team":      0,
        "pageitems": 500,           # large page to get all qualifiers at once
        "pagenum":   1,
    }

    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    payload = resp.json()

    # FanGraphs returns {"data": [...], "count": N}
    records = payload.get("data", payload)
    if not records:
        print(f"  {year}: no data returned")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df.insert(0, "Season", year)
    df.insert(1, "DateRange", f"{start_date} to {end_date}")
    print(f"  {year}: {len(df)} rows, {len(df.columns)} columns")
    return df


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    all_frames = []

    print(f"Downloading fWAR leaderboard {START_YEAR}–{END_YEAR} (Mar 1 → May 3)…\n")
    for year in range(START_YEAR, END_YEAR + 1):
        try:
            df = fetch_season(year)
            if not df.empty:
                all_frames.append(df)
        except requests.HTTPError as e:
            print(f"  {year}: HTTP error — {e}")
        except Exception as e:
            print(f"  {year}: unexpected error — {e}")

        time.sleep(SLEEP_SEC)

    if not all_frames:
        print("\nNo data collected — check network / FanGraphs availability.")
        return

    combined = pd.concat(all_frames, ignore_index=True)

    # ── Tidy up column names (FanGraphs returns camelCase keys) ────────────────
    # Rename the most useful columns to human-friendly names when present
    rename_map = {
        "PlayerName":     "Name",
        "playerid":       "FG_ID",
        "teamid":         "TeamID",
        "Team":           "Team",
        "Age":            "Age",
        "G":              "G",
        "PA":             "PA",
        "WAR":            "fWAR",
        "Off":            "Off",
        "Def":            "Def",
        "BsR":            "BsR",
        "RAR":            "RAR",
        "Dollars":        "Dollars",
        "WPA":            "WPA",
        "HR":             "HR",
        "AVG":            "AVG",
        "OBP":            "OBP",
        "SLG":            "SLG",
        "wOBA":           "wOBA",
        "wRC+":           "wRC+",
    }
    combined.rename(columns={k: v for k, v in rename_map.items() if k in combined.columns},
                    inplace=True)

    # Sort by Season desc, fWAR desc
    war_col = "fWAR" if "fWAR" in combined.columns else "WAR"
    sort_cols = ["Season", war_col] if war_col in combined.columns else ["Season"]
    combined.sort_values(sort_cols, ascending=[False, False], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved {len(combined)} rows × {len(combined.columns)} columns → {OUTPUT_FILE}")
    print("\nColumn list:")
    print(combined.columns.tolist())
    print("\nSample (top 10 rows):")
    display_cols = ["Season", "Name", "Team", "G", "PA", "fWAR" if "fWAR" in combined.columns else "WAR"]
    display_cols = [c for c in display_cols if c in combined.columns]
    print(combined[display_cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
