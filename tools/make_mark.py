#!/usr/bin/env python3
"""The site mark: a baseball with curved seams and 4 square-ended stitches per seam,
tilted 45 degrees (rotation baked into the coordinates). Prints web/static/favicon.svg
and the header <svg> in web/templates/base.html; then run tools/make_icons.py."""
import math


def f(x):
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def rot(x, y, deg=-45.0):
    a = math.radians(deg)
    dx, dy = x - 12, y - 12
    return 12 + dx * math.cos(a) - dy * math.sin(a), 12 + dx * math.sin(a) + dy * math.cos(a)


def mark(r, tick, ticks=(0.2, 0.62), inner=0.27, edge_deg=41):
    edge = math.radians(edge_deg)
    ex, ey = -r * math.sin(edge), -r * math.cos(edge)
    ix = -inner * r
    c = (ix * ix - ex * ex - ey * ey) / (2 * (ix - ex))
    R = ix - c
    phi = math.asin(abs(ey) / R)
    seams, stitches = [], []
    for side in (-1, 1):
        cx = 12 + c if side < 0 else 12 - c
        sx, sy = rot(12 + (ex if side < 0 else -ex), 12 + ey)
        tx, ty = rot(12 + (ex if side < 0 else -ex), 12 - ey)
        sweep = 1 if side < 0 else 0
        seams.append(f"M{f(sx)} {f(sy)}A{f(R)} {f(R)} 0 0 {sweep} {f(tx)} {f(ty)}")
        for t in ticks:
            for sign in (1, -1):
                a = sign * t * phi
                ux, uy = math.cos(a), math.sin(a)
                if side > 0:
                    ux = -ux
                px, py = cx + R * ux, 12 + R * uy
                x1, y1 = rot(px - ux * tick, py - uy * tick)
                x2, y2 = rot(px + ux * tick, py + uy * tick)
                stitches.append(f"M{f(x1)} {f(y1)}L{f(x2)} {f(y2)}")
    return "".join(seams), "".join(stitches)


seam, stitch = mark(8.2, 1.45)
favicon = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#0a0e15"/>'
           '<g fill="none" stroke="#f97316" stroke-width="1.7">'
           f'<circle cx="12" cy="12" r="8.2"/><path d="{seam}"/>'
           f'<path stroke-width="1.1" d="{stitch}"/></g></svg>')
seam9, stitch9 = mark(9.2, 1.45 * 9.2 / 8.2)
header = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">'
          f'<circle cx="12" cy="12" r="9.2"/><path d="{seam9}"/>'
          f'<path stroke-width="1.2" d="{stitch9}"/></svg>')
if __name__ == "__main__":
    print(favicon)
    print(header)
