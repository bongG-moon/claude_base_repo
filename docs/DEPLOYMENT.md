# Company Agent 설치와 배포 — Windows 0.3

직원은 Claude Code와 사내 SMALL/MEDIUM/LARGE 연결이 준비된 상태에서 ZIP 하나를 받습니다. 완전한 배포 ZIP에는 Python도 포함되어 Python/pip/Git 설치나 외부 접속이 필요하지 않습니다. Claude Code CLI 2.1.220 이상, Windows 10/11 x64를 확인합니다. ARM64 PC에는 별도 검증한 해당 아키텍처 패키지를 배포합니다.

## 직원이 하는 일

1. 열려 있는 Claude Code를 닫고 ZIP을 로컬 폴더에 모두 압축 해제합니다.
2. 최상위 `Install-CompanyAgent.cmd`를 더블클릭합니다. 관리자 권한으로 실행하지 않습니다.
3. **Claude 전체** 또는 **이 프로젝트만**을 선택합니다. 프로젝트라면 대상 폴더도 선택합니다.
4. 기존 하네스가 발견되면 **기존 하네스 유지** 또는 **백업 후 Company Agent 설치**를 선택합니다. 없으면 추가 질문 없이 설치합니다.
5. 설치가 완료되면 Claude Code를 다시 실행합니다. ‘유지’는 설치·변경 없이 종료하므로 재시작할 필요가 없습니다.

| 선택 | 적용되는 곳 | 자동 기록되는 Claude 설정 | 관리자 권한 |
| --- | --- | --- | --- |
| Claude 전체 / User | 현재 Windows 사용자의 Claude 작업 전체 | 사용자 settings.json의 플러그인 등록 | 불필요 |
| 이 프로젝트만 / Project | 선택한 프로젝트와 하위 폴더 | 프로젝트 .claude/settings.local.json의 플러그인 등록 | 불필요 |

‘전체’는 본인 Windows 계정의 Claude 환경입니다. PC의 모든 직원이나 전사 PC를 즉시 변경하는 기능은 아닙니다. 같은 ZIP을 직원에게 배포하면 같은 공통 하네스를 각각 설치합니다. Project 설치는 Claude의 `local` scope를 사용하여 PC별 설치 경로가 공유 settings.json에 들어가지 않게 합니다.

두 범위를 함께 사용할 수 있습니다. 동일한 플러그인 ID `company-agent@company-agent-local`를 사용하고, 가장 가까운 프로젝트 등록이 개인 상태를 선택합니다. 해당 프로젝트 밖에서는 User 상태를 사용합니다. Project만 설치한 PC에서는 다른 프로젝트에 활성화되지 않습니다.

현재 배포본은 한 Windows 계정에서 하나의 Claude 설정 프로필을 지원합니다. 다른 `CLAUDE_CONFIG_DIR` 프로필로 기존 등록을 덮어쓰려 하면 중단합니다.

전용 실행기 없이 평소처럼 Claude를 사용합니다. 프로젝트에서 다음처럼 요청할 수 있습니다.

> 이 프로젝트의 내용을 먼저 확인하고, 이 일을 잘 수행할 수 있는 하네스를 구성해줘. 꼭 필요한 내용만 물어봐줘.

## Claude에게 설치 맡기기

압축을 푼 폴더의 `INSTALL_WITH_CLAUDE.md`를 Claude에 주고 “이 지침대로 설치해줘”라고 요청합니다. 적용 범위와 필요한 경우 대상 프로젝트를 받고 Dry Run으로 확인합니다. 기존 하네스가 있으면 유지/교체 선택도 받습니다. 이미 말한 선택은 다시 묻지 않도록 지침에 반영했습니다. 모델 ID, 비밀번호, MCP, Outlook 정보는 요구하지 않습니다.

