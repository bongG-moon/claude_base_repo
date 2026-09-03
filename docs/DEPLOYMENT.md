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
  ├─ config                           모델·MCP·Claude 관리 설정
  └─ state\current.json              현재 Core/Knowledge/모델 매핑
           \previous.json            직전 선택, 즉시 Rollback 용도

%LOCALAPPDATA%\CompanyAgent
  ├─ config\user.json                본인 Outlook 주소와 개인 설정
  ├─ knowledge                        Personal Overlay와 합성 인덱스
  ├─ personal-root\.claude\skills    자동 활성화 개인 Skill
  ├─ mcp\registry.json               개인 MCP Registry
  ├─ tools / ledger / sessions
  └─ memory                           추출된 개인 Memory
```

일반 사용자는 Corporate Base를 읽을 수만 있고 `%LOCALAPPDATA%`의 Personal Overlay와 Skill은 계속 발전시킬 수 있다. 업데이트와 기본 삭제는 개인 상태를 변경하지 않는다.

## 1. 사전 조건

- Windows 10/11 또는 대응되는 Windows Server
- Windows PowerShell 5.1 이상
- 사내에서 승인해 오프라인 설치한 Claude Code CLI 2.1.220 이상
- Python 3.11 이상이 `PATH`의 `python`으로 실행 가능할 것
- 최초 설치·업데이트·롤백·삭제 작업용 로컬 관리자 또는 소프트웨어 배포 계정
- 사내 SMALL, MEDIUM, LARGE 모델의 실제 Claude Code 모델 ID

설치와 실행 스크립트는 `claude`와 Python 3.11 이상을 검사하고 조건이 맞지 않으면 즉시 중단한다. 운영 PC에서 `-SkipPrerequisiteCheck`를 사용하면 안 된다.

PowerShell 실행 정책이 `RemoteSigned`인 환경을 고려해 **번들을 만들기 전에** 소스의 `deploy\*.ps1`에 사내 코드 서명을 적용하고 서명 인증서를 신뢰 체인에 배포한다. ZIP의 SHA-256 manifest는 파일 손상을 검출하지만 배포 주체의 신원을 증명하지는 않으므로 생성된 ZIP에도 사내 패키지 서명을 별도로 적용한다.

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

Bundler가 이 일치를 강제로 검사한다. 동일 버전 경로에 내용이 다른 Core 또는 Knowledge를 덮어쓸 수 없으므로 내용이 변경되면 반드시 새 버전을 부여한다.

### 2.2 MCP 설정

실제 배포 전 예시 파일을 복사해 실제 파일을 만든다.

```powershell
Copy-Item .\config\managed-mcp.example.json .\config\managed-mcp.json
```

`managed-mcp.json`에서 다음 두 서버의 사내 실행 명령을 설정한다.

- `corp-db-read`: 서버 자체에서도 SELECT-only를 강제해야 한다.
- `corp-outlook-self`: 서버 자체에서도 초기화된 본인 계정만 송신하도록 강제해야 한다.

두 MCP 도구를 Claude 설정의 `permissions.allow`에 직접 추가하지 않는다. 정상 호출은 PreToolUse Hook이 승인하지만 Hook이 실행되지 못한 경우에는 Claude Code의 일반 권한 확인으로 되돌아가야 한다. 다만 프로세스 강제 종료나 timeout까지 Hook만으로 보안 경계로 만들 수는 없으므로 서버 측 권한 강제가 필수다.

Hook 검사는 2차 방어선이다. DB 계정 권한과 MCP 서버 권한을 실제 보안 경계로 유지한다. 토큰, 비밀번호, DB 접속 문자열을 Markdown이나 ZIP에 넣지 말고 Windows Credential Manager 또는 승인된 사내 비밀 저장소를 사용한다.

선택적으로 다음 파일을 실제 이름으로 제공하면 번들에 포함된다.

```text
config\managed.json
config\managed.settings.json
config\managed-mcp.json
```

`managed.json`의 모델 ID와 설치 경로는 설치 매개변수 기준으로 다시 생성된다. 실제 `managed.settings.json`이 없으면 installer가 `haiku`, `sonnet`, `opus`만 허용하는 기본 설정을 생성한다.

### 2.3 오프라인 ZIP 생성

저장소 루트에서 실행한다.

```powershell
powershell.exe -NoLogo -NoProfile -File .\deploy\New-OfflineBundle.ps1 `
  -CoreVersion '0.1.0' `
  -KnowledgeVersion '2026.09.03' `
  -OutputPath 'D:\Release\company-agent-0.1.0-2026.09.03.zip'
```

