# Company Agent Harness Architecture

## Native installation scopes (0.3)

The default installer now registers the same offline plugin ID in Claude's user
scope or project-local scope. Ordinary `claude` sessions load the hooks without a
special launcher. Shared releases live under `%LOCALAPPDATA%\CompanyAgent-Distribution`,
while User/Project state is independently selected from installer records under
`%LOCALAPPDATA%\CompanyAgent\installations`. A Project record takes precedence only
inside its project and only while its native installation remains enabled.

`SessionStart` invokes PowerShell as a real Windows executable, selects the
bundled Python runtime, initializes the chosen state without email prompts, and
builds the knowledge index. Every hook resolves the same scope from its input cwd.
Prompt hooks inject bounded personal Skill metadata and knowledge paths; Claude
reads the relevant Skill body before use. The runtime supplies an absolute CLI
command, so neither global PATH edits nor copying personal Skills into unrelated
Claude directories are necessary.

The Project Harness Factory designs native project agents, Skills and a rule file.
The main conversation retains project orchestration and calls its stage workers;
ordinary subagents do not recursively orchestrate other subagents. Generic
single-worker routing remains the default for other work. Models and retries are
guided by instructions; the Stop hook enforces a bounded verification-record
check, not an independent test runner or a complete shell-write detector.

The machine launcher and Program Files/ProgramData lifecycle described below
remain available as the explicit administrator deployment path. See
[deployment scopes](DEPLOYMENT.md), [project generation](PROJECT_HARNESS.md), and
[implementation evidence and limits](IMPLEMENTATION_REVIEW.md) for the default flow.

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
                 Skills + optional MCP tools
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

With the default `AUTO` mode, the interactive parent session keeps the model already selected by the user's Claude Code configuration. Claude Code does not expose a Hook response field that changes the active main-session model. Therefore the native CLI implementation performs real workload-specific execution through plugin subagents whose `model` frontmatter is `haiku`, `sonnet`, or `opus`. Those aliases are already configured to the company's SMALL, MEDIUM, and LARGE models before this Harness is installed.

This keeps ordinary Claude Code interaction, Skills, MCP, permissions, and session UX intact. A future custom UI can use the Agent SDK streaming `set_model` API if switching the same main-session model is a hard requirement.

The repository assumes the company's existing Claude Code-compatible internal model connection works. It does not implement or validate an Anthropic Messages API shim.

## Model routing policy

| Tier | Default use | Escalation examples | Worker model alias |
|---|---|---|---|
| SMALL | concise summary, translation, formatting, bounded lookup | tool use, file change, ambiguity | `haiku` |
| MEDIUM | normal implementation, analysis, document creation, testing | cross-system design, security, difficult root cause | `sonnet` |
| LARGE | architecture, high-risk decisions, broad migrations, Skill/Tool/MCP creation | no automatic downgrade during the turn | `opus` |

The worker classifier is deterministic and keeps MEDIUM as the unknown delegated-task default. This does not force the interactive parent to MEDIUM. High-risk signals override a user's request for a lower worker tier. Routing metadata contains only tier, alias, worker name, verification requirement, and reason codes.

If a SMALL or MEDIUM worker discovers that the task is broader or riskier than classified, the coordinator performs one-way escalation to MEDIUM or LARGE. It never silently downgrades a safety floor.

The standard `claude-config` mode stores aliases, not internal model IDs:

```text
SMALL  = haiku
MEDIUM = sonnet
LARGE  = opus

AUTO main session       -> no --model argument; keep existing Claude default
forced tier / subagent  -> --model or frontmatter uses the selected alias
```

The Launcher does not set `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, or `ANTHROPIC_DEFAULT_OPUS_MODEL` in this mode. It clears inherited process-level `CLAUDE_CODE_SUBAGENT_MODEL` overrides only inside its child process so that the three workers are not collapsed onto one model; it does not change Windows or Claude settings. Because Claude settings can inject those variables again, Setup and Start inspect the user, project/local, file-managed, and Windows registry settings they can access and refuse to run when a non-empty forcing value is present. An explicit model-ID map remains only as a backward-compatible advanced mode.

References: [Claude Code model configuration](https://code.claude.com/docs/en/model-config), [custom subagents](https://code.claude.com/docs/en/sub-agents), and [Hooks](https://code.claude.com/docs/en/hooks).

## Separation of ownership

```text
C:\Program Files\CompanyAgent\versions\<core-version>
  Replaceable: plugin, hooks, agents, Skills, Python harness

