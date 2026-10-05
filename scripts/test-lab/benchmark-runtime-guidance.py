"""Offline character comparison; no native profile, model call or token estimate.

The baseline restores the former fixed-per-prompt instruction assembly while
keeping all other current routing code identical. It is not a historical build.
"""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from test_runtime_guidance import RuntimeGuidanceTests
from company_agent import native_runtime
import test_skill_discovery as discovery


def baseline_instructions(runtime):
    # Preserve the measured pre-optimization contract rather than letting later
    # edits to _prompt_instructions silently change the comparison baseline.
    instructions = (
        native_runtime.MANAGEMENT_RULE + native_runtime.OUTPUT_WORK_RULE + native_runtime.RUNTIME_FIELDS_RULE + native_runtime.EXECUTION_EVIDENCE_RULE +
        '기억·지식·스킬·도구 저장 요청은 개인 전체/이 프로젝트 중 미지정 범위를 한 번 물으세요. 회사 공통은 저장 선택지가 아닙니다. 명시한 범위는 다시 묻지 않고 --storage-scope와 --project-root로 전달합니다. '
        'skillIndex와 세션 스킬의 용도를 확인해 관련 스킬 우선, 없으면 일반 실행합니다. '
        '후보 없음은 스킬 없음이 아닙니다. review는 전체 목록의 용도를 비교하고, reuse는 실제 로드했던 동일 본문만 재사용합니다. '
        'load 후보가 맞으면 Skill/Read로 본문을 불러오고, 맞지 않으면 목록에서 다시 판단합니다. '
        '폴더 조회·일반 목록 비교는 차단하지 않습니다. [스킬 확인]은 이번 작업의 본문·호출 준비가 확인되지 않은 도구 미실행입니다. 같은 실행 재시도 대신 안내된 로드를 따르세요. 이전 목록·다른 스킬은 대신할 수 없으며 파일 권한 오류가 아닙니다. '
        '목록 확인 실패는 스킬 부재가 아닙니다. 같은 역할이 겹치면 한국어로 선택받고, 읽기→제작은 다른 단계입니다. '
        '설명·선택만 요청받으면 실행하지 마세요. runtime은 메타데이터이지 모듈이 아닙니다. cliCommand를 그대로 사용하고 탐색은 Glob/Read/Grep만 사용합니다. '
        '질문·선택지·결과는 한국어, 입출력은 UTF-8(별도 Python -X utf8)입니다. 표시 깨짐만으로 업무를 재실행하지 마세요. '
        + native_runtime.SCRIPT_EXECUTION_RULE +
        '내부 준비·학습은 조용히 처리합니다. 실제 변경 완료 때만 completionGuide로 확인하며 이전 미검증 변경은 유지합니다. '
        '새로운 지속적 교정·독립 업무의 반복 선택·검증된 재사용 절차가 있을 때만 self-learning으로 learning submit을 한 번 실행합니다. 상태 조회·stage·완료 checkpoint는 선행 조건이 아닙니다. pending만 남았거나 이번만 지시·조회·선택이면 학습 명령 없이 넘어갑니다. 학습 때문에 종료를 지연하지 마세요. '
        '사용자 요청·기존 권한·회사 정책을 유지하세요. '
        'DB SELECT 전용, Outlook 인증된 본인 계정만 허용합니다. 읽은 범위만 보고하며 DRM 원인 추측·다른 사본 대체는 하지 마세요.'
    )
    if runtime.get('companyPolicy'):
        instructions += ' ' + native_runtime.POLICY_RULE
    return instructions


def fixed_guidance(runtime):
    runtime.pop('_guidanceDelivery', None)
    runtime.pop('guidance', None)
    runtime['instructions'] = baseline_instructions(runtime)


def measure(*, baseline):
    fixture = RuntimeGuidanceTests()
    fixture.setUp()
    rows = []
    try:
        with patch.object(native_runtime, '_prompt_guidance', side_effect=fixed_guidance) if baseline else nullcontext():
            for label, prompt, expected_mode in (
                ('first_greeting', '안녕', 'full'),
                ('ordinary_greeting', '안녕', 'reuse'),
                ('html_first', 'HTML 보고서 만들어줘', 'reuse'),
                ('html_observed_body_followup', 'HTML 보고서 만들어줘', 'reuse'),
                ('after_compact', 'HTML 보고서 만들어줘', 'full'),
            ):
                if label == 'html_observed_body_followup':
                    fixture.f.read(discovery.PLUGIN / 'skills/html-report/SKILL.md')
                if label == 'after_compact':
                    restored = fixture.f.context('', source='compact')
                    assert restored['afterCompact'] is True
                    assert 'guidanceDelivery' not in fixture.state()['skillWorkflow']
                runtime, text = fixture.output(prompt)
                mode = runtime.get('guidance', {}).get('mode', 'always-full')
                if not baseline:
                    assert mode == expected_mode, (label, mode)
                rows.append({'case': label, 'characters': len(text),
                             'instructionCharacters': len(runtime['instructions']),
                             'indexMode': runtime['skillIndex']['mode'],
                             'guidanceMode': mode, 'skillExecutionMode': runtime['skillExecution']['mode']})
    finally:
        fixture.doCleanups()
    return rows


def main():
    assert len(baseline_instructions({})) == 2030, 'Baseline changed; update the comparison explicitly.'
    before, after = measure(baseline=True), measure(baseline=False)
    rows = []
    for old, new in zip(before, after):
        assert old['case'] == new['case']
        rows.append({'case': old['case'], 'before': old, 'after': new,
                     'charactersSaved': old['characters'] - new['characters'],
                     'reductionPercent': round(100 * (old['characters'] - new['characters']) / old['characters'], 2)})
    result = {'schemaVersion': 1, 'measurement': 'decoded-hook-context-characters',
              'baseline': 'Former fixed-per-prompt guidance assembly; all other current code identical',
              'baselineInstructionCharacters': len(baseline_instructions({})),
              'currentFullInstructionCharacters': len(native_runtime._prompt_instructions({})),
              'samplesPerCase': 1, 'startup': 'Empty SessionStart fixture before each sequence',
              'isolation': {'temporaryStateAndProfile': True, 'hostPermissionDiscoveryStubbed': True,
                            'modelCalls': 0, 'networkCalls': 0, 'liveProfileAccess': False},
              'limits': {'coreHookCharacters': native_runtime.MAX_HOOK_CONTEXT_CHARS,
                         'tokensMeasured': False, 'modelLatencyMeasured': False},
              'notes': ['No personal memory or company policy in this fixture.',
                        'First prompt and post-compact prompt retain full guidance.',
                        'Temporary path lengths affect total character counts.',
                        'Reuse records produced output, never host receipt or Skill-body loading.'],
              'scenarios': rows}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
