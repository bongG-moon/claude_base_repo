"""Workbook analysis and static VBA evidence integration; no macro execution."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_fixture_paths import fixture_root

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
FIXTURES = fixture_root()
sys.path.insert(0, str(SKILL / "scripts"))
import excel_pipeline as pipeline
import vba_extract


def extracted_module():
    source = ('Attribute VB_Name = "Example"\nOption Explicit\n'
              'Public Sub Prepare()\n    Worksheets("입력").Calculate\nEnd Sub\n'
              'Public Function CalculateFee(ByVal Amount As Double) As Double\n'
              '    CalculateFee = Amount * 2\nEnd Function\n')
    return {"name": "Example", "relative_path": "modules/001_Example.bas",
            "source": source, "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "stream_path": "VBA/Example", "decoded_with_replacement": False}


class CombinedVbaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FIXTURES / "complex_workbook.xlsx"
        cls.baseline = pipeline.analyze(cls.source)

    def test_ordinary_xlsx_never_runs_vba_extraction(self):
        with patch("vba_extract.extract_vba", side_effect=AssertionError("ordinary xlsx must not call VBA")), \
                patch("vba_extract.run_worker", side_effect=AssertionError("must not spawn")):
            result = pipeline.analyze(self.source)
        self.assertNotIn("vba", result)
        self.assertNotIn("vba", result["summary"])
        self.assertEqual(result["summary"]["formula_status"], {"computed": 82})

    def test_xlsm_extension_without_vba_produces_manifest_only(self):
        # Controlled absence case, not a claim that renaming creates a native XLSM.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            source, output = Path(folder) / "without-vba.xlsm", Path(folder) / "result"
            shutil.copyfile(self.source, source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch("vba_extract.run_worker", side_effect=AssertionError("no VBA must not spawn")):
                result = pipeline.analyze(source)
            self.assertEqual(result["vba"]["status"], "no_vba")
            self.assertEqual(result["migration_plan"]["translation_status"], "not_required")
            self.assertEqual(result["summary"]["formula_status"], {"computed": 82})
            pipeline.publish(result, output, emit_project=False)
            manifest = json.loads((output / "vba" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "no_vba")
            self.assertFalse((output / "vba" / "modules").exists())
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_missing_dependency_preserves_cell_analysis_and_reports_blocked_migration(self):
        result = copy.deepcopy(self.baseline)
        before_formulas, before_tables = copy.deepcopy(result["formulas"]), copy.deepcopy(result["tables"])
        missing = vba_extract.outcome("dependency_missing", "시험용 oletools 미설치")
        with patch("vba_extract.extract_vba", return_value=missing) as extract:
            pipeline.attach_vba_analysis(self.source, result)
        extract.assert_called_once_with(self.source)
        self.assertEqual(result["formulas"], before_formulas)
        self.assertEqual(result["tables"], before_tables)
        self.assertEqual(result["summary"]["status"], "review_required")
        self.assertIn("vba_source_unavailable", result["summary"]["review_flags"])
        self.assertEqual(result["migration_plan"]["translation_status"], "blocked_source_unavailable")
        self.assertFalse(result["summary"]["vba"]["translation_generated"])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            output = Path(folder) / "result"
            pipeline.publish(result, output, emit_project=False)
            self.assertTrue((output / "tables" / "s01_t01.json").is_file())
            manifest = json.loads((output / "vba" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "dependency_missing")
            self.assertEqual(manifest["modules"], [])

    def test_extracted_sources_are_evidence_not_automatic_translation(self):
        result, module = copy.deepcopy(self.baseline), extracted_module()
        extraction = dict(vba_extract.outcome("extracted", "원문 추출"), modules=[module])
        with patch("vba_extract.extract_vba", return_value=extraction):
            pipeline.attach_vba_analysis(self.source, result)
        self.assertEqual(result["summary"]["vba"]["procedure_count"], 2)
        self.assertEqual(result["migration_plan"]["translation_status"], "requires_semantic_translation")
        self.assertIsNone(result["migration_plan"]["reviewed_python_entrypoint"])
        self.assertFalse(result["migration_plan"]["macro_executed"])
        self.assertEqual(result["migration_plan"]["calculation_order_candidates"][0]["procedure"], "Prepare")
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            output = Path(folder) / "result"
            pipeline.publish(result, output, emit_project=True)
            source = output / "vba" / module["relative_path"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), module["source_sha256"])
            manifest = json.loads((output / "vba" / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("source", manifest["modules"][0])
            self.assertTrue((output / "pipeline_lib" / "vba_extract.py").is_file())
            self.assertIn("oletools==0.60.2", (output / "requirements-vba.txt").read_text(encoding="utf-8"))

    def test_udf_candidate_does_not_claim_execution_or_match_string_literals(self):
        result = copy.deepcopy(self.baseline)
        result["formulas"] = [
            {"sheet": "수식", "cell": "A1", "formula": "=CalculateFee(10)"},
            {"sheet": "수식", "cell": "A2", "formula": '=IF(TRUE,"CalculateFee(10)",0)'},
        ]
        with patch("vba_extract.extract_vba", return_value=dict(vba_extract.outcome("extracted", ""), modules=[extracted_module()])):
            pipeline.attach_vba_analysis(self.source, result)
        self.assertEqual(result["migration_plan"]["formula_udf_candidates"], [
            {"sheet": "수식", "cell": "A1", "functions": ["CalculateFee"]}])
        self.assertFalse(result["migration_plan"]["macro_executed"])


if __name__ == "__main__":
    unittest.main()
