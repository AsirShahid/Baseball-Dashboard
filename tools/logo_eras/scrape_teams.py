import re, json, time, urllib.request, os, html as H
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
teams = {"TBR": "2535/Tampa-Bay-Rays-Logos", "MIA": "3637/Miami-Marlins-Logos", "HOU": "4929/Houston-Astros-Logos",
 "ARI": "50/Arizona-Diamondbacks-Logos", "ATL": "51/Atlanta-Braves-Logos", "BAL": "52/Baltimore-Orioles-Logos",
 "BOS": "53/Boston-Red-Sox-Logos", "CHC": "54/Chicago-Cubs-Logos", "CHW": "55/Chicago-White-Sox-Logos",
 "CIN": "56/Cincinnati-Reds-Logos", "WSN": "578/Washington-Nationals-Logos", "COL": "58/Colorado-Rockies-Logos",
 "DET": "59/Detroit-Tigers-Logos", "KCR": "62/Kansas-City-Royals-Logos", "LAD": "63/Los-Angeles-Dodgers-Logos",
 "MIL": "64/Milwaukee-Brewers-Logos", "MIN": "65/Minnesota-Twins-Logos", "LAA": "6521/Los-Angeles-Angels-Logos",
 "NYM": "67/New-York-Mets-Logos", "NYY": "68/New-York-Yankees-Logos", "CLE": "6804/Cleveland-Guardians-Logos",
 "ATH": "6921/Athletics-Logos", "PHI": "70/Philadelphia-Phillies-Logos", "PIT": "71/Pittsburgh-Pirates-Logos",
 "STL": "72/St-Louis-Cardinals-Logos", "SDP": "73/San-Diego-Padres-Logos", "SFG": "74/San-Francisco-Giants-Logos",
 "SEA": "75/Seattle-Mariners-Logos", "TEX": "77/Texas-Rangers-Logos", "TOR": "78/Toronto-Blue-Jays-Logos"}
out = {}
for code, path in teams.items():
    fn = f"html/{path.split('/')[0]}.html"
    if not os.path.exists(fn):
        req = urllib.request.Request(f"https://www.sportslogos.net/logos/list_by_team/{path}/", headers=UA)
        open(fn, "wb").write(urllib.request.urlopen(req, timeout=60).read()); time.sleep(1.0)
    s = open(fn, encoding="utf-8", errors="replace").read()
    s = s[s.find('id="sln-grid-view"'):]
    secs = re.split(r'<h3 class="cftr_browseHeading"[^>]*>', s)[1:]
    res = []
    for sec in secs:
        head = re.sub(r"\s+", " ", sec.split("</h3>")[0]).strip()
        for m in re.finditer(r'<a href="(/logos/view/[^"]+)"\s*title="([^"]+)".*?<img src="([^"]+)"', sec, re.S):
            t = H.unescape(m.group(2))
            y = re.search(r"\((\d{4})\s*-\s*(\d{4}|Pres)", t)
            res.append(dict(section=head, title=t, view=m.group(1), thumb=m.group(3),
                            y0=int(y.group(1)) if y else None,
                            y1=(None if not y else (2026 if y.group(2).startswith("Pres") else int(y.group(2))))))
    out[code] = res
json.dump(out, open("teams.json", "w"), indent=1)
for code, res in out.items():
    prim = [r for r in res if "Primary" in r["section"]]
    print(code, len(res), "primary", len(prim), "|", "; ".join(f"{r['title'].split(' Primary')[0]} {r['y0']}-{r['y1']}" for r in prim))
