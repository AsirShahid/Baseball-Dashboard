"""Process downloaded era logos into wt/Logos/eras/ + manifest.json and build
per-club review sheets.

- Primary logos come from sportslogos.net franchise histories (eras_raw.json).
- Eras whose primary is a Native American caricature are replaced by the cap
  logo the club wore those seasons (SUB below); a caricature cap carries the
  previous cap forward. Caps are letters on a cap-colour swatch, so the swatch
  is flooded out.
- Very dark logos (navy/black, unreadable on the dark theme) get a thin light
  outline.
"""
import json, os
from PIL import Image, ImageDraw, ImageFilter, ImageChops

E = json.load(open("eras_raw.json"))
full = json.load(open("full.json"))
spans = {k: sorted(v) for k, v in json.load(open("spans.json")).items()}
OUT = "wt/Logos/eras"
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith(".png"):
        os.remove(os.path.join(OUT, f))
MAX = 320

WHITE_BG = set(json.load(open("white_bg.json")))
caps = {code: sorted(rows, key=lambda c: (c["y0"], c["y1"])) for code, rows in E["caps"].items()}
# Index numbers refer to caps_<CODE>.png (sorted by first season).
SUB = {
    "CLE": dict(drop=[1928, 1929, 1933, 1939, 1946, 1948, 1949, 1973, 1979, 1986],
                add=[(1928, 14), (1933, 15), (1939, 18), (1958, 21), (1963, 23), (1965, 24),
                     (1970, 25), (1972, 26), (1973, 27), (1978, 28), (2002, 30), (2008, 34)]),
    # 1912-20 carry the 1911 Rustlers "B" (no Braves cap before 1915 except pinstripes).
    "BSN": dict(drop=[1912, 1916, 1929, 1945],
                add=[(1929, 4), (1932, 5), (1933, 7), (1934, 8), (1945, 18), (1946, 19)]),
    "MLN": dict(drop=[1953, 1956], add=[(1953, 0)]),
    "ATL": dict(drop=[1966, 1968, 1985], add=[(1966, 0), (1972, 1), (1981, 3)]),
}


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(p):
    """WCAG relative luminance; > 0.06 is ~2:1 contrast on the dark theme."""
    return 0.2126 * _lin(p[0]) + 0.7152 * _lin(p[1]) + 0.0722 * _lin(p[2])


def flood_border(im, thresh):
    """Flood the background from the image edge. Seeds only on pixels of the
    dominant edge colour, so a logo that touches the edge isn't flooded."""
    from collections import Counter
    w, h = im.size
    pts = [(x, 0) for x in range(0, w, 4)] + [(x, h - 1) for x in range(0, w, 4)] + \
          [(0, y) for y in range(0, h, 4)] + [(w - 1, y) for y in range(0, h, 4)]
    cols = Counter(im.getpixel(p) for p in pts if im.getpixel(p)[3] > 0)
    if not cols:
        return im
    bg = cols.most_common(1)[0][0]
    for p in pts:
        q = im.getpixel(p)
        if q[3] > 0 and sum(abs(a - b) for a, b in zip(q, bg)) <= thresh:
            ImageDraw.floodfill(im, p, (0, 0, 0, 0), thresh=thresh)
    return im


def clean(fn, is_cap=False, white_bg=False):
    im = Image.open(fn).convert("RGBA")
    cap_sw = None
    w, h = im.size
    corners = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    boxed = all(c[3] > 200 for c in corners)    # opaque background, judged on the file as served
    if is_cap:
        bb0 = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
        if bb0:
            im = im.crop(bb0)   # flood from the swatch edge, not a transparent margin
        w, h = im.size
    if boxed or is_cap:
        im = flood_border(im, 70 if is_cap else 40)
    if white_bg:
        # Drawn on white paper: white trapped in counters/loops is background
        # too (reviewed per logo; white that is part of a design stays).
        px = im.load()
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                m = min(r, g, b)
                if a and m >= 205:
                    px[x, y] = (r, g, b, 0 if m >= 235 else round(a * (235 - m) / 30))
    if is_cap:
        # Cap swatches have a thin dark frame: flood the swatch colour too,
        # seeded just inside the frame.
        w, h = im.size
        ins = max(4, round(min(w, h) * 0.015))
        seeds = [(x, ins) for x in range(ins, w - ins, 6)] + [(x, h - 1 - ins) for x in range(ins, w - ins, 6)] + \
                [(ins, y) for y in range(ins, h - ins, 6)] + [(w - 1 - ins, y) for y in range(ins, h - ins, 6)]
        from collections import Counter
        sw = Counter(im.getpixel(p)[:3] for p in seeds if im.getpixel(p)[3] > 200).most_common(1)
        cap_sw = sw[0][0] if sw else (16, 24, 40)
        for p in seeds:          # connected swatch areas (panels, side bars)
            if im.getpixel(p)[3] > 0:
                ImageDraw.floodfill(im, p, (0, 0, 0, 0), thresh=60)
        im = flood_border(im, 70)
        # The dominant swatch colour also inside enclosed counters (the
        # holes of a B), anywhere in the image.
        px = im.load()
        for k, _ in sw:
            for y in range(h):
                for x in range(w):
                    r, g, b, a = px[x, y]
                    if a and abs(r - k[0]) + abs(g - k[1]) + abs(b - k[2]) < 70:
                        px[x, y] = (0, 0, 0, 0)
        # Crop on an eroded mask so 1–2 px frame remnants don't widen the box,
        # then clear anything outside it.
        m = im.getchannel("A").point(lambda v: 255 if v > 100 else 0).filter(ImageFilter.MinFilter(5))
        x0, y0, x1, y1 = m.getbbox()
        im = im.crop((max(0, x0 - 3), max(0, y0 - 3), min(w, x1 + 3), min(h, y1 + 3)))
    a = im.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    bb = a.getbbox()
    if bb:
        im = im.crop(bb)
    k = MAX / max(im.size)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    # A white cap letter vanishes on the light theme: stroke it in the cap's
    # own colour (how it looked on the cap).
    if cap_sw is not None:
        d0 = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
        op = [q for q in d0 if q[3] > 128]
        if sum(1 for q in op if min(q[:3]) >= 215) / max(1, len(op)) > 0.5:
            pad = 10
            base = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
            base.paste(im, (pad, pad), im)
            mask = base.getchannel("A").point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MaxFilter(9))
            stroke = Image.new("RGBA", base.size, cap_sw + (0,))
            stroke.putalpha(mask)
            im = Image.alpha_composite(stroke, base)
            im = im.crop(im.getchannel("A").getbbox())
            k = MAX / max(im.size)
            im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    # Dark logo? share of opaque pixels that read on a dark background.
    px = [p for p in im.get_flattened_data() if p[3] > 128] if hasattr(im, 'get_flattened_data') else [p for p in im.getdata() if p[3] > 128]
    light = sum(1 for p in px if rel_lum(p) > 0.06) / max(1, len(px))
    outlined = light < 0.15
    if outlined:
        pad = 10
        base = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
        base.paste(im, (pad, pad), im)
        mask = base.getchannel("A").point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MaxFilter(7))
        halo = Image.new("RGBA", base.size, (214, 218, 226, 0))
        halo.putalpha(mask.point(lambda v: 210 if v else 0))
        im = Image.alpha_composite(halo, base)
        im = im.crop(im.getchannel("A").getbbox())
        k = MAX / max(im.size)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    return im, boxed, outlined


