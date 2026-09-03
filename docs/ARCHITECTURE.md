# Company Agent Harness Architecture

## Runtime

```text
Natural-language user request
        |
        v
UserPromptSubmit hook
  deterministic route; prompt is not persisted
        |
        +-------------------+-------------------+
        |                   |                   |
        v                   v                   v
 SMALL worker          MEDIUM worker        LARGE worker
 haiku alias           sonnet alias         opus alias
 simple/low risk       normal work          complex/high risk
        \                   |                   /
         +------------------+------------------+
                            |
                 Skills + managed MCP tools
                            |
              PostToolUse compact activity state
                            |
                       Stop hook
                   +--------+--------+
                   |                 |
             validator PASS     missing/failed
                   |                 |
                finish       corrective feedback
                                     |
                              maximum two retries
```

The interactive parent session is a MEDIUM-model coordinator. Claude Code does not expose a Hook response field that changes the active main-session model. Therefore the native CLI implementation performs real workload-specific execution through plugin subagents whose `model` frontmatter is `haiku`, `sonnet`, or `opus`. The launcher maps those aliases to the already-working internal SMALL, MEDIUM, and LARGE model IDs.

This keeps ordinary Claude Code interaction, Skills, MCP, permissions, and session UX intact. A future custom UI can use the Agent SDK streaming `set_model` API if switching the same main-session model is a hard requirement.

The repository assumes the company's existing Claude Code-compatible internal model connection works. It does not implement or validate an Anthropic Messages API shim.

## Model routing policy

| Tier | Default use | Escalation examples | Worker model alias |
|---|---|---|---|
| SMALL | concise summary, translation, formatting, bounded lookup | tool use, file change, ambiguity | `haiku` |
| MEDIUM | normal implementation, analysis, document creation, testing | cross-system design, security, difficult root cause | `sonnet` |
| LARGE | architecture, high-risk decisions, broad migrations, Skill/Tool/MCP creation | no automatic downgrade during the turn | `opus` |

The classifier is deterministic and keeps MEDIUM as the unknown-task default. High-risk signals override a user's request for a lower tier. Routing metadata contains only tier, alias, worker name, verification requirement, and reason codes.

If a SMALL or MEDIUM worker discovers that the task is broader or riskier than classified, the coordinator performs one-way escalation to MEDIUM or LARGE. It never silently downgrades a safety floor.

Model IDs are configured in machine-managed configuration and exported at launch:

```text
ANTHROPIC_DEFAULT_HAIKU_MODEL  = internal SMALL model ID
ANTHROPIC_DEFAULT_SONNET_MODEL = internal MEDIUM model ID
ANTHROPIC_DEFAULT_OPUS_MODEL   = internal LARGE model ID
--model                        = haiku | sonnet | opus
```

References: [Claude Code model configuration](https://code.claude.com/docs/en/model-config), [custom subagents](https://code.claude.com/docs/en/sub-agents), and [Hooks](https://code.claude.com/docs/en/hooks).

## Separation of ownership

```text
C:\Program Files\CompanyAgent\versions\<core-version>
  Replaceable: plugin, hooks, agents, Skills, Python harness

C:\ProgramData\CompanyAgent\knowledge\versions\<knowledge-version>
  Administrator-managed: Corporate Knowledge Base

C:\ProgramData\CompanyAgent\config
  Administrator-managed: model IDs and managed MCP config

%LOCALAPPDATA%\CompanyAgent
  User-owned: Personal Knowledge, Skills, Tool/MCP candidates,
  compact session verification state, versions, exports, ledger
```

The launcher passes the Corporate Knowledge version and personal root with `--add-dir`, loads the versioned Core with `--plugin-dir`, and optionally passes managed and active personal MCP registries with `--mcp-config`. It never modifies `~\.claude`.

## Effective Knowledge

```text
Corporate Base by stable Knowledge ID
       +
Personal `extend`, `fork`, and `personal-new` Markdown
       |
       v
Generated local JSON/TSV/Markdown index
       |
       v
Corporate Knowledge router Skill reads only relevant documents
```

An `extend` is safely rebased when the Corporate Base changes. A `fork` whose base hash changed becomes a visible conflict. Neither case deletes the personal file. The source of truth remains Markdown; generated indexes can always be rebuilt.

The Harness stores extracted knowledge and short provenance only. It does not copy session transcripts, prompts, tool inputs, tool outputs, email bodies, or query results into User State.

At each prompt, the local Hook searches only active Personal Memory items by title and body, caps the result count and size, and injects relevant extracts inside an explicit untrusted-data boundary. Memory can personalize the answer but cannot override the current request or managed policy.

## Personal asset lifecycle

```text
Natural-language request
  -> Knowledge | Skill | Script Tool | MCP classification
  -> AssetSpec
  -> scaffold in User State
  -> static validation
  -> representative and negative tests
  -> activate
```

- Personal Skills become active immediately because their directory is supplied through `--add-dir` and Claude Code auto-discovers `.claude/skills` there.
- Script Tools are candidates until a bounded runtime test validates their JSON schemas and creates a signed receipt bound to the current asset hash. Activation rechecks that receipt and creates a personal Skill wrapper.
- MCP servers are candidates until compile/static checks and a real offline stdio initialize, tool-list, and health test create a content-bound receipt. A restart is then required.

Skills and supporting files are loaded progressively rather than putting the entire knowledge corpus in `CLAUDE.md`. See [Claude Code Skills](https://code.claude.com/docs/en/slash-commands).

## Security boundaries

Knowledge and Skills are not enforcement boundaries.

- `corp-db-read`: a PreToolUse Hook rejects non-SELECT SQL and multi-statements. The database principal and MCP server must also be physically read-only.
- `corp-outlook-self`: a PreToolUse Hook rejects a sender different from the initialized user's email. The MCP server must bind authentication to that same mailbox.
- The managed settings do not pre-allow either corporate MCP. A successful Hook decision makes safe calls seamless; if the Hook fails, Claude Code falls back to its normal permission boundary rather than an organization-provided allow rule. Server-side enforcement remains mandatory because a killed Hook cannot be a hard security boundary.
- Corporate Core and Knowledge directories receive read/execute ACLs for ordinary users.
- Personal generated code never writes into Core. Script Tools and MCP servers are candidates until validated.
- Personal generated code still runs with the current Windows user's privileges. Static analysis and receipts are integrity/quality controls, not an OS sandbox.
- Security policies sit above Corporate and Personal Knowledge and cannot be forked.

## Feedback loop

The activity Hook records only minimal session metadata. If a mutating tool ran after the last successful verification, the Stop Hook returns corrective context and prevents completion. The Agent runs the relevant deterministic check and records a short pass/fail summary. Equivalent failure retry is bounded at two attempts to prevent an endless loop.
