"""Portable Huashu subset contracts; browser/Office smoke is recorded separately."""
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT/'standalone-skills/huashu-presentation'


def module(name):
    spec = importlib.util.spec_from_file_location('test_huashu_'+name, SKILL/'scripts'/f'{name}.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.by_id = {}
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get('id'):
            self.by_id[attrs['id']] = (tag, attrs)


class HuashuPresentationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.index = module('build_index')
        self.export = module('export_pptx')

    def source(self, name='01.html'):
        file = self.root/name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('<!doctype html><html lang="ko"><body><section class="slide"><h1>원문 126건</h1></section></body></html>',encoding='utf-8')
        return file

    def test_fixed_upstream_license_engine_and_shell_are_preserved(self):
        fixed = {
            'LICENSE':'6d6a2a9caf2e6d2b76974050427053b2892d8aa4c33fd168ce63a537fcee9d96',
            'scripts/pptx_from_rendered.py':'9c81eac40cafcbd0c213267a0c37419c7fe16811a4da9aa7e3b9bc707aa50315',
            'assets/deck_index.html':'83d63a9ed531fb4f4a7b47c23c13024cb0b1831ab4883fc902bda351724c6820',
        }
        provenance = json.loads((SKILL/'upstream/provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(provenance['commit'],'b2460b031c33ff32d2bf3b97263527daa231e4de')
        self.assertEqual(provenance['license'],'MIT')
        for record in provenance['files']:
            with self.subTest(file=record['path']):
                file = SKILL/'upstream'/record['path']
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),record['sha256'])
                self.assertFalse(record['modified'])
                if record['sourcePath'].endswith('.md'):
                    self.assertEqual(record['path'],record['sourcePath']+'.txt')
        for name, digest in fixed.items():
            self.assertEqual(hashlib.sha256((SKILL/'upstream'/name).read_bytes()).hexdigest(),digest)
        self.assertEqual(list((SKILL/'upstream').rglob('*.md')),[])

    def test_shell_keeps_explicit_slide_order_and_navigation_controls(self):
        first = self.source('slides/첫 장.html')
        second = self.source('slides/a&b.html')
        originals = {p:p.read_bytes() for p in [first,second]}
        output = self.root/'index.html'
        result = self.index.build([second,first],output,1280,720,'품질 발표')
        source = output.read_text(encoding='utf-8')
        manifest = json.loads(re.search(r'window\.DECK_MANIFEST\s*=\s*(\[.*?\]);',source,re.S).group(1))
        self.assertEqual([v['file'] for v in manifest],['slides/a&b.html','slides/첫 장.html'])
        self.assertEqual(manifest[0]['label'],'a&amp;b')
        self.assertEqual(result['defaultView'],'one-slide')
        elements = Elements(source).by_id
        for identity, label in [('navL','이전 장'),('navR','다음 장')]:
            self.assertEqual(elements[identity][0],'button')
            self.assertEqual(elements[identity][1]['aria-label'],label)
        self.assertEqual(elements['overviewBtn'][0],'button')
        self.assertIn('counter',elements)
        self.assertIn('printStack',elements)
        self.assertEqual(source.count('id="frame"'),1)
        for file, content in originals.items():
            self.assertEqual(file.read_bytes(),content)

    def test_existing_shell_output_is_not_changed(self):
        slide = self.source()
        output = self.root/'saved.html'
        output.write_bytes(b'USER SAVED CONTENT')
        with self.assertRaises(FileExistsError):
            self.index.build([slide],output)
        self.assertEqual(output.read_bytes(),b'USER SAVED CONTENT')

    def test_shell_rejects_outside_missing_or_non_html_inputs_without_writes(self):
        outside = self.source()
        target_folder = self.root/'presentation'
        target_folder.mkdir()
        invalid = [outside,self.root/'missing.html',self.source('presentation/file.txt')]
        for number, file in enumerate(invalid):
            with self.subTest(file=file):
                output = target_folder/f'index-{number}.html'
                with self.assertRaises((ValueError,FileNotFoundError)):
                    self.index.build([file],output)
                self.assertFalse(output.exists())
        output = self.root/'bad-size.html'
        with self.assertRaises(ValueError):
            self.index.build([outside],output,0,720)
        self.assertFalse(output.exists())

    def test_export_input_boundary_rejects_network_and_wrong_type(self):
        for invalid in ['https://example.invalid/source.html',r'\\server\share\source.html','//server/share/source.html']:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.export.local_file(invalid,{'.html','.htm'})
        with self.assertRaises(ValueError):
            self.export.local_file(self.source('source.txt'),{'.html','.htm'})
        source = self.source('한국어 입력.html')
        self.assertEqual(self.export.local_file(source,{'.html','.htm'}),source.resolve())

    def test_existing_pptx_is_preserved_before_engine_is_loaded(self):
        source = self.source()
        output = self.root/'saved.pptx'
        output.write_bytes(b'USER EDITED PPTX')
        args = SimpleNamespace(check=False,browser=None,source=[str(source)],output=str(output),
            template=None,layout=None,skip_class=None,selector='.slide',font='Malgun Gothic',background=None,scale=3)
        with patch.object(self.export,'dependencies',return_value={}), \
                patch.object(self.export,'runtime_browser',new=Mock(return_value='test-browser-awaitable')), \
                patch.object(self.export.asyncio,'run',return_value='test-browser'), \
                patch.object(self.export,'load_engine') as engine:
            result = self.export.run(args)
        self.assertFalse(result['ok'])
        self.assertIn('기존 출력',result['error'])
        self.assertEqual(output.read_bytes(),b'USER EDITED PPTX')
        self.assertFalse((self.root/'saved_assets').exists())
        engine.assert_not_called()

    def test_import_does_not_launch_engine_or_write_files(self):
        before = sorted(p.name for p in self.root.iterdir())
        script = '''import importlib.util, pathlib, sys
for name in ('build_index','export_pptx'):
 p=pathlib.Path(sys.argv[1])/'scripts'/(name+'.py')
 spec=importlib.util.spec_from_file_location('isolated_'+name,p)
 mod=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(mod)
assert 'playwright.async_api' not in sys.modules
assert 'pptx' not in sys.modules
assert 'PIL.Image' not in sys.modules
'''
        result = subprocess.run([sys.executable,'-I','-B','-c',script,str(SKILL)],cwd=self.root,
            capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'')
        self.assertEqual(result.stderr,'')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),before)

    def test_active_markdown_links_are_portable_and_resolve(self):
        for file in [SKILL/'SKILL.md',*(SKILL/'references').glob('*.md')]:
            for target in re.findall(r'\]\(([^)]+)\)',file.read_text(encoding='utf-8')):
                with self.subTest(document=file.name,target=target):
                    self.assertNotIn('://',target)
                    resolved = (file.parent/target).resolve()
                    self.assertTrue(resolved.is_relative_to(SKILL.resolve()))
                    self.assertTrue(resolved.is_file())

    def test_raster_capture_uses_shared_sequence_across_svg_and_canvas(self):
        captured, requested = [], []

        class Node:
            def __init__(self, tag, number): self.tag,self.number = tag,number
            def as_element(self): return self
            async def evaluate(self, script): return self.tag
            async def screenshot(self, **kwargs): captured.append((self.number,kwargs['path']))
            async def dispose(self): pass

        class Targets:
            async def evaluate(self, script): return 4
            async def get_property(self, sequence):
                requested.append(sequence)
                number=int(sequence)
                return Node(['svg','canvas','canvas','svg'][number],number)
            async def dispose(self): pass

        class Slide:
            async def evaluate_handle(self, script): return Targets()

        data={'els':[{'kind':'svg','tagName':tag,'seq':i} for i,tag in enumerate(['svg','canvas','canvas','svg'])]}
        task=self.export.capture_rasters(Slide(),data,self.root,'p001')
        # Fake browser operations resolve immediately; no event-loop sockets or
        # browser dependency are needed for this sequence-binding regression.
        with self.assertRaises(StopIteration): task.send(None)
        self.assertEqual(requested,['0','1','2','3'])
        self.assertEqual([v[0] for v in captured],[0,1,2,3])
        self.assertEqual([Path(v['file']).name for v in data['els']],
            ['p001_svg0.png','p001_canvas1.png','p001_canvas2.png','p001_svg3.png'])

    def test_raster_capture_fails_fast_when_dom_no_longer_matches_engine(self):
        class Targets:
            async def evaluate(self, script): return 0
            async def get_property(self, sequence): raise AssertionError('No screenshot lookup should happen')
            async def dispose(self): pass
        class Slide:
            async def evaluate_handle(self, script): return Targets()
        data={'els':[{'kind':'svg','tagName':'canvas','seq':0}]}
        task=self.export.capture_rasters(Slide(),data,self.root,'p001')
        with self.assertRaisesRegex(ValueError,'추출 결과가 다릅니다'): task.send(None)


if __name__ == '__main__':
    unittest.main()
