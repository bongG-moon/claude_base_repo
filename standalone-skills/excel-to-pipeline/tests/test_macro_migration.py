"""Behavior tests of the reviewed VBA-to-Python example; no Excel/VBA execution."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from test_case_preserving_controls import revised_expected
from test_fixture_paths import advanced_root

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migrate_training", ROOT / "examples" / "macro-migration" / "migrate_training.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def row(sheet, data, line=6):
    return dict(zip(migration.SCHEMAS[sheet], data), source_sheet=sheet, source_row=line)


def inputs():
    return {
        "신청원본": [row("신청원본", [" A001 ", "00101", "기획", " c01 ", "2026-10-14", 1, "승인", 0, None, 1, "", "A"])],
        "출결원본": [row("출결원본", ["A001", i, 1, 2], i + 5) for i in range(1, 4)],
        "평가원본": [row("평가원본", ["A001", 60, 1])],
        "사원기준": [row("사원기준", ["00101", "가상직원", "기획", "사원", 1])],
        "교육기준": [row("교육기준", ["c01", "분석", 100.5, 6, 60])],
        "정책": [row("정책", ["필수참석차시", 3]), row("정책", ["기본수료점수", 60], 7), row("정책", ["금액소수자리", 0], 8)],
    }


class MacroMigrationTest(unittest.TestCase):
    def test_macro_only_no_formula_needed(self):
        source = inputs()
        before = copy.deepcopy(source)
        result = migration.process_inputs(source)
        self.assertEqual(result["summary"]["total_amount"], 101)
        self.assertEqual(result["summary"]["completed_count"], 1)
        self.assertEqual(result["records"][0]["employee_id"], "00101")
        self.assertEqual(result["records"][0]["course_code"], "c01")
        self.assertEqual(source, before)

    def test_identifiers_preserve_lowercase_and_mixed_case(self):
        for value in ("c03", "AbC-001", "straße", "001Ab"):
            with self.subTest(value=value):
                self.assertEqual(migration.code(" " + value + " "), value)

    def test_case_distinct_lookup_keys_do_not_merge(self):
        records = [row("교육기준", [key, "분석", 100, 6, 60], i)
                   for i, key in enumerate(("c01", "C01", "c01A"), 6)]
        self.assertEqual(set(migration.unique_lookup(records, "과정코드")), {"c01", "C01", "c01A"})

    def test_case_distinct_application_ids_do_not_deduplicate_or_join(self):
        source = inputs()
        source["신청원본"] = [dict(source["신청원본"][0], 신청ID=" a001 "),
                              dict(source["신청원본"][0], 신청ID="A001", source_row=7),
                              dict(source["신청원본"][0], 신청ID="a001X", source_row=8)]
        before = copy.deepcopy(source)
        for mode in ("macro-only", "mixed"):
            result = migration.process_inputs(source, mode)
            actual = {item["application_id"]: item for item in result["records"]}
            self.assertEqual(set(actual), {"a001", "A001", "a001X"})
            self.assertEqual(result["summary"]["superseded_count"], 0)
            self.assertTrue(actual["A001"]["completed"])
            self.assertFalse(actual["a001"]["completed"])
            self.assertFalse(actual["a001X"]["completed"])
        self.assertEqual(source, before)

    def test_case_mismatch_is_rejected_not_silently_corrected(self):
        source = inputs()
        source["교육기준"][0]["과정코드"] = "C01"
        for mode in ("macro-only", "mixed"):
            result = migration.process_inputs(source, mode)
            self.assertEqual(result["summary"]["approved_count"], 0)
            self.assertEqual(result["summary"]["rejected_count"], 1)
            self.assertIn("과정코드", result["rejected"][0]["reason"])

    def test_changed_policy_does_not_claim_vba_equivalence(self):
        result = migration.process_inputs(inputs())
        self.assertFalse(result["summary"]["original_vba_equivalent"])
        self.assertEqual(result["summary"]["identifier_policy"],
                         "trim_whitespace_preserve_case_case_sensitive_match")
        self.assertTrue(result["summary"]["source_rule_changes"])

    def test_mixed_recalculates_same_result_without_cache(self):
        a = migration.process_inputs(inputs(), "macro-only")
        b = migration.process_inputs(inputs(), "mixed")
        self.assertEqual(a["records"], b["records"])
        self.assertEqual(a["departments"], b["departments"])
        self.assertEqual(len(b["formula_steps"]), 1)
        self.assertFalse(b["summary"]["formula_caches_used"])

    def test_excel_round_not_vba_bankers_round(self):
        self.assertEqual(round(100.5), 100)
        self.assertEqual(migration.excel_round("100.5"), 101)
        self.assertEqual(migration.excel_round("-2.5"), -3)

    def test_zero_override_wins_but_blank_does_not(self):
        source = inputs()
        source["신청원본"][0]["수동금액"] = 0
        for mode in ["macro-only", "mixed"]:
            result = migration.process_inputs(source, mode)
            self.assertEqual(result["summary"]["total_amount"], 0)
        source["신청원본"][0]["수동금액"] = ""
        self.assertEqual(migration.process_inputs(source)["summary"]["total_amount"], 101)

    def test_revision_numeric_latest_then_tied_later_row(self):
        source = inputs()
        for line, version, quantity in [(7, 10, 2), (8, 2, 4), (9, 10, 3)]:
            item = dict(source["신청원본"][0], 갱신순번=version, 수량=quantity, source_row=line)
            source["신청원본"].append(item)
        result = migration.process_inputs(source)
        self.assertEqual(result["summary"]["superseded_count"], 3)
        self.assertEqual(result["summary"]["total_amount"], 302)
        self.assertEqual(result["records"][0]["source_row"], 9)

    def test_department_conflict_not_corrected(self):
        source = inputs()
        source["신청원본"][0]["부서"] = "생산"
        result = migration.process_inputs(source)
        self.assertEqual(result["summary"]["approved_count"], 0)
        self.assertEqual(result["summary"]["rejected_count"], 1)
        self.assertIn("자동 교정하지", result["rejected"][0]["reason"])

    def test_waiting_and_cancelled_not_counted(self):
        source = inputs()
        for state in ["대기", "취소"]:
            source["신청원본"][0]["상태"] = state
            result = migration.process_inputs(source)
            self.assertEqual(result["summary"]["excluded_count"], 1)
            self.assertEqual(result["summary"]["total_amount"], 0)

    def test_duplicate_session_does_not_complete(self):
        source = inputs()
        source["출결원본"] = [source["출결원본"][0]] * 3
        result = migration.process_inputs(source)
        self.assertEqual(result["records"][0]["attended_sessions"], 1)
        self.assertFalse(result["records"][0]["completed"])

    def test_missing_score_is_not_zero(self):
        source = inputs()
        source["평가원본"][0].update(점수=None, 응시=0)
        for mode in ["macro-only", "mixed"]:
            result = migration.process_inputs(source, mode)
            self.assertIsNone(result["records"][0]["score"])
            self.assertFalse(result["records"][0]["completed"])

    def test_taken_exam_without_score_rejected(self):
        source = inputs()
        source["평가원본"][0]["점수"] = None
        result = migration.process_inputs(source)
        self.assertEqual(result["summary"]["rejected_count"], 1)

    def test_invalid_inputs_do_not_silently_become_zero(self):
        for key, value in [("수량", None), ("수량", -1), ("수량", 1.5), ("할인율", None),
                           ("할인율", 1.1), ("교육일", "2026-02-30"), ("사번", 101),
                           ("과정코드", "UNKNOWN"), ("수동금액", -1)]:
            with self.subTest(key=key, value=value):
                source = inputs()
                source["신청원본"][0][key] = value
                self.assertEqual(migration.process_inputs(source)["summary"]["rejected_count"], 1)

    def test_reference_duplicate_is_visible_error(self):
        source = inputs()
        source["교육기준"].append(dict(source["교육기준"][0]))
        with self.assertRaises(migration.InputError):
            migration.process_inputs(source)

    def test_zero_quantity_and_pass_score_boundary(self):
        source = inputs()
        source["신청원본"][0]["수량"] = 0
        result = migration.process_inputs(source)
        self.assertEqual(result["summary"]["total_amount"], 0)
        self.assertTrue(result["records"][0]["completed"])
        source["평가원본"][0]["점수"] = 59.999
        self.assertFalse(migration.process_inputs(source)["records"][0]["completed"])

    def test_rounding_after_discount(self):
        source = inputs()
        source["신청원본"][0].update(수량=3, 할인율=0.1)
        for mode in ["macro-only", "mixed"]:
            self.assertEqual(migration.process_inputs(source, mode)["summary"]["total_amount"], 271)

    def test_vba_numeric_bounds_preserved(self):
        for key in ["수량", "수동금액", "갱신순번"]:
            with self.subTest(key=key):
                source = inputs()
                source["신청원본"][0][key] = 10**15 + 1
                self.assertEqual(migration.process_inputs(source)["summary"]["rejected_count"], 1)
        source = inputs()
        source["교육기준"][0]["단가"] = 10**15 + 1
        self.assertEqual(migration.process_inputs(source)["summary"]["rejected_count"], 1)
        source = inputs()
        source["출결원본"][0]["차시"] = 10**9 + 1
        self.assertEqual(migration.process_inputs(source)["summary"]["rejected_count"], 1)

    def test_discount_half_tie_has_same_reviewed_semantics(self):
        source = inputs()
        source["교육기준"][0]["단가"] = 2.5
        source["신청원본"][0].update(수량=2, 할인율=0.9)
        for mode in ["macro-only", "mixed"]:
            self.assertEqual(migration.process_inputs(source, mode)["summary"]["total_amount"], 1)

    def test_large_valid_product_and_lazy_zero_override(self):
        source = inputs()
        source["교육기준"][0]["단가"] = 10**15
        source["신청원본"][0].update(수량=10**15, 수동금액=0)
        for mode in ["macro-only", "mixed"]:
            self.assertEqual(migration.process_inputs(source, mode)["summary"]["total_amount"], 0)
        source["신청원본"][0]["수동금액"] = None
        for mode in ["macro-only", "mixed"]:
            self.assertEqual(migration.process_inputs(source, mode)["summary"]["total_amount"], 10**30)

    def test_json_preserves_identifier_and_existing_output(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            output = Path(temp) / "new"
            result = migration.process_inputs(inputs())
            migration.publish(result, output)
            raw = (output / "records.json").read_bytes()
            self.assertEqual(json.loads(raw)[0]["employee_id"], "00101")
            with self.assertRaises(migration.InputError):
                migration.publish(result, output)
            self.assertEqual((output / "records.json").read_bytes(), raw)


class MacroFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = advanced_root()
        manifest_path = cls.folder / "advanced-manifest.json"
        cls.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def assert_expected(self, result, expected):
        expected = revised_expected(expected)
        for key, value in expected.items():
            if key in result["summary"]:
                self.assertEqual(result["summary"][key], value, key)
        self.assertEqual({r["department"]: r for r in result["departments"]},
                         {r["department"]: r for r in expected["departments"]})
        actual = {r["application_id"]: r for r in result["records"]}
        self.assertEqual(len(actual), len(expected["records"]))
        for row in expected["records"]:
            self.assertEqual({key: actual[row["application_id"]][key] for key in row}, row)

    def test_macro_only_workbook_all_records_match_independent_controls(self):
        source = self.folder / self.manifest["files"]["macro_only"]
        result = migration.process_workbook(source, "macro-only")
        self.assert_expected(result, self.manifest["base_expected"])
        self.assertTrue(result["summary"]["source_unchanged"])

    def test_mixed_workbook_all_records_match_independent_controls(self):
        source = self.folder / self.manifest["files"]["mixed"]
        result = migration.process_workbook(source, "mixed", True)
        self.assert_expected(result, self.manifest["all_expected"])
        self.assertEqual(len(result["formula_steps"]), result["summary"]["approved_count"])
        self.assertEqual(len(result["lineage"]), result["summary"]["approved_count"])

    def test_both_modes_on_both_files_agree_without_cache(self):
        outputs = []
        for kind in ["macro_only", "mixed"]:
            for mode in ["macro-only", "mixed"]:
                result = migration.process_workbook(self.folder / self.manifest["files"][kind], mode, True)
                outputs.append((result["records"], result["departments"], result["rejected"], result["excluded"]))
        self.assertTrue(all(value == outputs[0] for value in outputs))


if __name__ == "__main__":
    unittest.main()
