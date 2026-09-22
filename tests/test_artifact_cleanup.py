from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'company-agent-plugin/scripts'))
from company_agent import artifact_delivery as delivery, artifact_cleanup as cleaning
from company_agent import business_artifacts as artifacts


class ArtifactCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root/'state'
        self.output = self.root/'final.html'
        self.spec = {'title':'Report','style':'minimal','length':'standard','mode':'scroll',
                     'sections':[{'title':'Summary','body':'Content'}]}
        self.work = Path(delivery.start(self.state, self.output)['workFile'])

    def build(self):
        result = delivery.build(self.state, self.work, 'html', self.spec)
        self.assertTrue(result['ok'], result)
        return Path(result['outputPath'])

    def read(self):
        return json.loads(self.work.read_text(encoding='utf-8'))

    def write(self, data):
        self.work.write_text(json.dumps(data), encoding='utf-8')

    def test_cleanup_requires_publication_and_preserves_active_work(self):
        candidate = self.build()
        before = candidate.read_bytes()
        result = delivery.cleanup(self.state, self.work)
        self.assertEqual('artifact_not_published', result['code'])
        self.assertEqual(before, candidate.read_bytes())
        self.assertFalse(self.output.exists())

    def test_explicit_registry_and_cleanup_scope_preserve_user_and_source_files(self):
        old = self.build()
        new = self.build()
        files = [self.work.parent/'job.json', old.parent/'notes.txt', new.parent/'source.png',
                 self.root/'memory.md', self.root/'SKILL.md']
        for path in files:
            path.write_text('user content', encoding='utf-8')
        data = self.read()
        self.assertEqual(2, data['schema'])
        self.assertEqual(2, len(data['ownedFiles']))
        for record in data['ownedFiles']:
            self.assertFalse(Path(record['path']).is_absolute())
            self.assertEqual('candidate', record['role'])
            self.assertRegex(record['sha256'], r'^[a-f0-9]{64}$')
        final = delivery.publish(self.state, self.work)
        self.assertTrue(final['ok'], final)
        self.assertEqual(2, final['cleanup']['deletedCount'])
        self.assertTrue(self.output.is_file())
        self.assertTrue(self.work.is_file())
        self.assertTrue(all(path.read_text(encoding='utf-8') == 'user content' for path in files))
        repeat = delivery.cleanup(self.state, self.work)
        self.assertTrue(repeat['ok'], repeat)
        self.assertEqual(0, repeat['cleanup']['deletedCount'])
        self.assertEqual(2, repeat['cleanup']['missingCount'])

    def test_changed_or_replaced_file_even_same_bytes_is_retained(self):
        changed = self.build()
        changed.write_text('User revision', encoding='utf-8')
        replaced = self.build()
        before = replaced.read_bytes()
        replacement = replaced.parent/'user-copy.html'
        replacement.write_bytes(before)
        os.replace(replacement, replaced)
        self.build()
        result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['deletedCount'])
        self.assertEqual(2, result['cleanup']['retainedCount'])
        self.assertEqual(2, result['cleanup']['reasons']['changed'])
        self.assertEqual('User revision', changed.read_text(encoding='utf-8'))
        self.assertEqual(before, replaced.read_bytes())

    def test_hardlinked_registered_file_is_retained(self):
        old = self.build()
        outside = self.root/'retained-source.html'
        os.link(old, outside)
        self.build()
        result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['deletedCount'])
        self.assertEqual(1, result['cleanup']['reasons']['linked_or_unverified'])
        self.assertEqual(old.read_bytes(), outside.read_bytes())

    def test_linked_attempt_is_retained_without_following_target(self):
        old = self.build()
        source_folder = self.root/'user-source'
        source_folder.mkdir()
        source = source_folder/'result.html'
        source.write_text('user file', encoding='utf-8')
        old.unlink()
        old.parent.rmdir()
        try:
            old.parent.symlink_to(source_folder, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('Directory links unavailable')
            # Junctions are available to normal Windows users and cover reparse handling.
            # Directory junction creation via cmd is non-destructive; both targets are exact temp paths.
            call = subprocess.run(['cmd', '/c', 'mklink', '/J', str(old.parent), str(source_folder)],
                                  capture_output=True)
            if call.returncode:
                self.skipTest('Directory junction creation unavailable')
        self.addCleanup(lambda: os.rmdir(old.parent) if old.parent.exists() else None)
        self.build()
        result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['reasons']['linked_or_unverified'])
        self.assertEqual('user file', source.read_text(encoding='utf-8'))

    def test_legacy_work_remains_usable_and_never_gains_ownership(self):
        first = self.build()
        data = self.read()
        data['schema'] = 1
        data.pop('ownedFiles')
        self.write(data)
        second = self.build()
        result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual('legacy_retained', result['cleanup']['status'])
        self.assertNotIn('ownedFiles', self.read())
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())
        self.assertEqual('legacy_retained', delivery.cleanup(self.state, self.work)['cleanup']['status'])

    def test_malformed_registry_and_outside_paths_never_delete_any_file(self):
        candidate = self.build()
        original = self.read()
        outside = self.root/'private.txt'
        outside.write_text('personal', encoding='utf-8')
        invalid = [None, {}, [{'path':'../private.txt'}],
                   [{**original['ownedFiles'][0], 'path':str(outside)}],
                   [{**original['ownedFiles'][0], 'path':'attempts/../private.txt'}],
                   [{**original['ownedFiles'][0], 'role':'source'}],
                   original['ownedFiles'] * 2,
                   [{**original['ownedFiles'][0], 'state':{'inode':True}}]]
        # Establish a verified receipt while cleanup is held back.
        with patch.object(cleaning, 'after_publish', return_value={}):
            self.assertTrue(delivery.publish(self.state, self.work)['ok'])
        published = self.read()
        for registry in invalid:
            with self.subTest(registry=registry):
                self.write({**published, 'ownedFiles':registry})
                result = delivery.cleanup(self.state, self.work)
                self.assertTrue(result['ok'], result)
                self.assertEqual('invalid_registry', result['cleanup']['status'])
                self.assertTrue(candidate.is_file())
                self.assertEqual('personal', outside.read_text(encoding='utf-8'))

    def test_malformed_receipt_rejected_before_cleanup(self):
        candidate = self.build()
        data = self.read()
        data['published'] = {'sha256':123, 'status':'created'}
        self.write(data)
        self.assertEqual('invalid_artifact_work', delivery.cleanup(self.state, self.work)['code'])
        self.assertTrue(candidate.is_file())

    def test_locked_file_and_unexpected_cleanup_failure_do_not_fail_delivery(self):
        old = self.build()
        self.build()
        original = cleaning._remove_registered
        def locked(path, record):
            if path == old:
                raise PermissionError('in use')
            return original(path, record)
        with patch.object(cleaning, '_remove_registered', side_effect=locked):
            result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['deletedCount'])
        self.assertEqual(1, result['cleanup']['failedCount'])
        stamp = self.output.stat().st_mtime_ns
        with patch.object(cleaning, 'run', side_effect=OSError('cleanup failed')):
            result = delivery.publish(self.state, self.work)
        self.assertTrue(result['alreadyDelivered'])
        self.assertEqual('unavailable', result['cleanup']['status'])
        self.assertEqual(stamp, self.output.stat().st_mtime_ns)
        self.assertEqual(1, delivery.cleanup(self.state, self.work)['cleanup']['deletedCount'])

    @unittest.skipUnless(os.name == 'nt', 'Windows checked-handle deletion')
    def test_real_open_file_is_preserved_and_cleanup_retries_only_removal(self):
        old = self.build()
        self.build()
        with old.open('rb'):
            result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['failedCount'])
        self.assertTrue(old.is_file())
        with patch.object(artifacts, 'create_html', side_effect=AssertionError('no regeneration')):
            result = delivery.cleanup(self.state, self.work)
        self.assertEqual(1, result['cleanup']['deletedCount'])

    def test_cleanup_cannot_remove_final_even_when_manifest_points_at_it(self):
        candidate = self.build()
        data = self.read()
        # A malformed/moved final path in the attempt area still must never be deleted.
        data['output'] = str(candidate)
        data['published'] = {k:data['candidate'][k] for k in ('sha256','status','warnings')}
        self.write(data)
        result = delivery.cleanup(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['reasons']['final_output'])
        self.assertTrue(candidate.is_file())

    def test_changed_final_prevents_any_cleanup(self):
        candidate = self.build()
        with patch.object(cleaning, 'after_publish', return_value={}):
            self.assertTrue(delivery.publish(self.state, self.work)['ok'])
        self.output.write_text('user final edit', encoding='utf-8')
        self.assertEqual('delivered_file_changed', delivery.cleanup(self.state, self.work)['code'])
        self.assertTrue(candidate.is_file())

    def test_local_html_dependencies_and_unknown_scripts_are_retained(self):
        cases = ['<img src="asset.png">', '<style>body{background:url(asset.png)}</style>',
                 '<script>const p="asset.png";window.load(p)</script>',
                 '<img srcset="a.png 1x, b.png 2x">']
        for html in cases:
            with self.subTest(html=html):
                output = self.root/('final-' + str(cases.index(html)) + '.html')
                work = Path(delivery.start(self.state, output)['workFile'])
                def create(_spec, path, **_kwargs):
                    path.write_text(html, encoding='utf-8')
                    asset = path.parent/'asset.png'
                    asset.write_bytes(b'asset')
                    return {'ok':True,'status':'created','outputPath':str(path)}
                with patch.object(artifacts, 'create_html', side_effect=create):
                    built = delivery.build(self.state, work, 'html', self.spec)
                result = delivery.publish(self.state, work)
                self.assertTrue(result['ok'], result)
                self.assertEqual(1, result['cleanup']['reasons']['final_dependencies'])
                self.assertTrue(Path(built['outputPath']).is_file())
                self.assertTrue((Path(built['outputPath']).parent/'asset.png').is_file())

    def test_final_html_can_keep_a_registered_local_dependency(self):
        dependency = self.build()
        def create(_spec, path, **_kwargs):
            path.write_text('<iframe src="' + dependency.as_uri() + '"></iframe>', encoding='utf-8')
            return {'ok':True,'status':'created','outputPath':str(path)}
        with patch.object(artifacts, 'create_html', side_effect=create):
            candidate = self.build()
        result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(2, result['cleanup']['reasons']['final_dependencies'])
        self.assertTrue(dependency.is_file())
        self.assertTrue(candidate.is_file())
        self.assertIn(dependency.as_uri(), self.output.read_text(encoding='utf-8'))

    @unittest.skipUnless(os.name == 'nt', 'Windows checked-handle deletion')
    def test_cleanup_handle_denies_concurrent_file_writes(self):
        old = self.build()
        self.build()
        with patch.object(cleaning, 'after_publish', return_value={}):
            self.assertTrue(delivery.publish(self.state, self.work)['ok'])
        original = cleaning.hashlib.file_digest
        blocked = []
        old_identity = old.stat().st_ino
        def attempt_write(stream, algorithm):
            # Only deletion holds a duplicated OS handle (the stream name is an fd).
            if (isinstance(stream.name, int) and os.fstat(stream.fileno()).st_ino == old_identity
                    and not blocked):
                with self.assertRaises(PermissionError):
                    old.write_text('concurrent user write', encoding='utf-8')
                blocked.append(True)
            return original(stream, algorithm)
        with patch.object(cleaning.hashlib, 'file_digest', side_effect=attempt_write):
            result = delivery.cleanup(self.state, self.work)
        self.assertEqual([True], blocked)
        self.assertEqual(2, result['cleanup']['deletedCount'])

    @unittest.skipUnless(os.name == 'nt', 'Windows checked-handle deletion')
    def test_final_cannot_change_or_be_replaced_during_cleanup(self):
        self.build()
        self.build()
        replacement = self.root/'user-new-final.html'
        replacement.write_text('<img src="a-new-dependency.png">', encoding='utf-8')
        original = cleaning._remove_registered
        attempts = []
        def concurrent_edit(path, record):
            with self.assertRaises(PermissionError):
                self.output.write_text('user edit during cleanup', encoding='utf-8')
            with self.assertRaises(PermissionError):
                os.replace(replacement, self.output)
            attempts.append(True)
            return original(path, record)
        with patch.object(cleaning, '_remove_registered', side_effect=concurrent_edit):
            result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(2, result['cleanup']['deletedCount'])
        self.assertEqual([True, True], attempts)
        self.assertTrue(replacement.is_file())

    @unittest.skipUnless(os.name == 'nt', 'Windows checked-handle deletion')
    def test_final_writer_lock_retains_all_without_failing_publication(self):
        candidate = self.build()
        original = cleaning.run
        def final_in_use(work, data):
            with self.output.open('r+b'):
                return original(work, data)
        with patch.object(cleaning, 'run', side_effect=final_in_use):
            result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual('final_unavailable', result['cleanup']['status'])
        self.assertEqual(1, result['cleanup']['retainedCount'])
        self.assertTrue(candidate.is_file())
        self.assertTrue(self.output.is_file())
        retry = delivery.cleanup(self.state, self.work)
        self.assertEqual(1, retry['cleanup']['deletedCount'])

    def test_final_change_before_pin_is_rechecked_and_retains_all(self):
        candidate = self.build()
        original = cleaning.run
        def changed(work, data):
            self.output.write_text('user edit before final pin', encoding='utf-8')
            return original(work, data)
        with patch.object(cleaning, 'run', side_effect=changed):
            result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual('final_unavailable', result['cleanup']['status'])
        self.assertTrue(candidate.is_file())
        self.assertEqual('user edit before final pin', self.output.read_text(encoding='utf-8'))

    def test_concurrent_publish_and_cleanup_are_idempotent(self):
        for _ in range(3):
            self.build()
        with patch.object(cleaning, 'after_publish', return_value={}):
            self.assertTrue(delivery.publish(self.state, self.work)['ok'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: delivery.cleanup(self.state,self.work) if n % 2
                                    else delivery.publish(self.state,self.work), range(4)))
        self.assertTrue(all(r['ok'] for r in results), results)
        self.assertEqual(3, sum(r['cleanup']['deletedCount'] for r in results))
        self.assertTrue(self.output.is_file())

    def test_missing_owned_file_count_is_not_a_cleanup_error(self):
        old = self.build()
        old.unlink()
        self.build()
        result = delivery.publish(self.state, self.work)
        self.assertTrue(result['ok'], result)
        self.assertEqual(1, result['cleanup']['missingCount'])
        self.assertEqual(1, result['cleanup']['deletedCount'])
        self.assertEqual(0, result['cleanup']['failedCount'])


if __name__ == '__main__':
    unittest.main()
