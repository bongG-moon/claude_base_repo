# Company Agent 설치와 배포 — Windows

현재 공개 배포 버전은 **1.4.23**입니다. 직원은 회사가 승인한 [1.4.23 Release](https://github.com/bongG-moon/claude_base_repo/releases/tag/v1.4.23)의 설치 ZIP 또는 별도로 승인된 후속 배포본을 사용합니다. **1.4.23에는 기본 Office 읽기 스킬과 전용 실행·승인 연결 제거, 학습·스킬 선택 보완, 안내서 갱신을 포함합니다.** 기존 Release·ZIP·설치된 PC는 자동 갱신되지 않습니다. [1.4.23 변경 내용](UPDATE_1.4.23.md)과 [배포 검증 범위](https://github.com/bongG-moon/claude_base_repo/blob/v1.4.23/docs/VALIDATION_RELEASE_1.4.23.md)를 확인하세요. 과거 버전의 변경·검증 기록은 당시 배포 내용이며 현재 기능 목록으로 사용하지 않습니다.

관련 스킬 우선 적용·관련 스킬이 없을 때 일반 실행·중복 후보 선택·개인 자료 보존은 유지합니다. 실제 회사 DRM·Office·사내 모델 연동과 체감 속도는 운영 PC에서 별도로 확인해야 합니다. 기존 설치 PC는 같은 범위로 업데이트하며 개인 자료와 기존 규칙·Hook을 유지합니다. 자동 학습은 기본 활성화이며 Claude에서 “자동 학습을 잠시 멈춰줘”라고 변경할 수 있습니다. ZIP 생성 자체는 게시를 수행하지 않습니다.

직원 PC에는 Claude Code와 사내 SMALL/MEDIUM/LARGE 연결, 회사 승인 Python 3.11 이상이 이미 준비되어 있어야 합니다. 기본 ZIP에는 Python 실행 파일과 DLL을 넣지 않고 PC의 Python을 사용합니다. 설치 과정에서 Python/pip/Git를 설치하거나 다운로드하지 않으며 PC의 PATH 설정도 바꾸지 않습니다. 설치 조건은 Claude Code CLI 2.1.220 이상, Windows PowerShell 5.1 이상, Windows 10/11입니다. 대상 PC의 운영체제와 Python 아키텍처는 사내 담당자가 확인합니다.

## 직원이 하는 일

배포 전 1.0.0 설치 파일에서 `cp949 codec can't encode character` 오류를 겪었다면 수정 ZIP을 **새 폴더에 완전히 압축 해제**하여 실행합니다. 기존 Skill 설명을 지우거나 Python/Windows 언어를 재설정하지 않습니다. 수정본은 설치기의 Python 입출력을 UTF-8로 처리하고, JSON의 한글·특수문자·경로를 손실 없이 복원합니다. Skill 검사에서 중단됐다면 백업·기존 규칙 비활성화 이전 단계입니다. 이미 다른 1.0.0 내용으로 설치에 성공한 환경에서 ‘같은 버전의 내용이 다름’ 오류가 나오면 보호 검사를 우회하거나 개인 저장 영역을 지우지 말고 담당자에게 확인합니다.

1. 열려 있는 Claude Code를 닫고 ZIP을 로컬 폴더에 모두 압축 해제합니다.
2. 최상위 `Install-CompanyAgent.cmd`를 평소처럼 더블클릭합니다. 별도로 ‘관리자 권한으로 실행’을 선택할 필요는 없습니다.
3. **Claude 전체** 또는 **이 프로젝트만**을 선택합니다. 프로젝트라면 대상 폴더도 선택합니다.
4. 같은 범위에 Company Agent가 있으면 **기존 버전 → 새 버전**을 확인하고 1번 업데이트 또는 2번 현재 버전 유지를 선택합니다. 같은 버전이면 다시 적용/복구로 안내합니다. 다른 하네스만 있으면 **기존 하네스 유지** 또는 **백업 후 Company Agent 설치**를 선택하고, 없으면 다음 단계로 진행합니다.
5. 자동 확인된 본인 계정과 Claude 실행 파일·설정 위치를 확인합니다. Claude 후보 선택이 필요할 때만 평소 쓰는 파일을 고릅니다. Python도 자동으로 찾으며, 찾을 수 없을 때만 회사 승인 `python.exe`의 경로를 입력합니다. 경로를 모르면 사내 담당자에게 확인합니다.
6. 들어오는 Skill과 같은 이름이 있으면 후보의 출처를 확인하고 **기존 선택 유지** 또는 **새 Company Agent Skill 우선**을 고릅니다. 겹침이 없으면 추가 질문 없이 진행합니다.
7. 설치·업데이트·다시 적용이 완료되면 Claude Code를 다시 실행합니다. ‘유지’는 설치·변경 없이 종료하므로 재시작할 필요가 없습니다.

결과의 `status: installed`는 처음 설치, `updated`는 버전 변경, `reapplied`는 같은 버전 다시 적용 완료입니다. `kept`는 변경 없이 유지, `input-required`는 아직 선택이 필요하다는 뜻입니다. `operation`에는 `install`/`update`/`reapply`가 표시되고, 버전 변경은 `previousCoreVersion`과 `coreVersion`으로 확인합니다. 출력된 개인 자료 위치와 백업 위치도 보관하세요.

| 선택 | 적용되는 곳 | 자동 기록되는 Claude 설정 | 관리자 권한 |
| --- | --- | --- | --- |
| Claude 전체 / User | 현재 Windows 사용자의 Claude 작업 전체 | 사용자 settings.json의 플러그인 등록 | 불필요 |
| 이 프로젝트만 / Project | 선택한 프로젝트와 하위 폴더 | 프로젝트 .claude/settings.local.json의 플러그인 등록 | 불필요 |

‘전체’는 본인 Windows 계정의 Claude 환경입니다. PC의 모든 직원이나 전사 PC를 즉시 변경하는 기능은 아닙니다. 같은 ZIP을 직원에게 배포하면 같은 공통 하네스를 각각 설치합니다. Project 설치는 Claude의 `local` scope를 사용하여 PC별 설치 경로가 공유 settings.json에 들어가지 않게 합니다.

두 범위를 함께 사용할 수 있습니다. 동일한 플러그인 ID `company-agent@company-agent-local`를 사용하고, 가장 가까운 프로젝트 등록이 개인 상태를 선택합니다. 해당 프로젝트 밖에서는 User 상태를 사용합니다. Project만 설치한 PC에서는 다른 프로젝트에 활성화되지 않습니다.

현재 배포본은 한 Windows 계정에서 하나의 Claude 설정 프로필을 지원합니다. 별도 지정이 없으면 같은 범위의 기존 등록에 저장된 설정 위치를 재사용합니다. 다른 `CLAUDE_CONFIG_DIR` 프로필로 기존 등록을 덮어쓰려 하면 중단합니다.

전용 실행기 없이 평소처럼 Claude를 사용합니다. 프로젝트에서 다음처럼 요청할 수 있습니다.

> 이 프로젝트의 내용을 먼저 확인하고, 이 일을 잘 수행할 수 있는 하네스를 구성해줘. 꼭 필요한 내용만 물어봐줘.

## 계정과 Claude 위치를 확인하는 방법

설치기의 확인 대상은 **지금 로그인해 사용하는 본인의 Windows 환경**입니다. Claude 실행 파일이 있는 폴더와 모델·MCP·Skill을 보관하는 개인 설정 폴더는 다를 수 있으므로 따로 확인합니다. 프로그램 위치만으로 계정이나 개인 저장 위치를 결정하지 않습니다.

- 실행 중인 Windows 계정이 같은 세션에서 실제 로그인한 사용자와 일치하고, 개인 폴더도 그 사용자의 것인지 확인합니다. 같은 사용자로 확인된 높은 권한 실행은 허용합니다.
- 다른 계정으로 실행했거나 서비스 실행, 사용자·세션·개인 폴더 확인 실패인 경우 설치 대상 파일을 변경하기 전에 중단합니다. 다른 직원의 폴더를 탐색해 그쪽에 설치하지 않습니다.
- Claude는 현재 실행 경로(PATH)와 현재 사용자의 일반적인 설치 위치를 확인합니다. 후보가 없거나 여러 개여서 선택이 필요하면 직접 설치에서는 후보를 고르거나 실제 경로를 입력받습니다. 전체 디스크나 다른 사용자의 프로필을 무차별 검색하지 않습니다.
- Claude 설정 위치는 명시한 `-ClaudeConfigRoot` → 현재 `CLAUDE_CONFIG_DIR` → 같은 범위의 정상 기존 설치 기록 → 본인의 기본 `%USERPROFILE%\.claude` 순으로 결정합니다. 기존 기록과 명시한 프로필이 다르면 덮어쓰지 않고 중단합니다. 화면에서 실제 사용 경로와 선택 근거를 확인할 수 있습니다.
- 기존 등록의 개인 자료 위치는 그대로 재사용합니다. Claude 실행 파일을 새로 찾았다는 이유로 개인 Memory·Skill·Knowledge를 다른 위치로 옮기지 않습니다. 모델·MCP 설정 내용이나 비밀번호를 새로 입력할 필요도 없습니다.

Claude 후보가 없거나 여러 개일 때 `-NonInteractive` 또는 `-DryRun`은 `status: input-required`, `input: ClaudeCommand`와 후보 목록을 반환합니다. 이것은 설치 완료가 아닙니다. Claude에게 설치를 맡긴 경우 사용자가 평소 사용하는 파일을 확인하고 아래처럼 실제 경로를 지정해 다시 점검합니다. 경로는 예시이며 그대로 복사하지 않습니다.

```powershell
powershell.exe -NoProfile -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -ClaudeCommand "C:\Users\본인계정\.local\bin\claude.exe" -NonInteractive -DryRun
```

### 그냥 더블클릭했는데 관리자 오류가 나왔을 때

1.1.1의 `Run this installer from your normal Windows account` 오류는 권한이 부족하다는 뜻이 아니라, 설치기가 높은 권한 실행을 일괄 차단했다는 뜻입니다. 회사 PC 설정에 따라 일반 더블클릭에서도 나타날 수 있습니다. **1.1.2 ZIP 전체를 새 폴더에 풀고**, 같은 최상위 `Install-CompanyAgent.cmd`를 다시 더블클릭합니다. 기존 설치가 있으면 이전과 같은 범위를 선택하여 업데이트합니다. 1.1.1의 이 사전 검사에서 실패한 것만으로 기존 자료를 지우거나 재설치할 필요는 없습니다.

1.1.2에서도 사용자 확인 오류가 나면 오류 문구와 표시된 계정·설정 위치만 사내 담당자에게 전달하세요. 본인 계정인지 확인되지 않은 상태에서 진행하지 않습니다. UAC나 회사 보안 정책을 끄거나, `-SkipAdminCheck` 같은 보호 검사 생략 옵션으로 해결하지 않습니다. 이미 설치된 Claude와 Python을 삭제할 필요도 없습니다. 사전 검사에서 중단되면 백업이 아직 만들어지지 않았을 수 있으며, 화면에 백업 위치가 없다면 백업 완료로 해석하지 않습니다.

## Claude에게 설치 맡기기

압축을 푼 폴더의 `INSTALL_WITH_CLAUDE.md`를 Claude에 주고 “이 지침대로 설치해줘” 또는 “기존 Company Agent를 업데이트해줘”라고 요청합니다. 적용 범위와 필요한 경우 대상 프로젝트를 받고 Dry Run으로 확인합니다. 기존 Company Agent면 업데이트/유지, 다른 하네스면 유지/교체를 구분합니다. 이미 말한 선택은 다시 묻지 않도록 지침에 반영했습니다. 모델 ID, 비밀번호, MCP, Outlook 정보는 요구하지 않습니다.

운영자용 단일 명령 예시:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -NonInteractive

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope Project -ProjectRoot "C:\Work\Report" -NonInteractive
```

사전 점검만 하려면 같은 명령에 `-DryRun`을 추가합니다. 범위 없는 무인 실행은 선택을 추측하지 않고 필요한 인자를 안내합니다. 조직이 실행 정책을 강제한 경우 사내 서명 정책에 맞춰 실행합니다.

설치기는 `python`, `py`로 실행할 수 있는 Python을 찾아 실제 버전이 3.11 이상인지 확인합니다. 찾으면 별도 경로 입력 없이 진행합니다. 자동 탐색으로 찾지 못한 경우 직접 설치는 경로를 물으며, `-NonInteractive` 실행은 필요한 런타임과 재실행 방법을 안내하고 설치를 중단합니다. 승인 Python의 실제 경로를 알고 있다면 아래처럼 지정합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -PythonCommand "C:\ApprovedPython\python.exe" -NonInteractive -DryRun
```

`C:\ApprovedPython\python.exe`는 예시입니다. PC에 설치된 실제 경로로 바꾸세요. 승인 Python이 없거나 버전이 낮으면 사내 담당자가 준비한 뒤 재실행합니다. 설치기는 실행과 버전 호환성을 검사하며 회사의 승인 여부를 판정하지는 않습니다. 설치기가 Python이나 pip를 내려받거나 설치하지 않습니다. 설치 후 승인 Python 경로가 바뀌면 새 경로로 다시 점검·설치해야 합니다.

`-ExistingHarnessAction Ask|Keep|Replace|Update`의 기본값은 `Ask`입니다. 같은 범위에 정상 Company Agent 등록이 있는 무인 `Ask`는 `status: input-required`, `input: ExistingHarnessAction`, `choices: Update/Keep`를 반환합니다. 다른 하네스만 있으면 `choices: Keep/Replace`입니다.
Claude 설치 위임이나 배포 자동화는 이 결과를 사용자에게 보여 주고 필요한 선택을 받아야 합니다. 사용자가 이미 요청한 일반 업데이트에는 `Update`를 사용하며 `Replace`를 대신 지정하지 않습니다. `Update`는 같은 범위의 정상 Company Agent 등록이 있을 때만 유효합니다.
Dry Run은 기존 하네스 목록과 요청한 선택을 읽기 전용으로 보여 주며 백업·비활성화·설치를 실행하지 않습니다.

사용자가 기존 Company Agent 업데이트를 요청한 경우입니다. 같은 버전이면 다시 적용/복구로 진행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -ExistingHarnessAction Update -NonInteractive
```

다른 하네스의 규칙·Hook 비활성화와 새 설치를 사용자가 선택한 경우입니다. 유지라면 `Replace` 대신 `Keep`을 사용합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -ExistingHarnessAction Replace -NonInteractive
```

## 들어오는 Skill과 겹칠 때

설치기는 기존 Skill과 이번 플러그인의 Skill 이름·출처를 함께 보여 줍니다. frontmatter `name` 또는 폴더 이름을 대소문자 구분 없이 비교하며, 의미가 비슷한 다른 이름이나 MCP·Tool 전체의 중복을 판정하지는 않습니다. 겹침이 있는 경우에만 `-SkillConflictAction Ask|KeepCurrent|PreferIncoming`으로 선택합니다.

`Ask`가 기본값입니다. 충돌이 있는 무인 `Ask`는 `status: input-required`, `input: SkillConflictAction`을 반환하므로 사용자 선택 후 다시 실행합니다. `KeepCurrent`는 이미 저장된 선호 설정을 유지하고 새 후보도 설치합니다. 기존 Skill이 항상 이긴다는 의미는 아닙니다. `PreferIncoming`은 백업 후 새 Company Agent 후보를 겹친 이름의 우선 선택으로 저장합니다. 설치가 실패하면 설치기가 변경한 선택도 복구합니다. Dry Run은 어느 선택에서도 기록하지 않습니다.

사용자가 기존 하네스 교체와 새 Skill 우선을 모두 선택한 예시입니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Setup-CompanyAgent.ps1 -Scope User -ExistingHarnessAction Replace -SkillConflictAction PreferIncoming -NonInteractive
```

기존 하네스의 `Keep`은 설치 자체를 하지 않는 선택이므로 위 Skill 선택과 구별합니다. Skill 파일은 그대로 보존하며 플러그인 네임스페이스로 함께 사용할 수 있습니다. 이 선호 설정은 Company Agent의 검색·컨텍스트·선택된 파일 읽기에 적용하고, Claude의 일반 `/Skill명` 우선순위는 바꾸지 않습니다. 설치 후 `/company-agent:skills`로 목록을 보고 이름별·프로젝트별 후보와 출처 순서를 바꿀 수 있습니다. [사용법과 적용 범위](SKILL_PRIORITY.md)

## 기존 Company Agent 업데이트와 다른 하네스 교체 구분

감지는 설치 대상으로 선택한 범위에서 수행합니다. 모델·MCP만 설정되어 있거나 독립 Skill만 있는 경우에는 기존 하네스로 판정하지 않습니다.
같은 범위에 Company Agent가 정상 등록되어 있으면 현재 Core/Knowledge와 패키지 버전을 보여 주는 업데이트 화면이 나옵니다. 1번은 백업 후 업데이트(기본값), 2번은 현재 버전 유지입니다. 두 버전이 모두 같으면 업데이트 대신 다시 적용/복구로 안내합니다. 사용자가 추가한 규칙·Hook이 함께 발견되어도 일반 `Update`에서는 그대로 두며, 다른 하네스처럼 비활성화하지 않습니다.

아래 표는 별도로 명시한 `Replace`에만 적용됩니다. 기존 Company Agent에도 운영자가 `Replace`를 명시할 수 있지만, 일반 업데이트에 필요한 절차는 아닙니다.

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

현재 로그인 사용자·실행 계정·세션·개인 폴더의 일치, Claude 실행 파일과 설정 폴더·버전, 승인 Python의 실행과 3.11 이상 여부, 번들 해시, 대상 경로와 기존 플러그인을 확인합니다. 기존 모델 별칭 haiku/sonnet/opus를 그대로 사용하며 API shim을 만들지 않습니다. 모든 subagent를 한 모델로 강제하는 설정이 있으면 해당 문제를 안내합니다.

Python 경로가 바뀌면 같은 설치 파일을 다시 실행하여 새 경로를 선택할 수 있습니다. 버전별 `runtime-selection.json`에 확인된 실행 경로를 기록하므로 Claude의 캐시에 예전 경로가 남아 있어도 새 경로를 사용합니다. 같은 Core 버전을 사용하는 User/Project 범위는 이 하네스 실행용 Python 선택을 공유합니다. 설치 실패 시 이전 선택으로 복구하며 개인 Memory는 이동하지 않습니다. 별도로 생성한 개인 MCP의 실행 환경은 자동 교체하지 않으므로 [개인 MCP의 Python 경로 변경 안내](STATE_PRESERVATION.md#개인-mcp의-python-경로가-바뀐-경우)를 따릅니다.

Claude native CLI의 설정 저장 과정에서 정밀도가 달라질 수 있는 큰 정수 리터럴(`±9007199254740991` 범위 초과)이 기존 설정에 있으면 변경 전에 중단합니다.
해당 항목이 문자열을 허용하는 경우 담당자와 확인하여 수정한 뒤 재시도합니다. 설치기가 값을 임의 변환하지 않으며, 이 검사는 모든 소수·지수 표기의 정밀도를 검증하는 기능은 아닙니다.

설정 변경 전에 아래 위치로 선택 백업합니다.

```text
%LOCALAPPDATA%\CompanyAgent-Backups\pre-install-<시각>-<ID>
```

User는 앞서 확인한 실제 Claude 설정 폴더를 사용하며, 기본값은 `%USERPROFILE%\.claude`입니다. Project는 여기에 대상 프로젝트의 `.claude`도 추가합니다. 명시한 설정 위치, `CLAUDE_CONFIG_DIR` 또는 기존 등록으로 별도 위치를 확인했다면 그 경로가 기준입니다.

- settings*.json, Markdown 지시 파일, Skill, Agent, Command, Hook
- 플러그인 등록 JSON과 기존 Company Agent 등록
- 개인 Memory 원본/수정 이력, Knowledge entries/overlays/versions, 개인 Skill, 사용자 설정 및 있는 경우 State 형식 표시

Skill 선택은 현재 개인 State의 `config/skill-preferences.json`에 있는 `defaults`와 `projects`에 기록됩니다. 기존 선택은 업데이트에서 보존하며 위 개인 설정 백업에 포함합니다.

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
   ├─ knowledge\                 관리자 Markdown Base
   └─ config\                    배포 설정

%LOCALAPPDATA%\CompanyAgent\
├─ installations\user\
├─ installations\projects\<경로해시>\
└─ states\
   ├─ user\                      사용자 Memory / Knowledge / Skill
   └─ projects\<경로해시>\         프로젝트별 Memory / Knowledge / Skill
```

기본 설치는 위 공통 Core와 별도로, PC에 이미 설치된 승인 Python 경로를 사용합니다. Python을 복사하거나 그 설치 폴더를 변경하지 않습니다. 관리자가 `-IncludeBundledPython`으로 만든 선택 패키지에만 `plugin\runtime\python\`과 Python 라이선스가 추가됩니다.

사용자 권한의 로컬 설치입니다. 설치 프로그램이 Core와 개인 상태를 구분해 보존하지만 사용자가 OS 권한으로 Core를 직접 편집하는 것까지 금지하는 영역은 아닙니다. DB와 Outlook의 보안 경계는 사내 MCP와 계정 권한으로 집행합니다. 관리자 ACL로 Core를 보호하는 기존 machine 배포는 별도 경로로 유지합니다.

Core, Knowledge, 설정이 바뀌면 관리자에게 새 CoreVersion의 ZIP을 받습니다. 새 ZIP을 새 폴더에 풀고 설치 파일을 다시 실행하여 기존 범위를 선택합니다. Company Agent 업데이트 화면에서 이전 버전 → 새 버전을 확인하고 업데이트를 선택하면 갱신됩니다. 기존 개인 저장 위치, 개인 기억·지식·스킬·자동 학습 설정과 사용자가 추가한 규칙·Hook은 유지됩니다. ‘현재 버전 유지’를 선택하면 업데이트도 하지 않습니다. User와 여러 Project scope를 쓰면 각 scope를 갱신하고 Claude를 재시작합니다.

동일 Core/Knowledge 버전은 다시 적용/복구로 표시하며 Python 실행 경로 재선택 등 설치 확인 절차를 다시 수행합니다. 같은 버전의 내용이 다르다는 보호 검사는 유지하므로, 배포 내용을 바꿀 때는 새 CoreVersion을 발급해야 합니다. 더 오래된 숫자 버전으로 내리는 일반 설치는 차단합니다. 등록 형식·플러그인 식별자·Claude 설정 위치가 맞지 않으면 처음 설치로 간주하지 않고 중단하며, 개인 자료나 등록 파일을 지워 우회하지 않습니다.

동일 scope의 기존 등록에 저장된 `userStateRoot`를 기본 경로보다 우선합니다. 처음 지정한 개인 경로를 업데이트 때 다시 입력할 필요가 없습니다. 기존 등록과 다른 `-UserStateRoot`는 자동 이관을 뜻하지 않으므로 파일·등록을 바꾸기 전에 거절합니다. User↔Project 변경이나 프로젝트 경로 이동 역시 별도 상태이며 자동 병합하지 않습니다.

설치 전 `state check`는 개인 State의 형식 표시와 사용자 설정 형식을 읽기 전용으로 확인합니다. 지원하지 않는 미래 버전/손상된 표시가 있으면 초기화하지 않고 중단합니다. 기존 형식 표시가 없는 State는 호환 대상으로 읽습니다. 이는 호환성 보호 장치이지 일반 마이그레이션 엔진은 아닙니다.

개인 Knowledge는 Corporate Base와 분리된 Markdown overlay입니다. `extend`는 이전 Base의 계약 해시가 새 Base의 계약 해시와 같을 때만 안전한 자동 갱신 대상입니다. 계약이 바뀌거나 비교할 기존 해시가 없으면 충돌로 남기며, `fork`의 Base 변경도 사용자가 검토합니다. 회사 원본에서 대상이 없어져도 개인 자료는 삭제하지 않습니다. 현재 설치의 상태 갱신과 모든 별도 프로젝트 저장소의 색인 갱신을 같은 것으로 간주하지 말고, 업데이트 후 실제 사용하는 범위의 지식 출처·충돌 상태를 확인합니다. 자세한 기준은 [관리자 지식 안내](ADMIN_KNOWLEDGE_GUIDE.md)를 참고하세요.

개인 Skill은 선택한 개인 저장 범위에 저장됩니다. 매 요청에 관련 Skill 정보를 찾고 Claude가 SKILL.md를 읽어 사용합니다. 모든 개인 Skill이 슬래시 메뉴에 표시된다는 의미는 아닙니다. Factory가 프로젝트 .claude/skills와 .claude/agents에 생성한 파일은 Claude가 직접 발견합니다.

Skill 선호 설정은 현재 경로에 가장 가까운 프로젝트 설정을 같은 State의 기본값보다 우선합니다. User 설치 하나로 여러 프로젝트를 쓰는 경우에는 기본값과 프로젝트별 예외를 같은 State에 기록합니다. 별도 Project 설치는 자기 State를 사용하므로 User 설치나 다른 Project 설치의 선호를 자동 공유하지 않습니다. 선택한 후보가 사라지면 오래된 선택으로 알리고 다시 고르도록 하며 다른 후보로 조용히 대체하지 않습니다.

## 제거와 재설치

설치 도중 실패했을 때의 자동 복구, 개인 자료 선택 복원, 교체 전 하네스 복구는 서로 다릅니다. **성공한 User/Project 업데이트를 한 명령으로 이전 공통 버전으로 되돌리는 기능은 현재 제공하지 않습니다.** 일반 설치기의 숫자 버전 하향 차단을 우회하지 마세요. `Rollback-CompanyAgent.ps1`는 별도 관리자용 Machine 설치 경로의 도구이며 이 User/Project 절차에 쓰지 않습니다. [보존과 복구 안내](STATE_PRESERVATION.md)를 기준으로 담당자와 복구 대상을 먼저 확인합니다.

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

다음 명령은 **소스 저장소 루트**에서 실행합니다. 빌드 PC에도 승인 Python 3.11 이상과 Claude Code CLI 2.1.220 이상이 준비되어 있어야 합니다. 기본 빌드는 외부에서 Python을 내려받지 않습니다. 아래 꺾쇠 항목은 담당자가 확정한 버전으로 바꾸는 자리입니다. 현재 소스가 공개 1.4.23의 내용과 다르면 1.4.23을 재사용하지 말고 새 CoreVersion을 발급하고 플러그인 manifest의 버전도 맞춥니다. 회사 Knowledge/config만 바뀌어도 같은 조건입니다. 지식팩 버전은 `corporate-knowledge/pack.json`과 일치해야 합니다.

```powershell
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion "<새 CoreVersion>" -KnowledgeVersion "<지식팩 버전>"
```

결과는 로컬의 `dist\company-agent-<CoreVersion>-<KnowledgeVersion>.zip`입니다. 날짜 형식의 KnowledgeVersion은 공통 지식 묶음의 버전이며 파일 생성일이 아닙니다. 같은 CoreVersion에 다른 내용을 덮어쓰는 것은 `-Force`로도 허용하지 않습니다. ZIP 생성은 GitHub 공개나 조직 배포를 수행하지 않습니다. 이미 설치된 배포본을 덮어쓰지 않고 새 버전으로 전달합니다. ZIP에는 쉬운 사용자 안내서 HTML/Markdown, 한국어 진단 실행 파일, 자동 학습 설명서와 업무 시범 운영 안내서도 포함됩니다. 직원의 첫 업무 안내와 설치된 `resources/manuals`는 해당 배포에 동봉한 사본이므로, 저장소 문서만 고쳐서는 기존 설치 안내서가 바뀌지 않습니다. 별도 Workspace ZIP의 안내서도 그 ZIP을 따로 갱신해야 합니다.

`-WithoutBundledPython`은 기존 빌드 명령과의 호환을 위해 유지하며 현재 기본값과 같은 결과를 냅니다. 직원 ZIP에는 설치·실행·제거·복구에 필요한 파일을 넣고, `New-OfflineBundle.ps1`, `Get-EmbeddedPython.ps1`, `Test-*.ps1` 같은 빌드·테스트 도구는 제외합니다. 해당 도구와 테스트 소스는 저장소에 남아 있으며 개발 검증은 저장소에서 수행합니다.

기본 ZIP에는 `.exe`, `.dll`, `.pyd`가 없습니다. 이는 Python 런타임을 별도로 준비한다는 뜻이며 하네스를 문서만으로 바꾼 것은 아닙니다. 하네스에는 실행에 필요한 `.cmd`, `.ps1`, `.py` 코드가 남습니다. Gmail이나 사내 보안 시스템은 이 파일도 차단할 수 있으므로 첨부·반입·실행 승인을 보장하지 않습니다. 확장자 변경이나 코드 난독화로 숨기지 않고 사내에서 허용한 배포 경로를 사용합니다.

Python을 함께 전달해야 하는 별도 운영 환경에서만 관리자가 다음 옵션을 선택합니다. Windows x64용 공식 Python 3.13.15 embeddable archive를 준비하는 예시이며, 회사가 승인한 반입·검증 절차를 거칩니다.

```powershell
# 인터넷 가능한 관리자 빌드 PC에서만 준비
powershell.exe -NoProfile -File .\deploy\Get-EmbeddedPython.ps1

# Python 동봉을 명시적으로 선택
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion "<새 CoreVersion>" -KnowledgeVersion "<지식팩 버전>" -IncludeBundledPython -OutputPath ".\dist\company-agent-<CoreVersion>-<KnowledgeVersion>-with-python.zip"
```

폐쇄망 빌드 PC에는 검증된 Python ZIP을 반입할 수 있습니다. 별도 경로의 런타임은 `-IncludeBundledPython`, `-PythonRuntimeZip`, 정확한 `-PythonRuntimeSha256`을 함께 지정합니다. 동봉 패키지는 Python 라이선스와 실행 바이너리를 포함하며, 직원 설치 과정에서 다운로드하지 않습니다. 기본 패키지와 같은 CoreVersion의 다른 내용을 이미 설치한 PC에는 덮어쓸 수 없으므로, 같은 배포 대상에 전달할 구성은 릴리스 전에 확정합니다.

빌더는 플러그인·Knowledge 버전과 구조, Python import, 파일별 해시를 검사합니다. 전사 정식 배포는 사내 서명·소프트웨어 배포 절차로 전달합니다. 빌더가 자동으로 회사 서명을 붙이지 않으며 해시 목록은 배포 주체 인증을 대신하지 않습니다.

## 적용 후 확인

직원은 ZIP 최상위 `Diagnose-CompanyAgent.cmd`를 실행하고 실제 작업 폴더를 입력할 수 있습니다. 사용자/프로젝트 설치 기록에서 Python을 찾고, 실행부와 동일한 규칙으로 개인 상태를 선택합니다. 설정 변경이나 모델 호출 없이 스킬 안내·본문 로드 기록과 업무별 준비물을 보여줍니다. 원문 대화·문서·인증정보는 출력하지 않습니다. 조직 정책과 모델의 실제 사용 성공까지 확인하는 도구는 아닙니다.

Claude에 “Company Agent 설치 상태를 확인해줘”라고 요청하면 자동 전달된 실행 경로로 doctor를 호출할 수 있습니다. 진단은 구조와 모델 별칭 상속을 확인하며 사내 모델에 실제 응답을 요청하지 않습니다. 실제 모델 전환과 업무 품질은 대표 프로젝트 작업으로 확인합니다.

사내 MCP 구현은 별도입니다. 기존 Claude MCP 설정을 유지하고 사내 서버는 기존 운영 방식으로 연결합니다. DB SELECT-only와 Outlook 본인 계정 제한은 서버 자체가 강제해야 합니다. 하네스 생성 기능은 실제 MCP와 계약을 확인하며, 존재하지 않는 서버 기능을 생성 결과에 꾸며 넣지 않도록 합니다.

개인 MCP는 구조·프로토콜 검증을 통과한 후 `asset activate-mcp`에서 선택 scope의 Claude 등록까지 수행합니다. 응답 유실 등으로 등록만 남으면 `asset sync-mcp --name ...`으로 재시도합니다. 기존 이름이나 다른 scope의 동일 이름은 덮어쓰지 않습니다. 하네스 자체는 승인 Python의 표준 라이브러리로 실행되지만, 새 MCP 생성에는 해당 자산이 사용하는 승인된 MCP SDK 환경이 별도로 필요합니다. 설치기는 그 SDK나 pip 패키지를 추가하지 않습니다. 모델·자산 실행 환경이 바뀌면 기존 검증 receipt는 재검증이 필요할 수 있습니다.

[Skill 우선 선택](SKILL_PRIORITY.md) · [프로젝트 하네스 생성](PROJECT_HARNESS.md) · [최초 의도와 구현 대조](IMPLEMENTATION_REVIEW.md) · [기존 관리자 배포](LEGACY_MACHINE_DEPLOYMENT.md)
