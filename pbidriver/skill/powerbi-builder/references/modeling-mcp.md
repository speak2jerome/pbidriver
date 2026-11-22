# Power BI Modeling MCP recipes

Microsoft's Power BI Modeling MCP edits the semantic model inside the running Power BI Desktop. Every tool takes
one `request` object with an `operation`. Any tool explains itself with `{"operation": "Help"}`. Its
property names are case-insensitive (`"operation"` = `"Operation"`).

## Connect

```json
connection_operations {"request": {"operation": "Connect", "dataSource": "localhost:<model_port>"}}
```

`model_port` comes from `pbi_new open=true`, `pbi_instances` or `pbi_status`. Alternatively
`{"operation": "ListLocalInstances"}` lists every local Power BI with its port and window title. Later calls use
the last connection; with several windows pass `connectionName` (returned by Connect, e.g.
`PBIDesktop-Sales-49826`).

Writes ask the user to confirm once per model (an MCP elicitation the client shows as a prompt). If the server
says its EULA isn't accepted, ask the user; only they can accept it (`accept_eula` tool, or the
`--accepteula` flag / `PBI_MODELING_MCP_ACCEPT_EULA=true` in their MCP config).

## Tables

Import from CSV (Power Query M). Columns are required for M tables: `name` and `dataType`
(`Int64`, `Double`, `Decimal`, `String`, `DateTime`, `Boolean`); `sourceColumn` defaults to `name`.

```json
table_operations {"request": {"operation": "Create", "definitions": [{
  "name": "Sales",
  "mExpression": "let\n  Source = Csv.Document(File.Contents(\"C:\\data\\sales.csv\"), [Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n  Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n  Typed = Table.TransformColumnTypes(Promoted, {{\"OrderID\", Int64.Type}, {\"OrderDate\", type date}, {\"Region\", type text}, {\"Units\", Int64.Type}, {\"Revenue\", type number}})\nin\n  Typed",
  "columns": [
    {"name": "OrderID", "dataType": "Int64", "summarizeBy": "None"},
    {"name": "OrderDate", "dataType": "DateTime"},
    {"name": "Region", "dataType": "String"},
    {"name": "Units", "dataType": "Int64", "summarizeBy": "Sum"},
    {"name": "Revenue", "dataType": "Double", "summarizeBy": "Sum"}
  ]}]}}
```

Other sources, same shape (only the M changes):

- Excel: `Excel.Workbook(File.Contents("C:\\data\\book.xlsx"), null, true){[Item="Sheet1", Kind="Sheet"]}[Data]`,
  then `Table.PromoteHeaders` and `Table.TransformColumnTypes`.
- SQL Server: `Sql.Database("server", "database"){[Schema="dbo", Item="Sales"]}[Data]`.
- Folder of CSVs, web, SharePoint: any M that returns a table.

Use absolute paths with doubled backslashes inside JSON. Column names in `columns` must match the M output.

Calculated table (DAX; no `columns`):

```json
table_operations {"request": {"operation": "Create", "definitions": [
  {"name": "Regions", "daxExpression": "DATATABLE(\"Region\", STRING, \"Manager\", STRING, {{\"East\", \"Ann\"}, {\"West\", \"Bo\"}})"},
  {"name": "Date", "daxExpression": "ADDCOLUMNS(CALENDAR(DATE(2025,1,1), DATE(2025,12,31)), \"Year\", YEAR([Date]), \"Month\", FORMAT([Date], \"MMM\"), \"MonthNo\", MONTH([Date]))"}
]}}
```

Then mark the date table: `{"operation": "MarkAsDateTable", "markAsDateTableDefinitions": [{"tableName": "Date", "dateColumnName": "Date"}]}`,
and sort month names: `column_operations {"operation": "Update", "definitions": [{"tableName": "Date", "name": "Month", "sortByColumn": "MonthNo"}]}`.

`Measures` is a reserved table name.

## Relationships

`from` is the many side (fact table), `to` the one side (dimension):

```json
relationship_operations {"request": {"operation": "Create", "definitions": [{
  "fromTable": "Sales", "fromColumn": "Region", "fromCardinality": "Many",
  "toTable": "Regions", "toColumn": "Region", "toCardinality": "One",
  "crossFilteringBehavior": "OneDirection"}]}}
```

`crossFilteringBehavior`: `OneDirection` (default choice), `BothDirections` (one-to-one, or on purpose), `Automatic`.
The `to` column must have unique values.

## Measures

```json
measure_operations {"request": {"operation": "Create", "definitions": [
  {"tableName": "Sales", "name": "Total Revenue", "expression": "SUM(Sales[Revenue])", "formatString": "\\$#,0.00"},
  {"tableName": "Sales", "name": "Orders", "expression": "COUNTROWS(Sales)", "formatString": "#,0"},
  {"tableName": "Sales", "name": "Avg Order Value", "expression": "DIVIDE([Total Revenue], [Orders])", "formatString": "\\$#,0.00"},
  {"tableName": "Sales", "name": "Revenue YTD", "expression": "TOTALYTD([Total Revenue], 'Date'[Date])", "formatString": "\\$#,0"}
]}}
```

Format strings: `#,0` integer, `#,0.00` two decimals, `0.0%` percent, `\$#,0.00` dollars (escape `$` as `\$`).
Use `"operation": "Update"` with the same shape to change a measure, `Rename` with `renameDefinitions`.

## Columns

Calculated column: `column_operations {"operation": "Create", "definitions": [{"tableName": "Sales", "name": "Year", "expression": "YEAR(Sales[OrderDate])", "dataType": "Int64"}]}`.
Hide keys and set summarization: `{"operation": "Update", "definitions": [{"tableName": "Sales", "name": "OrderID", "isHidden": true, "summarizeBy": "None"}]}`.

## Load data

After creating or changing tables, load data with **pbidriver's `pbi_refresh sync=true`**. Power BI Desktop
only refreshes queries it has read from the project, so a table added through this MCP is skipped by its
Refresh until the project is saved and reloaded; `sync=true` does exactly that (save, reload from disk,
refresh, save). `table_operations Refresh` / `model_operations Refresh` load the engine too, but Power BI doesn't
keep data it didn't load itself: the saved project reopens empty. `pbi_refresh` returns the failing query's error
text when a source is wrong. Changing only measures needs no refresh.

## Check

- `pbi_model` (or `table_operations List`, `measure_operations List`, `relationship_operations List`).
- `pbi_dax` / `dax_query_operations` for numbers: `EVALUATE SUMMARIZECOLUMNS(Regions[Manager], "rev", [Total Revenue]) ORDER BY Regions[Manager]`.

## Save

The Modeling MCP changes the model in memory. `pbi_save` writes it to the project's TMDL files (plus the
report and data cache). Don't write TMDL files yourself while the project is open.
