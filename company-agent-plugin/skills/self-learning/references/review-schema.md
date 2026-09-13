# Learning review schema

All fields below are model-reported distilled evidence, not raw conversation.
Never copy this illustrative report as evidence of a real user preference.

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
  detail was corrected. Use an exact ID returned by learning status.
- At most one Skill observation per personal Skill per review; combine the
  single smallest necessary procedural lesson before submitting.
- Do not add unknown fields, transcripts, arbitrary file paths or command text.
  Session/turn IDs are command arguments, not part of this spec.

Repeated-choice observations need evidence from independent completed work units
before activation. Different replies, retries or user turns within the same work
unit are not independent evidence. A single broad preference inferred by the model is not durable fact.
The engine may defer a valid review's candidate due to conflicts or insufficient
evidence; review completion does not imply every proposal was applied.
