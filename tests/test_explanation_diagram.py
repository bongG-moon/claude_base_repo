from __future__ import annotations

import copy
from html.parser import HTMLParser
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent import business_artifacts as artifacts
from company_agent import explanation_diagram as diagrams


class _HTML(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ExplanationDiagramTests(unittest.TestCase):
    @staticmethod
    def sample(kind="flow", count=3):
        raw = {"type": kind, "title": "처리 흐름 설명", "summary": "이미 수행한 작업의 기록을 설명합니다.",
               "nodes": [{"id": f"n{i}", "label": f"항목 {i + 1}", "detail": "상세 설명", "evidence": "검증 기록"} for i in range(count)],
               "edges": [{"from": f"n{i}", "to": f"n{i + 1}", "label": "다음 항목"} for i in range(count - 1)]}
        if kind == "swimlane":
            raw["lanes"] = [{"id": "owner", "label": "담당자"}, {"id": "system", "label": "시스템"}]
            for index, node in enumerate(raw["nodes"]):
                node["lane"] = "owner" if index % 2 else "system"
        return raw

    def assert_invalid(self, raw):
        with self.assertRaises(artifacts.ArtifactError) as caught:
            diagrams.normalize(raw)
        self.assertEqual("invalid_diagram", caught.exception.code)

    def test_normalization_is_repeatable_without_input_mutation(self):
        for kind in diagrams.TYPES:
            raw = self.sample(kind)
            original = copy.deepcopy(raw)
            normalized = diagrams.normalize(raw)
            self.assertEqual(original, raw)
            self.assertEqual(normalized, diagrams.normalize(normalized))
            self.assertEqual("none", normalized["motion"])
            self.assertEqual([], normalized["steps"])
            self.assertTrue(all(node["status"] == "unknown" for node in normalized["nodes"]))

    def test_nodes_edges_and_lanes_are_independent_copies(self):
        raw = self.sample("swimlane")
        raw.update(motion="steps", steps=["n0", "n2"])
        normalized = diagrams.normalize(raw)
        normalized["nodes"][0]["label"] = "수정"
        normalized["lanes"][0]["label"] = "수정"
        normalized["edges"][0]["label"] = "수정"
        normalized["steps"].append("n1")
        self.assertEqual("항목 1", raw["nodes"][0]["label"])
        self.assertEqual("담당자", raw["lanes"][0]["label"])
        self.assertEqual("다음 항목", raw["edges"][0]["label"])
        self.assertEqual(["n0", "n2"], raw["steps"])

    def test_invalid_container_and_type(self):
        for raw in (None, [], "flow", 1, True):
            self.assert_invalid(raw)
        for value in (None, [], {}, "Flow", "svg", "", True):
            self.assert_invalid({**self.sample(), "type": value})

    def test_text_required_types_and_exact_limits(self):
        for field, limit in (("title", 120), ("summary", 600)):
            self.assertEqual("가" * limit, diagrams.normalize({**self.sample(), field: "가" * limit})[field])
            for value in ("가" * (limit + 1), None, {}, [], True, 1):
                with self.subTest(field=field, value=str(value)[:20]):
                    self.assert_invalid({**self.sample(), field: value})
        for field, limit in (("label", 80), ("detail", 300), ("evidence", 300)):
            raw = self.sample()
            raw["nodes"][0][field] = "가" * limit
            self.assertEqual("가" * limit, diagrams.normalize(raw)["nodes"][0][field])
            for value in ("가" * (limit + 1), None, 1, {}, True):
                raw["nodes"][0][field] = value
                self.assert_invalid(raw)
        for location in ("title", "label"):
            for value in ("", " \n\t "):
                raw = self.sample()
                (raw if location == "title" else raw["nodes"][0])[location] = value
                self.assert_invalid(raw)

    def test_control_characters_and_lone_surrogates_rejected(self):
        for character in ("\x00", "\x01", "\x1b", "\x7f", "\x85", "\ud800", "\udfff"):
            self.assert_invalid({**self.sample(), "summary": "test" + character})
        raw = self.sample()
        raw["summary"] = "첫째\n둘째\r\n셋째\t내용"
        self.assertEqual(raw["summary"], diagrams.normalize(raw)["summary"])

    def test_unknown_fields_are_not_silently_dropped(self):
        for field in ("svg", "script", "url", "path", "html", "style", "onload", "fetch", "autoplay", "loop", "extra"):
            raw = {**self.sample(), field: "untrusted"}
            self.assert_invalid(raw)
            raw = self.sample()
            raw["nodes"][0][field] = "untrusted"
            self.assert_invalid(raw)
            raw = self.sample()
            raw["edges"][0][field] = "untrusted"
            self.assert_invalid(raw)
            raw = self.sample("swimlane")
            raw["lanes"][0][field] = "untrusted"
            self.assert_invalid(raw)

    def test_invalid_lists_and_items(self):
        for key in ("nodes", "edges", "lanes", "steps"):
            for value in ({}, "data", None, 1, True):
                self.assert_invalid({**self.sample(), key: value})
        for key, kind in (("nodes", "flow"), ("edges", "flow"), ("lanes", "swimlane")):
            for value in (None, "data", 1, [], True):
                raw = self.sample(kind)
                raw[key] = [value]
                self.assert_invalid(raw)

    def test_node_limit_and_empty(self):
        self.assert_invalid({**self.sample(), "nodes": []})
        self.assert_invalid(self.sample(count=10))
        self.assertEqual(9, len(diagrams.normalize(self.sample(count=9))["nodes"]))
        self.assertEqual(1, len(diagrams.normalize(self.sample(count=1))["nodes"]))

    def test_id_syntax_length_and_duplicate(self):
        for value in ("한글", "1node", "x x", "x,y", "x\"", "x<", "", "a" * 33, "a\n", 1, None, True):
            raw = self.sample()
            raw["nodes"][0]["id"] = value
            self.assert_invalid(raw)
        raw = self.sample(count=1)
        for value in ("a", "A_b-19", "A" * 32):
            raw["nodes"][0]["id"] = value
            self.assertEqual(value, diagrams.normalize(raw)["nodes"][0]["id"])
        raw = self.sample()
        raw["nodes"][1]["id"] = "n0"
        self.assert_invalid(raw)

    def test_status_is_explicit_and_not_inferred_from_order(self):
        for status, label in diagrams.STATUSES.items():
            raw = self.sample()
            raw["nodes"][0]["status"] = status
            raw.update(motion="steps", steps=["n2", "n0"])
            text = diagrams.render(raw, 1)
            self.assertIn(f"상태: {label}", text)
            self.assertEqual(status, diagrams.normalize(raw)["nodes"][0]["status"])
        for status in ("success", "in_progress", None, [], {}, True, 1):
            raw = self.sample()
            raw["nodes"][0]["status"] = status
            self.assert_invalid(raw)

    def test_edges_limits_labels_dangling_and_duplicate(self):
        raw = self.sample(count=9)
        raw["edges"] = [{"from": f"n{i // 9}", "to": f"n{i % 9}", "label": "연" * 80} for i in range(12)]
        self.assertEqual(12, len(diagrams.normalize(raw)["edges"]))
        raw["edges"].append({"from": "n8", "to": "n8"})
        self.assert_invalid(raw)
        for bad in ({"from": "missing", "to": "n0"}, {"from": "n0", "to": "missing"},
                    {"from": "n0"}, {"to": "n0"}, {"from": "n0", "to": "n1", "label": "a" * 81}):
            self.assert_invalid({**self.sample(), "edges": [bad]})
        raw = self.sample()
        raw["edges"].append(copy.deepcopy(raw["edges"][0]))
        self.assert_invalid(raw)
        raw["edges"] = [{"from": "n0", "to": "n0"}, {"from": "n0", "to": "n1"}, {"from": "n1", "to": "n0"}]
        self.assertEqual(3, len(diagrams.normalize(raw)["edges"]))

    def test_swimlane_requires_explicit_valid_membership(self):
        for value in ([], [{"id": "x", "label": "구역"}] * 5,
                      [{"id": "x", "label": "구역"}, {"id": "x", "label": "중복"}],
                      [{"id": "x", "label": "x" * 81}], [{"id": "x", "label": ""}]):
            raw = self.sample("swimlane")
            raw["lanes"] = value
            self.assert_invalid(raw)
        for value in ("absent", "", None, 1):
            raw = self.sample("swimlane")
            raw["nodes"][0]["lane"] = value
            self.assert_invalid(raw)
        raw = self.sample("swimlane")
        del raw["nodes"][0]["lane"]
        self.assert_invalid(raw)
        raw = self.sample()
        raw["nodes"][0]["lane"] = "owner"
        self.assert_invalid(raw)
        self.assert_invalid({**self.sample(), "lanes": [{"id": "owner", "label": "담당"}]})
        raw = self.sample("swimlane")
        raw["lanes"] += [{"id": "empty1", "label": "빈 구역1"}, {"id": "empty2", "label": "빈 구역2"}]
        self.assertEqual(4, len(diagrams.normalize(raw)["lanes"]))

    def test_motion_is_opt_in_with_explicit_unique_known_order(self):
        for value in ("auto", "loop", "Steps", None, True, [], {}):
            self.assert_invalid({**self.sample(), "motion": value})
        self.assert_invalid({**self.sample(), "motion": "steps"})
        self.assert_invalid({**self.sample(), "steps": ["n0"]})
        for steps in ([], ["n0", "n0"], ["missing"], [1], [None], ["n0"] * 10):
            self.assert_invalid({**self.sample(), "motion": "steps", "steps": steps})
        raw = {**self.sample(count=9), "motion": "steps", "steps": [f"n{i}" for i in reversed(range(9))]}
        self.assertEqual(raw["steps"], diagrams.normalize(raw)["steps"])

    def test_render_revalidates_input_and_numeric_index(self):
        for index in (-1, 10000, True, "1", None, 1.2):
            with self.assertRaises(artifacts.ArtifactError):
                diagrams.render(self.sample(), index)
        with self.assertRaises(artifacts.ArtifactError):
            diagrams.render({**self.sample(), "script": "evil"}, 0)
        self.assertIn('id="explanation-9999"', diagrams.render(self.sample(), 9999))

    def test_markup_injection_is_escaped_in_every_text_context(self):
        evil = '<script>alert("x")</script>&\"'
        raw = self.sample("swimlane")
        raw.update(title=evil, summary=evil, motion="steps", steps=["n0"])
        for node in raw["nodes"]:
            node.update(label=evil, detail=evil, evidence=evil)
        raw["edges"][0]["label"] = evil
        raw["lanes"][0]["label"] = evil
        result = diagrams.render(raw, 5)
        self.assertNotIn(evil, result)
        self.assertIn("&lt;script&gt;", result)
        parsed = _HTML(result)
        self.assertNotIn("script", [tag for tag, _ in parsed.tags])
        self.assertFalse(any(name.startswith("on") for _, attrs in parsed.tags for name in attrs))
        self.assertFalse(any(name in {"href", "src", "style"} for _, attrs in parsed.tags for name in attrs))

    def test_literal_url_evidence_is_text_never_a_fetch_or_link(self):
        raw = self.sample()
        raw["nodes"][0]["evidence"] = "https://example.invalid/private?x=1&y=2"
        source = diagrams.render(raw, 0)
        self.assertIn("https://example.invalid/private?x=1&amp;y=2", source)
        self.assertNotIn("<a ", source)
        self.assertFalse(any(tag in ("image", "img", "use", "script", "foreignobject", "iframe") for tag, _ in _HTML(source).tags))

    def test_svg_is_complete_accessible_and_has_intrinsic_geometry(self):
        for kind in diagrams.TYPES:
            raw = self.sample(kind, 9)
            source = diagrams.render(raw, 2)
            svg = ET.fromstring(re.search(r"<svg\b.*?</svg>", source, re.S).group())
            self.assertEqual("img", svg.attrib["role"])
            self.assertEqual("explanation-2-title explanation-2-desc", svg.attrib["aria-labelledby"])
            self.assertIn("viewBox", svg.attrib)
            self.assertEqual(9, sum(el.attrib.get("class") == "diagram-node" for el in svg.iter()))
            self.assertEqual(8, sum(el.tag.endswith("polygon") for el in svg.iter()))
            self.assertFalse(any(el.tag.endswith("marker") for el in svg.iter()))
            self.assertNotIn("<script", source)
            self.assertNotIn("diagram-motion", source)
            self.assertEqual(9, source.count('class="diagram-evidence"'))
            self.assertIn("실제 작업을 다시 실행하지 않습니다", source)

    def test_long_korean_content_is_preserved_and_wrapped(self):
        raw = self.sample("swimlane", 9)
        for node in raw["nodes"]:
            node.update(label="한" * 80, detail="설" * 300, evidence="근" * 300)
        raw["lanes"][0]["label"] = "역" * 80
        raw["edges"][0]["label"] = "관" * 80
        source = diagrams.render(raw, 0)
        self.assertIn("한" * 80, source)
        self.assertIn("설" * 300, source)
        self.assertIn("근" * 300, source)
        self.assertIn("관" * 80, source)
        self.assertTrue(all(len(line) <= 12 for line in diagrams._wrap("한" * 80)))
        svg = ET.fromstring(re.search(r"<svg\b.*?</svg>", source, re.S).group())
        for element in svg.iter():
            if element.attrib.get("class") == "diagram-node-label":
                self.assertEqual("한" * 80, "".join(element.itertext()))
        layout = diagrams._layout(diagrams.normalize(raw))
        self.assertGreaterEqual(layout["boxes"]["n0"][3], 7 * 24 + 72)

    def test_layouts_express_sequence_tiers_roles_and_state_ring(self):
        geometries = {}
        for kind in diagrams.TYPES:
            raw = self.sample(kind, 4)
            raw["edges"] = [{"from": "n0", "to": f"n{i}"} for i in range(1, 4)]
            geometries[kind] = diagrams._layout(diagrams.normalize(raw))
        flow = geometries["flow"]["boxes"]
        self.assertLess(flow["n0"][0], flow["n1"][0])
        self.assertEqual(flow["n0"][1], flow["n1"][1])
        structure = geometries["structure"]["boxes"]
        self.assertLess(structure["n0"][1], structure["n1"][1])
        self.assertEqual(structure["n1"][1], structure["n2"][1])
        lanes = geometries["swimlane"]["boxes"]
        self.assertEqual(lanes["n0"][1], lanes["n2"][1])
        self.assertNotEqual(lanes["n0"][1], lanes["n1"][1])
        state = geometries["state"]["boxes"]
        self.assertEqual(state["n0"][0], state["n2"][0])
        self.assertLess(state["n0"][1], state["n2"][1])

    def test_geometry_stays_bounded_with_nonoverlapping_nodes(self):
        for kind in diagrams.TYPES:
            for count in (1, 4, 9):
                raw = self.sample(kind, count)
                for node in raw["nodes"]:
                    node["label"] = "가" * 80
                layout = diagrams._layout(diagrams.normalize(raw))
                self.assertLessEqual(layout["width"], 3700)
                self.assertLessEqual(layout["height"], 3200)
                boxes = list(layout["boxes"].values())
                for index, (x, y, width, height) in enumerate(boxes):
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x + width, layout["width"])
                    self.assertLessEqual(y + height, layout["height"])
                    for bx, by, bw, bh in boxes[index + 1:]:
                        self.assertTrue(x + width <= bx or bx + bw <= x or y + height <= by or by + bh <= y)

    def test_routed_edges_avoid_all_unrelated_boxes_including_cycles(self):
        for kind in diagrams.TYPES:
            for long_labels in (False, True):
                raw = self.sample(kind, 9)
                if long_labels:
                    for node in raw["nodes"]:
                        node["label"] = "한" * 80
                # Layout is fixed here; route every directed pair including self.
                layout = diagrams._layout(diagrams.normalize(raw))
                for source in layout["boxes"]:
                    for target in layout["boxes"]:
                        with self.subTest(kind=kind, source=source, target=target, long_labels=long_labels):
                            edge = {"from": source, "to": target}
                            points = diagrams._route(layout, edge, (int(source[1:]) + int(target[1:])) % 12)
                            self.assertGreaterEqual(len(points), 2)
                            self.assertEqual(points, diagrams._route(layout, edge, (int(source[1:]) + int(target[1:])) % 12))
                            for x, y in points:
                                self.assertTrue(0 <= x <= layout["width"] and 0 <= y <= layout["height"])
                            for a, b in zip(points, points[1:]):
                                self.assertTrue(a[0] == b[0] or a[1] == b[1])
                                for key, box in layout["boxes"].items():
                                    if key not in (source, target):
                                        self.assertFalse(diagrams._intersects(a, b, box))
                            self.assertEqual(3, len(diagrams._arrow(points).split()))

    def test_structure_handles_disconnected_cycles_and_self_links(self):
        raw = self.sample("structure", 5)
        raw["edges"] = [{"from": "n0", "to": "n0"}, {"from": "n1", "to": "n2"},
                        {"from": "n2", "to": "n1"}, {"from": "n3", "to": "n4"}]
        source = diagrams.render(raw, 0)
        self.assertEqual(5, source.count('class="diagram-node"'))
        self.assertEqual(source, diagrams.render(raw, 0))

    def test_dense_relation_badges_do_not_overlap_cards_or_each_other(self):
        for kind in diagrams.TYPES:
            raw = self.sample(kind, 9)
            raw["edges"] = ([{"from": "n0", "to": f"n{i}", "label": "연결 설명 " * 10} for i in range(1, 9)] +
                            [{"from": f"n{i}", "to": "n0"} for i in range(1, 4)] + [{"from": "n0", "to": "n0"}])
            diagram = diagrams.normalize(raw)
            layout = diagrams._layout(diagram)
            source = diagrams.render(diagram, 0)
            svg = ET.fromstring(re.search(r"<svg\b.*?</svg>", source, re.S).group())
            badges = [(float(el.attrib["cx"]), float(el.attrib["cy"])) for el in svg.iter() if el.tag.endswith("circle")]
            self.assertEqual(12, len(badges))
            for index, (x, y) in enumerate(badges):
                for other in badges[index + 1:]:
                    self.assertGreaterEqual(math.dist((x, y), other), 25.98)
                for bx, by, width, height in layout["boxes"].values():
                    self.assertFalse(bx - 14 < x < bx + width + 14 and by - 14 < y < by + height + 14)

    def test_motion_markup_and_fallback_styles_keep_content_complete(self):
        raw = {**self.sample(), "motion": "steps", "steps": ["n2", "n0"]}
        source = diagrams.render(raw, 0)
        self.assertIn('data-steps="n2,n0"', source)
        self.assertIn('<div class="diagram-motion" hidden>', source)
        self.assertEqual(4, source.count("data-diagram-action="))
        self.assertIn('aria-live="polite"', source)
        self.assertNotIn('class="diagram-node" hidden', source)
        self.assertIn("prefers-reduced-motion:reduce", diagrams.CSS)
        self.assertIn("@media print", diagrams.CSS)
        self.assertIn("'Noto Sans KR'", diagrams.CSS)
        self.assertNotIn("@import", diagrams.CSS)
        self.assertNotIn("url(", diagrams.CSS)
        for forbidden in ("fetch(", "XMLHttpRequest", "setInterval", "eval(", "innerHTML", "requestAnimationFrame", "animation:"):
            self.assertNotIn(forbidden, diagrams.JS + diagrams.CSS)

    @unittest.skipUnless(shutil.which("node"), "Node.js needed for controller behavioral check")
    def test_motion_controller_no_autoplay_pause_step_reset_single_timer_and_reduced_motion(self):
        harness = r'''
const assert=require('assert');
const timers=new Map();let timerId=0;const events={},documentEvents={};
const media={matches:false,addEventListener(name,callback){this.changed=callback}};
function button(){return{disabled:false,callbacks:{},addEventListener(name,callback){this.callbacks[name]=callback},click(){if(!this.disabled)this.callbacks.click()}}}
function figure(){
 const nodes=['a','b','c'].map(id=>({dataset:{nodeId:id,label:'항목 '+id},classes:new Set(),classList:{toggle(name,value){if(value)this.owner.classes.add(name);else this.owner.classes.delete(name)}}}));
 nodes.forEach(node=>node.classList.owner=node);
 const buttons={};['play','step','pause','reset'].forEach(action=>{buttons[action]=button();buttons[action].dataset={diagramAction:action}});
 const controls={hidden:true,querySelectorAll(){return Object.values(buttons)}};
 const status={textContent:''};
 return {nodes,buttons,controls,status,dataset:{steps:'c,a,b'},querySelector(s){return s==='.diagram-motion'?controls:status},querySelectorAll(){return nodes}};
}
const figures=[figure(),figure()];
global.document={hidden:false,querySelectorAll(){return figures},addEventListener(name,callback){documentEvents[name]=callback}};
global.window={matchMedia(){return media},setTimeout(callback,delay){assert.equal(delay,1600);timers.set(++timerId,callback);return timerId},clearTimeout(id){timers.delete(id)},addEventListener(name,callback){events[name]=callback}};
function highlighted(f){return f.nodes.filter(node=>node.classes.has('is-highlighted')).map(node=>node.dataset.nodeId)}
function tick(){assert.equal(timers.size,1);const [id,callback]=timers.entries().next().value;timers.delete(id);callback()}
'''
        checks = r'''
const [first,second]=figures;
assert.equal(timers.size,0);assert.deepEqual(highlighted(first),[]);assert.equal(first.controls.hidden,false);
first.buttons.step.click();assert.deepEqual(highlighted(first),['c']);assert.equal(timers.size,0);
first.buttons.play.click();assert.deepEqual(highlighted(first),['a']);assert.equal(timers.size,1);
first.buttons.pause.click();assert.deepEqual(highlighted(first),['a']);assert.equal(timers.size,0);
first.buttons.reset.click();assert.deepEqual(highlighted(first),[]);assert.equal(timers.size,0);
first.buttons.play.click();assert.equal(timers.size,1);
second.buttons.play.click();assert.equal(timers.size,1);assert.equal(first.buttons.pause.disabled,true);
tick();assert.equal(timers.size,1);tick();assert.equal(timers.size,0);
assert.deepEqual(highlighted(second),['b']);assert.equal(second.buttons.step.disabled,true);assert.match(second.status.textContent,/설명 완료/);
second.buttons.play.click();assert.deepEqual(highlighted(second),['c']);assert.equal(timers.size,1);
document.hidden=true;documentEvents.visibilitychange();assert.equal(timers.size,0);
first.buttons.play.click();assert.equal(timers.size,1);events.beforeprint();assert.equal(timers.size,0);assert.deepEqual(highlighted(first),[]);
media.matches=true;media.changed();assert.equal(first.controls.hidden,true);first.buttons.play.click();assert.equal(timers.size,0);
media.matches=false;media.changed();assert.equal(first.controls.hidden,false);first.buttons.play.click();assert.equal(timers.size,1);
events.pagehide();assert.equal(timers.size,0);
figures.forEach(f=>assert.match(f.status.textContent,/실제 작업을 다시 실행하지 않습니다/));
'''
        result = subprocess.run([shutil.which("node"), "-e", harness + diagrams.JS + checks], capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
