"""Synthetic reference specimens, made by the same renderer as delivered reports.

업무 원문이나 원격 자료를 포함하지 않습니다. 예제 생성은 제작/배포 때만 사용합니다.
"""
from __future__ import annotations
import copy


def style_example_spec(style: str) -> dict:
    """열 가지 양식을 같은 수치와 충분한 본문으로 비교합니다."""
    from .report_styles import STYLES
    if style not in {row[0] for row in STYLES}:
        raise ValueError('등록된 디자인을 선택해 주세요.')
    source = '디자인 비교용 가상 자료. 실적과 과제 목록은 서로 다른 관리 지표입니다.'
    rows = []
    for i in range(48):
        status = '완료' if i < 30 else '검토 중' if i < 42 else '지연'
        rows.append([f'TASK-{i+1:03d}', ['운영', '품질', '지원'][i % 3],
                     ['입력 기준 정리', '집계 항목 확인', '예외 처리 검토', '담당자 인계'][i % 4],
                     status, f'2026-08-{i % 28 + 1:02d}',
                     '근거 확인 완료' if status == '완료' else '원자료와 판단 근거를 확인한 뒤 담당자가 상태를 확정합니다.'])
    return {'title': '월간 운영 리뷰', 'subtitle': '2026년 6–8월 / 디자인 비교용 가상 자료',
            'style': style, 'length': 'detailed', 'mode': 'both', 'fontChoice': 'auto', 'motion': 'subtle',
            'facts': [{'id': 'actual', 'label': '누적 실적', 'unit': '백만원', 'op': 'sum', 'inputs': [145, 175, 210], 'decimals': 0},
                      {'id': 'achievement', 'label': '목표 달성률', 'unit': '%', 'op': 'ratio', 'inputs': [530, 450], 'decimals': 2},
                      {'id': 'open', 'label': '미완료 과제', 'unit': '건', 'op': 'sum', 'inputs': [12, 6], 'decimals': 0}],
            'sections': [
                {'title': '성장한 실적,\n다음은 실행의 완결성', 'layout': 'cover', 'eyebrow': '01 / 이번 달 판단',
                 'takeaway': '목표는 넘었지만, 남은 과제의 완료 조건을 확인해야 합니다.',
                 'body': '매출 실적과 운영 과제를 구분해 봅니다. 실적은 세 달 합계이며, 미완료 과제는 8월 말 기준입니다. 서로 다른 단위의 수치를 한 성과로 합산하지 않습니다.',
                 'kpis': [{'fact': 'actual', 'note': '6–8월 합계 / 목표 450백만원'},
                          {'fact': 'achievement', 'note': '530 ÷ 450 × 100'},
                          {'fact': 'open', 'note': '검토 중 12건 + 지연 6건'}], 'source': source},
                {'title': '실적은 세 달 모두 목표를 넘었습니다', 'layout': 'split', 'eyebrow': '02 / 변화의 근거',
                 'body': '8월 실적은 210백만원으로 목표 180백만원보다 30백만원 높습니다. 단기 상승을 지속적인 추세로 단정하지 않고 다음 기간에 같은 기준으로 비교합니다.',
                 'chart': {'type': 'column', 'title': '월별 목표와 실적 / 백만원', 'categories': ['6월', '7월', '8월'],
                           'series': [{'name': '목표', 'values': [120, 150, 180]}, {'name': '실적', 'values': [145, 175, 210]}]},
                 'source': source},
                {'title': '확인할 대상을 먼저 좁힙니다', 'layout': 'summary', 'eyebrow': '03 / 판단 기준',
                 'body': '전체 48건 중 완료는 30건입니다. 미완료 18건의 원인과 다음 조치를 먼저 확인합니다.',
                 'bullets': ['검토 중: 증빙이나 담당자 판단이 남은 12건', '지연: 계획일을 넘겨 일정 재합의가 필요한 6건',
                             '완료: 근거가 확인된 30건. 재검토할 변경이 없으면 그대로 유지'], 'source': source},
                {'title': '담당자가 다음 행동을 고를 수 있게', 'layout': 'summary', 'eyebrow': '04 / 실행 순서',
                 'scenarios': {'title': '상태별 처리 방법', 'items': [
                     {'label': '검토 중', 'input': '확인할 증빙이 남아 있는 과제', 'steps': ['원자료와 판단 기준을 함께 확인합니다.', '담당자가 완료 여부를 확정합니다.'], 'output': '판단 근거와 확정된 상태'},
                     {'label': '지연', 'input': '계획일을 넘긴 과제', 'steps': ['지연 원인과 의존 작업을 확인합니다.', '새 일정과 책임자를 정합니다.'], 'output': '합의한 일정과 다음 확인일'},
                     {'label': '완료', 'input': '근거가 확인된 과제', 'steps': ['기존 결과와 확인 일자를 유지합니다.', '조건이 바뀐 경우에만 재검토합니다.'], 'output': '재사용 가능한 작업 기록'}]}, 'source': source},
                {'title': '근거 자료에서 필요한 기록만 찾으세요', 'layout': 'table', 'eyebrow': '05 / 상세 목록',
                 'body': '전체 48건입니다. 검색, 정렬과 페이지 이동으로 확인하고, 전체 자료와 현재 검색 결과를 구분해 CSV로 내려받을 수 있습니다. 상단 지표는 검색 여부와 관계없이 전체 기준입니다.',
                 'table': {'headers': ['과제 ID', '담당', '작업', '상태', '확인일', '다음 조치'], 'rows': rows,
                           'columnTypes': ['id', 'text', 'text', 'text', 'date', 'text']}, 'source': source},
                {'title': '다음 회의에서는 세 가지만 결정합니다', 'layout': 'summary', 'eyebrow': '06 / 결정 사항',
                 'takeaway': '판단 근거, 담당자, 다음 확인일을 한 기록으로 남깁니다.',
                 'bullets': ['검토 중 12건을 확정할 담당자와 필요한 증빙', '지연 6건의 변경 일정과 의존 작업', '다음 비교에서도 유지할 지표와 집계 기준'],
                 'details': [{'title': '이 예제의 범위와 읽는 방법', 'body': '모든 디자인은 같은 가상 자료를 사용합니다. 참고 사이트의 코드, 로고나 이미지를 복제하지 않았습니다. 실제 업무에서는 첨부 양식과 지정한 글꼴, 분량을 우선합니다.'}], 'source': source}]}


