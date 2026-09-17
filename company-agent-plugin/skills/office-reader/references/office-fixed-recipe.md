# PPT·Word 고정 읽기 절차

사내 파일 읽기는 실제 Office를 거친다. Excel/CSV는 xlwings, PPT/Word는
pywin32의 win32com.client를 사용한다. 사용자가 모듈 이름을 말하지 않아도 이
스킬을 선택했다면 같은 경로를 적용한다. 매번 다른 코드를 만들지 않는다.

## 실행

설치된 공통 `business office-read --spec ...` 명령은 PPT/Word 요청을
`Read-CompanyOffice.py` → `company_agent/office_pywin32.py`로 전달한다.
사용자에게 Python/JSON 작성을 요구하지 않는다. 경로가 없을 때만 질문한다.

- PPT: `DispatchEx("PowerPoint.Application")` →
  `Presentations.Open(path, -1, 0, 0)` → 슬라이드 글자/표 → `Close()`.
- Word: `DispatchEx("Word.Application")` →
  `Documents.Open(path, False, True, False)` → 본문 문단 → `Close(0)`.

두 경로 모두 읽기 전용이며 저장하지 않는다. 실제 구현은 COM 초기화, 범위 제한,
한글 JSON 출력, 오류 처리와 설정 복원을 포함한다. 사용자가 이미 열어둔 원본을
닫거나 프로그램 전체를 종료하지 않는다. 읽기 후 빈 Office 프로세스가 남을 수 있다.

## 대기 구간 확인

표준 출력은 결과 JSON이고, 표준 오류에는 `[문서 읽기]` 단계 안내만 짧게 표시한다.
호스트가 출력을 모아서 보여주면 실시간 표시는 늦어질 수 있다. 안내가 없다고
같은 작업을 반복하지 않는다. 최종 `diagnostics.progress.stageMs`에는 준비·확인 창
시작·사용자 응답 대기·열기·추출·닫기 등의 시간이 남는다. 원문은 기록하지 않는다.

- 실행 진입점의 Python 확인은 후보별 10초 제한이며 중복 경로는 검사하지 않는다.
  시간 초과 시 다른 Python으로 재시도하지 않고 `office_bootstrap_timeout`으로 중단한다.
- 확인 창 시작은 30초, 실제 표시 후 사용자 응답은 300초 제한이다.
  각각 `confirmation_start_timeout`, `confirmation_wait_timeout`으로 구분한다.
  승인 없이는 Office를 열지 않는다.
- Office 보조 프로세스 전체는 기존처럼 60초 제한이다. `office_timeout`의 `stage`와
  `diagnostics.progress.lastStage`로 마지막 구간을 확인한다. Office 자체는 강제 종료하지 않는다.
- Claude의 생각 시간·도구 실행 전 권한 판정·실행 호스트 대기는 이 측정 밖이다.
  전체 화면 경과 시간을 그대로 Office 처리 시간으로 보고하지 않는다.

## 사용 예와 범위

- “이 사내 PPT를 읽고 1~5장의 핵심을 요약해줘.”
- “이 Word 문서 앞부분을 읽어서 할 일을 정리해줘.”
- “이 DRM 문서를 설치된 Office로 열어서 읽어줘.”

PPT 기본 1~5장, Word 기본 처음 20개 본문 문단. Word의 문단 번호는 페이지 번호가
아니다. 지정 범위는 최대 50개, 응답은 기본 10,000자/최대 20,000자다.
PPT는 텍스트·표·그룹을 읽고 개체 좌표와 표 ID·행·열을 함께 반환한다.
SmartArt·그림·노트·차트 값은 제외한다. Word 표 안 문단에는 표 ID·셀 행·열과
제공 가능한 페이지 정보를 포함한다. 병합 범위·머리말·주석까지 추출하지 않는다.
일부 범위만 읽고 전체 문서 검색을 완료했다고 말하지 않는다.

## 준비물·실패 처리

현재 하네스가 사용하는 Python에 pywin32, PC에 해당 Office가 설치돼 있어야 한다.
누락 시 준비물을 한국어로 안내하며 자동 다운로드하거나 다른 엔진으로 전환하지 않는다.
내용 전달 전 기존 확인 창을 유지한다. 실제 접근 거절 또는 명시된 제한은 중단한다.
선택적 Office IRM API 미지원은 별도 진단으로 표시하며 그것을 실제 문서 거절이나
회사 DRM/AI 허가라고 단정하지 않는다. 암호 해제·복사본 생성·보호 설정 변경은 없다.

공식 참고:
- https://mhammond.github.io/pywin32/html/com/win32com/HTML/QuickStartClientCom.html
- https://learn.microsoft.com/en-us/office/vba/api/powerpoint.presentations.open
- https://learn.microsoft.com/en-us/office/vba/api/word.documents.open
