"""Executable Python generation, output slicing and legacy compatibility."""
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
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze, publish
from compact_project import compile_sheets, formula_comments
from project_selection import select_result
from project_builder import make_rules
from project_runtime import read_excel_data, calculate_data
from python_formulas import FormulaBook


def values(result):
    return {(f["sheet"], f["cell"]): (f["value"], f["status"]) for f in result["formulas"]}


def run_compiled(result, data=None):
    modules, schedule = compile_sheets(result)
    book = FormulaBook()
    for _, source in modules.values():
        namespace = {}
        # Trusted compiler output, never raw formula text or arbitrary workbook code.
        exec(compile(source, "<generated-test>", "exec"), namespace)
        namespace["register"](book)
    rules = make_rules(result)
    data = data or read_excel_data(result["project_source"], rules)
    return calculate_data(data, rules, book.nodes, schedule["sheet_order"]), schedule


def edited_formula(result, sheet, address, expression):
    for cell in result["source_cells"]:
        if (cell["sheet"], cell["cell"]) == (sheet, address):
            cell["formula"] = expression
    for formula in result["formulas"]:
        if (formula["sheet"], formula["cell"]) == (sheet, address):
            formula["formula"] = expression


def literal_data(result):
    rules = make_rules(result)
    observed = {f"{c['sheet']}!{c['cell']}": c["value"] for c in result["source_cells"] if not c["formula"]}
    return {"cells": {key: observed.get(key) for key in rules["inputs"]}}


