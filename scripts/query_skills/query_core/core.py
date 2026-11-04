"""조회 준비, 조건 확인과 파일 전달. 원본 데이터 행은 반환값에 넣지 않습니다."""
from __future__ import annotations

from contextlib import contextmanager
import csv
import datetime as dt
import decimal
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import time
import threading
import uuid

from .store import Store, atomic_json, fingerprint, read_json, safe_path

DEFAULTS = {'max_rows':10_000, 'max_bytes':20*1024*1024, 'timeout':30}
# 큰 조회도 명시적 동의 후 이 실행기의 유한한 상한 안에서 처리합니다.
CEILINGS = {'max_rows':1_000_000, 'max_bytes':512*1024*1024, 'timeout':1800}
SIZE_EVIDENCE_SECONDS = 7 * 24 * 60 * 60
BEHAVIOR_RISK = '사용자 함수의 동작은 DB의 조회 전용 권한으로도 확인해야 합니다.'
COUNTABLE_SIZE_RISKS = {
    '조회 조건이 없는 데이터 범위가 있습니다.',
    '건너뛰는 행이 많아 조회 비용이 커질 수 있습니다.',
    '입력한 날짜 사이가 31일을 넘습니다. 긴 기간 조회인지 확인해 주세요.',
}
REPEATABLE_SIZE_RISKS = {
    '조회 조건이 없는 데이터 범위가 있습니다.',
    '건너뛰는 행이 많아 조회 비용이 커질 수 있습니다.',
    '입력한 날짜 사이가 31일을 넘습니다. 긴 기간 조회인지 확인해 주세요.',
    '결합 조건이 없는 조인이 있습니다.',
}


def default_limits(engine='demo'):
    result = dict(DEFAULTS)
    if engine in {'oracle', 'datalake', 'ehub'}:
        result['max_rows'] = 50_000
    if engine in {'oracle', 'ehub'}:
        result['timeout'] = 60
    if engine == 'datalake':
        result.update(max_bytes=None, timeout=None)
    return result


def limits(values, engine='demo'):
    result = default_limits(engine)
    for key, value in (values or {}).items():
        if engine == 'datalake' and key in {'max_bytes', 'timeout'}:
            if value is None:
                result[key] = None
                continue
            # JSON 정수 정밀도와 OS 대기 API가 지원하는 범위만 검사합니다.
            maximum = min(2**53 - 1, int(threading.TIMEOUT_MAX) - 1) if key == 'timeout' else 2**53 - 1
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('지정한 용량이나 시간을 이 실행 환경에서 처리할 수 없습니다. 제한 없이 조회하려면 해당 지정을 생략해 주세요.')
            result[key] = value
            continue
        if key not in result or type(value) is not int or not 1 <= value <= CEILINGS[key]:
            raise ValueError('조회 한도는 양의 정수로 설정하고 실행기의 최대 범위 안에서 지정해 주세요.')
        result[key] = value
    return result


def _prepared(store, engine, query_id, values):
    from .sql import bind_params, analyze_sql
    query = store.query(query_id, engine)
    profile = store.profile(query['profile'])
    binds = bind_params(query['sql'], query['parameters'], values, profile['engine'])
    analysis = analyze_sql(query['sql'], profile['engine'])
    return query, profile, binds, analysis


def _prepared_again(store, engine, query_id, values, prepared):
    """Reuse parsing only within one call after rechecking mutable definitions."""
    if prepared is None:
        return _prepared(store, engine, query_id, values)
    query, profile, binds, analysis = prepared
    current_query = store.query(query_id, engine)
    current_profile = store.profile(current_query['profile'])
    if fingerprint(current_query) != fingerprint(query) or fingerprint(current_profile) != fingerprint(profile):
        raise ValueError('SQL이나 연결 설정이 바뀌었습니다. 바뀐 조건으로 다시 준비해 주세요.')
    return current_query, current_profile, binds, analysis


def _size_evidence_key(body):
    return fingerprint({key:body[key] for key in ('engine', 'queryHash', 'profileHash',
                        'connectionHash', 'params', 'limits')})


def _request_identity(engine, query, profile, secrets, values, selected):
    return {'queryId':query['id'], 'queryHash':fingerprint(query), 'profileHash':fingerprint(profile),
            'connectionHash':fingerprint(secrets), 'engine':engine, 'params':values, 'limits':selected}


