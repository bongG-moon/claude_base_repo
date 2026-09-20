# Optional MCP contracts

The repository does not implement the company's database and Outlook transports. They are separate development and security deliverables; installing the base Harness neither requires nor configures them. When an approved MCP is ready, its real command can be supplied in `managed-mcp.json`. The Harness then enforces the following outer contracts, and each MCP server must independently enforce the same rules.

If `managed-mcp.json` is absent/empty and the personal registry has no active servers, Company Agent does not pass `--mcp-config` or `--strict-mcp-config`; the user's existing Claude Code MCP sources remain available. A non-empty Harness MCP configuration merges with those existing sources by default. Strict MCP isolation is an explicit administrator decision in versioned `managed.json`, not a base-install default.

## `corp-db-read`

- Authenticate with the current employee's approved database identity; installation of Company Agent must not request or store database credentials.
- Expose read-only metadata and query tools only.
- Keep query tool names within the Harness allowlist (`query`, `select`, `execute_query`, `run_query`, or names composed from those read verbs). A name that also contains a write verb is rejected.
- Put executable SQL in a recognized string field such as `sql`, `query`, `statement`, `query_text`, `sql_text`, or `command`. Unknown fields containing SQL-shaped text and unknown operations are rejected.
- Accept only one `SELECT`, `WITH ... SELECT`, or `EXPLAIN SELECT` statement.
- Reject DML, DDL, stored procedure execution, multi-statements, transaction controls, writable temporary operations, malformed quotes/comments, and SQL Server `SELECT ... INTO`.
- Use a database principal that physically lacks write permission. Hook validation is defense in depth, not the security boundary.
- Bound row count, duration, and result size.

## `corp-outlook-self`

- Bind the connection to the current employee's mailbox through the separately deployed MCP's user-context onboarding. Base Harness installation must not request Outlook identity or credentials.
- Every send/reply/forward/resend call must expose either the sender identity or a top-level `authenticatedAccount*` identity that the MCP server injects immutably. Ignore or reject any override that differs from the onboarded `user_email`; never let the model supply a field that is presented as immutable authentication evidence.
- Permit recipients according to company mail policy; the Harness requirement here constrains the sender, not recipients.
- Read/search operations may run automatically. Non-send mutations and unknown Outlook operations require a user confirmation instead of being auto-approved.
- Return a confirmation preview before any send if the managed MCP itself is configured to require it.
- Record only the minimum operational receipt required by existing company policy; the Harness stores no message body.

## Business pilot in 1.2.0

The bundled Outlook helper is a separate, read-only local pilot, not an implementation or automatic registration of `corp-outlook-self`. It attaches only to an already-running Classic Outlook session. Selecting an account and matching its delivery store is profile mapping, not proof of corporate identity or DRM permission. Reading a body requires the trusted native confirmation dialog; a model-supplied JSON approval flag is ignored. Attachments are metadata-only. Sending, moving messages, creating PST files and mailbox cleanup remain capabilities of a separately implemented, authorized corporate MCP.

Corporate adapters should return structured per-item errors such as `protection_blocked`, `protection_unknown` or `permission_denied`, with sanitized operational messages. Do not return protected plaintext with the error. Distinguish the readable mail body from an unreadable attachment; return partial results for authorized items only. The Harness adds guidance to exclude restricted sources, disclose omissions and stop that subtask without decryption, capture, OCR, application switching or disabling security. It conservatively suppresses free-text automatic learning in that session. This is not universal DRM detection, an OS sandbox or control of Claude's own transcript retention.

## Personal MCP validation

Asset Factory로 만든 개인 MCP는 `candidate` 상태에서 시작합니다. 새 도구는 회사 표준 `platform-tools-v1` 형식의 `src/mcp/tools.py`와 로컬 stdio 어댑터를 사용합니다. `register_tools(mcp: FastMCP) -> None`에서 도구를 등록하며, 로컬 시험 통과가 전사 서버 배포나 권한 부여를 뜻하지는 않습니다. 기존 legacy 형식을 자동 변환하지 않습니다.

활성화 전에는 다음을 확인합니다.

