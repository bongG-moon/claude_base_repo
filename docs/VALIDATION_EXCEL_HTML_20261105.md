# Excel 분석과 HTML 차트 개선 검증

검증일: 2026-11-05. 개별 스킬 정본, 기존 플러그인 호환 경로와 `skills_zip`을 갱신했다.
회사 원본 파일은 제공되지 않았으므로 전달된 실행 로그와 로컬 합성 파일을 구분한다.

## 변경 사항

- Excel의 기존 누적 250,000셀 중단을 2,000,000셀 예산으로 조정했다. 모델 입력 기본값은
  12,000자와 표별 앞 5행을 유지한다. 압축, 병합, 수식 평가의 별도 한도는 유지한다.
- 일반 OOXML은 직접 읽고, 필요한 파일만 허용된 Excel 읽기로 처리한다. 빈 서식으로 늘어난
  UsedRange 대신 내용 범위를 찾고 약 25,000셀 블록으로 읽는다. 값과 수식의 셀별 COM 조회는 없다.
- 실제 Excel에서 부분 범위 XML의 병합 경계 잘림을 재현했다. 블록 경계에 걸린 병합만 확인해
  범위를 확장하며, 이미 읽은 Value2와 Formula2로 값과 수식의 누락도 검사한다.
- 오류 관찰값, 수식 원문, 깨진 참조와 외부 파일 참조를 시트별로 요약한다. `#REF!`를 외부 파일
  누락으로 단정하거나 오류값만 보고 수식을 확보했다고 말하지 않는다.
- 요청 시 같은 분석에서 `필요자료.xlsx`를 만든다. 결과 범위를 지정하면 정적으로 확인한
  선행 데이터, 수식과 필요한 열 제목만 보존한다. 원본 파일을 저장하거나 해제하지 않는다.
- 사본은 기존 좌표와 수식 원문을 유지한다. 수식 캐시는 옮기지 않으며 수동 계산 상태다.
  동적 참조와 셀 외부 상태가 필요한 함수는 선택 사본으로 완전 재현했다고 주장하지 않는다.
- HTML 차트에 마우스, 터치, 키보드 툴팁과 선택 강조를 기본 적용했다. 차트 확대 상한과
  축 12px, 표 14px의 기본 크기로 제목과 본문 위계를 정리하고 선택한 테마와 글꼴을 유지한다.
- 추가 상시 후크, 모델 호출, 사용자 프로필 설치 또는 전역 설정 변경은 없다.

## 실제 실행 결과

| 검증 | 결과 |
|---|---|
| Excel 전체 회귀 | 298개 통과. 마지막 공통 예산 변경과 XLSX 사본은 후속 관련 검사에 포함 |
| XLSX 사본과 compact 프로젝트 | 후속 관련 검사 32개 통과. 전체 회귀와 일부 중복되므로 합산하지 않음 |
| 플러그인 CLI와 설치 사본 통합 | openpyxl이 포함된 격리 Python 환경에서 17개 통과 |
| HTML 관련 회귀 | 81개 통과 |
| 플랫폼 패키지 계약 | 38개 통과 |
| 독립 시각 스킬 | 14개 통과, 격리 Python의 python-pptx 미설치 조건으로 기존 2개 건너뜀 |
| 원본/ZIP 동기화 | Excel sync --check 및 build-skill-packages.py --check 통과 |
| 실제 Excel 대용량 읽기 | 8시트 272,518개 값과 8,001개 수식 전수 일치. 읽기와 정규화 9.320초 |
| Excel 읽기 경계 | 16블록, 경계 병합 확인 2회. 원본 해시 유지, 소유 Excel 정상 종료 |
| 복합 수식 실습 | 8시트, 원본 1,140행, 수식 11,499개 계산 성공. Excel 캐시와 모두 일치 |
| 생성 Python 재실행 | 최종 7개 지표가 독립 계산과 일치. 검증표 8개 대조 일치, 수식 오류 0개 |
| 필요한 XLSX 생성 | 42,688개 원본 셀 중 10,790개 셀과 5,988개 수식 보존 |
| 새 XLSX 계산 대조 | 별도 시험 사본에서 Excel 재계산 후 최종 7개 지표 일치, 오류 0개. 전달 사본은 변경하지 않음 |
| HTML 실제 브라우저 | 2테마 × 2화면 폭 × 4차트. 키보드, hover, touch, 인쇄, 페이지 이동, 글자 위계와 넘침 확인 |
| 독립 Excel ZIP | 압축 해제한 코드로 복합 수식 실습 파일과 최소 XLSX 생성 성공, 원본 해시 유지 |
| 독립 HTML ZIP | 빈 프로필과 별도 폴더에서 python -I로 4종 차트 생성. 런타임과 CSP 해시 확인 |

첫 통합 검사는 동기화 전 사본과 `-I`에서 openpyxl을 사용할 수 없는 Python 환경 때문에
실패했다. 소스 동기화와 기존 격리 환경을 사용한 재검사에서 통과했다. 전역 패키지를 설치하거나
사용자의 Python 설정을 변경하지 않았다.

실습 파일 분석 시간은 약 4.55초이며, 사본과 프로젝트 기록을 포함한 명령은 약 9.15초였다.
이는 합성 실습 파일의 로컬 측정이며 회사 파일의 처리 시간이나 Claude 대화 전체 시간을 보장하지 않는다.

## 자료와 근거

- `outputs/excel-html-improvements-20261105/사용안내.txt`
- `outputs/excel-html-improvements-20261105/실습자료/생산품질_8시트_복합수식_실습.xlsx`
- `outputs/excel-html-improvements-20261105/excel-to-pipeline/outputs/복합수식-분석/`
- `outputs/excel-html-improvements-20261105/HTML-차트-예제.html`
- `.smoke/excel-reader-20261105/native-verification.json`
- `.smoke/excel-reader-20261105/pytest-final.txt`
- `.smoke/excel-training-20261105/native-verification.json`
- `.smoke/excel-training-20261105/minimal-native-verification.json`
- `.smoke/excel-training-20261105/pipeline-output-verification.json`
- `.smoke/excel-package-20261105/verification.json`
- `.smoke/html-chart-usability-20261105/browser-verification.json`
- `.smoke/html-chart-usability-20261105/package-d49ac785/verification.json`

실제 사내 DOCUMENT SAFER 파일, 회사의 내보내기 허용 여부와 사내 모델의 전체 대화 수행은
검증하지 않았다. 구조 분석의 모호한 헤더와 표 경계 표시는 보존하며 계산 오류와 구분한다.
빌드 결과에서 `presentation.zip`도 바뀐 것은 공유 HTML 렌더링 모듈의 동기화이며 PPT 디자인 변경은 아니다.
이번 작업에서 설치, 게시, 커밋과 푸시는 실행하지 않았다.
