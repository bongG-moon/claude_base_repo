"""Windows Claude shell receives Korean JSON as UTF-8, independently of locale."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32', 'Windows code-page behavior')
class HtmlCliUtf8Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / 'html-report'
        shutil.copytree(ROOT / 'standalone-skills/html-report', self.skill)
        metadata = json.loads((ROOT / 'scripts/platform_skills/catalog-metadata.json').read_text(encoding='utf-8-sig'))
        runtime = self.skill / 'scripts/visual_engine'
        runtime.mkdir(parents=True, exist_ok=True)
        for name in metadata['html-report']['packaging']['runtimeModules']:
            shutil.copyfile(ROOT / 'company-agent-plugin/scripts/company_agent' / name, runtime / name)
        self.script = self.skill / 'scripts/report.py'
        self.source = self.root / 'reference.html'
        self.source.write_text('<html><body>가상 자료</body></html>', encoding='utf-8')
        self.env = dict(os.environ)
        self.env.pop('PYTHONUTF8', None)
        self.env['PYTHONIOENCODING'] = 'cp949'

    def check_result(self, data):
        parsed = json.loads(data.decode('utf-8'))
        self.assertTrue(parsed['ok'], parsed)
        self.assertIn('첨부 양식', ' '.join(parsed['reference']['warnings']))

    def test_native_process_writes_utf8_even_with_legacy_environment(self):
        run = subprocess.run([sys.executable, str(self.script), 'reference', '--file', str(self.source)],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(0, run.returncode, run.stderr)
        self.check_result(run.stdout)

    def test_powershell_pipeline_receives_korean_json(self):
        ps = shutil.which('powershell.exe')
        if not ps:
            self.skipTest('Windows PowerShell unavailable')
        for path in (sys.executable, str(self.script), str(self.source)):
            self.assertNotIn("'", path)
        expression = f"& '{sys.executable}' '{self.script}' reference --file '{self.source}' | ForEach-Object {{ $_ }}"
        run = subprocess.run([ps, '-NoLogo', '-NoProfile', '-Command', expression],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(0, run.returncode, run.stderr)
        self.check_result(run.stdout)

    def test_bash_receives_korean_json(self):
        git_bash = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Git/bin/bash.exe'
        bash = str(git_bash) if git_bash.is_file() else shutil.which('bash.exe')
        if not bash:
            self.skipTest('Bash unavailable')
        args = [Path(sys.executable).as_posix(), self.script.as_posix(), 'reference', '--file', self.source.as_posix()]
        run = subprocess.run([bash, '-c', shlex.join(args)], env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=30)
        if b'NtCreateDirectoryObject' in run.stderr and b'0xC0000022' in run.stderr:
            self.skipTest('Git Bash system objects are blocked by this sandbox')
        self.assertEqual(0, run.returncode, run.stderr)
        self.check_result(run.stdout)


if __name__ == '__main__':
    unittest.main()
