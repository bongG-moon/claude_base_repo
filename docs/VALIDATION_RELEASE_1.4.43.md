# Company Harness 1.4.43 검증 기록

2026-10-18. Excel DATA/PROCESS 프로젝트 생성과 한국어 주석 변경만 배포합니다. Workspace 화면 전환·폴더 카드, 다른 앱·비전 미커밋 변경은 포함하지 않습니다. 이전 공개 커밋에서 분리한 소스에 명시한 Excel/버전/문서 변경만 적용해 시험·패키징했습니다.

## 통과한 검사

- 독립 Excel 분석·재사용 회귀 테스트 225개, 하네스 CLI 연동 14개: 분리 배포 소스에서도 통과.
- 안내서 계약 21개: 배포 안내의 이전 버전 표기 한 건을 수정한 뒤 통과.
- 스킬 원본/배포 사본 동기화, Claude 플러그인 strict 검사, 회사 지식 검증 통과.
- 오프라인 번들 회귀 검사 통과. 최종 ZIP manifest 249개 파일 및 설치 EXE 내장 payload 250개 파일 검증 통과.
- Windows PowerShell 5.1에서 원본 1.4.42 ZIP → 최종 1.4.43 ZIP의 격리 업데이트 통과. 개인 자료·모델·MCP·다른 플러그인·긴 경로 스킬 백업·이전 ZIP 보존, 등록 버전·실제 SessionStart·Read 후크 일치 확인.
- 단독 HTML: 6부분·52장, 429,536바이트. Chrome 1440/768/390px, 화면 45개·내부 링크 147개·오프라인 Noto Sans KR·인쇄·예문 선택 검사 통과. 깨진 문구·넘침·외부 요청·페이지 오류 없음.

## 복잡한 Excel 재사용

12시트·16표·6,798수식 XLSM에서 생성한 프로젝트를 실행했습니다. DATA만 Excel에서 Python/JSON 입력으로 바꾸고 수량을 1→2로 수정하자 `수식처리!J7`이 211,386→422,773으로 계산됐습니다. 독립 기대값과 일치하고 PROCESS와 원본 파일의 SHA-256은 유지됐습니다. 계산 6,790개·미지원 4개·오류 4개를 구분했으며 VBA나 추가 LLM은 실행하지 않았습니다.

이번 변경은 고정 행·열·수식 구조의 재사용입니다. 모든 Excel 함수/VBA 자동 번역, 행 증가 자동 처리, 사내 DRM 및 실제 매크로 결과 동등성은 보장하지 않습니다. 기존 `transform.py` 재분석 경로는 유지합니다. 자세한 구현 검증은 `VALIDATION_EXCEL_DATA_PROCESS_20261018.md`에 있습니다.

## 배포 파일

| 파일 | SHA-256 |
| --- | --- |
| company-agent-1.4.43-2026.09.03.zip | e142fe09f122fbc22171e2021c3901d60dabdf961536650a5148df9c749fbe28 |
| Company-Harness-Setup.exe | 3ca4e941ca8fe6f5dd7c1f342ba7e0c2816f40be77f01de43445df37531c62fe |
| Company-Agent-User-Guide.html | 50c76d03d946d897f9de0bf7bb059ce23b7377c2e59387730c91ae4db8f1c077 |
| Company-Harness-GitLab-Delivery-1.4.43.zip | 86f0373ba3938fa8a18e2490b1bb1c0fcacf13e590829f3d99a01938675b8c4b |

EXE는 서명되지 않았으며 GitLab 묶음 생성은 실제 사내 게시가 아닙니다. 실제 사용자의 설치·모델·MCP 설정은 변경하지 않았습니다.
