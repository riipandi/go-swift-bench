"""Grafik SVG sederhana (garis dan batang) tanpa dependency; konversi ke PNG lewat qlmanage bawaan macOS bila ada.

Palet (aman untuk buta warna, Okabe-Ito): Go = biru, Swift = oranye-merah.
"""
import html
import math
import os
import shutil
import subprocess
import tempfile

PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"]
COLORS = {"go": "#0072B2", "swift": "#D55E00"}
W, H = 900, 520
ML, MR, MT, MB = 80, 160, 50, 60


def nice_ticks(lo, hi, n=6):
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    start = math.floor(lo / step) * step
    ticks = []
    t = start
    while t <= hi + step * 0.5:
        ticks.append(round(t, 10))
        t += step
    return ticks


def fmtv(v):
    if abs(v) >= 1e6:
        return "%.1fM" % (v / 1e6)
    if abs(v) >= 1e4:
        return "%.0fk" % (v / 1e3)
    if abs(v) >= 100 or v == int(v):
        return "%d" % round(v)
    return "%.2g" % v


def _frame(title, xlabel, ylabel, extra=""):
    return ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="Helvetica, Arial, sans-serif" font-size="12">' % (W, H, W, H),
            '<rect width="100%" height="100%" fill="#fff"/>',
            '<text x="%d" y="26" font-size="15" font-weight="bold">%s</text>' % (ML, html.escape(title)),
            '<text x="%d" y="%d" text-anchor="middle">%s</text>' % ((ML + W - MR) // 2, H - 14, html.escape(xlabel)),
            '<text transform="translate(18,%d) rotate(-90)" text-anchor="middle">%s</text>' % ((MT + H - MB) // 2, html.escape(ylabel))]


def line_chart(path, title, xlabel, ylabel, series, logx=False, xticks=None, note=None):
    """series: {nama: [(x, y), ...]}; garis + titik."""
    pts = [p for s in series.values() for p in s if p[1] is not None]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = 0.0, max(ys) * 1.08 or 1.0
    yt = nice_ticks(ylo, yhi)
    yhi = max(yt[-1], yhi)
    fx = (lambda x: math.log(x)) if logx else (lambda x: x)
    x0, x1 = fx(xlo), fx(xhi)
    if x1 == x0:
        x1 = x0 + 1
    px = lambda x: ML + (fx(x) - x0) / (x1 - x0) * (W - ML - MR)
    py = lambda y: H - MB - (y - ylo) / (yhi - ylo) * (H - MT - MB)
    out = _frame(title, xlabel, ylabel)
    for t in yt:
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ddd"/><text x="%d" y="%.1f" text-anchor="end">%s</text>' % (ML, py(t), W - MR, py(t), ML - 6, py(t) + 4, fmtv(t)))
    for t in (xticks or sorted(set(xs))):
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#eee"/><text x="%.1f" y="%d" text-anchor="middle">%s</text>' % (px(t), MT, px(t), H - MB, px(t), H - MB + 16, fmtv(t)))
    out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="#888"/>' % (ML, MT, W - ML - MR, H - MT - MB))
    for i, (name, s) in enumerate(series.items()):
        col = COLORS.get(name.split()[0].lower(), PALETTE[i % len(PALETTE)])
        s = [p for p in s if p[1] is not None]
        if not s:
            continue
        out.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (col, " ".join("%.1f,%.1f" % (px(x), py(y)) for x, y in sorted(s))))
        for x, y in s:
            out.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>' % (px(x), py(y), col))
        out.append('<rect x="%d" y="%d" width="12" height="12" fill="%s"/><text x="%d" y="%d">%s</text>' % (W - MR + 14, MT + 6 + i * 20, col, W - MR + 32, MT + 17 + i * 20, html.escape(name)))
    if note:
        out.append('<text x="%d" y="%d" font-size="11" fill="#555">%s</text>' % (ML, H - 34, html.escape(note)))
    out.append("</svg>")
    open(path, "w").write("\n".join(out))
    return path


def bar_chart(path, title, ylabel, groups, series_names, values, note=None):
    """groups: label sumbu x; series_names: ['go','swift']; values[g][s] = angka atau None."""
    allv = [v for g in values for v in g if v is not None]
    if not allv:
        return None
    yt = nice_ticks(0, max(allv) * 1.1)
    yhi = yt[-1]
    py = lambda y: H - MB - (y / yhi) * (H - MT - MB)
    out = _frame(title, "", ylabel)
    for t in yt:
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ddd"/><text x="%d" y="%.1f" text-anchor="end">%s</text>' % (ML, py(t), W - MR, py(t), ML - 6, py(t) + 4, fmtv(t)))
    gw = (W - ML - MR) / max(1, len(groups))
    bw = gw * 0.7 / max(1, len(series_names))
    for gi, g in enumerate(groups):
        gx = ML + gi * gw + gw * 0.15
        for si, sn in enumerate(series_names):
            v = values[gi][si]
            if v is None:
                continue
            col = COLORS.get(sn, PALETTE[si % len(PALETTE)])
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"><title>%s %s: %s</title></rect>' % (gx + si * bw, py(v), bw - 2, H - MB - py(v), col, html.escape(g), sn, fmtv(v)))
        out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="11" transform="rotate(-25 %.1f %d)">%s</text>' % (gx + gw * 0.35, H - MB + 16, gx + gw * 0.35, H - MB + 16, html.escape(g)))
    for si, sn in enumerate(series_names):
        col = COLORS.get(sn, PALETTE[si % len(PALETTE)])
        out.append('<rect x="%d" y="%d" width="12" height="12" fill="%s"/><text x="%d" y="%d">%s</text>' % (W - MR + 14, MT + 6 + si * 20, col, W - MR + 32, MT + 17 + si * 20, sn))
    out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="#888"/>' % (ML, MT, W - ML - MR, H - MT - MB))
    if note:
        out.append('<text x="%d" y="%d" font-size="11" fill="#555">%s</text>' % (ML, H - 34, html.escape(note)))
    out.append("</svg>")
    open(path, "w").write("\n".join(out))
    return path


def to_png(svg_path):
    """Konversi SVG -> PNG lewat qlmanage + sips (bawaan macOS). qlmanage selalu merender ke kanvas persegi, jadi salinan SVG diberi
    kanvas persegi (konten di kiri-atas) lalu PNG dipotong sesuai ukuran konten. Kembalikan path PNG atau None (SVG tetap ada)."""
    if not (shutil.which("qlmanage") and shutil.which("sips")):
        return None
    tmp = tempfile.mkdtemp()
    try:
        txt = open(svg_path).read()
        scale = 2
        head_old = 'width="%d" height="%d" viewBox="0 0 %d %d"' % (W, H, W, H)
        off = (W - H) // 2
        # kanvas persegi, konten di tengah vertikal; pemotongan sips berpusat mengembalikan tepat area konten
        sq = txt.replace(head_old, 'width="%d" height="%d" viewBox="0 0 %d %d"' % (W, W, W, W), 1)
        i = sq.index(">") + 1
        sq = sq[:i] + '<rect width="%d" height="%d" fill="#fff"/><g transform="translate(0,%d)">' % (W, W, off) + sq[i:]
        sq = sq[: sq.rindex("</svg>")] + "</g></svg>"
        src = os.path.join(tmp, "chart.svg")
        open(src, "w").write(sq)
        subprocess.run(["qlmanage", "-t", "-s", str(W * scale), "-o", tmp, src], capture_output=True, timeout=60)
        produced = os.path.join(tmp, "chart.svg.png")
        if not os.path.exists(produced):
            return None
        subprocess.run(["sips", "-c", str(H * scale), str(W * scale), produced], capture_output=True, timeout=60)
        dest = svg_path[:-4] + ".png"
        shutil.move(produced, dest)
        return dest
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
