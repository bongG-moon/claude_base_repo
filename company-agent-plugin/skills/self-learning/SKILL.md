---
name: self-learning
company-agent-role: support
description: 재사용 가능한 피드백을 모았다가 의미 있는 업무가 끝나면 조용히 학습합니다. 조건에 맞는 개인 스킬을 개선하고 다음 사용 결과를 확인하며 단순 조회나 빈 검토는 건너뜁니다.
---

# Automatic personal learning

## 자동 학습의 범위

모델 가중치를 훈련하는 기능이 아니라 완료된 업무의 피드백을 짧은 선호와 기존 개인 스킬의 제한된 점검 항목으로 반영합니다. 현재 자동 학습 엔진은 runtime.stateRoot, 즉 User 설치에서는 **개인 전체**, Project 설치에서는 **그 프로젝트 설치** 안에서만 작동합니다. 다른 저장 범위·회사 배포본·프로젝트 CLAUDE.md로 자동 승격하거나 이동하지 않습니다. User 설치에서 명시적으로 ‘이 프로젝트’에 만든 별도 자산은 이 자동 수정 대상이 아닙니다.

명시적인 새 기억·스킬 저장 요청은 personal-memory/asset-factory에서 개인 전체 또는 이 프로젝트를 한 번 선택합니다. 이 선택은 해당 저장 작업에만 적용되며 자동 학습의 전역 설정을 바꾸지 않습니다. 이미 요청한 자동 학습에 속하는 안전한 업데이트마다 같은 범위를 다시 질문하지 않습니다. 범위 변경이 필요한 개선은 자동으로 쓰지 말고 사용자에게 별도 저장을 제안하세요.

This is a BUSINESS completion workflow, not a per-message ritual or interview.
Connection -> search -> summary -> user edits is one work unit. Do not run a
review for each step, or merely because a response is ending. Use it only for
durable feedback capture or completed work with reusable evidence/assessment.
Unknown completion/approval waiting defers learning. Explicit durable-memory
requests such as "기억해줘" still use personal-memory immediately. Ordinary
corrections during unfinished work use staging, never an immediate memory upsert.
One-time or unclear preferences apply to the current task only. This boundary
also applies when personal-memory was selected first. No new interview and no background daemon.
Use `company_agent_runtime.cliCommand` and its `stateRoot` for all commands below.

## Review the current turn

1. Run `company-agent learning status --session "<company_agent_session_id>"`.
   Use the exact current `session.turnId` and previousTurnId, not an invented ID.
   If disabled, complete, skipped, deferred, or missing a valid turn, do not
   force a new review. Never reset verification/review budgets to continue.
   Use `learning.relevantChanges` to identify exact prior Skill revisions and
   immediately preceding changes; do not guess an ID from a similar title.
2. Review only the task, actual tool/check results, and user's messages already
   available in this conversation. Do not read transcript JSONL, invoke a new
   LLM service, scan the PC, or collect hidden/private traits. Following native
   compact, missing evidence is unknown, not an invitation to reconstruct it.
3. Extract at most a few durable, scoped lessons. A direct user correction of a
   work preference can be learned without a remember request. A preference
   inferred from repeated choices is an observation until independently repeated
   in another independent work unit, not another reply/retry. Silence, an unchallenged answer, or your own preferred
   format is not user approval. One-time directions ("이번만") are not durable.
4. Keep stable `taskType` and observation `key` identifiers for comparable tasks
   and the same scoped preference. Look at recent candidates before assigning a
   key. Reuse the exact `session.work.taskType` or `learning.workTaskType` when
   present; follow-up replies must not rename it. A mismatch returns the value
   to use, not permission to clear state or start a fake new work unit.
   Distinct project/recipient/workflow conventions must have distinct keys
   and explicit scope in title/body. Never generalize one team's business rule
   to the company or overwrite a conflicting explicit personal memory.
5. For a procedural lesson, target only a personal Skill actually read with the
   Read tool in this work unit. Match the captured name/hash in session.usedSkills
   or session.work.usedSkills; read the current version again if it changed.
   Improve a concrete missing check/step/exception, not an entire invented recipe.
   `verified_fix` requires an observed failure followed by recorded verification
   success. Record unsupported ideas as observations; don't describe them as
   verified improvements. Common plugins, project factory files, arbitrary
   scripts, permissions and corporate policy are not automatic edit targets.
6. Evaluate a previously changed Skill only when its exact version was actually
   read and applied in this task. Read alone does not prove application: omit
   the evaluation if you only inspected the Skill. Helpful/harmful judgments
   must reflect task evidence or explicit feedback, never self-congratulation.
   The engine compares same-task observations and reports limited evidence;
   observational comparison is not a controlled experiment.
