# SQL 등록과 수정

새 SQL을 저장하거나 기존 정의를 바꿀 때만 읽습니다. 이미 등록된 쿼리를 실행할 때는 SKILL.md의 `execute`로 바로 진행합니다.

## 명세를 만들고 한 번 등록

사용자가 준 SQL과 원하는 이름을 작은 `.query-work/register.json`에 담습니다. 연결, 테이블과 열 이름은 실제 확인한 값을 쓰고 예시를 운영 정보로 간주하지 않습니다. 임의로 기간과 조건을 채우거나 SQL에 값을 문자열로 붙이지 않습니다.

```json
{
  "name": "생산실적조회",
  "profile": "실제 등록된 연결 ID",
  "sql": "SELECT work_date, process, quantity FROM 실제_테이블 WHERE work_date >= :start_date AND work_date < :end_date AND process = :process",
  "parameters": {
    "start_date": {
      "type": "date",
      "required": true
    },
    "end_date": {
      "type": "date",
      "required": true
    },
    "process": {
      "type": "text",
      "required": true
    }
  }
}
```

위 예시는 사용자가 기간과 공정을 변수로 지정한 경우입니다. 종료일은 `미만` 경계입니다. 상대 날짜는 현재 날짜와 요청의 시간대에 맞춰 계산하며 모호할 때만 묻습니다. Datalake에서는 SQL의 테이블 경로가 대상을 정하므로 별도 DB를 등록하지 않습니다.

```text
python -X utf8 -B "<스킬 절대경로>/scripts/query.py" queries register --spec "<업무 폴더>/.query-work/register.json" --param start_date=2026-10-01 --param end_date=2026-11-01 --param process=WB
```

`--param "이름=공백 있는 값"`을 반복하면 PowerShell에서도 인용 오류를 줄일 수 있습니다. 목록이나 null 등 복잡한 값만 `--params <UTF-8 JSON 파일>`로 전달하고 두 입력 방식을 섞지 않습니다. 조건이 없으면 생략하며 빠진 필수 조건만 한 번 확인합니다. `queries review`를 등록 전에 매번 추가하지 않습니다.

## 고정 조건 후보가 반환되면

`parameter_review_required`이면 아직 저장하거나 조회하지 않았습니다. `fac_id='ICPKG'`, 날짜 등 실제 `candidates` 목록을 보여 주고 변수로 바꿀 항목과 고정할 값을 한 번 선택받습니다. 모두 고정으로 두어도 됩니다. 모든 숫자와 문자열을 무조건 변수로 만들지 않습니다.

선택한 항목만 `:변수명`과 `parameters` 정의로 바꾸고 같은 등록 명령에 `--parameters-reviewed`를 붙입니다. 이미 사용자 의사가 명확하면 재질문하지 않습니다. 이 옵션을 자동으로 붙여 선택을 생략하지 않습니다. 수정은 `--replace-id <기존 번호>`로 같은 항목을 갱신합니다.

## 시험 결과만 보고

등록은 기본적으로 최대 10행 시험을 수행합니다. 별도 실행 승인이나 중복 조회를 추가하지 않습니다. 사용자가 저장만 원하면 `--save-only`를 사용하며 시험 조건을 묻지 않습니다. 이 옵션도 고정 조건 선택까지 생략하지는 않습니다.

`registered`와 `validationStatus`를 구분합니다. 등록 성공이 실제 조회 성공은 아닙니다.

| 상태 | 의미 |
|---|---|
| `success_with_rows` | 최대 10행 시험에서 데이터가 확인됐습니다. 전체 건수와 이후 조회 성공 보장은 아닙니다. |
| `success_empty` | 지정 조건에서 정상 0건입니다. 오류가 아닙니다. |
| `approval_required` | 저장했지만 위험이나 긴 조건 확인 때문에 시험을 아직 실행하지 않았습니다. |
| `not_tested` | 저장만 했으며 실제 조회를 시험하지 않았습니다. |
| `parameters_required` | 시험에 필요한 조건이 빠졌거나 맞지 않습니다. |
| `error` | 오류 코드, 가린 이유와 실패 단계를 알려 줍니다. |
| 그 외 미확정 상태 | 입력, 결과 저장이나 제한 등 응답의 이유를 전달하며 성공으로 바꾸지 않습니다. |

응답의 `status`는 위 구분 앞에 `query_registered_`가 붙을 수 있습니다. `queryExecuted`, `resultComplete`와 `errorDetails`를 함께 봅니다. 승인 대기이면 [관리와 예외](usage.md)의 해당 계획만 허락받아 실행합니다. 저장만 하거나 실패한 경우 SQL, 계정, 날짜를 바꾸어 자동 재시도하지 않습니다.

시험 결과가 현재 요청의 범위를 `resultComplete: true`로 완전히 충족하면 그 요청의 후속 처리에 쓸 수 있습니다. 부분 시험을 전체 결과로 쓰거나 나중의 새 조회에 재사용하지 않습니다. CSV가 필요하면 해당 결과 ID로 `export-csv`를 사용합니다.

최근 시험 기록을 요청받았을 때만 `queries show --id <번호>`의 `validation`을 봅니다. `checkedAt`과 `resultId`는 저장된 시험 기록이며 새 조회가 아닙니다. `stale`은 SQL이나 조건 정의가 바뀌어 이전 시험을 현재 근거로 쓸 수 없다는 뜻입니다.
