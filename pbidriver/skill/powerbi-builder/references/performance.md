# Performance tuning

## Measure

`pbi_perf` refreshes the page's visuals with Power BI's Performance Analyzer and returns, per visual:
`total_ms`, `dax_query_ms`, `visual_display_ms`, `other_ms` (waiting for other visuals), `direct_query_ms` when
there is DirectQuery, the `bottleneck` (the largest part), `slow` (at or over `threshold`), and `hints`.

| Option | Use |
|---|---|
| `runs=3` | refresh three times and report medians (single runs vary) |
| `cold=true` | clear the model engine's cache before each refresh: what a first-time viewer gets |
| `threshold=500` | ms from which a visual counts as slow (default 500) |
| `top=5` | only the slowest visuals |
| `all_pages=true` | every visible page, slowest first, top visuals per page |
| `queries=true` | each visual's DAX query (copied through the clipboard, which is restored) |

`pbi_shot overlay=[index, title, perf]` paints each visual's render time on the page.
`pbi_dax query=... runs=3 cold=true` times one query cold (min, median, max), for comparing a measure before
and after a change.

## Workflow

1. Baseline: `pbi_perf runs=3 cold=true` on each important page (or `all_pages=true`). Note `slowest_ms` and
   `sum_ms`.
2. For each slow visual, read its `bottleneck`:
   - `dax_query`: `pbi_perf queries=true` for its query. Time it with `pbi_dax runs=3 cold=true`. For detail,
     the Power BI Modeling MCP: `dax_query_operations` `{"operation": "ClearCache"}`, then
     `{"operation": "Execute", "query": "...", "getExecutionMetrics": true}` shows storage engine vs formula
     engine time. Find the measures it uses (`pbi_model part=measures`) and rewrite them with the Modeling MCP
     (`measure_operations Update`).
   - `visual_display`: too many points or a heavy visual. Add a Top N filter, use a lower-granularity axis
     (month instead of day), or a simpler visual type.
   - `other`: the visual waits because the page sends many queries at once. Fewer visuals per page, one new card
     (`cardVisual`) with several measures instead of many cards, details on another page.
   - `direct_query`: the source is slow: aggregate there, add an aggregation table, or import the table.
3. Re-measure with the same `runs` and `cold`, and compare. Keep a change only if it helps and `pbi_dax` returns
   the same numbers as before.
4. `pbi_save`.

## DAX patterns that are usually slow

- `FILTER(Table, ...)` over a whole fact table inside `CALCULATE`: filter a column instead
  (`CALCULATE([Sales], Sales[Region] = "East")`) or use `KEEPFILTERS`.
- Iterators (`SUMX`, `AVERAGEX`) over large tables with nested `CALCULATE` per row: aggregate first, or use a
  column that already holds the value.
- Repeating the same sub-expression: compute it once in a `VAR`.
- `DISTINCTCOUNT` on high-cardinality columns in big visuals.
- Measures that reference many other heavy measures in one visual: check which one is slow by timing each.
- Bidirectional relationships and many-to-many relationships on big tables.

## Model checks

- Hide and set `summarizeBy: None` on ID columns; remove columns no visual uses.
- Turn off auto date/time for large models and use one marked date table.
- Prefer integer keys for relationships; avoid calculated columns on large tables when Power Query can do it.

## Faster pbidriver commands

Commands wait up to `settle` seconds (default 20) for rendering to finish. On light pages a lower `settle`
(for example 5), or the environment variable `PBIDRIVER_SETTLE`, makes commands return sooner.
