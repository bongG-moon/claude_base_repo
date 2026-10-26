"""Synthetic-only reproducible visual/integration example. No live profiles."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_catalog import main as collect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.fixture_root).resolve()
    if root.exists():
        raise ValueError('Use a new fixture folder')
    files = {
        'education/CLAUDE.md': '# 교육 운영 업무\n이 자료는 실습용 가상 지침입니다.',
        'education/.claude/skills/enrollment/SKILL.md': '---\nname: 교육 신청 데이터 집계\ndescription: 엑셀 신청자를 과정별로 집계하고 교육 결과 보고서를 작성합니다.\n---\n실습용 스킬.',
        'education/knowledge/terms.md': '---\ntitle: 교육 신청 중복과 취소 처리 기준\nsummary: 이 가상 업무에서는 같은 신청자·과정 조합을 중복 후보로 검토합니다. 취소 건의 집계 포함 여부는 담당자가 정하며 자동 확정하지 않습니다.\n---\n교육 과정과 신청 상태의 실습용 정의입니다.',
        'education/memory/inventory.md': '# 재고 보고 작성 방식\n가상 예제에서는 품목별 집계와 안전재고 비교 후 발주표를 검토합니다.',
        'sales/AGENTS.md': '# 매출 분석 업무\n이 자료는 실습용 가상 지침입니다.',
        'sales/.agents/skills/report/SKILL.md': '---\nname: 주간 매출 보고서\ndescription: 데이터 분석 결과를 보고서로 정리합니다.\n---\n실습용 스킬.',
        'sales/memory/style.md': '# 보고서 작성 방식 기억\n실습용 기억.',
        'profile/settings.json': '{"env":{"API_KEY":"FAKE_ONLY_DO_NOT_EXPORT"}}',
        'state/memory/note.json': '{"note":"관리 JSON은 이 실습에서도 내용 수집하지 않습니다."}',
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    rows = [
        {'type':'user','uuid':'demo-u1','sessionId':'demo-education','cwd':str(root/'education'),'message':{'content':'교육 신청 CSV를 읽고 중복 신청을 제거한 뒤 부서별 신청 인원을 집계하고 강사 명단과 매칭한 후 HTML 현황을 만들어줘'}},
    ]
    # 실제 로그와 같은 호출 ID로 결과를 연결합니다. 원문 인수/결과는 보고서에 복사하지 않습니다.
    def call_pair(session_id, number, name, arguments, error=False):
        call_id = session_id + '-call-' + str(number)
        return [
            {'type':'assistant','uuid':call_id+'-event','sessionId':session_id,
             'message':{'content':[{'type':'tool_use','id':call_id,'name':name,'input':arguments}]}},
            {'type':'user','uuid':call_id+'-result','sessionId':session_id,
             'message':{'content':[{'type':'tool_result','tool_use_id':call_id,'is_error':error,
                                    'content':'FAKE_RESULT_BODY_DO_NOT_EXPORT'}]}}
        ]
    rows += call_pair('demo-education',1,'Skill',{'skill':'enrollment'})
    rows += call_pair('demo-education',2,'Read',{'file_path':str(root/'education/신청목록.csv')})
    rows += call_pair('demo-education',3,'Bash',{'command':'python enrollment_summary.py'})
    rows += call_pair('demo-education',4,'Write',{'file_path':str(root/'education/신청현황.html'),'content':'FAKE_HTML_BODY_DO_NOT_EXPORT'})
    rows += call_pair('demo-education',9,'Write',{'file_path':str(root/'education/.claude/skills/enrollment/SKILL.md'),'content':'FAKE_SKILL_BODY_DO_NOT_EXPORT'})
    rows += [{'type':'user','uuid':'demo-u2','sessionId':'demo-education','message':{'content':'별개로 재고 CSV를 읽고 품목코드 중복을 제거한 후 품목별 재고량을 집계하고 안전재고를 계산해서 발주표를 작성한 뒤 수량을 확인하고 결과를 저장해줘'}}]
    rows += call_pair('demo-education',5,'Read',{'file_path':str(root/'education/재고.csv')})
    rows += call_pair('demo-education',6,'Bash',{'command':'python inventory_report.py'},error=True)
    rows += call_pair('demo-education',7,'Edit',{'file_path':str(root/'education/inventory_report.py'),'old_string':'private old code','new_string':'private new code'})
    rows += call_pair('demo-education',8,'Bash',{'command':'python inventory_report.py'})
    rows += call_pair('demo-education',10,'Write',{'file_path':str(root/'education/memory/inventory.md'),'content':'FAKE_MEMORY_BODY_DO_NOT_EXPORT'})
    session = root / 'profile/projects/education/session.jsonl'
    session.parent.mkdir(parents=True)
    session.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    # 같은 업무를 다른 날 요청한 세션, 도구는 같지만 별개인 업무를 구분합니다.
    for i in range(1, 4):
        repeat = json.loads(json.dumps(rows[:1]))
        repeat[0]['sessionId'] = 'education-repeat-' + str(i)
        repeat[0]['uuid'] = 'education-repeat-user-' + str(i)
        if i == 3:
            repeat[0]['message']['content'] = '교육 신청 CSV를 읽고 과정별 신청 인원을 집계한 후 누락 여부를 확인해줘'
        repeat += call_pair(repeat[0]['sessionId'],1,'Read',{'file_path':str(root/'education/신청목록.csv')})
        repeat += call_pair(repeat[0]['sessionId'],2,'Bash',{'command':'python enrollment_summary.py'})
        repeat += call_pair(repeat[0]['sessionId'],3,'Edit',{'file_path':str(root/'education/.claude/skills/enrollment/SKILL.md'),
            'old_string':'FAKE_OLD_BODY_DO_NOT_EXPORT','new_string':'FAKE_NEW_BODY_DO_NOT_EXPORT'})
        (session.parent / ('repeat-' + str(i) + '.jsonl')).write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in repeat), encoding='utf-8')
    sales = {'type': 'user', 'uuid': 'sales-user', 'sessionId': 'sales-work', 'cwd': str(root/'sales'),
        'message': {'content': '매출 CSV를 읽고 결측값을 정리한 후 월별 매출을 집계하고 고객 명단과 매칭해서 HTML을 만든 뒤 합계를 검증해줘'}}
    sales_rows = [sales] + call_pair('sales-work',1,'Read',{'file_path':str(root/'sales/매출.csv')})
    sales_rows += call_pair('sales-work',2,'Bash',{'command':'python monthly_report.py'})
    # 이 업무는 자산 저장 근거가 없으므로 전체 유형 요약에만 남습니다.
    # 결과가 끊긴 호출은 성공으로 표시하지 않아야 합니다.
    sales_rows += [{'type':'assistant','uuid':'sales-last','sessionId':'sales-work','message':{'content':[
        {'type':'tool_use','id':'sales-write','name':'Write','input':{'file_path':str(root/'sales/매출보고서.html')}}]}}]
    (session.parent / 'sales.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in sales_rows), encoding='utf-8')
    for i in range(28):
        long_path = root / 'education/knowledge/부서별-신청-현황과-강사-매칭-세부-운영-기준' / ('업무-지식-' + str(i) + '.md')
        long_path.parent.mkdir(parents=True, exist_ok=True)
        long_path.write_text('---\ntitle: 교육 과정별 신청 기준과 장기 교육 운영 담당자의 확인 항목 ' + str(i) + '\nsummary: 신청 인원을 부서와 과정 기준으로 집계하고 중복 신청, 취소, 정원 초과, 강사 배정 누락을 구분하는 실습용 설명입니다.\n---\n실습용 가상 자료', encoding='utf-8')
    # 인사만 있는 기록은 제외하고, 실패나 짧은 실제 업무 요청은 남기는 예제입니다.
    for name, question in [('greeting', '안녕하세요!'), ('investigation', '교육 집계 오류 원인을 확인해줘'),
        ('weather', '오늘 날씨 알려줘'), ('uncertain', '응'), ('one-step', '계약서를 검토해줘')]:
        row = {'type': 'user', 'uuid': 'demo-' + name, 'sessionId': 'demo-' + name,
               'message': {'content': question}}
        (session.parent / (name + '.jsonl')).write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
    return collect(['--root',str(root/'education'),'--root',str(root/'sales'),'--profile-root',str(root/'profile'),
                    '--state-root',str(root/'state'),'--output',args.output])


if __name__ == '__main__':
    raise SystemExit(main())
