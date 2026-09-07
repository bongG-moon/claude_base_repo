# 전사 기본 Skill 및 Claude Plugin 검토

검토일: 2026-09-05

대상: `C:\Users\qkekt\Desktop\Agent_ground\agent_skill_hub` 및 현재 Company Agent 하네스

범위: 읽기 전용 조사와 도입 제안. 이 문서 외에 Skill 원본, 설치 설정, 배포 ZIP은 변경하지 않았다.

## 1. 결론

Hub 전체를 기본 설치하기보다 **작은 일반 업무팩 + 개발/UI/차트 선택팩**으로 재구성하는 것이 적합하다. 현재 Hub는 범용 사무 자동화보다 개발·디자인 절차에 강하다.

- 실제 Skill은 36개이며 Hub에서 active 31개, candidate 5개로 분류되어 있다. active가 곧 Company Agent와의 통합 검증 완료를 뜻하지는 않는다.
- 1차 기본팩에는 업무 요청 정리, 업무 계획, 업무 문서, 오류 해결의 네 기능을 회사용으로 수정해 포함하는 것을 권장한다.
- Context 선택, 근거 확인, 최소 변경, 단계별 검증은 별도 자동 발동 Skill을 늘리지 말고 기존 하네스 규칙을 보강하는 데 사용한다.
- 사내 용어·테이블 지식 정리에는 `re0`와 `ssotize`가 유용하지만 현재 Hub에서도 평가 대기 상태다. 작은 실제 업무 평가 후 추가한다.
- Office 파일 처리, 회의록, 업무 메일 작성 기능은 별도 보완해야 한다. Markdown Skill 설치만으로 Excel·Word·PPT·PDF 처리 실행환경이 생기지는 않는다.

여기서 말하는 평가 대기는 **조직 기본 배포본을 고르는 작업**이다. 개인이 만든 Skill을 자동 활성화하고 필요하면 자발적으로 공유한다는 기존 요구를 변경하거나, 개인 Skill에 관리자 승격 절차를 추가하자는 뜻이 아니다.

## 2. 먼저 넣을 기본 기능

아래 회사 Skill 이름은 구현 제안이며 아직 생성·설치되지 않았다.

| 회사 기본 기능 | 재사용할 Hub 내용 | 사용자 요청 예 | 필요한 조정 |
| --- | --- | --- | --- |
| `work-brief` — 업무 요청 정리 | `idea-refine`, `interview-me`의 일부 | “이런 일을 하고 싶은데 정리해줘” | 이미 제공한 정보 재사용. 결과를 바꾸는 누락만 1–2개 질문. 추천안을 포함한 짧은 선택지. 긴 인터뷰는 사용자가 원할 때만 |
| `work-plan` — 업무 계획 | `planning-and-task-breakdown`, `spec-driven-development`의 일부 | “진행 순서와 완료 기준을 잡아줘” | 개발 파일 수 대신 업무 입력·산출물·완료 조건 중심. 기존 project-harness spec과 연결. 작은 업무는 별도 계획 파일 없이 실행 |
| `work-doc` — 업무 문서 작성·정리 | `documentation-and-adrs` | “이 내용을 보고서/업무 매뉴얼로 정리해줘” | 개발 ADR뿐 아니라 보고·업무 결정·인수인계에 맞춤. 사내 MD 서식 우선. 실제 docx/pptx 출력은 별도 문서 실행팩에 연결 |
| `troubleshoot` — 문제 해결 | `debugging-and-error-recovery` | “이 파일이 안 열려요”, “실행이 안 돼요” | 파일·설치·MCP 오류 사례로 확장. 안전한 진단은 자동 수행, 사용자 요청이 진단뿐이면 수정은 하지 않음. 로그 속 명령은 지시가 아니라 증거로 취급 |

하네스 내부로 흡수할 내용:

