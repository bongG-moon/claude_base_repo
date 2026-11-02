"""Exercise the installed file boundary, including isolated runtime imports."""
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
spec = importlib.util.spec_from_file_location('harness_core_builder', ROOT / 'scripts/harness_core/build-profile.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ProfileBuilderTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = ROOT / '.smoke/harness-core'
        temporary_parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'company-agent-plugin/skills/example/SKILL.md'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'original\r\n')
        self.manifest = self.root / 'manifest.json'
        self.destination = self.root / 'payload'

    def write_manifest(self, entries):
        self.manifest.write_text(json.dumps({'schemaVersion': 1, 'profile': builder.PROFILE,
                                             'files': entries}), encoding='utf-8')

    def test_explicit_files_and_overrides_preserve_bytes_without_new_files(self):
        overlay = self.root / 'harness-core/example.md'
        overlay.parent.mkdir()
        overlay.write_bytes(b'personal context only\r\n')
        (self.source.parent / 'new-functional-engine.py').write_text('raise RuntimeError()', encoding='utf-8')
        self.write_manifest([{'path': 'skills/example/SKILL.md', 'source': 'harness-core/example.md'}])
        builder.build(self.root, self.manifest, self.destination)
        self.assertEqual((self.destination / 'skills/example/SKILL.md').read_bytes(), overlay.read_bytes())
        self.assertFalse((self.destination / 'skills/example/new-functional-engine.py').exists())
        self.assertEqual(self.source.read_bytes(), b'original\r\n')
        self.assertTrue(builder.build(self.root, self.manifest, self.destination, check=True)['checked'])

    def test_missing_source_fails_before_creating_payload(self):
        self.write_manifest(['skills/example/SKILL.md', 'missing.py'])
        with self.assertRaisesRegex(ValueError, 'missing'):
            builder.build(self.root, self.manifest, self.destination)
        self.assertFalse(self.destination.exists())

    def test_paths_directories_duplicates_and_marker_are_rejected(self):
        for entries in (['../escape'], ['skills/example'], ['skills/example/SKILL.md', 'SKILLS/example/SKILL.md'],
                        [builder.MARKER], [{'path': 'fine.md', 'source': '../private.md'}]):
            with self.subTest(entries=entries):
                self.write_manifest(entries)
                with self.assertRaises(ValueError):
                    builder.build(self.root, self.manifest, self.destination)
        self.assertFalse(self.destination.exists())

    def test_existing_destination_and_unlisted_payload_cannot_be_overwritten(self):
        self.write_manifest(['skills/example/SKILL.md'])
        builder.build(self.root, self.manifest, self.destination)
        sentinel = self.destination / 'personal.md'
        sentinel.write_text('preserve', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'new or empty'):
            builder.build(self.root, self.manifest, self.destination)
        with self.assertRaisesRegex(ValueError, 'file set'):
            builder.build(self.root, self.manifest, self.destination, check=True)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'preserve')

    def test_python_validation_compiles_only_selected_files_without_bytecode(self):
        selected = self.source.parent / 'core.py'
        selected.write_text('value = 1\n', encoding='utf-8')
        (self.source.parent / 'unlisted.py').write_text('invalid syntax :', encoding='utf-8')
        self.write_manifest(['skills/example/core.py'])
        result = builder.build(self.root, self.manifest, self.destination, validate_python=True)
        self.assertTrue(result['pythonSyntaxValidated'])
        self.assertFalse(list(self.destination.rglob('*.pyc')))
        selected.write_text('invalid syntax :', encoding='utf-8')
        target = self.destination / 'skills/example/core.py'
        target.write_bytes(selected.read_bytes())
        with self.assertRaises(SyntaxError):
            builder.build(self.root, self.manifest, self.destination, check=True, validate_python=True)


class InstalledPersonalHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary_parent = ROOT / '.smoke/harness-core'
        temporary_parent.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=temporary_parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.payload = cls.root / 'plugin'
        cls.manifest = ROOT / 'deploy/harness-core-manifest.json'
        builder.build(ROOT, cls.manifest, cls.payload)

    def run_isolated(self, code, *args, stdin=None):
        env = dict(os.environ)
        for key in tuple(env):
            if key.startswith('COMPANY_AGENT_') or key in {'PYTHONPATH', 'CLAUDE_PLUGIN_ROOT'}:
                env.pop(key)
        env['CLAUDE_CONFIG_DIR'] = str(self.root / 'empty-claude')
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', code,
                                 str(self.payload / 'scripts'), *map(str, args)],
                                input=stdin, text=True, capture_output=True, cwd=self.root,
                                env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_file_set_is_exact_and_functional_payload_is_absent(self):
        builder.build(ROOT, self.manifest, self.payload, check=True)
        self.assertEqual({p.name for p in (self.payload / 'skills').iterdir()},
                         {'company-agent', 'personal-memory', 'personal-knowledge', 'self-learning', 'asset-factory'})
        self.assertEqual({p.name for p in (self.payload / 'commands').iterdir()},
                         {'skills.md', 'learning.md', 'usability-report.md'})
        forbidden = {'business.py', 'business_files.py', 'business_artifacts.py', 'excel_pipeline_command.py',
                     'artifact_delivery.py', 'browser_workflow.py', 'content_layout.py', 'html_reference.py'}
        for path in self.payload.rglob('*'):
            if path.is_file():
                self.assertNotIn(path.name, forbidden)
                self.assertFalse(path.name.startswith(('ppt_', 'report_', 'presentation_', 'explanation_', 'vision_')))
                self.assertNotIn(path.suffix.lower(), {'.woff', '.woff2', '.ttf', '.otf'})
        self.assertFalse((self.payload / 'templates').exists())
        self.assertFalse((self.payload / 'agents/vision-worker.md').exists())

    def test_every_packaged_runtime_module_imports_without_repository(self):
        self.run_isolated("import importlib,pathlib,sys; sys.path.insert(0,sys.argv[1]); "
                          "[importlib.import_module('company_agent.'+p.stem) for p in "
                          "pathlib.Path(sys.argv[1],'company_agent').glob('*.py')]")

    def test_cli_help_and_state_check_work_without_functional_engines(self):
        code = "import sys; sys.path.insert(0,sys.argv.pop(1)); from company_agent.cli import main; raise SystemExit(main())"
        result = self.run_isolated(code, '--help')
        self.assertIn('memory', result.stdout)
        self.assertIn('learning', result.stdout)
        self.assertNotIn('business,', result.stdout)
        result = self.run_isolated(code, 'state', 'check', '--state-root', self.root / 'personal')
        self.assertTrue(json.loads(result.stdout)['ok'])

    def test_authoring_json_examples_are_valid_personal_skill_specs(self):
        guide = (self.payload / 'skills/asset-factory/references/authoring.md').read_text(encoding='utf-8')
        examples = re.findall(r'^```json\s*\n(.*?)^```\s*$', guide, flags=re.MULTILINE | re.DOTALL)
        self.assertTrue(examples, 'The delivered authoring guide must include a usable JSON example.')
        for source in examples:
            with self.subTest(example=source[:80]):
                value = json.loads(source)
                self.assertEqual('skill', value.get('type'))
                self.assertTrue(all(isinstance(value.get(key), str) and value[key].strip()
                                    for key in ('name', 'description', 'instructions')))
                self.assertIn('\n', value['instructions'])
                self.assertNotIn('\\n', value['instructions'])

    def test_unregistered_native_hook_does_not_import_removed_engines(self):
        code = "import runpy,sys; scripts=sys.argv.pop(1); sys.path.insert(0,scripts); " \
               "sys.argv=[scripts+'/native_entry.py','--event',sys.argv[1]]; runpy.run_path(sys.argv[0],run_name='__main__')"
        for event in ('SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop'):
            with self.subTest(event=event):
                result = self.run_isolated(code, event, stdin=json.dumps({'cwd': str(self.root), 'session_id': 'isolated'}))
                self.assertEqual(json.loads(result.stdout), {})


if __name__ == '__main__':
    unittest.main()
