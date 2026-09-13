import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent.business_artifacts import create_html, STYLES


class ReportDesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "report.html"

    def tearDown(self):
        self.temp.cleanup()

    def spec(self):
        return {"title": "실적 검토", "mode": "slides", "facts": [
            {"id": "actual", "op": "sum", "inputs": [{"table": [1, i, 1]} for i in range(3)], "expected": 530, "unit": "백만원"},
            {"id": "target", "op": "sum", "inputs": [{"table": [1, i, 2]} for i in range(3)]},
            {"id": "rate", "op": "ratio", "inputs": [{"fact": "actual"}, {"fact": "target"}], "decimals": 2, "unit": "%"},
            {"id": "chartTotal", "op": "sum", "inputs": [{"chart": [2, 0, i]} for i in range(3)]}],
            "checks": [{"left": "actual", "right": "chartTotal"}], "sections": [
                {"title": "달성률 {{fact:rate}}%", "layout": "cover", "body": "실적 {{fact:actual}}백만원",
                 "kpis": [{"fact": "actual"}, {"fact": "rate"}]},
                {"title": "원자료", "layout": "table", "table": {"headers": ["월", "실적", "목표"], "rows": [["6월",145,150],["7월",175,150],["8월",210,150]]}},
                {"title": "추이", "layout": "split", "chart": {"title": "실적 추이", "type": "column", "categories": ["6월", "7월", "8월"], "series": [{"name": "실적", "values": [145,175,210]}]}}]}

    def test_original_510_error_blocks_publication(self):
        spec = self.spec(); spec["facts"][0]["expected"] = 510
        result = create_html(spec,self.output)
        self.assertEqual(result["code"], "numeric_validation_failed")
        self.assertFalse(self.output.exists())

    def test_one_calculation_binds_title_body_and_kpis(self):
        result = create_html(self.spec(), self.output)
        self.assertTrue(result["ok"], result)
        text = self.output.read_text(encoding="utf-8")
        self.assertIn("달성률 117.78%", text)
        self.assertIn("실적 530백만원", text)
        self.assertNotIn("{{fact:", text)
        self.assertIn('class="kpi-value">530', text)
        self.assertEqual(result["validation"]["crossChecks"],1)
        self.assertEqual(result["validation"]["visual"],"not_verified")
        self.assertEqual(result["validation"]["sourceAccuracy"],"not_verified")

    def test_cross_view_mismatch_blocks_publication(self):
        spec=self.spec(); spec["sections"][2]["chart"]["series"][0]["values"][0]=125
        self.assertEqual(create_html(spec,self.output)["code"],"numeric_validation_failed")
        self.assertFalse(self.output.exists())

    def test_actual_svg_for_each_supported_chart(self):
        for kind in ("column","bar","line","pie"):
            with self.subTest(kind=kind):
                spec=self.spec(); spec["sections"][2]["chart"]["type"]=kind
                output=self.output.with_name(kind+".html")
                self.assertTrue(create_html(spec,output)["ok"])
                text=output.read_text(encoding="utf-8")
                svg=re.search(r"<svg\b.*?</svg>",text,re.S).group()
                root=ET.fromstring(svg)
                self.assertEqual(root.attrib["role"],"img")
                self.assertIn("530", text)
                self.assertIn('<details class="chart-values">',text)
                self.assertIn("polyline" if kind=="line" else "path" if kind=="pie" else "rect",svg)
                self.assertNotRegex(svg,r'="(?:nan|inf|-inf)')

    def test_negative_zero_single_point_and_single_slice(self):
        for kind, values in (("column",[-10,0,20]),("bar",[-10,0,20]),("line",[0]),("column",[0]),("pie",[100])):
            spec={"sections":[{"chart":{"type":kind,"categories":[str(i) for i in range(len(values))],"series":[{"name":"값","values":values}]}}]}
            output=self.output.with_name(kind+str(len(values))+".html")
            result=create_html(spec,output);self.assertTrue(result["ok"],result)
            svg=re.search(r"<svg\b.*?</svg>",output.read_text(encoding="utf-8"),re.S).group()
            root=ET.fromstring(svg)
            for node in root.iter():
                for attr in ("width","height","r"):
                    if attr in node.attrib:self.assertGreaterEqual(float(node.attrib[attr]),0)

    def test_missing_cyclic_bool_nonfinite_and_zero_denominator_are_rejected(self):
        bad_facts=[
            [{"id":"x","inputs":[{"fact":"x"}]}],
            [{"id":"x","inputs":[True]}],
            [{"id":"x","inputs":[float("nan")]}],
            [{"id":"x","inputs":[{"table":[-1,0,0]}]}],
            [{"id":"x","op":"ratio","inputs":[10,0]}],
            [{"id":"x","inputs":[1],"decimals":True}],
            [{"id":"x","inputs":[1]},{"id":"x","inputs":[1]}],
        ]
        for facts in bad_facts:
            with self.subTest(facts=facts):
                result=create_html({"facts":facts,"sections":[{"title":"검사"}]},self.output)
                self.assertFalse(result["ok"]);self.assertFalse(self.output.exists())

    def test_bad_binding_kpi_and_layout_are_rejected(self):
        for row in ({"body":"{{fact:missing}}"},{"body":"{{fact:bad text}}"},{"kpis":[{"fact":"missing"}]},{"layout":"<script>"}):
            self.assertFalse(create_html({"sections":[row]},self.output)["ok"])
            self.assertFalse(self.output.exists())

    def test_escaping_new_fields_and_svg_text(self):
        evil='</script><img src=x onerror=alert(1)>'
        spec=self.spec();spec["facts"][0]["label"]=evil;spec["facts"][0]["unit"]= '<img src=x>'
        row=spec["sections"][2];row.update(eyebrow=evil,takeaway=evil,source=evil)
        row["chart"]["title"]=evil;row["chart"]["categories"][0]=evil
        self.assertTrue(create_html(spec,self.output)["ok"])
        text=self.output.read_text(encoding="utf-8")
        self.assertNotIn(evil,text);self.assertEqual(text.count('<script>'),1)
        self.assertNotRegex(text,r'<(?:img|script)\b[^>]*src="?https?')
        ET.fromstring(re.search(r"<svg\b.*?</svg>",text,re.S).group())

    def test_styles_change_layout_and_kpi_treatment(self):
        hashes=set()
        for style in STYLES:
            spec=self.spec();spec["style"]=style
            output=self.output.with_name(style+".html")
            self.assertTrue(create_html(spec,output)["ok"])
            hashes.add(hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(len(hashes),8)
        text=output.read_text(encoding="utf-8")
        self.assertIn('layout-cover',text);self.assertIn('layout-split',text)
        self.assertIn('grid-template-columns:1.2fr 1fr',text)

    def test_no_facts_is_not_numerical_verification(self):
        result=create_html({"sections":[{"body":"합계 510"}]},self.output)
        self.assertTrue(result["ok"])
        self.assertEqual(result["validation"]["arithmetic"],"not_provided")
        self.assertEqual(result["validation"]["freeTextClaims"],"not_verified")
        self.assertTrue(result["warnings"])

    def test_difference_growth_and_rounding(self):
        spec={"facts":[{"id":"growth","op":"percent_change","inputs":[210,175],"decimals":2},
                       {"id":"diff","op":"difference","inputs":[210,175]},
                       {"id":"round","op":"value","inputs":["1.005"],"decimals":2,"expected":"1.01"}],
              "sections":[{"body":"{{fact:growth}} / {{fact:diff}} / {{fact:round}}"}]}
        self.assertTrue(create_html(spec,self.output)["ok"])
        self.assertIn('20.00 / 35 / 1.01',self.output.read_text(encoding="utf-8"))

    def test_skill_requires_design_reference_and_distinct_checks(self):
        skill=ROOT/'company-agent-plugin/skills/html-report/SKILL.md'
        text=skill.read_text(encoding='utf-8')
        self.assertIn('references/design-and-numbers.md',text)
        self.assertIn('current Skill catalog',text)
        self.assertIn('not only individual input rows',text)
        guide=(skill.parent/'references/design-and-numbers.md').read_text(encoding='utf-8')
        example=json.loads(re.search(r'```json\n(.*?)\n```',guide,re.S).group(1))
        self.assertTrue(create_html(example,self.output)['ok'])


if __name__ == '__main__':
    unittest.main()
