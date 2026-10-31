"""Maintainer export regressions; never uses real profiles, sessions or servers."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('skill_export', ROOT / 'scripts/build-skill-packages.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class PackageUnitTests(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / '.smoke/platform-skills'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def metadata(self, slug='demo'):
        return {slug: {'sourceDir': 'company-agent-plugin/skills/' + slug, 'runtimeRequired': False, 'distribution': 'portable'}}

    def files(self, slug='demo'):
        return {'company-agent-plugin/skills/' + slug + '/SKILL.md': b'---\nname: demo\n---\n'}

    def artifacts(self, raw=b'zip'):
        return {'company-demo.zip': raw, 'catalog.json': export.encoded({
            'generator': 'company-platform-skills-v1', 'managedFiles': {'company-demo.zip': export.digest(raw)}})}

    def test_discovery_includes_new_skill_when_metadata_added(self):
        found = export.discover({**self.files(), **self.files('new')}, {**self.metadata(), **self.metadata('new')})
        self.assertEqual(set(found), {'demo', 'new'})

    def test_new_skill_not_silently_omitted(self):
        with self.assertRaisesRegex(ValueError, '새 스킬'):
            export.discover({**self.files(), **self.files('new')}, self.metadata())

    def test_removed_skill_excluded(self):
        self.assertEqual(set(export.discover(self.files(), {**self.metadata(), **self.metadata('old')})), {'demo'})

    def test_missing_canonical_source_not_replaced_by_plugin_wrapper(self):
        meta = self.metadata()
        meta['demo']['sourceDir'] = 'standalone-skills/demo'
        with self.assertRaisesRegex(ValueError, '정본'):
            export.discover(self.files(), meta)

    def test_harness_only_requires_reason_and_is_visible_as_exclusion(self):
        meta = {**self.metadata(), **self.metadata('core')}
        meta['core'].update(distribution='harness-only')
        with self.assertRaisesRegex(ValueError, '제외 이유'):
            export.discover({**self.files(), **self.files('core')}, meta)
        meta['core']['distributionReason'] = 'session hooks required'
        self.assertEqual(set(export.discover({**self.files(), **self.files('core')}, meta)), {'demo'})

    def test_portable_cannot_require_harness(self):
        meta = self.metadata(); meta['demo']['runtimeRequired'] = True
        with self.assertRaisesRegex(ValueError, '하네스를 요구'):
            export.discover(self.files(), meta)

    def test_new_package_must_choose_portable_or_harness_only(self):
        meta = self.metadata(); del meta['demo']['distribution']
        with self.assertRaisesRegex(ValueError, '배포 구분'):
            export.discover(self.files(), meta)

    def test_changed_plugin_requires_portable_instruction_review(self):
        tree = self.files(); meta = self.metadata()
        meta['demo']['packaging'] = {'reviewedPluginDigest': export.plugin_digest(tree, 'demo')}
        export.discover(tree, meta)
        tree['company-agent-plugin/skills/demo/references/new.md'] = b'changed behavior'
        with self.assertRaisesRegex(ValueError, '독립판'):
            export.discover(tree, meta)

    def test_portable_replaces_whole_source_and_does_not_leak_old_references(self):
        tree = self.files()
        tree['company-agent-plugin/skills/demo/references/runtime.md'] = b'old runtime instructions'
        tree['standalone-skills/demo/SKILL.md'] = b'---\nname: demo\n---\nportable'
        tree['company-agent-plugin/THIRD_PARTY_NOTICES.md'] = b'notice'
        tree['company-agent-plugin/licenses/license.txt'] = b'license'
        info = {'sourceDir':'standalone-skills/demo', 'runtimeRequired':False}
        selected, _ = export.source_files('demo', info, tree)
        self.assertNotIn('skills/demo/references/runtime.md', selected)
        self.assertEqual(selected['skills/demo/SKILL.md'][1], tree['standalone-skills/demo/SKILL.md'])

    def test_portable_modules_are_exact_source_and_paths_are_validated(self):
        tree = self.files()
        tree['company-agent-plugin/THIRD_PARTY_NOTICES.md'] = b'notice'
        tree['company-agent-plugin/licenses/license.txt'] = b'license'
        tree['company-agent-plugin/scripts/company_agent/render.py'] = b'# exact engine bytes\r\n'
        info = self.metadata()['demo']; info['packaging'] = {'runtimeModules':['render.py']}
        selected, _ = export.source_files('demo', info, tree)
        self.assertEqual(selected['skills/demo/scripts/visual_engine/render.py'][1], b'# exact engine bytes\r\n')
        for name in ('../state.py', 'C:/secrets.py', 'render/more.py'):
            info['packaging']['runtimeModules'] = [name]
            with self.assertRaises(ValueError):
                export.source_files('demo', info, tree)

    def test_missing_portable_reference_fails_before_release(self):
        tree = self.files()
        tree['standalone-skills/demo/SKILL.md'] = b'---\nname: demo\n---\n[guide](references/missing.md)'
        tree['company-agent-plugin/THIRD_PARTY_NOTICES.md'] = b'notice'
        tree['company-agent-plugin/licenses/license.txt'] = b'license'
        with self.assertRaisesRegex(ValueError, 'Missing portable reference'):
            export.source_files('demo', {'sourceDir':'standalone-skills/demo'}, tree)

    def test_unsafe_source_and_dependency_paths_rejected(self):
        for source in ('../private', 'C:/private', 'standalone-skills/other'):
            meta = self.metadata(); meta['demo']['sourceDir'] = source
            with self.assertRaises(ValueError):
                export.discover(self.files(), meta)
        meta = self.metadata(); meta['demo']['packaging'] = {'includeAdditionalPaths': ['skills/../../private']}
        with self.assertRaises(ValueError):
            export.discover(self.files(), meta)

    def test_multiline_invocation_controls_and_support_role_preserved(self):
        original = '---\nname: original\ndescription: >\n  old description\ncompany-agent-role: support\ndisable-model-invocation: true\nallowed-tools:\n  - Read\n  - Grep\n---\n'
        result = export.wrapper('demo', {'desc': '새 설명', 'displayName': '이름', 'runtimeRequired': True}, original).decode()
        self.assertIn('company-agent-role: support', result)
        self.assertIn('disable-model-invocation: true', result)
        self.assertIn('allowed-tools:\n  - Read\n  - Grep', result)
        self.assertNotIn('old description', result)

    def test_relative_reference_closure_preserves_original_bytes(self):
        tree = self.files()
        tree['company-agent-plugin/skills/demo/SKILL.md'] += b'\n[ref](../shared/reference.md)\n'
        tree['company-agent-plugin/skills/shared/reference.md'] = b'unchanged\r\n'
        tree['company-agent-plugin/THIRD_PARTY_NOTICES.md'] = b'notice'
        tree['company-agent-plugin/licenses/license.txt'] = b'license'
        files, links = export.source_files('demo', self.metadata()['demo'], tree)
        self.assertEqual(files['skills/shared/reference.md'][1], b'unchanged\r\n')
        self.assertEqual(links, [{'from': 'skills/demo/SKILL.md', 'to': 'skills/shared/reference.md'}])

    def test_missing_explicit_dependency_rejected(self):
        meta = self.metadata()['demo']; meta['packaging'] = {'includeAdditionalPaths': ['skills/missing/info.md']}
        with self.assertRaisesRegex(ValueError, 'Missing dependency'):
            export.source_files('demo', meta, self.files())

    def test_runtime_caches_not_collected(self):
        base = self.root / 'source'; base.mkdir()
        (base / 'SKILL.md').write_text('safe', encoding='utf-8')
        (base / '.env').write_text('secret', encoding='utf-8')
        (base / '__pycache__').mkdir()
        (base / '__pycache__/runtime.pyc').write_bytes(b'cache')
        self.assertEqual(set(export.read_tree(base, '.')), {'SKILL.md'})

    def test_packaging_normalizes_only_declared_utf8_text_without_editing_sources(self):
        for name in ('guide.md', 'run.py', 'invoke.ps1', 'LICENSE', 'SOURCE_LICENSE'):
            path = self.root / name
            original = b'\xef\xbb\xbfline 1\r\nline 2  \r\n'
            path.write_bytes(original)
            self.assertEqual(export.package_source_bytes(path), b'\xef\xbb\xbfline 1\nline 2  \n')
            self.assertEqual(path.read_bytes(), original)
        for name in ('font.woff', 'external.zip', 'unknown.bin'):
            path = self.root / name; raw = b'\xff\x00\r\nunchanged'
            path.write_bytes(raw)
            self.assertEqual(export.package_source_bytes(path), raw)
        for raw in (b'\xff\r\n', b'line\x00\r\n'):
            path = self.root / 'invalid.py'; path.write_bytes(raw)
            with self.assertRaises(ValueError):
                export.package_source_bytes(path)

    def test_reparse_source_rejected(self):
        import stat
        from types import SimpleNamespace
        path = self.root / 'source'; path.mkdir()
        real = Path.lstat
        def lstat(p, *a, **kw):
            if p == path:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return real(p, *a, **kw)
        with patch.object(Path, 'lstat', lstat), self.assertRaisesRegex(ValueError, '재분석'):
            export.no_links(path)

    def test_standard_missing_is_not_fallback_to_old_copy(self):
        with self.assertRaises(ValueError):
            export.standard_files(self.root)

    def test_standard_instruction_change_changes_fingerprint(self):
        for name in ('SKILL.md', 'references/package-format.md', 'assets/INSTALL_GUIDE.template.md',
                     'scripts/prepare_package.py', 'scripts/package_contract.py', 'scripts/install_scope.py'):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'v1')
        before = export.standard_files(self.root)
        (self.root / 'SKILL.md').write_bytes(b'v2')
        after = export.standard_files(self.root)
        self.assertNotEqual(export.digest(export.encoded({k: export.digest(v) for k, v in before.items()})),
                            export.digest(export.encoded({k: export.digest(v) for k, v in after.items()})))

    def test_check_is_read_only_and_noop_keeps_timestamp(self):
        out = self.root / 'dist'
        self.assertTrue(export.reconcile(out, self.artifacts(), check=True))
        self.assertFalse(out.exists())
        export.reconcile(out, self.artifacts())
        before = {p.name: p.stat().st_mtime_ns for p in out.iterdir()}
        self.assertEqual(export.reconcile(out, self.artifacts(), check=True), [])
        self.assertEqual(export.reconcile(out, self.artifacts()), [])
        self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in out.iterdir()})

    def test_modified_zip_preserved_before_any_write(self):
        out = self.root / 'dist'; export.reconcile(out, self.artifacts())
        (out / 'company-demo.zip').write_bytes(b'user edit')
        before = (out / 'catalog.json').read_bytes()
        with self.assertRaisesRegex(ValueError, '보존'):
            export.reconcile(out, self.artifacts(b'new'))
        self.assertEqual((out / 'company-demo.zip').read_bytes(), b'user edit')
        self.assertEqual((out / 'catalog.json').read_bytes(), before)

    def test_unrelated_files_preserved(self):
        out = self.root / 'dist'; out.mkdir(); (out / 'my-note.md').write_bytes(b'keep')
        export.reconcile(out, self.artifacts())
        self.assertEqual((out / 'my-note.md').read_bytes(), b'keep')

    def test_removed_managed_zip_is_recoverable(self):
        out = self.root / 'dist'; export.reconcile(out, self.artifacts())
        export.reconcile(out, {'catalog.json': export.encoded({'generator': 'company-platform-skills-v1', 'managedFiles': {}})})
        self.assertFalse((out / 'company-demo.zip').exists())
        self.assertEqual((out / '.previous' / export.digest(b'zip') / 'company-demo.zip').read_bytes(), b'zip')

    def test_owned_manifest_cannot_target_parent(self):
        out = self.root / 'dist'; out.mkdir()
        (out / 'catalog.json').write_bytes(export.encoded({'generator': 'company-platform-skills-v1', 'managedFiles': {'../escape': 'x'}}))
        with self.assertRaisesRegex(ValueError, '관리 파일'):
            export.reconcile(out, self.artifacts())

    @unittest.skipUnless(export.DEFAULT_STANDARD.is_dir(), 'Latest distribution skill required')
    def test_real_rebuild_tracks_skill_and_platform_changes_reproducibly(self):
        root = self.root / 'repo'; standard = self.root / 'standard'
        shutil.copytree(export.DEFAULT_STANDARD, standard, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        support = self.root / 'support'; support.mkdir()
        shutil.copyfile(export.SUPPORT / 'install_skill.py', support / 'install_skill.py')
        for directory in ('company-agent-plugin/resources/manuals', 'standalone-skills'):
            (root / directory).mkdir(parents=True)
        for name, content in {
            'company-agent-plugin/.claude-plugin/plugin.json': '{"version":"1.0.0"}',
            'company-agent-plugin/THIRD_PARTY_NOTICES.md': 'test notice',
            'company-agent-plugin/licenses/license.txt': 'test license',
            'company-agent-plugin/licenses/LICENSE': 'test license\nsecond line\n',
            'company-agent-plugin/skills/demo/SKILL.md': '---\nname: demo\ndescription: example\n---\n# Test\n',
        }.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding='utf-8')
        binary = root / 'company-agent-plugin/licenses/binary.dat'; binary.write_bytes(b'\xff\x00\r\nkeep')
        metadata = self.metadata()
        metadata['demo'].update(displayName='테스트', desc='가상 패키지', requirements=['시험 전용'], workTags=['시험'],
                                workflow={'steps': [{'title': '시험', 'description': '가상 자료 확인'}]})
        config = root / 'metadata.json'; config.write_bytes(export.encoded(metadata))
        def build(number):
            stage = self.root / ('stage-' + str(number)); stage.mkdir()
            with patch.object(export, 'SUPPORT', support):
                return export.build(root, standard, stage, config)
        # Model both Git checkout modes, including helper/contract source files.
        text_paths = [p for folder in (root, standard, support) for p in folder.rglob('*')
                      if p.is_file() and (p.suffix.lower() in export.TEXT_SUFFIXES or p.name.upper() in export.TEXT_NAMES)]
        for path in text_paths:
            path.write_bytes(export.package_source_bytes(path))
        first = build(1)
        for path in text_paths:
            path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(first, build(2), 'LF and CRLF checkouts must produce identical ZIPs/catalogues')
        self.assertEqual(binary.read_bytes(), b'\xff\x00\r\nkeep')
        source = root / 'company-agent-plugin/skills/demo/SKILL.md'
        source.write_text(source.read_text(encoding='utf-8') + '\nChanged instructions\n', encoding='utf-8')
        changed = build(3); self.assertNotEqual(first['demo.zip'], changed['demo.zip'])
        standard_skill = standard / 'SKILL.md'
        standard_skill.write_text(standard_skill.read_text(encoding='utf-8') + '\nTest revision\n', encoding='utf-8')
        revised = build(4); self.assertNotEqual(changed['demo.zip'], revised['demo.zip'])
        for artifacts in (first, changed, revised):
            self.assertEqual(json.loads(artifacts['catalog.json'])['packages'][0]['packageId'], 'demo')
        out = root / 'dist'; export.reconcile(out, first)
        (standard / 'scripts/prepare_package.py').write_text('raise ValueError("new unsupported contract")', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '규격 검사 실패'):
            build(5)
        self.assertEqual((out / 'demo.zip').read_bytes(), first['demo.zip'])


@unittest.skipUnless(export.DEFAULT_STANDARD.is_dir(), 'Latest platform distribution skill is required')
class ActualPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = ROOT / 'skills_zip'
        cls.catalog = json.loads((cls.out / 'catalog.json').read_text(encoding='utf-8'))
        cls.skills = [r for r in cls.catalog['packages'] if not r.get('external')]

    def test_all_discovered_skills_have_one_zip(self):
        actual = {p.parent.name for p in (ROOT / 'company-agent-plugin/skills').glob('*/SKILL.md')}
        metadata = json.loads((ROOT / 'scripts/platform_skills/catalog-metadata.json').read_text(encoding='utf-8'))
        actual |= {slug for slug, info in metadata.items() if info.get('standaloneOnly') is True
                   and (ROOT / info['sourceDir'] / 'SKILL.md').is_file()}
        self.assertEqual(actual, {r['slug'] for r in self.skills} | {r['slug'] for r in self.catalog['harnessOnly']})
        self.assertTrue(all(not r['runtimeRequired'] for r in self.skills))
        self.assertTrue(all(r['file'] == r['slug'] + '.zip' for r in self.skills))
        self.assertEqual(len(self.catalog['packages']), len(list(self.out.glob('*.zip'))))

    def test_all_archives_source_hashes_and_contract(self):
        sys.path.insert(0, str(export.DEFAULT_STANDARD / 'scripts'))
        from package_contract import read_package
        for row in self.skills:
            with self.subTest(skill=row['slug']):
                path = self.out / row['file']; export.check_zip(path)
                self.assertEqual(export.digest(path.read_bytes()), row['sha256'])
                with ZipFile(path) as z:
                    manifest = read_package(z)
                    self.assertEqual(manifest['packageId'], row['slug'])
                    self.assertEqual(row['packageId'], row['slug'])
                    self.assertEqual(row['installName'], row['slug'])
                    self.assertEqual(row['file'], row['slug'] + '.zip')
                    self.assertNotIn('Company', manifest['name'])
                    self.assertGreater(len(manifest['workflow']['steps']), 0)
                    source = json.loads(z.read('PACKAGE_SOURCE.json'))
                    self.assertEqual(source['textNormalization'], 'utf8-crlf-to-lf')
                    for name, original in source['files'].items():
                        self.assertEqual(z.read(name), export.package_source_bytes(ROOT / original['repoPath']))
                    self.assertEqual(z.read('install_scope.py'), export.package_source_bytes(export.DEFAULT_STANDARD / 'scripts/install_scope.py'))
                    self.assertEqual(z.read('install_skill.py'), export.package_source_bytes(export.SUPPORT / 'install_skill.py'))

    def test_portable_entries_and_requirements_have_no_harness_commands(self):
        forbidden = ('company_agent_runtime', 'stateRoot', 'company-agent:vision-worker',
                     'Invoke-CompanyAgent.ps1', 'company-agent business', 'company-agent asset')
        for row in self.skills:
            with self.subTest(skill=row['slug']), ZipFile(self.out / row['file']) as z:
                manifest = json.loads(z.read('ai-square.json'))
                instructions = z.read('SKILL.md').decode('utf-8') + z.read(f'source/skills/{row["slug"]}/SKILL.md').decode('utf-8')
                instructions += json.dumps(manifest, ensure_ascii=False)
                for value in forbidden:
                    self.assertNotIn(value, instructions)
                self.assertIn('name: ' + row['slug'] + '\n', z.read('SKILL.md').decode('utf-8'))

    def test_packaged_visual_engine_has_complete_local_imports_and_no_hooks(self):
        import ast
        for slug in ('presentation', 'html-report'):
            with ZipFile(self.out / (slug + '.zip')) as z:
                prefix = f'source/skills/{slug}/scripts/visual_engine/'
                files = {n[len(prefix):]:z.read(n) for n in z.namelist() if n.startswith(prefix)}
                for name, raw in files.items():
                    if not name.endswith('.py'):
                        continue
                    for node in ast.walk(ast.parse(raw)):
                        if isinstance(node, ast.ImportFrom) and node.level:
                            if node.module:
                                self.assertIn(node.module.split('.')[0] + '.py', files, (slug, name, node.module))
                            else:
                                for alias in node.names:
                                    self.assertIn(alias.name + '.py', files, (slug, name, alias.name))
                self.assertFalse({'cli.py', 'state.py', 'hooks.py', 'vision_routing.py'} & files.keys())

    def test_actual_platform_upload_inspection_and_autofill(self):
        sys.path.insert(0, str(ROOT))
        from flask import Flask
        from werkzeug.datastructures import FileStorage
        from pt_ai_square.backend.artifacts import stage_upload
        from pt_ai_square.backend.package_contract import registration_fields
        with tempfile.TemporaryDirectory(dir=ROOT / '.smoke/platform-skills') as td:
            base = Path(td); (base / 'artifacts').mkdir()
            app = Flask(__name__); app.config['DATA_DIR'] = str(base)
            with app.app_context(), patch('pt_ai_square.backend.artifacts.save_upload', lambda upload, path: upload.save(path)):
                for row in self.catalog['packages']:
                    with self.subTest(skill=row['slug']):
                        upload = FileStorage(stream=io.BytesIO((self.out / row['file']).read_bytes()), filename=row['file'])
                        staged = stage_upload(upload)
                        self.assertFalse(staged['packageWarning'])
                        fields = registration_fields(staged['package'])
                        self.assertEqual(fields['name'], row['name'])
                        self.assertEqual(fields['workflow'], staged['package']['workflow'])

    def test_every_archive_installs_in_isolated_project(self):
        sys.path.insert(0, str(export.DEFAULT_STANDARD / 'scripts'))
        spec = importlib.util.spec_from_file_location('actual_installer', export.SUPPORT / 'install_skill.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        for row in self.skills:
            with self.subTest(skill=row['slug']), tempfile.TemporaryDirectory(dir=ROOT / '.smoke/platform-skills') as td:
                base = Path(td); project = base / 'project'; project.mkdir()
                package = base / 'package'
                with ZipFile(self.out / row['file']) as z:
                    z.extractall(package)
                with contextlib.redirect_stdout(io.StringIO()):
                    dry = installer.install(package, scope='project', project_dir=str(project), dry_run=True, interactive=False)
                    self.assertEqual(dry['status'], 'dry-run')
                    self.assertFalse((project / '.claude').exists())
                    installed = installer.install(package, scope='project', project_dir=str(project), yes=True, interactive=False)
                target = Path(installed['target'])
                hashes = json.loads((package / 'PACKAGE_CONTENTS.json').read_bytes())['files']
                for name, sha in hashes.items():
                    self.assertEqual(export.digest((target / name).read_bytes()), sha)
                self.assertEqual(list((project / '.claude').iterdir()), [project / '.claude/skills'])

    def run_python(self, script, *args):
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(script), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8', timeout=120,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def test_packaged_excel_runs_and_calculates_across_sheets(self):
        import openpyxl
        with tempfile.TemporaryDirectory(dir=ROOT / '.smoke/platform-skills') as td:
            base = Path(td)
            with ZipFile(self.out / 'excel-to-pipeline.zip') as z:
                z.extractall(base / 'package')
            book = openpyxl.Workbook(); sheet = book.active; sheet.title = 'Data'
            for row in [['product', 'quantity', 'price', 'amount'], ['A', 2, 30, '=B2*C2'], ['B', 3, 20, '=B3*C3'], ['C', 1, 60, '=B4*C4']]:
                sheet.append(row)
            summary = book.create_sheet('Summary'); summary.append(['metric', 'value'])
            summary.append(['total_amount', '=SUM(Data!D2:D4)']); summary.append(['total_quantity', '=SUM(Data!B2:B4)'])
            source = base / 'synthetic.xlsx'; book.save(source); book.close(); before = source.read_bytes()
            script = base / 'package/source/skills/excel-to-pipeline/scripts/excel_pipeline.py'
            project = base / 'project'; result = base / 'result'
            self.run_python(script, source, '--reader', 'openpyxl', '--output', project)
            self.run_python(project / 'main.py', '--output', result)
            tables = json.loads((result / '결과표.json').read_text(encoding='utf-8'))
            values = next(t['rows'] for t in tables if t['sheet'] == 'Summary')
            self.assertEqual(dict(values), {'total_amount': 180, 'total_quantity': 6})
            self.assertTrue((project / '업무흐름.html').is_file())
            self.assertEqual(source.read_bytes(), before)

    def test_packaged_catalog_reports_synthetic_skill_without_sessions(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.smoke/platform-skills') as td:
            base = Path(td)
            with ZipFile(self.out / 'work-context-catalog.zip') as z:
                z.extractall(base / 'package')
            project = base / 'project'; skill = project / '.claude/skills/weekly-report'; skill.mkdir(parents=True)
            source = skill / 'SKILL.md'
            source.write_text('---\nname: weekly-report\ndescription: 합성 주간 보고\n---\n# 가상 실습 전용\n', encoding='utf-8')
            before = source.read_bytes(); result = base / 'result'
            self.run_python(base / 'package/source/skills/work-context-catalog/scripts/work_catalog.py',
                            '--root', project, '--no-sessions', '--output', result)
            catalog = json.loads((result / 'catalog.json').read_text(encoding='utf-8'))
            self.assertEqual(catalog['summary']['observed_sessions'], 0)
            self.assertTrue(any(a['title'] == 'weekly-report' for a in catalog['assets']))
            self.assertTrue((result / '업무현황.html').is_file())
            markdown = (result / '업무자산.md').read_text(encoding='utf-8')
            self.assertIn('weekly-report', markdown)
            self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