운영자용 단일 명령 예시:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -NonInteractive

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope Project -ProjectRoot "C:\Work\Report" -NonInteractive
```

사전 점검만 하려면 같은 명령에 `-DryRun`을 추가합니다. 범위 없는 무인 실행은 선택을 추측하지 않고 필요한 인자를 안내합니다. 조직이 실행 정책을 강제한 경우 사내 서명 정책에 맞춰 실행합니다.

`-ExistingHarnessAction Ask|Keep|Replace`의 기본값은 `Ask`입니다. 기존 하네스를 감지한 무인 `Ask` 실행은
`status: input-required`, `input: ExistingHarnessAction`, `choices: Keep/Replace`를 반환합니다.
Claude 설치 위임이나 배포 자동화는 이 결과를 사용자에게 보여 주고 선택을 받아야 합니다. 교체를 임의로 기본값으로 사용하지 않습니다.
Dry Run은 기존 하네스 목록과 요청한 선택을 읽기 전용으로 보여 주며 백업·비활성화·설치를 실행하지 않습니다.

사용자가 교체를 선택한 경우의 명령 예시입니다. 유지라면 `Replace` 대신 `Keep`을 사용합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -ExistingHarnessAction Replace -NonInteractive
```

## 기존 하네스 유지 또는 교체 — 0.3.3

감지는 설치 대상으로 선택한 범위에서 수행합니다. 모델·MCP만 설정되어 있거나 독립 Skill만 있는 경우에는 기존 하네스로 판정하지 않습니다.
같은 범위에 Company Agent가 이미 등록되어 있으면 업데이트에서도 유지/교체를 묻습니다.

| 범위 | 교체 시 비활성화하는 기존 파일/설정 |
| --- | --- |
| User | 현재 Claude 설정 폴더의 `CLAUDE.md`·`CLAUDE.local.md`, `rules/**/*.md`, `settings.json`의 최상위 `hooks` |
| Project | 선택 프로젝트 루트와 `.claude`의 `CLAUDE.md`·`CLAUDE.local.md`, `.claude/rules/**/*.md`, `.claude/settings.json`과 `.claude/settings.local.json`의 최상위 `hooks` |

**유지**는 백업이나 Company Agent 설치도 하지 않고 변경 없이 종료합니다. **교체**는 기존 항목을 자동 백업한 뒤 위 항목만 비활성화하고 설치합니다.
기존 모델 별칭, MCP, env, permissions, 일반 Skill, 다른 플러그인, 개인 Memory/Knowledge/Skill은 유지합니다.
설정 파일 전체를 지우지 않고 최상위 `hooks`만 제거하므로 모델/API 설정을 다시 입력할 필요가 없습니다.

다른 범위에서 상속한 규칙·Hook, 상위 폴더의 지침, 별도 플러그인이 제공하는 Hook은 대상이 아니며 유지됩니다.
프로젝트 설치가 사용자 전체 하네스까지 비활성화하지는 않습니다. 감지·유지 목록을 확인해야 하며 이 기능은 전체 환경 초기화가 아닙니다.

## 자동 점검과 백업

사용자 컨텍스트, Claude 버전, 포함된 Python 실행 여부, 번들 해시, 대상 경로와 기존 플러그인을 확인합니다. 기존 모델 별칭 haiku/sonnet/opus를 그대로 사용하며 API shim을 만들지 않습니다. 모든 subagent를 한 모델로 강제하는 설정이 있으면 해당 문제를 안내합니다.

Claude native CLI의 설정 저장 과정에서 정밀도가 달라질 수 있는 큰 정수 리터럴(`±9007199254740991` 범위 초과)이 기존 설정에 있으면 변경 전에 중단합니다.
해당 항목이 문자열을 허용하는 경우 담당자와 확인하여 수정한 뒤 재시도합니다. 설치기가 값을 임의 변환하지 않으며, 이 검사는 모든 소수·지수 표기의 정밀도를 검증하는 기능은 아닙니다.

설정 변경 전에 아래 위치로 선택 백업합니다.

