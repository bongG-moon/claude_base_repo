# 허용된 Office 문서 읽기 계약

이 기능은 사용자의 Excel·PowerPoint·Word를 통한 읽기입니다. DRM 해제나 권한
우회가 아닙니다. Office 열기 성공·Permission.Enabled=False는 회사 DRM 전체의
자동화/AI 권한을 증명하지 않습니다. 별도 DRM 연동 승인이 필요한 환경에는 그
절차가 우선하며 사용자 클릭이 예외를 만들지 않습니다.

## 요청 데이터

Excel/CSV (시트 번호는 1부터):

```json
{"file":"C:\\work\\data.xlsx","sheet":1,"range":"A1:F50","maxChars":10000}
```

PowerPoint (슬라이드 번호는 1부터):

```json
{"file":"C:\\work\\report.pptx","start":1,"end":5,"maxChars":10000}
```

Word (페이지가 아니라 본문 문단 번호, 1부터):

```json
{"file":"C:\\work\\memo.docx","start":1,"end":20,"maxChars":10000}
```

범위를 모르면 제한된 미리보기임을 먼저 설명합니다. Excel 기본값은 첫 시트의
`range: "used"`입니다. [고정 xlwings 절차](excel-fixed-recipe.md)로 사용 영역을
제한한 뒤 DataFrame으로 읽고 셀 위치와 값을 반환합니다. CSV의 자동 형 변환,
구분자/문자 인코딩은 Office 설정 영향을 받습니다. 숫자·한글을 원본과 대조하고
깨진 문자열을 올바른 내용인 것처럼 사용하지 않습니다. 전체 UsedRange를 무제한
가져오지 않습니다. 범위 200행·20열·2,000셀 이내, 문단/슬라이드 한 번에 50개
이내, 전체 텍스트 최대 20,000자입니다.

PPT는 최상위 텍스트 상자와 표만 읽습니다. 그룹·SmartArt·그림 속 글자·차트 값·
노트는 제외합니다. Word는 본문 문단만 읽고 머리말·꼬리말·텍스트 상자·주석·
변경 기록은 완전 수집하지 않습니다. 읽은 자료만으로 전체 파일에 내용이 없다고
단정하지 않습니다. 실제 자료에서 적용 범위와 한글 표시를 운영 검증해야 합니다.

## 실행/보존

Excel/CSV는 현재 하네스의 Python에 설치된 xlwings·pandas와 데스크톱 Excel을
사용합니다. 누락 시 필요한 준비물을 알려주고 멈추며 다른 Python을 임의 선택하거나
인터넷에서 설치하지 않습니다. PPT/Word는 같은 Python의 pywin32를 사용하는
[고정 Office 절차](office-fixed-recipe.md)입니다. PowerShell 읽기로 전환하지 않습니다.
지원 확장자는 xlsx/csv/pptx/docx이며 구형 바이너리·매크로 형식은 초기 범위에서 제외합니다.
원본을 직접 읽기 전용으로 열고 저장·복사·변환하지 않습니다. 새로운 보안 예외,
Protected View 해제, 사용자 문서 전체 종료, 강제 프로세스 종료는 하지 않습니다.
필요한 Office/DRM 인증 창에 자동 응답하지 않습니다. 대기하면 해당 작업만 중단합니다.

읽은 본문은 Office/Python 메모리와 반환 JSON을 거쳐 Claude에 전달됩니다.
별도 TXT·Memory·Knowledge·원문 로그를 생성하지 않습니다. Office 자체 캐시와
자동 복구 파일, OS 메모리, Claude 대화 기록의 미보존을 보장하는 기능은 아닙니다.
출력은 UTF-8/JSON으로 전달하지만 입력 단계에서 이미 깨진 글자를 복구하지는 않습니다.

## 공식 참고

- https://learn.microsoft.com/en-us/office/vba/api/excel.workbooks.open
- https://learn.microsoft.com/en-us/office/vba/api/excel.application.automationsecurity
- https://learn.microsoft.com/en-us/office/vba/api/powerpoint.presentations.open
- https://learn.microsoft.com/en-us/office/vba/api/word.documents.open
- https://learn.microsoft.com/en-us/office/vba/api/office.permission.enabled

매크로 ForceDisable도 Excel 4.0 매크로를 보편적으로 차단하는 것은 아닙니다.
Office 보안 정책과 보안 대화상자는 유지하며 자동 승인하지 않습니다.
