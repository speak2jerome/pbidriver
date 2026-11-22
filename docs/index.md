# pbidriver: WebDriver for Power BI Desktop

**Let AI agents see and drive Power BI Desktop.** pbidriver is an open-source command-line tool that gives Claude Code, GitHub Copilot, Codex, Cursor, or any agent that can run a shell command, eyes and hands inside Power BI Desktop. It covers:

- pixel-exact screenshots of report pages, single visuals and every view
- the data behind visuals
- blocking dialogs
- slicers, tooltips, menus and bookmarks
- DAX queries
- Performance Analyzer timings

Everything runs locally against Power BI Desktop. There are no screen grabs and nothing is published to the Power BI service.

```powershell
pip install pbidriver
```

Or with Node.js: `npx pbidriver ...` or `npm install -g pbidriver`. This runs the same tool and needs [uv](https://docs.astral.sh/uv/) or Python 3.9+.

```powershell
pbidriver launch "C:\reports\Sales.pbix"
pbidriver shot --page "Overview" --annotate     # PNG of the canvas, each visual labelled with its index
pbidriver read --page "Overview"                # chart points, card values, table and matrix cells, slicer state
pbidriver slicer --visual "Region" --select "West" --shot
pbidriver dax "EVALUATE TOPN(5, Sales)"
```

Every command prints one JSON object (`{"ok": true, ...}` or `{"ok": false, "error": "..."}`), so an agent can read the result and decide what to do next.

!!! note "Not a data connector"
    "Driver" as in WebDriver, the thing that drives an app for automation. pbidriver is not an ODBC driver or a Power BI connector.

## Why pbidriver

AI agents can already write DAX and edit PBIP report files, but they can't see the result. A screenshot of the whole desktop is noisy and needs the window in front. Publishing the report to look at it breaks the fast edit-and-check loop. pbidriver closes that gap.

| | What pbidriver gives your agent |
|---|---|
| **See** | Pixel-exact PNGs of the canvas, one visual, every visual, the full UI, or the Table, Model, DAX query and TMDL views. Works when the canvas is bigger than the window, and when the window is minimized or behind other windows. |
| **Read** | The values behind visuals, exactly as Power BI formats them: chart data points, cards, whole tables and matrices, and slicer options with their selection. |
| **Never get stuck** | Blocking dialogs of all three kinds Power BI uses (in-app, native Windows and legacy Internet Explorer) are reported on every call and answered with `dialog --click`. Input is refused while a modal is open. Broken visuals are reported too. |
| **Interact** | Real mouse and keyboard input: slicers, clicks, scrolling (including sideways in wide tables), typing, keys, tooltips, context and "More options" menus, and bookmarks. |
| **Understand** | Every page, visual, field, filter and bookmark from the report file, and the model's tables, columns, measures (with DAX) and relationships. |
| **Measure** | Performance Analyzer timings per visual (DAX query, visual display, other), optionally with each visual's query. |
| **Close the loop** | Reload a PBIP after edits on disk, save, and close, answering the save prompt. |

## Works with any open Power BI Desktop

| | Started with `pbidriver launch` | Any open Power BI Desktop |
|---|---|---|
| How | WebView2 DevTools on a private profile, so it works next to your other Power BI windows | Microsoft's Desktop Bridge, the local model engine, and Windows itself |
| Page and visual screenshots | ✅ live state, all views | ✅ report pages and visuals |
| Table / Model / DAX / TMDL view screenshots | ✅ | ❌ |
| Read visual data, hover, menus, slicers, click, scroll, type | ✅ | ❌ |
| Dialogs | ✅ all kinds | ✅ native and legacy |
| `inventory`, `dax`, `model`, `reload`, `close`, `status` | ✅ | ✅ |

## Requirements

- Windows 10 or 11 with Power BI Desktop (Microsoft Store or installer build).
- Python 3.9 or later.
- Optional: Microsoft's Desktop Bridge (Power BI Desktop June 2026 or later, on by default) for captures and reloads on windows you opened yourself.

## Next steps

- [Use pbidriver with AI agents](agents.md): set up Claude Code, GitHub Copilot, Codex or Cursor, with ready-made recipes.
- [Command reference](commands.md): every command and option.
- [How it works](how-it-works.md): DevTools, the Desktop Bridge, dialogs, data reading, security and limits.
- [FAQ](faq.md)
- Source on [GitHub](https://github.com/speak2jerome/pbidriver), package on [PyPI](https://pypi.org/project/pbidriver/).
