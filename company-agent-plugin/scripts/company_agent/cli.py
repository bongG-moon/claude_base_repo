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
    rebind_mcp_runtime,
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
from .memory import compact_memory, search_memory, upsert_memory
from .context_audit import audit_context
from .paths import atomic_write_json, ensure_user_layout, knowledge_base_root, load_json, user_state_root
from .policy import evaluate_tool_call
from .state import load_session, mark_verified
from .state_compatibility import check_state_compatibility


def _path(value: str | None, default: Path | None = None) -> Path | None:
    return Path(value).expanduser().resolve() if value else default


def _state_root(args: argparse.Namespace) -> Path:
    return _path(getattr(args, "state_root", None), user_state_root())  # type: ignore[return-value]


def _base_root(args: argparse.Namespace) -> Path | None:
    return _path(getattr(args, "base", None), knowledge_base_root())


def _print_json(value: Any) -> None:
    # ASCII-safe JSON wire output survives legacy Windows pipes without losing
    # Unicode: JSON readers restore every escaped character, including paths.
    print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))


def cmd_init_user(args: argparse.Namespace) -> int:
    root = _state_root(args)
    layout = ensure_user_layout(root)
    existing = load_json(layout["config"] / "user.json", {}) or {}
    config = {
        **existing,
        "schemaVersion": existing.get("schemaVersion", 1),
        "user_email": args.email or existing.get("user_email", ""),
        "display_name": args.display_name or existing.get("display_name") or os.environ.get("USERNAME", "local-user"),
        "knowledgeCapture": "extracted-only",
    }
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


def cmd_state_check(args: argparse.Namespace) -> int:
    _print_json(check_state_compatibility(_state_root(args)))
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
    native = None
    if os.environ.get("COMPANY_AGENT_SCOPE") in {"User", "Project"}:
        from .native_mcp import sync_native_mcp
        native = sync_native_mcp(_state_root(args), args.name)
    _print_json({"ok": True, "registry": str(registry), "name": args.name, "nativeRegistration": native})
    return 0


def cmd_asset_sync_mcp(args: argparse.Namespace) -> int:
    from .native_mcp import sync_native_mcp
    _print_json(sync_native_mcp(_state_root(args), args.name))
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


def cmd_asset_rebind_mcp(args: argparse.Namespace) -> int:
    receipt = rebind_mcp_runtime(_state_root(args), args.name, args.timeout)
    _print_json({"ok": True, "name": args.name, "receipt": str(receipt),
                 "activationRequired": True, "nativeRegistrationChanged": False,
                 "nextStep": "Run asset activate-mcp with this receipt; review any native registration conflict separately."})
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


def cmd_memory_compact(args: argparse.Namespace) -> int:
    _print_json(compact_memory(_state_root(args)))
    return 0


