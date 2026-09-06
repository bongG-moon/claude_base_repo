# 최초 의도 대비 구현 점검

구현의 기준은 이미 사내 모델과 연결된 Windows Claude Code입니다. 모델 연결·API 변환 계층을 다시 구축하지 않습니다. 아래는 코드에서 제공하는 기능과 별도 업무 검증이 필요한 범위를 구분한 점검입니다.

| 최초 요구 | 실제 구현 | 확인 근거와 한계 |
| --- | --- | --- |
| 사용자 지시를 받아 실행·검증·수정 | 요청 Hook, 실행 Skill, 작업별 Agent, PostToolUse 활동 기록, Stop 검증 기록 확인 | `state.py`는 변경 후 검증 표시가 없을 때 최대 두 번 보정을 유도한다. `session verify --status pass`는 Agent가 작성하는 기록이며 실제 테스트 성공을 독립 증명하지 않는다. |
| 업무 난도에 따른 SMALL/MEDIUM/LARGE | `model_router.py`의 규칙 기반 분류와 기존 haiku/sonnet/opus 별칭의 worker frontmatter | 키워드와 요청 특징으로 분류하고 메인 대화가 적합한 worker를 호출하는 구조다. Hook이 메인 세션 모델을 직접 강제 전환하지 않는다. 실제 내부 모델 식별은 사내 실행에서 확인해야 한다. |
| 지속적인 개인화 | 추출한 Markdown Memory 저장, 관련 항목 검색·주입, 사용자 Knowledge overlay | 모델 가중치 학습이 아니라 재사용 가능한 지식·규칙·절차 축적이다. Memory와 파일 속 지시는 사용자 요청이나 회사 정책보다 우선하지 않는다. |
| Hermes형 자동 학습 연결 | 아직 미구현 | 실행/검증/재시도와 개인 Memory·Skill 생성/수정·검색은 있으나, 업무 종료 후 경험을 추출하고 기존 Skill을 고치는 자동 검토 호출과 다음 업무 성과 평가는 연결되지 않았다. 저장 기능이나 재시도 Hook을 완성된 폐쇄형 학습 루프로 설명하지 않는다. |
| 세션 원문과 Memory의 효율적 관리 | Harness는 짧은 검증 상태와 추출된 Memory/Knowledge를 저장 | Harness가 원문을 별도로 복제하지 않는다는 의미다. Claude Code 자체 history·transcript의 저장 정책을 변경하거나 기존 로그를 삭제하지 않는다. |
| 관리자 지식을 개인도 발전시킴 | Markdown Corporate Base + 개인 extend/fork/personal-new, 로컬 재생성 인덱스 | `knowledge.py`가 원본 변경 시 overlay의 재반영과 충돌 표시를 수행한다. 개인 파일을 회사 원본에 자동 덮어쓰거나 회사 공용 Skill로 승격하지 않는다. |
| 개인 Skill 자동 사용 | Asset Factory에서 Skill 생성 후 개인 저장, 활성 항목 검색과 런타임 문맥 안내 | 신규 기본 설치에서는 관련 Skill을 문맥으로 찾아 Read하여 적용한다. 모든 개인 Skill이 Claude slash 메뉴에 표시된다는 뜻은 아니다. |
| 사용자 Tool/MCP 생성 지원 | AssetSpec, 정적 검사, 제한된 실행 검사, 콘텐츠 해시에 연결된 활성화 기록 | Python Tool/MCP는 현재 사용자 권한으로 실행한다. 검사와 해시는 OS 격리가 아니며, 사내 MCP SDK 등 오프라인 의존성은 해당 자산 구현에 필요하다. |
| DB 조회만·메일 본인 계정 | 해당 MCP 이름에 대한 사전 검사와 정책 지침 | `corp-db-read`, `corp-outlook-self` 서버는 별도 개발 대상이다. DB 권한 및 인증 메일함 고정은 해당 MCP 서버가 집행해야 하고 프롬프트 지침만으로 보장되지 않는다. |
| Core 배포 후 개인 데이터 보존 | 배포/개인 영역 분리; 기존 지정 경로 재사용; 개인 학습자료 선택 백업; State 형식 확인 | 0.3.2에서 사용자 지정 경로 생략 업데이트 시 연결이 기본 경로로 바뀌던 문제를 보완했다. 경로 변경은 자동 이관하지 않으며, 지원하지 않는 State 형식은 보존 후 거절한다. `STATE_PRESERVATION.md`에 백업 제외 항목과 제한을 명시했다. |
| 초보자 설치와 범위 선택 | 설치 진입 파일, 사전 조건 검사, 필요한 범위·프로젝트 선택, Claude 설치 위임 문서 | Claude Code가 이미 설치된 환경을 전제로 한다. 배포 ZIP과 실제 회사 PC의 사전 조건 검사는 구분하며, 패키지에 포함된 런타임과 설치 결과로 확인한다. |
| 기존 하네스 유지 또는 백업 후 교체 | 선택 범위의 기존 지시·규칙·Hook/Company Agent 등록 감지, `Ask/Keep/Replace`, DPAPI 원본 백업, 실패 복구 | 0.3.3에서 추가했다. Keep은 변경 없이 종료하며 Replace만 선택 범위의 기존 Markdown 지시·규칙과 settings의 최상위 hooks를 비활성화한다. 모델·MCP·개인 상태·일반 Skill·다른 플러그인은 유지한다. 상위 폴더/다른 범위/플러그인 자체의 Hook까지 초기화하지 않는다. 암호화 백업은 같은 Windows 사용자·PC에서 복구하며 지시 파일/새 Hook 충돌은 덮어쓰지 않고 Hook 이외의 설정 변경은 보존한다. |
| 프로젝트별 하네스를 쉽게 만듦 | Project Harness Factory가 목적·작업·성공 기준을 받아 namespaced Agent/Skill/규칙 생성 | 표준 subagent와 여섯 협업 패턴을 지원한다. 생성된 프로젝트 파일은 일반 Claude에서도 사용된다. Factory의 결정적 검사는 구조·소유권·경로 검증이며 실제 업무 품질의 대체물이 아니다. |

새 Project Factory 검증에는 기존 파일 충돌, 수동 편집 보존과 명시적 재생성, 백업, 변경 실패 원복, 반복 실행, 조작된 manifest, junction 차단을 포함했습니다. 실제 CLI의 inspect → plan → apply → validate를 한글 경로의 일반 업무 분석 및 API 개발 예제로 실행합니다. 이 확인은 코드 생성기의 동작 검증이며 내부 모델 호출이나 사내 MCP의 통합 검증은 아닙니다.

이 구조를 Hermes와 같은 별도 자율 실행 엔진의 완전한 재구현으로 설명하면 과장입니다. Claude Code의 Hook·Skill·subagent 기능을 이용해 개인화 저장과 검증 절차를 제공하고, 프로젝트별 구성을 생성하는 확장입니다. 사내 도입 확인에서는 대표 업무 한 건의 실제 실행 결과, 선택된 worker 모델, 검증 증거, 사용자 피드백의 다음 요청 반영을 함께 확인하면 됩니다.
