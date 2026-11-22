"""Layout checks, overlays and Performance Analyzer helpers. No Power BI needed."""
import pytest

from pbidriver import cli, layout


def v(i, x, y, w, h, type_="card", title="", error=None):
    return {"index": i, "type": type_, "label": title, "title": title, "error_text": error, "hidden": False,
            "box": {"x": x, "y": y, "w": w, "h": h}}


def units(*vs, page=(1280, 720)):
    return layout.to_units(list(vs), {"w": page[0], "h": page[1]}, page)


def test_expand():
    assert layout.expand(["index", "type"]) == ["index", "type"]
    assert layout.expand(["all"]) == list(layout.ALL) and "perf" not in layout.expand(["all"])
    assert layout.expand(["size,pos", "size"]) == ["size", "pos"]
    with pytest.raises(ValueError, match="Unknown overlay"):
        layout.expand(["sparkles"])


def test_to_units_scales_dom_pixels_to_page_units():
    us, page = layout.to_units([v(0, 30, 15, 150, 75), {**v(1, 0, 0, 0, 0), "hidden": True}],
                               {"w": 1920, "h": 1080}, (1280, 720))
    assert page == (1280, 720) and len(us) == 1
    assert (us[0]["x"], us[0]["y"], us[0]["w"], us[0]["h"]) == (20, 10, 100, 50)
    us, page = layout.to_units([v(0, 30, 15, 150, 75)], {"w": 1920, "h": 1080}, None)
    assert page == (1920, 1080) and us[0]["x"] == 30  # unknown page size: canvas pixels


def test_snap_to_file_uses_exact_positions_and_ids():
    us, page = units(v(0, 20.3, 19.6, 599.2, 250.4, "donutChart"), v(1, 700, 300, 100, 100, "card"))
    file_visuals = [{"id": "aaa", "type": "donutChart", "x": 20, "y": 20, "w": 600, "h": 250},
                    {"id": "bbb", "type": "card", "x": 900, "y": 300, "w": 100, "h": 100}]  # moved since: no match
    layout.snap_to_file(us, file_visuals)
    assert (us[0]["x"], us[0]["w"], us[0]["id"]) == (20, 600, "aaa")
    assert "id" not in us[1] and us[1]["x"] == 700
    assert layout.legend(us)[0]["id"] == "aaa"


def test_clean_grid_has_no_issues():
    us, page = units(v(0, 20, 20, 300, 100), v(1, 340, 20, 300, 100), v(2, 20, 140, 620, 200))
    geo = layout.layout_check(us, page)
    assert geo["issues"] == [] and geo["usual_gap"] == 20


def test_issues_are_found():
    us, page = units(
        v(0, 20, 20, 300, 100), v(1, 340, 20, 300, 100),          # a clean row, gap 20
        v(2, 663, 23, 300, 100),                                  # gap 23 and 3 units lower: uneven + near-miss
        v(3, 600, 200, 200, 100), v(4, 780, 250, 200, 100),       # overlap
        v(5, 1200, 600, 200, 200),                                # off the page
        v(6, 0, 0, 1280, 720, type_="shape"))                     # background shape: not an overlap
    geo = layout.layout_check(us, page)
    kinds = {}
    for iss in geo["issues"]:
        kinds.setdefault(iss["kind"], []).append(iss)
    assert {"overlap", "near_alignment", "uneven_gap", "off_page"} <= set(kinds)
    assert [i["visuals"] for i in kinds["overlap"]] == [[3, 4]]
    assert kinds["off_page"][0]["visuals"] == [5]
    assert any(i["visuals"] == [1, 2] and i["edge"] == "top" and i["off_by"] == 3 for i in kinds["near_alignment"])
    assert any(i["visuals"] == [1, 2] and i["gap"] == 23 for i in kinds["uneven_gap"])
    assert "_gaps" in geo and all("a" not in g for g in geo["gaps"])  # the public gaps carry no boxes


