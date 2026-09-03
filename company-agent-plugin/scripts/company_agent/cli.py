from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .asset_factory import (
    activate_mcp,
    activate_script_tool,
    create_asset,
    run_script_tool,
    validate_asset,
    validate_mcp_runtime,
    validate_script_tool_runtime,
)
from .knowledge import (
    build_index,
    export_knowledge,
    reconcile_overlays,
    search_catalog,
    upsert_personal,
    validate_pack,
)
from .model_router import classify_prompt
from .memory import search_memory, upsert_memory
from .paths import atomic_write_json, ensure_user_layout, knowledge_base_root, load_json, user_state_root
from .policy import evaluate_tool_call
from .state import load_session, mark_verified


def _path(value: str | None, default: Path | None = None) -> Path | None:
    return Path(value).expanduser().resolve() if value else default


def _state_root(args: argparse.Namespace) -> Path:
    return _path(getattr(args, "state_root", None), user_state_root())  # type: ignore[return-value]


def _base_root(args: argparse.Namespace) -> Path | None:
    return _path(getattr(args, "base", None), knowledge_base_root())


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_init_user(args: argparse.Namespace) -> int:
    root = _state_root(args)
    layout = ensure_user_layout(root)
    existing = load_json(layout["config"] / "user.json", {}) or {}
    config = {
        "schemaVersion": 1,
        "user_email": args.email or existing.get("user_email", ""),
        "display_name": args.display_name or existing.get("display_name") or os.environ.get("USERNAME", "local-user"),
        "knowledgeCapture": "extracted-only",
    }
    if not config["user_email"]:
        raise ValueError("--email is required on first initialization")
    atomic_write_json(layout["config"] / "user.json", config)
    registry_path = layout["mcp"] / "registry.json"
    if not registry_path.exists():
        atomic_write_json(registry_path, {"mcpServers": {}})
    base = _base_root(args)
    if base and base.exists():
        _, issues = build_index(base, layout["knowledge"], layout["index"])
        if any(item.level == "error" for item in issues):
            raise ValueError("knowledge index initialization failed; run knowledge validate")
    _print_json({"ok": True, "stateRoot": str(root), "email": config["user_email"]})
    return 0


def _issues_payload(issues: list[Any]) -> list[dict[str, Any]]:
    return [item.__dict__ for item in issues]


def cmd_knowledge_validate(args: argparse.Namespace) -> int:
    roots = [root for root in (_base_root(args), _path(args.personal) if args.personal else None) if root]
    documents, issues = validate_pack(*roots)
    payload = {
        "ok": not any(item.level == "error" for item in issues),
        "documents": len(documents),
        "errors": sum(item.level == "error" for item in issues),
        "warnings": sum(item.level == "warning" for item in issues),
        "issues": _issues_payload(issues),
    }
    _print_json(payload)
    return 0 if payload["ok"] else 1


def cmd_knowledge_build(args: argparse.Namespace) -> int:
    state = _state_root(args)
    layout = ensure_user_layout(state)
    personal = _path(args.personal, layout["knowledge"])
    output = _path(args.output, layout["index"])
    catalog, issues = build_index(_base_root(args), personal, output)  # type: ignore[arg-type]
    ok = not any(item.level == "error" for item in issues)
    _print_json({"ok": ok, "entries": len(catalog.get("entries", [])), "output": str(output), "issues": _issues_payload(issues)})
    return 0 if ok else 1


def cmd_knowledge_search(args: argparse.Namespace) -> int:
    layout = ensure_user_layout(_state_root(args))
    results = search_catalog(_path(args.index, layout["index"]), args.query, args.limit)  # type: ignore[arg-type]
    _print_json({"query": args.query, "count": len(results), "results": results})
    return 0


def cmd_knowledge_upsert(args: argparse.Namespace) -> int:
    with Path(args.spec).open("r", encoding="utf-8-sig") as stream:
        spec = json.load(stream)
    path = upsert_personal(spec, _state_root(args), _base_root(args))
    _print_json({"ok": True, "path": str(path), "knowledgeId": spec.get("id")})
    return 0


def cmd_knowledge_reconcile(args: argparse.Namespace) -> int:
    base = _base_root(args)
    if base is None:
        raise ValueError("--base or COMPANY_AGENT_KNOWLEDGE_BASE is required")
    report = reconcile_overlays(_state_root(args), base, apply_safe=args.apply_safe)
    _print_json(report)
    return 2 if report["conflicts"] or report["detached"] else 0


def cmd_knowledge_export(args: argparse.Namespace) -> int:
    destination = export_knowledge(_state_root(args), args.id, Path(args.output).resolve())
    _print_json({"ok": True, "output": str(destination), "knowledgeIds": args.id})
    return 0


