"""Isolated 0/100/500-document startup samples; never accesses a live profile.

The baseline replays the former no-overlay startup call sequence using the
current safe scanner. It is a conservative sequence comparison, not execution
of a historical release. All fixtures are created under TemporaryDirectory.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import knowledge, knowledge_cache
from company_agent.frontmatter import dump_frontmatter
from company_agent.paths import atomic_write_json, ensure_user_layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix='knowledge-performance-') as temporary:
        fixture = Path(temporary)
        for count in (0, 100, 500):
            base, state = fixture / str(count) / 'company', fixture / str(count) / 'state'
            base.mkdir(parents=True)
            atomic_write_json(base / 'pack.json', {'version': '1'})
            body = 'Stable manufacturing reference material. ' * 40
            for number in range(count):
                (base / f'term-{number:04}.md').write_text(dump_frontmatter({
                    'id': f'term.fixture-{number}', 'kind': 'term', 'title': f'Fixture {number}',
                    'owner': 'fixture', 'status': 'active'}, body), encoding='utf-8')
            layout = ensure_user_layout(state)

            def baseline():
                knowledge.discover_documents(base)
                knowledge.discover_documents(layout['overlays'])
                _, issues = knowledge.build_index(base, layout['knowledge'], layout['index'])
                report = {'baseVersion': knowledge.read_pack_version(base), 'compatible': [],
                          'rebased': [], 'conflicts': [], 'detached': [],
                          'indexIssues': [knowledge.asdict(issue) for issue in issues]}
                knowledge.atomic_write_json(layout['conflicts'] / 'report.json', report)
                return report

            def current():
                return knowledge.reconcile_overlays(state, base, apply_safe=True)

            def sample(label, run, prepare=lambda: None):
                counts = {'sourceReads': 0, 'parses': 0, 'builds': 0, 'indexJsonWrites': 0,
                          'indexTextWrites': 0, 'reportWrites': 0, 'cacheWrites': 0}
                original_read = Path.read_text
                def read(path, *a, **kw):
                    if path.suffix.casefold() == '.md' and path.is_relative_to(base):
                        counts['sourceReads'] += 1
                    return original_read(path, *a, **kw)
                def observe(original, key):
                    def call(*a, **kw):
                        counts[key] += 1
                        return original(*a, **kw)
                    return call
                original_json = knowledge.atomic_write_json
                def write_json(path, value):
                    counts['reportWrites' if path.name == 'report.json' else 'indexJsonWrites'] += 1
                    return original_json(path, value)
                prepare()
                with ExitStack() as patches:
                    patches.enter_context(patch.object(Path, 'read_text', read))
                    patches.enter_context(patch.object(knowledge, 'parse_frontmatter_text', observe(knowledge.parse_frontmatter_text, 'parses')))
                    patches.enter_context(patch.object(knowledge, 'build_index', observe(knowledge.build_index, 'builds')))
                    patches.enter_context(patch.object(knowledge, 'atomic_write_json', write_json))
                    patches.enter_context(patch.object(knowledge, 'atomic_write_text', observe(knowledge.atomic_write_text, 'indexTextWrites')))
                    patches.enter_context(patch.object(knowledge_cache, 'atomic_write_json', observe(knowledge_cache.atomic_write_json, 'cacheWrites')))
                    report = run()
                if report.get('indexIssues'):
                    raise AssertionError(report)
                elapsed = []
                for _ in range(args.repeats):
                    prepare()
                    started = time.perf_counter()
                    report = run()
                    elapsed.append(round((time.perf_counter() - started) * 1000, 3))
                    if report.get('indexIssues'):
                        raise AssertionError(report)
                return {'case': label, **counts, 'medianMs': round(statistics.median(elapsed), 3), 'samplesMs': elapsed}

            cases = [sample('prior_no_overlay_sequence', baseline)]
            current()
            cases.append(sample('unchanged_after', current))
            change = 0
            def modify_source():
                nonlocal change
                change += 1
                if count:
                    path = base / 'term-0000.md'
                    path.write_text(dump_frontmatter({'id': 'term.fixture-0', 'kind': 'term', 'title': 'Fixture 0',
                                                     'owner': 'fixture', 'status': 'active'}, body + f' Revision {change}.'), encoding='utf-8')
                else:
                    atomic_write_json(base / 'pack.json', {'version': str(change + 1)})
            cases.append(sample('source_changed_after', current, modify_source))
            def corrupt_cache():
                (layout['index'] / 'startup-cache.json').write_text('{broken-cache', encoding='utf-8')
            cases.append(sample('corrupt_cache_after', current, corrupt_cache))
            results.append({'documents': count, 'approximateBodyCharsPerDocument': len(body), 'cases': cases})
    artifact = {
        'schemaVersion': 1, 'measuredAt': datetime.now(timezone.utc).isoformat(),
        'python': sys.version.split()[0], 'repeats': args.repeats,
        'scope': 'Temporary synthetic fixtures only; no Claude, Driver, network or live profile.',
        'baseline': 'Prior no-overlay startup read/rebuild sequence using the current safe scanner; not a historical binary.',
        'limits': 'Local filesystem warm-cache samples; source bytes still read and hashed on every run. Not enterprise-device latency.',
        'results': results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(artifact, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