def _small_complete(metadata, defaults):
    if metadata.get('status') != 'complete' or metadata.get('complete') is not True:
        return False
    for key, field in (('max_rows', 'savedRows'), ('max_bytes', 'dataBytes'), ('timeout', 'elapsedMs')):
        value = metadata.get(field)
        if type(value) is not int or value < 0:
            return False
        maximum = defaults[key]
        if maximum is not None and value >= maximum * (1000 if key == 'timeout' else 1):
            return False
    return True


def _previous_small_query(store, body):
    risks = set(body['risks'])
    if not risks:
        return None
    defaults = default_limits(body['engine'])
    if any(defaults[k] is not None and body['limits'][k] > defaults[k] for k in defaults):
        return None
    with store.connect() as conn:
        row = conn.execute('SELECT body, checked FROM query_size_evidence WHERE id=?',
                           (_size_evidence_key(body),)).fetchone()
    if row is None or not 0 <= time.time() - row['checked'] <= SIZE_EVIDENCE_SECONDS:
        return None
    try:
        evidence = json.loads(row['body'])
    except (TypeError, ValueError):
        return None
    if (not risks <= REPEATABLE_SIZE_RISKS | {BEHAVIOR_RISK}
            or evidence.get('riskDigest') != fingerprint(body['risks'])
            or (BEHAVIOR_RISK in risks and evidence.get('behaviorApproved') is not True)):
        _forget_size_evidence(store, body)
        return None
    return evidence if _small_complete(evidence, defaults) else None


def _forget_size_evidence(store, proposal):
    if proposal.get('risks') == []:
        return  # Ordinary queries never create approval evidence.
    with store.connect() as conn:
        conn.execute('DELETE FROM query_size_evidence WHERE id=?', (_size_evidence_key(proposal),))


def _remember_size_evidence(store, proposal, metadata, *, behavior_approved=False):
    # Store only bounded proof of a completed query, never rows or credentials.
    if (not proposal['risks'] or not set(proposal['risks']) <= REPEATABLE_SIZE_RISKS | {BEHAVIOR_RISK}
            or (BEHAVIOR_RISK in proposal['risks'] and not behavior_approved)
            or not _small_complete(metadata, default_limits(proposal['engine']))):
        return
    evidence = {key:metadata[key] for key in ('status', 'complete', 'savedRows', 'dataBytes', 'elapsedMs', 'resultId')}
    evidence['riskDigest'] = fingerprint(proposal['risks'])
    if BEHAVIOR_RISK in proposal['risks']:
        evidence['behaviorApproved'] = True
    try:
        with store.connect() as conn:
            now = time.time()
            conn.execute('DELETE FROM query_size_evidence WHERE checked < ?', (now-SIZE_EVIDENCE_SECONDS,))
            conn.execute('INSERT OR REPLACE INTO query_size_evidence VALUES (?,?,?)',
                         (_size_evidence_key(proposal), json.dumps(evidence), now))
    except (OSError, sqlite3.Error):
        # An optional performance receipt must not turn a saved result into a failure.
        pass


@contextmanager
def _using_backend(profile, secrets, *, demo, timeout_seconds, reuse=None):
    """명시적인 한 번의 조회에서만 같은 연결을 쓰고 설정 변경은 거부합니다."""
    if reuse is not None:
        backend, connection_hash = reuse
        if fingerprint({'profile': profile, 'secrets': secrets, 'demo': demo}) != connection_hash:
            raise ValueError('연결 설정이 바뀌었습니다. 현재 설정으로 다시 조회해 주세요.')
        yield backend
    else:
        from .adapters import open_backend
        with open_backend(profile, secrets, demo=demo, timeout_seconds=timeout_seconds) as backend:
            yield backend


