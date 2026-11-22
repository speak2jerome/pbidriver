"""Pure helpers and the CLI surface; none of these need Power BI."""
import json

import pytest

from pbidriver import bridge, cli


def test_every_command_has_a_handler():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    expected = {"launch", "instances", "status", "pages", "alerts", "visuals", "inventory", "shot", "read", "dax",
                "model", "perf", "bookmarks", "reload", "save", "close", "wait", "dialog", "click", "hover", "menu",
                "scroll", "type", "key", "slicer"}
    assert expected <= set(sub.choices)
    for name, p in sub.choices.items():
        assert callable(p.get_default("func")), name


def test_parses_typical_calls():
    p = cli.build_parser()
    a = p.parse_args(["slicer", "--visual", "Region", "--select", "West", "East", "--shot"])
    assert a.select == ["West", "East"] and a.shot and a.view == "report"
    a = p.parse_args(["menu", "--visual", "3", "--more", "--choose", "Sort by > Sales"])
    assert a.more and a.choose == "Sort by > Sales"
    a = p.parse_args(["read", "--page", "Overview"])
    assert a.view == "report" and a.max_rows is None
    a = p.parse_args(["close", "--discard", "--pid", "1234"])
    assert a.discard and a.pid == 1234
    with pytest.raises(SystemExit):
        p.parse_args(["close", "--discard", "--save"])


def test_invalid_input_keeps_json_contract(capsys, tmp_path):
    missing = tmp_path / "nope.pbix"
    assert cli.main(["launch", str(missing)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "not found" in out["error"]


def test_points_merge_series_per_category():
    points = [
        [["Year", "2024"], ["Sales", "10"]],
        [["Year", "2025"], ["Sales", "12"]],
        [["Year", "2024"], ["Margin", "3%"]],
        [["Year", "2025"], ["Margin", "4%"]],
    ]
    cols, rows, total = cli._points_table(points, 100)
    assert cols == ["Year", "Sales", "Margin"]
    assert rows == [["2024", "10", "3%"], ["2025", "12", "4%"]] and total == 2


def test_points_keep_distinct_series_rows():
    points = [
        [["Age", "18-25"], ["Attrition", "No"], ["Count", "79"]],
        [["Age", "18-25"], ["Attrition", "Yes"], ["Count", "44"]],
    ]
    cols, rows, total = cli._points_table(points, 1)
    assert cols == ["Age", "Attrition", "Count"] and rows == [["18-25", "No", "79"]] and total == 2


def test_match_label_normalises_quotes_and_case():
    labels = ["Save", "Don’t save", "Cancel"]
    assert cli._match_label(labels, "don't save") == 1
    assert cli._match_label(labels, "cancel") == 2
    assert cli._match_label(labels, "sa") is None  # ambiguous substring


def test_pick_by_index_text_and_ambiguity():
    items = [{"index": 0, "name": "Overview"}, {"index": 1, "name": "Detail A"}, {"index": 2, "name": "Detail B"}]
    assert cli.pick(items, "1", "page", "name")["name"] == "Detail A"
    assert cli.pick(items, "overview", "page", "name")["index"] == 0
    with pytest.raises(cli.DriverError, match="ambiguous"):
        cli.pick(items, "detail", "page", "name")


def test_adomd_column_names_are_cleaned():
    assert bridge._clean_columns(["[Name]", "Sales[Region]", "Total"]) == ["Name", "Sales[Region]", "Total"]


def test_slug_and_png_name(tmp_path):
    assert cli.slug("Sales by Region / 2026!") == "sales-by-region-2026"
    path = cli.as_png(tmp_path / "shots" / "out")
    assert path.name == "out.png" and path.parent.is_dir()
