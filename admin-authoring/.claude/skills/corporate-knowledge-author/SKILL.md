---
name: corporate-knowledge-author
description: Help an authorized administrator create or revise Corporate Knowledge Markdown from natural language, DDL, SELECT queries, column lists, or existing documents. Use only in the writable corporate knowledge authoring repository.
---

# Corporate Knowledge authoring

Work only in the current authoring repository. Never write directly to a deployed `C:\ProgramData\CompanyAgent\knowledge\versions\...` directory.

1. Identify the requested kind: term, table, join, metric, or business rule.
2. Copy the matching template and extract technical fields from the supplied material.
3. Ask only for missing business semantics that cannot be inferred safely:
   - table row grain and unique key;
   - mandatory filters;
   - join cardinality and row multiplication risk;
   - business meaning and exceptions;
   - owner and review date.
4. Never copy credentials, connection strings, actual personal data, or production rows. Replace examples with synthetic values.
5. SQL examples must be SELECT-only.
6. Run the Company Agent knowledge validator, update the generated index, and show the administrator the diff.
7. Do not mark a draft active unless required fields and references validate.

Offer simple choices rather than asking the administrator to understand YAML or Markdown syntax.
