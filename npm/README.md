# pbidriver

**WebDriver for Power BI Desktop.** Let AI agents see and drive Power BI Desktop: screenshots of pages, visuals and every view, the data behind visuals, blocking dialogs, slicers, tooltips, menus, bookmarks, DAX and Performance Analyzer. Everything runs locally; nothing is published to the Power BI service.

This npm package runs the [pbidriver](https://pypi.org/project/pbidriver/) command-line tool from Node, so it fits JavaScript projects and agents that prefer `npx`.

> **⚠️ pbidriver is a new tool.** It edits Power BI project files and drives Power BI Desktop. Work on a copy of your report, or keep it in git and commit before letting an agent change it. Report bugs with `npx pbidriver bug-report` or at [GitHub](https://github.com/speak2jerome/pbidriver/issues).

```powershell
npx pbidriver launch "C:\reports\Sales.pbix"
npx pbidriver shot --page "Overview" --annotate
npx pbidriver read --page "Overview"
npx pbidriver slicer --visual "Region" --select "West" --shot
npx pbidriver dax "EVALUATE TOPN(5, Sales)"
```

Every command prints one JSON object: `{"ok": true, ...}` or `{"ok": false, "error": "..."}`.

**MCP server:** `npx -y pbidriver mcp` runs pbidriver as an MCP server over stdio: every command is a `pbi_*` tool, and screenshots come back as images. In an MCP client config on Windows: `{"command": "cmd", "args": ["/c", "npx", "-y", "pbidriver@latest", "mcp"]}`. `npx pbidriver setup` configures it, together with Microsoft's Power BI Modeling MCP, for Claude Code, VS Code, Cursor and Codex; see [Build reports with agents](https://speak2jerome.github.io/pbidriver/kit/).

## Requirements

- Windows 10 or 11 with Power BI Desktop.
- Node.js 18 or later.
- Either [uv](https://docs.astral.sh/uv/) or Python 3.9+. pbidriver drives Power BI through Windows APIs that only Python reaches well, so this package starts the same Python CLI rather than reimplementing it.

## How the Python side is found

1. `PBIDRIVER_PYTHON` set to a Python interpreter: that interpreter runs `-m pbidriver`.
2. `uvx` on PATH: `uvx --from pbidriver==<this version> pbidriver ...`. No Python setup needed; uv downloads and caches it on first use.
3. Python 3.9+ on PATH: runs `-m pbidriver`. If the matching version isn't installed, it is installed once with pip (`--user`). Set `PBIDRIVER_NO_INSTALL=1` to never install.

Installer output goes to stderr, so stdout stays a single JSON object.

## JavaScript API

```js
const { run } = require('pbidriver');

const shot = await run(['shot', '--page', 'Overview', '--annotate']);
if (shot.ok) console.log('PNG at', shot.file);

const data = await run(['read', '--visual', '3']);
if (data.alerts?.blocked) {
  await run(['dialog', '--click', 'Cancel']);
}
```

`run(args, { cwd, env, timeout })` resolves with the command's JSON object (check `ok`). It rejects only when no JSON comes back, for example for `--help`. Types are included.

## Documentation

- [Project page](https://zynxtech.in/projects/pbidriver/) (Zynxtech)
- [Documentation site](https://speak2jerome.github.io/pbidriver/)
- [Use with AI agents](https://speak2jerome.github.io/pbidriver/agents/): Claude Code, GitHub Copilot, Codex and Cursor, with recipes
- [Command reference](https://speak2jerome.github.io/pbidriver/commands/)
- [FAQ](https://speak2jerome.github.io/pbidriver/faq/)
- Source: [github.com/speak2jerome/pbidriver](https://github.com/speak2jerome/pbidriver)

MIT licence. Author: Jerome Eliezer, [Zynxtech](https://zynxtech.in) ([jeromeeliezer@zynxtech.in](mailto:jeromeeliezer@zynxtech.in), GitHub [speak2jerome](https://github.com/speak2jerome)). pbidriver is part of Zynxtech open source: [project page](https://zynxtech.in/projects/pbidriver/).
