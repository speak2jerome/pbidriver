# How it works

pbidriver combines three local routes into Power BI Desktop. It picks whichever one each command needs.

## WebView2 DevTools

Power BI Desktop draws its interface in WebView2 (Chromium) pages, one per view: Report, Table, Model, DAX query and TMDL. `pbidriver launch` starts Power BI Desktop with two environment variables:

- `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` turns on the Chrome DevTools Protocol.
- `WEBVIEW2_USER_DATA_FOLDER` points at a private profile. That gives the instance its own browser process, so the debugging flag applies even while other Power BI windows are open.

pbidriver then attaches with Playwright's `connect_over_cdp`. It doesn't download a browser; it only uses the one inside Power BI Desktop.

### Pixel-exact captures

Only the target's rectangle is captured, with `Page.captureScreenshot` and a clip, so panes, scrollbars and the ribbon never leak into a visual's image.

- **Canvas bigger than the window:** the viewport is emulated larger for the capture, then restored. Power BI resets script-driven scrolling, so scrolling the canvas isn't an option.
- **Minimized window:** WebView2 stops painting while minimized, so pbidriver restores the window without focusing it, then puts it back exactly as it was. A window behind other windows captures fine.
- **Finished rendering:** captures wait until the canvas has stopped changing.

### Reading visual data

- **Charts and cards:** built-in visuals bind each data point to its element with `tooltipInfo`, the field names and values exactly as Power BI formats them. `read` collects those, so there's no need to hover every point. Series of the same category are merged into one row.
- **Tables and matrices:** read cell by cell through their ARIA grid roles. They're virtualized, so `read` scrolls them one axis at a time. Power BI moves one column per horizontal wheel event, whatever its size.
- **Custom visuals:** they run in sandboxed iframes, so their data isn't readable. Query their fields with `dax` instead.

### Input

Clicks, typing, scrolling and keys are real input events sent through DevTools, so visuals react exactly as if a person used them. Ctrl+S is handled by the host window and never reaches the page, so `save` clicks Power BI's own Save button instead.

## Dialogs

Power BI Desktop uses three dialog technologies. pbidriver handles all of them.

| Kind | Examples | How pbidriver reads and answers it |
|---|---|---|
| In-app (WebView2) | First-run tips, DAX and TMDL dialogs, message banners | From the page DOM; clicked like any element |
| Native Windows (WinForms) | Prompts and warnings | From the dialog's child windows; buttons pressed with `BM_CLICK` |
| Legacy Internet Explorer | "Do you want to save your changes?", "Enable script visuals", "Create table" | Through the dialog's own HTML document, via `WM_HTML_GETOBJECT` |

While a modal dialog is open, Power BI's main window is disabled. Every command reports this as `alerts.blocked`, and input commands refuse to run, because input sent through DevTools would go around the modal. `dialog --shot` captures native and legacy dialogs with `PrintWindow`, because they're outside WebView2.

## Microsoft's Desktop Bridge

Power BI Desktop June 2026 and later include the Desktop Bridge: a local JSON-RPC API on the named pipe `pbi-desktop-bridge-<pid>`. pbidriver uses it for:

- page and region snapshots of any open window, including windows not started by `launch`
- `reload` of PBIP/PBIR projects after edits on disk
- unsaved-changes state, used by `status` and to confirm `save`

The Bridge is on by default: Options > Security > "Enable external tool access to Power BI Desktop through secure local APIs".

## DAX and the model

Power BI Desktop runs a local Analysis Services engine (`msmdsrv`) on a random port. `dax` and `model` find that port, then let Windows PowerShell load the ADOMD.NET client that ships inside Power BI Desktop. Nothing extra is installed. `model` uses the `INFO.VIEW` DAX functions to list tables, columns, measures and relationships.

## Security and privacy

- `launch` opens a DevTools port on `127.0.0.1`. While that instance runs, any program on your machine could drive it, including your signed-in Power BI session. Close it when you're done with `pbidriver close`.
- Everything stays on your machine. Screenshots and data are written to local files; what your agent does with them is up to the agent.
- `perf --queries` reads queries through the clipboard. It restores your clipboard text afterwards, but non-text clipboard content is lost.

## Limits

- The DOM selectors are Power BI internals. They're tested on Power BI Desktop 2.152 (March 2026) and 2.159 (November 2026), both Microsoft Store builds. A monthly update can rename them.
- Ribbon features (`perf`, `bookmarks`) look for English labels.
- `read` on large tables returns the rows Power BI has loaded, which it loads in windows of about 500. Use `dax` for every row.
- Slicer commands rescan the list after each click: about 10 s on a 28-option list.
- Bridge captures locate visuals from the saved file, so unsaved layout changes may be off. `reload` works for PBIP/PBIR projects only, and reloading the model needs a recent model compatibility level.
- Spotting broken visuals relies on matching Power BI's error messages, so it's a heuristic.