def cmd_learning(args: argparse.Namespace) -> int:
    from .learning import learning_status, rollback_change, set_learning_enabled, submit_review
    root = _state_root(args)
    operation = args.learning_command
    if operation == "status":
        session = load_session(args.session, root) if args.session else None
        result = {"ok": True, "learning": learning_status(root, session=session)}
        if args.session:
            result["session"] = session
    elif operation in {"pause", "resume"}:
        result = set_learning_enabled(root, operation == "resume")
    elif operation == "rollback":
        result = rollback_change(root, args.change)
    else:
        # Only the turn-owned staging file is accepted. The completion hook can
        # distinguish this bookkeeping write from a business artifact mutation.
        import stat
        from .state import safe_session_id
        if args.session != safe_session_id(args.session):
            raise ValueError("Use the exact sanitized session ID from the current runtime.")
        if len(args.turn) != 32 or any(char not in "0123456789abcdef" for char in args.turn):
            raise ValueError("Use the exact current learning turn ID.")
        if load_session(args.session, root).get("turnId") != args.turn:
            raise ValueError("Learning review must belong to the current user turn.")
        spec_path = Path(args.spec).absolute()
        expected = root / "tmp" / f"learning-review-{args.turn}.json"
        if spec_path != expected.absolute():
            raise ValueError("The learning review spec must use this turn's named file under the active state tmp directory.")
        for parent in (spec_path, *spec_path.parents):
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise ValueError("Learning review paths cannot contain symbolic links or junctions.")
        info = spec_path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32_768:
            raise ValueError("Learning review spec must be a compact JSON file of at most 32 KiB.")
        with spec_path.open("rb") as stream:
            raw = stream.read(32_769)
        if len(raw) > 32_768:
            raise ValueError("Learning review spec exceeds 32 KiB.")
        cleanup = "retained_unavailable"
        submission_error = None
        try:
            spec = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(spec, dict):
                raise ValueError("Learning review must be a JSON object.")
            if operation == "stage":
                from .work import checkpoint
                result = checkpoint(root, args.session, args.turn, "active", spec=spec)
            else:
                result = submit_review(root, args.session, args.turn, spec)
        except (OSError, ValueError) as exc:
            submission_error = str(exc)
        finally:
            # This exact current-turn input is disposable, including rejected
            # sensitive/malformed input. Never delete a subsequently edited
            # file, follow a changed ancestor link, or scan other tmp files.
            try:
                linked = any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
                             for parent in (spec_path, *spec_path.parents))
                latest = spec_path.stat() if not linked else None
                if (latest is not None and stat.S_ISREG(latest.st_mode)
                        and latest.st_ino == info.st_ino and latest.st_size == len(raw)):
                    with spec_path.open("rb") as stream:
                        unchanged = stream.read(32_769) == raw
                    if unchanged:
                        spec_path.unlink()
                        cleanup = "removed"
                    else:
                        cleanup = "retained_changed"
                else:
                    cleanup = "retained_changed"
            except OSError:
                pass
        if submission_error is not None:
            _print_json({"ok": False, "error": submission_error, "stagingCleanup": cleanup,
                         "needsSpecRewrite": cleanup == "removed",
                         "nextAction": "Check learning status and the completed work checkpoint before retrying. Rewrite a removed spec only within the existing review budget; do not rerun business work."})
            return 1
        result["stagingCleanup"] = cleanup
    _print_json(result)
    return 0


def cmd_work(args: argparse.Namespace) -> int:
    from .work import checkpoint, resolve_unfinished
    if args.work_command == "resolve":
        _print_json(resolve_unfinished(_state_root(args), args.session, args.turn, args.work_id))
    else:
        _print_json(checkpoint(_state_root(args), args.session, args.turn, args.status,
                               new=args.new == "yes", learn=args.learn == "yes"))
    return 0


def cmd_context_audit(args: argparse.Namespace) -> int:
    _print_json(audit_context(Path(args.project)))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    from .handoff import create_handoff, read_handoff, safe_path
    # Validate redirect identity BEFORE resolve() in the general _state_root helper.
    root = safe_path(Path(args.state_root).expanduser() if args.state_root else user_state_root())
    if args.handoff_command == "create":
        check_state_compatibility(root)
        spec_path = safe_path(Path(args.spec).expanduser())
        if spec_path.stat().st_size > 32768:
            raise ValueError("handoff spec too large")
        result = create_handoff(root, Path(args.project), args.session, load_json(spec_path))
    else:
        result = read_handoff(root, Path(args.project), args.id)
    _print_json(result)
    return 0


