# Claude Code에게 맡기는 Company Agent 설치

Company Agent ZIP을 로컬 PC의 폴더에 완전히 압축 해제한 뒤 이 문서를 Claude Code에 전달한다.
사용자는 **“이 문서를 읽고 Company Agent를 설치해 줘”**라고 요청하면 된다.
직접 설치하려면 같은 폴더의 `Install-CompanyAgent.cmd`를 더블클릭하면 된다.

이 안내는 **Claude Code와 회사 승인 Python 3.11 이상이 이미 설치된 PC**를 기준으로 한다.
직원용 기본 ZIP에는 Python 실행 파일이나 DLL을 포함하지 않는다. 실제 버전은 동봉된 `bundle-manifest.json`을 기준으로 확인한다. 기존 사내 모델 설정을 그대로 사용한다. 이전 1.x 버전을 설치한 PC도 동일 범위로 업데이트할 수 있으며 개인 자료와 자동 학습 설정은 유지한다. 이전 `0.3.x`는 배포 전 개발 버전이다.

설치 후 Claude를 다시 열고 필요하면 `/company-agent:business-check`로 기본 조건을 확인한다. 폴더별 자동 스킬 목록은 시작/다음 요청 때 준비되므로 별도 생성 명령이 필요 없다. 메일 본문이나 운영 문서를 설치 점검 중 자동 조회하지 않는다. DRM 정책을 바꾸거나 인터넷에서 패키지를 설치하지 않는다. 실제 메일 발송·PST 이동은 별도 연결된 `corp-outlook-self` 기능이 있을 때만 사용한다. 로컬 Outlook 점검기는 읽기 전용이다. 처음 사용하는 사람은 [온보딩 코스](docs/Company-Agent-Onboarding.html), 운영 시험은 `docs/BUSINESS_PILOT_GUIDE.md`를 참고한다.

이전 설치 시 `cp949 codec can't encode character` 오류가 있었다면 수정된 ZIP을 새 폴더에 완전히 풀어 사용한다. 기존 Skill 내용을 삭제하거나 Windows 전역 인코딩/Python을 재설정하지 않는다. 압축 해제한 설치기 일부만 바꾸면 무결성 검증에 실패하므로 수정 ZIP 전체를 사용한다.

1.1.1에서 그냥 더블클릭해도 `Run this installer from your normal Windows account` 오류가 났다면 1.1.2 ZIP 전체를 새 폴더에 풀어 다시 진행한다. 1.1.2는 관리자 권한 여부만으로 거절하지 않고, 설치 프로세스와 실제 로그인한 Windows 사용자·세션·개인 폴더의 일치를 먼저 확인한다. 같은 사용자로 확인된 높은 권한 실행은 허용하지만, 다른 계정·서비스·대상이 불명확한 실행은 설치 대상 파일을 바꾸기 전에 중단한다. 회사 보안 정책을 변경하거나 관리자 실행을 권장하지 않는다.

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

   설치기는 평소 실행 가능한 `claude`와 현재 사용자의 일반적인 설치 위치를 확인한다. Claude 후보가 없거나 여러 개여서 선택이 필요하면, 사용자가 실제 쓰는 파일을 확인하여 `-ClaudeCommand "실제 Claude 실행 파일 경로"`로 다시 실행한다. `input-required`는 설치 성공이 아니며 임의 후보를 선택하지 않는다. Claude 프로그램 위치로 개인 설정 폴더를 추측하거나 다른 계정의 폴더를 사용하지 않는다.

   화면에 표시된 Windows 계정, Claude 실행 파일과 설정 폴더를 확인한다. 설정 위치는 명시한 `-ClaudeConfigRoot`, 현재 `CLAUDE_CONFIG_DIR`, 기존 같은 범위의 정상 설치 기록, 본인의 기본 `.claude`를 구분해 사용한다. 기존 기록과 다른 프로필을 강제로 덮어쓰지 않는다. 사용자가 별도 설정 위치를 쓰는지 알 수 없다면 기존 설정 내용을 출력하는 대신 위치만 확인한다.

   설치기는 `python`과 `py`에서 실제 Python 3.11 이상을 자동으로 찾는다. 정상적으로 찾으면 경로를 묻지 않는다.
   Python을 찾을 수 없다는 안내가 나오면 사용자가 이미 알려 준 승인 Python 경로를 사용한다.
   경로가 없을 때만 승인된 `python.exe` 위치를 확인하고 같은 명령에 `-PythonCommand "C:\ApprovedPython\python.exe"`를 추가한다.
   예시 경로를 실제 설치 경로로 추측해서 사용하지 않는다. 승인 Python이 없으면 사내 담당자에게 준비를 요청하도록 안내한다.
   무인 실행의 Python 누락 안내는 설치 성공이 아니다. Python/pip 설치·다운로드나 PATH 변경으로 대신 해결하지 않는다.

