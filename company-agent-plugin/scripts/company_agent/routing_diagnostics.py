"""On-demand, read-only diagnostics. No runtime initialization or model calls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from datetime import datetime

PLUGIN_ID = 'company-agent@company-agent-local'
LOAD_LABELS = {
    'not-observed': '이번 요청에서 본문 로드 이벤트를 관찰하지 못함',
    'loaded': '본문 로드 확인', 'tool-failed': '도구 실패',
    'body-provided': '선택한 본문을 Hook 안내에 포함(모델 적용·Skill 호출 여부는 별도)',
    'catalog-unavailable': '목록 기록 확인 실패', 'read-path-unrecognized': '읽기 경로 형식 확인 필요',
    'skill-path-unmatched': '읽은 스킬 경로가 목록과 다름',
    'response-unrecognized': 'Skill 응답 형식 확인 필요',
    'name-ambiguous': '호출 이름 중복', 'skill-name-unmatched': '호출 이름이 목록과 다름',
    'choice-unresolved': '스킬 우선 선택 확인 필요',
    'body-unavailable-or-explicit-only': '본문 변경·삭제 또는 수동 전용 조건 확인 필요',
    'partial-read': '본문 일부만 읽은 것으로 확인',
    'read-response-unrecognized': 'Read 응답 내용·형식 확인 필요',
    'native-skill-outside-catalog': '로컬 목록 밖 호스트 스킬의 성공한 호출 확인(현재 요청만)',
}
REVIEW_LABELS = {
    'advised': '목록 비교 안내만 전달(차단 없음, 본문 적용 여부 미확인)',
    'redirected': '목록/본문 확인 누락으로 첫 실행 1회 교정(원래 도구 미실행)',
    'catalog-read': '교정 후 전체 목록 읽기 확인',
    'skill-loaded': '교정 후 스킬 본문 로드 확인',
    'native-skill-outside-catalog': '교정 후 호스트 스킬 로드 확인',
    'unconfirmed-limit-reached': '읽기 확인 없이 재시도함(반복 차단 안 함, 적용 성공 아님)',
}


def mapping(value):
    return value if isinstance(value, dict) else {}


def flag(value):
    return '예' if value is True else '아니요' if value is False else '설정 없음 또는 형식 확인 필요'


def read_object(path: Path) -> dict:
    # Do not follow junctions/symlinks or accidentally read an enormous transcript.
    # lstat attributes also detect Windows junctions on supported Python 3.11,
    # which does not have Path.is_junction().
    from .skill_registry import _no_reparse
    _no_reparse(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('oversize')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('not-object')
    return value


def inspect(claude_root: Path, local_data: Path, project: Path, session: str = '') -> dict:
    report = {'readOnly': True, 'claudeConfigRoot': str(claude_root), 'projectRoot': str(project),
              'plugins': [], 'registrations': [], 'sessions': [], 'warnings': []}
    def read(path):
        try:
            return read_object(path)
        except (OSError, ValueError):
            report['warnings'].append('기록을 읽지 못함: ' + str(path))
            return {}
    entries = mapping(read(claude_root / 'plugins/installed_plugins.json').get('plugins')).get(PLUGIN_ID, [])
    if not isinstance(entries, list):
        entries = []
    for item in entries[:20]:
        if isinstance(item, dict):
            view = {k: item.get(k) for k in ('scope', 'version', 'installPath', 'projectPath')}
            view['configuredHooks'] = []
            if isinstance(item.get('installPath'), str) and Path(item['installPath']).is_absolute():
                hooks = read(Path(item['installPath']) / 'hooks/hooks.json').get('hooks', {})
                if isinstance(hooks, dict):
                    view['configuredHooks'] = [event for event in ('SessionStart', 'UserPromptSubmit', 'PostToolUse') if hooks.get(event)]
            report['plugins'].append(view)
    settings = read(claude_root / 'settings.json')
    report['userPluginEnabled'] = mapping(settings.get('enabledPlugins')).get(PLUGIN_ID)
    report['userDisableAllHooks'] = settings.get('disableAllHooks')
    # These are file values, NOT a claim to know Claude's merged managed/CLI settings.
    report['effectiveHostSettings'] = 'not-observable'
    registry = local_data / 'CompanyAgent/installations'
    files = [registry / 'user/company-agent-install.json']
    projects = registry / 'projects'
    if projects.is_dir() and not projects.is_symlink() and not getattr(projects, 'is_junction', lambda: False)():
        for folder in list(projects.iterdir())[:200]:
            if folder.is_dir():
                files.append(folder / 'company-agent-install.json')
    for file in files:
        if not file.exists():
            continue
        rec = read(file)
        pr = rec.get('projectRoot')
        applies = rec.get('scope') == 'User' or (rec.get('scope') == 'Project' and isinstance(pr, str)
                    and project.resolve().is_relative_to(Path(pr).resolve()))
        if not applies:
            continue
        view = {k: rec.get(k) for k in ('coreVersion', 'scope', 'claudeConfigRoot', 'userStateRoot', 'projectRoot')}
        view['explicitlyDisabled'] = rec.get('enabled') is False
        view['configMatches'] = isinstance(rec.get('claudeConfigRoot'), str) and Path(rec['claudeConfigRoot']).resolve() == claude_root.resolve()
        view['overrideFlagRecorded'] = rec.get('claudeConfigDirOverride')
        report['registrations'].append(view)
    # Use exactly the native activation resolver, not a second approximation of
    # project depth, disabled plugins, registration schema or override settings.
    from .native_runtime import resolve_registration
    try:
        rec = resolve_registration(registry, project, claude_root=claude_root,
                                   config_override=bool(os.environ.get('CLAUDE_CONFIG_DIR', '').strip()))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        rec = None
        report['warnings'].append('실행부와 동일한 설치 확인을 완료하지 못했습니다. 설치 기록 형식을 확인해 주세요.')
    if not rec:
        report['warnings'].append('현재 폴더와 설정 위치에 맞는 설치 기록이 없습니다. 임의로 다른 개인 저장 위치를 읽지 않았습니다.')
        return report
    state = Path(rec['userStateRoot']) / 'sessions'
    report['selectedStateRoot'] = rec['userStateRoot']
    from .company_policy import inspect_policy
    managed = rec.get('managedConfigPath')
    policy = inspect_policy(Path(managed)) if isinstance(managed, str) and managed else {'status': 'not-configured'}
    report['companyPolicy'] = {key: policy[key] for key in ('status', 'path', 'revision', 'enforcement') if key in policy}
    if session and not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', session):
        raise ValueError('세션 ID 형식이 올바르지 않습니다.')
    try:
        from .skill_registry import _no_reparse
        _no_reparse(state)
        candidates = [state / (session + '.json')] if session else sorted(state.glob('*.json'), key=lambda f: f.stat().st_mtime, reverse=True)[:3]
        for file in candidates:
            data = read(file)
            hooks = {}
            for event in ('SessionStart', 'UserPromptSubmit'):
                source = mapping(data.get('hookDiagnostics')).get(event, {})
                if not isinstance(source, dict):
                    continue
                # Allowlist enums/numbers only; never export arbitrary error messages.
                row = {k: source[k] for k in ('elapsedMs', 'contextChars') if type(source.get(k)) is int}
                row['status'] = source.get('status') if source.get('status') in {'started', 'output-produced', 'failed'} else 'not-observed'
                names = source.get('candidateNames', [])
                row['candidateNames'] = [n for n in names if isinstance(n, str) and re.fullmatch(r'[a-z0-9_-]{1,160}', n)][:16] if isinstance(names, list) else []
                row['indexMode'] = source.get('indexMode') if source.get('indexMode') in {'inline', 'reuse', 'pages'} else None
                error = source.get('errorType')
                if isinstance(error, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', error):
                    row['errorType'] = error
                hooks[event] = row
            workflow = mapping(data.get('skillWorkflow'))
            observation = mapping(workflow.get('loadObservation'))
            current = observation.get('turn') == data.get('turnId') and observation.get('turn') is not None
            status = observation.get('status') if current else None
            checkpoint = mapping(workflow.get('reviewCheckpoint'))
            review = checkpoint.get('status') if checkpoint.get('turn') == data.get('turnId') and data.get('turnId') else None
            mode = mapping(workflow.get('executionPlan')).get('mode') if workflow.get('turn') == data.get('turnId') else None
            verification = mapping(data.get('verification')).get('status')
            counts = {key: data[key] for key in ('taskToolCount', 'taskFailureCount')
                      if type(data.get(key)) is int and 0 <= data[key] <= 1_000_000}
            from .workflow_evidence import workflow_progress
            report['sessions'].append({'sessionFile': file.name, 'updatedAt': datetime.fromtimestamp(file.stat().st_mtime).isoformat(timespec='seconds'),
                'workflowProgress': workflow_progress(data),
                **counts, 'verificationStatus': verification if verification in {'pass', 'fail', 'partial', 'unavailable', 'not_applicable'} else None,
                'indexRead': workflow.get('indexRead') is True,
                'executionMode': mode if mode in {'load', 'reuse', 'review', 'choose', 'select', 'general', 'inspect', 'provided'} else 'unknown',
                'reviewStatus': review if review in REVIEW_LABELS else 'not-observed',
                'reviewMessage': REVIEW_LABELS.get(review, '교정 기록 없음(정상 준비 또는 미관찰)'),
                'hooks': hooks, 'loadStatus': status if status in LOAD_LABELS else 'unknown',
                'loadMessage': LOAD_LABELS.get(status, '이번 요청의 본문 로드 진단 없음(이전 버전 또는 미관찰)')})
    except (OSError, ValueError, AttributeError, TypeError):
        report['warnings'].append('세션 진단 일부를 읽지 못했습니다. 기록 없음만으로 Hook 미실행을 단정하지 마세요.')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Company Agent 읽기 전용 한국어 진단')
    parser.add_argument('--claude-root', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude'))
    parser.add_argument('--local-appdata', type=Path, default=Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local'))
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--session', default='')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--report', type=Path, help='새 HTML 파일에 진단 저장 (기존 파일 보존)')
    parser.add_argument('--usage-log', type=Path, action='append', default=[], help='선택한 UTF-8 JSONL만 사용량 분석; 자동 탐색하지 않음')
    parser.add_argument('--office-result', type=Path, help='선택한 Office 결과 JSON의 단계 시간만 확인')
    args = parser.parse_args(argv)
    result = inspect(args.claude_root, args.local_appdata, args.project_root, args.session)
    from .environment_checks import inspect_environment
    result['environment'] = inspect_environment()
    from .usage_diagnostics import analyze_usage, inspect_office_timing
    result['usage'] = analyze_usage(args.usage_log)
    if args.office_result:
        result['officeTiming'] = inspect_office_timing(args.office_result)
    if args.report:
        from .diagnostic_report import write_report
        write_report(args.report, result)
        result['reportPath'] = str(args.report.absolute())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print('Company Agent 진단 — 설정 변경·모델 호출·업무 문서 열기 없음 (선택한 로그/결과만 별도 읽기)')
    print('확인 폴더:', result['projectRoot'])
    print('Claude 설정:', result['claudeConfigRoot'])
    for plugin in result['plugins']:
        print('등록된 플러그인:', plugin.get('version'), '/', plugin.get('scope'), '/', plugin.get('installPath'))
        print('설치 파일에 정의된 Hook:', ', '.join(plugin['configuredHooks']) or '확인 못함', '(실행 성공 증거는 아님)')
    print('사용자 설정의 플러그인 활성화:', flag(result.get('userPluginEnabled')))
    print('사용자 설정의 전체 Hook 끄기:', flag(result.get('userDisableAllHooks')))
    for rec in result['registrations']:
        print('설치 기록:', rec['coreVersion'], rec['scope'], '/ 설정 경로 일치:', flag(rec['configMatches']))
    print('개인 상태:', result.get('selectedStateRoot', '확인 못함'))
    print('관리 구조: 회사 기준 / 개인 업무 (프로젝트는 적용 범위, 별도 팀팩 없음)')
    print('회사 업무 기준:', result.get('companyPolicy', {}).get('status', '확인 못함'))
    if args.report:
        print('진단 화면:', result['reportPath'])
    if args.usage_log:
        print('사용량(선택한 로그의 관찰분):', json.dumps(result['usage']['tokens'], ensure_ascii=False))
        print(result['usage']['costReason'])
    print('\n업무별 준비 상태 (프로그램 실행 없이 확인):')
    print('진단에 사용한 Python:', result['environment']['python'])
    for item in result['environment']['features']:
        print('-', item['name'] + ':', item['status'], '/', item['requires'])
    print(result['environment']['notice'])
    if not result['sessions']:
        print('확인할 세션 기록이 없습니다. 저장 위치·설치 범위를 먼저 확인하세요.')
    for record in result['sessions']:
        print('\n세션:', record['sessionFile'], '/', record['updatedAt'])
        for event, row in record['hooks'].items():
            labels = {'output-produced': '안내 생성 완료(Claude 수신은 미확인)', 'started': '시작 기록만 있음', 'failed': '처리 실패', 'not-observed': '기록 없음'}
            print(event + ':', labels[row['status']], '/ 내부 처리(ms):', row.get('elapsedMs', '미확인'), '/ 후보:', ', '.join(row['candidateNames']) or '없음')
            if row.get('errorType'):
                print('오류 종류:', row['errorType'])
        print('본문 읽기:', record['loadMessage'])
        progress = record['workflowProgress']
        print('이번 요청 준비:', progress['decision'], '/', progress['bodyMessage'])
        print('업무 실행 관찰:', progress['operation'] or '없음', '/', progress['executionMessage'])
        if progress['operation']:
            print('실행 응답 시 본문 상태:', progress['bodyAtResponseMessage'], '(스킬 적용·결과 정확성 검증과 별개)')
        print('전체 목록 읽기:', flag(record['indexRead']), '/ 준비 단계:', record['executionMode'])
        print('목록 확인 교정:', record['reviewMessage'])
    for warning in result['warnings']:
        print('확인 필요:', warning)
    print('\n최근 세션이 문제 세션과 같은지 시간을 확인하세요. 필요하면 --session ID로 지정하세요.')
    print('유효한 조직 정책·명령줄 설정, 전체 실행 시간, Claude 수신·모델 적용 여부는 이 기록만으로 확인할 수 없습니다.')
    return 0
