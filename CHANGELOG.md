# Changelog

## 0.1.0 (2026-11-22)

First public release, as `pbidriver` (developed under the working name pbi_shot).

- **Capture:** canvas, single visual, every visual, full UI, and the Table / Model / DAX query / TMDL views. Options for `--scale` and `--annotate` (visual indices drawn on the image). Oversized canvases, minimized windows and background windows are handled.
- **Desktop Bridge:** page and visual captures, `reload` and unsaved state on any open Power BI Desktop (June 2026+), without DevTools.
- **Read:** chart data points, cards, tables and matrices (virtualized grids are scrolled through), slicer options and selection, textboxes.
- **Model:** `dax` queries and `model` (tables, columns, measures with DAX, relationships) through the ADOMD.NET client bundled with Power BI Desktop.
- **Performance:** `perf` reads Performance Analyzer timings per visual, optionally with each visual's DAX query.
- **Dialogs:** in-app, native WinForms and legacy Internet Explorer dialogs are detected on every call; `dialog` reads, captures and answers them. Input is refused while a modal blocks Power BI.
- **Interact:** `slicer`, `click`, `hover` (tooltips), `menu` (context and More options, with submenus), `scroll`, `type`, `key`, `bookmarks`, `wait`.
- **Report file:** `inventory` lists pages, visuals, fields, filters and bookmarks from `.pbix`, `.pbit` and `.pbip` files, in PBIR or legacy layout.
- **Lifecycle:** `launch` (isolated WebView2 profile per port), `instances`, `status`, `save`, `close --discard | --save`.
