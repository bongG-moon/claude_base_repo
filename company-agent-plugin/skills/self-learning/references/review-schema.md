# Unified learning submission schema

All fields below are model-reported distilled evidence, not raw conversation.
Never copy this illustrative report as evidence of a real user preference.
Normal learning uses `learning submit --session "<current id>" --turn "<current turn>"`
with `--spec "<stateRoot>/tmp/learning-review-<current turn>.json"` and the exact
injected cliCommand. The schema is unchanged; stage/review/checkpoint are not
prerequisites. Do not perform a status lookup merely to start a submission.

```json
{
  "schemaVersion": 1,
  "taskType": "weekly-report",
  "outcome": "success",
  "summary": "보고서에서 완료와 승인 대기를 구분했고 원문 대조를 수행함",
  "observations": [
    {
      "kind": "preference",
      "key": "team-report-conclusion-first",
      "signal": "explicit_correction",
      "title": "팀 보고의 설명 순서",
      "body": "팀장에게 보고할 때 결정이 필요한 내용을 먼저 설명한다."
    }
  ],
  "evaluations": []
}
```

- `taskType`, observation `key`, and `skillName`: compact stable identifiers,
  lowercase ASCII slugs; reuse existing key for the same scoped fact.
- `outcome`: `success`, `failure`, `partial`, `unknown`. A successful prose answer
  is not a machine-tested result. The engine keeps actual verification separately.
- `summary`: at most 400 characters; abstract outcome without raw materials.
- `observations`: small array, `kind` is `preference` or `skill`, `signal` is
  `explicit_correction`, `repeated_choice` or `verified_fix`.
  `title` at most 120 characters; distilled `body` at most 700 characters.
  A `skill` observation also needs `skillName` from captured usedSkills.
  `verified_fix` is for actual procedural fixes, not personal preferences.
- `evaluations`: small array of `{ "skillName": "<captured name>",
  "sha256": "<captured exact SHA256>", "verdict": "helpful" }`.
  Verdicts: `helpful`, `neutral`, `harmful`, `unknown`. Match observed versions;
  don't hash a different current file after it was edited.
- Optional `priorFeedback`: `{ "turnId": "<exact previousTurnId>",
  "verdict": "accepted" }`, or `corrected`. Only explicit feedback about the
  immediately prior task; never manufacture a prior-turn linkage.
  A correction normally records feedback only. Add optional `changeId` only
  when the user's correction specifically rejects that exact automatic change
  from the previous review. Never undo all changes because an unrelated task
  detail was corrected. Use an exact already-observed ID, or a status result when
  the user actually requests review/rollback; never scan history for a routine submission.
- At most one Skill observation per personal Skill per review; combine the
  single smallest necessary procedural lesson before submitting.
- Do not add unknown fields, transcripts, arbitrary file paths or command text.
  Session/turn IDs are command arguments, not part of this spec.

Repeated-choice observations need evidence from two independent work units, each
explicitly complete or supported by outcome success and actual current-turn verification
pass, before activation. Different replies, retries or user turns within the same work
unit are not independent evidence. A single broad preference inferred by the model is not durable fact.
The engine may defer a valid submission's candidate due to conflicts or insufficient
evidence; an accepted receipt does not imply every proposal was applied.

## Evidence and application boundaries

An explicit durable preference can be accepted during active work without a
business-complete checkpoint. One-time/unclear directions are not long-term facts.
Submission never closes unfinished work or clears a failed check. Use `unknown`
or `partial` when that is all that was observed; never fabricate outcome success.

A procedural observation targets only an existing personal Skill actually fully
loaded in this work unit at the captured hash. Partial Read ranges accumulate only
within the same user turn and unchanged hash; a new turn clears incomplete coverage.
A complete receipt may remain with the work. Failed/partial/another worker's reads
do not prove coordinator full load. Native Skill success must identify the exact body;
body load alone is not proof of application, successful work or a verified fix.
Outcome success and relevant actual verification pass for the current turn/latest
change are required to apply a procedural change, and
`verified_fix` additionally requires observed failure followed by a successful fix.
Do not mark the entire work complete solely to make a procedural candidate eligible.
Insufficient evidence leaves it observing/deferred. A prior failure or unchanged
file from unrelated work is not evidence for the current fix.

Skills requiring native metadata such as context:fork, model, allowed-tools or
dynamic execution need the correct native invocation; Read cannot replace that
execution. No common plugins, project-generator files, executable scripts or policy
are automatic targets. Keep only a bounded checklist lesson, not invented code.
One smallest combined Skill observation avoids claiming all distinct corrections
were retained. The same scoped key replaces its owned item, including A → B → A;
different scopes remain separate. Manual edits, ambiguous legacy items or version
conflicts are deferred rather than overwritten or repaired through direct edits.

Evaluate only actual later use of the exact changed version, with observed behavior
and relevant result. A missing result is unknown, not helpful. This is observational
feedback, not an independent experiment. Do not invent a task/turn or reset work to
multiply evidence. Optional priorFeedback changes only the exactly linked item.

## Reading receipts

Top-level `accepted`, `duplicate`, `disabled` or `deferred` describes submission handling.
`captureStatus` can be `captured`, `no_candidates`, `already_submitted`, `not_captured`
or `deferred`. `no_candidates` is an explicit no-lesson receipt, different from
never submitting. Use `capturedCount`, `appliedCount`,
`deferredCount` and returned changes/evidence together: only an active change is
applied, while observing/deferred is still a candidate. Do not retry accepted or
duplicate submissions just to make every count positive.
An already-active unchanged item has no new application and may have appliedCount zero.
Insufficient evidence can remain in work.pending for a later meaningful submission;
the engine merges it without making the model run stage/checkpoint/status first.

Status is an on-demand user control. With an exact injected current session,
`learning status --session "<id>"` can include currentSubmission and that session's
latest memoryDelivery receipt as separate records. Without a session ID use ordinary
global status; never discover one.
Delivery output-produced/provided-to-model records IDs/revision/scope only, not raw
titles, bodies or queries. It does not prove host receipt or model application;
not-observable must not become “실제 사용됨”. Missing delivery is not evidence that
no Memory exists or that a prior submission never happened.
