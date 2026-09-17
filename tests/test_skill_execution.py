"""Skill-first context delivery and honest fallback, not simulated HCP behavior."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

import test_skill_discovery as discovery
from company_agent.native_runtime import task_prompt_context, worker_runtime_input
from company_agent.skill_execution import MAX_REQUEST_CONTEXT_CHARS
from company_agent.skill_registry import inventory_skills, set_skill_preference
from company_agent.skill_workflow import preflight
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.state import load_session, stop_decision


class SkillExecutionTests(unittest.TestCase):
    def setUp(self):
        self.f = discovery.SkillDiscoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.context(source='startup')

    def output(self, prompt='@테스트자료.pptx 이 파일 내용 읽어줄래?', context=None):
        ctx = context or self.f.context(prompt)
        text = task_prompt_context('{"company_agent_instruction":"old","company_agent_route":{"tier":"MEDIUM"}}',
                                   json.dumps({'company_agent_runtime': ctx}, ensure_ascii=False))
        return json.loads(text.splitlines()[-1])['company_agent_runtime'], text

    def state(self):
        return load_session(self.f.sid, self.f.state)

    def test_unmentioned_ppt_gets_existing_load_target_not_fake_selection(self):
        ctx, text = self.output()
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertEqual('office-reader', ctx['skillExecution']['name'])
        body = (discovery.PLUGIN / 'skills/office-reader/SKILL.md').read_text(encoding='utf-8').split('---', 2)[2].strip()
        self.assertNotIn(body, text)
        self.assertEqual('load-relevant-skill', ctx['skillWorkflow']['nextAction'])
        self.assertLess(text.index('company-agent:office-reader'), text.index('company_agent_route'))
        self.assertLessEqual(len(text), MAX_REQUEST_CONTEXT_CHARS)
        self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])
        self.assertNotIn('lastBodyLoad', self.state()['skillWorkflow'])
        self.assertEqual('not-observed', self.state()['skillWorkflow']['loadObservation']['status'])
        self.assertIsNone(self.state()['skillWorkflow']['selected'])
        self.assertEqual(0, self.state()['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id': self.f.sid}, self.f.state))
        self.assertNotIn('테스트자료.pptx', json.dumps(self.state(), ensure_ascii=False))
        self.assertNotIn('Presentations.Open', json.dumps(self.state(), ensure_ascii=False))

    def test_followup_keeps_workflow_without_saving_original_prompt(self):
        self.output()
        ctx, text = self.output('company스킬 사용해서 읽어줘')
        self.assertEqual('office-reader', ctx['skillExecution']['name'])
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertNotIn('basis', ctx['skillExecution'])
        self.assertNotIn('Presentations.Open', text)
        self.assertNotIn('company스킬 사용해서', json.dumps(self.state(), ensure_ascii=False))

    def test_new_work_does_not_keep_previous_workflow(self):
        self.output()
        ctx, _ = self.output('HTML 보고서를 만들어줘')
        self.assertNotEqual('office-reader', ctx['skillExecution'].get('name'))

    def test_shortlist_miss_reviews_full_list_then_general_work_without_marker_commands(self):
        ctx, text = self.output('2 더하기 3은 얼마야?')
        self.assertEqual('review', ctx['skillExecution']['mode'])
        self.assertIn('관련 스킬이 없으면 일반 실행', text)
        self.f.read(Path(ctx['skillSelection']['catalog']['path']))
        for tool, inputs in [('Bash', {'command':'python -c "print(2+3)"'}), ('Write', {'file_path':str(self.f.project / 'answer.txt')})]:
            self.assertEqual({}, preflight(self.f.state, self.f.project, {'session_id':self.f.sid, 'tool_name':tool, 'tool_input':inputs}))
        self.assertEqual({}, stop_decision({'session_id':self.f.sid}, self.f.state))

    def test_same_name_conflict_requires_choice_and_never_injects_either_body(self):
        self.f.skill('office-reader', '기존 PPT 내용 분석 및 읽기')
        ctx, text = self.output()
        self.assertEqual('choose', ctx['skillExecution']['mode'])
        self.assertNotIn('Presentations.Open', text)
        self.assertNotIn('SECRET-BODY', text)
        self.assertIn('한국어로 물', text)

    def test_different_named_alternative_is_not_silently_discarded(self):
        self.f.skill('team-reader', 'PPT 내용 읽기 및 요약')
        ctx, text = self.output()
        self.assertEqual('select', ctx['skillExecution']['mode'])
        self.assertIn('team-reader', text)
        self.assertIn('office-reader', text)
        self.assertNotIn('Presentations.Open', text)

    def test_saved_preference_uses_exact_personal_file_not_company(self):
        file = self.f.skill('office-reader', '기존 PPT 내용 읽기')
        inv = inventory_skills(self.f.state, project_root=self.f.project, plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        item = next(x for x in inv['skills'] if x['path'] == str(file))
        set_skill_preference(self.f.state, 'office-reader', item['id'], project_root=self.f.project, plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        self.f.context(source='startup')
        ctx, text = self.output()
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertEqual(str(file), ctx['skillExecution']['path'])
        self.assertNotIn('SECRET-BODY-office-reader', text)
        self.assertNotIn('Presentations.Open', text)

    def test_explicit_native_options_remain_native(self):
        for extra in ['context: fork\n', 'allowed-tools: Read\n', 'disable-model-invocation: true\n', 'model: haiku\n',
                      'allowed-tools:\n  - Read\n']:
            with self.subTest(extra=extra):
                self.f.skill('native-special', 'uniquevalue', extra=extra)
                ctx, text = self.output('/native-special uniquevalue')
                self.assertNotIn('SECRET-BODY-native-special', text)
                self.assertEqual('load', ctx['skillExecution']['mode'])
                self.assertEqual('native-body-load', ctx['skillExecution']['reason'])
                self.assertNotIn('selectedSkill', text)

    def test_dynamic_substitution_remains_native(self):
        for token in ['$ARGUMENTS', '${CLAUDE_SKILL_DIR}', '!`some-command`', '$1']:
            with self.subTest(token=token):
                file = self.f.skill('dynamic-special', 'uniquevalue')
                atomic_write_text(file, file.read_text(encoding='utf-8') + token)
                ctx, text = self.output('uniquevalue')
                self.assertEqual('load', ctx['skillExecution']['mode'])
                self.assertEqual('native-body-load', ctx['skillExecution']['reason'])
                self.f.read(file)
                ctx, _ = self.output('uniquevalue')
                self.assertEqual('load', ctx['skillExecution']['mode'])
                self.assertEqual('native-skill-semantics', ctx['skillExecution']['reason'])
                self.assertNotIn('SECRET-BODY-dynamic-special', text)

    def test_read_or_skill_permission_rules_keep_native_permission_check(self):
        self.output()
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        for mode, rule in [('deny', 'Skill(company-agent:office-reader)'), ('deny', 'Read(**/SKILL.md)'),
                           ('ask', 'Read')]:
            with self.subTest(rule=rule, mode=mode):
                atomic_write_json(self.f.claude / 'settings.json', {'permissions': {mode:[rule]}})
                ctx, text = self.output()
                self.assertEqual('load', ctx['skillExecution']['mode'])
                self.assertEqual('host-loading-rules', ctx['skillExecution']['reason'])
                self.assertNotIn('Presentations.Open', text)

    def test_compact_resume_and_startup_clear_body_reuse(self):
        for source in ('compact', 'resume', 'startup'):
            with self.subTest(source=source):
                self.output()
                self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
                self.f.context(source=source)
                ctx, text = self.output()
                self.assertEqual('load', ctx['skillExecution']['mode'])
                self.assertNotIn('Presentations.Open', text)

    def test_incomplete_catalogue_is_not_general_or_fake_load(self):
        ctx = self.f.context()
        ctx['taskSkills'] = {'status':'incomplete','groups':[]}
        result, text = self.output(context=ctx)
        self.assertEqual('inspect', result['skillExecution']['mode'])
        self.assertIn('스킬 부재로 단정하지', text)
        self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])

    def test_catalogue_io_failure_without_candidate_metadata_is_not_general(self):
        ctx = self.f.context('ordinary task')
        ctx['taskSkills'] = {}
        ctx['skillSelection']['catalog'] = {'status':'unavailable'}
        result, _ = self.output(context=ctx)
        self.assertEqual('inspect', result['skillExecution']['mode'])

    def test_body_change_between_discovery_and_delivery_is_not_exposed(self):
        file = self.f.skill('custom-unique', 'uniquevalue')
        ctx = self.f.context('uniquevalue')
        atomic_write_text(file, file.read_text(encoding='utf-8') + '\nchanged')
        result, text = self.output(context=ctx)
        self.assertEqual('inspect', result['skillExecution']['mode'])
        self.assertNotIn('SECRET-BODY', text)

    def test_oversize_body_is_not_truncated_or_injected(self):
        self.f.skill('large-special', 'uniquevalue')
        file = self.f.claude / 'skills/large-special/SKILL.md'
        atomic_write_text(file, file.read_text(encoding='utf-8') + 'Z' * 8500)
        self.f.context(source='startup')
        ctx, text = self.output('uniquevalue')
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertNotIn('ZZZZ', text)

    def test_prompt_never_injects_body_and_stays_small(self):
        ctx, text = self.output()
        self.assertEqual('load', ctx['skillExecution']['mode'])
        self.assertNotIn('Presentations.Open', text)
        self.assertFalse(self.state()['skillWorkflow'].get('providedSkills'))
        self.assertLess(len(text), 5000)

    def test_native_read_receipt_remains_distinct(self):
        self.output()
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        ctx, _ = self.output()
        self.assertEqual('reuse', ctx['skillExecution']['mode'])
        self.assertEqual('observed-body-load', ctx['skillExecution']['basis'])
        self.assertEqual('Read', self.state()['skillWorkflow']['lastBodyLoad']['tool'])

    def test_worker_receives_verified_path_but_not_a_fake_body_receipt(self):
        self.output()
        inputs = {'session_id': self.f.sid,
                 'tool_input': {'subagent_type':'company-agent:medium-worker', 'prompt':'요약해줘'}}
        result = worker_runtime_input(discovery.PLUGIN, self.f.project, inputs)
        self.assertNotIn('"selectedSkill":', result['hookSpecificOutput']['updatedInput']['prompt'])
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        result = worker_runtime_input(discovery.PLUGIN, self.f.project, {'session_id': self.f.sid,
                 'tool_input': {'subagent_type':'company-agent:medium-worker', 'prompt':'요약해줘'}})
        text = result['hookSpecificOutput']['updatedInput']['prompt']
        self.assertIn('office-reader', text)
        self.assertIn('selectedSkill', text)
        self.assertNotIn('"skillIndex"', text)
        self.assertEqual(1, len(self.state()['skillWorkflow']['readSkills']))

    def test_legacy_delivery_is_not_reuse_and_is_removed(self):
        ctx = self.f.context()
        state = self.state()
        inv = inventory_skills(self.f.state, project_root=self.f.project, plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        item = next(x for x in inv['skills'] if x['name'] == 'office-reader')
        state['skillWorkflow']['providedSkills'] = {item['id']: item['sha256']}
        atomic_write_json(self.f.state / 'sessions' / (self.f.sid + '.json'), state)
        result, text = self.output(context=ctx)
        self.assertEqual('load', result['skillExecution']['mode'])
        self.assertNotIn('Presentations.Open', text)
        self.assertNotIn('providedSkills', self.state()['skillWorkflow'])
        self.assertIsNone(self.state()['skillWorkflow']['selected'])


if __name__ == '__main__':
    unittest.main()
