"""Explicit developer-only evaluation; never imported or invoked by a hook.

python -X utf8 -B scripts/test-lab/evaluate-harness-efficiency.py --output before.json
python -X utf8 -B scripts/test-lab/evaluate-harness-efficiency.py --baseline before.json

Temporary fixtures exercise the existing production context builder. Character
counts are NOT tokens; local Python time is NOT model or full CLI latency. The
optional --runs file contains sanitized measurements, never transcripts/prompts.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from test_runtime_guidance import RuntimeGuidanceTests  # noqa: E402
import test_skill_discovery as discovery  # noqa: E402


# Deliberately small, explicit cases. A new corpus changes its fingerprint so
# unlike before/after workloads cannot silently produce a speedup claim.
CASES = (
    {'case': 'greeting', 'prompt': '안녕', 'mode': 'review'},
    {'case': 'html', 'prompt': 'HTML 보고서 만들어줘', 'mode': 'load', 'skill': 'html-report'},
    {'case': 'ppt', 'prompt': '부서장 보고 PPT 만들어줘', 'mode': 'load', 'skill': 'presentation'},
    {'case': 'browser_use', 'prompt': '연결된 크롬 도구로 페이지를 열고 현재 표를 읽어줘',
     'forbidden': ['asset-factory'], 'choice': False},
    {'case': 'overlap', 'prompt': 'HTML 보고서 만들어줘', 'setup': 'overlap', 'mode': 'choose', 'choice': True},
    {'case': 'explicit_choice', 'prompt': '회사 html-report를 사용해줘', 'setup': 'overlap',
     'mode': 'load', 'skill': 'html-report', 'source': 'company'},
    {'case': 'body_reuse', 'prompt': 'HTML 보고서 만들어줘', 'setup': 'reuse',
     'mode': 'reuse', 'skill': 'html-report'},
    {'case': 'after_compact', 'prompt': 'HTML 보고서 만들어줘', 'setup': 'compact',
     'mode': 'load', 'skill': 'html-report'},
)
CORPUS_ID = hashlib.sha256(json.dumps(CASES, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
RUN_METRICS = ('elapsedMs', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens',
               'retries', 'questions')


def normalized_text(text: str, fixture) -> str:
    """Remove machine-specific path lengths, retaining all actual instructions."""
    for path, label in ((str(fixture.f.root), '<fixture>'), (str(ROOT), '<repository>')):
        for spelling in sorted({path, path.replace('\\', '/'), path.replace('\\', '\\\\')}, key=len, reverse=True):
            text = text.replace(spelling, label)
    return text


def measure_case(case: dict) -> dict:
    fixture = RuntimeGuidanceTests()
    try:
        fixture.setUp()
        if case.get('setup') == 'overlap':
            fixture.f.skill('html-report', 'HTML 보고서 작성')
        if case.get('setup') in {'reuse', 'compact'}:
            fixture.output('HTML 보고서 만들어줘')
            fixture.f.read(discovery.PLUGIN / 'skills/html-report/SKILL.md')
        if case.get('setup') == 'compact':
            fixture.f.context('', source='compact')
        start = time.perf_counter()
        context, text = fixture.output(case['prompt'])
        elapsed = (time.perf_counter() - start) * 1000
        plan = context.get('skillExecution', {})
        choice = plan.get('mode') == 'choose'
        issues = []
        for field, actual in (('mode', plan.get('mode')), ('skill', plan.get('name')), ('source', plan.get('source'))):
            if field in case and case[field] != actual:
                issues.append(f'{field}: expected {case[field]}, observed {actual}')
        if plan.get('name') in case.get('forbidden', []):
            issues.append('irrelevant-skill-selected')
        if choice != case.get('choice', False):
            issues.append('unexpected-choice-plan' if choice else 'missing-required-choice-plan')
        normalized = normalized_text(text, fixture)
        return {'case': case['case'], 'mode': plan.get('mode'), 'skill': plan.get('name'),
                'choicePlanned': choice, 'qualityPassed': not issues, 'issues': issues,
                'contextChars': len(text), 'contextUtf8Bytes': len(text.encode('utf-8')),
                'normalizedContextChars': len(normalized),
                'normalizedContextUtf8Bytes': len(normalized.encode('utf-8')),
                'instructionChars': len(context.get('instructions', '')),
                'localContextMs': elapsed}
    finally:
        fixture.doCleanups()


def collect(samples: int = 3) -> dict:
    if not 1 <= samples <= 20:
        raise ValueError('samples must be between 1 and 20')
    rows = []
    with ExitStack() as stack:
        # Fail rather than silently invoking a live model/browser/process.
        for target in ('subprocess.Popen', 'socket.create_connection', 'socket.socket.connect',
                       'socket.socket.connect_ex'):
            stack.enter_context(patch(target, side_effect=AssertionError('Offline evaluation forbids external execution')))
        for case in CASES:
            measured = [measure_case(case) for _ in range(samples)]
            row = measured[-1].copy()
            row['qualityPassed'] = all(item['qualityPassed'] for item in measured)
            row['issues'] = sorted({issue for item in measured for issue in item['issues']})
            row['localContextMs'] = round(statistics.median(item['localContextMs'] for item in measured), 3)
            row['localContextMinMs'] = round(min(item['localContextMs'] for item in measured), 3)
            row['localContextMaxMs'] = round(max(item['localContextMs'] for item in measured), 3)
            rows.append(row)
    return {'schemaVersion': 1, 'corpusId': CORPUS_ID, 'samplesPerCase': samples,
            'passed': all(row['qualityPassed'] for row in rows),
            'isolation': {'temporaryProfileAndState': True, 'modelCalls': 0, 'networkCalls': 0,
                          'liveProfileAccess': False, 'normalHookIntegration': False},
            'limits': ['Characters and bytes are measured, not tokens.',
                       'Times cover local context building, not startup, approvals, model inference or task completion.',
                       'Choice counts describe routing plans, not observed user questions or executed skills.',
                       'File-system timing varies; compare repeated runs on the same machine.',
                       'Observed run labels do not prove equal workload, model or environment; keep these fixed externally.',
                       'elapsedMs in supplied runs must cover the whole request including retries and approval waits.'],
            'scenarios': rows}


def read_json(path: Path):
    if path.stat().st_size > 1_048_576:
        raise ValueError('Measurement file exceeds 1 MiB')
    with path.open(encoding='utf-8-sig') as stream:
        return json.load(stream)


def compare(baseline: dict, current: dict) -> dict:
    if baseline.get('schemaVersion') != 1 or baseline.get('corpusId') != current['corpusId']:
        raise ValueError('Baseline schema/corpus differs; measure the same scenarios before comparing')
    old = {row['case']: row for row in baseline.get('scenarios', [])}
    if len(old) != len(baseline.get('scenarios', [])) or set(old) != {row['case'] for row in current['scenarios']}:
        raise ValueError('Baseline must contain every scenario exactly once')
    rows = []
    regressions = []
    quality_fixed = []
    for row in current['scenarios']:
        previous = old[row['case']]
        comparison = {'case': row['case'], 'qualityBefore': previous['qualityPassed'],
                     'qualityAfter': row['qualityPassed'],
                     'normalizedContextCharsDelta': row['normalizedContextChars'] - previous['normalizedContextChars'],
                     'normalizedContextUtf8BytesDelta': row['normalizedContextUtf8Bytes'] - previous['normalizedContextUtf8Bytes'],
                     'instructionCharsDelta': row['instructionChars'] - previous['instructionChars'],
                     'choicePlansDelta': int(row['choicePlanned']) - int(previous['choicePlanned']),
                     'localContextMsDelta': round(row['localContextMs'] - previous['localContextMs'], 3)}
        rows.append(comparison)
        if not previous['qualityPassed']:
            if row['qualityPassed']:
                quality_fixed.append(row['case'])
            # A former misroute is not a valid budget baseline for the repaired
            # workflow. Report its raw delta, but do not call it overhead.
            continue
        for field in ('normalizedContextCharsDelta', 'normalizedContextUtf8BytesDelta',
                      'instructionCharsDelta', 'choicePlansDelta'):
            if comparison[field] > 0:
                regressions.append({'case': row['case'], 'metric': field, 'delta': comparison[field]})
    return {'baselinePassed': baseline.get('passed'), 'currentPassed': current['passed'],
            'timingIsInformational': True, 'qualityFixedCases': quality_fixed,
            'deterministicRegressions': regressions, 'scenarios': rows}


def summarize_runs(data) -> dict:
    """Aggregate exact supplied values only. Missing usage stays unknown."""
    if not isinstance(data, list) or not 1 <= len(data) <= 1000:
        raise ValueError('Runs must be a nonempty JSON list with at most 1000 records')
    groups = {}
    for row in data:
        if not isinstance(row, dict) or set(row) - {'case', 'completed', *RUN_METRICS}:
            raise ValueError('Use sanitized measurement fields only; no prompts, paths or transcripts')
        name = row.get('case')
        if not isinstance(name, str) or not name or len(name) > 80 or any(ch in name for ch in '\r\n\\/'):
            raise ValueError('case must be a short scenario label, not a path')
        if type(row.get('completed')) is not bool:
            raise ValueError('completed must be true or false')
        for key in RUN_METRICS:
            value = row.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError(f'{key} must be nonnegative and finite, or null when unavailable')
        groups.setdefault(name, []).append(row)
    result = {}
    for name, rows in sorted(groups.items()):
        result[name] = {'runs': len(rows), 'completed': sum(row['completed'] for row in rows), 'metrics': {}}
        for key in RUN_METRICS:
            values = [row.get(key) for row in rows]
            known = [value for value in values if value is not None]
            result[name]['metrics'][key] = {'observedRuns': len(known),
                                           'total': sum(known) if len(known) == len(rows) else None,
                                           'median': statistics.median(known) if len(known) == len(rows) else None}
    return result


def compare_runs(before: dict, after: dict) -> dict:
    if set(before) != set(after):
        raise ValueError('Live comparisons require the same scenario labels')
    result = {}
    for name in before:
        old, new = before[name], after[name]
        comparable = (old['runs'] == new['runs'] and old['completed'] == old['runs']
                      and new['completed'] == new['runs'])
        result[name] = {'comparable': comparable, 'before': old, 'after': new, 'medianDeltas': {}}
        if comparable:
            for key in RUN_METRICS:
                a, b = old['metrics'][key]['median'], new['metrics'][key]['median']
                result[name]['medianDeltas'][key] = b - a if a is not None and b is not None else None
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--baseline', type=Path, help='Previously saved offline evaluation JSON')
    parser.add_argument('--strict', action='store_true',
                        help='With --baseline, fail deterministic context/instruction/choice growth on previously valid cases')
    parser.add_argument('--output', type=Path, help='Explicit destination for this report; defaults to stdout')
    parser.add_argument('--runs', type=Path, help='Optional sanitized real-task measurement JSON list')
    parser.add_argument('--baseline-runs', type=Path, help='Optional earlier real-task measurements (requires --runs)')
    args = parser.parse_args(argv)
    try:
        if args.baseline_runs and not args.runs:
            raise ValueError('--baseline-runs requires --runs')
        if args.strict and not args.baseline:
            raise ValueError('--strict requires --baseline')
        if args.output and any(path and path.resolve() == args.output.resolve()
                               for path in (args.baseline, args.runs, args.baseline_runs)):
            raise ValueError('Output must not overwrite an input measurement file')
        report = collect(args.samples)
        if args.baseline:
            report['comparison'] = compare(read_json(args.baseline), report)
        if args.runs:
            report['observedRuns'] = summarize_runs(read_json(args.runs))
        if args.baseline_runs:
            report['observedRunComparison'] = compare_runs(summarize_runs(read_json(args.baseline_runs)),
                                                           report['observedRuns'])
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(rendered, encoding='utf-8')
        else:
            print(rendered, end='')
        regressed = args.strict and report['comparison']['deterministicRegressions']
        return 0 if report['passed'] and not regressed else 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
