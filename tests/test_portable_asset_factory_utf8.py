"""Windows CLI output must survive Claude's UTF-8 tool decoding."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'standalone-skills' / 'asset-factory' / 'scripts'


@unittest.skipUnless(os.name == 'nt', 'Windows stdout encoding regression')
class PortableAssetFactoryUtf8Tests(unittest.TestCase):
    def test_success_and_existing_destination_failure_are_utf8(self):
        base = ROOT / '.smoke' / 'asset-factory-utf8'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            folder = Path(tmp)
            body = folder / '본문.txt'
            body.write_text('가상 자료를 정리합니다.', encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='cp949')
            cases = [
                ('author_skill.py', ['--destination', str(folder/'한글-스킬'),
                                     '--name', 'sample-skill', '--description', '가상 문서',
                                     '--body', str(body)]),
                ('create_project.py', ['--destination', str(folder/'한글-MCP')]),
            ]
            for script, args in cases:
                cmd = [sys.executable, '-B', str(SCRIPTS / script), *args]
                created = subprocess.run(cmd, capture_output=True, env=env, timeout=20)
                self.assertEqual(0, created.returncode, created.stderr)
                self.assertEqual('created', json.loads(created.stdout.decode('utf-8'))['status'])
                refused = subprocess.run(cmd, capture_output=True, env=env, timeout=20)
                self.assertEqual(1, refused.returncode, refused.stderr)
                payload = json.loads(refused.stdout.decode('utf-8'))
                self.assertEqual('failed', payload['status'])
                expected = '기존 폴더/파일은 덮어쓰지 않습니다' if script == 'create_project.py' else '같은 폴더가 있습니다'
                self.assertIn(expected, payload['error'])
            self.assertIn('가상 자료', (folder/'한글-스킬'/'SKILL.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
