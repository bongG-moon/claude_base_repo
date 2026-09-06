# 업데이트와 개인 상태 보존 — 0.3.2

## 직원의 업데이트 방법

새 배포 ZIP을 완전히 압축 해제한 뒤 `Install-CompanyAgent.cmd`를 실행한다.
기존과 같은 **Claude 전체 / 프로젝트** 범위를 선택하고, 프로젝트라면 같은 폴더를 지정한다.
완료되면 Claude를 재시작한다. 개인 저장 위치를 처음에 따로 지정했어도 다시 입력할 필요가 없다.
설치 프로그램은 기존 등록의 `userStateRoot`를 재사용한다.

| 상황 | 처리 |
| --- | --- |
| 기본 경로에서 동일 범위 업데이트 | 공통 버전/등록만 갱신, 개인 파일 유지 |
| 기존 사용자 지정 경로, 다음 설치에서 경로 생략 | 기존 등록 경로 재사용 |
| 기존 경로와 다른 `-UserStateRoot` 지정 | 백업/등록/배포 변경 전 중단. 자동 이동하지 않음 |
| 기존 등록이 손상되었거나 상대 경로/공통 영역을 가리킴 | 초기화하지 않고 중단 |
| State 형식 표시/사용자 설정이 지원하지 않는 버전 | 읽기 전용 검사에서 중단. 기존 데이터 유지 |
| User↔Project 변경, 프로젝트 폴더 이동/이름 변경 | 별도 상태. 자동 공유/병합/이관 없음 |

새 release는 `%LOCALAPPDATA%\CompanyAgent-Distribution\marketplace\versions\<CoreVersion>`에 둔다.
개인 상태는 `%LOCALAPPDATA%\CompanyAgent\states\user` 또는 `states\projects\<경로해시>`에 둔다.
등록 정보는 `CompanyAgent\installations`에 있으며 개인 학습자료는 공통 배포물에 넣지 않는다.
회사 Knowledge/config만 변경해도 현재 scoped 패키지는 새로운 CoreVersion이 필요하다.

## 설치 전 선택 백업

백업 폴더는 `%LOCALAPPDATA%\CompanyAgent-Backups\pre-install-<시간>-<ID>`이다.
현재 사용자와 LocalSystem만 접근하며, 작업 중인 원본은 그대로 둔다.

기존 Claude 설정·Skill·Hook·등록 백업 외에 `company-agent\personal-learning` 아래에 다음을 보관한다.

- `memory/items`, `memory/versions`: 추출 기억과 수정 이력
- `knowledge/entries`, `knowledge/overlays`, `knowledge/versions`: 개인 지식과 이력
- `personal-root/.claude/skills`: 개인 Skill 및 지원 파일
- `config/user.json`, 존재하는 `state-format.json`: 마스킹된 설정/형식 정보

이는 **선택한 학습자료 백업**이다. 전체 PC/전체 State를 복구하는 이미지가 아니다.
대화·세션 원문, history, tmp, 캐시, 검색 인덱스, MCP 실행환경과 자격 증명, `.env`, 개인키는 제외한다.
JSON의 secret/token/password 등 민감 필드는 마스킹하므로 복원 시 해당 값은 다시 설정해야 할 수 있다.
Markdown 안의 업무 지식까지 익명화하는 기능은 아니다. 백업을 공유 저장소나 Git에 올리지 않는다.
파일/총용량/개수/깊이 제한을 넘거나 필요한 선택 파일 복사에 실패하면 설치를 진행하지 않는다.
junction/symlink는 따라가지 않는다. 필수 개인 학습자료 안에서 발견되면 부분 백업을 성공으로 처리하지 않고 설치를 중단한다.
일반 선택 백업의 제외 항목은 백업 기록으로 확인한다. 기본 상한은 2만 파일, 합계 1GiB, 단일 파일 64MiB, 깊이 32이다.

## 복구

