# 1.4.27 배포 검증

검증일: 2026-09-27. 회사 지식팩 `2026.09.03`, Workspace 실행 코드 `0.9`를 유지합니다. [변경 안내](UPDATE_1.4.27.md)를 참고하세요.

## 이번에 다시 확인한 내용

| 검사 | 결과 |
| --- | --- |
| 정리 영향 범위 Python 회귀 | `test_test_lab` 15개, `test_handbook_contract` 20개, `test_guide_presentation` 4개: 39개 통과, 실패·생략 없음 |
| 실습실 실제 생성 | 임시 입력 ZIP으로 생성, 원본 검증 Markdown 바이트 보존, 35개 시나리오, 모든 대시보드 파일 링크 존재, 중복 HTML 미생성 확인 |
| 안내서 동기화 | `build-manuals.mjs --check` 통과. 6부·52장, 394,168 bytes, 단독 HTML과 설치 사본·Markdown 원본 7개 일치 |
| 설치 ZIP 생성 | 실제 Claude 플러그인 strict 검사, 회사 지식 검사, Python 구문 검사 통과. 기존 승인 Python 사용, 실행 파일 다운로드·동봉 없음 |
| 설치 ZIP 회귀 | Windows PowerShell 5.1 `Test-OfflineBundle.ps1` 통과. 허용 파일 목록·무결성·같은 버전 다른 내용 교체 방지 확인 |
| 실제 ZIP 업데이트 | Windows PowerShell 5.1 `Test-ReleaseUpgrade.ps1`: 1.4.26 → 1.4.27 통과. 격리 설정의 실제 Claude 등록·SessionStart, 개인 모델/MCP/기억/스킬·긴 경로 백업·원본 ZIP 보존 확인 |
| 최종 패키지 감사 | 직원 ZIP 206개 원본 + manifest, Workspace 33개 원본. 파일별 크기·SHA-256·원본 바이트와 manifest 버전 일치 |
| 패키지 포함 범위 | CRC·중복 경로·경로 이탈·링크·암호화 오류 없음. 개인 상태·인증·개발 캐시·예상 밖 실행 파일 미포함 |

하네스 실행 로직·스킬·후크 정책은 1.4.26과 동일하고 이번에는 문서·실습실 변경과 패키징/업데이트에 집중했습니다. [1.4.26 전체 회귀 기록](VALIDATION_RELEASE_1.4.26.md)의 1,350개 검사를 이번 버전에서 전부 재실행했다는 뜻은 아닙니다. 주요 비밀키 형태의 패턴 검사도 모든 기밀 데이터 형식을 보증하는 DLP 검사는 아닙니다.

## 정리 범위

- 중복 운영 검증 HTML과 전용 생성기만 Git에서 제거하고 원본 Markdown을 보존했습니다. 과거 Office Reader 진단 및 구현 기록은 역사적 자료임을 표시했습니다.
- 개발 PC의 중복 빌드 폴더 52개와 중간 ZIP 2개는 휴지통으로 옮겼습니다. 이 작업은 배포 프로그램에 포함되지 않으며 설치기가 사용자 파일을 삭제하지 않습니다.
- 개인 자료, 별도 CUA 시험 자료, 과거 릴리스 ZIP·태그는 보존합니다. `standalone-guides/`, `tmp/`, `.smoke/`는 커밋·배포에 넣지 않습니다.
- 기존 단독 사용자 안내서는 그대로 유지합니다. Workspace ZIP은 실행 코드가 아닌 안내의 버전·링크만 갱신했습니다.

## 확인하지 않은 범위

사내 HCP 모델의 실업무·속도·토큰 효과, 실제 회사 PC 설치, 새 브라우저 시각·인쇄·이미지 저장 검증은 이번 검사에 포함하지 않았습니다. 일반 권한 연결 토큰이 없는 관리자 PC의 WS-33 제한도 그대로이며 사용자 UAC·권한·인증 설정을 바꾸지 않았습니다.

## 최종 배포 파일

| 파일 | 크기 | SHA-256 |
| --- | ---: | --- |
| `company-agent-1.4.27-2026.09.03.zip` | 1,190,106 bytes | `d71bb97037a2da54580e2ee0babc311b848a7e6331a0cb6c921ffcf2aa45e5e4` |
| `company-workspace-preview-0.9-20260927-221236.zip` | 325,594 bytes | `51359fe62610c74a3c63acc15235d2664c22763c2397cacf1e92b970d67a1842` |
| `Company-Agent-User-Guide.html` | 394,168 bytes | `60e38622b9ac9855e1af0972e384a6e26e82c75041ac0cbc20a76322a28fb1d2` |

각 파일의 `.sha256`을 함께 제공합니다. 영문 파일명의 HTML은 `docs/Company-Agent-사용자-안내서.html`과 바이트가 같습니다. 이 검증 기록은 순환 해시를 피하기 위해 설치 ZIP 밖에 둡니다.
