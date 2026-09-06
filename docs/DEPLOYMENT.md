# Company Agent 설치와 배포 — Windows 0.3

직원은 Claude Code와 사내 SMALL/MEDIUM/LARGE 연결이 준비된 상태에서 ZIP 하나를 받습니다. 완전한 배포 ZIP에는 Python도 포함되어 Python/pip/Git 설치나 외부 접속이 필요하지 않습니다. Claude Code CLI 2.1.220 이상, Windows 10/11 x64를 확인합니다. ARM64 PC에는 별도 검증한 해당 아키텍처 패키지를 배포합니다.

## 직원이 하는 일

1. ZIP을 로컬 폴더에 모두 압축 해제합니다.
2. 최상위 `Install-CompanyAgent.cmd`를 더블클릭합니다. 관리자 권한으로 실행하지 않습니다.
3. **Claude 전체** 또는 **이 프로젝트만**을 선택합니다. 프로젝트라면 대상 폴더도 선택합니다.
4. 완료되면 열려 있던 Claude Code를 닫고 다시 실행합니다.

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

압축을 푼 폴더의 `INSTALL_WITH_CLAUDE.md`를 Claude에 주고 “이 지침대로 설치해줘”라고 요청합니다. 적용 범위와 필요한 경우 대상 프로젝트만 물어보고, Dry Run으로 확인한 뒤 설치합니다. 이미 말한 선택은 다시 묻지 않도록 지침에 반영했습니다. 모델 ID, 비밀번호, MCP, Outlook 정보는 요구하지 않습니다.

