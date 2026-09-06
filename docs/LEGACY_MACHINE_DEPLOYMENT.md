# Company Agent Windows 배포 가이드

이 문서는 폐쇄망 Windows PC에 Company Agent 하네스를 배포하고 개인 사용자 상태를 초기화하는 운영 절차다. 관리자 배포 영역과 개인 상태는 물리적으로 분리된다.

```text
오프라인 릴리스 ZIP
  ├─ payload/core/plugin             관리자 배포
  ├─ payload/knowledge               관리자 배포
  ├─ payload/config                  관리자 배포
  └─ deploy                          설치 및 복구 스크립트
             │
             ▼
C:\Program Files\CompanyAgent
  ├─ versions\<coreVersion>\plugin   버전별 불변 Core
  └─ bin                              Launcher/관리 스크립트

C:\ProgramData\CompanyAgent
  ├─ knowledge\versions\<version>    버전별 불변 Corporate Base
  ├─ config\versions\<coreVersion>   버전별 불변 Session/MCP/런타임 설정
  └─ state\current.json              현재 Core/Knowledge/Config 선택
           \previous.json            직전 선택, 즉시 Rollback 용도

%LOCALAPPDATA%\CompanyAgent
  ├─ config\user.json                로컬 사용자 설정(Outlook 정보는 선택 사항)
  ├─ knowledge                        Personal Overlay와 합성 인덱스
  ├─ personal-root\.claude\skills    자동 활성화 개인 Skill
  ├─ mcp\registry.json               개인 MCP Registry
  ├─ tools / ledger / sessions
  └─ memory                           추출된 개인 Memory

%LOCALAPPDATA%\CompanyAgent-Backups
  └─ pre-install-<timestamp>-<id>     설치 전 선택 백업과 manifest
```

일반 사용자는 Corporate Base를 읽을 수만 있고 `%LOCALAPPDATA%`의 Personal Overlay와 Skill은 계속 발전시킬 수 있다. 업데이트와 기본 삭제는 개인 상태를 변경하지 않는다.

## 1. 사전 조건

- Windows 10/11 또는 대응되는 Windows Server
- Windows PowerShell 5.1 이상
- 사내에서 승인해 오프라인 설치한 Claude Code CLI 2.1.220 이상
- 승인된 Python 3.11 이상이 `PATH`의 `python` 또는 Windows `py` launcher로 실행 가능할 것
- 최초 설치·업데이트·롤백·삭제 작업용 로컬 관리자 또는 소프트웨어 배포 계정
- Claude Code에서 이미 동작하는 `haiku`, `sonnet`, `opus` alias(SMALL, MEDIUM, LARGE)

쉬운 설치 프로그램은 관리자 권한을 요청하기 **전에 일반 사용자 컨텍스트에서** `claude`, 사용 가능한 `python`/`py` 후보의 Python 3.11 이상 여부, bundle manifest, 경로 충돌, 기존 Skill/Plugin/Hook 중복을 검사한다. 처음부터 관리자 권한으로 실행하면 잘못된 관리자 프로필을 백업하지 않도록 중단하고 일반 실행을 안내한다. 조건이 맞지 않으면 설치를 시작하지 않고 해결해야 할 항목만 표시한다. 모델 ID, MCP 명령, Outlook 주소는 묻지 않는다. 운영 PC에서 `-SkipPrerequisiteCheck`를 사용하면 안 된다.

PowerShell 실행 정책이 `RemoteSigned`인 환경을 고려해 **번들을 만들기 전에** 소스의 `deploy\*.ps1`에 사내 코드 서명을 적용하고 서명 인증서를 신뢰 체인에 배포한다. ZIP의 SHA-256 manifest는 파일 손상을 검출하지만 배포 주체의 신원을 증명하지는 않으므로 생성된 ZIP에도 사내 패키지 서명을 별도로 적용한다.

설치 프로그램은 `%USERPROFILE%\.claude`를 수정하지 않는다. 다만 기존 범용 Skill, command, agent, Hook, 설정 및 plugin 등록 정보가 함께 로드될 때의 운영 복구를 위해 다음 항목만 `%LOCALAPPDATA%\CompanyAgent-Backups`에 timestamp별로 복사한다. 백업 폴더 ACL은 현재 Windows 사용자와 LocalSystem으로 제한하고 junction/symlink는 따라가지 않는다.

