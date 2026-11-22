---
name: powerbi-builder
description: Build, change and verify Power BI reports end to end in Power BI Desktop. Use pbidriver (pbi_* tools or the pbidriver CLI) for projects, pages, visuals, screenshots, on-screen numbers, slicers, dialogs, refresh and save. Use Microsoft's Power BI Modeling MCP (table_operations, measure_operations, relationship_operations, ...) for the semantic model. Use when asked to create a Power BI report or dashboard, add or fix visuals or pages, model data for Power BI, or check what a Power BI report shows.
---

# Power BI builder

Two tools, two jobs. Use both; neither can do the other's job.

| Job | Use | Tools |
|---|---|---|
| Semantic model: tables, columns, measures, relationships, model-level DAX | **Power BI Modeling MCP** (Microsoft) | `connection_operations`, `table_operations`, `column_operations`, `measure_operations`, `relationship_operations`, `dax_query_operations`, ... |
| Power BI Desktop and the report: create/open projects, pages, visuals, screenshots, the numbers on screen, slicers, clicks, dialogs, refresh, save | **pbidriver** | `pbi_new`, `pbi_launch`, `pbi_add_visual`, `pbi_shot`, `pbi_read`, `pbi_dax`, `pbi_refresh`, `pbi_save`, ... |

Without MCP, every `pbi_<name>` tool is the CLI command `pbidriver <name>` (also `uvx pbidriver <name>` or
`npx pbidriver <name>`); arguments become `--flags` (`add_visual field=[...]` is `add-visual --field ... --field ...`)
and the output is the same JSON. `pbi_guide topic=X` is `pbidriver guide X`.

Screenshots are written to `./pbidriver_shots/` under the working folder (for the MCP server, the folder the
client started it in) unless you pass `out=<file.png>`; MCP tools also return them as images.

More detail (also available through the `pbi_guide` tool, `topic=` in brackets):

- [Visual types, roles, field syntax and layout grid](references/visuals.md) (`visuals`)
- [Power BI Modeling MCP recipes: connect, tables, relationships, measures, date table](references/modeling-mcp.md) (`modeling-mcp`)
- [PBIP folder layout and the PBIR visual.json format](references/pbir.md) (`pbir`)
- [Troubleshooting: symptoms and fixes](references/troubleshooting.md) (`troubleshooting`)

## Build a new report from data

1. **Project.** `pbi_new folder=<dir> name=<Name> open=true`. Creates a PBIP project (PBIR report + empty
   model) and opens it in Power BI Desktop with DevTools on `port` (default 9333). The result has `model_port`.
   For several Power BI windows give each its own `port`, and pass that `port` to every later call.
2. **Connect the Modeling MCP.** `connection_operations {"operation": "Connect", "dataSource": "localhost:<model_port>"}`.
   (`pbi_instances` lists every Power BI window with its `model_port`.) The first write asks the user to
   confirm once per model; a first-time user may also be asked to accept Microsoft's EULA. Ask the user, never
   accept on their behalf.
3. **Model.** With the Modeling MCP (exact requests: `pbi_guide topic=modeling-mcp`):
   - `table_operations Create`: `mExpression` (CSV, Excel, SQL, web...) plus `columns` with `name` and `dataType`;
     or `daxExpression` for calculated tables (no columns).
   - `relationship_operations Create`: from = many side (fact), to = one side (dimension).
   - `measure_operations Create`: `tableName`, `name`, `expression`, `formatString`.
4. **Load data with `pbi_refresh sync=true`.** After creating or changing tables through the Modeling MCP,
   Power BI's own refresh skips them until it re-reads the model; `sync=true` saves the project, reloads it
   from disk, refreshes, and saves again so the data is kept. Don't rely on the Modeling MCP's Refresh: Power
   BI only keeps data it loaded itself, so such a project reopens with blank visuals and a "Refresh now"
   banner. When `refreshed` is false, `error` says why (wrong path, bad column type): fix the table,
   `pbi_dialog click=Close`, refresh again. Measure-only changes need no refresh. After a plain `pbi_refresh`,
   `pbi_save` before adding visuals: a report reload makes Power BI forget the data changed.
5. **Check the model.** `pbi_model` (tables, columns, measures, relationships) and `pbi_dax` (`EVALUATE ...`).
6. **Pages and visuals.** `pbi_add_visual type=<type> field=[...] x= y= width= height= title=` per visual.
   Fields are checked against the live model, so typos fail fast with the valid names. Set `shot=true` on the
   last visual of a batch: it reloads the report and returns an annotated screenshot. Plan the layout on the
   1280x720 canvas first (`pbi_guide topic=visuals` has a grid). `pbi_add_page name=...` adds pages
   (then pass `page=` to add_visual). `pbi_layout` lists visual ids; `pbi_remove_visual` deletes one.
   `reload=true` and `shot=true` reload the report only: measures and tables you just made with the Modeling
   MCP stay, unsaved, and show up at once. Visual edits are written to disk right away, so a later `pbi_save`
   may report `had_unsaved_changes: false`; that's expected.
