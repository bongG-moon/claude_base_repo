"""Bound model evidence without changing full local processing or replay."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_fixture_paths import fixture_root

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
FIXTURES = fixture_root()
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish


class ContextCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FIXTURES / "complex_workbook.xlsx"
        cls.result = analyze(cls.source)

    def call(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(SKILL / "scripts/excel_pipeline.py"),
                               str(self.source), *map(str, args)], capture_output=True,
                              encoding="utf-8", timeout=30)

    def test_published_context_is_bounded_full_data_unchanged(self):
        baseline = copy.deepcopy(self.result)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            output = Path(folder) / "result"
            publish(self.result, output, sample_rows=0, context_chars=2000, layout="detailed")
            content = (output / "model_context.json").read_text(encoding="utf-8")
            self.assertLessEqual(len(content), 2000)
            self.assertIsInstance(json.loads(content), dict)
            for table in baseline["tables"]:
                self.assertEqual(json.loads((output / "tables" / (table["id"] + ".json")).read_text(encoding="utf-8")), table)
            self.assertEqual(json.loads((output / "formulas.json").read_text(encoding="utf-8")), baseline["formulas"])
            self.assertTrue((output / "pipeline_lib/model_context.py").is_file())
        self.assertEqual(self.result, baseline)

    def test_context_only_has_valid_bounded_json_and_preserves_source(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        completed = self.call("--context-only", "--sample-rows", "1000", "--context-chars", "2000")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertLessEqual(len(completed.stdout), 2000)
        self.assertIsInstance(json.loads(completed.stdout), dict)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_invalid_limits_rejected_before_processing(self):
        for args in (("--sample-rows", "1001"), ("--sample-rows", "-1"),
                     ("--context-chars", "1023"), ("--context-chars", "50001")):
            completed = self.call("--context-only", *args)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stdout, "")

    def test_context_only_cannot_silently_ignore_output(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            output = Path(folder) / "result"
            completed = self.call("--context-only", "--output", output)
            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
