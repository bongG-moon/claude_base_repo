"""Offline report navigation: motion must never gate content or keyboard use."""
import base64
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.business_artifacts import create_html, _CSS, _JS
from company_agent.report_design import INTERFACE_CSS


class ReportMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / '업무.html'

    def spec(self):
        return {'title': '검토 자료', 'mode': 'both', 'sections': [
            {'title': '첫 화면', 'body': '확인한 근거입니다.'},
            {'title': '긴 표', 'table': {'headers': ['이름', '처리'], 'rows': [['한글 이름', 12]]}},
            {'title': '확인 사항', 'body': '다음 결정에 필요한 사항입니다.'}]}

    def test_default_motion_is_short_local_feedback_with_csp_hash(self):
        self.assertTrue(create_html(self.spec(), self.target)['ok'])
        text = self.target.read_text(encoding='utf-8')
        self.assertIn('data-motion="subtle"', text)
        script = re.search(r'<script>(.*?)</script>', text, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn('sha256-' + digest, text)
        self.assertIn('180ms', text)
        self.assertIn('120ms', text)
        self.assertNotIn('IntersectionObserver', script)
        # Navigation never waits. CSV download cleanup may revoke its Blob URL
        # later so Chromium can finish handing the file to the download manager.
        self.assertNotIn('setTimeout', _JS)
        self.assertNotIn('requestAnimationFrame', script)
        self.assertNotIn('<script src=', text)

    def test_motion_can_be_disabled_without_changing_content_or_choices(self):
        spec = self.spec(); spec['motion'] = 'none'
        result = create_html(spec, self.target)
        self.assertTrue(result['ok'], result)
        text = self.target.read_text(encoding='utf-8')
        self.assertIn('data-motion="none"', text)
        for section in spec['sections']:
            self.assertIn(section['title'], text)

    def test_invalid_motion_is_rejected_without_writing(self):
        for value in ('bounce', 'subtle" onclick="bad', None, False, [], {}):
            with self.subTest(value=value):
                result = create_html({**self.spec(), 'motion': value}, self.target)
                self.assertEqual('invalid_motion', result['code'])
                self.assertFalse(self.target.exists())

    def test_no_script_fallback_and_reduced_motion_and_print_keep_content(self):
        # Hiding is enabled only after the navigation controller initialized.
        self.assertNotIn('body[data-view=slides] main>.section{display:none}', _CSS)
        self.assertIn('body.report-ready[data-view=slides] main>.section{display:none}', _CSS)
        self.assertIn('.section{display:block!important', _CSS)
        self.assertIn('@media screen and (prefers-reduced-motion:no-preference)', INTERFACE_CSS)
        self.assertIn('@media(prefers-reduced-motion:reduce)', INTERFACE_CSS)
        self.assertIn('@media print{*,*::before,*::after{animation:none!important', INTERFACE_CSS)
        self.assertNotRegex(INTERFACE_CSS, r'opacity\s*:\s*0(?:[;}])')

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for offline controller test')
    def test_navigation_keyboard_tables_and_rapid_changes_without_timers(self):
        harness = r'''
const assert=require('assert'),vm=require('vm');
function setup(view){
 const events={}, elements={};
 function classes(){const values=new Set();return{add(n){values.add(n)},toggle(n,v){v?values.add(n):values.delete(n)},contains(n){return values.has(n)}}}
 const sections=[0,1,2].map(()=>({classList:classes()}));
 for(const id of ['previous','next','toggle-view','print','slide-count'])elements[id]={disabled:false,textContent:'',callbacks:{},addEventListener(k,f){this.callbacks[k]=f},click(){if(!this.disabled)this.callbacks.click()}};
 const body={dataset:{view},classList:classes()};let printed=0;
 const context={document:{body,querySelectorAll(){return sections},getElementById(id){return elements[id]},addEventListener(k,f){events[k]=f}},window:{print(){printed++}}};
 return{context,elements,sections,body,events,printed:()=>printed,key(key,protectedTarget=false,mods={}){let prevented=false;events.keydown({key,target:{closest(){return protectedTarget}},preventDefault(){prevented=true},...mods});return prevented}};
}
'''
        checks = '''
for(const mode of ['scroll','slides']){
 const f=setup(mode);vm.runInNewContext(SOURCE,f.context);
 assert(f.body.classList.contains('report-ready'));assert(f.sections[0].classList.contains('active'));assert(f.elements.previous.disabled);
 if(mode==='scroll'){assert.equal(f.key('ArrowRight'),false);f.elements['toggle-view'].click()}
 assert.equal(f.body.dataset.view,'slides');assert.equal(f.key('ArrowRight'),true);assert(f.sections[1].classList.contains('active'));
 assert.equal(f.key('ArrowRight',true),false);assert(f.sections[1].classList.contains('active'));
 assert.equal(f.key('ArrowRight',false,{ctrlKey:true}),false);assert(f.sections[1].classList.contains('active'));
 f.elements.next.click();assert(f.elements.next.disabled);assert.equal(f.elements['slide-count'].textContent,'3 / 3');
 for(let i=0;i<20;i++){f.elements.previous.click();f.elements.next.click()}
 assert.equal(f.sections.filter(s=>s.classList.contains('active')).length,1);assert.equal(f.elements['slide-count'].textContent,'3 / 3');
 f.elements['toggle-view'].click();assert.equal(f.body.dataset.view,'scroll');assert.equal(f.key('ArrowLeft'),false);
 f.elements.print.click();assert.equal(f.printed(),1);
}
const broken=setup('slides');broken.context.document.querySelectorAll=()=>[];vm.runInNewContext(SOURCE,broken.context);assert.equal(broken.body.classList.contains('report-ready'),false);
'''
        import json
        result = subprocess.run([shutil.which('node'), '-e', harness + '\nconst SOURCE=' + json.dumps(_JS) + ';\n' + checks],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