def style_preview_markup(style: str) -> str:
    """동일 예제의 첫 구획을 같은 수치 계산기와 렌더러로 보여줍니다."""
    from . import business_artifacts as artifacts, report_design
    from .report_facts import resolve
    spec = style_example_spec(style)
    spec['fontSource'] = 'system'
    spec['mode'] = 'scroll'
    data = artifacts._normalize(spec, html_tables=True)
    facts, _ = resolve(spec, data['sections'])
    raw = spec['sections'][0]
    row = data['sections'][0]
    row.update({field: raw[field] for field in ('layout', 'eyebrow', 'takeaway', 'source')})
    row['kpis'] = [{**{key: facts[kpi['fact']][key] for key in ('label', 'display', 'unit')}, 'note': kpi['note']}
                   for kpi in raw['kpis']]
    data['sections'] = [row]
    document = report_design.render(data, '', '', artifacts._html_table)
    masthead = document.split('<header class="report-masthead">', 1)[1].split('</header>', 1)[0]
    # 미리보기에는 실행 버튼을 넣지 않습니다. 선택과 완성 예제 링크는 카드 바깥의 실제 조작입니다.
    masthead = masthead.split('<nav', 1)[0]
    main = document.split('<main class="report-main">', 1)[1].split('</main>', 1)[0]
    main = main.replace('01 / 01 ·', f'01 / {len(spec["sections"]):02d} ·', 1)
    return '<header class="report-masthead">' + masthead + '</header><main class="report-main">' + main + '</main>'


