"""Free HTML bundling does not execute sources or depend on a scene generator."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'standalone-skills/presentation/scripts/slides.py'
spec = importlib.util.spec_from_file_location('free_html_slides', SCRIPT)
slides = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slides)


class FreeHtmlPresentationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source_folder = self.root / 'new-authored'
        self.source_folder.mkdir()
        self.source = self.source_folder / '원본.html'
        self.target = self.root / '출력' / '발표본.html'
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.script = 'window.fixtureEditor = true;'
        (self.assets / 'html-deck-editor.js').write_text(self.script, encoding='utf-8')
        (self.assets / 'html-deck-editor.css').write_text('.hd-ui{color:#123456}', encoding='utf-8')
        (self.assets / 'fonts').mkdir()
        (self.assets / 'fonts/PretendardVariable.woff2').write_bytes(b'synthetic bundled font')
        self.addCleanup(patch.stopall)
        patch.object(slides, 'ASSETS', self.assets).start()

    def page(self, body='<section class="slide"><h1>제목</h1><p>본문</p></section>', head=''):
        text = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>한글 발표</title>' + head + '</head><body>' + body + '</body></html>'
        self.source.write_text(text, encoding='utf-8')
        return text

    def build(self, **kwargs):
        return slides.build(self.source, self.target, **kwargs)

    def reject(self, code=None):
        original = self.source.read_bytes()
        with self.assertRaises(slides.BuildError) as caught:
            self.build()
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(original, self.source.read_bytes())
        self.assertFalse(self.target.exists())

    def test_korean_svg_notes_and_authored_structure_survive_without_scene(self):
        body = '''<main id="deck"><section class="slide custom" id="start" data-notes="발표 메모 &amp; 근거">
<h1 data-edit="headline">한글 <strong>제목</strong></h1><div data-object="flow" style="display:grid;grid-template-columns:1fr 2fr">
<svg viewBox="0 0 100 80" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"><stop offset="0" stop-color="#123456"/></linearGradient></defs>
<rect width="100" height="80" fill="url(#g)"/><path d="M0 0L90 70"/><text x="5" y="20">한글 수치 123</text></svg></div><p>원본 설명</p>
</section><section class="slide" id="next"><h2>두 번째</h2><table><tr><th>구분</th><td>8주</td></tr></table></section></main>'''
        original = self.page(body, '<style>.custom{background:linear-gradient(#fff,#eee)}</style>')
        result = self.build()
        text = self.target.read_text(encoding='utf-8')
        self.assertEqual(self.source.read_text(encoding='utf-8'), original)
        self.assertEqual(result['slideCount'], 2)
        self.assertEqual(result['renderer'], 'free-html')
        self.assertEqual(result['visualReview'], 'not_verified')
        for token in ('viewBox="0 0 100 80"', '<linearGradient', 'data-notes="발표 메모 &amp; 근거"',
                      '한글 수치 123', 'data-object="flow"', 'grid-template-columns:1fr 2fr',
                      'linear-gradient(#fff,#eee)', 'id="start"', 'id="next"'):
            self.assertIn(token, text)
        self.assertNotIn('company-agent-ppt-scene', text)
        self.assertNotIn('pageRole', text)
        # The first slide's explicit scope is respected; the second gets leaf text scopes.
        parsed = slides.Document(text)
        p = next(n for n in parsed.root.nodes() if n.tag == 'p')
        self.assertFalse(p.has('data-edit'))
        self.assertTrue(all(n.has('data-edit') for n in parsed.root.nodes() if n.tag in {'h2','th','td'}))

    def test_script_and_network_inputs_are_rejected_without_output(self):
        cases = [
            ('<script>alert(1)</script>', ''),
            ('<script src="https://example.test/a.js"></script>', ''),
            ('<p onclick="alert(1)">실행</p>', ''),
            ('<img src="https://example.test/p.png">', ''),
            ('<a href="//example.test">링크</a>', ''),
            ('<iframe src="about:blank"></iframe>', ''),
            ('<canvas></canvas>', ''), ('<form></form>', ''), ('<object></object>', ''), ('<embed>', ''),
            ('', '<style>@import "local.css";</style>'),
            ('', '<style>@\\69mport "https://example.test/a.css";</style>'),
            ('', '<style>p{background:u\\72l("https://example.test/a.png")}</style>'),
            ('', '<style>p{background:url(//example.test/a.png)}</style>'),
            ('', '<meta http-equiv="refresh" content="0;url=https://example.test">'),
            ('<svg><foreignObject><p>우회</p></foreignObject></svg>', ''),
            ('<svg><set attributeName="href" to="https://example.test"/></svg>', ''),
            ('<img src="data:text/html;base64,PHNjcmlwdD4=">', ''),
        ]
        for body, head in cases:
            with self.subTest(body=body, head=head):
                self.page('<section class="slide"><h1>제목</h1>' + body + '</section>', head)
                self.reject()

    def test_only_valid_json_source_script_is_kept_and_editor_hash_is_exact(self):
        self.page('<section class="slide"><h1>제목</h1></section>', '<script type="application/json" id="facts">{"값":12,"목표":false}</script>')
        self.build()
        text = self.target.read_text(encoding='utf-8')
        self.assertIn('{"값":12,"목표":false}', text)
        digest = base64.b64encode(hashlib.sha256(self.script.encode()).digest()).decode()
        self.assertIn('sha256-' + digest, text)
        self.assertIn("connect-src &#x27;none&#x27;", text)
        self.assertIn("font-src data:", text)
        self.assertNotIn("script-src &#x27;unsafe-inline&#x27;", text)
        self.target.unlink()
        self.page(head='<script type="application/json">{"bad":NaN}</script>')
        self.reject('invalid_json')

    def test_local_resources_resolve_from_source_and_stylesheet_within_its_scope(self):
        (self.source_folder / 'css').mkdir()
        (self.source_folder / 'images').mkdir()
        (self.source_folder / 'fonts').mkdir()
        (self.source_folder / 'images/a.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        (self.source_folder / 'fonts/a.woff2').write_bytes(b'fixture font')
        (self.source_folder / 'css/theme.css').write_text('@font-face{font-family:"Custom";src:url(../fonts/a.woff2)}.slide{background-image:url("../images/a.png")}', encoding='utf-8')
        self.page('<section class="slide"><h1>제목</h1><img src="images/a.png"></section>', '<link rel="stylesheet" href="css/theme.css">')
        result = self.build()
        text = self.target.read_text(encoding='utf-8')
        self.assertTrue(result['ok'])
        self.assertIn('data:image/png;base64,', text)
        self.assertIn('data:font/woff2;base64,', text)
        self.assertNotIn('../images/a.png', text)
        self.assertNotIn('href="css/theme.css"', text)

    def test_parent_absolute_and_missing_resource_paths_do_not_search_other_folders(self):
        (self.root / 'outside.png').write_bytes(b'outside')
        for url in ('../outside.png', '%2e%2e/outside.png', str(self.root / 'outside.png'), '/outside.png', 'outside.png'):
            with self.subTest(url=url):
                self.page('<section class="slide"><img src="' + url + '"></section>')
                self.reject()

    def test_local_css_cannot_break_out_of_the_inline_style_element(self):
        (self.source_folder / 'theme.css').write_text('p::after{content:"</style><p>example</p>"}', encoding='utf-8')
        self.page(head='<link rel="stylesheet" href="theme.css">')
        self.build()
        text = self.target.read_text(encoding='utf-8')
        parsed = slides.Document(text)
        self.assertEqual(sum(n.tag == 'p' for n in parsed.root.nodes()), 1)
        self.assertIn('\\3c /style><p>example</p>', text)

    def test_source_and_existing_saved_outputs_are_unchanged(self):
        original = self.page()
        with self.assertRaises(slides.BuildError) as caught:
            slides.build(self.source, self.source)
        self.assertEqual(caught.exception.code, 'output_exists')
        self.target.parent.mkdir()
        self.target.write_text('사용자 편집 저장본', encoding='utf-8')
        with self.assertRaises(slides.BuildError):
            self.build()
        self.assertEqual(self.target.read_text(encoding='utf-8'), '사용자 편집 저장본')
        self.assertEqual(self.source.read_text(encoding='utf-8'), original)

    def test_defaults_editor_and_authored_css_order_preserves_reference_font(self):
        self.page(head='<style>:root{--deck-font:"Reference Font"}.slide{font-family:"Reference Font"}</style>')
        self.build()
        text = self.target.read_text(encoding='utf-8')
        self.assertLess(text.index('data-html-deck-base'), text.index('data-html-deck-editor'))
        self.assertLess(text.index('.hd-ui{'), text.index('--deck-font:"Reference Font"'))
        self.assertIn('data:font/woff2;base64,', text)
        self.assertNotIn('data-html-deck-font-override', text)
        self.target.unlink()
        self.build(font='명시 글꼴', width=1600)
        text = self.target.read_text(encoding='utf-8')
        self.assertIn('--slide-width:1600px;--slide-height:900px;', text)
        self.assertIn('--deck-font:"명시 글꼴",', text)
        self.assertGreater(text.index('data-html-deck-font-override'), text.index('--deck-font:"Reference Font"'))

    def test_unwrapped_slides_keep_ids_and_gain_only_missing_edit_scopes(self):
        self.page('<section class="slide" id="keep"><h1>제목 <em>강조</em></h1><p>본문</p></section><section class="slide"><p>다음</p></section>')
        self.build()
        parsed = slides.Document(self.target.read_text(encoding='utf-8'))
        deck = next(n for n in parsed.root.nodes() if n.get('id') == 'deck')
        pages = [n for n in deck.children if isinstance(n, slides.Node)]
        self.assertEqual([n.get('id') for n in pages], ['keep','slide-002'])
        self.assertEqual(deck.tag, 'main')
        self.assertTrue(all(n.has('data-edit') for n in deck.nodes() if n.tag in {'h1','p'}))

    def test_invalid_size_structure_and_duplicate_ids_are_explicit(self):
        self.page()
        with self.assertRaises(slides.BuildError):
            self.build(width=1280, height=800)
        self.page('<section class="slide" id="same"></section><section class="slide" id="same"></section>')
        self.reject('duplicate_id')
        self.page('<main id="deck"><div><section class="slide"></section></div></main>')
        self.reject('invalid_deck')

    def test_input_html_and_each_resource_have_separate_size_limits(self):
        self.assertEqual(slides.MAX_HTML, 20 * 1024 * 1024)
        self.assertEqual(slides.MAX_ASSET, 10 * 1024 * 1024)
        self.page()
        with patch.object(slides, 'MAX_HTML', 32):
            self.reject('html_too_large')
        (self.source_folder / 'big.png').write_bytes(b'x' * 32)
        self.page('<section class="slide"><img src="big.png"></section>')
        with patch.object(slides, 'MAX_ASSET', 32):
            self.reject('asset_too_large')

    def test_standalone_cli_uses_only_shipped_script_and_assets(self):
        staged = self.root / 'skill'
        (staged / 'scripts').mkdir(parents=True)
        shutil.copyfile(SCRIPT, staged / 'scripts/slides.py')
        shutil.copytree(self.assets, staged / 'assets')
        self.page()
        process = subprocess.run([sys.executable, '-I', '-B', str(staged / 'scripts/slides.py'),
                                  'build', '--source', str(self.source)], cwd=self.root,
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stdout.decode('utf-8') + process.stderr.decode(errors='replace'))
        result = json.loads(process.stdout.decode('utf-8'))
        self.assertEqual(Path(result['outputPath']), self.root / 'presentation/outputs/발표본.html')
        self.assertEqual(result['slideCount'], 1)


if __name__ == '__main__':
    unittest.main()