- `.claude`의 Markdown 지시 파일, `settings*.json`, `skills`, `commands`, `agents`, `hooks`
- Claude plugin 등록 JSON
- 기존 Company Agent의 current/previous 선택, versioned config, launcher, 바로가기

`.credentials.json` 같은 별도 자격 증명 파일, `.env`, private-key/certificate/비밀번호 저장소 파일, 세션 원문, `history`, `projects`, plugin cache, 일반 cache/debug/telemetry는 백업하지 않는다. 선택된 JSON의 token/password/secret/credential/PAT 계열 필드는 값 대신 redaction 표식을 저장하므로 복원 시 다시 입력해야 한다. 개인 Company Agent 상태는 별도 복사하지 않고 `%LOCALAPPDATA%\CompanyAgent`에 그대로 보존한다. `CLAUDE_CONFIG_DIR`가 설정되어 있으면 `.claude` 대신 그 경로를 기준으로 검사·백업한다. 백업에는 업무 지시 내용이 남을 수 있으므로 다른 사람과 공유하지 않는다.

## 2. 릴리스 준비

### 2.1 버전 일치

다음 세 값이 반드시 일치해야 한다.

- `company-agent-plugin\.claude-plugin\plugin.json`의 `version`
- `New-OfflineBundle.ps1 -CoreVersion`
- 배포 후 `C:\Program Files\CompanyAgent\versions\<coreVersion>`

Corporate Knowledge도 다음 값이 일치해야 한다.

- `corporate-knowledge\pack.json`의 `version`
- `New-OfflineBundle.ps1 -KnowledgeVersion`
- 배포 후 `C:\ProgramData\CompanyAgent\knowledge\versions\<knowledgeVersion>`

Bundler가 이 일치와 최상위 `Install-CompanyAgent.cmd`, `INSTALL_WITH_CLAUDE.md` 존재를 강제로 검사한다. 동일 버전 경로에 내용이 다른 Core 또는 Knowledge를 덮어쓸 수 없으므로 내용이 변경되면 반드시 새 버전을 부여한다. Session/MCP/런타임 설정은 `<coreVersion>`에 결합되므로 그 설정만 바뀌어도 Core 릴리스 버전을 올린다.

### 2.2 선택 사항: 별도 개발한 MCP 연결

MCP는 Company Agent Core와 별도로 개발·검증·배포한다. 준비된 사내 MCP가 있을 때만 예시 파일을 복사해 실제 파일을 만든다.

```powershell
Copy-Item .\config\managed-mcp.example.json .\config\managed-mcp.json
```

`managed-mcp.json`에서 다음 두 서버의 사내 실행 명령을 설정할 수 있다.

- `corp-db-read`: 서버 자체에서도 SELECT-only를 강제해야 한다.
- `corp-outlook-self`: 서버 자체에서도 초기화된 본인 계정만 송신하도록 강제해야 한다.

두 MCP 도구를 Claude 설정의 `permissions.allow`에 직접 추가하지 않는다. 정상 호출은 PreToolUse Hook이 승인하지만 Hook이 실행되지 못한 경우에는 Claude Code의 일반 권한 확인으로 되돌아가야 한다. 다만 프로세스 강제 종료나 timeout까지 Hook만으로 보안 경계로 만들 수는 없으므로 서버 측 권한 강제가 필수다.

Hook 검사는 2차 방어선이다. DB 계정 권한과 MCP 서버 권한을 실제 보안 경계로 유지한다. 토큰, 비밀번호, DB 접속 문자열을 Markdown이나 ZIP에 넣지 말고 Windows Credential Manager 또는 승인된 사내 비밀 저장소를 사용한다.

`managed-mcp.json`이 없거나 관리형·개인 registry에 서버가 하나도 없으면 Launcher는 `--mcp-config`와 `--strict-mcp-config`를 전달하지 않는다. 따라서 사용자가 기존 Claude Code에 설치한 MCP는 계속 보인다. Harness MCP가 있으면 기본값은 기존 MCP에 더하는 `merge`이며, 조직이 의도적으로 격리해야 할 때만 versioned `managed.json`의 `strictMcpConfig`를 `true`로 설정한다.

