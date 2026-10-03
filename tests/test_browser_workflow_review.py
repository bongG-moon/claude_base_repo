"""Independent offline review of the novice web-Skill authoring journey."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))

from company_agent.browser_workflow import plan_web_workflow
from company_agent.cli import main


def education_request():
    # These tool names are synthetic contract metadata, never invoked.
    return {
        'name': 'weekly-training-applicants',
        'purpose': '매주 교육 신청 현황을 표로 정리',
        'site': 'https://training.example.invalid/applicants',
        'fields': ['이름', '부서', '신청일'],
        'filter': '사용자가 지정한 조회 기간',
        'output': 'table',
        'connection': 'reported_connected',
        'toolContract': {'server': 'existing-external-browser', 'tools': [
            {'name': 'selected_page_text', 'inputSchema': {'type': 'object',
             'properties': {'page': {'type': 'string'}}, 'required': ['page']}},
            {'name': 'selected_table_rows', 'inputSchema': {'type': 'object',
             'properties': {'table': {'type': 'string'}, 'limit': {'type': 'integer'}},
             'required': ['table', 'limit']}}]},
    }


def with_reported_trial(spec):
    spec = copy.deepcopy(spec)
    trial = plan_web_workflow(spec)
    spec['trial'] = {'status': 'passed', 'fingerprint': trial['trialPlan']['fingerprint'],
                     'rowCount': 3, 'fieldsMatch': True}
    return spec


class BrowserWorkflowJourneyReviewTests(unittest.TestCase):
    def test_novice_request_only_needs_the_missing_page(self):
        spec = education_request()
        spec.pop('site')
        reply = plan_web_workflow(spec)
        self.assertEqual('input_required', reply['status'])
        self.assertEqual(['site'], reply['missing'])
        self.assertEqual(['어느 웹페이지에서 할까요?'], reply['questions'])
        self.assertNotIn('assetSpec', reply)

    def test_missing_connection_stops_before_trial_without_search_or_install(self):
        spec = education_request()
        spec['connection'] = 'missing'
        reply = plan_web_workflow(spec)
        self.assertEqual('connection_required', reply['status'])
        self.assertIn('담당자', reply['message'])
        self.assertNotIn('trialPlan', reply)
        self.assertNotIn('assetSpec', reply)
        self.assertFalse(reply['browserExecuted'])
        self.assertFalse(reply['liveConnectionVerified'])

    def test_existing_external_connection_and_report_do_not_claim_verified_execution(self):
        spec = education_request()
        trial = plan_web_workflow(spec)
        self.assertEqual('trial_required', trial['status'])
        self.assertEqual(5, trial['trialPlan']['maxRows'])
        spec = with_reported_trial(spec)
        storage = plan_web_workflow(spec)
        self.assertEqual('storage_required', storage['status'])
        self.assertEqual(['내 모든 작업에서', '이 프로젝트에서만'],
                         [row['label'] for row in storage['options']])
        spec['storageScope'] = 'project'
        reply = plan_web_workflow(spec)
        self.assertEqual('ready_to_save', reply['status'])
        self.assertFalse(reply['browserExecuted'])
        self.assertFalse(reply['liveConnectionVerified'])
        self.assertFalse(reply['saved'])
        self.assertEqual('caller-reported', reply['trialEvidence'])
        self.assertNotIn('tool_dependencies', reply['assetSpec'])
        instructions = reply['assetSpec']['instructions']
        self.assertIn('existing-external-browser', instructions)
        self.assertIn('schemaHash', instructions)
        self.assertIn('최대 한 번 재시도', instructions)
        self.assertIn('다른 사이트·탭·계정으로 범위를 넓히지 않는다', instructions)
        self.assertNotIn('inputSchema', instructions)

    def test_failed_or_changed_trial_requires_targeted_followup(self):
        spec = with_reported_trial(education_request())
        spec['storageScope'] = 'project'
        spec['trial']['status'] = 'failed'
        self.assertEqual('trial_failed', plan_web_workflow(spec)['status'])
        spec['trial']['status'] = 'passed'
        spec['toolContract']['tools'][0]['inputSchema']['properties']['page']['type'] = 'integer'
        reply = plan_web_workflow(spec)
        self.assertEqual('trial_required', reply['status'])
        self.assertNotIn('assetSpec', reply)
        self.assertIn('바뀐 범위만', reply['message'])

    def test_quoted_credential_values_cannot_be_saved_as_task_description(self):
        for field in ('purpose', 'filter'):
            for credential in ('{"password":"SYNTHETIC_REVIEW_SECRET"}',
                               '{"api_key": "SYNTHETIC_REVIEW_SECRET"}',
                               '{"token": "SYNTHETIC_REVIEW_SECRET"}',
                               '{"쿠키": "SYNTHETIC_REVIEW_SECRET"}',
                               "{'authorization': 'SYNTHETIC_REVIEW_SECRET'}"):
                with self.subTest(field=field, credential=credential):
                    spec = education_request()
                    spec[field] = '교육 신청 현황 ' + credential
                    with self.assertRaises(ValueError) as caught:
                        plan_web_workflow(spec)
                    self.assertNotIn('SYNTHETIC_REVIEW_SECRET', str(caught.exception))


class BrowserWorkflowMalformedInputReviewTests(unittest.TestCase):
    def call_cli(self, raw):
        output, errors = io.StringIO(), io.StringIO()
        # Only the spec read is replaced; no file or connection is created.
        with patch.object(Path, 'open', return_value=io.BytesIO(raw)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(['asset', 'web-plan', '--spec', 'synthetic-review.json'])
        return code, output.getvalue(), errors.getvalue()

    def test_json_decoder_recursion_is_a_normal_input_error_without_traceback(self):
        raw = b'{"purpose":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'
        # Decoder recursion limits differ between supported Python versions.
        with patch('company_agent.cli.json.loads', side_effect=RecursionError('deep input')):
            code, output, errors = self.call_cli(raw)
        self.assertEqual(1, code)
        self.assertEqual('', output)
        self.assertFalse(json.loads(errors)['ok'])
        self.assertNotIn('Traceback', errors)

    def test_malformed_url_returns_a_korean_error_without_reflecting_input(self):
        spec = education_request()
        spec['site'] = 'https://[SYNTHETIC_REVIEW_SECRET'
        code, output, errors = self.call_cli(json.dumps(spec).encode())
        self.assertEqual(1, code)
        self.assertEqual('', output)
        message = json.loads(errors)['error']
        self.assertRegex(message, '[가-힣]')
        self.assertNotIn('SYNTHETIC_REVIEW_SECRET', message)
        self.assertNotIn('Traceback', errors)


if __name__ == '__main__':
    unittest.main()
