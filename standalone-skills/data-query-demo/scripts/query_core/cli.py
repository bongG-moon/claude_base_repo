"""모델에는 짧은 상태만 전달하는 독립 조회 명령."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from . import core
from .adapters import AdapterError
from .store import Store, read_json


def parser(engine):
    p = argparse.ArgumentParser(description='인증정보를 한 번 설정하고 테이블 경로의 데이터와 저장 쿼리를 조회합니다.' if engine == 'datalake' else '연결과 쿼리를 저장하고 필요한 조건으로 조회합니다. 데이터 행은 출력하지 않습니다.')
    p.add_argument('--state-root', type=Path)
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('start', help='이번 업무의 인증정보, 저장 쿼리와 이전 결과 요약 (접속 없음)' if engine == 'datalake' else '이번 업무의 연결, 저장 쿼리와 이전 결과 요약 (DB 접속 없음)')
    manage = commands.add_parser('manage', help='인증정보와 저장 쿼리 관리 화면' if engine == 'datalake' else 'DB와 저장 쿼리 관리 화면')
    manage.add_argument('--profile')
    profiles = commands.add_parser('profiles').add_subparsers(dest='action',required=True)
    profiles.add_parser('list')
    setup = profiles.add_parser('setup')
    setup.add_argument('--profile',help='기존 인증정보가 여러 개일 때 사용할 식별자' if engine == 'datalake' else '수정할 기존 연결 ID. 없으면 연결 추가')
    if engine == 'datalake':
        auth = commands.add_parser('auth', help='Data Lake 인증정보 설정. 테이블별 DB 등록은 불필요').add_subparsers(dest='action', required=True)
        for action in ('setup', 'import-env'):
            command = auth.add_parser(action)
            command.add_argument('--profile', help='기존 인증정보가 여러 개일 때 사용할 식별자')
            if action == 'import-env':
                command.add_argument('--file', type=Path)
                command.add_argument('--name')
        imported = profiles.add_parser('import-env', help='현재 작업 폴더의 .env 한 개만 가져오기')
        imported.add_argument('--file', type=Path)
        imported.add_argument('--profile')
        imported.add_argument('--name')
        discovery = commands.add_parser('discover', help='테이블과 컬럼, 파티션 메타데이터 탐색')
        operations = discovery.add_subparsers(dest='action', required=True)
        for action in ('tables', 'describe', 'show-create', 'explain'):
            operation = operations.add_parser(action)
            operation.add_argument('--profile', help='기존 인증정보가 여러 개일 때 사용할 식별자')
            if action == 'tables':
                operation.add_argument('--schema', required=True)
                operation.add_argument('--like', required=True)
                operation.add_argument('--limit', type=int, default=100)
            elif action == 'explain':
                operation.add_argument('--sql-file', required=True, type=Path)
            else:
                operation.add_argument('--table', required=True)
    queries = commands.add_parser('queries').add_subparsers(dest='action',required=True)
    queries.add_parser('list')
    register = queries.add_parser('register')
    register.add_argument('--spec',required=True,type=Path)
    register.add_argument('--replace-id',type=int)
    show = queries.add_parser('show')
    show.add_argument('--id',required=True,type=int)
    prepare = commands.add_parser('plan')
    prepare.add_argument('--id',required=True,type=int)
    prepare.add_argument('--params',required=True,type=Path)
    prepare.add_argument('--max-rows',type=int)
    prepare.add_argument('--max-bytes',type=int)
    prepare.add_argument('--timeout',type=int)
    run = commands.add_parser('run')
    run.add_argument('--plan',required=True)
    run.add_argument('--confirm',action='store_true')
    run.add_argument('--allow-large',action='store_true')
    direct = commands.add_parser('execute', help='명확히 요청한 일반 조회를 한 번에 준비하고 실행')
    direct.add_argument('--id', required=True, type=int)
    direct.add_argument('--params', required=True, type=Path)
    direct.add_argument('--confirm', action='store_true')
    direct.add_argument('--max-rows', type=int)
    direct.add_argument('--max-bytes', type=int)
    direct.add_argument('--timeout', type=int)
    results = commands.add_parser('results').add_subparsers(dest='action', required=True)
    listing = results.add_parser('list')
    listing.add_argument('--limit', type=int, default=20)
    cleanup_plan = results.add_parser('cleanup-plan')
    cleanup_plan.add_argument('--id', action='append', dest='result_ids')
    cleanup = results.add_parser('cleanup')
    cleanup.add_argument('--plan', required=True)
    cleanup.add_argument('--confirm', action='store_true')
    result = commands.add_parser('result')
    result.add_argument('--id',required=True)
    export = commands.add_parser('export-csv')
    export.add_argument('--id',required=True)
    export.add_argument('--output',required=True,type=Path)
    if engine == 'demo':
        commands.add_parser('demo-init')
    return p


def execute(engine, args):
    if engine not in {'oracle','datalake','ehub','demo'}:
        raise ValueError('지원하지 않는 조회 스킬입니다.')
    default = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'DataQuerySkills'
    root = args.state_root or default / ('demo' if engine=='demo' else 'personal')
    store = Store(root,demo=engine=='demo')
    if args.command == 'auth':
        if args.action == 'import-env':
            return store.import_datalake_env(args.file, name=args.name, profile_id=args.profile)
        from .setup_ui import show
        return show(store, engine, args.profile)
    if args.command == 'manage':
        from .manager_ui import show
        return show(store, engine, args.profile)
    if args.command == 'start':
        return startup(store, engine)
    if args.command == 'discover':
        from .discovery import discover
        return discover(store, engine, args)
    if args.command == 'results':
        from . import results
        if args.action == 'list':
            return results.list_results(store, engine, limit=args.limit)
        if args.action == 'cleanup':
            return results.delete_cleanup(store, engine, args.plan, confirmed=args.confirm)
        ids = args.result_ids
        if not ids:
            candidates = results.list_candidates(store, engine)
            ids = [item['resultId'] for item in candidates['results']]
        if not ids:
            return {'ok': True, 'status': 'nothing_to_cleanup', 'count': 0, 'dataRowsReturned': 0}
        return results.prepare_cleanup(store, engine, ids)
    if args.command == 'profiles':
        if args.action == 'list':
            return {'ok':True,'profiles':store.profiles(engine),'connected':False}
        if args.action == 'import-env':
            return store.import_datalake_env(args.file, name=args.name, profile_id=args.profile)
        from .setup_ui import show
        return show(store,engine,args.profile)
    if args.command == 'queries':
        if args.action == 'list':
            return {'ok':True,'queries':store.queries(engine)}
        if args.action == 'show':
            query = store.query(args.id,engine)
            return {'ok':True,'query':query,'sourceName':store.profile(query['profile'])['name'],'executed':False}
        return dict(ok=True, **store.save_query(read_json(args.spec),engine,query_id=args.replace_id))
    if args.command in {'plan', 'execute'}:
        if args.command == 'execute' and not args.confirm:
            raise ValueError('SQL과 조회 조건이 명확한 사용자 요청을 확인한 뒤 실행해 주세요.' if engine == 'datalake' else '조회할 DB와 쿼리, 조건이 명확한 사용자 요청을 확인한 뒤 실행해 주세요.')
        options = {k:getattr(args,k) for k in core.DEFAULTS if getattr(args,k) is not None}
        if args.command == 'plan':
            return core.plan(store,engine,args.id,read_json(args.params),options)
        return core.execute(store, engine, args.id, read_json(args.params), options, confirmed=True)
    if args.command == 'run':
        return core.run(store,engine,args.plan,confirmed=args.confirm,allow_large=args.allow_large)
    if args.command == 'result':
        return core.result_info(store,args.id)
    if args.command == 'export-csv':
        return core.export_csv(store,args.id,args.output)
    if args.command == 'demo-init':
        return core.demo_init(store)
    raise ValueError('지원하지 않는 동작입니다.')


def startup(store, engine):
    """업무 시작 때만 메타정보를 요약합니다. 조회마다 실행하거나 행을 읽지 않습니다."""
    from . import results
    profiles, queries = store.profiles(engine), store.queries(engine)
    candidates = results.list_candidates(store, engine)
    items = candidates['results']
    cleanup = None
    if items:
        try:
            cleanup = results.prepare_cleanup(store, engine, [item['resultId'] for item in items])
        except (ValueError, OSError):
            # 이전 결과의 변경/잠금은 새 조회를 막을 이유가 아닙니다.
            cleanup = {'ok': False, 'status': 'retained', 'count': 0,
                       'message': '변경되었거나 확인할 수 없는 이전 결과는 유지하고 조회를 계속합니다.'}
    result = {'ok': True, 'status': 'ready', 'profiles': profiles[:20], 'profileCount': len(profiles),
            'queries': queries[:20], 'queryCount': len(queries), 'limits': core.default_limits(engine),
            'previousResults': candidates, 'cleanup': cleanup, 'connected': False, 'dataRowsReturned': 0}
    if engine == 'datalake':
        result['credentialHelp'] = credential_help()
        result['targetSelection'] = 'table-path'
    return result


def credential_help():
    return {'keyPage': 'https://lake.skhynix.com/myprofile/mykey',
            'requiredFields': ['사번', 'JWT Token', 'S3 Access Key', 'S3 Secret Key'],
            'message': '사내 SSO로 로그인한 뒤 My Key에서 네 가지 값을 확인하거나 발급하세요. 인증값은 채팅에 보내지 말고 로컬 인증 설정 화면에 입력하세요. 테이블 경로가 조회 대상을 정하므로 테이블마다 DB를 등록하지 않습니다.'}


def main(engine, argv=None):
    args = parser(engine).parse_args(argv)
    try:
        result = execute(engine,args)
        code = 0 if result.get('ok') else 2
    except ImportError:
        result = {'ok':False,'status':'dependency_missing','message':'이 스킬의 requirements.txt에 적힌 Python 패키지를 준비해 주세요.'}
        code = 2
    except AdapterError as error:
        result = {'ok':False,'status':error.code,'message':error.message,'dataRowsReturned':0}
        if engine == 'datalake' and error.code in {'auth_config', 'api_401', 'api_403'}:
            result['credentialHelp'] = credential_help()
        code = 2
    except (ValueError, OSError, RuntimeError) as error:
        # SQL/접속 모듈은 정해진 오류만 내보냅니다. 파일 오류는 원문 경로를 숨깁니다.
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            message = str(error)
            status = 'input_required'
        else:
            message = '작업을 완료하지 못했습니다. 입력 파일과 개인 저장소, 연결 상태를 확인해 주세요.'
            status = 'failed'
        result = {'ok':False,'status':status,'message':message,'dataRowsReturned':0}
        code = 2
    except Exception:
        result = {'ok':False,'status':'failed','message':'조회 준비 또는 실행을 완료하지 못했습니다. 접속 정보와 조회 조건을 확인해 주세요.','dataRowsReturned':0}
        code = 2
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return code