class CompactProjectTests(unittest.TestCase):
    def test_formula_comments_describe_source_references_operations_and_editing(self):
        notes = "\n".join(formula_comments(
            "=ROUND(B2*$C$1,0)", ("call", "ROUND", [
                ("binary", "*", ("ref", None, "B2", "B2"), ("ref", None, "$C$1", "$C$1")),
                ("literal", 0)]), "매출", 2, 100, "D"))
        for expected in ("99개 셀", "=ROUND(B2*$C$1,0)", "매출!B2", "매출!$C$1",
                         "두 값을 곱합니다", "반올림", "고정한 행", "수정 위치", "생성 시점"):
            self.assertIn(expected, notes)

    def test_generated_comments_cover_all_formula_groups_and_are_safe(self):
        modules, schedule = compile_sheets(self.result)
        text = "\n".join(source for _, source in modules.values())
        self.assertGreaterEqual(text.count("# 원본 Excel 수식"), schedule["loop_groups"])
        notes = formula_comments('="a\\nb"\nprint("bad")', None, "시트", 2, 2, "A")
        self.assertTrue(all("\n" not in line and line.startswith("    # ") for line in notes))
        self.assertIn("자동 해석 불가", "\n".join(notes))

    @classmethod
    def setUpClass(cls):
        cls.result = analyze(fixture_root() / "complex_workbook.xlsx")

    def test_all_values_match_and_sheet_order_is_dependency_order(self):
        actual, schedule = run_compiled(self.result)
        self.assertEqual(values(self.result), values(actual))
        position = {s: i for i, s in enumerate(schedule["sheet_order"])}
        self.assertFalse(schedule["intertwined_sheets"])
        for sheet, dependencies in schedule["dependencies"].items():
            for dependency in dependencies:
                self.assertLess(position[dependency], position[sheet])

    def test_6798_formula_workbook_groups_and_preserves_errors(self):
        original = analyze(fixture_root() / "고급_내장VBA_혼합.xlsm")
        actual, schedule = run_compiled(original)
        self.assertEqual(6798, len(actual["formulas"]))
        self.assertEqual(values(original), values(actual))
        self.assertLess(schedule["loop_groups"], 400)
        self.assertFalse(actual["summary"]["vba"]["macro_executed"])

    def test_unsupported_and_circular_status_preserved(self):
        original = analyze(fixture_root() / "ambiguous_cases.xlsx")
        actual, _ = run_compiled(original)
        self.assertEqual(values(original), values(actual))

    def test_one_module_per_calculated_sheet_compact_top_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "project"
            publish(self.result, output)
            self.assertEqual({"DATA", "PROCESS", "outputs", "tables", "_details", "_support", "main.py", "README.md", "업무흐름.html"},
                             {p.name for p in output.iterdir()})
            count = len({f["sheet"] for f in self.result["formulas"]})
            self.assertEqual(count, len(list((output / "PROCESS").glob("sheet_*.py"))))
            self.assertFalse(list((output / "PROCESS").glob("*.json")))
            self.assertFalse((output / "_details/formulas.json").exists())
            self.assertNotIn("table_steps.py", [p.name for p in (output / "PROCESS").iterdir()])
            self.assertLessEqual(len((output / "_details/model_context.json").read_text(encoding="utf-8")), 12000)

    def test_compact_main_executes_and_python_formula_edits_take_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "한글 프로젝트"
            publish(self.result, project)
            script = next(p for p in (project / "PROCESS").glob("sheet_*.py") if "정산" in p.name)
            text = script.read_text(encoding="utf-8")
            # Change a real generated expression, not the source formula contract.
            self.assertIn("VALUE(0)", text)
            # Add a clear multiplier to the H column's generated expression.
            lines = text.splitlines()
            changed = False
            for index, line in enumerate(lines):
                if 'book.set(SHEET, f"H{row}",' in line:
                    lines[index] = line[:-1] + " * VALUE(2))"
                    changed = True
            self.assertTrue(changed)
            script.write_text("\n".join(lines) + "\n", encoding="utf-8")
            run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(project / "main.py"),
                                  "--output", str(root / "out"), "--diagnostics"],
                                 cwd=root, capture_output=True, encoding="utf-8", timeout=45)
            self.assertEqual(0, run.returncode, run.stderr)
            rows = json.loads((root / "out/_details/formulas.json").read_text(encoding="utf-8"))
            self.assertEqual(200000, next(f["value"] for f in rows if f["sheet"] == "정산" and f["cell"] == "H6"))

    def test_target_transitive_closure_excludes_unrelated_inputs_and_formulas(self):
        selected = select_result(self.result, ["집계!D8"])
        self.assertEqual(1, len(selected["tables"]))
        self.assertLess(len(selected["formulas"]), len(self.result["formulas"]))
        self.assertLess(len(selected["source_cells"]), len(self.result["source_cells"]))
        actual, _ = run_compiled(selected)
        self.assertEqual(values(self.result)[("집계", "D8")], values(actual)[("집계", "D8")])
        for key, value in values(actual).items():
            self.assertEqual(values(self.result)[key], value)

    def test_target_table_id_and_multiple_ranges(self):
        selected = select_result(self.result, [self.result["tables"][0]["id"], "정산!H6", "정산!H6"])
        self.assertEqual(2, len(selected["tables"]))
        actual, _ = run_compiled(selected)
        self.assertEqual(values(self.result)[("정산", "H6")], values(actual)[("정산", "H6")])

    def test_unknown_target_and_opaque_dependencies_refuse_pruning(self):
        with self.assertRaises(ValueError):
            select_result(self.result, ["존재안함!A1"])
        original = analyze(fixture_root() / "ambiguous_cases.xlsx")
        for address in ("C5", "C6"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                select_result(original, [original["formulas"][0]["sheet"] + "!" + address])

    def test_vba_pruning_refused_before_output_creation(self):
        original = analyze(fixture_root() / "고급_내장VBA_혼합.xlsm")
        with self.assertRaisesRegex(ValueError, "VBA"):
            select_result(original, [original["tables"][0]["id"]])

    def test_data_replacement_reuses_process(self):
        selected = select_result(self.result, ["집계!D8"])
        rules = make_rules(selected)
        data = read_excel_data(selected["project_source"], rules)
        data["cells"]["신청!G6"] = 2
        actual, _ = run_compiled(selected, data)
        self.assertEqual((1285000, "computed"), values(actual)[("집계", "D8")])

    def test_both_if_branches_are_dependencies_and_blank_cells_are_kept(self):
        original = copy.deepcopy(self.result)
        target = next(c for c in original["source_cells"] if c["sheet"] == "집계" and c["cell"] == "D8")
        target["formula"] = "=IF(TRUE,신청!G6,신청!Z99)"
        # Selection reads source expressions rather than assuming evaluated branch suffices.
        selected = select_result(original, ["집계!D8"])
        rules = make_rules(selected)
        self.assertIn("신청!G6", rules["inputs"])
        self.assertIn("신청!Z99", rules["inputs"])

    def test_generated_main_does_not_mutate_source(self):
        source = Path(self.result["project_source"])
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "project"
            publish(select_result(self.result, ["집계!D8"]), output)
            completed = subprocess.run([sys.executable, "-X", "utf8", "-B", str(output / "main.py")],
                                       capture_output=True, encoding="utf-8", timeout=45)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_unknown_function_in_unused_branch_keeps_lazy_semantics(self):
        result = copy.deepcopy(self.result)
        edited_formula(result, "정산", "H6", "=IF(TRUE,7,UNKNOWN(1))")
        actual, schedule = run_compiled(result, literal_data(result))
        self.assertEqual((7, "computed"), values(actual)[("정산", "H6")])
        self.assertIn("정산", schedule["uncertain_sheets"])
        with self.assertRaises(ValueError):
            select_result(result, ["정산!H6"])

    def test_mutual_sheet_refs_are_not_mistaken_for_cell_cycles(self):
        result = copy.deepcopy(self.result)
        edited_formula(result, "정산", "H6", "=IF(TRUE,7,집계!A1)")
        actual, schedule = run_compiled(result, literal_data(result))
        self.assertIn("정산", schedule["intertwined_sheets"])
        self.assertEqual((7, "computed"), values(actual)[("정산", "H6")])

    def test_actual_cell_cycle_reports_error_without_waiting(self):
        result = copy.deepcopy(self.result)
        edited_formula(result, "정산", "H6", "=집계!D8")
        edited_formula(result, "집계", "D8", "=정산!H6")
        actual, schedule = run_compiled(result, literal_data(result))
        self.assertEqual((None, "error"), values(actual)[("정산", "H6")])
        self.assertTrue(schedule["intertwined_sheets"])

    def test_string_literals_are_not_executed(self):
        result = copy.deepcopy(self.result)
        edited_formula(result, "정산", "H6", '="__import__(\'os\').system(\'never run\')"')
        actual, _ = run_compiled(result, literal_data(result))
        self.assertEqual(("__import__('os').system('never run')", "computed"),
                         values(actual)[("정산", "H6")])

    def test_mixed_absolute_and_relative_reference_patterns(self):
        result = copy.deepcopy(self.result)
        for row in (6, 7, 8):
            edited_formula(result, "정산", f"H{row}", f"=신청!$G{row}*100000+신청!G$6")
        actual, _ = run_compiled(result, literal_data(result))
        baseline = calculate_data(literal_data(result), make_rules(result))
        self.assertEqual(values(baseline), values(actual))
        modules, _ = compile_sheets(result)
        source = next(text for sheet, text in modules.values() if sheet == "정산")
        self.assertIn("range(6, 9)", source)
        self.assertIn("'G6'", source)

    def test_invalid_and_whole_column_targets_refused(self):
        for target in ("집계!A:A", "집계!A0", "집계!XFE1", "집계!A1048577"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                select_result(self.result, [target])


if __name__ == "__main__":
    unittest.main()