manifest, review = {}, []
for code, rows in E["eras"].items():
    sub = SUB.get(code, {})
    items, seen = [], set()
    for r in rows:
        if r["y0"] in seen or r["y0"] in sub.get("drop", []):
            continue
        seen.add(r["y0"])
        items.append(dict(y0=r["y0"], view=r["view"], title=r["title"], cap=False))
    for y0, idx in sub.get("add", []):
        c = caps[code][idx]
        items.append(dict(y0=y0, view=c["view"], title=c["title"], cap=True))
    items.sort(key=lambda r: r["y0"])
    first, last = spans[code][0], spans[code][-1]
    out = []
    for i, it in enumerate(items):
        info = full.get(it["view"])
        if not info:
            print("missing image", code, it["y0"], it["view"]); continue
        im, boxed, outlined = clean(info["file"], it["cap"], f"{code}:{it['y0']}" in WHITE_BG)
        y0 = max(it["y0"], first) if i == 0 else it["y0"]
        nxt = items[i + 1]["y0"] - 1 if i + 1 < len(items) else None
        y1 = nxt if nxt is not None else (None if last == 2026 else last)
        name = f"eras/{code.lower()}-{y0}{'-cap' if it['cap'] else ''}.png"
        im.save(f"wt/Logos/{name}", optimize=True)
        out.append([y0, y1, name])
        review.append(dict(code=code, y0=y0, y1=y1, title=it["title"], file=name, boxed=boxed,
                           cap=it["cap"], outlined=outlined, src=info["url"]))
    manifest[code] = out
json.dump(manifest, open(f"{OUT}/manifest.json", "w"), indent=1, sort_keys=True)
json.dump(review, open("review.json", "w"), indent=1)
print("codes", len(manifest), "logos", sum(map(len, manifest.values())),
      "caps", sum(r["cap"] for r in review), "outlined", sum(r["outlined"] for r in review))

cell, lab = 120, 26
codes = list(manifest)
per_sheet = 8
for si in range(0, len(codes), per_sheet):
    chunk = codes[si:si + per_sheet]
    ncol = min(12, max(len(manifest[c]) for c in chunk))
    rows_needed = sum((len(manifest[c]) + ncol - 1) // ncol for c in chunk)
    for bg, tag in (((15, 18, 24), "dark"), ((246, 247, 249), "light")):
        sheet = Image.new("RGB", (60 + ncol * cell, rows_needed * (cell + lab)), bg)
        d = ImageDraw.Draw(sheet)
        row = 0
        for c in chunk:
            its = [r for r in review if r["code"] == c]
            for i, r in enumerate(its):
                if i % ncol == 0:
                    if i:
                        row += 1
                    d.text((4, row * (cell + lab) + cell // 2), c, fill=(128, 128, 128))
                im = Image.open(f"wt/Logos/{r['file']}"); im.thumbnail((cell - 16, cell - 16))
                x = 60 + (i % ncol) * cell; y = row * (cell + lab)
                sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2), im)
                d.text((x + 4, y + cell + 2), f"{r['y0']}-{r['y1'] or ''}{' CAP' if r['cap'] else ''}", fill=(128, 128, 128))
            row += 1
        sheet.save(f"sheet_{si // per_sheet:02d}_{tag}.png")
print("sheets", (len(codes) + per_sheet - 1) // per_sheet)