운영자용 단일 명령 예시:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -NonInteractive

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope Project -ProjectRoot "C:\Work\Report" -NonInteractive
```

사전 점검만 하려면 같은 명령에 `-DryRun`을 추가합니다. 범위 없는 무인 실행은 선택을 추측하지 않고 필요한 인자를 안내합니다. 조직이 실행 정책을 강제한 경우 사내 서명 정책에 맞춰 실행합니다.

## 자동 점검과 백업

사용자 컨텍스트, Claude 버전, 포함된 Python 실행 여부, 번들 해시, 대상 경로와 기존 플러그인을 확인합니다. 기존 모델 별칭 haiku/sonnet/opus를 그대로 사용하며 API shim을 만들지 않습니다. 모든 subagent를 한 모델로 강제하는 설정이 있으면 해당 문제를 안내합니다.

설정 변경 전에 아래 위치로 선택 백업합니다.

```text
%LOCALAPPDATA%\CompanyAgent-Backups\pre-install-<시각>-<ID>
```

User는 `%USERPROFILE%\.claude`, Project는 여기에 대상 프로젝트의 `.claude`도 추가합니다. `CLAUDE_CONFIG_DIR`가 있으면 해당 경로를 사용합니다.

- settings*.json, Markdown 지시 파일, Skill, Agent, Command, Hook
- 플러그인 등록 JSON과 기존 Company Agent 등록
- 개인 Memory 원본/수정 이력, Knowledge entries/overlays/versions, 개인 Skill, 사용자 설정 및 있는 경우 State 형식 표시

자격 증명, .env, 개인키, Claude 세션/대화 history, cache는 백업하지 않습니다. JSON의 token/password/secret 계열 값은 마스킹하므로 복구 시 다시 입력해야 할 수 있습니다. 백업은 현재 사용자와 LocalSystem으로 접근을 제한하고 junction/symlink를 따라가지 않습니다. 업무 지시가 남을 수 있으므로 개인 PC에서 보관합니다.

개인 학습자료는 `company-agent\personal-learning`에 선택 백업합니다. 전체 State, MCP 환경, 인증정보를 복제하는 기능은 아닙니다. 백업 범위·제한·복구 순서는 [개인 상태 보존](STATE_PRESERVATION.md)에 설명되어 있습니다.

기존 Skill·모델·MCP를 덮어쓰지 않고 네이티브 플러그인 등록 키만 병합합니다. 다른 배포본이 동일 플러그인 이름을 사용하거나 같은 버전에 다른 내용을 설치하려 하면 중단합니다. 등록 실패 시 Company Agent가 변경한 키를 복원하고 다른 등록과 개인 상태를 보존합니다.

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

Core, Knowledge, 설정이 바뀌면 관리자에게 새 CoreVersion의 ZIP을 받습니다. 새 ZIP의 설치 파일을 다시 실행하고 기존 범위를 선택하면 갱신됩니다. 이전 릴리스와 개인 상태는 유지됩니다. User와 여러 Project scope를 쓰면 각 scope를 갱신하고 Claude를 재시작합니다.

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

## 빌드 PC에서 배포 ZIP 만들기

인터넷 가능한 빌드 PC에서 다음을 한 번 실행합니다. 직원 PC는 다운로드하지 않습니다.

```powershell
powershell.exe -NoProfile -File .\deploy\Get-EmbeddedPython.ps1
```

Python 3.13.15 Windows x64 embeddable archive의 공식 SHA-256을 확인하여 build/runtime에 보관합니다. 폐쇄망 빌드 PC로 검증된 ZIP을 반입할 수도 있습니다. Python 라이선스를 배포물에 포함하고 격리된 import 경로에 하네스 scripts만 추가합니다. pip나 PC 전역 PATH를 변경하지 않습니다.

```powershell
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion 0.3.2 -KnowledgeVersion 2026.09.03
```

결과는 `dist\company-agent-0.3.2-2026.09.03.zip`입니다. `-WithoutBundledPython`은 승인된 Python이 이미 있는 PC용 경량 패키지에만 사용합니다. 별도 런타임은 `-PythonRuntimeZip`과 정확한 `-PythonRuntimeSha256`을 함께 지정합니다.

빌더는 플러그인·Knowledge 버전과 구조, Python import, 파일별 해시를 검사합니다. 전사 정식 배포는 사내 서명·소프트웨어 배포 절차로 전달합니다. 해시 목록은 배포 주체 인증을 대신하지 않습니다.

## 적용 후 확인

Claude에 “Company Agent 설치 상태를 확인해줘”라고 요청하면 자동 전달된 실행 경로로 doctor를 호출할 수 있습니다. 진단은 구조와 모델 별칭 상속을 확인하며 사내 모델에 실제 응답을 요청하지 않습니다. 실제 모델 전환과 업무 품질은 대표 프로젝트 작업으로 확인합니다.

사내 MCP 구현은 별도입니다. 기존 Claude MCP 설정을 유지하고 사내 서버는 기존 운영 방식으로 연결합니다. DB SELECT-only와 Outlook 본인 계정 제한은 서버 자체가 강제해야 합니다. 하네스 생성 기능은 실제 MCP와 계약을 확인하며, 존재하지 않는 서버 기능을 생성 결과에 꾸며 넣지 않도록 합니다.

개인 MCP는 구조·프로토콜 검증을 통과한 후 `asset activate-mcp`에서 선택 scope의 Claude 등록까지 수행합니다. 응답 유실 등으로 등록만 남으면 `asset sync-mcp --name ...`으로 재시도합니다. 기존 이름이나 다른 scope의 동일 이름은 덮어쓰지 않습니다. 새 MCP 생성에는 해당 자산이 사용하는 승인된 MCP SDK 환경이 별도로 필요하며, 기본 내장 Python은 하네스 실행에 필요한 표준 라이브러리만 포함합니다. 모델·자산 실행 환경이 바뀌면 기존 검증 receipt는 재검증이 필요할 수 있습니다.

[프로젝트 하네스 생성](PROJECT_HARNESS.md) · [최초 의도와 구현 대조](IMPLEMENTATION_REVIEW.md) · [기존 관리자 배포](LEGACY_MACHINE_DEPLOYMENT.md)
