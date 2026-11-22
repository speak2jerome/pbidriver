"""End-to-end test of the agent kit: pbidriver's MCP server + Microsoft's Power BI Modeling MCP, driven
through the official MCP Python client exactly the way an agent drives them.

    pip install mcp            # the MCP client used here (pbidriver itself doesn't need it)
    python scripts/e2e_kit.py [--work DIR] [--port 9444] [--modeling-cmd "path\\to\\powerbi-modeling-mcp.exe"]

It creates a PBIP project from a generated CSV, builds the model (fact table, dimension table, relationship,
measures) through the Modeling MCP, refreshes through Power BI, adds pages and visuals through pbidriver,
checks every number on screen against DAX, slices, saves, closes, reopens, and checks the data survived.
It needs Power BI Desktop and opens (and at the end closes) one Power BI window on --port.
Exit code 0 when every check passes; a JSON report is written to <work>/e2e_report.json.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import shlex
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

try:
    import mcp.types as types
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    sys.exit("This test drives the servers through the MCP Python client: pip install mcp")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pbidriver import kit  # noqa: E402

REGIONS = {"East": "Ann", "West": "Bo", "North": "Cy", "South": "Di"}
PRICES = {"Widget": 12.5, "Gadget": 30.0, "Gizmo": 7.25, "Doohickey": 55.0, "Thingamajig": 19.99}


class Check:
    def __init__(self):
        self.results: list[dict] = []

    def __call__(self, name: str, ok: bool, detail=None) -> bool:
        self.results.append({"check": name, "ok": bool(ok), **({"detail": detail} if detail is not None else {})})
        print(("  PASS " if ok else "  FAIL ") + name + ("" if ok or detail is None else f": {detail}"))
        return ok


def make_csv(path: Path) -> list[dict]:
    rnd = random.Random(7)
    rows = []
    for i in range(1, 601):
        p = rnd.choice(list(PRICES))
        u = rnd.randint(1, 20)
        rows.append({"OrderID": i, "OrderDate": (date(2025, 1, 1) + timedelta(days=rnd.randint(0, 364))).isoformat(),
                     "Region": rnd.choice(list(REGIONS)), "Product": p, "Units": u, "Revenue": round(u * PRICES[p], 2)})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


async def confirm_writes(context, params):
    """The Modeling MCP asks once per model before writing (MCP elicitation). An agent's user would click
    'Continue'; here we answer the form with its first (affirmative) choice."""
    content = {}
    for k, v in ((getattr(params, "requested_schema", None) or {}).get("properties") or {}).items():
        content[k] = v["enum"][0] if v.get("enum") else True if v.get("type") == "boolean" else "Yes"
    return types.ElicitResult(action="accept", content=content)


def money(text: str) -> float:
    return float(str(text).split(" ")[0].replace("$", "").replace(",", ""))


class Agent:
    def __init__(self, P: ClientSession, M: ClientSession, log: list):
        self.P, self.M, self.log = P, M, log

    async def _call(self, session, tool, args):
        t0 = time.time()
        res = await session.call_tool(tool, args)
        text = "\n".join(c.text for c in res.content if c.type == "text")
        images = sum(1 for c in res.content if c.type == "image")
        entry = {"tool": tool, "args": args, "seconds": round(time.time() - t0, 1), "error": bool(res.is_error),
                 "images": images, "result": text[:3000]}
        self.log.append(entry)
        print(f"-> {tool} {json.dumps(args)[:110]} ({entry['seconds']}s){' ERROR' if res.is_error else ''}")
        return text, images, res.is_error

    async def pbi(self, tool, **args):
        text, images, err = await self._call(self.P, tool, args)
        data = json.loads(text) if text.startswith("{") else {"ok": False, "error": text}
        data["_images"] = images
        if err and data.get("ok", True):
            data["ok"] = False
        return data

    async def model(self, tool, **request):
        text, _, err = await self._call(self.M, tool, {"request": request})
        try:
            data = json.loads(text)
        except ValueError:
            data = {"success": False, "message": text}
        if err:
            data["success"] = False
        return data


async def run(a) -> int:
    work = Path(a.work).resolve()
    if work.exists() and a.clean:
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    rows = make_csv(work / "data" / "sales.csv")
    total_rev = round(sum(r["Revenue"] for r in rows), 2)
    total_units = sum(r["Units"] for r in rows)
    by_region = {}
    for r in rows:
        by_region[r["Region"]] = round(by_region.get(r["Region"], 0) + r["Revenue"], 2)

    if a.modeling_cmd:
        parts = shlex.split(a.modeling_cmd, posix=False)
        mcmd, margs = parts[0].strip('"'), parts[1:] or ["--start"]
    else:
        cfg = kit.modeling_server("exe" if kit.modeling_exes() else "npx")
        mcmd, margs = cfg["command"], cfg["args"]
    check, log = Check(), []
    pb = StdioServerParameters(command=sys.executable, args=["-m", "pbidriver", "mcp", "--cwd", str(work)])
    mm = StdioServerParameters(command=mcmd, args=margs)
    t_start = time.time()
    async with stdio_client(pb) as (r1, w1), stdio_client(mm) as (r2, w2):
        async with ClientSession(r1, w1) as P, ClientSession(r2, w2, elicitation_callback=confirm_writes) as M:
            init = await P.initialize()
            await M.initialize()
            ag = Agent(P, M, log)
            tools = {t.name for t in (await P.list_tools()).tools}
            check("pbidriver server lists its tools", {"pbi_new", "pbi_add_visual", "pbi_shot", "pbi_guide"} <= tools,
                  sorted(tools))
            check("pbidriver server sends instructions", "Modeling MCP" in (init.instructions or ""))
            guide = await ag._call(P, "pbi_guide", {})
            check("pbi_guide returns the workflow", "pbi_refresh" in guide[0], guide[0][:200])

            # 1. project
            r = await ag.pbi("pbi_new", folder=str(work / "proj"), name="Sales", open=True, port=a.port)
            if not check("pbi_new creates and opens the project",
                         r.get("ok") and r.get("launch", {}).get("loaded") and r.get("model_port"), r):
                return 1
            r = await ag.pbi("pbi_model", port=a.port)
            check("pbi_model on an empty model", r.get("ok") and r["counts"].get("tables") == 0, r)
            inst = next((i for i in (await ag.pbi("pbi_instances"))["instances"] if i.get("devtools_port") == a.port), {})
            check("pbi_instances reports the model port", bool(inst.get("model_port")), inst)

            # 2. model through the Modeling MCP
            r = await ag.model("connection_operations", operation="Connect", dataSource=f"localhost:{inst['model_port']}")
            check("Modeling MCP connects to localhost:<model_port>", r.get("success"), r)
            csv_path = work / "data" / "sales.csv"
            m = ('let\n    Source = Csv.Document(File.Contents("' + str(csv_path) + '"), [Delimiter=",", Columns=6, '
                 'Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n'
                 '    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n'
                 '    Typed = Table.TransformColumnTypes(Promoted, {{"OrderID", Int64.Type}, {"OrderDate", type date}, '
                 '{"Region", type text}, {"Product", type text}, {"Units", Int64.Type}, {"Revenue", type number}})\n'
                 'in\n    Typed')
            cols = [("OrderID", "Int64", "None"), ("OrderDate", "DateTime", None), ("Region", "String", None),
                    ("Product", "String", None), ("Units", "Int64", "Sum"), ("Revenue", "Double", "Sum")]
            r = await ag.model("table_operations", operation="Create", definitions=[{
                "name": "Sales", "mExpression": m,
                "columns": [{"name": n, "sourceColumn": n, "dataType": t, **({"summarizeBy": s} if s else {})}
                            for n, t, s in cols]}])
            check("table_operations Create (M from CSV)", r.get("success"), r)
            rows_dax = ", ".join(f'{{"{k}", "{v}"}}' for k, v in REGIONS.items())
            r = await ag.model("table_operations", operation="Create", definitions=[{
                "name": "Regions",
                "daxExpression": f'DATATABLE("Region", STRING, "Manager", STRING, {{{rows_dax}}})'}])
            check("table_operations Create (DAX calculated table)", r.get("success"), r)
            r = await ag.model("relationship_operations", operation="Create", definitions=[{
                "fromTable": "Sales", "fromColumn": "Region", "fromCardinality": "Many",
                "toTable": "Regions", "toColumn": "Region", "toCardinality": "One",
                "crossFilteringBehavior": "OneDirection", "isActive": True}])
            check("relationship_operations Create (many-to-one)", r.get("success"), r)
            r = await ag.model("table_operations", operation="Create", definitions=[{
                "name": "Date", "daxExpression": 'ADDCOLUMNS(CALENDAR(DATE(2025,1,1), DATE(2025,12,31)), '
                                                 '"Month", FORMAT([Date], "MMM"), "MonthNo", MONTH([Date]))'}])
            check("table_operations Create (date table)", r.get("success"), r)
            r = await ag.model("table_operations", operation="MarkAsDateTable",
                               markAsDateTableDefinitions=[{"tableName": "Date", "dateColumnName": "Date"}])
            check("table_operations MarkAsDateTable", r.get("success"), r)
            r = await ag.model("column_operations", operation="Update", definitions=[
                {"tableName": "Date", "name": "Month", "sortByColumn": "MonthNo"},
                {"tableName": "Sales", "name": "OrderID", "isHidden": True}])
            check("column_operations Update (sort by, hide)", r.get("success"), r)
            r = await ag.model("relationship_operations", operation="Create", definitions=[{
                "fromTable": "Sales", "fromColumn": "OrderDate", "fromCardinality": "Many",
                "toTable": "Date", "toColumn": "Date", "toCardinality": "One"}])
            check("relationship to the date table", r.get("success"), r)
            r = await ag.model("measure_operations", operation="Create", definitions=[
                {"tableName": "Sales", "name": "Total Revenue", "expression": "SUM(Sales[Revenue])",
                 "formatString": "\\$#,0.00"},
                {"tableName": "Sales", "name": "Total Units", "expression": "SUM(Sales[Units])", "formatString": "#,0"},
                {"tableName": "Sales", "name": "Avg Price", "expression": "DIVIDE([Total Revenue], [Total Units])",
                 "formatString": "\\$#,0.00"}])
            check("measure_operations Create", r.get("success"), r)

            # 3. data, loaded by Power BI itself so the save keeps it
            r = await ag.pbi("pbi_refresh", port=a.port)
            check("plain pbi_refresh reports tables it couldn't load and suggests sync",
                  r.get("ok") and not r.get("refreshed") and "--sync" in str(r.get("next")), r)
            r = await ag.pbi("pbi_refresh", port=a.port, sync=True)
            check("pbi_refresh sync=true loads the data", r.get("ok") and r.get("refreshed")
                  and r.get("synced", {}).get("reloaded"), r)
            r = await ag.pbi("pbi_dax", port=a.port, query='EVALUATE ROW("rows", COUNTROWS(Sales), '
                                                           '"rev", [Total Revenue], "units", [Total Units])')
            got = (r.get("rows") or [[None] * 3])[0]
            check("DAX totals match the CSV", got[0] == len(rows) and abs(got[1] - total_rev) < 0.01
                  and got[2] == total_units, {"dax": got, "csv": [len(rows), total_rev, total_units]})
            r = await ag.pbi("pbi_model", port=a.port)
            check("pbi_model sees tables, measures and the relationship",
                  r.get("ok") and r["counts"]["measures"] == 3 and r["counts"]["relationships"] >= 1, r.get("counts"))

            # 4. report: page 1
            visuals = [
                ("textbox", {"text": "Sales overview 2025", "x": 20, "y": 10, "width": 900, "height": 50}),
                ("card", {"field": ["[Total Revenue]"], "x": 20, "y": 70, "width": 300, "height": 110}),
                ("card", {"field": ["[Total Units]"], "x": 340, "y": 70, "width": 300, "height": 110}),
                ("slicer", {"field": ["Sales[Region]"], "mode": "dropdown", "title": "Region", "x": 960, "y": 10,
                            "width": 300, "height": 90}),
                ("clusteredColumnChart", {"field": ["Category=Sales[Region]", "Y=[Total Revenue]"], "x": 20, "y": 200,
                                          "width": 620, "height": 250, "title": "Revenue by region"}),
                ("donutChart", {"field": ["Sales[Product]", "[Total Revenue]"], "x": 660, "y": 200, "width": 600,
                                "height": 250}),
                ("tableEx", {"field": ["Sales[Product]", "[Total Units]", "[Total Revenue]", "[Avg Price]"], "x": 20,
                             "y": 470, "width": 620, "height": 240}),
                ("lineChart", {"field": ["Category=Sales[OrderDate]", "Y=[Total Units]"], "x": 660, "y": 470,
                               "width": 600, "height": 240, "title": "Units over time"}),
            ]
            ok = True
            for i, (vt, args) in enumerate(visuals):
                last = i == len(visuals) - 1
                r = await ag.pbi("pbi_add_visual", port=a.port, type=vt, **args, **({"shot": True} if last else {}))
                ok = ok and r.get("ok")
            check("pbi_add_visual x8 (fields checked against the live model)", ok, r)
            check("add_visual shot=true returns an image", r.get("_images", 0) >= 1)
            r = await ag.pbi("pbi_alerts", port=a.port)
            check("no alerts after building page 1", r.get("ok") and not r.get("alerts"), r.get("alerts"))
            r = await ag.pbi("pbi_read", port=a.port)
            vis = {v["type"] + str(i): v for i, v in enumerate(r.get("visuals", []))}
            cards = [v for v in r.get("visuals", []) if v["type"] == "card"]
            col = next((v for v in r.get("visuals", []) if v["type"] == "clusteredColumnChart"), {})
            shown = {row[0]: money(row[1]) for row in col.get("rows", [])}
            check("column chart values equal DAX/CSV per region", shown == by_region, {"shown": shown, "csv": by_region})
            check("cards show the totals", any("6,207" in str(c.get("values")) or str(total_units) in str(c.get("values"))
                                               for c in cards), [c.get("values") for c in cards])
            check("every visual on page 1 rendered data", len(vis) == len(visuals) and not any(
                v.get("error_text") for v in r.get("visuals", [])), [v["type"] for v in r.get("visuals", [])])

            # 5. page 2: matrix through the relationship
            r = await ag.pbi("pbi_add_page", port=a.port, name="By manager")
            check("pbi_add_page", r.get("ok"), r)
            r = await ag.pbi("pbi_add_visual", port=a.port, type="pivotTable", page="By manager",
                             field=["Rows=Regions[Manager]", "Columns=Sales[Product]", "Values=[Total Revenue]"],
                             x=20, y=20, width=1240, height=400, title="Revenue by manager and product")
            r = await ag.pbi("pbi_add_visual", port=a.port, type="clusteredBarChart", page="By manager",
                             field=["Regions[Manager]", "Avg(Sales[Units])"], x=20, y=440, width=610, height=260)
            r = await ag.pbi("pbi_add_visual", port=a.port, type="columnChart", page="By manager",
                             field=["Category='Date'[Month]", "Y=[Total Revenue]"], x=650, y=440, width=610,
                             height=260, title="Revenue by month", shot=True)
            check("page 2 visuals added and captured", r.get("ok") and r.get("_images", 0) >= 1, r)
            r = await ag.pbi("pbi_read", port=a.port, page="By manager")
            months = next((v for v in r.get("visuals", []) if v["type"] == "columnChart"), {}).get("rows", [])
            check("months sorted Jan..Dec through sortByColumn",
                  [m[0] for m in months] == ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                             "Nov", "Dec"], [m[0] for m in months])
            matrix = next((v for v in r.get("visuals", []) if v["type"] == "pivotTable"), {})
            text = json.dumps(matrix)
            check("matrix rows come through the relationship (managers)", all(n in text for n in REGIONS.values()),
                  matrix.get("rows", [])[:3])
            dax = await ag.pbi("pbi_dax", port=a.port, query='EVALUATE ROW("ann", CALCULATE([Total Revenue], '
                                                             'Regions[Manager] = "Ann"))')
            ann = (dax.get("rows") or [[None]])[0][0]
            check("matrix total for Ann equals DAX", ann is not None and f"{ann:.2f}" in text.replace(",", ""),
                  dax.get("rows") or dax.get("error"))

            # 6. interact: slicer on page 1
            r = await ag.pbi("pbi_slicer", port=a.port, page="Page 1", visual="slicer", select=["East"], shot=True)
            check("pbi_slicer selects East", r.get("ok") and r.get("selected") == ["East"], r)
            r = await ag.pbi("pbi_read", port=a.port, visual="clusteredColumnChart")
            shown = {row[0]: money(row[1]) for row in r.get("visual", {}).get("rows", [])}
            check("chart follows the slicer", shown == {"East": by_region["East"]}, shown)
            await ag.pbi("pbi_slicer", port=a.port, visual="slicer", clear=True)

            # 7. save, close, reopen
            r = await ag.pbi("pbi_save", port=a.port)
            check("pbi_save", r.get("ok") and r.get("saved"), r)
            sm = work / "proj" / "Sales.SemanticModel"
            check("TMDL has the tables and measures", (sm / "definition" / "tables" / "Sales.tmdl").is_file()
                  and "Total Revenue" in (sm / "definition" / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
                  and (sm / "definition" / "tables" / "Regions.tmdl").is_file())
            check("data cache saved (cache.abf)", (sm / ".pbi" / "cache.abf").is_file())
            r = await ag.pbi("pbi_close", port=a.port)
            check("pbi_close", r.get("ok") and r.get("closed"), r)
            r = await ag.pbi("pbi_launch", file=str(work / "proj" / "Sales.pbip"), port=a.port)
            check("pbi_launch reopens the project", r.get("ok") and r.get("loaded"), r)
            r = await ag.pbi("pbi_read", port=a.port, page="Page 1", visual="clusteredColumnChart")
            shown = {row[0]: money(row[1]) for row in r.get("visual", {}).get("rows", [])}
            check("data survived save + reopen", shown == by_region, {"shown": shown, "alerts": r.get("alerts")})
            r = await ag.pbi("pbi_shot", port=a.port, page="By manager")
            check("pbi_shot after reopen returns an image", r.get("ok") and r.get("_images", 0) == 1, r)
            if not a.keep_open:
                r = await ag.pbi("pbi_close", port=a.port, discard=True)
                check("final close", r.get("ok"), r)

    passed = sum(c["ok"] for c in check.results)
    report = {"passed": passed, "failed": len(check.results) - passed, "seconds": round(time.time() - t_start, 1),
              "checks": check.results, "calls": log}
    (work / "e2e_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{passed}/{len(check.results)} checks passed in {report['seconds']}s. Report: {work / 'e2e_report.json'}")
    return 0 if passed == len(check.results) else 1


def money(text) -> float | None:
    try:
        return float(str(text).split(" ")[0].replace("$", "").replace(",", ""))
    except ValueError:
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", default="pbidriver_e2e", help="working folder (default ./pbidriver_e2e)")
    p.add_argument("--port", type=int, default=9444, help="DevTools port for the test's Power BI window")
    p.add_argument("--modeling-cmd", help="command line of the Power BI Modeling MCP (default: the VS Code "
                                          "extension's exe if installed, else npx)")
    p.add_argument("--clean", action="store_true", help="delete the working folder first")
    p.add_argument("--keep-open", action="store_true", help="leave the Power BI window open at the end")
    a = p.parse_args()
    return asyncio.run(asyncio.wait_for(run(a), 1800))


if __name__ == "__main__":
    sys.exit(main())