선택적으로 다음 파일을 실제 이름으로 제공하면 번들에 포함된다.

```text
config\managed.json
config\session.settings.json
config\managed-mcp.json
```

`session.settings.json`은 Company Agent로 시작한 세션에만 추가되는 최소 권한 설정이다. 모델, alias 환경 변수, 기존 사용자 설정을 덮어쓰지 않는다. 기본 설치의 `managed.json`에는 모델 ID가 아니라 `claude-config` 모드와 alias 이름만 기록된다. 세 파일은 Core와 동일한 versioned config 디렉터리에 설치되어 update/rollback 때 함께 전환된다.

### 2.3 오프라인 ZIP 생성

저장소 루트에서 실행한다.

```powershell
powershell.exe -NoLogo -NoProfile -File .\deploy\New-OfflineBundle.ps1 `
  -CoreVersion '0.2.0' `
  -KnowledgeVersion '2026.09.03' `
  -OutputPath 'D:\Release\company-agent-0.2.0-2026.09.03.zip'
```

기본 릴리스 검사는 다음 순서로 수행되며 하나라도 실패하면 ZIP을 만들지 않는다.

1. Plugin/Knowledge 내부 버전과 명령행 버전 일치
2. `claude plugin validate --strict`
3. `harness_cli.py knowledge validate`
4. Python `compileall`
5. payload 파일별 SHA-256·길이 manifest 생성

`.git`, `__pycache__`, `*.pyc`, pytest/mypy/ruff/tox 캐시 및 coverage 산출물은 staging에서 제외된다. 소스는 삭제하거나 수정하지 않는다. `-SkipSourceValidation`은 격리된 배포 스크립트 테스트에만 사용한다.

## 3. 설치

### 3.1 일반 사용자: 더블클릭

1. 승인된 ZIP을 로컬 폴더에 모두 압축 해제한다. ZIP 안에서 직접 실행하지 않는다.
2. 최상위 `Install-CompanyAgent.cmd`를 더블클릭한다.
3. 사전 검사를 확인하고 Windows 관리자 권한 요청(UAC)만 승인한다.
4. 완료되면 시작 메뉴의 **Company Agent**를 일반 사용자로 실행한다.

CMD wrapper는 `deploy\Setup-CompanyAgent.ps1`을 호출한다. Setup은 사용자의 기존 Claude/Python 환경을 먼저 확인하고 선택 백업을 만든 뒤, 관리 영역을 쓸 때만 스스로 상승한다. 기존 설치를 발견하면 동일한 진입점이 안전한 update/reinstall 경로를 선택한다. 모델 ID, MCP, Outlook 정보는 설치 중 입력하지 않는다.

### 3.2 Claude에게 설치 요청

비기술 사용자는 압축을 푼 폴더의 `INSTALL_WITH_CLAUDE.md`를 Claude Code에 첨부하거나 경로를 알려주고 “이 지침대로 설치해줘”라고 요청할 수 있다. 이 파일은 Claude가 dry-run과 preflight를 먼저 확인하고, 사용자의 선택이 실제로 필요한 경우에만 짧게 질문한 뒤 같은 Setup을 실행하도록 제한한다. 자격 증명이나 모델 ID를 Claude에게 전달할 필요가 없다.

### 3.3 운영자/배포 도구용 명령

Intune/SCCM 또는 운영자가 명시적으로 실행할 때도 쉬운 Setup을 우선 사용한다.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
  'C:\CompanyAgent-Staging\0.2.0\deploy\Setup-CompanyAgent.ps1' `
  -BundleRoot 'C:\CompanyAgent-Staging\0.2.0' `
  -NonInteractive
```

`Install-CompanyAgent.ps1`은 이미 상승된 machine-context 배포나 테스트를 위한 저수준 진입점이다. 직접 호출할 때도 `-UseExistingClaudeModels -DefaultTier AUTO`를 사용하며 세 모델 ID를 전달하지 않는다. System 계정은 실제 직원의 `.claude` 환경을 검사할 수 없으므로, 대량 배포에서는 일반 사용자 preflight/선택 백업 단계와 machine install 단계를 별도 패키지 단계로 구성해야 한다.

