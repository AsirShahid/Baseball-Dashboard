"""Small server-rendered SVG charts, so pages need no charting library."""

from __future__ import annotations

from markupsafe import Markup, escape


def _scale(lo, hi, size, pad=0.0):
    span = (hi - lo) or 1.0
    return lambda value: pad + (value - lo) / span * (size - 2 * pad)


def game_bars(values, wins=None, average=None, width=720, height=120, labels=None):
    """One bar per game, green for a win and red for a loss, with the average."""
    values = [0 if value is None else value for value in values]
    if not values:
        return Markup("")
    top = max(max(values), average or 0, 1)
    gap = 2 if len(values) <= 60 else 1
    bar = max(2.0, (width - gap * (len(values) - 1)) / len(values))
    y = _scale(0, top, height - 16)
    parts = [f'<svg class="chart bars" viewBox="0 0 {width} {height}" role="img" '
             f'preserveAspectRatio="none" aria-label="Game by game">']
    for index, value in enumerate(values):
        tall = y(value)
        state = "" if wins is None else (" w" if wins[index] else " l")
        title = f"<title>{escape(labels[index])}</title>" if labels else ""
        parts.append(
            f'<rect class="bar{state}" x="{index * (bar + gap):.1f}" y="{height - tall:.1f}" '
            f'width="{bar:.1f}" height="{max(tall, 1):.1f}" rx="1">{title}</rect>'
        )
    if average is not None:
        level = height - y(average)
        parts.append(f'<line class="avg" x1="0" x2="{width}" y1="{level:.1f}" y2="{level:.1f}"/>')
        parts.append(f'<text class="avg-label" x="{width - 4}" y="{max(level - 4, 10):.1f}" '
                     f'text-anchor="end">avg {average:.1f}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def trend(series, x_labels, width=720, height=220, percent=False, digits=1):
    """Lines over a shared x axis. series: [(name, color, [value or None])]."""
    points = [value for _, _, values in series for value in values if value is not None]
    if not points or not x_labels:
        return Markup("")
    lo, hi = min(points), max(points)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    left, right, top, bottom = 44, 12, 10, 24
    plot_w, plot_h = width - left - right, height - top - bottom
    count = len(x_labels)

    def x(index):
        return left + (plot_w / 2 if count == 1 else index / (count - 1) * plot_w)

    def y(value):
        return top + plot_h - (value - lo) / ((hi - lo) or 1) * plot_h

    def show(value):
        return f"{value * 100:.{digits}f}" if percent else f"{value:.{digits}f}"

    parts = [f'<svg class="chart trend" viewBox="0 0 {width} {height}" role="img">']
    for step in range(5):
        value = lo + (hi - lo) * step / 4
        level = y(value)
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{level:.1f}" y2="{level:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 6}" y="{level + 3:.1f}" text-anchor="end">{show(value)}</text>')
    every = max(1, round(count / 10))
    for index, label in enumerate(x_labels):
        if index % every == 0 or index == count - 1:
            parts.append(f'<text class="tick" x="{x(index):.1f}" y="{height - 6}" text-anchor="middle">{escape(label)}</text>')
    for name, color, values in series:
        run, runs = [], []
        for index, value in enumerate(values):
            if value is None:
                if run:
                    runs.append(run)
                run = []
            else:
                run.append((x(index), y(value), value, x_labels[index]))
        if run:
            runs.append(run)
        for run in runs:
            path = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}" for i, (px, py, _, _) in enumerate(run))
            parts.append(f'<path class="line" d="{path}" stroke="{escape(color)}"/>')
            for px, py, value, label in run:
                parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{escape(color)}">'
                             f'<title>{escape(name)} {escape(label)}: {show(value)}</title></circle>')
    parts.append("</svg>")
    return Markup("".join(parts))


def spark(values, width=96, height=24):
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return Markup("")
    x = _scale(0, len(values) - 1, width, 2)
    y = _scale(min(values), max(values), height, 3)
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{height - y(v):.1f}" for i, v in enumerate(values))
    return Markup(f'<svg class="chart spark" viewBox="0 0 {width} {height}" width="{width}" '
                  f'height="{height}"><path class="line" d="{path}"/></svg>')


def season_bars(seasons, series, width=1240, height=170, digits=1, unit=""):
    """Stacked bars per season. series: [(name, color, {season: value})]. Negative values hang below 0."""
    if not seasons:
        return Markup("")
    totals_hi = [sum(max(v.get(s) or 0, 0) for _, _, v in series) for s in seasons]
    totals_lo = [sum(min(v.get(s) or 0, 0) for _, _, v in series) for s in seasons]
    hi, lo = max(totals_hi + [1]), min(totals_lo + [0])
    lo = 0.0 if lo > -0.05 else lo
    left, bottom, top = 34, 20, 8
    plot_h = height - bottom - top
    gap = 3 if len(seasons) <= 30 else 1
    bar = max(3.0, (width - left - gap * (len(seasons) - 1)) / len(seasons))

    def y(value):
        return top + (hi - value) / ((hi - lo) or 1) * plot_h

    parts = [f'<svg class="chart sbars" viewBox="0 0 {width} {height}" role="img" aria-label="By season">']
    for value in (lo, 0, hi / 2, hi):
        if value == lo and lo == 0:
            continue
        parts.append(f'<line class="grid" x1="{left}" x2="{width}" y1="{y(value):.1f}" y2="{y(value):.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 5}" y="{y(value) + 3:.1f}" text-anchor="end">{value:.{0 if abs(hi) >= 10 else 1}f}</text>')
    every = max(1, round(len(seasons) / 12))
    for index, season in enumerate(seasons):
        x = left + index * (bar + gap)
        up, down = 0.0, 0.0
        tip = [str(season)]
        for name, color, values in series:
            v = values.get(season)
            if v is None:
                continue
            tip.append(f"{name} {v:.{digits}f}{unit}")
            if v >= 0:
                y0, y1 = y(up + v), y(up)
                up += v
            else:
                y0, y1 = y(down), y(down + v)
                down += v
            parts.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar:.1f}" height="{max(y1 - y0, 0.8):.1f}" '
                         f'rx="1.5" fill="{escape(color)}"/>')
        parts.append(f'<rect class="hitbox" x="{x:.1f}" y="{top}" width="{bar:.1f}" height="{plot_h}" '
                     f'fill="transparent"><title>{escape(", ".join(tip))}</title></rect>')
        if index % every == 0 or index == len(seasons) - 1:
            parts.append(f'<text class="tick" x="{x + bar / 2:.1f}" y="{height - 5}" text-anchor="middle">'
                         f'{"\u2019" + str(season)[2:] if len(seasons) > 12 else season}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))
