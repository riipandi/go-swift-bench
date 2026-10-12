"""Flame graph SVG sederhana dari 'go tool pprof -traces' (pengganti 'pprof -svg' yang butuh Graphviz)."""
import html
import re


def parse_traces(text):
    """Kembalikan dict {stack_root_ke_leaf(tuple): nilai}. Nilai dalam satuan apa pun yang dicetak pprof (ms/us/s)."""
    unit = {"ns": 1e-6, "us": 1e-3, "µs": 1e-3, "ms": 1.0, "s": 1000.0}
    stacks = {}
    block = []
    for line in text.splitlines() + ["-----------+"]:
        if line.startswith("-----------+"):
            if block:
                m = re.match(r"\s*([\d.]+)(ns|us|µs|ms|s)\s+(.*)$", block[0])
                if m:
                    val = float(m.group(1)) * unit[m.group(2)]
                    frames = [m.group(3).strip()] + [b.strip() for b in block[1:] if b.strip()]
                    key = tuple(reversed(frames))
                    stacks[key] = stacks.get(key, 0.0) + val
            block = []
        elif line.strip() and not line.startswith(("File:", "Type:", "Time:", "Duration:", "Showing")):
            block.append(line)
    return stacks


def build_tree(stacks):
    root = {"name": "all", "value": 0.0, "children": {}}
    for st, v in stacks.items():
        root["value"] += v
        node = root
        for f in st:
            node = node["children"].setdefault(f, {"name": f, "value": 0.0, "children": {}})
            node["value"] += v
    return root


def to_svg(stacks, title, width=1400, row_h=16, min_frac=0.002):
    root = build_tree(stacks)
    total = root["value"] or 1.0
    rects = []
    max_depth = [0]

    def walk(node, x, depth):
        w = node["value"] / total * (width - 20)
        if w < min_frac * width:
            return
        max_depth[0] = max(max_depth[0], depth)
        rects.append((x, depth, w, node["name"], node["value"]))
        cx = x
        for ch in sorted(node["children"].values(), key=lambda c: -c["value"]):
            walk(ch, cx, depth + 1)
            cx += ch["value"] / total * (width - 20)

    walk(root, 10, 0)
    h = (max_depth[0] + 2) * row_h + 40
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="monospace" font-size="11">' % (width, h),
           '<text x="10" y="16" font-size="13">%s (total %.0f ms; flame graph dari pprof -traces)</text>' % (html.escape(title), total)]
    for x, d, w, name, val in rects:
        y = 28 + d * row_h
        hue = (hash(name) % 40)
        fill = "rgb(%d,%d,%d)" % (230, 120 + hue * 3, 40 + hue)
        label = html.escape(name if len(name) * 6.2 < w else name[: max(0, int(w / 6.2) - 1)])
        out.append('<g><title>%s (%.1f ms, %.1f%%)</title><rect x="%.1f" y="%d" width="%.1f" height="%d" fill="%s" stroke="#fff"/>'
                   '<text x="%.1f" y="%d">%s</text></g>' % (html.escape(name), val, val / total * 100, x, y, max(w, 0.5), row_h - 1, fill, x + 2, y + 11, label))
    out.append("</svg>")
    return "\n".join(out)
