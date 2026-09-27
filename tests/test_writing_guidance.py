"""Writing defaults travel with existing context, never become an output filter."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'company-agent-plugin'
sys.path.insert(0, str(PLUGIN / 'scripts'))
from company_agent import native_runtime, user_language


class WritingGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'
        self.project = Path(self.temp.name) / 'project'
        self.policy = {'status': 'available', 'path': 'C:/company/policy.json',
                       'rules': [{'id': 'keep-source', 'level': 'required',
                                  'text': '원문과 실제 권한을 보존합니다.'}]}
        self.environment = patch.dict(os.environ, {
            'COMPANY_AGENT_USER_STATE': str(self.state),
            'COMPANY_AGENT_KNOWLEDGE_BASE': '', 'COMPANY_AGENT_SCOPE': 'User',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_shared_default_is_bounded_and_not_duplicated(self):
        rule = user_language.KOREAN_WRITING_RULE
        self.assertLessEqual(len(rule), 400)
        self.assertEqual(1, user_language.KOREAN_DEFAULT_RULE.count(rule))

    def test_normal_and_condensed_runtime_keep_shared_rule_and_policy(self):
        captured = []
        encode = native_runtime._encode_runtime

        def observe(runtime):
            captured.append(copy.deepcopy(runtime))
            return encode(runtime)

        with patch.object(native_runtime, '_skill_routing', return_value=([], {'status': 'ready'})), \
                patch.object(native_runtime, '_knowledge_matches', return_value=[]), \
                patch.object(native_runtime, 'policy_context', return_value=self.policy), \
                patch.object(native_runtime, '_encode_runtime', side_effect=observe):
            encoded = native_runtime.runtime_context(PLUGIN, self.project, source='startup')
        initial = captured[0]
        self.assertNotIn('guidanceCondensed', initial)
        self.assertEqual(1, initial['instructions'].count(user_language.KOREAN_WRITING_RULE))
        runtime = json.loads(encoded)['company_agent_runtime']
        self.assertTrue(runtime['guidanceCondensed'])
        self.assertNotIn('guidanceMinimal', runtime)
        self.assertEqual(1, runtime['instructions'].count(user_language.KOREAN_WRITING_RULE))
        self.assertEqual(self.policy, runtime['companyPolicy'])
        self.assertEqual(initial['cliCommand'], runtime['cliCommand'])
        self.assertLessEqual(len(encoded), native_runtime.MAX_RUNTIME_BASE_CHARS)
        self.assertFalse(self.state.exists())

    def test_minimal_runtime_retains_writing_rule_without_losing_runtime_identity(self):
        # Long cached-installation paths require the existing second reduction.
        core = {key: 'C:/' + ('한글 path/' * 50) + key for key in (
            'project', 'stateRoot', 'knowledgeBase', 'cliCommand', 'completionGuide', 'metadataCommand')}
        core.update(scope='User', company_agent_session_id='writing-test')
        runtime = {**core, 'instructions': 'optional guidance ' * 600,
                   'companyPolicy': copy.deepcopy(self.policy),
                   'personalSkills': [], 'knowledgeMatches': []}
        encoded = native_runtime._encode_runtime(runtime)
        result = json.loads(encoded)['company_agent_runtime']
        self.assertTrue(result['guidanceMinimal'])
        self.assertNotIn('contextStatus', result)
        self.assertEqual(1, result['instructions'].count(user_language.KOREAN_WRITING_RULE))
        self.assertEqual(core, {key: result[key] for key in core})
        self.assertEqual(self.policy, result['companyPolicy'])
        self.assertIn('SELECT', result['instructions'])
        self.assertLessEqual(len(encoded), native_runtime.MAX_RUNTIME_BASE_CHARS)

    def test_owned_workers_receive_style_context_without_mutating_request_or_model(self):
        prompt = ('영어 메일 본문만 작성. 회사 격식과 개인 선호: 짧은 존댓말. '
                  '인용 "승인되지 않으면 발송할 수 없다"와 {{fact:rate}}, 12.50%, API_KEY를 보존.')
        for tier in ('small', 'medium', 'large'):
            inputs = {'subagent_type': f'company-agent:{tier}-worker', 'model': 'existing-model',
                      'description': 'requested work', 'prompt': prompt}
            original = copy.deepcopy(inputs)
            with self.subTest(tier=tier), \
                    patch.object(native_runtime, '_skill_routing', return_value=([], {'status': 'ready'})), \
                    patch.object(native_runtime, 'policy_context', return_value=self.policy):
                result = native_runtime.worker_runtime_input(PLUGIN, self.project, {
                    'session_id': 'writing-test', 'tool_input': inputs})['hookSpecificOutput']
            self.assertNotIn('permissionDecision', result)
            updated = result['updatedInput']
            self.assertEqual({k: v for k, v in inputs.items() if k != 'prompt'},
                             {k: v for k, v in updated.items() if k != 'prompt'})
            self.assertIn('[원래 업무 요청]\n' + prompt, updated['prompt'])
            self.assertEqual(1, updated['prompt'].count(user_language.KOREAN_WRITING_RULE))
            self.assertIn('keep-source', updated['prompt'])
            self.assertEqual(original, inputs)
        self.assertFalse(self.state.exists())

    def test_third_party_worker_is_not_changed(self):
        payload = {'session_id': 'writing-test', 'tool_input': {
            'subagent_type': 'personal:writer', 'prompt': 'Use my style.', 'model': 'existing'}}
        original = copy.deepcopy(payload)
        self.assertEqual({}, native_runtime.worker_runtime_input(PLUGIN, self.project, payload))
        self.assertEqual(original, payload)
        self.assertFalse(self.state.exists())

    def test_prose_defaults_do_not_rewrite_artifact_inputs_or_add_a_gate(self):
        content = ('<h1>반드시 승인 전에는 발송하지 말 것</h1>\n'
                   '{"API_KEY":"original", "rate":12.50, "label":"{{fact:rate}}"}\n'
                   '인용: "이 조건이면 가능할 수 있다."\n1. 검토\n2. 승인\n')
        for tool in ('Write', 'Edit', 'Bash', 'mcp__corp_outlook__send'):
            payload = {'session_id': 'writing-test', 'tool_name': tool,
                       'tool_input': {'content': content, 'body': content}}
            original = copy.deepcopy(payload)
            with self.subTest(tool=tool):
                self.assertEqual({}, user_language.question_preflight(self.state, payload))
                self.assertEqual(original, payload)
        self.assertFalse(self.state.exists())


if __name__ == '__main__':
    unittest.main()
