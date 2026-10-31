"""조회 준비, 조건 확인과 파일 전달. 원본 데이터 행은 반환값에 넣지 않습니다."""
from __future__ import annotations

import csv
import datetime as dt
import decimal
import json
from pathlib import Path
import time
import uuid

from .store import Store, atomic_json, fingerprint, read_json, safe_path

DEFAULTS = {'max_rows':10_000, 'max_bytes':20*1024*1024, 'timeout':30}
# 큰 조회도 명시적 동의 후 이 실행기의 유한한 상한 안에서 처리합니다.
CEILINGS = {'max_rows':1_000_000, 'max_bytes':512*1024*1024, 'timeout':1800}


def limits(values):
    result = dict(DEFAULTS)
    for key, value in (values or {}).items():
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


def plan(store: Store, engine, query_id, values, options=None):
    from .adapters import open_backend
    if not isinstance(values, dict):
        raise ValueError('조회 조건은 이름과 값으로 입력해 주세요.')
    selected = limits(options)
    query, profile, binds, analysis = _prepared(store, engine, query_id, values)
    # 연결 검사/추정은 이 명시적 조회 요청에서만 수행합니다. 등록과 목록은 접속하지 않습니다.
    connection_secrets = store.secrets(profile['id'])
    with open_backend(profile, connection_secrets, demo=store.demo,
                      timeout_seconds=min(selected['timeout'], 10)) as backend:
        observation = backend.inspect(query['sql'], binds)
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
    if estimated is not None and estimated > DEFAULTS['max_rows']:
        risks.append('예상 결과가 기본 조회 범위보다 큽니다.')
    if observation.get('plan_max_rows', 0) and observation['plan_max_rows'] > DEFAULTS['max_rows']:
        risks.append('실행계획에 큰 중간 처리량이 관찰됐습니다. 결과 건수와는 다릅니다.')
    if any(selected[k] > DEFAULTS[k] for k in selected):
        risks.append('기본 한도를 확대하는 조회입니다.')
    risks = list(dict.fromkeys(risks))
    body = {'queryId':query['id'], 'queryHash':fingerprint(query), 'profileHash':fingerprint(profile),
            'connectionHash':fingerprint(connection_secrets),
            'engine':engine, 'params':values, 'limits':selected, 'createdAt':time.time(),
            'requiresLargeApproval':bool(risks), 'risks':risks,
            'knownOverLimit': exact is not None and exact > selected['max_rows']}
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
            'requiresLargeApproval':bool(risks), 'risks':risks,
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


