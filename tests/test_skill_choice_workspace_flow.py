"""Workspace answers through native hooks; no model, process or personal profile."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))

import native_entry
import test_skill_execution as execution
import test_skill_discovery as discovery
from company_agent.paths import atomic_write_text
from company_agent.skill_registry import inventory_skills
from company_agent.state import begin_turn
from local_app.bridge import ClaudeSession


class WorkspaceSkillChoiceFlowTests(unittest.TestCase):
    output = execution.SkillExecutionTests.output
    state = execution.SkillExecutionTests.state

    def setUp(self):
        execution.SkillExecutionTests.setUp(self)
        no_process = patch('subprocess.Popen', side_effect=AssertionError('No child process in this test'))
        no_process.start()
        self.addCleanup(no_process.stop)
        self.events = []
        self.bridge = ClaudeSession(['unused-test-cli'], {'permissionMode': 'manual'}, self.f.project,
                                    lambda kind, data: self.events.append((kind, deepcopy(data))))
        self.addCleanup(self.bridge.close)
        self.question_number = 0

    def hook(self, event, tool, inputs, *, tool_id='skill-question-1', response=None, **extra):
        payload = {'session_id': self.f.sid, 'cwd': str(self.f.project),
                   'hook_event_name': event, 'tool_name': tool,
                   'tool_use_id': tool_id, 'tool_input': deepcopy(inputs), **extra}
        if response is not None:
            payload['tool_response'] = deepcopy(response)
        stdout = io.StringIO()
        with patch.object(native_entry, 'configure_runtime', return_value=True), \
                patch.object(sys, 'argv', ['native_entry.py', '--event', event]), \
                patch.object(sys, 'stdin', io.StringIO(json.dumps(payload, ensure_ascii=False))), \
                redirect_stdout(stdout):
            self.assertEqual(0, native_entry.main())
        result = json.loads(stdout.getvalue())
        self.assertNotIn('하네스 검사는 사용할 수 없습니다', result.get('systemMessage', ''))
        return result

    def overlap(self):
        file = self.f.skill('team-report', 'HTML 보고서 제작')
        self.output('HTML 보고서 만들어줘')
        route = self.state()['skillWorkflow']
        data = inventory_skills(self.f.state, project_root=self.f.project,
                                plugin_root=discovery.PLUGIN, claude_root=self.f.claude)
        candidates = [item for item in data['skills'] if item['id'] in route['requiredChoiceIds']]
        self.assertEqual(2, len(candidates))
        selected = next(item for item in candidates if item['path'] == str(file))
        inputs = {'questions': [{'question': '어떤 스킬로 보고서를 만들까요?', 'header': 'Choice',
                   'options': [{'label': (item.get('invocation') or item['name'])
                                       + (' (Recommended)' if item['id'] == selected['id'] else ''),
                                'description': '확인한 보고서 제작 방식'} for item in candidates],
                   'multiSelect': False}]}
        return selected, inputs

    def prepare(self, inputs, **context):
        self.question_number += 1
        tool_id = 'skill-question-' + str(self.question_number)
        result = self.hook('PreToolUse', 'AskUserQuestion', inputs, tool_id=tool_id, **context)
        decision = result.get('hookSpecificOutput', {})
        self.assertNotEqual('deny', decision.get('permissionDecision'))
        return tool_id, deepcopy(decision.get('updatedInput', inputs))

    def answer_in_workspace(self, inputs, answer=None, *, allow=True):
        rid = 'ui-request-' + str(self.question_number)
        self.bridge.handle({'type': 'control_request', 'request_id': rid, 'request': {
            'subtype': 'can_use_tool', 'tool_name': 'AskUserQuestion', 'input': deepcopy(inputs)}})
        request = next(data for kind, data in reversed(self.events) if kind == 'request')
        self.assertEqual(inputs, request['input'])
        with patch.object(self.bridge, '_write') as transport:
            answers = {question['question']: answer for question in inputs['questions']} if allow else None
            self.bridge.respond(rid, allow, answers)
        message = transport.call_args.args[0]
        self.assertEqual('control_response', message['type'])
        self.assertEqual(rid, message['response']['request_id'])
        self.assertNotIn(rid, self.bridge.pending)
        return message['response']['response']

    def assert_pending(self, invocation='team-report'):
        route = self.state()['skillWorkflow']
        self.assertNotIn('choiceAnswer', route)
        result = self.hook('PreToolUse', 'Skill', {'skill': invocation})
        self.assertEqual('deny', result['hookSpecificOutput']['permissionDecision'])

    @staticmethod
    def returned(reply):
        # Real native toolUseResult repeats questions and answers, with no
        # required success flag; Workspace's input map alone is insufficient.
        inputs = reply['updatedInput']
        return {key: deepcopy(inputs[key]) for key in ('questions', 'answers')}

    def test_translated_workspace_answer_records_choice_and_releases_selected_skill(self):
        selected, original = self.overlap()
        self.assert_pending(selected['invocation'])
        tool_id, shown = self.prepare(original)
        self.assertEqual('선택', shown['questions'][0]['header'])
        self.assertIn('(Recommended)', json.dumps(original))
        self.assertNotIn('(Recommended)', json.dumps(shown))
        label = next(option['label'] for option in shown['questions'][0]['options']
                     if option['label'].startswith(selected['invocation']))
        self.assertTrue(label.endswith('(추천)'))
        reply = self.answer_in_workspace(shown, label)
        self.assertEqual('allow', reply['behavior'])
        self.assertEqual({shown['questions'][0]['question']: label}, reply['updatedInput']['answers'])
        self.assertNotIn('answers', shown)
        self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                  tool_id=tool_id, response=self.returned(reply))
        route = self.state()['skillWorkflow']
        self.assertEqual(selected['id'], route['choiceAnswer']['id'])
        self.assertEqual(selected['id'], route['requestChoice']['id'])
        self.assertNotIn('choiceIds', route['executionPlan'])
        self.assertIsNone(route['selected'])  # Answering is not a body-load receipt.
        self.assertEqual({}, route['readSkills'])
        self.assertEqual({}, self.hook('PreToolUse', 'Skill', {'skill': selected['invocation']}))
        self.hook('PostToolUse', 'Skill', {'skill': selected['invocation']}, response={'success': True})
        self.assertEqual(selected['id'], self.state()['skillWorkflow']['selected']['id'])
        self.assertEqual({}, self.hook('PreToolUse', 'Write', {'file_path': str(self.f.project / 'report.html')}))
        serialized = json.dumps(self.state(), ensure_ascii=False)
        self.assertNotIn(original['questions'][0]['question'], serialized)
        self.assertNotIn('확인한 보고서 제작 방식', serialized)

    def test_untranslated_question_also_accepts_only_the_host_added_answer(self):
        selected, original = self.overlap()
        original['questions'][0]['header'] = '스킬 선택'
        for option in original['questions'][0]['options']:
            option['label'] = option['label'].replace(' (Recommended)', '')
        tool_id, shown = self.prepare(original)
        self.assertEqual(original, shown)
        reply = self.answer_in_workspace(shown, selected['invocation'])
        self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                  tool_id=tool_id, response=self.returned(reply))
        self.assertEqual(selected['id'], self.state()['skillWorkflow']['requestChoice']['id'])

    def test_cli_result_answers_can_resolve_the_registered_original_question(self):
        selected, original = self.overlap()
        tool_id, shown = self.prepare(original)
        label = next(option['label'] for option in shown['questions'][0]['options']
                     if option['label'].startswith(selected['invocation']))
        reply = self.answer_in_workspace(shown, label)
        # Older hosts report the untouched model input plus the returned answer.
        self.assertNotIn('answers', original)
        self.hook('PostToolUse', 'AskUserQuestion', original,
                  tool_id=tool_id, response=self.returned(reply))
        self.assertEqual(selected['id'], self.state()['skillWorkflow']['requestChoice']['id'])

    def test_workspace_cancel_and_negative_answer_do_not_record_a_choice(self):
        for allow in (False, True):
            with self.subTest(allow=allow):
                _, original = self.overlap()
                tool_id, shown = self.prepare(original)
                reply = self.answer_in_workspace(shown, '취소', allow=allow)
                if allow:
                    self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                              tool_id=tool_id, response=self.returned(reply))
                else:
                    self.assertEqual('deny', reply['behavior'])
                    self.assertNotIn('updatedInput', reply)
                    before = self.state()
                    result = self.hook('PostToolUseFailure', 'AskUserQuestion', shown,
                                       tool_id=tool_id, error='사용자가 취소했습니다')
                    self.assertEqual({}, result)
                    after = self.state()
                    for counter in ('taskFailureCount', 'mutationCount'):
                        self.assertEqual(before[counter], after[counter], counter)
                    late = {**deepcopy(shown), 'answers': {shown['questions'][0]['question']: 'team-report'}}
                    self.hook('PostToolUse', 'AskUserQuestion', late, tool_id=tool_id,
                              response={'questions': late['questions'], 'answers': late['answers']})
                self.assert_pending()

    def test_pre_authored_answers_or_missing_pretool_receipt_cannot_impersonate_workspace_choice(self):
        for authored in (None, {}, {'어떤 스킬로 보고서를 만들까요?': 'team-report'}):
            with self.subTest(authored=authored):
                selected, original = self.overlap()
                if authored is None:
                    # A host-shaped response alone does not prove a prior question.
                    self.question_number += 1
                    tool_id, shown = 'no-pretool-receipt', original
                else:
                    original['answers'] = authored
                    tool_id, shown = self.prepare(original)
                reply = self.answer_in_workspace(shown, selected['invocation'])
                self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                          tool_id=tool_id, response=self.returned(reply))
                self.assert_pending()

    def test_other_tool_id_or_changed_question_does_not_inherit_a_question_receipt(self):
        for change in ('tool-id', 'question', 'options'):
            with self.subTest(change=change):
                selected, original = self.overlap()
                tool_id, shown = self.prepare(original)
                if change == 'tool-id':
                    tool_id += '-different'
                elif change == 'question':
                    shown['questions'][0]['question'] = '다른 질문의 답을 사용할까요?'
                elif change == 'options':
                    shown['questions'][0]['options'][0]['description'] = '나중에 바꾼 선택 의미'
                reply = self.answer_in_workspace(shown, selected['invocation'])
                self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                          tool_id=tool_id, response=self.returned(reply))
                self.assert_pending()

    def test_question_receipt_is_not_reused_after_new_turn_or_catalog_revision(self):
        for changed_catalog in (False, True):
            with self.subTest(changed_catalog=changed_catalog):
                selected, original = self.overlap()
                tool_id, shown = self.prepare(original)
                reply = self.answer_in_workspace(shown, selected['invocation'])
                before = self.state()['skillWorkflow']
                if changed_catalog:
                    path = Path(selected['path'])
                    atomic_write_text(path, path.read_text(encoding='utf-8') + '\n절차 변경\n')
                    # Refresh the catalogue during this same turn to distinguish
                    # revision binding from merely rejecting old turns.
                    discovery.runtime_context(discovery.PLUGIN, self.f.project,
                                              'HTML 보고서 만들어줘', session_id=self.f.sid)
                else:
                    self.output('HTML 보고서 만들어줘')
                after = self.state()['skillWorkflow']
                if changed_catalog:
                    self.assertEqual(before['turn'], after['turn'])
                    self.assertNotEqual(before['revision'], after['revision'])
                else:
                    self.assertNotEqual(before['turn'], after['turn'])
                self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                          tool_id=tool_id, response=self.returned(reply))
                if changed_catalog:
                    # A changed candidate may itself make the old competition
                    # obsolete; only the stale answer must remain unrecorded.
                    current = self.state()['skillWorkflow']
                    self.assertNotIn('choiceAnswer', current)
                    self.assertNotIn('requestChoice', current)
                    self.assertIsNone(current['selected'])
                else:
                    self.assert_pending()

    def test_failed_question_result_does_not_turn_an_answer_into_selection(self):
        for failure in ({'success': False}, {'success': True, 'isError': True}):
            with self.subTest(failure=failure):
                selected, original = self.overlap()
                tool_id, shown = self.prepare(original)
                reply = self.answer_in_workspace(shown, selected['invocation'])
                self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                          tool_id=tool_id, response={**self.returned(reply), **failure})
                self.assert_pending()

    def test_missing_or_different_returned_answers_do_not_confirm_workspace_input(self):
        for changed_answer in (False, True):
            with self.subTest(changed_answer=changed_answer):
                selected, original = self.overlap()
                tool_id, shown = self.prepare(original)
                reply = self.answer_in_workspace(shown, selected['invocation'])
                response = {'success': True}
                if changed_answer:
                    response = self.returned(reply)
                    response['answers'][shown['questions'][0]['question']] = 'company-agent:html-report'
                self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                          tool_id=tool_id, response=response)
                self.assert_pending()

    def test_workspace_choice_can_keep_an_already_loaded_host_skill(self):
        self.output('HTML 보고서 만들어줘')
        self.hook('PostToolUse', 'Skill', {'skill': 'artifact-design'}, response={'success': True})
        self.assertFalse(self.state()['skillWorkflow']['hostChoice']['selected'])
        before = self.hook('PreToolUse', 'Skill', {'skill': 'company-agent:html-report'})
        self.assertEqual('deny', before['hookSpecificOutput']['permissionDecision'])
        original = {'questions': [{'question': '이번 보고서는 어떤 방식으로 만들까요?', 'header': 'Choice',
                     'options': [{'label': 'artifact-design (Recommended)', 'description': '이미 불러온 방식'},
                                 {'label': 'company-agent:html-report', 'description': '공통 보고서 방식'}],
                     'multiSelect': False}]}
        tool_id, shown = self.prepare(original)
        reply = self.answer_in_workspace(shown, 'artifact-design (추천)')
        self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                  tool_id=tool_id, response=self.returned(reply))
        route = self.state()['skillWorkflow']
        self.assertTrue(route['hostChoice']['selected'])
        self.assertEqual({}, route['readSkills'])
        self.assertIsNone(route['selected'])
        self.assertEqual({}, self.hook('PreToolUse', 'Write', {'file_path': str(self.f.project / 'report.html')}))

    def test_worker_or_stale_native_prompt_question_never_creates_parent_choice_receipt(self):
        for boundary in ('worker', 'stale-prompt'):
            with self.subTest(boundary=boundary):
                context = {'agent_id': 'isolated-worker-1'}
                if boundary == 'stale-prompt':
                    def begin_native_turn(*args, **kwargs):
                        return begin_turn(*args, **kwargs,
                                          native_prompt_id='11111111-1111-4111-8111-111111111111')
                    with patch.object(discovery, 'begin_turn', side_effect=begin_native_turn):
                        selected, original = self.overlap()
                    context = {'prompt_id': '22222222-2222-4222-8222-222222222222'}
                else:
                    selected, original = self.overlap()
                previous = deepcopy(self.state().get('skillQuestionReceipts'))
                tool_id, shown = self.prepare(original, **context)
                self.assertEqual(previous, self.state().get('skillQuestionReceipts'))
                reply = self.answer_in_workspace(shown, selected['invocation'])
                self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                          tool_id=tool_id, response=self.returned(reply), **context)
                self.assertEqual(previous, self.state().get('skillQuestionReceipts'))
                self.assert_pending(selected['invocation'])

    def test_workspace_host_comparison_can_select_the_company_skill(self):
        self.output('HTML 보고서 만들어줘')
        self.hook('PostToolUse', 'Skill', {'skill': 'artifact-design'}, response={'success': True})
        original = {'questions': [{'question': '이번 보고서는 어떤 방식으로 만들까요?', 'header': '스킬 선택',
                     'options': [{'label': 'artifact-design', 'description': '이미 불러온 방식'},
                                 {'label': 'company-agent:html-report (Recommended)', 'description': '공통 보고서 방식'}],
                     'multiSelect': False}]}
        target = self.state()['skillWorkflow']['hostChoice']['targetId']
        tool_id, shown = self.prepare(original)
        reply = self.answer_in_workspace(shown, 'company-agent:html-report (추천)')
        self.hook('PostToolUse', 'AskUserQuestion', reply['updatedInput'],
                  tool_id=tool_id, response=self.returned(reply))
        route = self.state()['skillWorkflow']
        self.assertNotIn('hostChoice', route)
        self.assertEqual(target, route['requestChoice']['id'])
        self.assertEqual(target, route['executionPlan']['id'])
        self.assertIsNone(route['selected'])
        self.assertEqual({}, self.hook('PreToolUse', 'Skill', {'skill': 'company-agent:html-report'}))
        self.hook('PostToolUse', 'Skill', {'skill': 'company-agent:html-report'}, response={'success': True})
        self.assertEqual(target, self.state()['skillWorkflow']['selected']['id'])
        self.assertEqual({}, self.hook('PreToolUse', 'Write', {'file_path': str(self.f.project / 'report.html')}))

    def test_real_failure_hook_routes_ask_user_question_to_native_failure_event(self):
        hooks = json.loads((discovery.PLUGIN / 'hooks/hooks.json').read_text(encoding='utf-8'))['hooks']
        matching = [item for item in hooks['PostToolUseFailure']
                    if re.fullmatch(item.get('matcher', ''), 'AskUserQuestion')]
        self.assertTrue(matching)
        commands = [command for item in matching for command in item['hooks']]
        self.assertTrue(any(command.get('type') == 'command'
                            and command.get('args', [])[-2:] == ['-Event', 'PostToolUseFailure']
                            for command in commands))


if __name__ == '__main__':
    unittest.main()
