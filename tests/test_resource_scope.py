"""Scope choice, persistence and retrieval; no production state or model calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import cli
from company_agent.asset_factory import create_asset
from company_agent.memory import search_scoped_memory, render_memory_context, MAX_MEMORY_RESULTS, upsert_memory, _load_safe_memory
from company_agent.resource_scope import destinations, selected_root, search_knowledge
from company_agent.skill_registry import inventory_skills
from company_agent.workspace_api import WorkspaceService


class ResourceScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='scope 한글 ')
        self.base = Path(self.tmp.name)
        self.a, self.b, self.state, self.config = [self.base/n for n in ('A', 'B', 'state', 'config')]
        self.a.mkdir(); self.b.mkdir(); self.config.mkdir()
        self.env = patch.dict(os.environ, {'COMPANY_AGENT_SCOPE':'User','CLAUDE_CONFIG_DIR':str(self.config),
                                          'COMPANY_AGENT_CWD':str(self.a)})
        self.env.start()
        self.record = {'scope':'User','userStateRoot':str(self.state),'claudeConfigRoot':str(self.config)}
        self.service = WorkspaceService(self.record, self.a, ROOT/'company-agent-plugin')

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def save(self, scope, title):
        spec = {'kind':'memory','storageScope':scope,'title':title,'body':title+' 조건을 확인한다.'}
        plan = self.service.plan(spec)
        return self.service.apply(plan), plan

    def test_choice_missing_and_company_target_cannot_write(self):
        for value in (None, 'company', 'shared', '../personal'):
            with self.subTest(scope=value), self.assertRaises(ValueError):
                self.service.plan({'kind':'memory','storageScope':value,'title':'선호','body':'결론 먼저'})
        self.assertFalse(self.state.exists())

    def test_user_and_project_memory_are_separate_but_retrievable(self):
        self.save('personal','여러 폴더의 표현')
        project, _ = self.save('project','A에서만 확인')
        a = search_scoped_memory(self.state,self.a,'',MAX_MEMORY_RESULTS)
        b = search_scoped_memory(self.state,self.b,'',MAX_MEMORY_RESULTS)
        self.assertEqual({'personal','project'},{x['storageScope'] for x in a})
        self.assertEqual(['여러 폴더의 표현'],[x['title'] for x in b])
        self.assertNotIn('A에서만',render_memory_context(b))
        self.assertEqual('project',project['scope']['resourceScope'])
        self.assertEqual(1,len(self.service.snapshot('project-memory')['memory']['items']))
        self.assertEqual(1,len(self.service.snapshot('personal-memory')['memory']['items']))
        self.assertFalse((self.b/'.claude').exists())

    def test_preview_rebinds_target_and_rejects_scope_tampering(self):
        saved, plan = self.save('project','프로젝트 값')
        self.assertTrue(self.service.apply(plan)['reused'])
        with self.assertRaises(ValueError):
            self.service.apply({**plan,'storageScope':'personal'})
        other = WorkspaceService(self.record,self.b,ROOT/'company-agent-plugin')
        with self.assertRaises(ValueError):
            other.apply(plan)
        item=self.service.snapshot('project-memory')['memory']['items'][0]
        with self.assertRaises(ValueError):
            self.service.plan({'kind':'memory','storageScope':'personal','itemId':item['id'],
                'expectedSha256':item['sha256'],'title':'복사 금지','body':'잘못된 이동'})
        self.assertTrue(Path(saved['path']).exists())

    def test_relevant_personal_memory_is_not_displaced_by_project_defaults(self):
        for index in range(MAX_MEMORY_RESULTS):
            self.save('project', f'표현 방식 {index}')
        upsert_memory({'kind': 'work_context', 'title': '분기 재고 산식',
                       'body': '재고 기준은 분기 말 확정 수량이다.'}, self.state)
        with patch('company_agent.memory._load_safe_memory', wraps=_load_safe_memory) as read:
            found = search_scoped_memory(self.state, self.a, '분기 재고 산식')
        self.assertEqual('분기 재고 산식', found[0]['title'])
        self.assertEqual('personal', found[0]['storageScope'])
        self.assertEqual(MAX_MEMORY_RESULTS, len(found))
        self.assertEqual(MAX_MEMORY_RESULTS + 1, read.call_count)
        self.assertNotIn('score', found[0])

    def test_scoped_memory_ranks_full_body_and_keeps_project_ties(self):
        project_root = selected_root(self.state, self.a, 'project')
        upsert_memory({'kind': 'work_context', 'title': '개인 계산 기준',
                       'body': '가' * 1100 + ' 심층키워드'}, self.state)
        self.save('project', '일반 표현')
        found = search_scoped_memory(self.state, self.a, '심층키워드', limit=1)
        self.assertEqual('개인 계산 기준', found[0]['title'])
        for folder, title in ((self.state, '공유 계산 기준'), (project_root, '지역 계산 기준')):
            upsert_memory({'kind': 'work_context', 'title': title, 'body': '동점키워드'}, folder)
        found = search_scoped_memory(self.state, self.a, '동점키워드', limit=2)
        self.assertEqual(['project', 'personal'], [item['storageScope'] for item in found])

    def test_scoped_memory_deduplicates_and_bounds_invalid_limits(self):
        self.save('project', '같은 기억')
        self.save('personal', '같은 기억')
        for limit in ('5', None, 'invalid', 999):
            with self.subTest(limit=limit):
                found = search_scoped_memory(self.state, self.a, '', limit=limit)
                self.assertEqual(1, len(found))
                self.assertEqual('project', found[0]['storageScope'])
        for limit in (0, -3, '-1'):
            self.assertEqual([], search_scoped_memory(self.state, self.a, '', limit=limit))

    def test_scope_read_does_not_create_directories(self):
        for view in ('personal-memory','project-memory','personal-harness','project-harness','shared-memory','shared-harness'):
            self.service.snapshot(view)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.a/'.claude').exists())

    def test_project_skill_in_a_not_b_and_personal_skill_in_both(self):
        for scope,name in (('personal','all-folders'),('project','a-only')):
            folder=selected_root(self.state,self.a,scope)
            create_asset({'type':'skill','name':name,'description':'범위 시험','instructions':'수치를 확인한다.'},folder)
        def names(project):
            return {s['name']:s for s in inventory_skills(self.state,project_root=project,claude_root=self.config)['skills']}
        self.assertEqual({'all-folders','a-only'},set(names(self.a)))
        self.assertEqual({'all-folders'},set(names(self.b)))
        self.assertEqual('project',names(self.a)['a-only']['storageScope'])
        self.assertEqual('',names(self.a)['a-only']['invocation']) # exact Read, not invented native Skill

    def test_cli_missing_choice_returns_question_not_error_or_write(self):
        for command in (['memory','upsert'],['knowledge','upsert'],['asset','create']):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                code=cli.main([*command,'--spec',str(self.base/'not-written.json'),'--state-root',str(self.state)])
            value=json.loads(out.getvalue())
            self.assertEqual(0,code)
            self.assertEqual('needs_scope_choice',value['status'])
            self.assertFalse(value['written'])
            self.assertEqual(['personal','project'],[x['id'] for x in value['choices']])
        self.assertFalse(self.state.exists())

    def test_cli_explicit_scope_end_to_end(self):
        spec=self.base/'input.json'
        spec.write_text(json.dumps({'kind':'preference','title':'A 전용','body':'A 지침을 확인한다.'}),encoding='utf-8')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=cli.main(['memory','upsert','--spec',str(spec),'--state-root',str(self.state),
                          '--storage-scope','project','--project-root',str(self.a)])
        self.assertEqual(0,code)
        path=Path(json.loads(out.getvalue())['path'])
        self.assertTrue(path.is_relative_to(selected_root(self.state,self.a,'project')))
        self.assertEqual([],search_scoped_memory(self.state,self.b,''))

    def test_cli_scoped_skill_is_discoverable_only_in_selected_project(self):
        spec=self.base/'skill.json'
        spec.write_text(json.dumps({'type':'skill','name':'only-a','description':'A 범위 시험',
                                    'instructions':'A의 확인한 수치를 비교한다.'}),encoding='utf-8')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=cli.main(['asset','create','--spec',str(spec),'--state-root',str(self.state),
                          '--storage-scope','project','--project-root',str(self.a)])
        self.assertEqual(0,code)
        self.assertTrue(Path(json.loads(out.getvalue())['path']).is_relative_to(selected_root(self.state,self.a,'project')))
        self.assertEqual(['only-a'],[s['name'] for s in inventory_skills(self.state,project_root=self.a,claude_root=self.config)['skills']])
        self.assertEqual([],inventory_skills(self.state,project_root=self.b,claude_root=self.config)['skills'])

    def test_saved_knowledge_is_searchable_without_cross_project_leak(self):
        for scope,title in (('personal','공통 개인 산식'),('project','A의 산식')):
            self.service.apply(self.service.plan({'kind':'knowledge','storageScope':scope,
                'title':title,'body':title+'은 확인된 수치로 계산한다.','reference':'가상 자료 직접 확인','status':'active'}))
        a=search_knowledge(self.state,self.a,'산식',10)
        b=search_knowledge(self.state,self.b,'산식',10)
        self.assertEqual({'personal','project'},{x['storageScope'] for x in a})
        self.assertEqual(['공통 개인 산식'],[x['title'] for x in b])
        self.assertLessEqual(len(search_knowledge(self.state,self.a,'',100)),10)

    def test_knowledge_draft_is_listed_but_not_automatically_applied(self):
        self.service.apply(self.service.plan({'kind':'knowledge','storageScope':'project',
            'title':'미확인 산식','body':'확인하기 전 초안이다.','reference':'가상 검토 대기'}))
        self.assertEqual(1,len(self.service.snapshot('project-memory')['knowledge']['items']))
        self.assertEqual([],search_knowledge(self.state,self.a,'산식',10))

    def test_project_tool_create_validate_activate_run_keeps_its_scope(self):
        spec=self.base/'tool.json'
        spec.write_text(json.dumps({'type':'script-tool','name':'scope-counter','description':'가상 행 계산',
            'code':"import json, sys\np=json.load(sys.stdin)\njson.dump({'count':len(p['rows'])},sys.stdout)\n",
            'input_schema':{'type':'object','required':['rows'],'properties':{'rows':{'type':'array'}}},
            'output_schema':{'type':'object','required':['count'],'properties':{'count':{'type':'integer'}}}}),encoding='utf-8')
        input_path=self.base/'rows.json';input_path.write_text('{"rows":[1,2]}',encoding='utf-8')
        def call(arguments):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                code=cli.main(['asset',*arguments,'--state-root',str(self.state),
                              '--storage-scope','project','--project-root',str(self.a)])
            self.assertEqual(0,code,out.getvalue())
            return json.loads(out.getvalue())
        call(['create','--spec',str(spec)])
        receipt=call(['test-tool','--name','scope-counter','--input',str(input_path),'--timeout','5'])
        active=call(['activate-tool','--name','scope-counter','--receipt',receipt['receipt']])
        skill=(Path(active['skill'])/'SKILL.md').read_text(encoding='utf-8')
        bound=selected_root(self.state,self.a,'project')
        self.assertIn('--state-root "'+bound.as_posix()+'"',skill)
        self.assertIn('cliCommand',skill)
        self.assertEqual(2,call(['run-tool','--name','scope-counter','--input',str(input_path)])['result']['count'])
        self.assertFalse((self.state/'assets/registry.json').exists())
        self.assertEqual([],inventory_skills(self.state,project_root=self.b,claude_root=self.config)['skills'])

    def test_project_store_survives_invalid_or_other_profile_user_registration(self):
        reg=self.base/'registrations'; path=reg/'user/company-agent-install.json';path.parent.mkdir(parents=True)
        record={**self.record,'scope':'Project','registrationsRoot':str(reg),'projectRoot':str(self.a)}
        for content in ('{', '[]', json.dumps({**self.record,'schemaVersion':1,'claudeConfigRoot':str(self.base/'other-profile')})):
            path.write_text(content,encoding='utf-8')
            found=destinations(self.state,self.a,record)
            self.assertFalse(found['personal']['available'])
            self.assertEqual(str(self.state),found['project']['stateRoot'])
        self.assertFalse(self.state.exists())

    def test_project_install_does_not_invent_personal_install(self):
        record={**self.record,'scope':'Project','projectRoot':str(self.a)}
        found=destinations(self.state,self.a,record)
        self.assertFalse(found['personal']['available'])
        self.assertEqual(str(self.state),found['project']['stateRoot'])
        self.assertFalse(self.state.exists())

    def test_project_install_uses_registered_custom_user_path_without_migration(self):
        reg=self.base/'registrations'; path=reg/'user/company-agent-install.json';path.parent.mkdir(parents=True)
        custom=self.base/'custom-user'
        path.write_text(json.dumps({**self.record,'schemaVersion':1,'userStateRoot':str(custom)}),encoding='utf-8')
        record={**self.record,'scope':'Project','registrationsRoot':str(reg),'projectRoot':str(self.a)}
        self.assertEqual(str(custom),destinations(self.state,self.a,record)['personal']['stateRoot'])
        self.assertFalse(custom.exists())

    def test_learning_scope_is_visible_and_not_changed_by_save_choice(self):
        self.save('project','명시적으로만 저장')
        personal=self.service.snapshot('personal-memory')['learning']
        project=self.service.snapshot('project-memory')['learning']
        self.assertTrue(personal['activeInstallation'])
        self.assertFalse(project['activeInstallation'])
        self.assertEqual('개인 전체',project['scopeLabel'])
        with self.assertRaises(ValueError):
            self.service.dispatch({'operation':'learning','storageScope':'project','enabled':False,'confirmed':True})


if __name__ == '__main__':
    unittest.main()
