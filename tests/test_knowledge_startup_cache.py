from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import knowledge
from company_agent.frontmatter import dump_frontmatter


class KnowledgeStartupCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'company'
        self.base.mkdir()
        self.state = self.root / 'state'
        self.index = self.state / 'knowledge/generated-index'
        self.cache = self.index / 'startup-cache.json'
        self.source = self.base / 'terms/example.md'
        self.write(self.source, 'term.example')
        (self.base / 'pack.json').write_text('{"version":"1"}', encoding='utf-8')

    def write(self, path, identifier, body='Example source definition.'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_frontmatter({'id': identifier, 'kind': 'term', 'title': identifier,
                                         'owner': 'team', 'status': 'active'}, body), encoding='utf-8')

    def run_start(self, base=None):
        return knowledge.reconcile_overlays(self.state, base or self.base, apply_safe=True)

    def catalog(self):
        return json.loads((self.index / 'catalog.json').read_text(encoding='utf-8'))

    def test_unchanged_sources_are_read_once_without_parsing_rebuild_or_writes(self):
        first = self.run_start()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.index.iterdir()}
        reads = []
        real = Path.read_text
        def read(path, *args, **kwargs):
            if path.suffix == '.md':
                reads.append(path)
            return real(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read), \
                patch.object(knowledge, 'parse_frontmatter_text', side_effect=AssertionError('parsed unchanged source')), \
                patch.object(knowledge, 'build_index', side_effect=AssertionError('rebuilt unchanged index')), \
                patch('company_agent.paths.atomic_write_text', side_effect=AssertionError('wrote unchanged index')):
            self.assertEqual(first, self.run_start())
        self.assertEqual([self.source], reads)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.index.iterdir()})

    def test_cold_and_changed_rebuild_reuse_source_reads(self):
        for change in (False, True):
            if change:
                self.write(self.source, 'term.example', 'Changed definition.')
            reads = []
            real = Path.read_text
            def read(path, *args, **kwargs):
                if path.suffix == '.md':
                    reads.append(path)
                return real(path, *args, **kwargs)
            with patch.object(Path, 'read_text', read), patch.object(knowledge, 'build_index', wraps=knowledge.build_index) as built:
                self.assertEqual([], self.run_start()['indexIssues'])
            self.assertEqual([self.source], reads)
            self.assertEqual(1, built.call_count)

    def test_content_change_with_same_size_and_restored_mtime_invalidates(self):
        self.run_start()
        stamp = self.source.stat()
        original = self.source.read_text(encoding='utf-8')
        self.source.write_text(original.replace('Example source', 'Changed source'), encoding='utf-8')
        os.utime(self.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.run_start()
        self.assertIn('Changed source', self.catalog()['entries'][0]['searchText'])

    def test_add_delete_and_metadata_change_invalidate(self):
        self.run_start()
        other = self.base / 'extra.md'
        self.write(other, 'term.other')
        self.run_start()
        self.assertEqual(2, len(self.catalog()['entries']))
        self.source.unlink()
        self.run_start()
        self.assertEqual(['term.other'], [x['id'] for x in self.catalog()['entries']])
        other.write_text(other.read_text(encoding='utf-8').replace('"active"', '"draft"'), encoding='utf-8')
        self.run_start()
        self.assertEqual([], self.catalog()['entries'])

    def test_missing_or_tampered_generated_file_forces_rebuild(self):
        for name in ('catalog.json', 'catalog.tsv', 'INDEX.md', 'manifest.json'):
            for action in ('remove', 'tamper'):
                self.run_start()
                path = self.index / name
                if action == 'remove':
                    path.unlink()
                else:
                    path.write_text('tampered generated file', encoding='utf-8')
                with patch.object(knowledge, 'build_index', wraps=knowledge.build_index) as built:
                    self.assertEqual([], self.run_start()['indexIssues'])
                self.assertEqual(1, built.call_count, (name, action))
                self.assertEqual('term.example', self.catalog()['entries'][0]['id'])

    def test_missing_malformed_oversized_or_wrong_schema_cache_falls_back(self):
        for content in (None, '{broken', '[]', '{}', 'x' * 1_048_577):
            self.run_start()
            if content is None:
                self.cache.unlink()
            else:
                self.cache.write_text(content, encoding='utf-8')
            with patch.object(knowledge, 'build_index', wraps=knowledge.build_index) as built:
                self.run_start()
            self.assertEqual(1, built.call_count)

    def test_missing_report_and_malformed_report_cache_force_rebuild(self):
        self.run_start()
        (self.state / 'knowledge/conflicts/report.json').unlink()
        with patch.object(knowledge, 'build_index', wraps=knowledge.build_index) as built:
            self.run_start()
        self.assertEqual(1, built.call_count)
        cache = json.loads(self.cache.read_text(encoding='utf-8'))
        cache['report'] = {'unexpected': True}
        self.cache.write_text(json.dumps(cache), encoding='utf-8')
        with patch.object(knowledge, 'build_index', wraps=knowledge.build_index) as built:
            self.run_start()
        self.assertEqual(1, built.call_count)

    def prepare_rebase(self):
        self.write(self.source, 'term.example')
        overlay = knowledge.upsert_personal({'id': 'personal.extend.example', 'title': 'Extra detail',
                                             'mode': 'extend', 'extends': 'term.example', 'body': 'Extra definition.'},
                                            self.state, self.base)
        self.run_start()
        raw = self.source.read_text(encoding='utf-8')
        self.source.write_text(raw.replace('owner: "team"', 'owner: "new-team"'), encoding='utf-8')
        return overlay

    def test_rebased_overlay_uses_new_hash_without_replaying_the_action(self):
        overlay = self.prepare_rebase()
        reads = []
        real_read = Path.read_text
        def read(path, *args, **kwargs):
            if path.suffix == '.md':
                reads.append(path)
            return real_read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            report = self.run_start()
        self.assertCountEqual([self.source, overlay, overlay], reads)
        self.assertEqual(['personal.extend.example'], report['rebased'])
        self.assertEqual(knowledge.text_sha256(overlay.read_text(encoding='utf-8')),
                         self.catalog()['entries'][0]['overlays'][0]['content_hash'])
        self.assertEqual([], self.run_start()['rebased'])
        reads.clear()
        with patch.object(Path, 'read_text', read), \
                patch.object(knowledge, 'build_index', side_effect=AssertionError('unchanged rebase rebuilt')):
            self.assertEqual([], self.run_start()['rebased'])
        self.assertCountEqual([self.source, overlay], reads)

    def test_overlay_replaced_after_rebase_does_not_publish_or_cache_stale_index(self):
        overlay = self.prepare_rebase()
        before = {p.name: p.read_bytes() for p in self.index.iterdir()}
        real_write = knowledge.atomic_write_text
        replaced = False
        def write(path, text, *args, **kwargs):
            nonlocal replaced
            real_write(path, text, *args, **kwargs)
            if path == overlay and not replaced:
                replaced = True
                real_write(path, text.replace('Extra definition.', 'Concurrent definition.'))
        with patch.object(knowledge, 'atomic_write_text', side_effect=write):
            report = self.run_start()
        self.assertTrue(replaced)
        self.assertIn('source_changed', [x['code'] for x in report['indexIssues']])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.index.iterdir()})
        self.assertIn('Concurrent definition.', overlay.read_text(encoding='utf-8'))
        self.assertEqual([], self.run_start()['indexIssues'])
        entry = self.catalog()['entries'][0]
        self.assertIn('Concurrent definition.', entry['searchText'])
        self.assertEqual(knowledge.text_sha256(overlay.read_text(encoding='utf-8')),
                         entry['overlays'][0]['content_hash'])

    def test_overlay_replaced_during_rebase_readback_does_not_publish_stale_index(self):
        overlay = self.prepare_rebase()
        before = {p.name: p.read_bytes() for p in self.index.iterdir()}
        real_write, real_read = knowledge.atomic_write_text, Path.read_text
        written = replaced = False
        def write(path, text, *args, **kwargs):
            nonlocal written
            real_write(path, text, *args, **kwargs)
            if path == overlay:
                written = True
        def read(path, *args, **kwargs):
            nonlocal replaced
            text = real_read(path, *args, **kwargs)
            if path == overlay and written and not replaced:
                replaced = True
                real_write(path, text.replace('Extra definition.', 'Concurrent definition.'))
            return text
        with patch.object(knowledge, 'atomic_write_text', side_effect=write), \
                patch.object(Path, 'read_text', read):
            report = self.run_start()
        self.assertTrue(replaced)
        self.assertIn('source_changed', [x['code'] for x in report['indexIssues']])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.index.iterdir()})
        self.assertEqual([], self.run_start()['indexIssues'])
        self.assertIn('Concurrent definition.', self.catalog()['entries'][0]['searchText'])

    def test_overlay_unavailable_after_rebase_reports_source_changed(self):
        for failure in ('deleted', 'permission', 'decode'):
            with self.subTest(failure=failure):
                overlay = self.prepare_rebase()
                before = {p.name: p.read_bytes() for p in self.index.iterdir()}
                real_write, real_read = knowledge.atomic_write_text, Path.read_text
                written = False
                def write(path, text, *args, **kwargs):
                    nonlocal written
                    real_write(path, text, *args, **kwargs)
                    if path == overlay:
                        written = True
                        if failure == 'deleted':
                            path.unlink()
                def read(path, *args, **kwargs):
                    if path == overlay and written:
                        if failure == 'permission':
                            raise PermissionError('Concurrent access blocked readback')
                        if failure == 'decode':
                            raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'Invalid source bytes')
                    return real_read(path, *args, **kwargs)
                with patch.object(knowledge, 'atomic_write_text', side_effect=write), \
                        patch.object(Path, 'read_text', read):
                    report = self.run_start()
                self.assertTrue(written)
                self.assertIn('source_changed', [x['code'] for x in report['indexIssues']])
                self.assertEqual(before, {p.name: p.read_bytes() for p in self.index.iterdir()})
                self.assertEqual([], self.run_start()['indexIssues'])
                if failure == 'deleted':
                    self.assertEqual([], self.catalog()['entries'][0]['overlays'])

    def test_pack_version_and_base_root_changes_invalidate(self):
        self.run_start()
        (self.base / 'pack.json').write_text('{"version":"2"}', encoding='utf-8')
        self.run_start()
        self.assertEqual('2', self.catalog()['corporatePackVersion'])
        other = self.root / 'replacement-company'
        self.write(other / 'term.md', 'term.replacement')
        self.run_start(other)
        self.assertEqual(['term.replacement'], [x['id'] for x in self.catalog()['entries']])
        self.assertIn(str(other), self.catalog()['entries'][0]['path'])

    def test_excluded_trees_are_not_traversed(self):
        excluded = self.base / 'versions'
        self.write(excluded / 'old/deep.md', 'term.history')
        visited = []
        real = os.scandir
        def scan(path):
            visited.append(Path(path))
            self.assertFalse(Path(path).is_relative_to(excluded))
            return real(path)
        with patch('company_agent.knowledge_cache.os.scandir', side_effect=scan):
            self.run_start()
        self.assertNotIn(excluded, visited)
        self.assertEqual(['term.example'], [x['id'] for x in self.catalog()['entries']])

    def test_linked_markdown_is_rejected_before_read_even_after_cache_hit(self):
        self.run_start()
        real_stat, real_read = Path.lstat, Path.read_text
        def linked(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if path == self.source:
                return type('LinkStat', (), {'st_mode': stat.S_IFLNK, 'st_file_attributes': 0})()
            return info
        def read(path, *args, **kwargs):
            self.assertNotEqual(self.source, path)
            return real_read(path, *args, **kwargs)
        with patch.object(Path, 'lstat', linked), patch.object(Path, 'read_text', read):
            report = self.run_start()
        self.assertTrue(report['indexIssues'])

    def test_source_change_during_parse_does_not_publish_or_cache_stale_index(self):
        self.run_start()
        before = (self.index / 'catalog.json').read_bytes()
        self.write(self.source, 'term.example', 'First edit.')
        real = knowledge.parse_frontmatter_text
        changed = False
        def parse(*args, **kwargs):
            nonlocal changed
            result = real(*args, **kwargs)
            if not changed:
                changed = True
                self.write(self.source, 'term.example', 'Concurrent edit.')
            return result
        with patch.object(knowledge, 'parse_frontmatter_text', side_effect=parse):
            report = self.run_start()
        self.assertIn('source_changed', [x['code'] for x in report['indexIssues']])
        self.assertEqual(before, (self.index / 'catalog.json').read_bytes())
        self.run_start()
        self.assertIn('Concurrent edit', self.catalog()['entries'][0]['searchText'])

    def test_new_markdown_during_parse_does_not_publish_or_cache_stale_index(self):
        for relative in ('added.md', 'new-directory/added.md'):
            with self.subTest(relative=relative):
                self.run_start()
                before = (self.index / 'catalog.json').read_bytes()
                self.write(self.source, 'term.example', f'First edit before {relative}.')
                real = knowledge.parse_frontmatter_text
                changed = False
                def parse(*args, **kwargs):
                    nonlocal changed
                    result = real(*args, **kwargs)
                    if not changed:
                        changed = True
                        self.write(self.base / relative, 'term.concurrent')
                    return result
                with patch.object(knowledge, 'parse_frontmatter_text', side_effect=parse):
                    report = self.run_start()
                self.assertIn('source_changed', [x['code'] for x in report['indexIssues']])
                self.assertEqual(before, (self.index / 'catalog.json').read_bytes())
                self.run_start()
                self.assertIn('term.concurrent', [x['id'] for x in self.catalog()['entries']])
                (self.base / relative).unlink()

    def test_cache_write_failure_keeps_successful_index(self):
        with patch('company_agent.knowledge_cache.atomic_write_json', side_effect=PermissionError):
            self.assertEqual([], self.run_start()['indexIssues'])
        self.assertEqual('term.example', self.catalog()['entries'][0]['id'])

    def test_another_base_publish_cannot_be_cached_under_this_source_revision(self):
        other = self.root / 'other-company'
        self.write(other / 'other.md', 'term.other')
        original = knowledge.build_index
        def overlapping(*args, **kwargs):
            result = original(*args, **kwargs)
            original(other, self.state / 'knowledge', self.index)
            return result
        with patch.object(knowledge, 'build_index', side_effect=overlapping):
            self.run_start()
        self.assertFalse(self.cache.exists())
        self.run_start()
        self.assertEqual(['term.example'], [x['id'] for x in self.catalog()['entries']])


if __name__ == '__main__':
    unittest.main()