- 자산 이름·소스·진입점·Python 명령과 인자가 허용된 개인 자산 범위에 있는지 확인합니다.
- 정적 코드 검사에서 미검토 기능과 지원하지 않는 동적·셸·네이티브·파괴적 동작을 확인합니다.
- 승인된 오프라인 Python 환경의 SDK 범위를 확인합니다. 표준 형식은 `mcp>=1.28,<2`, 기존 legacy 형식은 `mcp>=1.20,<2`입니다. 하네스가 인터넷에서 설치하지 않습니다.
- 실제 stdio 연결에서 `initialize`, `tools/list`, 인자 없는 `health`를 제한 시간 안에 실행합니다.
- 표준 형식은 가상 입력의 `tool_tests`도 실행합니다. 실제 업무 도구마다 성공 사례가 필요하며 필수 입력이 있는 도구에는 잘못된 입력 사례도 필요합니다. `health` 성공만으로 업무 도구 검증을 대신하지 않습니다.
- 현재 자산 내용 해시에 연결된 서명된 검증 기록을 발급하고, 활성화할 때 다시 확인합니다. MCP 연결 설정은 시작 시 읽으므로 새 MCP 적용 후에는 연결을 다시 시작합니다.

### JSON 조건의 지원 범위

Script Tool의 입력·출력 조건과 표준 MCP의 `expect.json_schema`는 JSON Schema 전체 규격이 아닌 작은 부분집합을 지원합니다.

- 지원 키: `type`, `required`, `properties`, `items`, `minimum`, `maximum`, `enum`, `additionalProperties`, `title`, `description`.
- `type`은 JSON 기본 자료형 이름 또는 중복 없는 목록입니다. `properties`와 `items`의 중첩 조건도 검사합니다. `additionalProperties`는 boolean만 받으며 추가 속성의 스키마는 지원하지 않습니다.
- 숫자 범위·열거값·필수 키·추가 속성 제한을 실제로 검사합니다. `true`와 숫자 `1`은 다르고, 수치상 같은 `1`과 `1.0`은 같습니다. `NaN`·`Infinity`는 거절합니다.
- 알 수 없는 키(`$ref`, `anyOf`, `pattern` 등)나 잘못된 정의를 무시하고 성공 처리하지 않습니다. 스키마는 깊이 32·노드 1,024개, JSON 값은 깊이 64, `enum`은 1~128개로 제한합니다.

Script Tool은 입력 조건 위반을 실행 전에 거절하고, 출력 조건 위반은 검증 기록 발급 전에 실패합니다. 표준 MCP에서는 `tools.py`와 MCP SDK가 실제 입력 검증을 담당하며, 업무 시험은 잘못된 입력의 오류 반환과 출력 기대값을 확인합니다. 이 부분집합 검사는 MCP의 모든 입력 스키마를 대신하는 공통 실행 차단기가 아닙니다. 표준 MCP의 시험 기대값은 `text`, 정확한 `json`, `json_schema` 중 하나를 사용합니다. 시험은 민감 자료가 아닌 가상 자료로 작성합니다.

### 기존 검증 기록의 재사용

표준 MCP 시험에 `expect.json` 또는 `expect.json_schema`가 있으면 현재 검사 기준(`schemaValidationVersion: 1`)으로 다시 시험해야 합니다. 과거에는 정확한 JSON 비교에서도 boolean과 숫자가 같다고 처리될 수 있었기 때문입니다. text-only 표준 MCP의 기존 기록은 다른 서명·내용 일치·업무 시험 조건을 만족하면 유지됩니다.

Script Tool도 현재 기준의 기록이 있어야 활성화하거나 관리 실행할 수 있습니다. 업데이트가 도구를 자동 실행해 재시험하지는 않습니다. 원본·기존 등록을 지우지 않고 재시험을 안내하며, 이미 독립적으로 등록된 Claude native MCP를 강제로 해제하지 않습니다. Python 경로 변경과 상태 보존 절차는 [상태 보존 안내](STATE_PRESERVATION.md)를 참고하세요.

개인 MCP는 현재 Windows 사용자의 권한으로 실행됩니다. 정적 검사·서명된 기록·프로토콜 시험·시간 제한은 안전 점검이지 OS 샌드박스가 아닙니다. 네트워크·외부 라이브러리 등 기능은 manifest에 명시하고 해당 업무 범위에서 검토해야 합니다.
