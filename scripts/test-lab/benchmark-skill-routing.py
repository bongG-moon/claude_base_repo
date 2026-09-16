"""Offline before/after comparison against published 1.4.10. No model calls."""
from pathlib import Path
import json
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import test_skill_discovery as fixtures
import company_agent.native_runtime as runtime
import company_agent.skill_registry as registry
from company_agent.skill_task_context import task_candidates


def old_module(relative):
    source = subprocess.check_output(['git', 'show', 'v1.4.10:' + relative], cwd=ROOT).decode('utf-8')
    namespace = {'__name__': 'company_agent.benchmark_baseline', '__package__': 'company_agent'}
    exec(compile(source, relative, 'exec'), namespace)
    return namespace


def main():
    old = old_module('company-agent-plugin/scripts/company_agent/skill_task_context.py')
    old_runtime = old_module('company-agent-plugin/scripts/company_agent/native_runtime.py')
    old_runtime.update(skill_brief=old['skill_brief'])
    fixture = fixtures.SkillDiscoveryTests()
    fixture.setUp()
    prompt = '@테스트자료.pptx 이 자료 내용 확인해서 정리해줄 수 있을까?'
    try:
        fixture.context(source='startup')
        with patch.object(runtime, 'task_candidates', old['task_candidates']):
            before = fixture.context(prompt)
        after = fixture.context(prompt)
        route = '{"company_agent_route":{"tier":"MEDIUM"}}'
        encode = lambda ctx: json.dumps({'company_agent_runtime': ctx}, ensure_ascii=False, separators=(',', ':'))
        before_text = old_runtime['task_prompt_context'](route, encode(before))
        after_text = runtime.task_prompt_context(route, encode(after))
        result = {'measurement': 'characters-not-tokens; metadata search only, not full hook time',
                  'beforeChars': len(before_text), 'afterChars': len(after_text),
                  'reductionPercent': round((1 - len(after_text) / len(before_text)) * 100, 1),
                  'beforeCandidates': [g['name'] for g in before['taskSkills']['groups']],
                  'afterCandidates': [g['name'] for g in after['taskSkills']['groups']]}
        # Same actual directory scan, uncached vs warm metadata reuse. Count
        # SKILL.md body reads only, not directory stats/settings/cache reads.
        for name, cached in [('uncached', False), ('warm', True)]:
            with patch.object(registry, '_read', wraps=registry._read) as reads:
                inventory = registry.inventory_skills(fixture.state, project_root=fixture.project,
                    claude_root=fixture.claude, plugin_root=fixtures.PLUGIN, metadata_cache=cached)
                result[name + 'SkillBodyReads'] = sum(Path(call.args[0]).name == 'SKILL.md' for call in reads.call_args_list)
                result[name + 'SkillCount'] = len(inventory['skills'])
        items = [{'id': str(i), 'name': f'custom-{i}', 'source': 'user', 'invocation': f'custom-{i}',
                  'description': 'PPT 내용을 읽고 요약', 'path': f'C:/skills/{i}/SKILL.md'} for i in range(1000)]
        inv = {'complete': True, 'skills': items}
        for name, function in [('before', old['task_candidates']), ('after', task_candidates)]:
            samples = []
            for _ in range(7):
                start = time.perf_counter()
                function(inv, prompt)
                samples.append((time.perf_counter() - start) * 1000)
            result[name + '1000SkillMedianMs'] = round(statistics.median(samples), 2)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