def example_spec(key: str) -> dict:
    """세 구성의 차이를 볼 수 있는 가상 교육 운영 자료를 반환합니다."""
    if key not in ('reference-1', 'reference-2', 'reference-3'):
        raise ValueError('Unknown report reference')
    source = '양식 확인을 위해 만든 가상 자료입니다. 실제 운영 실적이나 개선 효과가 아닙니다.'
    common = {'title': '교육 운영 검토', 'subtitle': '양식 완성 예제 / 모든 수치는 가상 자료',
              'referencePreset': key, 'length': 'standard', 'mode': 'scroll',
              'fontChoice': 'auto', 'motion': 'subtle'}
    trend = {'type': 'column', 'title': '수료 판정이 필요한 상황 / 가상 건수',
             'categories': ['조건 충족', '보완 필요', '검토 필요'],
             'series': [{'name': '신청 기록', 'values': [48, 16, 8]}]}
    scenarios = {'title': '같은 기준으로 서로 다른 신청을 살펴보세요', 'items': [
        {'label': '조건 충족', 'input': 'A 회차 신청. 출석과 실습 제출이 모두 확인됐습니다.',
         'steps': ['신청 번호로 출석 기록을 연결합니다.', '실습 제출 여부를 같은 기준일로 확인합니다.',
                   '두 조건이 충족되면 수료 후보로 표시합니다.'],
         'output': '수료 후보. 최종 확정은 담당자가 원자료와 함께 확인합니다.'},
        {'label': '자료 보완', 'input': 'B 회차 신청. 출석은 확인됐지만 실습 제출 기록이 비어 있습니다.',
         'steps': ['빈 기록을 미제출 확정과 구분합니다.', '담당자에게 확인할 항목을 남깁니다.',
                   '보완 전까지 수료 집계에 포함하지 않습니다.'],
         'output': '확인 대기. 누락된 증빙을 받은 뒤 같은 규칙으로 다시 판단합니다.'},
        {'label': '중복 신청', 'input': '같은 신청 번호가 서로 다른 회차에 나타났습니다.',
         'steps': ['같은 번호의 기록을 묶어 비교합니다.', '자동으로 최신 한 건을 고르지 않습니다.',
                   '회차 변경 이력인지 실제 중복인지 확인합니다.'],
         'output': '검토 후보. 확인 전까지 원본 두 건을 유지합니다.'}]}
    explanation = {'title': '왜 신청 인원과 수료 인원을 나누어 볼까요?',
                   'body': '신청은 참여 의사이고 수료는 조건을 충족했다는 기록입니다. 두 지표를 합치면 준비 상태와 성과를 구분하기 어렵습니다.',
                   'bullets': ['기간은 동일하게 맞춥니다.', '미확인 값과 0을 구분합니다.', '규칙을 바꿀 때는 적용 기준일을 함께 남깁니다.']}
    intro = {'title': '신청 목록에서\n다음 행동까지', 'layout': 'split', 'eyebrow': '01 / 상황을 이해하기',
             'takeaway': '자료를 더 모으기 전에 판단 기준을 함께 정합니다.',
             'body': '참여 신청, 출석, 실습 제출은 서로 다른 기록입니다. 하나의 결과로 섞기보다 기준을 맞추고 필요한 조치를 분리하면 담당자가 다음 행동을 고르기 쉽습니다.',
             'chart': trend, 'source': source}
    compare = {'title': '자동 판단과 담당자 확인의 경계', 'eyebrow': '03 / 비교 근거',
               'body': '자동 처리는 같은 규칙의 반복 계산을 맡습니다. 기록이 충돌하거나 기준이 바뀌는 경우는 근거를 함께 보여 줍니다.',
               'table': {'headers': ['상황', '자동으로 하는 일', '사람이 확인할 일'], 'interactive': False,
                         'rows': [['조건 충족', '같은 기준일의 증빙 연결', '최종 수료 확정'],
                                  ['자료 누락', '비어 있는 항목 분리', '누락 원인과 보완 일정'],
                                  ['중복 기록', '관련 원본을 함께 표시', '변경 이력 또는 실제 중복 여부']]},
               'source': source}
    if key == 'reference-1':
        return {**common, 'title': '신청 기록을 업무 판단으로 바꾸는 방법', 'sections': [intro,
            {'title': '사례를 바꾸면 처리 과정도 달라집니다', 'eyebrow': '02 / 직접 살펴보기',
             'body': '아래 사례를 선택하면 입력, 처리 순서와 결과가 함께 바뀝니다. 자료 자체를 수정하거나 서버에 전송하지 않습니다.',
             'scenarios': scenarios, 'source': source}, compare,
            {'title': '기준을 남겨야 다음에도 재사용할 수 있습니다', 'eyebrow': '04 / 적용 조건',
             'body': '조회 기간과 포함 범위, 예외 조건을 결과 가까이에 남깁니다. 이후 기록이 추가되면 같은 기준으로 다시 계산할 수 있습니다.',
             'details': [explanation, {'title': '이 예제가 확인하지 않은 것',
               'body': '실제 출석 시스템 연결과 개인별 수료 판단은 하지 않았습니다. 아래 수치는 양식 검토를 위한 가상 자료입니다.'}], 'source': source}]}
    if key == 'reference-2':
        rows = [[f'EDU-{i+1:03d}', 'A' if i % 2 == 0 else 'B', ['생산', '품질', '지원'][i % 3],
                 ['조건 충족', '보완 필요', '검토 필요'][0 if i < 48 else 1 if i < 64 else 2],
                 '2026-10-01', '증빙과 판정 기준을 확인한 뒤 결과를 확정합니다.'] for i in range(72)]
        return {**common, 'title': '교육 신청 현황과 확인이 필요한 기록',
            'facts': [{'id': 'total', 'label': '전체 신청', 'unit': '건', 'op': 'value', 'inputs': [72]},
                      {'id': 'complete', 'label': '조건 충족', 'unit': '건', 'op': 'value', 'inputs': [48]},
                      {'id': 'pending', 'label': '보완 또는 검토', 'unit': '건', 'op': 'value', 'inputs': [24]}],
            'sections': [{**intro, 'title': '72건 중 24건은\n추가 확인이 필요합니다', 'kpis': []},
                {'title': '집계 기준을 먼저 확인하세요', 'eyebrow': '02 / 핵심 지표', 'layout': 'dashboard',
                 'kpis': [{'fact': 'total', 'note': '표에 포함된 전체 기록'}, {'fact': 'complete', 'note': '최종 수료 확정과는 다름'},
                          {'fact': 'pending', 'note': '보완 16건 + 검토 8건'}],
                 'body': '기준일은 2026년 10월 1일입니다. 표를 검색해도 이 지표는 전체 72건 기준으로 유지됩니다.', 'source': source},
                {'title': '필요한 기록만 찾아보세요', 'eyebrow': '03 / 상세 데이터', 'layout': 'table',
                 'body': '회차나 상태로 좁힌 뒤 정렬하세요. CSV를 내려받을 때 전체 자료인지 현재 검색 결과인지 구분할 수 있습니다.',
                 'table': {'headers': ['신청 ID', '회차', '부서', '상태', '기준일', '다음 조치'], 'rows': rows,
                           'columnTypes': ['id', 'text', 'text', 'text', 'date', 'text']}, 'source': source},
                {'title': '집계 방식과 제외 범위', 'eyebrow': '04 / 읽기 전에 알아둘 점',
                 'details': [explanation], 'body': '전체 표는 72건입니다. 현재 페이지에 보이는 행 수와 전체 건수는 다릅니다.', 'source': source}]}
    return {**common, 'title': '교육 운영 개선안을 검토하기 위한 브리핑', 'sections': [
        {**intro, 'title': '확인 대상을 먼저 좁히고\n자동화 범위를 정합니다',
         'takeaway': '누락과 충돌을 분리하는 작은 작업부터 적용합니다.'},
        {**compare, 'title': '선택지는 같은 기준으로 비교합니다', 'layout': 'split'},
        {'title': '도입 전후에 확인할 순서', 'eyebrow': '03 / 실행 경로',
         'body': '한꺼번에 전환하기보다 시험 범위와 확인 책임을 정한 뒤 적용합니다.',
         'scenarios': {'title': '검토 단계를 선택하세요', 'items': [
             {'label': '1. 기준 합의', 'input': '신청, 출석과 제출 자료의 실제 열 이름과 기준일',
              'steps': ['같은 사람과 회차를 연결할 키를 확인합니다.', '빈 값과 중복을 처리할 규칙을 정합니다.'],
              'output': '입력 항목, 판정 기준과 예외 처리 조건'},
             {'label': '2. 소규모 확인', 'input': '조건 충족, 누락과 중복을 포함한 시험 자료',
              'steps': ['같은 자료로 수작업 결과와 비교합니다.', '결과가 다른 항목의 근거를 함께 확인합니다.'],
              'output': '차이가 난 항목과 적용 가능 범위'},
             {'label': '3. 운영 반영', 'input': '확인한 기준과 담당자 검토 결과',
              'steps': ['사용자가 결과와 원본을 함께 볼 수 있게 합니다.', '기준 변경 시 다시 확인할 조건을 남깁니다.'],
              'output': '운영 기준과 담당자가 확인할 기록 목록'}]}, 'source': source},
        {'title': '효과는 운영 자료로 확인한 뒤 판단합니다', 'eyebrow': '04 / 결정 조건',
         'body': '시간 절감이나 정확도 향상을 미리 확정하지 않습니다. 같은 범위의 작업을 비교하고 검토 시간이 줄었는지 확인합니다.',
         'details': [{'title': '시작 전에 필요한 정보', 'bullets': ['시험 대상 회차와 기준일', '원본 자료를 확인할 담당자', '판단이 다른 항목의 처리 방법']}],
         'source': source}]}


def preview_markup(key: str) -> str:
    """완성 예제 첫 구획을 동일 렌더러로 축소합니다. JS는 실행하지 않습니다."""
    from . import business_artifacts as artifacts, report_design
    spec = example_spec(key)
    spec['fontSource'] = 'system'  # 축소 DOM만 사용하므로 글꼴 바이트는 갤러리에 한 번 넣습니다.
    spec['sections'] = spec['sections'][:1]
    spec.pop('facts', None)
    data = artifacts._normalize(spec, html_tables=True)
    data['sections'][0].update({field: copy.deepcopy(spec['sections'][0][field])
                              for field in ('layout', 'eyebrow', 'takeaway', 'source') if field in spec['sections'][0]})
    doc = report_design.render(data, '', '', artifacts._html_table)
    return doc.split('<main class="report-main">', 1)[1].split('</main>', 1)[0]