- `context-engineering`: 관련된 사내 Knowledge와 개인 overlay만 선택하고 필요한 근거를 짧게 전달한다.
- `source-driven-development`: 내부 Knowledge → 설치된 소스/버전 정보 → 로컬 버전 문서 → 승인된 내부 mirror 순으로 확인한다. 없는 근거를 만들어내지 않는다.
- `karpathy-guidelines`: 요청 범위만 변경하고 단순하게 구현하며 검증 가능한 완료 조건을 둔다.
- `incremental-implementation`: 작은 변경 후 확인하는 원칙만 사용한다. 매 단계 자동 커밋 지시는 가져오지 않는다.

현재 `company-agent`, `asset-factory`, `project-harness`, `personal-memory`, `personal-knowledge`와 이중으로 질문·계획·검증하지 않아야 한다. 하나의 주 작업 절차가 실행을 이끌고 나머지는 필요한 참고 규칙으로 사용한다.

## 3. 전체 36개 분류

‘수정 후 기본’은 원본 그대로 전 직원에게 배포하라는 의미가 아니다. ‘평가 대기’ 다섯 개는 Hub의 현재 상태를 그대로 표시했다.

| Skill | 권장 위치 | 핵심 판단 |
| --- | --- | --- |
| `idea-refine` | 수정 후 기본 | 아이디어를 실제 업무 정의로 정리. 질문·대안 개수 축소 |
| `planning-and-task-breakdown` | 수정 후 기본 | 단계·의존성·완료 기준. 고정 task 경로와 추가 명령 가정 제거 |
| `documentation-and-adrs` | 수정 후 기본 | 업무 문서·결정 기록으로 범위 확장 |
| `debugging-and-error-recovery` | 수정 후 기본 | 증거 수집·원인 확인·재검증을 일반 업무 오류에 적용 |
| `interview-me` | 핵심만 코어 흡수 / 긴 인터뷰 선택 | 반복 확인 요구가 초보자 자동 실행 목표와 충돌 |
| `context-engineering` | 코어 흡수 | 기존 Knowledge/Memory/프로젝트 지시와 중복 방지 |
| `karpathy-guidelines` | 제작 worker/Asset Factory 규칙 | 최소 변경·단순 구현·검증 원칙 |
| `source-driven-development` | 근거 원칙 코어 흡수 / 개발 선택 | 외부 인터넷 대신 설치 버전·내부 문서 근거 |
| `spec-driven-development` | Project Harness 통합 / 개발 선택 | 기존 생성 spec 재사용. 단계마다 불필요한 사용자 승인 반복 금지 |
| `incremental-implementation` | 개발 선택 / 일부 코어 흡수 | 자동 커밋·DB 변경 예시 수정 필요 |
| `api-and-interface-design` | 개발팩 | MCP·자동화·서비스 인터페이스 설계 |
| `test-driven-development` | 개발팩 | 테스트 가능한 코드 변경에 한정, 일반 문서에는 미발동 |
| `code-review-and-quality` | 개발팩 | 변경 코드 검토. 요청 없는 수정·게시로 확대하지 않음 |
| `code-simplification` | 개발팩 | 동작 보존을 검증하며 범위를 제한 |
| `security-and-hardening` | 개발팩 / 제작 검증 규칙 | 생성한 Tool/MCP의 안전성 보완. Windows 명령과 사내 정책 반영 |
| `frontend-ui-engineering` | UI팩 | 화면·대시보드·HTML 보고서 프로젝트 |
| `browser-testing-with-devtools` | UI팩의 조건부 기능 | 별도 로컬 Chrome DevTools MCP와 격리 브라우저 필요 |
| `doubt-driven-development` | 고급 개발/검증 선택 | 메인 조정자에서만 사용. 회사 검증 Agent에 연결하고 재귀 루프 방지 |
| `performance-optimization` | 성능 업무 선택 | 측정 근거가 있는 최적화에 사용 |
| `git-workflow-and-versioning` | Git 업무 선택 | 커밋·push는 사용자 요청 범위에서만 |
| `shipping-and-launch` | 운영 담당 선택 | 사내 배포 계약과 실행 권한 확인 전 실제 배포하지 않음 |
| `observability-and-instrumentation` | 운영 담당 선택 | 내부 수집기 또는 로컬 진단에 한정. 외부 계정/전송 전제 제거 |
| `deprecation-and-migration` | 운영 담당 선택 | 회사 DB 변경은 계획·초안만. 실제 DB 도구의 SELECT-only 유지 |
| `flint-chart-author` | 차트팩, 실행환경 포함 시 | 차트 스펙 생성은 가능. 실제 그림에는 Flint MCP/runtime 필요 |
| `hallmark` | 수정 후 UI팩 | 사내 포털·HTML 보고서에 유용. 원격 이미지/폰트 예시 제거 필요 |
| `animation-vocabulary` | UI팩 참고 문서 | 독립 자동 Skill보다 용어 reference로 사용 |
| `apple-design` | UI팩 선택 참고 문서 | Apple 스타일 원칙이며 macOS 설치 요구는 아님. 사내 브랜드가 우선 |
| `emil-design-eng` | 수정 후 UI팩 참고 문서 | 질문이 없으면 대기하는 지시를 자동 실행 흐름에 맞춤 |
| `find-animation-opportunities` | UI 전문가 선택 | 애니메이션 기회 분석 전용, 구현 완료로 보고하지 않음 |
| `improve-animations` | UI 전문가 선택 | 계획 작성과 실제 소스 수정을 구분 |
| `review-animations` | UI 전문가 수동 선택 | 좁은 diff 검토. 근거 없는 지적을 늘리지 않도록 조정 |
| `project-design-context` | UI팩 후보 — 평가 대기 | 프로젝트 DESIGN.md와 개인 디자인 선호. 회사 Knowledge 구조와 연결 |
| `re0` | 지식/문서 정리 후보 — 평가 대기 | 요청된 단일 문서 정리. 이력·출처·필수 계약 보존 |
| `ssotize` | 지식 정합성 후보 — 평가 대기 | 용어·테이블 정의의 중복/충돌 조사. 개인 overlay에서 보완 |
| `mandela` | 평가 설계 보조 — 평가 대기 | 자기확증·평가 누수 점검. 독립적인 테스트의 대체물은 아님 |
| `langflow-1-9-2-development` | 전사 기본 제외 — 평가 대기 | 정확한 Langflow 버전용. 해당 사내 버전 프로젝트에만 검토 |

