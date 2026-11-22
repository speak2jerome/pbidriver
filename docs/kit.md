# Build Power BI reports with AI agents

pbidriver and Microsoft's [Power BI Modeling MCP](https://github.com/microsoft/powerbi-modeling-mcp) together
let an AI agent build a Power BI report end to end, in Power BI Desktop, and check its own work:

| Job | Tool |
|---|---|
| Semantic model: tables (CSV, Excel, SQL, DAX), columns, measures, relationships | **Power BI Modeling MCP** (Microsoft) |
| Power BI Desktop and the report: create or open projects, pages, visuals, screenshots, the numbers each visual shows, slicers, clicks, dialogs, refresh, save | **pbidriver** (MCP server or CLI) |
| How to use both together | the **powerbi-builder** skill, the `pbi_guide` tool and the MCP server's instructions |

The Modeling MCP can't create report pages or visuals, and it can't see the report; pbidriver doesn't edit the
model. Each covers what the other can't.

## Set up in one command

In the folder where your agent works (your report project, or an empty folder):

```powershell
pip install pbidriver
```

```powershell
pbidriver setup
```

`setup` writes, without overwriting anything that's already there:

| File | For | Contents |
|---|---|---|
| `.mcp.json` | Claude Code | the `pbidriver` and `powerbi-modeling` MCP servers |
| `.vscode/mcp.json` | VS Code / GitHub Copilot | the `pbidriver` server (the Modeling MCP VS Code extension registers its own server; without the extension, setup adds it too) |
| `.cursor/mcp.json` | Cursor | both servers |
| `.codex/config.toml` | OpenAI Codex (with `--client codex` or `--client all`) | both servers |
| `AGENTS.md` | Codex, Copilot, Cursor and most agents | a short "how to build Power BI reports here" section between `<!-- pbidriver -->` markers |
| `CLAUDE.md` | Claude Code | `@AGENTS.md`, which imports that section |
| `.claude/skills/powerbi-builder/`, `.github/skills/powerbi-builder/` | Claude Code, Copilot | the full skill: workflow, visual types and roles, Modeling MCP recipes, PBIR format, troubleshooting |

Restart the agent (or reload its MCP servers) and ask for a report.

Options: `--client claude|vscode|cursor|codex|all` (repeatable), `--runner uvx|npx|python` (how clients start
pbidriver; default uvx if [uv](https://docs.astral.sh/uv/) is installed, else npx, else this Python),
`--modeling npx|exe|none` (how clients start the Modeling MCP; default npx when Node.js is installed, else the
VS Code extension's exe), `--dry-run`, `--force`.

`pbidriver doctor` checks the machine: Power BI Desktop and its version, running instances, the Desktop Bridge,
the Modeling MCP, uv and Node, and whether the current folder is set up.

### Claude Code plugin

Instead of `setup`, Claude Code users can install everything as a plugin (needs Node.js, plus uv or Python):

```text
/plugin marketplace add speak2jerome/pbidriver
/plugin install pbidriver@pbidriver
```

From a terminal: `claude plugin marketplace add speak2jerome/pbidriver`, then
`claude plugin install pbidriver@pbidriver`. The skill is then available as `/pbidriver:powerbi-builder`, and
`/mcp` lists the two servers.

### Configure an MCP client by hand

pbidriver's server is `pbidriver mcp` (stdio). Any of these starts it:

```json
{"command": "uvx", "args": ["pbidriver@latest", "mcp"]}
{"command": "cmd", "args": ["/c", "npx", "-y", "pbidriver@latest", "mcp"]}
{"command": "python", "args": ["-m", "pbidriver", "mcp"]}
```

Microsoft's server: `{"command": "cmd", "args": ["/c", "npx", "-y", "@microsoft/powerbi-modeling-mcp@latest", "--start"]}`,
or the `powerbi-modeling-mcp.exe` inside the VS Code extension folder with `--start`.

## What the agent does

The skill and the `pbi_guide` tool teach this loop:

1. `pbi_new folder=... name=Sales open=true`: a blank PBIP project, opened in Power BI Desktop. The result
   carries `model_port`.
2. Modeling MCP: `connection_operations Connect` to `localhost:<model_port>`, then `table_operations Create`
   (Power Query M from CSV/Excel/SQL, or DAX), `relationship_operations Create`, `measure_operations Create`.
   The Modeling MCP asks you once to confirm writes to the model.
3. `pbi_refresh sync=true`: saves, reloads the project so Power BI picks up the new tables, refreshes, saves.
4. `pbi_add_visual` for each visual, with field names checked against the live model; `shot=true` returns an
   annotated screenshot. `pbi_add_page` for more pages.
5. `pbi_shot`, `pbi_read` (the numbers each visual shows) and `pbi_dax` to verify; `pbi_alerts` must be empty.
6. `pbi_save`.

Every pbidriver result is JSON; screenshots come back as images the agent can look at. Errors say what to do
next, and `alerts` reports anything that blocks Power BI (dialogs, banners, broken visuals) on every call.

## Tested end to end

`scripts/e2e_kit.py` in the repository drives both MCP servers through the official MCP Python client, exactly as
an agent would, against a real Power BI Desktop (2.159, November 2026). It creates a project from a 600-row CSV, builds a
fact table, two DAX tables, two relationships, a date table with sorted months and three measures, refreshes,
builds two pages with 11 visuals, compares every chart and card with DAX and the source data, slices, saves,
closes, reopens and checks the data survived: 40 checks, about 100 seconds.

```powershell
pip install mcp
python scripts/e2e_kit.py --clean
```

## Things worth knowing

- **Refresh after model changes with `sync=true`.** Power BI Desktop only refreshes queries it has read from the
  project, so tables created through the Modeling MCP are skipped by its Refresh button until the project is
  saved and reloaded. Data loaded only through the Modeling MCP's own Refresh isn't kept when Power BI saves.
  `pbi_refresh sync=true` handles both; a plain refresh that leaves tables empty says so.
- **Don't hand-edit TMDL while the project is open.** Power BI overwrites it on save. Model changes go through
  the Modeling MCP and reach the files on `pbi_save`.
- **Report-only reloads keep unsaved model changes**; a full reload re-reads the model from disk and discards
  them. `pbi_add_visual reload=true` and `shot=true` use report-only reloads.
- **EULA and confirmations.** Microsoft's server may ask you to accept its EULA on first use and to confirm
  writes once per model. pbidriver's instructions tell agents to ask you rather than accept for you.
