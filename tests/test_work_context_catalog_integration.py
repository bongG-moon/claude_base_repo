"""Portable skill packaging and discovery; no actual profiles or sessions read."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'company-agent-plugin'
sys.path.insert(0, str(PLUGIN / 'scripts'))
import test_skill_discovery as discovery
from company_agent.skill_registry import inventory_skills
from company_agent.skill_task_context import task_candidates
from company_agent.skill_decision import decide_preparation


class WorkCatalogIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixture = discovery.SkillDiscoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture_root = fixture.root
        self.inventory = inventory_skills(fixture.state, project_root=fixture.project,
                                         plugin_root=PLUGIN, claude_root=fixture.claude)
        self.skill = next(s for s in self.inventory['skills'] if s['name']=='work-context-catalog')

    def test_explicit_request_uses_shipped_skill_without_runtime_read(self):
        with patch('pathlib.Path.open', side_effect=AssertionError('no file reads')):
            candidates = task_candidates(self.inventory, '회사 work-context-catalog 스킬로 업무 자료 집계해줘')
        decision = decide_preparation(candidates,self.inventory['skills'],[])
        self.assertEqual(('load',self.skill['id']),(decision.mode,decision.candidate_id))

    def test_does_not_steal_unrelated_work(self):
        for request in ('안녕', 'HTML 보고서 만들어줘', '위 내용을 HTML로 만들어줘',
                        'PPT 만들어줘', '새 스킬 만들어줘', '엑셀 수식 구조를 분석해줘',
                        '이 문장을 기억해줘', 'Chrome에서 페이지를 읽어줘',
                        '방금 작업한 흐름을 그림으로 보여줘', '구조를 정리해줘',
                        'Claude 세션 연결 오류를 분석해줘', 'Claude 사용 기록이 무슨 뜻인지 알려줘',
                        '여러 세션 간 인증 상태 공유 구조를 설명해줘',
                        'Claude 사용 기록을 집계하는 방법을 알려줘',
                        'Claude 사용 기록 분석 기능의 사용법을 설명해줘',
                        'Explain how to summarize Claude usage history'):
            candidates = task_candidates(self.inventory, request)
            self.assertNotIn(self.skill['id'], candidates.get('strongIds',[]),request)

    def test_html_creation_has_one_workflow_without_usage_inventory(self):
        for request in ('HTML 보고서 만들어줘', '위 내용을 HTML로 만들어줘'):
            candidates = task_candidates(self.inventory, request)
            decision = decide_preparation(candidates, self.inventory['skills'], [])
            html_skill = next(s for s in self.inventory['skills'] if s['name'] == 'html-report')
            self.assertEqual(('load', html_skill['id']), (decision.mode, decision.candidate_id), request)

    def test_usage_inventory_remains_discoverable_without_explicit_name(self):
        candidates = task_candidates(self.inventory, 'Claude 사용 기록을 집계하고 업무 흐름을 설명해줘')
        self.assertTrue(any(row['id'] == self.skill['id'] for group in candidates.get('groups', [])
                            for row in group['candidates']))
        decision = decide_preparation(candidates, self.inventory['skills'], [])
        self.assertEqual(('load', self.skill['id']), (decision.mode, decision.candidate_id))

    def test_current_task_and_usage_history_remain_distinct_scopes(self):
        for prompt in ('Claude 사용 기록을 업무별로 정리해줘', '모든 세션을 업무 유형으로 분류해줘',
                       'Claude 사용 기록을 HTML로 만들어줘',
                       'Summarize Claude usage history and show the workflows'):
            with self.subTest(prompt=prompt):
                candidates = task_candidates(self.inventory, prompt)
                decision = decide_preparation(candidates, self.inventory['skills'], [])
                self.assertEqual(('load', self.skill['id']), (decision.mode, decision.candidate_id))

    def test_usage_analysis_keeps_separate_ppt_delivery_and_skill_authoring(self):
        candidates = task_candidates(self.inventory, 'Claude 사용 기록을 집계하고 PPT 발표자료 만들어줘')
        names = {row['name'] for group in candidates.get('groups', []) for row in group['candidates']}
        self.assertTrue({'work-context-catalog', 'presentation'} <= names, names)
        self.assertNotEqual('choose', decide_preparation(candidates, self.inventory['skills'], []).mode)
        candidates = task_candidates(self.inventory, 'Claude 사용 기록을 분석하는 새 스킬 만들어줘')
        choice = decide_preparation(candidates, self.inventory['skills'], [])
        asset = next(s for s in self.inventory['skills'] if s['name'] == 'asset-factory')
        self.assertEqual(('load', asset['id']), (choice.mode, choice.candidate_id))

    def test_distributed_files_match_and_no_fixtures_are_shipped(self):
        path=ROOT/'scripts/sync-work-context-skill.py'
        spec=importlib.util.spec_from_file_location('catalog_sync',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for name,expected in module.expected_files().items():
            actual=(PLUGIN/'skills/work-context-catalog'/name).read_bytes()
            if not name.endswith('.woff'): actual=actual.replace(b'\r\n',b'\n')
            self.assertEqual(expected,actual,name)
        self.assertFalse((PLUGIN/'skills/work-context-catalog/tests').exists())
        hooks=(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8')
        self.assertNotIn('work-context-catalog',hooks)

    def test_installed_cli_includes_work_sessions_without_extra_flag(self):
        """Test a real installed entry, but never discover the live user's profile."""
        path = PLUGIN / 'skills/work-context-catalog/scripts/work_catalog.py'
        spec = importlib.util.spec_from_file_location('installed_work_catalog', path)
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(path.parent), *sys.path]):
            spec.loader.exec_module(module)
        profile = self.fixture_root / 'synthetic-profile'
        sessions = profile / 'projects' / 'fixture'
        sessions.mkdir(parents=True)
        for name, question in [('work', '신청 자료의 집계 오류 원인을 확인해줘'), ('hello', '안녕하세요!')]:
            row = {'type': 'user', 'uuid': name, 'sessionId': name,
                   'message': {'content': question}}
            (sessions / (name + '.jsonl')).write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
        for extra, expected in [((), 1), (('--no-sessions',), 0)]:
            output = self.fixture_root / ('included' if not extra else 'excluded')
            with redirect_stdout(io.StringIO()):
                code = module.main(['--profile-root', str(profile), '--output', str(output), *extra])
            self.assertEqual(0, code)
            report = json.loads((output / 'catalog.json').read_text(encoding='utf-8'))
            self.assertEqual(expected, report['summary']['observed_sessions'])
            self.assertEqual(not extra, report['coverage']['sessions_requested'])
            self.assertNotIn('신청 자료의 집계 오류', json.dumps(report, ensure_ascii=False))
            self.assertNotIn(str(profile), json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': unittest.main()
