# 가상 데이터로 조회 연습

실제 사내 계정과 네트워크 없이 동작하는 연습입니다. 결과에는 가상 데이터임을 표시합니다. 다른 조회 스킬이나 Company Harness를 설치할 필요는 없습니다.

## 인증정보 입력

**“이 연습은 인증정보 없이 진행합니다. 채팅에 계정이나 키를 입력하지 마세요.”**라고 안내합니다. 가상 연결은 `demo-init`이 준비하므로 사번, 비밀번호, 토큰과 S3 키를 요청하거나 실제 연결 설정창을 열지 않습니다. 인증이 필요하다는 오류를 이유로 운영 스킬이나 계정으로 조용히 전환하지 않습니다.

사용자가 이미 실제 인증값을 채팅에 적었어도 반복 인용하거나 가상 설정, 명령 인자와 로그에 옮기지 않고 값 없이 연습을 계속합니다. 실제 접속을 사용자가 별도로 요청하면 해당 운영 스킬과 연결 범위를 먼저 구분하며, 운영 인증정보를 받는 위치는 그 스킬의 로컬 입력창입니다.

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

사용자가 쿼리와 조건을 정해 조회를 요청했다면 일반 조회는 `execute --id <번호> --params <조건 JSON> --confirm`으로 이어갑니다. 같은 내용을 다시 확인받으려고 계획과 질문을 반복하지 않습니다. 앞의 `plan`과 `run`은 사전 검토를 요청한 경우나 큰 조회가 필요한 경우의 흐름입니다.

```text
python -X utf8 -B scripts/query.py plan --id <등록 번호> --params <조건 JSON> --max-rows 50000 --max-bytes 52428800 --timeout 90
python -X utf8 -B scripts/query.py run --plan <새 계획 ID> --confirm --allow-large
```

가상 데이터도 일부만 얻은 결과와 전체 결과를 구분합니다. 시간 초과와 0건, 사용자 허락이 필요한 상태를 성공으로 바꾸지 않습니다. 데이터 원문은 출력하지 않고 저장 파일을 Python으로 계산합니다.

## 내 SQL 저장 연습

사용자가 SQL 등록을 요청하면 바뀔 조건을 확인하고 작은 실제 시험 조회까지 이어갑니다. 등록 명령은 기본적으로 저장 후 최대 10행의 시험 조회를 수행하므로 별도 `--confirm` 옵션이 없어도 실행됩니다. 이미 정해진 조건과 조회 전용 요청에 대해 “시험해도 될까요?”를 반복하지 않습니다. 등록 명세와 조건을 준비해 다음을 실행합니다.

```text
python -X utf8 -B scripts/query.py queries register --spec <등록 명세 JSON> --params <조건 JSON 파일 또는 JSON 객체>
```

시험 조회는 최대 10행을 저장하며 행 원문을 자동 반환하지 않습니다. 필요한 조건이 없는 쿼리는 `--params`를 생략하면 `{}`로 시험합니다. 필수 값이 빠졌다면 임의로 채우지 말고 필요한 값만 한 번 확인합니다. `--params`는 JSON 파일 경로와 인라인 JSON 객체를 모두 받습니다. 예를 들어 `--params '{"process":"WB"}'`도 가능하지만 셸 인용이 복잡하면 스킬이 작은 조건 파일을 만들어 전달합니다. 잘못된 JSON이나 없는 파일은 입력 오류이며 SDK 또는 인증 실패로 단정하지 않습니다.

사용자가 저장만 요청하면 `--save-only`로 실제 조회 없이 저장하고 `query_registered_not_tested`로 안내합니다. 이 경우 시험을 권하거나 빠진 시험 조건을 다시 묻지 않습니다. 기존 `--confirm`은 같은 기본 시험을 수행하는 호환 인자이며 `--save-only`와 함께 사용하지 않습니다. 실제 시험에서 정상 응답과 데이터 존재, 정상 0건, 서버 오류, 한도로 끝까지 확인하지 못한 결과를 각각 알립니다. 10행만 확인한 시험을 전체 건수 검증으로 설명하지 않습니다. 넓은 기간 등 기존 큰 조회 승인 대상은 작은 시험이어도 같은 승인 절차를 따릅니다. 승인 대기와 오류를 검증 성공으로 바꾸지 않습니다. 시험 결과가 현재 요청을 `complete: true`로 완전히 충족하면 같은 조회를 즉시 한 번 더 실행할 필요가 없습니다.


저장만 요청한 경우에는 다음처럼 실행합니다. 기본 등록 예문에 별도 확인 질문을 더하지 않습니다.

```text
python -X utf8 -B scripts/query.py queries register --spec <등록 명세 JSON> --save-only
```

### 실제 시험 기록 확인

등록 응답의 `registered`와 `validationStatus`를 따로 봅니다. 다음 `status`는 저장 여부와 시험 상태를 함께 표시하며 승인 대기를 완료로 바꾸지 않습니다.

