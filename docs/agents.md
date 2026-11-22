# Use pbidriver with AI agents

pbidriver works with any coding agent, three ways:

- **MCP server** (`pbidriver mcp`): every command is a typed tool (`pbi_shot`, `pbi_add_visual`, ...) and
  screenshots come back as images. Best for Claude Code, GitHub Copilot in VS Code, Cursor and Codex.
- **Claude Code plugin**: the MCP server, Microsoft's Power BI Modeling MCP and the powerbi-builder skill in
  one install.
- **CLI**: plain commands that print JSON, for any agent that can run a shell command, and for scripts.

!!! warning "Give agents a copy, or a git repository"
    pbidriver is new and lets agents change report files. Keep reports in git (commit before an agent works on
    them) or let agents work on copies. The agent instructions below and the powerbi-builder skill tell agents to
    check this and ask you first.

## Set up (MCP, recommended)

```powershell
pip install pbidriver
```

```powershell
pbidriver setup
```

This writes MCP configs for Claude Code, VS Code and Cursor (add `--client codex` or `--client all` for
Codex), an `AGENTS.md` section, and the powerbi-builder skill, and also configures Microsoft's Power BI
Modeling MCP so the agent can build the model too. Details, the Claude Code plugin and manual configuration:
[Build reports with agents](kit.md).

## Set up (CLI only)

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
- Build: `pbidriver new <folder> --name <Name> --open`; model through the Power BI Modeling MCP, then
  `pbidriver refresh --sync`; `pbidriver add-visual <type> --field "Category=T[Col]" --field "[Measure]" --shot`.
  `pbidriver add-visual --help` lists the types; `pbidriver layout` lists what's on a page.
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

## Recipes

### Build a report from a CSV

With the Power BI Modeling MCP configured next to pbidriver (see [Build reports with agents](kit.md)), ask:
"Build a sales report from data\sales.csv: revenue by region and month, top products, a region slicer." The
agent creates the project with `pbi_new`, the model with the Modeling MCP, loads it with
`pbi_refresh sync=true`, lays out visuals with `pbi_add_visual`, checks them with `pbi_shot` and `pbi_read`
against `pbi_dax`, and saves. The same steps by hand:

```powershell
pbidriver new C:\work\sales --name Sales --open
# ... tables and measures through the Power BI Modeling MCP ...
pbidriver refresh --sync
pbidriver add-visual card --field "[Total Revenue]" --x 20 --y 70 --width 300 --height 110
pbidriver add-visual clusteredColumnChart --field "Category=Sales[Region]" --field "Y=[Total Revenue]" --x 20 --y 200 --width 620 --height 250 --title "Revenue by region" --shot
pbidriver read
pbidriver save
```

### Turn a .pbix into an editable project

```powershell
pbidriver launch "C:\reports\Sales.pbix"
pbidriver save --as "C:\reports\Sales\Sales.pbip"
pbidriver layout
```

### Edit a PBIP report and check the result

The agent edits the report's PBIR or `report.json` files, then reloads and looks:

```powershell
pbidriver launch "C:\reports\Sales\Sales.pbip"
# ... the agent edits files under Sales.Report\ ...
pbidriver reload --report-only
pbidriver shot --page "Overview" --annotate
pbidriver read --page "Overview"
```

`reload` uses Microsoft's Desktop Bridge, so Power BI picks up the edits in place without a restart. `--report-only` keeps model changes that aren't saved yet; a full reload re-reads the model from disk too.

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

### Review how a page looks

```powershell
pbidriver shot --page "Overview" --clean --scale 2          # the page as a viewer sees it, plus layout issues
pbidriver shot --page "Overview" --overlay index size pos gaps align
```

The first returns a clean image and `layout.issues` (overlaps, edges that almost line up, uneven gaps, visuals off the page); the second draws each visual's size and position in page units, the spacing between neighbours and the near-miss edges.

### Find slow visuals

```powershell
pbidriver perf --page "Overview" --runs 3 --cold --queries
pbidriver perf --all-pages --top 3
pbidriver shot --page "Overview" --overlay index title perf
```

`perf` returns every visual sorted by total time (medians of 3 refreshes with a cleared cache), with DAX query, visual display and other time, each visual's bottleneck, tuning hints, and the DAX query each visual sent. Time a single query before and after a measure change with `pbidriver dax "<query>" --runs 3 --cold`.

### Report a pbidriver bug

```powershell
pbidriver bug-report --command "pbidriver read --visual 3" --error "<error or wrong result>" --expected "<what should happen>"
```

This drafts a GitHub issue with versions and the failing call, with personal paths and report names redacted, and returns a link to the pre-filled bug form. Nothing is sent until you open it.

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
