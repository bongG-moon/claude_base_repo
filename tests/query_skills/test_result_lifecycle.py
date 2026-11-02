"""Synthetic local results only: metadata review, explicit cleanup and repeat runs."""
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import core, results
from query_core.store import Store, atomic_json, read_json


class ResultLifecycleTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-result-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'demo', demo=True)
        self.now = time.time()

    def saved(self, *, hours=25, engine='demo', store=None, result_id=None):
        store = store or self.store
        result_id = result_id or uuid.uuid4().hex
        folder = store.root / 'results' / result_id
        folder.mkdir(parents=True)
        raw = b'["RAW_RESULT_VALUE_MUST_NOT_APPEAR"]\n'
        data = folder / 'data.jsonl'
        data.write_bytes(raw)
        metadata = {'schemaVersion':1, 'ok':True, 'resultId':result_id, 'engine':engine, 'dbId':'fixture-db',
                    'queryId':1, 'sourceName':'가상DB', 'queryName':'같은 조회', 'status':'complete', 'complete':True,
                    'createdAt':self.now-hours*3600, 'dataFile':str(data), 'dataBytes':len(raw),
                    'dataSha256':hashlib.sha256(raw).hexdigest(), 'savedRows':1, 'columns':['VALUE'],
                    'columnCount':1, 'format':'jsonl-arrays', 'demo':store.demo,
                    'params':{'private-filter':'SECRET_PARAMETER_MUST_NOT_APPEAR'},
                    'queryHash':'query-fixture-hash', 'planId':uuid.uuid4().hex}
        atomic_json(folder / 'metadata.json', metadata)
        return result_id, folder, metadata

    def prepare(self, ids, **kwargs):
        return results.prepare_cleanup(self.store, 'demo', ids, now=self.now, **kwargs)

    def delete(self, proposal, **kwargs):
        return results.delete_cleanup(self.store, 'demo', proposal['planId'], now=self.now+1, **kwargs)

    def test_listing_is_metadata_only_bounded_and_a_single_old_latest_result_is_eligible(self):
        first, _, _ = self.saved()
        real_open = Path.open
        def metadata_only(path, *args, **kwargs):
            if path.suffix in {'.jsonl', '.csv'}:
                raise AssertionError('Listing opened original rows')
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', metadata_only), patch.object(self.store, 'secrets', side_effect=AssertionError('secrets forbidden')):
            summary = results.list_candidates(self.store, 'demo', now=self.now)
        self.assertEqual(summary['count'], 1)
        self.assertEqual(summary['results'][0]['resultId'], first)
        self.assertNotIn('RAW_RESULT', json.dumps(summary))
        self.assertNotIn('SECRET_PARAMETER', json.dumps(summary))
        for _ in range(11):
            self.saved()
        with patch.object(Path, 'open', metadata_only):
            summary = results.list_candidates(self.store, 'demo', now=self.now)
        self.assertEqual(summary['count'], 12)
        self.assertEqual(summary['returnedCount'], 10)
        self.assertTrue(summary['reviewLimited'])
        self.assertLess(len(json.dumps(summary, ensure_ascii=False)), 7000)

    def test_24_hour_boundary_recent_and_explicit_current_are_preserved(self):
        old, _, _ = self.saved(hours=24)
        recent, _, _ = self.saved(hours=23.99)
        selected = results.list_candidates(self.store, 'demo', now=self.now)
        self.assertEqual([item['resultId'] for item in selected['results']], [old])
        selected = results.list_candidates(self.store, 'demo', now=self.now, current_result_id=old)
        self.assertEqual(selected['count'], 0)
        for result_id, options in ((recent, {}), (old, {'current_result_id':old})):
            with self.assertRaises(ValueError):
                self.prepare([result_id], **options)

    def test_prepare_never_deletes_and_confirmation_is_exact_once(self):
        selected, folder, _ = self.saved()
        unselected, untouched, _ = self.saved()
        catalog = self.store.db.read_bytes()
        plan = self.prepare([selected])
        self.assertTrue((folder / 'data.jsonl').exists())
        self.assertEqual(plan['resultIds'], [selected])
        with self.assertRaisesRegex(ValueError, '확인'):
            self.delete(plan)
        self.assertTrue(folder.exists())
        report = self.delete(plan, confirmed=True)
        self.assertEqual(report['deletedIds'], [selected])
        self.assertGreater(report['deletedBytes'], 0)
        self.assertFalse(folder.exists())
        self.assertTrue(untouched.exists())
        self.assertEqual(catalog, self.store.db.read_bytes())
        with self.assertRaisesRegex(ValueError, '이미'):
            self.delete(plan, confirmed=True)

    def test_plan_tampering_expiry_and_wrong_engine_never_delete(self):
        result_id, folder, _ = self.saved()
        plan = self.prepare([result_id])
        with self.assertRaises(ValueError):
            results.delete_cleanup(self.store, 'oracle', plan['planId'], confirmed=True, now=self.now+1)
        with self.assertRaisesRegex(ValueError, '15분'):
            results.delete_cleanup(self.store, 'demo', plan['planId'], confirmed=True, now=self.now+901)
        path = self.store.root / 'result-cleanup-plans' / (plan['planId'] + '.json')
        body = read_json(path)
        body['snapshots'][0]['resultId'] = uuid.uuid4().hex
        atomic_json(path, body)
        with self.assertRaisesRegex(ValueError, '바뀌'):
            self.delete(plan, confirmed=True)
        self.assertTrue(folder.exists())

    def test_changed_data_same_size_and_restored_mtime_are_preserved(self):
        result_id, folder, _ = self.saved()
        plan = self.prepare([result_id])
        path = folder / 'data.jsonl'
        previous = path.stat()
        path.write_bytes(path.read_bytes().replace(b'RAW_RESULT', b'NEW_RESULT'))
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        report = self.delete(plan, confirmed=True)
        self.assertEqual(report['deletedIds'], [])
        self.assertTrue(path.exists())
        self.assertEqual(report['retained'][0]['resultId'], result_id)

    def test_changed_metadata_extra_files_and_newer_current_marker_are_preserved(self):
        for variant in ('metadata', 'extra', 'recent'):
            with self.subTest(variant=variant):
                result_id, folder, metadata = self.saved()
                plan = self.prepare([result_id])
                if variant == 'extra':
                    (folder / 'personal-note.md').write_text('keep', encoding='utf-8')
                else:
                    metadata['createdAt'] = self.now if variant == 'recent' else metadata['createdAt']
                    metadata['queryName'] = 'changed'
                    atomic_json(folder / 'metadata.json', metadata)
                self.assertEqual(self.delete(plan, confirmed=True)['deletedIds'], [])
                self.assertTrue((folder / 'data.jsonl').exists())

    def test_unknown_or_external_paths_are_never_candidates(self):
        for variant in ('extra-file', 'empty-folder', 'outside', 'missing', 'wrong-id', 'unknown-engine'):
            with self.subTest(variant=variant):
                result_id, folder, metadata = self.saved()
                if variant == 'extra-file': (folder / 'personal.md').write_text('keep')
                elif variant == 'empty-folder': (folder / 'personal').mkdir()
                elif variant == 'outside': metadata['dataFile'] = str(self.store.db)
                elif variant == 'missing': (folder / 'data.jsonl').unlink()
                elif variant == 'wrong-id': metadata['resultId'] = uuid.uuid4().hex
                elif variant == 'unknown-engine': metadata['engine'] = 'unknown'; metadata['demo'] = False
                atomic_json(folder / 'metadata.json', metadata)
                self.assertNotIn(result_id, [item['resultId'] for item in results.list_candidates(self.store, 'demo', now=self.now)['results']])
                with self.assertRaises(ValueError): self.prepare([result_id])
                self.assertTrue(folder.exists())
        for invalid in ('../catalog.sqlite3', '', 'A'*32):
            with self.assertRaises(ValueError): self.prepare([invalid])

    def test_managed_exports_delete_together_but_external_csv_survives(self):
        result_id, folder, _ = self.saved()
        internal = folder / 'exports' / 'view.csv'
        external = self.root / 'user-chosen.csv'
        core.export_csv(self.store, result_id, internal)
        core.export_csv(self.store, result_id, external)
        before = external.read_bytes()
        metadata = read_json(folder / 'metadata.json')
        self.assertEqual(metadata['managedExports'][0]['path'], 'exports/view.csv')
        plan = self.prepare([result_id])
        self.assertEqual(self.delete(plan, confirmed=True)['deletedIds'], [result_id])
        self.assertFalse(folder.exists())
        self.assertEqual(before, external.read_bytes())

    def test_modified_managed_export_and_unregistered_export_are_preserved(self):
        for tracked in (True, False):
            result_id, folder, _ = self.saved()
            output = folder / 'exports' / 'view.csv'
            if tracked:
                core.export_csv(self.store, result_id, output)
                output.write_text('personal edit', encoding='utf-8')
            else:
                output.parent.mkdir()
                output.write_text('personal file', encoding='utf-8')
            with self.assertRaises(ValueError): self.prepare([result_id])
            self.assertTrue(output.exists())

    def test_legacy_engine_is_recovered_from_matching_used_plan_without_secrets(self):
        store = Store(self.root / 'personal')
        result_id, folder, metadata = self.saved(store=store, engine='oracle')
        plan_id = store.save_plan({'engine':'oracle', 'queryHash':metadata['queryHash']})
        store.claim_plan(plan_id)
        metadata.pop('engine'); metadata.pop('createdAt'); metadata.pop('dataSha256')
        metadata['planId'] = plan_id
        atomic_json(folder / 'metadata.json', metadata)
        stamp = self.now-25*3600
        os.utime(folder / 'data.jsonl', (stamp-1, stamp-1))
        os.utime(folder / 'metadata.json', (stamp, stamp))
        before = store.db.read_bytes()
        with patch.object(store, 'secrets', side_effect=AssertionError('no credentials')), patch('socket.socket', side_effect=AssertionError('no network')):
            summary = results.list_candidates(store, 'oracle', now=self.now)
        self.assertEqual(summary['count'], 1)
        self.assertTrue(summary['results'][0]['timeApproximate'])
        self.assertEqual(results.list_candidates(store, 'ehub', now=self.now)['count'], 0)
        self.assertEqual(before, store.db.read_bytes())
        metadata['queryHash'] = 'changed'
        atomic_json(folder / 'metadata.json', metadata)
        os.utime(folder / 'metadata.json', (stamp, stamp))
        self.assertEqual(results.list_candidates(store, 'oracle', now=self.now)['count'], 0)
        self.assertTrue(folder.exists())
        metadata['queryHash'] = 'query-fixture-hash'
        atomic_json(folder / 'metadata.json', metadata)
        os.utime(folder / 'metadata.json', (stamp, stamp))
        plan = results.prepare_cleanup(store, 'oracle', [result_id], now=self.now)
        report = results.delete_cleanup(store, 'oracle', plan['planId'], confirmed=True, now=self.now+1)
        self.assertEqual(report['deletedIds'], [result_id])
        self.assertFalse(folder.exists())
        self.assertEqual(before, store.db.read_bytes())

    def test_failed_results_can_be_cleaned_without_data_and_other_engine_is_preserved(self):
        result_id, folder, metadata = self.saved()
        (folder / 'data.jsonl').unlink()
        metadata.pop('dataSha256')
        metadata.update(status='failed', dataAvailable=False)
        atomic_json(folder / 'metadata.json', metadata)
        plan = self.prepare([result_id])
        self.assertEqual(self.delete(plan, confirmed=True)['deletedIds'], [result_id])

    def test_hard_link_is_preserved(self):
        result_id, folder, _ = self.saved()
        target = self.root / 'personal-original.jsonl'
        os.link(folder / 'data.jsonl', target)
        with self.assertRaises(ValueError): self.prepare([result_id])
        self.assertTrue(target.exists())
        self.assertTrue(folder.exists())

    def test_symbolic_link_target_is_preserved(self):
        result_id, folder, _ = self.saved()
        target = self.root / 'outside-personal.jsonl'
        target.write_bytes(b'private original')
        data = folder / 'data.jsonl'
        data.unlink()
        try:
            data.symlink_to(target)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                # Junction creation does not require SeCreateSymbolicLinkPrivilege.
                # Both endpoints are owned by this synthetic workspace fixture.
                junction_target = self.root / 'linked-result'
                self.assertTrue(folder.resolve().is_relative_to(self.root.resolve()))
                self.assertTrue(junction_target.resolve().is_relative_to(self.root.resolve()))
                folder.rename(junction_target)
                ps = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                quoted = lambda value: "'" + str(value).replace("'", "''") + "'"
                subprocess.run([str(ps), '-NoProfile', '-Command',
                                "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path " + quoted(folder) + ' -Target ' + quoted(junction_target) + ' | Out-Null'],
                               check=True, capture_output=True, timeout=15)
            else:
                raise
        with self.assertRaises(ValueError): self.prepare([result_id])
        self.assertEqual(target.read_bytes(), b'private original')
        self.assertTrue(folder.exists())

    @unittest.skipUnless(os.name == 'nt', 'NTFS stream protection')
    def test_file_directory_and_root_alternate_streams_are_preserved(self):
        for kind in ('file', 'directory', 'root'):
            with self.subTest(kind=kind):
                result_id, folder, _ = self.saved()
                target = folder / 'data.jsonl' if kind == 'file' else folder if kind == 'directory' else folder.parent
                stream = Path(str(target) + ':personal-note')
                stream.write_bytes(b'personal alternate data')
                try:
                    with self.assertRaises(ValueError): self.prepare([result_id])
                    self.assertEqual(stream.read_bytes(), b'personal alternate data')
                    self.assertTrue(folder.exists())
                finally:
                    stream.unlink()

    def test_demo_repeated_same_conditions_produce_unique_identifiable_results(self):
        core.demo_init(self.store)
        params = {'start_date':'2026-10-01','end_date':'2026-11-01','process':'WB'}
        snapshots = []
        for _ in range(2):
            with patch('socket.socket', side_effect=AssertionError('network forbidden')):
                proposal = core.plan(self.store, 'demo', 1, params)
                response = core.run(self.store, 'demo', proposal['planId'], confirmed=True)
            self.assertLess(len(json.dumps(response)), 1800)
            folder = Path(response['dataFile']).parent
            metadata = read_json(folder / 'metadata.json')
            self.assertEqual(metadata['dbId'], 'production')
            self.assertEqual(metadata['queryId'], 1)
            self.assertEqual(metadata['params'], params)
            self.assertEqual(metadata['limits']['max_rows'], 10000)
            self.assertIn(response['resultId'][:8], metadata['label'])
            self.assertTrue(metadata['executedAt'])
            snapshots.append((response['resultId'], folder, (folder / 'metadata.json').read_bytes(), (folder / 'data.jsonl').read_bytes()))
        self.assertNotEqual(snapshots[0][0], snapshots[1][0])
        first = snapshots[0]
        self.assertEqual(first[2], (first[1] / 'metadata.json').read_bytes())
        self.assertEqual(first[3], (first[1] / 'data.jsonl').read_bytes())
        self.assertEqual(results.list_candidates(self.store, 'demo')['count'], 0)


if __name__ == '__main__':
    unittest.main()
