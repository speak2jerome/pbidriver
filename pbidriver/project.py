"""Power BI projects (PBIP) for agents: scaffold a new project and author PBIR report pages and visuals.

The semantic model side is left to Microsoft's Power BI Modeling MCP server (TMDL); this module writes
the report side in the PBIR format that Power BI Desktop 2.15x writes itself, so an agent can add a
page or a visual with one call instead of hand-writing JSON, then `pbidriver reload` and look.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from pathlib import Path

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
SCHEMAS = {
    "pbip": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
    "platform": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
    "pbir": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
    "pbism": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
    "version": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
    "report": f"{SCHEMA}/item/report/definition/report/3.3.0/schema.json",
    "pages": f"{SCHEMA}/item/report/definition/pagesMetadata/1.1.0/schema.json",
    "page": f"{SCHEMA}/item/report/definition/page/2.1.0/schema.json",
    "visual": f"{SCHEMA}/item/report/definition/visualContainer/2.14.0/schema.json",
}

# Data roles per visual type: (role, kind) where kind is "column", "measure" or "any".
# Verified by rendering each type in Power BI Desktop 2.159 and reading it back with `pbidriver read`.
VISUALS: dict[str, dict] = {
    "card": {"roles": [("Values", "measure")], "about": "single number (classic card)"},
    "cardVisual": {"roles": [("Data", "measure")], "about": "new card, one or more measures"},
    "columnChart": {"roles": [("Category", "column"), ("Y", "measure"), ("Series", "column")], "about": "stacked column chart"},
    "clusteredColumnChart": {"roles": [("Category", "column"), ("Y", "measure"), ("Series", "column")], "about": "clustered column chart"},
    "barChart": {"roles": [("Category", "column"), ("Y", "measure"), ("Series", "column")], "about": "stacked bar chart"},
    "clusteredBarChart": {"roles": [("Category", "column"), ("Y", "measure"), ("Series", "column")], "about": "clustered bar chart"},
    "lineChart": {"roles": [("Category", "column"), ("Y", "measure"), ("Series", "column")], "about": "line chart"},
    "areaChart": {"roles": [("Category", "column"), ("Y", "measure"), ("Series", "column")], "about": "area chart"},
    "pieChart": {"roles": [("Category", "column"), ("Y", "measure")], "about": "pie chart"},
    "donutChart": {"roles": [("Category", "column"), ("Y", "measure")], "about": "donut chart"},
    "tableEx": {"roles": [("Values", "any")], "about": "table"},
    "pivotTable": {"roles": [("Rows", "column"), ("Columns", "column"), ("Values", "measure")], "about": "matrix"},
    "slicer": {"roles": [("Values", "column")], "about": "slicer (list or dropdown)"},
    "textbox": {"roles": [], "about": "text box (use --text)"},
}

# Power BI's query aggregation codes. Verified against DAX: 2 is a distinct count, 5 counts every
# non-blank row (what DAX COUNT returns).
AGGREGATIONS = {"sum": 0, "avg": 1, "average": 1, "distinctcount": 2, "min": 3, "max": 4, "count": 5, "median": 6}
_AGG_LABEL = {0: "Sum", 1: "Average", 2: "Count", 3: "Min", 4: "Max", 5: "Count", 6: "Median"}
_AGG_REF = {0: "Sum", 1: "Avg", 2: "Count", 3: "Min", 4: "Max", 5: "CountNonNull", 6: "Median"}


class ProjectError(Exception):
    """A project/PBIR problem the user or agent can fix; reported as {"ok": false, "error": ...}."""


BASE_THEME = "CY24SU10"  # the base theme Power BI Desktop 2.15x puts in new reports


def base_theme_file(name: str = BASE_THEME) -> Path:
    """The base theme JSON from the local Power BI Desktop install (not bundled with pbidriver)."""
    import glob
    import os
    import subprocess

    rel = Path("bin") / "WebView2Resources" / "minerva" / "sharedresources" / "BaseThemes" / f"{name}.json"
    roots: list[Path] = []
    if os.environ.get("PBI_DESKTOP_EXE"):
        roots.append(Path(os.environ["PBI_DESKTOP_EXE"]).resolve().parent.parent)
    roots.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Power BI Desktop")
    try:
        import psutil

        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "pbidesktop.exe" and p.info.get("exe"):
                roots.append(Path(p.info["exe"]).parent.parent)
    except Exception:  # noqa: BLE001
        pass
    for root in roots:
        if (root / rel).exists():
            return root / rel
    try:  # Microsoft Store build: the package folder isn't listable, so ask Windows where it is
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                              "(Get-AppxPackage Microsoft.MicrosoftPowerBIDesktop).InstallLocation"],
                             capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        for line in out.splitlines():
            if line and (Path(line) / rel).exists():
                return Path(line) / rel
    except (OSError, subprocess.SubprocessError):
        pass
    for hit in glob.glob(str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps" / "Microsoft.MicrosoftPowerBIDesktop_*" / rel)):
        return Path(hit)
    raise ProjectError(f"Couldn't find Power BI Desktop's {name} theme. Is Power BI Desktop installed? "
                       "Set PBI_DESKTOP_EXE to its PBIDesktop.exe if it's in an unusual place.")


def _hex_id(n: int = 20) -> str:
    return secrets.token_hex(n // 2 + 1)[:n]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _literal(value) -> dict:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = f"{value}D"
    else:
        text = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": text}}}


# --------------------------------------------------------------------------- locating a project

def report_dir(path: str | Path) -> Path:
    """The `<Name>.Report` folder of a .pbip file, a project folder, or the report folder itself."""
    p = Path(path).expanduser().resolve()
    if p.suffix.lower() == ".pbip":
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        rels = [a["report"]["path"] for a in data.get("artifacts", []) if "report" in a]
        p = (p.parent / rels[0]) if rels else p.with_name(p.stem + ".Report")
    elif p.is_dir() and not p.name.endswith(".Report"):
        reports = sorted(p.glob("*.Report"))
        if len(reports) != 1:
            raise ProjectError(f"Expected one .Report folder in {p}, found {len(reports)}. Pass the .pbip file.")
        p = reports[0]
    if not (p / "definition").is_dir():
        raise ProjectError(f"{p} has no PBIR definition/ folder. Legacy report.json projects can't be edited here; "
                           "re-save the report from Power BI Desktop (PBIR is the default since 2026).")
    return p


def model_dir(report: Path) -> Path | None:
    """The semantic model folder referenced by definition.pbir (byPath)."""
    pbir = report / "definition.pbir"
    if not pbir.exists():
        return None
    ref = json.loads(pbir.read_text(encoding="utf-8-sig")).get("datasetReference", {}).get("byPath", {}).get("path")
    return (report / ref).resolve() if ref else None


# --------------------------------------------------------------------------- new project

def new_project(folder: str | Path, name: str, page: str = "Page 1", width: int = 1280, height: int = 720,
                culture: str = "en-US") -> dict:
    """Create a blank PBIP: <name>.pbip, <name>.Report (PBIR, one page) and <name>.SemanticModel (TMDL)."""
    if not re.fullmatch(r"[^\\/:*?\"<>|]+", name):
        raise ProjectError(f"Invalid project name {name!r}.")
    root = Path(folder).expanduser().resolve()
    pbip = root / f"{name}.pbip"
    rep, sem = root / f"{name}.Report", root / f"{name}.SemanticModel"
    for p in (pbip, rep, sem):
        if p.exists():
            raise ProjectError(f"{p} already exists.")
    theme = base_theme_file()
    root.mkdir(parents=True, exist_ok=True)

    _write_json(pbip, {"$schema": SCHEMAS["pbip"], "version": "1.0",
                       "artifacts": [{"report": {"path": f"{name}.Report"}}], "settings": {"enableAutoRecovery": True}})
    for folder_, kind in ((rep, "Report"), (sem, "SemanticModel")):
        _write_json(folder_ / ".platform", {"$schema": SCHEMAS["platform"], "metadata": {"type": kind, "displayName": name},
                                            "config": {"version": "2.0", "logicalId": str(uuid.uuid4())}})
    _write_json(rep / "definition.pbir", {"$schema": SCHEMAS["pbir"], "version": "4.0",
                                          "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}})
    d = rep / "definition"
    _write_json(d / "version.json", {"$schema": SCHEMAS["version"], "version": "2.0.0"})
    # Power BI won't load a report without its base theme, and it expects the theme file in the project.
    themes = rep / "StaticResources" / "SharedResources" / "BaseThemes"
    themes.mkdir(parents=True, exist_ok=True)
    (themes / theme.name).write_bytes(theme.read_bytes())
    _write_json(d / "report.json", {
        "$schema": SCHEMAS["report"],
        "themeCollection": {"baseTheme": {"name": theme.stem,
                                          "reportVersionAtImport": {"visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"},
                                          "type": "SharedResources"}},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": theme.stem, "path": f"BaseThemes/{theme.name}", "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })
    _write_json(d / "pages" / "pages.json", {"$schema": SCHEMAS["pages"], "pageOrder": [], "activePageName": ""})
    first = add_page(rep, page, width, height)

    _write_json(sem / "definition.pbism", {"$schema": SCHEMAS["pbism"], "version": "4.2", "settings": {}})
    tm = sem / "definition"
    tm.mkdir(parents=True, exist_ok=True)
    (tm / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n\n", encoding="utf-8")
    (tm / "model.tmdl").write_text(
        "model Model\n"
        f"\tculture: {culture}\n"
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        f"\tsourceQueryCulture: {culture}\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        'annotation PBI_ProTooling = ["DevMode"]\n', encoding="utf-8")
    (root / ".gitignore").exists() or (root / ".gitignore").write_text(
        "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    return {"pbip": str(pbip), "report": str(rep), "semantic_model": str(sem), "tmdl": str(tm), "page": first}


# --------------------------------------------------------------------------- pages

def _pages_meta(rep: Path) -> tuple[Path, dict]:
    path = rep / "definition" / "pages" / "pages.json"
    meta = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"$schema": SCHEMAS["pages"], "pageOrder": []}
    return path, meta


def list_pages(rep: Path) -> list[dict]:
    _, meta = _pages_meta(rep)
    out = []
    for i, pid in enumerate(meta.get("pageOrder", [])):
        page_file = rep / "definition" / "pages" / pid / "page.json"
        if page_file.exists():
            pj = json.loads(page_file.read_text(encoding="utf-8-sig"))
            visuals = sorted((rep / "definition" / "pages" / pid / "visuals").glob("*/visual.json"))
            out.append({"index": i, "id": pid, "name": pj.get("displayName", pid), "width": pj.get("width"),
                        "height": pj.get("height"), "visuals": len(visuals)})
    return out


def find_page(rep: Path, spec: str | None) -> dict:
    pages = list_pages(rep)
    if not pages:
        raise ProjectError("The report has no pages; add one with add-page.")
    if spec is None:
        _, meta = _pages_meta(rep)
        active = meta.get("activePageName")
        return next((p for p in pages if p["id"] == active), pages[0])
    s = spec.strip().lower()
    for test in (lambda p: str(p["index"]) == s, lambda p: p["id"].lower() == s, lambda p: p["name"].lower() == s,
                 lambda p: s in p["name"].lower()):
        hits = [p for p in pages if test(p)]
        if len(hits) == 1:
            return hits[0]
    raise ProjectError(f"No single page matches {spec!r}. Pages: " + ", ".join(p["name"] for p in pages))


def add_page(rep: Path, name: str, width: int = 1280, height: int = 720, display: str = "FitToPage") -> dict:
    pid = _hex_id()
    _write_json(rep / "definition" / "pages" / pid / "page.json", {
        "$schema": SCHEMAS["page"], "name": pid, "displayName": name, "displayOption": display,
        "height": height, "width": width})
    path, meta = _pages_meta(rep)
    meta.setdefault("pageOrder", []).append(pid)
    if not meta.get("activePageName"):
        meta["activePageName"] = pid
    _write_json(path, meta)
    return {"id": pid, "name": name, "width": width, "height": height}


# --------------------------------------------------------------------------- model fields

_TMDL_NAME = r"(?:'(?P<q>(?:[^']|'')+)'|(?P<b>[^\s=]+))"


def _unquote(m) -> str:
    return m.group("q").replace("''", "'") if m.group("q") is not None else m.group("b")


def model_fields_from_tmdl(sem_definition: Path) -> dict[str, dict[str, set]]:
    """{table: {"columns": {...}, "measures": {...}}} from TMDL files."""
    out: dict[str, dict[str, set]] = {}
    for f in sorted((sem_definition / "tables").glob("*.tmdl")):
        table = None
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^table " + _TMDL_NAME, line)
            if m:
                table = _unquote(m)
                out.setdefault(table, {"columns": set(), "measures": set()})
                continue
            if table is None:
                continue
            m = re.match(r"^\t(column|measure) " + _TMDL_NAME, line)
            if m:
                out[table]["columns" if m.group(1) == "column" else "measures"].add(_unquote(m))
    return out


def model_fields_from_info(info: dict) -> dict[str, dict[str, set]]:
    """Same shape from pbidriver.bridge.model_info() (the live model, including unsaved changes)."""
    out: dict[str, dict[str, set]] = {}
    for c in info.get("columns", []) if isinstance(info.get("columns"), list) else []:
        out.setdefault(c.get("Table"), {"columns": set(), "measures": set()})["columns"].add(c.get("Name"))
    for m in info.get("measures", []) if isinstance(info.get("measures"), list) else []:
        out.setdefault(m.get("Table"), {"columns": set(), "measures": set()})["measures"].add(m.get("Name"))
    return out


_FIELD = re.compile(r"^\s*(?:(?P<agg>[A-Za-z]+)\s*\(\s*(?P<inner>.+)\s*\)|(?P<plain>.+?))\s*$")
_REF = re.compile(r"^\s*(?:'(?P<tq>(?:[^']|'')+)'|(?P<t>[^\[]+?))?\s*\[(?P<f>[^\]]+)\]\s*$")


def parse_field(spec: str, fields: dict[str, dict[str, set]] | None) -> dict:
    """'Sales[Amount]', "'My Table'[Total Sales]", '[Total Sales]' or 'Sum(Sales[Amount])' -> projection."""
    m = _FIELD.match(spec)
    agg = None
    body = spec
    if m and m.group("agg") and m.group("agg").lower() in AGGREGATIONS:
        agg, body = AGGREGATIONS[m.group("agg").lower()], m.group("inner")
    r = _REF.match(body)
    if not r:
        raise ProjectError(f"Field {spec!r} should look like Table[Column], [Measure] or Sum(Table[Column]) "
                           f"(aggregations: {', '.join(sorted(AGGREGATIONS))}).")
    table = (r.group("tq").replace("''", "'") if r.group("tq") else (r.group("t") or "").strip()) or None
    name = r.group("f")
    kind = None
    if fields:
        owners = [t for t, v in fields.items() if name in v["columns"] or name in v["measures"]]
        if table is None:
            owners_m = [t for t, v in fields.items() if name in v["measures"]]
            if len(owners_m) == 1:
                table = owners_m[0]
            elif len(owners) == 1:
                table = owners[0]
        if table is None and not owners:
            raise ProjectError(f"No column or measure named {name!r} in the model. Tables: {', '.join(sorted(fields)) or '(none yet)'}")
        if table is None:
            raise ProjectError(f"Can't tell which table {spec!r} belongs to: {name!r} is in "
                               f"{', '.join(sorted(owners))}. Write it as Table[{name}].")
        if table not in fields:
            known = ", ".join(sorted(fields)) or "(none yet)"
            raise ProjectError(f"Unknown table in {spec!r}. Tables: {known}")
        if name in fields[table]["measures"]:
            kind = "measure"
        elif name in fields[table]["columns"]:
            kind = "column"
        else:
            cols = sorted(fields[table]["columns"])[:30]
            meas = sorted(fields[table]["measures"])[:30]
            raise ProjectError(f"{table!r} has no column or measure {name!r}. Columns: {cols}. Measures: {meas}")
    if table is None:
        raise ProjectError(f"Can't tell which table {spec!r} belongs to; write it as Table[{name}].")
    if kind is None:
        kind = "measure" if body.strip().startswith("[") else "column"
    if agg is not None and kind == "measure":
        raise ProjectError(f"{spec!r}: measures can't take an aggregation.")
    source = {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}
    if agg is not None:
        field = {"Aggregation": {"Expression": {"Column": source}, "Function": agg}}
        return {"field": field, "queryRef": f"{_AGG_REF[agg]}({table}.{name})", "nativeQueryRef": f"{_AGG_LABEL[agg]} of {name}",
                "kind": "aggregate"}
    return {"field": {("Measure" if kind == "measure" else "Column"): source}, "queryRef": f"{table}.{name}",
            "nativeQueryRef": name, "kind": kind}


# --------------------------------------------------------------------------- visuals

def add_visual(rep: Path, page_spec: str | None, vtype: str, roles: dict[str, list[str]], x: float, y: float,
               width: float, height: float, title: str | None = None, text: str | None = None,
               slicer_mode: str | None = None, fields: dict[str, dict[str, set]] | None = None,
               sort: str | None = None, sort_dir: str = "desc") -> dict:
    """Write one visual.json. `roles` maps a data role (see VISUALS) to field specs."""
    if vtype not in VISUALS:
        raise ProjectError(f"Unsupported visual type {vtype!r}. Supported: {', '.join(VISUALS)}")
    spec = VISUALS[vtype]
    allowed = {r for r, _ in spec["roles"]}
    unknown = set(roles) - allowed
    if unknown:
        raise ProjectError(f"{vtype} has no role {sorted(unknown)}. Roles: {sorted(allowed) or 'none'}")
    page = find_page(rep, page_spec)
    vid = _hex_id()
    existing = sorted((rep / "definition" / "pages" / page["id"] / "visuals").glob("*/visual.json"))
    z = 1000 * (len(existing) + 1)
    visual: dict = {"visualType": vtype}
    query: dict = {}
    for role, kind in spec["roles"]:
        specs = roles.get(role) or []
        if not specs:
            continue
        projections = []
        for s in specs:
            proj = parse_field(s, fields)
            if kind == "measure" and proj["kind"] == "column":
                raise ProjectError(f"{vtype} role {role} needs a measure or an aggregation like Sum({s}), not a column.")
            if kind == "column" and proj["kind"] != "column":
                raise ProjectError(f"{vtype} role {role} needs a column, not {s!r}.")
            proj.pop("kind")
            if role in ("Category", "Rows", "Columns", "Series") or (vtype == "slicer"):
                proj["active"] = True
            projections.append(proj)
        query[role] = {"projections": projections}
    if spec["roles"] and not query:
        need = ", ".join(r for r, _ in spec["roles"])
        raise ProjectError(f"{vtype} needs fields for at least one role: {need}")
    if query:
        visual["query"] = {"queryState": query}
    if sort:
        if not query:
            raise ProjectError("--sort needs a visual with fields.")
        visual["query"]["sortDefinition"] = {"sort": [{
            "field": parse_field(sort, fields)["field"],
            "direction": "Ascending" if sort_dir.lower().startswith("asc") else "Descending"}]}
    objects: dict = {}
    if vtype == "textbox":
        if not text:
            raise ProjectError("A textbox needs --text.")
        objects["general"] = [{"properties": {"paragraphs": [
            {"textRuns": [{"value": line, "textStyle": {"fontSize": "14pt"}}]} for line in text.split("\n")]}}]
    if vtype == "slicer" and slicer_mode:
        objects["data"] = [{"properties": {"mode": _literal("Dropdown" if slicer_mode.lower() == "dropdown" else "Basic")}}]
    if vtype == "slicer" and title:  # a slicer already has a header (the field name): retitle that one
        objects["header"] = [{"properties": {"text": _literal(title)}}]
        title = None
    if vtype == "card" and title:  # a card labels its number with the field name; the title replaces that label
        objects["categoryLabels"] = [{"properties": {"show": _literal(False)}}]
    if objects:
        visual["objects"] = objects
    if title:
        visual["visualContainerObjects"] = {"title": [{"properties": {"show": _literal(True), "text": _literal(title)}}]}
    visual["drillFilterOtherVisuals"] = True
    data = {"$schema": SCHEMAS["visual"], "name": vid,
            "position": {"x": x, "y": y, "z": z, "height": height, "width": width, "tabOrder": z},
            "visual": visual}
    path = rep / "definition" / "pages" / page["id"] / "visuals" / vid / "visual.json"
    _write_json(path, data)
    return {"id": vid, "page": page["name"], "type": vtype, "file": str(path)}


def remove_visual(rep: Path, page_spec: str | None, visual_id: str) -> dict:
    import shutil

    page = find_page(rep, page_spec)
    folder = rep / "definition" / "pages" / page["id"] / "visuals" / visual_id
    if not (folder / "visual.json").exists():
        raise ProjectError(f"No visual {visual_id!r} on page {page['name']!r}.")
    shutil.rmtree(folder)
    return {"removed": visual_id, "page": page["name"]}


def list_visuals(rep: Path, page_spec: str | None) -> list[dict]:
    page = find_page(rep, page_spec)
    out = []
    for f in sorted((rep / "definition" / "pages" / page["id"] / "visuals").glob("*/visual.json")):
        v = json.loads(f.read_text(encoding="utf-8-sig"))
        pos = v.get("position", {})
        qs = (v.get("visual", {}).get("query") or {}).get("queryState") or {}
        out.append({"id": v.get("name"), "type": v.get("visual", {}).get("visualType"),
                    "x": pos.get("x"), "y": pos.get("y"), "width": pos.get("width"), "height": pos.get("height"),
                    "fields": {role: [p.get("queryRef") for p in st.get("projections", [])] for role, st in qs.items()}})
    return out
