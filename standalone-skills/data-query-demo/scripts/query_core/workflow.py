"""A의 새 조회 결과를 Python에서 조건으로 추려 B로 전달합니다."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import re
import time
import uuid

from . import core
from .preview import MAX_LINE_BYTES, result_metadata
from .sql import MAX_LIST, bind_params
from .store import atomic_json, fingerprint, read_json, safe_path

MAX_PARAMETER_BYTES = 100_000
ID = re.compile(r'[0-9a-f]{32}')


def _path(store, workflow_id):
    if not isinstance(workflow_id, str) or not ID.fullmatch(workflow_id):
        raise ValueError('업무 흐름 번호를 확인해 주세요.')
    return safe_path(store.root / 'workflows' / (workflow_id + '.json'))


def _save(store, record):
    atomic_json(_path(store, record['workflowId']), record)


def _completion_path(store, workflow_id, plan_id):
    if not isinstance(plan_id, str) or not ID.fullmatch(plan_id):
        raise ValueError('조회 준비 번호를 확인해 주세요.')
    folder = _path(store, workflow_id).parent
    return safe_path(folder / (workflow_id + '.' + plan_id + '.completion.json'))


@contextmanager
def _lock(store, workflow_id):
    path = safe_path(_path(store, workflow_id).with_suffix('.lock'))
    token = uuid.uuid4().hex.encode('ascii')
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('이 업무 흐름은 실행 중이거나 중단 상태 확인이 필요합니다. 중복 조회하지 않았습니다.') from None
    try:
        os.write(descriptor, token)
        yield
    finally:
        os.close(descriptor)
        # 알 수 없는 잠금 파일이나 중단된 작업의 잠금을 자동 회수하지 않습니다.
        if path.is_file() and path.read_bytes() == token:
            path.unlink()


def _summary(store, record):
    output = {'ok': record['state'] in {'complete', 'empty_source', 'empty_source_keys'},
              'status': record['state'], 'workflowId': record['workflowId'],
              'workflowFile': str(_path(store, record['workflowId'])),
              'sourceResultId': record.get('sourceResultId'), 'targetResultId': record.get('targetResultId'),
              'sourceRows': record.get('sourceRows'), 'targetRows': record.get('targetRows'),
              'sourceComplete': record.get('sourceComplete'), 'targetComplete': record.get('targetComplete'),
              'keyCount': record.get('keyCount', 0), 'nullKeysSkipped': record.get('nullKeysSkipped', 0),
              'dataRowsReturned': 0, 'message': record.get('message', '')}
    if record.get('pending'):
        pending = record['pending']
        output.update({key: pending[key] for key in ('planId', 'limits', 'requiresLargeApproval', 'conditionsTruncated') if key in pending})
        output['pendingStage'] = pending['stage']
        output['conditionReviewFile'] = str(_path(store, record['workflowId']))
    if record.get('keyCountAtLeast') is not None:
        output['keyCountAtLeast'] = record['keyCountAtLeast']
    if record.get('failedStage'):
        output['failedStage'] = record['failedStage']
    if record['state'] == 'partial_target':
        output.update(complete=False, outcome='partial', reason=record.get('targetReason'))
    return output


def _validate(store, engine, spec):
    if not isinstance(spec, dict) or set(spec) - {'source', 'target', 'allowPartialSource'}:
        raise ValueError('source, target과 부분 결과 사용 여부만 지정해 주세요.')
    if type(spec.get('allowPartialSource', False)) is not bool:
        raise ValueError('부분 결과 사용 여부는 true 또는 false로 지정해 주세요.')
    queries = {}
    for stage in ('source', 'target'):
        step = spec.get(stage)
        allowed = {'queryId', 'params', 'options'} | ({'fromColumn', 'toParameter'} if stage == 'target' else set())
        if (not isinstance(step, dict) or set(step) - allowed or type(step.get('queryId')) is not int
                or step['queryId'] < 1 or not isinstance(step.get('params', {}), dict)
                or not isinstance(step.get('options', {}), dict)):
            raise ValueError('각 단계의 쿼리 번호, 조건과 선택 한도를 확인해 주세요.')
        queries[stage] = store.query(step['queryId'], engine)
        core.limits(step.get('options'), engine)
    target = spec['target']
    if not isinstance(target.get('fromColumn'), str) or not 1 <= len(target['fromColumn']) <= 256:
        raise ValueError('A 결과에서 사용할 실제 컬럼 이름을 지정해 주세요.')
    parameter = target.get('toParameter')
    definition = queries['target']['parameters'].get(parameter) if isinstance(parameter, str) else None
    if not isinstance(definition, dict):
        raise ValueError('B 쿼리에 등록된 목록 조건 이름을 지정해 주세요.')
    kind = str(definition.get('type', 'text')).lower()
    if not (kind == 'list' or kind.startswith('list[') and kind.endswith(']')):
        raise ValueError('A의 값은 B 쿼리의 IN 목록 조건으로 전달해야 합니다.')
    if parameter in target.get('params', {}):
        raise ValueError('자동 전달할 목록 조건을 고정 조건에 중복 지정하지 마세요.')
    return queries


def _record_stage(store, record, stage, receipt):
    result_id = receipt.get('resultId')
    if not isinstance(result_id, str) or not ID.fullmatch(result_id):
        raise ValueError('조회 결과 번호를 확인하지 못했습니다. 다음 단계를 실행하지 않았습니다.')
    metadata, _ = result_metadata(store, record['engine'], result_id)
    if metadata.get('queryId') != record['spec'][stage]['queryId'] or metadata.get('queryHash') != record['queryHashes'][stage]:
        raise ValueError('업무 흐름의 쿼리와 결과가 일치하지 않습니다.')
    record[stage + 'ResultId'] = result_id
    record[stage + 'Rows'] = metadata.get('savedRows')
    record[stage + 'Complete'] = metadata.get('complete') is True
    record[stage + 'Reason'] = metadata.get('reason')
    record.pop('pending', None)
    failed = metadata.get('status') == 'failed' or metadata.get('dataAvailable') is False
    partial_target = stage == 'target' and not failed and metadata.get('complete') is not True
    record['state'] = 'failed' if failed else 'partial_target' if partial_target else 'source_ready' if stage == 'source' else 'complete'
    if failed:
        record['message'] = '조회가 실패하여 다음 단계는 실행하지 않았습니다.'
    elif partial_target:
        record['message'] = 'B는 일부 결과만 저장했습니다. 전체 조회가 완료된 것으로 해석하지 말고 중단 사유와 범위를 확인해 주세요.'
    elif stage == 'target':
        record['message'] = 'A와 B 조회를 마쳤습니다.' if metadata.get('savedRows') else 'A와 B 조회는 성공했지만 B 조건에 맞는 데이터는 0건입니다.'
    else:
        record['message'] = 'A 조회를 마쳤습니다.'
    _save(store, record)


def _wait(store, record, stage, proposal):
    plan_id = proposal.get('planId')
    if not isinstance(plan_id, str) or not ID.fullmatch(plan_id):
        raise ValueError('조회 준비 번호를 확인하지 못했습니다.')
    pending = {'stage': stage, 'planId': plan_id}
    pending.update({key: proposal[key] for key in ('limits', 'requiresLargeApproval', 'conditionsTruncated') if key in proposal})
    record.update(state='approval_required', pending=pending,
                  message='해당 단계의 조건과 한도를 확인한 뒤 같은 준비 번호로 실행하고 이 업무 흐름을 이어가세요.')
    context = {'workflowId': record['workflowId'], 'workflowFile': str(_path(store, record['workflowId'])), 'stage': stage}
    plan = store.get_plan(plan_id)
    plan['workflowContext'] = context
    with store.connect() as connection:
        if connection.execute('UPDATE plans SET body=? WHERE id=? AND used=0', (json.dumps(plan, ensure_ascii=False), plan_id)).rowcount != 1:
            raise ValueError('조회 준비가 이미 실행되었거나 변경되었습니다. 중복 실행하지 않았습니다.')
    _save(store, record)


def _execute_stage(store, record, stage, params):
    step = record['spec'][stage]
    try:
        record['state'] = 'running_' + stage
        record['message'] = '조회 단계가 실행 중입니다. 같은 단계를 다시 실행하지 마세요.'
        _save(store, record)
        receipt = core.execute(store, record['engine'], step['queryId'], params,
                               step.get('options'), confirmed=True)
        if receipt.get('executed') is False or receipt.get('requiresLargeApproval') and not receipt.get('resultId'):
            _wait(store, record, stage, receipt)
            return False
        _record_stage(store, record, stage, receipt)
        return record['state'] != 'failed'
    except Exception as error:
        result_id = getattr(error, 'result_id', None)
        if result_id:
            record[stage + 'ResultId'] = result_id
        record['state'], record['failedStage'] = 'failed', stage
        record['message'] = '조회가 실패하여 다음 단계는 실행하지 않았습니다.'
        _save(store, record)
        error.workflow_context = {'workflowId': record['workflowId'], 'workflowFile': str(_path(store, record['workflowId'])),
                                  'failedStage': stage, 'sourceResultId': record.get('sourceResultId'),
                                  'targetResultId': record.get('targetResultId')}
        raise


def _continue(store, record):
    if record['state'] != 'source_ready':
        return _summary(store, record)
    metadata, data = result_metadata(store, record['engine'], record['sourceResultId'])
    if not metadata.get('complete') and not record['spec'].get('allowPartialSource', False):
        record.update(state='partial_source', message='A가 일부 결과여서 B를 실행하지 않았습니다. 전체 결과를 조회하거나 부분 사용 범위를 명시해 주세요.')
        _save(store, record)
        return _summary(store, record)
    if metadata['savedRows'] == 0:
        record.update(state='empty_source', message='A 조회는 성공했지만 0건이어서 B는 실행하지 않았습니다.')
        _save(store, record)
        return _summary(store, record)
    name = record['spec']['target']['fromColumn']
    if metadata['columns'].count(name) != 1:
        raise ValueError('A의 전달 컬럼을 확인해 주세요. 이름이 겹치면 SQL 별칭으로 구분해 주세요.')
    column = metadata['columns'].index(name)
    digest = hashlib.sha256()
    values, seen = [], set()
    read_rows = nulls = 0
    with data.open('rb') as stream:
        while raw := stream.readline(MAX_LINE_BYTES + 1):
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError('A의 한 행이 너무 큽니다. 전달할 키 컬럼만 조회해 주세요.')
            digest.update(raw)
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ValueError('A 결과 파일의 행 형식을 확인해 주세요.') from None
            if not isinstance(row, list) or len(row) != len(metadata['columns']):
                raise ValueError('A 결과 파일의 컬럼 수를 확인해 주세요.')
            read_rows += 1
            value = row[column]
            if value is None:
                nulls += 1
                continue
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise ValueError('A의 전달 키는 문자열이나 숫자로 지정해 주세요.')
            token = json.dumps(value, ensure_ascii=False, allow_nan=False)
            if token not in seen:
                seen.add(token)
                values.append(value)
                if len(values) > MAX_LIST:
                    record.update(state='key_limit', keyCountAtLeast=len(values), nullKeysSkipped=nulls,
                                  message='전달할 고유값이 500개를 초과해 B를 실행하지 않았습니다. 임의 절단이나 자동 분할 없이 범위를 다시 정해 주세요.')
                    _save(store, record)
                    return _summary(store, record)
    if digest.hexdigest() != metadata.get('dataSha256') or read_rows != metadata['savedRows']:
        raise ValueError('A 결과 파일이 바뀌어 B를 실행하지 않았습니다. 원본 결과를 확인해 주세요.')
    record.update(keyCount=len(values), nullKeysSkipped=nulls)
    if not values:
        record.update(state='empty_source_keys', message='A에 전달할 키 값이 없어 B는 실행하지 않았습니다.')
        _save(store, record)
        return _summary(store, record)
    params = dict(record['spec']['target'].get('params', {}))
    params[record['spec']['target']['toParameter']] = values
    if len(json.dumps(params, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_PARAMETER_BYTES:
        record.update(state='parameter_limit', message='전달할 조건이 100KB를 초과해 B를 실행하지 않았습니다. 필요한 키 범위를 줄여 주세요.')
        _save(store, record)
        return _summary(store, record)
    target = store.query(record['spec']['target']['queryId'], record['engine'])
    profile = store.profile(target['profile'])
    bind_params(target['sql'], target['parameters'], params, profile['engine'])
    record['targetParams'] = params
    _save(store, record)
    _execute_stage(store, record, 'target', params)
    return _summary(store, record)


def run_workflow(store, engine, spec, *, confirmed=False):
    if not confirmed:
        raise ValueError('A에서 B로 이어갈 조회 조건을 사용자가 요청한 경우에 실행해 주세요.')
    queries = _validate(store, engine, spec)
    workflow_id = uuid.uuid4().hex
    record = {'schemaVersion': 1, 'workflowId': workflow_id, 'engine': engine,
              'spec': spec, 'specHash': fingerprint(spec), 'createdAt': time.time(), 'state': 'started',
              'queryHashes': {stage: fingerprint(query) for stage, query in queries.items()}}
    _save(store, record)
    with _lock(store, workflow_id):
        if not _execute_stage(store, record, 'source', spec['source'].get('params', {})):
            return _summary(store, record)
        return _safe_continue(store, record)


def _safe_continue(store, record):
    try:
        return _continue(store, record)
    except Exception as error:
        if not getattr(error, 'workflow_context', None):
            record.update(state='failed', failedStage='transfer', message='조건 전달을 확인하지 못해 B를 실행하지 않았습니다.')
            _save(store, record)
            error.workflow_context = {'workflowId': record['workflowId'], 'workflowFile': str(_path(store, record['workflowId'])),
                                      'failedStage': 'transfer', 'sourceResultId': record.get('sourceResultId'),
                                      'targetResultId': record.get('targetResultId')}
        raise


def _validate_completion(record, engine, stage, plan_id, metadata):
    if (record.get('engine') != engine or stage not in ('source', 'target')
            or metadata.get('planId') != plan_id
            or metadata.get('queryId') != record['spec'][stage]['queryId']
            or metadata.get('queryHash') != record['queryHashes'][stage]):
        raise ValueError('업무 흐름의 실행 계획과 완료 결과가 일치하지 않습니다.')
    if record.get(stage + 'ResultId') == metadata['resultId']:
        return False  # 이전 단계의 완료 표식을 다시 적용해 다음 단계의 상태를 덮지 않는다.
    pending = record.get('pending', {})
    if pending.get('stage') != stage or pending.get('planId') != plan_id:
        raise ValueError('업무 흐름과 실행 계획이 일치하지 않습니다.')
    return True


def _recover_completion(store, record):
    pending = record.get('pending')
    if not isinstance(pending, dict):
        return
    plan_id, stage = pending.get('planId'), pending.get('stage')
    path = _completion_path(store, record['workflowId'], plan_id)
    if not path.is_file():
        return
    marker = read_json(path, limit=4096)
    if (marker.get('schemaVersion') != 1 or marker.get('workflowId') != record['workflowId'] or marker.get('engine') != record['engine']
            or marker.get('stage') != stage or marker.get('planId') != plan_id):
        raise ValueError('업무 흐름의 완료 표식이 실행 계획과 일치하지 않습니다.')
    metadata, _ = result_metadata(store, record['engine'], marker.get('resultId'))
    if _validate_completion(record, record['engine'], stage, plan_id, metadata):
        _record_stage(store, record, stage, {'resultId': metadata['resultId']})


def record_plan_result(store, engine, proposal, receipt):
    """완료 표식을 먼저 보존해 계보 잠금 충돌 뒤에도 SQL 재실행 없이 복구한다."""
    context = proposal.get('workflowContext')
    if not isinstance(context, dict):
        return None
    path = _path(store, context.get('workflowId'))
    if safe_path(context.get('workflowFile', '')) != path:
        raise ValueError('업무 흐름 기록 위치가 일치하지 않습니다.')
    record = read_json(path, limit=2 * 1024 * 1024)
    if record.get('workflowId') != context['workflowId']:
        raise ValueError('업무 흐름 기록의 번호와 위치가 일치하지 않습니다.')
    plan_id, stage = proposal.get('planId'), context.get('stage')
    metadata, _ = result_metadata(store, engine, receipt.get('resultId'))
    if (metadata.get('queryId') != proposal.get('queryId')
            or metadata.get('queryHash') != proposal.get('queryHash')):
        raise ValueError('조회 준비와 완료 결과가 일치하지 않습니다.')
    needs_update = _validate_completion(record, engine, stage, plan_id, metadata)
    marker_path = _completion_path(store, context['workflowId'], plan_id)
    marker = {'schemaVersion': 1, 'workflowId': context['workflowId'], 'engine': engine,
              'stage': stage, 'planId': plan_id, 'resultId': metadata['resultId']}
    if needs_update:
        if marker_path.exists() and read_json(marker_path, limit=4096) != marker:
            raise ValueError('다른 완료 표식이 있습니다. 결과를 임의로 대체하지 않았습니다.')
        atomic_json(marker_path, marker)
    with _lock(store, context['workflowId']):
        record = read_json(path, limit=2 * 1024 * 1024)
        if record.get('workflowId') != context['workflowId']:
            raise ValueError('업무 흐름 기록의 번호와 위치가 일치하지 않습니다.')
        if _validate_completion(record, engine, stage, plan_id, metadata):
            _record_stage(store, record, stage, receipt)
        return {'workflowId': record['workflowId'], 'workflowFile': str(path), 'workflowState': record['state'],
                'nextStep': '같은 업무 흐름 번호로 resume하여 이어가세요.' if stage == 'source' else '업무 흐름 결과를 확인하세요.'}


def resume_workflow(store, engine, workflow_id, *, confirmed=False):
    if not confirmed:
        raise ValueError('이 업무 흐름의 이어가기를 요청한 경우에 실행해 주세요.')
    with _lock(store, workflow_id):
        record = read_json(_path(store, workflow_id), limit=2 * 1024 * 1024)
        if record.get('workflowId') != workflow_id or record.get('engine') != engine:
            raise ValueError('이 스킬의 업무 흐름 번호를 선택해 주세요.')
        if record.get('specHash') != fingerprint(record.get('spec')):
            raise ValueError('업무 흐름 명세가 변경되었습니다. 현재 조건을 다시 확인해 주세요.')
        queries = _validate(store, engine, record['spec'])
        if record['queryHashes'] != {stage: fingerprint(query) for stage, query in queries.items()}:
            raise ValueError('업무 흐름의 쿼리가 바뀌었습니다. 예전 결과로 자동 이어가지 않았습니다.')
        _recover_completion(store, record)
        return _safe_continue(store, record)
