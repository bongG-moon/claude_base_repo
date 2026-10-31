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
    p = argparse.ArgumentParser(description='연결과 쿼리를 저장하고 필요한 조건으로 조회합니다. 데이터 행은 출력하지 않습니다.')
    p.add_argument('--state-root', type=Path)
    commands = p.add_subparsers(dest='command', required=True)
    profiles = commands.add_parser('profiles').add_subparsers(dest='action',required=True)
    profiles.add_parser('list')
    setup = profiles.add_parser('setup')
    setup.add_argument('--profile',help='수정할 기존 연결 ID. 없으면 연결 추가')
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
    if args.command == 'profiles':
        if args.action == 'list':
            return {'ok':True,'profiles':store.profiles(engine),'connected':False}
        from .setup_ui import show
        return show(store,engine,args.profile)
    if args.command == 'queries':
        if args.action == 'list':
            return {'ok':True,'queries':store.queries(engine)}
        if args.action == 'show':
            query = store.query(args.id,engine)
            return {'ok':True,'query':query,'sourceName':store.profile(query['profile'])['name'],'executed':False}
        return dict(ok=True, **store.save_query(read_json(args.spec),engine,query_id=args.replace_id))
    if args.command == 'plan':
        options = {k:getattr(args,k) for k in core.DEFAULTS if getattr(args,k) is not None}
        return core.plan(store,engine,args.id,read_json(args.params),options)
    if args.command == 'run':
        return core.run(store,engine,args.plan,confirmed=args.confirm,allow_large=args.allow_large)
    if args.command == 'result':
        return core.result_info(store,args.id)
    if args.command == 'export-csv':
        return core.export_csv(store,args.id,args.output)
    if args.command == 'demo-init':
        return core.demo_init(store)
    raise ValueError('지원하지 않는 동작입니다.')


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