Installer는 다음을 수행한다.

- Bundle manifest의 모든 파일 hash와 manifest에 기록되지 않은 모든 번들 파일을 검사한다.
- Core와 Corporate Knowledge를 side-by-side 불변 버전 경로에 설치한다.
- 기존 Claude alias를 사용한다는 선택과 Session/MCP 설정을 versioned `ProgramData`에 기록한다.
- 기존 `current.json`을 `previous.json`으로 보존한 뒤 새 포인터를 원자적으로 활성화한다.
- 일반 사용자에게 `Program Files`와 `ProgramData`의 읽기/실행만 허용하는 ACL을 설정한다.
- 모든 사용자 시작 메뉴에 `Company Agent` 바로가기를 만든다.
- `%USERPROFILE%\.claude` 또는 `CLAUDE_CONFIG_DIR`의 파일을 생성·수정·삭제하지 않는다.

`-SkipAcl`, `-SkipAdminCheck`, `-SkipBundleVerification`, `-SkipPrerequisiteCheck`는 운영 배포에 사용하지 않는다. `-ExecutionPolicy Bypass`는 서명된 승인 bundle을 실행하는 wrapper에만 사용하고, 조직 정책에서 허용하지 않으면 Authenticode 신뢰 정책에 맞는 실행 명령으로 교체한다.

## 4. 개인 PC 최초 적용

### 권장: 시작 메뉴에서 실행

사용자가 시작 메뉴의 **Company Agent**를 실행한다. 사용자 디렉터리가 없으면 Windows 사용자 이름을 기본 표시 이름으로 사용해 자동 초기화하고 바로 Claude Code를 시작한다. 기본 설치에는 MCP가 없으므로 Outlook 이메일도 묻지 않는다. 나중에 `corp-outlook-self`가 별도로 배포될 때 그 MCP의 사용자 onboarding 절차에서만 본인 계정 정보를 받는다.

기존 `user.json`, Personal Knowledge, Memory, Skill, Tool 후보는 update/reinstall 후에도 보존된다.

### 무인 사용자 초기화

VDI provisioning이나 사용자 컨텍스트 배포가 필요하면 다음을 실행한다.

```powershell
powershell.exe -NoLogo -NoProfile -File `
  'C:\Program Files\CompanyAgent\bin\Initialize-CompanyAgentUser.ps1' `
  -NonInteractive
```

이 스크립트는 반드시 실제 사용자의 비상승 컨텍스트로 실행해야 `%LOCALAPPDATA%`가 해당 직원에게 연결된다. 필요하면 `-DisplayName`을 선택적으로 지정할 수 있고, 미래의 승인된 Outlook MCP onboarding에서만 `-UserEmail`을 사용할 수 있다. 관리자 프로필에 개인 상태를 만들지 않도록 상승된 실행은 기본적으로 거부된다.

초기화 과정은 개인 디렉터리와 빈 `mcp\registry.json`을 만들고 Corporate Base와 Personal Overlay를 합친 `knowledge\generated-index\catalog.json`을 즉시 생성한다.

## 5. 일상 실행과 모델 전환

직접 실행할 수도 있다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Start-CompanyAgent.ps1'
```

특정 시작 모델을 강제로 고를 때만 다음 옵션을 사용한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Start-CompanyAgent.ps1' -ModelTier SMALL
& 'C:\Program Files\CompanyAgent\bin\Start-CompanyAgent.ps1' -ModelTier MEDIUM
& 'C:\Program Files\CompanyAgent\bin\Start-CompanyAgent.ps1' -ModelTier LARGE
```

기본 `AUTO`는 main coordinator에 `--model`을 전달하지 않으므로 사용자가 기존 Claude Code에 설정한 기본 모델을 그대로 유지한다. 이후 각 사용자 prompt는 Plugin router가 난이도와 위험도를 분류해 worker를 선택한다.

```text
SMALL  → 기존 Claude Code `haiku` alias
MEDIUM → 기존 Claude Code `sonnet` alias
LARGE  → 기존 Claude Code `opus` alias
```

