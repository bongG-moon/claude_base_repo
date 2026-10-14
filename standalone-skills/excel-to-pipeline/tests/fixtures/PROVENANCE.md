# 재현 가능한 가상 Excel 시험 자료

이 폴더는 실제 회사 자료가 아닌 가상 교육 신청·정산 자료입니다. Git에서 받은
소스만으로 테스트할 수 있도록 이전에 작성하고 검증한 파일을 바이트 그대로 보관합니다.
개인 PC의 `outputs` 폴더, Excel 설치, 모델 연결, 네트워크는 단위 시험에 필요하지 않습니다.

- `complex_workbook.xlsx`, `variant_next_month.xlsx`, `ambiguous_cases.xlsx`:
  `../build_fixtures.mjs`와 같은 폴더의 생성·검사 코드로 만든 기본 시험 자료입니다.
  기대값과 작성 방식은 `../fixtures-manifest.json`에 있습니다.
- `고급_수식매크로_혼합.xlsx`, `매크로전용_입력.xlsx`:
  `../build_advanced_fixtures.mjs`로 만든 가상 업무입니다. 원래 업무 규칙의 독립 기대값은
  `../advanced-manifest.json`, 사용자 요청으로 변경한 대소문자 보존 규칙의 독립 보정은
  `../test_case_preserving_controls.py`에 있습니다.
- `고급_내장VBA_혼합.xlsm`: 위 고급 XLSX에 검토한 교육용 VBA 3개 모듈과 결과 반환용
  시험 모듈을 `../build_embedded_fixture.py`로 내장한 파일입니다. 자동 실행 진입점은
  없습니다. pyOpenVBA 6.5.0(MIT)로 작성했고 관련 고지는 `pyOpenVBA-LICENSE.md`입니다.
  원문 계약과 예제의 VBA는 `../../examples/macro-migration`에 있습니다.

원본 매크로의 `CodeOf/UCase`는 과거 원문 증거로 그대로 보존합니다. 현재 Python
예제는 사용자 요청에 따라 대소문자를 바꾸지 않으므로 원본 VBA와 의미가 다릅니다.
이 원문이나 기대값을 현재 Python에 맞춰 조용히 변경하지 않습니다.

## 단위 시험

Python 3.10 이상에서 스킬의 `requirements-vba.txt`를 준비한 뒤 저장소 루트에서:

```text
python -X utf8 -m unittest discover -s standalone-skills/excel-to-pipeline/tests -p "test_*.py" -v
```

이 명령은 Excel을 실행하거나 VBA를 실행하지 않습니다. 실제 Excel 경로를 확인하는
`verify_xlwings_trial.py`는 사용자가 별도로 요청한 Windows 시험에서만 실행합니다.
직원용 하네스 ZIP에는 이 시험 자료·시험 코드·예제 VBA를 포함할 필요가 없습니다.

## SHA-256

| 파일 | SHA-256 |
|---|---|
| complex_workbook.xlsx | 8f41ca309228faaf9f9522913c7c0bec11b8be0c0ce316a58ed76d54ab750d0f |
| variant_next_month.xlsx | 75148e835cc12d9f1692ee3149400b7007fab09e0d1cc4b33fe67645f14a7ea5 |
| ambiguous_cases.xlsx | 47baebb81d4a5a8708d363944e4f0afee06ac9b955030ad44e058ed41420c822 |
| 고급_수식매크로_혼합.xlsx | 6fb091b4a6af124983b4842afa846b3203a0a59fd4ac51f4d1305908a5fedd97 |
| 매크로전용_입력.xlsx | a3d9922c7fd9afb40ee2cb7119621fc167f720857b2776a294ddef4f3099465f |
| 고급_내장VBA_혼합.xlsm | 34e03d7bcc1db17e83d448c156449d8ff34c11ad5190edf69ca4c17a2298901c |
| ../advanced-manifest.json | c5e8783c0d4378eb4972c2f79eb7881eab8b130c0b2d72a164af43423884248a |
