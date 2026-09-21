# 업데이트와 개인 상태 보존

공통 엔진과 개인 자료를 분리하는 업데이트 원칙을 유지한다. 기존 상태 형식이 지원될 때만 같은 범위의 새 버전으로 업데이트하며, 지원하지 않는 형식은 보존 후 중단한다. 아래는 일반 Company Agent 업데이트와 별도로 요청한 기존 개인 하네스 교체를 구분한 안내다. 이전 `0.3.x`는 배포 전 개발 버전이다.

## 직원의 업데이트 방법

새 배포 ZIP을 완전히 압축 해제한 뒤 `Install-CompanyAgent.cmd`를 실행한다.
기존과 같은 **Claude 전체 / 프로젝트** 범위를 선택하고, 프로젝트라면 같은 폴더를 지정한다.
정상 Company Agent 등록이 있으면 이전/새 버전을 보여 주는 **백업 후 업데이트**를 선택한다. 프로그램과 회사 지식 버전이 모두 같으면 **같은 버전 다시 적용·복구**다. 두 경우 모두 사용자 규칙·Hook과 개인 자료를 유지한다. **현재 버전 유지**는 갱신 없이 종료한다. 다른 하네스만 있는 경우에만 기존 유지/백업 후 교체 화면을 사용한다.
설치 전에 Claude를 닫고, 완료되면 다시 실행한다. 개인 저장 위치를 처음에 따로 지정했어도 다시 입력할 필요가 없다.
설치 프로그램은 기존 등록의 `userStateRoot`를 재사용한다.

| 상황 | 처리 |
| --- | --- |
| 기존 하네스 감지 후 Keep 선택 | 백업·비활성화·설치 없이 종료 |
| 기존 하네스 감지 후 Replace 선택 | 기존 규칙·Hook을 암호화 백업 후 선택 범위에서 비활성화, 개인 상태 유지 |
| 기존 하네스 없음 | 하네스 유지/교체 질문 없이 진행. Skill 이름 겹침이 있으면 별도로 선택 |
| 기본 경로에서 동일 범위 업데이트 | 공통 버전/등록 갱신, 개인 파일 유지 |
| 기존 사용자 지정 경로, 다음 설치에서 경로 생략 | 기존 등록 경로 재사용 |
| 기존 경로와 다른 `-UserStateRoot` 지정 | 백업/등록/배포 변경 전 중단. 자동 이동하지 않음 |
| 기존 등록이 손상되었거나 상대 경로/공통 영역을 가리킴 | 초기화하지 않고 중단 |
| State 형식 표시/사용자 설정이 지원하지 않는 버전 | 읽기 전용 검사에서 중단. 기존 데이터 유지 |
| User↔Project 변경, 프로젝트 폴더 이동/이름 변경 | 별도 상태. 자동 공유/병합/이관 없음 |

새 release는 `%LOCALAPPDATA%\CompanyAgent-Distribution\marketplace\versions\<CoreVersion>`에 둔다.
개인 상태는 `%LOCALAPPDATA%\CompanyAgent\states\user` 또는 `states\projects\<경로해시>`에 둔다.
등록 정보는 `CompanyAgent\installations`에 있으며 개인 학습자료는 공통 배포물에 넣지 않는다.
회사 Knowledge/config만 변경해도 현재 scoped 패키지는 새로운 CoreVersion이 필요하다.

## 무엇이 어디에 저장되나요

아래 경로는 기본값이다. 개인 경로를 따로 지정했다면 설치 결과와 등록의 `userStateRoot`가 기준이다. 경로를 확인하기 위해 자료를 새 기본 폴더로 복사하거나 기존 폴더를 초기화하지 않는다.

