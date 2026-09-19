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
       'CUA_DRIVER_PILOT.md':'Company-Agent-Cua-Pilot.html'}


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
        self.assertEqual(12,len(actual))

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
        for source,output in FILES.items():
            with self.subTest(source=source):
                raw=(ROOT/'docs'/source).read_text(encoding='utf-8')
                page=(ROOT/'docs'/output).read_text(encoding='utf-8')
                sha=hashlib.sha256(raw.encode()).hexdigest()
                self.assertIn('content="'+sha+'"',page)
                self.assertIn("script-src 'none'",page)
                self.assertIn("connect-src 'none'",page)
                self.assertNotRegex(page,r'<(?:script|iframe|object|img)\b')
                self.assertNotIn('\ufffd',page)
                for link in re.findall(r'href="([^"#]+\.html)"',page):
                    self.assertIn(link,FILES.values())
                    self.assertTrue((ROOT/'docs'/link).is_file())

    def test_both_bundle_builders_include_every_manual(self):
        for builder in ['New-WorkspaceBundle.ps1','New-OfflineBundle.ps1']:
            text=(ROOT/'deploy'/builder).read_text(encoding='utf-8')
            for name in [*FILES,*FILES.values()]:
                self.assertIn(name,text)

    def test_installed_manuals_match_source_and_local_links(self):
        installed=PLUGIN/'resources/manuals'
        self.assertEqual(set(FILES.values()),{p.name for p in installed.glob('*.html')})
        for name in FILES.values():
            page=(installed/name).read_text(encoding='utf-8')
            self.assertEqual((ROOT/'docs'/name).read_bytes(),(installed/name).read_bytes())
            for link in re.findall(r'href="([^"#]+\.html)"',page):
                self.assertTrue((installed/link).is_file(),link)

    def test_onboarding_is_discoverable_without_an_always_on_hook(self):
        first=(PLUGIN/'resources/first-work.html').read_text(encoding='utf-8')
        for name in ('Company-Agent-Onboarding.html','Company-Agent-Handbook.html'):
            self.assertIn('href="manuals/'+name+'"',first)
        installer=(ROOT/'deploy/Install-ScopedCompanyAgent.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("resources\\manuals\\Company-Agent-Onboarding.html",installer)
        self.assertIn('처음이라면 이 파일을 열고',installer)
        self.assertNotIn('onboarding',(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8').lower())
        self.assertIn('전체 온보딩 코스 따라 하기',(ROOT/'INSTALL_WITH_CLAUDE.md').read_text(encoding='utf-8'))

    def test_cua_remains_opt_in_not_new_skill_or_hook(self):
        self.assertFalse((PLUGIN/'skills/cua-driver').exists())
        self.assertNotIn('cua-driver',(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8'))
        text=(ROOT/'docs/CUA_DRIVER_PILOT.md').read_text(encoding='utf-8')
        for expected in ['실행 없는 준비 확인','실제 사내 HCP','CUA_DRIVER_RS_UPDATE_CHECK=false','강제 제한 장치가 아닙니다']:
            self.assertIn(expected,text)


if __name__=='__main__':
    unittest.main()
