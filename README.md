# Company Agent Harness

A Windows-first, offline-deployable Claude Code CLI harness for one personalized Agent per employee.

It provides:

- automatic SMALL/MEDIUM/LARGE workload routing through model-specific Claude Code subagents;
- a bounded execute → verify → correct feedback loop;
- an administrator-managed Corporate Knowledge Base plus a writable per-user Knowledge Overlay;
- compact, relevant Personal Memory retrieval on each request without copying raw sessions into the Harness state;
- natural-language creation of personal Skills, script Tools, and MCP candidates;
- content-bound runtime/protocol receipts before generated Tools or MCP servers can activate;
- defense-in-depth enforcement for `corp-db-read` SELECT-only access and `corp-outlook-self` sender identity;
- side-by-side Core and Knowledge installation, update, rollback, hash verification, ACLs, and user-state-preserving uninstall;
- no external SaaS, vector database, or Python package dependency for the Harness itself.

## Repository layout

```text
company-agent-plugin/   Versioned Claude Code plugin and standard-library Python runtime
corporate-knowledge/    Administrator-managed Markdown seed pack
admin-authoring/        Author-only Claude Code Skill
config/                 Managed settings and MCP examples
deploy/                 Windows PowerShell deployment lifecycle
docs/                   Architecture, operations, and authoring guides
tests/                  Python and deployment smoke tests
```

## Development validation

Prerequisites on the build PC:

- Windows PowerShell 5.1 or PowerShell 7
- Python 3.11 or newer
- the company-supported Claude Code CLI 2.1.220 or newer

```powershell
python -m unittest discover -s .\tests -v
python -m compileall -q .\company-agent-plugin
claude plugin validate --strict .\company-agent-plugin
python .\company-agent-plugin\scripts\harness_cli.py knowledge validate `
  --base .\corporate-knowledge
```

## Prepare an internal release

1. Replace the example values in `config\managed-mcp.example.json` with the real internal MCP commands and save the approved file as `config\managed-mcp.json`.
2. Add validated company Markdown to `corporate-knowledge` and update its `pack.json` version.
3. Build a hash-manifested offline bundle:

```powershell
.\deploy\New-OfflineBundle.ps1 `
  -CoreVersion 0.1.0 `
  -KnowledgeVersion 2026.09.03
```

4. Code-sign the ZIP delivery wrapper and every PowerShell script using the company's signing certificate before enterprise distribution.

See [deployment instructions](docs/DEPLOYMENT.md), [architecture](docs/ARCHITECTURE.md), [Knowledge authoring](docs/ADMIN_KNOWLEDGE_GUIDE.md), and [managed MCP contracts](docs/MCP_CONTRACTS.md).

## Important model-routing assumption

The project assumes the existing internal model connection already works with Claude Code, as specified for this deployment. The Harness maps Claude Code's `haiku`, `sonnet`, and `opus` aliases to the internal SMALL, MEDIUM, and LARGE model IDs. It does not build an API shim and does not claim general non-Claude gateway compatibility.
