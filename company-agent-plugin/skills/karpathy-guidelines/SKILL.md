---
name: karpathy-guidelines
company-agent-role: support
description: 코드·스크립트·MCP·실행형 스킬을 만들거나 검토할 때 범위를 작게 유지하고 근거로 확인하는 개발 지침입니다. 일반 요약이나 업무 문서 작성에는 별도로 실행하지 않습니다.
license: MIT
---

# Karpathy Guidelines for Company Agent

Use these four principles within the current task. This is supporting guidance,
not a second interview, planning workflow, or approval process. Follow the
existing Company Agent model routing and personal Skill activation behavior.
The user does not need to name this Skill when the task matches its description.

## 1. Think before coding

- Read the relevant project files and reuse facts, choices, and authorization
  already provided by the user.
- State a material assumption briefly. For a routine, reversible implementation
  choice, use the simplest option consistent with the request and continue.
- Ask only when a missing choice materially changes the outcome or is needed
  to perform an action within the user's authority. Ask one short question at a
  time, with a recommendation when useful; do not ask again about settled choices.
- If a simpler approach satisfies the request, explain it briefly and use it.

## 2. Simplicity first

- Implement the smallest change that satisfies the requested result.
- Avoid speculative features, new dependencies, abstractions for one use, and
  configuration the task does not need. Reuse the project's existing tools.
- Keep necessary input validation, error handling, and the company's tool
  permission boundaries. Simplicity is not a reason to bypass them.
- After tracing the relevant flow, prefer existing code, then standard-library or native platform features, then installed dependencies, before new code. Choose the smallest readable solution that meets all explicit requirements, not the fewest lines. Document a deliberate limitation and its measured upgrade condition only when one actually exists.
- Use the installed Windows/offline runtime and project conventions. If a
  necessary dependency is unavailable, identify it rather than downloading
  executable code from the public internet.

## 3. Surgical changes

- Preserve existing user edits, working behavior, comments, and conventions.
  Every changed file must support the user's requested outcome.
- Do not rewrite unrelated code or delete existing unused code merely because
  it was encountered. Remove an orphan introduced by this change only when its
  lack of remaining uses is verified.
- Keep personal Skills, Memory, and Knowledge in the scope's User State, not
  the installed Company Agent plugin. Do not overwrite an existing user Skill
  or append these rules to the user's global or project CLAUDE.md.
- Commit, push, or deploy only within the user's requested scope. This Skill
  does not authorize automatic commits or introduce a new approval gate.
- A request to review or diagnose stays read-only unless it also requests a fix.
- For a reported code/runtime defect, read `references/evidence-diagnosis.md`; do not load it for ordinary feature work or business summaries. It supports the current workflow and retry budget, not another review loop.

## 4. Goal-driven execution

- Define observable success criteria. Reuse the current workflow's plan and
  completion checks instead of starting another one.
- For a behavior change or bug fix, run relevant tests or reproduce the failure
  when feasible, make the change, and check the actual result. For a refactor,
  verify the intended behavior before and after. Do not invent tests for a
  simple text-only change with no behavioral effect.
- For a regression, first confirm the check detects the original defect, then
  confirm it passes after the fix. Do not weaken the expected behavior merely
  to make a test pass. If reproduction is unavailable, state that limitation.
- On failure, use the evidence to make a scoped correction within the existing
  harness retry budget. Do not start an independent unbounded review loop.
- Report what was verified and what remains unverified. A generated test file,
  a model's self-review, or a saved completion record is not evidence that the
  program ran successfully.
- Use results from after the latest relevant change. Inspect the actual exit
  status, failures and skipped checks; an old pass or a worker's claim is not
  current evidence. Passing tests alone does not prove every user requirement.

Source and adaptation details are in [SOURCE.md](SOURCE.md). The preserved
upstream text under `references/` is provenance, not a second active workflow.
