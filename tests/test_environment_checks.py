import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent.environment_checks import inspect_environment


class EnvironmentChecksTests(unittest.TestCase):
    def test_missing_dependencies_are_separate_from_basic_install(self):
        with patch('company_agent.environment_checks._module', return_value=False), patch('company_agent.environment_checks._office', return_value=False):
            report = inspect_environment()
        states = {item['name']: item['status'] for item in report['features']}
        self.assertIn('준비 항목 있음', states['HTML 보고서'])
        self.assertEqual('추가 준비 필요', states['Excel·CSV 읽기'])
        self.assertEqual('추가 준비 필요', states['PPT 제작'])
        self.assertTrue(report['readOnly'])

    def test_registration_is_not_reported_as_successful_office_or_authentication(self):
        with patch('company_agent.environment_checks._module', return_value=True), patch('company_agent.environment_checks._office', return_value=True):
            report = inspect_environment()
        self.assertIn('실제 파일 실행은 미확인', report['features'][1]['status'])
        states = {item['name']: item['status'] for item in report['features']}
        self.assertEqual('계정 연결 확인 필요', states['Outlook 조회'])

    def test_only_installed_office_program_is_ready(self):
        with patch('company_agent.environment_checks._module', return_value=True), patch('company_agent.environment_checks._office', side_effect=lambda name: name == 'PowerPoint.Application'):
            states = {item['name']: item['status'] for item in inspect_environment()['features']}
        self.assertIn('실제 파일 실행은 미확인', states['PPT 읽기'])
        self.assertEqual('추가 준비 필요', states['Word 읽기'])


if __name__ == '__main__':
    unittest.main()
