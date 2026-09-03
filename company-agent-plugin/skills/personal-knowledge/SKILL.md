---
name: personal-knowledge
description: Create, update, search, reconcile, or share a user's local company terminology, table knowledge, join rules, metric definitions, examples, and work conventions. Trigger when the user says to remember a business fact or corrects how future work should be done.
---

# Personal Knowledge writer

Personal Knowledge is a writable overlay under `%LOCALAPPDATA%\CompanyAgent\knowledge`. The administrator's Corporate Base remains immutable.

## Decide what to store

- A durable business fact, term, table meaning, join rule, metric, or query convention becomes Personal Knowledge.
- A reusable multi-step procedure becomes a Skill; use the Asset Factory instead.
- A tone or interaction preference becomes Personal Memory, not business knowledge.
- A one-off value, query result, email body, credential, or personal/sensitive row must not be stored.

When the user explicitly says “기억해”, “앞으로”, “등록해”, or corrects a prior answer, save the extracted fact automatically after validation. For an inferred pattern, ask once with simple choices: save personally, use once, or edit.

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
