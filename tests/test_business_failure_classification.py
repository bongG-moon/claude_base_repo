"""Operational failures must not become fabricated document protection denials."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'company-agent-plugin' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from company_agent.business_safety import failure_result, protection_notice
from company_agent.state import begin_turn, load_session
import activity_hook


class BusinessFailureClassificationTests(unittest.TestCase):
    def result(self, code='source_not_found'):
        return {'ok': False, 'status': 'failed', 'code': code, 'sourceOpened': False,
                'documentAccess': 'not_checked',
                'message': '파일 경로를 확인하세요. 인코딩·DRM 문제로 단정하지 마세요.'}

    def error(self, result, ascii=True):
        return 'Exit code 1\n[문서 읽기] 읽기 요청 확인 중\n' + json.dumps(result, ensure_ascii=ascii, indent=2)

    def test_typed_failure_error_never_classifies_recovery_advice_as_drm(self):
        for code in ('source_not_found', 'invalid_office_request', 'conversation_session_required',
                     'source_metadata_unavailable', 'office_open_failed', 'unknown_failure'):
            for ascii in (True, False):
                with self.subTest(code=code, ascii=ascii):
                    self.assertEqual('', protection_notice({'error': self.error(self.result(code), ascii)}))

    def test_structured_error_code_wins_over_message_keywords(self):
        result = self.result()
        result['message'] = 'Do not infer permission denied or DRM blocked from a missing path.'
        for error in (json.dumps(result), self.error(result), result):
            self.assertEqual('', protection_notice({'error': error}))
        result['message'] = '{"code":"permission_denied"}'
        self.assertEqual('', protection_notice({'error': self.error(result)}))

    def test_label_and_truncated_result_are_not_protection_evidence(self):
        for text in ('DRM', 'DRM is not blocked', 'rights management is available',
                     'DRM 보호가 차단되지 않았습니다.',
                     'DRM 파일을 읽을 수 있는지 아직 확인하지 않았습니다.',
                     self.error(self.result())[:-40],
                     "FileNotFoundError: 'C:/DRM/source.xlsx' does not exist"):
            with self.subTest(text=text):
                self.assertEqual('', protection_notice({'error': text}))

    def test_real_access_and_protection_denials_remain_restricted(self):
        for text in ('PermissionError: access denied', 'Access is denied.', 'permission denied',
                     '액세스가 거부되었습니다.', 'DRM protection blocked', 'DRM: access denied',
                     'Operation blocked by rights management', '보호 설정 때문에 차단되었습니다.'):
            with self.subTest(text=text):
                self.assertTrue(protection_notice({'error': text}))

    def test_generic_json_errors_preserve_real_denials(self):
        for result in ({'message': 'Access is denied.', 'type': 'PermissionError'},
                       {'error': 'Permission denied'},
                       {'exception': {'message': 'DRM protection blocked'}},
                       {'ok': False, 'error': '액세스가 거부되었습니다.'}):
            for value in (result, json.dumps(result)):
                with self.subTest(value=value):
                    self.assertTrue(protection_notice({'error': value}))

    def test_document_content_is_not_an_operational_result(self):
        for key in ('text', 'content', 'body', 'subject', 'contentHtml', 'structure'):
            result = {'ok': True, 'kind': 'excel', 'items': [
                {'location': 'A1', key: json.dumps({'code': 'permission_denied'})}]}
            self.assertEqual('', protection_notice({'tool_response': {'stdout': json.dumps(result)}}))
            self.assertEqual('', protection_notice({'error': result}))
        # A separate actual attachment denial still counts, even when body
        # text happens to look like a successful or failed tool response.
        result['items'].append({'code': 'permission_denied'})
        self.assertTrue(protection_notice({'tool_response': {'stdout': json.dumps(result)}}))

    def test_mcp_explicit_error_text_is_not_discarded_as_document_content(self):
        for text in ('Access is denied.', json.dumps({'code': 'permission_denied'}),
                     json.dumps({'message': 'Permission denied'})):
            envelope = {'content': [{'type': 'text', 'text': text}]}
            self.assertEqual('', protection_notice({'tool_response': envelope}))
            self.assertEqual('', protection_notice({'tool_response': {**envelope, 'isError': False}}))
            self.assertTrue(protection_notice({'tool_response': {**envelope, 'isError': True}}))
        self.assertEqual('', protection_notice({'tool_response': {'isError': True,
            'content': [{'type': 'text', 'text': self.error(self.result())}]}}))

    def test_structured_denials_in_failure_and_normal_results_are_preserved(self):
        for code in ('protection_blocked', 'permission_denied', 'drm_blocked',
                     'protected_input', 'protection_unknown', 'protected_or_unsupported'):
            result = {'ok': False, 'status': 'blocked', 'code': code}
            for payload in ({'error': self.error(result)}, {'tool_error': json.dumps(result)},
                            {'tool_response': {'stdout': self.error(result)}}):
                with self.subTest(code=code, payload=payload):
                    self.assertTrue(protection_notice(payload))

    def test_independent_attachment_denial_is_not_hidden_by_request_error(self):
        self.assertTrue(protection_notice({'error': self.error(self.result()),
            'tool_response': {'items': [{'code': 'protection_blocked'}]}}))
        self.assertTrue(protection_notice({'error': self.error({'ok': False, 'code': 'partial',
            'items': [{'body': 'PRIVATE'}, {'code': 'permission_denied'}]})}))

    def test_missing_drm_named_file_is_an_ordinary_exception(self):
        result = failure_result(FileNotFoundError('C:/DRM/source.xlsx is missing'))
        self.assertEqual('operation_failed', result['code'])
        self.assertNotIn('source.xlsx', json.dumps(result))
        self.assertEqual('permission_denied', failure_result(PermissionError('C:/DRM/source.xlsx'))['code'])
        self.assertEqual('protection_blocked', failure_result(RuntimeError('DRM protection blocked'))['code'])

    def test_activity_hook_does_not_emit_protected_notice_or_poison_session(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'COMPANY_AGENT_USER_STATE': temp}):
            root = Path(temp)
            begin_turn('missing-source', 'SMALL', False, [], root)
            payload = {'hook_event_name': 'PostToolUseFailure', 'session_id': 'missing-source',
                       'tool_name': 'Bash', 'tool_input': {'command': 'pwd'},
                       'error': self.error(self.result())}
            output = io.StringIO()
            with patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
                self.assertEqual(0, activity_hook.main())
            self.assertEqual({}, json.loads(output.getvalue()))
            self.assertFalse(load_session('missing-source', root).get('protectionRestricted', False))
            self.assertNotIn('DRM', (root / 'sessions' / 'missing-source.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
