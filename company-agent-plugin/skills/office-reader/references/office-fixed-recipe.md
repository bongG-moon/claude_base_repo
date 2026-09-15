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
