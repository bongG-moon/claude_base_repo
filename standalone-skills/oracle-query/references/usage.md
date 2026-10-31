# 사용 방법

## 대화 예시

- “처음 사용할 거야. 연결 설정해줘.”
- “DB 하나 더 추가해줘. 이름은 품질DB야.”
- “이 SQL을 생산실적조회로 저장해줘. 기간과 공정만 바꿀 수 있으면 좋겠어.”
- “저장한 쿼리를 보여줘.”
- “1번을 지난달 WB 공정으로 조회해줘.”
- “데이터가 많아도 이번에는 5만 행까지 허용할게.”

프로필과 쿼리 이름은 사용자 표현을 유지합니다. 실제 등록된 DB 이름을 화면과 답변에 사용합니다. 계정과 토큰은 로컬 설정창에서만 입력합니다.

## 실행 명령

아래 `scripts/query.py`는 **현재 스킬 본문이 있는 폴더** 기준입니다. 플랫폼 ZIP은 본문과 함께 있는 scripts 폴더를 사용합니다. 알려진 실제 경로를 인용하고 설치 위치나 세션 ID를 찾으려고 PC 전체를 탐색하지 않습니다.

```text
python -X utf8 -B scripts/query.py profiles list
python -X utf8 -B scripts/query.py profiles setup
python -X utf8 -B scripts/query.py profiles setup --profile <등록된 연결 ID>
python -X utf8 -B scripts/query.py queries register --spec <등록 명세 JSON>
python -X utf8 -B scripts/query.py queries register --spec <수정 명세 JSON> --replace-id 1
python -X utf8 -B scripts/query.py queries list
python -X utf8 -B scripts/query.py queries show --id 1
python -X utf8 -B scripts/query.py plan --id 1 --params <조건 JSON>
python -X utf8 -B scripts/query.py run --plan <반환된 계획 ID> --confirm
python -X utf8 -B scripts/query.py result --id <반환된 결과 ID>
```

사용자에게 위 명령어 작성을 요구하지 않습니다. 대화를 바탕으로 스킬이 실행하고 사람이 정할 조건만 확인합니다. 별도 실습 경로는 `--state-root <절대경로>`를 명령 앞에 지정합니다. 실제 사용은 기본 개인 저장소를 재사용합니다.

연결 설정을 저장하는 작업과 실제 접속은 별개입니다. 서버 주소를 임의로 낮은 보안 방식으로 바꾸거나 인증서 검증을 끄지 않습니다. 연결 실패 시 설정값 자체를 출력하지 않습니다.

## 쿼리 등록

사용자가 준 SQL을 읽고 변수로 사용할 값과 고정할 값을 한 번 확인합니다. 모든 숫자와 문자열을 무조건 변수로 바꾸지 않습니다. 등록 명세에는 인증정보를 넣지 않습니다.

```json
{
  "name": "생산실적조회",
  "profile": "등록된 연결 ID",
  "sql": "SELECT work_date, process, quantity FROM production_records WHERE work_date >= :start_date AND work_date < :end_date AND process = :process",
  "parameters": {
    "start_date": {"type": "date", "required": true},
    "end_date": {"type": "date", "required": true},
    "process": {"type": "text", "required": true}
  }
}
```

이는 설명용 테이블입니다. 운영 DB에 이 테이블이 있다고 가정하지 않습니다. 조회 시 조건 파일은 다음처럼 만듭니다.

```json
{"start_date":"2026-10-01","end_date":"2026-11-01","process":"WB"}
```

위 예문의 종료 날짜는 `미만` 조건이므로 10월 전체입니다. 날짜 경계와 시간대를 SQL 의미에 맞게 설명합니다. 상대 날짜는 실제 날짜로 풀어 확인합니다. 값은 바인드로 전달하며 문자열 조합으로 SQL에 끼워 넣지 않습니다.

## 큰 조회를 허용하는 흐름

기본 한도보다 넓은 범위도 사용자 허락을 받으면 실행할 수 있습니다. 필요한 한도로 먼저 새 계획을 만듭니다.

```text
python -X utf8 -B scripts/query.py plan --id 1 --params <조건 JSON> --max-rows 50000 --max-bytes 52428800 --timeout 90
```

반환된 계획의 DB 이름, 조건과 예상 크기, 실행 제한을 보여주고 허락을 받습니다. 실제 답변 뒤에만 다음을 실행합니다.