def cmd_asset_create(args: argparse.Namespace) -> int:
    with Path(args.spec).open("r", encoding="utf-8-sig") as stream:
        spec = json.load(stream)
    path = create_asset(spec, _state_root(args))
    _print_json({"ok": True, "path": str(path), "type": spec.get("type"), "name": spec.get("name")})
    return 0


def cmd_asset_validate(args: argparse.Namespace) -> int:
    result = validate_asset(Path(args.path).resolve())
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_asset_activate_mcp(args: argparse.Namespace) -> int:
    registry = activate_mcp(_state_root(args), args.name, args.receipt)
    _print_json({"ok": True, "registry": str(registry), "name": args.name})
    return 0


def cmd_asset_activate_tool(args: argparse.Namespace) -> int:
    skill = activate_script_tool(_state_root(args), args.name, args.receipt)
    _print_json({"ok": True, "skill": str(skill), "name": args.name})
    return 0


def cmd_asset_test_tool(args: argparse.Namespace) -> int:
    receipt = validate_script_tool_runtime(
        _state_root(args),
        args.name,
        Path(args.input).resolve(),
        args.timeout,
    )
    _print_json({"ok": True, "name": args.name, "receipt": str(receipt)})
    return 0


def cmd_asset_test_mcp(args: argparse.Namespace) -> int:
    receipt = validate_mcp_runtime(_state_root(args), args.name, args.timeout)
    _print_json({"ok": True, "name": args.name, "receipt": str(receipt)})
    return 0


def cmd_asset_run_tool(args: argparse.Namespace) -> int:
    result = run_script_tool(_state_root(args), args.name, Path(args.input).resolve(), args.timeout)
    _print_json(result)
    return 0


def cmd_memory_upsert(args: argparse.Namespace) -> int:
    with Path(args.spec).open("r", encoding="utf-8-sig") as stream:
        spec = json.load(stream)
    path = upsert_memory(spec, _state_root(args))
    _print_json({"ok": True, "path": str(path)})
    return 0


def cmd_memory_search(args: argparse.Namespace) -> int:
    results = search_memory(_state_root(args), args.query, args.limit)
    _print_json({"query": args.query, "count": len(results), "results": results})
    return 0


def cmd_session_verify(args: argparse.Namespace) -> int:
    state = mark_verified(args.session, args.status, args.summary, _state_root(args))
    _print_json({"ok": True, "verification": state["verification"], "session": state["sessionId"]})
    return 0 if args.status == "pass" else 1


def cmd_session_status(args: argparse.Namespace) -> int:
    _print_json(load_session(args.session, _state_root(args)))
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    _print_json(classify_prompt(prompt).as_dict())
    return 0


def cmd_policy_check(args: argparse.Namespace) -> int:
    with Path(args.payload).open("r", encoding="utf-8-sig") as stream:
        payload = json.load(stream)
    _print_json(evaluate_tool_call(payload, _state_root(args)))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    state = _state_root(args)
    layout = ensure_user_layout(state)
    base = _base_root(args)
    plugin_root = Path(__file__).resolve().parents[2]
    checks = {
        "python": {"ok": sys.version_info >= (3, 11), "value": platform.python_version()},
        "claude": {"ok": shutil.which("claude") is not None, "value": shutil.which("claude")},
        "pluginManifest": {"ok": (plugin_root / ".claude-plugin" / "plugin.json").exists()},
        "hooks": {"ok": (plugin_root / "hooks" / "hooks.json").exists()},
        "userConfig": {"ok": (layout["config"] / "user.json").exists()},
        "knowledgeBase": {"ok": bool(base and base.exists()), "value": str(base) if base else None},
        "smallModel": {"ok": bool(os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")), "value": os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")},
        "mediumModel": {"ok": bool(os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")), "value": os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")},
        "largeModel": {"ok": bool(os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")), "value": os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")},
    }
    ok = all(item["ok"] for item in checks.values())
    _print_json({"ok": ok, "version": __version__, "stateRoot": str(state), "checks": checks})
    return 0 if ok else 1


def _add_state_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-root", help="Override the per-user state root.")


