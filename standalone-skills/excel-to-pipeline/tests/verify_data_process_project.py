"""One opt-in, synthetic XLSM demonstration; no Office/VBA/model invocation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish, write_json
from project_builder import make_rules
from project_runtime import read_excel_data


def hashes(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    source = SKILL / 'tests/fixtures/고급_내장VBA_혼합.xlsm'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    analysis = analyze(source)
    publish(analysis, output)
    process_before = hashes(output / 'PROCESS')
    command = [sys.executable, '-X', 'utf8', '-B', str(output / 'main.py'), '--output']
    first = subprocess.run(command + [str(output / 'outputs/01-excel')], cwd=output.parent,
                           capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert first.returncode == 0, first.stderr
    baseline = json.loads((output / 'outputs/01-excel/formulas.json').read_text(encoding='utf-8'))
    assert {(f['sheet'], f['cell']): (f['value'], f['status']) for f in baseline} == {
        (f['sheet'], f['cell']): (f['value'], f['status']) for f in analysis['formulas']}
    data = read_excel_data(source, make_rules(analysis))
    data['cells']['신청원본!G7'] = 2  # original quantity 1; change only the data source
    data['source_name'] = '다른 Python에서 제공한 가상 자료'
    for name in ('input_evidence', 'sha256', 'source_unchanged'):
        data.pop(name, None)
    write_json(output / 'DATA/external_values.json', data)
    (output / 'DATA/load.py').write_text(
        '"""Excel 대신 다른 Python에서 전달한 자료를 읽는 검증 예제입니다."""\n'
        'import json\nfrom pathlib import Path\n\n'
        'def load_data():\n'
        '    # 외부 Python의 함수 호출 또는 승인된 DB 조회를 연결할 위치입니다.\n'
        '    # 이 예제는 로그인이나 서버 연결 없이 가상 JSON 자료를 읽습니다.\n'
        '    # cells의 키와 자료형을 유지하면 PROCESS는 바꾸지 않아도 됩니다.\n'
        '    return json.loads(Path(__file__).with_name("external_values.json").read_text(encoding="utf-8"))\n',
        encoding='utf-8')
    second = subprocess.run(command + [str(output / 'outputs/02-python-source')], cwd=output.parent,
                            capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert second.returncode == 0, second.stderr
    changed = json.loads((output / 'outputs/02-python-source/formulas.json').read_text(encoding='utf-8'))
    amount = lambda items: next(f['value'] for f in items if f['sheet'] == '수식처리' and f['cell'] == 'J7')
    # Independent arithmetic: C08 price 222512 × quantity 2 × 95%, rounded to whole units.
    assert amount(baseline) == 211386
    assert amount(changed) == 422773
    assert process_before == hashes(output / 'PROCESS')
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    for folder in ('01-excel', '02-python-source'):
        assert len((output / 'outputs' / folder / 'model_context.json').read_text(encoding='utf-8')) <= 12000
    report = {'status': 'passed', 'source_sha256': source_hash, 'source_unchanged': True,
              'sheets': analysis['summary']['sheet_count'], 'tables': analysis['summary']['table_count'],
              'formulas': len(baseline), 'formula_status': analysis['summary']['formula_status'],
              'baseline_matches_all_original_formula_values_and_statuses': True,
              'changed_only': ['DATA/load.py', 'DATA/external_values.json'],
              'process_unchanged': True, 'process_sha256': process_before,
              'control': {'cell': '수식처리!J7', 'before': amount(baseline), 'after': amount(changed),
                          'expected_after': 422773}, 'macros_executed': False, 'model_calls': 0}
    write_json(output / 'reuse-verification.json', report)
    with (output / 'README.md').open('a', encoding='utf-8') as stream:
        stream.write('\n## 이 검증 예제의 현재 상태\n\n'
                     '12개 시트·16개 표·6,798개 수식의 가상 XLSM으로 만들었습니다.\n'
                     '현재 DATA/load.py는 Excel 대신 DATA/external_values.json을 읽습니다.\n'
                     'main.py를 실행하면 이 Python/JSON 입력으로 기존 PROCESS를 실행합니다.\n'
                     '첫 실행은 outputs/01-excel, DATA만 교체한 결과는 outputs/02-python-source입니다.\n'
                     '수량 1→2 변경으로 수식처리!J7은 211,386→422,773으로 바뀌었습니다.\n'
                     'PROCESS 해시와 원본 해시는 그대로입니다. 자세한 증거는 reuse-verification.json입니다.\n'
                     'VBA는 실행하거나 자동 이전하지 않았으며, 기존 미지원 수식 4개·오류 4개는 남겨 표시했습니다.\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
