from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
sys.path.insert(0, str(ROOT))
from company_agent.harness_map import build_map
from company_agent.harness_map_html import render_map, write_map
from company_agent.resource_scope import destinations
from company_agent.skill_registry import inventory_skills
from company_agent.workspace_api import WorkspaceService
from local_app.companion import Companion


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value, encoding='utf-8')


class HarnessMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='구성 지도 ')
        self.base = Path(self.tmp.name)
        self.project, self.config, self.state, self.reg = [self.base / name for name in ('업무 폴더', '설정', '개인 자료', '설치')]
        self.project.mkdir(); self.config.mkdir()
        (self.project / '.git').mkdir()
        self.plugin = ROOT / 'company-agent-plugin'
        self.pid = 'company-agent@company-agent-local'
        self.record = {'schemaVersion': 1, 'scope': 'User', 'nativeClaudeScope': 'user',
                       'coreVersion': 'map-test', 'claudeConfigRoot': str(self.config),
                       'userStateRoot': str(self.state), 'pluginId': self.pid}
        self.native = {self.pid: [{'scope': 'user', 'installPath': str(self.plugin), 'version': 'map-test'}]}
        write(self.config / 'settings.json', {'enabledPlugins': {self.pid: True}, 'env': {'SECRET': 'never-export-config'}})
        write(self.config / 'plugins/installed_plugins.json', {'plugins': self.native})
        write(self.reg / 'user/company-agent-install.json', self.record)
        self.env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': '', 'COMPANY_AGENT_REGISTRATIONS_ROOT': str(self.reg)})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def report(self, **kwargs):
        return build_map(self.project, config=self.config, record=self.record, plugin=self.plugin, **kwargs)

    def rows(self, report, area=None, category=None):
        return [row for group in report['groups'] if area is None or group['id'] == area
                for row in group['items'] if category is None or row['category'] == category]

    def hashes(self):
        return {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.base.rglob('*') if p.is_file()}

    def test_three_areas_active_skills_readonly_no_shell_model_or_body_export(self):
        write(self.project / 'CLAUDE.md', '# NEVER_EXPORT_INSTRUCTION_BODY')
        before = self.hashes()
        with patch('subprocess.run', side_effect=AssertionError('no shell')), patch('socket.socket', side_effect=AssertionError('no network')):
            report = self.report()
        self.assertEqual(before, self.hashes())
        self.assertFalse(self.state.exists())
        self.assertEqual(['company', 'personal', 'project'], [g['id'] for g in report['groups']])
        self.assertEqual('enabled', self.rows(report, 'company', '설치')[0]['status'])
        self.assertIn('company-agent:html-report', [r['name'] for r in self.rows(report, 'company', '스킬')])
        self.assertEqual(0, report['modelCalls'])
        content = json.dumps(report) + render_map(report)
        self.assertNotIn('NEVER_EXPORT_INSTRUCTION_BODY', content)
        self.assertNotIn('never-export-config', content)
        self.assertNotIn('<script', render_map(report))

    def test_scoped_memory_status_and_no_other_project(self):
        target = destinations(self.state, self.project, self.record)['project']['stateRoot']
        other = self.base / 'other'; other.mkdir()
        wrong = destinations(self.state, other, self.record)['project']['stateRoot']
        for folder, name, status in [(self.state, '개인 선호', 'active'), (Path(target), '현재 프로젝트', 'draft'), (Path(wrong), 'DO_NOT_SCAN_OTHER_PROJECT', 'active')]:
            write(folder / 'memory/items/a.md', f'---\nid: a\ntitle: {name}\nstatus: {status}\n---\nNEVER_EXPORT_MEMORY_BODY')
        report = self.report()
        self.assertIn('개인 선호', [r['name'] for r in self.rows(report, 'personal')])
        self.assertIn('현재 프로젝트', [r['name'] for r in self.rows(report, 'project')])
        self.assertEqual('draft', next(r['status'] for r in self.rows(report) if r['name'] == '현재 프로젝트'))
        self.assertNotIn('DO_NOT_SCAN_OTHER_PROJECT', json.dumps(report))
        self.assertNotIn('NEVER_EXPORT_MEMORY_BODY', json.dumps(report))

    def test_disabled_and_unset_plugins_do_not_appear_enabled(self):
        write(self.config / 'settings.json', {'enabledPlugins': {self.pid: False, 'off@test': False}})
        write(self.config / 'plugins/installed_plugins.json', {'plugins': {**self.native,
              'unset@test': [{'scope': 'user', 'installPath': str(self.plugin)}]}})
        report = self.report()
        self.assertFalse(any(r['status'] == 'enabled' for r in self.rows(report, 'company')))
        self.assertFalse(self.rows(report, 'company', '스킬'))
        self.assertEqual('disabled', next(r['status'] for r in self.rows(report) if r['name'] == 'off@test'))
        self.assertEqual('unknown', next(r['status'] for r in self.rows(report) if r['name'] == 'unset@test'))

    def test_mcp_names_only_and_project_disabled_choice(self):
        write(self.config.parent / '.claude.json', {'oauthAccount': 'SECRET_ACCOUNT',
              'mcpServers': {'my-tool': {'command': 'SECRET_COMMAND', 'env': {'TOKEN':'SECRET_TOKEN'}}},
              'projects': {str(self.project): {'disabledMcpServers': ['my-tool'], 'disabledMcpjsonServers':['shared-tool'],
                                              'mcpServers': {'local-tool': {'url': 'SECRET_URL'}}},
                           str(self.base/'other'): {'mcpServers': {'OTHER_PROJECT_TOOL': {}}}}})
        write(self.project / '.mcp.json', {'mcpServers': {'shared-tool': {'command': 'SECRET_CMD'}}})
        report = self.report()
        content = json.dumps(report) + render_map(report)
        for name in ('SECRET_ACCOUNT', 'SECRET_COMMAND', 'SECRET_TOKEN', 'SECRET_URL', 'OTHER_PROJECT_TOOL'):
            self.assertNotIn(name, content)
        for name in ('my-tool', 'shared-tool'):
            self.assertEqual('disabled', next(r['status'] for r in self.rows(report) if r['name'] == name))
        self.assertEqual('defined', next(r['status'] for r in self.rows(report) if r['name'] == 'local-tool'))

    def test_malformed_settings_and_learning_are_not_claimed_enabled(self):
        write(self.config / 'settings.json', '{ broken')
        write(self.state / 'config/learning.json', {})
        report = self.report()
        self.assertTrue(report['warnings'])
        self.assertEqual('unknown', self.rows(report, 'company', '설치')[0]['status'])
        self.assertEqual('unknown', self.rows(report, 'personal', '자동 학습')[0]['status'])

    def test_explicit_only_and_name_overlap(self):
        for folder in (self.config, self.project/'.claude'):
            write(folder/'skills/shared/SKILL.md', '---\nname: shared\ndisable-model-invocation: true\n---\nbody')
        write(self.config/'skills/manual/SKILL.md', '---\nname: manual\ndisable-model-invocation: true\n---\nbody')
        report = self.report()
        self.assertEqual(2, sum(r['status'] == 'choice' for r in self.rows(report, category='스킬')))
        self.assertEqual('manual', next(r['status'] for r in self.rows(report) if r['name'] == 'manual'))

    def test_saved_choice_and_stale_choice_are_not_silent_auto_selection(self):
        write(self.config/'skills/html-report/SKILL.md', '---\nname: html-report\n---\nbody')
        inv = inventory_skills(self.state, project_root=self.project, claude_root=self.config,
                               plugin_root=self.plugin, resource_record=self.record)
        chosen = next(s for s in inv['skills'] if s['name']=='html-report' and s['source']=='user')
        pref = {'schemaVersion':1, 'defaults':{'sourceOrder':[], 'skills':{'html-report':chosen['id']}}, 'projects':{}}
        write(self.state/'config/skill-preferences.json', pref)
        self.assertEqual(['html-report'], [r['name'] for r in self.rows(self.report()) if r.get('preferred')])
        pref['defaults']['skills']['html-report'] = 'user:' + '0'*24
        write(self.state/'config/skill-preferences.json', pref)
        report = self.report()
        self.assertEqual(2, sum(r['status']=='choice' for r in self.rows(report, category='스킬')))
        self.assertFalse(any(r.get('preferred') for r in self.rows(report)))

    def test_load_evidence_requires_exact_session_project_id_and_hash(self):
        inv = inventory_skills(self.state, project_root=self.project, claude_root=self.config,
                               plugin_root=self.plugin, resource_record=self.record)
        skill = next(s for s in inv['skills'] if s['name'] == 'html-report')
        route = {'project': os.path.normcase(str(self.project)), 'readSkills': {skill['id']: skill['sha256']}}
        write(self.state/'sessions/session-a.json', {'skillWorkflow': route})
        write(self.state/'sessions/unrelated.json', {'skillWorkflow': route})
        self.assertFalse(any(r.get('observed') for r in self.rows(self.report())))
        self.assertEqual(1, sum(bool(r.get('observed')) for r in self.rows(self.report(session_id='session-a'))))
        route['readSkills'][skill['id']] = '0'*64
        write(self.state/'sessions/session-a.json', {'skillWorkflow': route})
        self.assertFalse(any(r.get('observed') for r in self.rows(self.report(session_id='session-a'))))
        route['readSkills'][skill['id']] = skill['sha256']; route['project'] = str(self.base/'other')
        write(self.state/'sessions/session-a.json', {'skillWorkflow': route})
        self.assertFalse(any(r.get('observed') for r in self.rows(self.report(session_id='session-a'))))
        with self.assertRaises(ValueError):
            self.report(session_id='../outside')

    def test_native_only_no_registration_does_not_invent_installation(self):
        report = build_map(self.project, config=self.config, registrations=self.base/'not-registered')
        self.assertEqual('unknown', self.rows(report, 'company', '설치')[0]['status'])
        self.assertIn('company-agent:html-report', [r['name'] for r in self.rows(report, 'company', '스킬')])
        self.assertFalse(self.rows(report, category='자동 학습'))
        self.assertFalse((self.base/'not-registered').exists())
        self.assertFalse(self.state.exists())

    def test_registration_profile_version_and_most_specific_project(self):
        report = build_map(self.project, config=self.config, registrations=self.reg)
        self.assertEqual('enabled', self.rows(report, 'company', '설치')[0]['status'])
        write(self.reg / 'user/company-agent-install.json', {**self.record, 'coreVersion': 'old'})
        report = build_map(self.project, config=self.config, registrations=self.reg)
        self.assertEqual('unknown', self.rows(report, 'company', '설치')[0]['status'])
        self.assertTrue(report['warnings'])

    def test_project_install_learning_is_project_not_personal(self):
        record = {**self.record, 'scope': 'Project', 'nativeClaudeScope': 'local', 'projectRoot':str(self.project)}
        write(self.config/'plugins/installed_plugins.json', {'plugins': {self.pid: [{
            'scope':'local','projectPath':str(self.project),'installPath':str(self.plugin),'version':'map-test'}]}})
        report = build_map(self.project, config=self.config, record=record, plugin=self.plugin)
        self.assertEqual(1, len(self.rows(report, 'project', '자동 학습')))
        self.assertFalse(self.rows(report, 'personal', '자동 학습'))

    def test_html_escape_csp_and_exclusive_write(self):
        write(self.project/'.mcp.json', {'mcpServers': {'<img src=x onerror=alert(1)>': {}}})
        report = self.report()
        html = render_map(report)
        self.assertIn('&lt;img', html)
        self.assertNotIn('<img', html)
        self.assertIn("default-src 'none'", html)
        out = self.base/'지도.html'
        write_map(out, report)
        with self.assertRaises(FileExistsError):
            write_map(out, report)
        with self.assertRaises(ValueError):
            write_map(self.base/'map.txt', report)
        self.assertEqual(html, out.read_text(encoding='utf-8'))

    def test_limits_visible_and_junction_not_followed(self):
        for i in range(105):
            write(self.config/f'rules/{i}.md', '# rule')
        report = self.report()
        self.assertEqual(100, len(self.rows(report,'personal','지침')))
        self.assertTrue(any('상한' in w for w in report['warnings']))

    def test_symlinked_rule_is_not_followed(self):
        outside = self.base / 'outside.md'; write(outside, '# Outside')
        link = self.project / '.claude/rules/linked.md'; link.parent.mkdir(parents=True)
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest('OS does not permit test symlinks')
        report = self.report()
        self.assertFalse(any(r.get('path') == str(link) for r in self.rows(report)))
        self.assertTrue(report['warnings'])

    def test_wrong_project_registration_is_rejected(self):
        with self.assertRaises(ValueError):
            build_map(self.project, config=self.config, plugin=self.plugin, record={
                **self.record, 'scope':'Project', 'projectRoot':str(self.base/'other')})

    def test_custom_config_mcp_and_global_hook_disable(self):
        record = {**self.record, 'claudeConfigDirOverride':True}
        write(self.config/'.claude.json', {'mcpServers':{'only-custom-profile':{'command':'SECRET'}}})
        write(self.config.parent/'.claude.json', {'mcpServers':{'DO_NOT_USE_OTHER_PROFILE':{}}})
        write(self.config/'settings.json', {'enabledPlugins':{self.pid:True}, 'disableAllHooks':True})
        report = build_map(self.project, config=self.config, record=record, plugin=self.plugin)
        self.assertIn('only-custom-profile', [r['name'] for r in self.rows(report)])
        self.assertNotIn('DO_NOT_USE_OTHER_PROFILE', json.dumps(report))
        self.assertTrue(all(r['status']=='disabled' for r in self.rows(report, category='후크')))

    def test_encoded_response_bound_is_disclosed(self):
        with patch('company_agent.harness_map.MAX_ENCODED_ITEMS', 4000):
            report = self.report()
        self.assertTrue(any('응답 크기 상한' in w for w in report['warnings']))
        self.assertLess(len(json.dumps({'map':report,'html':render_map(report)})), 30000)

    def test_companion_forwards_only_current_session_and_demo_does_not_scan(self):
        companion = Companion(self.base/'ui')
        item = {'id':'app-id','workspace':str(self.project),'sessionId':'native-session','state':'idle'}
        with patch.object(companion.client, 'call', return_value={'scope':{'id':'test','kind':'User'}}) as call:
            companion.snapshot(item, 'map')
            call.assert_called_once_with(str(self.project), {'operation':'snapshot','view':'map','sessionId':'native-session'})
        companion.demo=True
        with patch.object(companion.client, 'call', side_effect=AssertionError('demo must not scan')):
            self.assertIn('unavailable', companion.snapshot(item,'map'))

    def test_workspace_snapshot_passes_session_and_never_creates_state(self):
        service = WorkspaceService(self.record, self.project, self.plugin)
        response = service.dispatch({'operation':'snapshot','view':'map','sessionId':'session-a'})
        self.assertTrue(response['map']['readOnly'])
        self.assertIn('<html lang="ko">', response['html'])
        self.assertFalse(self.state.exists())

    def test_cli_outputs_utf8_standalone_and_does_not_overwrite(self):
        out = self.base/'현재 지도.html'
        env = {**os.environ, 'CLAUDE_CONFIG_DIR':str(self.config)}
        command = [sys.executable, '-X','utf8','-B',str(self.plugin/'scripts/harness_cli.py'),
                   'context','map','--project',str(self.project),'--output',str(out)]
        first = subprocess.run(command, env=env, capture_output=True)
        self.assertEqual(0, first.returncode, first.stderr.decode('utf-8'))
        self.assertEqual(str(out), json.loads(first.stdout)['path'])
        before = out.read_bytes()
        second = subprocess.run(command, env=env, capture_output=True)
        self.assertNotEqual(0, second.returncode)
        self.assertEqual(before, out.read_bytes())


if __name__ == '__main__':
    unittest.main()