| 내용 | 저장 위치와 관리 주체 |
| --- | --- |
| 회사 공통 엔진·스킬·후크·지식·정책 | `CompanyAgent-Distribution/marketplace/versions/<CoreVersion>`의 배포 자료. 관리자가 새 버전으로 전달 |
| User 설치의 개인 전체 자료 | `%LOCALAPPDATA%/CompanyAgent/states/user` 또는 등록된 개인 경로 |
| User 설치에서 명시 선택한 프로젝트 자료 | 위 개인 경로의 `project-scopes/<폴더 해시>` |
| 별도 Project 설치의 개인 자료 | `%LOCALAPPDATA%/CompanyAgent/states/projects/<경로해시>` 또는 그 설치에 등록된 개인 경로 |
| 기억·지식·개인 스킬·도구·MCP | 선택한 개인 저장소의 `memory`, `knowledge`, `personal-root/.claude/skills`, `tools`, `mcp` |
| 설치 기본 설정·학습 설정·스킬 선택·실행 기록 | 활성 설치 저장소의 `config`, `learning`, `sessions` 등. 모두가 선택 백업에 포함되는 것은 아님 |
| Claude 자체 설정·규칙·자동 기억·기존 MCP | 기존 Claude의 저장소. Company Agent 개인 기억과 자동 병합하지 않음 |

User 설치의 `project-scopes`는 요청의 정확한 작업 폴더 경로를 구분한다. 같은 프로젝트의 하위 폴더라도 별도 경로로 열면 같은 프로젝트 자료가 자동 상속된다고 가정하지 않는다. 반면 **별도 Project 설치의 적용 범위**는 등록한 폴더와 하위 폴더다. User의 프로젝트 자료를 별도 Project 설치로 전환하거나 폴더를 옮길 때 자동 이관하지 않는다는 점도 구분한다.

Skill 우선 선택은 같은 개인 상태의 `config/skill-preferences.json`에 둔다.
“기존 선택 유지”로 갱신하면 기본값과 프로젝트별 선택이 유지된다. “새 Company Agent Skill 우선”을
선택한 경우에만 겹친 이름의 선택을 변경하며, 설치 실패 시 그 변경도 복구한다. 버전/캐시 경로가
바뀌어도 회사 Skill의 논리적 이름과 상대 경로가 같으면 기존 선택을 새 파일로 연결한다.
Skill 자체의 이름/구조가 바뀌어 후보를 찾지 못하면 조용히 대체하지 않고 `/company-agent:skills`로
다시 선택하도록 안내한다. 자세한 적용 범위는 [Skill 우선 선택](SKILL_PRIORITY.md)을 참고한다.

## 개인 전체와 프로젝트 기억의 조회

기억을 저장할 때 선택하는 **개인 전체 / 이 프로젝트**는 별도 저장 범위다. 사용자 설치에서 프로젝트 전용 자료는 개인 State의 `project-scopes/<폴더 해시>`에 두고, 별도 Project 설치는 자신의 State를 사용한다. 회사 공통이나 Claude 자체 기억으로 자동 복사·병합하지 않는다.

업무 요청에 기억을 참고할 때는 현재 읽을 수 있는 프로젝트·개인 기억을 **관련도 순으로 함께 정렬**한다. 같은 점수일 때만 프로젝트를 우선하며, 중복을 제거한 뒤 두 범위를 합쳐 최대 5개를 전달한다. 프로젝트 기억이 5개 있다는 이유로 더 관련 있는 개인 기억을 배제하지 않는다. 저장 위치·원문은 그대로이며 검색 점수나 검색어를 새 기억으로 저장하지 않는다.

별도 모델·임베딩·벡터 저장소를 추가하지 않고 기존 파일을 읽어 비교한다. 자료가 많아지면 파일 조회 비용을 별도로 측정해야 한다. 자동 학습의 저장 범위는 현재 활성 설치의 State를 따르며, 특정 기억을 프로젝트에 저장한 선택만으로 이후 모든 자동 학습의 범위가 바뀌지는 않는다.

## 설치 전 선택 백업

백업 폴더는 `%LOCALAPPDATA%\CompanyAgent-Backups\pre-install-<시간>-<ID>`이다.
현재 사용자와 LocalSystem만 접근하며, 작업 중인 원본은 그대로 둔다.
다만 **교체**를 선택하면 안전한 백업 후 기존 규칙·Hook 원본을 선택 범위에서 비활성화한다.

기존 Claude 설정·Skill·Hook·등록 백업 외에 `company-agent\personal-learning` 아래에 다음을 보관한다.

