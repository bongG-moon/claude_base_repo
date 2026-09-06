# Company Agent Harness

Windows 폐쇄망에서 이미 설치된 Claude Code와 사내 SMALL/MEDIUM/LARGE 모델을 사용하는 개인화 하네스입니다. 공통 엔진과 개인 Knowledge·Memory·Skill을 분리하고 사용자 또는 프로젝트 범위로 설치합니다.

## 직원 설치

1. 열려 있는 Claude Code를 닫고 배포 ZIP을 모두 압축 해제합니다.
2. `Install-CompanyAgent.cmd`를 더블클릭합니다.
3. **Claude 전체** 또는 **이 프로젝트만**을 선택합니다. 프로젝트라면 폴더도 지정합니다.
4. 기존 하네스가 감지되면 **기존 하네스 유지** 또는 **백업 후 Company Agent 설치**를 선택합니다. 없으면 바로 설치합니다.
5. 설치가 완료되면 Claude Code를 다시 엽니다. ‘유지’를 선택하면 변경 없이 종료하므로 재시작할 필요가 없습니다.

완전한 Windows x64 패키지에는 Python도 포함됩니다. 모델 ID, MCP, Outlook 정보를 입력하지 않으며 평소 `claude` 명령에서도 적용됩니다. 설치 전 기존 설정·Skill·Hook·플러그인 등록과 개인 Memory·Knowledge·Skill을 선택 백업합니다. ‘백업 후 설치’에서는 선택한 범위의 기존 Markdown 지시·규칙과 설정의 Hook을 별도로 암호화 백업한 뒤 비활성화합니다. 모델·MCP·개인 Memory·기존 일반 Skill은 유지합니다. 사용자/프로젝트 설치에는 관리자 권한이 필요하지 않습니다.

Claude에 [INSTALL_WITH_CLAUDE.md](INSTALL_WITH_CLAUDE.md)를 주고 “이 지침대로 설치해줘”라고 해도 됩니다. Markdown 파일과 실제 배포 ZIP의 나머지 파일은 같은 폴더에 있어야 합니다.

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
- 기존 하네스 감지와 유지/교체 선택, 교체 전 암호화 백업 및 선택 범위의 이전 규칙·Hook 비활성화

모델 라우팅과 절차 수행은 Claude의 도구 사용과 생성 지침을 통해 이뤄집니다. 모델 가중치를 학습시키지 않으며 자체 검증 기록과 실제 테스트 결과는 구별해야 합니다. [구현 대조](docs/IMPLEMENTATION_REVIEW.md)에 근거와 범위를 정리했습니다.

0.3.3은 기존 하네스 유지/교체 선택을 추가합니다. 0.3.2에서 도입한 개인 저장 경로 재사용과 State 형식 보호도 유지합니다. 교체는 선택 범위에만 적용하며 상위 폴더·다른 범위·별도 플러그인의 지침/Hook까지 초기화하지 않습니다. [개인 상태 보존과 복구](docs/STATE_PRESERVATION.md)를 참고하세요. 업무 종료 후 경험을 자동 추출하여 Skill을 개선하는 Hermes형 학습 연결은 아직 별도 구현 대상입니다.

## 관리자 ZIP 생성

빌드 PC: Windows PowerShell 5.1+, Python 3.11+, Claude Code CLI 2.1.220+.

```powershell
# 인터넷 가능한 빌드 PC에서만 실행. 검증 ZIP을 폐쇄망 반입 가능.
powershell.exe -NoProfile -File .\deploy\Get-EmbeddedPython.ps1

# 외부 접속 없이 전체 배포 ZIP 생성
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion 0.3.3 -KnowledgeVersion 2026.09.03
```

Core/설정/Knowledge 변경 시 새 버전을 부여합니다. 정식 배포에는 회사 서명과 배포 채널을 사용합니다. MCP는 별도 개발·배포하며 DB와 Outlook 권한은 해당 서버에서 강제합니다.

[컨텍스트·Compact·실패 복구](docs/CONTEXT_OPTIMIZATION.md)에서 구현 범위와 native Rewind의 차이를 확인할 수 있습니다. 자동 대화 rewind나 업무 파일 rollback은 구현하지 않으며, 원본 기억을 지우는 압축도 하지 않습니다.

## 개발 검증

```powershell
python -m unittest discover -s .\tests -v
claude plugin validate --strict .\company-agent-plugin
powershell.exe -NoProfile -File .\deploy\Test-DeploymentSmoke.ps1
powershell.exe -NoProfile -File .\deploy\Test-ScopedInstallSmoke.ps1
powershell.exe -NoProfile -File .\deploy\Test-PersonalStateBackup.ps1
powershell.exe -NoProfile -File .\deploy\Test-ExistingHarness.ps1
powershell.exe -NoProfile -File .\deploy\Test-HarnessReplacement.ps1
```

Scoped smoke는 임시 Claude 설정과 프로젝트에서 실제 CLI 등록을 확인하며 개인 Claude 설정을 변경하지 않습니다. 내부 LLM/MCP를 호출하는 업무 검증과는 별개입니다.

```text
company-agent-plugin/   공통 플러그인, Python 코드, 프로젝트 Harness Factory
corporate-knowledge/    관리자 Markdown seed pack
config/                실행 설정, 별도 MCP 계약 예시
deploy/                쉬운 설치, scope 등록, 패키징, 기존 machine 배포
docs/                  직원 설치, 운영, 구현 대조, 프로젝트 하네스 생성
tests/                 동작·충돌·개인 상태 보존 테스트
```

[설치·배포](docs/DEPLOYMENT.md) · [프로젝트 하네스 생성](docs/PROJECT_HARNESS.md) · [구현 대조](docs/IMPLEMENTATION_REVIEW.md) · [회사 지식 작성](docs/ADMIN_KNOWLEDGE_GUIDE.md) · [MCP 계약](docs/MCP_CONTRACTS.md)

프로젝트 Harness Factory는 [revfactory/harness](https://github.com/revfactory/harness)의 도메인 분석·팀 설계·Skill 생성·검증 패턴을 참고한 독립 구현입니다. 직원 PC에서 해당 저장소에 접속하거나 외부 플러그인을 내려받지 않습니다.