| 등록 응답의 status | 의미 |
|---|---|
| `query_registered_success_with_rows` | 시험에서 반환 행을 확인했습니다. `resultComplete`가 거짓이면 최대 10행 범위의 확인이며 전체 조회를 마친 것은 아닙니다. |
| `query_registered_success_empty` | 실제 시험이 오류 없이 끝났고 지정한 조건의 반환 행은 0건입니다. |
| `query_registered_approval_required` | 쿼리는 저장됐지만 시험도 범위 검토나 큰 조회 승인이 필요해 아직 실행하지 않았습니다. |
| `query_registered_not_tested` | `--save-only`로 쿼리만 저장했으며 실제 시험 조회는 실행하지 않았습니다. |
| `query_registered_parameters_required` | 시험에 필요한 조건이 빠졌거나 맞지 않아 아직 실행하지 않았습니다. |
| `query_registered_error` | 접속 또는 SQL 실행 과정에서 실패했습니다. `errorCode`, 가린 `errorDetails`와 `queryExecuted`를 함께 설명합니다. |
| `query_registered_partial_inconclusive`, `query_registered_input_error`, `query_registered_result_error` | 제한, 입력 또는 결과 저장 문제로 충분히 검증하지 못했습니다. 해당 이유를 안내합니다. |

기록을 확인할 필요가 있을 때만 `queries show --id <번호>`의 `validation`을 봅니다. 여기에 있는 `checkedAt`, `resultId`, `validationStatus`는 최근 시험 기록이며 새 조회가 아닙니다. `not_tested`는 기록 없음, `stale`은 SQL이나 조건 정의가 바뀌어 예전 시험을 현재 쿼리의 근거로 쓸 수 없다는 뜻입니다. 매 일반 조회마다 이 명령을 추가 실행하지 않습니다.

승인 대기 중인 등록 시험은 사용자가 해당 범위를 허락한 뒤 반환된 계획을 `run --plan <ID> --confirm --allow-large`로 실행하면 같은 시험 기록에 연결됩니다. 큰 조회가 아니라 전체 조건 확인만 필요하면 `--allow-large`를 붙이지 않습니다. 결과 기록 연결에 문제가 있다는 경고가 있으면 같은 조회를 자동 반복하지 말고 저장된 결과와 경고를 안내합니다.

현재 요청에 필요한 범위를 `complete: true`로 받은 시험 결과만 그 요청의 후속 처리에 바로 쓸 수 있습니다. 10행 한도로 일부만 확인한 시험을 완전한 업무 결과처럼 재사용하지 않습니다. 나중의 새 조회 요청이나 실시간 현황에는 다시 조회합니다.

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
python -X utf8 -B scripts/query.py queries register --spec <명세 JSON> --params <조건 JSON>
python -X utf8 -B scripts/query.py queries register --spec <수정 명세 JSON> --replace-id <기존 번호> --params <조건 JSON>
```

등록이나 수정 후에는 적용할 조건으로 작은 시험 조회를 이어갑니다. 저장만 했거나 조건이 없어 시험하지 못했다면 미검증으로 안내합니다. 바꿀 조건과 고정할 값을 구분하며 SQL 문자열에 값을 직접 끼워 넣지 않습니다.

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

## 새 조회와 이전 결과 구분

실행 결과의 `status`와 `outcome`도 구분합니다. 정상 전체 결과는 `status: complete`와 `outcome: rows_returned` 또는 `empty`, 한도에 걸린 결과는 `status: partial`과 `outcome: partial`, 실패는 `status: failed`와 `outcome: error`입니다. 실패를 0건으로 바꾸지 않습니다. `SELECT COUNT(*)`가 반환한 한 행의 값 0은 반환 행 수 0과 다르므로 해당 쿼리의 의미에 맞게 설명합니다.


저장된 결과가 있다는 이유만으로 재사용하지 않습니다. 현재 상태, 할당, 재고, 진행 현황 등 실시간성 조회는 기본적으로 새로 실행합니다. 이력 조회도 새 조회 요청이면 다시 실행하며, 과거 결과를 쓰려면 조회 시각과 조건, 완전성을 알리고 사용자의 허락을 받습니다. 기본값대로 새로 조회할 때는 재사용 여부를 매번 묻지 않습니다. 사용자가 “방금 조회한 결과로 합계 내줘”처럼 현재 작업의 결과를 지정한 후속 분석은 그 파일을 사용할 수 있습니다. 다른 시점의 결과까지 같은 허락으로 넓히지 않습니다.

정상 0건은 오류가 아닙니다. 반대로 SQL 또는 접속 오류로 실패한 조회를 0건으로 표시하지 않습니다. 실패 시 응답에 있는 오류 코드와 인증정보를 가린 짧은 이유, 실패 단계를 알려줍니다. 비밀번호, 토큰, DSN과 전체 예외 추적을 출력하지 않으며 한 번의 실패를 피해 SQL, 계정이나 날짜를 임의로 바꾸지 않습니다.

## 소량 미리보기와 A 결과로 B 조회하기

미리보기와 연속 조회가 필요할 때만 [Python 연속 조회와 미리보기](workflows.md)를 읽습니다. 기본 조회 응답은 데이터 원문을 반환하지 않습니다. 미리보기는 명시 요청 때만 기본 5행, 최대 20행과 8,000자 안에서 제공하며 전체 저장 파일은 Python으로 처리합니다.
