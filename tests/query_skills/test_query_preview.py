"""미리보기는 명시한 상위 일부만 반환하고 원본을 변경하지 않습니다."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core.preview import preview_result
from query_core.store import Store, atomic_json


class QueryPreviewTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.smoke/query-preview-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name), demo=True)

    def fixture(self, rows, columns=None, **changes):
        columns = columns or ['id', 'label']
        result_id = uuid.uuid4().hex
        folder = self.store.root / 'results' / result_id
        folder.mkdir(parents=True)
        raw = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
        data = folder / 'data.jsonl'
        data.write_bytes(raw)
        metadata = {'resultId': result_id, 'engine': 'demo', 'status': 'complete', 'complete': True,
                    'savedRows': len(rows), 'columns': columns, 'columnCount': len(columns),
                    'dataFile': str(data), 'dataBytes': len(raw), 'dataSha256': hashlib.sha256(raw).hexdigest(),
                    'executedAt': '2026-11-02T11:17:00+00:00'}
        metadata.update(changes)
        atomic_json(folder / 'metadata.json', metadata)
        return result_id, data

    def test_default_five_rows_and_selected_columns_only(self):
        result_id, data = self.fixture([[index, '값 ' + str(index)] for index in range(1000)])
        original = data.read_bytes()
        result = preview_result(self.store, 'demo', result_id, columns=['label'])
        self.assertEqual(result['columns'], ['label'])
        self.assertEqual(result['rows'], [['값 ' + str(index)] for index in range(5)])
        self.assertEqual(result['savedRows'], 1000)
        self.assertEqual(result['dataRowsReturned'], 5)
        self.assertTrue(result['previewTruncated'])
        self.assertEqual(result['source'], 'saved-result')
        self.assertEqual(data.read_bytes(), original)

    def test_zero_rows_are_empty_not_error(self):
        result_id, _ = self.fixture([])
        result = preview_result(self.store, 'demo', result_id)
        self.assertTrue(result['ok'])
        self.assertEqual(result['outcome'], 'empty')
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['dataRowsReturned'], 0)

    def test_requested_maximum_rows_and_character_budget(self):
        result_id, data = self.fixture([[index, '매우 긴 내용 ' * 500] for index in range(100)])
        original = data.read_bytes()
        result = preview_result(self.store, 'demo', result_id, rows=20)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 8000)
        self.assertLessEqual(len(result['rows']), 20)
        self.assertTrue(result['previewTruncated'])
        self.assertTrue(result['cellsTruncated'])
        self.assertEqual(data.read_bytes(), original)

    def test_wide_names_and_cells_stay_bounded_and_explain_truncation(self):
        columns = [str(i) + '열' * 250 for i in range(40)]
        result_id, _ = self.fixture([['값' * 1000] * 40], columns)
        result = preview_result(self.store, 'demo', result_id)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 8000)
        self.assertTrue(result['columnsTruncated'])
        self.assertTrue(result['cellsTruncated'])

    def test_failed_result_does_not_open_data_file(self):
        result_id, data = self.fixture([], status='failed', dataAvailable=False, errorDetails={'serverCode': 'ORA-00904'})
        data.unlink()
        result = preview_result(self.store, 'demo', result_id)
        self.assertFalse(result['ok'])
        self.assertEqual(result['outcome'], 'error')
        self.assertEqual(result['errorDetails']['serverCode'], 'ORA-00904')
        self.assertEqual(result['dataRowsReturned'], 0)

    def test_invalid_rows_columns_other_engine_and_changed_file_are_rejected(self):
        result_id, data = self.fixture([[1, '원본']])
        for count in (0, 21, True, -1):
            with self.subTest(count=count), self.assertRaises(ValueError):
                preview_result(self.store, 'demo', result_id, rows=count)
        for columns in ([], ['missing'], ['id', 'id'], 'id'):
            with self.subTest(columns=columns), self.assertRaises(ValueError):
                preview_result(self.store, 'demo', result_id, columns=columns)
        with self.assertRaises(ValueError):
            preview_result(self.store, 'oracle', result_id)
        data.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '변경'):
            preview_result(self.store, 'demo', result_id)

    def test_missing_data_and_arbitrary_metadata_path_are_not_followed(self):
        result_id, data = self.fixture([[1, '원본']], dataFile=str(self.store.root / 'catalog.sqlite3'))
        with self.assertRaisesRegex(ValueError, '위치'):
            preview_result(self.store, 'demo', result_id)


if __name__ == '__main__':
    unittest.main()