기본 릴리스 검사는 다음 순서로 수행되며 하나라도 실패하면 ZIP을 만들지 않는다.

1. Plugin/Knowledge 내부 버전과 명령행 버전 일치
2. `claude plugin validate --strict`
3. `harness_cli.py knowledge validate`
4. Python `compileall`
5. payload 파일별 SHA-256·길이 manifest 생성

`.git`, `__pycache__`, `*.pyc`, pytest/mypy/ruff/tox 캐시 및 coverage 산출물은 staging에서 제외된다. 소스는 삭제하거나 수정하지 않는다. `-SkipSourceValidation`은 격리된 배포 스크립트 테스트에만 사용한다.

## 3. 관리자 설치

ZIP을 로컬 staging 폴더에 압축 해제한 후 상승된 Windows PowerShell에서 실행한다.

```powershell
Expand-Archive `
  -LiteralPath 'D:\Release\company-agent-0.1.0-2026.09.03.zip' `
  -DestinationPath 'C:\CompanyAgent-Staging\0.1.0'

powershell.exe -NoLogo -NoProfile -File `
  'C:\CompanyAgent-Staging\0.1.0\deploy\Install-CompanyAgent.ps1' `
  -BundleRoot 'C:\CompanyAgent-Staging\0.1.0' `
  -SmallModelId  'INTERNAL_SMALL_MODEL_ID' `
  -MediumModelId 'INTERNAL_MEDIUM_MODEL_ID' `
  -LargeModelId  'INTERNAL_LARGE_MODEL_ID' `
  -DefaultTier 'MEDIUM'
```

Installer는 다음을 수행한다.

- Bundle manifest의 모든 파일 hash와 manifest에 기록되지 않은 모든 번들 파일을 검사한다.
- Core와 Corporate Knowledge를 side-by-side 불변 버전 경로에 설치한다.
- 모델 매핑과 관리형 Claude/MCP 설정을 `ProgramData`에 기록한다.
- 기존 `current.json`을 `previous.json`으로 보존한 뒤 새 포인터를 원자적으로 활성화한다.
- 일반 사용자에게 `Program Files`와 `ProgramData`의 읽기/실행만 허용하는 ACL을 설정한다.
- 모든 사용자 시작 메뉴에 `Company Agent` 바로가기를 만든다.
- `%USERPROFILE%\.claude`의 파일을 생성·수정·삭제하지 않는다.

대량 배포에서 `Install-CompanyAgent.ps1`은 System/관리자 컨텍스트로 실행한다. Intune Win32 app 또는 SCCM의 install command에는 위 명령을 사용하고 세 모델 ID를 조직의 실제 값으로 고정한다. `-SkipAcl`, `-SkipAdminCheck`, `-SkipBundleVerification`은 운영 배포에 사용하지 않는다.

## 4. 개인 PC 최초 적용

### 권장: 시작 메뉴에서 실행

사용자가 시작 메뉴의 **Company Agent**를 실행한다. 최초 한 번 다음 두 값을 알기 쉬운 prompt로 입력한다.

1. 본인의 사내 Outlook 이메일 주소
2. Agent가 사용할 표시 이름

그 뒤에는 동일 정보를 다시 묻지 않는다. 기존 `user.json`의 다른 설정은 보존되며 누락된 필드만 채운다.

### 무인 사용자 초기화

VDI provisioning이나 사용자 컨텍스트 배포가 필요하면 다음을 실행한다.

```powershell
powershell.exe -NoLogo -NoProfile -File `
  'C:\Program Files\CompanyAgent\bin\Initialize-CompanyAgentUser.ps1' `
  -UserEmail 'employee@company.internal' `
  -DisplayName '홍길동' `
  -NonInteractive
```

`-NonInteractive`에서 이메일이나 표시 이름이 빠지면 안전하게 실패한다. 이 스크립트는 반드시 실제 사용자의 컨텍스트로 실행해야 `%LOCALAPPDATA%`와 Outlook 본인 계정 경계가 올바르게 연결된다.

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

기본 `AUTO`는 `DefaultTier`로 coordinator를 시작한다. 이후 각 사용자 prompt는 Plugin router가 난이도와 위험도를 분류해 worker를 선택한다.

```text
SMALL  → haiku alias  → INTERNAL_SMALL_MODEL_ID
MEDIUM → sonnet alias → INTERNAL_MEDIUM_MODEL_ID
LARGE  → opus alias   → INTERNAL_LARGE_MODEL_ID
```

