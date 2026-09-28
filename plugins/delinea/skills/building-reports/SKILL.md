---
name: building-reports
description: Build and run Delinea Secret Server SQL reports, such as stale or unused secrets, who can access a folder, role and group membership, recent logins and audit activity. Use whenever the user asks a question about their Secret Server data that a list or search tool can't answer directly, or asks for a report, audit, count or export.
---

# Build Secret Server reports

Secret Server answers analytic questions through SQL reports. The Delinea
MCP server runs a report as a temporary report that it deletes afterwards,
with the configured account's reporting permissions.

The tools named below come from the Delinea MCP server. Depending on how it
is installed, they may appear with a prefix such as `mcp__delinea__`.

## Workflow

1. **Read the reference first.** Call `list_example_reports`. It returns
   tested example queries, the tables and columns they use, and special
   fields. Build every query from that reference. Don't guess table or
   column names.
2. **Start from the closest example.** Adapt an example query rather than
   writing one from scratch. Keep its joins and `WITH (NOLOCK)` hints.
3. **Write a narrow query.** Select only the columns the user needs, filter
   with `WHERE`, and aggregate (`COUNT`, `GROUP BY`) when the user asks "how
   many" or "which ones most".
4. **Run it** with `run_report`. Pass a short, descriptive `report_name`.
   Results are capped by `max_rows` (default 200). If `truncated` is true,
   refine the query or aggregate instead of raising the cap.
5. **Check the result.** Empty or surprising results usually mean a wrong
   join or filter. Re-check the reference and adjust before concluding.
6. **Present it.** Show a table, or a summary with the key numbers, and say
   which filters you used. Offer the SQL if the user wants to save it as a
   permanent report in Secret Server.

## SQL rules

- The database is Microsoft SQL Server (T-SQL). Use `SELECT TOP 50 ...`, not
  `LIMIT`. Use `GETDATE()` and `DATEADD(day, -90, GETDATE())` for dates.
- Only `SELECT` statements run. Don't attempt `INSERT`, `UPDATE`, `DELETE`
  or DDL. Make changes through the management tools instead.
- Bracket reserved or spaced names: `[Permissions]`, `[Role Permission]`.
- Report results pass through the conversation, so **never select secret
  values**. Don't select `tbSecretItem.ItemValue` for password, key or token
  fields. To work with a credential, follow the no-secret-visibility skill.
- Joining audit tables over long periods can be slow. Filter
  `DateRecorded` to the window the user cares about.

## Common requests

| Question                               | Starting point                                                                                                                      |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Secrets nobody has used recently       | Example "Retrieve Secrets with Latest Audit Information", filtered with `WHERE a.latestdaterecorded < DATEADD(day, -90, GETDATE())` |
| Who can reach a folder                 | Example "Get User Permissions for Folders", filtered by `f.FolderId`                                                                |
| Who can reach a secret                 | Example "Get Group Permissions for Secrets", joined to `tbUserGroup` for users                                                      |
| Secrets that don't inherit permissions | Example "Get Secret Inheritance Settings" with `WHERE s.EnableInheritPermissions = 0`                                               |
| Users who haven't signed in lately     | `tbUser` filtered on `LastLogin`, with `Enabled = 1`                                                                                |
| What a role allows                     | Example "Get User Role Permissions", or `tbRoleToRolePermission` joined to `tbRolePermission`                                       |

## When a report fails

- **Invalid column or object name**: the name isn't in the reference. Pick
  one that is, or ask the user what they're after.
- **Permission denied**: the configured account can't run custom reports.
  An administrator must grant the report permissions in Secret Server.
- **Timeout**: add a `WHERE` filter, narrow the date range, or aggregate.
