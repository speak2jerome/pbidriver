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
| `perf [--page P] [--queries]` | Performance Analyzer: per-visual total, DAX query, visual display and other time in ms, optionally with each visual's DAX query. |

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

## Dialogs, files and lifecycle

| Command | What it does |
|---|---|
| `dialog` | Reads the dialog that is blocking Power BI: title, text and buttons. |
| `dialog --shot` | Captures it as a PNG. |
| `dialog --click BUTTON` | Answers it. |
| `reload [--report-only]` | Reloads a PBIP/PBIR report, and its model, from disk after an agent edited the files. Uses the Desktop Bridge. |
| `save` | Saves the report; the Desktop Bridge confirms that no unsaved changes are left. |
| `close [--discard \| --save]` | Closes a Power BI window and answers the "Do you want to save your changes?" prompt. |

## Common options

| Option | Meaning |
|---|---|
| `--port N` | DevTools port of a `launch`ed instance (default 9333, or the `PBIDRIVER_PORT` environment variable). |
| `--pid N` | A Power BI process from `instances`, for windows you opened yourself. |
| `--settle S` | Maximum seconds to wait for rendering to finish (default 20). |
| `--out PATH` | Where to write a capture. The default is `./pbidriver_shots/`. |
