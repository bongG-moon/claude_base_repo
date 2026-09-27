"""Execute shipped controls in a Node VM with a local DOM/timer test double.

No browser, localhost server, remote resource, screenshot, or visual-QA claim.
"""
import json
import os
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin' / 'scripts'))
from company_agent import explanation_diagram as engine
from company_agent import explanation_export


class _Tree(HTMLParser):
    """Parse the real generated markup instead of duplicating control fixtures."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': 'body', 'attrs': {}, 'children': []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'children': []}
        self.stack[-1]['children'].append(node)
        if tag not in {'br', 'hr', 'img', 'input', 'meta', 'link'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.stack[-1]['tag'] != tag:
            raise AssertionError(f'Unbalanced generated markup: {tag}')
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].setdefault('text', '')
        self.stack[-1]['text'] += data


def _node_runtime():
    configured = os.environ.get('CODEX_NODE')
    if configured:
        candidate = Path(configured)
        return str(candidate) if candidate.is_file() else None
    found = shutil.which('node')
    if found:
        return found
    bundled = (Path.home() / '.cache/codex-runtimes/codex-primary-runtime'
               '/dependencies/node/bin/node.exe')
    return str(bundled) if bundled.is_file() else None


class ExplanationControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = _node_runtime()
        if not cls.node:
            raise unittest.SkipTest('Node unavailable: set CODEX_NODE to an approved local runtime')
        diagram = {
            'type': 'flow', 'title': '검증한 흐름', 'summary': '설명용 순서',
            'nodes': [
                {'id': 'a', 'label': '입력', 'status': 'completed', 'evidence': '입력 확인'},
                {'id': 'b', 'label': '처리', 'status': 'planned'},
                {'id': 'c', 'label': '결과', 'status': 'unknown'},
            ],
            'edges': [{'from': 'a', 'to': 'b'}, {'from': 'b', 'to': 'c'}],
            'motion': 'steps', 'steps': ['a', 'b', 'c'],
        }
        tree = _Tree()
        for index in range(3):
            spec = diagram if index < 2 else dict(diagram, motion='none', steps=[])
            tree.feed(engine.render(spec, index) + explanation_export.controls(index))
        if len(tree.stack) != 1:
            raise AssertionError('Generated controls did not close their markup')
        cls.payload = json.dumps({'tree': tree.root, 'engine': engine.JS,
                                  'exporter': explanation_export.JS}, ensure_ascii=False)

    def run_case(self, case):
        result = subprocess.run(
            [self.node, str(ROOT / 'tests/fixtures/explanation_controls.cjs'), case],
            input=self.payload, text=True, encoding='utf-8', capture_output=True,
            cwd=ROOT, timeout=15, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({'ok': True, 'case': case}, json.loads(result.stdout))

    def test_initial_load_has_no_playback_or_download(self):
        self.run_case('initial')

    def test_play_is_finite_and_only_one_diagram_timer_runs(self):
        self.run_case('playback')

    def test_step_pause_reset_preserve_content_and_status_evidence(self):
        self.run_case('manual')

    def test_visibility_print_pagehide_and_reduced_motion_stop_playback(self):
        self.run_case('lifecycle')

    def test_svg_export_is_user_triggered_unhighlighted_and_cleans_resources(self):
        self.run_case('svg')

    def test_png_export_is_bounded_serialized_and_cleans_resources(self):
        self.run_case('png')

    def test_export_failures_reenable_buttons_and_preserve_html(self):
        self.run_case('export-failures')

    def test_export_timeout_and_download_failure_release_resources(self):
        self.run_case('cleanup-failures')

    def test_missing_export_capability_keeps_controls_hidden(self):
        self.run_case('unsupported')


if __name__ == '__main__':
    unittest.main()
