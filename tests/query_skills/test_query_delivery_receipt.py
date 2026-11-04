"""CSV delivery evidence comes from its writer, not another model/tool round."""
from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import cli, core
from query_core.store import Store, atomic_json


class QueryDeliveryReceiptTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-delivery-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'state', demo=True)

    def result(self, rows, columns=('name', 'value'), *, complete=True):
        result_id = uuid.uuid4().hex
        folder = self.store.root / 'results' / result_id
        folder.mkdir(parents=True)
        data = folder / 'data.jsonl'
        content = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
        data.write_bytes(content)
        metadata = {
            'ok': True, 'resultId': result_id, 'sourceName': '실습 DB', 'queryName': '자료',
            'executedAt': '2026-11-04T06:50:09+00:00', 'status': 'complete' if complete else 'partial',
            'complete': complete, 'savedRows': len(rows), 'columns': list(columns),
            'columnCount': len(columns), 'dataFile': str(data), 'dataAvailable': True,
            'dataSha256': hashlib.sha256(content).hexdigest(), 'dataRowsReturned': 0,
        }
        atomic_json(folder / 'metadata.json', metadata)
        return metadata

    def test_multiline_cells_are_logical_rows_and_source_is_read_once(self):
        source = self.result([['첫 줄\n다음 줄', '00123'], ['=SUM(A1:A2)', '항목,값']])
        original_open = Path.open
        reads = []
        def observe(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get('mode', 'r')
            if str(path) == source['dataFile']:
                reads.append(mode)
            if path.suffix == '.csv':
                self.assertNotIn('r', mode, 'CSV must not be read back for bookkeeping')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', observe):
            result = core.deliver_csv(self.store, core.receipt(source), self.root / 'outputs')
        self.assertEqual(['rb'], reads)
        self.assertEqual('complete', result['exportStatus'])
        self.assertEqual('verified', result['deliveryVerification'])
        self.assertEqual('csv-file-only', result['verificationScope'])
        self.assertEqual(2, result['exportedRows'])
        self.assertEqual(Path(result['outputFile']).stat().st_size, result['outputBytes'])
        with Path(result['outputFile']).open(encoding='utf-8-sig', newline='') as data:
            rows = list(csv.reader(data))
        self.assertEqual([['name', 'value'], ['첫 줄\n다음 줄', '00123'], ["'=SUM(A1:A2)", '항목,값']], rows)
        self.assertEqual(0, result['dataRowsReturned'])

    def test_partial_query_delivery_never_becomes_complete(self):
        source = self.result([['한 행', 10]], complete=False)
        result = core.deliver_csv(self.store, core.receipt(source), self.root / 'outputs')
        self.assertEqual('partial', result['status'])
        self.assertFalse(result['complete'])
        self.assertEqual('verified', result['deliveryVerification'])
        self.assertIn('_일부.csv', result['outputFile'])

    def test_empty_complete_query_has_verified_header_only_csv(self):
        source = self.result([])
        result = core.export_csv(self.store, source['resultId'], self.root / 'empty.csv')
        self.assertEqual(0, result['exportedRows'])
        self.assertTrue(result['complete'])
        self.assertGreater(result['outputBytes'], 0)
        self.assertEqual('verified', result['deliveryVerification'])

    def test_changed_source_and_wrong_row_or_column_count_fail_without_final_file(self):
        for replacement in (b'["changed", 1]\n', b'["original", 1]\n["extra", 2]\n', b'["short"]\n'):
            with self.subTest(replacement=replacement):
                source = self.result([['original', 1]])
                Path(source['dataFile']).write_bytes(replacement)
                output = self.root / (source['resultId'] + '.csv')
                with self.assertRaises(ValueError):
                    core.export_csv(self.store, source['resultId'], output)
                self.assertFalse(output.exists())
                self.assertTrue(Path(source['dataFile']).exists())

    def test_existing_user_csv_is_preserved(self):
        source = self.result([['original', 1]])
        output = self.root / 'user.csv'
        output.write_bytes(b'USER CONTENT')
        with self.assertRaises(FileExistsError):
            core.export_csv(self.store, source['resultId'], output)
        self.assertEqual(b'USER CONTENT', output.read_bytes())

    def test_writer_failure_cleans_only_new_output_and_preserves_query_result(self):
        source = self.result([['original', 1]])
        writer_factory = csv.writer
        class BrokenWriter:
            def __init__(self, target):
                self.target = writer_factory(target)
                self.count = 0
            def writerow(self, row):
                self.target.writerow(row)
                self.count += 1
                if self.count == 2:
                    raise OSError('synthetic disk write failure')
        with patch('query_core.core.csv.writer', BrokenWriter):
            result = core.deliver_csv(self.store, core.receipt(source), self.root / 'outputs')
        self.assertEqual('failed', result['exportStatus'])
        self.assertNotIn('deliveryVerification', result)
        self.assertEqual([], list((self.root / 'outputs').iterdir()))
        self.assertTrue(Path(source['dataFile']).exists())

    def test_real_cli_returns_delivery_receipt_in_single_execute(self):
        core.demo_init(self.store)
        text = io.StringIO()
        with redirect_stdout(text):
            code = cli.main('demo', ['--state-root', str(self.store.root), 'execute', '--id', '1',
                '--param', 'start_date=2026-10-01', '--param', 'end_date=2026-11-01',
                '--param', 'process=WB', '--output-dir', str(self.root / 'outputs')])
        result = json.loads(text.getvalue())
        self.assertEqual(0, code)
        self.assertEqual('verified', result['deliveryVerification'])
        self.assertEqual(result['savedRows'], result['exportedRows'])
        self.assertGreater(result['outputBytes'], 0)
        self.assertNotIn('rows', result)


if __name__ == '__main__':
    unittest.main()