일반 `claude-config` 모드의 Launcher는 `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`을 설정하지 않는다. 사용자의 기존 alias 설정이 유일한 모델 매핑 원본이다. 프로세스의 `CLAUDE_CODE_SUBAGENT_MODEL`과 `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`는 Company Agent가 시작한 Claude 자식 프로세스 안에서만 제거하고 Windows 환경은 변경하지 않는다. 사용자·프로젝트·로컬·Windows 관리 설정에서 같은 변수를 강제하면 Claude가 다시 주입할 수 있으므로 Setup/Launcher가 해당 파일·정책 위치와 변수명만 표시하고 실행을 차단한다. 원본 설정을 자동 수정하지 않는다.

각 시작 시 다음 순서가 자동 수행된다.

1. Python과 Claude Code prerequisite 확인
2. 새 Corporate Knowledge와 Personal Overlay의 안전한 자동 reconcile
3. 충돌·분리 항목을 보존하고 사용자에게 경고
4. Effective Knowledge `catalog.json` 재생성
5. 현재 Core를 `--plugin-dir`로 로드
6. Corporate Knowledge, Personal Knowledge, Personal Skill root를 `--add-dir`로 로드
7. Harness MCP가 있을 때만 기존 MCP에 추가하는 `--mcp-config`로 로드(관리자가 명시한 경우에만 strict)
8. `AUTO`이면 기존 main 모델로, 강제 tier이면 해당 alias로 Claude Code 시작

실행 프로세스의 `PATH` 앞에는 현재 Core의 `plugin\bin`만 임시로 추가된다. 따라서 Agent가 사용하는 `company-agent knowledge`, `asset`, `memory`, `session` 명령은 별도 사용자 설치 없이 동작하며, Claude Code가 종료되면 원래 환경으로 복원된다.

따라서 관리자가 Corporate Pack을 업데이트해도 개인 `extend` overlay는 다음 실행에서 안전한 범위 안에서 자동 rebase된다. 충돌 내용은 삭제하지 않고 `%LOCALAPPDATA%\CompanyAgent\knowledge\conflicts`에 남긴다.

## 6. 업데이트

새 ZIP을 별도 staging 폴더에 풀고 상승된 PowerShell에서 실행한다.

```powershell
& 'C:\CompanyAgent-Staging\0.2.0\deploy\Update-CompanyAgent.ps1' `
  -BundleRoot 'C:\CompanyAgent-Staging\0.2.0' `
  -UseExistingClaudeModels `
  -DefaultTier 'AUTO'
```

일반 update는 `deploy\Setup-CompanyAgent.ps1` 또는 새 bundle의 최상위 CMD를 다시 실행하면 된다. 기존 0.1의 명시적 모델 ID 매핑을 유지해야 하는 호환 update가 아니라면 `-UseExistingClaudeModels`로 현재 Claude alias 설정을 사용한다. 모델 ID를 직접 주입하는 explicit-map 모드는 특수 운영 환경을 위한 고급 호환 옵션이며 일반 직원 설치에 사용하지 않는다.

업데이트는 새 버전을 옆에 설치한 뒤 포인터만 전환한다. Config·바로가기·ACL 등 포인터 전환 전 단계가 실패하면 이전 launcher, current/previous 포인터, 바로가기를 자동 복원한다. 다음 경로는 건드리지 않는다.

```text
%LOCALAPPDATA%\CompanyAgent
```

새 버전의 최초 사용자 실행에서 Knowledge reconcile과 index 재생성이 자동 수행된다.

## 7. 즉시 롤백

상승된 PowerShell에서 다음을 실행한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Rollback-CompanyAgent.ps1'
```

`current.json`과 `previous.json`을 원자적으로 교환해 Core, Corporate Knowledge, versioned Session/MCP/런타임 설정을 함께 되돌린다. 한 번 더 실행하면 직전 상태로 다시 전환된다. 개인 상태는 변경되지 않는다. 이전 Core, Knowledge, config 버전 디렉터리 중 하나라도 수동 삭제된 경우 rollback은 활성화 전에 실패한다.

## 8. 삭제

기본 삭제는 시스템 Core와 Corporate Knowledge만 제거하고 개인 상태를 보존한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Uninstall-CompanyAgent.ps1' -Confirm:$false
```

재설치 후 이전 Personal Overlay, Memory, Skill을 이어서 사용할 수 있다. 개인 상태까지 영구 삭제하도록 명시한 경우에만 다음을 사용한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Uninstall-CompanyAgent.ps1' `
  -RemoveUserState `
  -Confirm:$false
```

