# Excel DATA / PROCESS 프로젝트 검증

검증일: 2026-10-18. 독립 스킬과 하네스 배포용 스킬에 같은 생성기를 반영했습니다. 배포본 검증은 `VALIDATION_RELEASE_1.4.43.md`에 별도로 기록합니다.

## 사용자에게 달라지는 점

- `main.py`로 실행하며 입력은 `DATA`, 계산과 추가 업무 처리는 `PROCESS`, 실행 결과는 `outputs`로 구분합니다.
- `DATA/sources.py`에서 파일 위치를, `DATA/load.py`에서 Python·JSON 등 다른 자료를 읽는 방법을 바꿉니다.
- `PROCESS/pipeline.py`는 저장한 수식을 Python 계산기로 실행합니다. `PROCESS/table_steps.py`에는 표별 추가 처리 위치와 원래 수식의 의미를 한국어로 안내합니다.
- 사용자 편집 대상 Python에는 역할·입출력·수정할 곳·주의사항을 쉬운 한국어 주석으로 설명합니다. 세부 사용법은 생성된 `README.md`에 있습니다.
- 일반 파일 직접 읽기, 필요한 파일만 xlwings 읽기, 원본 보존, 대소문자 보존, 요약 크기 제한을 유지합니다. 새 후크나 모델 호출을 추가하지 않았습니다.

## 실제 재사용 시험

예제 프로젝트: `outputs/excel-data-process-20261018`. 상세 증거: 그 안의 `reuse-verification.json`.

내장 VBA가 있는 가상 XLSM(12개 시트, 16개 표, 6,798개 수식)을 분석한 뒤 생성된 `main.py`를 별도 프로세스로 실행했습니다.

1. 원래 Excel 입력의 모든 수식 값·오류 상태를 최초 분석과 대조했습니다.
2. `DATA/load.py`만 Python·JSON 입력으로 교체하고 `DATA/external_values.json`을 추가했습니다.
3. 수량 한 값을 1에서 2로 바꿨습니다. `수식처리!J7`은 211,386에서 422,773으로 바뀌었으며, 독립 계산한 기대값과 일치했습니다.
4. `PROCESS` 파일 전체의 SHA-256이 그대로였으며 원본 XLSM도 변경되지 않았습니다.

계산 성공 6,790개, 미지원 4개, 오류 4개를 구분했습니다. 미지원·오류를 성공이나 0으로 바꾸지 않았습니다. 이 시험은 VBA를 실행하거나 자동 이전한 시험이 아닙니다. 모델 호출은 0회입니다.

## 자동 테스트

- 독립 스킬 회귀 테스트: 225개 통과.
- 하네스 연동 테스트: 14개 통과. 배포용 사본에서 생성한 `main.py` 실행 포함.
- 두 스킬의 형식 검사와 원본/배포용 런타임 동기화 검사 통과.
- 통합 HTML 안내서는 Chrome에서 1440·768·390px 폭으로 검사했습니다. 45개 화면, 내부 링크 147개, 오프라인 Noto Sans KR, 인쇄·예문 선택을 확인했으며 글자 깨짐·가로 넘침·외부 요청·페이지 오류는 없었습니다.
  검사 결과 JSON 출력 뒤 Chrome 종료 대기가 끝나지 않아 검사 프로세스를 중단했습니다. 화면 검사 결과와 별개로 실행기의 정상 종료까지 통과했다고 기록하지 않습니다.
- 추가 시험: 다른 작업 폴더에서 실행, 한국어 경로, 입력 열·타입·헤더 불일치, 기존 출력 덮어쓰기 방지, 문자열 `=` 보존, 빈 값과 0 구분, 행·수식 변경 감지, JSON 입력 중 Excel 열기 금지.

## 한계와 해석

- 현재 재사용 계약은 같은 행·열 배치와 수식 구조입니다. 행 증가·열 이동·수식 변경은 변경 부분을 재검토해야 합니다. 기존 `transform.py`의 구조 재분석은 고정된 PROCESS를 그대로 쓰는 것과 다릅니다.
- 모든 Excel 수식을 개별 업무용 pandas 코드로 자동 번역하지는 않습니다. 저장한 수식 규칙을 Python 계산기로 재실행하고, 별도 업무 정제는 표별 Python 함수에 추가합니다.
- VBA 원문 추출과 업무 코드 이전은 별개입니다. VBA 이전은 원문과 업무 의미 검토 후 PROCESS에 구현하고 따로 비교합니다.
- 사내 DRM 실제 파일과 원본 VBA 실행은 이번 시험에서 수행하지 않았습니다. 기존 xlwings 경로의 회귀 테스트 통과를 운영환경 성공으로 확대하지 않습니다.
- 일반 실행에 새 LLM 검증 단계는 없습니다. 입력 계약 검사는 로컬 Python으로 수행하므로 비용이 0인 것은 아니며, 운영환경의 전체 경과·토큰은 별도 측정 대상입니다.

재현 명령:

```text
python -X utf8 -m unittest discover -s standalone-skills/excel-to-pipeline/tests -p "test_*.py" -q
python -X utf8 -m unittest discover -s tests -p test_excel_pipeline_integration.py -q
python -X utf8 standalone-skills/excel-to-pipeline/tests/verify_data_process_project.py --output outputs/새-검증-폴더
python -X utf8 scripts/sync-excel-pipeline-skill.py --check
```