7. **Verify, don't assume.** Look at the screenshot: titles, overlaps, truncated labels, empty visuals. Then
   `pbi_read` gives the numbers each visual shows; compare a few with `pbi_dax`. A visual can render without
   errors and still be wrong (a missing relationship repeats the grand total on every row; a column summed
   instead of counted). `pbi_alerts` must come back empty.
8. **Save.** `pbi_save`. Writes the report, the model (TMDL) and the data cache to the project folder.

## Work on an existing report

- **.pbip:** `pbi_launch file=<path>.pbip`. **.pbix:** `pbi_launch`, then `pbi_save as=<dir>/<Name>.pbip` to convert
  it; pbidriver authors visuals in PBIP projects only. A .pbix can still be inspected and driven.
  `pbi_launch` returns `model_port` (for the Modeling MCP). If it returns `next` about a refresh, or
  `alerts.banners` says "Refresh now" (data missing or stale), run `pbi_refresh sync=true` before reading numbers.
- Look first: `pbi_inventory` (pages, visuals, fields, filters, bookmarks from the file, no clicking),
  `pbi_pages`, `pbi_shot page=... annotate=true` per page, `pbi_read`.
- Model changes go through the Modeling MCP, connected as in step 2. Report changes go through
  `pbi_add_visual` / `pbi_remove_visual` / `pbi_add_page`, or by editing PBIR JSON (`pbi_guide topic=pbir`)
  and then `pbi_reload report_only=true`.
- Interact like a user: `pbi_slicer`, `pbi_click`, `pbi_hover` (tooltips), `pbi_menu` (context menus, e.g. sort),
  `pbi_bookmarks`, `pbi_scroll`, `pbi_type`, `pbi_key`. Add `shot=true` to see the result.
- Performance: `pbi_perf` (Performance Analyzer timings per visual, `queries=true` for their DAX).

## Rules

- **Never hand-edit TMDL files of a project that is open in Power BI.** Power BI overwrites them on save. Model
  changes go through the Modeling MCP and reach the files on `pbi_save`.
- **Report files on disk change, Power BI doesn't notice:** after editing PBIR JSON yourself, call
  `pbi_reload report_only=true`. That keeps unsaved Modeling MCP changes; a full reload re-reads the model from
  disk, so save before one.
- **Every pbidriver result is JSON** with `ok`. Read `error`, `next` and `alerts`. `alerts` lists blocking
  dialogs, message banners and visuals that show an error, whatever tool you called.
- **A dialog blocks Power BI:** `pbi_dialog` reads it, `pbi_dialog click=<button>` answers it. Don't pass
  `force=true` to type or click through a dialog unless you mean to.
- **Close only windows you opened**, with `pbi_close` (`discard=true` or `save=true` when there are unsaved
  changes). Don't kill Power BI processes.
- **One window per port.** `pbi_launch` and `pbi_new open=true` start a new window; pass the same `port` to every
  call for it.
- Screenshots and reads come from the real Power BI window. Keep the user informed when a step changes their
  files, and show them the final screenshots.

## pbidriver tools at a glance

| Need | Tool |
|---|---|
| Machine ready? | `pbi_doctor` |
| Windows, files, ports | `pbi_instances`, `pbi_status` |
| New project / open file / convert .pbix | `pbi_new`, `pbi_launch`, `pbi_save as=` |
| Pages and visuals in the files | `pbi_layout`, `pbi_add_page`, `pbi_add_visual`, `pbi_remove_visual`, `pbi_reload` |
| What the report looks like | `pbi_shot` (canvas, `visual=`, `full=true`, `view=table/model/dax/tmdl`, `annotate=true`) |
| What the visuals show | `pbi_read`, `pbi_visuals`, `pbi_inventory` |
| Model | `pbi_model`, `pbi_dax` (read-only checks; changes go through the Modeling MCP) |
| Data | `pbi_refresh` |
| Interact | `pbi_slicer`, `pbi_click`, `pbi_hover`, `pbi_menu`, `pbi_scroll`, `pbi_type`, `pbi_key`, `pbi_bookmarks`, `pbi_wait` |
| Dialogs and problems | `pbi_alerts`, `pbi_dialog` |
| Speed | `pbi_perf` |
| Finish | `pbi_save`, `pbi_close` |
