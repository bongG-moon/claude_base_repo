# Corporate Knowledge administrator guide

## Authoring

Open Claude Code from the writable authoring repository, not from the deployed ProgramData directory. The `corporate-knowledge-author` Skill accepts natural language, DDL, a SELECT query, a column list, or an existing Markdown document.

Recommended prompts:

```text
MES의 WIP_HISTORY 테이블을 등록해줘. 이 DDL에서 기술 정보를 읽고
내가 확인해야 할 업무 의미만 쉬운 선택지로 물어봐.
```

```text
LOT_MASTER와 WIP_HISTORY 조인 방법을 추가해줘.
조인 후 행이 늘어날 수 있는지도 반드시 확인해줘.
```

The Agent copies a template, asks for missing grain/key/filter/cardinality/owner information, and runs validation. Administrators should review the Markdown diff before publishing.

## Validate

```powershell
python .\company-agent-plugin\scripts\harness_cli.py knowledge validate `
  --base .\corporate-knowledge
```

Validation checks required metadata, unique IDs, references, alias conflicts, credential-like strings, and non-SELECT SQL examples.

## Content release

Increment `corporate-knowledge\pack.json` version, validate, build the offline bundle, then install the new Knowledge version side-by-side. The installer changes the current pointer only after hash and structure checks pass. Existing user overlays remain in LocalAppData.

When an updated Corporate document changes the base hash of a personal overlay:

- `extend` can be safely rebased and remains active;
- `fork` becomes a conflict and the user chooses combine, corporate, or personal when the distinction matters;
- missing targets become detached but are not deleted.

## Content rules

- Use stable IDs such as `table.mes.wip_history`; do not encode a release version in the ID.
- Record the table grain, key, mandatory filters, join cardinality, and row multiplication risk.
- Store a managed database profile name, never a password or connection string.
- Use synthetic or masked examples, never production personal data.
- Keep executable instructions out of knowledge documents. They are facts and references, not prompts.
