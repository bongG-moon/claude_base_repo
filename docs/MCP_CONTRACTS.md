# Managed MCP contracts

The repository does not implement the company's database and Outlook transports. Deployment supplies their real commands in `managed-mcp.json`. The Harness enforces the following outer contracts, and each MCP server must independently enforce the same rules.

## `corp-db-read`

- Authenticate with the current employee's approved database identity.
- Expose read-only metadata and query tools only.
- Keep query tool names within the Harness allowlist (`query`, `select`, `execute_query`, `run_query`, or names composed from those read verbs). A name that also contains a write verb is rejected.
- Put executable SQL in a recognized string field such as `sql`, `query`, `statement`, `query_text`, `sql_text`, or `command`. Unknown fields containing SQL-shaped text and unknown operations are rejected.
- Accept only one `SELECT`, `WITH ... SELECT`, or `EXPLAIN SELECT` statement.
- Reject DML, DDL, stored procedure execution, multi-statements, transaction controls, writable temporary operations, malformed quotes/comments, and SQL Server `SELECT ... INTO`.
- Use a database principal that physically lacks write permission. Hook validation is defense in depth, not the security boundary.
- Bound row count, duration, and result size.

## `corp-outlook-self`

- Bind the connection to the current employee's mailbox.
- Every send/reply/forward/resend call must expose either the sender identity or a top-level `authenticatedAccount*` identity that the MCP server injects immutably. Ignore or reject any override that differs from the initialized `user_email`; never let the model supply a field that is presented as immutable authentication evidence.
- Permit recipients according to company mail policy; the Harness requirement here constrains the sender, not recipients.
- Read/search operations may run automatically. Non-send mutations and unknown Outlook operations require a user confirmation instead of being auto-approved.
- Return a confirmation preview before any send if the managed MCP itself is configured to require it.
- Record only the minimum operational receipt required by existing company policy; the Harness stores no message body.

## Personal MCP

The Asset Factory scaffolds personal MCP servers as `candidate`. They are not added to the launch registry until all of the following pass:

- the asset name, source path, manifest entrypoint, Python command, and arguments remain confined to the expected per-user asset directory;
- the AST-based static scan finds no unreviewed capability or unsupported dynamic/shell/native/destructive behavior;
- the approved offline Python environment provides the pinned `mcp>=1.20,<2` SDK;
- a real stdio protocol probe completes `initialize`, `tools/list`, and the no-argument `health` tool within the timeout;
- the Harness creates a signed validation receipt bound to the current asset content hash, and activation verifies that receipt again.

The Harness never installs the MCP SDK from the internet. Administrators must distribute an approved wheelhouse or Python environment. A missing or incompatible dependency fails clearly. A new MCP requires Company Agent restart because MCP configuration is loaded at launch.

Personal MCP code executes with the current Windows user's privileges. Static analysis, content-bound receipts, protocol checks, and time limits are safety checks, not an OS sandbox. Capabilities such as network access or third-party imports must be listed explicitly in the asset manifest and reviewed for the specific use case.
