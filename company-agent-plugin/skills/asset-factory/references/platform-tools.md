# 회사 표준 도구와 스킬 연결

새 재사용 업무 도구의 기본 경로입니다. 기존 도구가 있으면 연결·재사용부터 확인합니다. 회사 형식은 코드 계약이며 회사 서버에 배포해야만 로컬에서 실행되는 것은 아닙니다.

## 제작과 시험

1. AssetSpec에 `type: "mcp"`, `format: "platform-tools-v1"`, `name`, `description`, `tools_code`, `tool_tests`, `reviewed_capabilities`를 둡니다. `tools_code`는 `register_tools(mcp: FastMCP) -> None` 전체 소스입니다. 함수 설명·타입·입력/출력 한도를 정의합니다. `health`는 로컬 연결 확인용 예약 이름입니다.
2. `asset create`가 선택된 저장소에 업무 파일 `src/mcp/tools.py`, 로컬 stdio 어댑터 `server.py`, 시험용 `config.py`, `tool-tests.json`을 만듭니다. 업무 파일에는 Company Agent 경로·모듈·비밀값을 넣지 않습니다. 전사 설정/API를 추측하지 않습니다.
3. `asset validate "<경로>"` 후 `asset test-mcp --name "<이름>" --timeout 30`을 실행합니다. 승인된 `mcp>=1.28,<2` 환경이 필요합니다. 패키지가 없으면 필요한 환경을 알리고 미검증으로 남깁니다. 자동 설치하지 않습니다.
4. 시험은 실제 stdio initialize → tools/list → health → 명시한 업무 사례를 실행합니다. 각 업무 도구의 정상 사례, 필수 입력이 있는 도구의 잘못된 입력 사례가 필요합니다. health 성공만으로 활성화하지 않습니다. 외부 시스템에 쓰는 사례는 승인된 시험 대상을 사용합니다.
5. 사용자가 연결·사용도 요청했다면 반환된 정확한 영수증으로 `asset activate-mcp --name "<이름>" --receipt "<영수증>"`를 수행합니다. 같은 저장 범위로 Claude 네이티브 MCP에 등록하며 기존 이름을 덮어쓰지 않습니다. 등록 실패만 재시도할 때는 `asset sync-mcp --name "<이름>"`입니다. 소스만 요청했다면 등록하지 않습니다.
6. Claude를 다시 시작한 뒤 현재 세션의 실제 도구 이름·입력 형식으로 호출합니다. stdio는 Claude가 프로세스를 관리하므로 사용자가 별도 HTTP 서버/포트를 관리할 필요가 없습니다. 등록 성공과 세션에서의 호출 성공은 따로 확인합니다.

`tool_tests` 예시(업무 함수 `sum_values`가 JSON 문자열을 반환하는 경우):

```json
[
  {"tool":"sum_values","arguments":{"values":[1,2]},"expect":{"json":{"total":3}}},
  {"tool":"sum_values","arguments":{},"is_error":true}
]
```

`expect`는 `text`, `json`, `json_schema` 중 하나입니다. 명시한 합성 사례만 호출하며 영수증에는 원문 입력·출력을 보관하지 않습니다. 표준 오류 응답 형식을 쓰는 도구는 그 형식도 정상 반환값 기대치로 시험합니다.

`json_schema`는 `type`, `required`, `properties`, `items`, `minimum`, `maximum`, `enum`, `additionalProperties`(true/false), `title`, `description`만 지원합니다. 알 수 없는 조건은 무시하지 않고 오류로 알립니다. 복잡한 조건은 검증 가능한 작은 사례나 정확한 `json` 기대값으로 표현합니다. JSON의 `true`와 숫자 `1`은 다르게 비교하며 NaN/Infinity는 허용하지 않습니다. 이전 JSON 기반 업무시험 영수증에 현재 검증 버전이 없으면 재시험 후 활성화·연결해야 합니다. `text`만 사용하는 기존 영수증은 유지합니다.

## 스킬에서 재사용

- 같은 선택 저장소에서 검증·활성화된 MCP를 연결할 때 스킬 AssetSpec에 `tool_dependencies: [{"server":"<등록 이름>","tools":["sum_values"]}]`를 추가합니다. 없는 이름·미검증 도구는 연결하지 않습니다. 본문은 목적·순서·입력 구성·결과 해석을 설명하고 실행 코드를 복제하지 않습니다.
- 생성기는 검증된 소스/스키마에 의존성을 묶고 첫 사용 안내를 넣습니다. `asset check-skill --name "<스킬>" --state-root "<생성 결과의 저장소>" --project-root "<프로젝트>"`는 서버나 LLM을 시작하지 않는 읽기 전용 검사입니다. 같은 대화에서 변경 없는 검사 결과는 재사용합니다. 도구 변경 시 재시험 후 의존성을 명시적으로 갱신합니다.
- 세션에 도구가 없거나 검사가 실패하면 필요한 연결·수정만 알립니다. 임의 호출명·직접 `tools.py` 실행·다른 파싱 코드로 대체하지 않습니다. 스킬 생성은 외부 쓰기 권한이나 설치 승인이 아닙니다.
- 다른 저장소/외부 MCP도 실제 연결을 확인해 스킬에서 재사용할 수 있습니다. 다만 위 해시 검사는 같은 선택 저장소의 관리 자산만 지원합니다. 외부 도구를 로컬 검증 완료로 표시하거나 중복 등록하지 않습니다.

## 전사 제출이나 독립 HTTP 개발이 필요한 경우만

`../../platform-mcp-builder/references/platform-contract.md`를 읽습니다. 기존 전사 프로젝트는 그 경로와 파일을 유지합니다. 새 독립 개발 폴더에는 `../../platform-mcp-builder/scripts/create_project.py --destination "<새 절대경로>"` 지원 생성기를 쓸 수 있습니다. 관리 저장소 등록과 다른 소스 제작 경로이며 자동 활성화하지 않습니다. 전사 제출은 `tools.py`, 명시한 업무 모듈·추가 의존성·cfg 항목명·입출력 예시·시험 결과만 대상으로 합니다. 개인 경로·로컬 어댑터·영수증·비밀값은 제출하지 않습니다. 실제 회사 플랫폼의 인증/SDK/접근 권한은 별도 확인합니다.