4. Dry Run 결과를 보고 **기존 Company Agent 업데이트**와 **다른 하네스 교체**를 구분한다.

   - 같은 범위의 정상 Company Agent 등록이 있으면 현재 버전과 새 버전을 보여 주고 **백업 후 업데이트** 또는 **현재 버전 유지**를 묻는다. 직접 실행 화면은 1번 업데이트가 기본값이고 2번은 유지다.
   - **업데이트**: `-ExistingHarnessAction Update`. 기존 개인 기억·지식·스킬·자동 학습 설정·모델·MCP뿐 아니라, 사용자가 추가한 지시·규칙·Hook도 비활성화하지 않고 유지한다. Core와 Knowledge 버전이 모두 같으면 **같은 버전 다시 적용/복구**로 설명한다.
   - **현재 버전 유지**: `-ExistingHarnessAction Keep`. 업데이트·백업·설정 변경 없이 종료한다.
   - 다른 하네스만 있으면 **기존 하네스 유지**(`Keep`) 또는 **백업 후 Company Agent 설치**(`Replace`)를 묻는다. `Replace`는 선택 범위의 기존 지시·규칙·Hook을 백업 후 비활성화하는 별도 선택이다.
   - 사용자가 이미 업데이트를 요청했다면 정상 Company Agent 등록을 확인한 뒤 `Update`를 사용하고 같은 선택을 반복해서 묻지 않는다. 일반 업데이트에 `Replace`를 대신 사용하지 않는다. 기존 Company Agent에서도 `Replace`를 사용할 수 있지만, 기존 규칙·Hook 비활성화를 사용자가 별도로 명시한 경우에만 허용한다.
   - 아무 하네스도 없으면 별도 질문 없이 처음 설치한다. `Update`는 같은 범위의 정상 Company Agent 등록이 있는 경우에만 사용할 수 있다.
   - 무인 `Ask`의 `status: input-required`, `input: ExistingHarnessAction`은 선택 요청이다. 기존 Company Agent면 `choices: Update/Keep`, 다른 하네스면 `choices: Keep/Replace`를 안내하고 선택 후 다시 실행한다. 무인 실행의 입력 누락을 자동 교체로 처리하지 않는다.
   - 등록 형식·플러그인 식별자·Claude 설정 위치가 맞지 않거나 더 오래된 숫자 버전의 패키지이면 중단 내용을 설명한다. 등록을 지우거나 처음 설치로 우회하지 않는다.
5. 설치를 계속할 경우 Dry Run의 Skill 목록에서 기존 후보와 들어올 후보의 같은 이름 겹침도 확인한다.
   겹치지 않으면 이 질문을 하지 않는다. 겹치면 이름과 출처를 짧은 목록으로 보여 주고 **기존 선택 유지** 또는 **새 Company Agent Skill 우선**을 고르게 한다.

   - **기존 선택 유지**: `-SkillConflictAction KeepCurrent`. 선호 설정을 그대로 두고 새 Skill을 함께 설치한다. 모든 기존 Skill이 무조건 우선한다는 뜻은 아니다.
   - **새 Company Agent Skill 우선**: `-SkillConflictAction PreferIncoming`. 백업 후 겹치는 이름에 새 후보의 우선 선택을 저장한다.
   - 사용자가 이미 선택했다면 다시 묻지 않는다. 무인 실행의 `status: input-required`, `input: SkillConflictAction`은 선택 요청으로 안내한다.
   - 기존 하네스의 `Keep`은 설치 자체를 하지 않는 선택이다. 이때 Skill 선택을 추가로 묻지 않는다.
   - Skill 파일은 삭제·변경·이름 변경하지 않는다. 이 선택으로 Claude의 일반 슬래시 명령 우선순위가 바뀐다고 안내하지 않는다.

