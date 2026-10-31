# 가상 데이터로 조회 연습

실제 사내 계정과 네트워크 없이 동작하는 연습입니다. 결과에는 가상 데이터임을 표시합니다. 다른 조회 스킬이나 Company Harness를 설치할 필요는 없습니다.

## 사용자가 해볼 말

1. “조회 연습을 준비하고 저장한 쿼리를 보여줘.”
2. “생산실적조회에 어떤 조건을 넣을 수 있어?”
3. “이번에는 날짜와 공정을 바꿔 조회해줘.”
4. “같은 결과를 Python으로 합계 내줘.”
5. “큰 조회도 연습해보고 싶어. 허용 전에 어떤 범위인지 알려줘.”

## 스킬의 실행 순서

현재 스킬 본문과 함께 있는 scripts/query.py를 사용합니다. 처음 한 번만 다음을 실행합니다.

```text
python -X utf8 -B scripts/query.py demo-init
python -X utf8 -B scripts/query.py profiles list
python -X utf8 -B scripts/query.py queries list
```

`demo-init`이 준비한 실제 목록의 번호와 연결 이름을 사용합니다. 번호나 테이블 이름을 미리 가정하지 않습니다. 쿼리 조건은 `queries show --id <번호>`로 확인합니다.

```text
python -X utf8 -B scripts/query.py queries show --id <등록 번호>
python -X utf8 -B scripts/query.py plan --id <등록 번호> --params <조건 JSON>
python -X utf8 -B scripts/query.py run --plan <반환된 계획 ID> --confirm
python -X utf8 -B scripts/query.py result --id <반환된 결과 ID>
```

준비되는 연결은 생산DB, 품질DB, 실습 데이터레이크와 실습 E-HUB입니다. 쿼리는 5개이며 생산실적조회에는 {"start_date":"2026-10-01","end_date":"2026-11-01","process":"WB"} 조건을 사용할 수 있습니다. plan이 반환한 DB 이름과 조건을 보여주고 한 번 확인받습니다. `run`의 확인 인자는 실제 사용자 답변 뒤에 사용합니다. 큰 조회는 확대할 행 수, 크기와 시간을 먼저 지정한 새 계획을 보여주고 허락받습니다.

```text
python -X utf8 -B scripts/query.py plan --id <등록 번호> --params <조건 JSON> --max-rows 50000 --max-bytes 52428800 --timeout 90
python -X utf8 -B scripts/query.py run --plan <새 계획 ID> --confirm --allow-large
```

가상 데이터도 일부만 얻은 결과와 전체 결과를 구분합니다. 시간 초과와 0건, 사용자 허락이 필요한 상태를 성공으로 바꾸지 않습니다. 데이터 원문은 출력하지 않고 저장 파일을 Python으로 계산합니다.

## 내 SQL 저장 연습

실습 자료에 있는 테이블을 기준으로 SQL과 바뀔 조건을 정하고 등록할 수 있습니다. 다음 명세의 테이블은 실제 가상 DB에서 확인한 이름으로 사용합니다.

```json
{
  "name":"내 조회 연습",
  "profile":"목록에서 확인한 연결 ID",
  "sql":"SELECT work_date, process, quantity FROM production_records WHERE process = :process",
  "parameters":{"process":{"type":"text","required":true}}
}
```

```text
python -X utf8 -B scripts/query.py queries register --spec <명세 JSON>
python -X utf8 -B scripts/query.py queries register --spec <수정 명세 JSON> --replace-id <기존 번호>
```

새로 등록하거나 수정하는 작업만으로 데이터를 조회하지 않습니다. 바꿀 조건과 고정할 값을 구분하며 SQL 문자열에 값을 직접 끼워 넣지 않습니다.

## 실행 환경

Python 3.11 이상과 sqlglot==28.5.0이 필요합니다. 설치가 필요하면 승인된 사내 패키지 저장소나 접근 가능한 공급처를 사용합니다. 사용자에게 명령 작성이나 JSON 편집을 요구하지 않고 대화를 바탕으로 스킬이 필요한 작은 파일을 준비합니다.

개인 실습 저장소는 설치 폴더 밖에 만들어집니다. 별도 시험 위치가 필요한 경우에만 명령 앞에 `--state-root <절대경로>`를 지정합니다. 운영 `profiles setup`이나 실제 인증정보는 사용하지 않습니다. 더미 스킬의 성공은 Oracle/StarRocks 실접속과 사내 모델의 자연어 수행을 검증한 결과가 아닙니다.

기본 결과는 JSONL 행 배열이며 같은 폴더의 metadata.json에서 열 이름을 확인합니다. 기본 10,000행, 20MiB, 30초 한도를 적용합니다. 계획은 15분 뒤 만료되고 한 번만 실행됩니다. CSV는 요청할 때만 명시적으로 내보냅니다. 수식처럼 보이는 문자열의 CSV 보호 표시는 JSONL 원본 값을 변경하지 않습니다.

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
