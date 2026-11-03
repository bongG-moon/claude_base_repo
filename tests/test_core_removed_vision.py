"""A real core payload never dispatches images to a harness-specific model."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'scripts/harness_core/build-profile.py'

DRIVER = r'''
import io, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
event = sys.argv[2]
if event == 'profile':
    from company_agent.core_profile import is_core_install
    from company_agent.cli import build_parser
    import argparse
    parser = build_parser()
    choices = next(x.choices for x in parser._actions if isinstance(x, argparse._SubParsersAction))
    print(json.dumps({'core': is_core_install(), 'vision': 'vision' in choices,
                      'business': 'business' in choices}))
else:
    import native_entry
    native_entry.configure_runtime = lambda *args, **kwargs: True
    sys.argv = ['native_entry.py', '--event', event]
    raise SystemExit(native_entry.main())
'''


class CoreRemovedVisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='core-no-vision-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.plugin = root / 'plugin'
        spec = importlib.util.spec_from_file_location('core_profile_builder', BUILDER)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        builder.build(ROOT, ROOT / 'deploy/harness-core-manifest.json', self.plugin)
        self.marker = self.plugin / 'resources/core-install.json'
        self.project = root / 'project'
        self.project.mkdir()
        self.config = root / 'claude'
        self.config.mkdir()
        self.settings = self.config / 'settings.json'
        self.settings.write_text(json.dumps({'model': 'personal-model', 'mcpServers': {
            'personal': {'command': 'personal-tool'}}}), encoding='utf-8')
        self.initial_settings = self.settings.read_bytes()
        self.env = dict(os.environ, COMPANY_AGENT_USER_STATE=str(root / 'state'),
                        CLAUDE_CONFIG_DIR=str(self.config), COMPANY_AGENT_KNOWLEDGE_BASE='',
                        COMPANY_AGENT_SCOPE='User', COMPANY_AGENT_PYTHON=sys.executable,
                        COMPANY_AGENT_CWD=str(self.project),
                        COMPANY_AGENT_REGISTRATIONS_ROOT=str(root / 'registrations'))

    def run_event(self, event, **fields):
        payload = {'session_id': 'd3432f2e-72f4-4cff-b741-0123456789ab',
                   'cwd': str(self.project), **fields}
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', DRIVER,
                                  str(self.plugin / 'scripts'), event],
                                 input=json.dumps(payload), capture_output=True, text=True,
                                 encoding='utf-8', env=self.env, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        return json.loads(process.stdout)

    def test_profile_marker_fail_safe_and_native_read(self):
        for marker_state in ('valid', 'missing', 'corrupt'):
            with self.subTest(marker=marker_state):
                if marker_state == 'missing':
                    self.marker.unlink()
                elif marker_state == 'corrupt':
                    self.marker.write_text('{broken', encoding='utf-8')
                self.assertEqual({'core': True, 'vision': False, 'business': False},
                                 self.run_event('profile'))
                for suffix in ('.txt', '.png', '.pdf'):
                    self.assertEqual({}, self.run_event('PreToolUse', tool_name='Read',
                        tool_input={'file_path': str(self.project / ('source' + suffix))}))
                pre = self.run_event('PreToolUse', tool_name='Bash',
                                     tool_input={'command': 'echo hello'})
                self.assertNotEqual('deny', pre.get('hookSpecificOutput', {}).get('permissionDecision'))
                for event in ('PostToolUse', 'PostToolUseFailure'):
                    observed = self.run_event(event, tool_name='Read',
                        tool_input={'file_path': str(self.project / 'source.png')},
                        tool_response={'status': 'synthetic'})
                    self.assertNotIn('systemMessage', observed)
                for event in ('SessionStart', 'UserPromptSubmit'):
                    result = self.run_event(event, source='startup', prompt='안녕하세요')
                    self.assertIn('hookSpecificOutput', result)
                    self.assertNotIn('visionRouting', json.dumps(result))
                self.assertEqual(self.initial_settings, self.settings.read_bytes())

    def test_installed_payload_does_not_ship_removed_model_router(self):
        for name in ('vision_routing', 'vision_dispatch', 'vision_handoff',
                     'vision_settings', 'vision_image'):
            self.assertFalse((self.plugin / 'scripts/company_agent' / (name + '.py')).exists())
        self.assertFalse((self.plugin / 'agents/vision-worker.md').exists())
        self.assertFalse((self.plugin / 'commands/vision-model.md').exists())
        removed = re.compile(r'company-agent:vision-worker|company-vision|visionRouting|'
                             r'vision_(?:routing|dispatch|handoff|settings|image)|'
                             r'vision_configuration_command', re.I)
        for path in (self.plugin / 'scripts').rglob('*'):
            if path.is_file() and path.suffix in {'.py', '.ps1'}:
                self.assertIsNone(removed.search(path.read_text(encoding='utf-8-sig')), str(path))
        hooks = json.loads((self.plugin / 'hooks/hooks.json').read_text(encoding='utf-8'))
        self.assertTrue(all('Read' not in item.get('matcher', '') for item in hooks['hooks']['PreToolUse']))
        self.assertTrue(any('Read' in item.get('matcher', '') for item in hooks['hooks']['PostToolUse']))


if __name__ == '__main__':
    unittest.main()
