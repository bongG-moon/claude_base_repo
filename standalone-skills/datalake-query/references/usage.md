# 사용 방법

## 대화 예시

- “처음 사용할 거야. 연결 설정해줘.”
- “DB 하나 더 추가해줘. 이름은 품질DB야.”
- “등록한 DB와 쿼리를 관리할 수 있는 화면을 열어줘.”
- “이 SQL을 생산실적조회로 저장해줘. 기간과 공정만 바꿀 수 있으면 좋겠어.”
- “저장한 쿼리를 보여줘.”
- “1번을 지난달 WB 공정으로 조회해줘.”
- “이번에는 10만 행까지 허용할게.”

프로필과 쿼리 이름은 사용자 표현을 유지합니다. 실제 등록된 DB 이름을 화면과 답변에 사용합니다. 계정과 토큰은 로컬 설정창에서만 입력합니다.

## 실행 명령

아래 `scripts/query.py`는 **현재 스킬 본문이 있는 폴더** 기준입니다. 플랫폼 ZIP은 본문과 함께 있는 scripts 폴더를 사용합니다. 알려진 실제 경로를 인용하고 설치 위치나 세션 ID를 찾으려고 PC 전체를 탐색하지 않습니다.

```text
python -X utf8 -B scripts/query.py start
python -X utf8 -B scripts/query.py manage
python -X utf8 -B scripts/query.py manage --profile <등록된 연결 ID>
python -X utf8 -B scripts/query.py profiles list
python -X utf8 -B scripts/query.py profiles setup
python -X utf8 -B scripts/query.py profiles setup --profile <등록된 연결 ID>
python -X utf8 -B scripts/query.py queries register --spec <등록 명세 JSON>
python -X utf8 -B scripts/query.py queries register --spec <수정 명세 JSON> --replace-id 1
python -X utf8 -B scripts/query.py queries list
python -X utf8 -B scripts/query.py queries show --id 1
python -X utf8 -B scripts/query.py execute --id 1 --params <조건 JSON> --confirm
python -X utf8 -B scripts/query.py plan --id 1 --params <조건 JSON>
python -X utf8 -B scripts/query.py run --plan <반환된 계획 ID> --confirm
python -X utf8 -B scripts/query.py result --id <반환된 결과 ID>
```

사용자에게 위 명령어 작성을 요구하지 않습니다. 대화를 바탕으로 스킬이 실행하고 사람이 정할 조건만 확인합니다. 별도 실습 경로는 `--state-root <절대경로>`를 명령 앞에 지정합니다. 실제 사용은 기본 개인 저장소를 재사용합니다.

연결 설정을 저장하는 작업과 실제 접속은 별개입니다. `start`, 목록과 관리 화면은 DB에 접속하지 않습니다. `plan`과 `execute`의 사전 검토는 실제 LakeHouse 준비 API와 실행계획 조회를 사용합니다. 준비 API가 클러스터를 기동할 수 있으므로 연결 설정의 기동 허용은 사용자가 선택해야 합니다. 서버 주소를 임의로 낮은 보안 방식으로 바꾸거나 인증서 검증을 끄지 않습니다. 연결 실패 시 설정값 자체를 출력하지 않습니다.

## 업무 시작과 이전 결과 정리

`start`는 새 조회 업무를 시작할 때 한 번만 실행합니다. 등록된 연결과 쿼리 요약을 함께 받고, 24시간이 지난 로컬 결과가 있으면 최대 10개 후보를 정리 계획으로 준비합니다. 결과 행과 인증정보는 반환하지 않습니다. 같은 업무에서 조건을 바꾸어 다시 조회하거나 저장된 결과를 분석할 때는 `start`를 반복하지 않습니다.

