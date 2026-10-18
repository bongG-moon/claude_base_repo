"""Execute generated projects and replace DATA without changing PROCESS."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_fixture_paths import fixture_root

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish
from project_builder import make_rules
from project_runtime import calculate_data, read_excel_data, replace_tables, validate_data


def formulas(result):
    return {(f["sheet"], f["cell"]): (f["value"], f["status"]) for f in result["formulas"]}


def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


class GeneratedProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = fixture_root() / "complex_workbook.xlsx"
        cls.analysis = analyze(cls.source)
        cls.rules = make_rules(cls.analysis)
        cls.data = read_excel_data(cls.source, cls.rules)

    def test_frozen_rules_reproduce_all_tables_and_formulas(self):
        actual = calculate_data(self.data, self.rules)
        self.assertEqual(formulas(actual), formulas(self.analysis))
        self.assertEqual([t["rows"] for t in actual["tables"]], [t["rows"] for t in self.analysis["tables"]])
        self.assertEqual({"unavailable": 82}, actual["summary"]["cache_comparison"])

    def test_changed_input_updates_calculations_without_file_access(self):
        changed = copy.deepcopy(self.data)
        changed["cells"]["신청!G6"] = 2  # quantity 1 -> 2; unit price 100000
        changed["cells"]["신청!B6"] = "aB001"  # case is not normalized
        with patch("workbook_input.load_workbooks", side_effect=AssertionError("PROCESS must not open files")):
            actual = calculate_data(changed, self.rules)
        values = formulas(actual)
        self.assertEqual((200000, "computed"), values[("정산", "H6")])
        self.assertEqual((1285000, "computed"), values[("집계", "D8")])
        self.assertTrue(any(c["value"] == "aB001" for c in actual["source_cells"]))

    def test_table_adapter_changes_data_only(self):
        table = next(t for t in self.rules["tables"] if t["sheet"] == "신청")
        rows = [{name: self.data["cells"][key] for name, key in mapping.items()} for mapping in table["input_rows"]]
        column = next(name for name, key in table["input_rows"][0].items() if key == "신청!G6")
        rows[0][column] = 2
        changed = replace_tables(self.data, {table["id"]: rows}, self.rules)
        self.assertEqual(1, self.data["cells"]["신청!G6"])
        self.assertEqual(2, changed["cells"]["신청!G6"])
        self.assertEqual((1285000, "computed"), formulas(calculate_data(changed, self.rules))[("집계", "D8")])
        self.assertNotIn("sha256", changed)
        with self.assertRaisesRegex(ValueError, "행"):
            replace_tables(self.data, {table["id"]: rows + [rows[0]]}, self.rules)
        rows[0]["unexpected"] = 3
        with self.assertRaisesRegex(ValueError, "열"):
            replace_tables(self.data, {table["id"]: rows}, self.rules)

    def test_missing_wrong_type_and_header_fail_clearly(self):
        for key, value, expected in [("신청!B6", 101, "문자열"), ("신청!G6", "2", "숫자"),
                                     ("신청!G6", float("nan"), "NaN"), ("신청!B5", "다른 열", "열 제목")]:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(self.data)
                bad["cells"][key] = value
                with self.assertRaisesRegex(ValueError, expected):
                    calculate_data(bad, self.rules)
        bad = copy.deepcopy(self.data)
        del bad["cells"]["신청!G6"]
        with self.assertRaisesRegex(ValueError, "누락"):
            calculate_data(bad, self.rules)

    def test_row_or_formula_growth_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "구조"):
            read_excel_data(fixture_root() / "variant_next_month.xlsx", self.rules)

    def test_literal_equals_is_not_executed_and_blanks_are_not_zeroed(self):
        data = copy.deepcopy(self.data)
        data["cells"]["신청!B6"] = "=1+2"
        data["cells"]["실적!F9"] = None
        actual = calculate_data(data, self.rules)
        cell = next(c for c in actual["source_cells"] if c["sheet"] == "신청" and c["cell"] == "B6")
        self.assertEqual("=1+2", cell["value"])
        self.assertIsNone(cell["formula"])
        self.assertEqual(82, len(actual["formulas"]))
        self.assertIsNone(next(c["value"] for c in actual["source_cells"] if c["sheet"] == "실적" and c["cell"] == "F9"))

    def test_main_runs_then_only_data_loader_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "한글 업무 프로젝트"
            publish(self.analysis, project, context_chars=4000)
            before = hashes(project / "PROCESS")
            source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
            first = root / "첫 결과"
            command = [sys.executable, "-X", "utf8", "-B", str(project / "main.py"), "--output", str(first)]
            run = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertEqual({"computed": 82}, json.loads(run.stdout)["summary"]["formula_status"])
            # Replace the loader with a Python/JSON data source. No workbook or
            # plugin path is passed; PROCESS and main.py are not edited.
            changed = copy.deepcopy(self.data)
            changed["cells"]["신청!G6"] = 2
            changed.pop("input_evidence", None)
            changed.pop("sha256", None)
            changed.pop("source_unchanged", None)
            (project / "DATA" / "records.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            (project / "DATA" / "load.py").write_text(
                '"""엑셀 대신 다른 Python에서 준비한 JSON 자료를 읽습니다."""\n'
                'import json\nfrom pathlib import Path\n'
                'def load_data():\n'
                '    return json.loads(Path(__file__).with_name("records.json").read_text(encoding="utf-8"))\n', encoding="utf-8")
            second = root / "다른 출처 결과"
            command[-1] = str(second)
            run = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            summary = json.loads(run.stdout)["summary"]
            self.assertEqual("python_adapter", summary["reader"])
            values = json.loads((second / "formulas.json").read_text(encoding="utf-8"))
            total = next(f["value"] for f in values if f["sheet"] == "집계" and f["cell"] == "D8")
            self.assertEqual(1285000, total)
            self.assertEqual(before, hashes(project / "PROCESS"))
            self.assertEqual(source_hash, hashlib.sha256(self.source.read_bytes()).hexdigest())
            self.assertLessEqual(len((second / "model_context.json").read_text(encoding="utf-8")), 4000)
            self.assertTrue((second / "processed_tables.json").is_file())
            # Existing output must fail before any loader or Excel activity.
            (project / "DATA" / "load.py").write_text('def load_data():\n    raise AssertionError("must not read")\n', encoding="utf-8")
            run = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(2, run.returncode)
            self.assertIn("이미 있습니다", run.stderr)

    def test_embedded_vba_complex_case_keeps_every_formula_status(self):
        source = fixture_root() / "고급_내장VBA_혼합.xlsm"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        result = analyze(source)
        rules = make_rules(result)
        data = read_excel_data(source, rules)
        actual = calculate_data(data, rules)
        self.assertEqual(6798, len(actual["formulas"]))
        self.assertEqual(formulas(result), formulas(actual))
        self.assertEqual([t["rows"] for t in result["tables"]], [t["rows"] for t in actual["tables"]])
        self.assertFalse(actual["summary"]["vba"]["macro_executed"])
        self.assertIn("vba_semantic_migration_required", actual["summary"]["review_flags"])
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
