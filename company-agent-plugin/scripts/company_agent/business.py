"""User-facing business workflow CLI. No new MCP registration or credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
from typing import Any

from .business_safety import blocked_input, cancelled, confirm_action, failure_result, safe_path
from .paths import user_state_root


def doctor() -> dict[str, Any]:
    from .business_artifacts import capabilities
    from .environment_checks import inspect_environment
    return {"ok": True, "status": "diagnostic_only", "python": platform.python_version(),
            "environment": inspect_environment(),
            "windows": os.name == "nt", "artifacts": capabilities(),
            "fileOrganizer": {"available": os.name == "nt", "previewRequired": True, "permanentDelete": False},
            "outlook": {"status": "connection_not_tested", "readOnlyPilot": True,
                        "next": "business mail-capabilities", "existingMcpPreserved": True},
            "imageGeneration": {"status": "use_existing_approved_mcp_if_available", "newEndpointConfigured": False},
            "drm": {"status": "unknown", "universalDetection": False, "bypassSupported": False},
            "message": "기본 실행 조건만 확인했습니다. 메일 본문 조회·파일 이동·DRM 설정 변경은 하지 않았습니다. 운영 자료의 허용 여부는 별도 확인이 필요합니다."}


def _spec(path: str) -> dict[str, Any]:
    selected = safe_path(path, exists=True)
    with selected.open("rb") as stream:
        content = stream.read(512 * 1024 + 1)
    if len(content) > 512 * 1024:
        raise ValueError("The business specification must be at most 512 KiB.")
    value = json.loads(content.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("The business specification must be a JSON object.")
    return value


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    action = args.business_action
    state = safe_path(args.state_root or user_state_root())
    if action in {'artifact-start','artifact-publish'}:
        from . import artifact_delivery
        return artifact_delivery.start(state,args.output) if action == 'artifact-start' else artifact_delivery.publish(state,args.work)
    if action in {"html", "ppt", "ppt-design-preview", "ppt-template", "ppt-fit-images"} and getattr(args,'work',None):
        from .artifact_delivery import build
        return build(state,args.work,action,spec_path=args.spec,
                     template=Path(args.template) if getattr(args,'template',None) else None)
    if action == "doctor":
        return doctor()
    if action == 'ppt-capabilities':
        from .business_artifacts import capabilities
        return capabilities()['ppt']
    if action == 'runtime-check':
        from .runtime_diagnostics import inspect_runtime
        return inspect_runtime()
    if action == "html-designs":
        from .business_artifacts import html_designs
        return html_designs(Path(args.output) if args.output else None, open_preview=getattr(args, 'open_preview', False))
    if action == 'html-template':
        from .html_reference import inspect_template
        return inspect_template(safe_path(args.template, exists=True),
                                safe_path(args.output) if args.output else None,
                                open_preview=getattr(args, 'open_preview', False))
    if action == "files-plan":
        from .business_files import create_plan
        return create_plan(state, Path(args.folder))
    if action in {"files-execute", "files-undo"}:
        from .business_files import run_plan
        return run_plan(state, args.plan, undo=action == "files-undo")
    if action == "mail-capabilities":
        from .business_mail import capabilities
        return capabilities()
    if action == "eml-read":
        from .business_eml import read_eml
        return read_eml(Path(args.file))
    if action == "ppt-inspect":
        from .business_artifacts import inspect_template
        return inspect_template(safe_path(args.template, exists=True))
    if action == 'ppt-analyze':
        from .ppt_workflow import analyze
        return analyze(safe_path(args.template, exists=True))
    if action == 'ppt-preview':
        from .business_artifacts import preview_template
        return preview_template(safe_path(args.template, exists=True), safe_path(args.output))
    if action == 'office-read' and getattr(args, 'file', None):
        from .execution_contract import office_file_name
        # Join only a bare filename to the actual invocation cwd. No guessing,
        # recursion, fallback to Desktop, or repair of an explicit wrong path.
        source = str(Path.cwd() / args.file) if office_file_name(args.file) else args.file
        spec = {'file': source}
        for flag, field in (('start','start'),('end','end'),('sheet','sheet'),('range','range'),
                            ('max_chars','maxChars'),('expected_count','expectedCount')):
            value = getattr(args, flag, None)
            if value is not None:
                spec[field] = int(value) if flag=='sheet' and value.isdigit() else value
    else:
        if action == 'office-read' and any(getattr(args,key,None) is not None for key in
                                          ('start','end','sheet','range','max_chars','expected_count')):
            raise ValueError('office-read: --spec과 직접 범위 인자는 함께 사용할 수 없습니다.')
        spec = _spec(args.spec)
    if (blocked := blocked_input(spec)) is not None:
        return blocked
    spec.pop("protection", None)
    if action == 'office-read':
        from .office_reader import read_office
        from .office_progress import cli_progress
        return read_office(spec, progress=cli_progress(), state_root=state,
                           session_id=getattr(args, 'session', '') or '')
    if action == 'ppt-choices':
        from .ppt_workflow import choices
        return choices(spec, args.template)
    if action == 'html-choices':
        from .business_artifacts import html_choices
        return html_choices(spec)
    if action == 'ppt-fit-images':
        from .ppt_image_edit import resize
        return resize(spec,safe_path(args.output))
    if action in {"html", "ppt", "ppt-design-preview", "ppt-template"}:
        from .business_artifacts import create_html, create_ppt
        output = safe_path(args.output)
        if output.exists():
            raise ValueError("The output exists. Choose a new filename; it was not overwritten.")
        if action == "html":
            return create_html(spec, output, require_choices=True)
        template = safe_path(args.template, exists=True) if args.template else None
        if action == 'ppt-template':
            from .ppt_html import save_template
            return save_template(spec, output, template)
        return create_ppt(spec, output, template, require_choices=True, preview_only=action=='ppt-design-preview')
    if action == "mail-search":
        from .business_mail import search_mail
        return search_mail(spec)
    if action == "mail-read":
        from .business_mail import read_mail
        # A model-provided JSON approval cannot authorize a body extraction.
        spec.pop("body_access_approved", None)
        if spec.get("include_body") is True:
            details = ("회사에서 AI 처리가 허용된 메일만 선택했는지 확인하세요.\n"
                       "아래 메일 본문을 읽어 현재 Claude 대화에 전달합니다. Claude 자체 대화 기록에 남을 수 있습니다.\n"
                       "하네스는 본문을 별도 Memory/Knowledge에 저장하지 않습니다. 첨부는 추출하지 않습니다.\n"
                       "IRM 제한이 확인되면 승인해도 읽지 않습니다. 이 확인은 사내 DRM 허가를 대신하지 않습니다.\n\n"
                       + json.dumps({k: spec.get(k) for k in ("account_smtp", "store_ids", "message_refs")}, ensure_ascii=False, indent=2))
            if not confirm_action("메일 본문의 AI 처리 확인", details):
                return cancelled()
            spec["body_access_approved"] = True
        return read_mail(spec)
    raise ValueError("Unknown business operation.")


def run(args: argparse.Namespace) -> int:
    try:
        result = dispatch(args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = failure_result(exc)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    # Partial/cancelled results remain machine-readable rather than causing a
    # shell-driven retry of a potentially completed external action.
    return 0 if result.get("ok") or result.get("status") in {"partial", "cancelled", "blocked", "input_required"} else 1


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("business", help="Local business pilot workflows with partial-result reporting.")
    actions = parser.add_subparsers(dest="business_action", required=True)
    for action in ("doctor", "runtime-check", "files-plan", "files-execute", "files-undo", "html", "html-designs", "html-template", "html-choices", "ppt", "ppt-inspect", "ppt-choices", "ppt-analyze", "ppt-preview", "ppt-design-preview", "ppt-template",
                   "mail-capabilities", "mail-search", "mail-read", "eml-read", "office-read", "artifact-start", "artifact-publish", "ppt-fit-images", "ppt-capabilities"):
        command = actions.add_parser(action)
        command.add_argument("--state-root")
        if action in {'html-designs', 'html-template'}:
            command.add_argument('--output')
            command.add_argument('--open', action='store_true', dest='open_preview')
        if action == 'html-template':
            command.add_argument('--template', required=True)
        if action == "eml-read":
            command.add_argument("--file", required=True)
        if action == "files-plan":
            command.add_argument("--folder", required=True)
        if action in {"files-execute", "files-undo"}:
            command.add_argument("--plan", required=True)
        if action == 'office-read':
            command.add_argument('--session', help='후크 JSON의 현재 대화 ID (환경변수가 아님; 연결된 후크가 누락 값 보완)')
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument('--spec')
            source.add_argument('--file')
            for flag in ('start','end','max-chars','expected-count'):
                command.add_argument('--'+flag, type=int)
            command.add_argument('--sheet')
            command.add_argument('--range')
        if action in {"html", "html-choices", "ppt-choices", "ppt", "ppt-design-preview", "ppt-template", "ppt-fit-images", "mail-search", "mail-read"}:
            command.add_argument("--spec", required=True)
        if action in {"html", "ppt", "ppt-design-preview", "ppt-template", "ppt-fit-images"}:
            destination = command.add_mutually_exclusive_group(required=True)
            destination.add_argument('--work',help='artifact-start에서 반환된 workFile. 중간 결과는 작업 공간에만 저장합니다.')
            destination.add_argument('--output',help='기존 직접 저장 호환 모드. 일반 스킬 작업은 --work를 사용합니다.')
        if action in {"ppt-preview", "artifact-start"}:
            command.add_argument("--output", required=True)
        if action == 'artifact-publish':
            command.add_argument('--work',required=True)
        if action in {"ppt", "ppt-inspect", "ppt-choices", "ppt-analyze", "ppt-preview", "ppt-design-preview", "ppt-template"}:
            command.add_argument("--template", required=action in {'ppt-inspect','ppt-analyze','ppt-preview'})
        command.set_defaults(func=run)
