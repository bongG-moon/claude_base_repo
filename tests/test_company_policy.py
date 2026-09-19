from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.company_policy import inspect_policy, policy_context, validate_standards, MAX_CONTEXT_CHARS


class CompanyPolicyTests(unittest.TestCase):
    def test_matching_is_bounded_and_does_not_write_personal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '회사.json'
            config = json.loads((ROOT / 'config/managed.example.json').read_text(encoding='utf-8'))
            path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            before = path.read_bytes()
            with patch.dict(os.environ, {'COMPANY_AGENT_MANAGED_CONFIG': str(path)}):
                general = policy_context([])
                report = policy_context(['html-report'])
            self.assertEqual(2, len(general['rules']))
            self.assertEqual(3, len(report['rules']))
            self.assertEqual('default', report['rules'][-1]['level'])
            self.assertEqual(['html-report'], report['forWorkflows'])
            self.assertLessEqual(len(json.dumps(report, ensure_ascii=False, separators=(',', ':'))), MAX_CONTEXT_CHARS)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([path], list(Path(tmp).iterdir()))

    def test_legacy_missing_and_invalid_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'managed.json'
            self.assertEqual('unavailable', inspect_policy(path)['status'])
            path.write_text('{"policy": {}}', encoding='utf-8')
            self.assertEqual('not-configured', inspect_policy(path)['status'])
            path.write_text('{"workStandards": {"revision":"1","rules":null}}', encoding='utf-8')
            self.assertEqual('unavailable', inspect_policy(path)['status'])

    def test_default_cannot_supply_executable_fields(self):
        with self.assertRaises(ValueError):
            validate_standards({'revision': '1', 'rules': [{'id':'x','level':'default', 'workflows':['*'], 'text':'a', 'command':'bad'}]})

    def test_overflow_keeps_required_first_and_explicit_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'managed.json'
            rules = [{'id': f'rule-{n}', 'level': 'required' if n == 5 else 'default', 'workflows':['*'], 'text':'가' * 300} for n in range(6)]
            path.write_text(json.dumps({'workStandards': {'revision':'1', 'rules':rules}}), encoding='utf-8')
            with patch.dict(os.environ, {'COMPANY_AGENT_MANAGED_CONFIG': str(path)}):
                context = policy_context([])
            self.assertTrue(context['truncated'])
            self.assertEqual('required', context['rules'][0]['level'])
            self.assertEqual(str(path), context['path'])

    def test_oversized_path_is_not_truncated_or_treated_as_absent_policy(self):
        with patch('company_agent.company_policy.inspect_policy', return_value={
                'status':'available','path':'x'*2000,'rules':[]}):
            context = policy_context([])
        self.assertEqual('unavailable', context['status'])
        self.assertNotIn('path', context)
        self.assertLess(len(json.dumps(context)), MAX_CONTEXT_CHARS)


if __name__ == '__main__':
    unittest.main()