def cmd_setup_helper(args: argparse.Namespace) -> int:
    from .setup_helper import create_setup_helper, _safe_path
    root = _safe_path(Path(args.state_root).expanduser() if args.state_root else user_state_root())
    check_state_compatibility(root)
    spec_path = _safe_path(Path(args.spec).expanduser())
    if spec_path.stat().st_size > 32768:
        raise ValueError("setup helper spec too large")
    _print_json(create_setup_helper(root, load_json(spec_path)))
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
        "smallModel": {"ok": True, "alias": "haiku", "source": "existing Claude configuration", "liveVerified": False},
        "mediumModel": {"ok": True, "alias": "sonnet", "source": "existing Claude configuration", "liveVerified": False},
        "largeModel": {"ok": True, "alias": "opus", "source": "existing Claude configuration", "liveVerified": False},
    }
    ok = all(item["ok"] for item in checks.values())
    _print_json({"ok": ok, "version": __version__, "stateRoot": str(state), "checks": checks})
    return 0 if ok else 1


def _add_state_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-root", help="Override the per-user state root.")


def cmd_harness(args: argparse.Namespace) -> int:
    from .project_harness import (
        apply_project_harness, inspect_project, plan_project_harness, validate_project_harness,
    )

    if args.harness_command == "inspect":
        result = inspect_project(args.project)
    elif args.harness_command == "validate":
        result = validate_project_harness(args.project)
    else:
        spec = load_json(Path(args.spec))
        if not isinstance(spec, dict):
            raise ValueError("Harness specification must be a JSON object")
        operation = apply_project_harness if args.harness_command == "apply" else plan_project_harness
        result = operation(args.project, spec)
    _print_json(result)
    return 0 if result.get("ok", True) else 1


def _skill_options(args: argparse.Namespace, *, writing: bool = False) -> dict[str, Any]:
    # Preserve raw path ancestors so the registry can reject reparse points.
    def path(value: str | None) -> Path | None:
        return Path(value).expanduser() if value else None

    project = None if args.no_project else path(args.project_root) or Path.cwd()
    if writing and args.scope == "default":
        project = None
    elif writing and args.no_project:
        raise ValueError("Project preferences need --project-root; use --scope default for the current state defaults.")
    return {
        "project_root": project,
        "claude_root": path(args.claude_root),
        "plugin_root": path(args.plugin_root or os.environ.get("COMPANY_AGENT_PLUGIN_ROOT")),
        "incoming_plugin": path(args.incoming_plugin),
        "incoming_skill": path(args.incoming_skill),
        "knowledge_root": path(args.base or os.environ.get("COMPANY_AGENT_KNOWLEDGE_BASE")),
    }


def cmd_skill(args: argparse.Namespace) -> int:
    from .skill_registry import (
        inventory_skills, reset_skill_preferences, resolve_skill, search_skills,
        set_skill_preference, set_skill_source_order,
    )
    root = Path(args.state_root).expanduser() if args.state_root else user_state_root()
    operation = args.skill_command
    writing = operation in {"prefer", "prefer-incoming", "order", "reset"}
    options = _skill_options(args, writing=writing)
    if operation in {"inventory", "list", "conflicts"}:
        result = inventory_skills(root, **options)
        if operation == "conflicts":
            result.pop("skills", None)
    elif operation == "search":
        result = search_skills(root, args.query, limit=args.limit, **options)
    elif operation == "resolve":
        result = resolve_skill(root, args.name, **options)
    elif operation == "prefer":
        result = set_skill_preference(root, args.name, args.candidate, **options)
    elif operation == "order":
        result = set_skill_source_order(root, args.sources, project_root=options["project_root"])
    elif operation == "reset":
        result = reset_skill_preferences(root, project_root=options["project_root"], name=args.name)
    else:
        if not options["incoming_plugin"] and not options["incoming_skill"]:
            raise ValueError("prefer-incoming requires an explicit incoming plugin or Skill path.")
        inventory = inventory_skills(root, **options)
        if inventory.get("complete") is not True:
            raise ValueError("Skill discovery was incomplete. Resolve inventory warnings before preferring incoming Skills.")
        selections = []
        for conflict in inventory["conflicts"]:
            incoming = [item for item in conflict["candidates"] if item.get("incoming")]
            existing = [item for item in conflict["candidates"] if not item.get("incoming")]
            if not incoming or not existing:
                continue
            if len(incoming) != 1:
                raise ValueError("Incoming Skill choices are ambiguous; use skill prefer for each exact candidate.")
            selections.append((conflict["name"], incoming[0]["id"]))
        # Validate all groups before changing any preference. The installer
        # additionally snapshots/restores the file as part of its transaction.
        changes = [set_skill_preference(root, name, candidate, **options) for name, candidate in selections]
        result = {"ok": True, "changes": changes, "preferencesPath": inventory["preferencesPath"]}
    result.setdefault("ok", True)
    result["discovery"] = (
        "Metadata only. Read the chosen SKILL.md before using it. These preferences govern Company Agent "
        "recommendations, not Claude's native /name precedence; explicit user choices and managed policies still apply."
    )
    _print_json(result)
    return 0


