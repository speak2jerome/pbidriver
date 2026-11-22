"""Read a Power BI report definition (pages, visuals, types, fields) without opening Power BI.

Supports:
  * .pbix / .pbit with the classic `Report/Layout` (UTF-16 JSON)
  * .pbix with the newer PBIR folder `Report/definition/...`
  * .pbip projects whose `<name>.Report` folder holds PBIR `definition/` or legacy `report.json`
"""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


# --------------------------------------------------------------------------- loading

def _load_json_bytes(raw: bytes):
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError("Could not decode report JSON")


def load_definition(path: str | Path) -> tuple[str, object]:
    """Return ("legacy", layout_dict) or ("pbir", {relative_path: bytes})."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".pbix", ".pbit"):
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if "Report/Layout" in names:
                return "legacy", _load_json_bytes(z.read("Report/Layout"))
            prefix = "Report/definition/"
            files = {n[len(prefix):]: z.read(n) for n in names if n.startswith(prefix) and n.endswith(".json")}
            if files:
                return "pbir", files
        raise ValueError(f"No report definition found inside {p.name}")
    if suffix == ".pbip":
        pbip = json.loads(p.read_text(encoding="utf-8-sig"))
        report_dirs = [p.parent / a["report"]["path"] for a in pbip.get("artifacts", []) if "report" in a]
        report_dir = report_dirs[0] if report_dirs else p.with_name(p.stem + ".Report")
    elif p.is_dir():
        report_dir = p
    else:
        raise ValueError("Expected a .pbix, .pbit, .pbip or a .Report folder")
    definition = report_dir / "definition"
    if definition.is_dir():
        return "pbir", {f.relative_to(definition).as_posix(): f.read_bytes() for f in definition.rglob("*.json")}
    if (report_dir / "report.json").exists():
        return "legacy", _load_json_bytes((report_dir / "report.json").read_bytes())
    raise ValueError(f"No report definition in {report_dir}")


# --------------------------------------------------------------------------- helpers

def _literal(expr) -> str | None:
    """Unwrap {"expr": {"Literal": {"Value": "'text'"}}} style values."""
    try:
        v = expr["expr"]["Literal"]["Value"]
    except (KeyError, TypeError):
        return None
    return v[1:-1].replace("''", "'") if isinstance(v, str) and v.startswith("'") and v.endswith("'") else v


def _title(objects: dict | None) -> str | None:
    for item in (objects or {}).get("title", []) or []:
        props = item.get("properties", {})
        show = _literal(props.get("show"))
        text = _literal(props.get("text"))
        if text and show != "false":
            return text
    return None


def _textbox_text(objects: dict | None) -> str | None:
    """Plain text of a textbox visual (objects.general.paragraphs[].textRuns[].value)."""
    parts = []
    for item in (objects or {}).get("general", []) or []:
        for para in (item.get("properties", {}) or {}).get("paragraphs", []) or []:
            parts.append("".join(str(run.get("value", "")) for run in para.get("textRuns", []) or []))
    text = " ".join(p.strip() for p in parts if p.strip())
    return text[:200] or None


def _field_label(field: dict, sources: dict | None = None) -> str:
    """Human label for a field reference (Measure/Column/Aggregation...), e.g. "Sales.Amount".
    `sources` maps query aliases ("From": [{"Name": "s", "Entity": "Sales"}]) to table names."""
    if not isinstance(field, dict):
        return str(field)
    for kind in ("Measure", "Column", "Hierarchy", "HierarchyLevel"):
        if kind in field:
            f = field[kind]
            ref = f.get("Expression", {}).get("SourceRef", {})
            if "Hierarchy" in f.get("Expression", {}):
                ref = f["Expression"]["Hierarchy"].get("Expression", {}).get("SourceRef", {})
            entity = ref.get("Entity") or (sources or {}).get(ref.get("Source"), ref.get("Source"))
            name = f.get("Property") or f.get("Level") or f.get("Hierarchy")
            return f"{entity}.{name}" if entity else str(name)
    if "Aggregation" in field:
        agg = {0: "Sum", 1: "Avg", 2: "Count", 3: "Min", 4: "Max", 5: "CountNonNull", 6: "Median"}.get(field["Aggregation"].get("Function"), "Agg")
        return f"{agg}({_field_label(field['Aggregation'].get('Expression', {}), sources)})"
    return json.dumps(field)[:80]


def _condition_values(cond: dict, sources: dict) -> dict:
    """Readable gist of a filter condition: In-lists, comparisons, negation."""
    if not isinstance(cond, dict):
        return {}
    if "Not" in cond:
        inner = _condition_values(cond["Not"].get("Expression", {}), sources)
        return {**inner, "not": True}
    if "In" in cond:
        vals = [_literal({"expr": v[0]}) if v else None for v in cond["In"].get("Values", [])]
        return {"values": vals}
    if "Comparison" in cond:
        c = cond["Comparison"]
        op = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}.get(c.get("ComparisonKind"), "?")
        return {"compare": f"{op} {_literal({'expr': c.get('Right', {})})}"}
    for key in ("And", "Or"):
        if key in cond:
            parts = [_condition_values(cond[key].get(side, {}), sources) for side in ("Left", "Right")]
            return {key.lower(): parts}
    return {}


def _filters(raw) -> list[dict]:
    """Summarise a filter list (legacy JSON string or PBIR filterConfig)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("filters", [])
    out = []
    for f in raw or []:
        flt = f.get("filter") or {}
        sources = {s.get("Name"): s.get("Entity") for s in flt.get("From", []) if isinstance(s, dict)}
        item = {"field": _field_label(f.get("field") or f.get("expression") or {}, sources), "type": f.get("type")}
        where = flt.get("Where") or []
        if where:
            item.update(_condition_values(where[0].get("Condition", {}), sources))
        else:
            item["active"] = False  # a filter card with nothing selected
        for flag in ("isHiddenInViewMode", "isLockedInViewMode"):
            if f.get(flag):
                item[flag] = True
        out.append(item)
    return out


