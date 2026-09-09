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
    return {"ok": True, "status": "diagnostic_only", "python": platform.python_version(),
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
    if action == "doctor":
        return doctor()
    if action == "files-plan":
        from .business_files import create_plan
        return create_plan(state, Path(args.folder))
    if action in {"files-execute", "files-undo"}:
        from .business_files import run_plan
        return run_plan(state, args.plan, undo=action == "files-undo")
    if action == "mail-capabilities":
        from .business_mail import capabilities
        return capabilities()
    if action == "ppt-inspect":
        from .business_artifacts import inspect_template
        return inspect_template(safe_path(args.template, exists=True))
    spec = _spec(args.spec)
    if (blocked := blocked_input(spec)) is not None:
        return blocked
    spec.pop("protection", None)
    if action in {"html", "ppt"}:
        from .business_artifacts import create_html, create_ppt
        output = safe_path(args.output)
        if output.exists():
            raise ValueError("The output exists. Choose a new filename; it was not overwritten.")
        if action == "html":
            return create_html(spec, output)
        template = safe_path(args.template, exists=True) if args.template else None
        return create_ppt(spec, output, template)
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
    return 0 if result.get("ok") or result.get("status") in {"partial", "cancelled", "blocked"} else 1


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("business", help="Local business pilot workflows with partial-result reporting.")
    actions = parser.add_subparsers(dest="business_action", required=True)
    for action in ("doctor", "files-plan", "files-execute", "files-undo", "html", "ppt", "ppt-inspect",
                   "mail-capabilities", "mail-search", "mail-read"):
        command = actions.add_parser(action)
        command.add_argument("--state-root")
        if action == "files-plan":
            command.add_argument("--folder", required=True)
        if action in {"files-execute", "files-undo"}:
            command.add_argument("--plan", required=True)
        if action in {"html", "ppt", "mail-search", "mail-read"}:
            command.add_argument("--spec", required=True)
        if action in {"html", "ppt"}:
            command.add_argument("--output", required=True)
        if action in {"ppt", "ppt-inspect"}:
            command.add_argument("--template", required=action == "ppt-inspect")
        command.set_defaults(func=run)
