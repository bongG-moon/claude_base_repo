"""Offline authoring tests; do not claim a live Chrome or corporate login test."""
from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.browser_workflow import plan_web_workflow
from company_agent.cli import main
from company_agent.asset_factory import create_asset, validate_asset


def request():
    return {'name': 'weekly-applicants', 'purpose': '매주 교육 신청 현황 정리',
            'site': 'https://training.example.invalid/applicants',
            'fields': ['이름', '부서', '신청일'], 'output': 'table', 'maxRows': 50,
            'connection': 'reported_connected',
            'toolContract': {'server': 'approved-browser', 'tools': [
                {'name': 'read_table', 'inputSchema': {'type': 'object',
                 'properties': {'pageId': {'type': 'string'}}, 'required': ['pageId']}}]}}


def reported_trial(spec):
    result = plan_web_workflow(spec)
    spec['trial'] = {'status': 'passed', 'fingerprint': result['trialPlan']['fingerprint'],
                     'rowCount': 3, 'fieldsMatch': True}
    return spec


class WebWorkflowTests(unittest.TestCase):
    def test_questions_only_ask_missing_answers(self):
        result = plan_web_workflow({'purpose': '교육 신청 현황 정리'})
        self.assertEqual(['site', 'fields'], result['missing'])
        self.assertEqual(2, len(result['questions']))
        self.assertFalse(result['browserExecuted'])

    def test_missing_connection_does_not_invent_tools_or_create_asset(self):
        spec = request()
        spec.pop('connection')
        spec.pop('toolContract')
        result = plan_web_workflow(spec)
        self.assertEqual('connection_required', result['status'])
        self.assertNotIn('assetSpec', result)
        self.assertNotIn('trialPlan', result)

    def test_reported_connection_does_not_prove_live_connection(self):
        result = plan_web_workflow(request())
        self.assertEqual('trial_required', result['status'])
        self.assertEqual(5, result['trialPlan']['maxRows'])
        self.assertFalse(result['liveConnectionVerified'])
        self.assertEqual('caller-reported-metadata', result['evidenceBasis'])

    def test_empty_tool_metadata_requests_actual_tools(self):
        spec = request()
        spec.pop('toolContract')
        self.assertEqual('tools_required', plan_web_workflow(spec)['status'])

    def test_known_storage_is_reused_and_not_part_of_read_trial_hash(self):
        spec = reported_trial(request())
        result = plan_web_workflow(spec)
        self.assertEqual('storage_required', result['status'])
        self.assertEqual(['personal', 'project'], [v['value'] for v in result['options']])
        spec['storageScope'] = 'project'
        result = plan_web_workflow(spec)
        self.assertEqual('ready_to_save', result['status'])
        self.assertEqual('project', result['storageScope'])
        self.assertFalse(result['saved'])
        self.assertNotIn('tool_dependencies', result['assetSpec'])

    def test_generated_spec_uses_existing_asset_creator_without_mcp_registration(self):
        spec = reported_trial(request())
        spec['storageScope'] = 'project'
        asset = plan_web_workflow(spec)['assetSpec']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict('os.environ', {'CLAUDE_CONFIG_DIR': str(root / 'claude')}):
                path = create_asset(asset, root / 'project-state')
            self.assertTrue(validate_asset(path)['ok'])
            body = (path / 'SKILL.md').read_text(encoding='utf-8')
            self.assertIn('approved-browser', body)
            self.assertIn('read_table', body)
            self.assertIn('schemaHash', body)
            self.assertNotIn('reported_connected', body)
            self.assertFalse((root / 'claude/settings.json').exists())
            self.assertNotIn('mcpServers', body)

    def test_changed_contract_or_scope_requires_new_trial(self):
        base = reported_trial(request())
        for key, value in [('site', 'https://other.example.invalid/page'),
                           ('fields', ['부서']), ('maxRows', 100), ('filter', '이번 달')]:
            spec = copy.deepcopy(base)
            spec[key] = value
            with self.subTest(key=key):
                self.assertEqual('trial_required', plan_web_workflow(spec)['status'])
        spec = copy.deepcopy(base)
        spec['toolContract']['tools'][0]['inputSchema']['required'] = []
        self.assertEqual('trial_required', plan_web_workflow(spec)['status'])

    def test_tool_order_does_not_invalidate_trial(self):
        spec = request()
        spec['toolContract']['tools'].append({'name': 'list_tabs', 'inputSchema': {'type': 'object'}})
        reported_trial(spec)
        spec['toolContract']['tools'].reverse()
        spec['storageScope'] = 'personal'
        self.assertEqual('ready_to_save', plan_web_workflow(spec)['status'])

    def test_failed_trial_and_auth_failures_do_not_silently_switch_routes(self):
        spec = reported_trial(request())
        spec['trial']['status'] = 'failed'
        self.assertEqual('trial_failed', plan_web_workflow(spec)['status'])
        for state, expected in [('denied', 'permission_denied'), ('login_required', 'login_required'),
                                ('disconnected', 'connection_required')]:
            spec['connection'] = state
            result = plan_web_workflow(spec)
            self.assertEqual(expected, result['status'])
            self.assertNotIn('assetSpec', result)

    def test_empty_results_can_be_valid_but_bool_count_is_not(self):
        spec = reported_trial(request())
        spec['storageScope'] = 'personal'
        spec['trial']['rowCount'] = 0
        self.assertEqual('ready_to_save', plan_web_workflow(spec)['status'])
        for count in [True, -1, 6, '3']:
            spec['trial']['rowCount'] = count
            with self.assertRaises(ValueError):
                plan_web_workflow(spec)

    def test_do_not_echo_secret_or_accept_arbitrary_request_data(self):
        for field, value in [('headers', {'Authorization': 'Bearer SUPER_SECRET'}),
                             ('script', 'fetch()'), ('purpose', 'api_key=SUPER_SECRET'),
                             ('site', 'https://user:SUPER_SECRET@training.example.invalid'),
                             ('site', 'https://training.example.invalid?token=SUPER_SECRET'),
                             ('site', 'https://training.example.invalid/#SUPER_SECRET')]:
            spec = request()
            spec[field] = value
            with self.assertRaises(ValueError) as caught:
                plan_web_workflow(spec)
            self.assertNotIn('SUPER_SECRET', str(caught.exception))
        for name in ['password', 'Authorization', '비밀번호', '토큰']:
            spec = request()
            spec['fields'] = [name]
            with self.assertRaises(ValueError):
                plan_web_workflow(spec)

    def test_invalid_shapes_are_bounded_errors_not_type_tracebacks(self):
        for field, value in [('output', []), ('storageScope', {}), ('connection', []),
                             ('maxRows', True), ('fields', ['']), ('toolContract', {'tools': []})]:
            spec = request()
            spec[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                plan_web_workflow(spec)

    def test_cli_does_not_require_state_or_session_and_waiting_is_not_an_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['asset', 'web-plan'])
        self.assertEqual(0, code)
        self.assertEqual('input_required', json.loads(output.getvalue())['status'])

    def test_cli_rejects_large_input_and_invalid_json_without_content(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'spec.json'
            for value in ['SUPER_SECRET', ' ' * 65537]:
                file.write_text(value, encoding='utf-8')
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = main(['asset', 'web-plan', '--spec', str(file)])
                self.assertEqual(1, code)
                self.assertNotIn('SUPER_SECRET', err.getvalue())

    def test_missing_spec_has_one_korean_action_not_a_traceback(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(err):
            code = main(['asset', 'web-plan', '--spec', str(Path(temp)/'missing.json')])
        self.assertEqual(1, code)
        self.assertIn('파일 위치와 읽기 권한', json.loads(err.getvalue())['error'])
        self.assertNotIn('Traceback', err.getvalue())

    def test_planner_does_not_create_a_stop_obligation_or_grant_permission(self):
        from company_agent.execution_contract import classify_command, safe_permission
        from company_agent.state import begin_turn, record_activity, stop_decision
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}"'
            for args in ['asset web-plan', 'asset web-plan --help',
                         f'asset web-plan --spec "{root / "request.json"}"']:
                command = prefix + ' ' + args
                self.assertEqual('read_only', classify_command(command))
                permission = safe_permission({'hook_event_name': 'PermissionRequest',
                    'tool_name': 'Bash', 'tool_input': {'command': command}}, root)
                # Existing exact-help policy approves shipped help text only;
                # planning user metadata does not gain automatic permission.
                self.assertEqual({'behavior': 'allow'} if args.endswith('--help') else None, permission)
            self.assertEqual('unknown', classify_command(prefix + ' asset web-plan --execute'))
            self.assertEqual('unknown', classify_command(prefix + ' asset web-plan; echo changed'))
            begin_turn('web-plan-test', 'SMALL', False, [], root)
            state = record_activity({'session_id': 'web-plan-test', 'hook_event_name': 'PostToolUse',
                'tool_name': 'Bash', 'tool_input': {'command': prefix + ' asset web-plan'},
                'tool_response': {'stdout': '{"status":"input_required"}'}}, root)
            self.assertEqual(0, state['mutationCount'])
            self.assertEqual({}, stop_decision({'session_id': 'web-plan-test'}, root))


class WebAuthoringRoutingTests(unittest.TestCase):
    def setUp(self):
        import test_skill_discovery as discovery
        self.fixture = discovery.SkillDiscoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.plugin = discovery.PLUGIN

    def inventory(self, **options):
        from company_agent.skill_registry import inventory_skills
        return inventory_skills(self.fixture.state, project_root=self.fixture.project,
                                plugin_root=self.plugin, claude_root=self.fixture.claude, **options)

    def decision(self, inventory, prompt):
        from company_agent.skill_task_context import task_candidates
        from company_agent.skill_decision import decide_preparation
        hints = task_candidates(inventory, prompt)
        return hints, decide_preparation(hints, inventory['skills'], [])

    def test_authoring_uses_existing_owner_without_stealing_html_or_ppt_requests(self):
        inventory = self.inventory()
        expected = {item['name']: item['id'] for item in inventory['skills']}
        for prompt, owner in [('크롬에서 신청 현황을 정리하는 스킬 만들어줘', 'asset-factory'),
                              ('웹페이지의 표를 읽는 스킬을 만들어줘', 'asset-factory'),
                              ('HTML 보고서 만들어줘', 'html-report'),
                              ('교육 과정 안내 PPT 6장 만들어줘', 'presentation')]:
            with self.subTest(prompt=prompt):
                hints, decision = self.decision(inventory, prompt)
                self.assertEqual(expected[owner], decision.candidate_id, (decision, hints))

    def test_sentence_boundary_keeps_authoring_distinct_from_later_reuse(self):
        from company_agent.skill_task_context import _features
        self.assertEqual(({'assets'}, {'make'}),
                         _features('업무 도구를 만듭니다. 기존 도구 재사용을 확인합니다.'))
        self.assertEqual(({'html'}, {'make'}), _features('스킬을 사용해서 HTML 보고서를 만들어줘'))

    def test_actual_runtime_receives_authoring_owner_without_support_competition(self):
        from company_agent.skill_execution import prepare_execution
        runtime = self.fixture.context('크롬에서 신청 현황을 정리하는 스킬 만들어줘')
        execution, _ = prepare_execution(runtime)
        self.assertEqual('load', execution['mode'])
        self.assertEqual('asset-factory', execution['name'])
        self.assertNotIn('competingIds', runtime['taskSkills'])
        self.assertNotIn('karpathy-guidelines',
                         [group['name'] for group in runtime['taskSkills']['groups']])

    def test_explicit_project_harness_and_support_invocations_remain_available(self):
        inventory = self.inventory()
        expected = {item['name']: item['id'] for item in inventory['skills']}
        for prompt, owner in [
                ('/company-agent:project-harness 프로젝트 작업 구조 만들어줘', 'project-harness'),
                ('project-harness 스킬을 사용해 프로젝트 작업 구조 만들어줘', 'project-harness'),
                ('/company-agent:karpathy-guidelines 개발 지침 확인', 'karpathy-guidelines'),
                ('karpathy-guidelines 스킬을 사용해 개발 범위를 검토해줘', 'karpathy-guidelines')]:
            with self.subTest(prompt=prompt):
                hints, decision = self.decision(inventory, prompt)
                self.assertEqual(expected[owner], decision.candidate_id, (decision, hints))
                self.assertEqual('explicit-choice', decision.reason)

    def test_real_alternative_authoring_workflow_still_requires_a_choice(self):
        self.fixture.skill('web-skill-author', '웹 업무 스킬을 만들고 수정합니다.')
        inventory = self.inventory()
        expected = {item['id'] for item in inventory['skills']
                    if item['name'] in {'asset-factory', 'web-skill-author'}}
        hints, decision = self.decision(inventory, '웹페이지의 표를 읽는 스킬을 만들어줘')
        self.assertEqual('choose', decision.mode)
        self.assertEqual('competing-workflows', decision.reason)
        self.assertEqual(expected, set(decision.choice_ids))
        from company_agent.skill_task_context import MAX_TASK_SKILL_CHARS
        self.assertLessEqual(len(json.dumps(hints, ensure_ascii=False)), MAX_TASK_SKILL_CHARS)

    def test_same_name_personal_and_company_authoring_workflows_remain_alternatives(self):
        self.fixture.skill('asset-factory', '개인 업무 스킬을 만들고 수정합니다.')
        inventory = self.inventory()
        expected = {item['id'] for item in inventory['skills'] if item['name'] == 'asset-factory'}
        self.assertEqual(2, len(expected))
        hints, decision = self.decision(inventory, '크롬에서 신청 현황을 정리하는 스킬 만들어줘')
        self.assertEqual('choose', decision.mode)
        self.assertEqual(expected, set(decision.choice_ids))

    def test_support_metadata_survives_cache_hits_and_refreshes_after_role_edit(self):
        from company_agent import skill_registry
        self.fixture.skill('authoring-advice', '업무 스킬을 만들고 검토하는 지침입니다.',
                           extra='company-agent-role: support\n')
        uncached = self.inventory()
        first = self.inventory(metadata_cache=True)
        self.assertEqual(uncached, first)
        with patch.object(skill_registry, '_read', wraps=skill_registry._read) as read:
            warm = self.inventory(metadata_cache=True)
        self.assertEqual(first, warm)
        self.assertFalse(any(call.args[0].name == 'SKILL.md' for call in read.call_args_list))
        advice = next(item for item in warm['skills'] if item['name'] == 'authoring-advice')
        self.assertEqual('support', advice['role'])
        hints, decision = self.decision(warm, '웹 업무 스킬 만들어줘')
        self.assertEqual('load', decision.mode)
        self.assertNotIn(advice['id'], hints.get('competingIds', []))

        self.fixture.skill('authoring-advice', '업무 스킬을 만들고 검토하는 지침입니다.')
        changed = self.inventory(metadata_cache=True)
        advice = next(item for item in changed['skills'] if item['name'] == 'authoring-advice')
        self.assertEqual('workflow', advice['role'])
        _, decision = self.decision(changed, '웹 업무 스킬 만들어줘')
        self.assertEqual('choose', decision.mode)
        self.assertIn(advice['id'], decision.choice_ids)

    def test_legacy_cache_without_role_is_reparsed_instead_of_losing_support_role(self):
        self.inventory(metadata_cache=True)
        file = self.fixture.state / 'cache/skill-metadata-v1.json'
        cache = json.loads(file.read_text(encoding='utf-8'))
        for entry in cache['entries'].values():
            entry['metadata'].pop('role')
        file.write_text(json.dumps(cache), encoding='utf-8')
        refreshed = self.inventory(metadata_cache=True)
        advice = next(item for item in refreshed['skills'] if item['name'] == 'karpathy-guidelines')
        self.assertEqual('support', advice['role'])
        _, decision = self.decision(refreshed, '웹 업무 스킬 만들어줘')
        self.assertEqual('load', decision.mode)
        self.assertEqual('asset-factory', next(item['name'] for item in refreshed['skills']
                                             if item['id'] == decision.candidate_id))


if __name__ == '__main__':
    unittest.main()
