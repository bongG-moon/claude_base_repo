"""Shared deck behavior, including an opt-in real isolated browser interaction."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ppt_deck_shell', ROOT / 'company-agent-plugin/scripts/company_agent/ppt_deck_shell.py')
shell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell)


class ResultReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.on = False
        self.value = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and dict(attrs).get('id') == 'test-result':
            self.on = True

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.on = False

    def handle_data(self, value):
        if self.on:
            self.value += value


class SharedDeckTests(unittest.TestCase):
    def document(self, count=12):
        pages = []
        for i in range(count):
            pages.append(f'<section class="ppt-page" style="--paper:#f0faf9;--font:Malgun Gothic">'
                         f'<div class="ppt-slide" data-slide="P{i+1:02}" data-title="{i+1}장">'
                         f'<h1 data-deck-title="true" data-edit="p{i}-title">{i+1}장 제목</h1>'
                         f'<table><tr><th data-edit="p{i}-c0-0">항목</th><td data-edit="p{i}-c0-1">원본</td></tr></table>'
                         '</div><details class="data-notes"><summary>차트 근거</summary><p>10</p></details></section>')
        return shell.render_shell(
            title='발표 <예시>', slides_html=''.join(pages), width=960, height=540,
            notes={'P01': {'text': '</script><script>alert(1)</script>', 'source': '가상 자료'}},
            metadata_html='<script id="company-agent-ppt-scene" type="application/json">{"pages":[]}</script>'
                          '<script id="company-agent-ppt-template" type="application/json">{}</script>',
            extra_head='<meta name="ppt-deck-format" content="editable-scene-v1">',
            design_css='.ppt-slide{background:var(--paper);font-family:var(--font)}')

    def test_controls_are_default_and_design_and_notes_stay_separate(self):
        document = self.document()
        self.assertIn('data-ppt-deck="1"', document)
        for identity in ('deck-prev', 'deck-next', 'deck-save', 'deck-edit-toggle', 'deck-notes-toggle', 'deck-overview-toggle'):
            self.assertIn(f'id="{identity}"', document)
        self.assertIn('전체 12장', document)
        self.assertEqual(document.count('class="ppt-slide"'), 12)
        self.assertIn('--paper:#f0faf9;--font:Malgun Gothic', document)
        self.assertIn('발표 &lt;예시&gt;', document)
        self.assertNotIn('<script>alert(1)', document)
        config = json.loads(re.search(r'<script id="deck-config"[^>]*>(.*?)</script>', document, re.S)[1])
        self.assertEqual(config['notes']['P01']['text'], '</script><script>alert(1)</script>')
        self.assertIn('page-break-after:always', document)
        self.assertIn('prefers-reduced-motion', document)

    def test_only_shipped_script_has_csp_permission_and_saved_edit_keeps_scene_baseline(self):
        document = self.document(1)
        digest = base64.b64encode(hashlib.sha256(shell.SCRIPT.encode('utf-8')).digest()).decode('ascii')
        self.assertIn('sha256-' + digest, document)
        self.assertNotIn("script-src 'unsafe-inline'", document)
        self.assertNotIn("script-src &#x27;unsafe-inline&#x27;", document)
        self.assertIn("querySelectorAll('#company-agent-ppt-template')", shell.SCRIPT)
        self.assertNotIn("querySelectorAll('#company-agent-ppt-scene", shell.SCRIPT)
        self.assertIn("removeAttribute('inert')", shell.SCRIPT)
        self.assertIn('HTML 수정본입니다.', shell.SCRIPT)

    def test_invalid_frame_and_page_counts_do_not_produce_empty_viewer(self):
        args = dict(title='x', slides_html='', width=960, height=540, notes={})
        for changed in ({}, {'width': float('nan')}, {'height': -1}, {'notes': []},
                        {'slides_html': '<div class="ppt-slide"></div>' * 61}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                shell.render_shell(**{**args, **changed})

    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    def test_browser_script_parses(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'deck.js'
            script.write_text(shell.SCRIPT, encoding='utf-8')
            result = subprocess.run([shutil.which('node'), '--check', str(script)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    @unittest.skipUnless(os.environ.get('COMPANY_DECK_BROWSER_TEST') == '1', 'opt-in local browser interaction')
    def test_real_browser_navigation_edit_save_reload_and_metadata(self):
        candidates = []
        for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
            candidates.extend(Path(os.environ[base]) / relative for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if base in os.environ)
        candidates.extend(Path(value) for name in ('chromium', 'google-chrome', 'microsoft-edge') if (value := shutil.which(name)))
        browser = next((path for path in candidates if path.is_file()), None)
        if browser is None:
            self.skipTest('No local Chromium browser')
        script = r"""(async()=>{try{
          const errors=[], check=(value,message)=>{if(!value)errors.push(message)};
          check(window.deck.ids.length===12,'12 pages');
          document.querySelector('#deck-next').click();check(window.deck.current==='P02','next');
          document.querySelector('[data-goto="P12"]').click();check(window.deck.current==='P12','12th');
          document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));check(window.deck.current==='P01','Home');
          document.querySelector('#deck-notes-toggle').click();check(document.body.classList.contains('deck-notes-open'),'notes');
          check(document.querySelector('#deck-note-text').textContent.includes('<\/script>'),'notes literal');
          document.querySelector('#deck-notes-close').click();
          document.querySelector('#deck-edit-toggle').click();
          const title=document.querySelector('[data-deck-title]');title.textContent='수정 제목';title.dispatchEvent(new InputEvent('input',{bubbles:true}));
          const cell=document.querySelector('td[data-edit]');cell.textContent='변경 값';cell.dispatchEvent(new InputEvent('input',{bubbles:true}));
          check(document.querySelector('#deck-note-title').textContent==='수정 제목','live edited title');
          document.querySelector('#deck-overview-toggle').click();check(document.querySelectorAll('.deck-thumb').length===12,'overview');
          check(document.querySelector('.deck-thumb-caption span').textContent==='수정 제목','overview updated title');
          check(document.querySelector('#deck-workspace').inert,'modal inert');
          let blob;const make=URL.createObjectURL;URL.createObjectURL=value=>{blob=value;return make(value)};HTMLAnchorElement.prototype.click=function(){};
          window.deck.save();const saved=await blob.text(),doc=new DOMParser().parseFromString(saved,'text/html');
          check(!doc.querySelector('[contenteditable]'),'save editing cleared');check(!doc.querySelector('[inert]'),'save inert cleared');
          check(!!doc.querySelector('#company-agent-ppt-scene'),'scene baseline retained');check(!doc.querySelector('#company-agent-ppt-template'),'stale template removed');
          check(doc.body.dataset.pptEdited==='1','edited marked');
          check(!doc.querySelector('#deck-overview-grid').children.length,'no duplicated thumbnail contents');
          const pre=document.createElement('pre');pre.id='test-result';pre.textContent=JSON.stringify({errors,saved});document.body.append(pre);
        }catch(error){const pre=document.createElement('pre');pre.id='test-result';pre.textContent=JSON.stringify({error:String(error)});document.body.append(pre)}})();"""
        reload = """window.deck.show(11);document.querySelector('#deck-edit-toggle').click();window.deck.fit();const pre=document.createElement('pre');pre.id='test-result';pre.textContent=JSON.stringify({page:window.deck.current,title:document.querySelector('[data-deck-title]').textContent,cell:document.querySelector('td[data-edit]').textContent,inert:document.querySelector('#deck-workspace').inert,toastClear:document.querySelector('#deck-toast').getBoundingClientRect().bottom<=document.querySelector('#deck-toolbar').getBoundingClientRect().top-12});document.body.append(pre);"""
        with tempfile.TemporaryDirectory(prefix='ppt-shared-deck-') as temporary:
            root = Path(temporary)

            def run(document, script, number):
                digest = base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii')
                # Only the harmless test script gets extra authorization in this fixture.
                marker = "script-src &#x27;"
                if marker in document:
                    document = document.replace(marker, f"script-src &#x27;sha256-{digest}&#x27; &#x27;", 1)
                else:
                    document = document.replace("script-src '", f"script-src 'sha256-{digest}' '", 1)
                page = root / f'test-{number}.html'
                page.write_text(document.replace('</body>', '<script id="test-script">' + script + '</script></body>'), encoding='utf-8')
                result = subprocess.run([str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                    '--disable-background-networking', '--disable-extensions', '--disable-component-update', '--disable-sync', '--metrics-recording-only',
                    '--user-data-dir=' + str(root / f'profile-{number}'), '--window-size='+('520,900' if number == 2 else '1400,900'), '--virtual-time-budget=1500', '--dump-dom', page.as_uri()],
                    capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                parsed = ResultReader(); parsed.feed(result.stdout.decode('utf-8-sig')); parsed.close()
                self.assertTrue(parsed.value, f'Browser returned {result.returncode}, no result')
                return json.loads(parsed.value)

            result = run(self.document(), script, 1)
            self.assertEqual(result.get('errors'), [], result.get('error') or result.get('errors'))
            saved = re.sub(r'<script id="test-script">.*?</script>', '', result['saved'], flags=re.S)
            reopened = run(saved, reload, 2)
            self.assertEqual(reopened, {'page': 'P12', 'title': '수정 제목', 'cell': '변경 값', 'inert': False, 'toastClear': True})


if __name__ == '__main__':
    unittest.main()
