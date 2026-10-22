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
        'education/knowledge/terms.md': '# 교육 과정과 신청 상태 용어\n실습용 용어 정의.',
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
        {'type':'user','uuid':'demo-u1','sessionId':'demo-education','cwd':str(root/'education'),'message':{'content':'교육 신청 엑셀을 집계하고 보고서로 정리해줘'}},
        {'type':'assistant','uuid':'demo-a1','sessionId':'demo-education','message':{'content':[{'type':'tool_use','name':'Read','input':{'file_path':'not exported'}}, {'type':'tool_use','name':'Skill','input':{'skill':'enrollment'}}]}},
    ]
    session = root / 'profile/projects/education/session.jsonl'
    session.parent.mkdir(parents=True)
    session.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    # 인사만 있는 기록은 제외하고, 실패나 짧은 실제 업무 요청은 남기는 예제입니다.
    for name, question in [('greeting', '안녕하세요!'), ('investigation', '집계 오류 원인을 확인해줘')]:
        row = {'type': 'user', 'uuid': 'demo-' + name, 'sessionId': 'demo-' + name,
               'message': {'content': question}}
        (session.parent / (name + '.jsonl')).write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
    return collect(['--root',str(root/'education'),'--root',str(root/'sales'),'--profile-root',str(root/'profile'),
                    '--state-root',str(root/'state'),'--output',args.output])


if __name__ == '__main__':
    raise SystemExit(main())
