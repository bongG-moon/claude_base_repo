"""Cheap selection, independent action briefs, and read-only diagnostics."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_skill_discovery as discovery
from company_agent.skill_task_context import task_candidates, skill_brief, MAX_SKILL_BRIEF_CHARS, TASK_SKILL_RULE
from company_agent.native_runtime import task_prompt_context
from company_agent.paths import atomic_write_json
from company_agent.skill_workflow import observe
from company_agent.state import load_session
from company_agent.routing_diagnostics import inspect


class LeanRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = discovery.SkillDiscoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def names(self, prompt):
        return [g['name'] for g in self.f.context(prompt)['taskSkills']['groups']]

    def test_document_read_does_not_promote_harness_mail_or_creation(self):
        for prompt in ('@테스트자료.pptx 이 자료 내용 확인해서 정리해줄 수 있을까?',
                       'PPT 내용을 읽고 md파일로 요약해줘', 'Read and summarize this PowerPoint'):
            with self.subTest(prompt=prompt):
                self.assertEqual(['office-reader'], self.names(prompt))

    def test_new_ppt_and_multi_step_request(self):
        self.assertEqual(['presentation'], self.names('월간 실적 PPT를 새로 만들어줘'))
        names = self.names('기존 PPT 내용을 읽고 새 PPT를 만들어줘')
        self.assertIn('office-reader', names)
        self.assertIn('presentation', names)

    def test_extension_is_not_dispatch_for_file_organization(self):
        names = self.names('PPT 파일을 다른 폴더로 이동해줘')
        self.assertIn('file-organizer', names)
        self.assertNotIn('office-reader', names)

    def test_ordinary_document_read_does_not_reload_catalogue(self):
        from unittest.mock import patch
        self.f.context()
        with patch('company_agent.skill_workflow._snapshot', side_effect=AssertionError('unexpected catalogue IO')):
            observe(self.f.state, self.f.project, {'hook_event_name': 'PostToolUse', 'session_id': self.f.sid,
                'tool_name': 'Read', 'tool_input': {'file_path': str(self.f.project / 'report.md')}, 'tool_response': {'success': True}})

    def test_different_named_personal_alternative_not_silently_hidden(self):
        self.f.skill('team-reader', 'PPT 내용을 읽고 요약하는 개인 스킬')
        self.assertIn('team-reader', self.names('PPT 읽고 요약해줘'))
        self.f.skill('general-reader', '업무 문서 읽기 및 요약')
        self.assertIn('general-reader', self.names('PPT 읽고 요약해줘'))

    def test_brief_is_self_contained_on_reuse_and_not_duplicated(self):
        self.f.context(source='startup')
        ctx = self.f.context('PPT 읽고 요약해줘')
        self.assertEqual('reuse', ctx['skillIndex']['mode'])
        result = task_prompt_context('{"company_agent_route":{}}', json.dumps({'company_agent_runtime': ctx}, ensure_ascii=False))
        brief = result.split('\n{"company_agent_route"')[0]
        self.assertIn('company-agent:office-reader', brief)
        self.assertIn(str(discovery.PLUGIN / 'skills/office-reader/SKILL.md').replace('\\', '\\\\'), brief)
        tail = json.loads(result.splitlines()[-1])['company_agent_runtime']
        self.assertNotIn('groups', tail['taskSkills'])
        self.assertNotIn(TASK_SKILL_RULE, tail['instructions'])
        self.assertLessEqual(len(brief), MAX_SKILL_BRIEF_CHARS)
        self.assertNotIn('Presentations.Open', result)
        from company_agent.native_runtime import worker_runtime_input
        worker = worker_runtime_input(discovery.PLUGIN, self.f.project, {'session_id': self.f.sid,
            'tool_input': {'subagent_type': 'company-agent:medium-worker', 'prompt': 'PPT 읽기'}})
        worker_text = worker['hookSpecificOutput']['updatedInput']['prompt']
        self.assertIn('skillCatalog.path', worker_text)
        self.assertNotIn('"groups":', worker_text)

    def test_large_conflict_requires_catalogue_not_partial_choice(self):
        rows = [{'id': str(i), 'source': str(i), 'path': 'C:/' + 'a' * 500 + '/SKILL.md'} for i in range(10)]
        brief = skill_brief({'taskSkills': {'groups': [{'name': 'reader', 'resolution': 'unresolved', 'candidates': rows}]}})
        self.assertLessEqual(len(brief), MAX_SKILL_BRIEF_CHARS)
        self.assertNotIn('"source":"0"', brief)
        self.assertIn('skillSelection.catalog.path', brief)

    def test_unrecognized_skill_response_records_reason_not_success_or_payload(self):
        self.f.context()
        payload = {'hook_event_name': 'PostToolUse', 'session_id': self.f.sid, 'tool_name': 'Skill',
                   'tool_input': {'skill': 'company-agent:office-reader'}, 'tool_response': {'text': 'PRIVATE-BODY'}}
        observe(self.f.state, self.f.project, payload)
        state = load_session(self.f.sid, self.f.state)
        self.assertEqual('response-unrecognized', state['skillWorkflow']['loadObservation']['status'])
        self.assertNotIn('lastBodyLoad', state['skillWorkflow'])
        self.assertNotIn('PRIVATE-BODY', json.dumps(state))
        observe(self.f.state, self.f.project, {**payload, 'tool_response': {'success': True}})
        self.assertEqual('loaded', load_session(self.f.sid, self.f.state)['skillWorkflow']['loadObservation']['status'])
        self.f.context('다음 질문')
        self.assertEqual('not-observed', load_session(self.f.sid, self.f.state)['skillWorkflow']['loadObservation']['status'])

    def test_partial_read_distinguished_from_bad_shape(self):
        self.f.context()
        file = discovery.PLUGIN / 'skills/office-reader/SKILL.md'
        payload = {'hook_event_name': 'PostToolUse', 'session_id': self.f.sid, 'tool_name': 'Read',
                   'tool_input': {'file_path': str(file)}}
        observe(self.f.state, self.f.project, {**payload, 'tool_response': {'text': 'wrong-shape'}})
        self.assertEqual('read-response-unrecognized', load_session(self.f.sid, self.f.state)['skillWorkflow']['loadObservation']['status'])
        observe(self.f.state, self.f.project, {**payload, 'tool_response': {'file': {'content': file.read_text(encoding='utf-8-sig').splitlines()[0], 'startLine': 1}}})
        self.assertEqual('partial-read', load_session(self.f.sid, self.f.state)['skillWorkflow']['loadObservation']['status'])


class ReadOnlyDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.claude = self.root / 'claude'
        self.local = self.root / 'local'
        self.project = self.root / 'project'
        self.project.mkdir()
        self.state = self.root / 'state'
        atomic_write_json(self.claude / 'plugins/installed_plugins.json', {'plugins': {'company-agent@company-agent-local': [
            {'scope': 'user', 'version': '1.4.10', 'installPath': str(self.root / 'plugin'), 'SECRET': 'PRIVATE'}]}})
        atomic_write_json(self.claude / 'settings.json', {'enabledPlugins': {'company-agent@company-agent-local': True}, 'env': {'API_KEY': 'PRIVATE'}})
        self.rec = {'schemaVersion': 1, 'coreVersion': '1.4.10', 'scope': 'User', 'claudeConfigRoot': str(self.claude), 'userStateRoot': str(self.state)}
        atomic_write_json(self.local / 'CompanyAgent/installations/user/company-agent-install.json', self.rec)
        atomic_write_json(self.state / 'sessions/example.json', {'turnId': 'one', 'prompt': 'PRIVATE', 'hookDiagnostics': {
            'UserPromptSubmit': {'status': 'output-produced', 'elapsedMs': 234, 'candidateNames': ['office-reader'], 'raw': 'PRIVATE'}},
            'skillWorkflow': {'loadObservation': {'status': 'response-unrecognized', 'turn': 'one'}}})

    def snapshot(self):
        return {str(f): (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_mtime_ns) for f in self.root.rglob('*') if f.is_file()}

    def test_read_only_private_and_no_claim_of_host_receipt(self):
        before = self.snapshot()
        report = inspect(self.claude, self.local, self.project)
        self.assertEqual(before, self.snapshot())
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual('response-unrecognized', report['sessions'][0]['loadStatus'])
        self.assertEqual('not-observable', report['effectiveHostSettings'])
        self.assertEqual(str(self.state), report['selectedStateRoot'])

    def test_cli_is_read_only_utf8_and_runs_without_harness_activation(self):
        before = self.snapshot()
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(discovery.PLUGIN / 'scripts/diagnose_skill_routing.py'),
            '--claude-root', str(self.claude), '--local-appdata', str(self.local), '--project-root', str(self.project)],
            capture_output=True, encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'cp949'})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Skill 응답 형식 확인 필요', result.stdout)
        self.assertNotIn('PRIVATE', result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_project_state_wins_but_unrelated_projects_do_not(self):
        project_state = self.root / 'project-state'
        atomic_write_json(project_state / 'sessions/other.json', {})
        atomic_write_json(self.local / 'CompanyAgent/installations/projects/one/company-agent-install.json',
                          {**self.rec, 'scope': 'Project', 'projectRoot': str(self.project), 'userStateRoot': str(project_state)})
        report = inspect(self.claude, self.local, self.project)
        self.assertEqual(str(project_state), report['selectedStateRoot'])
        self.assertEqual(str(self.state), inspect(self.claude, self.local, self.root)['selectedStateRoot'])

    def test_missing_or_malformed_records_do_not_initialize_state(self):
        before = self.snapshot()
        report = inspect(self.root / 'absent', self.root / 'missing', self.project)
        self.assertTrue(report['warnings'])
        self.assertEqual(before, self.snapshot())
        with self.assertRaises(ValueError):
            inspect(self.claude, self.local, self.project, '../secret')

    def test_native_project_activation_matches_runtime_not_just_record_depth(self):
        project_state = self.root / 'project-state'
        project_rec = {**self.rec, 'scope': 'Project', 'nativeClaudeScope': 'local',
                       'projectRoot': str(self.project), 'userStateRoot': str(project_state)}
        path = self.local / 'CompanyAgent/installations/projects/one/company-agent-install.json'
        atomic_write_json(path, project_rec)
        atomic_write_json(self.claude / 'plugins/installed_plugins.json', {'plugins': {'company-agent@company-agent-local': [
            {'scope': 'user'}, {'scope': 'local', 'projectPath': str(self.project)}]}})
        settings = self.project / '.claude/settings.local.json'
        for enabled in (False, True):
            atomic_write_json(settings, {'enabledPlugins': {'company-agent@company-agent-local': enabled}})
            state = project_state if enabled else self.state
            self.assertEqual(str(state), inspect(self.claude, self.local, self.project)['selectedStateRoot'])
        for invalid in ({'schemaVersion': 2}, {'enabled': False}, {'claudeConfigDirOverride': True}):
            atomic_write_json(path, {**project_rec, **invalid})
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': ''}):
                self.assertEqual(str(self.state), inspect(self.claude, self.local, self.project)['selectedStateRoot'])

    def test_stale_load_is_not_reported_as_current_success(self):
        atomic_write_json(self.state / 'sessions/example.json', {'turnId': 'two', 'skillWorkflow': {
            'lastBodyLoad': {'name': 'office-reader'}, 'loadObservation': {'status': 'loaded', 'turn': 'one'}}})
        self.assertEqual('unknown', inspect(self.claude, self.local, self.project)['sessions'][0]['loadStatus'])


if __name__ == '__main__':
    unittest.main()