- `memory/items`, `memory/versions`: 추출 기억과 수정 이력
- `knowledge/entries`, `knowledge/overlays`, `knowledge/versions`: 개인 지식과 이력
- `personal-root/.claude/skills`: 개인 Skill 및 지원 파일
- `config/user.json`, 존재하는 `state-format.json`: 마스킹된 설정/형식 정보
- `config/skill-preferences.json`, `config/skill-preferences-history`: Skill 기본값·프로젝트별 선택과 변경 전 이력
- `config/learning.json`, `learning/state.json`: 자동 학습 켜짐/중지, 관찰, 개인 자동 변경 전후 점검 영역, 다음 사용 평가와 복구 기록. 잠금 파일과 임시 제출 파일은 선택하지 않는다.

이는 **선택한 설치 저장소의 일부 학습자료 백업**이다. 전체 PC/전체 State를 복구하는 이미지나 다른 PC로 완전히 이사하는 패키지가 아니다.
현재 선택 목록은 `project-scopes` 전체를 따라가거나 `tools`·`mcp/servers`의 소스 전체 및 자산 검증 기록까지 수집하지 않는다. 대화·세션 원문, history, tmp, 캐시, 검색 인덱스, MCP 실행환경과 자격 증명, `.env`, 개인키도 제외한다.
제외됐다는 것은 일반 업데이트가 해당 원본을 삭제한다는 뜻이 아니다. 원래 저장소에는 남지만 **이 선택 백업만으로 모든 프로젝트 자료·도구·MCP를 재구성할 수는 없다.** PC 교체나 전체 복구가 필요하면 담당자가 원본 경로·추가 백업·의존성·등록을 별도 확인한다.
JSON의 secret/token/password 등 민감 필드는 마스킹하므로 복원 시 해당 값은 다시 설정해야 할 수 있다.
Markdown 안의 업무 지식까지 익명화하는 기능은 아니다. 백업을 공유 저장소나 Git에 올리지 않는다.
파일/총용량/개수/깊이 제한을 넘거나 필요한 선택 파일 복사에 실패하면 설치를 진행하지 않는다.
junction/symlink는 따라가지 않는다. 필수 개인 학습자료 안에서 발견되면 부분 백업을 성공으로 처리하지 않고 설치를 중단한다.
일반 선택 백업의 제외 항목은 백업 기록으로 확인한다. 기본 상한은 2만 파일, 합계 1GiB, 단일 파일 64MiB, 깊이 32이다.

## 기존 하네스의 별도 암호화 백업

‘백업 후 설치’를 선택하고 교체할 기존 파일·Hook이 있으면 같은 백업 폴더의 `previous-harness`에 해당 원본을 추가 보관한다.
일반 선택 백업의 마스킹된 사본과 달리, 원본 전체를 **Windows DPAPI CurrentUser로 암호화**한다.
따라서 기존 settings에 포함된 비밀값도 복구할 수 있지만 평문 자격 증명 파일을 백업 폴더에 복사하지는 않는다.
복구는 백업을 만든 동일 Windows 사용자·PC와 **원래 백업 폴더 경로**에서 수행한다.
백업 폴더를 옮겼다면 설치 때 출력된 원래 위치로 되돌린 뒤 복구한다. PC 교체/계정 이관용 백업으로 사용하지 않는다.
추가 암호화 백업의 한도는 512개 파일, 단일 원본 8MiB, 원본 합계 32MiB이다.
이 한도를 넘거나 스냅샷 작성·검증에 실패하면 기존 규칙·Hook을 비활성화하지 않고 설치를 중단한다.

| 선택 범위 | 비활성화 대상 |
| --- | --- |
| User | 현재 Claude 설정 폴더의 `CLAUDE.md`·`CLAUDE.local.md`, `rules/**/*.md`, `settings.json`의 최상위 `hooks` |
| Project | 선택 프로젝트 루트와 `.claude`의 `CLAUDE.md`·`CLAUDE.local.md`, `.claude/rules/**/*.md`, `.claude/settings.json`과 `.claude/settings.local.json`의 최상위 `hooks` |

설정의 나머지 항목(모델·MCP·env·permissions 등), 개인 Memory/Knowledge/Skill, 일반 Skill과 다른 플러그인은 유지한다.
상위 폴더·다른 범위·별도 플러그인에서 적용되는 규칙/Hook은 비활성화 대상이 아니다. 전체 환경 초기화가 아니다.
기존 Company Agent 등록도 같은 범위의 기존 하네스로 감지한다. 모델·MCP 전용 설정이나 독립 Skill만으로는 감지하지 않는다.