def _legacy_bookmarks(items: list, group: str | None = None) -> list[dict]:
    out = []
    for b in items or []:
        if b.get("children"):
            out += _legacy_bookmarks(b["children"], b.get("displayName"))
            continue
        out.append({"name": b.get("displayName"), "id": b.get("name"), "group": group,
                    "page_id": (b.get("explorationState") or {}).get("activeSection")})
    return out


def _pbir_bookmarks(files: dict[str, bytes]) -> list[dict]:
    meta = {}
    for key, raw in files.items():
        if key.startswith("bookmarks/") and key.endswith(".bookmark.json"):
            b = _load_json_bytes(raw)
            meta[b.get("name") or key.rsplit("/", 1)[-1].split(".")[0]] = b
    order, groups = [], {}
    if "bookmarks/bookmarks.json" in files:
        for item in _load_json_bytes(files["bookmarks/bookmarks.json"]).get("items", []):
            if item.get("children"):
                for child in item["children"]:
                    order.append(child)
                    groups[child] = item.get("displayName")
            else:
                order.append(item.get("name"))
    order += [k for k in meta if k not in order]
    return [{"name": meta[k].get("displayName", k), "id": k, "group": groups.get(k),
             "page_id": (meta[k].get("explorationState") or {}).get("activeSection")} for k in order if k in meta]


# --------------------------------------------------------------------------- normalise

def _legacy_pages(layout: dict) -> list[dict]:
    pages = []
    for ordinal, sec in enumerate(sorted(layout.get("sections", []), key=lambda s: s.get("ordinal", 0))):
        sec_cfg = json.loads(sec.get("config") or "{}")
        visuals = []
        for vc in sec.get("visualContainers", []):
            cfg = json.loads(vc.get("config") or "{}")
            sv = cfg.get("singleVisual")
            group = cfg.get("singleVisualGroup")
            fields = {role: [p.get("queryRef") for p in projs] for role, projs in (sv or {}).get("projections", {}).items()}
            visuals.append({
                "id": cfg.get("name"),
                "type": sv.get("visualType") if sv else ("group" if group else "unknown"),
                "title": _title((sv or {}).get("vcObjects")) or (group or {}).get("displayName"),
                "text": _textbox_text((sv or {}).get("objects")),
                "x": round(vc.get("x", 0)), "y": round(vc.get("y", 0)), "w": round(vc.get("width", 0)), "h": round(vc.get("height", 0)),
                "z": vc.get("z"),
                "hidden": ((sv or {}).get("display") or {}).get("mode") == "hidden" or bool((group or {}).get("isHidden")),
                "group": cfg.get("parentGroupName"),
                "fields": fields,
                "filters": _filters(vc.get("filters")),
            })
        pages.append({
            "index": ordinal, "id": sec.get("name"), "name": sec.get("displayName"),
            "hidden": sec_cfg.get("visibility") == 1,
            "width": sec.get("width"), "height": sec.get("height"),
            "filters": _filters(sec.get("filters")), "visuals": visuals,
        })
    return pages


