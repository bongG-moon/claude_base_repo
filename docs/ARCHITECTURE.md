# Company Agent Harness Architecture

## Company and personal ownership

There are two management domains: company policy/work standards (including department applicability) and personal work. Project scope is not a third policy authority or an installable team pack. Optional `workStandards` in the registered managed config distinguishes required guidance from overridable defaults. It does not replace existing enforcement or grant native permissions. Only matching bounded rules are passed to the coordinator and owned workers; references are not promoted into policy. See [company/personal workflow](COMPANY_PERSONAL_WORKFLOW.md) for the schema, offline onboarding, opt-in diagnostics, and limitations.

## Native installation scopes (1.1.0)

1.0.0 is the first-release baseline. 1.1.0 adds automatic personal learning without replacing personal state.
Earlier 0.3.x labels refer to pre-release development iterations.

The default installer now registers the same offline plugin ID in Claude's user
scope or project-local scope. Ordinary `claude` sessions load the hooks without a
special launcher. Shared releases live under `%LOCALAPPDATA%\CompanyAgent-Distribution`,
while User/Project state is independently selected from installer records under
`%LOCALAPPDATA%\CompanyAgent\installations`. A Project record takes precedence only
inside its project and only while its native installation remains enabled.

`SessionStart` invokes PowerShell as a real Windows executable, selects the
existing Python 3.11+ interpreter validated at installation, initializes the chosen state without email prompts, and
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
              learning review corrective feedback
                                     |
                              maximum two retries
```

After verification passes or its bounded retry budget is exhausted, `Stop`
requests a main-conversation self-learning review (at most two continuations).
Read-only turns are also reviewed. The local engine validates turn identity,
evidence, private paths and observed Skill hashes before changing only owned
preference items or small personal Skill checklist sections. Later same-task
uses assess the exact changed version; effects remain observational, not causal
proof. No separate LLM process, transcript reader or background daemon is used.
See [automatic learning](SELF_LEARNING.md) for evidence gates and pause/rollback.

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

For the three general workers, the standard `claude-config` mode stores aliases, not internal model IDs:

```text
SMALL  = haiku
MEDIUM = sonnet
LARGE  = opus

AUTO main session       -> no --model argument; keep existing Claude default
forced tier / subagent  -> --model or frontmatter uses the selected alias
```

The Launcher does not set `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, or `ANTHROPIC_DEFAULT_OPUS_MODEL` in this mode. It clears inherited process-level `CLAUDE_CODE_SUBAGENT_MODEL` overrides only inside its child process so that the three workers are not collapsed onto one model; it does not change Windows or Claude settings. Because Claude settings can inject those variables again, Setup and Start inspect the user, project/local, file-managed, and Windows registry settings they can access and refuse to run when a non-empty forcing value is present. An explicit model-ID map remains only as a backward-compatible advanced mode.