def run(store: Store, engine, plan_id, *, confirmed=False, allow_large=False):
    from .adapters import open_backend
    if not confirmed:
        raise ValueError('조회 조건을 사용자에게 먼저 확인해 주세요.')
    proposal = store.get_plan(plan_id)
    if proposal['engine'] != engine or time.time() - proposal['createdAt'] > 900:
        raise ValueError('조회 준비가 다른 스킬에 속하거나 15분이 지났습니다. 다시 준비해 주세요.')
    query, profile, binds, _ = _prepared(store, engine, proposal['queryId'], proposal['params'])
    if fingerprint(query) != proposal['queryHash'] or fingerprint(profile) != proposal['profileHash']:
        raise ValueError('SQL이나 연결 설정이 바뀌었습니다. 바뀐 조건으로 다시 준비해 주세요.')
    if proposal['requiresLargeApproval'] and not allow_large:
        return {'ok':False, 'status':'large_query_approval_required', 'planId':plan_id,
                'sourceName':profile['name'], 'limits':proposal['limits'],
                'message':'큰 조회의 범위와 한도를 안내하고 사용자 동의를 받은 뒤 실행해 주세요.', 'dataRowsReturned':0}
    if proposal['knownOverLimit']:
        return {'ok':False, 'status':'larger_limit_required', 'planId':plan_id,
                'message':'사용자가 허용한 행 수로 한도를 확대해 새 조회를 준비해 주세요. 아직 실행하지 않았습니다.', 'dataRowsReturned':0}
    selected = limits(proposal['limits'])
    secrets = store.secrets(profile['id'])
    if fingerprint(secrets) != proposal['connectionHash']:
        raise ValueError('접속 정보가 바뀌었습니다. 변경된 연결로 다시 준비해 주세요.')
    # 같은 준비 번호가 동시에 실행되거나 재시도로 중복 조회되지 않게 먼저 소비합니다.
    store.claim_plan(plan_id)
    result_id = uuid.uuid4().hex
    folder = safe_path(store.root / 'results' / result_id)
    folder.mkdir(parents=True, exist_ok=False)
    data = folder / 'data.jsonl'
    start = time.monotonic()
    count = written = 0
    columns = []
    status = 'complete'
    reason = None
    try:
        with open_backend(profile, secrets, demo=store.demo, timeout_seconds=selected['timeout']) as backend:
            with backend.execute(query['sql'], binds, limit=selected['max_rows'], timeout_seconds=selected['timeout']) as result:
                columns, rows = result
                columns = list(columns)
                if not all(isinstance(c,str) and len(c) <= 256 for c in columns) or len(columns) > 500:
                    raise ValueError('조회 컬럼이 너무 많거나 형식이 맞지 않습니다.')
                with data.open('xb') as out:
                    for row in rows:
                        if time.monotonic() - start > selected['timeout']:
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
                        if written + len(chunk) > selected['max_bytes']:
                            status, reason = 'partial', 'byte_limit'
                            break
                        out.write(chunk)
                        written += len(chunk)
                        count += 1
    except Exception:
        # 생성 중인 원본 값이나 드라이버 예외를 대화로 전달하지 않습니다.
        if data.exists():
            data.unlink()
        atomic_json(folder / 'metadata.json', {'resultId':result_id, 'status':'failed', 'dataAvailable':False})
        raise
    metadata = {'ok':True, 'resultId':result_id, 'sourceName':profile['name'], 'queryName':query['name'],
                'status':status, 'complete':status=='complete', 'reason':reason, 'savedRows':count,
                'columnCount':len(columns), 'columns':columns, 'limits':selected, 'demo':store.demo,
                'elapsedMs':round((time.monotonic()-start)*1000), 'dataBytes':written,
                'dataFile':str(data), 'format':'jsonl-arrays', 'params':proposal['params'],
                'queryHash':proposal['queryHash'], 'planId':plan_id,
                'message':'조회 결과를 로컬에 저장했습니다.' if status=='complete' else '일부 데이터만 저장했습니다. 전체 결과로 해석하지 말고 범위 또는 한도를 다시 지정해 주세요.',
                'dataRowsReturned':0}
    atomic_json(folder / 'metadata.json', metadata)
    return receipt(metadata)


def receipt(metadata):
    keys = ('ok','resultId','sourceName','queryName','status','complete','reason','savedRows',
            'columnCount','demo','elapsedMs','dataBytes','dataFile','format','message','dataRowsReturned')
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
    info = result_info(store, result_id)
    if info.get('status') == 'failed':
        raise ValueError('실패한 조회에는 내보낼 데이터가 없습니다.')
    metadata = read_json(store.root / 'results' / result_id / 'metadata.json', limit=2*1024*1024)
    output = safe_path(output)
    if output.suffix.lower() != '.csv':
        raise ValueError('CSV 파일 이름을 지정해 주세요.')
    def spreadsheet_safe(v):
        # Excel이 문자열을 수식으로 실행하지 않게 표시용 CSV에서만 보호합니다.
        return "'"+v if isinstance(v,str) and (v.lstrip().startswith(('=','+','-','@')) or v.startswith(('\t','\r'))) else v
    with output.open('x', newline='', encoding='utf-8-sig') as out:
        writer = csv.writer(out)
        writer.writerow([spreadsheet_safe(v) for v in metadata['columns']])
        for row in load_result_rows(metadata['dataFile']):
            writer.writerow([spreadsheet_safe(v) for v in row])
    return {'ok':True, 'filePath':str(output), 'savedRows':metadata['savedRows'],
            'complete':metadata['complete'], 'format':'csv', 'dataRowsReturned':0,
            'message':'CSV는 Excel용 수식 문자열 보호를 적용했습니다. 원본 값은 JSONL에 유지됩니다.'}


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
