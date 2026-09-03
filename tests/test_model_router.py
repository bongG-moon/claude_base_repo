from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.model_router import (  # noqa: E402
    LARGE,
    MEDIUM,
    SMALL,
    classify_prompt,
    hook_output,
)
from company_agent.memory import MEMORY_CONTEXT_BEGIN, upsert_memory  # noqa: E402


class ModelRouterTests(unittest.TestCase):
    def test_simple_summary_routes_small(self) -> None:
        decision = classify_prompt("이 문단을 짧게 요약해줘")
        self.assertEqual(SMALL, decision.tier)
        self.assertEqual("haiku", decision.model_alias)

    def test_normal_implementation_routes_medium_and_requires_verification(self) -> None:
        decision = classify_prompt("이 Python 파일의 오류를 수정하고 테스트도 실행해줘")
        self.assertEqual(MEDIUM, decision.tier)
        self.assertEqual("sonnet", decision.model_alias)
        self.assertTrue(decision.verification_required)

    def test_architecture_and_mcp_creation_route_large(self) -> None:
        decision = classify_prompt("전사 에이전트 아키텍처를 설계하고 MCP 서버를 구현해줘")
        self.assertEqual(LARGE, decision.tier)
        self.assertEqual("opus", decision.model_alias)
        self.assertTrue(decision.verification_required)

    def test_large_safety_floor_overrides_explicit_small(self) -> None:
        decision = classify_prompt(
            "SMALL 모델로 전사 보안 아키텍처를 전면 재설계하고 구현해줘"
        )
        self.assertEqual(LARGE, decision.tier)
        self.assertIn("SAFE_TIER_FLOOR_APPLIED", decision.reason_codes)

    def test_read_only_analysis_does_not_require_file_verification(self) -> None:
        decision = classify_prompt("이 장애의 근본 원인을 분석해서 설명해줘")
        self.assertEqual(LARGE, decision.tier)
        self.assertFalse(decision.verification_required)

    def test_unknown_work_uses_conservative_medium_default(self) -> None:
        decision = classify_prompt("도와줘")
        self.assertEqual(MEDIUM, decision.tier)
        self.assertIn("CONSERVATIVE_DEFAULT", decision.reason_codes)

    def test_context_is_deterministic_and_does_not_echo_prompt(self) -> None:
        secret_prompt = "간단히 번역해줘 SECRET-DO-NOT-STORE"
        decision = classify_prompt(secret_prompt)
        first = decision.as_additional_context()
        second = decision.as_additional_context()
        self.assertEqual(first, second)
        self.assertNotIn("SECRET-DO-NOT-STORE", first)
        parsed = json.loads(first)
        self.assertEqual(SMALL, parsed["company_agent_route"]["tier"])

    def test_hook_output_uses_user_prompt_submit_context(self) -> None:
        output = hook_output(classify_prompt("간단히 요약해줘"))
        specific = output["hookSpecificOutput"]
        self.assertEqual("UserPromptSubmit", specific["hookEventName"])
        self.assertIsInstance(json.loads(specific["additionalContext"]), dict)

    def test_hook_process_emits_only_route_metadata(self) -> None:
        script = SCRIPTS / "model_route_hook.py"
        marker = "PRIVATE-PROMPT-MARKER"
        completed = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": f"이 문장을 짧게 요약해줘 {marker}",
                }
            ),
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual("", completed.stderr)
        self.assertNotIn(marker, completed.stdout)
        parsed = json.loads(completed.stdout)
        route = json.loads(parsed["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(SMALL, route["company_agent_route"]["tier"])

    def test_hook_process_fails_open_to_medium_on_invalid_json(self) -> None:
        script = SCRIPTS / "model_route_hook.py"
        completed = subprocess.run(
            [sys.executable, str(script)],
            input="not-json",
            text=True,
            capture_output=True,
            check=True,
        )
        parsed = json.loads(completed.stdout)
        route = json.loads(parsed["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(MEDIUM, route["company_agent_route"]["tier"])
        self.assertEqual(
            ["UNREADABLE_HOOK_INPUT"],
            route["company_agent_route"]["reason_codes"],
        )

    def test_hook_session_state_contains_route_but_not_prompt(self) -> None:
        script = SCRIPTS / "model_route_hook.py"
        marker = "PRIVATE-ROUTE-CONTENT"
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = dict(os.environ)
            environment["COMPANY_AGENT_USER_STATE"] = temp_dir
            subprocess.run(
                [sys.executable, str(script)],
                input=json.dumps({"session_id": "route-session", "prompt": f"간단히 요약해줘 {marker}"}),
                text=True,
                capture_output=True,
                check=True,
                env=environment,
            )
            state = (Path(temp_dir) / "sessions" / "route-session.json").read_text(encoding="utf-8")
            self.assertNotIn(marker, state)
            self.assertIn('"tier": "SMALL"', state)

    def test_hook_injects_relevant_memory_without_echoing_prompt_and_exposes_safe_session_id(self) -> None:
        script = SCRIPTS / "model_route_hook.py"
        marker = "PRIVATE-CURRENT-PROMPT-MARKER"
        with tempfile.TemporaryDirectory() as temp_dir:
            state_root = Path(temp_dir)
            upsert_memory(
                {
                    "id": "memory.convention.report-order",
                    "kind": "convention",
                    "title": "보고서 순서",
                    "body": "보고서는 결론과 검증 결과부터 작성한다.",
                },
                state_root,
            )
            environment = dict(os.environ)
            environment["COMPANY_AGENT_USER_STATE"] = temp_dir
            completed = subprocess.run(
                [sys.executable, str(script)],
                input=json.dumps(
                    {
                        "session_id": "route/session with spaces",
                        "prompt": f"새 보고서를 작성해줘 {marker}",
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                env=environment,
            )

        self.assertEqual("", completed.stderr)
        self.assertNotIn(marker, completed.stdout)
        output = json.loads(completed.stdout)
        context = json.loads(output["hookSpecificOutput"]["additionalContext"])
        self.assertEqual("route-session-with-spaces", context["company_agent_session_id"])
        memory_context = context["company_agent_personal_memory_context"]
        self.assertIn(MEMORY_CONTEXT_BEGIN, memory_context)
        self.assertIn("보고서는 결론과 검증 결과부터 작성한다.", memory_context)
        self.assertIn("managed policy", memory_context)

    def test_hook_skips_corrupt_memory_without_breaking_routing(self) -> None:
        script = SCRIPTS / "model_route_hook.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            item_root = Path(temp_dir) / "memory" / "items"
            item_root.mkdir(parents=True)
            (item_root / "broken.md").write_text("---\nid: broken\n", encoding="utf-8")
            environment = dict(os.environ)
            environment["COMPANY_AGENT_USER_STATE"] = temp_dir
            completed = subprocess.run(
                [sys.executable, str(script)],
                input=json.dumps({"session_id": "safe-session", "prompt": "간단히 요약해줘"}),
                text=True,
                capture_output=True,
                check=True,
                env=environment,
            )

        context = json.loads(json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(SMALL, context["company_agent_route"]["tier"])
        self.assertEqual("safe-session", context["company_agent_session_id"])
        self.assertNotIn("company_agent_personal_memory_context", context)


if __name__ == "__main__":
    unittest.main()
