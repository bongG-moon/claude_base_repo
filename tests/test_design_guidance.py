"""Reachability and real artifact contracts for the existing design references.

These checks do not claim to measure a model's design or Korean writing quality.
"""
from __future__ import annotations

import copy
import html
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "company-agent-plugin" / "skills"
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent import business_artifacts, ppt_html


class DesignGuidanceTests(unittest.TestCase):
    def test_changed_references_are_reachable_from_current_skill_entrypoints(self):
        for skill, references in (
            ("html-report", ("references/design-and-numbers.md", "references/explanation-diagrams.md")),
            ("presentation", ("references/design-and-quality.md",)),
        ):
            entry = SKILLS / skill / "SKILL.md"
            paths = re.findall(r"`([^`\n]+\.md)`", entry.read_text(encoding="utf-8"))
            for relative in references:
                with self.subTest(skill=skill, reference=relative):
                    self.assertIn(relative, paths)
                    target = (entry.parent / relative).resolve()
                    self.assertTrue(target.is_relative_to(SKILLS.resolve()))
                    self.assertTrue(target.is_file())
                    self.assertTrue(target.read_text(encoding="utf-8").strip())

    def test_existing_html_layouts_preserve_source_text_without_inventing_metrics(self):
        body = '확정 아님. 2026-09-27, 3 kg, 코드 x < 2. 인용: "추가 확인이 필요합니다."'
        table_label = '원문 그대로: 취소하지 않음'
        with tempfile.TemporaryDirectory() as directory:
            for layout in ("cover", "dashboard", "split", "table", "summary"):
                with self.subTest(layout=layout):
                    spec = {"title": "확인할 결정", "style": "minimalism", "mode": "scroll",
                            "facts": [{"id": "total", "op": "sum", "inputs": [{"table": [0, 0, 1]}, {"table": [0, 1, 1]}]}],
                            "sections": [{"title": "합계 {{fact:total}} kg", "layout": layout,
                                          "body": body, "takeaway": "원인은 추정이며 승인 의무는 유지됩니다.",
                                          "table": {"headers": ["기록", "kg"], "rows": [[table_label, 2], ["두 번째", 3]]}}]}
                    original = copy.deepcopy(spec)
                    output = Path(directory) / f"{layout}.html"
                    result = business_artifacts.create_html(spec, output)
                    self.assertTrue(result["ok"], result)
                    self.assertEqual(original, spec)
                    page = output.read_text(encoding="utf-8")
                    self.assertIn(f'layout-{layout}', page)
                    self.assertIn("합계 5 kg", page)
                    self.assertIn(html.escape(body, quote=True), page)
                    self.assertIn(table_label, page)
                    self.assertIn("원인은 추정이며 승인 의무는 유지됩니다.", page)
                    self.assertNotIn('<div class="kpis">', page)
                    self.assertNotIn('<svg class="report-chart"', page)
                    self.assertNotIn('<figure class="explanation-diagram"', page)
                    self.assertNotRegex(page, r'<(?:script|link)[^>]+(?:src|href)="https?://')

    def test_ppt_keeps_its_own_layout_contract_and_native_source_content(self):
        body = "2026-09-27, 3 kg. 승인되지 않았으며 원인은 추정입니다."
        for layout in ("auto", "summary", "evidence", "comparison", "actions"):
            with self.subTest(layout=layout):
                spec = {"title": "판단 근거", "facts": [{"id": "amount", "op": "value", "inputs": [3]}],
                        "slides": [{"layout": layout, "title": "검토 대상 {{fact:amount}} kg",
                                    "body": body, "source": '인용: "원문 유지"',
                                    "table": {"headers": ["기록", "수량"], "rows": [["코드 x < 2", 3]]}}]}
                original = copy.deepcopy(spec)
                data, _, _, _, _ = ppt_html.prepare(spec)
                self.assertEqual(original, spec)
                row = data["sections"][0]
                self.assertEqual(layout, row["layout"])
                self.assertEqual("검토 대상 3 kg", row["title"])
                self.assertEqual(body, row["body"])
                self.assertEqual('인용: "원문 유지"', row["source"])
                self.assertEqual([], row["kpis"])
                self.assertEqual("Malgun Gothic", data["presentationFont"])
                elements = data["presentationPlan"]["pages"][0]["elements"]
                self.assertTrue(any(element["kind"] == "table" for element in elements))
                self.assertTrue(any(element.get("text") == body for element in elements))
                self.assertFalse(any(element["kind"] in ("image", "chart") for element in elements))


if __name__ == "__main__":
    unittest.main()