References: [Claude Code model configuration](https://code.claude.com/docs/en/model-config), [custom subagents](https://code.claude.com/docs/en/sub-agents), and [Hooks](https://code.claude.com/docs/en/hooks).

### Image-only routing

`company-agent:vision-worker` is a separate observation worker whose model frontmatter is the exact ID `HCP-Vision-Latest`. This is an operational HCP model, not a fourth workload tier or a replacement for the main session's model. The existing environment value `ANTHROPIC_CUSTOM_MODEL_OPTION == "HCP-Vision-Latest"` enables `visionRouting.enabled`; an absent model in a personal or validation environment must not trigger a probe or forced model request. Enabling routing is local configuration detection, not a model-availability check.

When an image-file `Read` or a recognized screenshot MCP call requires visual inspection, the parent delegates the bounded observation to this worker in a separate context. An ordinary worker instead returns `NEEDS_VISION` with the exact existing image paths, or the exact capture tool name and arguments, the requested page/region, and the current `workFile`. It does not recursively invoke a worker. The parent passes the Korean text result back to the original task and model; the vision worker does not edit the work file or create another deliverable.

Only the review purpose, question, required page/region, and relevant paths or capture arguments belong in that context. Do not forward full conversation history, unrelated business-document bodies, secrets, or unrelated images. The response identifies the observed area, findings, and unverified scope in Korean text; it excludes original image payloads, raw base64, and full OCR dumps. Native permissions and source-data handling restrictions still apply. A routing handoff is not authority to retry an actual permission denial through another tool, model, or worker.

If the model, image input, or observation tool is unavailable, the worker returns `VISION_UNAVAILABLE` with the reason and unverified scope. The parent continues feasible structural/content checks and reports visual inspection as unverified. It does not switch to another model, repeatedly discover model lists, or resend the same images. Offline fixtures can verify this routing contract without gateway or model requests; they do not establish that operational image inspection succeeded.

Two boundaries remain explicit: a native CLI image pasted directly into the prompt reaches the model API before tool hooks, so this routing cannot intercept it; a general MCP can return mixed text/image content that its name does not reveal. Known image-file and screenshot routes therefore do not guarantee automatic conversion of every image input or MCP output. Users can request a bounded review by giving an image file path and then continue with an ordinary text follow-up.

The image backstop covers `Read` for PNG/JPEG/GIF/WebP and PDF (which can include rendered pages), `chrome-devtools.take_screenshot`, `playwright.browser_take_screenshot`, and `local-computer-use.zoom` under those exact MCP server names. The vision worker has an explicit observation-only tool list; a different server with a same-named tool is not implicitly trusted. Mixed `computer_inspect`/`get_window_state` calls can be delegated proactively when the existing session is known to return images, but are not auto-classified from their names. No extra status query is run merely to decide routing.

The per-invocation Agent `model` override is removed only for this worker, selecting its frontmatter ID: the installed CLI's Agent tool parameter accepts family aliases, not this custom ID. General workers' model arguments are preserved. Vision results do not create mutation receipts or Stop retries, and existing unfinished output-verification obligations remain intact.

New scoped installations give `Read` a separate lightweight entry using the Python executable selected by setup. Ordinary reads return an empty hook result without opening the document, settings, registrations, catalogue or session files; this does not grant native tool permission. Actual vision interventions, malformed input and incompatible runtimes retain the existing PowerShell checks, including the installed user/project scope. That fallback adds an extra process for image handoffs, so this is an ordinary-read optimization, not a claim that every hook is faster. Source/legacy installations and unsupported launcher paths retain the original PowerShell entry. A durable launcher outside the immutable plugin copy follows same-version Python reconfiguration, and installer failure restores its prior bytes together with runtime selection. An execution failure is never automatically rerun through a second path.

Before operational acceptance, confirm all of the following in the company environment: the HCP model is registered in the model list; the exact `HCP-Vision-Latest` ID is permitted by the gateway and account; and the installed CLI accepts that full custom ID in subagent model frontmatter. These are separate checks. A configured label, a successful mock test, or a worker definition alone proves none of them.

Offline verification on 2026-10-07: 142 targeted tests passed with the production routing flag supplied only to the test process, including 23 new routing/continuation checks, real PowerShell hook-input checks, existing context-budget tests, ordinary worker model preservation, native runtime, skill execution and PPT preparation. No HCP or substitute model was called. Local Claude Code agent-definition validation and standalone manual regeneration/check passed. A broader run in the shared development checkout exposed two separate Workspace documentation/package-contract failures (`test_current_install_entry_points_do_not_send_staff_to_old_releases` and `test_both_bundle_builders_include_every_manual` in `test_handbook_contract.py`). These observations describe that test run; the 1.4.37 release scope excludes separate Workspace application changes. Production image understanding, gateway authorization and actual request-model logs remain unverified. Installer packaging, release publication and operational acceptance are verified separately.

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

An `extend` is safely rebased when the Corporate Base changes. A `fork` whose base hash changed becomes a visible conflict. Neither case deletes the personal file. The source of truth remains Markdown; generated indexes can always be rebuilt. After an automatic rebase, only the rewritten overlay is read back and its content and file signature verified together. Concurrent replacement, deletion or unreadability prevents publishing a new index/cache from that snapshot; the last valid index is retained for a later retry. Unchanged startup sources are not reread by this additional check.

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

## Local preparation decisions and evidence

Skill preparation uses a finite, local decision contract over the verified catalogue. Candidate delivery, observed body loading, business-command results, and output verification remain separate. The existing activity write stores only bounded execution metadata; it grants no permission and never drives Stop retries. No additional model/API or prompt payload is introduced. See [local decision workflow](LOCAL_DECISION_WORKFLOW_2026-09-19.md).
