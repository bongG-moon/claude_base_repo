"""Exact-scope memory receipts and reversible, optimistic-concurrency corrections."""
from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import cli
from company_agent.frontmatter import load_markdown
from company_agent.memory import MemoryConflict, search_memory, upsert_memory
from company_agent.memory_history import memory_history, restore_memory
from company_agent.resource_scope import selected_root


class MemoryReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='memory receipt 한글 ')
        self.base = Path(self.temp.name)
        self.root = self.base / 'state'
        self.project = self.base / 'A'
        self.other = self.base / 'B'
        self.project.mkdir(); self.other.mkdir()
        self.env = patch.dict(os.environ, {'COMPANY_AGENT_SCOPE': 'User', 'COMPANY_AGENT_CWD': str(self.project)})
        self.env.start()
        self.spec = {'id': 'memory.preference.report', 'title': '보고서 순서', 'body': '표 다음에 설명을 쓴다.'}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call(self, action, *args, scope='project', project=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(['memory', action, *args, '--state-root', str(self.root),
                             '--storage-scope', scope, '--project-root', str(project or self.project)])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def upsert(self, spec=None, **kwargs):
        file = self.base / 'memory-input.json'
        file.write_text(json.dumps(spec or self.spec, ensure_ascii=False), encoding='utf-8')
        return self.call('upsert', '--spec', str(file), **kwargs)

    def checked_update(self, receipt, body, **kwargs):
        file = self.base / 'memory-input.json'
        file.write_text(json.dumps({**self.spec, 'body': body}), encoding='utf-8')
        return self.call('upsert', '--spec', str(file), '--expected-revision', str(receipt['revision']),
                         '--expected-sha256', receipt['sha256'], **kwargs)

    def test_project_receipt_and_explicit_search_use_actual_scope_not_legacy_owner(self):
        code, saved = self.upsert()
        self.assertEqual(0, code)
        self.assertEqual(('project', '이 프로젝트', str(self.project)),
                         (saved['storageScope'], saved['scopeLabel'], saved['projectRoot']))
        self.assertEqual(self.spec['id'], saved['id'])
        self.assertEqual('persisted-content-verified', saved['verification']['status'])
        path = Path(saved['path'])
        raw = path.read_bytes()
        self.assertEqual('personal', load_markdown(path).metadata['scope'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), saved['sha256'])
        code, found = self.call('search', '보고서')
        self.assertEqual(0, code)
        self.assertEqual(saved['storageScope'], found['results'][0]['storageScope'])
        self.assertEqual(saved['sha256'], found['results'][0]['sha256'])
        self.assertEqual('이 프로젝트', found['results'][0]['scopeLabel'])
        self.assertEqual(raw, path.read_bytes())
        self.assertEqual([], self.call('search', '보고서', project=self.other)[1]['results'])

    def test_personal_receipt_has_no_project_scope_and_no_other_files_readback(self):
        with patch('company_agent.memory._read_memory_document', wraps=__import__(
                'company_agent.memory', fromlist=['_read_memory_document'])._read_memory_document) as read:
            code, saved = self.upsert(scope='personal')
        self.assertEqual(0, code)
        self.assertEqual(('personal', '개인 전체', None),
                         (saved['storageScope'], saved['scopeLabel'], saved['projectRoot']))
        self.assertTrue(all(str(call.args[0]) == saved['path'] for call in read.call_args_list))
        self.assertEqual('개인 전체', self.call('search', '', scope='personal')[1]['results'][0]['scopeLabel'])

    def test_changed_revision_hash_and_change_id_noop_are_truthful(self):
        _, first = self.upsert()
        raw = Path(first['path']).read_bytes()
        _, same = self.upsert()
        self.assertFalse(same['changed'])
        self.assertEqual(first['changeId'], same['changeId'])
        self.assertEqual(raw, Path(first['path']).read_bytes())
        code, updated = self.checked_update(first, '설명 다음에 표를 쓴다.')
        self.assertEqual(0, code)
        self.assertEqual(2, updated['revision'])
        self.assertTrue(updated['changed'])
        self.assertNotEqual(first['sha256'], updated['sha256'])

    def test_blind_update_requires_both_expected_values_and_preserves_file(self):
        _, first = self.upsert()
        raw = Path(first['path']).read_bytes()
        code, failed = self.upsert({**self.spec, 'body': '설명을 먼저 쓴다.'})
        self.assertEqual(1, code)
        self.assertEqual('memory_expected_revision_required', failed['code'])
        self.assertFalse(failed['changed'])
        self.assertEqual(raw, Path(first['path']).read_bytes())

    def test_stale_hash_detects_manual_edit_even_without_revision_bump(self):
        _, first = self.upsert()
        path = Path(first['path'])
        path.write_bytes(path.read_bytes() + '\n수동 교정'.encode('utf-8'))
        raw = path.read_bytes()
        code, failed = self.checked_update(first, '설명을 먼저 쓴다.')
        self.assertEqual(1, code)
        self.assertEqual('memory_revision_conflict', failed['code'])
        self.assertEqual(raw, path.read_bytes())

    def test_history_restore_creates_revision_and_preserves_previous_status(self):
        _, first = self.upsert({**self.spec, 'status': 'draft'})
        _, second = self.checked_update(first, '설명을 먼저 쓴다.')
        code, history = self.call('history', '--id', self.spec['id'])
        self.assertEqual(0, code)
        self.assertEqual('project', history['storageScope'])
        self.assertEqual(second['sha256'], history['current']['sha256'])
        self.assertEqual([1], [x['revision'] for x in history['versions']])
        code, restored = self.call('restore', '--id', self.spec['id'], '--revision', '1',
                                   '--expected-revision', '2', '--expected-sha256', second['sha256'])
        self.assertEqual(0, code)
        self.assertEqual(('restore', 1, 3, 'draft'),
                         (restored['operation'], restored['restoredFrom'], restored['revision'], restored['status']))
        document = load_markdown(Path(first['path']))
        self.assertEqual(self.spec['body'], document.body.strip())
        self.assertEqual('draft', document.metadata['status'])
        self.assertEqual([], search_memory(Path(first['path']).parents[2], ''))
        # Replaying exactly this already-complete restore creates no new version.
        code, replayed = self.call('restore', '--id', self.spec['id'], '--revision', '1',
                                   '--expected-revision', '2', '--expected-sha256', second['sha256'])
        self.assertEqual(0, code)
        self.assertFalse(replayed['changed'])
        self.assertEqual(3, replayed['revision'])

    def test_restore_preserves_newer_edit_and_cannot_change_other_scope(self):
        _, first = self.upsert()
        _, second = self.checked_update(first, '설명을 먼저 쓴다.')
        _, third = self.checked_update(second, '확인된 새 방식을 따른다.')
        code, failed = self.call('restore', '--id', self.spec['id'], '--revision', '1',
                                 '--expected-revision', '2', '--expected-sha256', second['sha256'])
        self.assertEqual(1, code)
        self.assertEqual('memory_revision_conflict', failed['code'])
        self.assertEqual(third['sha256'], hashlib.sha256(Path(third['path']).read_bytes()).hexdigest())
        code, failed = self.call('restore', '--id', self.spec['id'], '--revision', '1',
                                 '--expected-revision', '3', '--expected-sha256', third['sha256'], scope='personal')
        self.assertEqual(1, code)
        self.assertFalse((self.root / 'memory/items').exists())

    def test_history_is_bounded_and_restore_stops_if_scan_is_incomplete(self):
        first = upsert_memory(self.spec, self.root, receipt=True)
        second = upsert_memory({**self.spec, 'body': '설명 먼저'}, self.root, receipt=True)
        with patch('company_agent.memory_history.MAX_HISTORY_DIRECTORIES', 0):
            history = memory_history(self.root, self.spec['id'])
            self.assertTrue(history['truncated'])
            with self.assertRaisesRegex(ValueError, '완전히'):
                restore_memory(self.root, self.spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])
        self.assertNotEqual(first['sha256'], second['sha256'])

    def test_history_read_missing_target_does_not_create_store(self):
        with self.assertRaises(FileNotFoundError):
            memory_history(self.root, self.spec['id'])
        self.assertFalse(self.root.exists())

    def test_traversal_and_reparse_destinations_rejected(self):
        for identifier in ('../outside', 'x/y', 'x\\y', 'a' * 161):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                memory_history(self.root, identifier)
        outside = self.base / 'outside'
        outside.mkdir()
        self.root.mkdir()
        try:
            (self.root / 'memory').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symbolic link creation requires host privilege')
        with self.assertRaises(ValueError):
            upsert_memory(self.spec, self.root)
        self.assertEqual([], list(outside.iterdir()))

    def test_bom_and_crlf_hashes_are_exact(self):
        path = upsert_memory(self.spec, self.root)
        path.write_bytes(b'\xef\xbb\xbf' + path.read_bytes().replace(b'\n', b'\r\n'))
        found = search_memory(self.root, '')[0]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), found['sha256'])
        receipt = upsert_memory({**self.spec, 'body': '교정된 내용'}, self.root,
                                expected_revision=found['revision'], expected_sha256=found['sha256'], receipt=True)
        self.assertEqual(2, receipt['revision'])

    def test_ambiguous_or_tampered_snapshot_cannot_be_restored(self):
        upsert_memory(self.spec, self.root)
        second = upsert_memory({**self.spec, 'body': '교정'}, self.root, receipt=True)
        original = next((self.root / 'memory/versions').glob('*/*.md'))
        fake = self.root / 'memory/versions/20000101-000000-000000' / original.name
        fake.parent.mkdir()
        fake.write_text(original.read_text(encoding='utf-8').replace(self.spec['body'], '다른 내용'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '서로 다릅니다'):
            restore_memory(self.root, self.spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])

    def test_two_checked_updates_cannot_both_replace_the_same_revision(self):
        first = upsert_memory(self.spec, self.root, receipt=True)
        def update(body):
            try:
                return upsert_memory({**self.spec, 'body': body}, self.root, receipt=True,
                                     expected_revision=1, expected_sha256=first['sha256'], require_expected=True)
            except MemoryConflict as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, ['교정 A', '교정 B']))
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertIn('memory_revision_conflict', results)
        self.assertEqual(2, load_markdown(Path(first['path'])).metadata['revision'])

    def test_external_edit_while_snapshotting_is_not_overwritten(self):
        first = upsert_memory(self.spec, self.root, receipt=True)
        path = Path(first['path'])
        import shutil
        copy = shutil.copy2
        def edit_after_snapshot(source, target):
            result = copy(source, target)
            source.write_bytes(source.read_bytes() + '\n직접 수정'.encode('utf-8'))
            return result
        with patch('company_agent.memory.shutil.copy2', side_effect=edit_after_snapshot):
            with self.assertRaises(MemoryConflict):
                upsert_memory({**self.spec, 'body': '교정'}, self.root, expected_revision=1,
                              expected_sha256=first['sha256'], require_expected=True)
        self.assertIn('직접 수정', path.read_text(encoding='utf-8'))

    def test_snapshot_with_raw_sensitive_payload_cannot_be_restored(self):
        upsert_memory(self.spec, self.root)
        second = upsert_memory({**self.spec, 'body': '교정'}, self.root, receipt=True)
        original = next((self.root / 'memory/versions').glob('*/*.md'))
        original.write_text(original.read_text(encoding='utf-8').replace(self.spec['body'], 'password=do-not-restore'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '무결성'):
            restore_memory(self.root, self.spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])
        self.assertEqual(second['sha256'], hashlib.sha256(Path(second['path']).read_bytes()).hexdigest())

    def test_legacy_trailing_punctuation_id_can_update_and_restore_without_filename_collision(self):
        for suffix in ('.', '-'):
            with self.subTest(suffix=suffix):
                root = self.root / ('dot' if suffix == '.' else 'dash')
                spec = {**self.spec, 'id': self.spec['id'] + suffix}
                first = upsert_memory(spec, root, receipt=True)
                path = Path(first['path'])
                self.assertEqual('memory.preference.report.md', path.name)
                self.assertEqual(spec['id'], search_memory(root, '')[0]['id'])
                second = upsert_memory({**spec, 'body': '설명 먼저'}, root, receipt=True,
                                       expected_revision=1, expected_sha256=first['sha256'], require_expected=True)
                with self.assertRaisesRegex(ValueError, 'identity'):
                    upsert_memory(self.spec, root, receipt=True, expected_revision=2,
                                  expected_sha256=second['sha256'], require_expected=True)
                history = memory_history(root, spec['id'])
                self.assertEqual('hash-matched', history['versions'][0]['integrity'])
                restored = restore_memory(root, spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])
                self.assertEqual((3, 1, spec['id']), (restored['revision'], restored['restoredFrom'], restored['id']))
                self.assertEqual(self.spec['body'], load_markdown(path).body.strip())

    def test_single_plain_text_snapshot_tamper_fails_integrity_without_overwrite(self):
        upsert_memory(self.spec, self.root)
        second = upsert_memory({**self.spec, 'body': '교정'}, self.root, receipt=True)
        snapshot = next((self.root / 'memory/versions').glob('*/*.md'))
        snapshot.write_text(snapshot.read_text(encoding='utf-8').replace(self.spec['body'], '정상처럼 보이는 다른 내용'), encoding='utf-8')
        current = Path(second['path']).read_bytes()
        before = snapshot.read_bytes()
        history = memory_history(self.root, self.spec['id'])
        self.assertEqual('mismatch', history['versions'][0]['integrity'])
        self.assertFalse(history['versions'][0]['restoreAvailable'])
        with self.assertRaisesRegex(ValueError, '무결성'):
            restore_memory(self.root, self.spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])
        self.assertEqual(current, Path(second['path']).read_bytes())
        self.assertEqual(before, snapshot.read_bytes())

    def test_legacy_snapshot_without_integrity_is_shown_but_not_auto_restored(self):
        upsert_memory(self.spec, self.root)
        second = upsert_memory({**self.spec, 'body': '교정'}, self.root, receipt=True)
        snapshot = next((self.root / 'memory/versions').glob('*/*.md'))
        snapshot.with_suffix('.receipt.json').unlink()
        before = snapshot.read_bytes()
        history = memory_history(self.root, self.spec['id'])
        self.assertEqual('unverified-legacy', history['versions'][0]['integrity'])
        with self.assertRaisesRegex(ValueError, '직접 검토'):
            restore_memory(self.root, self.spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])
        self.assertEqual(before, snapshot.read_bytes())
        self.assertFalse(snapshot.with_suffix('.receipt.json').exists())

    def test_malformed_or_oversized_integrity_receipt_is_not_used(self):
        upsert_memory(self.spec, self.root)
        second = upsert_memory({**self.spec, 'body': '교정'}, self.root, receipt=True)
        snapshot = next((self.root / 'memory/versions').glob('*/*.md'))
        receipt = snapshot.with_suffix('.receipt.json')
        for raw in (b'{', b'x' * 2049, b'[]'):
            receipt.write_bytes(raw)
            with self.subTest(raw=raw[:5]):
                self.assertEqual('mismatch', memory_history(self.root, self.spec['id'])['versions'][0]['integrity'])
                with self.assertRaisesRegex(ValueError, '무결성'):
                    restore_memory(self.root, self.spec['id'], 1, expected_revision=2, expected_sha256=second['sha256'])

    def test_no_receipt_claims_unverified_write_was_unchanged(self):
        with patch('company_agent.memory.atomic_write_text'):
            # Simulate unsuccessful persistence at the exact output boundary.
            with self.assertRaises(FileNotFoundError):
                upsert_memory(self.spec, self.root, receipt=True)


if __name__ == '__main__':
    unittest.main()