1. 실행 중인 Claude와 해당 개인 상태를 쓰는 작업을 종료한다.
2. 출력된 백업 폴더의 `backup-manifest.json`에서 원래 저장 위치와 백업 항목을 확인한다.
3. 현재 개인 데이터도 별도로 보존하고, 필요한 파일만 원래 위치로 복원한다. 폴더 전체를 무조건 덮어쓰지 않는다.
4. 마스킹된 설정과 제외된 인증정보/MCP 의존성은 기존 회사 설정 절차로 복구한다.
5. 호환되는 Core로 다시 실행해 Memory 검색과 개인 Skill 사용을 확인한다.

사용자 지정 경로 설치를 **제거**하면 활성 등록도 삭제된다. 제거 전에 등록/백업의 `userStateRoot`를 보관하고,
다시 설치할 때 같은 `-UserStateRoot`를 전달한다. 제거 후 경로 자동 추정은 하지 않는다.
0.3.1 등 이전 설치기로 이미 경로가 끊겼다면 새 설치기가 잃어버린 경로를 추측하지 않는다.
원래 등록 백업을 확인하고, 사용자의 명시적 복구 요청 아래 해당 범위 등록과 원래 경로를 다시 연결한다.

## 형식 호환성과 한계

`company-agent state check --state-root "<개인 경로>"`는 파일을 만들거나 변경하지 않는다.
선택적인 `state-format.json`은 `schemaVersion: 1`, 기존 `config/user.json`은 native 1 / legacy machine 2를 지원한다.
표시 없는 기존 State와 사용자 설정은 호환 대상으로 유지한다. 표시가 있는데 잘못되었거나 미래 버전이면 거절한다.
런타임의 개인 상태 쓰기도 같은 검사를 통과해야 하며, 알 수 없는 세션 schema를 기존 형식으로 덮어쓰지 않는다.
`init-user` 재실행은 기존 사용자 설정의 추가 필드를 보존한다.

일반 데이터 마이그레이션/전체 세션 검사 기능은 아니다. 향후 저장 형식 변경은 명시적인 변환과 검증이 필요하다.
이 보호 장치를 모르는 과거 Core까지 안전하게 역호환된다고 보장하지 않는다. 형식 표시를 지워 검사를 우회하지 않는다.
동시에 실행 중인 업무가 백업 도중 파일을 바꾸면 전체 파일들의 단일 시점 일관성까지 보장하지 않는다.
업데이트 전에 Claude를 닫고 실행하는 것이 권장된다. 새 학습내용을 이전 백업으로 자동 되돌리지 않는다.

## 개인 MCP의 Python 경로가 바뀐 경우

회사에서 별도로 운영하는 `corp-db-read` / `corp-outlook-self`는 이 절차의 대상이 아니다.
Factory로 만든 개인 MCP에는 검증 당시 Python 경로가 기록된다. Core 업데이트로 그 경로가 달라졌을 때
서명된 기존 검증 기록과 실제 소스가 일치하는 MCP만 다음 명령으로 명시적으로 재검증할 수 있다.

```text
company-agent asset rebind-mcp-runtime --name <개인-MCP-이름> --timeout 30
company-agent asset activate-mcp --name <개인-MCP-이름> --receipt <위에서-반환한-경로>
```

현재 승인된 Python에 오프라인 MCP SDK가 있어야 한다. 이전 명령 경로를 임의로 신뢰하거나 인터넷 설치하지 않는다.
probe/서명 확인에 실패하면 기존 자산과 등록을 유지한다. 성공하면 새 검증 기록을 발급하며 다시 활성화해야 한다.
Claude native 등록이 이전 Python을 가리키면 해당 **소유권이 확인된 개인 MCP 하나**의 재등록 안내를 낸다.
이 명령은 기존 native 등록을 자동 삭제·교체하지 않는다. 다른 서버를 삭제하거나 전체 MCP 설정을 초기화하지 않는다.

## 검증 명령

```powershell
python -B -m unittest discover -s tests -q
powershell.exe -NoProfile -File .\deploy\Test-PersonalStateBackup.ps1
powershell.exe -NoProfile -File .\deploy\Test-ScopedInstallSmoke.ps1 -IncludeBundledPython
```

Scoped 검사는 임시 Claude 프로필·프로젝트에서 실제 Plugin CLI를 사용한다.
실제 개인 설치, 사내 모델, 회사 DB, Outlook 계정에 작업을 실행하지 않는다.