C:\ProgramData\CompanyAgent\knowledge\versions\<knowledge-version>
  Administrator-managed: Corporate Knowledge Base

C:\ProgramData\CompanyAgent\config\versions\<core-version>
  Administrator-managed, versioned: session settings, alias mode,
  optional managed MCP config

%LOCALAPPDATA%\CompanyAgent
  User-owned: Personal Knowledge, Skills, Tool/MCP candidates,
  compact session verification state, versions, exports, ledger
```

The launcher passes the Corporate Knowledge version and personal root with `--add-dir`, loads the versioned Core with `--plugin-dir`, and passes managed and active personal MCP registries with `--mcp-config` only when they contain a server. Empty Harness registries therefore leave existing user/project/plugin MCP configuration visible. Non-empty Harness registries merge by default; strict isolation requires an explicit managed setting. The Launcher never modifies `%USERPROFILE%\.claude` or `CLAUDE_CONFIG_DIR`.

Before first installation, the Windows Setup performs a selective, timestamped recovery backup of existing Claude instructions/settings, Skills, commands, agents, Hooks, and plugin registration metadata. The backup ACL is limited to the current Windows user and LocalSystem, secret-like JSON fields are redacted, and reparse points are never followed. It excludes credential files, transcripts, history/projects, cache, debug data, and telemetry. Core, versioned config, Corporate Knowledge, and User State remain separate so an update or rollback cannot replace personal Knowledge, Memory, Skills, or asset candidates.

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
- Before creating or activating a personal Skill, the Asset Factory checks the existing global Claude Skill directory. A matching name is rejected without overwriting either copy; the user is guided to a unique name such as `company-personal-<name>`.
- Script Tools are candidates until a bounded runtime test validates their JSON schemas and creates a signed receipt bound to the current asset hash. Activation rechecks that receipt and creates a personal Skill wrapper.
- MCP servers are candidates until compile/static checks and a real offline stdio initialize, tool-list, and health test create a content-bound receipt. A restart is then required.

Skills and supporting files are loaded progressively rather than putting the entire knowledge corpus in `CLAUDE.md`. Plugin Skills remain namespaced, while personal and added-directory Skills must use unique names. See [Claude Code Skills](https://code.claude.com/docs/en/skills) and [plugins](https://code.claude.com/docs/en/plugins).

## Security boundaries

Knowledge and Skills are not enforcement boundaries.

- `corp-db-read`: a PreToolUse Hook rejects non-SELECT SQL and multi-statements. The database principal and MCP server must also be physically read-only.
- `corp-outlook-self`: when this separately developed MCP is installed and its user onboarding is complete, a PreToolUse Hook rejects a sender different from the initialized user's email. The MCP server must bind authentication to that same mailbox.
- The managed settings do not pre-allow either corporate MCP. A successful Hook decision makes safe calls seamless; if the Hook fails, Claude Code falls back to its normal permission boundary rather than an organization-provided allow rule. Server-side enforcement remains mandatory because a killed Hook cannot be a hard security boundary.
- Corporate Core and Knowledge directories receive read/execute ACLs for ordinary users.
- Personal generated code never writes into Core. Script Tools and MCP servers are candidates until validated.
- Personal generated code still runs with the current Windows user's privileges. Static analysis and receipts are integrity/quality controls, not an OS sandbox.
- Security policies sit above Corporate and Personal Knowledge and cannot be forked.

## Feedback loop

The activity Hook records only minimal session metadata. If a mutating tool ran after the last successful verification, the Stop Hook returns corrective context and prevents completion. The Agent runs the relevant deterministic check and records a short pass/fail summary. Equivalent failure retry is bounded at two attempts to prevent an endless loop.