`re0`/`ssotize`를 넣더라도 개인 수정은 개인 Knowledge overlay 또는 사용자가 지정한 프로젝트 문서에 저장한다. 업데이트로 교체될 Corporate Base나 다른 직원의 기준 문서를 자동 덮어쓰지 않는다. 확정된 사내 기준과 개인적으로 보완한 정의를 표시한다.

## 4. 기본 반입 전 고쳐야 할 실제 항목

### 4.1 사용자 상호작용과 실행 범위

- `interview-me/SKILL.md:113` 부근은 “알아서”, “좋아요”, “진행해요”에 해당하는 응답을 충분한 확인으로 보지 않고 다시 질문하도록 한다. 회사 기본판에서는 중요한 미결정 사항만 묻는다.
- `idea-refine/SKILL.md:62` 부근은 3–5개 질문과 5–8개 대안을 요구한다. 단순 업무는 초안을 먼저 제시하도록 줄인다.
- `incremental-implementation/SKILL.md:239` 부근은 매 단계 commit과 깨끗한 working tree를 요구한다. 사용자 변경을 보존하고 자동 커밋은 요청 범위로 제한한다.
- `deprecation-and-migration/SKILL.md:188`에는 UPDATE/CREATE INDEX 예시가 있다. 설명·스크립트 초안과 실제 DB 실행을 분리한다.

