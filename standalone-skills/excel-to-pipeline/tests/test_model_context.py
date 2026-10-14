"""Budget/provenance tests independent of Excel, VBA, network and model runtimes."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from model_context import build_model_context, serialize_model_context, _row_pattern


def analysis(table_count=1, rows=10):
    return {"summary": {"source_name": "교육.xlsx", "status": "extracted", "review_flags": []},
            "sheets": [{"name": "원본", "range": "A1:B2001", "state": "visible", "table_count": table_count}],
            "tables": [{"id": f"t{index}", "sheet": "원본", "range": "A1:B2001",
                        "columns": ["사번", "금액"],
                        "rows": [[f"{row:05}", row] for row in range(rows)],
                        "source_rows": list(range(2, rows + 2)), "row_kinds": ["data"] * rows}
                       for index in range(table_count)], "formulas": [], "source_cells": [],
            "pipeline_plan": {"full": "untouched"}}


class ModelContextTests(unittest.TestCase):
    def checked(self, result, sample_rows=5, max_chars=12000):
        before = copy.deepcopy(result)
        context = build_model_context(result, sample_rows, max_chars)
        encoded = serialize_model_context(context)
        self.assertEqual(json.loads(encoded), context)
        self.assertEqual(len(encoded), context["serialized_chars"])
        self.assertLessEqual(len(encoded), max_chars)
        self.assertEqual(result, before)
        self.assertEqual(context["unit"], "serialized_json_characters_not_tokens")
        return context

    def test_default_is_five_not_thousand(self):
        context = self.checked(analysis(rows=1200))
        self.assertEqual(context["sampled_data_rows"], 5)
        self.assertEqual(context["totals"]["data_rows"], 1200)
        self.assertEqual(context["omitted"]["data_rows"], 1195)
        self.assertEqual(context["tables"][0]["sample_rows"][0]["values"], ["00000", 0])

    def test_hard_ceiling_and_explicit_requested_value(self):
        context = self.checked(analysis(rows=1201), sample_rows=5000, max_chars=200000)
        self.assertEqual(context["limits"]["requested_rows"], 5000)
        self.assertEqual(context["limits"]["effective_rows"], 1000)
        self.assertEqual(context["sampled_data_rows"], 1000)
        self.assertEqual(context["omitted"]["data_rows"], 201)

    def test_many_tables_global_budget(self):
        context = self.checked(analysis(table_count=100, rows=20), sample_rows=1000, max_chars=2000)
        self.assertEqual(context["totals"]["tables"], 100)
        self.assertEqual(context["omitted"]["tables"], 100 - len(context["tables"]))
        self.assertGreater(context["omitted"]["tables"], 0)
        self.assertEqual(context["omitted"]["data_rows"], 2000 - context["sampled_data_rows"])

    def test_unicode_and_large_escaped_cell(self):
        data = analysis(rows=1)
        data["tables"][0]["columns"][0] = "한글🌏" * 10000
        data["tables"][0]["rows"][0][0] = '\n"\\한국어🌏' * 20000
        context = self.checked(data, max_chars=5000)
        header = context["tables"][0]["columns"][0]["name"]
        cell = context["tables"][0]["sample_rows"][0]["values"][0]
        self.assertTrue(header["truncated"])
        self.assertEqual(header["original_chars"], len(data["tables"][0]["columns"][0]))
        self.assertEqual(cell["original_chars"], len(data["tables"][0]["rows"][0][0]))
        self.assertEqual(context["truncated_fields"], 2)
        self.assertGreater(len(serialize_model_context(context).encode("utf-8")), context["serialized_chars"])

    def test_zero_samples_still_has_structure(self):
        context = self.checked(analysis(), sample_rows=0)
        self.assertEqual(context["sampled_data_rows"], 0)
        self.assertEqual(context["omitted"]["data_rows"], 10)
        self.assertEqual(len(context["tables"][0]["columns"]), 2)

    def test_summary_and_header_rows_not_data_samples(self):
        data = analysis(rows=6)
        data["tables"][0]["row_kinds"] = ["header_candidate", "data", "summary_candidate", "data", "data", "data"]
        context = self.checked(data, sample_rows=2)
        self.assertEqual(context["totals"]["extracted_rows"], 6)
        self.assertEqual(context["totals"]["data_rows"], 4)
        self.assertEqual([s["source_row"] for s in context["tables"][0]["sample_rows"]], [3, 5])

    def test_no_vba_dependency_or_source_cells_dump(self):
        data = analysis()
        data["source_cells"] = [{"value": "NEVER_RAW_DUMP"}] * 9999
        context = self.checked(data)
        self.assertEqual(context["vba"]["status"], "not_present")
        self.assertEqual(context["omitted"]["source_cells"], 9999)
        self.assertNotIn("NEVER_RAW_DUMP", serialize_model_context(context))

    def test_only_vba_module_and_procedure_index(self):
        data = analysis(rows=1)
        data["vba"] = {"status": "extracted", "modules": [
            {"name": "Main", "relative_path": "modules/Main.bas", "module_type": ".bas", "source": "NEVER_FULL_VBA" * 10000}]}
        data["vba_index"] = {"modules": [{"file": "Main.bas", "procedures": [
            {"name": "Prepare", "kind": "Sub", "start_line": 3, "end_line": 20,
             "call_candidates": ["NO_FULL_CALL_DUMP"] * 1000}]}]}
        context = self.checked(data)
        self.assertEqual(context["totals"]["vba_modules"], 1)
        self.assertEqual(context["totals"]["vba_procedures"], 1)
        self.assertEqual(context["vba"]["procedures"][0]["name"], "Prepare")
        self.assertNotIn("NEVER_FULL_VBA", serialize_model_context(context))
        self.assertNotIn("NO_FULL_CALL_DUMP", serialize_model_context(context))

    def test_representative_formula_patterns_keep_constants_and_absolute_rows(self):
        data = analysis(rows=1)
        expressions = ["=A2*2+$B$5", "=A3*2+$B$5", "=A3*3+$B$5", '=IF(A4="A1",1,0)']
        data["formulas"] = [{"sheet": "원본", "cell": f"C{i+2}", "formula": f,
                             "status": "computed", "functions": []} for i, f in enumerate(expressions)]
        context = self.checked(data)
        self.assertEqual(context["totals"]["formulas"], 4)
        self.assertEqual(context["totals"]["formula_patterns"], 3)
        self.assertEqual(context["formula_patterns"][0]["count"], 2)
        self.assertEqual(context["formula_patterns"][0]["pattern"], "=A[r+0]*2+$B$5")
        self.assertIn('"A1"', context["formula_patterns"][-1]["pattern"])

    def test_relative_offsets_keep_exceptional_formula_separate(self):
        data = analysis(rows=1)
        data["formulas"] = [
            {"sheet": "원본", "cell": "C2", "formula": "=A2+A3", "status": "computed"},
            {"sheet": "원본", "cell": "C3", "formula": "=A3+A4", "status": "computed"},
            {"sheet": "원본", "cell": "C2", "formula": "=A2+A9000", "status": "computed"},
        ]
        context = self.checked(data)
        self.assertEqual(context["totals"]["formula_patterns"], 2)
        self.assertEqual(context["formula_patterns"][0]["count"], 2)
        self.assertIn("[r+8998]", context["formula_patterns"][1]["pattern"])

    def test_formula_grouping_protects_quoted_sheets_functions_and_strings(self):
        self.assertEqual(_row_pattern('=\'A1\'!A2+\'A1\'!$B$5+LOG10(A2)+"B19"', "C2"),
                         '=\'A1\'!A[r+0]+\'A1\'!$B$5+LOG10(A[r+0])+"B19"')
        self.assertEqual(_row_pattern("='A1''s'!A2+A1!B2", "C2"), "='A1''s'!A[r+0]+A1!B[r+0]")
        for origin in (None, "", "A0", "XFE3", "A1048577", "not a cell"):
            self.assertEqual(_row_pattern("=A2+A3", origin), "=A2+A3")

    def test_huge_formula_and_functions_are_bounded(self):
        data = analysis(rows=2)
        data["formulas"] = [{"sheet": "원본", "cell": "A2", "formula": "=SUM(" + "A1," * 10000 + "0)",
                             "status": "unsupported", "functions": ["BIG" * 100] * 100}]
        context = self.checked(data, max_chars=12000)
        group = context["formula_patterns"][0]
        self.assertTrue(group["example"]["formula"]["truncated"])
        self.assertEqual(group["example"]["omitted_functions"], 92)

    def test_indexes_do_not_consume_all_sample_space(self):
        data = analysis(table_count=12, rows=50)
        data["formulas"] = [{"sheet": "원본", "cell": "C2", "formula": f"=A2+{n}",
                             "status": "computed", "functions": []} for n in range(100)]
        data["vba"] = {"status": "extracted", "modules": [
            {"name": f"Sheet{n}", "relative_path": f"Sheet{n}.cls", "module_type": "cls"} for n in range(30)] +
            [{"name": "Business", "relative_path": "Business.bas", "module_type": "bas"}]}
        data["vba_index"] = {"modules": [{"file": "Business.bas", "procedures": [
            {"name": f"Prepare{n}", "kind": "Sub", "start_line": n * 5 + 1, "end_line": n * 5 + 4}
            for n in range(30)]}]}
        context = self.checked(data)
        self.assertEqual(len(context["tables"]), 12)
        self.assertGreaterEqual(context["sampled_data_rows"], 12)
        self.assertEqual(context["vba"]["modules"][0]["name"], "Business")
        self.assertGreater(context["omitted"]["vba_modules"], 0)
        small = self.checked(data, max_chars=8000)
        self.assertGreater(small["sampled_data_rows"], 0)
        self.assertTrue(all(table["columns"] for table in small["tables"]))

    def test_minimum_budget_and_empty_result(self):
        for value in ({}, analysis(rows=0), analysis(table_count=20, rows=50)):
            with self.subTest(keys=list(value)):
                self.checked(value, max_chars=1024)

    def test_invalid_limits(self):
        for value in (-1, 1.5, "5", True):
            with self.subTest(sample_rows=value):
                with self.assertRaises(ValueError):
                    build_model_context({}, sample_rows=value)
        for value in (0, 1023, 2000.5, "2000", True):
            with self.subTest(max_chars=value):
                with self.assertRaises(ValueError):
                    build_model_context({}, max_chars=value)

    def test_all_supported_budgets_and_long_names(self):
        data = analysis(table_count=8, rows=200)
        data["summary"]["source_name"] = "긴이름" * 10000
        data["summary"]["review_flags"] = ["불명확" * 1000] * 50
        for limit in (1024, 1200, 2000, 4096, 12000, 50000):
            with self.subTest(limit=limit):
                self.checked(data, sample_rows=1000, max_chars=limit)

    def test_incomplete_row_kind_and_source_mapping_stays_explicit(self):
        data = analysis(rows=3)
        data["tables"][0]["row_kinds"] = []
        data["tables"][0]["source_rows"] = []
        context = self.checked(data)
        self.assertEqual(context["sampled_data_rows"], 3)
        self.assertIsNone(context["tables"][0]["sample_rows"][0]["source_row"])


if __name__ == "__main__":
    unittest.main()
