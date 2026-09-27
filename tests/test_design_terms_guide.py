"""The design glossary is readable reference content, not a runtime feature list."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TERMS = (
    '그라디언트 배경', '글래스모피즘', '미니멀·스위스', '다크 모드',
    '그레인 텍스처', '빅 타이포', '플랫 디자인', '플랫 2.0',
    '머티리얼 디자인', '클레이모피즘', '스큐어모피즘', '3D 렌더',
    '키네틱 타이포그래피', '구성주의', '아르데코', '팝 아트',
    '멤피스 디자인', '브루탈리즘(웹)', '스칸디나비안', '저팬디',
    '와비사비', '아르누보', '프루티거 에어로', '레트로 퓨처리즘',
    'Y2K', '베이퍼웨이브', '사이버펑크', '미드센추리 모던',
    '아크릴', '리퀴드 글래스',
)


class DesignTermsGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'docs/DESIGN_TERMS.md').read_text(encoding='utf-8')

    def test_all_reference_terms_have_plain_explanations_and_examples(self):
        rows = re.findall(r'^\| \*\*(.*?)\*\*([^\n]+)$', self.source, re.M)
        self.assertEqual(list(TERMS), [term for term, _ in rows])
        for term, rest in rows:
            with self.subTest(term=term):
                cells = rest.split('|')
                self.assertEqual(4, len(cells))
                self.assertGreater(len(cells[1].strip()), 25)
                self.assertTrue(cells[2].strip().startswith('“'))
                self.assertTrue(cells[2].strip().endswith('”'))
        self.assertEqual(9, len(re.findall(r'^## ', self.source, re.M)))

    def test_reference_does_not_claim_thirty_new_features(self):
        for text in ('30개 디자인 기능이 새로 추가됐다는 뜻은 아닙니다',
                     '표의 예문은 모양을 설명하는 말이지 메뉴 선택 명령이 아닙니다',
                     '실제 3D 모델·렌더링·회전 뷰어 기능이 아닙니다',
                     '클레이모피즘·스큐어모피즘·뉴모피즘은 서로 다른 표현',
                     '테마 전환 버튼이 자동으로 생기는 것은 아닙니다',
                     '전체 슬라이드 이미지만 넣는 방식으로 대신하지 않도록',
                     '아직 파일을 생성하거나 양식·기억에 저장하지 마'):
            self.assertIn(text, self.source)

    def test_new_part_is_in_both_standalone_and_installed_readers(self):
        sha = hashlib.sha256(self.source.encode()).hexdigest()
        for directory in ('docs', 'company-agent-plugin/resources/manuals'):
            for name in ('Company-Agent-사용자-안내서.html',):
                with self.subTest(directory=directory, name=name):
                    page = (ROOT / directory / name).read_text(encoding='utf-8')
                    self.assertIn(f'data-file="DESIGN_TERMS.md" content="{sha}"', page)
                    self.assertIn('id="design">디자인 용어 참고', page)
                    self.assertIn('href="#design"', page)
                    self.assertIn('href="#usage">업무별 사용법</a>', page)
                    for term in TERMS:
                        self.assertIn(f'<strong>{term}</strong>', page)
                    for number in range(1, 10):
                        self.assertIn(f'id="design-section-{number}"', page)
                    self.assertNotRegex(page, r'<(?:script|iframe|img|link)\b')
                    self.assertNotIn('href="DESIGN_TERMS.md"', page)
        self.assertEqual(
            (ROOT / 'docs/DESIGN_TERMS.md').read_bytes(),
            (ROOT / 'company-agent-plugin/resources/manuals/DESIGN_TERMS.md').read_bytes(),
        )

    def test_glossary_is_discoverable_from_existing_guides(self):
        for name in ('README.md', 'USER_GUIDE.md'):
            self.assertIn('(DESIGN_TERMS.md)', (ROOT / 'docs' / name).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