6. 설치를 선택했다면 작업 중인 다른 Claude 세션을 닫도록 안내하고 동일한 명령에서 `-DryRun`을 제거해 실행한다.
   기존 하네스가 있었다면 선택한 `-ExistingHarnessAction`, Skill 겹침이 있었다면 선택한 `-SkillConflictAction`도 함께 전달한다.
   모델 ID, MCP 서버 주소, Outlook 계정, 사용자 이름은 묻지 않는다.
7. 설치 완료 시 사용자에게 **Claude Code를 닫았다 다시 열면 적용된다**고 안내하고 출력된
   설치 범위와 백업 경로를 알려 준다. 프로젝트 설치이면 선택한 폴더에서 열도록 안내한다.
   `status: installed`는 처음 설치, `updated`는 버전 변경, `reapplied`는 같은 버전 다시 적용 완료다.
   버전 변경이면 `previousCoreVersion`과 `coreVersion`으로 이전 버전 → 적용 버전을 설명한다.
   `Keep`으로 종료한 경우 설치되었다고 말하지 않는다. 재시작도 필요 없다.
8. 실제 설치가 완료된 경우에만 `First-Work.html`의 **전체 온보딩 코스 따라 하기** 또는 설치 완료 화면에 표시된 `Company-Agent-Onboarding.html`을 안내한다. 처음에는 가상 자료 읽기 한 단계만 해도 된다. 안내서를 자동 실행하거나 읽기·제작·기억 저장 요청을 대신 보내지 않는다.
   폴더별 별도 업무 구조가 필요한 경우에만 “이 프로젝트에 맞는 하네스를 만들어 줘” 또는 `/company-agent:project-harness`를 안내한다. 기본 사용을 위해 새 프로젝트 하네스를 또 만들 필요는 없다. Skill별·프로젝트별 선택은 `/company-agent:skills`에서 할 수 있다.
   `Keep`이면 이 안내 없이 종료한다.

## 설치 프로그램이 자동으로 처리하는 내용

- 실행 프로세스가 현재 로그인한 Windows 사용자의 것인지, 개인 폴더가 그 사용자와 일치하는지 먼저 확인한다. 관리자 권한으로 감지되는 본인 실행도 이 확인을 통과하면 허용한다. 다른 계정·서비스·불명확한 실행은 중단한다.
- Claude 실행 파일을 PATH와 현재 사용자의 일반적인 설치 위치에서 확인한다. 후보 선택이 필요할 때만 질문하며, 개인 설정 폴더는 실행 파일 위치와 별도로 확인한다.
- Claude Code 최소 버전 확인. 모델 alias `haiku`, `sonnet`, `opus`는 기존 설정을 재사용한다.
- 패키지 무결성 검사 후 PC의 승인된 Python 3.11 이상을 확인한다. 직접 설치에서는 자동 탐색 실패 시에만 경로를 입력받는다.
- Python/pip를 설치·다운로드하거나 PC의 PATH 설정을 변경하지 않는다. 관리자가 명시적으로 만든 Python 포함 패키지는 동봉 런타임을 사용할 수 있다.
- 기존 Skill, command, agent, Hook, Markdown 지시 파일, 설정 및 Plugin 등록 정보의 선택 백업.
- 기존 개인 Memory와 수정 이력, Knowledge 원본/overlay/이력, 개인 Skill, 사용자 설정을 선택 백업.
- 같은 범위의 기존 설치가 있으면 사용자 지정 개인 저장 경로도 자동 재사용한다. 새 경로를 임의로 지정하지 않는다.
- 같은 범위의 기존 Company Agent면 버전을 비교해 업데이트/유지를 묻고 기존 지시·규칙·Hook을 보존한다. 다른 하네스만 있으면 유지/교체를 묻는다. 모델·MCP만 있는 설정이나 독립 Skill만으로 기존 하네스라고 판정하지 않는다.
- 기존 Skill과 이번 플러그인 Skill의 같은 이름 겹침을 보여 주고 선택을 받는다. 충돌 없는 경우에는 별도 질문이 없다.
- Skill 우선 선택은 현재 State의 `config/skill-preferences.json`에 보존하며 업데이트 백업에 포함한다. 설치가 바꾼 선택은 실패 시 복구한다.
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
같은 범위의 Company Agent 등록은 별도의 업데이트 대상으로 감지한다. 일반 `Update`에서는 위 교체 대상 파일도 모두 유지한다. `Replace`는 기존 규칙·Hook 비활성화를 별도로 선택한 경우에만 사용한다.

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

