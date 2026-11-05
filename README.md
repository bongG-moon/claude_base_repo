# Company Harness

기존 Claude Code가 사용자의 업무 맥락과 선호를 기억하고, 검증된 업무 절차를 다시 사용하도록 돕는 개인화 하네스입니다. 모델을 재훈련하지 않으며 기존 모델 연결과 개인 자료를 유지합니다.

처음이라면 **[사용자 안내서](docs/Company-Agent-사용자-안내서.html)**를 여세요. 설치, 기억과 지식의 차이, 개인 스킬, 학습 내역, Claude Code 명령어와 단축키를 한 파일에서 볼 수 있습니다. 인터넷 없이 읽을 수 있으며 Noto Sans KR을 포함합니다.

기본 하네스는 **1.5.2**, 개별 스킬의 최신 갱신은 **2026-11-05 배포**입니다. [스킬 변경과 검증 기록](docs/releases/v1.5.2-skills-20261105.md)을 참고하세요. 기본 설치와 개별 업무 기능을 분리했습니다. 로컬 빌드와 온라인 게시, 직원 PC 업데이트는 서로 다른 단계입니다. 이전 공개 파일은 [Release 이력](https://github.com/bongG-moon/claude_base_repo/releases)에 보존됩니다.

## 기본 하네스와 개별 스킬

| 기본 설치에 포함 | 필요한 사람이 별도 설치 |
| --- | --- |
| 개인 선호와 지속적인 업무 맥락 | HTML 보고서와 웹 화면 제작 |
| 개인 지식과 출처 관리 | 편집 가능한 PPT 제작 |
| 회사 공통, 개인 전체, 프로젝트 범위 구분 | Excel 분석과 Python 전처리 |
| 설치된 스킬 검색, 선택, 재사용 | 파일 정리, DB 조회 |
| 개인 업무 절차를 스킬로 저장하고 같은 원본 수정 | 도구와 MCP 제작 |
| 근거가 있는 교정의 학습, 내역 확인과 복구 | 전체 업무 기록 분석과 자산 정리 |

개별 기능은 **[개별 스킬 설치 안내](skills_zip/등록_설치_안내.html)**에서 선택합니다. ZIP 하나로 사용할 수 있고 Company Harness 설치가 필요하지 않습니다. 해당 기능이 요구하는 Python 패키지나 업무 시스템 권한은 각 안내에 명시합니다. 설치했다고 실제 업무 연결까지 검증된 것은 아닙니다.

발표 제작은 `presentation`과 `huashu-presentation` 중 선택합니다. 둘 다 HTML에서 한 장씩 넘기는 발표가 기본입니다. `presentation`은 문구와 도형 묶음 편집, `huashu-presentation`은 Huashu의 발표 제작 방식과 원본 변환 엔진을 제공합니다. 개별 스킬 17개와 기존 별도 MCP 1개를 구분해 배포합니다.

기본 하네스에는 `company-agent`, `personal-memory`, `personal-knowledge`, `self-learning`, 개인 절차 저장용 `asset-factory`만 들어갑니다. 기본 `asset-factory`는 기존 업무를 개인 스킬로 저장하고 수정하는 역할입니다. 도구나 MCP를 제작하려면 개별 배포의 `asset-factory`를 사용합니다. 이름이 겹치면 선택한 출처를 유지합니다.

VLM 모델 자동 선택과 이미지 인계는 이번 구성에서 제외합니다. 사용자가 이미 설정한 모델이나 별도 MCP를 삭제하거나 변경하지 않습니다. 관련 스킬이 없어도 일반 요청은 기존 도구로 계속할 수 있습니다.

## 사용 예시

> 앞으로 팀 보고서는 결론부터 쓰고, 확인된 수치와 예상 수치를 구분해줘. 내 업무 방식으로 기억해줘.

> 이번에 확인한 업무 순서를 내 스킬로 저장해줘. 다음에는 같은 순서로 처리하고 싶어.

> 최근에 배운 내용을 보여줘. 실제 적용된 것과 아직 후보인 것, 보류한 이유를 구분해줘.

자동 학습은 지속적인 명시 교정, 독립된 업무에서 반복된 선택, 실제 사용하고 검증한 개인 절차 개선을 대상으로 합니다. 매 답변에 회고나 질문을 붙이지 않고 학습을 위해 끝난 업무를 다시 실행하지 않습니다. 새 스킬은 저장 요청이나 제안 수락 후 만듭니다. [학습의 동작과 한계](docs/SELF_LEARNING.md)를 참고하세요.

## 설치와 업데이트

Claude Code와 회사 승인 Python 3.11 이상이 준비된 Windows PC에서 직원용 `Company-Harness-Setup.exe`를 실행합니다. 사용할 범위를 선택한 뒤 설치하고 Claude Code를 다시 엽니다. ZIP으로 받았다면 **전체 압축을 푼 뒤** `Install-CompanyAgent.cmd`를 실행합니다. GitHub의 자동 `Source code (zip)`은 직원 설치 파일이 아닙니다.

같은 범위의 기존 설치는 백업 후 업데이트합니다. 개인 기억과 지식, 직접 설치한 스킬, 모델 설정과 MCP 연결은 유지합니다. 기본 설치에서 빠진 기능을 개인 폴더로 자동 복사하지 않습니다. 예전 회사 기능 스킬의 우선 선택이 남아 있으면 다른 후보로 몰래 바꾸지 않고 선택이 오래됐음을 안내합니다.

이전 설치 파일을 줄이려면 설치 화면의 **사용하지 않는 이전 설치 파일 삭제 (백업 없음)**를 선택합니다. 기본값은 보존입니다. 설치가 성공한 뒤 원본과 사용 여부가 확인된 이전 버전만 삭제하며, 개인 자료와 기존 백업은 유지합니다. Claude가 실행 중이거나 다른 프로젝트에서 쓰는 버전은 남깁니다.

개인 전체 스킬은 현재 Claude 설정 폴더의 `skills/<이름>/SKILL.md`, 프로젝트 스킬은 `<프로젝트>/.claude/skills/<이름>/SKILL.md`에 저장합니다. 같은 원본을 수정하며 `/<이름>`으로 사용합니다. 현재 호스트가 아직 목록을 갱신하지 않았다면 지원되는 스킬 새로고침이나 새 연결이 필요할 수 있습니다. 기존 비공개 저장소의 개인 스킬은 이동하거나 복제하지 않습니다.

설치기는 Python이나 pip를 내려받지 않고 PC의 PATH를 바꾸지 않습니다. 본인의 Windows 계정과 기존 설정 범위를 확인합니다. 다른 하네스를 교체하는 작업은 일반 버전 업데이트와 구분해 안내합니다. [설치와 배포](docs/DEPLOYMENT.md), [Claude에게 설치 맡기기](INSTALL_WITH_CLAUDE.md), [개인 자료 보존](docs/STATE_PRESERVATION.md)을 참고하세요.

별도 앱은 [Workspace 문서](docs/LOCAL_WORKSPACE.md)에서 다룹니다. 하네스 설치가 앱 배포나 업데이트를 대신하지 않습니다.

## 설치 파일 만들기

저장소 루트에서 Windows PowerShell 5.1로 실행합니다.

```powershell
powershell.exe -NoProfile -File .\deploy\New-OfflineBundle.ps1 -CoreVersion 1.5.2 -KnowledgeVersion 2026.09.03
powershell.exe -NoProfile -File .\deploy\Test-OfflineBundle.ps1
powershell.exe -NoProfile -File .\deploy\New-CompanyAgentSetup.ps1 -BundleZip .\dist\company-agent-1.5.2-2026.09.03.zip
```

뒤의 날짜는 회사 지식팩 버전입니다. 빌드는 게시나 개인 PC 설치를 실행하지 않습니다. 사내 GitLab 배포 자료는 `deploy/New-GitLabHarnessDelivery.ps1`로 준비합니다. 공개 Release나 GitLab 업로드는 별도로 진행합니다. EXE의 회사 코드 서명은 배포 담당자가 적용합니다.

소스 폴더 전체를 설치하지 않습니다. `deploy/harness-core-manifest.json`에 지정한 파일만 넣고 `harness-core/`의 짧은 핵심 지침을 적용합니다. `company-agent-plugin/`에 남아 있는 기능 엔진은 개별 ZIP을 만들 때 재사용하는 개발 소스입니다. 이 폴더를 직접 `--plugin-dir`로 로드하는 것은 직원용 기본 구성과 다릅니다. [구조와 검증 기록](docs/HARNESS_CORE_SPLIT.md)

## 개별 ZIP과 검증

```powershell
python -X utf8 -B scripts/build-skill-packages.py
python -X utf8 -B scripts/build-skill-packages.py --check
```

플랫폼 정본을 확인하고 원본과 `skills_zip`을 함께 갱신합니다. 현재 파일을 패키징하며 게시하거나 사용자 프로필에 자동 설치하지 않습니다. [패키지 관리](docs/PLATFORM_SKILL_PACKAGES.md)

검증은 격리된 설정과 가상 자료를 사용합니다. 설치 전후 개인 자료 보존, 스킬 생성과 수정, 기억 조회와 학습, 필요한 기능만 포함됐는지를 검사합니다. 로컬 계약 검증은 실제 사내 모델의 판단 품질이나 업무 성공률을 보증하지 않습니다.

```text
harness-core/           기본 설치의 짧은 지침과 작업자 정의
company-agent-plugin/   공통 런타임과 개별 패키지에서 재사용하는 개발 소스
standalone-skills/      독립 배포 스킬의 정본
skills_zip/             개별 배포 ZIP과 설치 안내
corporate-knowledge/    회사 공통 지식팩
deploy/                설치, 보존, 패키징과 배포 검사
docs/                  사용자 안내서와 운영 문서
tests/                 기능과 경계 회귀검사
```