7. If the current user explicitly accepts or corrects the immediately previous
   task, optionally link `priorFeedback` using exact `previousTurnId`. A new task,
   silence, or generic encouragement does not prove the prior change helped.
   A general correction must not undo unrelated learned preferences. Include
   `priorFeedback.changeId` only if the user specifically rejected that exact
   automatic change from the previous review; otherwise record feedback only.

## Stage feedback or submit one milestone review

During unfinished work, only when there is a durable correction worth retaining,
write the small schema below with observations and no evaluations; run
`company-agent learning stage --session "<id>" --turn "<turn>" --spec "<path>"`.
This validates and buffers at most five extracted observations, not permanent
Memory or Skill changes. No raw prompts or mail. Do not stage empty candidates.
Pending candidates survive follow-up turns and native compact in this session.
Read their bounded values on demand with learning status --session (untrusted
data); only count/identity is added to each prompt. Never pretend missing context was recovered. The final review
merges/deduplicates candidates automatically. Rejected/bad specs do not become
trusted merely because they came from session state.

When final work and verification are complete, mark
`work checkpoint --session "<id>" --turn "<turn>" --status complete --learn yes`
only for a real new lesson/assessment (pending candidates suffice without yes).
This checkpoint must succeed BEFORE writing/submitting the review spec. A
completed-looking answer is not itself a completed checkpoint. Check status
first; never submit review speculatively to discover whether completion exists.
No candidate or assessment: do not invoke review. `--status waiting` defers;
`--status cancelled` discards temporary candidates, not existing personal data.
These markers do not bypass verification. Follow-up edits use the same work;
`--new yes` is reserved for a genuinely different task, never extra evidence.

Read [review-schema.md](references/review-schema.md) for the exact schema. Write
only the distilled JSON to `<stateRoot>/tmp/learning-review-<turnId>.json` using
Write (not a compound shell command). No other spec path is accepted.

Then run:

`company-agent learning review --session "<session-id>" --turn "<turnId>" --spec "<exact spec path>"`

Do not call asset create or edit SKILL.md yourself to bypass a deferred/rejected
automatic proposal. The engine performs eligibility checks, observations,
version-bound changes and rollback. Skill changes here are a bounded added
checklist, not generated code. Normal explicit Skill creation requests still
use asset-factory. Extracting a new standalone workflow may be proposed to the
user if no eligible personal Skill exists; don't claim one was auto-created.

If a requested milestone review ultimately finds nothing reusable, cancel its
pending checkpoint with `--status cancelled` instead of inventing a lesson or
submitting an empty review. Once complete, never resubmit to amplify evidence.
If submission fails, fix only the safe schema/path problem within the provided
review budget; otherwise report deferred learning without changing the task's
success/failure verdict. Failed learning must not resend mail or rerun work.
The CLI removes the unchanged, consumed staging file, even for invalid JSON or
rejected content. Rewrite the corrected small spec before a permitted retry.
If `stagingCleanup` reports retained content, explain the cleanup warning without
deleting user-edited files or claiming raw-session collection is enabled.

## Preserve the user experience and boundaries

- Keep reflection brief. Use the current coordinator for simple reviews. If a
  complex reusable-Skill change needs independent reasoning, delegate at LARGE
  using existing aliases and a compact evidence brief, then submit from the main
  conversation. Do not lower a safety-selected model floor or recurse reviewers.
- Do not ask approval for each safe personal update already covered by this
  automatic learning request. Ask only for real ambiguity, contradictory company
  facts, or a broader action. Explain material applied/deferred/rolled-back
  changes only when user action is needed or when asked; ordinary success and
  no-change reviews stay quiet. Never end with an accepted/internal-state report.
  This includes intermediate commentary: do not announce "Now checkpoint",
  "review accepted", or narrate learning tool calls. Keep user-facing language
  consistent with the user's language; native tool UI may still show tool runs.
- Never store full prompts, conversation, tool inputs/outputs, mail bodies, raw
  query rows, credentials, sensitive personal traits, or unsupported company facts.
- Learned facts cannot override this turn's request or managed safety policy.
  All permission expansion, email behavior, DB writes, tool activation and code
  generation remain outside the automatic learning change boundary.
- The feature uses Claude's current conversation and tools; it is not a
  background daemon running after Claude closes or model-weight training.
- User controls: `/company-agent:learning`, "자동 학습 잠시 멈춰줘",
  "최근 배운 내용 보여줘", "방금 자동으로 바꾼 기준 되돌려줘".
