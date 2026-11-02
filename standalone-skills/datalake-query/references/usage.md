# 사용 방법

## 대화 예시

- “처음 사용할 거야. Data Lake 인증정보를 설정해줘.”
- “이 테이블을 조회해줘. 경로는 lake_catalog.스키마.테이블이야.”
- “인증정보와 저장 쿼리를 관리하는 화면을 열어줘.”
- “이 SQL을 생산실적조회로 저장해줘. 기간과 공정만 바꿀 수 있으면 좋겠어.”
- “저장한 쿼리를 보여줘.”
- “1번을 지난달 WB 공정으로 조회해줘.”
- “이번에는 10만 행까지 허용할게.”

조회할 DB와 스키마, 테이블 정보는 SQL의 `lake_catalog.스키마.테이블` 경로에 있습니다. DB 이름, 접속 주소, 포트나 DSN을 별도로 입력받거나 등록하지 않습니다. 사번, JWT, S3 Access Key와 S3 Secret Key는 이와 별개인 개인 인증값입니다. 저장된 인증정보가 있으면 바로 재사용하고, 없거나 불완전할 때만 필요한 값을 받습니다. 최초 스킬 사용이라는 이유로 설정창을 다시 열지 않습니다. 쿼리 이름과 기존 인증 설정의 별칭은 사용자 표현을 유지하며 인증정보를 대화로 요청하지 않습니다.

## 실행 명령

아래 `scripts/query.py`는 **현재 스킬 본문이 있는 폴더** 기준입니다. 플랫폼 ZIP은 본문과 함께 있는 scripts 폴더를 사용합니다. 알려진 실제 경로를 인용하고 설치 위치나 세션 ID를 찾으려고 PC 전체를 탐색하지 않습니다.

