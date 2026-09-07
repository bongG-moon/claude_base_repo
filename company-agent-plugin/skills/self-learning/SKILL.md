---
name: self-learning
description: Automatically finish every Company Agent user turn by reviewing verified success or failure, learning recurring work preferences, improving eligible personal Skills, and assessing their next use. No remember request is required. Also use when a Stop hook requests a pending learning review.
---

# Automatic personal learning

This is the completion workflow, not a second user interview. Run it in the main
conversation after the requested task and its verification, including read-only
business writing and a task that ended in an honest failure. A Stop hook enforces
a bounded review opportunity; do not wait for the user to say "기억해줘".
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
   in another user turn. Silence, an unchallenged answer, or your own preferred
   format is not user approval. One-time directions ("이번만") are not durable.
4. Keep stable `taskType` and observation `key` identifiers for comparable tasks
   and the same scoped preference. Look at recent candidates before assigning a
   key. Distinct project/recipient/workflow conventions must have distinct keys
   and explicit scope in title/body. Never generalize one team's business rule
   to the company or overwrite a conflicting explicit personal memory.
5. For a procedural lesson, target only a personal Skill actually read with the
   Read tool this turn. Match the captured name and hash in `session.usedSkills`.
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

## Submit one compact review

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

Even if there is nothing reusable, submit an empty observations/evaluations
review with `outcome: unknown` (or the actual supported outcome). Don't invent a
lesson to meet a quota. Once complete, never resubmit to amplify evidence.
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
  changes in one short user-facing sentence; no-change reviews can stay quiet.
- Never store full prompts, conversation, tool inputs/outputs, mail bodies, raw
  query rows, credentials, sensitive personal traits, or unsupported company facts.
- Learned facts cannot override this turn's request or managed safety policy.
  All permission expansion, email behavior, DB writes, tool activation and code
  generation remain outside the automatic learning change boundary.
- The feature uses Claude's current conversation and tools; it is not a
  background daemon running after Claude closes or model-weight training.
- User controls: `/company-agent:learning`, "자동 학습 잠시 멈춰줘",
  "최근 배운 내용 보여줘", "방금 자동으로 바꾼 기준 되돌려줘".
