"""Picker markup and real controller behavior without a browser or HTTP server.

The DOM fixture is derived from the generated picker rather than recreating its
choices. It checks state and clipboard behavior, not rendered layout or fonts.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import report_styles


class _PickerDOM(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        node = {'tag': tag, 'attrs': dict(attributes), 'parent': self.stack[-1] if self.stack else None, 'text': ''}
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append(len(self.nodes) - 1)

    def handle_endtag(self, tag):
        for offset in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[offset]]['tag'] == tag:
                del self.stack[offset:]
                break

    def handle_data(self, data):
        if self.stack:
            self.nodes[self.stack[-1]]['text'] += data

    def by_id(self, identity):
        return next(node for node in self.nodes if node['attrs'].get('id') == identity)

    def ancestors(self, node):
        parent = node['parent']
        while parent is not None:
            yield self.nodes[parent]
            parent = self.nodes[parent]['parent']

    def with_class(self, name):
        return [node for node in self.nodes if name in node['attrs'].get('class', '').split()]


NODE_FIXTURE = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const actions = [], writes = [], listeners = {};
function matches(element, selector) {
  return selector.split(',').some(part => {
    part = part.trim();
    if (part.startsWith('.')) return element.classList.contains(part.slice(1));
    if (part.startsWith('#')) return element.id === part.slice(1);
    if (/^\[[\w-]+\]$/.test(part)) return element.hasAttribute(part.slice(1, -1));
    if (/^[a-z]+$/.test(part)) return element.tagName === part.toUpperCase();
    throw new Error('Unsupported fixture selector: ' + part);
  });
}
class Element {
  constructor(raw) {
    this.tagName = raw.tag.toUpperCase(); this.attrs = {...raw.attrs};
    this.id = this.attrs.id || ''; this.dataset = {}; this.children = [];
    this.handlers = {}; this.parentElement = null; this._text = raw.text;
    this.style = {setProperty(name, value) {this[name] = value;}, removeProperty(name) {delete this[name];}};
    this.open = this.hasAttribute('open'); this.hidden = this.hasAttribute('hidden');
    this.classList = {contains: name => (this.attrs.class || '').split(/\s+/).includes(name)};
    this.clientWidth = this.classList.contains('mini-window') ? 480 : 960;
    this.scrollHeight = 900;
    for (const [name, value] of Object.entries(this.attrs)) {
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    }
  }
  get textContent() {return this._text + this.children.map(child => child.textContent).join('');}
  set textContent(value) {this._text = String(value); this.children = [];}
  get text() {return this.textContent;}
  get options() {return this.children.filter(child => child.tagName === 'OPTION');}
  get selectedIndex() {
    if (this._selectedIndex !== undefined) return this._selectedIndex;
    const marked = this.options.findIndex(option => option.hasAttribute('selected'));
    return marked < 0 ? 0 : marked;
  }
  set selectedIndex(value) {this._selectedIndex = value;}
  get value() {
    if (this.tagName === 'SELECT') return this.options[this.selectedIndex]?.value || '';
    return this._value ?? this.attrs.value ?? (this.tagName === 'TEXTAREA' ? this.textContent : '');
  }
  set value(value) {
    if (this.tagName === 'SELECT') this.selectedIndex = this.options.findIndex(option => option.value === value);
    else this._value = value;
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
  }
  getAttribute(name) {return this.attrs[name] ?? null;}
  hasAttribute(name) {return Object.hasOwn(this.attrs, name);}
  removeAttribute(name) {delete this.attrs[name];}
  addEventListener(name, handler) {(this.handlers[name] ||= []).push(handler);}
  async fire(name) {for (const handler of this.handlers[name] || []) await handler({target: this, currentTarget: this});}
  closest(selector) {
    for (let item = this; item; item = item.parentElement) if (matches(item, selector)) return item;
    return null;
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(matches(child, selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
  focus() {actions.push(['focus', this.id, ids['prompt-details']?.open]);}
  select() {actions.push(['select', this.id, ids['prompt-details']?.open]);}
  scrollIntoView() {actions.push(['scrollIntoView', this.id]);}
}
const elements = rawNodes.map(raw => new Element(raw));
rawNodes.forEach((raw, index) => {
  if (raw.parent !== null) {
    elements[index].parentElement = elements[raw.parent];
    elements[raw.parent].children.push(elements[index]);
  }
});
const ids = Object.fromEntries(elements.filter(item => item.id).map(item => [item.id, item]));
const all = selector => elements.filter(item => matches(item, selector));
const document = {getElementById: id => ids[id] || null, querySelectorAll: all,
  querySelector: selector => all(selector)[0] || null, fonts: {ready: Promise.resolve()}};
const navigator = clipboardMode === 'missing' ? {} : {clipboard: {async writeText(value) {
  if (clipboardMode === 'reject') throw new Error('Clipboard denied');
  writes.push(value);
}}};
const context = {document, navigator, location: {hash: '#additional-designs'},
  window: {addEventListener: (name, handler) => {listeners[name] = handler;},
    scrollTo: (...args) => actions.push(['scrollTo', ...args]), scrollBy: (...args) => actions.push(['scrollBy', ...args])}};
vm.runInNewContext(controller, context);
const buttons = all('[data-choice]');
const choose = async value => {
  const button = buttons.find(item => item.dataset.choice === value);
  assert.ok(button, 'Missing choice ' + value);
  await button.fire('click');
  for (const item of buttons) {
    const selected = item.dataset.choice === value;
    assert.equal(item.getAttribute('aria-pressed'), String(selected));
    const card = item.closest('.design-card, .reference-card, .template-callout');
    if (card) assert.equal(card.dataset.selected, String(selected));
  }
  const displayName = ids['selected-design'].textContent.trim();
  assert.ok(displayName.length > 0 && button.dataset.label.includes(displayName),
    'The selection panel must identify the selected design');
};
const change = async (id, value) => {ids[id].value = value; await ids[id].fire('change');};
'''


class ReportPickerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = report_styles.picker_html()
        cls.dom = _PickerDOM(cls.document)

    def test_all_designs_are_visible_and_selection_precedes_gallery(self):
        gallery = self.dom.by_id('additional-designs')
        self.assertEqual('section', gallery['tag'])
        self.assertNotIn('hidden', gallery['attrs'])
        self.assertFalse(any(node['tag'] == 'details' for node in self.dom.ancestors(gallery)))
        cards = self.dom.with_class('design-card')
        self.assertEqual(10, len(cards))
        for card in cards:
            self.assertIn(gallery, list(self.dom.ancestors(card)))
        panel, = self.dom.with_class('selection-panel')
        self.assertEqual('aside', panel['tag'])
        self.assertLess(self.dom.nodes.index(panel), self.dom.nodes.index(gallery))
        for name in ('picker-header', 'picker-hero', 'picker-gallery'):
            self.assertEqual(1, len(self.dom.with_class(name)))
        self.assertEqual(3, len(self.dom.with_class('reference-card')))
        self.dom.by_id('reference-options')
        self.dom.by_id('own-template')

    def test_controls_keep_existing_choices_and_manual_copy_is_accessible(self):
        for identity in ('length-choice', 'mode-choice', 'font-choice'):
            control = self.dom.by_id(identity)
            selected = [node for node in self.dom.nodes if node['parent'] == self.dom.nodes.index(control)
                        and node['tag'] == 'option' and 'selected' in node['attrs']]
            self.assertEqual(['keep'], [node['attrs'].get('value') for node in selected])
        result = self.dom.by_id('choice-result')
        self.assertEqual('textarea', result['tag'])
        self.assertIn('readonly', result['attrs'])
        details = self.dom.by_id('prompt-details')
        self.assertEqual('details', details['tag'])
        self.assertIn(details, list(self.dom.ancestors(result)))
        for identity in ('font-name', 'font-preview-status', 'copy-status', 'selected-design', 'copy-choice'):
            self.dom.by_id(identity)
        self.assertEqual('polite', self.dom.by_id('copy-status')['attrs'].get('aria-live'))

    def run_controller(self, checks, clipboard='success'):
        if not shutil.which('node'):
            self.skipTest('Node.js is needed for picker controller tests')
        setup = ('const rawNodes=' + json.dumps(self.dom.nodes, ensure_ascii=False) + ';\n'
                 + 'const clipboardMode=' + json.dumps(clipboard) + ';\n'
                 + 'const controller=' + json.dumps(report_styles.PICKER_JS) + ';\n')
        script = setup + NODE_FIXTURE + '\n(async()=>{\n' + checks + '\n})().catch(error=>{console.error(error);process.exitCode=1;});\n'
        result = subprocess.run([shutil.which('node')], input=script, text=True, encoding='utf-8',
                                capture_output=True, timeout=15, cwd=ROOT)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_design_reference_and_template_choices_preserve_keep_without_moving_focus(self):
        choices = [row[0] for row in report_styles.STYLES] + [row[0] for row in report_styles.REFERENCE_PRESETS] + ['template']
        self.run_controller(r'''
for (const value of ''' + json.dumps(choices) + r''') {
  await choose(value);
  for (const id of ['length-choice', 'mode-choice', 'font-choice']) assert.equal(ids[id].value, 'keep');
  assert.ok(ids['choice-result'].value.includes('유지'));
  assert.ok(!ids['choice-result'].value.includes('분량:'));
  assert.ok(!ids['choice-result'].value.includes('보기:'));
  assert.ok(!ids['choice-result'].value.includes('글꼴:'));
  if (value.startsWith('reference-')) assert.ok(ids['choice-result'].value.includes('구성'));
  if (value === 'template') assert.ok(ids['choice-result'].value.includes('양식 파일을 받고'));
}
assert.deepEqual(actions, [], 'Selection must not move focus or scroll the page');
''')

    def test_explicit_settings_survive_switching_all_choice_kinds(self):
        self.run_controller(r'''
await change('length-choice', 'detailed'); await change('mode-choice', 'slides');
await change('font-choice', 'custom'); ids['font-name'].value='맑은 고딕'; await ids['font-name'].fire('input');
for (const value of ['bento-grid', 'reference-2', 'template', 'editorial']) {
  await choose(value);
  assert.equal(ids['length-choice'].value, 'detailed'); assert.equal(ids['mode-choice'].value, 'slides');
  assert.equal(ids['font-choice'].value, 'custom'); assert.equal(ids['font-name'].value, '맑은 고딕');
  assert.equal(ids['font-name'].hidden, false);
  assert.ok(ids['choice-result'].value.includes('분량: 상세'));
  assert.ok(ids['choice-result'].value.includes('보기: 페이지 넘김'));
  assert.ok(ids['choice-result'].value.includes('글꼴: 맑은 고딕'));
}
await change('font-choice', 'pretendard');
assert.equal(ids['font-name'].hidden, true);
for (const preview of all('.style-preview')) assert.equal(preview.dataset.fontPreview, 'Pretendard');
assert.deepEqual(actions, []);
''')

    def test_copy_success_copies_current_prompt_and_selection_resets_status(self):
        self.run_controller(r'''
await choose('reference-3');
const prompt = ids['choice-result'].value;
await ids['copy-choice'].fire('click');
assert.deepEqual(writes, [prompt]);
assert.ok(ids['copy-status'].textContent.includes('복사했습니다'));
assert.deepEqual(actions, []);
await choose('minimalism');
assert.ok(!ids['copy-status'].textContent.includes('복사했습니다'));
assert.ok(ids['copy-status'].textContent.includes('아직'));
''')

    def test_copy_failure_opens_prompt_before_focus_and_selection(self):
        for clipboard in ('missing', 'reject'):
            with self.subTest(clipboard=clipboard):
                self.run_controller(r'''
await choose('template');
ids['prompt-details'].open = false;
await ids['copy-choice'].fire('click');
assert.deepEqual(writes, []);
assert.equal(ids['prompt-details'].open, true);
assert.deepEqual(actions, [['focus', 'choice-result', true], ['select', 'choice-result', true]]);
assert.ok(ids['copy-status'].textContent.includes('Ctrl+C'));
assert.ok(ids['copy-status'].textContent.includes('제한'));
''', clipboard=clipboard)


if __name__ == '__main__':
    unittest.main()