```text
%LOCALAPPDATA%\CompanyAgent-Backups\pre-install-<시각>-<ID>
```

User는 `%USERPROFILE%\.claude`, Project는 여기에 대상 프로젝트의 `.claude`도 추가합니다. `CLAUDE_CONFIG_DIR`가 있으면 해당 경로를 사용합니다.

- settings*.json, Markdown 지시 파일, Skill, Agent, Command, Hook
- 플러그인 등록 JSON과 기존 Company Agent 등록
- 개인 Memory 원본/수정 이력, Knowledge entries/overlays/versions, 개인 Skill, 사용자 설정 및 있는 경우 State 형식 표시

일반 선택 백업은 자격 증명, .env, 개인키, Claude 세션/대화 history, cache를 제외합니다. JSON의 token/password/secret 계열 값은 마스킹하므로 복구 시 다시 입력해야 할 수 있습니다. 백업은 현재 사용자와 LocalSystem으로 접근을 제한하고 junction/symlink를 따라가지 않습니다. 업무 지시가 남을 수 있으므로 개인 PC에서 보관합니다.

교체할 기존 파일·Hook이 있으면 `previous-harness` 아래에 해당 규칙·설정의 정확한 원본을 Windows DPAPI CurrentUser로 암호화하여 추가 백업합니다.
이는 기존 설정 안의 비밀값도 손실 없이 복구하기 위한 별도 사본입니다. 평문 인증정보 파일을 복사하지 않으며,
같은 Windows 사용자·PC에서만 복구하는 로컬 복구본입니다. 다른 PC로 옮기거나 Git/공유 저장소에 올리지 않습니다.
복구 시 백업의 원래 폴더 경로도 같아야 합니다. 이동했다면 설치 때 출력된 원래 위치로 되돌립니다.
추가 암호화 백업은 최대 512개 파일, 단일 원본 8MiB, 원본 합계 32MiB이며 상한 초과나 백업 실패 시 기존 하네스는 비활성화하지 않습니다.

개인 학습자료는 `company-agent\personal-learning`에 선택 백업합니다. 전체 State, MCP 환경, 인증정보를 복제하는 기능은 아닙니다. 백업 범위·제한·복구 순서는 [개인 상태 보존](STATE_PRESERVATION.md)에 설명되어 있습니다.

기존 Skill·모델·MCP를 덮어쓰지 않고 네이티브 플러그인 등록 키를 병합합니다. 교체를 선택한 경우에만 위의 기존 규칙·Hook을 비활성화합니다. 다른 배포본이 동일 플러그인 이름을 사용하거나 같은 버전에 다른 내용을 설치하려 하면 중단합니다. 설치 실패 시 Company Agent가 변경한 등록과 비활성화한 규칙·Hook을 복원합니다. 설치 도중 다른 작업이 같은 파일을 수정해 충돌하면 덮어쓰지 않고 백업 위치와 해결 방법을 안내합니다. 설치·업데이트 전 Claude를 닫아 두세요.
파일별 변경 검사를 수행하지만 여러 파일을 OS 전체에서 한꺼번에 잠그는 원자적 작업은 아닙니다. 설치·복구 중에는 다른 Claude 세션과 대상 폴더를 수정하는 작업도 종료합니다.

## 저장 위치와 업데이트

```text
%LOCALAPPDATA%\CompanyAgent-Distribution\marketplace\
├─ .claude-plugin\marketplace.json
└─ versions\<CoreVersion>\
   ├─ plugin\                    공통 Core + 프로젝트 하네스 생성 Skill
   │  └─ runtime\python\         포함된 Python + 라이선스
   ├─ knowledge\                 관리자 Markdown Base
   └─ config\                    배포 설정

%LOCALAPPDATA%\CompanyAgent\
├─ installations\user\
├─ installations\projects\<경로해시>\
└─ states\
   ├─ user\                      사용자 Memory / Knowledge / Skill
   └─ projects\<경로해시>\         프로젝트별 Memory / Knowledge / Skill
```

