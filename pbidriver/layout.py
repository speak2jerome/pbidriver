"""Page geometry for screenshots: layout checks (overlaps, near-misses in alignment, uneven gaps, visuals off the
page) and overlays drawn on canvas captures (index, type, title, size, position, errors, render time, grid,
alignment, gaps, overlaps). Pure functions on visual boxes, so they're testable without Power BI.

Units: "page units" are the report page's own coordinates (the x/y/width/height that PBIR files and
`add-visual` use, e.g. 1280 x 720). Boxes measured in the DOM are converted with the page's real size.
"""
from __future__ import annotations

from pathlib import Path

OVERLAYS = ("index", "type", "title", "size", "pos", "errors", "perf", "grid", "align", "gaps", "overlap")
ALL = tuple(o for o in OVERLAYS if o != "perf")  # `all`: everything that doesn't need a Performance Analyzer run
DECORATIVE = {"shape", "basicShape", "image", "actionButton", "pageNavigator", "bookmarkNavigator"}
LABELS = {"index", "type", "title", "size", "pos", "perf"}

RED = (230, 30, 60)
ORANGE = (245, 130, 0)
BLUE = (0, 120, 215)
GREEN = (16, 140, 60)


def expand(items: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        for part in str(item).replace(",", " ").split():
            part = part.strip().lower()
            if part == "all":
                out += [o for o in ALL if o not in out]
            elif part not in OVERLAYS:
                raise ValueError(f"Unknown overlay {part!r}. Choose from: {', '.join(OVERLAYS)}, all")
            elif part not in out:
                out.append(part)
    return out


def to_units(visuals: list[dict], canvas: dict, page_size: tuple[float, float] | None) -> tuple[list[dict], tuple]:
    """Visible visuals with boxes in page units, and the page size used. Without a known page size the
    canvas' own pixels are used."""
    cw, ch = max(1, canvas["w"]), max(1, canvas["h"])
    pw, ph = page_size or (cw, ch)
    kx, ky = pw / cw, ph / ch
    out = []
    for v in visuals:
        if v.get("hidden"):
            continue
        b = v["box"]
        out.append({"index": v["index"], "type": v["type"], "label": v.get("label") or "", "title": v.get("title") or "",
                    "error": v.get("error_text"), "x": b["x"] * kx, "y": b["y"] * ky, "w": b["w"] * kx, "h": b["h"] * ky})
    return out, (pw, ph)


def _overlap(a: dict, b: dict) -> tuple[float, float, float, float] | None:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    return (x0, y0, x1 - x0, y1 - y0) if x1 - x0 > 1 and y1 - y0 > 1 else None


def _span_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def layout_check(units: list[dict], page: tuple[float, float], tol: float = 6.0) -> dict:
    """Issues a designer would fix, in page units:
    - off_page: a visual sticks out of the page
    - overlap: two content visuals overlap (shapes, images and buttons are treated as decoration)
    - near_alignment: two edges are 1..tol units apart, i.e. meant to line up but don't
    - uneven_gap: spacing between neighbours differs slightly from the most common spacing
    Also returns the neighbour gaps (for drawing)."""
    pw, ph = page
    issues: list[dict] = []
    for v in units:
        if v["x"] < -0.5 or v["y"] < -0.5 or v["x"] + v["w"] > pw + 0.5 or v["y"] + v["h"] > ph + 0.5:
            issues.append({"kind": "off_page", "visuals": [v["index"]],
                           "detail": f"visual {v['index']} ({v['type']}) extends outside the {pw:.0f}x{ph:.0f} page"})
    content = [v for v in units if v["type"] not in DECORATIVE]
    for i, a in enumerate(content):
        for b in content[i + 1:]:
            r = _overlap(a, b)
            if r:
                issues.append({"kind": "overlap", "visuals": [a["index"], b["index"]],
                               "rect": [round(x, 1) for x in r],
                               "detail": f"visuals {a['index']} and {b['index']} overlap by {r[2]:.0f}x{r[3]:.0f}"})
    edges = {"left": lambda v: v["x"], "right": lambda v: v["x"] + v["w"],
             "top": lambda v: v["y"], "bottom": lambda v: v["y"] + v["h"]}
    near: list[dict] = []
    for i, a in enumerate(units):
        for b in units[i + 1:]:
            for name, f in edges.items():
                d = f(b) - f(a)
                if 1.0 < abs(d) <= tol:
                    near.append({"kind": "near_alignment", "edge": name, "visuals": [a["index"], b["index"]],
                                 "off_by": round(d, 1),
                                 "detail": f"{name} edges of visuals {a['index']} and {b['index']} are {abs(d):.0f} apart"})
    issues += near[:30]

    gaps: list[dict] = []
    for a in units:
        right = [(b["x"] - (a["x"] + a["w"]), b) for b in units if b is not a
                 and b["x"] >= a["x"] + a["w"] - 0.5
                 and _span_overlap(a["y"], a["y"] + a["h"], b["y"], b["y"] + b["h"]) > 0.3 * min(a["h"], b["h"])]
        below = [(b["y"] - (a["y"] + a["h"]), b) for b in units if b is not a
                 and b["y"] >= a["y"] + a["h"] - 0.5
                 and _span_overlap(a["x"], a["x"] + a["w"], b["x"], b["x"] + b["w"]) > 0.3 * min(a["w"], b["w"])]
        for d, lst in (("h", right), ("v", below)):
            if lst:
                g, b = min(lst, key=lambda t: t[0])
                if g <= max(pw, ph) * 0.125:  # neighbours, not opposite ends of the page
                    gaps.append({"from": a["index"], "to": b["index"], "dir": d, "value": round(g, 1), "a": a, "b": b})
    values = [round(g["value"]) for g in gaps if g["value"] >= 0]
    common = max(set(values), key=values.count) if values else None
    if common is not None:
        for g in gaps:
            if 1.0 < abs(g["value"] - common) <= tol:
                g["uneven"] = True
                issues.append({"kind": "uneven_gap", "visuals": [g["from"], g["to"]], "gap": g["value"], "usual_gap": common,
                               "detail": f"gap between visuals {g['from']} and {g['to']} is {g['value']:.0f}, most gaps are {common}"})
    return {"page_units": [round(pw), round(ph)], "usual_gap": common, "issues": issues,
            "gaps": [{k: g[k] for k in ("from", "to", "dir", "value")} | ({"uneven": True} if g.get("uneven") else {})
                     for g in gaps],
            "_gaps": gaps}


def legend(units: list[dict], perf_ms: dict | None = None) -> list[dict]:
    out = []
    for v in units:
        item = {"index": v["index"], "type": v["type"], "label": v["label"][:80],
                "box": [round(v["x"]), round(v["y"]), round(v["w"]), round(v["h"])]}
        if v.get("error"):
            item["error"] = v["error"]
        if perf_ms and v["index"] in perf_ms:
            item["render_ms"] = perf_ms[v["index"]]
        out.append(item)
    return out


def draw(path: Path, units: list[dict], page: tuple[float, float], items: list[str], *, grid: int = 40,
         layout: dict | None = None, perf_ms: dict | None = None, threshold: float = 500) -> None:
    """Draw the chosen overlays onto a canvas capture (in place)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(path).convert("RGBA")
    k = img.width / max(1, page[0])
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    try:
        font = ImageFont.truetype("segoeuib.ttf", max(12, int(11 * k)))
        small = ImageFont.truetype("segoeui.ttf", max(11, int(10 * k)))
    except OSError:
        font = small = ImageFont.load_default()
    px = lambda *vals: [v * k for v in vals]  # noqa: E731
    w2 = max(2, int(1.5 * k))

    if "grid" in items and grid > 0:
        for i, x in enumerate(range(0, int(page[0]) + 1, grid)):
            d.line(px(x, 0, x, page[1]), fill=(120, 120, 120, 110 if i % 5 == 0 else 50), width=1)
        for i, y in enumerate(range(0, int(page[1]) + 1, grid)):
            d.line(px(0, y, page[0], y), fill=(120, 120, 120, 110 if i % 5 == 0 else 50), width=1)

    if "overlap" in items and layout:
        for iss in layout["issues"]:
            if iss["kind"] == "overlap":
                x, y, w, h = iss["rect"]
                d.rectangle(px(x, y, x + w, y + h), fill=RED + (90,), outline=RED + (255,), width=w2)

    if "errors" in items:
        for v in units:
            if v.get("error"):
                d.rectangle(px(v["x"], v["y"], v["x"] + v["w"], v["y"] + v["h"]), fill=RED + (60,))

    if "align" in items and layout:
        by_index = {v["index"]: v for v in units}
        for iss in layout["issues"]:
            if iss["kind"] != "near_alignment":
                continue
            for idx in iss["visuals"]:
                v = by_index[idx]
                if iss["edge"] in ("left", "right"):
                    x = v["x"] if iss["edge"] == "left" else v["x"] + v["w"]
                    d.line(px(x, v["y"], x, v["y"] + v["h"]), fill=ORANGE + (255,), width=w2 + 1)
                else:
                    y = v["y"] if iss["edge"] == "top" else v["y"] + v["h"]
                    d.line(px(v["x"], y, v["x"] + v["w"], y), fill=ORANGE + (255,), width=w2 + 1)

    if "gaps" in items and layout:
        for g in layout["_gaps"]:
            a, b = g["a"], g["b"]
            color = (ORANGE if g.get("uneven") else BLUE) + (255,)
            if g["dir"] == "h":
                y = (max(a["y"], b["y"]) + min(a["y"] + a["h"], b["y"] + b["h"])) / 2
                x0, x1 = a["x"] + a["w"], b["x"]
                d.line(px(x0, y, x1, y), fill=color, width=w2)
                tx, ty = px((x0 + x1) / 2, y)
            else:
                x = (max(a["x"], b["x"]) + min(a["x"] + a["w"], b["x"] + b["w"])) / 2
                y0, y1 = a["y"] + a["h"], b["y"]
                d.line(px(x, y0, x, y1), fill=color, width=w2)
                tx, ty = px(x, (y0 + y1) / 2)
            text = f"{g['value']:.0f}"
            tw, th = d.textbbox((0, 0), text, font=small)[2:]
            d.rectangle([tx - tw / 2 - 3, ty - th / 2 - 2, tx + tw / 2 + 3, ty + th / 2 + 2], fill=color)
            d.text((tx - tw / 2, ty - th / 2 - 1), text, fill="white", font=small)

    if set(items) & LABELS or "errors" in items:
        for v in units:
            x0, y0, x1, y1 = px(v["x"], v["y"], v["x"] + v["w"], v["y"] + v["h"])
            d.rectangle([x0, y0, x1, y1], outline=RED + (255,), width=w2)
            lines = []
            head = " ".join(str(p) for p, on in ((v["index"], "index" in items), (v["type"], "type" in items)) if on)
            if head:
                lines.append(head)
            if "title" in items and (v["title"] or v["label"]):
                lines.append((v["title"] or v["label"])[:40])
            if "size" in items:
                lines.append(f"{v['w']:.0f} x {v['h']:.0f}")
            if "pos" in items:
                lines.append(f"x {v['x']:.0f}  y {v['y']:.0f}")
            if "errors" in items and v.get("error"):
                lines.append("ERROR: " + v["error"][:40])
            bg = RED
            if "perf" in items and perf_ms and v["index"] in perf_ms:
                ms = perf_ms[v["index"]]
                lines.append(f"{ms:.0f} ms")
                bg = GREEN if ms < threshold / 2 else ORANGE if ms < threshold else RED
            if not lines:
                continue
            y = y0
            for n, line in enumerate(lines):
                f = font if n == 0 else small
                tw, th = d.textbbox((0, 0), line, font=f)[2:]
                d.rectangle([x0, y, x0 + tw + 8, y + th + 6], fill=bg + (235,))
                d.text((x0 + 4, y + 2), line, fill="white", font=f)
                y += th + 6

    Image.alpha_composite(img, layer).convert("RGB").save(path)
