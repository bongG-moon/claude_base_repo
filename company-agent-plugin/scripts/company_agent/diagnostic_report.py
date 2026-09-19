"""Offline presentation of existing read-only diagnostics. No active scripts."""
from html import escape
from pathlib import Path


def render_report(report: dict) -> str:
    labels = {'available':'확인됨', 'not-configured':'별도 기준 미설정', 'unavailable':'미확인',
              'not-requested':'로그 분석 미요청', 'observed':'관찰됨', 'partial':'부분 관찰',
              'pass':'검증 통과 기록', 'fail':'검증 실패 기록', 'not_applicable':'검증 대상 아님'}
    def value(item):
        if item is None:
            return '미확인'
        return escape(str(item))

    def rows(items):
        return ''.join('<tr><th>' + value(label) + '</th><td>' + value(content) + '</td></tr>' for label, content in items)

    policy = report.get('companyPolicy', {})
    body = '<h1>내 업무 환경 확인</h1><p>회사 관리 영역과 개인 업무 영역을 함께 확인합니다. 프로젝트는 적용 범위이며 별도 팀팩이 아닙니다.</p>'
    body += '<section><h2>회사 · 개인</h2><table>' + rows([
        ('회사 기준', labels.get(policy.get('status'), '미확인')), ('회사 기준 버전', policy.get('revision')),
        ('회사 기준 위치', policy.get('path')), ('개인 자료 위치', report.get('selectedStateRoot')),
        ('현재 작업 폴더', report.get('projectRoot')), ('Claude 설정 위치', report.get('claudeConfigRoot')),
    ]) + '</table><p>필수 기준은 유지하고 회사 기본값만 개인화합니다. 업무 지침 확인이며 시스템 접근 권한 검사는 아닙니다. 참고 지식은 실행 정책이 아닙니다.</p></section>'
    body += '<section><h2>업무별 준비 상태</h2><p>설치·패키지 확인은 실제 실행 성공이 아닙니다.</p><table>'
    body += rows((item['name'], item['status'] + ' / ' + item['requires']) for item in report.get('environment', {}).get('features', []))
    body += '</table></section><section><h2>최근 스킬 사용과 결과 확인</h2>'
    if not report.get('sessions'):
        body += '<p>관찰 기록 없음. 미실행·다른 세션·설정 문제를 이 정보만으로 구분할 수 없습니다.</p>'
    for session in report.get('sessions', []):
        body += '<h3>' + value(session.get('sessionFile')) + '</h3><table>'
        body += rows([('본문 로드', session.get('loadMessage')), ('목록 확인', session.get('reviewMessage')),
                      ('업무 도구 호출 수', session.get('taskToolCount')), ('실패 기록 수', session.get('taskFailureCount')),
                      ('결과 검증 기록', labels.get(session.get('verificationStatus'), '미확인'))])
        progress = session.get('workflowProgress', {})
        body += rows([('현재 본문 관찰', progress.get('bodyMessage')),
                      ('최근 업무 명령', progress.get('operation')),
                      ('업무 실행 응답', progress.get('executionMessage')),
                      ('실행 응답 시 본문 상태', progress.get('bodyAtResponseMessage') if progress.get('operation') else None)])
        for event, hook in session.get('hooks', {}).items():
            body += rows([(event + ' 준비 처리(ms)', hook.get('elapsedMs')), (event + ' 안내 크기(문자)', hook.get('contextChars'))])
        body += '</table><p>본문 로드나 도구 호출만으로 결과의 정확성을 보장하지 않습니다. 검증 기록은 기록된 범위만 뜻합니다.</p>'
    body += '</section><section><h2>시간 · 사용량</h2>'
    usage = report.get('usage', {})
    body += '<p>사용자가 선택한 로그만 분석합니다. 원문·명령·파일 내용은 표시하지 않습니다.</p><table>'
    body += rows([('분석 상태', labels.get(usage.get('status', 'not-requested'), '미확인')), ('로그 관찰 구간(ms, 사용자 대기 포함)', usage.get('observedSpanMs')),
                  ('입력 토큰(관찰분)', usage.get('tokens', {}).get('input_tokens')),
                  ('출력 토큰(관찰분)', usage.get('tokens', {}).get('output_tokens')),
                  ('캐시 읽기 토큰(관찰분)', usage.get('tokens', {}).get('cache_read_input_tokens')),
                  ('캐시 생성 토큰(관찰분)', usage.get('tokens', {}).get('cache_creation_input_tokens')),
                  ('해석하지 못한 기록', usage.get('skippedRecords') if usage.get('status') != 'not-requested' else None),
                  ('식별자 없는 사용량 기록', usage.get('usageRecordsWithoutId') if usage.get('status') != 'not-requested' else None),
                  ('동일 범위 재읽기', usage.get('sameRangeReads')), ('비용', '단가 미설정 · 미확인')])
    body += '</table><p>누락·부분 로그는 전체 사용량이 아닙니다. 필요한 재확인도 재읽기에 포함될 수 있습니다.</p>'
    if usage.get('toolCalls'):
        body += '<h3>관찰된 도구 요청</h3><table>' + rows(usage['toolCalls'].items()) + '</table><p>요청 횟수이며 실제 실행·성공 횟수는 아닙니다.</p>'
    timing = report.get('officeTiming', {})
    if timing:
        from .office_progress import LABELS
        body += '<h3>선택한 Office 결과의 처리 시간</h3><table>'
        body += rows((LABELS.get(key, '실행기 준비') + ' (ms)', val) for key, val in timing.get('stageMs', {}).items())
        body += '</table><p>' + value(timing.get('notice')) + '</p>'
    body += '</section><section><h2>다음 확인</h2><ul>'
    for warning in report.get('warnings', []):
        body += '<li>' + value(warning) + '</li>'
    body += '<li>문제가 발생한 세션과 같은지 확인하세요. 미확인은 실패나 승인 거절을 뜻하지 않습니다.</li><li>설정 초기화·재설치·업무 재실행은 이 보고서가 자동으로 수행하지 않습니다.</li></ul></section>'
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Company Agent 업무 환경 확인</title><style>body{font:16px/1.8 system-ui,'Malgun Gothic',sans-serif;color:#203b4b;background:#f4f7f8;margin:0}main{max-width:960px;margin:auto;padding:28px}section{background:white;border:1px solid #dce5e8;border-radius:12px;padding:22px;margin:20px 0}h1{font-size:30px}h2{font-size:22px}table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #e1e8eb;overflow-wrap:anywhere}th{width:34%}p{color:#405765}h3{overflow-wrap:anywhere}@media(max-width:600px){main{padding:14px}section{padding:14px}td,th{padding:8px}}</style><main>''' + body + '</main></html>'


def write_report(path: Path, report: dict) -> None:
    from .skill_registry import _no_reparse
    path = Path(path).absolute()
    _no_reparse(path)
    if path.suffix.casefold() != '.html':
        raise ValueError('report output must be HTML')
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(render_report(report))
