"""Native Claude plugin entry, independent of the Company Agent launcher."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys

# An embeddable interpreter has an isolated ._pth beside its executable. Select
# this entry's plugin code explicitly when the durable interpreter and Claude's
# plugin cache live in different directories or versions.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from company_agent.native_runtime import COMPANY_WORKERS, bounded_prompt_context, configure_runtime, runtime_context, session_start


def main() -> int:
    plugin = Path(__file__).resolve().parent.parent
    if sys.argv[1:2] == ["--cli"]:
        if not configure_runtime(plugin, Path.cwd()):
            print(json.dumps({"ok": False, "error": "Company Agent is not installed for this folder/user. Run Install-CompanyAgent.cmd."}))
            return 1
        from company_agent.cli import main as cli_main
        return cli_main(sys.argv[2:])
    event = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--event" else ""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook input is not an object")
        if event == "PreToolUse" and payload.get("tool_name") in {"Agent", "Task"}:
            inputs = payload.get("tool_input")
            if not isinstance(inputs, dict) or inputs.get("subagent_type") not in COMPANY_WORKERS:
                # An unrelated agent must remain usable even if our own
                # installation record is broken. Do not configure its runtime.
                print("{}")
                return 0
        cwd = Path(str(payload.get("cwd") or os.getcwd()))
        active = configure_runtime(plugin, cwd)
        if not active:
            print("{}")
            return 0
        preparation = {}
        if event == "PreToolUse":
            from company_agent.skill_workflow import preflight
            from company_agent.paths import user_state_root
            try:
                preparation = preflight(user_state_root(), cwd, payload)
            except Exception:
                # Advisory discovery must not block tools or skip the real MCP policy.
                # In particular, an old/malformed receipt can have the wrong
                # JSON shape. Only this optional step is fail-soft.
                preparation = {}
        if event == "SessionStart":
            result = session_start(plugin, cwd, session_id=str(payload.get("session_id") or ""), source=str(payload.get("source") or ""))
        elif event == "PermissionRequest":
            from company_agent.execution_contract import safe_permission
            from company_agent.paths import user_state_root
            payload["hook_event_name"] = event
            decision = safe_permission(payload, user_state_root())
            result = {"hookSpecificOutput": {"hookEventName": event, "decision": decision}} if decision else {}
        elif event == "PreToolUse" and payload.get("tool_name") in {"Agent", "Task"}:
            from company_agent.native_runtime import worker_runtime_input
            result = worker_runtime_input(plugin, cwd, payload)
        else:
            handlers = {
                "UserPromptSubmit": "model_route_hook",
                "PreToolUse": "policy_guard_hook",
                "PostToolUse": "activity_hook",
                "PostToolUseFailure": "activity_hook",
                "Stop": "stop_feedback_hook",
            }
            if event not in handlers:
                raise ValueError("Unsupported hook event")
            payload["hook_event_name"] = event
            # The corporate policy handler accepts only its own MCP servers.
            # Other tools get preparation checks, NOT a new permission grant.
            if event == "PreToolUse" and not str(payload.get("tool_name", "")).startswith(("mcp__corp-db-read__", "mcp__corp-outlook-self__")):
                print(json.dumps(preparation, ensure_ascii=True))
                return 0
            handler = __import__(handlers[event])
            output = io.StringIO()
            original_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
                with contextlib.redirect_stdout(output):
                    handler.main()
            finally:
                sys.stdin = original_stdin
            result = json.loads(output.getvalue() or "{}")
            if event == "UserPromptSubmit":
                text = result["hookSpecificOutput"]["additionalContext"]
                result["hookSpecificOutput"]["additionalContext"] = bounded_prompt_context(text, runtime_context(
                    plugin, cwd, str(payload.get("prompt", payload.get("user_prompt", ""))),
                    session_id=str(payload.get("session_id") or "")
                ))
            if event == "PostToolUse":
                from company_agent.skill_workflow import observe
                from company_agent.paths import user_state_root
                try:
                    observe(user_state_root(), cwd, payload)
                except Exception:
                    # No fabricated read receipt; a later preflight reports the
                    # missing preparation without turning it into a Stop error.
                    pass
                if payload.get("tool_name") in {"Bash", "PowerShell"}:
                    from company_agent.execution_contract import _trusted_arguments
                    inputs = payload.get("tool_input") or {}
                    args = _trusted_arguments(str(inputs.get("command") or inputs.get("cmd") or ""))
                    if args and len(args) > 1 and args[0] == "skill" and args[1] in {"prefer", "prefer-incoming", "order", "reset"}:
                        # Preference edits are uncommon. Refresh just here, not
                        # after every tool call; no stale same-turn substitution.
                        context = runtime_context(plugin, cwd, session_id=str(payload.get("session_id") or ""))
                        result.setdefault("hookSpecificOutput", {"hookEventName": "PostToolUse"})
                        prior = result["hookSpecificOutput"].get("additionalContext", "")
                        result["hookSpecificOutput"]["additionalContext"] = prior + "\n" + context
        if preparation and event == 'PreToolUse':
            target = result.setdefault('hookSpecificOutput', {'hookEventName': event})
            # A real corporate deny always wins; do not confuse it with discovery.
            if target.get('permissionDecision') != 'deny':
                target['additionalContext'] = '\n'.join(filter(None, [target.get('additionalContext'), preparation['hookSpecificOutput']['additionalContext']]))
        # ASCII-safe JSON round-trips Korean even through a legacy Windows pipe.
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception:
        # No exception payload, model credentials or raw prompt is logged.
        if event == "PreToolUse":
            result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                      "permissionDecisionReason": "Company Agent 실행 준비 정보를 읽지 못했습니다. 설치 상태를 확인해 주세요. 기존 실행 권한과 회사 정책은 변경하지 않았습니다."}}
        else:
            result = {"systemMessage": "Company Agent를 준비하지 못했습니다. 설치 상태를 확인해 주세요. 이 대화의 하네스 검사는 사용할 수 없습니다."}
        print(json.dumps(result))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