```text
python -X utf8 -B scripts/query.py run --plan <새 계획 ID> --confirm --allow-large
```

기본 한도는 10,000행, 20MiB, 30초입니다. 이 실행기의 최대 범위는 1,000,000행, 512MiB, 1,800초이며 DB의 더 낮은 제한은 그대로 적용됩니다. 계획은 15분 뒤 만료되고 한 번만 실행됩니다. 계획과 다른 SQL, 조건, 연결 또는 한도에는 이전 허락을 재사용하지 않습니다. 정확한 건수가 없으면 미확인으로 말합니다. DB의 권한과 자원 제한, 드라이버 지원 범위는 사용자 허락으로 해제되지 않습니다. 실패를 피해 다른 SQL이나 계정으로 바꾸지 않습니다.

수정은 `queries register --replace-id <기존 번호>`로 같은 항목을 갱신합니다. SQL이나 조건이 달라졌다면 예전 계획을 실행하지 말고 새 계획을 만듭니다.

## 결과와 재사용

실행 응답은 결과 ID, 파일 위치, 행 수와 완전성 등 짧은 정보입니다. 원본 데이터를 Read, head, 출력문으로 대화에 쏟지 않습니다. Python에서 결과 파일을 불러 계산하고 필요한 집계만 출력합니다. 기본 결과는 한 줄에 한 행을 배열로 저장한 JSONL입니다. 열 이름은 같은 폴더의 metadata.json에 있으며 숫자와 날짜 의미를 유지합니다. CSV가 필요할 때만 export-csv로 내보냅니다. CSV는 수식처럼 보이는 문자열에 보호 표시를 붙이며 JSONL 원본은 바꾸지 않습니다. 엑셀에서 식별자의 앞자리 0을 보존할 열 형식은 별도로 지정합니다.

같은 결과에 대한 후속 분석은 저장 파일을 재사용합니다. 최신 데이터를 요청한 경우에만 다시 조회합니다. 조회 결과가 0건인 경우와 오류, 제한으로 중단된 경우를 구분합니다.

## 설치 환경과 실제 검증 범위

Python 3.11 이상과 이 스킬의 requirements.txt에 적힌 패키지가 필요합니다. 패키지 설치는 승인된 사내 패키지 저장소 또는 접근 가능한 공급처를 사용합니다. 기존 Python이나 다른 환경의 설정을 초기화하지 않습니다. 로컬 설정창에는 tkinter가 포함된 Python이 필요합니다.

이 ZIP은 지침과 실행 코드입니다. 실제 DB 권한이나 사내망 접근을 제공하지 않습니다. 더미 검증으로 사내 연결, Oracle 버전별 SQL 호환성을 보증하지 않습니다.

## Python으로 결과를 재사용하기

`result`가 반환한 dataFile 경로를 사용합니다. 아래 예시는 데이터 원문 대신 저장 행 수와 숫자 합계만 출력합니다. 전체 조회가 완료됐는지 먼저 확인하고 실제 열 이름에 맞게 계산합니다. 날짜는 ISO 문자열, 정밀한 소수는 문자열일 수 있으므로 필요한 형식으로 명시적으로 변환합니다.

```python
import json
from decimal import Decimal
from pathlib import Path

# 실행 응답에 있는 실제 경로로 바꿉니다. 개인 저장소 전체를 찾지 않습니다.
data_file = Path(r"결과의 dataFile 경로")
metadata = json.loads(data_file.with_name("metadata.json").read_text(encoding="utf-8"))
if not metadata["complete"]:
    raise ValueError("일부 결과입니다. 전체 합계로 사용하지 마세요.")
columns = metadata["columns"]
# 이 예제는 quantity 열의 합계만 계산합니다. 행 내용은 출력하지 않습니다.
quantity_index = columns.index("quantity")
total = Decimal("0")
rows = 0
with data_file.open(encoding="utf-8") as source:
    for line in source:
        row = json.loads(line)
        if row[quantity_index] is not None:
            total += Decimal(str(row[quantity_index]))
        rows += 1
print(json.dumps({"rows": rows, "quantityTotal": str(total)}, ensure_ascii=False))
```

CSV 파일이 필요한 경우에만 다음 명령을 사용합니다. 기존 파일을 덮어쓰지 않습니다.

```text
python -X utf8 -B scripts/query.py export-csv --id <결과 ID> --output <새 CSV 절대경로>
```
