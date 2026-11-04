---
name: datalake-query
description: "사내 LakeHouse SDK의 인증정보를 한 번 설정하고 테이블 경로와 저장 쿼리로 데이터레이크를 조회합니다. 결과는 로컬 파일로 전달하며 큰 조회의 허용 범위를 구분합니다."
---

# Datalake 데이터 조회

사내 LakeHouse SDK로 읽기 전용 조회를 합니다. SQL의 `lake_catalog.스키마.테이블`이 대상을 정하므로 DB 주소나 DSN을 따로 등록하지 않습니다. 현재 스킬의 `scripts/query.py`를 절대경로로 실행합니다. 설치 폴더로 이동하거나 하네스와 MCP를 설치하지 않습니다.

## 기본 흐름

1. 새 조회 업무의 첫 호출에만 `start`로 저장된 연결과 쿼리를 확인합니다. 24시간 지난 결과 정리 후보가 있으면 한 번 묻고 허락한 대상만 지웁니다. 조건을 바꾸는 후속 조회에서는 반복하지 않습니다.
2. 쿼리 번호와 조건이 정해졌으면 아래 `execute` 한 번으로 새로 조회하고 CSV를 전달합니다. 사용자가 바꾸지 않은 등록 기본값은 그대로 사용합니다. 필요한 조건을 이미 알면 `queries show`를 반복하지 않으며 모르는 필수 항목만 확인합니다. 일반 조회에 별도 `plan`, 승인 질문이나 COUNT 명령을 추가하지 않습니다. 규모 확인은 실행기가 처리합니다.

```text
python -X utf8 -B "<현재 스킬 절대경로>/scripts/query.py" execute --id 1 --param process=WB
```

결과는 현재 업무 폴더의 `datalake-query/outputs/`에 자동 저장합니다. 사용자가 다른 위치를 지정했을 때만 `--output-dir`로 따릅니다. 조건 이름과 값은 실제 쿼리에 맞춥니다. PowerShell에서는 `--param "이름=공백 있는 값"`을 반복하고, 목록이나 null만 `--params <UTF-8 JSON 파일>`로 전달합니다. 조건이 없으면 생략합니다.

3. `outputFile` 링크, 조회 시각, 행 수와 완전성을 짧게 전달하고 완료합니다. `deliveryVerification: verified`는 실행기가 CSV 저장을 확인한 결과이므로 같은 파일의 존재 확인, 전체 줄 수 재계산, 별도 `session verify`를 추가하지 않습니다. 부분 결과를 전체 완료로 표시하지 않으며 오류와 정상 0건을 구분합니다. CSV 저장만 실패하면 결과 ID로 재내보내기하고 DB를 다시 조회하지 않습니다.

## 필요한 경우에만

- **SQL 등록/수정:** [등록 안내](references/interaction.md). 고정 조건 후보가 있으면 변수로 쓸 항목을 한 번 선택받고 등록합니다. 최대 10행 시험은 자동 수행하며 저장만 요청하면 `--save-only`를 사용합니다.
- **인증/목록/정리:** [관리와 예외](references/usage.md)의 해당 항목만 읽습니다. 인증값 누락 때만 `auth setup`을 실행합니다. 키 발급 위치는 [My Key](https://lake.skhynix.com/myprofile/mykey)입니다. 인증정보는 채팅 대신 지금 여는 로컬 입력창에서 받으며 기존 값은 재사용합니다.
- **승인이 필요한 경우만:** `executed: false`이면 미실행입니다. 대기 상태만 먼저 설명하고 멈추지 말고, 필요한 위험과 범위를 질문 도구로 바로 한 번 물으세요. 받은 답변의 동일 계획만 `run --plan <ID> --confirm`으로 이어가며 `requiresLargeApproval`일 때만 `--allow-large`를 추가합니다. 실제 도구 권한이나 만료된 계획의 승인을 임의로 대신하지 않습니다.
- **A 결과로 B 조회/집계/미리보기:** [Python 후속 처리](references/workflows.md). 행 전체를 대화에 읽지 않습니다. 요청한 미리보기만 기본 5행, 최대 20행과 8,000자로 제한합니다.

새 조회는 과거 결과를 임의 재사용하지 않습니다. 사용자가 지정한 결과의 후속 분석만 그 파일을 씁니다. 결과 CSV는 `datalake-query/outputs/`, 필요한 입력 명세는 `datalake-query/.work/`에 두며 인증정보와 내부 기록은 기존 개인 저장소를 유지합니다.
새 테이블을 찾아야 할 때만 [테이블 탐색](references/discovery.md)을 읽습니다.
