# Claude Code에게 맡기는 Company Agent 설치

Company Agent ZIP을 로컬 PC의 폴더에 완전히 압축 해제한 뒤 이 문서를 Claude Code에 전달한다.
사용자는 **“이 문서를 읽고 Company Agent를 설치해 줘”**라고 요청하면 된다.
직접 설치하려면 같은 폴더의 `Install-CompanyAgent.cmd`를 더블클릭하면 된다.

## Claude Code가 수행할 절차

1. Windows인지 확인하고 이 문서와 같은 폴더에 `bundle-manifest.json`과
   `deploy\Setup-CompanyAgent.ps1`이 있는지 확인한다. ZIP 내부에서 실행하지 않는다.
2. 사용자 요청에 설치 범위가 이미 있으면 그대로 사용한다. 없으면 딱 한 번 묻는다.

   > 모든 Claude Code 작업에서 사용할까요, 아니면 특정 프로젝트 폴더에서만 사용할까요?

   - **Claude 전체**: 현재 Windows 계정의 모든 Claude Code 세션. `-Scope User`.
   - **프로젝트만**: 선택한 폴더에서 연 Claude Code. `-Scope Project -ProjectRoot "폴더 경로"`.
   - 프로젝트만 선택했는데 경로가 없다면 사용자에게 프로젝트 폴더 경로를 받는다.
   - 이 선택은 조직 전체 관리자 설치 여부가 아니다. 두 선택 모두 관리자 권한이 필요 없다.
3. 선택한 범위로 사전 검사한다. 다음은 전체 범위 예시다.

   ```powershell
   powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\deploy\Setup-CompanyAgent.ps1" -Scope User -NonInteractive -DryRun
   ```

   프로젝트 범위는 다음과 같다. 실제 선택한 경로로 치환한다.

   ```powershell
   powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\deploy\Setup-CompanyAgent.ps1" -Scope Project -ProjectRoot "C:\Work\MyProject" -NonInteractive -DryRun
   ```

4. Dry Run 결과의 기존 하네스 목록과 필요한 선택을 확인한다. 기존 하네스가 있으면 다음을 묻는다.

   > 기존 하네스를 그대로 유지할까요, 아니면 자동 백업 후 기존 규칙·Hook을 비활성화하고 Company Agent를 설치할까요?

   - **기존 하네스 유지**: `-ExistingHarnessAction Keep`. 설치하지 않고 변경 없이 종료한다.
   - **백업 후 Company Agent 설치**: `-ExistingHarnessAction Replace`. 선택 범위의 기존 지시·규칙·Hook을 백업 후 비활성화한다.
   - 사용자가 이미 이 선택을 명확히 말했다면 다시 묻지 않는다. 사용자 선택 없이 `Replace`를 지정하지 않는다.
   - 기존 Company Agent를 갱신할 때도 이 선택을 확인한다. 기존 하네스가 없으면 별도 질문 없이 설치한다.
   - 무인 실행의 `status: input-required`, `input: ExistingHarnessAction`, `choices: Keep/Replace`는 실패를 우회하라는 뜻이 아니다.
     이를 사용자 선택 입력 요청으로 보여 주고, 답을 받은 뒤 해당 인자를 명시해 재실행한다.
5. 설치를 선택했다면 작업 중인 다른 Claude 세션을 닫도록 안내하고 동일한 명령에서 `-DryRun`을 제거해 실행한다.
   기존 하네스가 있었다면 선택한 `-ExistingHarnessAction`도 함께 전달한다.
   모델 ID, MCP 서버 주소, Outlook 계정, 사용자 이름은 묻지 않는다.
6. 설치 완료 시 사용자에게 **Claude Code를 닫았다 다시 열면 적용된다**고 안내하고 출력된
   설치 범위와 백업 경로를 알려 준다. 프로젝트 설치이면 선택한 폴더에서 열도록 안내한다.
   `Keep`으로 종료한 경우 설치되었다고 말하지 않는다. 재시작도 필요 없다.
7. 실제 설치가 완료된 경우에만 새 세션에서 “이 프로젝트에 맞는 하네스를 만들어 줘” 또는
   `/company-agent:project-harness`를 사용할 수 있다고 안내한다. `Keep`이면 이 안내 없이 종료한다.

## 설치 프로그램이 자동으로 처리하는 내용

