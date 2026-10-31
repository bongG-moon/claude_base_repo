# 사내 Excel을 통해 읽기

## 사용자에게 필요한 설명

같은 분석 명령을 사용한다. 기본 `--reader auto`에서 일반 OOXML 파일은 `openpyxl`,
직접 해석할 수 없는 바이너리 보호 파일 후보는 `xlwings`로 처리한다. 일반 파일은
Excel을 실행하거나 xlwings를 불러오지 않는다. `--reader xlwings`는 실제 Excel 경로를
시험하거나 이미 회사 보호 방식이 확인된 파일을 명시적으로 읽을 때 사용한다.

DRM은 공급사별 형식이 다르다. “일반 OOXML 아님”은 DRM 확정이 아니며, 손상·다른
실체 형식도 가능하다. 파일 없음·일반 접근 권한 거절·손상 ZIP·검사 한도 실패를
DRM으로 바꾸거나 다른 경로로 반복하지 않는다. `--reader openpyxl`은 Excel을 열지 않는다.

## 준비와 실행

Windows에 설치된 Excel, 승인된 Python 3.10 이상, `requirements-excel.txt`의 의존성이
필요하다. 이미 설치돼 있으면 준비 명령은 생략한다. 하네스·MCP·Claude 설정은 바꾸지 않는다.

```text
python -m pip install -r "<스킬 폴더>/requirements-excel.txt"
python -X utf8 "<스킬 폴더>/scripts/excel_pipeline.py" "<입력.xlsx>" --output "<새 결과 폴더>"
```

일반 파일로 Excel 경로만 시험하려면 `--reader xlwings`를 추가한다. 기본 대기는 90초,
`--excel-timeout`은 10~300초다. 보안·로그인·암호 창 때문에 끝나지 않으면 제한 시간 뒤
중단하며 다른 방식으로 재시도하지 않는다. 보안 창을 자동 승인하거나 암호를 추측하지 않는다.

## 무엇을 읽는가

- 시트·절대 셀 위치·값·수식·표시 형식·병합·Excel Table·이름 범위·숨김 상태를
  메모리에 옮겨 기존 표 발견·수식 해석기를 사용한다. 해석기의 지원 함수 범위는 같다.
- 읽는 도중 Excel이 제공한 값은 `excel_observed_not_recalculated`로 구분한다.
  `cached_value` 필드는 비교용 관찰값을 담으며 `cached_value_origin`으로 출처를 확인한다.
  새로 재계산하거나 원본 매크로를 실행해 검증한 값은 아니다.
- `[h]:mm:ss` 같은 누적 시간은 이미 읽은 Value2의 원래 일수로 복원한다.
  `26:00:00`처럼 24시간을 넘는 기간을 보존하며, 날짜나 시각만으로 기간을 추정하지 않는다.
- Excel이 열면서 정규화한 문자열은 파일 내부 문자열과 다를 수 있다. 실제 시험 파일의
  `t="str"` 셀에서 `" c03 "`을 Excel 자체가 `"c03"`으로 읽는 사례를 확인했다.
  스킬은 Value2로 관찰한 문자열을 추가로 trim하지 않지만, 원문과 완전 동일하다고 보장하지 않는다.
- 내장 VBA는 Excel의 허용된 `VBProject` 접근으로 읽는다. 차단·잠김·원문 제한이면
  `vba_source_unavailable`과 상태를 남기고 표·수식 분석은 계속한다. 다른 추출기로
  접근 거절을 우회하지 않으며 결과값만으로 매크로 로직을 추정해 이전 완료라고 하지 않는다.
- 기존 교육용 `migrate_embedded_training.py`는 일반 OOXML 원문 계약 전용이다.
  보호 파일에 그대로 적용하지 말고, 확보한 원문에 맞춘 업무별 이전 코드가 필요하다.

## 원본과 Excel 보호

새 Excel 인스턴스에서 `AutomationSecurity=3`, 이벤트 끄기, 수동 계산,
`UpdateLinks=0`, 읽기 전용을 사용한다. 원본 저장·매크로 실행·Calculate·RefreshAll을
호출하지 않는다. 원본의 해제된 XLSX 사본도 만들지 않는다. 사용자 Excel에 연결하거나
사용자가 열어둔 파일을 닫지 않는다. 끝날 때 소유한 인스턴스만 정리한다.
단, Excel 시작 자체가 PID를 반환하기 전에 멈추면 소유권을 확인할 수 없어 새 Excel이
남을 수 있다. 이때 다른 Excel까지 일괄 종료하지 않는다.

이 설정은 PC/Office 전체 네트워크 차단이 아니다. 불투명한 DRM 내부의 연결이나
Excel 시작 추가 기능의 동작은 이 도구가 사전에 모두 검사할 수 없다. 회사에서
승인한 파일·Excel 환경에 한해 사용한다. 확인 가능한 OOXML의 연결·쿼리 및 Excel 4.0
매크로 시트는 Excel 경로로 열지 않는다. 직접 정적 분석 가능한 파일은 기존 방식으로 읽는다.
식별 가능한 구형 OLE의 Workbook/Book 스트림도 열기 전에 거절한다. 불투명한 보호
컨테이너 내부까지 사전 검증할 수는 없다. AutomationSecurity=3은 VBA 실행을 막지만
Excel 4.0 매크로에는 같은 보장이 없으며, 나타나는 보안 대화상자를 자동 승인하지 않는다.
최신 Excel은 Formula2로 Excel이 보여 주는 수식을 읽는다. Excel이 시트명의 따옴표나
구버전 수식의 `@`·`_xlfn` 표현을 바꿀 수 있으므로 파일 내부 문자열과 바이트 단위로
같다고 보장하지 않는다. 수식은 임의로 정리하지 않고 관찰된 그대로 보관한다.
구버전에서 Formula로 읽으면 동적 배열 표현 차이가 있을 수 있음을
`incomplete_metadata`에 남긴다. 미지원 수식은 계속 미지원으로 표시한다.

## 모델 입력·오류 처리

기존 한도 그대로 표별 앞 5행, 최대 1,000행, 전체 기본 12,000자를 사용한다.
범위를 많이 읽어도 그 전체를 LLM에 보내지 않는다. 읽기 경로와 VBA 제한은 요약에 남는다.
한도 초과 시 잘린 자료를 전체 처리로 보고하지 않는다. 셀·수식 JSON도 원본과 같은 보안
수준으로 사용자 지정 로컬 폴더에만 보관한다. 실사 DRM 지원은 회사 환경에서 따로 시험한다.

공식 참고: [xlwings 파일 열기](https://docs.xlwings.org/en/stable/api/books.html),
[Excel 자동화 보안과 Excel 4.0 예외](https://learn.microsoft.com/en-us/office/vba/api/excel.application.automationsecurity),
[읽기 전용·외부 링크 옵션](https://learn.microsoft.com/en-us/office/vba/api/excel.workbooks.open).
