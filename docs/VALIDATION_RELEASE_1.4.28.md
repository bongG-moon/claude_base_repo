# 1.4.28 배포 검증

검증일: 2026-09-27. 회사 지식팩 `2026.09.03`, Workspace 실행 코드 `0.9`를 유지합니다. [변경 안내](UPDATE_1.4.28.md)를 참고하세요.

## 이번에 다시 확인한 내용

| 검사 | 결과 |
| --- | --- |
| 변경 영향 범위 Python 회귀 | 25개 모듈 360건 실행: 359통과, 실패·오류 0, 생략 1. 93.391초 |
| 공통 작성 지침 | 일반·축약·최소 문맥과 3종 작업자 전달, 6,000자 기본 예산, 요청·모델·회사 정책 보존 확인. 공유 규칙 증가 319자 |
| 기존 산출물 계약 | HTML/PPT 레이아웃, 수치 계산, 원문·조건·인용 보존, 요청형 다이어그램·기존 승인·최종 결과 전달 회귀 통과 |
| 스킬 진입점 | HTML/PPT/Outlook 일반 스킬 검사 통과. 새 스킬·후크·외부 모델 호출 없음 |
| 안내서 동기화 | `build-manuals.mjs --check` 통과. 6부·52장, 395,443 bytes, 단독 HTML·설치 사본·Markdown 원본 7개 일치 |
| 설치 ZIP 생성 | 실제 Claude 플러그인 strict 검사, 회사 지식 검사, Python 구문 검사 통과. 기존 승인 Python 사용, 실행 파일 다운로드·동봉 없음 |
| 설치 ZIP 회귀 | Windows PowerShell 5.1 `Test-OfflineBundle.ps1` 통과. 허용 파일·무결성·동일 버전 다른 내용 교체 방지 및 새 Apache 라이선스 포함·원본 일치 확인 |
| 실제 ZIP 업데이트 | Windows PowerShell 5.1 `Test-ReleaseUpgrade.ps1`: 1.4.27 → 1.4.28 통과. 격리 설정의 실제 Claude 등록·SessionStart, 개인 모델/MCP/기억/스킬·긴 경로 백업·원본 ZIP 보존 확인 |
| Workspace | `check-workspace-bundle.py`: 33개 파일의 현재 소스 일치·실행기 진단 hash pin 유지 확인. 실행 코드는 변경하지 않음 |
| 최종 파일 독립 감사 | Core 207개 원본 + manifest, Workspace 33개 원본, 단독 HTML 모두 원본 바이트·크기·SHA-256 일치. CRC·경로 이탈·중복·링크·암호화 오류 없음. 개인 상태·인증·실행 파일·과거 Office Reader/CUA 시험 자료 미포함 |
| 비밀정보 검사 | 변경 28개 파일의 주요 비밀키 패턴 탐지 0건. 모든 기밀 데이터 형식을 보증하는 DLP 검사는 아님 |

생략 1건은 `test_artifact_delivery.ArtifactDeliveryTests.test_linked_state_is_rejected`입니다. 현재 Windows 계정에 심볼릭링크 생성 권한이 없어 실행하지 못했습니다. 최초 패키지식 테스트 수집에서 기존 모듈 import 경로 오류가 있었으며, 테스트 경로를 바로잡아 25개 모듈 전체를 위와 같이 재실행했습니다.

검사 모듈: `test_native_runtime`, `test_task_skill_context`, `test_skill_workflow`, `test_skill_list_review`, `test_skill_host_choice`, `test_skill_compact_continuation`, `test_lean_skill_contract`, `test_guide_presentation`, `test_design_terms_guide`, `test_handbook_contract`, `test_writing_guidance`, `test_user_language`, `test_worker_runtime_handoff`, `test_design_guidance`, `test_report_styles`, `test_report_design`, `test_presentation_preparation`, `test_presentation_design`, `test_explanation_skill_routing`, `test_explanation_integration`, `test_explanation_diagram`, `test_explanation_controls`, `test_business_artifacts`, `test_artifact_delivery`, `test_ppt_html`.

독립 검토의 설명용 다이어그램 표현과 승인본 임의 변경 금지 문구를 보완했습니다. `company-agent` 조정 스킬의 기존 `company-agent-role` 확장 키는 범용 Codex 스킬 검사기 대상이 아니므로 제거하지 않았습니다. 실제 Claude 플러그인 strict 검사와 저장소 회귀 검사를 적용했습니다.

## 확인하지 않은 범위

실제 사내 HCP가 문장을 다듬을 때의 의미 보존·품질·응답 시간·토큰 효과는 미검증입니다. 지침 전달과 렌더러 원문 보존 검사가 모델의 실제 문장 품질까지 증명하지는 않습니다. 이번에는 새 브라우저 시각 검사나 회사 PC 설치·Office·메일 실업무 시험을 수행하지 않았습니다. WS-33, 비전 모델·게이트웨이 설정은 변경하지 않았습니다.

LLM Wiki는 추후 검토용 소스 문서만 추가했으며 설치 ZIP 대상이 아닙니다. `standalone-guides/`, `tmp/`, `.smoke/`, 개인 상태·인증·개발 캐시는 커밋·배포에 넣지 않습니다. 과거 Release·태그·설치 ZIP은 보존합니다.

## 최종 배포 파일

| 파일 | 크기 | SHA-256 |
| --- | ---: | --- |
| `company-agent-1.4.28-2026.09.03.zip` | 1,199,237 bytes | `50e4cbccd78618dc28dd5e01583dbea37a91a4692cc455cf9fcafd29f1fe3d8f` |
| `company-workspace-preview-0.9-20260927-224943.zip` | 326,493 bytes | `97c6bc3dbaf3d52c63912a74b9d117ba6a34ce9201b59e4f0313ba137d1f0f49` |
| `Company-Agent-User-Guide.html` | 395,443 bytes | `28cead2417eeea63bb0d674aadce3afb22c710fad164ae522b1d70f79e70a91b` |

각 파일의 `.sha256`을 함께 제공합니다. 영문 파일명의 HTML은 `docs/Company-Agent-사용자-안내서.html`과 바이트가 같습니다. 이 기록은 순환 해시를 피하기 위해 설치 ZIP 밖에 둡니다.
