# 표 범위 조정

자동 탐지는 빈 행·열을 경계로 삼는다. 하나의 표 안의 공백과 여러 표의 경계가 같게
보일 수 있다. Excel의 정식 Table 범위는 자동 추정보다 우선한다.

사용자가 확인한 경우 `plan.json`의 표 범위와 헤더 행 수를 조정한다.
명세를 주면 여기에 적은 표만 추출한다. 포함하지 않은 발견 영역은 workbook.json에 남는다.

```json
{"version":1,"tables":[
  {"id":"applicants","sheet":"신청현황","range":"B4:G32","header_rows":2,"exclude_rows":[32]},
  {"id":"courses","sheet":"과정기준","range":"A1:D8","header_rows":1,"exclude_rows":[]}
]}
```

`header_rows:0`은 첫 행부터 데이터로 보존한다. `exclude_rows`는 원본 시트 행 번호다.
사용자가 합계·주석이라고 확인한 행만 제외한다. 중복 ID, 겹치는 범위, 잘못된 경계는 거절한다.
다음 파일에 행이 추가되면 고정 범위도 조정하거나 명세 없이 다시 탐지한다.