후보가 있을 때만 “이전 결과 3건, 8MiB를 삭제할까요, 보존할까요?”처럼 `cleanup.count`와 `cleanup.totalBytes`의 실제 계획 범위로 한 번 묻습니다. 전체 후보가 더 많더라도 이번 계획보다 많은 파일을 삭제한다고 안내하지 않습니다. 삭제를 선택하면 `cleanup.planId`의 고정된 대상에 대해 다음을 실행합니다. 사용자가 이미 같은 범위의 삭제를 지시했다면 그 지시를 사용하며 같은 허락을 재질문하지 않습니다.

```text
python -X utf8 -B scripts/query.py results cleanup --plan <cleanup.planId> --confirm
```

후보가 없거나 보존을 선택했다면 바로 조회를 계속합니다. 계획을 준비한 것만으로 삭제됐다고 말하지 않습니다. 계획에 없던 파일이나 바뀐 결과까지 삭제 범위를 넓히지 않습니다. 등록한 DB 연결, 인증정보와 쿼리 원본은 결과 정리 대상이 아닙니다. 후속 분석에 필요한 결과는 보존합니다.

별도로 결과를 확인하거나 사용자가 지정한 결과만 정리할 때는 다음 명령을 사용합니다. 번호는 응답의 실제 결과 ID를 사용합니다. `cleanup-plan`의 `--id`는 여러 번 지정할 수 있으며 생략하면 24시간이 지난 후보 중 최대 10개로 계획을 만듭니다. 계획 작성 후 삭제에는 실제 허락과 `--confirm`이 필요합니다.

```text
python -X utf8 -B scripts/query.py results list --limit 20
python -X utf8 -B scripts/query.py results cleanup-plan
python -X utf8 -B scripts/query.py results cleanup-plan --id <결과 ID> --id <다른 결과 ID>
```

## 연결과 쿼리 관리

`manage`는 현재 저장된 DB와 쿼리를 보여주는 로컬 웹 화면을 엽니다. DB 연결을 추가하거나 수정할 수 있고 입력칸의 설명을 보고 필요한 값을 넣습니다. `manage --profile <ID>`와 `profiles setup --profile <ID>`는 지정한 연결의 설정 화면을 엽니다. `profiles setup`도 같은 LakeHouse 설정 화면을 사용하며 저장이 끝나면 대화로 돌아옵니다. `manage`는 저장 뒤에도 목록을 계속 볼 수 있고 닫기로 종료합니다. 실제 DB에 접속해 확인하는 작업과 저장된 설정을 보는 작업은 구분합니다.

설정 화면에는 DB 이름, LakeHouse API 주소, 사번과 토큰을 입력합니다. 클러스터 이름과 CA 인증서 파일은 환경에 필요한 경우만 지정합니다. HTTP 사용과 클러스터 기동 허용은 기본으로 선택하지 않으며, 사용자가 회사 환경과 동작을 확인해 선택합니다. 클러스터 이름이 비어 있으면 서버가 제공한 기본 또는 유일한 클러스터를 사용하고, 여러 후보를 구분할 수 없으면 사용할 이름을 확인합니다. 기존 연결을 수정할 때 저장된 토큰을 매번 다시 입력하게 하지 않습니다.

사용자가 이미 지정한 연결과 쿼리가 있으면 그 값을 재사용합니다. 매번 `profiles list`, `queries list`, `queries show`를 모두 호출하거나 관리 화면을 열 필요가 없습니다. 목록과 상세 조회는 선택이 필요하거나 SQL과 조건 정의를 아직 모를 때만 사용합니다.

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

위 예문의 종료 날짜는 `미만` 조건이므로 10월 전체입니다. 날짜 경계와 시간대를 SQL 의미에 맞게 설명합니다. 상대 날짜는 실제 날짜로 풀고 의미가 불명확할 때만 확인합니다. 값은 바인드로 전달하며 문자열 조합으로 SQL에 끼워 넣지 않습니다.

## 같은 조건을 다시 묻지 않고 조회하기

사용자가 “생산DB의 1번을 10월 WB 공정으로 조회해줘”라고 했고 쿼리와 날짜 경계, 필수 조건이 모두 정해졌다면 그 요청을 실행 승인으로 사용합니다. 기본 행 한도는 **50,000행**이며 본 조회의 파일 용량과 시간에는 기본 제한이 없습니다. 이 기본 설정을 사용하기 위해 별도 확대 승인을 묻지 않습니다.