`-RemoveUserState`는 `%LOCALAPPDATA%\CompanyAgent`의 개인 지식, Skill, MCP, Memory, 이력을 복구 불가능하게 삭제한다. Uninstaller는 관리형 root marker가 없는 경로의 재귀 삭제를 거부한다. 시작 메뉴 링크도 대상이 이 설치의 `CompanyAgent.cmd`일 때만 삭제한다.

## 9. 검증

### 배포 스크립트 smoke test

관리자 권한이나 실제 시스템 경로를 사용하지 않고 임시 디렉터리에서 전체 생명주기를 검증한다.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
  .\deploy\Test-DeploymentSmoke.ps1
```

검증 범위:

- ZIP과 SHA-256 manifest
- 일반 사용자 preflight, 선택 백업, 쉬운 Setup dry-run
- side-by-side 설치와 immutable version
- 사용자 무입력 초기화와 빈 개인 MCP registry
- Corporate+Personal `catalog.json`
- `AUTO` main 모델 보존과 SMALL/MEDIUM/LARGE alias 선택
- 빈 Harness MCP의 기존 MCP 보존과 비어 있지 않은 registry의 merge
- versioned config를 포함한 업데이트, previous pointer, rollback
- 중첩 root 거부와 기존 `.claude` 무수정
- 기본 삭제의 개인 상태 보존
- 명시적인 개인 상태 삭제

### 설치 PC dry-run

Claude 프로세스를 시작하지 않고 실제 arguments와 경로를 확인한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Start-CompanyAgent.ps1' -DryRun |
  Format-List *
```

`current.json`, `catalog.json`, model mode/tier, MCP mode, active Core/Knowledge/config 경로가 모두 표시되어야 한다. 기본 상태의 `modelArgument`는 비어 있고 `mcpConfigMode`는 `existing-only`여야 한다.

## 10. 테스트 전용 경로 override

각 상태 변경 스크립트는 다음 override를 지원한다.

```powershell
-InstallRoot 'C:\Temp\CompanyAgentTest\install'
-DataRoot 'C:\Temp\CompanyAgentTest\data'
-UserStateRoot 'C:\Temp\CompanyAgentTest\user'
-SkipAcl
-SkipAdminCheck
```

이는 개발·CI의 격리 디렉터리에만 사용한다. 운영 배포에서 ACL, 관리자 검사, bundle 검증, prerequisite 검사를 끄면 Corporate Base 변조 방지와 재귀 삭제 보호를 약화시킨다.

## 11. 운영 체크리스트

- [ ] Plugin과 Knowledge 내부 버전을 새 릴리스 번호로 변경했다.
- [ ] MCP를 포함할 경우에만 `managed-mcp.json`을 만들었고 placeholder나 비밀값이 남지 않았다.
- [ ] MCP를 포함할 경우 DB principal 자체가 SELECT-only이고 Outlook MCP가 인증된 본인 mailbox만 송신한다.
- [ ] 대상 PC의 기존 `haiku`, `sonnet`, `opus` alias가 각각 SMALL/MEDIUM/LARGE 모델로 실제 응답한다.
- [ ] 선택 백업 manifest에 `.credentials.json`, 세션/history/projects/cache가 포함되지 않았다.
- [ ] 기존 범용 Skill과 같은 이름의 개인 Skill은 `company-personal-<name>` 등 고유 이름으로 바꿨다.
- [ ] 소스 `.ps1`에 Authenticode 서명을 적용한 뒤 Bundler 기본 validation을 통과했다.
- [ ] 생성된 최종 ZIP에 사내 패키지 서명을 적용했다.
- [ ] Windows PowerShell 5.1 smoke test가 통과했다.
- [ ] Pilot 사용자로 더블클릭 설치, 무입력 최초 실행, 개인 Knowledge 저장, Skill 생성, update 후 reconcile을 확인했다.
- [ ] Intune/SCCM의 install은 System 컨텍스트, 개인 초기화는 user 컨텍스트로 분리했다.
