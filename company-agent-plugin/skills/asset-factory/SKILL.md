---
name: asset-factory
description: 개인 스킬·스크립트·도구(tool)·MCP를 만들고 수정·검증하는 통합 제작 스킬입니다. 새 재사용 업무 도구는 전사 표준 tools.py로 만들며, 로컬 연결과 스킬의 도구 재사용을 함께 확인합니다.
---

# 스킬·도구 만들기

제작 진입점은 이 스킬 하나입니다. **스킬은 업무 순서, 도구는 실행 코드**를 담당합니다. 새 재사용 업무 도구는 회사 표준 `src/mcp/tools.py`의 `register_tools(mcp: FastMCP)`로 작성합니다. 설명·검토만 요청하면 생성·실행·등록하지 않습니다.

## 시작과 범위

- 관련 기존 스킬·도구부터 확인하고 맞는 기능은 재사용합니다. 다른 이름이라는 이유만으로 중복 제작하지 않습니다. 용어·업무 규칙은 유효 지식을 참고합니다.
- 글쓰기·체크리스트처럼 기존 도구로 가능한 작업에는 스킬만 만듭니다. 일회성 작업을 무조건 MCP로 만들지 않습니다. 기존 Script Tool/stdio MCP는 원래 형식으로 유지합니다.
- 저장 범위가 없으면 **개인 전체 / 이 프로젝트** 중 한 번만 묻고 기다립니다. 회사 공통은 개인의 직접 저장 선택지가 아닙니다. 기존 자산은 경로·범위를 유지합니다.
- 새 스킬은 Claude 기본 위치에 한 번만 저장합니다: 개인 전체는 현재 Claude 설정 폴더의 `skills/<이름>/SKILL.md`, 이 프로젝트는 `<프로젝트>/.claude/skills/<이름>/SKILL.md`. 프로젝트 스킬은 폴더 공유 시 함께 전달될 수 있음을 선택할 때 짧게 알립니다. 기억·도구의 비공개 저장 위치는 바꾸지 않습니다.
- 명령은 정확한 `company_agent_runtime.cliCommand`, `stateRoot`, 프로젝트 절대경로를 사용합니다. create/test/activate/sync에 동일한 `--storage-scope personal|project --project-root "<프로젝트>"`를 붙입니다. 생성 결과 경로를 확인하며 플러그인 캐시나 회사 원본에 개인 자산을 쓰지 않습니다.
- 이름·경로는 사용하는 셸에 맞는 리터럴 인수로 전달합니다. `tools_code`는 UTF-8 AssetSpec 파일에 저장하고 긴 코드를 중첩 셸 문자열로 실행하지 않습니다.
- 개인 스킬·기존 Script Tool wrapper를 만들기 전 `skill resolve "<이름>" --project-root "<프로젝트>"`로 충돌을 확인합니다. 실제 역할이 겹치고 우선 선택도 없을 때만 질문합니다. 충돌 회피를 위해 임의로 기존 자산을 덮어쓰거나 이름을 바꾸지 않습니다.
- 기존 스킬은 `asset inspect --name "<이름>" --project-root "<프로젝트>"`로 실제 원본(`effectivePath`)을 확인합니다. 범위를 생략하면 현재 프로젝트와 개인 전체 중 기존 자산 하나의 위치를 유지합니다. 동명이 있을 때만 확인합니다. `bodyIncluded: false`는 본문 로드가 아닙니다.
- 확인한 실제 원본을 읽고 요청한 부분만 고친 본문을 UTF-8 파일로 준비한 뒤 `asset update --name "<이름>" --instructions-file "<본문 파일>" --expected-sha256 "<조회 해시>" --project-root "<프로젝트>"`를 실행합니다. 본문 파일에는 frontmatter를 넣지 않습니다. 이름·범위·참조·연결 도구는 유지하며 설명 변경이 필요할 때만 `--description`을 줍니다. 이미 선택한 범위는 유지하고 사용자에게 AssetSpec 재작성, 스크립트 재생성, 경로 복사를 시키지 않습니다.
- 기존 private 스킬은 자동 이전·복제하지 않습니다. 기존 native 스킬도 같은 위치와 frontmatter를 보존합니다. 프로젝트 조상 폴더·외부 플러그인 등 inspect 범위 밖은 카탈로그의 정확한 원본을 확인하며 새 사본으로 대체하지 않습니다.

## 필요한 절차만 읽기

- 스킬 작성·수정: `references/authoring.md`.
- 크롬 등 웹페이지의 반복 조회를 스킬로 만들기: `references/web-workflow.md`만 먼저 읽습니다. 웹 개발 용어 대신 사이트·가져올 항목·결과로 질문합니다. 단순 웹 조회나 HTML 제작 요청은 이 제작 절차를 시작하지 않습니다.
- 새 도구/MCP 제작·연결 또는 스킬에서 MCP 재사용: `references/platform-tools.md`.
- 전사 제출·HTTP 호환성 확인: `../platform-mcp-builder/references/platform-contract.md`.
- 기존 Script Tool/일반 stdio MCP 유지보수 또는 그 형식을 명시 요청: `references/legacy-assets.md`.
- 사용자가 설치 도우미를 요청한 경우만: `references/windows-setup.md`.

These are conditional references; other tasks do not load them. 현재 대화에서 읽은 변경 없는 내용은 재사용합니다.

## 공통 검증

1. 입력·출력·완료 기준과 정상/잘못된 입력 시험을 먼저 정합니다. 시험에는 합성 자료를 사용하며 외부 쓰기는 승인된 시험 대상에 한정합니다.
2. 필요한 위험 기능을 설명하고 `reviewed_capabilities`에 명시합니다: `filesystem-read`, `filesystem-write`, `network`, `process`, `third-party-import`. 동적 코드·셸 실행·네이티브 코드·파괴적 파일 작업은 기존 제한을 유지합니다. 승인된 오프라인 의존성만 사용하고 인터넷 설치를 자동 실행하지 않습니다.
3. 새 스킬은 AssetSpec으로 `asset create --spec "<파일>"` → `asset validate "<생성 경로>"`를 수행합니다. 기존 관리 스킬 본문은 위 `asset update`로 수정합니다. 스킬에는 MCP 시험·활성화 단계가 없습니다. 응답의 `effectivePath`가 실제 적용 원본이며 작성용 파일이나 AssetSpec 변경은 자동 반영되지 않습니다. 실행 도구는 후보 상태입니다.
4. 도구의 실제 시험을 통과한 소스에만 검증 영수증으로 활성화합니다. 소스·스키마·명령이 바뀌면 재시험합니다. 정적 검사와 영수증은 OS 격리가 아닙니다.
5. **생성 / 시험 / 연결 등록 / 현재 세션 호출 / 전사 배포**를 구분해 보고합니다. 연결되지 않은 도구를 성공했다고 하거나 임의 코드로 대체하지 않습니다. 실제 권한 거절은 그대로 유지합니다.
6. 결과 위치·사용법·실제 검증 범위만 간단히 전달합니다. 새 native 스킬은 `/<이름>`으로 사용하고, 목록에 없으면 원본 Claude에서 `/reload-skills` 또는 새 대화로 확인합니다. 파일 저장은 현재 세션 인식·업무 성공의 증명이 아닙니다. `user-invocable: false` 등 기존 native 조건은 유지합니다. 기존 private 스킬은 “`<이름> 스킬 실행해줘`” 또는 `/company-agent:skills <이름> 실행`을 유지합니다. 전사 공유·배포는 별도입니다.