def _add_base_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", help="Corporate Knowledge Pack root. Defaults to COMPANY_AGENT_KNOWLEDGE_BASE.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="company-agent", description="Company Agent local harness administration CLI")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_user = subparsers.add_parser("init-user", help="Create the per-user state directory without touching ~/.claude.")
    _add_state_argument(init_user)
    _add_base_argument(init_user)
    init_user.add_argument("--email")
    init_user.add_argument("--display-name")
    init_user.set_defaults(func=cmd_init_user)

    knowledge = subparsers.add_parser("knowledge", help="Validate, index, search, update, and reconcile Markdown knowledge.")
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_command", required=True)
    validate = knowledge_sub.add_parser("validate")
    _add_base_argument(validate)
    validate.add_argument("--personal")
    validate.set_defaults(func=cmd_knowledge_validate)
    build = knowledge_sub.add_parser("build")
    _add_state_argument(build)
    _add_base_argument(build)
    build.add_argument("--personal")
    build.add_argument("--output")
    build.set_defaults(func=cmd_knowledge_build)
    search = knowledge_sub.add_parser("search")
    _add_state_argument(search)
    search.add_argument("query")
    search.add_argument("--index")
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(func=cmd_knowledge_search)
    upsert = knowledge_sub.add_parser("upsert")
    _add_state_argument(upsert)
    _add_base_argument(upsert)
    upsert.add_argument("--spec", required=True)
    upsert.set_defaults(func=cmd_knowledge_upsert)
    reconcile = knowledge_sub.add_parser("reconcile")
    _add_state_argument(reconcile)
    _add_base_argument(reconcile)
    reconcile.add_argument("--apply-safe", action="store_true")
    reconcile.set_defaults(func=cmd_knowledge_reconcile)
    export = knowledge_sub.add_parser("export")
    _add_state_argument(export)
    export.add_argument("--id", action="append", required=True)
    export.add_argument("--output", required=True)
    export.set_defaults(func=cmd_knowledge_export)

    asset = subparsers.add_parser("asset", help="Create and validate personal Skills, script tools, and MCP servers.")
    asset_sub = asset.add_subparsers(dest="asset_command", required=True)
    create = asset_sub.add_parser("create")
    _add_state_argument(create)
    create.add_argument("--spec", required=True)
    create.set_defaults(func=cmd_asset_create)
    validate_asset_parser = asset_sub.add_parser("validate")
    validate_asset_parser.add_argument("path")
    validate_asset_parser.set_defaults(func=cmd_asset_validate)
    test_tool = asset_sub.add_parser("test-tool")
    _add_state_argument(test_tool)
    test_tool.add_argument("--name", required=True)
    test_tool.add_argument("--input", required=True)
    test_tool.add_argument("--timeout", type=int, default=30)
    test_tool.set_defaults(func=cmd_asset_test_tool)
    test_mcp = asset_sub.add_parser("test-mcp")
    _add_state_argument(test_mcp)
    test_mcp.add_argument("--name", required=True)
    test_mcp.add_argument("--timeout", type=int, default=30)
    test_mcp.set_defaults(func=cmd_asset_test_mcp)
    activate = asset_sub.add_parser("activate-mcp")
    _add_state_argument(activate)
    activate.add_argument("--name", required=True)
    activate.add_argument("--receipt", required=True)
    activate.set_defaults(func=cmd_asset_activate_mcp)
    activate_tool = asset_sub.add_parser("activate-tool")
    _add_state_argument(activate_tool)
    activate_tool.add_argument("--name", required=True)
    activate_tool.add_argument("--receipt", required=True)
    activate_tool.set_defaults(func=cmd_asset_activate_tool)
    run_tool = asset_sub.add_parser("run-tool")
    _add_state_argument(run_tool)
    run_tool.add_argument("--name", required=True)
    run_tool.add_argument("--input", required=True)
    run_tool.add_argument("--timeout", type=int, default=60)
    run_tool.set_defaults(func=cmd_asset_run_tool)

    memory = subparsers.add_parser("memory", help="Store extracted personal preferences without session transcripts.")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_upsert = memory_sub.add_parser("upsert")
    _add_state_argument(memory_upsert)
    memory_upsert.add_argument("--spec", required=True)
    memory_upsert.set_defaults(func=cmd_memory_upsert)
    memory_search = memory_sub.add_parser("search")
    _add_state_argument(memory_search)
    memory_search.add_argument("query")
    memory_search.add_argument("--limit", type=int, default=10)
    memory_search.set_defaults(func=cmd_memory_search)

    session = subparsers.add_parser("session", help="Manage compact verification state; no transcript content is stored.")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    verify = session_sub.add_parser("verify")
    _add_state_argument(verify)
    verify.add_argument("--session", required=True)
    verify.add_argument("--status", choices=("pass", "fail"), required=True)
    verify.add_argument("--summary", required=True)
    verify.set_defaults(func=cmd_session_verify)
    status = session_sub.add_parser("status")
    _add_state_argument(status)
    status.add_argument("--session", required=True)
    status.set_defaults(func=cmd_session_status)

    route = subparsers.add_parser("route", help="Classify a prompt without storing it.")
    route.add_argument("--prompt")
    route.set_defaults(func=cmd_route)

    policy = subparsers.add_parser("policy-check", help="Evaluate a saved hook payload for diagnostics.")
    _add_state_argument(policy)
    policy.add_argument("--payload", required=True)
    policy.set_defaults(func=cmd_policy_check)

    doctor = subparsers.add_parser("doctor", help="Check local installation prerequisites and model mappings.")
    _add_state_argument(doctor)
    _add_base_argument(doctor)
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
