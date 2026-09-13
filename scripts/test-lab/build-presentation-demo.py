"""Exercise the deployed Python/Office factory, not an alternate showcase engine."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.business_artifacts import create_ppt


def make_spec(data):
    if data.get('columns') != ['월', '팀', '목표_백만원', '실적_백만원', '재작업_건']:
        raise ValueError('Expected synthetic lab dataset columns.')
    months, teams = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0])
    for month, team, target, actual, rework in data['rows']:
        if any(type(v) not in (int, float) for v in (target, actual, rework)):
            raise ValueError('Expected numeric source values.')
        for group in (months[month], teams[team]):
            for i, value in enumerate((target, actual, rework)):
                group[i] += value
    m, t = sorted(months), sorted(teams)
    facts = [
        {'id': 'actual', 'label': '누적 실적', 'unit': '백만원', 'op': 'sum', 'inputs': [{'chart': [0, 1, i]} for i in range(len(m))]},
        {'id': 'target', 'label': '목표', 'op': 'sum', 'inputs': [{'chart': [0, 0, i]} for i in range(len(m))]},
        {'id': 'rate', 'label': '목표 달성률', 'unit': '%', 'op': 'ratio', 'decimals': 2, 'inputs': [{'fact': 'actual'}, {'fact': 'target'}]},
        {'id': 'excess', 'label': '목표 초과 실적', 'unit': '백만원', 'op': 'difference', 'inputs': [{'fact': 'actual'}, {'fact': 'target'}]},
        {'id': 'monthly', 'op': 'sum', 'inputs': [{'table': [1, i, 2]} for i in range(len(m))]},
        {'id': 'team', 'op': 'sum', 'inputs': [{'table': [1, len(m)+i, 2]} for i in range(len(t))]},
    ]
    for i, values in enumerate([months[name] for name in m]+[teams[name] for name in t]):
        facts.append({'id': f'rate{i}', 'op': 'ratio', 'inputs': values[:2][::-1], 'decimals': 2})
    source = '출처: 월간실적_대체자료.json · 실습용 가상 데이터 · 금액 단위: 백만원'
    return {'title': '6~8월 실적 보고', 'subtitle': '부서장 검토용 · 디자인 및 수치 수정본', 'facts': facts,
            'checks': [{'left': 'actual', 'right': 'monthly'}, {'left': 'actual', 'right': 'team'}], 'slides': [
        {'eyebrow': '실적 종합 / 2026년 6~8월', 'title': '누적 실적은 목표를 {{fact:excess}}백만원 초과',
         'takeaway': '목표 {{fact:target}}백만원 대비 {{fact:rate}}% 달성. 증가 원인은 별도 확인이 필요합니다.',
         'layout': 'summary', 'kpis': [{'fact': 'actual'}, {'fact': 'rate'}, {'fact': 'excess'}],
         'chart': {'type': 'column', 'title': '월별 목표와 실적 · 백만원', 'categories': [name[5:]+'월' for name in m],
                   'series': [{'name': '목표', 'values': [months[name][0] for name in m]}, {'name': '실적', 'values': [months[name][1] for name in m]}]},
         'body': '읽는 기준\n\n6월은 목표 미달,\n7·8월은 목표 초과.\n\n증가 추세와 원인을\n구분해 해석합니다.', 'source': source},
        {'eyebrow': '상세 근거 / 월별·팀별 비교', 'title': '월별 합계와 팀별 합계는 같은 실적입니다',
         'takeaway': '두 집계 모두 {{fact:actual}}백만원입니다. 월 합계와 팀 합계를 다시 더하지 않습니다.',
         'layout': 'evidence', 'table': {'headers': ['구분', '목표', '실적', '달성률', '재작업'], 'rows': [
             [name[5:]+'월' if name in months else name.replace('가상 ', ''), *values[:2], '{{fact:rate'+str(i)+'}}%', str(values[2])+'건']
             for i, (name, values) in enumerate([(name, months[name]) for name in m]+[(name, teams[name]) for name in t])]},
         'body': '재작업 추이\n\n월별 11 → 8 → 6건.\n\n건수 감소는 확인되지만\n품질·비용 개선 효과는\n추가 근거가 필요합니다.', 'source': source},
        {'eyebrow': '후속 확인 / 사실과 가설 구분', 'title': '원인·담당자·일정은 확인 후 확정합니다',
         'takeaway': '아래 항목은 기존 보고서의 확인 과제입니다. 이번 재집계로 원인까지 검증한 것은 아닙니다.',
         'layout': 'actions', 'table': {'headers': ['확인 항목', '다음에 확인할 내용', '현재 상태'], 'rows': [
             ['A팀 8월 실적', '증가 원인을 뒷받침할 근거', '확인 필요'],
             ['B팀 절차 변경', '실적 변화와 인과관계', '확인 필요'],
             ['후속 점검', '담당자와 완료 기한', '미정'],
             ['다음 보고', '회의 일정 확정 여부', '미정'],
             ['재작업 감소', '품질·비용 효과의 측정 기준', '확인 필요']]},
         'source': '확인 과제: 기존 PPT의 후속 항목 보존 · 원인·담당자·기한을 임의로 채우지 않음'}]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--office-only', action='store_true', help='Exercise the packaged no-python-pptx branch.')
    args = parser.parse_args()
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.data, args.template)}
    spec = make_spec(json.loads(args.data.read_text(encoding='utf-8-sig')))
    if args.office_only:
        from unittest.mock import patch
        with patch('company_agent.business_artifacts.importlib.util.find_spec', return_value=None):
            result = create_ppt(spec, args.output, args.template)
    else:
        result = create_ppt(spec, args.output, args.template)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in before.items())
    print(json.dumps({**result, 'inputHashes': before}, ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 1)
