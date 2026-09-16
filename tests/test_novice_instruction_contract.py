"""Small instruction/UI contracts; browser/live probes validate actual behavior separately."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NoviceInstructionContractTests(unittest.TestCase):
    def test_html_choices_are_plain_and_have_an_easy_default(self):
        source = (ROOT / "company-agent-plugin/skills/html-report/SKILL.md").read_text(encoding="utf-8")
        for text in ("깔끔한 업무형", "지표 중심형", "추가 디자인(미리보기)", "추천대로", "1 / 보통 / 스크롤",
                     "minimal /", "standard / scroll", "Preserve explicit choices", "does not waive approval",
                     'absence of a reply is not acceptance', 'NOT a report style'):
            self.assertIn(text, source)

    def test_design_questions_are_sequential_and_preserve_answers(self):
        source = (ROOT / 'company-agent-plugin/skills/html-report/SKILL.md').read_text(encoding='utf-8')
        for text in ('Never batch the initial design question', "IMMEDIATELY show the helper's selectionPrompt",
                     'Do not ask length/mode or start a worker before a specific design is chosen', 'business html-choices',
                     'NEVER replace the whole object', 'delegate generation only after ready',
                     'Preview is optional', 'length:"detailed",mode:"scroll"',
                     'all ten numbered names', 'END THIS TURN', '선택 대기 중입니다',
                     'End the turn', 'same design question and WAIT'):
            self.assertIn(text, source)

    def test_download_request_does_not_claim_saved(self):
        source = (ROOT / "scripts/test-lab/dashboard.html").read_text(encoding="utf-8")
        download_handler = source.split("document.getElementById('download').addEventListener('click',()=>{", 1)[1]
        self.assertNotIn("dirty=false", download_handler)
        self.assertIn('id="confirm-saved" disabled', source)
        self.assertIn("savedButton.disabled=true", source)
        self.assertIn("파일이 실제 저장된 것을 확인", source)


if __name__ == "__main__":
    unittest.main()
