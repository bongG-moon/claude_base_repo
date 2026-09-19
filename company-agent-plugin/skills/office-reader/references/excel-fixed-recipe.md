# Excel·CSV 고정 읽기 절차

사용자 요청의 의도: “엑셀에 DRM이 적용되어 일반 라이브러리로 읽히지 않으면,
사전에 정한 xlwings 코드로 Excel을 열고 내용을 읽는다.” 실행할 때마다 다른
방법을 찾아 쓰거나 즉석 코드를 만드는 스킬이 아니다.

## 실행 경로

`business office-read --spec ... --session "현재 세션 ID"`는 대화 승인 후 확장자가 xlsx/csv이면 항상 설치본의
`Read-CompanyExcel.py` → `company_agent/excel_xlwings.py`를 호출한다.
일반 파일도 같은 고정 경로를 쓴다. 원본을 저장하지 않고 읽은 범위만 반환한다.
라이브러리 부족, 파일 열기 실패, 읽기 거절은 실제 반환된 결과로 구분해 안내한다.

아래는 절차를 설명하는 핵심 예시다. 이 예시를 별도 파일로 복제·실행하지 말고
위의 설치된 공통 명령을 사용한다. 실제 구현에는 범위 제한·오류 처리·정리가 포함돼 있다.

```python
import xlwings as xw
import pandas as pd

app = xw.App(visible=False, add_book=False)
book = app.books.open(file_path, read_only=True, update_links=False)
sheet = book.sheets[0]  # 첫 번째 시트
selected = sheet.used_range  # 실제 구현은 큰 영역을 제한하고 일부 읽기라고 표시
df = selected.options(pd.DataFrame, header=False, index=False).value
# 첫 행/첫 열도 데이터로 유지. 불필요한 index 열을 추가하지 않음.
book.close()            # 저장하지 않음
# 실제 구현은 자신이 만든 문서만 닫고, 다른 문서가 없을 때만 해당 app을 종료
```

사용자가 준 `xw.Book(path)` 대신 `app.books.open(path)`를 사용하는 이유는
새로 만든 Excel과 열 파일을 확실히 연결하기 위해서다. 다른 Excel 창에서 사용
중인 문서를 가져와 닫지 않는다. `reset_index(drop=False)`로 원래 없던 인덱스
열을 추가하지 않고 원래 셀 위치와 값을 반환한다.

## 사용자 입력

- “이 DRM 엑셀을 정해진 xlwings 방식으로 읽고 요약해줘.”
- 파일 경로가 있으면 다시 묻지 않는다. 시트를 지정하지 않으면 첫 번째 시트를 사용한다.
- 범위가 없으면 `range: "used"`로 사용 영역을 확인한다. 최대 200행·20열·2,000셀,
  전체 텍스트 최대 20,000자만 읽고 초과하면 일부 읽기임을 표시한다.
- 정확한 범위를 받으면 `range: "A1:F50"`처럼 지정한다.
- 읽은 내용을 AI 대화에 전달하기 전 Claude 안에서 파일·범위를 보여주고 승인/취소를 받는다. 별도 Windows 창은 열지 않는다.

## 해석하지 말아야 할 것

- 성공: Excel이 지정한 영역의 값을 제공했다는 뜻이지 DRM을 해제했다는 뜻이 아니다.
- Office IRM 속성이 제공되지 않는 경우: 부가 권한 정보 미제공으로 표시한다.
  이 상태만으로 일반 문서가 차단됐다고 단정하지 않는다. 속성이 실제 제한을
  보고하거나 접근 거절이 반환되면 중단한다. 회사의 자동화·AI 허용 범위는 별개다.
- xlwings/pandas가 없으면 그 사실만 알리고 자동 설치·다른 라이브러리 대체를 하지 않는다.
- 한글 입력이 이미 깨졌다면 UTF-8 출력만으로 복원되지 않는다. CSV 형 변환,
  날짜·숫자·빈 칸을 실제 표와 비교한다.

공식 참고: https://docs.xlwings.org/en/stable/api/books.html ·
https://docs.xlwings.org/en/stable/converters.html