Skill은 업무 수행 지침이지 보안 경계가 아니다. DB SELECT-only와 본인 Outlook 계정 발신 제한은 별도 개발될 MCP 서버·인증·DB 권한에서 강제해야 하며, Skill이 우회 도구를 만들도록 안내하지 않게 한다. 메일 초안 작성은 발송 요청과 구분하고, 발송 자체를 항상 금지하는 정책을 새로 만들지는 않는다.

### 4.2 오프라인과 Windows

- Hallmark의 `references/assets.md`는 원격 URL을 금지하지만 `references/imagery-kit.md`에는 usehallmark.com 이미지 URL 예시가 남아 있다. 폰트 문서에도 공개 서비스 관련 잔재가 있다. 로컬 자산·사내 서체·SVG로 치환한다.
- `idea-refine/scripts/idea-refine.sh`는 폴더 생성용 shell helper다. 기존 파일 도구 또는 PowerShell로 대체할 수 있다.
- 브라우저·Flint Skill은 MCP 실행파일을 함께 제공하지 않는다. `npx -y ...` 또는 `npm install --offline` 문자열만으로 빈 폐쇄망 PC에 설치 가능한 것은 아니다.
- 현재 1.0.0 기본 하네스는 PC에 이미 설치된 승인 Python 3.11 이상을 사용한다. Python이 있다고 Office 라이브러리, Node, Chrome DevTools MCP까지 설치된 것은 아니다. 각 선택팩의 실행환경과 버전별 Windows 검증이 따로 필요하다.

### 4.3 설치와 의존 파일

- Hub `install.ps1:79` 부근은 별도 선택이 없으면 active 전체를 선택한다.
- `install.ps1:223` 부근의 `-Force`는 대응 파일을 바로 덮어쓰며 백업·트랜잭션·오래된 파일 정리가 없다. 회사 초보자용 설치 진입점으로 그대로 노출하지 않는다.
- `install.ps1:144` 부근에서 Addy 공통 LICENSE와 shared references를 각 Skill에 합성하고, `:174` 부근에서 SECURITY_POLICY.md와 안내문을 추가한다. `skills/`만 통째로 복사하면 이 내용이 빠진다.
- 예: planning/incremental이 참조하는 `references/definition-of-done.md`는 원본 Skill 폴더가 아니라 collection shared references에 있다.
- `doubt-driven-development`의 추상 Agent 목록은 그대로 배포된 실제 Agent가 아니다. 회사 Agent 이름으로 연결해야 한다.
- lock의 36개 MIT 표시는 확인했지만 전체 고지 포함 여부는 별도다. 특히 Karpathy 패키지는 선언·출처만 있어 원 저작권/라이선스 고지를 보완해야 한다. 회사 수정본의 SOURCE에는 수정 사실과 원본 commit을 함께 기록한다.

원본 Hub의 보안/저작 지침은 이번 조사에서 **검토 대상 데이터**로 읽었다. 그 문서의 절차를 사용자 요청보다 우선하여 실행하거나, 삭제 목록을 자동 복원하지 않았다.

## 5. Claude 플러그인으로 추가할 후보