```text
python -X utf8 -B scripts/query.py execute --id 1 --params <조건 JSON> --confirm
```

`execute`는 계획 검증을 거쳐 일반 조회만 바로 실행합니다. 사용자가 정한 DB와 조건을 짧게 알리고 진행하며, 같은 내용을 “실행할까요?”라고 다시 묻지 않습니다. 단순히 쿼리를 보여 달라는 요청이나 SQL 등록 요청을 조회 승인으로 바꾸지 않습니다. DB 선택과 필수 조건이 빠졌거나 의미가 모호하면 필요한 내용만 먼저 확인합니다.

응답이 `executed: false`와 `planId`를 반환하면 아직 조회 결과가 아닙니다. 큰 조회 승인이 필요하면 아래 절차를 따릅니다. `conditionsTruncated`가 참이면 사용자가 `conditionReviewFile`의 전체 조건을 로컬에서 확인한 뒤 해당 계획을 실행합니다. 큰 조회가 아니라면 `run --confirm`만 사용하며, `requiresLargeApproval`도 참일 때만 `--allow-large`를 추가합니다.

검토만 요청했거나 실행 전에 계획을 따로 보고 싶으면 `plan`을 사용합니다. 이때 확인한 계획을 `run --plan <계획 ID> --confirm`으로 실행하며 동일한 허락을 다시 묻지 않습니다.

## 계획 단계에서 실제로 하는 일

`plan`은 LakeHouse 준비 API에서 클러스터 상태와 접속 위치를 확인하고, 연결한 뒤 `EXPLAIN COSTS`로 SQL의 처리 규모를 검토합니다. 원본 결과 행이나 실행계획 원문을 대화로 반환하지 않습니다. 큰 조회 승인을 기다리는 경우에도 이 사전 준비는 이미 이루어졌을 수 있습니다. `execute`도 같은 검토를 거친 다음 일반 조회만 실행합니다.

일반 `execute`는 한 요청 안에서 준비한 연결을 계획 검토와 본 조회에 재사용합니다. 별도 `plan` 후 `run`을 호출하거나 큰 조회와 긴 조건의 승인을 기다렸다가 실행하면 새 연결을 준비합니다. 연결, 클러스터 준비와 `EXPLAIN COSTS`에는 실패를 감지하기 위한 시간 제한이 있습니다. 본 조회에 도구의 기본 시간 제한이 없더라도 서버의 쿼리 제한이나 네트워크 자체 제한까지 해제되지는 않습니다. 인증 오류나 준비 실패를 해결하려고 설정 변경, 다른 계정 사용이나 반복 재시도를 자동으로 하지 않습니다. 결과 건수가 미확인이라고 별도 전체 COUNT를 추가하지 않습니다.

파일 용량이나 조회 시간을 사용자가 제한하고 싶을 때만 `plan` 또는 `execute`에 `--max-bytes <양의 정수 바이트>`와 `--timeout <양의 정수 초>`를 지정합니다. 생략하면 해당 제한을 두지 않습니다. 이전의 파일 용량과 조회 시간 상한은 적용하지 않습니다. 직접 지정한 숫자는 실행 환경이 지원하는 범위 안에서 사용하며, 처리할 수 없는 값은 조용히 줄이지 않고 안내합니다. 이 제한을 추가했다는 이유만으로 큰 조회 승인을 요구하지 않습니다. 행 수와 SQL 범위에 대한 승인 조건은 그대로 적용합니다.

## 큰 조회를 허용하는 흐름

기본 한도보다 넓은 범위도 사용자 허락을 받으면 실행할 수 있습니다. 필요한 한도로 먼저 새 계획을 만듭니다.

```text
python -X utf8 -B scripts/query.py plan --id 1 --params <조건 JSON> --max-rows 100000
```