def _pbir_pages(files: dict[str, bytes]) -> list[dict]:
    order = []
    if "pages/pages.json" in files:
        order = _load_json_bytes(files["pages/pages.json"]).get("pageOrder", [])
    page_ids = sorted({k.split("/")[1] for k in files if k.startswith("pages/") and k.count("/") >= 2})
    page_ids.sort(key=lambda pid: order.index(pid) if pid in order else len(order))
    pages = []
    for ordinal, pid in enumerate(page_ids):
        meta = _load_json_bytes(files.get(f"pages/{pid}/page.json", b"{}"))
        visuals = []
        for key in sorted(k for k in files if k.startswith(f"pages/{pid}/visuals/") and k.endswith("/visual.json")):
            v = _load_json_bytes(files[key])
            vis, pos = v.get("visual") or {}, v.get("position", {})
            fields = {}
            for role, state in ((vis.get("query") or {}).get("queryState") or {}).items():
                fields[role] = [pr.get("nativeQueryRef") or pr.get("queryRef") or _field_label(pr.get("field", {}))
                                for pr in state.get("projections", [])]
            group = v.get("visualGroup")
            visuals.append({
                "id": v.get("name"),
                "type": vis.get("visualType") or ("group" if group else "unknown"),
                "title": _title(vis.get("visualContainerObjects")) or (group or {}).get("displayName"),
                "text": _textbox_text(vis.get("objects")),
                "x": round(pos.get("x", 0)), "y": round(pos.get("y", 0)), "w": round(pos.get("width", 0)), "h": round(pos.get("height", 0)),
                "z": pos.get("z"),
                "hidden": bool(v.get("isHidden")),
                "group": v.get("parentGroupName"),
                "fields": fields,
                "filters": _filters(v.get("filterConfig")),
            })
        pages.append({
            "index": ordinal, "id": pid, "name": meta.get("displayName", pid),
            "hidden": meta.get("visibility") == "HiddenInViewMode",
            "width": meta.get("width"), "height": meta.get("height"),
            "filters": _filters(meta.get("filterConfig")), "visuals": visuals,
        })
    return pages


_CUSTOM = re.compile(r"([0-9A-F]{32}|\d{10,})$", re.I)  # custom visual ids end in a GUID or a long number


def report_inventory(path: str | Path) -> dict:
    """Pages and visuals of a report file, plus a usage summary by visual type."""
    kind, data = load_definition(path)
    if kind == "legacy":
        pages = _legacy_pages(data)
        cfg = json.loads(data.get("config") or "{}")
        bookmarks = _legacy_bookmarks(cfg.get("bookmarks", []))
        report_filters = _filters(data.get("filters"))
    else:
        pages = _pbir_pages(data)
        bookmarks = _pbir_bookmarks(data)
        report = _load_json_bytes(data["report.json"]) if "report.json" in data else {}
        report_filters = _filters(report.get("filterConfig"))
    page_names = {p["id"]: p["name"] for p in pages}
    for b in bookmarks:
        b["page"] = page_names.get(b.pop("page_id"))
    by_type: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        for v in page["visuals"]:
            v["custom"] = bool(_CUSTOM.search(v["type"] or ""))
            by_type[v["type"]].append(page["name"])
    summary = {t: {"count": len(where), "pages": dict(Counter(where))} for t, where in sorted(by_type.items(), key=lambda kv: -len(kv[1]))}
    return {"file": str(path), "format": kind, "page_count": len(pages),
            "visual_count": sum(len(p["visuals"]) for p in pages), "types": summary,
            "report_filters": report_filters, "bookmarks": bookmarks, "pages": pages}


if __name__ == "__main__":
    import sys

    print(json.dumps(report_inventory(sys.argv[1]), indent=2, ensure_ascii=False))