def execute(store: Store, engine, query_id, values, options=None, *, confirmed=False):
    """원래 요청이 명확한 일반 조회는 준비와 실행에 같은 연결을 사용합니다."""
    if not confirmed:
        raise ValueError('SQL과 조회 조건이 명확한 사용자 요청을 확인한 뒤 실행해 주세요.' if engine == 'datalake' else '조회할 DB와 쿼리, 조건이 명확한 사용자 요청을 확인한 뒤 실행해 주세요.')
    if not isinstance(values, dict):
        raise ValueError('조회 조건은 이름과 값으로 입력해 주세요.')
    selected = limits(options, engine)
    prepared = _prepared(store, engine, query_id, values)
    query, profile, _, _ = prepared
    secrets = store.secrets(profile['id'])
    identity = _request_identity(engine, query, profile, secrets, values, selected)
    deadline = time.monotonic() + selected['timeout'] if selected['timeout'] is not None else None
    try:
        with _using_backend(profile, secrets, demo=store.demo, timeout_seconds=selected['timeout']) as backend:
            reuse = (backend, fingerprint({'profile': profile, 'secrets': secrets, 'demo': store.demo}))
            proposal = plan(store, engine, query_id, values, options, _reuse=reuse,
                            _prepared_context=prepared, _secrets=secrets)
            if proposal['requiresLargeApproval'] or proposal['conditionsTruncated']:
                # 승인 대기 중 연결을 보관하지 않습니다. 이후 같은 계획을 run으로 실행합니다.
                return dict(proposal, executed=False,
                            nextStep='표시한 범위 또는 전체 조건을 확인한 뒤 같은 준비 번호로 실행하세요.')
            return run(store, engine, proposal['planId'], confirmed=True, _reuse=reuse,
                       _prepared_context=prepared, _execution_deadline=deadline)
    except Exception:
        # Opening a backend can fail before plan/run has consumed the proof.
        _forget_size_evidence(store, identity)
        raise


