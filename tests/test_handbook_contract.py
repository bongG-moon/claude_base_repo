"""Keep beginner-facing inventory and generated offline readers honest."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'company-agent-plugin'
FILES={'COMPANY_AGENT_HANDBOOK.md':'Company-Agent-Handbook.html',
       'ONBOARDING_COURSE.md':'Company-Agent-Onboarding.html',
       'CUA_DRIVER_PILOT.md':'Company-Agent-Cua-Pilot.html',
       'USER_GUIDE.md':'Company-Agent-사용자-안내서.html',
       'CLAUDE_CODE_COMMANDS.md':'Claude-Code-필수-사용법.html'}
GUIDE='Company-Agent-Guide.html'


class HandbookTests(unittest.TestCase):
    def test_three_scopes_are_consistent(self):
        for file in [ROOT/'docs/COMPANY_AGENT_HANDBOOK.md', ROOT/'docs/ONBOARDING_COURSE.md',
                     ROOT/'docs/COMPANY_PERSONAL_WORKFLOW.md', ROOT/'local_app/web/companion.js',
                     PLUGIN/'resources/onboarding-course.json', PLUGIN/'skills/company-agent/SKILL.md']:
            text=file.read_text(encoding='utf-8')
            for term in ['회사 공통','개인 전체','이 프로젝트']:
                self.assertIn(term,text,str(file))
        ui=(ROOT/'local_app/web/companion.js').read_text(encoding='utf-8')
        self.assertNotIn("knowledge:'회사·개인 지식'",ui)
        self.assertNotIn("brief:'폴더 업무 지침'",ui)

    def test_default_skills_match_source_exactly(self):
        text=(ROOT/'docs/COMPANY_AGENT_HANDBOOK.md').read_text(encoding='utf-8')
        section=text.split('## 4.',1)[1].split('## 5.',1)[0]
        documented=set(re.findall(r'^\| `company-agent:([\w-]+)` \|',section,re.M))
        actual={p.parent.name for p in (PLUGIN/'skills').glob('*/SKILL.md')}
        self.assertEqual(actual,documented)
        self.assertEqual(13,len(actual))

    def test_hooks_commands_and_agents_match_source(self):
        text=(ROOT/'docs/COMPANY_AGENT_HANDBOOK.md').read_text(encoding='utf-8')
        section=text.split('## 5.',1)[1].split('## 6.',1)[0]
        documented=set(re.findall(r'^\| `(\w+)` \|',section,re.M))
        actual=set(json.loads((PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8'))['hooks'])
        self.assertEqual(actual,documented)
        section=text.split('## 6.',1)[1].split('## 7.',1)[0]
        self.assertEqual({p.stem for p in (PLUGIN/'commands').glob('*.md')},set(re.findall(r'`/company-agent:([\w-]+)`',section)))
        self.assertEqual({p.stem for p in (PLUGIN/'agents').glob('*.md')},set(re.findall(r'`company-agent:([\w-]+)`',section)))

    def test_offline_readers_match_markdown_and_do_not_load_code(self):
        page=(ROOT/'docs'/GUIDE).read_text(encoding='utf-8')
        for source,output in FILES.items():
            with self.subTest(source=source):
                raw=(ROOT/'docs'/source).read_text(encoding='utf-8')
                sha=hashlib.sha256(raw.encode()).hexdigest()
                self.assertIn('data-file="'+source+'" content="'+sha+'"',page)
                self.assertIn("script-src 'none'",page)
                self.assertIn("connect-src 'none'",page)
                self.assertNotRegex(page,r'<(?:script|iframe|object|img)\b')
                self.assertNotIn('\ufffd',page)
                legacy=(ROOT/'docs'/output).read_text(encoding='utf-8')
                self.assertIn('href="'+GUIDE+'#',legacy)
                self.assertNotIn('<pre>',legacy)
        ids=re.findall(r'\bid="([^"]+)"',page)
        self.assertEqual(len(ids),len(set(ids)))
        for link in re.findall(r'href="([^"]+)"',page):
            self.assertTrue(link.startswith(('#','https://')),link)
            if link.startswith('#'):
                self.assertIn(link[1:],ids)
        for part in ('onboarding','usage','handbook','commands','cua'):
            self.assertIn(part,ids)
        self.assertIn('id="onboarding-section-9">8. 개인 스킬',page)

    def test_both_bundle_builders_include_every_manual(self):
        for builder in ['New-WorkspaceBundle.ps1','New-OfflineBundle.ps1']:
            text=(ROOT/'deploy'/builder).read_text(encoding='utf-8')
            for name in [*FILES,*FILES.values(),GUIDE]:
                self.assertIn(name,text)
        # Windows PowerShell 5.1 otherwise misreads Korean filenames in source.
        builder=ROOT/'deploy/New-WorkspaceBundle.ps1'
        self.assertTrue(builder.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_installed_manuals_match_source_and_local_links(self):
        installed=PLUGIN/'resources/manuals'
        self.assertEqual({*FILES.values(),GUIDE},{p.name for p in installed.glob('*.html')})
        for name in [*FILES.values(),GUIDE]:
            page=(installed/name).read_text(encoding='utf-8')
            self.assertEqual((ROOT/'docs'/name).read_bytes(),(installed/name).read_bytes())
            for link in re.findall(r'href="([^"#]+\.html)(?:#[^"]*)?"',page):
                self.assertTrue((installed/link).is_file(),link)

    def test_onboarding_is_discoverable_without_an_always_on_hook(self):
        first=(PLUGIN/'resources/first-work.html').read_text(encoding='utf-8')
        self.assertIn('href="manuals/'+GUIDE+'"',first)
        installer=(ROOT/'deploy/Install-ScopedCompanyAgent.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("resources\\manuals\\"+GUIDE,installer)
        self.assertIn('처음이라면 이 파일을 열고',installer)
        self.assertNotIn('onboarding',(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8').lower())
        self.assertIn('통합 가이드',(ROOT/'INSTALL_WITH_CLAUDE.md').read_text(encoding='utf-8'))

    def test_no_materials_course_matches_ui_and_safe_workflow(self):
        course=json.loads((PLUGIN/'resources/onboarding-course.json').read_text(encoding='utf-8'))
        self.assertEqual(len(course['steps']),5)
        first=course['steps'][0]
        for phrase in ('온보딩_가상자료.md','회사 시스템','덮어쓰지','기억에 저장하지 마'):
            self.assertIn(phrase,first['prompt'])
        self.assertIn('실제로 읽고',first['alternativePrompt'])
        ppt=course['steps'][1]['alternativePrompt']
        for phrase in ('참고 파일은 없어','새 디자인','HTML 초안','내가 확인하면','최종 PPT 한 파일','자동 설치하지 마'):
            self.assertIn(phrase,ppt)
        text=(ROOT/'docs/ONBOARDING_COURSE.md').read_text(encoding='utf-8')
        for phrase in ('1-1. 준비물 없는','1-2. 만든 파일','1-3. Office','MD·HTML 실습만','미실행','목표 합계 300'):
            self.assertIn(phrase,text)
        self.assertIn(first['prompt'],(PLUGIN/'resources/first-work.html').read_text(encoding='utf-8'))

    def test_guide_is_not_injected_in_runtime_context(self):
        for folder in (PLUGIN/'hooks',PLUGIN/'scripts/company_agent'):
            for file in folder.glob('*'):
                if file.suffix in ('.py','.json'):
                    self.assertNotIn(GUIDE,file.read_text(encoding='utf-8'),str(file))

    def test_cua_remains_opt_in_not_new_skill_or_hook(self):
        self.assertFalse((PLUGIN/'skills/cua-driver').exists())
        self.assertNotIn('cua-driver',(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8'))
        text=(ROOT/'docs/CUA_DRIVER_PILOT.md').read_text(encoding='utf-8')
        for expected in ['실행 없는 준비 확인','실제 사내 HCP','CUA_DRIVER_RS_UPDATE_CHECK=false','강제 제한 장치가 아닙니다']:
            self.assertIn(expected,text)


if __name__=='__main__':
    unittest.main()
