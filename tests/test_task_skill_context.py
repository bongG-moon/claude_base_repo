"""Real metadata/routing regressions; not a claim of HCP model adherence."""
import json
from pathlib import Path
import unittest

import test_skill_discovery as discovery
from company_agent.skill_task_context import task_candidates, MAX_TASK_SKILL_CHARS
from company_agent.skill_workflow import choose, preflight, internal_command
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.state import load_session, record_activity

PLUGIN = discovery.PLUGIN


class TaskSkillContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = discovery.SkillDiscoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture

    def test_generic_question_words_do_not_select_unrelated_mail_skill(self):
        context = self.f.context('관련 없는 질문')
        self.assertEqual([], context['taskSkills']['groups'])

    def test_memory_word_does_not_force_personal_storage_for_common_knowledge(self):
        context = self.f.context('공통 기억의 계산식을 조회해줘. 저장하지 마.')
        reminders = ' '.join(context.get('taskReminders', []))
        self.assertIn('공통 기억은 배포 지식 조회', reminders)
        self.assertIn('조회만 요청하면 저장하지 않습니다', reminders)
        self.assertIn('없는 스킬은 강제 호출하지 않습니다', reminders)
        self.assertNotIn('먼저 company-agent:personal-memory', reminders)
        actual = inventory_skills(self.f.state, project_root=self.f.project, claude_root=self.f.claude,
                                  plugin_root=PLUGIN)
        hints = task_candidates(actual, '공통 기억의 계산식을 조회해줘')
        self.assertIn('personal-knowledge', [g['name'] for g in hints['groups']])

    def test_actual_html_prompt_keeps_hints_on_first_and_later_requests(self):
        self.f.context(source='startup')
        for _ in range(2):
            context = self.f.context('@테스트자료.md 여기 자료로 HTML 보고서 만들어줄래?')
            self.assertEqual('reuse', context['skillIndex']['mode'])
            groups = context['taskSkills']['groups']
            self.assertIn('html-report', [g['name'] for g in groups])
            self.assertIn('AskUserQuestion', context['instructions'])
            self.assertIn('UTF-8', context['instructions'])
            route = load_session(self.f.sid, self.f.state)['skillWorkflow']
            self.assertIsNone(route['selected'])
            self.assertEqual({}, route['readSkills'])
            self.assertNotIn('테스트자료.md', json.dumps(route, ensure_ascii=False))

    def test_first_recovery_supplies_concrete_paths_without_permission_or_red_loop(self):
        self.f.context()
        payload = {'session_id': self.f.sid, 'tool_name': 'Bash',
                   'tool_input': {'command': 'python arbitrary_report.py'}}
        first = preflight(self.f.state, self.f.project, payload)['hookSpecificOutput']
        self.assertNotIn('permissionDecision', first)
        self.assertIn('html-report', first['additionalContext'])
        self.assertIn('SKILL.md', first['additionalContext'])
        self.assertEqual({}, preflight(self.f.state, self.f.project, payload))

    def conflict(self):
        self.f.skill('html-report', 'HTML 보고서 제작')
        return self.f.context('html-report HTML 보고서 만들어줘')

    def test_unresolved_name_shows_both_origins_and_preference_removes_question(self):
        context = self.conflict()
        group = next(g for g in context['taskSkills']['groups'] if g['name'] == 'html-report')
        self.assertEqual('unresolved', group['resolution'])
        self.assertEqual({'user', 'company'}, {c['source'] for c in group['candidates']})
        selected = next(x for x in group['candidates'] if x['source'] == 'user')
        set_skill_preference(self.f.state, 'html-report', selected['id'], project_root=self.f.project,
                             plugin_root=PLUGIN, claude_root=self.f.claude)
        changed = self.f.context('html-report HTML 보고서 만들어줘')
        group = next(g for g in changed['taskSkills']['groups'] if g['name'] == 'html-report')
        self.assertEqual('selected', group['resolution'])
        self.assertEqual([selected['id']], [c['id'] for c in group['candidates']])

    def test_answered_choice_does_not_fabricate_read_or_change_preferences(self):
        context = self.conflict()
        group = next(g for g in context['taskSkills']['groups'] if g['name'] == 'html-report')
        candidate = next(x for x in group['candidates'] if x['source'] == 'user')
        turn = context['skillWorkflow']['turn']
        result = choose(self.f.state, self.f.project, self.f.sid, turn, candidate['id'])
        self.assertFalse(result['bodyAlreadyRead'])
        self.assertFalse(result['preferencesChanged'])
        self.assertIsNone(load_session(self.f.sid, self.f.state)['skillWorkflow']['selected'])
        self.f.read(Path(result['readPath']))
        route = load_session(self.f.sid, self.f.state)['skillWorkflow']
        self.assertEqual(candidate['id'], route['selected']['id'])
        prefs = inventory_skills(self.f.state, project_root=self.f.project, plugin_root=PLUGIN,
                                 claude_root=self.f.claude)['effectivePreferences']
        self.assertEqual({}, prefs['skills'])
        # A new request must not inherit an unasked persistent preference.
        self.f.context('다음 업무')
        self.assertEqual({}, load_session(self.f.sid, self.f.state)['skillWorkflow']['turnChoices'])
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, turn, candidate['id'])

    def test_choice_bookkeeping_is_not_a_business_mutation_or_permission_grant(self):
        context = self.conflict()
        candidate = context['taskSkills']['groups'][0]['candidates'][0]
        command = (context['cliCommand'] + ' skill choose --session ' + self.f.sid +
                   ' --turn ' + context['skillWorkflow']['turn'] + ' --candidate ' + candidate['id'])
        state = load_session(self.f.sid, self.f.state)
        self.assertTrue(internal_command(command, self.f.sid, state, self.f.state))
        self.assertFalse(internal_command(command + ' && echo unsafe', self.f.sid, state, self.f.state))
        record_activity({'session_id': self.f.sid, 'tool_name': 'Bash',
                         'tool_input': {'command': command}}, self.f.state)
        self.assertEqual(0, load_session(self.f.sid, self.f.state)['mutationCount'])

    def test_explicit_only_and_namespaced_explicit_selection(self):
        file = self.f.skill('manual-reader', '기존 PPT 읽기', extra='disable-model-invocation: true\n')
        context = self.f.context('manual-reader PPT 읽기')
        self.assertNotIn('manual-reader', [g['name'] for g in context['taskSkills']['groups']])
        inv = inventory_skills(self.f.state, project_root=self.f.project, plugin_root=PLUGIN, claude_root=self.f.claude)
        candidate = next(x for x in inv['skills'] if x['path'] == str(file))
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, context['skillWorkflow']['turn'], candidate['id'])
        self.conflict()
        ctx = self.f.context('/company-agent:html-report HTML 보고서 만들어줘')
        group = next(g for g in ctx['taskSkills']['groups'] if g['name'] == 'html-report')
        self.assertEqual('explicit', group['resolution'])
        self.assertEqual('company', group['candidates'][0]['source'])

    def test_large_paged_index_still_exposes_relevant_description(self):
        for i in range(40):
            self.f.skill(f'unrelated-{i}', '다른 업무 조건 ' * 25)
        context = self.f.context()
        self.assertEqual('pages', context['skillIndex']['mode'])
        group = next(g for g in context['taskSkills']['groups'] if g['name'] == 'html-report')
        self.assertIn('HTML 보고서', group['candidates'][0]['description'])
        self.assertLessEqual(len(json.dumps(context['taskSkills'], ensure_ascii=False)), MAX_TASK_SKILL_CHARS)

    def test_oversize_conflict_group_is_not_silently_reduced_to_one_candidate(self):
        items = [{'id': str(i), 'name': 'reader', 'source': 'user', 'description': 'PPT ' * 70,
                  'path': 'C:/' + 'x' * 180 + f'/{i}/SKILL.md'} for i in range(20)]
        result = task_candidates({'complete': True, 'skills': items}, 'PPT 읽기')
        self.assertEqual('check-catalog', result['status'])
        self.assertEqual([], result['groups'])
        self.assertTrue(result['moreInCatalog'])

    def test_unmatched_and_incomplete_do_not_claim_no_relevant_skills(self):
        self.assertEqual('no-keyword-match', self.f.context('zxqv983')['taskSkills']['status'])
        self.assertEqual('incomplete', task_candidates({'complete': False}, 'PPT')['status'])

    def test_stale_preference_never_silently_picks_remaining_candidate(self):
        item = {'id': 'current', 'name': 'reader', 'source': 'user', 'description': 'PPT 읽기',
                'path': 'C:/reader/SKILL.md'}
        result = task_candidates({'complete': True, 'skills': [item],
                                  'effectivePreferences': {'skills': {'reader': 'removed'}, 'sourceOrder': []}}, 'PPT')
        self.assertEqual('needs-choice', result['status'])
        self.assertEqual('stale-choice', result['groups'][0]['resolution'])

    def test_complementary_names_are_hints_not_an_automatic_conflict(self):
        context = self.f.context('PPT 발표 자료와 HTML 보고서 만들기')
        self.assertNotEqual('needs-choice', context['taskSkills']['status'])
        self.assertIn('서로 다른 단계의 스킬은 중복이 아닙니다', context['instructions'])

    def test_deleted_or_changed_candidate_cannot_be_chosen_from_old_snapshot(self):
        ctx = self.conflict()
        candidate = next(c for g in ctx['taskSkills']['groups'] if g['name'] == 'html-report'
                         for c in g['candidates'] if c['source'] == 'user')
        self.f.skill('html-report', '수정된 설명')
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, ctx['skillWorkflow']['turn'], candidate['id'])
        with self.assertRaises(ValueError):
            choose(self.f.state, self.f.project, self.f.sid, ctx['skillWorkflow']['turn'], 'not-an-id')


if __name__ == '__main__':
    unittest.main()