def _add_base_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", help="Corporate Knowledge Pack root. Defaults to COMPANY_AGENT_KNOWLEDGE_BASE.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="company-agent", description="Company Agent local harness administration CLI")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    state = subparsers.add_parser("state", help="Check personal state compatibility without changing files.")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    state_check = state_sub.add_parser("check")
    _add_state_argument(state_check)
    state_check.set_defaults(func=cmd_state_check)

    handoff = subparsers.add_parser("handoff", help="Create or read a project-bound continuation note without resetting work.")
    handoff_sub = handoff.add_subparsers(dest="handoff_command", required=True)
    for operation in ("create", "read"):
        action = handoff_sub.add_parser(operation)
        _add_state_argument(action)
        action.add_argument("--project", required=True)
        if operation == "create":
            action.add_argument("--session", required=True)
            action.add_argument("--spec", required=True)
        else:
            action.add_argument("--id", required=True)
        action.set_defaults(func=cmd_handoff)

    helper = subparsers.add_parser("setup-helper", help="Generate a bounded offline questionnaire; never execute installation commands.")
    helper_sub = helper.add_subparsers(dest="helper_command", required=True)
    create = helper_sub.add_parser("create")
    _add_state_argument(create)
    create.add_argument("--spec", required=True)
    create.set_defaults(func=cmd_setup_helper)

    skill = subparsers.add_parser("skill", help="Inspect Skill overlaps and select state/project workflow preferences.")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    for operation in ("inventory", "list", "conflicts", "search", "resolve", "prefer", "prefer-incoming", "order", "reset"):
        action = skill_sub.add_parser(operation)
        _add_state_argument(action)
        _add_base_argument(action)
        project = action.add_mutually_exclusive_group()
        project.add_argument("--project-root", help="Project to inspect or configure; defaults to the current directory.")
        project.add_argument("--no-project", action="store_true", help="Inspect user/state sources only.")
        for name in ("claude-root", "plugin-root", "incoming-plugin", "incoming-skill"):
            action.add_argument("--" + name)
        if operation == "search":
            action.add_argument("query")
            action.add_argument("--limit", type=int, choices=range(1, 51), default=12)
        elif operation == "resolve":
            action.add_argument("name")
        if operation in {"prefer", "prefer-incoming", "order", "reset"}:
            action.add_argument("--scope", choices=("project", "default"), default="project")
        if operation == "prefer":
            action.add_argument("--name", required=True)
            action.add_argument("--candidate", required=True, help="Exact candidate ID from skill inventory; never guess.")
        elif operation == "order":
            action.add_argument("--sources", nargs="+", required=True,
                                choices=("user", "project", "personal", "company", "plugin", "corporate"))
        elif operation == "reset":
            action.add_argument("--name", help="Reset one Skill choice; omission resets the selected preference scope.")
        action.set_defaults(func=cmd_skill)

    harness = subparsers.add_parser("harness", help="Inspect, design, generate and validate a project-local agent harness.")
    harness_sub = harness.add_subparsers(dest="harness_command", required=True)
    for operation in ("inspect", "plan", "apply", "validate"):
        action = harness_sub.add_parser(operation)
        action.add_argument("--project", required=True)
        if operation in {"plan", "apply"}:
            action.add_argument("--spec", required=True)
        action.set_defaults(func=cmd_harness)

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
    rebind_mcp = asset_sub.add_parser("rebind-mcp-runtime", help="Explicitly revalidate a signed personal MCP with the current approved Python after a Core update.")
    _add_state_argument(rebind_mcp)
    rebind_mcp.add_argument("--name", required=True)
    rebind_mcp.add_argument("--timeout", type=int, default=30)
    rebind_mcp.set_defaults(func=cmd_asset_rebind_mcp)
    activate = asset_sub.add_parser("activate-mcp")
    _add_state_argument(activate)
    activate.add_argument("--name", required=True)
    activate.add_argument("--receipt", required=True)
    activate.set_defaults(func=cmd_asset_activate_mcp)
    sync_mcp = asset_sub.add_parser("sync-mcp", help="Retry native scoped registration for an already validated active MCP.")
    _add_state_argument(sync_mcp)
    sync_mcp.add_argument("--name", required=True)
    sync_mcp.set_defaults(func=cmd_asset_sync_mcp)
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

    context = subparsers.add_parser("context", help="Read-only instruction size diagnostics.")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_audit = context_sub.add_parser("audit")
    context_audit.add_argument("--project", default=str(Path.cwd()))
    context_audit.set_defaults(func=cmd_context_audit)

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
    memory_compact = memory_sub.add_parser("compact", help="Rebuild a deduplicated index without changing source memories.")
    _add_state_argument(memory_compact)
    memory_compact.set_defaults(func=cmd_memory_compact)

    learning = subparsers.add_parser("learning", help="Automatic personal learning review, observations, effects, and reversible changes.")
    learning_sub = learning.add_subparsers(dest="learning_command", required=True)
    for operation in ("review", "stage", "status", "pause", "resume", "rollback"):
        action = learning_sub.add_parser(operation)
        _add_state_argument(action)
        if operation in {"review", "stage"}:
            action.add_argument("--session", required=True)
            action.add_argument("--turn", required=True)
            action.add_argument("--spec", required=True)
        elif operation == "status":
            action.add_argument("--session")
        elif operation == "rollback":
            action.add_argument("--change", required=True)
        action.set_defaults(func=cmd_learning)

    work = subparsers.add_parser("work", help="Mark business milestones, not every chat reply.")
    work_sub = work.add_subparsers(dest="work_command", required=True)
    checkpoint = work_sub.add_parser("checkpoint")
    _add_state_argument(checkpoint)
    checkpoint.add_argument("--session", required=True)
    checkpoint.add_argument("--turn", required=True)
    checkpoint.add_argument("--status", choices=("active", "waiting", "complete", "cancelled"), required=True)
    checkpoint.add_argument("--learn", choices=("yes", "no"), default="no")
    checkpoint.add_argument("--new", choices=("yes", "no"), default="no")
    checkpoint.set_defaults(func=cmd_work)
    resolve_work = work_sub.add_parser("resolve", help="Link a current verified remediation to one prior unresolved work ID.")
    _add_state_argument(resolve_work)
    resolve_work.add_argument("--session", required=True)
    resolve_work.add_argument("--turn", required=True)
    resolve_work.add_argument("--work-id", required=True)
    resolve_work.set_defaults(func=cmd_work)

    session = subparsers.add_parser("session", help="Manage compact verification state; no transcript content is stored.")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    verify = session_sub.add_parser("verify")
    _add_state_argument(verify)
    verify.add_argument("--session", required=True)
    verify.add_argument("--status", choices=("pass", "fail", "not_applicable", "partial", "unavailable"), required=True)
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
    from .business import register as register_business
    register_business(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Error details can contain the same Unicode paths as successful output.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
