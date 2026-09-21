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
       'USER_GUIDE.md':'Company-Agent-사용자-안내서.html',
       'CLAUDE_CODE_COMMANDS.md':'Claude-Code-필수-사용법.html',
       'CLAUDE_CODE_BASICS.md':None}
HTMLS=[name for name in FILES.values() if name]
MARKDOWN=[*FILES, 'README.md']
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

    def test_storage_and_learning_limits_are_explained_to_users(self):
        handbook=(ROOT/'docs/COMPANY_AGENT_HANDBOOK.md').read_text(encoding='utf-8')
        self.assertIn(r'%LOCALAPPDATA%\CompanyAgent\states\user',handbook)
        for term in ('project-scopes/', 'memory/items/', 'personal-root/.claude/skills/',
                     'learning/state.json', 'Claude 자체', 'User 설치', 'Project 설치'):
            self.assertIn(term,handbook)
        for name in ('COMPANY_AGENT_HANDBOOK.md','USER_GUIDE.md','ONBOARDING_COURSE.md'):
            text=(ROOT/'docs'/name).read_text(encoding='utf-8')
            for term in ('새 스킬', '자동 학습', '일시 중지'):
                self.assertIn(term,text,name)
        index=(ROOT/'docs/README.md').read_text(encoding='utf-8')
        for term in ('어디에 저장', '후크', '무엇을 자동으로'):
            self.assertIn(term,index)

    def test_default_skills_match_source_exactly(self):
        text=(ROOT/'docs/COMPANY_AGENT_HANDBOOK.md').read_text(encoding='utf-8')
        section=text.split('## 4.',1)[1].split('## 5.',1)[0]
        documented=set(re.findall(r'^\| `company-agent:([\w-]+)` \|',section,re.M))
        actual={p.parent.name for p in (PLUGIN/'skills').glob('*/SKILL.md')
                if 'disable-model-invocation: true' not in p.read_text(encoding='utf-8').split('---',2)[1]}
        self.assertEqual(actual,documented)
        self.assertEqual(11,len(actual))
        self.assertIn(f'기본 스킬 {len(actual)}개와 이전 이름 1개',text)
        compatibility=(PLUGIN/'skills/platform-mcp-builder/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('disable-model-invocation: true',compatibility.split('---',2)[1])
        self.assertIn('호환용으로만 남아',text)

    def test_current_implementation_inventory_tracks_skill_removal(self):
        skills=list((PLUGIN/'skills').glob('*/SKILL.md'))
        automatic=[p for p in skills
                   if 'disable-model-invocation: true' not in p.read_text(encoding='utf-8').split('---',2)[1]]
        review=(ROOT/'docs/IMPLEMENTATION_REVIEW.md').read_text(encoding='utf-8')
        self.assertIn(f'현재 소스의 기본 스킬 파일은 {len(skills)}개',review)
        self.assertIn(f'자동 호출 가능 {len(automatic)}개와 호환 안내 {len(skills)-len(automatic)}개',review)

    def test_current_install_entry_points_do_not_send_staff_to_old_releases(self):
        # Historical UPDATE/VALIDATION records retain their original versions.
        # Only the currently linked install instructions must agree with README.
        readme=(ROOT/'README.md').read_text(encoding='utf-8')
        version=re.search(r'현재 공개 배포 버전은 \*\*([\d.]+)\*\*',readme).group(1)
        for name in ('DEPLOYMENT.md','BUSINESS_PILOT_GUIDE.md','LOCAL_WORKSPACE.md'):
            intro='\n'.join((ROOT/'docs'/name).read_text(encoding='utf-8').splitlines()[:40])
            self.assertIn(version,intro,name)
            linked=re.findall(r'/releases/(?:tag|download)/v([\d.]+)',intro)
            self.assertTrue(all(v==version for v in linked),(name,linked))

    def test_audit_guidance_gives_next_steps_without_claiming_full_plugin_install(self):
        handbook=(ROOT/'docs/COMPANY_AGENT_HANDBOOK.md').read_text(encoding='utf-8')
        for name in ('Karpathy','Superpowers','Ponytail','i-have-adhd'):
            self.assertIn(name,handbook)
        self.assertIn('외부 플러그인 전체를 설치한 것이 아니며',handbook)
        self.assertIn('별도 ADHD 병렬 추론 프로젝트는 도입하지 않았습니다',handbook)
        for name in ('USER_GUIDE.md','ONBOARDING_COURSE.md','COMPANY_AGENT_HANDBOOK.md'):
            text=(ROOT/'docs'/name).read_text(encoding='utf-8')
            for phrase in ('정적','재시험','저장 범위'):
                self.assertIn(phrase,text,name)
        basics=(ROOT/'docs/CLAUDE_CODE_BASICS.md').read_text(encoding='utf-8')
        self.assertIn('종료를 확인하지 못하면 중지 성공으로 표시하지 않습니다',basics)
        self.assertIn('모든 하위 프로그램의 종료를 보장하지는 않습니다',basics)

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
                if output:
                    legacy=(ROOT/'docs'/output).read_text(encoding='utf-8')
                    self.assertIn('href="'+GUIDE+'#',legacy)
                    self.assertNotIn('<pre>',legacy)
        ids=re.findall(r'\bid="([^"]+)"',page)
        self.assertEqual(len(ids),len(set(ids)))
        for link in re.findall(r'href="([^"]+)"',page):
            self.assertTrue(link.startswith(('#','https://')),link)
            if link.startswith('#'):
                self.assertIn(link[1:],ids)
        for part in ('onboarding','basics','usage','handbook','commands'):
            self.assertIn(part,ids)
        self.assertIn('id="onboarding-section-9">8. 개인 스킬',page)

    def test_both_bundle_builders_include_every_manual(self):
        for builder in ['New-WorkspaceBundle.ps1','New-OfflineBundle.ps1']:
            text=(ROOT/'deploy'/builder).read_text(encoding='utf-8')
            for name in [*MARKDOWN,*HTMLS,GUIDE]:
                self.assertIn(name,text)
            self.assertIn('AUDIT_HARNESS_2026-09-20.md',text)
            self.assertIn('SKILL_PRIORITY.md',text)
        # Windows PowerShell 5.1 otherwise misreads Korean filenames in source.
        builder=ROOT/'deploy/New-WorkspaceBundle.ps1'
        self.assertTrue(builder.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_installed_manuals_match_source_and_local_links(self):
        installed=PLUGIN/'resources/manuals'
        self.assertEqual({*HTMLS,GUIDE},{p.name for p in installed.glob('*.html')})
        for name in [*HTMLS,GUIDE]:
            page=(installed/name).read_text(encoding='utf-8')
            self.assertEqual((ROOT/'docs'/name).read_bytes(),(installed/name).read_bytes())
            for link in re.findall(r'href="([^"#]+\.html)(?:#[^"]*)?"',page):
                self.assertTrue((installed/link).is_file(),link)

    def test_markdown_survives_installation_without_drifting_or_broken_links(self):
        installed=PLUGIN/'resources/manuals'
        self.assertEqual(set(MARKDOWN),{p.name for p in installed.glob('*.md')})
        for name in MARKDOWN:
            with self.subTest(name=name):
                source=(ROOT/'docs'/name).read_bytes()
                self.assertEqual(source,(installed/name).read_bytes())
                text=source.decode('utf-8')
                self.assertTrue(text.startswith('# '))
                self.assertNotIn('\ufffd',text)
                for link in re.findall(r'\]\(([^)\s]+)\)',text):
                    if not link.startswith(('https://','#')):
                        filename=link.split('#',1)[0]
                        self.assertIn(filename,[*MARKDOWN,GUIDE],name)
                        self.assertTrue((installed/filename).is_file(),link)

    def test_markdown_index_basics_and_shortcuts_are_beginner_facing(self):
        index=(ROOT/'docs/README.md').read_text(encoding='utf-8')
        for name in FILES:
            self.assertIn(']('+name+')',index)
        for phrase in ('회사 자료나 참고 PPT','안내서 전체를 `CLAUDE.md`나 기억에 복사'):
            self.assertIn(phrase,index)
        basics=(ROOT/'docs/CLAUDE_CODE_BASICS.md').read_text(encoding='utf-8')
        for phrase in ('작업 폴더','승인·중단·되돌리기','대화·프로젝트 지침·기억','사용량','미확인'):
            self.assertIn(phrase,basics)
        commands=(ROOT/'docs/CLAUDE_CODE_COMMANDS.md').read_text(encoding='utf-8')
        for entry in ('Ctrl+C','Ctrl+D','Ctrl+G','Shift+Tab','/usage','/permissions','/plan','/copy','/rewind'):
            self.assertIn(entry,commands)
        self.assertIn('일반 복사 키로 생각하지 마',commands)
        self.assertIn('2026-09-20',commands)

    def test_packaging_rejects_stale_installed_markdown(self):
        builder=(ROOT/'deploy/New-OfflineBundle.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('Required Markdown manual is missing',builder)
        self.assertIn('Packaged Markdown is out of date',builder)
        self.assertLess(builder.index('Packaged Markdown is out of date'),
                        builder.index('$stagePath ='))

    def test_onboarding_is_discoverable_without_an_always_on_hook(self):
        first=(PLUGIN/'resources/first-work.html').read_text(encoding='utf-8')
        self.assertIn('href="manuals/'+GUIDE+'"',first)
        self.assertIn('href="manuals/README.md"',first)
        installer=(ROOT/'deploy/Install-ScopedCompanyAgent.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("resources\\manuals\\"+GUIDE,installer)
        self.assertIn('resources\\manuals\\README.md',installer)
        self.assertIn('처음이라면 이 파일을 열고',installer)
        self.assertNotIn('onboarding',(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8').lower())
        self.assertIn('통합 가이드',(ROOT/'INSTALL_WITH_CLAUDE.md').read_text(encoding='utf-8'))

    def test_no_materials_course_matches_ui_and_safe_workflow(self):
        course=json.loads((PLUGIN/'resources/onboarding-course.json').read_text(encoding='utf-8'))
        self.assertEqual(len(course['steps']),5)
        first=course['steps'][0]
        for phrase in ('실습_가상자료.md','회사 시스템','덮어쓰지','기억에 저장하지 마'):
            self.assertIn(phrase,first['prompt'])
        self.assertIn('실제로 읽고',first['alternativePrompt'])
        ppt=course['steps'][1]['alternativePrompt']
        for phrase in ('참고 파일은 없어','새 디자인','HTML 초안','내가 확인하면','최종 PPT 한 파일','자동 설치하지 마'):
            self.assertIn(phrase,ppt)
        text=(ROOT/'docs/ONBOARDING_COURSE.md').read_text(encoding='utf-8')
        for phrase in ('1-1. 준비물 없는','1-2. 만든 파일','미실행','목표 합계 300'):
            self.assertIn(phrase,text)
        self.assertNotIn('company-agent:office-reader',text)
        self.assertNotIn('이 범위 읽기 승인',text)
        self.assertIn(first['prompt'],(PLUGIN/'resources/first-work.html').read_text(encoding='utf-8'))

    def test_beginner_copy_is_plain_and_excludes_internal_delivery_notes(self):
        page=(ROOT/'docs'/GUIDE).read_text(encoding='utf-8')
        self.assertIn('01 · 시작하기',page)
        self.assertIn('Company Agent 시작하기',page)
        for phrase in ('실습_가상자료.md','실습_가상실적.pptx','회사 공통','개인 전체','이 프로젝트'):
            self.assertIn(phrase,page)
        for file in [*(ROOT/'docs'/name for name in [*MARKDOWN,*HTMLS,GUIDE]),
                     PLUGIN/'resources/first-work.html', PLUGIN/'resources/onboarding-course.json']:
            text=file.read_text(encoding='utf-8')
            for phrase in ('온보딩','내 하네스에서 여는 곳','수정용 원본:',
                           '담당자용 소스 문서','이 원본은 업무 예문만 관리',
                           '문서와 구현을 함께 관리하기','LOCAL · OFFLINE · KOREAN'):
                self.assertNotIn(phrase,text,str(file))
        # Keep existing file names and section URLs usable after the wording change.
        for anchor in ('onboarding-section-2','onboarding-section-7','onboarding-section-8','onboarding-section-9'):
            self.assertIn('id="'+anchor+'"',page)
        course=json.loads((PLUGIN/'resources/onboarding-course.json').read_text(encoding='utf-8'))
        for filename in ('실습_가상자료.md','실습_가상실적.pptx'):
            self.assertIn(filename,json.dumps(course,ensure_ascii=False))

    def test_guide_is_not_injected_in_runtime_context(self):
        for folder in (PLUGIN/'hooks',PLUGIN/'scripts/company_agent'):
            for file in folder.glob('*'):
                if file.suffix in ('.py','.json'):
                    self.assertNotIn(GUIDE,file.read_text(encoding='utf-8'),str(file))

    def test_removed_screen_control_is_not_shipped_or_advertised(self):
        for name in ('local_app/computer_use.py', 'docs/CUA_DRIVER_PILOT.md',
                     'docs/Company-Agent-Cua-Pilot.html',
                     'company-agent-plugin/resources/manuals/CUA_DRIVER_PILOT.md',
                     'company-agent-plugin/resources/manuals/Company-Agent-Cua-Pilot.html',
                     'company-agent-plugin/skills/cua-driver'):
            self.assertFalse((ROOT/name).exists(),name)
        for folder in (ROOT/'local_app', PLUGIN/'hooks', PLUGIN/'resources/manuals'):
            for file in folder.rglob('*'):
                if file.suffix in ('.py','.js','.json','.md','.html'):
                    self.assertNotRegex(file.read_text(encoding='utf-8'),
                                        r'(?i)\bcua(?:\b|[가-힣])|trycua|cua[-_.]|computer_use|computer-check|화면 조작 시험',str(file))


if __name__=='__main__':
    unittest.main()
