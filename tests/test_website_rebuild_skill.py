"""Real discovery boundaries and portable resource closure for the new skill."""
from pathlib import Path
import re
import unittest

import test_skill_discovery as discovery
from company_agent.skill_decision import decide_preparation
from company_agent.skill_registry import inventory_skills
from company_agent.skill_task_context import task_candidates


ROOT = Path(__file__).resolve().parents[1]


class WebsiteRebuildSkillTests(unittest.TestCase):
    def setUp(self):
        self.fixture = discovery.SkillDiscoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.inventory = inventory_skills(f.state, project_root=f.project,
                                          claude_root=f.claude, plugin_root=discovery.PLUGIN)
        self.skill = next(item for item in self.inventory['skills'] if item['name'] == 'website-rebuild')

    def test_explicit_recreation_request_loads_the_real_skill(self):
        hints = task_candidates(self.inventory, '회사 website-rebuild로 이 URL 화면을 재현해줘')
        decision = decide_preparation(hints, self.inventory['skills'], [])
        self.assertEqual('load', decision.mode)
        self.assertEqual(self.skill['id'], decision.candidate_id)
        self.assertTrue(Path(self.skill['path']).is_file())

    def test_report_creation_does_not_gain_a_competing_rebuild_candidate(self):
        hints = task_candidates(self.inventory, '자료로 HTML 보고서를 만들어줘')
        self.assertNotIn(self.skill['id'], hints.get('strongIds', []))
        self.assertNotIn('website-rebuild', [group['name'] for group in hints['groups']])

    def test_plain_image_reading_does_not_force_recreation(self):
        hints = task_candidates(self.inventory, '이 이미지 읽고 내용을 확인해줘')
        self.assertNotIn(self.skill['id'], hints.get('strongIds', []))

    def test_browser_action_does_not_force_recreation(self):
        hints = task_candidates(self.inventory, '크롬에서 신청 버튼을 클릭해줘')
        self.assertNotIn('website-rebuild', [group['name'] for group in hints['groups']])

    def test_url_recreation_is_discoverable_without_reading_bodies(self):
        hints = task_candidates(self.inventory, '이 URL 사이트의 화면과 동작을 그대로 재현해줘 https://example.com')
        self.assertIn('website-rebuild', [group['name'] for group in hints['groups']])

    def test_portable_resources_are_self_contained_and_match_harness_guidance(self):
        company = ROOT / 'company-agent-plugin/skills/website-rebuild'
        portable = ROOT / 'standalone-skills/website-rebuild'
        company_files = {p.relative_to(company) for p in company.rglob('*') if p.is_file()}
        portable_files = {p.relative_to(portable) for p in portable.rglob('*') if p.is_file()}
        self.assertEqual(company_files, portable_files)
        for rel in company_files:
            with self.subTest(path=str(rel)):
                self.assertEqual((company / rel).read_bytes(), (portable / rel).read_bytes())
                source = portable / rel
                if source.suffix == '.md':
                    for target in re.findall(r'\]\(([^)]+)\)', source.read_text(encoding='utf-8')):
                        if '://' in target or target.startswith('#'):
                            continue
                        resolved = (source.parent / target.split('#')[0]).resolve()
                        self.assertTrue(resolved.is_relative_to(portable.resolve()), target)
                        self.assertTrue(resolved.is_file(), target)


if __name__ == '__main__':
    unittest.main()
