---
name: personal-knowledge
description: 공통 기억인 회사 용어·계산식·테이블·연결 규칙·지표·업무 기준을 조회하고, 내 기억의 업무 지식을 기록·검색·보완합니다. 공통 원본은 유지하며 개인 적용 기준을 구분합니다.
---

# Personal Knowledge writer

사용자에게 Corporate Base는 ‘공통 기억’, Personal Knowledge는 ‘내 기억의 업무 지식’으로 안내합니다. 회사 정책·공통 절차는 ‘공통 하네스’이며 참고 지식과 다릅니다. 개인 저장·로컬 검토용 내보내기를 공통 반영이나 실시간 공유로 설명하지 마세요.

Personal Knowledge uses the selected private resource root plus `knowledge`. The administrator's Corporate Base remains immutable. 화면에서는 회사 공통 / 개인 전체 / 이 프로젝트 안의 ‘기억·지식’으로 구분합니다.

새 지식 저장 범위가 미지정이면 AskUserQuestion으로 **개인 전체(여러 프로젝트)** / **이 프로젝트(현재 작업에서만)**를 한 번 묻고 답변을 기다립니다. 질문 도구가 없으면 일반 질문 후 멈춥니다. 회사 공통 저장은 선택지에 넣지 않습니다. 명시한 범위는 다시 묻지 않고 기존 항목은 원래 범위에서 수정합니다. 생성·수정·내보내기 명령에 `--storage-scope personal|project --project-root "<company_agent_runtime.project>"`를 붙이고 runtime.stateRoot는 그대로 둡니다. 범위 없는 조회는 현재 프로젝트와 개인 전체만 확인하며 다른 프로젝트를 검색하지 않습니다.

When authoring or reconciling terminology, table meanings or business definitions, read `references/term-quality.md`. Ordinary lookup does not load this authoring reference.

Use the exact `company_agent_runtime.cliCommand` prefix and `stateRoot` for the argument examples below. Write the compact spec with Write under `<stateRoot>/tmp/knowledge-<unique-id>.json`; never guess a bare command, global state directory, or shell redirection. If runtime context is missing, resolve the installed runtime before writing.

## Decide what to store

- A durable business fact, term, table meaning, join rule, metric, or query convention becomes Personal Knowledge.
- A reusable multi-step procedure becomes a Skill; use the Asset Factory instead.
- A tone or interaction preference becomes Personal Memory, not business knowledge.
- A one-off value, query result, email body, credential, or personal/sensitive row must not be stored.

An explicit durable request such as “기억해” or “등록해” can save a validated extracted fact after scope selection. A correction alone is not permission to retain a company fact: use it in the current task and ask if durable storage is unclear. Do not guess the destination from a file's location.

## Write safely

1. Search the effective index and relevant Corporate Markdown first.
2. Choose one mode:
   - `extend`: add aliases, examples, filters, or cautions without replacing the corporate fact.
   - `fork`: intentionally use a different personal rule; preserve and label the corporate rule.
   - `personal-new`: create a fact not present in the Corporate Base.
3. Create a compact JSON spec. Store only the extracted fact and a short reason; never include the transcript.
4. Run:

   `company-agent knowledge upsert --spec "<spec.json>"`

5. Read back the generated Markdown and report its title and mode in plain language.

Only documents and overlays with `status: active` enter the effective catalog. `draft`, `deprecated`, and `example` content remains available for authoring or history but is never used at runtime. Active overlay aliases, tags, table/schema/column metadata, and body terms are searchable together with the Corporate Base.

Example spec:

```json
{
  "title": "WIP_HISTORY 개인 조회 기준",
  "mode": "extend",
  "extends": "table.mes.wip_history",
  "body": "# 개인 적용 기준\n\n라인 A 분석에서는 TEST 이벤트도 제외한다.",
  "reason": "사용자가 향후 조회 기준으로 명시",
  "source": "explicit_user_feedback"
}
```

If a Corporate update conflicts with a personal `fork`, do not silently choose. Present: combine both, use corporate, or keep personal. Security restrictions are never a valid fork target.

If a Corporate item is removed or deprecated, its active Personal Overlay becomes detached. Report it for reconciliation and exclude it from runtime lookup; a detached overlay alone must not prevent rebuilding the rest of the valid catalog. An `extend` may auto-rebase only when the Corporate item's kind and kind-required structural frontmatter are unchanged. Otherwise treat it as a conflict requiring review.