설치 실패 시 비활성화했던 항목을 자동 복구한다. 동시 편집 등으로 원래 위치의 파일이 달라졌으면 강제로 덮어쓰지 않고
복구 충돌과 백업 위치를 안내한다. Claude와 해당 폴더를 수정하는 작업을 닫은 상태에서 설치해야 한다.
파일마다 원본 변경을 다시 확인하지만 여러 파일을 OS 전체에서 한꺼번에 잠그는 원자적 교체·복구는 아니다.
따라서 다른 프로세스가 동시에 파일을 쓰는 상황까지 전체 파일의 단일 시점 일관성을 보장하지 않는다.

## 복구

다음 네 가지를 구분한다.

| 필요한 복구 | 현재 지원 범위 |
| --- | --- |
| 설치 도중 실패 | 설치기가 변경한 등록·선택 및 교체 대상의 복구를 시도. 충돌 시 강제 덮어쓰기 없이 안내 |
| 개인 기억·지식 등 일부 복원 | 아래 선택 백업의 실제 포함 항목을 확인하여 필요한 파일만 복원 |
| 명시적으로 교체했던 기존 하네스로 복귀 | 같은 범위 Company Agent 제거 후 `Restore-PreviousHarness.ps1`로 기존 규칙·Hook 복구 |
| 성공한 User/Project 업데이트의 공통 버전을 하향 | 일반 설치기는 숫자 버전 하향을 차단하며, 현재 이를 한 번에 수행하는 전용 scoped 롤백 명령은 없음 |

`Rollback-CompanyAgent.ps1`는 별도 관리자용 Machine 설치 경로를 위한 도구다. 현재 User/Project 설치나 개인 자료 선택 복원을 위한 명령으로 사용하지 않는다. 아래 수동 복원도 전체 이관·모든 외부 연결의 복구를 보장하지 않는다.

1. 실행 중인 Claude와 해당 개인 상태를 쓰는 작업을 종료한다.
2. 출력된 백업 폴더의 `backup-manifest.json`에서 원래 저장 위치와 백업 항목을 확인한다.
3. 현재 개인 데이터도 별도로 보존하고, 필요한 파일만 원래 위치로 복원한다. 폴더 전체를 무조건 덮어쓰지 않는다.
4. 마스킹된 설정과 제외된 인증정보/MCP 의존성은 기존 회사 설정 절차로 복구한다.
5. 호환되는 Core로 다시 실행해 Memory 검색과 개인 Skill 사용을 확인한다.

교체 전 하네스로 돌아가려는 경우에는 위 개인 자료 선택 복구와 별도로 다음 절차를 사용한다.

1. Claude를 닫고 `deploy\Uninstall-ScopedCompanyAgent.ps1`로 설치했던 같은 User/Project 범위의 Company Agent를 제거한다.
2. 같은 Windows 사용자·PC에서 설치 때 출력된 백업 경로를 지정해 아래 Dry Run을 실행한다.
3. 충돌이 없으면 두 번째 명령으로 기존 규칙·설정을 복구하고 Claude를 다시 연다.

```powershell
powershell.exe -NoProfile -File .\deploy\Restore-PreviousHarness.ps1 -BackupPath "<pre-install 백업 폴더>" -DryRun
powershell.exe -NoProfile -File .\deploy\Restore-PreviousHarness.ps1 -BackupPath "<pre-install 백업 폴더>" -NonInteractive
```

이 복구 스크립트는 Company Agent를 자동 제거하지 않는다. 지시 파일이 수정·재생성되었거나 새 Hook과 충돌하면 복구를 거절한다.
모델·MCP·Plugin 등록 등 Hook 이외의 설정 변경은 유지하면서 기존 Hook만 복구한다.
충돌한 현재 자료를 별도로 보존하고 안내를 확인한다. 백업과 맞추기 위해 현재 설정이나 개인 자료를 무조건 삭제하지 않는다.

사용자 지정 경로 설치를 **제거**하면 활성 등록도 삭제된다. 제거 전에 등록/백업의 `userStateRoot`를 보관하고,
다시 설치할 때 같은 `-UserStateRoot`를 전달한다. 제거 후 경로 자동 추정은 하지 않는다.
개발 중인 이전 설치기를 로컬 검증하며 경로 연결이 끊긴 경우에도 새 설치기가 잃어버린 경로를 추측하지 않는다.
원래 등록 백업을 확인하고, 사용자의 명시적 복구 요청 아래 해당 범위 등록과 원래 경로를 다시 연결한다.

