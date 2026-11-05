"""Visual diagnostics for authored slides using an already-installed browser."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'standalone-skills/presentation/scripts/export_pptx.cjs'
NODE=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
MODULES=NODE.parent.parent/'node_modules'
_BROWSER_RELATIVE='ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe'
_BROWSER_ROOTS=[Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local')), Path.home()/'AppData/Local']
BROWSER=next((base/_BROWSER_RELATIVE for base in _BROWSER_ROOTS if (base/_BROWSER_RELATIVE).exists()), _BROWSER_ROOTS[0]/_BROWSER_RELATIVE)


@unittest.skipUnless(NODE.exists() and (MODULES/'playwright').exists() and BROWSER.exists(), 'existing browser/runtime not available')
class AuditTests(unittest.TestCase):
    def test_catches_slide_overflow_and_svg_line_through_html_label(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; shots=root/'screenshots'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}
            .slide{position:relative;width:400px;height:300px;overflow:hidden}
            .label{position:absolute;left:50px;top:40px;font-size:20px}
            .outside{position:absolute;left:0;top:290px;font-size:20px}
            </style></head><body><main id="deck"><section class="slide">
            <svg width="400" height="100" style="position:absolute;top:0;left:0"><line x1="0" y1="53" x2="200" y2="53" stroke="red"/></svg>
            <div class="label" data-edit="">겹친 글자</div><p class="outside" data-edit="">잘린 마지막 줄</p>
            </section></main></body></html>''',encoding='utf-8')
            before=source.read_bytes();env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--audit-only','--input',str(source),'--screenshots',str(shots),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr)
            data=json.loads(p.stdout); self.assertEqual('ok',data['status'])
            self.assertTrue(data['sourcePreserved']);self.assertEqual(before,source.read_bytes())
            self.assertTrue((shots/'slide-01.png').is_file())
            self.assertTrue(data['layoutWarnings'][0]['scrollOverflow'] or data['layoutWarnings'][0]['examples'])
            self.assertTrue(any('겹친 글자' in x['text'] for x in data['layoutWarnings'][0]['svgIntersections']))
            self.assertFalse((root/'presentation'/'outputs'/'발표본.pptx').exists())

    def test_plain_korean_multiline_keeps_browser_line_boundaries_in_editable_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; dest=root/'new.pptx'
            text='생산 검사 데이터를 확인합니다'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}
            .slide{position:relative;width:400px;height:300px;overflow:hidden}
            .label{position:absolute;left:50px;top:40px;width:120px;font-size:22px;line-height:1.4;word-break:keep-all;font-family:"Malgun Gothic"}
            </style></head><body><main id="deck"><section class="slide">
            <div class="label" data-edit="">'''+text+'''</div></section></main></body></html>''',encoding='utf-8')
            before=source.read_bytes();env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--input',str(source),'--output',str(dest),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr)
            data=json.loads(p.stdout);self.assertEqual('ok',data['status'])
            self.assertTrue(any(c['text']==text and 'line breaks' in c['change'] for c in data['textLinePreservation']['changes']))
            with ZipFile(dest) as archive:slide=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
            shape=next(s for s in slide.findall('.//p:sp',ns) if ''.join(t.text or '' for t in s.findall('.//a:t',ns))==text)
            self.assertGreater(len(shape.findall('.//a:br',ns)),0)
            self.assertEqual('none',shape.find('.//a:bodyPr',ns).get('wrap'))
            self.assertEqual(before,source.read_bytes())

    def test_native_table_keeps_actual_row_heights_column_widths_and_cell_padding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; dest=root/'table.pptx'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}
            .slide{position:relative;width:400px;height:300px;overflow:hidden}
            table{position:absolute;left:20px;top:30px;border-collapse:collapse;width:250px}
            td,th{padding:7px 10px;font-size:18px;line-height:1.4}
            </style></head><body><main id="deck"><section class="slide">
            <table><tr><th>항목</th><th>결과</th></tr><tr><td>생산</td><td>126</td></tr></table>
            </section></main></body></html>''',encoding='utf-8')
            env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--input',str(source),'--output',str(dest),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr)
            data=json.loads(p.stdout);self.assertEqual('ok',data['status'])
            self.assertEqual([2],[t['rows'] for t in data['tableGeometry']['changed']])
            with ZipFile(dest) as archive:slide=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
            table=slide.find('.//a:tbl',ns);self.assertIsNotNone(table)
            rows=table.findall('a:tr',ns);self.assertEqual(len(rows),2)
            self.assertTrue(all(int(r.get('h'))>0 for r in rows))
            self.assertTrue(all(int(c.get('w'))>0 for c in table.findall('a:tblGrid/a:gridCol',ns)))
            self.assertEqual(int(rows[1].find('a:tc/a:tcPr',ns).get('marL')),95250)
            self.assertEqual(''.join(t.text or '' for t in table.findall('.//a:t',ns)),'항목결과생산126')

    def test_multiline_inline_bold_retains_text_and_individual_run_formatting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; dest=root/'rich.pptx'
            text='읽기 전용 권한: 데이터 연결은 기존 읽기 전용 권한만 사용합니다.'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}
            .slide{position:relative;width:400px;height:300px;overflow:hidden}
            p{position:absolute;left:30px;top:30px;width:230px;font-size:22px;line-height:1.4;word-break:keep-all;font-family:"Malgun Gothic"}
            </style></head><body><main id="deck"><section class="slide"><p data-edit="">
            <strong style="color:#c52828">읽기 전용 권한:</strong> 데이터 연결은 기존 읽기 전용 권한만 사용합니다.</p></section></main></body></html>'''.replace('<p data-edit="">\n            ','<p data-edit="">'),encoding='utf-8')
            env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--input',str(source),'--output',str(dest),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr);data=json.loads(p.stdout)
            self.assertTrue(any(c['text']==text and 'line breaks' in c['change'] for c in data['textLinePreservation']['changes']))
            with ZipFile(dest) as archive:slide=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
            shape=next(s for s in slide.findall('.//p:sp',ns) if ''.join(t.text or '' for t in s.findall('.//a:t',ns))==text)
            self.assertGreater(len(shape.findall('.//a:br',ns)),0)
            runs=shape.findall('.//a:r',ns)
            self.assertEqual(''.join(t.text or '' for r in runs for t in r.findall('a:t',ns)),text)
            bold=''.join(''.join(t.text or '' for t in r.findall('a:t',ns)) for r in runs if r.find('a:rPr',ns).get('b')=='1')
            self.assertEqual(bold,'읽기 전용 권한:')
            bold_colors={c.get('val') for r in runs if r.find('a:rPr',ns).get('b')=='1' for c in r.findall('a:rPr/a:solidFill/a:srgbClr',ns)}
            self.assertEqual(bold_colors,{'C52828'})

    def test_unsupported_multiline_mixed_font_size_warns_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; dest=root/'mixed.pptx'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}.slide{position:relative;width:400px;height:300px}
            p{width:210px;font-size:20px;line-height:1.5;word-break:keep-all}span{font-size:28px}
            </style></head><body><main id="deck"><section class="slide"><p data-edit=""><span>강조 문구:</span> 같은 구조에서 추가로 긴 설명을 표기합니다.</p></section></main></body></html>''',encoding='utf-8')
            env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--input',str(source),'--output',str(dest),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr);data=json.loads(p.stdout)
            self.assertGreater(data['textLinePreservation']['skippedCount'],0)
            self.assertTrue(any(w['code']=='multiline_text_unverified' for w in data['layoutWarnings']))
            with ZipFile(dest) as archive:slide=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
            self.assertIn('강조 문구: 같은 구조에서 추가로 긴 설명을 표기합니다.',''.join(t.text or '' for t in slide.findall('.//a:t',ns)))

    def test_merged_table_is_explicitly_reported_for_manual_ppt_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; dest=root/'merged.pptx'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}.slide{width:400px;height:300px;position:relative}
            table{position:absolute;left:20px;top:20px;width:240px}td,th{padding:6px;font-size:18px}
            </style></head><body><main id="deck"><section class="slide"><table>
            <tr><th colspan="2">제목</th></tr><tr><td>항목</td><td>126</td></tr>
            </table></section></main></body></html>''',encoding='utf-8')
            env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--input',str(source),'--output',str(dest),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr)
            data=json.loads(p.stdout); self.assertTrue(data['tableGeometry']['skipped'])
            self.assertTrue(any(w['code']=='table_geometry_unverified' for w in data['layoutWarnings']))
            self.assertTrue(any('표' in s and '화면' in s for s in data['limitations']))

    def test_mixed_size_kpi_and_explicit_line_breaks_keep_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source.html'; dest=root/'text.pptx'
            source.write_text('''<!doctype html><html><head><style>
            :root{--slide-width:400px;--slide-height:300px}.slide{position:relative;width:400px;height:300px}
            .kpi{position:absolute;left:20px;top:10px;width:200px;height:48px;font-size:40px;line-height:1.2;font-weight:700;white-space:nowrap}
            .kpi small{font-size:20px;font-weight:400}.node{position:absolute;left:20px;top:100px;width:160px;height:60px;font-size:18px;line-height:1.3}
            </style></head><body><main id="deck"><section class="slide">
            <div class="kpi" data-edit="">126<small>건</small></div>
            <div class="node" data-edit="">조치 필요<br>승인 여부</div>
            </section></main></body></html>''',encoding='utf-8')
            env=os.environ.copy();env['NODE_PATH']=str(MODULES)
            p=subprocess.run([str(NODE),str(SCRIPT),'--input',str(source),'--output',str(dest),'--browser',str(BROWSER)],capture_output=True,text=True,encoding='utf-8',env=env,timeout=45)
            self.assertEqual(0,p.returncode,p.stdout+p.stderr);data=json.loads(p.stdout)
            self.assertTrue(any(c['text']=='126건' and c['change']=='match browser line height for mixed text sizes' for c in data['textLinePreservation']['changes']))
            with ZipFile(dest) as archive:slide=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
            shapes=slide.findall('.//p:sp',ns)
            kpi=next(s for s in shapes if ''.join(t.text or '' for t in s.findall('.//a:t',ns))=='126건')
            self.assertGreaterEqual(int(kpi.find('.//a:spcPts',ns).get('val')),3000)
            node=next(s for s in shapes if '조치 필요' in ''.join(t.text or '' for t in s.findall('.//a:t',ns)))
            self.assertEqual('none',node.find('.//a:bodyPr',ns).get('wrap'))


if __name__=='__main__':unittest.main()
