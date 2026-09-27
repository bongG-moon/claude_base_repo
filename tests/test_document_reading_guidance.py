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
        for name in ('html-report', 'presentation'):
            files.extend((PLUGIN / 'skills' / name).rglob('*.md'))
        for file in files:
            text = file.read_text(encoding='utf-8').lower()
            # The removed Office-reader policy used these blanket directives.
            # A generic word ban also rejects legitimate actual-denial safeguards.
            for old in ('never decrypt', 'do not recommend a protection-free copy',
                        'never suggest an unprotected copy', 'no alternate capture',
                        '다른 엔진으로 재시도하지 않는다', '이 절차로 다시 추출하지 않는다'):
                self.assertNotIn(old, text, str(file))

    def test_actual_permission_restrictions_remain_binding(self):
        protection = (PLUGIN / 'skills/company-agent/references/business-protection.md').read_text(encoding='utf-8')
        self.assertIn('Existing corporate MCP policy, native permissions and DRM rules remain binding.', protection)
        self.assertIn('A DRM label, unknown DRM technology or generic parser error alone is not an access', protection)
        explanation = (PLUGIN / 'skills/html-report/references/explanation-diagrams.md').read_text(encoding='utf-8')
        self.assertIn('위임·보호·권한 정책은 유지하며 실제 거절을 우회하지 않습니다.', explanation)
        presentation = (PLUGIN / 'skills/presentation/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Actual permission denials are never retried through another route.', presentation)

    def test_runtime_no_longer_reintroduces_removed_document_instructions(self):
        text = (PLUGIN / 'scripts/company_agent/native_runtime.py').read_text(encoding='utf-8')
        for old in ('No fallback after denial', 'Never suggest an unprotected copy',
                    'no alternate capture/OCR', '보호 해제 사본·캡처·다른 추출 경로를 제안하지 마세요'):
            self.assertNotIn(old, text)
        self.assertIn('DB SELECT 전용', text)
        self.assertIn('Outlook 인증된 본인 계정만 허용합니다', text)

    def test_error_guidance_retains_partial_result_reporting(self):
        text = protection_notice({'tool_response': {'code':'protected_input'}})
        self.assertNotIn('우회', text)
        self.assertNotIn('보호 해제된 사본', text)
        self.assertIn('첨부 내용은 제외하고 요약했습니다', text)


if __name__ == '__main__':
    unittest.main()
