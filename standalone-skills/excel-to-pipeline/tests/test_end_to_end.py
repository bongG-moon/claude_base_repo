import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_fixture_paths import fixture_root

ROOT = Path(__file__).resolve().parents[3]
SKILL = Path(__file__).resolve().parents[1]
FIXTURES = fixture_root()
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((SKILL / "tests" / "fixtures-manifest.json").read_text(encoding="utf-8"))["files"]

    def test_complex_table_ranges_headers_and_controls(self):
        source = FIXTURES / "complex_workbook.xlsx"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = analyze(source)
        expected = self.manifest[source.name]
        self.assertEqual(result["summary"]["sheet_count"], expected["sheets"])
        self.assertEqual(result["summary"]["table_count"], len(expected["tables"]))
        self.assertEqual(result["summary"]["formula_status"], {"computed": 82})
        self.assertEqual(result["summary"]["cache_comparison"], {"match": 82})
        tables = {(t["sheet"], t["range"]): t for t in result["tables"]}
        for item in expected["tables"]:
            table = tables[(item["sheet"], item["range"])]
            self.assertEqual(table["header_rows"], item["headerRows"])
            self.assertEqual(len(table["rows"]), item["dataRows"] + len(item.get("totalRows", [])))
            self.assertEqual(table["blank_rows"], item.get("blankRows", []))
            if "flattenedHeaders" in item:
                self.assertEqual(table["columns"], item["flattenedHeaders"])
        self.assert_controls(result, expected["expectedCells"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def assert_controls(self, result, expectations):
        observed = {f"{cell['sheet']}!{cell['cell']}": cell["value"] for cell in result["source_cells"]}
        observed.update({f"{f['sheet']}!{f['cell']}": f["value"] for f in result["formulas"]})
        for key, expected in expectations.items():
            with self.subTest(cell=key):
                if isinstance(expected, (int, float)):
                    self.assertAlmostEqual(observed[key], expected)
                else:
                    self.assertEqual(observed.get(key), expected)

    def test_generated_project_processes_changed_month(self):
        with tempfile.TemporaryDirectory(dir=FIXTURES) as folder:
            base, second = Path(folder) / "base", Path(folder) / "second"
            publish(analyze(FIXTURES / "complex_workbook.xlsx"), base)
            completed = subprocess.run([sys.executable, "-X", "utf8", str(base / "transform.py"),
                                        str(FIXTURES / "variant_next_month.xlsx"), "--output", str(second)],
                                       capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["formula_status"], {"computed": 89})
            self.assertEqual(summary["cache_comparison"], {"match": 89})
            actual = {"source_cells": json.loads((second / "source_cells.json").read_text(encoding="utf-8")),
                      "formulas": json.loads((second / "formulas.json").read_text(encoding="utf-8"))}
            self.assert_controls(actual, self.manifest["variant_next_month.xlsx"]["expectedCells"])
            self.assertTrue((second / "pipeline_plan.json").is_file())

    def test_exception_file_is_explicit_not_fake_success(self):
        result = analyze(FIXTURES / "ambiguous_cases.xlsx")
        self.assertEqual(result["summary"]["status"], "review_required")
        self.assertEqual(result["summary"]["formula_status"], {"unsupported": 2, "error": 4, "computed": 1})
        formulas = {f["cell"]: f for f in result["formulas"]}
        for cell in ("C5", "C6"):
            self.assertEqual(formulas[cell]["status"], "unsupported")
            self.assertIsNone(formulas[cell]["value"])
        for cell in ("C7", "C8", "C9", "C10"):
            self.assertEqual(formulas[cell]["status"], "error")
        self.assertEqual(formulas["C12"]["value"], 30)
        self.assertEqual(formulas["C12"]["cache_comparison"], "unavailable")
        self.assertIn("repeated_header_rows", result["summary"]["review_flags"])

    def test_table_dependency_order(self):
        result = analyze(FIXTURES / "complex_workbook.xlsx")
        stages = {s["table"]: s for s in result["pipeline_plan"]["stages"]}
        self.assertIn("s02_t01", stages["s01_t01"]["depends_on_tables"])
        self.assertIn("s04_t01", stages["s02_t01"]["depends_on_tables"])
        self.assertIn("s03_t01", stages["s02_t01"]["depends_on_tables"])
        order = result["pipeline_plan"]["suggested_table_order"]
        self.assertLess(order.index("s04_t01"), order.index("s02_t01"))
        self.assertLess(order.index("s02_t01"), order.index("s01_t01"))


if __name__ == "__main__":
    unittest.main()
