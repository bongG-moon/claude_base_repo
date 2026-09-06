---
name: asset-factory
description: Design, create, repair, validate, or package a personal Claude Code Skill, script Tool, or MCP server from a natural-language request. Use for reusable automation and route the implementation through the LARGE worker.
---

# Personal Asset Factory

Turn a user's natural-language automation request into the smallest reusable asset that solves it.

## Select the asset type

- **Knowledge**: a fact, term, table definition, join, metric, or business rule. Use Personal Knowledge, not this factory.
- **Skill**: instructions, a checklist, a prompt workflow, or a procedure Claude can perform with existing tools. Prefer this by default; personal Skills become active immediately.
- **Script Tool**: deterministic local computation or file transformation requiring code. It is created as `candidate` until its tests pass.
- **MCP**: a durable typed interface to another system or capability. Use only when a Skill or script cannot provide the needed boundary. It is created as `candidate` and requires protocol/security validation before activation.

## Build contract

1. Consult Effective Knowledge before defining inputs, table meanings, or business rules.
2. Ask only for missing material choices, using at most three simple options.
3. For a Skill, choose a name that is unique across the Harness personal Skill root and the user's existing Claude config root (`CLAUDE_CONFIG_DIR` or `%USERPROFILE%\.claude`). If the create/activate command reports an external Skill collision, do not overwrite or disable the existing Skill. Rename the new asset with a clear prefix such as `company-personal-<name>` and retry.
4. Define success cases, invalid-input cases, JSON input/output schemas, permission boundaries, and offline dependencies before writing code.
5. List every required risky capability in `reviewed_capabilities`. Supported reviewable capabilities are `filesystem-read`, `filesystem-write`, `network`, `process`, and `third-party-import`. Explain the need in plain language before adding one. Dynamic code, shell execution, native code, and destructive filesystem operations are rejected because this Harness does not provide an OS sandbox.
6. Create a JSON AssetSpec and run:

   `company-agent asset create --spec "<asset-spec.json>"`

7. Validate its structure and static security scan:

   `company-agent asset validate "<asset-path>"`

8. Skills need no manual activation. For a Script Tool, save one representative JSON input under `%COMPANY_AGENT_USER_STATE%\tmp`, then let the Harness execute it with a bounded timeout and validate JSON output against the manifest schema:

   `company-agent asset test-tool --name "<name>" --input "<input.json>" --timeout 30`

   This returns a signed receipt bound to the current manifest and source hash. Activate using that exact receipt; activation creates an auto-discovered Skill wrapper:

   `company-agent asset activate-tool --name "<name>" --receipt "<receipt.json>"`

9. For an MCP, use only the administrator-approved Python environment containing the pinned `mcp>=1.20,<2` SDK. If it is absent, stop and tell the user that the approved offline wheel is required. Never run `pip` against the internet. Run the real stdio initialize, tools/list, and `health` test:

   `company-agent asset test-mcp --name "<name>" --timeout 30`

   Activate only with the receipt returned by that command:

   `company-agent asset activate-mcp --name "<name>" --receipt "<receipt.json>"`

10. Any source, manifest, command, argument, or entrypoint change invalidates the receipt. Re-run the relevant test command rather than editing a receipt.
11. In native User/Project installations, activation also registers the receipt-validated server through Claude's native `mcp add-json` for that scope. Restart Claude afterwards. If registration fails, report that native activation is pending and resolve the stated cause; retry with `company-agent asset sync-mcp --name "<name>"`. Existing/unowned MCP names are never overwritten. In the machine launcher, restart Company Agent to reload its MCP registry. Script Tool and personal Skill changes are available through live contextual retrieval.

Never write personal assets into the plugin installation directory. That directory is replaced on Core update. Store every generated asset under the user state directory selected by the harness.

Script Tools and personal MCP servers run with the current Windows user's privileges. Hash receipts, static analysis, schemas, and time/output limits reduce mistakes but are not an OS sandbox. Do not activate code that needs broader access than the user explicitly reviewed.
