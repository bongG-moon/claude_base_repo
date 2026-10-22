"""Keep beginner-facing inventory and generated offline readers honest."""
import hashlib
import json
from pathlib import Path
import posixpath
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'company-agent-plugin'
FILES={'COMPANY_AGENT_HANDBOOK.md':None,
       'ONBOARDING_COURSE.md':None,
       'USER_GUIDE.md':'Company-Agent-사용자-안내서.html',
       'CLAUDE_CODE_COMMANDS.md':None,
       'CLAUDE_CODE_BASICS.md':None, 'DESIGN_TERMS.md':None}
HTMLS=[name for name in FILES.values() if name]
MARKDOWN=[*FILES, 'README.md']
GUIDE='Company-Agent-사용자-안내서.html'
STANDALONE='Company-Agent-사용자-안내서.html'


def powershell_files(text, variable):
    """Read the literal packaging allowlist, not incidental filenames/comments."""
    match=re.search(r'\$'+re.escape(variable)+r'\s*=\s*@\((.*?)\)',text,re.S)
    if not match:
        raise AssertionError(f'Missing packaging allowlist: ${variable}')
    values=re.findall(r"'([^']+)'",match.group(1))
    remaining=re.sub(r"'[^']+'|[\s,]",'',match.group(1))
    if remaining or not values:
        raise AssertionError(f'Expected a nonempty literal allowlist: ${variable}')
    return {value.replace('\\','/') for value in values}


