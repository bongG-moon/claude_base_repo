# Company Agent Harness

현재 배포 버전은 **1.4.2**입니다. 사내 Office 읽기에 PPT 그룹·표·배치, Word 표 셀·문단 구조를 추가하고 불필요한 실행 경로 탐색을 줄였습니다. 공통 Skill은 12개이며 기존 개인 자료를 유지합니다. DRM 해제·접근 거절 우회 기능은 아닙니다. [변경·설치 안내](docs/UPDATE_1.4.2.md)를 확인하세요.

설치 파일은 [최신 Release](https://github.com/bongG-moon/claude_base_repo/releases/latest) 또는 [1.4.2 설치 ZIP 바로 받기](https://github.com/bongG-moon/claude_base_repo/releases/download/v1.4.2/company-agent-1.4.2-2026.09.03.zip)에서 받으세요. GitHub가 자동 생성하는 `Source code (zip)`은 직원용 설치 파일이 아닙니다.
[폴더별 자동 스킬 목록](docs/SKILL_CATALOG.md), 각 PC의 Python 탐색과 Ouroboros 연결 교정을 포함합니다.
기존 코어와 ZIP은 덮어쓰지 않습니다. 1.4.2 묶음에서 기존과 같은 범위를 골라 백업 후 업데이트하세요. 개인 Memory·Skill·Knowledge·모델·MCP 설정을 유지합니다. 파일명 뒤 `2026.09.03`은 회사 지식팩 버전이며 설치 프로그램 버전은 `1.4.2`입니다.

Office 읽기는 별도 준비물이 필요합니다: Excel/CSV는 선택한 Python의 xlwings·pandas와 Excel, PPT/Word는 pywin32와 해당 Office. ZIP에 이 라이브러리나 Office를 넣거나 자동 다운로드하지 않습니다. 개발 PC의 일반 PPT·Word 읽기는 성공했지만 Excel은 xlwings 미설치로 실제 읽기 미검증이며, 사내 DRM 호환성은 별도로 확인해야 합니다.

Windows 폐쇄망에서 이미 설치된 Claude Code와 사내 SMALL/MEDIUM/LARGE 모델을 사용하는 개인화 하네스입니다. 공통 엔진과 개인 Knowledge·Memory·Skill을 분리하고 사용자 또는 프로젝트 범위로 설치합니다.

1.2.0에서 시작한 파일 정리, Outlook 조회 안내, HTML 보고서와 편집 가능한 PPT 업무팩을 계속 개선했습니다. 실제 회사 Office·DRM 통합 검증은 별도로 필요하므로 시범 운영 범위를 유지합니다. 일부 회사 PC의 관리자 권한 감지 보완, 본인 Claude 실행·설정 위치 확인, 자동 학습과 업데이트 시 개인 자료·규칙·Hook 보존을 포함합니다. 이전 버전은 [Release 이력](https://github.com/bongG-moon/claude_base_repo/releases)에서 확인할 수 있습니다.

업무팩은 새 앱을 따로 여는 대신 Claude에 한국어로 요청하는 방식입니다. 파일은 정리안을 먼저 보여주고 본인의 확인 창 승인 후 이동하며, HTML은 8가지 분위기와 스크롤/슬라이드 방식을 고릅니다. PPT는 승인된 Python 환경과 설치된 PowerPoint 또는 이미 준비된 제작 도구를 사용합니다. Outlook은 기존 `corp-outlook-self` 연결을 우선하고, 선택적인 로컬 조회는 읽기 전용입니다. 새 메일 발송·PST 이동 연결이나 외부 이미지 생성 API를 자동 설치하지 않습니다. 실제 회사 Office·메일 환경의 통합 검증은 별도로 필요합니다. [업무팩 시범 사용 안내](docs/BUSINESS_PILOT_GUIDE.md)에서 네 가지 업무 예시, 보호된 자료 처리, 준비물과 미지원 범위를 확인하세요.

코딩에 익숙하지 않은 직원을 위한 [상세 사용자 안내서](docs/Company-Agent-사용자-안내서.html)를 제공합니다. HTML 파일을 내려받아 더블클릭하면 인터넷 연결 없이 읽을 수 있고, 업무 예문을 복사할 수 있습니다. [수정용 원본](docs/USER_GUIDE.md)에는 첫 사용, 보고·회의·자료 비교, 개인 기억과 지식, 반복업무 스킬, 프로젝트별 활용, 업데이트와 문제 해결을 정리했습니다.

[Claude Code 필수 사용법·단축키 검색 안내서](docs/Claude-Code-필수-사용법.html)는 별도 설치 없이 HTML 하나로 열 수 있습니다. 핵심 8개와 상황별 20개 안내, 실행 중 메시지·대기 요청의 차이, 여러 세션, 예시 복사와 현재 목록 인쇄를 포함하며 1.3.9 설치 ZIP에도 들어 있습니다.

기본 배포 ZIP은 **회사 PC에 이미 설치된 승인 Python 3.11 이상**을 사용합니다. Claude Code 설치와 사내 모델 연결도 미리 준비되어 있어야 합니다. Python 실행 파일과 DLL은 ZIP에 넣지 않습니다.

실제 자료를 준비하지 않고 시험하려면 [로컬 연습실 안내](docs/TEST_LAB.md)를 사용하세요. 바탕화면에 가상 파일·메일 예시·보고서 입력과 질문 복사 화면을 생성하고, 사용자가 실행하면 테스트 프로젝트 설치를 안내합니다. 실제 업무용 개인 기억으로 자동 대체하지 않으며 Outlook·DRM·사내 DB 통합 시험은 별도로 구분합니다.

## 직원 설치

1. 열려 있는 Claude Code를 닫고 배포 ZIP을 모두 압축 해제합니다.
2. `Install-CompanyAgent.cmd`를 평소처럼 더블클릭합니다. 별도로 ‘관리자 권한으로 실행’을 선택할 필요는 없습니다.
3. **Claude 전체** 또는 **이 프로젝트만**을 선택합니다. 프로젝트라면 폴더도 지정합니다.
4. 같은 범위에 Company Agent가 있으면 **기존 버전 → 새 버전**을 확인하고 업데이트를 선택합니다. 같은 버전이면 다시 적용/복구로 안내합니다. 다른 하네스만 있으면 **기존 하네스 유지** 또는 **백업 후 Company Agent 설치**를 선택하며, 아무것도 없으면 다음 단계로 진행합니다.
5. 설치기가 본인의 Windows 계정, Claude 실행 파일·설정 위치와 Python 3.11 이상을 확인합니다. Claude를 찾지 못하거나 후보가 여러 개면 평소 쓰는 실행 파일을 선택하고, Python을 찾지 못하면 승인된 `python.exe` 경로를 입력합니다. 경로를 모르면 사내 담당자에게 확인합니다.
6. 들어오는 Skill과 같은 이름이 발견되면 목록을 확인하고 **기존 선택 유지** 또는 **새 Company Agent Skill 우선**을 선택합니다. 겹침이 없으면 추가 질문은 없습니다.
7. 설치·업데이트·다시 적용이 완료되면 Claude Code를 다시 엽니다. ‘유지’를 선택하면 변경 없이 종료하므로 재시작할 필요가 없습니다.

설치기는 Python이나 pip를 설치·다운로드하지 않고 PC의 PATH 설정을 바꾸지 않습니다. 모델 ID, MCP, Outlook 정보를 입력하지 않으며 평소 `claude` 명령에서도 적용됩니다. 설치 전 기존 설정·Skill·Hook·플러그인 등록과 개인 Memory·Knowledge·Skill을 선택 백업합니다. ‘백업 후 설치’에서는 선택한 범위의 기존 Markdown 지시·규칙과 설정의 Hook을 별도로 암호화 백업한 뒤 비활성화합니다. 모델·MCP·개인 Memory·기존 일반 Skill은 유지합니다. 사용자/프로젝트 설치에는 관리자 권한이 필요하지 않습니다.

Claude에 [INSTALL_WITH_CLAUDE.md](INSTALL_WITH_CLAUDE.md)를 주고 “이 지침대로 설치해줘”라고 해도 됩니다. Markdown 파일과 실제 배포 ZIP의 나머지 파일은 같은 폴더에 있어야 합니다.

1.1.1에서 `Run this installer from your normal Windows account` 오류가 나왔다면 **1.1.2 ZIP 전체를 새 폴더에 풀고** 다시 실행하세요. 기존 설치가 있으면 같은 범위로 업데이트합니다. 다른 계정이나 확인할 수 없는 실행 환경은 새 설치기도 중단하며, Claude 파일 위치만으로 다른 사용자의 설정을 선택하지 않습니다. 회사 보안 설정을 끄거나 기존 설정을 삭제할 필요가 없습니다. [계정·Claude 위치 확인과 문제 해결](docs/DEPLOYMENT.md#계정과-claude-위치를-확인하는-방법)

## 기능

- 난도에 따른 haiku / sonnet / opus worker 배정과 단계적 상향
- 변경 → 검증 → 제한된 수정 재시도 → 검증 메타데이터 기록
- 관리자 Markdown 회사 지식과 사용자/프로젝트별 개인 overlay
- 세션 원문 대신 추출한 개인 Memory 저장과 관련 항목 조회
- 관련 Skill/Knowledge의 주입량 제한, 비파괴 Memory 중복 정리, native Compact 후 검증 상태 복원
- 코드·Script·MCP 제작에 Karpathy Guidelines 회사판 기본 제공
- 개인 Skill, Script Tool, MCP 후보 생성 및 검증
- “이 프로젝트 하네스 구성해줘” 요청으로 Agent·Skill·QA 규칙 생성
- 버전별 배포, 기존 파일 충돌 검사, 실패 복구, 개인 상태 보존
- 기존 Company Agent의 버전별 업데이트/다시 적용 안내와 개인 자료·기존 규칙·Hook 보존
- 다른 하네스의 유지/교체 선택, 명시적 교체 전 암호화 백업 및 선택 범위의 이전 규칙·Hook 비활성화
- 현재·신규 Skill 목록과 같은 이름의 겹침 표시, 프로젝트별 후보 선택과 출처 순서 저장
- 매 사용자 요청 종료 시 자동 회고, 반복 관찰 기반 개인 선호 반영, 실제 읽은 개인 Skill의 점검 절차 개선, 다음 사용 비교와 회귀 복구

모델 라우팅과 절차 수행은 Claude의 도구 사용과 생성 지침을 통해 이뤄집니다. 모델 가중치를 학습시키지 않으며 자체 검증 기록과 실제 테스트 결과는 구별해야 합니다. [구현 대조](docs/IMPLEMENTATION_REVIEW.md)에 근거와 범위를 정리했습니다.

1.0.0에서 제공한 설치 전 Skill 겹침 확인, 프로젝트별 우선 선택, 외부 Python 사용, 기존 하네스 유지/교체 선택, 개인 저장 경로 재사용·형식 보호를 유지합니다. 교체는 선택 범위에만 적용하며 상위 폴더·다른 범위·별도 플러그인의 지침/Hook까지 초기화하지 않습니다. [개인 상태 보존과 복구](docs/STATE_PRESERVATION.md)를 참고하세요.

1.1.0부터 `Stop` 완료 검토 → 추출된 관찰 → 안전한 개인 변경 → 다음 업무의 결과 비교를 연결합니다. 명확한 사용자 교정은 기억 요청 없이 반영할 수 있고, 추론한 선호는 서로 다른 요청에서 반복 관찰된 후 반영합니다. 개인 Skill의 자동 수정 범위는 실제 읽은 버전에 대한 제한된 점검 절차이며, 공통 Skill·다른 플러그인·실행 코드를 자율 재작성하지 않습니다. 검토는 기존 Claude 대화에서 수행하며 새 LLM 연결은 필요하지 않습니다. `/company-agent:learning`으로 내역 확인·일시 중지·재개·선택 복구를 요청할 수 있습니다. [자동 학습 동작과 한계](docs/SELF_LEARNING.md)를 참고하세요.

## Skill이 겹치면

프로젝트에서 `/company-agent:skills`를 입력하면 Skill 이름과 출처를 보고 사용할 후보를 선택할 수 있습니다. “이 프로젝트만”으로 저장하면 같은 개인 상태의 기본 선택보다 우선합니다. 별도로 Project 설치한 경우에는 그 프로젝트의 상태에 저장되며 다른 설치의 설정과 자동 합쳐지지 않습니다.

이 선택은 Company Agent가 검색·안내하고 읽을 Skill에 적용합니다. Claude의 일반 `/Skill명` 우선순위를 바꾸거나 모든 자동 호출을 강제하는 기능은 아닙니다. 원본 Skill 파일은 함께 보존합니다. 설치 시 “기존 선택 유지”도 기존 후보가 무조건 이긴다는 뜻이 아니라 기존 선호 설정을 유지한다는 뜻입니다. 자세한 흐름과 명령은 [Skill 목록과 프로젝트별 선택](docs/SKILL_PRIORITY.md)에 있습니다.

## 관리자 ZIP 생성

빌드 PC: Windows PowerShell 5.1+, Python 3.11+, Claude Code CLI 2.1.220+.

다음 명령은 **소스 저장소 루트**에서 실행합니다. 직원 ZIP에는 빌더와 테스트 도구가 들어 있지 않습니다.

```powershell
# PC에 이미 설치된 승인 Python을 사용하는 기본 직원 ZIP 생성
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion 1.2.0 -KnowledgeVersion 2026.09.03
```

결과는 `dist\company-agent-1.2.0-2026.09.03.zip`입니다. 뒤의 날짜는 회사 지식팩 버전이며 ZIP 생성일이 아닙니다. ZIP 생성은 로컬 산출물을 만드는 단계이며 GitHub 공개나 조직 배포를 수행하지 않습니다. 기존 `-WithoutBundledPython` 옵션도 같은 외부 Python 방식으로 사용할 수 있습니다. 관리자가 Python을 함께 배포해야 할 때만 `-IncludeBundledPython`을 명시하며, 준비 방법은 [설치·배포](docs/DEPLOYMENT.md)에 있습니다.

1.2.0은 사용자 요청에 따라 이 ZIP 하나를 소스와 함께 Git에 기록하고 동일 파일을 Release에도 제공합니다. 다른 로컬 빌드 ZIP은 계속 제외됩니다. ZIP을 갱신할 때는 안내서와 소스를 먼저 검증하고 다시 빌드한 뒤, 커밋의 파일과 Release 첨부 파일이 같은지 SHA-256으로 확인해야 합니다.

기본 ZIP에는 `.exe`, `.dll`, `.pyd`가 없지만 설치·실행용 `.cmd`, `.ps1`, `.py` 파일은 포함됩니다. 따라서 Gmail이나 사내 보안 시스템의 첨부 허용을 보장하지 않습니다. 파일 이름·확장자를 숨기거나 바꾸지 않고 사내 승인된 배포 채널로 전달합니다. Python 실행 환경을 분리한 것이며, 하네스 자체는 코드를 실행합니다.

Core/설정/Knowledge 변경 시 새 버전을 부여합니다. 정식 배포에는 회사 서명과 배포 채널을 사용합니다. 기본 ZIP이 자동으로 회사 서명되는 것은 아닙니다. MCP는 별도 개발·배포하며 DB와 Outlook 권한은 해당 서버에서 강제합니다.

[컨텍스트·Compact·실패 복구](docs/CONTEXT_OPTIMIZATION.md)에서 구현 범위와 native Rewind의 차이를 확인할 수 있습니다. 자동 대화 rewind나 임의의 업무 전체를 되돌리는 기능은 구현하지 않으며, 원본 기억을 지우는 압축도 하지 않습니다. 1.2.0의 파일 정리에는 별도의 명시적 되돌리기가 있지만, 해당 정리 기록에 포함되고 이후 변경되지 않은 파일만 대상으로 합니다.

## 개발 검증

아래 도구도 직원 ZIP이 아닌 소스 저장소에서 실행합니다.

```powershell
python -m unittest discover -s .\tests -v
claude plugin validate --strict .\company-agent-plugin
powershell.exe -NoProfile -File .\deploy\Test-DeploymentSmoke.ps1
powershell.exe -NoProfile -File .\deploy\Test-ScopedInstallSmoke.ps1 -LegacyEncoding
powershell.exe -NoProfile -File .\deploy\Test-PersonalStateBackup.ps1
powershell.exe -NoProfile -File .\deploy\Test-ExistingHarness.ps1
powershell.exe -NoProfile -File .\deploy\Test-HarnessReplacement.ps1
powershell.exe -NoProfile -File .\deploy\Test-ExternalPython.ps1
powershell.exe -NoProfile -File .\deploy\Test-RuntimeSelection.ps1
powershell.exe -NoProfile -File .\deploy\Test-OfflineBundle.ps1
powershell.exe -NoProfile -File .\deploy\Test-SkillInstallConflicts.ps1
powershell.exe -NoProfile -File .\deploy\Test-InstallerEncoding.ps1
```

Scoped smoke는 임시 Claude 설정과 프로젝트에서 실제 CLI 등록을 확인하며 개인 Claude 설정을 변경하지 않습니다. 내부 LLM/MCP를 호출하는 업무 검증과는 별개입니다.

배포 전 인코딩 검증에는 `Test-InstallerEncoding.ps1`과 `Test-ScopedInstallSmoke.ps1 -LegacyEncoding`을 포함합니다. CP949 부모 콘솔·Python 환경과 한글/특수문자/이모지 경로를 사용하여 실제 프로세스의 출력·JSON 파싱·설치 보존을 확인합니다. 일반 CLI도 ASCII-safe JSON을 사용하므로 JSON 파싱 후 원래 Unicode 값이 유지됩니다. PC의 전역 코드페이지·언어 설정을 변경하지 않습니다.

일반 Python 테스트 실행은 실제 Claude CLI를 호출하는 MCP 등록 테스트 한 개를 기본적으로 생략합니다. 이 테스트는 Windows와 명시적 `COMPANY_AGENT_TEST_REAL_CLAUDE=1` 설정이 필요한 opt-in 검사이며, 라이브러리 누락이나 알려진 실패 때문에 제외한 것은 아닙니다. 임시 `CLAUDE_CONFIG_DIR`에서 실제 `claude mcp add-json`의 User/Project 등록 범위를 확인하고, 실제 개인 프로필을 수정하거나 MCP 서버에 접속하지 않습니다.

**배포 전 전체 검증**에서는 Claude Code가 설치된 Windows에서 아래와 같이 이 테스트까지 포함합니다. 환경 변수는 현재 PowerShell 프로세스에만 설정하고 완료 후 원래 값으로 복원합니다.

```powershell
$previousRealClaudeTestFlag = $env:COMPANY_AGENT_TEST_REAL_CLAUDE
try {
    $env:COMPANY_AGENT_TEST_REAL_CLAUDE = '1'
    python -B -m unittest discover -s .\tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Python 전체 테스트가 실패했습니다.' }
}
finally {
    $env:COMPANY_AGENT_TEST_REAL_CLAUDE = $previousRealClaudeTestFlag
}
```

이 검사는 CLI 등록 계약의 검증입니다. 사내 모델·실제 DB·Outlook 계정의 업무 통합 검증을 대신하지 않습니다.

```text
company-agent-plugin/   공통 플러그인, Python 코드, 프로젝트 Harness Factory
corporate-knowledge/    관리자 Markdown seed pack
config/                실행 설정, 별도 MCP 계약 예시
deploy/                쉬운 설치, scope 등록, 패키징, 기존 machine 배포
docs/                  직원 설치, 운영, 구현 대조, 프로젝트 하네스 생성
tests/                 동작·충돌·개인 상태 보존 테스트
```

[설치·배포](docs/DEPLOYMENT.md) · [Skill 우선 선택](docs/SKILL_PRIORITY.md) · [프로젝트 하네스 생성](docs/PROJECT_HARNESS.md) · [구현 대조](docs/IMPLEMENTATION_REVIEW.md) · [회사 지식 작성](docs/ADMIN_KNOWLEDGE_GUIDE.md) · [MCP 계약](docs/MCP_CONTRACTS.md)

프로젝트 Harness Factory는 [revfactory/harness](https://github.com/revfactory/harness)의 도메인 분석·팀 설계·Skill 생성·검증 패턴을 참고한 독립 구현입니다. 직원 PC에서 해당 저장소에 접속하거나 외부 플러그인을 내려받지 않습니다.
