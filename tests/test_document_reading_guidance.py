"""Document guidance describes observed results, not blanket bypass directives."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'company-agent-plugin'
sys.path.insert(0, str(PLUGIN / 'scripts'))
from company_agent.business_safety import protection_notice


class DocumentReadingGuidanceTests(unittest.TestCase):
    def test_document_skills_do_not_include_blanket_bypass_prohibitions(self):
        files = [PLUGIN / 'skills/company-agent/references/business-protection.md']
        for name in ('office-reader', 'html-report', 'presentation'):
            files.extend((PLUGIN / 'skills' / name).rglob('*.md'))
        for file in files:
            text = file.read_text(encoding='utf-8').lower()
            for old in ('우회', 'bypass', 'never decrypt', 'do not recommend a protection-free copy',
                        'never suggest an unprotected copy', 'no alternate capture',
                        '다른 엔진으로 재시도하지 않는다', '이 절차로 다시 추출하지 않는다'):
                self.assertNotIn(old, text, str(file))

    def test_runtime_no_longer_reintroduces_removed_document_instructions(self):
        text = (PLUGIN / 'scripts/company_agent/native_runtime.py').read_text(encoding='utf-8')
        for old in ('No fallback after denial', 'Never suggest an unprotected copy',
                    'no alternate capture/OCR', '보호 해제 사본·캡처·다른 추출 경로를 제안하지 마세요'):
            self.assertNotIn(old, text)
        self.assertIn('DB SELECT only', text)
        self.assertIn('Outlook authenticated own account only', text)

    def test_error_guidance_retains_partial_result_reporting(self):
        text = protection_notice({'tool_response': {'code':'protected_input'}})
        self.assertNotIn('우회', text)
        self.assertNotIn('보호 해제된 사본', text)
        self.assertIn('첨부 내용은 제외하고 요약했습니다', text)
        reader = (PLUGIN / 'scripts/company_agent/office_reader.py').read_text(encoding='utf-8')
        self.assertNotIn('대체 추출에 사용하지 마세요', reader)


if __name__ == '__main__':
    unittest.main()
