# Use pbidriver with AI agents

pbidriver is a plain command-line tool that prints JSON, so it works with any coding agent that can run shell commands: Claude Code, GitHub Copilot (agent mode and CLI), OpenAI Codex, Cursor, Windsurf, Gemini CLI, or your own scripts. No MCP server or plugin is needed.

## Set up

1. Install it where the agent runs (on Windows, next to Power BI Desktop):

    ```powershell
    pip install pbidriver
    ```

    Node.js projects can use `npx pbidriver ...` instead (needs [uv](https://docs.astral.sh/uv/) or Python 3.9+), or call it from JavaScript with `require('pbidriver').run([...])`.

2. Paste the instructions below into the file your agent reads on start:

    | Agent | File |
    |---|---|
    | Claude Code | `CLAUDE.md` |
    | OpenAI Codex, and other agents that read it | `AGENTS.md` |
    | GitHub Copilot | `.github/copilot-instructions.md` |
    | Cursor | `.cursor/rules/pbidriver.mdc` |

```text
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

## Recipes

### Edit a PBIP report and check the result

The agent edits the report's PBIR or `report.json` files, then reloads and looks:

```powershell
pbidriver launch "C:\reports\Sales\Sales.pbip"
# ... the agent edits files under Sales.Report\ ...
pbidriver reload
pbidriver shot --page "Overview" --annotate
pbidriver read --page "Overview"
```

`reload` uses Microsoft's Desktop Bridge, so Power BI picks up the edits in place without a restart.

### Check that a measure shows the right number

```powershell
pbidriver dax "EVALUATE ROW(""Sales"", [Total Sales])"
pbidriver read --visual "Total Sales"
```

The first is what the model returns; the second is what the card visual displays, formatted as the report shows it.

### Test slicers and cross-filtering

```powershell
pbidriver slicer --visual "Region" --select "West" "East" --shot
pbidriver read --visual "Sales by Month"
pbidriver slicer --visual "Region" --clear
```

### Find slow visuals

```powershell
pbidriver perf --page "Overview" --queries
```

This returns every visual sorted by total time, with DAX query, visual display and other time in milliseconds, and the DAX query each visual sent.

### Get past startup prompts

Reports with Python or R visuals, an outdated custom visual or a recovered file can open with a prompt. The agent sees it in `alerts` and answers it:

```powershell
pbidriver launch "C:\reports\Sales.pbix"      # alerts.blocked: true, "Enable script visuals"
pbidriver dialog --shot                         # look at it
pbidriver dialog --click "Cancel"
```

### Document a report

```powershell
pbidriver inventory --summary                   # visual types and where they are used
pbidriver inventory --type slicer               # every slicer and its fields
pbidriver model --part measures                 # measures with their DAX
```

## Tips

- One `launch`ed instance per port (default 9333). Use `--port` for a second report, or `--pid` for a window you opened yourself (see `pbidriver instances`).
- Captures go to `./pbidriver_shots/`, or to `--out`.
- Close what the agent opened with `pbidriver close --discard`, so no debugging port is left open.
