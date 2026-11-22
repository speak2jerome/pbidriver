# FAQ

## Can an AI agent see a Power BI Desktop report?

Yes, with pbidriver. `pbidriver shot --page "Overview"` saves a pixel-exact PNG of the report canvas, which the agent can open and look at. `pbidriver read --page "Overview"` returns the values behind the visuals as JSON. Neither needs the Power BI service or a screenshot of the whole desktop.

## How do I screenshot a single Power BI visual from the command line?

Run `pbidriver shot --visual "<title or index>"`. Only that visual's rectangle is captured, at the report's own resolution, or sharper with `--scale 2`. `pbidriver shot --all-visuals` saves one PNG per visual, and `pbidriver shot --annotate` labels every visual with the index you can pass to `--visual`.

## Does pbidriver need the Power BI service, a Pro licence or publishing?

No. It works entirely against Power BI Desktop on your own Windows machine. Nothing is uploaded or published.

## Does it work with Claude Code, GitHub Copilot, Codex or Cursor?

Yes. pbidriver has an MCP server (`pbidriver mcp`) whose tools return screenshots as images, and `pbidriver setup` configures it for Claude Code, VS Code (GitHub Copilot), Cursor and Codex in one step. Claude Code users can also install it as a plugin. Any agent that can run shell commands can use the CLI instead: paste the [agent instructions](agents.md) into `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md` or a Cursor rule.

## Can an AI agent build a Power BI report from scratch?

Yes, with pbidriver and Microsoft's Power BI Modeling MCP together. The agent creates a PBIP project (`pbi_new`), builds the model with the Modeling MCP (tables from CSV, Excel, SQL or DAX, relationships, measures), loads the data (`pbi_refresh sync=true`), adds pages and visuals (`pbi_add_visual`), checks the screenshots and every number against DAX, and saves. An end-to-end test of exactly this runs in about 100 seconds. See [Build reports with agents](kit.md).

## How is pbidriver different from Microsoft's Power BI Desktop Bridge?

The Desktop Bridge is Microsoft's local API in Power BI Desktop (June 2026 and later). It can report the open file, reload a PBIP project and capture report pages. pbidriver uses the Bridge where it helps, and adds:

- reading the data behind visuals
- slicers, clicks, hovering, menus, scrolling and bookmarks
- capturing the Table, Model, DAX query and TMDL views
- detecting and answering every kind of dialog
- reading the report file's pages, visuals, fields, filters and bookmarks
- DAX queries, the model's metadata, and Performance Analyzer timings

It also works on Power BI Desktop builds older than the Bridge.

## How is it different from the Power BI Modeling MCP server?

Microsoft's Power BI Modeling MCP server changes the semantic model: tables, measures and relationships. It can't create report pages or visuals, or see the report. pbidriver covers that side: it creates projects, pages and visuals, shows what the report looks like and what the visuals show, and how they react to slicers and clicks. `pbidriver setup` configures both servers, and pbidriver's skill and `pbi_guide` tool teach agents to use them together.

## Can it apply slicers, scroll tables and click visuals?

Yes. These are real mouse and keyboard events sent into Power BI Desktop, so visuals react exactly as if a person used them:

- `pbidriver slicer --visual "Region" --select "West"` sets exactly that selection, even in long virtualized lists.
- `pbidriver scroll --visual <index> --dx 1200` scrolls a wide table sideways.
- `pbidriver click`, `hover`, `menu` and `bookmarks` cover the rest.

## What happens when Power BI shows a dialog, like "Enable script visuals"?

Every pbidriver command reports blocking dialogs in `alerts`, with their title, text and buttons. This covers in-app, native Windows and legacy Internet Explorer dialogs. The agent answers with `pbidriver dialog --click "<button>"`. Until it does, pbidriver refuses to send input, so the agent never waits on a prompt it can't see.

## Can it read the numbers behind charts and tables?

Yes. `pbidriver read` returns chart data points, card values, every cell of tables and matrices (scrolling through virtualized grids), and slicer options with their selection, formatted exactly as the report shows them. Custom visuals are the exception, because they run in a sandbox; query their fields with `dax` instead.

