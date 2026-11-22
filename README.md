# pbidriver

[![PyPI](https://img.shields.io/pypi/v/pbidriver?label=pypi&cacheSeconds=1800)](https://pypi.org/project/pbidriver/)
[![npm](https://img.shields.io/npm/v/pbidriver?label=npm&cacheSeconds=1800)](https://www.npmjs.com/package/pbidriver)
[![Python](https://img.shields.io/pypi/pyversions/pbidriver?cacheSeconds=1800)](https://pypi.org/project/pbidriver/)
[![Tests](https://github.com/speak2jerome/pbidriver/actions/workflows/tests.yml/badge.svg)](https://github.com/speak2jerome/pbidriver/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/speak2jerome/pbidriver/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-speak2jerome.github.io%2Fpbidriver-indigo)](https://speak2jerome.github.io/pbidriver/)
[![Zynxtech open source](https://img.shields.io/badge/Zynxtech-open%20source-0a7)](https://zynxtech.in/projects/pbidriver/)

*Part of [Zynxtech](https://zynxtech.in) open source. Project page: [zynxtech.in/projects/pbidriver](https://zynxtech.in/projects/pbidriver/).*

**WebDriver for Power BI Desktop.** Let AI agents build, see and drive Power BI Desktop reports: create PBIP projects, pages and visuals; screenshots of pages, visuals and every view; the data behind visuals; blocking dialogs; slicers, tooltips, menus, bookmarks; refresh, DAX and Performance Analyzer. It all runs locally against Power BI Desktop, with no screen grabs and no publishing to the service.

Together with Microsoft's [Power BI Modeling MCP](https://github.com/microsoft/powerbi-modeling-mcp), which edits the semantic model, it's a complete kit for agents to build Power BI reports end to end and check their own work. One command sets both up for Claude Code, VS Code (GitHub Copilot), Cursor and Codex:

```powershell
pip install pbidriver
pbidriver setup            # MCP configs for pbidriver + the Power BI Modeling MCP, AGENTS.md, the powerbi-builder skill
```

(Not a data connector or ODBC driver: "driver" as in WebDriver, the thing that drives an app for automation.)

> **⚠️ Caution: pbidriver is a new tool** (first released November 2026). It edits Power BI project files, saves through Power BI and drives its UI, and like any new software it can have bugs that damage a report. **Work on a copy of your report, or keep it in git and commit before letting an agent change it**, so you can always go back. `pbidriver new --git` starts new projects under git, and commands that change files add a `caution` note while a project isn't under version control. Found a bug? See [Reporting bugs](#reporting-bugs).

**Documentation:** [speak2jerome.github.io/pbidriver](https://speak2jerome.github.io/pbidriver/), with [building reports with agents](https://speak2jerome.github.io/pbidriver/kit/), [setup for Claude Code, Copilot, Codex and Cursor](https://speak2jerome.github.io/pbidriver/agents/) and a [FAQ](https://speak2jerome.github.io/pbidriver/faq/).

pbidriver is an MCP server (`pbidriver mcp`, every command a `pbi_*` tool, screenshots returned as images) and a CLI where every command prints one JSON object, so any agent that can run a shell command can use it too.

```powershell
pbidriver launch "C:\reports\Sales.pbix"
pbidriver shot --page "Overview" --annotate     # PNG of the canvas, each visual labelled with its index
pbidriver read --page "Overview"                # chart points, card values, table/matrix cells, slicer state
pbidriver slicer --visual "Region" --select "West" --shot
pbidriver dax "EVALUATE TOPN(5, Sales)"
```

## Build a report with an agent

After `pbidriver setup`, ask your agent something like "Build a sales report from data\sales.csv: revenue by region and month, top products, a region slicer." It follows the powerbi-builder skill:

1. `pbi_new` creates a PBIP project and opens it in Power BI Desktop.
2. The Power BI Modeling MCP connects to it and creates tables (CSV, Excel, SQL or DAX), relationships and measures.
3. `pbi_refresh sync=true` loads the data.
4. `pbi_add_visual` adds each visual, with field names checked against the live model; `shot=true` returns a screenshot.
5. `pbi_shot`, `pbi_read` and `pbi_dax` verify that every visual shows the right numbers; `pbi_save` saves.

Claude Code users can install the same kit as a plugin: `/plugin marketplace add speak2jerome/pbidriver`, then `/plugin install pbidriver@pbidriver`. `scripts/e2e_kit.py` runs this whole flow through both MCP servers against a real Power BI Desktop and checks 42 things along the way, from model to saved-and-reopened report.

## Why

Agents can already write DAX and edit PBIP files, but they can't see the result. Screenshots of the whole desktop are noisy and need focus. Publishing to see a report breaks the fast loop. `pbidriver` closes that gap:

- **See:** pixel-exact PNGs of the canvas, one visual, every visual, the full UI, or the Table / Model / DAX query / TMDL views. It handles canvases bigger than the window, minimized windows, and windows behind other windows.
- **Read:** the values behind visuals, as Power BI formats them: chart data points, cards, whole tables and matrices (virtualized grids are scrolled through), and slicer options with their selection.
- **Never get stuck:** blocking dialogs of every kind Power BI uses (in-app, floating WebView2, native Windows, and legacy Internet Explorer) are detected on every call, can be read and captured, and are answered with `dialog --click`. Input is refused while a modal is open. Broken visuals ("Can't display this visual") are reported.
- **Interact:** real mouse and keyboard input, so visuals react exactly as if you clicked: slicers, clicks, scrolling (including sideways in wide tables), typing, keys, tooltips, context and "More options" menus (sort, drill, show as table…), and bookmarks.
- **Understand:** every page, visual, field, filter and bookmark read from the report file, plus the model's tables, columns, measures (with DAX) and relationships.
- **Review the design:** clean captures for judging how a page looks, and overlays with each visual's size and position (in page units), a grid, spacing, edges that almost line up, overlaps and render times, plus a layout check that lists those issues.
- **Tune performance:** Performance Analyzer timings per visual (DAX query / visual display / other), repeated runs with a cold cache, the bottleneck of each slow visual and what to do about it, every page ranked, and cold DAX query timings.
- **Build:** create PBIP projects, pages and visuals (14 types, fields checked against the live model), convert a `.pbix` into a PBIP project, refresh data and get the failing source's error.
- **Close the loop:** reload a PBIP after edits on disk, save, and close (answering the save prompt).

## Requirements

- Windows 10 or 11, with Power BI Desktop (Microsoft Store or installer build).
- Python 3.9 to 3.14 (each tested on Windows in CI).
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
| `shot --clean` | For judging the design: no labels, selection outline, hover header, tooltip or open menu. Still returns the legend (each visual's box in page units) and a layout check: overlaps, edges that almost line up, uneven gaps, visuals off the page. |
| `shot --overlay ITEM...` | Draws `index`, `type`, `title`, `size`, `pos` (page units), `errors`, `perf` (render ms, coloured against `--threshold`), `grid` (`--grid-size`), `align`, `gaps`, `overlap`, or `all` (everything but perf). |
| `shot --scale 2` | Real 2× detail, re-rendered rather than upscaled. |
| `shot --bridge` | Captures through the Desktop Bridge. This happens automatically when the instance has no DevTools. |
| `visuals [--page P] [--all-pages]` | Live list of visuals: index, type, title, box, text, error. |

**Read**

| Command | What it does |
|---|---|
| `read [--page P] [--visual V] [--max-rows N]` | The data behind visuals: `points` (charts), `card`, `grid` (tables and matrices, scrolled through), `slicer`, `text`. |
| `inventory [--file F] [--summary] [--type T]` | Every page, visual, field, filter and bookmark from the report file, with no clicking (`.pbix`, `.pbit`, `.pbip`, PBIR or legacy layout). |
| `model [--part tables\|columns\|measures\|relationships]` | The semantic model, including measure DAX. |
| `dax "EVALUATE ..." [--file q.dax] [--max-rows N] [--runs N] [--cold]` | Runs a DAX query against the open model. `--runs` times it N times (min/median/max); `--cold` clears the engine cache before each run. |
| `perf [--page P \| --all-pages] [--runs N] [--cold] [--threshold MS] [--top N] [--queries]` | Performance Analyzer: per-visual total, DAX query, visual display and other time in ms (medians over `--runs`), each visual's bottleneck, tuning hints, optionally each visual's query. `--cold` clears the cache before each refresh; `--all-pages` ranks every page. |

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

**Build reports** (PBIP projects; add `--reload` to show the change, `--shot` to also capture it)

| Command | What it does |
|---|---|
| `new FOLDER --name NAME [--open] [--git]` | Creates a blank PBIP project (one page, empty model); `--open` launches it, `--git` puts it under git with a first commit. |
| `layout [--page P]` | Pages and visuals in the PBIR files: ids, types, positions, fields. |
| `add-page NAME` | Adds a page. |
| `add-visual TYPE --field F ... [--x --y --width --height --title --page --sort F]` | Adds a card, chart (column, bar, line, area, pie, donut), table, matrix, slicer or textbox. Fields: `Table[Column]`, `[Measure]`, `Sum(Table[Column])`, optionally `Role=...`. |
| `remove-visual ID` | Deletes a visual. |
| `refresh [--sync]` | Refreshes data and waits; reports the failing source's error. `--sync` saves and reloads first so tables created through the Modeling MCP are included, then saves. |
| `save --as FILE.pbip` | Saves the open report as a PBIP project (or `.pbix`/`.pbit`). |

**Dialogs, file and lifecycle**

| Command | What it does |
|---|---|
| `dialog` / `dialog --shot` / `dialog --click BUTTON` | Reads, captures or answers the blocking dialog. |
| `reload [--report-only]` | Reloads a PBIP/PBIR report (and model) from disk after an agent edited the files (Desktop Bridge). `--report-only` keeps unsaved model changes. |
| `save` | Saves the report; the Desktop Bridge confirms there are no unsaved changes left. |
| `close [--discard \| --save]` | Closes a Power BI window and answers the "save your changes?" prompt. |

**Agent setup**

| Command | What it does |
|---|---|
| `mcp` | Runs the MCP server over stdio: every command as a `pbi_*` tool, plus `pbi_guide`. |
| `setup [FOLDER] [--client ...]` | Writes MCP configs (pbidriver + Power BI Modeling MCP), an `AGENTS.md` section and the powerbi-builder skill. |
| `doctor` | Checks Power BI Desktop, the Desktop Bridge, the Modeling MCP and the project setup. |
| `locate` | Where pbidriver and the Power BI Modeling MCP (VS Code extension, exe, npx package) are, how MCP clients start them, and install commands. |
| `guide [TOPIC]` | The powerbi-builder guide: workflow, visuals, design, performance, modeling-mcp, pbir, troubleshooting. |
| `bug-report [--command C] [--error E] [--expected X]` | Drafts a GitHub issue with versions, paths and names redacted, plus a pre-filled new-issue link. Nothing is sent. |

Common options: `--port` (default `9333`, env `PBIDRIVER_PORT`), `--pid`, `--settle` (max seconds to wait for rendering, default 20, env `PBIDRIVER_SETTLE`; lower it for faster commands on light pages). Captures go to `./pbidriver_shots/` unless you pass `--out`.

## Find pbidriver and the Power BI Modeling MCP

`pbidriver locate` prints where everything is on your machine. In short:

| | pbidriver | Power BI Modeling MCP (Microsoft) |
|---|---|---|
| Get it | `pip install pbidriver`, `uvx pbidriver@latest`, or `npx -y pbidriver@latest` | VS Code extension [`analysis-services.powerbi-modeling-mcp`](https://marketplace.visualstudio.com/items?itemName=analysis-services.powerbi-modeling-mcp): `code --install-extension analysis-services.powerbi-modeling-mcp`, or search "Power BI Modeling MCP" in VS Code's Extensions view. Without VS Code: `npx -y @microsoft/powerbi-modeling-mcp@latest --start` |
| On disk | `pip show pbidriver` | `%USERPROFILE%\.vscode\extensions\analysis-services.powerbi-modeling-mcp-<version>-win32-x64\server\powerbi-modeling-mcp.exe` |
| MCP server | `pbidriver mcp` | the exe (or npx) with `--start` |
| See it in your agent | VS Code: Command Palette > "MCP: List Servers"; Claude Code: `/mcp`; Cursor: Settings > MCP; Codex: `codex mcp list` | same; VS Code lists it as "Power BI Modeling MCP Server" |
| Source, issues | [speak2jerome/pbidriver](https://github.com/speak2jerome/pbidriver) | [microsoft/powerbi-modeling-mcp](https://github.com/microsoft/powerbi-modeling-mcp) |

## Reporting bugs

Please report bugs at [github.com/speak2jerome/pbidriver/issues](https://github.com/speak2jerome/pbidriver/issues). The easiest way:

```powershell
pbidriver bug-report --command "pbidriver read --visual 3" --error "<the error or the wrong result>" --expected "<what should happen>"
```

This drafts the issue with your pbidriver, Python, Windows and Power BI Desktop versions, and redacts your home folder, user name, report names and other paths. It writes the draft to a file and returns a link that opens GitHub's bug form pre-filled (and a `gh issue create` command if you use GitHub CLI). Nothing is sent until you open the link or run the command. Agents using pbidriver are told to do the same: draft with `pbi_bug_report`, show you, and file only with your OK. Problems with Microsoft's Modeling MCP go to [its repository](https://github.com/microsoft/powerbi-modeling-mcp/issues).

## Agent instructions (CLI only: paste into CLAUDE.md / AGENTS.md)

With MCP, `pbidriver setup` writes these for you. For agents that only run shell commands:

```
Power BI Desktop is driven with the `pbidriver` CLI; every call prints JSON.
- Start: `pbidriver status`; if nothing is running, `pbidriver launch "<report.pbix|.pbip>"`.
- Look: `pbidriver shot --page "<page>" --annotate`, then open the PNG at `file`. Visual indices in the
  picture work as `--visual <index>` everywhere.
- Numbers: `pbidriver read --page "<page>"` (all visuals) or `read --visual <index>`; `pbidriver dax "EVALUATE ..."`.
- Every result may contain "alerts". If alerts.blocked is true, read the dialog with `pbidriver dialog`
  and answer it with `pbidriver dialog --click "<button>"`. Fix alerts.visual_errors before moving on.
- Structure: `pbidriver inventory --summary`; measures and their DAX: `pbidriver model --part measures`.
- Build: `pbidriver new <folder> --name <Name> --open`; model through the Power BI Modeling MCP, then
  `pbidriver refresh --sync`; `pbidriver add-visual <type> --field "Category=T[Col]" --field "[Measure]" --shot`.
- After editing PBIP files on disk: `pbidriver reload --report-only`, then `shot` again.
- Interact: `slicer --visual "<name>" --select "<value>" --shot`, `scroll --visual <index> --dx 1200`,
  `hover --visual <index> --text "<value>"`, `menu --visual <index> --more --choose "Sort by > <field>"`.
- Design: `pbidriver shot --clean` (how it looks, plus layout issues); `--overlay size pos gaps align` to measure.
- Performance: `pbidriver perf --page "<page>" --runs 3 --cold` (bottlenecks and hints).
- When done: `pbidriver save` if the changes should be kept, then `pbidriver close --discard`.
- pbidriver is new: before changing a report, make sure it's in git with a fresh commit or work on a copy; ask
  the user if neither. If pbidriver misbehaves, `pbidriver bug-report --command "..." --error "..."`, show the
  draft to the user, and file it only with their OK.
```

## How it works

- **DevTools.** Power BI Desktop draws its UI in WebView2 (Chromium) pages, one per view. `launch` sets `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` and a private `WEBVIEW2_USER_DATA_FOLDER`. The private folder gives the instance its own browser process, so the flag applies even while other Power BI windows are open. `pbidriver` attaches with Playwright's `connect_over_cdp`.
- **Pixel-exact captures.** Only the target's rectangle is captured (`Page.captureScreenshot` with a clip), so panes and scrollbars never leak in. If the canvas doesn't fit the window, the viewport is emulated larger for the capture and then restored. Power BI resets script-driven scrolling, so scrolling isn't an option. WebView2 stops painting while minimized, so the window is restored without focus and put back exactly as it was. Captures wait for the canvas to stop changing.
- **Data.** Built-in visuals bind each data point to its element (`__data__`) with `tooltipInfo`: the field names and values exactly as Power BI formats them. Tables and matrices are read cell by cell through their ARIA grid roles. They are virtualized, so `read` scrolls them one axis at a time; Power BI moves one column per horizontal wheel event.
- **Dialogs.** Power BI uses four technologies. In-app dialogs are read from the DOM; floating ones (the refresh dialog) from their own WebView2 page while their window is visible. Native WinForms dialogs are read from their child windows and clicked with `BM_CLICK`. Legacy Internet Explorer dialogs (the "Do you want to save your changes?" prompt, "Enable script visuals", "Create table") are read and clicked through the dialog's own HTML via `WM_HTML_GETOBJECT`. While a modal is open, the main window is disabled; every command reports this as `alerts.blocked`, and input commands refuse to run, because input sent through DevTools would go around the modal.
- **Desktop Bridge.** Microsoft's local JSON-RPC API on the named pipe `pbi-desktop-bridge-<pid>`, used for page and region snapshots, reload and unsaved state.
- **DAX.** Windows PowerShell loads the ADOMD.NET client that ships inside Power BI Desktop and queries the local model engine (`msmdsrv`). Nothing extra is installed.
- **Authoring.** `new`, `add-page` and `add-visual` write PBIR JSON with the schema versions Power BI Desktop 2.159 uses, then reload the report through the Desktop Bridge. Fields are checked against the live model (including unsaved changes from the Modeling MCP), or the TMDL files when Power BI is closed.
- **Overlays and layout checks.** Visual boxes come from the canvas DOM and are converted to page units with the page size from the report file, so sizes and positions match what PBIR and `add-visual` use. The layout check compares edges and neighbour gaps within a small tolerance (6 units).
- **Performance.** `perf` drives Power BI's own Performance Analyzer pane; `--cold` sends an XMLA `ClearCache` to the local engine before each refresh, and `dax --cold` does the same between query runs.
- **MCP server.** `pbidriver mcp` generates its tools from the CLI's own argument definitions, runs each call as a CLI subprocess, and returns PNGs as image content. It's a small JSON-RPC implementation over stdio with no extra dependencies.

## Security and privacy

- pbidriver is new: work on copies of reports or keep them in git (see the caution at the top).
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
- `add-visual` covers 14 common visual types with their data roles, a title, position and size. Other visual types and formatting (colors, data labels, conditional formatting) mean editing the visual's PBIR JSON; the skill's `pbir` reference shows how.
- Authoring writes PBIR in the format Power BI Desktop 2.159 saves; Microsoft may change the schema versions in later releases.

## Related projects

- [Microsoft Power BI Desktop Bridge](https://learn.microsoft.com/en-us/power-bi/developer/agentic/power-bi-desktop-bridge-overview) and its `powerbi-desktop` CLI: Microsoft's official local API (status, open, reload, page snapshots). `pbidriver` uses it where it's available.
- [Power BI Modeling MCP server](https://github.com/microsoft/powerbi-modeling-mcp): Microsoft's MCP server for semantic model changes. pbidriver is built to work alongside it.
- [pbi-webview2](https://glama.ai/mcp/servers/bibiibjorn/pbi-webview2): an earlier MCP server that drives Power BI Desktop over the same WebView2 DevTools route.
- [sulaiman013/powerbi-mcp](https://github.com/sulaiman013/powerbi-mcp): an MCP server with model tools and Desktop Bridge screenshots.
- [PBI Inspector](https://github.com/NatVanG/PBI-Inspector): rule-based testing of report definitions.

## Development

```powershell
pip install -e .[test]
pytest
```

The tests use synthetic report files and need no Power BI. For live checks, `launch` a copy of a report and run the commands above, or run the full agent flow: `pip install mcp`, then `python scripts/e2e_kit.py --clean` (opens and closes one Power BI window on port 9444).

The npm package in `npm/` is a thin Node wrapper that runs the same Python CLI; test it with `npm test` inside `npm/`.

The powerbi-builder skill lives in `pbidriver/skill/` (packaged, used by `setup` and `pbi_guide`); `python scripts/sync_skill.py` copies it into the Claude Code plugin in `plugins/pbidriver/`, and a test checks the copies match.

The Tests workflow runs the offline suite on Windows with Python 3.9 to 3.14, and the npm tests, on every push and pull request.

**Releasing:**
1. Raise the version in `pbidriver/__init__.py`, `npm/package.json`, `plugins/pbidriver/.claude-plugin/plugin.json`, `CITATION.cff` and the version line in `llms.txt`; the publish workflow checks the first two match.
2. Add a `CHANGELOG.md` entry, and make sure the Tests workflow is green.
3. Tag `vX.Y.Z` and publish a GitHub release. The Publish workflow uploads to PyPI and npm through trusted publishing; no tokens or manual publishing.

## Author

Jerome Eliezer, [Zynxtech](https://zynxtech.in) ([jeromeeliezer@zynxtech.in](mailto:jeromeeliezer@zynxtech.in), GitHub [speak2jerome](https://github.com/speak2jerome)).

pbidriver is part of Zynxtech's open-source projects: [zynxtech.in/projects/pbidriver](https://zynxtech.in/projects/pbidriver/).

## License

MIT, see [LICENSE](https://github.com/speak2jerome/pbidriver/blob/main/LICENSE).
