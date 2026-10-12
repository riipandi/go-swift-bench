"""Statistik dan aturan penarikan kesimpulan (PRD: kesimpulan DX dan skalabilitas)."""
import math
import statistics


def stat(vals):
    v = [x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not v:
        return None
    m = statistics.mean(v)
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    return {"n": len(v), "med": statistics.median(v), "min": min(v), "max": max(v), "mean": m,
            "cv": (sd / m * 100.0) if m else 0.0, "vals": v}


def cell(s, d=1, scale=1.0, unit=""):
    """'median [min–max]' + tanda CV > 5% (⚠)."""
    if not s:
        return "–"
    f = "%%.%df" % d
    base = (f % (s["med"] * scale)) + unit
    if s["n"] > 1:
        base += " [" + (f % (s["min"] * scale)) + "–" + (f % (s["max"] * scale)) + "]"
    if s["cv"] > 5.0 and s["n"] > 1:
        base += " ⚠CV%.0f%%" % s["cv"]
    return base


def ratio(sa, sb):
    """Rasio median b/a dengan rentang konservatif [min_b/max_a, max_b/min_a]."""
    if not sa or not sb or not sa["med"]:
        return None
    return {"med": sb["med"] / sa["med"], "lo": sb["min"] / sa["max"] if sa["max"] else None, "hi": sb["max"] / sa["min"] if sa["min"] else None}


def fmt_ratio(r, d=2):
    if not r:
        return "–"
    f = "%%.%df" % d
    return "%s× [%s–%s]" % (f % r["med"], f % r["lo"], f % r["hi"])


def judge(sa, sb, lower_better, deterministic=False, thresh=0.05, name_a="Go", name_b="Swift"):
    """Aturan: lebih baik hanya bila rentang min-maks tidak tumpang tindih DAN selisih median > 5%.
    Kurang dari 2 ulangan (kecuali metrik deterministik): 'belum cukup bukti'. Selain itu: 'setara'.
    Kembalikan (kode, teks): kode in {'a','b','setara','belum'}."""
    if not sa or not sb:
        return "belum", "belum cukup bukti (data tidak ada)"
    if not deterministic and (sa["n"] < 2 or sb["n"] < 2):
        return "belum", "belum cukup bukti (ulangan < 2)"
    overlap = not (sa["max"] < sb["min"] or sb["max"] < sa["min"])
    base = sa["med"] if sa["med"] else 1e-12
    diff = abs(sb["med"] - sa["med"]) / abs(base)
    if overlap or diff <= thresh:
        return "setara", "setara (rentang tumpang tindih atau selisih median ≤ 5%)"
    a_better = (sa["med"] < sb["med"]) if lower_better else (sa["med"] > sb["med"])
    return ("a" if a_better else "b"), "%s lebih baik (rentang tidak tumpang tindih, selisih median %.0f%%)" % (name_a if a_better else name_b, diff * 100)


def slope(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