## Can it run DAX queries?

Yes. `pbidriver dax "EVALUATE ..."` runs a query against the model of the open report and returns columns and rows as JSON. `pbidriver model` lists tables, columns, measures with their DAX, and relationships. Both use the ADOMD.NET client that ships with Power BI Desktop, so nothing extra is installed.

## Does it work with PBIP and PBIR projects?

Yes. `pbidriver launch` opens `.pbix`, `.pbit` and `.pbip` files, and `inventory` reads PBIR and legacy report layouts. `pbidriver new` creates a PBIP project, `save --as` converts a `.pbix` into one, and `add-page`, `add-visual` and `remove-visual` edit its PBIR files. After an agent edits a PBIP project's files, `pbidriver reload --report-only` makes Power BI Desktop pick up the changes without a restart.

## Is there an npm package for Node.js?

Yes. `npx pbidriver ...` or `npm install -g pbidriver` runs the same command-line tool from Node.js. It needs uv or Python 3.9+; with uv nothing else is set up. The npm package also has a JavaScript API: `require('pbidriver').run(['shot', '--page', 'Overview'])` resolves with the command's JSON result.

## Does it work on macOS or Linux?

No. Power BI Desktop only runs on Windows, so pbidriver needs Windows 10 or 11.

## Is it safe to use?

pbidriver only talks to Power BI Desktop on your own machine. `launch` opens a DevTools port on `127.0.0.1`, so while that instance runs, other programs on the same machine could drive it too. Close it with `pbidriver close` when you're done. Nothing is sent anywhere else.

pbidriver is also new (first released November 2026), and it changes report files and saves through Power BI. Work on a copy of your report, or keep it in git and commit before letting an agent change it, so a bug can't cost you work. `pbidriver new --git` starts new projects under git, and the agent skill tells agents to check for version control and ask you before editing.

## How do I report a bug?

Run `pbidriver bug-report --command "<what you ran>" --error "<what went wrong>"`. It drafts an issue with your versions and redacts your home folder, user name, report names and other paths, then gives you a link that opens the pre-filled bug form on [GitHub](https://github.com/speak2jerome/pbidriver/issues) (or a `gh issue create` command). Nothing is sent until you open it. Agents have the same tool (`pbi_bug_report`) and are told to show you the draft and file it only with your OK.

## Where do I find the Power BI Modeling MCP VS Code extension?

It's `analysis-services.powerbi-modeling-mcp` on the [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=analysis-services.powerbi-modeling-mcp). Install it with `code --install-extension analysis-services.powerbi-modeling-mcp`, or search "Power BI Modeling MCP" in VS Code's Extensions view. `pbidriver locate` shows where it and pbidriver are installed on your machine, and `pbidriver setup` configures both for your agent.

## Can an agent judge how a report looks?

Yes. `pbidriver shot --clean` captures the page as a viewer sees it, with no labels, selection or hover, and lists layout problems: overlapping visuals, edges that almost line up, uneven spacing and visuals off the page. `--overlay size pos grid gaps align` draws the measurements on the page in the same units the report files use.

## Can it find slow visuals?

Yes. `pbidriver perf --runs 3 --cold` runs Power BI's Performance Analyzer with a cleared cache and reports each visual's time, its bottleneck (DAX query, rendering, or waiting on other visuals) and what to do about it. `--all-pages` ranks the whole report, `--overlay perf` paints the timings on the page, and `dax --runs 3 --cold` times a single query.

## Is pbidriver an ODBC driver or a data connector?

No. "Driver" is meant as in WebDriver: a tool that drives an application for automation. It doesn't connect Power BI to any data source.

## Which Power BI Desktop versions does it support?

It's tested on Power BI Desktop 2.152 (March 2026) and 2.159 (November 2026), Microsoft Store builds. The installer build works the same way. Desktop Bridge features need June 2026 or later.

## Is it free?

Yes. pbidriver is open source under the MIT licence. Install it with `pip install pbidriver`.
