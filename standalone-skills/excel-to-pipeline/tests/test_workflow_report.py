"""Offline presentation of observed lineage, not invented business execution."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workflow_report import build_workflow, render_workflow, table_name, MAX_NODES, MAX_EDGES
import workflow_report
from excel_pipeline import analyze, publish, InputError
from project_selection import select_result
from test_fixture_paths import fixture_root


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.links, self.ids = [], [], set()
        self.graph_cards = 0
        self.detail_cards = 0

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "node" in attrs.get("class", "").split():
            self.graph_cards += 1
        if "detail" in attrs.get("class", "").split():
            self.detail_cards += 1
        if "href" in attrs:
            self.links.append(attrs["href"])
        if "id" in attrs:
            self.ids.add(attrs["id"])


class WorkflowReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze(fixture_root() / "complex_workbook.xlsx")

    def test_edges_equal_observed_table_dependencies(self):
        model = build_workflow(self.result)
        by_key = {n["key"]: n for n in model["nodes"]}
        observed = {(by_key[s]["id"], by_key[t]["id"]) for s, t in model["edges"]
                    if not by_key[s]["outside"]}
        expected = {(dependency, stage["table"]) for stage in self.result["pipeline_plan"]["stages"]
                    for dependency in stage["depends_on_tables"]}
        self.assertEqual(expected, observed)
        self.assertTrue(observed)
        self.assertTrue(all(n["alias"] == n["id"] for n in model["nodes"] if not n["outside"]))

    def test_existing_identifiers_are_not_renamed_even_after_selection(self):
        result = {"tables": [
            {"id": "s03_t07", "sheet": "신청", "range": "A1:B3", "columns": []},
            {"id": "ApprovedRevenue", "sheet": "매출", "range": "A1:B3", "columns": []}],
            "pipeline_plan": {"stages": [
                {"table": "s03_t07", "depends_on_tables": []},
                {"table": "ApprovedRevenue", "depends_on_tables": ["s03_t07"]}]}}
        before = copy.deepcopy(result)
        model = build_workflow(result)
        self.assertEqual(["s03_t07", "ApprovedRevenue"], [n["alias"] for n in model["nodes"]])
        self.assertEqual([("n0", "n1")], model["edges"])
        page = render_workflow(result)
        self.assertIn("신청 테이블 (s03_t07)", page)
        self.assertIn("매출 테이블 (ApprovedRevenue)", page)
        self.assertEqual(before, result)
        result["tables"] = result["tables"][1:]
        self.assertEqual("ApprovedRevenue", build_workflow(result)["nodes"][0]["alias"])

    def test_names_use_labels_not_row_contents_and_do_not_mutate_source(self):
        result = copy.deepcopy(self.result)
        table = result["tables"][0]
        table["sheet"] = "Sheet1"
        table["columns"] = ["신청번호", "과정명", "부서"]
        table["rows"] = [["SECRET-DATA-DO-NOT-EXPORT", "010-1234-5678"]]
        before = copy.deepcopy(result)
        html = render_workflow(result)
        self.assertIn("신청 현황 테이블", html)
        self.assertNotIn("SECRET-DATA-DO-NOT-EXPORT", html)
        self.assertNotIn("010-1234-5678", html)
        self.assertEqual(before, result)

    def test_unreviewed_and_reviewed_names_are_distinct(self):
        name, basis = table_name({"sheet": "Sheet1", "columns": ["고객", "구분"]})
        self.assertEqual("고객 정보 테이블", name)
        self.assertIn("추정", basis)
        self.assertEqual(("입고 승인 대상 테이블", "확인한 명세의 이름"),
                         table_name({"display_name": "입고 승인 대상 테이블"}))
        self.assertEqual("데이터 테이블", table_name({"sheet": "Sheet1", "columns": []})[0])
        self.assertEqual("데이터 테이블", table_name({"sheet": "Sheet1", "columns": ["column_A", "column_B"]})[0])
        self.assertEqual("실적 테이블", table_name({"sheet": "실적", "columns": ["신청", "수료", "성과"]})[0])
        self.assertEqual("교육 과정 기준 테이블", table_name({"sheet": "기준표", "columns": ["과정코드", "과정명"]})[0])
        self.assertEqual("부서 예산 테이블", table_name({"sheet": "기준표", "columns": ["부서", "예산"]})[0])

    def test_plan_name_is_validated_and_propagated(self):
        table = self.result["tables"][0]
        spec = {key: table[key] for key in ("id", "sheet", "range", "header_rows")}
        spec["display_name"] = "교육비 검토 테이블"
        result = analyze(fixture_root() / "complex_workbook.xlsx", {"tables": [spec]})
        self.assertEqual("교육비 검토 테이블", build_workflow(result)["nodes"][0]["name"])
        spec["display_name"] = "bad\nname"
        with self.assertRaises(InputError):
            analyze(fixture_root() / "complex_workbook.xlsx", {"tables": [spec]})

    def test_html_escapes_workbook_labels_and_has_no_active_content(self):
        result = copy.deepcopy(self.result)
        result["tables"][0]["display_name"] = '<script>alert("name")</script>'
        result["summary"]["source_name"] = 'source<img src=x onerror=alert(1)>.xlsx'
        html = render_workflow(result)
        parser = ReportParser()
        parser.feed(html)
        self.assertNotIn("script", parser.tags)
        self.assertNotIn("img", parser.tags)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("font-family:'Noto Sans KR'", html)
        self.assertIn("data:font/woff;base64,d09GRg", html)
        self.assertTrue(all(link.startswith("#") and link[1:] in parser.ids for link in parser.links))
        self.assertIn("SIL OPEN FONT LICENSE", html)

    def test_selected_result_keeps_outside_references_visible(self):
        selected = select_result(self.result, ["집계!D8"])
        model = build_workflow(selected)
        self.assertEqual(["집계!D8"], model["selection"])
        self.assertEqual(1, model["table_count"])
        self.assertTrue(any(n["outside"] for n in model["nodes"]))
        self.assertTrue(model["edges"])

    def test_cycle_is_not_presented_as_linear_calculation_order(self):
        result = copy.deepcopy(self.result)
        tables = result["tables"][:2]
        result["tables"] = tables
        result["pipeline_plan"]["stages"] = [
            {"table": tables[0]["id"], "depends_on_tables": [tables[1]["id"]]},
            {"table": tables[1]["id"], "depends_on_tables": [tables[0]["id"]]}]
        model = build_workflow(result)
        self.assertTrue(all(n["intertwined"] for n in model["nodes"]))
        self.assertEqual(1, len({n["rank"] for n in model["nodes"]}))
        self.assertIn("상호 참조", " ".join(model["warnings"]))

    def test_missing_plan_and_vba_remain_unknown(self):
        result = copy.deepcopy(self.result)
        result["pipeline_plan"] = {}
        result["summary"]["vba"] = {"status": "extracted"}
        model = build_workflow(result)
        self.assertFalse(model["edges"])
        self.assertTrue(all(n["missing_plan"] for n in model["nodes"]))
        self.assertTrue(all(n["role"] == "unknown" for n in model["nodes"]))
        self.assertTrue(any("VBA" in warning for warning in model["warnings"]))

    def test_graph_limits_disclose_omitted_nodes_and_edges(self):
        result = {"sheets": [{"name": "Sheet1"}], "tables": [], "pipeline_plan": {"stages": []}}
        for i in range(80):
            result["tables"].append({"id": f"s01_t{i+1:02d}", "sheet": "Sheet1", "range": "A1:B2", "columns": []})
            result["pipeline_plan"]["stages"].append({"table": f"s01_t{i+1:02d}",
                                                   "depends_on_tables": [f"s01_t{j+1:02d}" for j in range(i)]})
        model = build_workflow(result)
        self.assertEqual(MAX_NODES, len(model["nodes"]))
        self.assertEqual(MAX_EDGES, len(model["edges"]))
        self.assertGreater(model["omitted_tables"], 0)
        self.assertGreater(model["omitted_edges"], 0)
        self.assertTrue(any("표시 한도" in warning for warning in model["warnings"]))
        # Classification uses all observed edges, not the displayed prefix.
        result["pipeline_plan"]["stages"][0]["formula_columns"] = [{"formula_count": 1}]
        all_model = build_workflow(result)
        self.assertNotEqual("output", all_model["nodes"][0]["role"])
        # An outgoing edge to a table beyond the node cap also prevents endpoint labeling.
        for stage in result["pipeline_plan"]["stages"]:
            stage["depends_on_tables"] = []
        result["pipeline_plan"]["stages"][-1]["depends_on_tables"] = ["s01_t01"]
        capped = build_workflow(result)
        self.assertNotEqual("output", capped["nodes"][0]["role"])

    def test_project_creation_only_no_workflow_cost_during_plain_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish(self.result, root / "project")
            self.assertTrue((root / "project/업무흐름.html").is_file())
            publish(self.result, root / "run", emit_project=False)
            self.assertFalse((root / "run/업무흐름.html").exists())

    def test_disconnected_tables_stay_in_details_not_in_graph(self):
        result = copy.deepcopy(self.result)
        result["pipeline_plan"] = {"stages": []}
        html = render_workflow(result)
        parser = ReportParser()
        parser.feed(html)
        self.assertEqual(0, parser.graph_cards)
        self.assertEqual(len(result["tables"]), parser.detail_cards)
        self.assertIn("표 간 연결을 확인하지 못했습니다", html)
        self.assertIn("max-height:780px", html)

    def test_same_sheet_tables_with_same_name_get_header_qualifiers(self):
        result = copy.deepcopy(self.result)
        result["tables"] = result["tables"][:2]
        for table in result["tables"]:
            table["sheet"] = "교육기준"
        result["tables"][0]["columns"] = ["과정코드", "과정명"]
        result["tables"][1]["columns"] = ["회차", "정원"]
        names = [n["name"] for n in build_workflow(result)["nodes"] if not n["outside"]]
        self.assertNotEqual(names[0], names[1])
        self.assertIn("과정코드", names[0])
        self.assertIn("회차", names[1])

    @staticmethod
    def explanation_result(formulas, columns=None, source_rows=None):
        columns = columns or ["수량", "단가", "금액", "검토"]
        return {"tables": [{"id": "sales_source", "sheet": "매출", "range": "C1:F12",
                             "header_rows": 1, "columns": columns,
                             "source_rows": source_rows if source_rows is not None else [2, 4, 5, 6, 7, 8],
                             "rows": [["PRIVATE-ROW-DO-NOT-EXPORT"]],
                             "source_cells": {"C2": "PRIVATE-SOURCE-CELL"}}],
                "formulas": [{"sheet": "매출", "cell": cell, "formula": formula,
                              "status": status, "dependencies": [],
                              "value": "PRIVATE-COMPUTED", "cached_value": "PRIVATE-CACHED"}
                             for cell, formula, status in formulas],
                "pipeline_plan": {"stages": [{"table": "sales_source", "depends_on_tables": [],
                    "formula_columns": [{"column": "금액", "formula_count": len(formulas),
                                         "unresolved": sum(status != "computed" for _, _, status in formulas),
                                         "functions": []}]}]}}

    def test_formula_groups_preserve_actual_columns_sparse_ranges_and_different_rules(self):
        result = self.explanation_result([
            ("E2", "=C2*D2", "computed"), ("E4", "=C4*D4", "computed"),
            ("E5", "=C5*10", "computed"), ("E6", "=C6*20", "computed"),
            ("E7", "=C$2*D7", "computed"), ("E8", "=C8*D8", "computed"),
            ("D4", "=10+5", "computed")])
        before = copy.deepcopy(result)
        info = build_workflow(result)["nodes"][0]["explanation"]
        self.assertEqual(["C", "D", "E", "F"], [c["column"] for c in info["columns"]])
        self.assertIn("원본 입력", info["columns"][1]["mode"])
        groups = [g for g in info["groups"] if g["column"] == "E"]
        self.assertEqual(4, len(groups))
        self.assertEqual("E2, E4, E8", groups[0]["range"])
        self.assertEqual(3, groups[0]["count"])
        self.assertIn("수량", " ".join(groups[0]["refs"]))
        self.assertIn("단가", " ".join(groups[0]["refs"]))
        self.assertIn("두 값을 곱합니다", " ".join(groups[0]["steps"]))
        self.assertTrue(any("$2" in g["formula"] for g in groups))
        self.assertEqual(before, result)

    def test_formula_strings_and_data_values_are_not_published(self):
        result = self.explanation_result([
            ("F2", '=IF(C2>0,"secret-first","secret-return")', "computed"),
            ("F4", '=IF(C4>0,"secret-second","secret-return")', "computed"),
            ("F5", '="unfinished-secret', "unsupported")],
            columns=["수량", "단가", '<script>alert("header")</script>', "검토"])
        info = build_workflow(result)["nodes"][0]["explanation"]
        self.assertEqual(3, info["group_count"])
        html = render_workflow(result)
        for text in ("secret-first", "secret-second", "secret-return", "unfinished-secret",
                     "PRIVATE-ROW-DO-NOT-EXPORT", "PRIVATE-SOURCE-CELL", "PRIVATE-COMPUTED", "PRIVATE-CACHED"):
            self.assertNotIn(text, html)
        self.assertIn("문자 상수 가림", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn('class="table-explanation"', html)
        self.assertIn('class="column-details"', html)
        self.assertIn('class="formula-details" open', html)

    def test_header_and_excluded_row_formulas_do_not_claim_data_column_computation(self):
        result = self.explanation_result([("E1", "=C1", "computed"),
                                          ("E3", "=C3*D3", "computed")], source_rows=[2, 4])
        info = build_workflow(result)["nodes"][0]["explanation"]
        self.assertIn("원본 입력/빈칸", info["columns"][2]["mode"])
        self.assertIn("데이터행 밖 수식", info["columns"][2]["mode"])
        self.assertNotIn("수식 계산", info["columns"][2]["mode"])
        self.assertEqual(["E1", "E3"], [group["range"] for group in info["groups"]])

    def test_missing_formula_records_do_not_label_planned_calculation_as_plain_input(self):
        result = self.explanation_result([("E2", "=C2*D2", "computed")])
        result["pipeline_plan"]["stages"][0]["formula_columns"][0]["formula_count"] = 3
        column = build_workflow(result)["nodes"][0]["explanation"]["columns"][2]
        self.assertIn("수식 기록 불완전", column["mode"])
        result["formulas"] = []
        column = build_workflow(result)["nodes"][0]["explanation"]["columns"][2]
        self.assertIn("수식 기록 불완전", column["mode"])
        self.assertNotIn("원본 입력/빈칸", column["mode"])

    def test_computed_formula_with_unsupported_branch_stays_unverified(self):
        result = self.explanation_result([
            ("E2", '=IF(1=1,2,WEBSERVICE("https://secret.invalid/token"))', "computed"),
            ("E4", "=1/0", "error"), ("E5", "=SUM(OtherTable[Amount])", "unsupported")])
        groups = build_workflow(result)["nodes"][0]["explanation"]["groups"]
        self.assertEqual(["WEBSERVICE"], groups[0]["unsupported_functions"])
        self.assertEqual(1, groups[1]["unresolved"])
        self.assertFalse(groups[2]["parsed"])
        page = render_workflow(result)
        self.assertIn("미지원 함수: WEBSERVICE", page)
        self.assertIn("대표식을 자동 해석하지 못했습니다", page)
        self.assertIn("모든 분기가 실행된다는 뜻은 아닙니다", page)
        self.assertNotIn("secret.invalid", page)

    def test_explanation_limits_are_explicit_without_dropping_actual_formula_count(self):
        result = self.explanation_result([(f"E{row}", f"=C{row}*{row}", "computed") for row in range(2, 10)])
        with patch.object(workflow_report, "MAX_DETAIL_COLUMNS", 2), \
             patch.object(workflow_report, "MAX_FORMULA_GROUPS", 2), \
             patch.object(workflow_report, "MAX_EXPLAIN_FORMULAS", 5):
            info = build_workflow(result)["nodes"][0]["explanation"]
            self.assertEqual(8, info["formula_count"])
            self.assertEqual(5, info["group_count"])
            self.assertEqual(2, info["omitted_columns"])
            self.assertEqual(3, info["omitted_groups"])
            self.assertEqual(3, info["omitted_formulas"])
            page = render_workflow(result)
            self.assertIn("계산 묶음 3개", page)
            self.assertIn("분석 예산 밖 수식 3개", page)
            self.assertIn("열 표시 한도", page)

    def test_real_fixture_formula_counts_match_without_extra_workbook_access(self):
        with patch("openpyxl.load_workbook", side_effect=AssertionError("must not reopen workbook")):
            model = build_workflow(self.result)
        calculated = [n for n in model["nodes"] if not n["outside"] and n["explanation"]["formula_count"]]
        self.assertTrue(calculated)
        for node in calculated:
            info = node["explanation"]
            self.assertEqual(node["formulas"], info["formula_count"])
            self.assertGreater(info["group_count"], 0)
            self.assertLessEqual(info["group_count"], info["formula_count"])

    def test_ast_and_analysis_references_are_deduplicated_keep_first_anchor_display(self):
        result = self.explanation_result([("E2", "=SUM($C$2:$C$4)", "computed")])
        result["formulas"][0]["dependencies"] = [{"sheet": "매출", "range": "C2:C4"}]
        refs = build_workflow(result)["nodes"][0]["explanation"]["groups"][0]["refs"]
        self.assertEqual(1, len(refs))
        self.assertIn("$C$2:$C$4", refs[0])

    def test_common_function_argument_roles_explain_actual_inputs_without_values(self):
        result = self.explanation_result([
            ("F2", '=SUMIFS($C$2:$C$8,$D$2:$D$8,E2,$E$2:$E$8,">SECRET")', "computed"),
            ("F4", "=ROUND(C4*D4,2)", "computed")])
        groups = build_workflow(result)["nodes"][0]["explanation"]["groups"]
        first = " ".join(groups[0]["steps"])
        self.assertIn("합계 범위: 매출!$C$2:$C$8", first)
        self.assertIn("조건 범위 매출!$D$2:$D$8", first)
        self.assertIn("조건 매출!E2", first)
        self.assertIn("모든 조건을 만족하는 행", first)
        self.assertIn("문자 상수(내용 가림)", first)
        self.assertNotIn("SECRET", first)
        second = " ".join(groups[1]["steps"])
        self.assertIn("수량", second)
        self.assertIn("단가", second)
        self.assertIn("자릿수는 2", second)

    def test_common_cautions_appear_once_per_table_and_branch_note_only_when_needed(self):
        result = self.explanation_result([
            ("F2", '=IF(C2>0,1,0)', "computed"), ("F4", '=IF(C4>1,2,0)', "computed"),
            ("F5", '=ROUND(C5,2)', "computed")])
        page = render_workflow(result)
        self.assertEqual(1, page.count("모든 분기가 실행된다는 뜻은 아닙니다"))
        self.assertEqual(1, page.count("실제 Excel 실행 결과와 동일하다는 검증을 대신하지 않습니다"))
        result = self.explanation_result([("F2", "=SUM(C2:D2)", "computed")])
        self.assertNotIn("모든 분기가 실행된다는 뜻은 아닙니다", render_workflow(result))


if __name__ == "__main__":
    unittest.main()