사용자 권한의 로컬 설치입니다. 설치 프로그램이 Core와 개인 상태를 구분해 보존하지만 사용자가 OS 권한으로 Core를 직접 편집하는 것까지 금지하는 영역은 아닙니다. DB와 Outlook의 보안 경계는 사내 MCP와 계정 권한으로 집행합니다. 관리자 ACL로 Core를 보호하는 기존 machine 배포는 별도 경로로 유지합니다.

Core, Knowledge, 설정이 바뀌면 관리자에게 새 CoreVersion의 ZIP을 받습니다. 새 ZIP의 설치 파일을 다시 실행하고 기존 범위와 ‘백업 후 Company Agent 설치’를 선택하면 갱신됩니다. 이전 릴리스와 개인 상태는 유지됩니다. ‘기존 하네스 유지’를 선택하면 업데이트도 하지 않습니다. User와 여러 Project scope를 쓰면 각 scope를 갱신하고 Claude를 재시작합니다.

0.3.2부터 동일 scope의 기존 등록에 저장된 `userStateRoot`를 기본 경로보다 우선합니다. 처음 지정한 개인 경로를 업데이트 때 다시 입력할 필요가 없습니다. 기존 등록과 다른 `-UserStateRoot`는 자동 이관을 뜻하지 않으므로 파일·등록을 바꾸기 전에 거절합니다. User↔Project 변경이나 프로젝트 경로 이동 역시 별도 상태이며 자동 병합하지 않습니다.

설치 전 `state check`는 개인 State의 형식 표시와 사용자 설정 형식을 읽기 전용으로 확인합니다. 지원하지 않는 미래 버전/손상된 표시가 있으면 초기화하지 않고 중단합니다. 기존 형식 표시가 없는 State는 호환 대상으로 읽습니다. 이는 호환성 보호 장치이지 일반 마이그레이션 엔진은 아닙니다.

개인 Knowledge는 Corporate Base와 분리된 Markdown overlay입니다. 충돌 없는 추가 지식은 새 Base에 맞춰 갱신하고 충돌한 수정은 별도로 기록합니다. 개인 Skill은 현재 scope의 상태 디렉터리에 저장됩니다. 매 요청에 관련 Skill 정보를 찾고 Claude가 SKILL.md를 읽어 사용합니다. 모든 개인 Skill이 슬래시 메뉴에 표시된다는 의미는 아닙니다. Factory가 프로젝트 .claude/skills와 .claude/agents에 생성한 파일은 Claude가 직접 발견합니다.

## 제거와 재설치

같은 배포본의 제거 스크립트에 범위를 지정합니다.

```powershell
powershell.exe -NoProfile -File .\deploy\Uninstall-ScopedCompanyAgent.ps1 -Scope User

powershell.exe -NoProfile -File .\deploy\Uninstall-ScopedCompanyAgent.ps1 -Scope Project -ProjectRoot "C:\Work\Report"
```

선택한 scope의 플러그인 등록만 제거하며 개인 상태와 공통 배포 파일은 보존합니다. 기본 경로는 같은 범위로 재설치하면 이전 개인 상태가 이어집니다. 사용자 지정 경로는 제거 전 등록/백업의 `userStateRoot`를 보관하고 재설치 때 같은 `-UserStateRoot`를 전달합니다. 사용자가 Factory로 만든 프로젝트 Agent와 Skill도 남습니다.

교체 전에 쓰던 하네스로 돌아가려면 Claude를 닫고 먼저 위 명령으로 같은 scope의 Company Agent를 제거합니다.
그다음 설치 때 출력된 `pre-install-...` 백업 폴더를 지정해 검사한 뒤 복구합니다.

```powershell
powershell.exe -NoProfile -File .\deploy\Restore-PreviousHarness.ps1 -BackupPath "<pre-install 백업 폴더>" -DryRun
powershell.exe -NoProfile -File .\deploy\Restore-PreviousHarness.ps1 -BackupPath "<pre-install 백업 폴더>" -NonInteractive
```

