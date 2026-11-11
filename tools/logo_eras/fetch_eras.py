"""Build code -> dated primary-logo eras from sportslogos.net franchise pages
(pages.json from scrape_former.py), clipped to each code's seasons in our data
(spans.json), then fetch each logo's view page for the full PNG and download it."""
import json, re, time, os, urllib.request, urllib.parse, html as H
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
pages = json.load(open("pages.json"))
spans = {k: set(v) for k, v in json.load(open("spans.json")).items()}
SEL = {
    "ARI": ["50"], "ATL": ["51"], "BSN": ["1459", "1460", "1461", "81", "1462"], "MLN": ["84"],
    "BAL": ["52"], "SLB": ["88"], "MLA": ["85"], "BLA": ["80"], "BOS": ["1458", "53"],
    "CHC": ["54"], "CHI": ["1465"], "CHW": ["55"], "CIN": ["56"], "CLE": ["1454", "1455", "57", "6804"],
    "COL": ["58"], "DET": ["59"], "HOU": ["991", "4929"], "KCR": ["62"], "LAD": ["63"],
    "BRO": ["1463", "82", "1464"], "MIL": ["64"], "SEP": ["89"], "MIN": ["65"], "WSH": ["1813"],
    "WSA": ["79"], "TEX": ["77"], "NYM": ["67"], "NYY": ["68"], "NYH": ["1453"], "ATH": ["6921"],
    "OAK": ["69"], "KCA": ["83"], "PHA": ["87"], "PHI": ["70"], "PIT": ["71"], "STL": ["72"],
    "SDP": ["73"], "SFG": ["74"], "NYG": ["86"], "SEA": ["75"], "TBR": ["2535"], "TBD": ["2535"],
    "TOR": ["78"], "MIA": ["3637"], "FLA": ["3637"], "WSN": ["578"], "MON": ["66"],
    "LAA": ["6521"], "CAL": ["6521"], "ANA": ["6521"],
}


def primary(tid):
    for s in pages[tid]["sections"]:
        if "Primary Logos History" in s["head"] and "Dark" not in s["head"]:
            return s["cards"]
    return []


def section(tid, word):
    return [c for s in pages[tid]["sections"] if word in s["head"] for c in s["cards"]]


eras = {}
for code, tids in SEL.items():
    yrs = spans.get(code, set())
    rows, seen = [], set()
    for tid in tids:
        for c in primary(tid):
            if c["y0"] is None or c["view"] in seen:
                continue
            if not any(c["y0"] <= y <= c["y1"] for y in yrs):
                continue
            seen.add(c["view"])
            rows.append(dict(c, page=tid))
    rows.sort(key=lambda r: (r["y0"], r["y1"]))
    eras[code] = rows

# Cap logos for the eras whose primary is a Native American caricature
# (decided after visual review; filled in by a later pass).
caps = {}
for code, tids in SEL.items():
    if code in ("CLE", "BSN", "MLN", "ATL"):
        caps[code] = [dict(c, page=t) for t in tids for c in section(t, "Cap Logos") if c["y0"]]

need = {r["view"]: r for rows in list(eras.values()) + list(caps.values()) for r in rows}
print("codes", len(eras), "era logos", sum(map(len, eras.values())), "cap candidates", sum(map(len, caps.values())), "unique views", len(need), flush=True)
os.makedirs("views", exist_ok=True); os.makedirs("raw", exist_ok=True)
full = json.load(open("full.json")) if os.path.exists("full.json") else {}
for i, (view, r) in enumerate(need.items()):
    if view in full and os.path.exists(full[view]["file"]):
        continue
    vid = view.split("/")[3]
    try:
        req = urllib.request.Request("https://www.sportslogos.net" + urllib.parse.quote(view), headers=UA)
        s = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        m = re.search(r'https://content\.sportslogos\.net/logos/[^"\']*/full/[^"\']+\.(?:png|gif|jpg)', s)
        d = re.search(r'<meta name="description" content="([^"]*)"', s)
        desc = re.search(r'<div[^>]*id="?logoDescription"?[^>]*>(.*?)</div>', s, re.S)
        if not m:
            print("no full image", view, flush=True); time.sleep(0.6); continue
        url = m.group(0)
        ext = url.rsplit(".", 1)[1]
        fn = f"raw/{vid}.{ext}"
        time.sleep(0.4)
        data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        open(fn, "wb").write(data)
        full[view] = dict(url=url, file=fn, meta=H.unescape(d.group(1)) if d else "",
                          desc=H.unescape(re.sub(r"<[^>]+>", " ", desc.group(1))).strip()[:400] if desc else "")
    except Exception as e:
        print("fail", view, e, flush=True)
    if i % 25 == 0:
        json.dump(full, open("full.json", "w"), indent=1); print("progress", i, len(need), flush=True)
    time.sleep(0.6)
json.dump(full, open("full.json", "w"), indent=1)
json.dump(dict(eras=eras, caps=caps), open("eras_raw.json", "w"), indent=1)
print("done", len(full), "of", len(need), flush=True)
