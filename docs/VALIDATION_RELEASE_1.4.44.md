# Company Harness 1.4.44 검증 기록

2026-10-20. 기존 공개 1.4.43 소스에서 Excel 구조화·한국어 수식 주석·관련 안내서만 분리하여 검증했습니다. 작업 중인 Workspace·비전 변경은 제외했습니다.

## 확인 결과

- 분리 소스의 Excel 회귀 테스트 245개, 하네스 연동 15개, 안내서 계약 21개 통과.
- 원본/플러그인 스킬 동기화 확인, 오프라인 번들 회귀 테스트 통과.
- 직원 ZIP의 252개 manifest 항목과 EXE 내장 payload 253개 검증 통과.
- 격리 프로필에서 1.4.43 → 1.4.44 설치·업데이트 통과. 개인 상태·모델·MCP·기존 ZIP·긴 경로 스킬 백업 보존 확인. 실제 사용자 설정은 변경하지 않음.
- 단독 HTML 재생성: 6부분·52장, 430,335바이트. 오프라인 글꼴 문자 범위 및 Markdown/HTML 계약 검사 통과. 이번 배포에서는 브라우저 시각 검사를 재실행하지 않음.
- 복잡한 XLSM 12시트·6,798수식 → 37개 반복 계산 묶음·계산 시트 Python 3개. 기존 엔진의 값·상태와 일치하며 미지원 4개·오류 4개는 그대로 표시.
- DATA만 교체한 별도 결과 선택 예제에서 1,285,000으로 계산됨. PROCESS 해시·원본 파일 유지. 추가 모델 호출·매크로 실행 없음.

사내 DRM·원본 VBA 실행과의 동등성·모든 Excel 함수 자동 변환은 보장하지 않습니다.
수식 주석은 생성 시점의 원본을 설명하며 사용자가 Python 계산을 수정하면 주석도 함께 수정해야 합니다.

## 배포 자산 SHA-256

| 파일 | SHA-256 |
| --- | --- |
| company-agent-1.4.44-2026.09.03.zip | dbff143beae57f9cec41ccaa55353290b24aa7c6c11f2a66d6023d0081e34efc |
| Company-Harness-Setup.exe | aff791af7f0d7783a5d9e83f7ae0fd4e9f888d7a6dc15178cebd838423b4d85f |
| Company-Agent-User-Guide.html | 4b2cb603df50acb1c79abd0527d73622dbbe6bedfe64bc37fdc8b8ccaeb0a623 |
| Company-Harness-GitLab-Delivery-1.4.44.zip | 1518e6162db3f01621f96d5d5044a1503f4375f9554a10f817d766692b22e55f |

설치 EXE는 서명되지 않았습니다. GitLab용 묶음 준비는 실제 사내 GitLab 게시와 별개입니다.
