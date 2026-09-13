"""Rebuild the supplied synthetic report through the production HTML factory.

Reads only the specified JSON dataset; creates a new report, never replaces the
old report, source spreadsheet, personal state or installed Company Agent.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.business_artifacts import create_html


def make_spec(data):
    if data.get('columns') != ['월', '팀', '목표_백만원', '실적_백만원', '재작업_건']:
        raise ValueError('Expected the synthetic lab dataset column contract.')
    rows = data['rows']
    if not rows or any(len(row) != 5 or any(type(v) not in (int, float) for v in row[2:]) for row in rows):
        raise ValueError('Invalid synthetic dataset rows.')
    months, teams = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0])
    for month, team, target, actual, rework in rows:
        for group in (months[month], teams[team]):
            for i, value in enumerate((target, actual, rework)):
                group[i] += value
    month_names, team_names = sorted(months), sorted(teams)
    source = '출처: 월간실적_대체자료.json (실습용 가상 데이터). XLSX와 중복 합산하지 않음. 금액: 백만원.'
    facts = [
        {'id': 'target', 'label': '누적 목표', 'unit': '백만원', 'op': 'sum', 'inputs': [{'table': [4, i, 2]} for i in range(len(rows))]},
        {'id': 'actual', 'label': '누적 실적', 'unit': '백만원', 'op': 'sum', 'inputs': [{'table': [4, i, 3]} for i in range(len(rows))]},
        {'id': 'rework', 'label': '재작업 합계', 'unit': '건', 'op': 'sum', 'inputs': [{'table': [4, i, 4]} for i in range(len(rows))]},
        {'id': 'rate', 'label': '목표 달성률', 'unit': '%', 'op': 'ratio', 'decimals': 2, 'inputs': [{'fact': 'actual'}, {'fact': 'target'}]},
        {'id': 'excess', 'label': '목표 초과 실적', 'unit': '백만원', 'op': 'difference', 'inputs': [{'fact': 'actual'}, {'fact': 'target'}]},
        {'id': 'monthly', 'op': 'sum', 'inputs': [{'chart': [1, 1, i]} for i in range(len(months))]},
        {'id': 'team_total', 'op': 'sum', 'inputs': [{'chart': [2, 1, i]} for i in range(len(teams))]},
        {'id': 'monthly_target', 'op': 'sum', 'inputs': [{'chart': [1, 0, i]} for i in range(len(months))]},
        {'id': 'team_target', 'op': 'sum', 'inputs': [{'chart': [2, 0, i]} for i in range(len(teams))]},
        {'id': 'detail_total', 'op': 'sum', 'inputs': [{'table': [3, i, 2]} for i in range(len(months))]},
        {'id': 'detail_target', 'op': 'sum', 'inputs': [{'table': [3, i, 1]} for i in range(len(months))]},
        {'id': 'detail_rework', 'op': 'sum', 'inputs': [{'table': [3, i, 4]} for i in range(len(months))]},
    ]
    for i in range(len(months)):
        facts.append({'id': f'month_rate_{i}', 'op': 'ratio', 'decimals': 2,
                      'inputs': [{'chart': [1, 1, i]}, {'chart': [1, 0, i]}]})
    for i, team in enumerate(team_names):
        facts.append({'id': f'team_rate_{i}', 'label': team+' 달성률', 'unit': '%', 'op': 'ratio', 'decimals': 2,
                      'inputs': [{'chart': [2, 1, i]}, {'chart': [2, 0, i]}]})
    if len(months) < 2:
        raise ValueError('This comparison example requires two months.')
    facts.append({'id': 'growth', 'label': '최근 월 전월 대비', 'unit': '%', 'op': 'percent_change', 'decimals': 2,
                  'inputs': [{'chart': [1, 1, len(months)-1]}, {'chart': [1, 1, len(months)-2]}]})
    return {'title': '월간 실적 보고 · 부서장 검토용', 'subtitle': f'{month_names[0]} — {month_names[-1]} | 실습용 가상 데이터 | 디자인·수치 수정본',
            'style': 'minimal', 'mode': 'slides', 'length': 'standard', 'facts': facts,
            'checks': [{'left': 'actual', 'right': name} for name in ('monthly', 'team_total', 'detail_total')]+
                      [{'left': 'target', 'right': name} for name in ('monthly_target', 'team_target', 'detail_target')]+
                      [{'left': 'rework', 'right': 'detail_rework'}], 'sections': [
                {'layout': 'cover', 'eyebrow': '실적 종합 / 의사결정을 위한 한눈 보기',
                 'title': '누적 실적과 목표 달성 현황',
                 'takeaway': '실적 {{fact:actual}}백만원, 목표 {{fact:target}}백만원 대비 {{fact:rate}}%. 증가 원인은 실적 수치와 구분해 확인합니다.',
                 'kpis': [{'fact': 'actual', 'note': '전체 월·팀의 실적 합계'}, {'fact': 'rate', 'note': '전체 실적 ÷ 전체 목표'}, {'fact': 'excess', 'note': '실적에서 목표를 뺀 금액'}],
                 'body': '재작업 건수는 별도의 참고 지표이며 실적 금액에서 차감하지 않았습니다.\n이 보고서는 회사의 실제 경영 실적이 아닌 실습용 자료입니다.', 'source': source},
                {'layout': 'split', 'eyebrow': '월별 변화', 'title': '월별 실적을 목표와 나란히 비교',
                 'takeaway': '최근 월의 전월 대비 변화율은 {{fact:growth}}%입니다.',
                 'body': '금액의 변화와 달성률을 함께 확인하세요.\n실적이 증가했다는 사실만으로 특정 조치의 효과라고 단정하지 않습니다.',
                 'chart': {'type': 'column', 'title': '월별 목표와 실적 · 백만원', 'categories': month_names,
                           'series': [{'name': '목표', 'values': [months[m][0] for m in month_names]}, {'name': '실적', 'values': [months[m][1] for m in month_names]}]}, 'source': source},
                {'layout': 'dashboard', 'eyebrow': '팀별 비교', 'title': '팀별 기여 금액과 달성률을 함께 확인',
                 'takeaway': '팀마다 목표 규모가 다르므로 금액과 비율을 구분해서 읽습니다.',
                 'kpis': [{'fact': f'team_rate_{i}'} for i in range(min(len(teams), 6))],
                 'chart': {'type': 'bar', 'title': '팀별 누적 목표와 실적 · 백만원', 'categories': team_names,
                           'series': [{'name': '목표', 'values': [teams[t][0] for t in team_names]}, {'name': '실적', 'values': [teams[t][1] for t in team_names]}]}, 'source': source},
                {'layout': 'table', 'eyebrow': '상세 수치 / 월별 합계', 'title': '월별 실적과 재작업을 분리해서 관리',
                 'takeaway': '누적 실적 {{fact:actual}}백만원 · 재작업 {{fact:rework}}건',
                 'table': {'headers': ['월', '목표(백만원)', '실적(백만원)', '달성률', '재작업(건)'],
                           'rows': [[m, months[m][0], months[m][1], '{{fact:month_rate_'+str(i)+'}}%', months[m][2]] for i, m in enumerate(month_names)]}, 'source': source},
                {'layout': 'table', 'eyebrow': '근거 자료 / 팀별 원자료', 'title': '집계에 사용한 데이터',
                 'table': {'headers': ['월', '팀', '목표(백만원)', '실적(백만원)', '재작업(건)'], 'rows': rows},
                 'source': source},
                {'layout': 'summary', 'eyebrow': '후속 확인', 'title': '숫자로 확인한 사실과 원인을 구분합니다',
                 'takeaway': '이 수정본은 실적 데이터의 집계와 디자인을 바로잡았습니다. 원인 분석은 별도 근거가 필요합니다.',
                 'bullets': ['확인 필요: 실적 변화의 구체적 원인과 절차 변경의 효과.',
                             '확인 필요: 후속 점검의 담당자·기한·다음 보고 일정.',
                             '제안: 재작업을 실적 금액과 분리된 품질 지표로 검토.',
                             '기존 보고서와 실적요약.md는 비교를 위해 그대로 보존했습니다. 기존 요약의 총계는 재사용하지 않았습니다.'],
                 'source': '수정본의 수치 출처는 가상 JSON 데이터입니다. 회의메모의 원인·담당자·기한은 이 생성 과정에서 새로 검증하지 않았습니다.'}
            ]}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    before=hashlib.sha256(args.data.read_bytes()).hexdigest()
    spec=make_spec(json.loads(args.data.read_text(encoding='utf-8-sig')))
    result=create_html(spec,args.output)
    assert hashlib.sha256(args.data.read_bytes()).hexdigest()==before
    print(json.dumps({**result, 'sourceSha256':before},ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 1)
