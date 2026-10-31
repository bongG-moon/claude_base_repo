"""Independent query distribution tests; no profiles, SQL servers or installation."""
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import zipfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


export = module('query_package_export', ROOT / 'scripts/build-skill-packages.py')
syncer = module('query_skill_sync', ROOT / 'scripts/sync-query-skills.py')


class StandaloneDiscoveryTests(unittest.TestCase):
    def data(self):
        tree = {'standalone-skills/test-query/SKILL.md': b'---\nname: test-query\n---\n'}
        metadata = {'test-query': {'sourceDir': 'standalone-skills/test-query',
                                  'runtimeRequired': False, 'standaloneOnly': True, 'distribution': 'portable'}}
        return tree, metadata

    def test_standalone_needs_no_harness_copy(self):
        tree, metadata = self.data()
        self.assertEqual(set(export.discover(tree, metadata)), {'test-query'})

    def test_missing_standalone_metadata_is_not_omitted(self):
        tree, _ = self.data()
        with self.assertRaisesRegex(ValueError, '새 스킬'):
            export.discover(tree, {})

    def test_explicit_standalone_opt_in_is_required(self):
        tree, metadata = self.data()
        del metadata['test-query']['standaloneOnly']
        with self.assertRaisesRegex(ValueError, 'standaloneOnly'):
            export.discover(tree, metadata)

    def test_missing_declared_source_is_failure(self):
        _, metadata = self.data()
        with self.assertRaisesRegex(ValueError, '정본'):
            export.discover({}, metadata)

    def test_false_flag_does_not_resurrect_removed_harness_skill(self):
        tree, metadata = self.data()
        metadata['removed'] = {'standaloneOnly': False, 'distribution': 'portable'}
        self.assertEqual(set(export.discover(tree, metadata)), {'test-query'})

    def test_harness_copy_conflicts_with_standalone_only(self):
        tree, metadata = self.data()
        tree['company-agent-plugin/skills/test-query/SKILL.md'] = b'plugin'
        with self.assertRaisesRegex(ValueError, '독립 전용'):
            export.discover(tree, metadata)

    def test_flag_is_strict_boolean(self):
        tree, metadata = self.data()
        metadata['test-query']['standaloneOnly'] = 'true'
        with self.assertRaises(ValueError):
            export.discover(tree, metadata)

    def test_real_skills_are_explicit_and_brief(self):
        metadata = json.loads((ROOT / 'scripts/platform_skills/catalog-metadata.json').read_text(encoding='utf-8'))
        for slug in syncer.SKILLS:
            with self.subTest(slug=slug):
                self.assertIs(metadata[slug]['standaloneOnly'], True)
                self.assertIs(metadata[slug]['runtimeRequired'], False)
                self.assertFalse((ROOT / 'company-agent-plugin/skills' / slug).exists())
                body = (ROOT / 'standalone-skills' / slug / 'SKILL.md').read_text(encoding='utf-8')
                self.assertLess(len(body.splitlines()), 100)
                self.assertIn('등록한 DB 이름', body)
                self.assertIn('--allow-large', body)


class QuerySyncTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-package-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root / 'scripts/query_skills/query_core'
        source.mkdir(parents=True)
        (source / '__init__.py').write_text('', encoding='utf-8')
        (source / 'cli.py').write_text('def main(engine): return 0\n', encoding='utf-8')
        (source / 'core.py').write_text('# first\n', encoding='utf-8')
        for slug in syncer.SKILLS:
            skill = self.root / 'standalone-skills' / slug
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: ' + slug + '\n---\n', encoding='utf-8')

    def test_check_does_not_create_runtime(self):
        self.assertEqual(set(syncer.sync(self.root, check=True)), set(syncer.SKILLS))
        for slug in syncer.SKILLS:
            self.assertFalse((self.root / 'standalone-skills' / slug / 'scripts').exists())

    def test_sync_exact_and_noop(self):
        self.assertEqual(len(syncer.sync(self.root)), 4)
        self.assertEqual(syncer.sync(self.root, check=True), [])
        self.assertEqual(syncer.sync(self.root), [])
        for slug in syncer.SKILLS:
            path = self.root / 'standalone-skills' / slug / 'scripts/query_core/core.py'
            self.assertEqual(path.read_bytes(), b'# first\n')

    def test_update_and_removed_managed_file(self):
        syncer.sync(self.root)
        source = self.root / 'scripts/query_skills/query_core'
        (source / 'core.py').unlink()
        (source / 'sql.py').write_text('# replacement\n', encoding='utf-8')
        self.assertEqual(len(syncer.sync(self.root)), 4)
        for slug in syncer.SKILLS:
            target = self.root / 'standalone-skills' / slug / 'scripts/query_core'
            self.assertFalse((target / 'core.py').exists())
            self.assertTrue((target / 'sql.py').exists())

    def test_unknown_files_preserved(self):
        syncer.sync(self.root)
        target = self.root / 'standalone-skills/oracle-query/scripts/query_core/private.txt'
        target.write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '보존'):
            syncer.sync(self.root)
        self.assertEqual(target.read_text(), 'keep')

    def test_manifest_traversal_rejected(self):
        syncer.sync(self.root)
        record = self.root / 'standalone-skills/oracle-query' / syncer.MANIFEST
        value = json.loads(record.read_text())
        value['files']['../../outside.py'] = 'x'
        record.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '잘못된 경로'):
            syncer.sync(self.root)

    def test_incomplete_canonical_source_is_not_success(self):
        (self.root / 'scripts/query_skills/query_core/cli.py').unlink()
        with self.assertRaisesRegex(ValueError, '필수 진입점'):
            syncer.sync(self.root)


class ActualQueryZipTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-zip-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def unpack(self, slug):
        folder = self.root / slug
        with zipfile.ZipFile(ROOT / 'skills_zip' / (slug + '.zip')) as archive:
            archive.extractall(folder)
        return folder / 'source/skills' / slug / 'scripts/query.py'

    def command(self, script, *args, expected=0):
        # PYTHONPATH와 현재 폴더는 배제하고, 사용자가 설치한 requirements 패키지는 허용합니다.
        result = subprocess.run([sys.executable,'-E','-P','-X','utf8','-B',str(script),
                                 '--state-root',str(self.root / (script.parents[1].name+'-state')),*args],
                                cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,expected,result.stderr+result.stdout)
        self.assertEqual(result.stderr,'')
        return json.loads(result.stdout)

    def test_each_live_zip_loads_without_sibling_skills_or_harness(self):
        for slug in ('oracle-query','datalake-query','ehub-query'):
            with self.subTest(slug=slug):
                response = self.command(self.unpack(slug),'profiles','list')
                self.assertFalse(response['connected'])
                self.assertEqual(response['profiles'],[])

    def test_demo_zip_complete_conversation_commands(self):
        script = self.unpack('data-query-demo')
        init = self.command(script,'demo-init')
        self.assertEqual(init['networkCalls'],0)
        self.assertEqual(init['queries'][0]['display'],'1. 생산실적조회 — 생산DB')
        params = self.root / 'conditions.json'
        params.write_text(json.dumps({'start_date':'2026-10-01','end_date':'2026-11-01','process':'WB'}),encoding='utf-8')
        plan = self.command(script,'plan','--id','1','--params',str(params))
        self.assertFalse(plan['requiresLargeApproval'])
        result = self.command(script,'run','--plan',plan['planId'],'--confirm')
        self.assertEqual(result['savedRows'],1)
        self.assertEqual(result['dataRowsReturned'],0)
        self.assertNotIn('LOT006',json.dumps(result))
        self.assertTrue(Path(result['dataFile']).is_file())
        self.assertEqual(self.command(script,'result','--id',result['resultId']),result)
        exported = self.command(script,'export-csv','--id',result['resultId'],'--output',str(self.root/'result.csv'))
        self.assertTrue(exported['complete'])

    def test_demo_zip_large_approval_and_query_registration(self):
        script = self.unpack('data-query-demo')
        self.command(script,'demo-init')
        spec = self.root / 'saved-query.json'
        spec.write_text(json.dumps({'name':'공정 건수','profile':'production',
            'sql':'SELECT COUNT(*) AS n FROM production_records WHERE process = :process',
            'parameters':{'process':{'type':'text'}}},ensure_ascii=False),encoding='utf-8')
        registered = self.command(script,'queries','register','--spec',str(spec))
        self.assertEqual(registered['id'],6)
        self.assertFalse(registered['executed'])
        params = self.root / 'empty.json'
        params.write_text('{}',encoding='utf-8')
        plan = self.command(script,'plan','--id','5','--params',str(params),'--max-rows','20000')
        response = self.command(script,'run','--plan',plan['planId'],'--confirm',expected=2)
        self.assertEqual(response['status'],'large_query_approval_required')
        result = self.command(script,'run','--plan',plan['planId'],'--confirm','--allow-large')
        self.assertTrue(result['complete'])
        self.assertEqual(result['savedRows'],12005)


if __name__ == '__main__':
    unittest.main()
