"""Bounded explanation data, safe HTML and offline scenario state changes."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import report_interactions as interactions


def example():
    return {
        'title': '원래 섹션은 유지',
        'scenarios': {'title': '같은 신청을 어떻게 처리하나요?', 'items': [
            {'label': '정상 신청', 'input': '필수 항목이 채워진 신청',
             'steps': ['신청 번호로 중복을 확인합니다.', '빈자리가 있으면 배정합니다.'], 'output': '배정 결과를 반환합니다.'},
            {'label': '확인 필요', 'input': '회차가 빠진 신청',
             'steps': ['누락된 항목을 구분합니다.', '회차를 확인한 뒤 배정합니다.'], 'output': '확인이 필요한 이유를 반환합니다.'},
        ]},
        'details': [{'title': '판단 기준', 'body': '신청 내용이 불충분하면 임의 배정하지 않습니다.',
                     'bullets': ['기존 접수 기록과 비교합니다.', '확인된 범위만 표시합니다.']}],
    }


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class ReportInteractionsTests(unittest.TestCase):
    def test_optional_fields_do_not_change_ordinary_sections(self):
        row = {'title': '기존 내용', 'body': '그대로 유지'}
        before = copy.deepcopy(row)
        self.assertIsNone(interactions.validate(row))
        self.assertEqual(before, row)
        self.assertEqual('', interactions.render(row, 1))

    def test_validates_without_mutating_nested_caller_objects(self):
        row = example()
        nested = row['scenarios']
        row['scenarios']['items'][0]['label'] = '  정상 신청  '
        interactions.validate(row)
        self.assertEqual('정상 신청', row['scenarios']['items'][0]['label'])
        self.assertEqual('  정상 신청  ', nested['items'][0]['label'])
        self.assertEqual('원래 섹션은 유지', row['title'])
        stable = copy.deepcopy(row)
        interactions.validate(row)
        self.assertEqual(stable, row)

    def test_validation_failure_leaves_original_unchanged(self):
        row = example()
        row['scenarios']['title'] = '  정상화 후보  '
        row['details'][0]['body'] = ['잘못된 본문']
        before = copy.deepcopy(row)
        with self.assertRaises(ValueError):
            interactions.validate(row)
        self.assertEqual(before, row)

    def test_scenario_count_boundaries(self):
        for count in (0, 1, 2, 8, 9):
            with self.subTest(count=count):
                row = example()
                seed = row['scenarios']['items'][0]
                row['scenarios']['items'] = [{**seed, 'label': f'사례 {i}'} for i in range(count)]
                if 2 <= count <= 8:
                    interactions.validate(row)
                else:
                    with self.assertRaisesRegex(ValueError, '2~8'):
                        interactions.validate(row)

    def test_required_and_unknown_scenario_fields_are_not_silently_lost(self):
        for key in ('label', 'input', 'steps', 'output'):
            row = example()
            del row['scenarios']['items'][0][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                interactions.validate(row)
        row = example()
        row['scenarios']['items'][0]['rawHtml'] = '<b>숨은 요청</b>'
        with self.assertRaisesRegex(ValueError, '지원하지 않는'):
            interactions.validate(row)

    def test_duplicate_labels_are_rejected_after_trimming(self):
        row = example()
        row['scenarios']['items'][1]['label'] = ' 정상 신청 '
        with self.assertRaisesRegex(ValueError, '사례 이름'):
            interactions.validate(row)

    def test_text_length_boundaries_are_explicit(self):
        for key, maximum in (('label', 80), ('input', 2400), ('output', 2400)):
            row = example()
            row['scenarios']['items'][0][key] = '가' * maximum
            interactions.validate(row)
            row['scenarios']['items'][0][key] += '나'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, str(maximum)):
                interactions.validate(row)
        row = example()
        row['scenarios']['title'] = '가' * 181
        with self.assertRaises(ValueError):
            interactions.validate(row)

    def test_steps_are_bounded_nonempty_text(self):
        for invalid in ([], [''] * 2, ['가'] * 11, '단일 문자열', [None], ['가' * 801]):
            row = example()
            row['scenarios']['items'][0]['steps'] = invalid
            with self.subTest(value=repr(invalid)[:30]), self.assertRaises(ValueError):
                interactions.validate(row)
        row = example()
        row['scenarios']['items'][0]['steps'] = ['가' * 800] * 10
        interactions.validate(row)

    def test_wrong_container_and_control_characters_are_rejected(self):
        for invalid in (None, [], 'text', False):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                interactions.validate({'scenarios': invalid})
        row = example()
        row['scenarios']['items'][0]['input'] = '숨김\x00문자'
        with self.assertRaisesRegex(ValueError, '제어 문자'):
            interactions.validate(row)

    def test_details_content_and_count_boundaries(self):
        interactions.validate({'details': []})
        for valid in ({'title': '본문', 'body': '내용'}, {'title': '목록', 'bullets': ['내용']}):
            interactions.validate({'details': [valid] * 12})
        for invalid in (None, {}, [{'title': '비어 있음'}], [{'title': '비어 있음', 'body': ' ', 'bullets': []}],
                        [{'title': '너무 많음', 'body': '내용'}] * 13,
                        [{'title': '긴 설명', 'body': '가' * 6001}],
                        [{'title': '긴 목록', 'bullets': ['가'] * 21}],
                        [{'title': '큰 항목', 'bullets': ['가' * 1001]}]):
            with self.subTest(invalid=repr(invalid)[:45]), self.assertRaises(ValueError):
                interactions.validate({'details': invalid})

    def test_all_content_is_escaped_without_executable_or_external_nodes(self):
        payload = '</p><script>alert("X")</script><img src="https://invalid.test/x" onerror="bad()"> &'
        row = example()
        row['scenarios']['title'] = payload
        for item in row['scenarios']['items']:
            item['input'] = payload
            item['steps'] = [payload]
            item['output'] = payload
        row['details'] = [{'title': payload, 'body': payload, 'bullets': [payload]}]
        text = interactions.render(row, 3)
        parser = Elements(text)
        self.assertNotIn('script', [tag for tag, _ in parser.elements])
        self.assertNotIn('img', [tag for tag, _ in parser.elements])
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('&amp;', text)
        self.assertTrue(all(not any(key.startswith('on') or key in ('src', 'href') for key in attrs)
                            for _, attrs in parser.elements))

    def test_controls_reference_unique_panels_and_initial_content_is_readable(self):
        text = interactions.render(example(), 2) + interactions.render(example(), 3)
        elements = Elements(text).elements
        ids = [attrs['id'] for _, attrs in elements if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        controls = [attrs for tag, attrs in elements if tag == 'button']
        for control in controls:
            self.assertIn(control['aria-controls'], ids)
            self.assertEqual('button', control['type'])
        self.assertEqual(['true', 'false', 'true', 'false'], [x['aria-pressed'] for x in controls])
        self.assertTrue(all('hidden' not in attrs and 'aria-hidden' not in attrs for _, attrs in elements))
        self.assertNotIn('is-ready', text)
        self.assertIn('확인이 필요한 이유를 반환합니다.', text)

    def test_render_validates_index_and_does_not_mutate_inputs(self):
        row = example()
        before = copy.deepcopy(row)
        interactions.render(row, 1)
        self.assertEqual(before, row)
        for index in (0, -1, True, '1" onclick="bad()', 1.5):
            with self.subTest(index=index), self.assertRaises(ValueError):
                interactions.render(row, index)

    def test_print_motion_and_readable_fallback_styles_are_present(self):
        self.assertIn('.report-scenarios.is-ready .scenario-panel:not(.is-active)', interactions.CSS)
        self.assertIn('@media print', interactions.CSS)
        self.assertIn('.report-detail::details-content', interactions.CSS)
        self.assertIn('prefers-reduced-motion', interactions.CSS)
        self.assertIn('body[data-motion=subtle]', interactions.CSS)
        self.assertIn('max-width:760px', interactions.CSS)
        for banned in ('fetch(', 'localStorage', 'innerHTML', 'setTimeout', 'eval('):
            self.assertNotIn(banned, interactions.JS)

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for scenario controller checks')
    def test_scenario_switch_is_atomic_and_print_restores_open_details(self):
        fixture = r'''
const assert = require('node:assert/strict');
function classes(initial = []) { const state = new Set(initial); return {
  contains: x => state.has(x), add: x => state.add(x),
  toggle: (x, on) => on ? state.add(x) : state.delete(x)
}; }
function button(id) { return { attrs: {'aria-controls': id},
  getAttribute(key) { return this.attrs[key]; },
  setAttribute(key, value) { this.attrs[key] = value; },
  closest() { return this; }
}; }
const buttons = [button('s1'), button('s2')];
const panels = [{id:'s1', classList:classes()}, {id:'s2', classList:classes()}];
const handlers = {};
const group = {classList:classes(),
  querySelectorAll: selector => selector === '.scenario-panel' ? panels : buttons,
  addEventListener: (name, handler) => { handlers[name] = handler; }
};
const details = [{open:false}, {open:true}];
global.document = {querySelectorAll: selector => selector === '[data-report-scenarios]' ? [group] : details.filter(x => !x.open)};
const windowHandlers = {};
global.window = {addEventListener: (name, handler) => { windowHandlers[name] = handler; }};
'''
        checks = r'''
assert.equal(group.classList.contains('is-ready'), true);
assert.equal(panels[0].classList.contains('is-active'), true);
assert.equal(panels[1].classList.contains('is-active'), false);
handlers.click({target:buttons[1]});
assert.equal(buttons[0].attrs['aria-pressed'], 'false');
assert.equal(buttons[1].attrs['aria-pressed'], 'true');
assert.equal(panels[0].classList.contains('is-active'), false);
assert.equal(panels[1].classList.contains('is-active'), true);
handlers.click({target:{closest:() => null}});
assert.equal(panels[1].classList.contains('is-active'), true);
windowHandlers.beforeprint(); windowHandlers.beforeprint();
assert.deepEqual(details.map(x=>x.open), [true,true]);
windowHandlers.afterprint(); windowHandlers.afterprint();
assert.deepEqual(details.map(x=>x.open), [false,true]);
'''
        result = subprocess.run([shutil.which('node'), '-e', fixture + interactions.JS + checks],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
