"""pbidriver.definition against small synthetic reports: classic .pbix Layout and a PBIR .pbip project."""
import json
import zipfile

import pytest

from pbidriver.definition import report_inventory


def _literal(value):
    return {"expr": {"Literal": {"Value": value}}}


def _legacy_layout():
    chart = {
        "name": "v1",
        "singleVisual": {
            "visualType": "columnChart",
            "projections": {"Category": [{"queryRef": "Sales.Region"}], "Y": [{"queryRef": "Sum(Sales.Amount)"}]},
            "vcObjects": {"title": [{"properties": {"show": _literal("true"), "text": _literal("'Sales by region'")}}]},
        },
    }
    textbox = {
        "name": "v2",
        "singleVisual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": "Quarterly "}, {"value": "review"}]}]}}]},
        },
    }
    custom = {"name": "v3", "singleVisual": {"visualType": "chordChart0123456789ABCDEF0123456789ABCDEF", "display": {"mode": "hidden"}}}
    page_filter = [{
        "name": "f1", "type": "Categorical",
        "expression": {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Region"}},
        "filter": {"Version": 2, "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                   "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": "Region"}}],
                                                   "Values": [[{"Literal": {"Value": "'West'"}}], [{"Literal": {"Value": "'East'"}}]]}}}]},
    }]
    return {
        "config": json.dumps({"bookmarks": [
            {"displayName": "Default", "name": "b1", "explorationState": {"activeSection": "s1"}},
            {"displayName": "Group A", "name": "g1", "children": [
                {"displayName": "Detail", "name": "b2", "explorationState": {"activeSection": "s2"}}]},
        ]}),
        "filters": "[]",
        "sections": [
            {"name": "s2", "displayName": "Details", "ordinal": 1, "width": 1280, "height": 720,
             "config": json.dumps({"visibility": 1}), "filters": "[]", "visualContainers": [
                 {"x": 0, "y": 0, "width": 100, "height": 50, "config": json.dumps(custom)}]},
            {"name": "s1", "displayName": "Overview", "ordinal": 0, "width": 1280, "height": 720,
             "config": "{}", "filters": json.dumps(page_filter), "visualContainers": [
                 {"x": 10.4, "y": 20, "width": 400, "height": 300, "z": 1, "config": json.dumps(chart)},
                 {"x": 500, "y": 20, "width": 200, "height": 40, "config": json.dumps(textbox)}]},
        ],
    }


@pytest.fixture
def legacy_pbix(tmp_path):
    path = tmp_path / "legacy.pbix"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Report/Layout", json.dumps(_legacy_layout()).encode("utf-16-le"))
    return path


def test_legacy_pages_and_visuals(legacy_pbix):
    inv = report_inventory(legacy_pbix)
    assert inv["format"] == "legacy"
    assert [p["name"] for p in inv["pages"]] == ["Overview", "Details"]  # ordinal order
    overview, details = inv["pages"]
    assert details["hidden"] is True and overview["hidden"] is False
    chart, textbox = overview["visuals"]
    assert chart["type"] == "columnChart" and chart["title"] == "Sales by region"
    assert chart["fields"] == {"Category": ["Sales.Region"], "Y": ["Sum(Sales.Amount)"]}
    assert (chart["x"], chart["w"]) == (10, 400)
    assert textbox["text"] == "Quarterly review"
    custom = details["visuals"][0]
    assert custom["custom"] is True and custom["hidden"] is True


def test_legacy_summary_filters_bookmarks(legacy_pbix):
    inv = report_inventory(legacy_pbix)
    assert inv["visual_count"] == 3
    assert inv["types"]["columnChart"] == {"count": 1, "pages": {"Overview": 1}}
    assert inv["pages"][0]["filters"] == [{"field": "Sales.Region", "type": "Categorical", "values": ["West", "East"]}]
    assert inv["bookmarks"] == [
        {"name": "Default", "id": "b1", "group": None, "page": "Overview"},
        {"name": "Detail", "id": "b2", "group": "Group A", "page": "Details"},
    ]


@pytest.fixture
def pbir_project(tmp_path):
    root = tmp_path / "proj"
    report = root / "Shop.Report"
    pages = report / "definition" / "pages"
    (pages / "p1" / "visuals" / "a").mkdir(parents=True)
    (root / "Shop.pbip").write_text(json.dumps({"version": "1.0", "artifacts": [{"report": {"path": "Shop.Report"}}]}), encoding="utf-8")
    (pages / "pages.json").write_text(json.dumps({"pageOrder": ["p1"]}), encoding="utf-8")
    (pages / "p1" / "page.json").write_text(json.dumps({"name": "p1", "displayName": "Main", "width": 1280, "height": 720}), encoding="utf-8")
    visual = {
        "name": "a",
        "position": {"x": 5, "y": 6, "width": 300, "height": 200},
        "visual": {"visualType": "barChart", "query": {"queryState": {"Values": {"projections": [
            {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Total"}}, "queryRef": "Sales.Total"}]}}}},
        "filterConfig": {"filters": [{"name": "f", "type": "Advanced",
                                      "field": {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Qty"}}}]},
    }
    (pages / "p1" / "visuals" / "a" / "visual.json").write_text(json.dumps(visual), encoding="utf-8")
    bm = report / "definition" / "bookmarks"
    bm.mkdir(parents=True)
    (bm / "bookmarks.json").write_text(json.dumps({"items": [{"name": "k1"}]}), encoding="utf-8")
    (bm / "k1.bookmark.json").write_text(json.dumps({"name": "k1", "displayName": "Start", "explorationState": {"activeSection": "p1"}}), encoding="utf-8")
    return root / "Shop.pbip"


def test_pbir_project(pbir_project):
    inv = report_inventory(pbir_project)
    assert inv["format"] == "pbir"
    page = inv["pages"][0]
    assert page["name"] == "Main" and page["id"] == "p1"
    v = page["visuals"][0]
    assert v["type"] == "barChart" and v["fields"] == {"Values": ["Sales.Total"]}
    assert (v["x"], v["y"], v["w"], v["h"]) == (5, 6, 300, 200)
    assert v["filters"] == [{"field": "Sales.Qty", "type": "Advanced", "active": False}]
    assert inv["bookmarks"] == [{"name": "Start", "id": "k1", "group": None, "page": "Main"}]


def test_rejects_unknown_files(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("x")
    with pytest.raises(ValueError):
        report_inventory(other)
