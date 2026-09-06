# Project design and spec

Choose the smallest pattern that matches the user's work. The main Claude conversation coordinates standard subagents. A subagent does not spawn another subagent.

| Pattern | Select when | Practical behavior |
| --- | --- | --- |
| `pipeline` | A later step needs the earlier result | Ordered stages with verified handoff |
| `fan-out-fan-in` | Independent views or files can be handled together | Up to three disjoint workers, then merge |
| `expert-pool` | Different request types need different expertise | Invoke only relevant specialists |
| `producer-reviewer` | A deliverable has concrete quality criteria | Produce, independently check, correct |
| `supervisor` | Task assignments depend on intermediate results | Main conversation maintains bounded task queue |
| `hierarchical-delegation` | The problem needs a two-level breakdown | Architect returns a tree; main invokes its leaves |

Default to producer-reviewer for ordinary report/build tasks. A pattern controls coordination; the stage tasks and acceptance criteria provide the domain detail. Do not invent organizational processes, tables, or MCP contracts.

The factory accepts this JSON contract. Unknown fields are rejected to catch misspellings.

```json
{
  "schemaVersion": 1,
  "name": "weekly-report",
  "goal": "프로젝트의 검증된 실적 파일에서 주간 보고서를 작성한다.",
  "pattern": "pipeline",
  "workflow": [
    {"id": "collect", "task": "입력 파일의 기간과 필수 항목을 확인하고 사용 가능한 근거를 정리한다.", "tier": "SMALL"},
    {"id": "summarize", "task": "확인한 근거에서 표와 요약을 작성하고 원본 파일과 숫자를 대조한다.", "tier": "MEDIUM"},
    {"id": "interpret", "task": "검증된 수치의 변동 원인과 아직 확인되지 않은 가설을 구분한다.", "tier": "LARGE"}
  ],
  "successCriteria": [
    "보고서의 각 수치가 원본 파일과 연결된다.",
    "누락된 입력이나 확인되지 않은 해석을 사실로 표현하지 않는다."
  ],
  "knowledgePaths": ["docs/report-rules.md"],
  "maxRetries": 2,
  "conflictStrategy": "preserve"
}
```

- `name` and each stage `id`: lowercase letters/digits/hyphens, start with a letter, at most 20 characters. IDs `architect` and `reviewer` are reserved for generated shared specialists.
- `workflow`: 1–8 objects with `id`, `task`, and optional `tier`; default MEDIUM. Every stage receives its own agent and task Skill.
- `successCriteria`: 1–30 observable checks. Prefer project-specific outputs and contracts over “good quality”.
- `knowledgePaths`: optional existing project-relative files/directories, use `/`. Remove example paths that do not exist. External paths and junctions are rejected; corporate/personal knowledge is resolved through Company Agent at runtime instead of embedded paths.
- `maxRetries`: 0–3 correction attempts per task. Generated orchestration also limits a workflow to 24 total Agent invocations.
- `conflictStrategy`: `preserve` by default; `replace-owned` is only for an explicitly requested regeneration of hand-edited factory-owned content.

Tier mapping uses the already configured `haiku`, `sonnet`, and `opus` aliases. A separate LARGE architect and MEDIUM independent reviewer are always generated. SMALL is appropriate for bounded extraction; complex design or unresolved correction should use LARGE. Do not force all tasks to the same model.

The factory adds `.claude/rules/company-agent-project-harness.md` as an automatically discovered pointer and leaves existing `CLAUDE.md` intact. Its manifest stores the normalized spec and expected SHA-256 values. Owned updates/removals are backed up before writes; unexpected apply failures restore changed files. Files outside its ownership set are not replaced, even with `replace-owned`.

After generation, restart Claude Code in the selected project so custom agent definitions are loaded. The generated assets need no network dependency on the factory. Their correction budget and tool boundaries are instructions interpreted by Claude; they are not an isolated execution engine. Existing corporate MCPs must enforce database and mail restrictions.