def plan(store: Store, engine, query_id, values, options=None, *, _reuse=None, _prepared_context=None, _secrets=None):
    if not isinstance(values, dict):
        raise ValueError('조회 조건은 이름과 값으로 입력해 주세요.')
    selected = limits(options, engine)
    if engine == 'datalake' and not store.demo and selected['timeout'] is not None:
        raise ValueError('현재 lakes SDK에는 조회 취소와 시간 제한을 전달하는 규격이 확인되지 않았습니다. Datalake의 --timeout 지정을 생략해 주세요.')
    defaults = default_limits(engine)
    query, profile, binds, analysis = _prepared_context if _prepared_context is not None else _prepared(store, engine, query_id, values)
    # 연결 검사/추정은 이 명시적 조회 요청에서만 수행합니다. 등록과 목록은 접속하지 않습니다.
    connection_secrets = store.secrets(profile['id']) if _secrets is None else _secrets
    identity = _request_identity(engine, query, profile, connection_secrets, values, selected)
    try:
        with _using_backend(profile, connection_secrets, demo=store.demo,
                            timeout_seconds=10 if selected['timeout'] is None else min(selected['timeout'], 10), reuse=_reuse) as backend:
            observation = backend.inspect(query['sql'], binds)
    except Exception:
        # E-HUB authenticates during inspection; never retain its earlier proof.
        _forget_size_evidence(store, identity)
        raise
    exact = observation.get('exact_count')
    estimated = observation.get('estimated_rows')
    for value in (exact, estimated):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('조회 규모 응답을 확인할 수 없습니다.')
    risks = list(analysis.get('riskReasons', []))
    dates = [v.date() if isinstance(v, dt.datetime) else v for v in binds.values() if isinstance(v, dt.date)]
    if len(dates) > 1 and (max(dates) - min(dates)).days > 31:
        risks.append('입력한 날짜 사이가 31일을 넘습니다. 긴 기간 조회인지 확인해 주세요.')
    if exact is not None and exact > selected['max_rows']:
        risks.append(f"현재 한도 {selected['max_rows']:,}행보다 결과가 많습니다. 확대할 행 수를 지정해 다시 준비하세요.")
    if estimated is not None and estimated > defaults['max_rows']:
        risks.append('예상 결과가 기본 조회 범위보다 큽니다.')
    if observation.get('plan_max_rows', 0) and observation['plan_max_rows'] > defaults['max_rows']:
        risks.append('실행계획에 큰 중간 처리량이 관찰됐습니다. 결과 건수와는 다릅니다.')
    if any(defaults[k] is not None and selected[k] > defaults[k] for k in selected):
        risks.append('기본 한도를 확대하는 조회입니다.')
    risks = list(dict.fromkeys(risks))
    body = {**identity, 'createdAt':time.time(),
            'requiresLargeApproval':bool(risks), 'risks':risks,
            'knownOverLimit': exact is not None and exact > selected['max_rows']}
    previous = _previous_small_query(store, body)
    if previous is not None:
        body['requiresLargeApproval'] = False
        body['sizeEvidenceResultId'] = previous['resultId']
        body['behaviorApprovalReused'] = previous.get('behaviorApproved') is True
    elif (exact is not None and exact <= selected['max_rows'] and risks
          and set(risks) <= COUNTABLE_SIZE_RISKS
          and not any(defaults[k] is not None and selected[k] > defaults[k] for k in selected)):
        # 이미 받은 정확한 건수가 작은데 다시 묻거나 COUNT하지 않습니다.
        # 함수/무조건 조인/큰 실행계획 등 별도 위험에는 이 판단을 쓰지 않습니다.
        body['requiresLargeApproval'] = False
    elif (engine in {'oracle', 'ehub'} and not store.demo and risks
          and set(risks) <= COUNTABLE_SIZE_RISKS and selected['max_rows'] == defaults['max_rows']
          and not any(defaults[k] is not None and selected[k] > defaults[k] for k in selected)):
        # A normal lookup never pays for COUNT. Only an unresolved size warning
        # gets a bounded probe, and unknown behavior/joins never execute here.
        from .adapters import AdapterError
        with _using_backend(profile, connection_secrets, demo=False,
                            timeout_seconds=selected['timeout'], reuse=_reuse) as backend:
            probe = getattr(backend, 'count_bounded', None)
            if probe is not None:
                try:
                    observed = probe(query['sql'], binds, limit=selected['max_rows'],
                                     timeout_seconds=min(2, selected['timeout']))
                except AdapterError as error:
                    _forget_size_evidence(store, body)
                    if error.code != 'count_timeout':
                        raise
                    body['sizeProbe'] = {'status': 'timeout', 'seconds': min(2, selected['timeout'])}
                else:
                    count, cap = observed.get('count'), observed.get('cap')
                    if (type(count) is not int or type(cap) is not int or cap != selected['max_rows'] + 1
                            or not 0 <= count <= cap or observed.get('complete') is not (count < cap)):
                        raise ValueError('조회 건수 확인 응답을 신뢰할 수 없습니다.')
                    body['sizeProbe'] = dict(observed, status='complete' if count < cap else 'over_limit')
                    body['requiresLargeApproval'] = count >= cap
                    body['knownOverLimit'] = count >= cap
                    if count < cap:
                        exact = count
                    else:
                        risks.append(f"최소 {cap:,}행으로 기본 한도를 넘습니다. 필요한 범위나 허용할 행 수를 확인해 주세요.")
    plan_id = store.save_plan(body)
    # 조건은 사용자가 입력한 범위만 표시합니다. 데이터 행/전체 실행계획은 내보내지 않습니다.
    conditions = json.loads(json.dumps(binds, ensure_ascii=False, default=str))
    condition_file = None
    truncated = len(json.dumps(conditions, ensure_ascii=False)) > 6000
    if truncated:
        # 긴 ID 목록을 모델에 반복 주입하지 않고 전체 조건은 로컬 검토 파일에 보존합니다.
        condition_file = safe_path(store.root / 'plans' / plan_id / 'conditions.json')
        atomic_json(condition_file, conditions)
        conditions = {k: {'preview':str(v)[:120], 'itemCount':len(v) if isinstance(v,list) else None}
                      for k,v in list(conditions.items())[:20]}
    return {'ok':True, 'status':'confirmation_required', 'planId':plan_id,
            'queryName':query['name'], 'sourceName':profile['name'], 'conditions':conditions,
            'conditionsTruncated':truncated, 'conditionReviewFile':str(condition_file) if condition_file else None,
            'exactCount':exact, 'estimatedRows':estimated, 'limits':selected,
            'requiresLargeApproval':body['requiresLargeApproval'], 'risks':risks,
            'sizeEvidenceReused':previous is not None,
            'sizeProbe':body.get('sizeProbe'),
            'notes':observation.get('notes', []) + analysis.get('advisories', []),
            'demo':store.demo, 'dataRowsReturned':0,
            'nextStep':'조건과 확대 범위를 사용자에게 한 번 확인한 뒤 이 준비 번호로 실행하세요.'}