업데이트는 새 ZIP의 설치 파일을 실행하고 기존과 같은 범위·프로젝트 경로를 선택한 뒤 버전 비교 화면에서 업데이트를 선택한다. Core와 Knowledge가 모두 같으면 다시 적용/복구로 진행하며 같은 버전의 다른 내용은 보호 검사에서 거절한다. 더 오래된 숫자 버전으로 되돌리는 일반 설치는 지원하지 않는다.
경로 변경 오류나 지원하지 않는 State 형식 오류가 나면 등록 파일/버전 표시를 지워 우회하지 않는다.
User와 Project의 기억은 별개이며 프로젝트 폴더를 옮겼을 때 자동 이관되지 않는다.

Skill 우선 선택도 같은 State 경계를 따른다. User 설치 하나로 여러 프로젝트를 쓰면 기본 선택과 프로젝트별 예외를 같은 State에 저장한다.
별도 Project 설치의 선호 설정은 해당 State에만 있고 다른 설치에서 자동 상속·병합하지 않는다.
선택은 Company Agent의 검색·컨텍스트·선택 파일 읽기에 적용하며 Claude의 일반 `/Skill명` 로딩 순서를 바꾸지 않는다.
설치 후 [Skill 목록과 프로젝트별 선택](docs/SKILL_PRIORITY.md)을 참고한다.

## 문제가 발생한 경우

무결성 검증 실패, 이미 다른 배포자가 소유한 동일 이름 Plugin/marketplace, 실행 조건 누락,
모든 subagent를 한 모델로 강제하는 설정, 경로 충돌이 있으면 오류 메시지의 해결 방법만 설명한다.
검사 우회 옵션을 사용하거나 기존 Plugin/Skill을 임의로 삭제하지 않는다.
Python 누락은 PC에 이미 설치된 승인 Python 3.11 이상의 경로를 `-PythonCommand`로 지정해 재시도한다.
승인 Python이 없거나 버전이 낮으면 사내 담당자에게 준비를 요청한다. 설치기가 임의로 다운로드하거나 설치하지 않는다.
기본 ZIP에 `.exe`, `.dll`, `.pyd`가 없어도 `.cmd`, `.ps1`, `.py`는 실행 가능한 코드다.
Gmail 또는 사내 보안 정책의 첨부·실행 허용을 보장하지 않으며, 파일을 숨기거나 확장자를 바꾸어 전달하지 않는다.
소스 저장소의 빌더와 테스트 스크립트는 직원 ZIP에서 제외한다. 이 ZIP 안에서 다시 빌드하거나 개발 테스트를 실행하려 하지 않는다.
기존 설정에 Claude native CLI가 정확히 유지할 수 없는 큰 정수 리터럴이 있으면 설정을 변경하기 전에 중단한다.
`±9007199254740991` 범위를 넘는 정수가 이에 해당한다. 해당 항목이 문자열을 허용하는지 담당자에게 확인한 뒤 명시적으로 수정하며,
숫자를 임의로 반올림하거나 검사만 우회하지 않는다. 이 검사는 모든 소수·지수 표기의 정밀도를 검증하는 기능은 아니다.

기존 `Program Files`/`ProgramData` 관리자 배포는 `-Scope Machine`으로 유지된다.
일반 사용자 안내에는 User/Project 설치를 사용하며 평소 계정에서 일반 더블클릭을 권한다.
1.1.2는 본인의 높은 권한 실행도 사용자·세션·프로필 확인 후 허용하므로, 관리자라는 이유만으로 계정을 바꾸도록 지시하지 않는다.
다른 계정 또는 사용자 확인 오류이면 출력된 계정·위치와 정확한 오류만 담당자에게 전달한다. 비밀번호, 토큰, 설정 파일 내용은 요구하지 않는다.
UAC·회사 보안 정책 변경, `-SkipAdminCheck` 등 보호 검사 생략, 타인 프로필 지정으로 우회하지 않는다.

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
