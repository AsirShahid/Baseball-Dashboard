import re, json, time, urllib.request, os, html as H, glob
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
former = ["1458","1459","1462","81","5933","1460","1461","82","1464","1463","1465","1456","1454","57","1455","991","83","84","85","1477","66","86","1453","69","87","89","88","80","90","79","1813","992","49","592","591","922","60","76","61"]
for tid in former:
    fn = f"html/{tid}.html"
    if not os.path.exists(fn):
        req = urllib.request.Request(f"https://www.sportslogos.net/logos/list_by_team/{tid}/x/", headers=UA)
        try:
            open(fn, "wb").write(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            print("fail", tid, e)
        time.sleep(1.0)
def parse(fn):
    s = open(fn, encoding="utf-8", errors="replace").read()
    title = re.search(r"<title>([^<]*)</title>", s); title = H.unescape(title.group(1)) if title else ""
    s = s[s.find('id="sln-grid-view"'):]
    secs = re.split(r'<h3 class="cftr_browseHeading"[^>]*>', s)[1:]
    out = []
    for sec in secs:
        head = H.unescape(re.sub(r"\s+", " ", sec.split("</h3>")[0]).strip())
        cards = []
        for m in re.finditer(r'<a href="(/logos/view/[^"]+)"\s*title="([^"]+)".*?<img src="([^"]+)"', sec, re.S):
            t = H.unescape(m.group(2))
            y = re.search(r"\((\d{4})\s*-\s*(\d{4}|Pres)", t)
            cards.append(dict(title=t, view=m.group(1), thumb=m.group(3), y0=int(y.group(1)) if y else None,
                              y1=None if not y else (2026 if y.group(2).startswith("Pres") else int(y.group(2)))))
        out.append(dict(head=head, cards=cards))
    return title, out
allp = {}
for fn in sorted(glob.glob("html/*.html")):
    tid = fn.split("/")[-1][:-5]
    if not tid.isdigit(): continue
    title, secs = parse(fn)
    allp[tid] = dict(title=title, sections=secs)
json.dump(allp, open("pages.json", "w"), indent=1)
for tid in former:
    p = allp.get(tid)
    if not p: continue
    prim = next((s for s in p["sections"] if "Primary Logos" in s["head"]), None)
    print(tid, p["title"][:45], "|", prim["head"][:40] if prim else None, "|", "; ".join(f"{c['y0']}-{c['y1']}" for c in (prim["cards"] if prim else [])), "| sections:", [s["head"][-28:] for s in p["sections"]][:6])
