# 허용된 Office 문서 읽기 계약

이 기능은 사용자의 Excel·PowerPoint·Word를 통한 읽기입니다. 열기 성공 여부와
실제로 읽은 범위를 구분해서 안내합니다. DRM 표시나 IRM 속성 하나만으로 파일의
상태와 오류 원인을 단정하지 않습니다.

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

PPT는 텍스트 상자·표·그룹 내부 텍스트를 읽고 개체 좌표(pt)와 표 행·열을 반환합니다.
그룹은 깊이 8·개체 2,000개 이내입니다. SmartArt·그림 속 글자·차트 값·노트는
제외합니다. Word는 본문 문단과 표에 속한 문단의 표 ID·행·열·페이지 정보를
반환합니다. 페이지 정보는 Office가 제공할 때만 포함하며 문단 선택과 다릅니다.
머리말·꼬리말·텍스트 상자·주석·변경 기록은 완전 수집하지 않습니다.
Excel은 빈 셀을 생략해도 원래 행·열 번호를 유지하며 병합 범위는 추정하지 않습니다.
읽은 자료만으로 전체 파일에 내용이 없다고
단정하지 않습니다. 실제 자료에서 적용 범위와 한글 표시를 운영 검증해야 합니다.

## 실행/보존

Excel/CSV는 현재 하네스의 Python에 설치된 xlwings·pandas와 데스크톱 Excel을
사용합니다. 누락 시 필요한 준비물을 알려주고 멈추며 다른 Python을 임의 선택하거나
인터넷에서 설치하지 않습니다. PPT/Word는 같은 Python의 pywin32를 사용하는
[고정 Office 절차](office-fixed-recipe.md)입니다. PowerShell 읽기로 전환하지 않습니다.
지원 확장자는 xlsx/csv/pptx/docx이며 구형 바이너리·매크로 형식은 초기 범위에서 제외합니다.
원본을 직접 읽기 전용으로 열고 저장·복사·변환하지 않습니다.
사용자 문서 전체 종료, 강제 프로세스 종료는 하지 않습니다.
필요한 Office/DRM 인증 창에 자동 응답하지 않습니다. 대기하면 해당 작업만 중단합니다.

읽은 본문은 Office/Python 메모리와 반환 JSON을 거쳐 Claude에 전달됩니다.
별도 TXT·Memory·Knowledge·원문 로그를 생성하지 않습니다. Office 자체 캐시와
자동 복구 파일, OS 메모리, Claude 대화 기록의 미보존을 보장하는 기능은 아닙니다.
출력은 UTF-8/JSON으로 전달하지만 입력 단계에서 이미 깨진 글자를 복구하지는 않습니다.

## 간단 실행과 범위 확인

일반 읽기는 후크의 `officeReadCommand` 뒤에 `--file "파일명 또는 확인한 절대경로"`와 필요한 범위만 붙입니다.
현재 폴더의 파일명은 실행 도구가 실제 작업 폴더에 연결하며 다른 폴더를 검색하지 않습니다.
`--spec`의 file 값은 계속 절대 경로를 사용합니다. 명시한 절대 경로는 자동으로 바꾸지 않습니다.
없으면 `cliCommand` 뒤에 `business office-read --file "파일명 또는 확인한 절대경로"`를 붙이고 대화에 실제로 전달된 세션·상태 값만 추가합니다.
`company_agent_session_id`·`stateRoot`·`cliCommand`는 환경변수가 아닌 JSON 값입니다. env·echo로 확인하지 않습니다.
JSON 파일이나 doctor 선행 실행은 필요 없습니다. `--start 1 --end 4 --expected-count 4`
처럼 요청 범위와 알고 있는 개수를 지정할 수 있습니다. spec과 직접 인자는 혼용하지 않습니다.
현재 후크는 등록된 단독 읽기 명령의 누락된 세션·상태 경로만 보완합니다. 명시된 값,
원본 경로·범위·승인·실행 권한은 바꾸지 않습니다. 세션 정보 누락 오류가 계속되면
세션 폴더·도움말 탐색 대신 중단하고 새 Claude 대화에서 다시 요청하도록 안내합니다.
연결 정보 누락은 문서를 열기 전의 상태이며 문서 권한·DRM·Office 지원 여부는 미확인입니다. 다른 파서로 대체하지 않습니다.
첫 호출은 문서를 열지 않고 한국어 질문을 반환합니다. Claude 대화에서 파일·범위·AI 처리
안내를 보여주고 승인/취소를 받습니다. 실제 사용자 답변을 후크가 확인한 뒤 같은 명령을
한 번 실행합니다. 별도 Windows 확인 창이나 모델이 작성한 승인 값은 사용하지 않습니다.
승인은 동일 세션·폴더·파일 상태·범위에만 적용되고 15분 후 만료됩니다. 범위 변경·후속
읽기는 새 확인 대상입니다. 연결된 Claude 세션이 없는 직접 CLI는 승인 대기 안내만 반환합니다.
coverage.end는 실제 방문한 마지막 단위이며 completeThrough는 완료된 마지막 단위입니다.
전체 읽기일 때 nextStart로 이어 읽되 limitReached면 같은 범위를 반복하지 않습니다.
개수 불일치는 partial이며 원인 미확인입니다. diagnostics의 원본 SHA256·실제 경로·
Python·소요 시간을 독립 시험과 비교합니다. 다른 사본의 내용으로 대신 결론내리지 않습니다.

`source_not_found`는 경로 확인 실패이며 Excel 실행·DRM·파일 사용 중의 증거가 아닙니다.
`file_in_use`는 실제 공유/잠금 오류를 확인한 경우입니다. 해당 파일을 저장하고 닫은 뒤 다시 요청하도록 안내합니다.
원인을 모르는 Office 오류는 그대로 알리고 다른 파서·반복 실행·프로그램 강제 종료로 바꾸지 않습니다.

## 공식 참고

- https://learn.microsoft.com/en-us/office/vba/api/excel.workbooks.open
- https://learn.microsoft.com/en-us/office/vba/api/excel.application.automationsecurity
- https://learn.microsoft.com/en-us/office/vba/api/powerpoint.presentations.open
- https://learn.microsoft.com/en-us/office/vba/api/word.documents.open
- https://learn.microsoft.com/en-us/office/vba/api/office.permission.enabled

매크로 ForceDisable도 Excel 4.0 매크로를 보편적으로 차단하는 것은 아닙니다.
Office 보안 정책과 보안 대화상자는 유지하며 자동 승인하지 않습니다.
