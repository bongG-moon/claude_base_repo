"""Offline HTML reporting entrypoint. No harness/profile/session dependency."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# -I 격리 실행에서도 이 배포본의 코드만 찾습니다.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description="HTML 보고서 만들기 · Python 표준 라이브러리만 사용")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="정리한 내용으로 HTML 생성")
    build.add_argument("--spec", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    reference = sub.add_parser("reference", help="HTML 양식의 색상·글꼴·구조 확인")
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
            result = html_reference.inspect_template(args.file, args.preview, open_preview=False)
        else:
            # JSON은 실행 코드가 아니라 보고서 내용입니다. 크기를 먼저 제한합니다.
            if args.spec.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("내용 파일은 4MB 이하로 나누어 주세요. 이미지는 별도 파일 경로로 지정합니다.")
            spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
            if not isinstance(spec, dict):
                raise ValueError("내용 파일은 JSON 객체여야 합니다.")
            result = artifacts.create_html(spec, args.output, require_choices=False)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "code": "invalid_input", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
