"""쿼리 등록과 제한된 실제 시험 결과를 따로 기록합니다. 원본 행은 반환하지 않습니다."""
from __future__ import annotations

import datetime as dt
import json

from .adapters import AdapterError
from .store import atomic_json, fingerprint, read_json, safe_path

TEST_ROWS = 10


def _from_result(record, result):
    record.update(checkedAt=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                  resultId=result.get('resultId'))
    if result.get('status') == 'failed':
        stage = result.get('errorDetails', {}).get('stage')
        attempted = stage in {'query', 'fetch', 'timeout'} or result.get('errorCode') == 'result_processing'
        record.update(validationStatus='error', queryExecuted=attempted, message=result['message'],
                      errorCode=result.get('errorCode'), errorDetails=result.get('errorDetails', {}))
        return
    rows = result['savedRows']
    if result['complete'] and rows == 0:
        status, message = 'success_empty', '쿼리는 오류 없이 실행됐지만 지정한 조건에서 조회된 데이터는 0건입니다.'
    elif rows > 0 and (result['complete'] or result.get('reason') == 'row_limit'):
        status, message = 'success_with_rows', '시험 조회에서 데이터가 확인됐습니다. 최대 10행 범위의 확인이며 전체 건수나 이후 시점의 데이터는 보증하지 않습니다.'
    else:
        status, message = 'partial_inconclusive', '시험 조회가 제한으로 끝나 성공 여부를 충분히 확인하지 못했습니다.'
    record.update(validationStatus=status, queryExecuted=True, savedRows=rows,
                  resultComplete=result['complete'], message=message)


def record_plan_validation(store, engine, proposal, result):
    context = proposal['validationContext']
    query = store.query(context['queryId'], engine)
    path = _path(store, query['id'])
    record = read_json(path)
    if (context.get('queryHash') != fingerprint(query) or record.get('queryHash') != context['queryHash']
            or record.get('planId') != proposal['planId'] or record.get('validationStatus') != 'approval_required'):
        raise ValueError('현재 등록 시험과 연결된 조회 준비가 아닙니다.')
    _from_result(record, result)
    atomic_json(path, record)


def _path(store, query_id):
    if type(query_id) is not int or query_id < 1:
        raise ValueError('등록한 쿼리 번호를 확인해 주세요.')
    return safe_path(store.root / 'query-validations' / (str(query_id) + '.json'))


def validation_info(store, engine, query_id):
    query = store.query(query_id, engine)
    path = _path(store, query['id'])
    if not path.is_file():
        return {'validationStatus': 'not_tested', 'queryExecuted': False,
                'message': '실제 시험 조회 기록이 없습니다. 등록만으로 실행 성공을 판단하지 않습니다.'}
    value = read_json(path)
    if value.get('queryHash') != fingerprint(query):
        return {'validationStatus': 'stale', 'queryExecuted': False,
                'message': 'SQL이나 조건 정의가 바뀌어 이전 시험 결과를 현재 쿼리의 성공 근거로 사용하지 않습니다.'}
    return {key: value[key] for key in ('validationStatus', 'queryExecuted', 'checkedAt', 'resultId', 'savedRows',
            'resultComplete', 'errorCode', 'errorDetails', 'planId', 'message') if key in value}


def register_query(store, engine, spec, *, values=None, confirmed=False, query_id=None):
    from . import core
    from .sql import bind_params
    saved = store.save_query(spec, engine, query_id=query_id)
    query = store.query(saved['id'], engine)
    record = {'queryHash': fingerprint(query), 'queryId': saved['id'], 'queryExecuted': False,
              'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'sampleRowLimit': TEST_ROWS}
    response = dict(ok=True, registered=True, **saved, dataRowsReturned=0)
    conditions = {} if values is None else values
    try:
        profile = store.profile(query['profile'])
        if confirmed:
            bind_params(query['sql'], query['parameters'], conditions, profile['engine'])
    except ValueError as error:
        record.update(validationStatus='parameters_required', message=str(error))
    else:
        if not confirmed:
            record.update(validationStatus='not_tested', message='쿼리만 저장했습니다. 실제 시험 조회는 실행하지 않았습니다.')
        else:
            try:
                result = core.execute(store, engine, query['id'], conditions, {'max_rows': TEST_ROWS}, confirmed=True)
            except AdapterError as error:
                record.update(validationStatus='error', errorCode=error.code, errorDetails=error.details,
                              queryExecuted=error.details.get('stage') in {'query', 'fetch', 'timeout'}, message=error.message)
                if getattr(error, 'result_id', None):
                    record['resultId'] = error.result_id
                if getattr(error, 'credential_input', None):
                    response['credentialInput'] = error.credential_input
                response.update(ok=False)
            except ValueError as error:
                record.update(validationStatus='input_error', message=str(error))
                if getattr(error, 'credential_input', None):
                    response['credentialInput'] = error.credential_input
                if getattr(error, 'result_id', None):
                    record.update(validationStatus='result_error', queryExecuted=True, resultId=error.result_id)
                response.update(ok=False)
            except (OSError, RuntimeError) as error:
                record.update(validationStatus='result_error', message='시험 조회 결과를 저장하지 못했습니다. 로컬 저장 위치와 권한을 확인해 주세요.')
                if getattr(error, 'result_id', None):
                    record.update(queryExecuted=True, resultId=error.result_id)
                response.update(ok=False)
            else:
                if result.get('executed') is False:
                    record.update(validationStatus='approval_required', planId=result['planId'],
                                  message='쿼리는 저장됐지만 시험 조회에도 범위 검토나 큰 조회 승인이 필요해 아직 실행하지 않았습니다.')
                    response['planId'] = result['planId']
                    response['requiresLargeApproval'] = result['requiresLargeApproval']
                    response['conditionsTruncated'] = result['conditionsTruncated']
                    response['review'] = {key: result[key] for key in ('limits', 'notes', 'conditionReviewFile') if key in result}
                    plan = store.get_plan(result['planId'])
                    plan['validationContext'] = {'queryId': query['id'], 'queryHash': record['queryHash']}
                    with store.connect() as connection:
                        connection.execute('UPDATE plans SET body=? WHERE id=? AND used=0',
                                           (json.dumps(plan, ensure_ascii=False), result['planId']))
                else:
                    _from_result(record, result)
                    response['testResult'] = result
    path = _path(store, query['id'])
    atomic_json(path, record)
    response.update(status='query_registered_' + record['validationStatus'], validationStatus=record['validationStatus'],
                    validationFile=str(path), queryExecuted=record['queryExecuted'], executed=record['queryExecuted'], message=record['message'])
    for key in ('resultId', 'errorCode', 'errorDetails'):
        if key in record:
            response[key] = record[key]
    return response
