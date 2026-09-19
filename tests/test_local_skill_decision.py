"""Offline decision/evidence tests, not claims about HCP model adherence."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_skill_execution as execution
import test_skill_discovery as discovery
import test_lean_routing as routing
from company_agent.paths import atomic_write_json
from company_agent.diagnostic_report import render_report
from company_agent.skill_decision import SkillDecision, decide_preparation, NEXT_ACTIONS
from company_agent.skill_execution import prepare_execution
from company_agent.state import record_activity, stop_decision
from company_agent.workflow_evidence import workflow_progress, MAX_RESULT_CHARS


def hints(candidate='reader', **changes):
    return {'status': 'candidates', 'matchingGroups': 1, 'groups': [
        {'name': 'reader', 'resolution': 'available', 'candidates': [{'id': candidate}]}], **changes}


class LocalDecisionTests(unittest.TestCase):
    def test_finite_decisions_distinguish_none_unknown_conflict_and_complementary_work(self):
        skills = [{'id': 'reader'}]
        cases = [
            ({}, [], 'general'),
            ({}, skills, 'review'),
            ({'status': 'incomplete'}, skills, 'inspect'),
            (hints(status='needs-choice'), skills, 'choose'),
            (hints(matchingGroups=2), skills, 'select'),
            (hints(moreInCatalog=True), skills, 'select'),
            (hints(), skills, 'load'),
            (hints('invented'), skills, 'inspect'),
            (hints(), skills + skills, 'inspect'),
            ({'groups': 'malformed'}, skills, 'inspect'),
            ({'groups': [None]}, skills, 'inspect'),
            ({'groups': [{'candidates': None}], 'matchingGroups': 1}, skills, 'inspect'),
            (hints(matchingGroups=True), skills, 'select'),
        ]
        for hint, rows, expected in cases:
            with self.subTest(expected=expected, hint=hint):
                before = copy.deepcopy((hint, rows))
                with patch.object(Path, 'open', side_effect=AssertionError('no I/O')), \
                     patch('socket.socket', side_effect=AssertionError('no network')):
                    answer = decide_preparation(hint, rows, [])
                self.assertEqual(expected, answer.mode)
                self.assertEqual(before, (hint, rows))
                self.assertIn(answer.mode, NEXT_ACTIONS)
                self.assertNotIn('confidence', answer.plan())

    def test_manual_or_incoming_candidates_are_not_forced(self):
        manual = {'id': 'manual', 'invocation': 'company:manual', 'explicitOnly': True}
        self.assertEqual('general', decide_preparation(hints('manual'), [manual], []).mode)
        self.assertEqual('load', decide_preparation(hints('manual'), [manual], ['company:manual']).mode)
        self.assertEqual('inspect', decide_preparation(hints('manual'), [{'id': 'reader'}, manual], []).mode)
        self.assertEqual('general', decide_preparation(hints(), [{'id': 'reader', 'incoming': True}], []).mode)

    def test_invalid_or_fabricated_decision_shape_is_rejected(self):
        for mode, reason, candidate in [('execute', 'test', None), ('load', 'test', None),
                                        ('general', 'test', 'invented'), ('review', '', None)]:
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    SkillDecision(mode, reason, candidate)


class LocalDecisionIntegrationTests(unittest.TestCase):
    setUp = execution.SkillExecutionTests.setUp
    output = execution.SkillExecutionTests.output
    state = execution.SkillExecutionTests.state

    def command(self, operation='office-read'):
        cli = discovery.PLUGIN / 'scripts/harness_cli.py'
        return f'"{sys.executable}" -B "{cli}" business {operation} --file "{self.f.project / "PRIVATE.pptx"}"'

    def activity(self, result=None, **changes):
        payload = {'session_id': self.f.sid, 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                   'tool_input': {'command': self.command()},
                   'tool_response': {'stdout': json.dumps(result if result is not None else {'ok': True, 'status': 'read'}), 'exitCode': 0}}
        payload.update(changes)
        return record_activity(payload, self.f.state)

    def test_forged_candidate_never_becomes_a_load_or_general_absence(self):
        ctx = self.f.context()
        ctx['taskSkills'] = hints('invented')
        result, _ = prepare_execution(ctx)
        self.assertEqual('inspect', result['mode'])
        self.assertEqual('candidate-not-eligible', result['reason'])
        self.assertNotIn('path', result)

    def test_candidate_metadata_cannot_replace_current_catalogue_identity(self):
        ctx = self.f.context()
        candidate = ctx['taskSkills']['groups'][0]['candidates'][0]
        candidate.update(path='C:/PRIVATE/invented.md', invocation='invented', name='invented')
        result, _ = prepare_execution(ctx)
        self.assertEqual('load', result['mode'])
        self.assertEqual('office-reader', result['name'])
        self.assertNotIn('invented', json.dumps(result))

    def test_every_preparation_mode_has_a_concrete_next_action(self):
        for prompt, expected in [('PPT 내용 읽어줘', 'load'), ('2 더하기 3', 'review')]:
            ctx, _ = self.output(prompt)
            self.assertEqual(expected, ctx['skillExecution']['mode'])
            self.assertEqual(NEXT_ACTIONS[expected], ctx['skillWorkflow']['nextAction'])
        self.f.skill('office-reader', 'PPT 내용 읽기')
        ctx, _ = self.output()
        self.assertEqual('ask-skill-choice', ctx['skillWorkflow']['nextAction'])

    def test_body_loading_alone_never_claims_execution_or_quality(self):
        self.output()
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        progress = workflow_progress(self.state())
        self.assertEqual('loaded', progress['body'])
        self.assertEqual('not-observed', progress['execution'])
        self.assertEqual('not-verified', progress['skillApplication'])
        self.assertEqual('not-verified', progress['resultQuality'])

    def test_known_runtime_result_is_separate_from_load_and_verification(self):
        self.output()
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        before = self.state()
        state = self.activity({'ok': True, 'status': 'read', 'items': [{'text': 'PRIVATE-DOCUMENT'}]})
        progress = workflow_progress(state)
        self.assertEqual('reported-success', progress['execution'])
        self.assertEqual('office-read', progress['operation'])
        self.assertEqual('loaded', progress['bodyAtResponse'])
        self.assertEqual('not-verified', progress['resultQuality'])
        self.assertEqual(before['verification'], state['verification'])
        self.assertEqual(before['mutationCount'], state['mutationCount'])
        self.assertNotIn('PRIVATE', json.dumps(state))
        self.assertEqual({}, stop_decision({'session_id': self.f.sid}, self.f.state))

    def test_execution_without_body_does_not_fabricate_skill_use(self):
        self.output()
        state = self.activity()
        self.assertEqual('reported-success', workflow_progress(state)['execution'])
        self.assertEqual('not-observed', workflow_progress(state)['bodyAtResponse'])
        self.assertEqual({}, state['skillWorkflow']['readSkills'])
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        self.assertEqual('not-observed', workflow_progress(self.state())['bodyAtResponse'])

    def test_runtime_partial_cancel_and_input_wait_are_not_success_or_retry_authorization(self):
        self.output()
        for status in ('partial', 'cancelled', 'blocked', 'input_required'):
            with self.subTest(status=status):
                progress = workflow_progress(self.activity({'ok': True, 'status': status}))
                self.assertEqual(status.replace('_', '-'), progress['execution'])
        self.assertEqual('failed', workflow_progress(self.activity({'ok': False}))['execution'])
        self.assertEqual('failed', workflow_progress(self.activity(tool_response={'stdout': '{"ok":true}', 'exitCode': 1}))['execution'])

    def test_denial_is_not_execution_and_never_clears_existing_mutation_obligations(self):
        self.output()
        record_activity({'session_id': self.f.sid, 'tool_name': 'Write', 'tool_input': {'file_path': 'existing.md'}}, self.f.state)
        before = self.state()['mutationCount']
        payload = {'hook_event_name': 'PostToolUseFailure',
                   'error': 'Permission for this tool use was denied. The action was NOT performed.'}
        state = self.activity(**payload)
        self.assertEqual('not-performed', workflow_progress(state)['execution'])
        self.assertEqual(before, state['mutationCount'])
        self.assertIsNone(state['verification'])

    def test_unknown_large_or_truncated_response_does_not_trigger_reads_or_success(self):
        self.output()
        for response in ({'stdout': 'not JSON'}, {'stdout': '[]'}, {'stdout': '{}'},
                         {'stdout': '{"ok":true}' + ' ' * MAX_RESULT_CHARS},
                         {'output_file': 'PRIVATE/result.json'}, None):
            state = self.activity(tool_response=response)
            self.assertEqual('result-unavailable', workflow_progress(state)['execution'])
            self.assertNotIn('PRIVATE', json.dumps(state))

    def test_help_discovery_unrelated_shell_and_worker_launch_are_not_business_results(self):
        self.output()
        commands = [self.command() + ' --help', self.command() + ' | more',
                    'python -c "print(1)"', self.command('doctor'),
                    f'"{self.f.project / "harness_cli.py"}" business office-read --file x.pptx']
        for cmd in commands:
            state = self.activity(tool_input={'command': cmd})
            self.assertEqual('not-observed', workflow_progress(state)['execution'])
        state = self.activity(tool_name='Agent', tool_input={'subagent_type': 'company-agent:medium-worker'})
        self.assertEqual('not-observed', workflow_progress(state)['execution'])

    def test_new_turn_and_compaction_do_not_reuse_execution_results(self):
        self.output()
        self.f.read(discovery.PLUGIN / 'skills/office-reader/SKILL.md')
        self.activity()
        self.output()
        progress = workflow_progress(self.state())
        self.assertEqual('reused', progress['body'])
        self.assertEqual('not-observed', progress['execution'])
        self.assertNotIn('businessObservation', self.state()['skillWorkflow'])
        self.f.context(source='compact')
        self.assertEqual('not-observed', workflow_progress(self.state())['body'])

    def test_observer_failure_never_blocks_business_or_creates_retries(self):
        self.output()
        with patch('company_agent.workflow_evidence.observe_business_result', side_effect=ValueError('PRIVATE')):
            state = self.activity()
        self.assertEqual('not-observed', workflow_progress(state)['execution'])
        self.assertEqual({}, stop_decision({'session_id': self.f.sid}, self.f.state))

    def test_evidence_is_latest_bounded_and_not_added_to_model_context(self):
        self.output()
        self.activity({'ok': False, 'error': 'PRIVATE'})
        state = self.activity()
        evidence = state['skillWorkflow']['businessObservation']
        self.assertLess(len(json.dumps(evidence)), 250)
        self.assertEqual({'turn', 'operation', 'status', 'bodyAtResponse'}, set(evidence))
        _, text = self.output()
        self.assertNotIn('businessObservation', text)
        self.assertNotIn('workflowProgress', text)
        self.assertLess(len(text), 5000)

    def test_corrupt_diagnostic_fields_are_not_exported(self):
        state = {'turnId': 'now', 'skillWorkflow': {'turn': 'now', 'executionPlan': {'mode': ['PRIVATE']},
                 'businessObservation': {'turn': 'now', 'operation': 'PRIVATE', 'status': ['PRIVATE'], 'bodyAtResponse': 'PRIVATE'}}}
        self.assertNotIn('PRIVATE', json.dumps(workflow_progress(state)))
        state['skillWorkflow']['businessObservation']['operation'] = 'office-read'
        self.assertEqual('not-observed', workflow_progress(state)['execution'])


class LocalDecisionDiagnosticTests(unittest.TestCase):
    setUp = routing.ReadOnlyDiagnosticTests.setUp
    snapshot = routing.ReadOnlyDiagnosticTests.snapshot

    def test_diagnostic_json_and_html_separate_load_execution_and_quality(self):
        sha = 'a' * 64
        atomic_write_json(self.state / 'sessions/example.json', {'turnId': 'one', 'skillWorkflow': {
            'turn': 'one', 'executionPlan': {'mode': 'load'},
            'selected': {'id': 'reader', 'sha256': sha}, 'readSkills': {'reader': sha},
            'lastBodyLoad': {'turn': 'one', 'id': 'reader', 'sha256': sha},
            'businessObservation': {'turn': 'one', 'operation': 'office-read',
                                    'status': 'partial', 'bodyAtResponse': 'loaded', 'raw': 'PRIVATE'}}})
        before = self.snapshot()
        report = routing.inspect(self.claude, self.local, self.project)
        self.assertEqual(before, self.snapshot())
        progress = report['sessions'][0]['workflowProgress']
        self.assertEqual('loaded', progress['body'])
        self.assertEqual('partial', progress['execution'])
        self.assertEqual('not-verified', progress['resultQuality'])
        html = render_report(report)
        self.assertIn('실행기 부분 완료 보고', html)
        self.assertIn('실행 응답 시 본문 상태', html)
        self.assertNotIn('PRIVATE', html + json.dumps(report))

    def test_old_or_stale_observations_do_not_become_current_results(self):
        for state in ({}, {'turnId': 'two', 'skillWorkflow': {'turn': 'one', 'executionPlan': {'mode': 'load'},
                      'businessObservation': {'turn': 'one', 'operation': 'office-read', 'status': 'reported-success'}}}):
            atomic_write_json(self.state / 'sessions/example.json', state)
            progress = routing.inspect(self.claude, self.local, self.project)['sessions'][0]['workflowProgress']
            self.assertEqual('unknown', progress['decision'])
            self.assertEqual('not-observed', progress['execution'])


if __name__ == '__main__':
    unittest.main()
