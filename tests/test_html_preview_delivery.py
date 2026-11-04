"""Reference previews must be reachable from real portable CLI responses."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import html_reference, business_artifacts


class HtmlPreviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / '원본 양식.html'
        self.reference.write_text('<html><style>body{color:#111;font-family:"Malgun Gothic"}</style>'
                                  '<body>private source<script>throw new Error("DO_NOT_EXECUTE")</script></body></html>',
                                  encoding='utf-8')

    def test_analysis_only_does_not_claim_preview_exists(self):
        result = html_reference.inspect_template(self.reference)
        self.assertTrue(result['ok'])
        self.assertFalse(result['previewCreated'])
        self.assertNotIn('previewLink', result)

    def test_open_failure_keeps_destination_and_confirmation_link(self):
        path = self.root / '미리 보기 #1.html'
        with patch.object(business_artifacts, 'open_local_preview', return_value={
            'browserOpened': False, 'previewOpenStatus': 'unavailable', 'previewMessage': '자동 열기 실패'}):
            result = html_reference.inspect_template(self.reference, path, open_preview=True)
        self.assertTrue(result['previewCreated'])
        self.assertEqual(str(path.resolve()), result['previewPath'])
        self.assertEqual(path.resolve().as_uri(), result['previewUrl'])
        self.assertIn(path.as_posix(), result['previewLink'])
        self.assertIn(str(path), result['previewMessage'])
        self.assertFalse(result['browserOpened'])
        pending = business_artifacts.html_choices({key: result[key] for key in ('htmlTemplate', 'templateReview')})
        self.assertEqual('template_confirm', pending['stage'])
        self.assertEqual(result['previewLink'], pending['previewLink'])

    def test_isolated_portable_cli_returns_real_preview_with_encoded_uri(self):
        skill = self.root / 'installed-skill'
        shutil.copytree(ROOT / 'standalone-skills/html-report', skill)
        catalog = json.loads((ROOT / 'scripts/platform_skills/catalog-metadata.json').read_text(encoding='utf-8'))
        for name in catalog['html-report']['packaging']['runtimeModules']:
            shutil.copyfile(ROOT / 'company-agent-plugin/scripts/company_agent' / name,
                            skill / 'scripts/visual_engine' / name)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CLAUDE', 'COMPANY', 'ANTHROPIC', 'PYTHONPATH'))}
        profile = self.root / 'unused-profile'
        env.update(CLAUDE_CONFIG_DIR=str(profile))
        # Relative output resolves against the user's work folder, not installation.
        output = '미리 보기 #1.html'
        proc = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', str(skill / 'scripts/report.py'),
                               'reference', '--file', str(self.reference), '--preview', output],
                              cwd=self.root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, proc.returncode, proc.stderr + proc.stdout)
        result = json.loads(proc.stdout)
        path = self.root / 'html-report/.work' / output
        self.assertTrue(result['previewCreated'])
        self.assertEqual(path.resolve().as_uri(), result['previewUrl'])
        self.assertIn('%23', result['previewUrl'])
        self.assertIn('previewLink', result['message'])
        self.assertTrue(path.is_file())
        self.assertFalse(profile.exists())
        text = path.read_text(encoding='utf-8')
        self.assertNotIn('DO_NOT_EXECUTE', text)
        self.assertNotIn('private source', text)


if __name__ == '__main__':
    unittest.main()
