# Visuals: types, roles, fields, layout

`pbi_add_visual` (CLI `pbidriver add-visual`) writes one visual into the PBIR files of the PBIP project open in
Power BI (or `project=<file.pbip>`). Set `reload=true` to show it right away, or `shot=true` to reload and get an
annotated screenshot back (`out=` picks the file; add `clean=true` for an unlabelled capture with a layout check).
Both reload the report only, so unsaved model changes stay.

## Types and roles

| `type` | What it is | Roles (kind of field) |
|---|---|---|
| `card` | single number, classic card | `Values` (measure) |
| `cardVisual` | new card, one or more numbers | `Data` (measure) |
| `clusteredColumnChart` | side-by-side columns | `Category` (column), `Y` (measure), `Series` (column) |
| `columnChart` | stacked columns | `Category`, `Y`, `Series` |
| `clusteredBarChart` | side-by-side horizontal bars | `Category`, `Y`, `Series` |
| `barChart` | stacked horizontal bars | `Category`, `Y`, `Series` |
| `lineChart` | line over a category or date axis | `Category`, `Y`, `Series` |
| `areaChart` | area | `Category`, `Y`, `Series` |
| `pieChart`, `donutChart` | share of total | `Category` (column), `Y` (measure) |
| `tableEx` | table | `Values` (columns and measures, in order) |
| `pivotTable` | matrix | `Rows` (column), `Columns` (column), `Values` (measure) |
| `slicer` | filter control; `mode=list` (checkboxes) or `mode=dropdown` | `Values` (column) |
| `textbox` | heading or note; `text=` (`\n` for new lines) | none |

A role can take several fields (repeat `field`): several `Y` measures give several series, several `Rows` give
a drill-down hierarchy.

## Field syntax

| Write | Means |
|---|---|
| `Sales[Region]` | column `Region` of table `Sales` |
| `'Sales Orders'[Order Date]` | quote table names with spaces |
| `[Total Revenue]` | measure (the table is found for you) |
| `Sales[Total Revenue]` | measure with its table |
| `Sum(Sales[Units])` | implicit measure: `Sum`, `Avg`/`Average`, `Min`, `Max`, `Count`, `DistinctCount`, `Median` |
| `Category=Sales[Region]` | put the field in a specific role |

Without `Role=`, a field goes to the first empty role that takes its kind (columns to `Category`/`Rows`,
measures and aggregates to `Y`/`Values`), else the last role that fits. Prefer explicit measures
(`measure_operations Create`) over implicit aggregates: they carry a format string and a clear name.

Field names are checked against the live model (or the TMDL files when Power BI isn't open). An error lists
the valid names: create missing measures first.

## Position and size

`x`, `y`, `width`, `height` are in canvas pixels; the default canvas is 1280 x 720 (`pbi_new width= height=`
changes it). Defaults: x=20, y=20, a third of the page wide and tall. Visuals added later sit on top.

A grid that works for 1280 x 720 (20 px margins and gaps):

| Row | y | height | Contents |
|---|---|---|---|
| Header | 10 | 50 | `textbox` title (width 900) + `slicer mode=dropdown` at x=960, width 300, height 90 |
| KPIs | 70 | 110 | up to 4 `card`s, width 290, at x = 20, 330, 640, 950 |
| Main | 200 | 250 | 2 charts, width 610, at x = 20 and 650 |
| Detail | 470 | 240 | table/matrix and a chart, width 610, at x = 20 and 650 |

Keep 1 to 2 rows of 2 charts per page; move detail to a second page (`pbi_add_page`) rather than shrinking
visuals until labels truncate. Check the screenshot after each batch.

## Titles and text

`title=` sets the visual's title (charts show a default title built from their fields otherwise). For a
slicer it renames the slicer header. For a `card` it replaces the label under the number (without `title`, the
card shows the measure name under the number, which is usually enough). Textboxes use `text=`; they render at 14 pt.

## Sorting

`sort="[Total Revenue]"` (and `sort_dir=asc`, default `desc`) sorts a chart or table by one of its fields when
it's added. To change the sort of an existing visual, use its menu like a user would:
`pbi_menu visual=<i> more=true` lists the items, `pbi_menu visual=<i> more=true choose="Sort by > Total Revenue"`
picks the field, `choose="Sort by > Sort descending"` sets the direction; then `pbi_save` writes it to the file.

## Changing or removing

There is no in-place edit: `pbi_layout` (ids, types, positions, fields per page), `pbi_remove_visual id=...`,
then add it again. For formatting `add_visual` doesn't cover (colors, data labels, conditional formatting,
other visual types), edit the visual's `visual.json` (see `pbi_guide topic=pbir`) and `pbi_reload report_only=true`.

## Reading back

- `pbi_shot clean=true`: the page as a viewer sees it, plus a layout check (see `pbi_guide topic=design`).
- `pbi_shot annotate=true`: canvas image with each visual's index and type drawn on it. The index is what
  `visual=` means in other tools (`pbi_read visual=2`, `pbi_click visual=2 text=East`). `visual=` also takes
  text that matches one visual's title, type or content.
- `pbi_read`: every visual's numbers (chart points with category and value, card values, table and matrix
  rows including totals, slicer items and selection), formatted as on screen.
- `pbi_visuals`: live list with type, label, position and any error text.