def _cell(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        raise ValueError('바이너리 컬럼은 기본 조회에서 제외해 주세요.')
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (str,int,float,bool)):
        return value
    # LOB 등 임의 객체를 str로 읽거나 대용량으로 펼치지 않습니다.
    raise ValueError('자동 저장하지 않는 자료형이 있습니다. 필요한 일반 컬럼만 선택해 주세요.')


def run(store: Store, engine, plan_id, *, confirmed=False, allow_large=False, _reuse=None,
        _prepared_context=None, _execution_deadline=None):
    if not confirmed:
        raise ValueError('조회 조건을 사용자에게 먼저 확인해 주세요.')
    proposal = store.get_plan(plan_id)
    proposal['planId'] = plan_id
    if proposal['engine'] != engine or time.time() - proposal['createdAt'] > 900:
        raise ValueError('조회 준비가 다른 스킬에 속하거나 15분이 지났습니다. 다시 준비해 주세요.')
    query, profile, binds, _ = _prepared_again(store, engine, proposal['queryId'], proposal['params'], _prepared_context)
    if fingerprint(query) != proposal['queryHash'] or fingerprint(profile) != proposal['profileHash']:
        raise ValueError('SQL이나 연결 설정이 바뀌었습니다. 바뀐 조건으로 다시 준비해 주세요.')
    if proposal.get('sizeEvidenceResultId') and not allow_large and _previous_small_query(store, proposal) is None:
        return {'ok':False, 'status':'large_query_approval_required', 'planId':plan_id,
                'sourceName':profile['name'], 'limits':proposal['limits'],
                'message':'이전의 작은 완료 결과 근거가 만료되거나 바뀌었습니다. 표시한 조회 범위를 확인해 주세요.',
                'dataRowsReturned':0}
    if proposal['requiresLargeApproval'] and not allow_large:
        return {'ok':False, 'status':'large_query_approval_required', 'planId':plan_id,
                'sourceName':profile['name'], 'limits':proposal['limits'],
                'message':'큰 조회의 범위와 한도를 안내하고 사용자 동의를 받은 뒤 실행해 주세요.', 'dataRowsReturned':0}
    if proposal['knownOverLimit']:
        return {'ok':False, 'status':'larger_limit_required', 'planId':plan_id,
                'message':'사용자가 허용한 행 수로 한도를 확대해 새 조회를 준비해 주세요. 아직 실행하지 않았습니다.', 'dataRowsReturned':0}
    selected = limits(proposal['limits'], engine)
    remaining = selected['timeout']
    if _execution_deadline is not None:
        remaining = min(remaining, _execution_deadline - time.monotonic())
        if remaining <= 0:
            from .adapters import AdapterError
            raise AdapterError('query_timeout', '조회 준비 중 제한 시간이 지났습니다. 본 조회는 실행하지 않았습니다.')
    secrets = store.secrets(profile['id'])
    if fingerprint(secrets) != proposal['connectionHash']:
        raise ValueError('접속 정보가 바뀌었습니다. 변경된 연결로 다시 준비해 주세요.')
    # 같은 준비 번호가 동시에 실행되거나 재시도로 중복 조회되지 않게 먼저 소비합니다.
    store.claim_plan(plan_id)
    # Failure, interruption or a newly partial result must not retain an older
    # small-success receipt for the same request.
    _forget_size_evidence(store, proposal)
    result_id = uuid.uuid4().hex
    folder = safe_path(store.root / 'results' / result_id)
    folder.mkdir(parents=True, exist_ok=False)
    data = folder / 'data.jsonl'
    created = time.time()
    executed_at = dt.datetime.fromtimestamp(created, dt.timezone.utc).isoformat(timespec='seconds')
    from .results import result_label
    identity = {'schemaVersion':1, 'resultId':result_id, 'engine':engine, 'dbId':profile['id'],
                'queryId':query['id'], 'sourceName':profile['name'], 'queryName':query['name'],
                'createdAt':created, 'executedAt':executed_at,
                'label':result_label(query['name'], profile['name'], created, result_id),
                'params':proposal['params'], 'limits':selected, 'demo':store.demo,
                'queryHash':proposal['queryHash'], 'planId':plan_id}
    digest = hashlib.sha256()
    start = time.monotonic()
    count = written = 0
    columns = []
    status = 'complete'
    reason = None
    try:
        with _using_backend(profile, secrets, demo=store.demo, timeout_seconds=remaining, reuse=_reuse) as backend:
            with backend.execute(query['sql'], binds, limit=selected['max_rows'], timeout_seconds=remaining) as result:
                columns, rows = result
                columns = list(columns)
                if not all(isinstance(c,str) and len(c) <= 256 for c in columns) or len(columns) > 500:
                    raise ValueError('조회 컬럼이 너무 많거나 형식이 맞지 않습니다.')
                with data.open('xb') as out:
                    for row in rows:
                        if remaining is not None and time.monotonic() - start > remaining:
                            status, reason = 'partial', 'time_limit'
                            break
                        if count >= selected['max_rows']:
                            status, reason = 'partial', 'row_limit'
                            break
                        if len(row) != len(columns):
                            raise ValueError('조회 결과의 컬럼 수가 일치하지 않습니다.')
                        normalized = [_cell(v) for v in row]
                        if any(isinstance(v,str) and len(v) > 1_000_000 for v in normalized):
                            status, reason = 'partial', 'cell_limit'
                            break
                        chunk = (json.dumps(normalized, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')
                        if selected['max_bytes'] is not None and written + len(chunk) > selected['max_bytes']:
                            status, reason = 'partial', 'byte_limit'
                            break
                        out.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        count += 1
    except Exception as error:
        # 원본 행은 남기지 않고 마스킹된 진단과 실패 사실을 보존합니다.
        if data.exists():
            data.unlink()
        from .adapters import AdapterError
        details = dict(error.details) if isinstance(error, AdapterError) else {}
        message = error.message if isinstance(error, AdapterError) else '조회 결과를 파일로 마무리하지 못했습니다. 결과 형식과 저장 위치를 확인해 주세요.'
        failed = dict(identity, ok=False, status='failed', outcome='error', complete=False,
                      dataAvailable=False, emptyResult=None, errorCode=getattr(error, 'code', 'result_processing'),
                      errorDetails=details, message=message, dataRowsReturned=0)
        atomic_json(folder / 'metadata.json', failed)
        error.result_id = result_id
        _record_links(store, engine, proposal, receipt(failed))
        raise
    metadata = dict(identity, **{'ok':True,
                'status':status, 'complete':status=='complete', 'reason':reason, 'savedRows':count,
                'columnCount':len(columns), 'columns':columns, 'limits':selected, 'demo':store.demo,
                'elapsedMs':round((time.monotonic()-start)*1000), 'dataBytes':written,
                'dataFile':str(data), 'format':'jsonl-arrays', 'dataSha256':digest.hexdigest(),
                'dataAvailable':True, 'emptyResult':status=='complete' and count==0,
                'outcome':'empty' if status=='complete' and count==0 else 'rows_returned' if status=='complete' else 'partial',
                'message':('조회는 오류 없이 끝났지만 지정한 조건의 데이터는 0건입니다.' if count==0 else '조회 결과를 로컬에 저장했습니다.') if status=='complete' else '일부 데이터만 저장했습니다. 전체 결과로 해석하지 말고 범위 또는 한도를 다시 지정해 주세요.',
                'dataRowsReturned':0})
    atomic_json(folder / 'metadata.json', metadata)
    _remember_size_evidence(store, proposal, metadata,
                            behavior_approved=allow_large or proposal.get('behaviorApprovalReused') is True)
    _record_links(store, engine, proposal, metadata)
    return receipt(metadata)


def _record_links(store, engine, proposal, metadata):
    """명시적으로 시작한 등록 시험과 연결 조회의 계보만 갱신합니다."""
    if proposal.get('workflowContext'):
        try:
            from .workflow import record_plan_result
            record_plan_result(store, engine, proposal, receipt(metadata))
        except Exception:
            metadata['workflowLinkWarning'] = '조회 결과는 보존했지만 연결 작업의 기록을 갱신하지 못했습니다. 같은 조회를 자동 반복하지 마세요.'
    if proposal.get('validationContext'):
        try:
            from .registration import record_plan_validation
            record_plan_validation(store, engine, proposal, receipt(metadata))
        except Exception:
            metadata['validationLinkWarning'] = '조회 결과는 보존했지만 등록 시험 기록을 갱신하지 못했습니다. 같은 조회를 자동 반복하지 마세요.'


def receipt(metadata):
    keys = ('ok','resultId','sourceName','queryName','dbId','queryId','executedAt','label','status','complete','reason','savedRows',
            'columnCount','demo','elapsedMs','dataBytes','dataFile','format','message','dataRowsReturned',
            'outcome','emptyResult','dataAvailable','errorCode','errorDetails','workflowLinkWarning','validationLinkWarning')
    return {k:metadata[k] for k in keys if k in metadata}


def result_info(store, result_id):
    if not isinstance(result_id,str) or len(result_id)!=32 or any(c not in '0123456789abcdef' for c in result_id):
        raise ValueError('결과 번호가 올바르지 않습니다.')
    metadata = read_json(safe_path(store.root / 'results' / result_id / 'metadata.json'), limit=2*1024*1024)
    return receipt(metadata)


def load_result_rows(result_file):
    """후속 Python 처리용입니다. CLI나 모델 응답으로 전체 행을 출력하지 마세요."""
    with safe_path(result_file).open(encoding='utf-8') as source:
        for line in source:
            yield json.loads(line)


def export_csv(store, result_id, output):
    import os
    import stat

    info = result_info(store, result_id)
    if info.get('status') == 'failed':
        raise ValueError('실패한 조회에는 내보낼 데이터가 없습니다.')
    metadata = read_json(store.root / 'results' / result_id / 'metadata.json', limit=2*1024*1024)
    output = safe_path(output)
    if output.suffix.lower() != '.csv':
        raise ValueError('CSV 파일 이름을 지정해 주세요.')
    managed_exports = safe_path(store.root / 'results' / result_id / 'exports')
    if output.parent == managed_exports:
        managed_exports.mkdir(exist_ok=True)
    def spreadsheet_safe(v):
        # Excel이 문자열을 수식으로 실행하지 않게 표시용 CSV에서만 보호합니다.
        return "'"+v if isinstance(v,str) and (v.lstrip().startswith(('=','+','-','@')) or v.startswith(('\t','\r'))) else v
    created_identity = None
    exported_rows = 0
    source_digest = hashlib.sha256()
    try:
        with output.open('x', newline='', encoding='utf-8-sig') as out:
            created = os.fstat(out.fileno())
            created_identity = (created.st_dev, created.st_ino)
            writer = csv.writer(out)
            writer.writerow([spreadsheet_safe(v) for v in metadata['columns']])
            # 기존 JSONL→CSV 한 번의 읽기에서 행, 열과 원본 해시를 확인합니다.
            # 셀 안 줄바꿈은 행이 아니므로 CSV의 물리적 줄 수를 세지 않습니다.
            with safe_path(metadata['dataFile']).open('rb') as source:
                for line in source:
                    source_digest.update(line)
                    row = json.loads(line)
                    if not isinstance(row, list) or len(row) != len(metadata['columns']):
                        raise ValueError('저장 결과의 열 수가 조회 기록과 다릅니다. 같은 조회를 자동 반복하지 마세요.')
                    writer.writerow([spreadsheet_safe(v) for v in row])
                    exported_rows += 1
            if exported_rows != metadata['savedRows']:
                raise ValueError('저장 결과의 행 수가 조회 기록과 다릅니다. 같은 조회를 자동 반복하지 마세요.')
            expected_hash = metadata.get('dataSha256')
            if expected_hash and source_digest.hexdigest() != expected_hash:
                raise ValueError('저장 결과가 조회 이후 변경됐습니다. 같은 조회를 자동 반복하지 마세요.')
            out.flush()
            expected_bytes = out.buffer.tell()
        saved = safe_path(output).stat()
        if ((saved.st_dev, saved.st_ino) != created_identity or saved.st_size != expected_bytes):
            raise ValueError('CSV 저장 완료를 확인하지 못했습니다. 기존 결과 ID로 내보내기를 다시 하세요.')
    except Exception:
        # exclusive-create로 이번 호출이 만든 동일 파일만 정리합니다.
        # 이미 있던 사용자 파일이나 이후 다른 파일로 교체된 경로는 보존합니다.
        if created_identity is not None:
            try:
                current = safe_path(output).lstat()
                if (stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                        and (current.st_dev, current.st_ino) == created_identity):
                    output.unlink()
            except (ValueError, OSError):
                pass
        raise
    if output.parent == managed_exports:
        from .results import register_export
        register_export(store, result_id, output)
    return {'ok':True, 'filePath':str(output), 'savedRows':metadata['savedRows'],
            'exportedRows':exported_rows, 'outputBytes':saved.st_size,
            'deliveryVerification':'verified', 'verificationScope':'csv-file-only',
            'complete':metadata['complete'], 'format':'csv', 'dataRowsReturned':0,
            'message':'CSV는 Excel용 수식 문자열 보호를 적용했습니다. 원본 값은 JSONL에 유지됩니다.'}


def deliver_csv(store, result, directory):
    """실행 기록은 개인 저장소에 두고 전달할 CSV만 업무 폴더에 만든다."""
    try:
        directory = safe_path(directory)
        # 개인 저장소 내부에 사용자 결과 폴더를 섞지 않는다.
        if directory == store.root or store.root in directory.parents:
            raise ValueError('전달할 결과 폴더는 개인 저장소 밖에 지정해 주세요.')
        directory.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[^\w가-힣-]+', '_', result['sourceName'] + '_' + result['queryName'])[:80].strip('_') or '조회'
        stamp = re.sub(r'[^0-9]', '', result['executedAt'])[:14]
        suffix = '_일부' if not result['complete'] else ''
        output = directory / f"{name}_{stamp}_{result['resultId'][:8]}{suffix}.csv"
        exported = export_csv(store, result['resultId'], output)
    except (ValueError, OSError):
        return dict(result, exportStatus='failed',
                    exportMessage='조회는 끝났지만 전달용 CSV 저장에 실패했습니다. 기존 결과 ID로 내보내기를 다시 하세요. 같은 조회를 반복하지 마세요.')
    return dict(result, outputFile=exported['filePath'], exportStatus='complete',
                outputBytes=exported['outputBytes'], exportedRows=exported['exportedRows'],
                deliveryVerification=exported['deliveryVerification'],
                verificationScope=exported['verificationScope'],
                exportMessage=exported['message'])


def demo_init(store):
    if not store.demo:
        raise ValueError('실습 스킬에서만 가상 자료를 만들 수 있습니다.')
    profiles = [
        {'id':'production','name':'생산DB','engine':'oracle','demo_database':'production'},
        {'id':'quality','name':'품질DB','engine':'oracle','demo_database':'quality'},
        {'id':'lake','name':'실습 데이터레이크','engine':'datalake','demo_database':'production'},
        {'id':'hub','name':'실습 E-HUB','engine':'ehub','demo_database':'production'},
    ]
    for profile in profiles:
        try:
            store.profile(profile['id'])
        except ValueError:
            store.save_profile(profile)
    specs = [
        {'name':'생산실적조회','profile':p['id'],
         'sql':'SELECT work_date, process, quantity, lot_id FROM production_records WHERE work_date >= :start_date AND work_date < :end_date AND process = :process ORDER BY work_date, lot_id',
         'parameters':{'start_date':{'type':'date'},'end_date':{'type':'date'},'process':{'type':'text'}}} for p in profiles]
    specs.append({'name':'대량조회 실습','profile':'production','sql':'SELECT id, work_date, quantity FROM large_records','parameters':{}})
    for spec in specs:
        if not any(q['name']==spec['name'] and q['sourceName']==store.profile(spec['profile'])['name'] for q in store.queries('demo')):
            store.save_query(spec, 'demo')
    return {'ok':True, 'demo':True, 'queries':store.queries('demo'), 'networkCalls':0,
            'message':'가상 데이터 조회가 준비됐습니다. 같은 명령을 다시 실행해도 개인 수정 내용은 덮어쓰지 않습니다.'}