- Claude Code 설치 및 최소 버전 확인. 모델 alias `haiku`, `sonnet`, `opus`는 기존 설정을 재사용한다.
- 패키지 무결성 검사 후 동봉된 Python을 확인하고, 없으면 PC의 승인된 Python 3.11 이상을 확인한다.
- 기존 Skill, command, agent, Hook, Markdown 지시 파일, 설정 및 Plugin 등록 정보의 선택 백업.
- 기존 개인 Memory와 수정 이력, Knowledge 원본/overlay/이력, 개인 Skill, 사용자 설정을 선택 백업.
- 같은 범위의 기존 설치가 있으면 사용자 지정 개인 저장 경로도 자동 재사용한다. 새 경로를 임의로 지정하지 않는다.
- 기존 하네스가 있으면 유지/교체를 묻는다. 모델·MCP만 있는 설정이나 독립 Skill만으로 기존 하네스라고 판정하지 않는다.
- 교체를 선택하면 선택 범위의 CLAUDE Markdown 지시·`rules/**/*.md`와 settings의 최상위 `hooks`를 암호화 백업 후 비활성화한다.
- 설치 전에 State 형식 호환성을 확인한다. 지원하지 않는 형식은 초기화하지 않고 중단한다.
- 백업 후 공식 Claude Plugin 명령으로 로컬 오프라인 marketplace를 등록한다.
- `User`는 사용자 설정에 Plugin 등록을 추가한다. 교체를 선택한 경우 해당 범위의 기존 규칙·Hook도 비활성화한다.
- `Project`는 `.claude/settings.local.json`에 등록하여 다른 PC에 적용되는 프로젝트 공용 설정에 로컬 경로를 넣지 않는다.
- 같은 PC에 User와 여러 Project 설치가 함께 존재할 수 있다. 공통 Plugin은 하나의 식별자를 사용하고,
  현재 작업 폴더에 해당하는 프로젝트 개인 상태가 우선한다.
- 기존 MCP, 모델, env, permissions, 일반 Skill과 다른 Plugin은 유지한다. MCP는 별도 개발·배포 대상이다.
- 설치 중 실패하면 Company Agent 등록과 교체로 비활성화한 기존 규칙·Hook을 복구한다. 동시 수정 등 복구 충돌은 백업 위치와 함께 안내한다.

## 교체가 적용되는 범위

User는 현재 Claude 설정 폴더의 `CLAUDE.md`·`CLAUDE.local.md`, `rules/**/*.md`, `settings.json`의 최상위 `hooks`를 대상으로 한다.
Project는 선택 프로젝트 루트와 `.claude`의 `CLAUDE.md`·`CLAUDE.local.md`, `.claude/rules/**/*.md`,
`.claude/settings.json` 및 `.claude/settings.local.json`의 최상위 `hooks`를 대상으로 한다.
같은 범위의 Company Agent 등록도 기존 하네스로 감지하므로 업데이트에서도 선택 화면이 나타난다.

상위 폴더·사용자 전체 등 **다른 범위에서 상속한 규칙/Hook과 다른 플러그인이 제공하는 Hook은 유지**한다.
교체를 ‘PC의 모든 하네스를 초기화’하는 작업으로 안내하지 않는다. 출력된 감지 목록과 범위를 사용자에게 설명한다.

## 백업과 저장 위치

```text
%LOCALAPPDATA%\CompanyAgent-Backups\pre-install-<시간>-<식별자>
%LOCALAPPDATA%\CompanyAgent-Distribution\marketplace\versions\<버전>
%LOCALAPPDATA%\CompanyAgent\installations\user\company-agent-install.json
%LOCALAPPDATA%\CompanyAgent\installations\projects\<프로젝트식별자>\company-agent-install.json
%LOCALAPPDATA%\CompanyAgent\states\user
%LOCALAPPDATA%\CompanyAgent\states\projects\<프로젝트식별자>
```

백업은 현재 Windows 사용자와 LocalSystem만 접근하도록 제한한다. 일반 선택 백업의 설정 JSON은
secret/token/password 계열 값을 마스킹하고 junction/symlink는 따라가지 않는다.
일반 선택 백업은 인증정보, `.env`, 개인키, 세션 원문, history, cache 등을 제외한다.
교체할 기존 파일·Hook이 있으면 `previous-harness`에 해당 규칙·설정의 정확한 원본을 Windows DPAPI CurrentUser로 **암호화**해 별도 보관한다.
이 암호화 사본은 설정 안의 비밀값도 원래대로 복구하기 위한 용도이며, 평문 자격 증명 파일을 복사하지 않는다.
복구는 백업을 만든 동일 Windows 사용자·PC와 **원래 백업 폴더 경로**에서 수행한다.
백업 폴더를 옮겼다면 원래 경로로 되돌린 뒤 복구한다. 다른 PC로 이관하는 백업이 아니다.
추가 암호화 백업의 상한은 512개 파일, 단일 원본 8MiB, 원본 합계 32MiB이며 초과하면 기존 하네스를 비활성화하지 않고 중단한다.
개인 Skill, Memory, Knowledge는 state 폴더에 보존하며 Core 업데이트로 덮어쓰지 않는다.
선택 학습자료 백업은 백업 폴더의 `company-agent\personal-learning`에 저장된다.
이는 전체 PC 또는 전체 User State 복제본이 아니다. MCP 실행환경·인증정보·대화·캐시는 포함하지 않는다.
현재 설정과 자격 증명 내용을 직접 열어 출력하거나 외부로 전송하지 않는다.
여러 파일을 OS 전체에서 한꺼번에 잠그는 원자적 백업·교체는 아니다. 설치·복구 전에 다른 Claude 세션과 해당 폴더를 수정하는 작업을 닫는다.

