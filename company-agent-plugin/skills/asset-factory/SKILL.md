---
name: asset-factory
description: 개인 스킬·스크립트·도구(tool)·MCP를 만들고 수정·검증하는 통합 제작 스킬입니다. 새 재사용 업무 도구는 전사 표준 tools.py로 만들며, 로컬 연결과 스킬의 도구 재사용을 함께 확인합니다.
---

# 스킬과 도구 만들기

**스킬은 업무 순서, 도구는 실행 코드**입니다. 기존 기능을 먼저 재사용하고 설명이나
검토만 요청하면 생성, 실행, 등록하지 않습니다. 일회성 작업을 무조건 MCP로 만들지 않습니다.

## 범위부터 이어가기

- 이미 있는 자산은 실제 원본과 저장 범위를 유지합니다. 실제로 새 자산을 저장할 때 범위가 미정인 경우만
  **개인 전체 / 이 프로젝트** 중 한 번 선택받습니다. 회사 공통은 직접 저장 선택지가 아닙니다.
- 새 스킬은 개인 Claude 설정 폴더의 `skills/<이름>/SKILL.md` 또는
  `<프로젝트>/.claude/skills/<이름>/SKILL.md`에 한 번 저장합니다. 프로젝트 폴더 공유 시
  함께 전달될 수 있음을 짧게 알립니다. 기존 private 스킬은 자동 이전하거나 복제하지 않습니다.
- 명령은 제공된 `company_agent_runtime.cliCommand` **문자열 뒤에** 붙입니다.
  실제 `stateRoot`와 프로젝트 절대경로를 사용하며 설치 경로나 세션 ID를 검색하지 않습니다.
  create/test/activate/sync에는 같은 `--state-root`, `--storage-scope personal|project`,
  `--project-root`를 사용합니다. `asset validate`는 경로만 받습니다.
- 이름과 경로는 셸의 리터럴 인수로, 긴 코드와 본문은 UTF-8 파일로 전달합니다.
  회사 원본이나 플러그인 캐시에 개인 자산을 쓰지 않습니다.

## 해당 흐름 하나로 진행

| 요청 | 실행 흐름과 필요한 자료 |
| --- | --- |
| 새 스킬 | `skill resolve "<이름>" --project-root "<프로젝트>"`로 중복 확인 → [작성과 수정](references/authoring.md)의 AssetSpec → `asset create` → 생성 경로의 `asset validate` |
| 기존 스킬 수정 | `asset inspect --name "<이름>" --project-root "<프로젝트>"` → 반환된 `effectivePath` 읽기 → 같은 원본을 `asset update`로 수정. [작성과 수정](references/authoring.md)의 명령 사용 |
| 새 도구/MCP 또는 스킬의 도구 연결 | [표준 도구](references/platform-tools.md). 새 재사용 도구는 `src/mcp/tools.py`의 `register_tools(mcp: FastMCP)` 형식 |
| 크롬의 반복 업무를 스킬로 만들기 | [웹 업무 관찰](references/web-workflow.md)만 먼저 읽기. 사이트, 필요한 항목, 결과로 질문 |
| 기존 Script Tool/일반 stdio MCP 수정 | [기존 자산](references/legacy-assets.md). 원래 형식을 유지 |
| 전사 제출 또는 설치 도우미 요청 | 각각 [제출 규격](../platform-mcp-builder/references/platform-contract.md), [Windows 설치](references/windows-setup.md)만 읽기 |

같은 역할의 후보가 실제로 겹치고 우선 선택도 없을 때만 묻습니다. 조회 결과의
`bodyIncluded: false`는 스킬 본문을 읽었다는 뜻이 아닙니다. 작성용 사본이 아니라 실제
원본을 고치고 사용자에게 AssetSpec 재작성이나 폴더 복사를 시키지 않습니다.
단순 웹 조회나 HTML 작성에는 웹 스킬 제작 절차를 시작하지 않습니다.

## 확인과 사용

문서형 스킬은 참조 경로, 입력과 완료 기준을 확인합니다. 실행 코드가 있으면 합성 자료로
정상 입력과 잘못된 입력을 시험합니다. 스킬만 만들 때 MCP 시험이나 활성화는 필요 없습니다.
도구의 필요한 위험 기능은 `reviewed_capabilities`에 `filesystem-read`, `filesystem-write`,
`network`, `process`, `third-party-import`로 명시합니다. 동적 코드, 셸, 네이티브 코드와
파괴적 작업의 기존 제한은 유지합니다. 영수증 기반 연결은 해당 참고자료를 따르며
정적 검사나 영수증을 OS 격리라고 하지 않습니다. 소스나 스키마가 바뀌면 재시험합니다. 외부 쓰기는
승인된 시험 범위에 한정하고 자동 인터넷 설치나 추가 Stop 후크를 넣지 않습니다.

생성, 시험, 연결 등록, 현재 대화 호출, 전사 배포를 구분해 실제 확인한 범위만 전달합니다.
새 native 스킬은 `/<이름>`으로 사용하며 목록에 없으면 `/reload-skills` 또는 새 대화에서
확인합니다. 기존 `user-invocable: false`는 유지합니다. 기존 private 스킬은 자연어 호출이나
`/company-agent:skills <이름> 실행`을 유지합니다. 저장 성공만으로 현재 대화 인식을 보증하지 않습니다.
