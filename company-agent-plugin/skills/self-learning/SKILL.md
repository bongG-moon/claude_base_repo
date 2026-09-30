---
name: self-learning
company-agent-role: support
description: 지속적인 명시적 교정·독립된 반복 선택·검증된 개인 절차 개선만 조용히 학습합니다. 후보·실제 적용·보류를 구분하며 학습만으로 업무를 재개하지 않습니다.
---

# Personal learning

모델을 훈련하지 않습니다. 재사용할 교정만 개인 선호나 기존 개인 스킬의 작은 점검 항목으로 반영합니다.
현재 자동 범위는 `runtime.stateRoot`입니다. User 설치는 개인 전체, Project 설치는 해당 설치 저장소이며,
회사 배포본·프로젝트 CLAUDE.md·User 설치의 별도 프로젝트 자산으로 자동 승격하거나 이동하지 않습니다.
명시적인 새 기억·스킬 저장은 personal-memory/asset-factory의 범위 선택을 따릅니다.
그 선택은 자동 학습 설정을 바꾸지 않습니다. 이미 허용한 안전한 자동 업데이트마다 다시 승인받지 마세요.

## Learn only when there is evidence

- A durable explicit correction may be submitted while work is active; it does not require task completion.
  Do not infer durability from a one-time choice, quoted text, silence, or an ambiguous correction.
  “이번만” and unclear directions apply only to the current task, not long-term Memory.
- A repeated choice needs independent work units with completion or actual current-turn verification,
  not retries or extra turns of the same work.
- A reusable procedural fix needs an existing personal Skill's full-load evidence, the exact observed
  version, outcome success and actual relevant verification pass for the current turn/latest change.
  A verified_fix also needs an observed failure and successful fix.
  Capture is not application; missing evidence leaves a candidate deferred, never a fabricated pass.
- Assess a prior improvement only after observing its actual next use at that exact version.
  Reading a file or providing it to the model is not proof it was applied or helped.
- Skip ordinary answers, lookups and empty reviews. No every-turn review, separate model service,
  learning-only Stop continuation, forced worker, or background scan of a closed conversation.

## Submit once using the current context

Use exact injected `company_agent_runtime.cliCommand`, `stateRoot`, `company_agent_session_id`
and the current `company_agent_learning.turnId`. They are JSON values, not environment variables.
Replace the `company-agent` prefix below with the full already-quoted cliCommand.
Missing exact context: defer learning and continue the business result. Never search settings, hooks,
session folders, env or transcripts, invent IDs, change roots, or run discovery commands.

1. Read [review-schema.md](references/review-schema.md) only when eligible evidence exists.
   Use only evidence already in the current conversation. After compaction, missing evidence is unknown.
2. Distill the smallest scoped lesson using the existing schema. Reuse stable taskType/key for the
   same fact; preserve the latest explicit correction without creating contradictory active entries.
   For skill/evaluation details, use the captured exact name/hash; never guess or hash a different version.
3. Use Write once at `<stateRoot>/tmp/learning-review-<turnId>.json`.
   Do not write a shell payload, workspace spec, raw prompt, tool output, business row or credential.
4. Run exactly one normal submission:
   `company-agent learning submit --session "<session-id>" --turn "<turnId>" --spec "<exact spec path>"`.
   No status/stage/checkpoint prerequisite. The engine owns eligibility, deduplication and history;
   submitting never declares the business work complete or clears unfinished verification.
5. Use the returned result; do not repeat status, submit, or the business action for reassurance.
   A safe schema/path correction may use the remaining retry budget, never an unchanged denied retry.
   Accepted/duplicate/disabled/deferred submissions need no additional review command or retry ritual.

## Interpret the result, preserve the user's work

- Submission accepted is a receipt, not “everything learned”. Only active changes mean actual application;
  observing candidates or deferred changes remain unapplied. No submission is not “submitted with no lesson”.
  A valid no_candidates receipt records no lesson; do not create a preference to fill an empty report.
- A remembered item supplied to a later model is only provided-to-model evidence, not observed application.
  Preserve that distinction in requested status reports and do not promise measured improvement.
- The engine may defer version/manual-edit conflicts, insufficient evidence, protected scope or capacity.
  Do not bypass deferral by memory upsert, editing a Skill directly, changing task names or creating fake work.
- Submission consumes only the unchanged canonical spec; report retained-file warnings only when useful.
  Never rerun a completed deliverable or external action because a learning record was missing.
- Waiting for approval/worker, failed or incomplete checks and exhausted correction budgets are not
  reasons to keep a Stop loop running. Keep pending evidence; return the result and its real limitation.
- Preserve source privacy: no raw mail, transcripts, DB rows, authentication, hidden personal traits,
  company facts guessed by the model, or copied source documents in specs or learning history.
- Never change settings, authorization, company policy, executable code, tool activation or common Skills.
  A new Skill or copy needs a separate user request/proposal acceptance through asset-factory.
- Keep successful internal bookkeeping quiet and user-facing questions/results in Korean.
  Do not replace the requested deliverable with a learning-status narrative.

## User controls

`/company-agent:learning` supports status, pause/resume and rollback of an identified automatic change.
Status is on demand, not an automatic prerequisite. Pause preserves existing Memory/Skills and their use.
Rollback preserves manual edits and does not undo business files, mail, DB writes or other plugins.
For prior-feedback links, version receipts and checklist-update limits, use the schema reference.
