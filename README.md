# pbidriver

[![PyPI](https://img.shields.io/pypi/v/pbidriver)](https://pypi.org/project/pbidriver/)
[![npm](https://img.shields.io/npm/v/pbidriver)](https://www.npmjs.com/package/pbidriver)
[![Python](https://img.shields.io/pypi/pyversions/pbidriver)](https://pypi.org/project/pbidriver/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-speak2jerome.github.io%2Fpbidriver-indigo)](https://speak2jerome.github.io/pbidriver/)

**WebDriver for Power BI Desktop.** Let AI agents see and drive Power BI Desktop: screenshots of pages, visuals and every view, the data behind visuals, blocking dialogs, slicers, tooltips, menus, bookmarks, DAX and Performance Analyzer. It all runs locally against Power BI Desktop, with no screen grabs and no publishing to the service.

(Not a data connector or ODBC driver: "driver" as in WebDriver, the thing that drives an app for automation.)

**Documentation:** [speak2jerome.github.io/pbidriver](https://speak2jerome.github.io/pbidriver/), with [setup for Claude Code, Copilot, Codex and Cursor](https://speak2jerome.github.io/pbidriver/agents/) and a [FAQ](https://speak2jerome.github.io/pbidriver/faq/).

Every command is a CLI call that prints one JSON object, so any agent that can run a shell command can use it: Claude Code, Codex, GitHub Copilot, Cursor or your own scripts.

```powershell
pbidriver launch "C:\reports\Sales.pbix"
pbidriver shot --page "Overview" --annotate     # PNG of the canvas, each visual labelled with its index
pbidriver read --page "Overview"                # chart points, card values, table/matrix cells, slicer state
pbidriver slicer --visual "Region" --select "West" --shot
pbidriver dax "EVALUATE TOPN(5, Sales)"
```

## Why

Agents can already write DAX and edit PBIP files, but they can't see the result. Screenshots of the whole desktop are noisy and need focus. Publishing to see a report breaks the fast loop. `pbidriver` closes that gap:

- **See:** pixel-exact PNGs of the canvas, one visual, every visual, the full UI, or the Table / Model / DAX query / TMDL views. It handles canvases bigger than the window, minimized windows, and windows behind other windows.
- **Read:** the values behind visuals, as Power BI formats them: chart data points, cards, whole tables and matrices (virtualized grids are scrolled through), and slicer options with their selection.
- **Never get stuck:** blocking dialogs of all three kinds Power BI uses (in-app, native Windows, and legacy Internet Explorer) are detected on every call, can be read and captured, and are answered with `dialog --click`. Input is refused while a modal is open. Broken visuals ("Can't display this visual") are reported.
- **Interact:** real mouse and keyboard input, so visuals react exactly as if you clicked: slicers, clicks, scrolling (including sideways in wide tables), typing, keys, tooltips, context and "More options" menus (sort, drill, show as table…), and bookmarks.
- **Understand:** every page, visual, field, filter and bookmark read from the report file, plus the model's tables, columns, measures (with DAX) and relationships.
- **Measure:** Performance Analyzer timings per visual (DAX query / visual display / other), optionally with each visual's DAX query.
- **Close the loop:** reload a PBIP after edits on disk, save, and close (answering the save prompt).

## Requirements

- Windows 10 or 11, with Power BI Desktop (Microsoft Store or installer build).
- Python 3.9+.
- Optional, for page captures and reloads on any open window: Microsoft's **Desktop Bridge**, in Power BI Desktop June 2026 or later. It's on by default (Options > Security > "Enable external tool access to Power BI Desktop through secure local APIs").

## Install

```powershell
pip install pbidriver
```

Or from npm, which runs the same tool and needs [uv](https://docs.astral.sh/uv/) or Python 3.9+:

```powershell
npx pbidriver status          # or: npm install -g pbidriver
```

The npm package also has a JavaScript API: `const { run } = require('pbidriver'); await run(['shot', '--page', 'Overview'])`.

The latest code from GitHub: `pip install git+https://github.com/speak2jerome/pbidriver`. From a checkout: `pip install .` (or `pip install -r requirements.txt` and run `python -m pbidriver`).

Playwright is used only to attach to Power BI's own WebView2, so `playwright install` is **not** needed.

## Two ways to connect

| | Started with `pbidriver launch` | Any open Power BI Desktop |
|---|---|---|
| How | DevTools on a private WebView2 profile, so it works next to your other Power BI windows | Microsoft's Desktop Bridge, the local model engine, and Windows itself |
| Page and visual screenshots | ✅ live state, any zoom, all views | ✅ report pages and visuals (positions from the saved file) |
| Table / Model / DAX / TMDL view screenshots | ✅ | ❌ |
| Read visual data, hover, menus, slicers, click, scroll, type | ✅ | ❌ |
| Dialogs | ✅ all kinds | ✅ native and legacy (in-app ones need `launch`) |
| `inventory`, `dax`, `model`, `reload`, `close`, `status` | ✅ | ✅ |

Use `pbidriver instances` to list every running Power BI with its pid, file, DevTools port and Bridge status. Pick one with `--pid`.

## Commands

Every command prints `{"ok": true, ...}` or `{"ok": false, "error": "..."}`. Commands that touch the UI also return `alerts` whenever something needs attention.

**Instances and state**

| Command | What it does |
|---|---|
| `launch FILE` | Opens a `.pbix`, `.pbip` or `.pbit` in its own Power BI with DevTools on `--port` (default 9333). Reports startup prompts, such as "Enable script visuals" or file recovery. |
| `instances` | Lists every running Power BI Desktop: pid, window, file, DevTools port, Bridge, model port, unsaved changes. |
| `status` | Current page, views, unsaved changes, alerts. |
| `pages` / `alerts [--all-views]` | Report pages; dialogs, banners and broken visuals right now. |

**Look**

| Command | What it does |
|---|---|
| `shot [--page P]` | Captures the report canvas. Add `--visual V` for one visual, `--all-visuals` for one PNG per visual, or `--full` for the whole UI. |
| `shot --view table\|model\|dax\|tmdl` | Captures another view without switching to it. |
| `shot --annotate` | Draws each visual's index and type on the capture, so you can say "visual 18". |
| `shot --scale 2` | Real 2× detail, re-rendered rather than upscaled. |
| `shot --bridge` | Captures through the Desktop Bridge. This happens automatically when the instance has no DevTools. |
| `visuals [--page P] [--all-pages]` | Live list of visuals: index, type, title, box, text, error. |

**Read**

| Command | What it does |
|---|---|
| `read [--page P] [--visual V] [--max-rows N]` | The data behind visuals: `points` (charts), `card`, `grid` (tables and matrices, scrolled through), `slicer`, `text`. |
| `inventory [--file F] [--summary] [--type T]` | Every page, visual, field, filter and bookmark from the report file, with no clicking (`.pbix`, `.pbit`, `.pbip`, PBIR or legacy layout). |
| `model [--part tables\|columns\|measures\|relationships]` | The semantic model, including measure DAX. |
| `dax "EVALUATE ..." [--file q.dax] [--max-rows N]` | Runs a DAX query against the open model. |
| `perf [--page P] [--queries]` | Performance Analyzer: per-visual total, DAX query, visual display and other time in ms, optionally with each visual's query. |

**Interact** (all accept `--page`, `--view`, `--shot`, `--force`)

| Command | What it does |
|---|---|
| `slicer --visual V --select A B \| --clear` | Sets exactly this selection, in list or dropdown slicers, including long virtualized lists. With no flag it lists the options. |
| `click [--visual V] [--text T \| --at X,Y] [--ctrl --shift --double --right]` | Clicks by text or accessible name, or at a point (fractions 0–1 or px) inside a visual. |
| `hover [--visual V] [--text T \| --at X,Y]` | Hovers a point and returns the tooltip rows. |
| `menu [--visual V] [--text T \| --at X,Y \| --more] [--choose "A > B"]` | Right-click or "More options" menu: lists the items, or chooses one (e.g. `--choose "Sort by > Total Sales"`). |
| `scroll [--visual V \| --view table] --dx N --dy N` | Mouse-wheel scrolling. In table visuals, every 120 px of `--dx` moves one column. |
| `type TEXT [--visual V] [--into T] [--press Enter]` / `key KEY...` | Typing (e.g. into a search slicer) and key presses (`Control+A`, `Escape`, `PageDown`). |
| `bookmarks [--apply NAME]` | Lists bookmarks, or applies one. |
| `wait --text T [--gone]` | Waits until text appears or disappears. |

**Dialogs, file and lifecycle**

| Command | What it does |
|---|---|
| `dialog` / `dialog --shot` / `dialog --click BUTTON` | Reads, captures or answers the blocking dialog. |
| `reload [--report-only]` | Reloads a PBIP/PBIR report (and model) from disk after an agent edited the files (Desktop Bridge). |
| `save` | Saves the report; the Desktop Bridge confirms there are no unsaved changes left. |
| `close [--discard \| --save]` | Closes a Power BI window and answers the "save your changes?" prompt. |

Common options: `--port` (default `9333`, env `PBIDRIVER_PORT`), `--pid`, `--settle` (max seconds to wait for rendering, default 20). Captures go to `./pbidriver_shots/` unless you pass `--out`.

## Agent instructions (paste into CLAUDE.md / AGENTS.md)

```
Power BI Desktop is driven with the `pbidriver` CLI; every call prints JSON.
- Start: `pbidriver status`; if nothing is running, `pbidriver launch "<report.pbix|.pbip>"`.
- Look: `pbidriver shot --page "<page>" --annotate`, then open the PNG at `file`. Visual indices in the
  picture work as `--visual <index>` everywhere.
- Numbers: `pbidriver read --page "<page>"` (all visuals) or `read --visual <index>`; `pbidriver dax "EVALUATE ..."`.
- Every result may contain "alerts". If alerts.blocked is true, read the dialog with `pbidriver dialog`
  and answer it with `pbidriver dialog --click "<button>"`. Fix alerts.visual_errors before moving on.
- Structure: `pbidriver inventory --summary`; measures and their DAX: `pbidriver model --part measures`.
- After editing PBIP files on disk: `pbidriver reload`, then `shot` again.
- Interact: `slicer --visual "<name>" --select "<value>" --shot`, `scroll --visual <index> --dx 1200`,
  `hover --visual <index> --text "<value>"`, `menu --visual <index> --more --choose "Sort by > <field>"`.
- Performance: `pbidriver perf --page "<page>"`.
- When done: `pbidriver save` if the changes should be kept, then `pbidriver close --discard`.
```

## How it works

- **DevTools.** Power BI Desktop draws its UI in WebView2 (Chromium) pages, one per view. `launch` sets `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` and a private `WEBVIEW2_USER_DATA_FOLDER`. The private folder gives the instance its own browser process, so the flag applies even while other Power BI windows are open. `pbidriver` attaches with Playwright's `connect_over_cdp`.
- **Pixel-exact captures.** Only the target's rectangle is captured (`Page.captureScreenshot` with a clip), so panes and scrollbars never leak in. If the canvas doesn't fit the window, the viewport is emulated larger for the capture and then restored. Power BI resets script-driven scrolling, so scrolling isn't an option. WebView2 stops painting while minimized, so the window is restored without focus and put back exactly as it was. Captures wait for the canvas to stop changing.
- **Data.** Built-in visuals bind each data point to its element (`__data__`) with `tooltipInfo`: the field names and values exactly as Power BI formats them. Tables and matrices are read cell by cell through their ARIA grid roles. They are virtualized, so `read` scrolls them one axis at a time; Power BI moves one column per horizontal wheel event.
- **Dialogs.** Power BI uses three technologies. In-app dialogs are read from the DOM. Native WinForms dialogs are read from their child windows and clicked with `BM_CLICK`. Legacy Internet Explorer dialogs (the "Do you want to save your changes?" prompt, "Enable script visuals", "Create table") are read and clicked through the dialog's own HTML via `WM_HTML_GETOBJECT`. While a modal is open, the main window is disabled; every command reports this as `alerts.blocked`, and input commands refuse to run, because input sent through DevTools would go around the modal.
- **Desktop Bridge.** Microsoft's local JSON-RPC API on the named pipe `pbi-desktop-bridge-<pid>`, used for page and region snapshots, reload and unsaved state.
- **DAX.** Windows PowerShell loads the ADOMD.NET client that ships inside Power BI Desktop and queries the local model engine (`msmdsrv`). Nothing extra is installed.

## Security and privacy

- `launch` opens a DevTools port on `127.0.0.1`. While that instance runs, any program on your machine could drive it, including your signed-in Power BI session. Close it when you're done (`pbidriver close`).
- Everything stays on your machine. Screenshots and data are written to local files; what your agent does with them is up to the agent.
- `perf --queries` reads queries through the clipboard. It restores your clipboard text afterwards, but non-text clipboard content is lost.

## Limits

- The DOM selectors are Power BI internals. They're tested on Power BI Desktop 2.152 (March 2026) and 2.159 (November 2026), both Store builds. A monthly update can rename them; they're grouped at the top of `pbidriver/cli.py`.
- Ribbon features (`perf`, `bookmarks`) look for English labels.
- Custom visuals render in sandboxed iframes. They can be captured and clicked (`--at`), but their data can't be read; use `dax` with the fields from `inventory`.
- `read` on large tables returns the rows Power BI has loaded (it loads them in windows of about 500). Use `dax` for every row.
- Slicer commands rescan the list after each click: about 10 s on a 28-option list.
- Bridge captures locate visuals from the saved file, so unsaved layout changes may be off. `reload` works for PBIP/PBIR projects only; reloading the model needs a recent model compatibility level.
- `error_text` for broken visuals matches known error phrases, so it's a heuristic.

## Related projects

- [Microsoft Power BI Desktop Bridge](https://learn.microsoft.com/en-us/power-bi/developer/agentic/power-bi-desktop-bridge-overview) and its `powerbi-desktop` CLI: Microsoft's official local API (status, open, reload, page snapshots). `pbidriver` uses it where it's available.
- [Power BI Modeling MCP server](https://github.com/microsoft/powerbi-modeling-mcp): Microsoft's MCP server for semantic model changes.
- [pbi-webview2](https://glama.ai/mcp/servers/bibiibjorn/pbi-webview2): an earlier MCP server that drives Power BI Desktop over the same WebView2 DevTools route.
- [sulaiman013/powerbi-mcp](https://github.com/sulaiman013/powerbi-mcp): an MCP server with model tools and Desktop Bridge screenshots.
- [PBI Inspector](https://github.com/NatVanG/PBI-Inspector): rule-based testing of report definitions.

## Development

```powershell
pip install -e .[test]
pytest
```

The tests use synthetic report files and need no Power BI. For live checks, `launch` a copy of a report and run the commands above.

The npm package in `npm/` is a thin Node wrapper that runs the same Python CLI; test it with `npm test` inside `npm/`.

**Releasing:**
1. Raise the version in `pbidriver/__init__.py` and `npm/package.json`; a test checks they match.
2. Add a `CHANGELOG.md` entry.
3. Tag `vX.Y.Z` and publish a GitHub release. The Publish workflow uploads to PyPI and npm through trusted publishing.

## Author

Jerome Eliezer ([speak2jerome](https://github.com/speak2jerome))

## License

MIT, see [LICENSE](LICENSE).
