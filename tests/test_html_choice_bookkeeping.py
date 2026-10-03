"""Choice preparation is not a report change; existing obligations remain."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "company-agent-plugin/scripts"))
from company_agent.state import begin_turn, load_session, mark_verified, record_activity, stop_decision
from company_agent.report_styles import choices


class HtmlChoiceBookkeepingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tmp").mkdir()
        self.path = self.root / "tmp/html-choices-report.json"
        begin_turn("choices", "MEDIUM", False, [], self.root)

    def write(self, content, path=None):
        return record_activity({"session_id": "choices", "hook_event_name": "PostToolUse",
                                "tool_name": "Write", "tool_input": {
                                    "file_path": str(path or self.path), "content": content}}, self.root)

    def test_selection_steps_are_silent_and_keep_no_business_content(self):
        for spec in ({}, {"designMenu": "initial"}, {"designMenu": "additional"},
                     {"designMenu": "additional", "style": "4"}, {"style": "글래스모피즘"},
                     {"designMenu": "additional", "style": "neumorphism", "length": "detailed", "mode": "scroll"},
                     {"designMenu": "template", "htmlTemplate": {"path": str(self.root / "form.html"), "sha256": "a" * 64}}):
            state = self.write(json.dumps(spec))
            self.assertEqual(0, state["mutationCount"])
            self.assertEqual([], state["work"]["pending"])
            self.assertIsNone(state["verification"])
            self.assertEqual({}, stop_decision({"session_id": "choices"}, self.root))

    def test_successful_edit_checks_complete_bounded_choice_file(self):
        self.path.write_text('{"designMenu":"additional","style":"4","length":"detailed"}', encoding='utf-8')
        payload = {"session_id":"choices", "hook_event_name":"PostToolUse", "tool_name":"Edit",
                   "tool_input":{"file_path":str(self.path), "old_string":"3", "new_string":"4"}}
        self.assertEqual(0, record_activity(payload, self.root)['mutationCount'])
        self.assertEqual({}, stop_decision({'session_id':'choices'}, self.root))
        self.path.write_text('{"style":"minimalism","sections":[{}]}', encoding='utf-8')
        self.assertEqual(1, record_activity(payload, self.root)['mutationCount'])

    def test_missing_or_large_edit_is_not_choice_bookkeeping(self):
        from company_agent.state import _is_html_choices_spec_write
        tool_input = {'file_path':str(self.path)}
        self.assertFalse(_is_html_choices_spec_write('Edit', tool_input, self.root))
        self.path.write_text(' ' * 8192 + '{}', encoding='utf-8')
        self.assertFalse(_is_html_choices_spec_write('Edit', tool_input, self.root))

    def test_report_content_invalid_values_and_other_paths_are_not_exempt(self):
        cases = [('{"sections": []}', self.path), ('{"title":"Report"}', self.path),
                 ('{"mode":"arbitrary"}', self.path), ('{"style":[]}', self.path),
                 ('[]', self.path), ('not json', self.path),
                 ('{"htmlTemplate":{"path":"relative.html","sha256":"abc"}}', self.path),
                 ('{}', self.root / "tmp/job.json"), ('{}', self.root / "html-choices-report.json"),
                 ('{}', self.root / "tmp/html-choices-report.html")]
        count = 0
        for content, path in cases:
            with self.subTest(content=content, path=path):
                count += 1
                self.assertEqual(count, self.write(content, path)["mutationCount"])
        self.assertEqual("block", stop_decision({"session_id": "choices"}, self.root)["decision"])

    def test_new_choices_do_not_clear_previous_unverified_report(self):
        self.write("<html>actual report</html>", self.root / "report.html")
        begin_turn("choices", "MEDIUM", False, [], self.root)
        self.write('{"style":"minimalism"}')
        self.assertEqual(1, load_session("choices", self.root)["mutationCount"])
        self.assertEqual("block", stop_decision({"session_id": "choices"}, self.root)["decision"])

    def wait_event(self):
        scripts = Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'
        command = f'"{sys.executable}" -B "{scripts / "harness_cli.py"}" business html-choices --spec "{self.path}" --state-root "{self.root}"'
        return {'session_id': 'choices', 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                'tool_input': {'command': command},
                'tool_response': {'stdout': json.dumps(choices({'designMenu': 'additional'})), 'exitCode': 0}}

    def test_observed_selection_wait_preserves_debt_and_retry_budget_until_answer(self):
        self.write('<html>unfinished</html>', self.root / 'report.html')
        self.assertEqual('block', stop_decision({'session_id': 'choices'}, self.root)['decision'])
        original = load_session('choices', self.root)
        state = record_activity(self.wait_event(), self.root)
        self.assertEqual('html-report-style', state['pendingInput']['kind'])
        for _ in range(3):
            self.assertEqual({}, stop_decision({'session_id': 'choices'}, self.root))
        after = load_session('choices', self.root)
        for key in ('mutationCount', 'verification', 'stopRetryCount', 'sameFailureCount'):
            self.assertEqual(original[key], after[key])
        begin_turn('choices', 'MEDIUM', False, [], self.root)
        self.assertIsNone(load_session('choices', self.root)['pendingInput'])
        self.assertEqual('block', stop_decision({'session_id': 'choices'}, self.root)['decision'])
        self.assertEqual(2, load_session('choices', self.root)['stopRetryCount'])
        self.assertNotIn('decision', stop_decision({'session_id': 'choices'}, self.root))

    def test_mutation_or_new_verification_cannot_hide_behind_previous_wait(self):
        self.write('<html>unfinished</html>', self.root / 'report.html')
        record_activity(self.wait_event(), self.root)
        mark_verified('choices', 'fail', 'actual content failure', self.root)
        self.assertEqual('block', stop_decision({'session_id': 'choices'}, self.root)['decision'])
        record_activity(self.wait_event(), self.root)
        self.write('<html>changed</html>', self.root / 'report.html')
        self.assertIsNone(load_session('choices', self.root)['pendingInput'])
        self.assertEqual('block', stop_decision({'session_id': 'choices'}, self.root)['decision'])

    def test_arbitrary_failed_stale_or_child_results_do_not_create_wait(self):
        from company_agent.state import _html_choice_wait
        event = self.wait_event()
        self.assertTrue(_html_choice_wait(event, self.root))
        cases = [
            {**event, 'agent_id': 'child'},
            {**event, 'hook_event_name': 'PostToolUseFailure'},
            {**event, 'tool_name': 'Read'},
            {**event, 'tool_input': {'command': 'echo choices'}},
            {**event, 'tool_input': {'command': event['tool_input']['command'] + ' | head -30'}},
            {**event, 'tool_input': {'command': event['tool_input']['command'].replace(f'--state-root "{self.root}"', f'--state-root "{self.root / "other"}"')}},
        ]
        for response in ({'stdout': '{}'}, {'stdout': event['tool_response']['stdout'], 'exitCode': 1},
                         {'stdout': event['tool_response']['stdout'], 'interrupted': True},
                         {'stdout': '{"ok":true,"ok":false}'}, {'stdout': '[' * 1100 + ']' * 1100},
                         {'stdout': ' ' * 32769}, {'stdout': event['tool_response']['stdout'] + '\n{}'}):
            cases.append({**event, 'tool_response': response})
        for invalid in cases:
            self.assertFalse(_html_choice_wait(invalid, self.root), invalid)
        self.write('<html>unfinished</html>', self.root / 'report.html')
        for extra in ({'error': 'failed'}, {'tool_response': {**event['tool_response'], 'isError': True}}):
            self.assertIsNone(record_activity({**event, **extra}, self.root)['pendingInput'])
        self.assertEqual('block', stop_decision({'session_id': 'choices'}, self.root)['decision'])

    def test_ready_or_later_tool_event_clears_pending_input(self):
        self.write('<html>unfinished</html>', self.root / 'report.html')
        for next_event in (
            {'session_id': 'choices', 'tool_name': 'Read', 'tool_input': {'file_path': 'result.html'}},
            {**self.wait_event(), 'tool_response': {'stdout': '{"ok":true,"status":"choices_ready","stage":"ready"}'}},
        ):
            record_activity(self.wait_event(), self.root)
            self.assertIsNone(record_activity(next_event, self.root)['pendingInput'])
        self.assertEqual('block', stop_decision({'session_id': 'choices'}, self.root)['decision'])

    def test_old_native_prompt_wait_does_not_suspend_current_turn(self):
        self.write('<html>unfinished</html>', self.root / 'report.html')
        current = '11111111-2222-3333-4444-555555555555'
        begin_turn('choices', 'MEDIUM', False, [], self.root, native_prompt_id=current)
        event = {**self.wait_event(), 'prompt_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'}
        self.assertIsNone(record_activity(event, self.root)['pendingInput'])
        self.assertEqual('block', stop_decision({'session_id': 'choices', 'prompt_id': current}, self.root)['decision'])


if __name__ == "__main__":
    unittest.main()
