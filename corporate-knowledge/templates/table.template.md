---
kind: "table"
id: "table.system.schema_table"
title: "업무 테이블명"
system: "SYSTEM"
database_profile: "managed-read-profile"
schema: "dbo"
table: "TABLE_NAME"
owner: "담당 조직"
status: "draft"
classification: "internal"
grain: "한 행이 의미하는 업무 단위"
primary_key: ["KEY_COLUMN"]
last_reviewed: "YYYY-MM-DD"
---

# 업무 의미

테이블의 업무 목적을 작성합니다.

# 주요 사용 조건

- 반드시 적용할 필터를 작성합니다.

# 주요 컬럼

| 컬럼 | 타입 | 업무 의미 | 필수 | 주의사항 |
|---|---|---|---|---|
| KEY_COLUMN | varchar | 예시 | Y | 실제 값이나 개인정보를 넣지 않습니다. |

# 권장 조회 예시

```sql
SELECT KEY_COLUMN
FROM dbo.TABLE_NAME
WHERE 1 = 0;
```

# 금지 및 주의

- 자격 증명과 실제 민감 데이터 샘플을 기록하지 않습니다.
