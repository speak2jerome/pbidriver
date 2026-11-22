"""PBIR authoring: new projects, pages, visuals, field parsing. No Power BI needed (the theme is faked)."""
import json

import pytest

from pbidriver import project
from pbidriver.project import ProjectError

FIELDS = {"Sales": {"columns": {"Region", "Units", "Order Date"}, "measures": {"Total Revenue"}},
          "My Dim": {"columns": {"Region", "Manager"}, "measures": set()}}


@pytest.fixture
def proj(tmp_path, monkeypatch):
    theme = tmp_path / "CY24SU10.json"
    theme.write_text('{"name": "CY24SU10"}')
    monkeypatch.setattr(project, "base_theme_file", lambda name=project.BASE_THEME: theme)
    out = project.new_project(tmp_path / "p", "Sales")
    return project.report_dir(out["pbip"]), out


def test_new_project_layout(proj):
    rep, out = proj
    root = rep.parent
    pbip = json.loads((root / "Sales.pbip").read_text())
    assert pbip["artifacts"][0]["report"]["path"] == "Sales.Report"
    report = json.loads((rep / "definition" / "report.json").read_text())
    assert report["themeCollection"]["baseTheme"]["name"] == "CY24SU10"
    assert (rep / "StaticResources" / "SharedResources" / "BaseThemes" / "CY24SU10.json").is_file()
    assert project.model_dir(rep) == (root / "Sales.SemanticModel").resolve()
    assert "compatibilityLevel: 1606" in (root / "Sales.SemanticModel" / "definition" / "database.tmdl").read_text()
    assert [p["name"] for p in project.list_pages(rep)] == ["Page 1"]
    assert project.report_dir(root) == rep and project.report_dir(rep) == rep
    with pytest.raises(ProjectError, match="already exists"):
        project.new_project(root, "Sales")


def test_parse_field():
    f = project.parse_field("Sales[Region]", FIELDS)
    assert f["kind"] == "column" and f["queryRef"] == "Sales.Region"
    f = project.parse_field("[Total Revenue]", FIELDS)
    assert f["kind"] == "measure" and "Measure" in f["field"]
    f = project.parse_field("'My Dim'[Manager]", FIELDS)
    assert f["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "My Dim"
    f = project.parse_field("Count(Sales[Units])", FIELDS)
    assert f["kind"] == "aggregate" and f["field"]["Aggregation"]["Function"] == 5
    assert project.parse_field("DistinctCount(Sales[Units])", FIELDS)["field"]["Aggregation"]["Function"] == 2
    assert project.parse_field("Sales[Order Date]", FIELDS)["nativeQueryRef"] == "Order Date"
    for bad, msg in [("Sales[Nope]", "has no column or measure"), ("Nope[Region]", "Unknown table"),
                     ("[Region]", "Can't tell which table"), ("Sum([Total Revenue])", "can't take an aggregation"),
                     ("Region", "should look like"), ("[Ghost]", "No column or measure named")]:
        with pytest.raises(ProjectError, match=msg):
            project.parse_field(bad, FIELDS)


def test_add_and_remove_visuals(proj):
    rep, _ = proj
    page = project.add_page(rep, "Second")
    out = project.add_visual(rep, "Second", "clusteredColumnChart",
                             {"Category": ["Sales[Region]"], "Y": ["[Total Revenue]"]}, 10, 20, 300, 200,
                             title="By region", fields=FIELDS)
    v = json.loads((rep / "definition" / "pages" / page["id"] / "visuals" / out["id"] / "visual.json").read_text())
    qs = v["visual"]["query"]["queryState"]
    assert qs["Category"]["projections"][0]["active"] is True
    assert qs["Y"]["projections"][0]["field"]["Measure"]["Property"] == "Total Revenue"
    assert v["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"] == "'By region'"
    assert v["position"]["x"] == 10 and len(out["id"]) == 20

    s = project.add_visual(rep, "Second", "slicer", {"Values": ["Sales[Region]"]}, 0, 0, 100, 100,
                           title="Pick", slicer_mode="dropdown", fields=FIELDS)
    sv = json.loads(open(s["file"], encoding="utf-8").read())["visual"]
    assert sv["objects"]["header"][0]["properties"]["text"]["expr"]["Literal"]["Value"] == "'Pick'"
    assert sv["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"] == "'Dropdown'"
    assert "visualContainerObjects" not in sv  # no second title on slicers

    t = project.add_visual(rep, "Second", "textbox", {}, 0, 0, 100, 40, text="Line 1\nLine 2")
    tv = json.loads(open(t["file"], encoding="utf-8").read())["visual"]
    assert len(tv["objects"]["general"][0]["properties"]["paragraphs"]) == 2

    c = project.add_visual(rep, "Second", "card", {"Values": ["[Total Revenue]"]}, 0, 0, 100, 100, title="Revenue",
                           fields=FIELDS)
    cv = json.loads(open(c["file"], encoding="utf-8").read())["visual"]
    assert cv["objects"]["categoryLabels"][0]["properties"]["show"]["expr"]["Literal"]["Value"] == "false"
    project.remove_visual(rep, "Second", c["id"])

    b = project.add_visual(rep, "Second", "clusteredBarChart", {"Category": ["Sales[Region]"], "Y": ["[Total Revenue]"]},
                           0, 0, 100, 100, fields=FIELDS, sort="[Total Revenue]")
    sd = json.loads(open(b["file"], encoding="utf-8").read())["visual"]["query"]["sortDefinition"]["sort"][0]
    assert sd["direction"] == "Descending" and sd["field"]["Measure"]["Property"] == "Total Revenue"
    project.remove_visual(rep, "Second", b["id"])

    listed = project.list_visuals(rep, "Second")
    assert {x["id"] for x in listed} == {out["id"], s["id"], t["id"]}
    project.remove_visual(rep, "Second", s["id"])
    assert {x["id"] for x in project.list_visuals(rep, "Second")} == {out["id"], t["id"]}

    with pytest.raises(ProjectError):
        project.add_visual(rep, "Second", "card", {"Values": ["Sales[Nope]"]}, 0, 0, 1, 1, fields=FIELDS)
    with pytest.raises(ProjectError):
        project.add_visual(rep, "Second", "textbox", {}, 0, 0, 1, 1)  # textbox without text
    with pytest.raises(ProjectError, match="No single page"):
        project.find_page(rep, "Nope")


def test_model_fields_from_tmdl(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "Sales.tmdl").write_text(
        "table Sales\n\tlineageTag: x\n\n\tmeasure 'Total Revenue' = SUM(Sales[Revenue])\n"
        "\t\tformatString: #,0\n\n\tcolumn Region\n\t\tdataType: string\n\n\tcolumn 'Order Date'\n", encoding="utf-8")
    (tables / "My Dim.tmdl").write_text("table 'My Dim'\n\n\tcolumn Manager\n", encoding="utf-8")
    f = project.model_fields_from_tmdl(tmp_path)
    assert f["Sales"]["measures"] == {"Total Revenue"} and f["Sales"]["columns"] == {"Region", "Order Date"}
    assert f["My Dim"]["columns"] == {"Manager"}
