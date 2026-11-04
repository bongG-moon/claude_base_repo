"""Compact, read-only style reference entrypoint for the free HTML workflow."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent


class ReferenceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def runtime(name):
    """Prefer the bundled modules; only this exact source checkout may fall back.

    No installed harness, home folder, user configuration or profile is searched.
    A broken bundled dependency is reported instead of loading a different copy.
    """
    if (HERE / 'visual_engine/ppt_reference.py').is_file():
        location, namespace = HERE, 'visual_engine'
    elif (HERE == HERE.parents[2] / 'skills/presentation/scripts'
          and (HERE.parents[2] / 'scripts/company_agent/ppt_reference.py').is_file()):
        # A plugin supplies its own sibling runtime; never search installed profiles.
        location, namespace = HERE.parents[2] / 'scripts', 'company_agent'
    else:
        repository = HERE.parents[2]
        expected = repository / 'standalone-skills/presentation/scripts'
        location = repository / 'company-agent-plugin/scripts'
        if HERE != expected or not (location / 'company_agent/ppt_reference.py').is_file():
            raise ReferenceError('incomplete_package', '참고 분석 모듈이 없습니다. SKILL.md만 복사하지 말고 배포 ZIP 전체를 사용하세요.')
        namespace = 'company_agent'
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))
    return importlib.import_module(namespace + '.' + name)


def selection(value):
    if value is None:
        return None
    try:
        numbers = [int(v.strip()) for v in value.split(',')] if isinstance(value, str) else value
        if (not isinstance(numbers, list) or not 1 <= len(numbers) <= 60
                or any(type(n) is not int or not 1 <= n <= 10000 for n in numbers)
                or len(numbers) != len(set(numbers))):
            raise ValueError
    except (ValueError, TypeError):
        raise ReferenceError('invalid_slide_selection', '중복 없는 1부터 시작하는 장 번호를 최대 60개 지정하세요.') from None
    return numbers


def inspect(file, *, office=False, slides=None, output=None):
    if file is None:
        raise ReferenceError('reference_file_required', '--file에 이미 선택한 참고 파일을 지정하세요.')
    selected = selection(slides)
    path = Path(file).absolute()
    if office:
        if output is None:
            raise ReferenceError('reference_output_required', '--office에는 --output으로 새 이미지 폴더를 지정하세요.')
        # The existing normal Office path preserves permission/output failures
        # and leaves an already-open user document alone. No fallback is added.
        return runtime('ppt_office_reference').render_reference(path, Path(output).absolute(), selected)
    if output is not None:
        raise ReferenceError('unexpected_output', '--output은 --office의 새 이미지 폴더에만 사용합니다.')
    reference = runtime('ppt_reference')
    request = {'file':str(path), 'purpose':'style'}
    if selected is not None:
        request['slides'] = selected
    result = reference.prepare_reference(request)
    if not result.get('ok'):
        return result
    if result.get('inputKind') == 'html':
        # This analyzer reads bounded literal CSS tokens and structural counts.
        # It does not require legacy scene/template metadata or run the HTML.
        analysis = runtime('html_reference').analyze(path)
        result = {**result, 'analysis':analysis, 'nextAction':'review_reference_html_with_allowed_tools',
                  'contentCoverage':'literal_style_tokens_and_structure_only',
                  'message':'HTML의 색, 글꼴 선언과 구역 수만 읽었습니다. 스크립트나 외부 자원은 실행하지 않았으며 실제 화면은 확인하지 않았습니다.'}
    elif result.get('inputKind') == 'image':
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        result = {**result, 'imageMetadata':{'format':path.suffix.lower().lstrip('.'),
                                            'sizeBytes':path.stat().st_size, 'sha256':digest.hexdigest()},
                  'message':'이미지 파일의 형식, 크기와 해시만 확인했습니다. 글꼴, 색과 배치는 현재 호스트의 이미지 읽기 기능으로 확인하세요.'}
    else:
        result = reference.summarize_reference(result)
    return result


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except (OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description='PPTX, HTML, 이미지의 스타일 참고 요약. Office 내보내기는 --office로 명시합니다.')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--office', action='store_true')
    parser.add_argument('--slides', help='1부터 시작하는 장 번호, 예: 1,3,5 (최대 60장)')
    parser.add_argument('--output', type=Path, help='--office에서 사용할 새 장별 PNG 폴더')
    args = parser.parse_args(argv)
    try:
        result = inspect(args.file, office=args.office, slides=args.slides, output=args.output)
    except ReferenceError as exc:
        result = {'ok':False, 'status':'input_required', 'code':exc.code, 'message':str(exc), 'sourcePreserved':True}
    except ModuleNotFoundError as exc:
        result = {'ok':False, 'code':'dependency_missing', 'module':exc.name,
                  'message':'참고 분석에 필요한 패키지 또는 배포 모듈이 없습니다. 자동 설치하지 않았습니다.'}
    except Exception as exc:
        if hasattr(exc, 'code') and hasattr(exc, 'message'):
            result = {'ok':False, 'code':exc.code, 'status':getattr(exc, 'status', 'unknown'), 'message':exc.message}
        elif isinstance(exc, PermissionError):
            result = {'ok':False, 'code':'permission_denied', 'status':'blocked',
                      'message':'참고 파일 접근이 거절되어 중단했습니다.', 'retryAllowed':False}
        else:
            result = {'ok':False, 'code':'reference_failed', 'status':'unknown',
                      'message':'참고 파일을 분석하지 못했습니다. 다른 추출 경로를 자동 실행하지 않았습니다.'}
        result['sourcePreserved'] = True
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
