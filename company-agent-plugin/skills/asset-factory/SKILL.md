---
name: asset-factory
description: 자연어 요청으로 개인 스킬·스크립트 도구·MCP를 만들고 수정·검증합니다. 반복 업무를 재사용 가능한 기능으로 구성하며 LARGE 작업자를 활용합니다.
---

# Personal Asset Factory

Turn a user's natural-language automation request into the smallest reusable asset that solves it.

전사 표준 `tools.py` / `register_tools(FastMCP)` 형식이나 회사 플랫폼 제출용 MCP를 요청하면 `company-agent:platform-mcp-builder`를 먼저 적용합니다. 아래의 일반 개인용 stdio MCP 생성·활성화 절차와 다른 용도입니다. 표준이 지정되지 않은 일반 개인 자산은 이 스킬을 유지합니다.

For Skill creation or repair, read `references/authoring.md` before drafting. For a requested interactive setup helper, also read `references/windows-setup.md`. These are supporting references, not additional Skills or workflows; other tasks do not load them.

For each `company-agent` example, use the exact `company_agent_runtime.cliCommand` prefix from the current session and safely quote names and paths as arguments. Use its `stateRoot` and clearly identified absolute project path; do not assume Python or the CLI is on PATH. A request only to inspect, explain, or review permits read-only discovery, not asset creation, activation, or preference writes.

## Select the asset type

- **Knowledge**: a fact, term, table definition, join, metric, or business rule. Use Personal Knowledge, not this factory.
- **Skill**: instructions, a checklist, a prompt workflow, or a procedure Claude can perform with existing tools. Prefer this by default; personal Skills become active immediately.
- **Script Tool**: deterministic local computation or file transformation requiring code. It is created as `candidate` until its tests pass.
- **MCP**: a durable typed interface to another system or capability. Use only when a Skill or script cannot provide the needed boundary. It is created as `candidate` and requires protocol/security validation before activation.

## Build contract

저장 범위가 미지정이면 제작 전에 AskUserQuestion으로 **개인 전체(여러 프로젝트)** / **이 프로젝트(현재 작업에서만)** 중 하나를 물어 답변을 기다립니다. 질문 도구가 없으면 한국어 질문 후 멈춥니다. 회사 공통은 직접 저장 선택지가 아닙니다. 사용자가 명시했다면 다시 묻지 않습니다. 기존 자산 수정은 원래 범위를 유지하고 다른 저장소로 이동·복사하지 않습니다.

아래 asset create/test/activate/sync/run 명령에 `--storage-scope personal|project --project-root "<company_agent_runtime.project>"`를 동일하게 붙입니다. runtime.stateRoot는 설치/세션 경로 그대로 유지합니다. 생성 결과의 실제 경로를 검증하며 대상 저장소를 추측하지 않습니다. 범위 누락 시 `needs_scope_choice`는 생성 전 질문 대기입니다. 회사 원본이나 `~/.claude`를 직접 덮어써 이 선택을 우회하지 않습니다. 별도 Project 설치 없이도 User 설치의 프로젝트 전용 개인 저장소를 사용할 수 있습니다.

1. Consult Effective Knowledge before defining inputs, table meanings, or business rules.
   Search relevant existing Skills and tools for the same capability before creating another asset; a different name does not prove a different purpose. Reuse a compatible selected candidate when it satisfies the request. If the user explicitly requests a separate asset, honor that scope without overwriting the existing one.
2. Ask only for missing material choices, using at most three simple options.
3. Before creating a personal Skill or Script Tool wrapper, run `company-agent skill resolve "<proposed-name>" --project-root "<absolute project>"`. Show any same-name candidates by name and origin, plus the current selection. If discovery is incomplete, explain its warnings rather than claiming no overlaps. The create/activate command's existing asset-name and personal/user Skill collision guards still apply: never overwrite, disable, or rename an existing asset to bypass them. If a requested new name is rejected, clearly propose an alternative such as `company-personal-<name>` and obtain the naming choice before retrying; do not silently rename it. Other same-name sources may coexist. Preserve any explicit priority choice and apply it after creation, when the new candidate ID exists.
4. Define success cases, invalid-input cases, JSON input/output schemas, permission boundaries, and offline dependencies before writing code.
5. List every required risky capability in `reviewed_capabilities`. Supported reviewable capabilities are `filesystem-read`, `filesystem-write`, `network`, `process`, and `third-party-import`. Explain the need in plain language before adding one. Dynamic code, shell execution, native code, and destructive filesystem operations are rejected because this Harness does not provide an OS sandbox.
6. Create a JSON AssetSpec and run:

   `company-agent asset create --spec "<asset-spec.json>"`

7. Validate its structure and static security scan:

   `company-agent asset validate "<asset-path>"`

8. Skills need no manual activation. For a Script Tool, save one representative JSON input under `%COMPANY_AGENT_USER_STATE%\tmp`, then let the Harness execute it with a bounded timeout and validate JSON output against the manifest schema:

   `company-agent asset test-tool --name "<name>" --input "<input.json>" --timeout 30`

   This returns a signed receipt bound to the current manifest and source hash. Resolve the wrapper name again with the same absolute project before activation and show any changed overlaps. Activate using that exact receipt; activation creates a Skill wrapper discoverable by Company Agent. A valid requested creation/activation can proceed without another activation confirmation; an unresolved priority is a separate selection:

   `company-agent asset activate-tool --name "<name>" --receipt "<receipt.json>"`

9. For an MCP, use only the administrator-approved Python environment containing the pinned `mcp>=1.20,<2` SDK. If it is absent, stop and tell the user that the approved offline wheel is required. Never run `pip` against the internet. Run the real stdio initialize, tools/list, and `health` test:

   `company-agent asset test-mcp --name "<name>" --timeout 30`

   Activate only with the receipt returned by that command:

   `company-agent asset activate-mcp --name "<name>" --receipt "<receipt.json>"`

10. Any source, manifest, command, argument, or entrypoint change invalidates the receipt. Re-run the relevant test command rather than editing a receipt.
11. In native User/Project installations, activation also registers the receipt-validated server through Claude's native `mcp add-json` for that scope. Restart Claude afterwards. If registration fails, report that native activation is pending and resolve the stated cause; retry with `company-agent asset sync-mcp --name "<name>"`. Existing/unowned MCP names are never overwritten. In the machine launcher, restart Company Agent to reload its MCP registry. Script Tool and personal Skill changes are available through live contextual retrieval.
12. After Skill creation or Script Tool activation, resolve its name again in the same project. If the user explicitly chose a preferred candidate and scope, use the returned exact candidate ID with `company-agent skill prefer --name "<name>" --candidate "<ID>" --scope project --project-root "<absolute project>"`, or `--scope default` for that choice. Verify project choices with the same project resolve. For defaults, first verify the candidate in `company-agent skill inventory --no-project`, then verify the saved choice with `company-agent skill resolve "<name>" --no-project`; project-only candidates cannot be default choices. Otherwise preserve the existing selection and use `/company-agent:skills` to choose project/default scope only if an overlap needs a missing or stale priority choice. Never edit preference JSON by hand. Read the selected full `SKILL.md` before using it; this preference does not change Claude's native `/name` precedence or intercept third-party installers.

Never write personal assets into the plugin installation directory. That directory is replaced on Core update. Store generated assets under the selected private resource root resolved by the harness. Project-private assets are not shared repository files; sharing requires a separate explicit request and review.

Script Tools and personal MCP servers run with the current Windows user's privileges. Hash receipts, static analysis, schemas, and time/output limits reduce mistakes but are not an OS sandbox. Do not activate code that needs broader access than the user explicitly reviewed.
