# Troubleshooting

Start with `pbi_doctor` (machine, Power BI, Desktop Bridge, Modeling MCP, project setup) and `pbi_status`
(the window: file, page, unsaved changes, dialogs).

| Symptom | Cause | Fix |
|---|---|---|
| `alerts.blocked: true`, tools refuse to click | a modal dialog is open | `pbi_dialog` to read it, `pbi_dialog click=<button>` to answer |
| `No Power BI DevTools endpoint on 127.0.0.1:N` | the window wasn't started by pbidriver, or it uses another port | `pbi_instances` shows each window's `devtools_port`; open the file with `pbi_launch file=... port=N`. Any window (pass `pid=`) still supports status, shot, dialog, inventory, dax, model, reload and close |
| `Several Power BI windows are open; pass --pid` | Bridge/model commands can't guess the window | pass `pid=` from `pbi_instances` (or `port=` of a pbidriver window) |
| `pbi_refresh` returns `refreshed: false` with `File or Folder: Could not find...` | a source path is wrong | fix the table's M (`table_operations Update` with a new `mExpression`), `pbi_dialog click=Close`, `pbi_refresh` |
| `pbi_refresh` says some tables are still empty; visuals show `(Blank)`; banner "Some of the tables have incomplete or no data" | tables were created through the Modeling MCP and Power BI hasn't re-read the model | `pbi_refresh sync=true` |
| Reopened project shows `(Blank)` and a "Refresh now" banner | data was loaded only through the Modeling MCP's Refresh | `pbi_refresh sync=true`, then `pbi_save` |
| `pbi_add_visual`: unknown field / table | name typo or the measure doesn't exist yet | the error lists valid names; create measures first |
| Visual shows the same value on every row | no relationship between the tables in the visual | `relationship_operations Create` (from fact to dimension) |
| Numbers look wrong | implicit sum of an ID or a wrong aggregation | `pbi_read` vs `pbi_dax`; use explicit measures; set `summarizeBy: None` on ID columns |
| Visual shows an error icon (`alerts.visual_errors`) | bad field reference after a rename, or a failed query | `pbi_layout` to see its fields, remove and re-add it |
| "Something went wrong / Failed to load the report" after editing JSON | malformed PBIR file | undo the edit (keep files in git), `pbi_reload report_only=true` |
| `pbi_reload` or `pbi_add_visual` complains about a .pbix | they need a PBIP project | `pbi_save as=<dir>/<Name>.pbip` first |
| "Enable script visuals" or other prompts after each reload | a report with R/Python visuals | `pbi_dialog click=Cancel` (or Enable if the user agrees) |
| Modeling MCP write declined | the user (or client) declined the confirmation | ask the user; don't retry on your own |
| Modeling MCP: EULA not accepted | first use | ask the user to accept it; never accept for them |
| Modeling MCP can't find the instance | Power BI still loading, or a different window | `pbi_instances` for `model_port`, Connect with `localhost:<port>` |
| Several Power BI windows | ports and connections mixed up | one `port` per window for pbidriver, `connectionName` for the Modeling MCP |
| Screenshot is empty or cut | window minimized/off-screen or still rendering | pbidriver restores and waits itself; raise `settle` for heavy pages |
| `pbi_save` says saved but `unsaved` stays true | a dialog interrupted the save | `pbi_alerts`, answer it, save again |

Errors always come back as `{"ok": false, "error": "..."}`; most include what to do next.