```text
python -X utf8 -B scripts/query.py start
python -X utf8 -B scripts/query.py manage
python -X utf8 -B scripts/query.py auth setup
python -X utf8 -B scripts/query.py auth import-env
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

인증 설정을 저장하는 작업과 실제 접속은 별개입니다. `start`, 목록과 관리 화면은 DB에 접속하지 않습니다. 실제 조회와 테이블 탐색은 사내 LakeHouse SDK를 사용합니다. 연결 실패 시 설정값, SDK의 예외 원문이나 인증정보를 출력하지 않습니다.

## 업무 시작과 이전 결과 정리

`start`는 새 조회 업무를 시작할 때 한 번만 실행합니다. 인증 설정과 저장 쿼리 요약을 함께 받고, 24시간이 지난 로컬 결과가 있으면 최대 10개 후보를 정리 계획으로 준비합니다. 결과 행과 인증정보는 반환하지 않습니다. 같은 업무에서 조건을 바꾸어 다시 조회하거나 저장된 결과를 분석할 때는 `start`를 반복하지 않습니다.

후보가 있을 때만 “이전 결과 3건, 8MiB를 삭제할까요, 보존할까요?”처럼 `cleanup.count`와 `cleanup.totalBytes`의 실제 계획 범위로 한 번 묻습니다. 전체 후보가 더 많더라도 이번 계획보다 많은 파일을 삭제한다고 안내하지 않습니다. 삭제를 선택하면 `cleanup.planId`의 고정된 대상에 대해 다음을 실행합니다. 사용자가 이미 같은 범위의 삭제를 지시했다면 그 지시를 사용하며 같은 허락을 재질문하지 않습니다.

```text
python -X utf8 -B scripts/query.py results cleanup --plan <cleanup.planId> --confirm
```

후보가 없거나 보존을 선택했다면 바로 조회를 계속합니다. 계획을 준비한 것만으로 삭제됐다고 말하지 않습니다. 계획에 없던 파일이나 바뀐 결과까지 삭제 범위를 넓히지 않습니다. 인증 설정과 쿼리 원본은 결과 정리 대상이 아닙니다. 후속 분석에 필요한 결과는 보존합니다.

별도로 결과를 확인하거나 사용자가 지정한 결과만 정리할 때는 다음 명령을 사용합니다. 번호는 응답의 실제 결과 ID를 사용합니다. `cleanup-plan`의 `--id`는 여러 번 지정할 수 있으며 생략하면 24시간이 지난 후보 중 최대 10개로 계획을 만듭니다. 계획 작성 후 삭제에는 실제 허락과 `--confirm`이 필요합니다.

```text
python -X utf8 -B scripts/query.py results list --limit 20
python -X utf8 -B scripts/query.py results cleanup-plan
python -X utf8 -B scripts/query.py results cleanup-plan --id <결과 ID> --id <다른 결과 ID>
```

## 인증정보와 쿼리 관리

`manage`는 인증정보와 저장 쿼리를 보여주는 로컬 웹 화면을 엽니다. 처음에는 `auth setup`으로 네 가지 인증값만 입력하며 저장이 끝나면 대화로 돌아옵니다. 인증 설정이 하나면 그 항목을 자동으로 재사용하고 테이블별 DB 추가 화면을 만들지 않습니다. `manage`는 저장 뒤에도 목록을 계속 볼 수 있고 닫기로 종료합니다. 실제 접속 확인과 저장된 설정 보기는 구분합니다.

기본 설정 화면에는 SDK가 요구하는 사번, JWT, S3 Access Key와 S3 Secret Key를 입력합니다. 인증 설정의 별칭과 운영 또는 개발 환경은 고급 설정이며 기본 별칭은 `Datalake`입니다. 별칭은 DB 이름이나 테이블 경로가 아닙니다. 발급 위치는 사용자가 제공한 [LakeHouse 개인 키 화면](https://lake.skhynix.com/myprofile/mykey)입니다. 이 문서는 해당 사내 사이트에 실제 접속해 발급이나 유효성을 확인한 기록이 아닙니다. API 주소, 클러스터 이름이나 CA 파일을 기본 인증정보 대신 요구하지 않습니다. 기존 인증정보를 수정할 때 저장된 비밀값은 비워 두어 유지할 수 있으며 없는 값만 새로 받습니다.

기존 개인 인증 설정과 저장 쿼리는 보존합니다. 새 SDK 방식에 필요한 S3 키가 기존 설정에 없으면 로컬 설정창에서 보완하며 직접 API 구현으로 자동 우회하지 않습니다. 예전에 저장한 인증 설정이 여러 개라면 사용할 계정만 한 번 확인하고 다른 계정으로 조용히 바꾸지 않습니다. 저장 쿼리를 수정할 때 인증정보를 지정하지 않으면 기존 쿼리에 연결된 계정을 유지합니다.

`auth import-env`는 사용자가 가져오기를 명시한 현재 작업 폴더의 `.env`만 읽습니다. 상위 폴더, 홈 디렉터리나 다른 프로젝트를 검색하지 않고 원본 파일도 수정하지 않습니다. 인증 설정이 하나면 같은 항목을 갱신합니다. 기존 설정이 여러 개라면 `--profile <인증 설정 ID>`로 대상 계정을 지정합니다. 이 ID는 내부 인증정보 관리용이며 조회할 DB를 고르는 값이 아닙니다. 기존 `profiles setup`과 `profiles import-env`, `manage --profile <ID>` 명령은 호환용으로 유지합니다.

원본 `.env`의 키 이름은 `LAKEHOUSE_USER_ID`, `LAKEHOUSE_TOKEN`, `LAKEHOUSE_S3_ACCESS_KEY`, `LAKEHOUSE_S3_SECRET_KEY`입니다. SDK 환경은 기본 운영(`prod`)이며 `lake_type` 설정으로 개발(`dev`)을 구분합니다. 환경과 인증정보를 추측해서 다른 서버에 연결하지 않습니다.

이미 인증정보와 저장 쿼리가 있으면 그 값을 재사용합니다. 매번 인증 목록, `queries list`, `queries show`를 모두 호출하거나 관리 화면을 열 필요가 없습니다. 목록과 상세 조회는 선택이 필요하거나 SQL과 조건 정의를 아직 모를 때만 사용합니다.

## 쿼리 등록

사용자가 준 SQL을 읽고 변수로 사용할 값과 고정할 값을 한 번 확인합니다. 모든 숫자와 문자열을 무조건 변수로 바꾸지 않습니다. 인증 설정이 하나면 등록 명세의 `profile`을 생략합니다. 예전 인증 설정이 여러 개라면 사용할 계정을 확인해 그 내부 ID를 지정합니다. 인증값 자체를 등록 명세에 넣지 않습니다.

```json
{
  "name": "생산실적조회",
  "sql": "SELECT work_date, process, quantity FROM lake_catalog.training.production_records WHERE work_date >= :start_date AND work_date < :end_date AND process = :process",
  "parameters": {
    "start_date": {"type": "date", "required": true},
    "end_date": {"type": "date", "required": true},
    "process": {"type": "text", "required": true}
  }
}
```

이는 설명용 가상 테이블 경로입니다. 운영 환경에 `lake_catalog.training.production_records`가 있다고 가정하지 않으며 실제 확인한 경로로 바꿉니다. 테이블 경로가 조회 대상을 지정하므로 DB를 별도 등록하지 않습니다. 조회 시 조건 파일은 다음처럼 만듭니다.

```json
{"start_date":"2026-10-01","end_date":"2026-11-01","process":"WB"}
```

위 예문의 종료 날짜는 `미만` 조건이므로 10월 전체입니다. 날짜 경계와 시간대를 SQL 의미에 맞게 설명합니다. 상대 날짜는 실제 날짜로 풀고 의미가 불명확할 때만 확인합니다. SDK의 `execute_pd(query=...)`에는 별도 바인드 인자가 없어 실행기가 검증한 조건을 SQL 구문 트리의 값 리터럴로 변환합니다. 직접 문자열을 이어 붙이지 않습니다. 역슬래시와 제어 문자가 들어간 값 등 지원하지 않는 조건은 조용히 바꾸지 않고 안내합니다.

## 같은 조건을 다시 묻지 않고 조회하기

사용자가 “1번을 10월 WB 공정으로 조회해줘”라고 했고 쿼리와 날짜 경계, 필수 조건이 모두 정해졌다면 그 요청을 실행 승인으로 사용합니다. 기본 행 한도는 **50,000행**이며 본 조회의 파일 용량과 시간에는 기본 제한이 없습니다. 이 기본 설정을 사용하기 위해 별도 확대 승인을 묻지 않습니다.

```text
python -X utf8 -B scripts/query.py execute --id 1 --params <조건 JSON> --confirm
```

`execute`는 계획 검증을 거쳐 일반 조회만 바로 실행합니다. 사용자가 정한 테이블 경로와 조건을 짧게 알리고 진행하며 같은 내용을 “실행할까요?”라고 다시 묻지 않습니다. 단순히 쿼리를 보여 달라는 요청이나 SQL 등록 요청을 조회 승인으로 바꾸지 않습니다. 테이블 경로나 필수 조건이 빠졌거나 의미가 모호하면 필요한 내용만 먼저 확인합니다.

응답이 `executed: false`와 `planId`를 반환하면 아직 조회 결과가 아닙니다. 큰 조회 승인이 필요하면 아래 절차를 따릅니다. `conditionsTruncated`가 참이면 사용자가 `conditionReviewFile`의 전체 조건을 로컬에서 확인한 뒤 해당 계획을 실행합니다. 큰 조회가 아니라면 `run --confirm`만 사용하며, `requiresLargeApproval`도 참일 때만 `--allow-large`를 추가합니다.

검토만 요청했거나 실행 전에 계획을 따로 보고 싶으면 `plan`을 사용합니다. 이때 확인한 계획을 `run --plan <계획 ID> --confirm`으로 실행하며 동일한 허락을 다시 묻지 않습니다.

## 계획 단계에서 실제로 하는 일

`plan`은 SQL 형태, 입력 조건과 한도를 검사합니다. 결과 건수를 미리 안다고 가정하지 않습니다. `execute`는 같은 계획 검사를 거쳐 일반 조회만 실행합니다. 전체 COUNT나 ANALYZE를 추가하거나 새 테이블 탐색을 매번 반복하지 않습니다. 큰 조회와 긴 조건의 승인을 기다리는 계획은 실제 결과와 구분합니다.

실행기는 `LakeHouse(user_id=..., token=..., s3_access_key=..., s3_secret_key=..., type='prod', spark=False)`를 생성하고 `execute_pd(query=...)`를 호출합니다. `type`에는 저장된 운영 또는 개발 환경을 사용합니다. 원본의 120초 설정을 도구의 기본 조회 제한으로 다시 적용하지 않습니다. 다만 SDK 내부의 연결 준비와 재시도, 서버의 쿼리 제한, 네트워크 자체 제한까지 해제되는 것은 아닙니다. 인증 오류나 조회 실패는 한 번 안내하고 중지합니다. 설정이나 계정을 바꾸거나 같은 실패를 반복 재시도하지 않습니다.

파일 용량을 사용자가 제한하고 싶을 때만 `plan` 또는 `execute`에 `--max-bytes <양의 정수 바이트>`를 지정합니다. 생략하면 도구의 기본 용량 제한을 두지 않습니다. 이는 저장 단계의 제한이며 SDK가 DataFrame을 반환하기 전의 수신량이나 메모리 상한을 보장하지 않습니다. 이 제한을 추가했다는 이유만으로 큰 조회 승인을 요구하지 않습니다.

조회 시간의 기본값은 제한 없음입니다. SDK의 `execute_pd`에 시간 제한이나 취소를 전달하는 계약이 확인되지 않아 운영 Datalake에서는 유한한 `--timeout`을 지원하지 않습니다. 지정하면 실행 전에 이유를 안내하며, 제한을 지키는 것처럼 실행하거나 조용히 제거하지 않습니다. 예전 계획에 유한한 시간 제한이 있다면 사용자가 지원 범위를 확인한 뒤 기본 시간 설정의 새 계획을 만들어야 합니다.

## 큰 조회를 허용하는 흐름

기본 한도보다 넓은 범위도 사용자 허락을 받으면 실행할 수 있습니다. 필요한 한도로 먼저 새 계획을 만듭니다.

```text
python -X utf8 -B scripts/query.py plan --id 1 --params <조건 JSON> --max-rows 100000
```

반환된 계획의 조회 대상, 조건, 행 한도와 주의점을 보여주고 허락을 받습니다. 기본 50,000행 확대 외에 31일을 넘는 기간, 조건 없는 범위나 결합 조건 없는 조인, 사용자 함수와 재귀 조회 등도 승인 대상이 될 수 있습니다. 이미 같은 범위와 한도를 명시적으로 허용했다면 그 지시를 재사용하되 새 주의점이나 변경된 범위를 이전 허락으로 넘기지 않습니다. 실제 허락이 있을 때만 다음을 실행합니다.

```text
python -X utf8 -B scripts/query.py run --plan <새 계획 ID> --confirm --allow-large
```

이 실행기의 최대 행 수는 1,000,000행입니다. Datalake의 본 조회에는 고정된 파일 용량과 시간 상한이 없으며 DB와 SDK의 제한은 그대로 적용됩니다. 계획은 15분 뒤 만료되고 한 번만 실행됩니다. 계획과 다른 SQL, 조건, 연결 또는 한도에는 이전 허락을 재사용하지 않습니다. 기본 한도로 실행한다는 뜻을 실제 결과가 50,000행 이하라고 확인한 것으로 설명하지 않습니다. SQL에는 초과 판정을 위한 한 행을 더한 제한을 적용하고, 행 한도에 걸리면 일부 결과로 안내합니다. SDK는 그 결과를 DataFrame으로 한 번에 메모리에 받으므로 특히 긴 컬럼이나 큰 행 한도에 주의합니다. DB의 권한과 자원 제한은 사용자 허락으로 해제되지 않습니다.

수정은 `queries register --replace-id <기존 번호>`로 같은 항목을 갱신합니다. SQL이나 조건이 달라졌다면 예전 계획을 실행하지 말고 새 계획을 만듭니다.

## 결과와 재사용

실행 응답은 결과 ID, `label`, 파일 위치, 행 수와 완전성 등 짧은 정보입니다. `label`은 쿼리 이름, 인증 설정의 별칭과 실행 시각으로 결과를 구분하는 표시 이름입니다. 별칭을 조회한 테이블이나 DB 이름으로 해석하지 않습니다. 실제 파일 위치는 반환된 `dataFile`을 사용하며 표시 이름으로 경로를 추측하지 않습니다. 원본 데이터를 Read, head, 출력문으로 대화에 쏟지 않습니다. Python에서 결과 파일을 불러 계산하고 필요한 집계만 출력합니다. 기본 결과는 한 줄에 한 행을 배열로 저장한 JSONL입니다. 열 이름은 같은 폴더의 metadata.json에 있으며 숫자와 날짜 의미를 유지합니다. CSV가 필요할 때만 export-csv로 내보냅니다. CSV는 수식처럼 보이는 문자열에 보호 표시를 붙이며 JSONL 원본은 바꾸지 않습니다. 엑셀에서 식별자의 앞자리 0을 보존할 열 형식은 별도로 지정합니다.

같은 결과에 대한 후속 분석은 저장 파일을 재사용합니다. 최신 데이터를 요청한 경우에만 다시 조회합니다. 조회 결과가 0건인 경우와 오류, 제한으로 중단된 경우를 구분합니다. 0건을 날짜 오류라고 단정하거나 임의로 다른 기간을 조회하지 않습니다. 날짜나 범위를 바꿀 필요가 있으면 원래 조건을 설명하고 변경 허락을 받습니다. 매번 미리보기 20행을 대화에 반환하지 않습니다.

## 설치 환경과 실제 검증 범위

Python 3.11 이상, `requirements.txt`의 SQL 파서, 사내 LakeHouse SDK와 로컬 관리 화면을 열 웹 브라우저가 필요합니다. 기존 Python이나 다른 환경의 설정을 초기화하지 않습니다. 공개 PyPI에서 이름이 같은 `lakes` 패키지를 설치하지 않습니다. 사내 SDK는 회사가 승인한 Nexus 공급처와 설치 명령을 사용합니다.

아래는 사용자가 제공한 사내 Nexus의 일회성 설치 명령입니다. 해당 환경에서 회사가 승인한 패키지 공급처인지 확인한 뒤 필요한 Python 환경에서만 실행합니다. `--trusted-host`는 이 명령에만 적용하며 전역 pip 설정을 바꾸지 않습니다. 이 스킬의 제작과 모의 검증에서 실제 설치한 것으로 안내하지 않습니다.

```text
python -m pip install lakes --index-url http://nexus.skhynix.com:8081/repository/pypi-group/simple --trusted-host nexus.skhynix.com
```

SDK의 `execute_pd`가 pandas DataFrame을 반환하는 계약을 사용합니다. pandas를 포함한 SDK의 실제 의존성 선언과 설치 가능한 버전은 사내 배포 메타데이터로 확인해야 하며 이 ZIP이 임의 버전을 보장하지 않습니다. `requirements.txt`에 공개 동명 `lakes`를 넣거나 SDK 전체를 복사해 배포하지 않습니다.

이 ZIP은 지침과 실행 코드입니다. 실제 DB 권한이나 사내망 접근을 제공하지 않습니다. 로컬 모의 검증으로 SDK 설치, 실제 인증, 사내 연결이나 테이블 접근 권한을 보증하지 않습니다.

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
