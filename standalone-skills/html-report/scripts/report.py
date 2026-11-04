"""Offline HTML reporting entrypoint. No harness/profile/session dependency."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# -I 격리 실행에서도 이 배포본의 코드만 찾습니다.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def output_path(path, *, intermediate=False):
    """단순 새 파일명만 스킬 폴더에 정리하고 지정 경로와 기존 파일은 보존합니다."""
    if path.is_absolute() or path.parent != Path('.') or path.exists():
        return path
    work = Path.cwd()
    if work.name in {'.work', 'outputs'} and work.parent.name == 'html-report':
        work = work.parent
    if work.name != 'html-report':
        work /= 'html-report'
    return work / ('.work' if intermediate else 'outputs') / path.name


def prepare_output(path, artifacts, *, intermediate=False):
    target = output_path(path, intermediate=intermediate)
    if target != path:
        # Validate the local destination before creating the default folders.
        target = artifacts.safe_path(target)
        artifacts._reject_reparse(target)
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def main(argv=None):
    # Claude Code's Windows shell consumes tool output as UTF-8 even when
    # Python inherits a legacy console code page. Keep the JSON readable in
    # both Bash and PowerShell without changing the user's system settings.
    if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="HTML 보고서 만들기 · Python 표준 라이브러리만 사용")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="정리한 내용으로 HTML 생성")
    build.add_argument("--spec", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    reference = sub.add_parser("reference", help="HTML 양식의 색상 조합, 글꼴, 여백, 표 스타일 확인")
    reference.add_argument("--file", type=Path, required=True)
    reference.add_argument("--preview", type=Path)
    args = parser.parse_args(argv)
    try:
        from visual_engine import business_artifacts as artifacts, html_reference
    except ImportError:
        print(json.dumps({"ok": False, "code": "incomplete_package", "message": "렌더링 파일이 없습니다. SKILL.md만 복사하지 말고 배포 ZIP 전체를 사용해 주세요."}, ensure_ascii=False))
        return 2
    try:
        if args.command == "reference":
            preview = prepare_output(args.preview, artifacts, intermediate=True) if args.preview else None
            result = html_reference.inspect_template(args.file, preview, open_preview=False)
        else:
            # JSON은 실행 코드가 아니라 보고서 내용입니다. 크기를 먼저 제한합니다.
            if args.spec.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("내용 파일은 4MB 이하로 나누어 주세요. 이미지는 별도 파일 경로로 지정합니다.")
            spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
            if not isinstance(spec, dict):
                raise ValueError("내용 파일은 JSON 객체여야 합니다.")
            # 새 작업은 기본값으로 디자인/분량을 정한 척하지 않습니다.
            # 사용자가 이미 고른 값 또는 자동 선택을 맡긴 값은 job에 보존하며,
            # 빠진 조건만 같은 응답에서 한 번에 돌려줍니다. 별도 사전 명령은 없습니다.
            spec.setdefault('fontChoiceRequired', True)
            result = artifacts.html_choices(spec)
            if result.get('ok'):
                result = artifacts.create_html(spec, prepare_output(args.output, artifacts), require_choices=True)
    except artifacts.ArtifactError as exc:
        result = artifacts._failure(exc)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "code": "invalid_input", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Choices and template confirmation are normal conversation pauses. They
    # must not look like command failures that invite an identical retry.
    waiting = result.get("status") == "input_required" and result.get("code") == "report_choices_required"
    return 0 if result.get("ok") or waiting else 1


if __name__ == "__main__":
    sys.exit(main())
