"""Add Negro League and Federal League logos to Logos/eras (2026-11-11).

sportslogos.net has no section for these leagues, so the images come from
Wikipedia and Wikimedia Commons. Each was checked by eye; rejected candidates
(team photos, a jersey photo, user drawings of whole caps, blurry crops, and
modern recreations where a period logo exists) are listed in README.md.

    python tools/logo_eras/historic.py <dir with logos/raw and logos_*.json>

Writes Logos/eras/<code>-<first>.png, adds the eras to manifest.json and the
provenance (source page, license, author) to historic_sources.json.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
ERAS = ROOT / "Logos" / "eras"
MAX = 320

# (code, first, last, raw file, all near-white is background)
ACCEPT = [
    ("BCA", 1932, 1932, "BCA-1932.png", False),
    ("AC", 1923, 1929, "AC-1923.png", False),
    ("BEG", 1938, 1948, "BEG-1938.png", False),
    ("BBB", 1924, 1948, "BBB-1924-logo.png", False),
    ("CBE", 1943, 1948, "CBE-1943.png", False),
    ("DS", 1920, 1931, "DS-1920.png", False),
    ("DW", 1932, 1932, "DW-1932.jpg", False),
    ("HIL", 1923, 1932, "HIL-1923-uniform.png", True),
    ("HG", 1929, 1948, "HG-1929.png", False),
    ("CWH", 1914, 1915, "CWH-1914.png", False),
    ("KCP", 1914, 1914, "KCP-1914.png", False),
    ("NWK", 1915, 1915, "NWK-1915.png", False),
    ("SLT", 1914, 1915, "SLT-1914.jpg", True),
    ("KCM", 1920, 1948, "KCM-1920.gif", False),
    ("IC", 1948, 1948, "IC-1948.png", False),
]


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(p):
    return 0.2126 * _lin(p[0]) + 0.7152 * _lin(p[1]) + 0.0722 * _lin(p[2])


def flood_border(im, thresh):
    """Flood the background from the edge (as process.py does)."""
    w, h = im.size
    pts = [(x, 0) for x in range(0, w, 2)] + [(x, h - 1) for x in range(0, w, 2)] + \
          [(0, y) for y in range(0, h, 2)] + [(w - 1, y) for y in range(0, h, 2)]
    cols = Counter(im.getpixel(p) for p in pts if im.getpixel(p)[3] > 0)
    if not cols:
        return im
    bg = cols.most_common(1)[0][0]
    for p in pts:
        q = im.getpixel(p)
        if q[3] > 0 and sum(abs(a - b) for a, b in zip(q, bg)) <= thresh:
            ImageDraw.floodfill(im, p, (0, 0, 0, 0), thresh=thresh)
    return im


def scale(im, size):
    k = size / max(im.size)
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def clean(path: Path, white_bg: bool):
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    if max(w, h) < 200:                      # small sources: upscale before flooding
        im = scale(im, 400)
        w, h = im.size
    corners = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    if all(c[3] > 200 for c in corners):
        im = flood_border(im, 60)
    if white_bg:
        px = im.load()
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                m = min(r, g, b)
                if a and m >= 205:
                    px[x, y] = (r, g, b, 0 if m >= 235 else round(a * (235 - m) / 30))
    bb = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bb:
        im = im.crop(bb)
    im = scale(im, MAX)
    # Very dark logo: a thin light outline so it shows on the dark page.
    px = [p for p in im.getdata() if p[3] > 128]
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
        im = scale(im.crop(im.getchannel("A").getbbox()), MAX)
    return im, outlined


def main(src: Path):
    meta = {}
    for f in ("logos_A.json", "logos_B.json"):
        for e in json.loads((src / f).read_text()):
            meta[Path(e["file"]).name] = e
    manifest = json.loads((ERAS / "manifest.json").read_text())
    sources_path = ERAS / "historic_sources.json"
    sources = json.loads(sources_path.read_text()) if sources_path.exists() else {}
    for code, first, last, raw, white_bg in ACCEPT:
        im, outlined = clean(src / "logos" / "raw" / raw, white_bg)
        name = f"{code.lower()}-{first}.png"
        out = im.convert("RGBA")
        if max(out.size) > 256:
            out = scale(out, 256)
        out.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(ERAS / name, optimize=True)
        rows = [r for r in manifest.get(code, []) if r[2] != f"eras/{name}"]
        rows.append([first, last, f"eras/{name}"])
        manifest[code] = sorted(rows, key=lambda r: r[0])
        e = meta[raw]
        sources[f"eras/{name}"] = {"code": code, "seasons": [first, last], "source_page": e["source_page"],
                                   "image_url": e["image_url"], "license": e["license"], "author": e.get("author"),
                                   "kind": e["kind"], "recreation": bool(e.get("recreation")),
                                   "era_evidence": e.get("era_evidence"), "outlined": outlined}
        print(f"{code:4} {first}-{last} {name:16} {out.size} outlined={outlined}")
    (ERAS / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    sources_path.write_text(json.dumps(sources, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