class HandbookTests(unittest.TestCase):
    def test_three_scopes_are_consistent(self):
        for file in [ROOT/'docs/COMPANY_AGENT_HANDBOOK.md', ROOT/'docs/ONBOARDING_COURSE.md',
                     ROOT/'docs/COMPANY_PERSONAL_WORKFLOW.md',
                     PLUGIN/'resources/onboarding-course.json', PLUGIN/'skills/company-agent/SKILL.md']:
            text=file.read_text(encoding='utf-8')
            for term in ['회사 공통','개인 전체','이 프로젝트']:
                self.assertIn(term,text,str(file))

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
        self.assertEqual(13,len(actual))
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
        # Version metadata, not an assumption of public release, is authoritative.
        readme=(ROOT/'README.md').read_text(encoding='utf-8')
        version=json.loads((PLUGIN/'.claude-plugin/plugin.json').read_text(encoding='utf-8'))['version']
        self.assertRegex(readme,rf'(?:현재 (?:공개 배포|소스·배포 준비)|이번 배포 대상) 버전은 \*\*{re.escape(version)}\*\*')
        draft='현재 소스·배포 준비 버전은' in readme
        if draft:
            self.assertTrue('Release는 **초안**' in readme or 'Release는 **미게시**' in readme)
        release_state = '미게시' if 'Release는 **미게시**' in readme else '초안'
        for name in ('DEPLOYMENT.md','BUSINESS_PILOT_GUIDE.md'):
            intro='\n'.join((ROOT/'docs'/name).read_text(encoding='utf-8').splitlines()[:40])
            self.assertIn(version,intro,name)
            if draft:
                self.assertIn(release_state,intro,name)
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
        ids=re.findall(r'\bid="([^"]+)"',page)
        self.assertEqual(len(ids),len(set(ids)))
        for link in re.findall(r'href="([^"]+)"',page):
            self.assertTrue(link.startswith(('#','https://')),link)
            if link.startswith('#'):
                self.assertIn(link[1:],ids)
        for part in ('onboarding','basics','usage','handbook','commands','design'):
            self.assertIn(part,ids)
        self.assertIn('id="onboarding-section-9">8. 개인 스킬',page)

    def test_user_guide_is_a_complete_standalone_reader(self):
        canonical=(ROOT/'docs'/GUIDE).read_text(encoding='utf-8')
        page=(ROOT/'docs'/STANDALONE).read_text(encoding='utf-8')
        self.assertEqual(canonical,page)
        self.assertIn('<title>Company Agent 사용자 안내서</title>', page)
        self.assertEqual(len(FILES),len(re.findall(r'<section class="book"',page)))
        chapters=sum(len(re.findall(r'^## ',(ROOT/'docs'/source).read_text(encoding='utf-8'),re.M)) for source in FILES)
        self.assertEqual(chapters,len(re.findall(r'<h3 id="[\w-]+-section-\d+"',page)))
        ids=re.findall(r'\bid="([^"]+)"',page)
        self.assertEqual(len(ids),len(set(ids)))
        for link in re.findall(r'href="([^"]+)"',page):
            self.assertTrue(link.startswith(('#','https://')),link)
            if link.startswith('#'):
                self.assertIn(link[1:],ids)
        self.assertNotIn('href="'+GUIDE,page)
        self.assertNotRegex(page,r'<(?:script|iframe|object|img|link)\b|\son\w+=')
        self.assertIn("script-src 'none'",page)
        self.assertIn("connect-src 'none'",page)
        self.assertIn('data:font/woff;base64,',page)
        self.assertNotIn('\ufffd',page)
        chapter_count=len(re.findall(r'^## ',(ROOT/'docs/USER_GUIDE.md').read_text(encoding='utf-8'),re.M))
        for number in range(1,chapter_count+1):
            self.assertIn(f'<h3 id="usage-section-{number}"><span id="section-{number}"',page)

    def test_harness_bundle_includes_user_manuals_and_operating_contracts(self):
        text=(ROOT/'deploy/New-OfflineBundle.ps1').read_text(encoding='utf-8-sig')
        markdown=powershell_files(text,'markdownManuals')
        operational=powershell_files(text,'operationalDocs')
        self.assertEqual(set(MARKDOWN),markdown)
        html=re.search(r"\$htmlManual\s*=\s*'([^']+)'",text)
        self.assertIsNotNone(html)
        self.assertEqual(GUIDE,html.group(1))
        required={'DEPLOYMENT.md','STATE_PRESERVATION.md','SKILL_PRIORITY.md',
                  'PROJECT_HARNESS.md','MCP_CONTRACTS.md','ADMIN_KNOWLEDGE_GUIDE.md',
                  'LEGACY_MACHINE_DEPLOYMENT.md','SELF_LEARNING.md','BUSINESS_PILOT_GUIDE.md',
                  'SKILL_CATALOG.md','HTML_DESIGN_SELECTION.md','COMPANY_PERSONAL_WORKFLOW.md'}
        self.assertFalse(required-operational,sorted(required-operational))
        app_docs={'LOCAL_WORKSPACE.md','WORKSPACE_STARTUP_DIAGNOSTIC.md','WORKSPACE_USER_GUIDE.html'}
        self.assertFalse(app_docs&(markdown|operational|{GUIDE}))
        for name in markdown|operational|{GUIDE}:
            self.assertTrue((ROOT/'docs'/name).is_file(),name)
            content=(ROOT/'docs'/name).read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)\s]+)\)',content):
                url=urlsplit(target)
                if not url.scheme and not url.netloc:
                    self.assertNotIn(posixpath.basename(unquote(url.path)),app_docs,name)
        self.assertIn('foreach ($docName in @($operationalDocs) + @($markdownManuals) + @($htmlManual))',text)
        self.assertIn("-Destination (Join-Path $stagePath ('docs\\' + $docName))",text)
        self.assertIn('foreach ($manualName in @($markdownManuals) + @($htmlManual))',text)
        self.assertIn('-Destination $manualDestination',text)

    def test_package_contract_rejects_missing_or_dynamic_allowlist(self):
        with self.assertRaisesRegex(AssertionError,'Missing packaging allowlist'):
            powershell_files("# 'USER_GUIDE.md'",'markdownManuals')
        with self.assertRaisesRegex(AssertionError,'nonempty literal allowlist'):
            powershell_files('$markdownManuals = @($unknown)','markdownManuals')

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
        page=(PLUGIN/'resources/manuals'/GUIDE).read_text(encoding='utf-8')
        self.assertIn('href="#onboarding-section-2"',page)
        self.assertFalse((PLUGIN/'resources/first-work.html').exists())
        installer=(ROOT/'deploy/Install-ScopedCompanyAgent.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("resources\\manuals\\"+GUIDE,installer)
        self.assertIn('처음이라면 이 파일을 열고',installer)
        self.assertNotIn('onboarding',(PLUGIN/'hooks/hooks.json').read_text(encoding='utf-8').lower())
        self.assertIn(GUIDE,(ROOT/'INSTALL_WITH_CLAUDE.md').read_text(encoding='utf-8'))

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
        self.assertIn('실습용 가상 자료를 실습_가상자료.md',(PLUGIN/'resources/manuals'/GUIDE).read_text(encoding='utf-8'))

    def test_beginner_copy_is_plain_and_excludes_internal_delivery_notes(self):
        page=(ROOT/'docs'/GUIDE).read_text(encoding='utf-8')
        self.assertIn('01 · 시작하기',page)
        self.assertIn('Company Agent 시작하기',page)
        for phrase in ('실습_가상자료.md','실습_가상실적.pptx','회사 공통','개인 전체','이 프로젝트'):
            self.assertIn(phrase,page)
        for file in [*(ROOT/'docs'/name for name in [*MARKDOWN,*HTMLS,GUIDE]),
                     PLUGIN/'resources/onboarding-course.json']:
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

    def test_duplicate_readers_and_generators_are_removed(self):
        retired=('Company-Agent-Guide.html','Company-Agent-Handbook.html',
                 'Company-Agent-Onboarding.html','Claude-Code-필수-사용법.html')
        for folder in (ROOT/'docs', PLUGIN/'resources/manuals'):
            for name in retired:
                self.assertFalse((folder/name).exists(), str(folder/name))
        self.assertFalse((ROOT/'scripts/build-first-work.py').exists())
        generator=(ROOT/'scripts/build-manuals.mjs').read_text(encoding='utf-8')
        self.assertIn("const output='"+GUIDE+"'",generator)
        self.assertNotIn('emit(standaloneOutput',generator)
        self.assertNotIn('emit(b.legacy',generator)

    def test_removed_screen_control_is_not_shipped_or_advertised(self):
        for name in ('docs/CUA_DRIVER_PILOT.md',
                     'docs/Company-Agent-Cua-Pilot.html',
                     'company-agent-plugin/resources/manuals/CUA_DRIVER_PILOT.md',
                     'company-agent-plugin/resources/manuals/Company-Agent-Cua-Pilot.html',
                     'company-agent-plugin/skills/cua-driver'):
            self.assertFalse((ROOT/name).exists(),name)
        for folder in (PLUGIN/'hooks', PLUGIN/'resources/manuals'):
            for file in folder.rglob('*'):
                if file.suffix in ('.py','.js','.json','.md','.html'):
                    self.assertNotRegex(file.read_text(encoding='utf-8'),
                                        r'(?i)\bcua(?:\b|[가-힣])|trycua|cua[-_.]|computer_use|computer-check|화면 조작 시험',str(file))


if __name__=='__main__':
    unittest.main()
