"""HTML-first, editable PPT generation without Company Harness or Office launch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

# -I 격리 실행에서도 이 배포본의 코드만 찾습니다.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description="HTML 초안 → 편집 가능한 PPT")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("draft", "전체 슬라이드 HTML 초안"), ("build", "승인된 초안으로 PPT 생성"), ("template", "가상 내용의 HTML 대표 양식 저장")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--spec", type=Path, required=True)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--template", type=Path)
    reference = sub.add_parser("reference", help="PPTX 첫 3장 또는 지정 장의 구조·글자 스타일 확인")
    reference.add_argument("--file", type=Path, required=True)
    reference.add_argument("--slides", help="1부터 시작하는 장 번호, 예: 1,3,5 (최대 3장)")
    args = parser.parse_args(argv)
    try:
        from visual_engine import business_artifacts as artifacts, ppt_html, ppt_workflow, presentation_design, content_layout
    except ImportError:
        print(json.dumps({"ok": False, "code": "incomplete_package", "message": "렌더링 파일이 없습니다. SKILL.md만 복사하지 말고 배포 ZIP 전체를 사용해 주세요."}, ensure_ascii=False))
        return 2
    try:
        if args.command == "reference":
            slides = [int(v) for v in args.slides.split(",")] if args.slides else None
            if slides is not None and (not 1 <= len(slides) <= 3 or any(n < 1 for n in slides)):
                raise ValueError("참고 장표는 1부터 시작하는 번호를 최대 3개 지정해 주세요.")
            result = ppt_workflow.analyze(args.file, selected_slides=slides, first_slides=None if slides else 3)
        else:
            if args.spec.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("내용 파일은 4MB 이하로 나누어 주세요. 이미지는 별도 파일 경로로 지정합니다.")
            spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
            if not isinstance(spec, dict):
                raise ValueError("내용 파일은 JSON 객체여야 합니다.")
            if args.command == "draft":
                result = ppt_html.create_draft(spec, args.output, args.template, require_choices=False)
            elif args.command == "template":
                result = ppt_html.save_template(spec, args.output, args.template)
                if result.get("ok"):
                    result["reuse"] = "presentation.py draft --spec NEW_JOB.json --output draft.html --template SAVED.html"
            else:
                # 사용자가 본 초안과 내용·참고 파일이 같은지 확인합니다.
                ppt_workflow.verify_design_review(spec, args.template)
                from visual_engine.business_safety import blocked_input
                blocked = blocked_input(spec)
                if blocked is not None:
                    result = blocked
                else:
                    target = artifacts._target(args.output, ".pptx")
                    data, arithmetic, inspected, template, preserve = ppt_html.prepare(spec, args.template)
                    with tempfile.TemporaryDirectory(prefix="presentation-build-") as temporary:
                        draft = Path(temporary) / "deck.pptx"
                        # 이 경로는 설치된 PowerPoint·별도 서버·프로필을 실행하지 않습니다.
                        native = (ppt_workflow.fill_template(data, draft, template, spec.get("templateSlides"))
                                  if preserve else presentation_design.render_python(data, draft, template))
                        check = artifacts.inspect_template(draft)
                        if not check.get("ok") or check.get("slideCount") != len(data["sections"]):
                            raise ValueError("출력 장수 또는 파일 구조 확인에 실패했습니다.")
                        layout = content_layout.check_ppt(draft, data) if not preserve else {"status": "not-requested"}
                        ppt_workflow.verify_design_review(spec, args.template)
                        artifacts._publish(draft, target)
                    result = {"ok": True, "outputPath": str(target), "slides": check["slideCount"],
                              "engine": "python-pptx", "editability": native, "arithmetic": arithmetic,
                              "contentLayoutValidation": layout, "visualReview": "not_verified",
                              "officeStarted": False, "harnessRequired": False,
                              "warnings": ["구조와 편집 가능한 개체를 확인했습니다. 실제 PowerPoint 화면의 글자 잘림·배치는 별도 확인이 필요합니다."]}
    except ModuleNotFoundError as exc:
        result = {"ok": False, "code": "dependency_missing", "message": "필요한 Python 패키지가 없습니다. requirements.txt를 확인해 주세요. 자동 설치하지 않았습니다.", "module": exc.name}
    except Exception as exc:
        result = artifacts._failure(exc)
        if isinstance(exc, ValueError):
            result = {"ok": False, "code": "invalid_input", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