반환된 계획의 DB 이름, 조건, 행 한도와 주의점을 보여주고 허락을 받습니다. 기본 50,000행 확대 외에 31일을 넘는 기간, 조건 없는 범위나 결합 조건 없는 조인, 사용자 함수와 재귀 조회 등도 승인 대상이 될 수 있습니다. 이미 같은 범위와 한도를 명시적으로 허용했다면 그 지시를 재사용하되, 새 주의점이나 변경된 범위를 이전 허락으로 넘기지 않습니다. 실제 허락이 있을 때만 다음을 실행합니다.

```text
python -X utf8 -B scripts/query.py run --plan <새 계획 ID> --confirm --allow-large
```

이 실행기의 최대 행 수는 1,000,000행입니다. Datalake의 본 조회에는 고정된 파일 용량과 시간 상한이 없으며 DB의 더 낮은 제한은 그대로 적용됩니다. 계획은 15분 뒤 만료되고 한 번만 실행됩니다. 계획과 다른 SQL, 조건, 연결 또는 한도에는 이전 허락을 재사용하지 않습니다. LakeHouse 계획은 `EXPLAIN COSTS`의 최대 단계 추정치만 확인합니다. 이 값은 결과 건수나 정확한 스캔 건수가 아니며, 전체 COUNT와 ANALYZE를 자동 실행하지 않으므로 실제 건수는 미확인일 수 있습니다. 기본 한도로 실행한다는 뜻을 실제 결과가 50,000행 이하라고 확인한 것으로 설명하지 않습니다. 행 한도에 걸리면 일부 결과로 안내합니다. DB의 권한과 자원 제한, 드라이버 지원 범위는 사용자 허락으로 해제되지 않습니다. 실패를 피해 다른 SQL이나 계정으로 바꾸지 않습니다.

수정은 `queries register --replace-id <기존 번호>`로 같은 항목을 갱신합니다. SQL이나 조건이 달라졌다면 예전 계획을 실행하지 말고 새 계획을 만듭니다.

## 결과와 재사용

실행 응답은 결과 ID, `label`, 파일 위치, 행 수와 완전성 등 짧은 정보입니다. `label`은 쿼리 이름, DB 이름과 실행 시각으로 결과를 구분하는 표시 이름입니다. 실제 파일 위치는 반환된 `dataFile`을 사용하며 표시 이름으로 경로를 추측하지 않습니다. 원본 데이터를 Read, head, 출력문으로 대화에 쏟지 않습니다. Python에서 결과 파일을 불러 계산하고 필요한 집계만 출력합니다. 기본 결과는 한 줄에 한 행을 배열로 저장한 JSONL입니다. 열 이름은 같은 폴더의 metadata.json에 있으며 숫자와 날짜 의미를 유지합니다. CSV가 필요할 때만 export-csv로 내보냅니다. CSV는 수식처럼 보이는 문자열에 보호 표시를 붙이며 JSONL 원본은 바꾸지 않습니다. 엑셀에서 식별자의 앞자리 0을 보존할 열 형식은 별도로 지정합니다.

같은 결과에 대한 후속 분석은 저장 파일을 재사용합니다. 최신 데이터를 요청한 경우에만 다시 조회합니다. 조회 결과가 0건인 경우와 오류, 제한으로 중단된 경우를 구분합니다.

## 설치 환경과 실제 검증 범위

Python 3.11 이상과 이 스킬의 requirements.txt에 적힌 패키지, 로컬 관리 화면을 열 웹 브라우저가 필요합니다. 패키지 설치는 승인된 사내 패키지 저장소 또는 접근 가능한 공급처를 사용합니다. 기존 Python이나 다른 환경의 설정을 초기화하지 않습니다.

이 ZIP은 지침과 실행 코드입니다. 실제 DB 권한이나 사내망 접근을 제공하지 않습니다. 더미 검증으로 사내 연결, LakeHouse의 현행 응답이나 실제 테이블 접근 권한을 보증하지 않습니다.

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
