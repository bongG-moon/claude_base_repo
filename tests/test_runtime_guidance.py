"""Fixed guidance reuse is output evidence, never host or Skill-load evidence."""
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest

import test_skill_discovery as discovery
from company_agent import native_runtime
from company_agent.model_router import classify_prompt
from company_agent.paths import atomic_write_json
from company_agent.state import _locked_session, learning_context, load_session


class RuntimeGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.f = discovery.SkillDiscoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        environment = patch.dict(os.environ, {
            'COMPANY_AGENT_SCOPE': 'User', 'COMPANY_AGENT_MANAGED_CONFIG': '',
            'COMPANY_AGENT_REGISTRATIONS_ROOT': '', 'COMPANY_WORKSPACE_UI': '',
            'CLAUDE_ENV_FILE': '', 'ProgramFiles': str(self.f.root / 'programs'),
        })
        environment.start()
        self.addCleanup(environment.stop)
        home = patch.object(Path, 'home', return_value=self.f.root)
        home.start()
        self.addCleanup(home.stop)
        # This suite tests hook text, not real host policy discovery. The native
        # permission contract has separate tests; never inspect a live profile.
        native = patch('company_agent.skill_execution.native_load_required', return_value=False)
        native.start()
        self.addCleanup(native.stop)
        self.f.context('', source='startup')

    def output(self, prompt='안녕', context=None):
        runtime = context or self.f.context(prompt)
        route = json.loads(classify_prompt(prompt).as_additional_context(
            session_id=runtime.get('company_agent_session_id', self.f.sid)))
        route['company_agent_learning'] = learning_context(load_session(self.f.sid, self.f.state))
        route['company_agent_memory_retrieval'] = 'ok'
        text = native_runtime.task_prompt_context(
            json.dumps(route, ensure_ascii=False, separators=(',', ':')),
            json.dumps({'company_agent_runtime': runtime}, ensure_ascii=False, separators=(',', ':')))
        return json.loads(text.splitlines()[-1])['company_agent_runtime'], text

    def state(self):
        return load_session(self.f.sid, self.f.state)

    def test_followup_is_smaller_without_claiming_body_or_host_receipt(self):
        first, first_text = self.output('HTML 보고서 만들어줘')
        later, later_text = self.output('HTML 보고서 만들어줘')
        self.assertEqual('full', first['guidance']['mode'])
        self.assertEqual('reuse', later['guidance']['mode'])
        self.assertEqual('previous-output-not-receipt', later['guidance']['basis'])
        self.assertEqual('load', later['skillExecution']['mode'])
        self.assertEqual({}, self.state()['skillWorkflow']['readSkills'])
        self.assertIsNone(self.state()['skillWorkflow']['selected'])
        self.assertNotIn('_guidanceDelivery', later_text)
        self.assertNotIn('revision', later['guidance'])
        self.assertEqual(64, len(self.state()['skillWorkflow']['guidanceDelivery']['revision']))
        self.assertLess(len(later_text), len(first_text) - 800)
        for text in ('한국어', '회사 필수 기준', '기존 권한/승인', '정확한 Read',
                     'fork·model·allowed-tools', '실제 거절·대기·실패', 'SELECT',
                     '인증된 본인 계정', '미검증 의무·재시도 한도', 'completionGuide'):
            self.assertIn(text, later['instructions'])

    def test_observed_same_body_reuses_but_restoration_reloads_full_guidance(self):
        self.output('HTML 보고서 만들어줘')
        self.f.read(discovery.PLUGIN / 'skills/html-report/SKILL.md')
        later, _ = self.output('HTML 보고서 만들어줘')
        self.assertEqual('reuse', later['skillExecution']['mode'])
        self.assertEqual('reuse', later['guidance']['mode'])
        with patch('company_agent.skill_execution.native_load_required', return_value=True):
            restricted, _ = self.output('HTML 보고서 만들어줘')
            self.assertEqual('host-loading-rules', restricted['skillExecution']['reason'])
            self.assertEqual('load', restricted['skillExecution']['mode'])
            self.assertEqual('full', restricted['guidance']['mode'])
        for source in ('compact', 'resume', 'startup'):
            with self.subTest(source=source):
                restored = self.f.context('', source=source)
                self.assertIn('skillIndex', restored['instructions'])
                self.assertNotIn('guidanceDelivery', self.state()['skillWorkflow'])
                following, _ = self.output('HTML 보고서 만들어줘')
                self.assertEqual('full', following['guidance']['mode'])
                self.assertEqual('load', following['skillExecution']['mode'])

    def test_runtime_policy_scope_and_profile_changes_restore_full_guidance(self):
        self.output()
        for key, value in (
            ('scope', 'Project'), ('cliCommand', 'changed-installed-command'),
            ('companyPolicy', {'status': 'available', 'revision': 'changed', 'rules': []}),
            ('knowledgeBase', str(self.f.root / 'different-knowledge')),
        ):
            with self.subTest(key=key):
                context = self.f.context('안녕')
                context[key] = value
                runtime, _ = self.output(context=context)
                self.assertEqual('full', runtime['guidance']['mode'])
                if key == 'companyPolicy':
                    self.assertIn('required', runtime['instructions'])
                self.output()  # Return to the original identity.
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.f.root / 'other-profile')}):
            runtime, _ = self.output()
            self.assertEqual('full', runtime['guidance']['mode'])

    def test_catalog_project_and_session_changes_restore_full_guidance(self):
        self.output()
        self.f.skill('new-reader', '새 문서 읽기')
        runtime, _ = self.output()
        self.assertEqual('full', runtime['guidance']['mode'])
        self.f.project = self.f.root / 'different-project'
        self.f.project.mkdir()
        runtime, _ = self.output()
        self.assertEqual('full', runtime['guidance']['mode'])
        self.f.sid = 'new-guidance-session'
        runtime, _ = self.output()
        self.assertEqual('full', runtime['guidance']['mode'])

    def test_missing_or_corrupt_output_metadata_falls_back_to_full(self):
        self.output()
        for invalid in (None, [], {'revision': 'bad'},
                        {'revision': 'a' * 64, 'evidence': 'host-received'}):
            with self.subTest(receipt=invalid):
                with _locked_session(self.f.sid, self.f.state) as (state, path):
                    state['skillWorkflow']['guidanceDelivery'] = invalid
                    atomic_write_json(path, state)
                runtime, _ = self.output()
                self.assertEqual('full', runtime['guidance']['mode'])
        with _locked_session(self.f.sid, self.f.state) as (state, path):
            state['skillWorkflow'] = None
            atomic_write_json(path, state)
        runtime, _ = self.output()
        self.assertEqual('full', runtime['guidance']['mode'])

    def test_changed_fixed_rules_and_incomplete_context_never_reuse(self):
        self.output()
        full = native_runtime._prompt_instructions
        with patch.object(native_runtime, '_prompt_instructions', side_effect=lambda runtime: full(runtime) + ' 새로운 기준.'):
            runtime, _ = self.output()
            self.assertEqual('full', runtime['guidance']['mode'])
        self.output()
        context = self.f.context('안녕')
        context['contextStatus'] = 'metadata-exceeds-budget'
        runtime, _ = self.output(context=context)
        self.assertEqual('full', runtime['guidance']['mode'])

    def test_failed_budget_does_not_publish_a_guidance_receipt(self):
        with patch.object(native_runtime, 'MAX_HOOK_CONTEXT_CHARS', 10):
            with self.assertRaises(ValueError):
                self.output()
        self.assertNotIn('guidanceDelivery', self.state()['skillWorkflow'])
        runtime, _ = self.output()
        self.assertEqual('full', runtime['guidance']['mode'])

    def test_long_paths_trim_duplicates_before_losing_a_discovery_type(self):
        command = '"C:/' + 'p' * 500 + '/python.exe" -B "C:/' + 's' * 500 + '/native_entry.py" cli'
        runtime = {
            'instructions': 'initial guidance ' * 300,
            'cliCommand': command, 'metadataCommand': command,
            'stateRoot': 'C:/Users/' + 'u' * 100 + '/state',
            'knowledgeMatches': [{'id': 'term.' + str(i), 'title': '조회' * 100,
                                  'path': 'C:/knowledge/test.md', 'hasOverlays': True} for i in range(3)],
            'preferredSkills': [{'name': 'reader-' + str(i), 'description': '업무 읽기 ' * 25} for i in range(3)],
            'personalSkills': [], 'skillSelection': {'conflicts': []},
            'companyPolicy': {'status': 'available', 'path': 'C:/policy.json',
                              'rules': [{'level': 'required', 'text': '회사 필수 기준'}]},
        }
        encoded = native_runtime._encode_base_runtime(runtime)
        result = json.loads(encoded)['company_agent_runtime']
        self.assertLessEqual(len(encoded), native_runtime.MAX_RUNTIME_BASE_CHARS)
        self.assertTrue(result['guidanceMinimal'])
        self.assertEqual(1, len(result['knowledgeMatches']))
        self.assertTrue(result['knowledgeMatches'][0]['hasOverlays'])
        self.assertEqual(1, len(result['preferredSkills']))
        self.assertEqual(command, result['cliCommand'])
        self.assertEqual('required', result['companyPolicy']['rules'][0]['level'])
        for rule in ('SELECT', 'required', '실제 거절', '권한', '미검증 의무'):
            self.assertIn(rule, result['instructions'])


if __name__ == '__main__':
    unittest.main()
