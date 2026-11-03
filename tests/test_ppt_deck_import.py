import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent import ppt_html_import as module

SOURCE = """<!doctype html><html><head><style>
body{margin:0;font-family:'Malgun Gothic'}#holder{width:1600px;height:900px;transform:scale(.5)}
.slide{position:absolute;width:1600px;height:900px;display:none;background:white}.slide.active{display:block}
h1{position:absolute;left:50px;top:20px;font-size:35px} .body{position:absolute;top:150px;left:50px;width:1450px}
.connection{position:relative;width:100px;height:80px}.connection::before{content:"";position:absolute;top:10px;left:0;right:0;border-top:2px solid #888}
table{border-collapse:collapse;width:1000px;font-size:24px}th{background:#303030;color:#fff}td{background:#eee;color:#222}
</style></head><body><div id="holder"><section class="slide active"><h1>가상 생산 현황</h1><div class="body"><div class="connection"></div><table><tr><th>부서</th><th>실적</th></tr><tr><td>가공</td><td>125</td></tr></table></div></section><section class="slide"><h1>후속 실행 계획</h1><div class="body">담당자는 원인을 확인합니다.</div></section></div><nav><button onclick="evil()">다음</button></nav><script>document.querySelector('h1').textContent='실행되면안됨'</script></body></html>"""

class DeckImportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'발표 자료.html'; self.path.write_text(SOURCE,encoding='utf-8')
 def test_controls_inert_and_deck_mode_typed(self):
  reader,*_=module.source_document({'path':str(self.path),'deckMode':True})
  clean=''.join(reader.parts)
  self.assertNotIn('evil',clean); self.assertNotIn('실행되면안됨',clean)
  with self.assertRaises(Exception):module.source_document({'path':str(self.path),'deckMode':'true'})
 def test_measured_no_wrap_line_does_not_get_guessed_wrap_warning(self):
  from company_agent import ppt_preflight
  plan={'font':'Malgun Gothic','pages':[{'elements':[{'kind':'text','text':'한글 제목과 실제 측정값','x':20,'y':20,'w':135,'h':25,'size':21,'wrap':False,'lineSpacing':1}]}]}
  result=ppt_preflight.inspect_plan(plan)
  self.assertFalse(any(i['code']=='estimated_text_overflow' for i in result['issues']))
 def test_actual_browser_all_pages_and_native_tables(self):
  if os.environ.get('RUN_LOCAL_BROWSER_TESTS')!='1':self.skipTest('explicit local browser test')
  if module.browser_path() is None:self.skipTest('no installed browser')
  data=module.capture({'path':str(self.path),'deckMode':True},{'title':'111111','text':'111111','background':'FFFFFF','accent':'444444','muted':'555555','tint':'EEEEEE'},'Malgun Gothic')
  self.assertEqual(2,len(data['pages']));self.assertAlmostEqual(540,data['height'])
  self.assertEqual('후속 실행 계획',data['pages'][1]['title'])
  table=next(e for e in data['pages'][0]['elements'] if e['kind']=='table')
  self.assertEqual('303030',table['tableStyle']['headerFill']);self.assertEqual('FFFFFF',table['tableStyle']['headerText'])
  self.assertTrue(any(e['kind']=='shape' and e.get('fill')=='888888' for e in data['pages'][0]['elements']))
if __name__=='__main__':unittest.main()
