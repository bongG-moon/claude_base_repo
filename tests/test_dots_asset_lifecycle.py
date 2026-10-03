"""Isolated DOTS asset integration; local processes only, never model/browser E2E.

DOTS_ASSET_AUDIT_ROOT retains synthetic evidence under an explicitly chosen root.
DOTS_ASSET_NATIVE_MCP=1 additionally uses the installed Claude CLI solely to write
an isolated CLAUDE_CONFIG_DIR. Ordinary tests use the launcher-local registry.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT/'company-agent-plugin'
sys.path.insert(0, str(PLUGIN/'scripts'))
from company_agent.browser_workflow import plan_web_workflow
from company_agent.native_runtime import runtime_context, task_prompt_context
from company_agent.skill_task_context import task_candidates
from company_agent.skill_workflow import observe
from company_agent.state import begin_turn, load_session
from company_agent import asset_factory as assets
from company_agent.paths import atomic_write_json, ensure_user_layout, load_json
from company_agent.mcp_execution import prepare_execution_bundle, bundle_evidence, read_execution_bundle


def context_probe(state, project, name, session, read_body):
    """A real new Python process constructs context; no LLM consumes it."""
    begin_turn(session, 'MEDIUM', False, [], state)
    prompt=f'{name} 스킬을 사용해서 월간 수량 합계 대조를 점검해줘'
    encoded=runtime_context(PLUGIN, project, prompt, session_id=session)
    expanded=task_prompt_context('{"company_agent_instruction":"","company_agent_route":{"tier":"MEDIUM"}}',encoded)
    runtime=json.loads(expanded.splitlines()[-1])['company_agent_runtime']
    execution=runtime.get('skillExecution',{})
    if read_body:
        file=Path(execution['path'])
        content=file.read_text(encoding='utf-8')
        observe(state,project,{'session_id':session,'hook_event_name':'PostToolUse','tool_name':'Read',
            'tool_input':{'file_path':str(file)},'tool_response':{'file':{'content':content,'startLine':1}}})
    route=load_session(session,state).get('skillWorkflow',{})
    return {'execution':execution,'contextChars':len(expanded),'indexMode':runtime.get('skillIndex',{}).get('mode'),
            'bodyReads':len(route.get('readSkills',{})),'selected':route.get('selected'),
            'llmExecuted':False}


class RpcChild:
    """Line-delimited JSON-RPC against the real generated stdio process."""
    def __init__(self, definition, cwd, env):
        self.child=subprocess.Popen([definition['command'],*definition['args']],cwd=cwd,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1)
        self.messages=queue.Queue()
        self.thread=threading.Thread(target=self._read,daemon=True)
        self.thread.start()
        self.sequence=0

    def _read(self):
        for line in self.child.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                self.messages.put({'invalidProtocol':True})

    def send(self, value):
        self.child.stdin.write(json.dumps(value,ensure_ascii=True)+'\n')
        self.child.stdin.flush()

    def call(self, method, params=None):
        self.sequence+=1
        identity=self.sequence
        self.send({'jsonrpc':'2.0','id':identity,'method':method,'params':params or {}})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            item=self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            if item.get('id')==identity:
                return item
        raise TimeoutError(method)

    def initialize(self):
        result=self.call('initialize',{'protocolVersion':'2024-11-05','capabilities':{},
            'clientInfo':{'name':'dots-isolated-audit','version':'1'}})
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
        return result

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()  # Only the exact isolated child created above.
        try:
            self.child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=5)
        self.thread.join(timeout=2)
        self.child.stdin.close()
        self.child.stdout.close()


class DotsAssetLifecycleTests(unittest.TestCase):
    def setUp(self):
        retain=os.environ.get('DOTS_ASSET_AUDIT_ROOT')
        if retain:
            parent=Path(retain).resolve()
            parent.mkdir(parents=True,exist_ok=True)
            self.folder=Path(tempfile.mkdtemp(prefix='assets-',dir=parent))
        else:
            temporary=tempfile.TemporaryDirectory(prefix='dots-assets-')
            self.addCleanup(temporary.cleanup)
            self.folder=Path(temporary.name)
        self.state,self.project,self.claude=[self.folder/name for name in ('state','project','claude')]
        self.project.mkdir()
        self.claude.mkdir()
        self.native=os.environ.get('DOTS_ASSET_NATIVE_MCP')=='1'
        self.env={k:v for k,v in os.environ.items() if not k.startswith(('ANTHROPIC_','OPENAI_','CLAUDE_CODE_OAUTH_'))}
        self.env.update(CLAUDE_CONFIG_DIR=str(self.claude),COMPANY_AGENT_USER_STATE=str(self.state),
            COMPANY_AGENT_SCOPE='User' if self.native else 'Machine',COMPANY_AGENT_PROJECT_ROOT=str(self.project),
            COMPANY_AGENT_CWD=str(self.project),COMPANY_AGENT_PLUGIN_ROOT=str(PLUGIN),
            COMPANY_AGENT_KNOWLEDGE_BASE='',COMPANY_AGENT_REGISTRATIONS_ROOT=str(self.folder/'registrations'),
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',DISABLE_TELEMETRY='1',PYTHONIOENCODING='utf-8')
        self.events=[]
        self.addCleanup(self.save_evidence)

    def save_evidence(self):
        evidence={'test':self.id(),'events':self.events,'externalModelCalled':False,'browserExecuted':False,
                  'nativeRegistrationRequested':self.native,'isolatedRoot':str(self.folder)}
        (self.folder/'assets-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')

    def run_child(self, arguments, expected=0):
        started=time.perf_counter()
        result=subprocess.run([sys.executable,'-X','utf8','-B',*map(str,arguments)],cwd=self.project,
            env=self.env,capture_output=True,text=True,encoding='utf-8',timeout=55)
        self.events.append({'operation':[str(x) for x in arguments[:4]],'seconds':round(time.perf_counter()-started,4),
                            'returncode':result.returncode,'outputBytes':len(result.stdout.encode())})
        self.assertEqual(expected,result.returncode,result.stdout+result.stderr)
        if expected and not result.stdout.strip():
            self.assertTrue(result.stderr.strip(), 'failed CLI should explain the refusal')
            return {'ok':False,'error':result.stderr.strip()}
        return json.loads(result.stdout)

    def cli(self, *args, expected=0):
        return self.run_child([PLUGIN/'scripts/harness_cli.py',*args],expected)

    def scoped(self):
        return ['--state-root',self.state,'--storage-scope','personal','--project-root',self.project]

    def create(self, spec, expected=0):
        file=self.folder/(spec['name']+'-spec.json')
        file.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
        return self.cli('asset','create','--spec',file,*self.scoped(),expected=expected)

    def probe(self, name, session, read=False):
        return self.run_child([Path(__file__),'--context-probe',self.state,self.project,name,session,str(int(read))])

    def skill_spec(self):
        return {'type':'skill','name':'dots-audit-reconcile','description':'월간 수량 합계 대조를 점검합니다.',
                'instructions':'입력한 월간 수량과 합계를 대조하고 차이를 표로 설명합니다.\n',
                'references':['합계는 같은 기간과 단위끼리 비교합니다.']}

    def test_skill_create_validate_auto_candidate_explicit_read_edit_and_new_context(self):
        spec=self.skill_spec()
        created=self.create(spec)
        file=Path(created['path'])/'SKILL.md'
        self.assertTrue(self.cli('asset','validate',file.parent)['ok'])
        registry=json.loads((self.state/'assets/registry.json').read_text(encoding='utf-8'))
        self.assertEqual('active',registry['assets'][0]['status'])  # Skills have no extra activate step.
        inventory=self.cli('skill','inventory','--state-root',self.state,'--project-root',self.project,
                           '--claude-root',self.claude,'--plugin-root',PLUGIN)
        hints=task_candidates(inventory,'월간 수량 합계 대조를 점검해줘')
        self.assertIn(spec['name'],[g['name'] for g in hints['groups']])
        target=next(x for x in inventory['skills'] if x['name']==spec['name'])
        self.assertEqual('personal',target['source'])
        self.assertEqual('',target['invocation'])  # Not falsely registered as a native /command.
        first=self.probe(spec['name'],'dots-first',read=True)
        self.assertEqual('load',first['execution']['mode'])
        self.assertEqual('Read',first['execution']['load']['tool'])
        self.assertEqual(str(file),first['execution']['path'])
        self.assertEqual(1,first['bodyReads'])
        second=self.probe(spec['name'],'dots-first')
        self.assertEqual('reuse',second['execution']['mode'])
        original_hash=target['sha256']
        spec['instructions']='수정된 기준: 월간 수량과 합계를 대조하고 차이가 있는 항목만 표로 설명합니다.\n'
        self.create(spec)
        self.assertTrue(list((self.state/'assets/versions').rglob('SKILL.md')))
        self.assertNotEqual(original_hash,hashlib.sha256(file.read_bytes()).hexdigest())
        edited=self.probe(spec['name'],'dots-first')
        fresh=self.probe(spec['name'],'dots-new-session')
        self.assertEqual('load',edited['execution']['mode'])
        self.assertEqual('load',fresh['execution']['mode'])
        self.assertEqual(0,fresh['bodyReads'])
        self.events.append({'automaticCandidates':len(hints['groups']),'firstContext':first,'sameContext':second,
                            'editedContext':edited,'newContext':fresh})

    def test_same_name_external_skill_is_preserved(self):
        spec=self.skill_spec()
        existing=self.claude/'skills'/spec['name']/'SKILL.md'
        existing.parent.mkdir(parents=True)
        existing.write_text('external-owned-original',encoding='utf-8')
        result=self.create(spec,expected=1)
        self.assertFalse(result['ok'])
        self.assertEqual('external-owned-original',existing.read_text(encoding='utf-8'))
        self.assertFalse((self.state/'personal-root/.claude/skills'/spec['name']).exists())

    def mcp_spec(self, multiplier=1):
        return {'type':'mcp','format':'platform-tools-v1','name':'dots-audit-sums',
            'description':'합성 숫자 목록의 합계를 계산하는 읽기 전용 시험 도구',
            'reviewed_capabilities':['third-party-import'],
            'tools_code':('import json\nfrom mcp.server.fastmcp import FastMCP\n\n'
                'def register_tools(mcp: FastMCP) -> None:\n'
                '    @mcp.tool()\n    def sum_values(values: list[float]) -> str:\n'
                '        """Return the total of at most ten synthetic numbers without external access."""\n'
                '        if len(values) > 10:\n            raise ValueError("at most ten values")\n'
                f'        return json.dumps({{"total": sum(values) * {multiplier}}})\n'),
            'tool_tests':[{'tool':'sum_values','arguments':{'values':[1,2]},'expect':{'json':{'total':3*multiplier}}},
                          {'tool':'sum_values','arguments':{},'is_error':True}]}

    def rpc_total(self, definition, values, interrupt=False):
        started=time.perf_counter()
        child=RpcChild(definition,self.project,self.env)
        try:
            initialized=child.initialize()
            self.assertIn('serverInfo',initialized['result'])
            listed=child.call('tools/list')['result']['tools']
            self.assertEqual({'health','sum_values'},{x['name'] for x in listed})
            response=child.call('tools/call',{'name':'sum_values','arguments':{'values':values}})
            self.assertFalse(response['result'].get('isError',False))
            text=next(x['text'] for x in response['result']['content'] if x['type']=='text')
            if interrupt:
                child.child.terminate()
                child.child.wait(timeout=5)
            self.events.append({'protocol':'initialize -> tools/list -> tools/call','seconds':round(time.perf_counter()-started,4),
                                'interruptedOwnChild':interrupt,'pid':child.child.pid,'result':json.loads(text)})
            return json.loads(text)
        finally:
            child.close()

    def require_sdk(self):
        try:
            version=tuple(int(x) for x in importlib.metadata.version('mcp').split('.')[:2])
        except importlib.metadata.PackageNotFoundError:
            self.skipTest('approved MCP SDK not installed; no installation attempted')
        if version[0]!=1 or version<(1,28):
            self.skipTest('approved mcp>=1.28,<2 required; no installation attempted')

    def test_platform_mcp_real_protocol_activation_restart_edit_and_skill_binding(self):
        self.require_sdk()
        spec=self.mcp_spec()
        path=Path(self.create(spec)['path'])
        self.assertTrue(self.cli('asset','validate',path)['ok'])
        receipt=self.cli('asset','test-mcp','--name',spec['name'],'--timeout','30',*self.scoped())['receipt']
        activated=self.cli('asset','activate-mcp','--name',spec['name'],'--receipt',receipt,*self.scoped())
        if self.native:
            self.assertEqual('registered',activated['nativeRegistration']['status'])
            self.assertTrue((self.claude/'.claude.json').is_file())
        definition=json.loads((self.state/'mcp/registry.json').read_text(encoding='utf-8'))['mcpServers'][spec['name']]
        self.assertEqual({'total':7},self.rpc_total(definition,[3,4],interrupt=True))
        self.assertEqual({'total':7},self.rpc_total(definition,[3,4]))
        skill={**self.skill_spec(),'tool_dependencies':[{'server':spec['name'],'tools':['sum_values']}]}
        self.create(skill)
        checked=self.cli('asset','check-skill','--name',skill['name'],'--state-root',self.state,'--project-root',self.project)
        self.assertTrue(checked['ok'],checked)
        self.assertEqual('not-checked',checked['liveConnection'])
        self.events.append({'nativeRegistration':activated['nativeRegistration'],'dependencyCheck':checked})
        self.create(self.mcp_spec(multiplier=2))
        edited_registry=json.loads((self.state/'assets/registry.json').read_text(encoding='utf-8'))
        candidate=next(x for x in edited_registry['assets'] if x['name']==spec['name'])
        self.assertEqual('candidate',candidate['status'])
        # Native and launcher registrations must retain the previously verified
        # implementation until the new candidate is explicitly activated.
        candidate_result=self.rpc_total(definition,[3,4])
        self.assertEqual({'total':7},candidate_result)
        self.events.append({'candidateExecutionAudit':{'assetStatus':candidate['status'],
                            'resultBeforeNewValidation':candidate_result,
                            'unvalidatedSourceWasExecuted':candidate_result=={'total':14}}})
        stale=self.cli('asset','activate-mcp','--name',spec['name'],'--receipt',receipt,*self.scoped(),expected=1)
        self.assertFalse(stale['ok'])
        broken=self.cli('asset','check-skill','--name',skill['name'],'--state-root',self.state,'--project-root',self.project,expected=1)
        self.assertFalse(broken['ok'])
        newer=self.cli('asset','test-mcp','--name',spec['name'],'--timeout','30',*self.scoped())['receipt']
        self.cli('asset','activate-mcp','--name',spec['name'],'--receipt',newer,*self.scoped())
        self.create(skill)  # Explicitly bind reviewed new source, not silent reuse.
        self.assertTrue(self.cli('asset','check-skill','--name',skill['name'],'--state-root',self.state,'--project-root',self.project)['ok'])
        self.assertEqual({'total':14},self.rpc_total(definition,[3,4]))

    def test_protocol_test_checks_actual_bundle_and_rejects_source_relative_file_dependency(self):
        self.require_sdk()
        spec=self.mcp_spec()
        spec['name']='dots-source-relative'
        spec['reviewed_capabilities'].append('filesystem-read')
        spec['tools_code']=spec['tools_code'].replace('import json\n','import json\nfrom pathlib import Path\n').replace(
            '        if len(values) > 10:',
            '        if not (Path(__file__).parents[2] / "tool-tests.json").is_file():\n'
            '            raise ValueError("source-relative file unavailable")\n'
            '        if len(values) > 10:')
        path=Path(self.create(spec)['path'])
        manifest=load_json(path/'asset.json')
        self.assertEqual({'total':7},self.rpc_total({'command':manifest['command'],'args':manifest['args']},[3,4]))
        rejected=self.cli('asset','test-mcp','--name',spec['name'],'--timeout','30',*self.scoped(),expected=1)
        self.assertFalse(rejected['ok'])
        self.assertEqual('candidate',load_json(path/'asset.json')['status'])
        self.assertFalse((path/'.receipts').exists())
        self.assertNotIn(spec['name'],load_json(self.state/'mcp/registry.json',{}).get('mcpServers',{}))
        self.events.append({'sourceCallSucceeded':True,'deploymentFormatProtocolTestRejected':True,
                            'receiptIssued':False,'activated':False})

    def test_web_planner_is_optional_small_metadata_without_fake_live_success(self):
        spec={'name':'dots-web-review','purpose':'주간 교육 신청 현황을 정리',
            'site':'https://training.example.invalid/applicants','fields':['부서','신청 수'],
            'storageScope':'personal','connection':'reported_connected',
            'toolContract':{'server':'synthetic-browser','tools':[{'name':'read_table','inputSchema':{'type':'object'}}]}}
        started=time.perf_counter()
        trial=plan_web_workflow(spec)
        self.assertEqual('trial_required',trial['status'])
        spec['trial']={'status':'passed','fingerprint':trial['trialPlan']['fingerprint'],'rowCount':2,'fieldsMatch':True}
        ready=plan_web_workflow(spec)
        self.assertEqual('ready_to_save',ready['status'])
        self.assertFalse(ready['browserExecuted'])
        self.assertFalse(ready['liveConnectionVerified'])
        self.assertFalse(ready['saved'])
        planning_seconds=time.perf_counter()-started
        created=self.create(ready['assetSpec'])
        self.assertTrue(self.cli('asset','validate',created['path'])['ok'])
        changed={**spec,'fields':['부서','신청 수','상태']}
        self.assertEqual('trial_required',plan_web_workflow(changed)['status'])
        self.events.append({'plannerCallsWithoutMissingInput':2,'planningSeconds':round(planning_seconds,4),
                            'generatedSkillChars':len(ready['assetSpec']['instructions']),
                            'evidenceBasis':ready['trialEvidence'],'realBrowserTest':'not-performed'})


class DotsFrozenExecutionTests(unittest.TestCase):
    """Unit receipts isolate activation edge cases; not protocol-test evidence."""
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='dots-frozen-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.state=self.root/'state'
        self.config=self.root/'claude'
        self.env=patch.dict(os.environ,{'COMPANY_AGENT_SCOPE':'Machine','CLAUDE_CONFIG_DIR':str(self.config)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.spec={'type':'mcp','name':'frozen-example','description':'Synthetic activation unit fixture',
                   'server_code':'print("previous")'}
        self.asset=assets.create_asset(self.spec,self.state)
        self.activate_fixture()
        self.definition=load_json(self.state/'mcp/registry.json')['mcpServers'][self.spec['name']]
        self.bundle=Path(self.definition['args'][0])

    def fixture_receipt(self):
        source_hash=assets._asset_content_hash(self.asset,'asset.json')
        _, content=prepare_execution_bundle(self.state,self.asset,self.spec['name'],load_json(self.asset/'asset.json'),
                                           {'assetHash':source_hash})
        return assets._write_receipt(ensure_user_layout(self.state),self.asset,'mcp-protocol','mcp',self.spec['name'],
                                     source_hash,{'unitFixture':True,**bundle_evidence(content)})

    def activate_fixture(self):
        return assets.activate_mcp(self.state,self.spec['name'],self.fixture_receipt())

    def output(self):
        result=subprocess.run([self.definition['command'],*self.definition['args']],cwd=self.root,
                              text=True,capture_output=True,timeout=10)
        self.assertEqual(0,result.returncode,result.stderr)
        return result.stdout.strip()

    def test_candidate_and_direct_source_edits_do_not_change_legacy_active_bundle(self):
        self.assertEqual('previous',self.output())
        original=self.bundle.read_bytes()
        (self.asset/'server.py').write_text('print("direct edit")\n',encoding='utf-8')
        self.assertEqual('previous',self.output())
        assets.create_asset({**self.spec,'server_code':'print("next")'},self.state)
        self.assertEqual(original,self.bundle.read_bytes())
        self.assertEqual('previous',self.output())
        self.activate_fixture()
        self.assertEqual(self.definition,load_json(self.state/'mcp/registry.json')['mcpServers'][self.spec['name']])
        self.assertEqual('next',self.output())
        with zipfile.ZipFile(self.bundle) as archive:
            self.assertFalse(any('.receipts' in name or '__pycache__' in name for name in archive.namelist()))
            self.assertNotIn('validation-receipt.key',archive.namelist())

    def test_source_change_after_receipt_check_cannot_publish_unvalidated_bytes(self):
        original=self.bundle.read_bytes()
        receipt=self.fixture_receipt()
        verify=assets._verify_receipt
        def concurrent_edit(*args,**kwargs):
            result=verify(*args,**kwargs)
            (self.asset/'server.py').write_text('print("unverified race")\n',encoding='utf-8')
            return result
        with patch.object(assets,'_verify_receipt',side_effect=concurrent_edit), self.assertRaisesRegex(ValueError,'changed while capturing'):
            assets.activate_mcp(self.state,self.spec['name'],receipt)
        self.assertEqual(original,self.bundle.read_bytes())
        self.assertEqual('previous',self.output())

    def test_unexpected_data_or_secret_file_is_never_copied_into_execution_bundle(self):
        original=self.bundle.read_bytes()
        (self.asset/'.env').write_text('SYNTHETIC_SECRET=do-not-package',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'review runtime data separately'):
            self.activate_fixture()
        self.assertEqual(original,self.bundle.read_bytes())
        self.assertNotIn(b'do-not-package',self.bundle.read_bytes())
        self.assertEqual('previous',self.output())

    def test_activation_metadata_failure_keeps_previous_bundle_and_registries(self):
        original=self.bundle.read_bytes()
        assets.create_asset({**self.spec,'server_code':'print("next")'},self.state)
        receipt=self.fixture_receipt()
        paths=[self.state/'mcp/registry.json',self.asset/'asset.json',self.state/'assets/registry.json']
        prior={path:path.read_bytes() for path in paths}
        write=assets.atomic_write_json
        for failed in paths:
            def failing_write(path,value):
                if path==failed:
                    raise OSError('synthetic activation metadata failure')
                return write(path,value)
            with self.subTest(file=failed.name), patch.object(assets,'atomic_write_json',side_effect=failing_write), \
                    self.assertRaisesRegex(OSError,'synthetic activation'):
                assets.activate_mcp(self.state,self.spec['name'],receipt)
            self.assertEqual(original,self.bundle.read_bytes())
            self.assertEqual(prior,{path:path.read_bytes() for path in paths})
            self.assertEqual('previous',self.output())

    def test_publication_failure_restores_metadata_without_replacing_previous_bundle(self):
        original=self.bundle.read_bytes()
        assets.create_asset({**self.spec,'server_code':'print("next")'},self.state)
        receipt=self.fixture_receipt()
        paths=[self.state/'mcp/registry.json',self.asset/'asset.json',self.state/'assets/registry.json']
        prior={path:path.read_bytes() for path in paths}
        replace=os.replace
        def failed_publication(source,target):
            if Path(target)==self.bundle:
                raise OSError('synthetic publish failure')
            return replace(source,target)
        with patch('company_agent.mcp_execution.os.replace',side_effect=failed_publication), \
                self.assertRaisesRegex(OSError,'synthetic publish'):
            assets.activate_mcp(self.state,self.spec['name'],receipt)
        self.assertEqual(original,self.bundle.read_bytes())
        self.assertEqual(prior,{path:path.read_bytes() for path in paths})

    def test_source_only_receipt_cannot_activate_an_untested_execution_format(self):
        previous=self.bundle.read_bytes()
        receipt=assets._write_receipt(ensure_user_layout(self.state),self.asset,'mcp-protocol','mcp',self.spec['name'],
                                     assets._asset_content_hash(self.asset,'asset.json'),{'sourceOnly':True})
        with self.assertRaisesRegex(ValueError,'matching protocol receipt'):
            assets.activate_mcp(self.state,self.spec['name'],receipt)
        self.assertEqual(previous,self.bundle.read_bytes())

    def test_active_bundle_read_is_bounded_before_registration_validation(self):
        with patch('company_agent.mcp_execution._MAX_BUNDLE_BYTES',16), \
                self.assertRaisesRegex(ValueError,'exceeds its size limit'):
            read_execution_bundle(self.definition)

    def test_legacy_launcher_and_native_direct_registrations_refuse_edit_without_source_write(self):
        original=(self.asset/'server.py').read_bytes()
        direct={**self.definition,'args':[str(self.asset/'server.py')]}
        registry=self.state/'mcp/registry.json'
        atomic_write_json(registry,{'mcpServers':{self.spec['name']:direct}})
        with self.assertRaisesRegex(ValueError,'legacy direct-source registration'):
            assets.create_asset({**self.spec,'server_code':'print("candidate")'},self.state)
        self.assertEqual(original,(self.asset/'server.py').read_bytes())
        atomic_write_json(registry,{'mcpServers':{self.spec['name']:self.definition}})
        config={'mcpServers':{self.spec['name']:direct,'another-owned-server':{'command':'keep.exe'}}}
        atomic_write_json(self.config/'.claude.json',config)
        with patch.dict(os.environ,{'COMPANY_AGENT_SCOPE':'User','COMPANY_AGENT_PROJECT_ROOT':str(self.root)}), \
                self.assertRaisesRegex(ValueError,'legacy direct-source registration'):
            assets.create_asset({**self.spec,'server_code':'print("candidate")'},self.state)
        self.assertEqual(original,(self.asset/'server.py').read_bytes())
        self.assertEqual(config,load_json(self.config/'.claude.json'))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--context-probe':
        value=context_probe(Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4],sys.argv[5],sys.argv[6]=='1')
        print(json.dumps(value,ensure_ascii=True))
    else:
        unittest.main()
