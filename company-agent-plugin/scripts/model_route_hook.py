#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook for deterministic model routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from company_agent.memory import MAX_MEMORY_RESULTS, render_memory_context, search_scoped_memory
from company_agent.model_router import MEDIUM, RouteDecision, hook_output, classify_prompt
from company_agent.paths import user_state_root
from company_agent.state import begin_turn, learning_context, safe_session_id


def _safe_default(reason: str) -> RouteDecision:
    return RouteDecision(
        tier=MEDIUM,
        model_alias="sonnet",
        agent="company-agent:medium-worker",
        verification_required=False,
        reason_codes=(reason,),
    )


def main() -> int:
    personal_memory_context = ""
    sanitized_session_id: str | None = None
    learning_metadata: dict | None = None
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            decision = _safe_default("INVALID_HOOK_INPUT")
        else:
            # `prompt` is the current Claude Code field. `user_prompt` keeps the
            # hook usable with older internal builds without echoing either.
            prompt = payload.get("prompt", payload.get("user_prompt", ""))
            prompt_text = prompt if isinstance(prompt, str) else ""
            decision = classify_prompt(prompt_text)

            # Search happens in memory only. Neither this query nor the raw
            # hook payload is persisted, logged, or returned.
            try:
                memories = search_scoped_memory(user_state_root(), Path(payload.get('cwd') or Path.cwd()),
                                                prompt_text, limit=MAX_MEMORY_RESULTS)
                personal_memory_context = render_memory_context(memories)
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                # Corrupt/unreadable memory is ignored. Routing must remain
                # available and unsafe memory must never enter model context.
                personal_memory_context = ""

            session_id = payload.get("session_id")
            if isinstance(session_id, str) and session_id:
                sanitized_session_id = safe_session_id(session_id)
                try:
                    state = begin_turn(
                        session_id,
                        decision.tier,
                        decision.verification_required,
                        decision.reason_codes,
                        native_prompt_id=payload.get("prompt_id"),
                    )
                    learning_metadata = learning_context(state)
                except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                    # A damaged session file must not prevent the user from
                    # starting a new Claude turn. Stop verification will fail
                    # closed later because no valid pass record exists.
                    pass
    except (json.JSONDecodeError, OSError, UnicodeError):
        decision = _safe_default("UNREADABLE_HOOK_INPUT")

    output = hook_output(
        decision,
        session_id=sanitized_session_id,
        personal_memory_context=personal_memory_context,
    )
    if learning_metadata:
        envelope = json.loads(output["hookSpecificOutput"]["additionalContext"])
        envelope["company_agent_learning"] = learning_metadata
        output["hookSpecificOutput"]["additionalContext"] = json.dumps(envelope, ensure_ascii=True, separators=(",", ":"))
    json.dump(
        output,
        sys.stdout,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