복구 스크립트 자체는 Company Agent를 제거하지 않습니다. 백업을 만든 동일 Windows 사용자·PC에서만 실행합니다.
지시 파일이 수정·재생성되었거나 새 Hook이 기존 Hook과 충돌하면 덮어쓰기를 거절합니다.
모델·MCP·Plugin 등록 등 Hook 이외의 설정 변경은 유지하면서 기존 Hook만 복구합니다. 충돌 시 현재 파일도 보존하고 안내를 확인합니다.

## 빌드 PC에서 배포 ZIP 만들기

인터넷 가능한 빌드 PC에서 다음을 한 번 실행합니다. 직원 PC는 다운로드하지 않습니다.

```powershell
powershell.exe -NoProfile -File .\deploy\Get-EmbeddedPython.ps1
```

Python 3.13.15 Windows x64 embeddable archive의 공식 SHA-256을 확인하여 build/runtime에 보관합니다. 폐쇄망 빌드 PC로 검증된 ZIP을 반입할 수도 있습니다. Python 라이선스를 배포물에 포함하고 격리된 import 경로에 하네스 scripts만 추가합니다. pip나 PC 전역 PATH를 변경하지 않습니다.

```powershell
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion 0.3.3 -KnowledgeVersion 2026.09.03
```

결과는 `dist\company-agent-0.3.3-2026.09.03.zip`입니다. 이미 공개한 0.3.2 릴리스의 ZIP을 덮어쓰지 않습니다. `-WithoutBundledPython`은 승인된 Python이 이미 있는 PC용 경량 패키지에만 사용합니다. 별도 런타임은 `-PythonRuntimeZip`과 정확한 `-PythonRuntimeSha256`을 함께 지정합니다.

빌더는 플러그인·Knowledge 버전과 구조, Python import, 파일별 해시를 검사합니다. 전사 정식 배포는 사내 서명·소프트웨어 배포 절차로 전달합니다. 해시 목록은 배포 주체 인증을 대신하지 않습니다.

## 적용 후 확인

Claude에 “Company Agent 설치 상태를 확인해줘”라고 요청하면 자동 전달된 실행 경로로 doctor를 호출할 수 있습니다. 진단은 구조와 모델 별칭 상속을 확인하며 사내 모델에 실제 응답을 요청하지 않습니다. 실제 모델 전환과 업무 품질은 대표 프로젝트 작업으로 확인합니다.

사내 MCP 구현은 별도입니다. 기존 Claude MCP 설정을 유지하고 사내 서버는 기존 운영 방식으로 연결합니다. DB SELECT-only와 Outlook 본인 계정 제한은 서버 자체가 강제해야 합니다. 하네스 생성 기능은 실제 MCP와 계약을 확인하며, 존재하지 않는 서버 기능을 생성 결과에 꾸며 넣지 않도록 합니다.

개인 MCP는 구조·프로토콜 검증을 통과한 후 `asset activate-mcp`에서 선택 scope의 Claude 등록까지 수행합니다. 응답 유실 등으로 등록만 남으면 `asset sync-mcp --name ...`으로 재시도합니다. 기존 이름이나 다른 scope의 동일 이름은 덮어쓰지 않습니다. 새 MCP 생성에는 해당 자산이 사용하는 승인된 MCP SDK 환경이 별도로 필요하며, 기본 내장 Python은 하네스 실행에 필요한 표준 라이브러리만 포함합니다. 모델·자산 실행 환경이 바뀌면 기존 검증 receipt는 재검증이 필요할 수 있습니다.

[프로젝트 하네스 생성](PROJECT_HARNESS.md) · [최초 의도와 구현 대조](IMPLEMENTATION_REVIEW.md) · [기존 관리자 배포](LEGACY_MACHINE_DEPLOYMENT.md)
