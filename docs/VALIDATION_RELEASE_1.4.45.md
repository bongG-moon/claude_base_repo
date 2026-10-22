# Company Harness 1.4.45 검증 기록

2026-10-22. 공개 1.4.44 소스에 Excel 설명 HTML·업무 기록 집계·관련 문서만 반영한 격리 스냅샷을 검증했습니다. 작업 중인 Workspace·비전 변경은 제외했습니다.

## 확인 결과

- Excel 전체 회귀 268개, 설치 연동 15개, 집계 배포 연동 4개, 스킬 후보 선택 27개, 스킬 탐색 13개, 안내서 계약 21개 통과.
- 집계 단위 38개 중 37개 통과, 실제 Windows symlink 생성 권한이 필요한 1개 제외. 링크 차단은 별도 모의 reparse 테스트로 확인했습니다.
- 합계 386개 실행, 385개 통과·1개 제외. 가상 자료와 격리 프로필만 사용했으며 직원의 실제 세션은 수집하지 않았습니다.
- 소스·플러그인 스킬 사본 일치, Claude 플러그인 strict 검증, Python 컴파일·회사 지식 검증 통과. CLI와 플러그인 manifest 모두 1.4.45입니다.
- 직원 ZIP의 manifest 263개 항목과 EXE 내장 payload 264개를 확인했습니다. GitLab 준비 단계에서 같은 ZIP이 EXE에 내장됐는지 검증했습니다.
- Windows PowerShell 5.1의 격리 프로필에서 1.4.44 → 1.4.45 설치·업데이트, 실제 Claude 등록과 SessionStart 통과. 개인 상태·모델·MCP·긴 경로 개인 스킬 백업·기존 ZIP을 보존했습니다. 실제 사용자 설정은 변경하지 않았습니다.
- 첫 업데이트 시험은 PowerShell 7에서 이전 설치기의 `Directory.SetAccessControl` API 차이로 중단됐습니다. 지원하는 Windows PowerShell 5.1에서 최종 ZIP으로 재실행해 통과했으며 보안 설정을 완화하지 않았습니다.
- 단독 HTML은 6부분·52장, 437,354바이트입니다. Markdown/HTML 계약·오프라인 글꼴 검사와 1440/768/390px Chrome 검사를 통과했습니다. 페이지 가로 넘침·JS 오류·외부 요청이 없습니다.
- 복잡한 엑셀 계산 결과·DATA 교체·설명 HTML 화면의 기능 검증은 [상세 기록](VALIDATION_WORKFLOW_CATALOG_20261022.md)을 참고하세요.

사내 DRM·원본 VBA 실행 동등성·실제 직원 기록의 모든 형식과 규모는 이번 검증에 포함하지 않았습니다. EXE는 코드 서명이 없으며 사내 승인 정책을 따라야 합니다. GitLab 배포 묶음 생성과 실제 사내 서버 게시는 별개입니다.

## 배포 자산 SHA-256

| 파일 | SHA-256 |
| --- | --- |
| company-agent-1.4.45-2026.09.03.zip | f32fb1a65b50b850674feafb84ba47cc0882240faa60b11e6de377323e51dfd9 |
| Company-Harness-Setup.exe | 8cf5b325b37d909f487ef118da35adf088573fbf6f8d6491e61097f01122545b |
| Company-Agent-User-Guide.html | 2da7f3c0fbed54785146fb51eae8b3e369eea2f4b3685796b3e3afc8af42a11b |
| Company-Harness-GitLab-Delivery-1.4.45.zip | 7ce1fd3a85a21f2c7b69cbc66532c74e510ae4ff0337dc2450ef02ff549b02f3 |
