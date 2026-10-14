from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from vba_inspect import comment_free, inspect_sources, main


class VBAIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def source(self, content, name="Sample.bas", encoding="utf-8"):
        path = self.folder / name
        path.write_text(content, encoding=encoding)
        return path

    def test_comments_and_quoted_apostrophes(self):
        self.assertEqual(comment_free('x = "O\'Brien" \' note'), 'x = "O\'Brien" ')
        self.assertEqual(comment_free('Rem Call Danger'), '')
        self.assertEqual(comment_free('s = "a""b" \'note'), 's = "a""b" ')

    def test_index_call_candidates_and_literal_ranges(self):
        p = self.source('Sub RunJob()\n Call Normalize\n Worksheets("신청").Range("B5:D20").ClearContents\nEnd Sub\nFunction Normalize()\nNormalize = 1\nEnd Function\n')
        before = p.read_bytes()
        report = inspect_sources([p])
        self.assertEqual(report["procedure_count"], 2)
        proc = report["modules"][0]["procedures"][0]
        self.assertEqual(proc["call_candidates"], ["normalize"])
        self.assertEqual(proc["literal_sheets"], ["신청"])
        self.assertEqual(proc["literal_ranges"], ["B5:D20"])
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse(report["macro_executed"])
        self.assertFalse(report["translation_generated"])

    def test_strings_and_comments_are_not_call_hints(self):
        p = self.source('Sub One()\n x = "Call Two"\n \' Call Two\nEnd Sub\nSub Two()\nEnd Sub')
        self.assertEqual(inspect_sources([p])["modules"][0]["procedures"][0]["call_candidates"], [])

    def test_event_external_action_and_rounding_review(self):
        p = self.source('Private Sub Workbook_Open()\n Shell "example"\n x = Round(2.5, 0)\n Application.Run name\nEnd Sub')
        proc = inspect_sources([p])["modules"][0]["procedures"][0]
        self.assertTrue(proc["event_entry_candidate"])
        kinds = {x["kind"] for x in proc["review_hints"]}
        self.assertTrue({"external_or_process_action", "rounding_semantics", "dynamic_dispatch"} <= kinds)

    def test_unterminated_and_conditional_compilation(self):
        p = self.source('#If VBA7 Then\nSub MissingEnd()\n x=1\n')
        warnings = inspect_sources([p])["modules"][0]["warnings"]
        self.assertEqual({w["reason"] for w in warnings}, {"unterminated_procedure", "conditional_compilation_requires_review"})

    def test_explicit_encoding_and_no_lossy_fallback(self):
        p = self.source('Sub 한글()\nEnd Sub', encoding="cp949")
        with self.assertRaises(UnicodeDecodeError):
            inspect_sources([p])
        self.assertEqual(inspect_sources([p], "cp949")["procedure_count"], 1)

    def test_workbook_not_misreported_as_vba(self):
        p = self.source('not a VBA file', name="fake.xlsm")
        with self.assertRaisesRegex(ValueError, "별도 단계"):
            inspect_sources([p])

    def test_existing_output_preserved(self):
        p = self.source('Sub Foo()\nEnd Sub')
        output = self.folder / "index.json"
        output.write_text("original", encoding="utf-8")
        self.assertEqual(main([str(p), "--output", str(output)]), 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
