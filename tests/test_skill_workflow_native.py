"""Actual Windows wrapper -> hooks -> scoped state, without model/Office access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_native_runtime as native
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.state import load_session


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
class SkillWorkflowNativeTests(native.NativeRuntimeTestBase):
    run_wrapper = native.NativePowerShellTests.run_wrapper

    def brief_groups(self, result):
        # Candidate details are transmitted once in the leading action brief.
        return [json.loads(line) for line in result['hookSpecificOutput']['additionalContext'].splitlines()
                if line.startswith('{"name":') and '"candidates":' in line]

    def test_attached_ppt_request_receives_index_before_file_probe(self):
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.root / 'isolated-claude')}):
            started = self.hook('SessionStart', source='startup')
            initial = json.loads(started['hookSpecificOutput']['additionalContext'])['company_agent_runtime']
            index = initial['skillIndex']
            self.assertEqual('inline', index['mode'])
            names = [row[0] for row in index['skills']]
            self.assertIn('office-reader', names)
            self.assertIn('presentation', names)
            result = self.hook('UserPromptSubmit', prompt='@테스트자료.pptx 이 자료 내용 확인해서 정리해줄 수 있을까?')
            runtime = json.loads(result['hookSpecificOutput']['additionalContext'].split('\n')[-1])['company_agent_runtime']
            self.assertEqual('reuse', runtime['skillIndex']['mode'])
            self.assertEqual('office-reader', runtime['skillExecution']['name'])
            self.assertEqual('load', runtime['skillExecution']['mode'])
            self.assertNotIn('Presentations.Open', result['hookSpecificOutput']['additionalContext'])
            self.assertIn('한국어로 선택받고', result['hookSpecificOutput']['additionalContext'])
            self.assertIn('UTF-8', runtime['instructions'])
            self.assertFalse(runtime['skillWorkflow']['indexRead'])
            self.assertTrue(runtime['skillWorkflow']['indexDelivered'])
            self.assertEqual('load-relevant-skill', runtime['skillWorkflow']['nextAction'])
            diag = load_session(self.payload['session_id'], Path(self.record['userStateRoot']))['hookDiagnostics']
            self.assertEqual(len(result['hookSpecificOutput']['additionalContext']), diag['UserPromptSubmit']['contextChars'])
            advice = self.hook('PreToolUse', tool_name='Bash', tool_input={'command':'pwd && ls -la test.pptx'})
            self.assertEqual('deny', advice['hookSpecificOutput']['permissionDecision'])
            self.assertNotIn('먼저 스킬 목록을 Read', json.dumps(advice, ensure_ascii=False))
            # A delivery is not native Read evidence or model adherence.
            # This separately simulates a genuine body Read receipt.
            self.read(self.plugin / 'skills/office-reader/SKILL.md')
            self.assertEqual({}, self.hook('Stop'))
            compacted = self.hook('SessionStart', source='compact')
            restored = json.loads(compacted['hookSpecificOutput']['additionalContext'])['company_agent_runtime']
            self.assertEqual('inline', restored['skillIndex']['mode'])
            state = load_session(self.payload['session_id'], Path(self.record['userStateRoot']))
            self.assertEqual({}, state['skillWorkflow']['readSkills'])

    def test_ppt_choice_file_and_helper_do_not_interrupt_approval_wait(self):
        self.hook('UserPromptSubmit',prompt='새 디자인으로 5장 PPT를 만들되 먼저 확인받아줘')
        root=Path(self.record['userStateRoot'])
        spec=root/'tmp/ppt-choices-native.json'
        content=json.dumps({'creationMode':'new','purpose':'월간 실적','audience':'부서장','slideCount':5})
        atomic_write_text(spec,content)
        self.hook('PostToolUse',tool_name='Write',tool_input={'file_path':str(spec),'content':content},tool_response={'success':True})
        result=self.run_wrapper(['-Mode','Cli','business','ppt-choices','--spec',str(spec),'--state-root',str(root)])
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual('design',json.loads(result.stdout)['stage'])
        self.assertEqual(0,load_session(self.payload['session_id'],root)['mutationCount'])
        self.assertEqual({},self.hook('Stop'))

    def test_background_wait_uses_native_stop_without_correction_budget(self):
        self.hook('UserPromptSubmit',prompt='HTML 보고서를 만들어줘')
        root=Path(self.record['userStateRoot'])
        self.hook('PostToolUse',tool_name='Write',tool_input={'file_path':str(self.project/'job.json')},tool_response={'success':True})
        for _ in range(3):
            self.assertEqual({},self.hook('Stop',stop_hook_active=True,
                background_tasks=[{'id':'worker-1','type':'subagent','status':'running'}]))
        state=load_session(self.payload['session_id'],root)
        self.assertEqual(0,state['stopRetryCount'])
        self.assertIsNone(state['verification'])
        # Native registry says done; an actual verification is still required.
        self.assertEqual('block',self.hook('Stop',background_tasks=[])['decision'])

    def setUp(self):
        super().setUp()
        self.plugin = self.root / "plugin copy"
        shutil.copytree(native.PLUGIN, self.plugin, ignore=shutil.ignore_patterns("__pycache__", "runtime"))
        self.record = self.register("project", "Project", self.project)
        atomic_write_json(self.plugin / "company-agent-install.json", {
            "registrationsRoot": str(self.registrations), "knowledgeBaseRoot": str(self.base)})
        self.payload = {"session_id": "native-selection", "cwd": str(self.project)}

    def hook(self, event, **values):
        result = self.run_wrapper(["-Mode", "Hook", "-Event", event], {**self.payload, **values})
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def read(self, file):
        raw = file.read_text(encoding="utf-8-sig")
        self.hook("PostToolUse", tool_name="Read", tool_input={"file_path": str(file)},
                  tool_response={"type": "text", "file": {"filePath": str(file), "content": raw,
                      "startLine": 1, "totalLines": len(raw.splitlines()), "numLines": len(raw.splitlines())}})

    def test_korean_choice_cli_preserves_state_and_does_not_require_verification(self):
        local_skill = self.project / '.claude/skills/office-reader/SKILL.md'
        atomic_write_text(local_skill, '---\nname: office-reader\ndescription: 기존 PPT 읽기\n---\n한글 — 자료 😀\n')
        result = self.hook('UserPromptSubmit', prompt='office-reader PPT 읽기')
        ctx = json.loads(result['hookSpecificOutput']['additionalContext'].split('\n')[-1])['company_agent_runtime']
        group = next(g for g in self.brief_groups(result) if g['name'] == 'office-reader')
        selected = next(c for c in group['candidates'] if c['source'] == 'project')
        reply = self.run_wrapper(['-Mode', 'Cli', 'skill', 'choose', '--session', self.payload['session_id'],
                                  '--turn', ctx['skillWorkflow']['turn'], '--candidate', selected['id']],
                                 env_overrides={'PYTHONIOENCODING': 'cp949', 'PYTHONUTF8': '0'})
        self.assertEqual(0, reply.returncode, reply.stderr)
        chosen = json.loads(reply.stdout)
        self.assertEqual(str(local_skill), chosen['readPath'])
        self.assertFalse(chosen['bodyAlreadyRead'])
        self.read(local_skill)
        root = Path(self.record['userStateRoot'])
        self.assertEqual(selected['id'], load_session(self.payload['session_id'], root)['skillWorkflow']['selected']['id'])
        self.assertEqual({}, self.hook('Stop'))

    def test_session_exports_utf8_and_cmd_uses_registration_without_state_env(self):
        import subprocess
        import sys
        env_file = self.root / 'session.env'
        started = self.run_wrapper(['-Mode', 'Hook', '-Event', 'SessionStart'],
                                   {**self.payload, 'source': 'startup'},
                                   env_overrides={'CLAUDE_ENV_FILE': str(env_file),
                                                  'PYTHONIOENCODING': 'cp949', 'PYTHONUTF8': '0'})
        self.assertEqual(0, started.returncode, started.stderr)
        self.assertIn('export PYTHONUTF8=1', env_file.read_text(encoding='utf-8'))
        self.assertIn('export PYTHONIOENCODING=utf-8', env_file.read_text(encoding='utf-8'))
        # Do not inherit state variables from a functioning hook: this is the
        # production failure path, where the bin shim was invoked directly.
        env = dict(os.environ)
        for name in list(env):
            if name.startswith('COMPANY_AGENT_'):
                env.pop(name)
        env.update(COMPANY_AGENT_PYTHON=sys.executable, PYTHONIOENCODING='cp949', PYTHONUTF8='0')
        result = subprocess.run([str(self.plugin / 'bin/company-agent.cmd'), 'state', 'check'],
                                cwd=self.project, env=env, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, repr(result.stderr))
        actual = json.loads(result.stdout)
        self.assertEqual(str(Path(self.record['userStateRoot'])), actual['stateRoot'])

    def test_native_hook_json_roundtrips_unicode_in_legacy_pipe(self):
        import subprocess
        import sys
        env = dict(os.environ, PYTHONIOENCODING='cp949', PYTHONUTF8='0',
                   CLAUDE_CONFIG_DIR=str(self.root / 'isolated-claude'))
        payload = dict(self.payload, prompt='@테스트자료.pptx — 한글 😀 내용 읽기')
        result = subprocess.run([sys.executable, '-B', str(self.plugin / 'scripts/native_entry.py'),
                                 '--event', 'UserPromptSubmit'], cwd=self.project, env=env,
                                input=json.dumps(payload, ensure_ascii=True).encode('ascii'),
                                capture_output=True, timeout=20)
        self.assertEqual(0, result.returncode, repr(result.stderr))
        self.assertEqual(b'', result.stderr)
        wire = json.loads(result.stdout.decode('ascii'))
        ctx = json.loads(wire['hookSpecificOutput']['additionalContext'].split('\n')[-1])['company_agent_runtime']
        self.assertEqual(str(self.project), ctx['project'])
        self.assertEqual('office-reader', ctx['skillExecution']['name'])
        self.assertIn('한국어', ctx['instructions'])

    def test_first_prompt_selection_execution_and_silent_list_flow(self):
        self.hook("SessionStart", source="startup")
        result = self.hook("UserPromptSubmit", prompt="기존 PPT 내용을 분석해줘")
        runtime = json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[-1])["company_agent_runtime"]
        self.assertEqual("ready", runtime["skillWorkflow"]["status"])
        self.assertFalse(runtime["skillWorkflow"]["indexRead"])
        self.assertTrue(runtime["skillWorkflow"]["turn"])
        execution = {"tool_name": "Bash", "tool_input": {"command": "python invented_reader.py"}}
        first = self.hook("PreToolUse", **execution)
        self.assertEqual('load', runtime['skillExecution']['mode'])
        self.assertEqual('deny', first['hookSpecificOutput']['permissionDecision'])
        self.assertIn('스킬 목록 확인 1회', first['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual({}, self.hook('PreToolUse', **execution))
        # Even before catalogue receipt, advisory discovery cannot bypass DB policy.
        denied = self.hook('PreToolUse', tool_name='mcp__corp-db-read__query', tool_input={'query':'DELETE FROM employees'})
        self.assertEqual('deny', denied['hookSpecificOutput']['permissionDecision'])
        self.read(Path(runtime["skillSelection"]["catalog"]["path"]))
        # A plain list lookup is already complete; Stop must not request pass/fail.
        self.assertNotIn("decision", self.hook("Stop"))
        self.read(self.plugin / "skills/office-reader/SKILL.md")
        self.assertEqual({}, self.hook("PreToolUse", **execution))
        state = load_session(self.payload["session_id"], Path(self.record["userStateRoot"]))
        self.assertEqual("office-reader", state["skillWorkflow"]["selected"]["name"])
        self.assertEqual(0, state["mutationCount"])
        # Corporate policy must still run after preparation; never emit allow.
        denied = self.hook("PreToolUse", tool_name="mcp__corp-db-read__query", tool_input={"query": "DELETE FROM employees"})
        self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])
        next_result = self.hook("UserPromptSubmit", prompt="이제 발표 자료를 만들어줘")
        next_runtime = json.loads(next_result["hookSpecificOutput"]["additionalContext"].split("\n")[-1])["company_agent_runtime"]
        self.assertTrue(next_runtime["skillWorkflow"]["indexRead"])
        self.assertIsNone(next_runtime["skillWorkflow"]["selected"])
        self.read(self.plugin / "skills/presentation/SKILL.md")
        self.assertEqual({}, self.hook("PreToolUse", **execution))

    def test_html_answer_turn_does_not_deadlock_and_choices_execute(self):
        self.hook("SessionStart", source="startup")
        result = self.hook("UserPromptSubmit", prompt="HTML 보고서를 만들어줘")
        runtime = json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[-1])["company_agent_runtime"]
        self.read(Path(runtime["skillSelection"]["catalog"]["path"]))
        self.read(self.plugin / "skills/html-report/SKILL.md")
        self.hook("UserPromptSubmit", prompt="추가 디자인 중 뉴모피즘, 상세, 스크롤로 해줘")
        root = Path(self.record["userStateRoot"])
        spec = root / "tmp/html-choices-report.json"
        content = json.dumps({"designMenu": "additional", "style": "neumorphism", "length": "detailed", "mode": "scroll"})
        inputs = {"file_path": str(spec), "content": content}
        result = self.hook("PreToolUse", tool_name="Write", tool_input=inputs)
        self.assertNotIn("permissionDecision", result.get("hookSpecificOutput", {}))
        atomic_write_text(spec, content)
        self.hook("PostToolUse", tool_name="Write", tool_input=inputs, tool_response={"success": True})
        command = (f'powershell.exe -NoLogo -NoProfile -File "{self.plugin / "scripts/Invoke-CompanyAgent.ps1"}"'
                   f' -Mode Cli business html-choices --spec "{spec}" --state-root "{root}"')
        for _ in range(3):
            self.assertEqual({}, self.hook("PreToolUse", tool_name="Bash", tool_input={"command": command}))
        completed = self.run_wrapper(["-Mode", "Cli", "business", "html-choices", "--spec", str(spec), "--state-root", str(root)])
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])
        self.hook("PostToolUse", tool_name="Bash", tool_input={"command": command}, tool_response={"stdout": completed.stdout})
        self.assertEqual(0, load_session(self.payload["session_id"], root)["mutationCount"])
        self.assertNotIn("decision", self.hook("Stop"))

    def test_malformed_advisory_receipt_does_not_block_tools_or_skip_db_policy(self):
        self.hook("UserPromptSubmit", prompt="목록을 확인해줘")
        root = Path(self.record["userStateRoot"])
        from company_agent.state import _locked_session
        with _locked_session(self.payload["session_id"], root) as (state, path):
            state["skillWorkflow"] = ["old-invalid-shape"]
            atomic_write_json(path, state)
        self.assertEqual({}, self.hook("PreToolUse", tool_name="Write", tool_input={"file_path": str(self.project / "report.html")}))
        denied = self.hook("PreToolUse", tool_name="mcp__corp-db-read__query", tool_input={"query": "DELETE FROM employees"})
        self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])
        self.hook("UserPromptSubmit", prompt="스킬 목록을 다시 확인해줘")
        route = load_session(self.payload["session_id"], root)["skillWorkflow"]
        self.assertIsInstance(route, dict)
        self.assertFalse(route["indexRead"])

    def test_real_corporate_deny_wins_over_first_list_correction(self):
        self.hook('UserPromptSubmit', prompt='PPT 읽어줘')
        result = self.hook('PreToolUse', tool_name='mcp__corp-db-read__query', tool_input={'query': 'DELETE FROM employees'})
        self.assertEqual('deny', result['hookSpecificOutput']['permissionDecision'])
        self.assertNotIn('스킬 목록 확인 1회', result['hookSpecificOutput']['permissionDecisionReason'])
        route = load_session(self.payload['session_id'], Path(self.record['userStateRoot']))['skillWorkflow']
        self.assertNotIn('reviewCheckpoint', route)

    def test_worker_dispatch_cannot_erase_list_correction(self):
        self.hook('UserPromptSubmit', prompt='PPT 읽어줘')
        result = self.hook('PreToolUse', tool_name='Agent', tool_input={
            'subagent_type': 'company-agent:medium-worker', 'prompt': 'PPT 읽어줘'})
        self.assertEqual('deny', result['hookSpecificOutput']['permissionDecision'])
        self.assertNotIn('updatedInput', result['hookSpecificOutput'])
        self.read(self.plugin / 'skills/office-reader/SKILL.md')
        result = self.hook('PreToolUse', tool_name='Agent', tool_input={
            'subagent_type': 'company-agent:medium-worker', 'prompt': 'PPT 읽어줘'})
        self.assertNotIn('permissionDecision', result['hookSpecificOutput'])
        self.assertIn('selectedSkill', result['hookSpecificOutput']['updatedInput']['prompt'])


if __name__ == "__main__":
    unittest.main()
