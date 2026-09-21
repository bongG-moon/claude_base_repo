from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent.usage_diagnostics import analyze_usage
from company_agent.diagnostic_report import render_report, write_report


class UsageDiagnosticsTests(unittest.TestCase):
    def test_streaming_dedup_utf8_partial_and_no_sensitive_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '한글 세션.jsonl'
            def msg(identifier, offset=1):
                return {'type':'assistant', 'timestamp':'2026-09-18T00:00:00Z', 'message': {
                    'id':identifier, 'model':'HCP-Big-Latest', 'usage': {'input_tokens':100, 'output_tokens':5},
                    'content':[{'type':'text','text':'SECRET 회사 원문'}, {'type':'tool_use','id':identifier+'-read',
                    'name':'Read','input': {'file_path':'SECRET/private.txt','offset':offset,'limit':10}}]}}
            first = msg('one')
            path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in [first, first, msg('two'), msg('three',11)]), encoding='utf-8')
            before = path.read_bytes()
            result = analyze_usage([path, path])
            self.assertEqual(300, result['tokens']['input_tokens'])
            self.assertIsNone(result['tokens']['cache_read_input_tokens'])
            self.assertIsNone(result['cost'])
            self.assertEqual(3, result['toolCalls']['Read'])
            self.assertEqual('HCP-Big-Latest', result['byModel'][0]['model'])
            self.assertEqual(300, result['byModel'][0]['tokens']['input_tokens'])
            self.assertEqual(1, result['sameRangeReads'])
            self.assertEqual('partial', result['status'])
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertEqual(before, path.read_bytes())

    def test_no_log_means_no_reads_not_zero_usage(self):
        with patch.object(Path, 'open', side_effect=AssertionError('no file access')):
            result = analyze_usage([])
        self.assertEqual('not-requested', result['status'])
        self.assertIsNone(result['tokens']['input_tokens'])
        self.assertIsNone(result['sameRangeReads'])

    def test_limits_malformed_and_missing_ids_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.jsonl'
            path.write_text('[]\nnot json\n' + json.dumps({'type':'assistant','message':{'usage':{'input_tokens':10}}}) + '\n', encoding='utf-8')
            result = analyze_usage([path])
            self.assertEqual(2, result['skippedRecords'])
            self.assertEqual(1, result['usageRecordsWithoutId'])
            self.assertIsNone(result['tokens']['input_tokens'])
            with patch('company_agent.usage_diagnostics.MAX_RECORDS', 1):
                self.assertTrue(analyze_usage([path])['limited'])

    def test_message_with_no_usage_is_visible_but_streamed_usage_can_complete_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'partial.jsonl'
            row = {'type':'assistant','message':{'id':'one','content':[]}}
            path.write_text(json.dumps(row), encoding='utf-8')
            result = analyze_usage([path])
            self.assertEqual('partial', result['status'])
            self.assertEqual(1, result['missingUsageFields']['input_tokens'])
            row['message']['usage'] = {key:0 for key in result['tokens']}
            with path.open('a', encoding='utf-8') as stream:
                stream.write('\n' + json.dumps(row))
            self.assertEqual('observed', analyze_usage([path])['status'])

    def test_report_escapes_data_is_offline_and_never_overwrites(self):
        data = {'projectRoot':'<script>alert(1)</script>', 'warnings':['<img src=x>'], 'sessions':[]}
        body = render_report(data)
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt;', body)
        self.assertIn("default-src 'none'", body)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '진단.html'
            write_report(path, data)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report(path, {'warnings':[]})
            self.assertEqual(before, path.read_bytes())


if __name__ == '__main__': unittest.main()
