"""Offline comparison with published 1.4.12; chars/CPU, not tokens/model latency."""
from contextlib import ExitStack
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import test_skill_discovery as fixtures
from company_agent import native_runtime, skill_execution, skill_registry


def baseline(name):
    path = f'company-agent-plugin/scripts/company_agent/{name}.py'
    raw = subprocess.check_output(['git', 'show', 'v1.4.12:' + path], cwd=ROOT).decode('utf-8')
    scope = {'__name__': 'company_agent.benchmark_baseline', '__package__': 'company_agent'}
    exec(compile(raw, path, 'exec'), scope)
    return scope


def measure(old=False, observed=False):
    f = fixtures.SkillDiscoveryTests()
    f.setUp()
    try:
        prompt = 'HTML 보고서 만들어줘'
        f.context(source='startup')
        if observed:
            f.context(prompt)
            f.read(fixtures.PLUGIN / 'skills/html-report/SKILL.md')
        context = f.context(prompt)
        wire = json.dumps({'company_agent_runtime': context}, ensure_ascii=False)
        route = '{"company_agent_instruction":"old","company_agent_route":{"tier":"MEDIUM"}}'
        with ExitStack() as stack:
            function = native_runtime.task_prompt_context
            if old:
                previous = baseline('native_runtime')
                previous['skill_brief'] = baseline('skill_task_context')['skill_brief']
                functions = baseline('skill_execution')
                for name in ('prepare_execution', 'record_execution', 'body_context'):
                    stack.enter_context(patch.object(skill_execution, name, functions[name], create=True))
                function = previous['task_prompt_context']
            start = time.perf_counter()
            text = function(route, wire)
            elapsed = (time.perf_counter() - start) * 1000
        runtime = json.loads(text.splitlines()[-1])['company_agent_runtime']
        with patch.object(skill_registry, '_read', wraps=skill_registry._read) as reads:
            inventory = skill_registry.inventory_skills(f.state, project_root=f.project,
                claude_root=f.claude, plugin_root=fixtures.PLUGIN, metadata_cache=True)
            body_reads = sum(Path(call.args[0]).name == 'SKILL.md' for call in reads.call_args_list)
        return {'chars': len(text), 'prepareMs': elapsed, 'mode': runtime['skillExecution']['mode'],
                'warmInventoryBodyReads': body_reads, 'skills': len(inventory['skills'])}
    finally:
        f.doCleanups()


def main():
    report = {'measurement': 'characters-not-tokens; local preparation-not-model-or-document-runtime',
              'extraModelCalls': 0, 'mandatorySelectionCommands': 0}
    for label, old, observed in [('publishedFirst', True, False), ('listFirst', False, False), ('observedReuse', False, True)]:
        samples = [measure(old, observed) for _ in range(5)]
        report[label] = {**samples[-1], 'prepareMs': round(statistics.median(s['prepareMs'] for s in samples), 2)}
    report['firstContextReductionPercent'] = round((1 - report['listFirst']['chars'] / report['publishedFirst']['chars']) * 100, 1)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