def test_legend_and_draw(tmp_path):
    from PIL import Image

    path = tmp_path / "canvas.png"
    Image.new("RGB", (1280, 720), "white").save(path)
    us, page = units(v(0, 20, 20, 300, 100, title="Revenue"), v(1, 343, 20, 300, 100, error="Can't display this visual"),
                     v(2, 300, 60, 100, 100))
    geo = layout.layout_check(us, page)
    leg = layout.legend(us, {0: 120})
    assert leg[0] == {"index": 0, "type": "card", "label": "Revenue", "box": [20, 20, 300, 100], "render_ms": 120}
    assert leg[1]["error"] == "Can't display this visual"
    layout.draw(path, us, page, layout.expand(["all", "perf"]), layout=geo, perf_ms={0: 120})
    img = Image.open(path)
    assert img.size == (1280, 720) and img.getcolors(1_000_000) and len(img.getcolors(1_000_000)) > 3


def perf_row(name, total, dax=0, vis=0, other=0):
    return {"name": name, "total_ms": total, "dax_query_ms": dax, "visual_display_ms": vis, "other_ms": other,
            "expanded": True, "copy": None}


def test_perf_summary_takes_medians_and_finds_bottlenecks():
    runs = [[perf_row("Sales", 900, dax=800, vis=50, other=50), perf_row("Card", 100, other=90), perf_row("Card", 80)],
            [perf_row("Sales", 700, dax=600, vis=50, other=50), perf_row("Card", 120, other=100), perf_row("Card", 60)],
            [perf_row("Sales", 800, dax=700, vis=50, other=50), perf_row("Card", 110, other=95), perf_row("Card", 70)]]
    rows = cli.perf_summary(runs, threshold=500)
    assert [r["name"] for r in rows] == ["Sales", "Card", "Card"]
    sales = rows[0]
    assert sales["total_ms"] == 800 and sales["runs_ms"] == [900, 700, 800]
    assert sales["bottleneck"] == "dax_query" and sales["slow"] is True
    assert rows[1]["total_ms"] == 110 and rows[1]["bottleneck"] == "other" and not rows[1]["slow"]
    assert "expanded" not in sales and "copy" not in sales
    hints = cli.perf_hints(rows, visual_count=20, threshold=500)
    assert any("DAX query is the bottleneck" in h for h in hints) and any("20 visuals" in h for h in hints)
    assert cli.perf_hints([], 3, 500) == ["No visual took 500 ms or more."]


def test_perf_rows_match_titles_then_unique_types():
    visuals = [v(0, 0, 0, 1, 1, "clusteredColumnChart", "Revenue by region"), v(1, 0, 0, 1, 1, "tableEx"),
               v(2, 0, 0, 1, 1, "card"), v(3, 0, 0, 1, 1, "card"), v(4, 0, 0, 1, 1, "textbox"),
               v(5, 0, 0, 1, 1, "pivotTable")]
    rows = [{"name": n} for n in ("Revenue by region", "Table", "Card", "Card", "Text box", "Matrix", "Gauge")]
    cli.match_perf_rows(rows, visuals)
    got = {r["name"]: r.get("visual_index") for r in rows}
    assert got["Revenue by region"] == 0 and got["Table"] == 1 and got["Text box"] == 4 and got["Matrix"] == 5
    assert got["Card"] is None and got["Gauge"] is None  # two cards: ambiguous; no gauge on the page
    assert all("note" in r for r in rows if r["name"] == "Card")

    # with queries (perf queries=true), cards are told apart by the measures they query
    cards = [{**v(2, 0, 0, 1, 1, "card"), "label": "Total Revenue $156K."},
             {**v(3, 0, 0, 1, 1, "card"), "label": "Total Units 6,207."}]
    rows = [{"name": "Card", "query": "EVALUATE ROW(\"x\", 'Sales'[Total Units])"},
            {"name": "Card", "query": "DEFINE VAR v = 1 EVALUATE ROW(\"y\", [Total Revenue])"}]
    cli.match_perf_rows(rows, cards)
    assert [r.get("visual_index") for r in rows] == [3, 2]