## 형식 호환성과 한계

`company-agent state check --state-root "<개인 경로>"`는 파일을 만들거나 변경하지 않는다.
선택적인 `state-format.json`은 `schemaVersion: 1`, 기존 `config/user.json`은 native 1 / legacy machine 2를 지원한다.
표시 없는 기존 State와 사용자 설정은 호환 대상으로 유지한다. 표시가 있는데 잘못되었거나 미래 버전이면 거절한다.
런타임의 개인 상태 쓰기도 같은 검사를 통과해야 하며, 알 수 없는 세션 schema를 기존 형식으로 덮어쓰지 않는다.
`init-user` 재실행은 기존 사용자 설정의 추가 필드를 보존한다.

Claude native CLI가 다시 저장할 설정에 안전한 정수 범위(`±9007199254740991`)를 넘는 정수 리터럴이 있으면,
설치 전 검사에서 기존 설정을 변경하지 않고 중단한다. 해당 설정 항목이 문자열 값을 허용하는지 확인한 뒤 명시적으로 수정한다.
이 검사는 숫자 임의 반올림이나 모든 소수·지수 표기의 정밀도 보장을 제공하지 않는다.

일반 데이터 마이그레이션/전체 세션 검사 기능은 아니다. 향후 저장 형식 변경은 명시적인 변환과 검증이 필요하다.
이 보호 장치를 모르는 과거 Core까지 안전하게 역호환된다고 보장하지 않는다. 형식 표시를 지워 검사를 우회하지 않는다.
동시에 실행 중인 업무가 백업 도중 파일을 바꾸면 전체 파일들의 단일 시점 일관성까지 보장하지 않는다.
업데이트 전에 Claude를 닫고 실행하는 것이 권장된다. 새 학습내용을 이전 백업으로 자동 되돌리지 않는다.

### 개인 도구의 기존 검증 기록

파일을 보존하는 것과 과거 검증 기록을 현재 실행 근거로 인정하는 것은 별개다. 표준 MCP에 정확한 JSON 또는 JSON 스키마 기대값이 있거나 Script Tool을 사용한다면 현재 JSON 검사 기준으로 다시 시험해야 한다. 표준 MCP의 text-only 검증 기록은 다른 유효성 조건을 만족하면 유지한다. 지원 조건은 [개인 MCP 검증 계약](MCP_CONTRACTS.md#personal-mcp-validation)을 참고한다.

재시험이 필요해도 업데이트가 도구를 임의로 실행하거나 소스·등록을 삭제하지 않는다. 가상 입력으로 현재 검증을 수행한 뒤 반환된 기록으로 활성화한다. Script Tool은 관리 실행 전에도 현재 기록을 확인한다. 이미 별도 등록된 Claude native MCP를 자동 해제하지 않으므로 그 연결의 운영 여부는 별도로 확인해야 한다.

## 개인 MCP의 Python 경로가 바뀐 경우

회사에서 별도로 운영하는 `corp-db-read` / `corp-outlook-self`는 이 절차의 대상이 아니다.
Factory로 만든 개인 MCP에는 검증 당시 Python 경로가 기록된다. Core 업데이트로 그 경로가 달라졌을 때
서명된 기존 검증 기록과 실제 소스가 일치하는 MCP만 다음 명령으로 명시적으로 재검증할 수 있다.
기존 기록이 현재 JSON 검사 기준을 충족하지 않으면 아래 경로 재연결 명령으로 생략하지 말고 먼저 현재 도구 검증 절차를 수행한다.

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
powershell.exe -NoProfile -File .\deploy\Test-ExistingHarness.ps1
powershell.exe -NoProfile -File .\deploy\Test-HarnessReplacement.ps1
powershell.exe -NoProfile -File .\deploy\Test-ScopedInstallSmoke.ps1
```

Scoped 검사는 임시 Claude 프로필·프로젝트에서 실제 Plugin CLI를 사용한다.
실제 개인 설치, 사내 모델, 회사 DB, Outlook 계정에 작업을 실행하지 않는다.
