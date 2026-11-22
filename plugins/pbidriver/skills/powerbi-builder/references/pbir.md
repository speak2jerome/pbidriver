# PBIP projects and the PBIR report format

A PBIP project is a folder Power BI Desktop saves as plain files:

```text
<Name>.pbip                          shortcut Power BI opens (points at the report folder)
<Name>.Report/
  definition.pbir                    which semantic model the report uses (byPath ../<Name>.SemanticModel)
  definition/
    report.json                      report settings and theme
    version.json
    pages/
      pages.json                     page order and the active page
      <pageId>/page.json             name, size, display option
      <pageId>/visuals/<visualId>/visual.json   one file per visual
  StaticResources/SharedResources/BaseThemes/<theme>.json
<Name>.SemanticModel/
  definition.pbism
  definition/                        the model in TMDL: database.tmdl, model.tmdl, tables/<Table>.tmdl, ...
  .pbi/cache.abf                     the loaded data (local; keep it out of git)
```

`pbi_new` writes this layout with the schema versions Power BI Desktop 2.159 uses. Convert a .pbix with
`pbi_save as=<dir>/<Name>.pbip`.

## Who edits what

| Part | Edit with | Then |
|---|---|---|
| Model (`*.SemanticModel/definition`) | Power BI Modeling MCP | `pbi_save` writes the TMDL |
| Pages and common visuals | `pbi_add_page`, `pbi_add_visual`, `pbi_remove_visual` | `reload=true` / `shot=true` |
| Anything else in the report | the JSON files directly | `pbi_reload report_only=true` |

Never write the TMDL of a project that Power BI has open. With Power BI closed, TMDL edits are fine; open the
project afterwards (`pbi_launch`) and run `pbi_refresh`.

## visual.json

What `pbi_add_visual type=clusteredColumnChart field=["Category=Sales[Region]","Y=[Total Revenue]"] title="Revenue by region"` writes:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json",
  "name": "8a0ccc63e2b5e1ed3fdb",
  "position": {"x": 20, "y": 200, "z": 4000, "height": 250, "width": 620, "tabOrder": 4000},
  "visual": {
    "visualType": "clusteredColumnChart",
    "query": {"queryState": {
      "Category": {"projections": [{"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Region"}},
                                    "queryRef": "Sales.Region", "nativeQueryRef": "Region", "active": true}]},
      "Y": {"projections": [{"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Total Revenue"}},
                             "queryRef": "Sales.Total Revenue", "nativeQueryRef": "Total Revenue"}]}
    }},
    "visualContainerObjects": {"title": [{"properties": {
      "show": {"expr": {"Literal": {"Value": "true"}}},
      "text": {"expr": {"Literal": {"Value": "'Revenue by region'"}}}}}]},
    "drillFilterOtherVisuals": true
  }
}
```

- Field kinds: `Column`, `Measure`, or `Aggregation` (`{"Aggregation": {"Expression": {"Column": ...}, "Function": 0}}`;
  0 Sum, 1 Avg, 2 DistinctCount, 3 Min, 4 Max, 5 Count, 6 Median).
- Literals are DAX-like strings inside `{"expr": {"Literal": {"Value": ...}}}`: text `"'quoted'"`, numbers
  `"12D"` (double) or `"12L"` (integer), booleans `"true"`, colors as text `"'#118DFF'"`.
- `visual.objects` holds visual-specific formatting (data labels, legend, axes, colors); `visualContainerObjects`
  holds container formatting (title, background, border). Each is `{"<card>": [{"properties": {...}}]}`.
  Examples: data labels on: `"objects": {"labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]}`;
  legend off: `"legend": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}]`.
- To learn the JSON for a setting, change it once by hand in Power BI on a copy, save, and diff the files.
- Visual ids are 20 lowercase hex characters and must match the folder name. Page ids likewise.

## Pages

`pages.json` lists `pageOrder` (ids) and `activePageName`. A `page.json`:
`{"$schema": ".../page/2.1.0/schema.json", "name": "<id>", "displayName": "By manager", "displayOption": "FitToPage", "height": 720, "width": 1280}`.

## Checks after editing

`pbi_reload report_only=true`, then `pbi_alerts` (a malformed file shows up as a load error dialog or a broken
visual) and `pbi_shot annotate=true`.
