# Changelog

## 0.2.0 (2026-11-22)

pbidriver now builds reports as well as inspecting them, and with Microsoft's Power BI Modeling MCP it's a complete kit for agents to build Power BI reports end to end.

- **MCP server:** `pbidriver mcp` exposes every command as a tool (`pbi_shot`, `pbi_add_visual`, ...) generated from the CLI's own options, returns screenshots as images, and adds a `pbi_guide` tool, guide resources and `build-report` / `review-report` prompts. Its instructions explain how to use it alongside the Power BI Modeling MCP. No new dependencies.
- **Agent setup:** `pbidriver setup` writes MCP configs for pbidriver and the Power BI Modeling MCP (Claude Code `.mcp.json`, VS Code `.vscode/mcp.json`, Cursor `.cursor/mcp.json`, Codex `.codex/config.toml`), an `AGENTS.md` section, `CLAUDE.md` import and the powerbi-builder skill, merging with what's there. `pbidriver doctor` checks the machine and project.
- **powerbi-builder skill:** the workflow (project, model, refresh, visuals, verify, save), visual types and roles, Modeling MCP recipes (CSV/Excel/SQL/DAX tables, relationships, measures, date tables), the PBIR format and troubleshooting. Also a Claude Code plugin marketplace in the repository: `/plugin marketplace add speak2jerome/pbidriver`.
- **Authoring PBIP projects:** `new` (blank project, `--open`), `layout`, `add-page`, `add-visual` (card, new card, column/bar/line/area/pie/donut charts, table, matrix, slicer, textbox; fields checked against the live model, including unsaved Modeling MCP changes; `--sort`), `remove-visual`. `--reload` / `--shot` show the result at once with a report-only reload.
- **`guide`:** the powerbi-builder guide from the command line (`pbi_guide` in MCP).
- **`launch`** returns the model's port and says when the data needs a refresh.
- **`save --as`:** saves the open report as a PBIP project (or `.pbix`/`.pbit`) through Power BI's own Save As dialog, so a `.pbix` can be authored.
- **`refresh`:** clicks the Refresh button itself (not its label), reports the failing query's error from Power BI's refresh dialog, and with `--sync` saves and reloads the project first so tables created through the Modeling MCP are refreshed, then saves the data. A refresh that leaves tables empty now says so instead of reporting success.
- **Legacy floating dialogs** (such as the refresh progress and error dialog) are detected, read, answered and captured like the other dialog kinds; a hidden one is no longer reported.
- **Fixes:** `model` on a model with no tables returns empty lists with a note instead of errors; `close` dismisses an error dialog instead of looking for "Don't save"; `launch` returns as soon as a load error dialog appears; pie and donut charts are read correctly; aggregation labels fixed (DistinctCount vs Count); a slicer's title renames its header and a card's title replaces its label, instead of showing the name twice; `read` on tables drops the "Row Selection" accessibility column; ambiguous field names get a clear error.
- **End-to-end test:** `scripts/e2e_kit.py` drives both MCP servers through the official MCP client against a real Power BI Desktop: project, model, refresh, two pages, slicing, save, reopen, 42 checks.

## 0.1.1 (2026-11-22)

No changes to commands.

- **npm package:** `npx pbidriver ...` or `npm install -g pbidriver` runs the same CLI from Node.js, through uv or Python. A JavaScript API, `run(args)`, resolves with each command's JSON result.
- **Documentation site:** [speak2jerome.github.io/pbidriver](https://speak2jerome.github.io/pbidriver/), with setup for Claude Code, GitHub Copilot, Codex and Cursor, a command reference, how it works and a FAQ.
- **Package metadata:** PyPI now links to the documentation and source, with more keywords and classifiers.
- **Installing on other platforms:** pywin32 is only required on Windows, so the package installs elsewhere, for example in docs builds and CI. The commands still need Windows and Power BI Desktop.

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
