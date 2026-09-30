"""Learning UI reports capture and application, not hook counts as success."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LearningUiContractTests(unittest.TestCase):
    def test_existing_card_distinguishes_not_submitted_empty_and_applied(self):
        source = (ROOT / 'local_app/web/companion.js').read_text(encoding='utf-8')
        for text in ('learn.totals?.reviews===0', "receipt.captureStatus==='no_candidates'",
                     'receipt.capturedCount', 'receipt.appliedCount', 'receipt.deferredCount',
                     '훅 실행 횟수는 학습 건수가 아닙니다', '실제 답변에 적용됐다는 증거와 다릅니다'):
            self.assertIn(text, source)
        self.assertIn('매 답변마다 학습하거나 학습 때문에 종료를 지연하지 않습니다', source)
        self.assertIn("active:'실제 반영'", source)
        self.assertIn("deferred:'보류'", source)


if __name__ == '__main__':
    unittest.main()
