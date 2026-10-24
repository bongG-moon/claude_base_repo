"""Imported MCP retention and offline install checks; no database or profile use."""
import importlib.util
import json
import os
from datetime import timedelta
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('external_export', ROOT / 'scripts/build-skill-packages.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class ExternalPackageTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.smoke/platform-skills'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        registry = ROOT / 'scripts/platform_skills/external-packages.json'
        self.config = json.loads(registry.read_bytes())
        self.item = self.config['packages'][0]
        (self.root / 'scripts/platform_skills').mkdir(parents=True)
        (self.root / 'skills_zip').mkdir()
        self.registry = self.root / 'scripts/platform_skills/external-packages.json'
        self.registry.write_bytes(registry.read_bytes())
        self.archive = self.root / 'skills_zip' / self.item['file']
        shutil.copyfile(ROOT / 'skills_zip' / self.item['file'], self.archive)

    def load(self):
        return export.external_packages(self.root, export.DEFAULT_STANDARD)

    def test_import_preserves_bytes_and_manifest_description(self):
        rows, files = self.load()
        self.assertEqual(files[self.item['file']], self.archive.read_bytes())
        self.assertEqual(rows[0]['type'], 'MCP/Tool')
        self.assertEqual(rows[0]['packageId'], self.item['packageId'])
        with ZipFile(self.archive) as z:
            self.assertEqual(rows[0]['description'], json.loads(z.read('ai-square.json'))['desc'])
            self.assertNotIn('.env', z.namelist())
            self.assertNotIn('oracle_connections.toml', z.namelist())
        catalog = json.loads((ROOT / 'skills_zip/catalog.json').read_bytes())
        self.assertIn(rows[0], catalog['packages'])

    def test_missing_or_changed_source_fails_instead_of_silent_removal(self):
        self.archive.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '해시'):
            self.load()
        self.archive.unlink()
        with self.assertRaises(FileNotFoundError):
            self.load()

    def test_duplicate_and_unsafe_registry_rejected(self):
        self.config['packages'].append(dict(self.item))
        self.registry.write_text(json.dumps(self.config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '중복'):
            self.load()
        self.item['file'] = '../outside.zip'
        self.registry.write_text(json.dumps(self.config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '파일명'):
            self.load()

    def test_wrong_identity_rejected(self):
        self.item['packageId'] = 'another-mcp'
        self.registry.write_text(json.dumps(self.config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'ID'):
            self.load()

    def test_offline_project_install_reinstall_preserves_config(self):
        self.load()  # Validate ZIP paths with the platform contract before extraction.
        package = self.root / 'package'
        with ZipFile(self.archive) as z:
            z.extractall(package)
        project = self.root / '프로젝트 with spaces'; project.mkdir()
        command = [sys.executable, '-B', '-X', 'utf8', str(package / 'install.py'),
                   '--scope', 'project', '--project-dir', str(project), '--skip-dependencies']
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = project / '.manufacturing-oracle-mcp'
        paths = [installed / 'config/.env', installed / 'config/oracle_connections.toml']
        for path in paths:
            with path.open('a', encoding='utf-8') as stream:
                stream.write('\n# synthetic user edit preserved\n')
        before = [p.read_bytes() for p in paths]
        again = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertFalse((project / '.mcp.json').exists())
        # Real stdio handshake with empty example settings; never query a database.
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        entry = json.loads((installed / 'claude-mcp.json').read_bytes())['mcpServers']['manufacturing-oracle']
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('MONGODB_', 'ORACLE_', 'RESULT_', 'METADATA_', 'PYTHONPATH'))}
        env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')

        async def scenario():
            params = StdioServerParameters(command=entry['command'], args=entry['args'], env=env)
            with (self.root / 'stdio.log').open('w', encoding='utf-8') as log, anyio.fail_after(40):
                async with stdio_client(params, errlog=log) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.serverInfo.name, 'manufacturing-oracle')
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        self.assertEqual(names, {'configuration_status', 'search_metadata', 'get_metadata',
                                                'check_oracle_connection', 'query_dataset', 'read_result'})
                        status = await session.call_tool('configuration_status', {})
                        self.assertFalse(status.isError)
                        self.assertFalse(status.structuredContent['data']['configured'])
        anyio.run(scenario)


if __name__ == '__main__':
    unittest.main()
