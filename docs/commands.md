# Command reference

Run `pbidriver <command> --help` for every option. Every command prints one JSON object: `{"ok": true, ...}` on success, `{"ok": false, "error": "..."}` on failure. Commands that touch the UI also return `alerts` whenever something needs attention: a blocking dialog, an in-app message banner, or a visual that failed to render.

## Instances and state

| Command | What it does |
|---|---|
| `launch FILE` | Opens a `.pbix`, `.pbip` or `.pbit` in its own Power BI Desktop with DevTools on `--port` (default 9333). Reports startup prompts such as "Enable script visuals" or file recovery. |
| `instances` | Lists every running Power BI Desktop: pid, window, file, DevTools port, Desktop Bridge, model port, unsaved changes. |
| `status` | Current page, available views, unsaved changes and alerts. |
| `pages` | The report's pages, with the selected and hidden ones marked. |
| `alerts [--all-views]` | Dialogs, banners and broken visuals right now. |

## Look

| Command | What it does |
|---|---|
| `shot [--page P]` | Captures the report canvas as a PNG. |
| `shot --visual V` | One visual, by index from `visuals` or by matching its title, type or text. |
| `shot --all-visuals` | One PNG per visible visual. |
| `shot --full` | The whole Power BI window contents (ribbon, panes and canvas). |
| `shot --view table\|model\|dax\|tmdl` | The Table, Model, DAX query or TMDL view, captured without switching to it. |
| `shot --annotate` | Draws each visual's index and type on the capture, so you can refer to "visual 18". |
| `shot --clean` | For judging the design: no labels, selection outline, hover header, tooltip or open menu. Returns the legend (each visual's box in page units) and a layout check: `overlap`, `near_alignment` (edges 1 to 6 units apart), `uneven_gap`, `off_page`, and the usual gap. |
| `shot --overlay ITEM ...` | Draws chosen items: `index`, `type`, `title`, `size` and `pos` (page units, as `add-visual` uses), `errors`, `perf` (render ms from Performance Analyzer, coloured against `--threshold`, default 500), `grid` (every `--grid-size` units, default 40), `align` (near-miss edges), `gaps` (spacing between neighbours), `overlap`, or `all` (everything but `perf`). Canvas captures only. |
| `shot --scale 2` | Real 2× detail, re-rendered rather than upscaled. |
| `shot --bridge` | Captures through Microsoft's Desktop Bridge. This happens automatically for a Power BI window that has no DevTools. |
| `visuals [--page P] [--all-pages]` | Live list of visuals: index, type, title, position and size, text, and any error. |

## Read data

| Command | What it does |
|---|---|
| `read [--page P]` | The data behind every visual on the page. |
| `read --visual V [--max-rows N]` | One visual in full. The result's `kind` is `points` (charts), `card`, `grid` (tables and matrices, scrolled through), `slicer` or `text`. |
| `inventory [--file F] [--summary] [--type T]` | Every page, visual, field, filter and bookmark from the report file, with no clicking. Reads `.pbix`, `.pbit` and `.pbip`, in PBIR or legacy layout. |
| `model [--part tables\|columns\|measures\|relationships]` | The semantic model, including each measure's DAX. |
| `dax "EVALUATE ..." [--file q.dax] [--max-rows N]` | Runs a DAX query against the open model and returns columns and rows. |
| `dax ... --runs N [--cold]` | Times the query N times (min, median, max ms). `--cold` clears the model engine's cache before each run. |
| `perf [--page P] [--queries]` | Performance Analyzer: per-visual total, DAX query, visual display and other time in ms, each visual's `bottleneck`, `slow` flag and tuning `hints`, optionally each visual's DAX query. |
| `perf --runs N --cold --threshold MS --top N` | Medians over N refreshes; clear the cache before each one; what counts as slow (default 500 ms); only the slowest. |
| `perf --all-pages` | Every visible page, slowest first, with its slowest visuals. |

## Interact

These accept `--page`, `--view`, `--shot` (capture the result) and `--force` (act even while a dialog is open).

| Command | What it does |
|---|---|
| `slicer --visual V --select A B ...` | Sets exactly this selection in a list or dropdown slicer, including long virtualized lists. |
| `slicer --visual V --clear` | Clears the slicer. With no flag, `slicer` lists the options and what is selected. |
| `click [--visual V] [--text T \| --at X,Y]` | Clicks an element by its text or accessible name, or at a point (fractions 0–1 or pixels) inside a visual. Add `--ctrl`, `--shift`, `--double` or `--right`. |
| `hover [--visual V] [--text T \| --at X,Y]` | Hovers a point and returns the tooltip's rows. |
| `menu [--visual V] [--text T \| --at X,Y]` | Opens the right-click menu and lists its items. |
| `menu --visual V --more` | Opens the visual's "More options" menu (sort, export data, show as a table, spotlight...). |
| `menu ... --choose "A > B"` | Clicks a menu item, with `>` for submenus, e.g. `--choose "Sort by > Total Sales"`. |
| `scroll [--visual V \| --view table] --dx N --dy N` | Mouse-wheel scrolling. In table visuals, every 120 px of `--dx` moves one column. |
| `type TEXT [--visual V] [--into T] [--press Enter]` | Types text, for example into a search slicer. |
| `key KEY ...` | Presses keys such as `Escape`, `Control+A` or `PageDown`. |
| `bookmarks [--apply NAME]` | Lists the report's bookmarks, or applies one. |
| `wait --text T [--gone]` | Waits until text appears on the page, or disappears with `--gone`. |

## Build reports (PBIP projects)

These write PBIR files in the PBIP project open in Power BI (or `--project <file.pbip>`). Add `--reload` to show the change in Power BI right away, or `--shot` to reload and capture the page with visual indices drawn on it (`--out` for the file, `--clean` for an unlabelled capture with a layout check). Both reload the report only, so unsaved model changes stay. While the project isn't in git, results include a `caution` note. Model changes (tables, measures, relationships) go through Microsoft's [Power BI Modeling MCP](kit.md).

| Command | What it does |
|---|---|
| `new FOLDER --name NAME [--open] [--git]` | Creates a blank PBIP project: report with one page, empty model. `--open` launches it and returns the model's port; `--git` runs `git init` and a first commit. |
| `layout [--page P]` | Pages and visuals as stored in the files: ids, types, positions, fields. |
| `add-page NAME [--width W --height H]` | Adds a page. |
| `add-visual TYPE --field F ... [--page P] [--x --y --width --height] [--title T] [--sort F [--sort-dir asc]]` | Adds a visual: `card`, `cardVisual`, `clusteredColumnChart`, `columnChart`, `clusteredBarChart`, `barChart`, `lineChart`, `areaChart`, `pieChart`, `donutChart`, `tableEx` (table), `pivotTable` (matrix), `slicer` (`--mode list\|dropdown`), `textbox` (`--text`). Fields: `Table[Column]`, `[Measure]`, `Sum(Table[Column])`, optionally with a role: `Category=Sales[Region]`. Names are checked against the live model. |
| `remove-visual ID [--page P]` | Deletes a visual (ids from `layout`). |
| `save --as FILE.pbip` | Saves the open report as a PBIP project (or another `.pbix`/`.pbit`) and switches to it. `--overwrite` replaces an existing file. |
| `refresh [--sync]` | Home > Refresh, waiting until it finishes; returns the error text when a source fails. `--sync` first saves and reloads the project so tables created through the Modeling MCP are included, and saves after. |

## Dialogs, files and lifecycle

| Command | What it does |
|---|---|
| `dialog` | Reads the dialog that is blocking Power BI: title, text and buttons. |
| `dialog --shot` | Captures it as a PNG. |
| `dialog --click BUTTON` | Answers it. |
| `reload [--report-only]` | Reloads a PBIP/PBIR report, and its model, from disk after an agent edited the files. Uses the Desktop Bridge. `--report-only` keeps model changes that aren't saved yet. |
| `save` | Saves the report; the Desktop Bridge confirms that no unsaved changes are left. |
| `close [--discard \| --save]` | Closes a Power BI window and answers the "Do you want to save your changes?" prompt. |

## Agent setup

| Command | What it does |
|---|---|
| `mcp [--no-images] [--cwd DIR]` | Runs pbidriver as an MCP server over stdio. Every command above is a tool named `pbi_<command>`; screenshots are returned as images. Also offers a `pbi_guide` tool, guide resources and two prompts (`build-report`, `review-report`). |
| `setup [FOLDER] [--client claude\|vscode\|cursor\|codex\|all] [--runner ...] [--modeling ...] [--dry-run]` | Writes MCP configs (pbidriver and the Power BI Modeling MCP), an `AGENTS.md` section and the powerbi-builder skill into a project, without overwriting what's there. |
| `doctor [--project FOLDER]` | Checks Power BI Desktop, running instances, the Desktop Bridge, the Modeling MCP, uv/Node and the project's agent setup. |
| `guide [workflow\|visuals\|design\|performance\|modeling-mcp\|pbir\|troubleshooting]` | Prints a topic of the powerbi-builder guide (the MCP tool `pbi_guide`). |
| `locate` | Where pbidriver and the Power BI Modeling MCP are installed (package, VS Code extension folder and exe, npx package), how MCP clients start them, links, and install commands. |
| `bug-report [--command C] [--error E] [--expected X] [--details D] [--title T] [--out FILE]` | Drafts a GitHub issue: versions, the failing call and the error, with home folder, user name, report names and other paths redacted. Returns the draft, a link that opens the pre-filled bug form, a `gh issue create` command when GitHub CLI is installed, and a search for existing issues. Nothing is sent. |

## Common options

| Option | Meaning |
|---|---|
| `--port N` | DevTools port of a `launch`ed instance (default 9333, or the `PBIDRIVER_PORT` environment variable). |
| `--pid N` | A Power BI process from `instances`, for windows you opened yourself. |
| `--settle S` | Maximum seconds to wait for rendering to finish (default 20, or the `PBIDRIVER_SETTLE` environment variable). Lower it for faster commands on light pages. |
| `--out PATH` | Where to write a capture. The default is `./pbidriver_shots/`. |
