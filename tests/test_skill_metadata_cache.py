import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import skill_registry as registry
from company_agent.skill_metadata_cache import MAX_AGE_SECONDS


class SkillMetadataCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.claude = self.root / 'claude'
        self.cache = self.state / 'cache/skill-metadata-v1.json'
        self.skill = self.claude / 'skills/sample/SKILL.md'
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text('---\nname: sample\ndescription: 문서 읽기\n---\nPRIVATE BODY', encoding='utf-8')

    def scan(self, cached=True):
        reads = []
        original = registry._read
        def observe(path, maximum):
            if path.name == 'SKILL.md':
                reads.append(path)
            return original(path, maximum)
        with patch.object(registry, '_read', side_effect=observe):
            result = registry.inventory_skills(self.state, claude_root=self.claude, metadata_cache=cached)
        self.assertTrue(result['complete'], result['warnings'])
        return result, reads

    def test_default_inventory_remains_read_only_and_uncached(self):
        for _ in range(2):
            self.assertEqual(1, len(self.scan(False)[1]))
        self.assertFalse(self.state.exists())

    def test_unchanged_bodies_not_read_or_cache_rewritten(self):
        first, reads = self.scan()
        self.assertEqual(1, len(reads))
        before = self.cache.stat().st_mtime_ns
        again, reads = self.scan()
        self.assertEqual([], reads)
        self.assertEqual(first, again)
        self.assertEqual(before, self.cache.stat().st_mtime_ns)
        self.assertNotIn('PRIVATE BODY', self.cache.read_text(encoding='utf-8'))

    def test_edit_add_delete_and_manual_only_change_are_detected(self):
        original, _ = self.scan()
        self.skill.write_text('---\nname: sample\ndescription: 메일 읽기\ndisable-model-invocation: true\n---\nCHANGED', encoding='utf-8')
        edited, reads = self.scan()
        self.assertEqual([self.skill], reads)
        self.assertTrue(edited['skills'][0]['explicitOnly'])
        self.assertNotEqual(original['skills'][0]['sha256'], edited['skills'][0]['sha256'])
        extra = self.claude / 'skills/other/SKILL.md'
        extra.parent.mkdir()
        extra.write_text('---\nname: other\ndescription: 새 스킬\n---\n', encoding='utf-8')
        added, reads = self.scan()
        self.assertEqual([extra], reads)
        self.assertEqual(2, len(added['skills']))
        extra.unlink()
        removed, reads = self.scan()
        self.assertEqual([], reads)
        self.assertEqual(1, len(removed['skills']))
        self.assertEqual(1, len(json.loads(self.cache.read_text(encoding='utf-8'))['entries']))

    def test_periodic_refresh_does_not_trust_stat_forever(self):
        self.scan()
        with patch('company_agent.skill_metadata_cache.time.time', return_value=__import__('time').time() + MAX_AGE_SECONDS + 1):
            self.assertEqual(1, len(self.scan()[1]))

    def test_corrupt_oversized_and_bad_metadata_cache_falls_back(self):
        self.scan()
        valid = self.cache.read_text(encoding='utf-8')
        for content in ('[]', '{bad', 'x' * 2_097_153):
            self.cache.write_text(content, encoding='utf-8')
            self.assertEqual(1, len(self.scan()[1]))
        data = json.loads(valid)
        next(iter(data['entries'].values()))['metadata']['name'] = '../escape'
        self.cache.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(1, len(self.scan()[1]))

    def test_new_bytes_are_rehashed_even_with_restored_mtime(self):
        self.scan()
        stamp = self.skill.stat()
        self.skill.write_text(self.skill.read_text(encoding='utf-8') + '!', encoding='utf-8')
        os.utime(self.skill, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        result, reads = self.scan()
        self.assertEqual(1, len(reads))
        self.assertEqual(hashlib.sha256(self.skill.read_bytes()).hexdigest(), result['skills'][0]['sha256'])

    def test_cache_write_failure_does_not_block_inventory(self):
        with patch('company_agent.paths.atomic_write_text', side_effect=PermissionError):
            self.assertEqual(1, len(self.scan()[0]['skills']))

    def test_reparse_rejection_is_applied_on_cache_hits(self):
        self.scan()
        real = registry._no_reparse
        def reject(path):
            if path == self.skill:
                raise ValueError('reparse fixture')
            return real(path)
        with patch.object(registry, '_no_reparse', side_effect=reject):
            result = registry.inventory_skills(self.state, claude_root=self.claude, metadata_cache=True)
        self.assertFalse(result['complete'])
        self.assertEqual([], result['skills'])


if __name__ == '__main__':
    unittest.main()
