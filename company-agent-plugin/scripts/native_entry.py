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

from company_agent.native_runtime import bounded_prompt_context, configure_runtime, runtime_context, session_start


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
        cwd = Path(str(payload.get("cwd") or os.getcwd()))
        active = configure_runtime(plugin, cwd)
        if not active:
            print("{}")
            return 0
        if event == "SessionStart":
            result = session_start(plugin, cwd, session_id=str(payload.get("session_id") or ""), source=str(payload.get("source") or ""))
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
                    plugin, cwd, str(payload.get("prompt", payload.get("user_prompt", "")))
                ))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        # No exception payload, model credentials or raw prompt is logged.
        if event == "PreToolUse":
            result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                      "permissionDecisionReason": "Company Agent runtime unavailable; reinstall the package before using corporate tools."}}
        else:
            result = {"systemMessage": "Company Agent initialization failed. Run the installer again; this session's harness checks are unavailable."}
        print(json.dumps(result))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