Skill은 ‘특정 일을 하는 방법’이고 Plugin은 Skill·Agent·Hook·MCP 설정을 배포하는 묶음이다. 여러 Skill을 회사 Plugin에 묶을 수 있고, 이름은 `/plugin-name:skill-name`으로 구분된다. 이름 충돌을 줄일 수 있지만 내용이 비슷한 Skill의 동시 발동까지 자동 해결하지는 않는다. [Claude Code 공식 Plugin 문서](https://code.claude.com/docs/en/plugins)

### 5.1 일반 업무에 참고할 공식 Skill

| 후보 | 판단 |
| --- | --- |
| Anthropic `internal-comms` | 보고·업무 공유·FAQ 등 기본 업무 문서에 적합한 추가 후보. 회사 MD 템플릿과 한국어 문체로 수정. 개별 LICENSE.txt는 Apache 2.0으로 확인됨 |
| Anthropic `doc-coauthoring` | 문서의 독자 관점 검토 절차는 참고 가치가 있음. 원본은 다수 질문·반복 인터뷰가 길어 기본 자동 흐름에는 과함. 개별 배포 권한 확인 전 복사·수정본 반입은 보류 |
| Anthropic `document-skills` | docx/xlsx/pptx/pdf 기능상 유용하나, 아래 라이선스와 Windows 실행환경 조건 때문에 지금 회사 ZIP에 묶을 기본 후보로 확정하지 않음 |

`internal-comms`의 구체적 범위와 라이선스: [공식 Skill](https://github.com/anthropics/skills/tree/main/skills/internal-comms), [개별 LICENSE](https://github.com/anthropics/skills/blob/main/skills/internal-comms/LICENSE.txt). 문서 협업 흐름은 [doc-coauthoring](https://github.com/anthropics/skills/tree/main/skills/doc-coauthoring)에서 확인했다.

공식 marketplace의 `example-skills`에는 문서 협업 외에도 디자인·MCP 제작·Skill 제작 등 여러 기능이 함께 들어 있다. 단지 internal-comms 하나를 쓰려고 전부 중복 설치하기보다, 허용된 구성요소만 고정해 회사팩으로 묶는 편이 적합하다. [공식 marketplace manifest](https://github.com/anthropics/skills/blob/main/.claude-plugin/marketplace.json)

**문서 스킬 라이선스 주의:** 공식 README도 docx/pdf/pptx/xlsx를 open source가 아닌 source-available로 구분한다. 검토일의 개별 LICENSE에는 서비스 밖 보관·복제·파생물·배포 제한이 명시되어 있다. 공개 GitHub에 있다는 이유로 사내 모델용 수정본을 ZIP에 복제·재배포할 수 있다고 판단하지 않는다. 사내 계약/허용 범위를 확인하거나, 해당 자료를 복제하지 않는 별도 회사 문서 Skill을 구현한다. [공식 설명](https://github.com/anthropics/skills), [docx LICENSE](https://github.com/anthropics/skills/blob/main/skills/docx/LICENSE.txt), [xlsx LICENSE](https://github.com/anthropics/skills/blob/main/skills/xlsx/LICENSE.txt), [pptx LICENSE](https://github.com/anthropics/skills/blob/main/skills/pptx/LICENSE.txt), [pdf LICENSE](https://github.com/anthropics/skills/blob/main/skills/pdf/LICENSE.txt)

### 5.2 개발 플러그인은 중복 설치보다 선택

- `skill-creator`, `claude-md-management`, `feature-dev`, `code-simplifier`는 현재 Asset Factory·Knowledge·Project Harness·Hub 개발 Skill과 겹친다. 이미 사용자 환경에 설치된 것은 보존하며 회사판과의 작업 우선순위를 정한다. 전 직원에게 별도 상시 설치할 우선순위는 낮다.
- `frontend-design`은 UI팩의 대체 후보다. Hallmark 등 여러 UI 주 흐름을 동시에 자동 실행하기보다 주 디자인 절차 하나와 사내 브랜드 참고 문서를 결합한다.
- `code-review` 공식판은 GitHub PR 및 인증된 `gh`를 전제로 하고 댓글 게시를 포함한다. 로컬 코드 검토용 기본팩과 같지 않으므로 그대로 전사 기본 설치하지 않는다.
- `pyright-lsp`, `typescript-lsp`는 해당 언어 개발 프로젝트에서 후보가 될 수 있다. 언어 서버 실행파일까지 사내 번들에 있어야 한다. 일반 사무 사용자에게 필요하지 않다.

확인 근거: [공식 Plugin catalog](https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json), [code-review 요구사항/동작](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/code-review), [frontend-design](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design). 이 목록 확인은 각 Plugin의 모든 파일·라이선스·실행 경로에 대한 반입 승인까지 의미하지 않는다.

### 5.3 차트는 Flint를 선택적으로

Flint는 로컬에서 PNG/SVG를 렌더링하는 MCP가 있어 사내 데이터 시각화 후보로 적합하다. 정적 렌더링은 브라우저 없이 실행할 수 있다. Node, Windows native dependency, 사내 한글 폰트, 고정된 MCP/Skill 버전은 함께 준비·검증해야 한다. Claude Code에서는 `render_chart` 기반 정적 출력부터 제공하고, MCP App UI가 반드시 표시된다고 약속하지 않는다. [Flint 공식 MCP 설명](https://github.com/microsoft/flint-chart/blob/main/packages/flint-mcp/README.md)

현재 upstream은 로컬 파일 참조를 기본 허용하며 호스트의 접근 통제를 신뢰한다. 사내 파일 경계를 더 제한하려면 버전의 실제 옵션을 확인해 inline 데이터만 허용하거나 회사 파일 접근 wrapper를 사용한다. 원격 URL을 사용하지 않는다는 것만으로 모든 로컬 파일 접근 정책이 해결되는 것은 아니다. 같은 공식 MCP 문서의 Security & limits 및 CLI options 참고.

## 6. 부족한 일반 업무 기능

Hub의 이름·본문·실행 파일을 검토한 결과 아래 기능은 전용 업무 Skill로 보완할 가치가 크다.

| 우선순위 | 추가 기능 | 기본 동작과 완료 확인 |
| --- | --- | --- |
| 높음 | 보고서·업무 공유문 작성 | 사내 템플릿과 제공한 사실 사용. 확정 사실/추정/미확인 구분 |
| 높음 | 회의록·액션 아이템 | 제공된 회의 메모에서 결정/할 일 추출. 담당자·기한이 없으면 임의로 확정하지 않음. 녹음·외부 회의 연결을 기본 요구하지 않음 |
| 높음 | 업무 메일 | 먼저 초안 작성. 발송 요청 시에만 별도 `corp-outlook-self` 사용. 수신자·첨부 누락 등 필요한 입력만 질문 |
| 높음 | 표/CSV/Excel 정리·검증 | 원본 보존, 행 수·단위·중복·집계 범위 확인. 수식 저장과 실제 계산 검증을 구분 |
| 다음 | Word/PPT/PDF 파일 제작·수정 | 실행 라이브러리·변환기·한글 폰트 포함. 파일 재열기와 필요한 렌더 검증. 확장자만 맞춘 파일을 성공으로 보고하지 않음 |
| 다음 | 사내 지식 문서 정합성 | 기존 Personal Knowledge를 중심으로 출처·정의 충돌·개인 보완 기록. `re0`/`ssotize` 검증 후 보조 연결 |

문서 작성 절차는 작은 기본팩으로 시작할 수 있다. 실제 Office 파일 변환·렌더링은 크기와 의존성이 다른 선택 실행팩으로 분리하고, 누락된 도구를 직원에게 복잡한 명령으로 설치시키지 않도록 한다.

## 7. 기존 설치 흐름에 연결할 방식 — 구현 제안

1차는 기존 `company-agent` Plugin에 회사용 기본 Skill 네 개를 추가하는 것이 가장 단순하다. 별도 Hook·Memory 엔진·모델 라우터를 중복 탑재하지 않는다. 이후 선택팩을 같은 내부 marketplace와 설치 진입점에 추가한다.

| 사용자에게 보일 항목 | 구성 | 기본 선택 |
| --- | --- | --- |
| 일반 업무 | 기존 하네스 + 수정한 네 기본 기능 | 예 |
| 코드·자동화 만들기 | 개발 선택 Skill, 필요한 프로젝트 검사 도구 | 아니오 |
| 화면·HTML 보고서 만들기 | 회사 UI 지침 + 선택 디자인 Skill | 아니오 |
| 차트 만들기 | Flint Skill + 검증된 로컬 MCP/runtime | 실행환경 준비 후 |
| Office 문서 다루기 | 별도 허용된 문서 Skill + 실행 라이브러리/변환기 | 실행팩 준비 후 |

직원에게 36개 Skill 이름을 고르게 하지 않는다. 기존처럼 파일 하나를 실행하거나 Claude에게 설치를 맡기고, 적용 범위는 **Claude 전체 / 이 프로젝트만** 중 고른다. 기본 업무팩은 포함하고 선택팩은 업무 목적을 짧게 물어보거나 “이 프로젝트에서 차트 작업도 하고 싶어”라는 요청으로 추가한다. 이 선택팩 UI는 아직 구현된 기능이 아니다.

기술 적용 원칙:

1. Hub catalog의 명시적 allowlist로 원본·참고 파일·라이선스를 조합하고, 회사 수정본의 source/해시를 별도로 기록한다. 전체 active를 암묵적 기본값으로 삼지 않는다.
2. 기존 `Install-ScopedCompanyAgent.ps1`의 User/Project 범위, 설치 전 백업, 버전별 공통 배포, 등록 실패 복원을 재사용한다. 기존 범용 Skill을 삭제하거나 덮어쓰지 않는다.
3. 선택팩에는 Hook을 기본 탑재하지 않는다. 하네스의 질문·개인 Memory·모델 라우팅·자기 수정 루프는 하나만 유지한다.
4. 개인 Skill/선호/사내 지식 보완은 현재 scope의 로컬 User State에 둔다. 공통팩을 업데이트해도 개인 파일을 교체하지 않는다.
5. SMALL/MEDIUM/LARGE는 기존 worker 라우팅을 유지한다. 단순 정리에는 가벼운 경로, 복합 분석에는 중간 경로, 재사용 Tool/Skill 설계·복잡한 검증에는 큰 경로를 활용하되 각 Skill이 모델을 임의로 다시 설정하지 않는다.
6. 실행팩은 설치 전에 Claude 버전·OS·경로·동봉 런타임·해시·실행 테스트를 확인한다. 누락되면 해당 기능만 미설치 상태로 설명하고, 업무 데이터나 자격 증명을 외부로 보내지 않는다.

## 8. 검증 결과와 실제 반영 전 확인

이번 검토에서 설치 없이 실행한 검사:

- `python -B scripts/build_exports.py --check`: 47개 export 및 canonical/package/shared 해시 검사 통과.
- `python -B scripts/skill_eval.py validate --suite all`: 3개 suite, 51개 case의 구조 검사 통과.

이는 **사내 모델로 업무를 수행해 성공했다는 의미가 아니다**. candidate 다섯 개의 routing eval은 여전히 pending이다. Windows에서 Office·브라우저·Flint를 실제 실행하거나 현재 Company Agent를 재설치하지도 않았다.

첫 배포 전에 확인할 대표 시나리오:

- “이 업무 정리해줘”에 장시간 인터뷰 없이 초안을 제시하는가.
- 질문에 이미 답했으면 재질문하지 않고, 중요한 누락만 짧게 묻는가.
- 문서 작업에 개발 TDD/commit/배포가 잘못 발동하지 않는가.
- 진단·검토 요청에서 원본 수정이나 메일 발송을 임의로 하지 않는가.
- 코드 생성 후 실제 테스트 증거와 모델의 자체 평가를 구분하는가.
- 사내 용어 수정이 개인 overlay에 보존되고 공통 업데이트 후에도 유지되는가.
- 기존 동명/유사 Skill이 있는 PC에서 기존 파일 보존과 주 절차 선택이 되는가.
- Project 설치는 해당 프로젝트 밖에 적용되지 않고, User 설치는 해당 사용자의 전체 작업에 적용되는가.
- 개인 Skill 자동 활성화가 유지되며 조직 공통팩 선정 절차와 혼동되지 않는가.
- 동봉 실행환경만 있는 오프라인 Windows PC에서 한글 파일명·한글 폰트·공백 경로가 동작하는가.

권장 다음 작업은 **기본 네 기능의 회사판 제작 → 기존 하네스 통합 평가 → 일반 업무부터 파일 실행팩 보완**이다. Hub 원본을 즉시 통째로 설치하는 작업은 권장하지 않는다.
