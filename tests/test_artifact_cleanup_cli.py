"""End-to-end scoped cleanup through the installed CLI contract, synthetic files only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts/harness_cli.py'


class ArtifactCleanupCliTests(unittest.TestCase):
    def test_publish_cleanup_and_explicit_repeat_preserve_source_and_final(self):
        with tempfile.TemporaryDirectory(prefix='company-cleanup-cli-') as directory:
            root = Path(directory)
            state = root / '개인 상태'
            source = root / '기존 원본.txt'
            source.write_text('보존할 원본', encoding='utf-8')
            output = root / '최종 보고서.html'

            def run(*args):
                result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SCRIPT),
                    'business', *args, '--state-root', str(state)], capture_output=True,
                    text=True, encoding='utf-8', timeout=20)
                return result, json.loads(result.stdout)

            _, work = run('artifact-start', '--output', str(output))
            spec = Path(work['jobPath'])
            spec.write_text(json.dumps({'title': '가상 보고', 'style': 'minimal',
                'length': 'standard', 'mode': 'scroll',
                'sections': [{'title': '확인', 'body': '가상 수치 10건'}]}, ensure_ascii=False), encoding='utf-8')
            _, built = run('html', '--work', work['workFile'], '--spec', str(spec))
            self.assertTrue(built['ok'], built)
            expected = Path(built['outputPath']).read_bytes()
            # This extra file was not created by the builder. It must never be adopted.
            unknown = Path(built['outputPath']).parent / '사용자가 넣은 파일.txt'
            unknown.write_text('자동 삭제 금지', encoding='utf-8')
            _, before = run('artifact-cleanup', '--work', work['workFile'])
            self.assertFalse(before['ok'], before)
            self.assertTrue(Path(built['outputPath']).exists())
            process, published = run('artifact-publish', '--work', work['workFile'])
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertTrue(published['ok'], published)
            self.assertGreater(published['cleanup']['deletedCount'], 0)
            self.assertFalse(Path(built['outputPath']).exists())
            self.assertEqual(expected, output.read_bytes())
            stamp = output.stat().st_mtime_ns
            process, cleaned = run('artifact-cleanup', '--work', work['workFile'])
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertTrue(cleaned['ok'], cleaned)
            self.assertEqual(0, cleaned['cleanup']['deletedCount'])
            self.assertEqual('보존할 원본', source.read_text(encoding='utf-8'))
            self.assertEqual('자동 삭제 금지', unknown.read_text(encoding='utf-8'))
            self.assertTrue(spec.exists())  # A supplied specification is not implicitly owned.
            self.assertEqual(stamp, output.stat().st_mtime_ns)
            self.assertTrue(Path(work['workFile']).exists())


if __name__ == '__main__':
    unittest.main()