업데이트는 새 ZIP의 설치 파일을 실행하고 기존과 같은 범위·프로젝트 경로를 선택한 뒤 ‘백업 후 Company Agent 설치’를 선택한다.
경로 변경 오류나 지원하지 않는 State 형식 오류가 나면 등록 파일/버전 표시를 지워 우회하지 않는다.
User와 Project의 기억은 별개이며 프로젝트 폴더를 옮겼을 때 자동 이관되지 않는다.

## 문제가 발생한 경우

무결성 검증 실패, 이미 다른 배포자가 소유한 동일 이름 Plugin/marketplace, 실행 조건 누락,
모든 subagent를 한 모델로 강제하는 설정, 경로 충돌이 있으면 오류 메시지의 해결 방법만 설명한다.
검사 우회 옵션을 사용하거나 기존 Plugin/Skill을 임의로 삭제하지 않는다.
Python 누락은 필요한 런타임이 포함된 완전한 Windows 번들을 받아 해결한다.
기존 설정에 Claude native CLI가 정확히 유지할 수 없는 큰 정수 리터럴이 있으면 설정을 변경하기 전에 중단한다.
`±9007199254740991` 범위를 넘는 정수가 이에 해당한다. 해당 항목이 문자열을 허용하는지 담당자에게 확인한 뒤 명시적으로 수정하며,
숫자를 임의로 반올림하거나 검사만 우회하지 않는다. 이 검사는 모든 소수·지수 표기의 정밀도를 검증하는 기능은 아니다.

기존 `Program Files`/`ProgramData` 관리자 배포는 `-Scope Machine`으로 유지된다.
일반 사용자 안내에는 User/Project 설치를 사용한다. 이미 관리자 권한으로 연 터미널이라면
일반 터미널에서 실행하도록 안내한다.

## 적용 해제와 재설치

사용자가 적용 해제를 요청하면 `deploy\Uninstall-ScopedCompanyAgent.ps1`을 선택한 범위로 실행한다.
전체 범위는 `-Scope User -NonInteractive`, 프로젝트 범위는
`-Scope Project -ProjectRoot "선택한 경로" -NonInteractive`를 사용한다.
선택한 범위의 Plugin 등록과 활성 설치 기록만 해제하고 개인 Memory, Skill, Knowledge와
다른 범위의 설치는 보존한다. 기본 경로는 같은 범위로 다시 설치하면 기존 개인 상태를 이어서 사용한다.
사용자 지정 경로 설치를 제거하면 활성 등록도 없어지므로, 제거 전 출력/백업의 `userStateRoot`를 보관하고
재설치 때 동일한 `-UserStateRoot`를 전달한다. 기존 경로를 추측하거나 개인 파일을 삭제하지 않는다.

기존 하네스로 돌아가려면 먼저 위 제거 스크립트로 같은 범위의 Company Agent 적용을 해제한다.
그다음 아래처럼 출력된 설치 전 백업 경로로 검사하고 복구한다.

```powershell
powershell.exe -NoProfile -File .\deploy\Restore-PreviousHarness.ps1 -BackupPath "<pre-install 백업 폴더>" -DryRun
powershell.exe -NoProfile -File .\deploy\Restore-PreviousHarness.ps1 -BackupPath "<pre-install 백업 폴더>" -NonInteractive
```

복구 스크립트는 Company Agent를 자동 제거하지 않는다. 지시 파일이 수정·재생성되었거나 다른 Hook이 추가되어 충돌하면 덮어쓰지 않고 중단한다.
모델·MCP·Plugin 등록처럼 Hook 이외의 설정 변경은 유지하며 기존 Hook만 복구한다.
충돌한 현재 자료를 보존하고 안내를 확인해야 하며, 강제 덮어쓰기로 우회하지 않는다.
