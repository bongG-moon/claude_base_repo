"""Explicit scope selection for generated installers. Does not install anything."""
import argparse
import json
import sys
from pathlib import Path


def select_scope(scope=None, project_dir=None, *, interactive=None, ask=input):
    if interactive is None: interactive=sys.stdin.isatty()
    if scope is None:
        if not interactive:
            raise ValueError('설치 범위가 필요합니다. --scope project 또는 --scope user를 명시하세요.')
        print('설치 범위: 1) 현재 디렉토리(프로젝트)  2) 전역(내 계정)')
        while scope is None:
            choice=ask('1 또는 2를 선택하세요. 빈 입력은 선택하지 않습니다: ').strip()
            if choice.lower() in {'q','취소'}: raise ValueError('설치를 취소했습니다.')
            scope={'1':'project','2':'user'}.get(choice)
    if scope not in {'project','user'}: raise ValueError('scope는 project 또는 user여야 합니다.')
    target=Path(project_dir or Path.cwd()).expanduser().resolve() if scope=='project' else Path.home().resolve()
    if not target.is_dir(): raise ValueError('설치 기준 디렉토리가 없습니다.')
    return {'scope':scope,'baseDirectory':str(target)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='전역 기본값 없이 설치 범위를 선택합니다. 파일은 변경하지 않습니다.')
    parser.add_argument('--scope',choices=['project','user'])
    parser.add_argument('--project-dir',help='프로젝트 기준 경로. 미지정 시 터미널의 현재 디렉토리')
    args=parser.parse_args()
    try: result=select_scope(args.scope,args.project_dir)
    except (ValueError,EOFError,KeyboardInterrupt) as error: parser.exit(2,f'{error}\n')
    print(json.dumps(result,ensure_ascii=False))