Launcher는 실행 프로세스에만 `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`을 설정한다. `CLAUDE_CODE_SUBAGENT_MODEL`은 모든 worker 모델을 하나로 덮어쓰므로 의도적으로 설정하지 않는다.

각 시작 시 다음 순서가 자동 수행된다.

1. Python과 Claude Code prerequisite 확인
2. 새 Corporate Knowledge와 Personal Overlay의 안전한 자동 reconcile
3. 충돌·분리 항목을 보존하고 사용자에게 경고
4. Effective Knowledge `catalog.json` 재생성
5. 현재 Core를 `--plugin-dir`로 로드
6. Corporate Knowledge, Personal Knowledge, Personal Skill root를 `--add-dir`로 로드
7. 관리형 MCP와 개인 MCP registry만 `--mcp-config ... --strict-mcp-config`로 로드
8. 선택된 alias로 Claude Code 시작

실행 프로세스의 `PATH` 앞에는 현재 Core의 `plugin\bin`만 임시로 추가된다. 따라서 Agent가 사용하는 `company-agent knowledge`, `asset`, `memory`, `session` 명령은 별도 사용자 설치 없이 동작하며, Claude Code가 종료되면 원래 환경으로 복원된다.

따라서 관리자가 Corporate Pack을 업데이트해도 개인 `extend` overlay는 다음 실행에서 안전한 범위 안에서 자동 rebase된다. 충돌 내용은 삭제하지 않고 `%LOCALAPPDATA%\CompanyAgent\knowledge\conflicts`에 남긴다.

## 6. 업데이트

새 ZIP을 별도 staging 폴더에 풀고 상승된 PowerShell에서 실행한다.

```powershell
& 'C:\CompanyAgent-Staging\0.2.0\deploy\Update-CompanyAgent.ps1' `
  -BundleRoot 'C:\CompanyAgent-Staging\0.2.0'
```

모델 ID 매개변수를 생략하면 기존 매핑이 유지된다. 모델도 바꾸려면 `-SmallModelId`, `-MediumModelId`, `-LargeModelId`, `-DefaultTier`를 함께 지정한다.

업데이트는 새 버전을 옆에 설치한 뒤 포인터만 전환한다. 다음 경로는 건드리지 않는다.

```text
%LOCALAPPDATA%\CompanyAgent
```

새 버전의 최초 사용자 실행에서 Knowledge reconcile과 index 재생성이 자동 수행된다.

## 7. 즉시 롤백

상승된 PowerShell에서 다음을 실행한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Rollback-CompanyAgent.ps1'
```

`current.json`과 `previous.json`을 원자적으로 교환해 Core, Corporate Knowledge, 모델 매핑을 함께 되돌린다. 한 번 더 실행하면 직전 상태로 다시 전환된다. 개인 상태는 변경되지 않는다. 이전 버전 디렉터리가 수동 삭제된 경우 rollback은 활성화 전에 실패한다.

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
- side-by-side 설치와 immutable version
- Outlook 본인 identity와 개인 MCP registry
- Corporate+Personal `catalog.json`
- SMALL/MEDIUM/LARGE alias 환경 매핑
- 관리형·개인 MCP의 strict scope
- 업데이트와 previous pointer
- rollback
- 기본 삭제의 개인 상태 보존
- 명시적인 개인 상태 삭제

### 설치 PC dry-run

Claude 프로세스를 시작하지 않고 실제 arguments와 경로를 확인한다.

```powershell
& 'C:\Program Files\CompanyAgent\bin\Start-CompanyAgent.ps1' -DryRun |
  Format-List *
```

`current.json`, `catalog.json`, 두 MCP config, 세 모델 alias, active Core/Knowledge 경로가 모두 표시되어야 한다.

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
- [ ] `managed-mcp.json`에 placeholder나 비밀값이 남지 않았다.
- [ ] DB MCP 계정 자체가 SELECT-only다.
- [ ] Outlook MCP가 초기화된 사용자의 mailbox만 송신한다.
- [ ] 세 사내 모델 ID가 Claude Code에서 실제로 응답한다.
- [ ] 소스 `.ps1`에 Authenticode 서명을 적용한 뒤 Bundler 기본 validation을 통과했다.
- [ ] 생성된 최종 ZIP에 사내 패키지 서명을 적용했다.
- [ ] Windows PowerShell 5.1 smoke test가 통과했다.
- [ ] Pilot 사용자로 최초 prompt, 개인 Knowledge 저장, Skill 생성, update 후 reconcile을 확인했다.
- [ ] Intune/SCCM의 install은 System 컨텍스트, 개인 초기화는 user 컨텍스트로 분리했다.
