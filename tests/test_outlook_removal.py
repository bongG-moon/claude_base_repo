"""Removing the built-in mail skill must preserve user skills and integrations."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent.business import doctor
from company_agent.cli import build_parser
from company_agent.execution_contract import classify_command, safe_permission
from company_agent.skill_registry import inventory_skills


class OutlookRemovalTests(unittest.TestCase):
    def test_retired_commands_are_not_available_or_auto_permitted(self):
        prefix = f'"{sys.executable}" -B "{ROOT / "company-agent-plugin/scripts/harness_cli.py"}"'
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            for action in ('mail-capabilities', 'mail-search', 'mail-read', 'eml-read'):
                with self.subTest(action=action):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        build_parser().parse_args(['business', action])
                    command = f'{prefix} business {action}'
                    self.assertEqual('unknown', classify_command(command))
                    self.assertIsNone(safe_permission({'hook_event_name': 'PermissionRequest',
                        'tool_name': 'Bash', 'tool_input': {'command': command}}, state))
            self.assertNotIn('outlook', doctor())

    def test_catalog_removes_only_builtin_mail_and_preserves_personal_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            claude = base / 'claude'
            skill = claude / 'skills/outlook-assistant/SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('---\nname: outlook-assistant\ndescription: 내 메일 조회\n---\nPersonal instructions.\n', encoding='utf-8')
            settings = claude / 'settings.json'
            settings.write_text(json.dumps({'mcpServers': {'my-mail': {'command': 'personal-mail'}}}), encoding='utf-8')
            before = {p: p.read_bytes() for p in (skill, settings)}
            result = inventory_skills(base / 'state', project_root=base,
                                      plugin_root=ROOT / 'company-agent-plugin', claude_root=claude)
            self.assertTrue(result['complete'], result.get('warnings'))
            mail = [r for r in result['skills'] if r['name'] == 'outlook-assistant']
            self.assertEqual(['user'], [r['source'] for r in mail])
            self.assertTrue(any(r['name'] == 'html-report' for r in result['skills']))
            for p, content in before.items():
                self.assertEqual(content, p.read_bytes())


if __name__ == '__main__':
    unittest.main()
