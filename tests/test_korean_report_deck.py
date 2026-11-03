import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('korean_deck', ROOT/'standalone-skills/presentation/scripts/deck.py')
deck=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)

class KoreanDeckTests(unittest.TestCase):
    def job(self, count=12):
        return {'title':'가상 검증', 'slides':[{'title':f'{i}장', 'hero':'핵심 메시지',
            'bodyHtml':'<div class="columns equal"><div class="column"><h3 class="region-title">[ 현황 ]</h3><p>내용 &amp; 근거</p></div><div class="column"><table class="matrix"><tbody><tr><th>값</th><td>10</td></tr></tbody></table></div></div>',
            'takeaway':'요약', 'notes':'메모 </script><script>alert(1)</script>'} for i in range(count)]}

    def test_twelve_pages_preserve_css_and_notes_and_editable_text(self):
        result=deck.render(self.job())
        template=deck.TEMPLATE.read_text(encoding='utf-8')
        css=lambda s: re.search(r'<style>(.*?)</style>',s,re.S)[1]
        self.assertEqual(css(template),css(result))
        self.assertEqual(12,len(re.findall(r'<section class="slide ',result)))
        self.assertIn('data-goto="P12"',result)
        self.assertIn('본문 12장',result)
        self.assertIn('Math.min(9, allSlides.length)',result)
        self.assertNotIn('<script>alert(1)',result)
        notes=json.loads(re.search(r'<script id="deck-notes"[^>]*>(.*?)</script>',result,re.S)[1])
        self.assertEqual(12,len(notes))
        self.assertIn('&lt;/script&gt;',notes['P01']['html'])
        edit_ids=re.findall(r'data-edit="([^"]+)"',result)
        self.assertEqual(len(edit_ids),len(set(edit_ids)))
        self.assertIn("removeAttribute('inert')",result)
        self.assertIn('refreshTitles()',result)

    def test_active_or_unknown_body_content_is_rejected(self):
        for body in ('<script>alert(1)</script>','<img src="x">','<div style="color:red">x</div>',
                     '<p onclick="x()">x</p>','<div class="unknown">x</div>','<p>x</div>',
                     '<table>text</table>','<iframe></iframe>'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                job=self.job(1);job['slides'][0]['bodyHtml']=body;deck.render(job)

    def test_text_fields_are_escaped(self):
        job=self.job(1);job['slides'][0]['title']='<script>bad</script>'
        result=deck.render(job)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;',result)
        self.assertNotIn('<script>bad</script>',result)

if __name__=='__main__': unittest.main()
