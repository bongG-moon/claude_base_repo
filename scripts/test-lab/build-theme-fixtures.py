"""Fresh synthetic reports for design QA. Never reads user business files."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.business_artifacts import create_html
from company_agent.report_styles import STYLES, picker_html
from company_agent.html_reference import inspect_template


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    chart = {'title': '월별 실적 · 가상 자료', 'type': 'column', 'categories': ['6월', '7월', '8월'],
             'series': [{'name': '실적', 'values': [145, 175, 210]}]}
    spec = {'title': '사업 운영 현황', 'subtitle': '디자인 검토용 가상 자료 · 실제 회사 실적 아님',
            'length': 'standard', 'mode': 'both',
            'facts': [{'id': 'actual', 'label': '누적 실적', 'unit': '백만원', 'op': 'sum',
                       'inputs': [{'table': [2, i, 1]} for i in range(3)], 'expected': 530},
                      {'id': 'target', 'label': '누적 목표', 'unit': '백만원', 'op': 'sum',
                       'inputs': [{'table': [2, i, 2]} for i in range(3)], 'expected': 450}],
            'sections': [
                {'title': '실적은 증가했고, 다음 달 대응을 준비합니다', 'layout': 'cover',
                 'eyebrow': '월간 운영 보고', 'takeaway': '목표와 실적을 같은 기준으로 비교합니다.',
                 'body': '수치와 설명은 모든 디자인에서 같습니다. 색상뿐 아니라 표면의 질감, 여백과 배치를 비교해 주세요.',
                 'kpis': [{'fact': 'actual'}, {'fact': 'target'}], 'source': '화면 검토를 위해 만든 예시 데이터'},
                {'title': '6월 이후 실적이 증가했습니다', 'layout': 'split', 'chart': chart,
                 'body': '6월 145백만원에서 8월 210백만원으로 증가했습니다. 증가 원인은 이 자료만으로 판단하지 않습니다.'},
                {'title': '월별 목표와 실적', 'layout': 'table',
                 'table': {'headers': ['월', '실적(백만원)', '목표(백만원)'],
                           'rows': [['6월', 145, 150], ['7월', 175, 150], ['8월', 210, 150]]}},
                {'title': '확인할 사항', 'layout': 'summary', 'body': '다음 달 공급 일정과 실제 수요를 확인합니다.'},
                {'title': '자료의 범위', 'layout': 'summary', 'body': '이 보고서는 디자인 검토용입니다. 회사 자료는 포함하지 않습니다.'}]}
    results = []
    for key, *_ in STYLES:
        result = create_html({**spec, 'style': key}, output / f'{key}.html', require_choices=True)
        if not result['ok']:
            raise RuntimeError(result)
        results.append(result)
    (output / 'picker.html').write_text(picker_html(), encoding='utf-8')
    reference = output / 'reference.html'
    reference.write_text('<!doctype html><html><head><style>:root{--paper:#ffeedd;--accent:#763314;--section-radius:9px}</style></head><body><h1>검토용 양식</h1></body></html>', encoding='utf-8')
    selected = inspect_template(reference)['htmlTemplate']
    result = create_html({**spec, 'style': 'glassmorphism', 'htmlTemplate': selected}, output / 'reference-report.html', require_choices=True)
    if not result['ok']:
        raise RuntimeError(result)
    (output / 'fixtures.json').write_text(json.dumps({'styles': [x[0] for x in STYLES], 'generated': len(results)}, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output.resolve())
