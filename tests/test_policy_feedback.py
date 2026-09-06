from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.paths import atomic_write_json, ensure_user_layout  # noqa: E402
from company_agent.policy import evaluate_tool_call, validate_select_only  # noqa: E402
from company_agent.state import (  # noqa: E402
    begin_turn,
    load_session,
    mark_verified,
    record_activity,
    stop_decision,
)


def decision(payload: dict[str, object]) -> str:
    output = payload.get("hookSpecificOutput", {})
    return str(output.get("permissionDecision", "allow"))  # type: ignore[union-attr]


def run_hook(
    script_name: str,
    stdin_text: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script_name)],
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=ROOT,
    )


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        layout = ensure_user_layout(self.state)
        atomic_write_json(
            layout["config"] / "user.json",
            {"user_email": "me@example.corp"},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_session_settings_preserve_models_and_do_not_bypass_policy(self) -> None:
        settings = json.loads(
            (ROOT / "config" / "session.settings.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("model", settings)
        self.assertNotIn("availableModels", settings)
        self.assertNotIn("enforceAvailableModels", settings)
        self.assertNotIn("env", settings)
        allowed = settings.get("permissions", {}).get("allow", [])
        self.assertFalse(
            any(
                "corp-db-read" in rule or "corp-outlook-self" in rule
                for rule in allowed
            )
        )

    def evaluate(self, tool_name: str, tool_input: object) -> str:
        result = evaluate_tool_call(
            {"tool_name": tool_name, "tool_input": tool_input},
            self.state,
        )
        return decision(result)

    def test_select_cte_and_explain_are_allowed(self) -> None:
        self.assertTrue(
            validate_select_only("SELECT * FROM T WHERE note='delete me'")[0]
        )
        self.assertTrue(
            validate_select_only(
                "WITH x AS (SELECT 1 AS n) SELECT n FROM x;"
            )[0]
        )
        self.assertTrue(validate_select_only("EXPLAIN SELECT * FROM T")[0])

    def test_mutation_multistatement_select_into_and_malformed_sql_are_denied(
        self,
    ) -> None:
        denied_sql = [
            "DELETE FROM T",
            "SELECT 1; SELECT 2",
            "WITH x AS (SELECT 1) UPDATE T SET a=1",
            "SELECT * INTO copied_table FROM T",
            "SELECT * FROM T WHERE note='unterminated",
            "SELECT * FROM [unterminated",
            "SELECT * FROM T /* unterminated",
        ]
        for sql in denied_sql:
            with self.subTest(sql=sql):
                self.assertFalse(validate_select_only(sql)[0])

    def test_db_query_requires_a_recognized_sql_payload(self) -> None:
        self.assertEqual(
            "deny",
            self.evaluate("mcp__corp-db-read__execute_query", {"table": "T"}),
        )
        self.assertEqual(
            "allow",
            self.evaluate(
                "mcp__corp-db-read__run_query",
                {"request": {"query_text": "SELECT * FROM T"}},
            ),
        )

    def test_db_rejects_mutation_and_unrecognized_nested_sql(self) -> None:
        cases = [
            (
                "mcp__corp-db-read__query",
                {"sql": "UPDATE T SET A=1"},
            ),
            (
                "mcp__corp-db-read__query",
                {"request": {"body": "SELECT * FROM T"}},
            ),
            (
                "mcp__corp-db-read__query",
                {"request": {"body": "notes; DELETE FROM T"}},
            ),
            (
                "mcp__corp-db-read__query",
                {"sql": "SELECT * INTO copied_table FROM T"},
            ),
        ]
        for tool_name, tool_input in cases:
            with self.subTest(tool_input=tool_input):
                self.assertEqual("deny", self.evaluate(tool_name, tool_input))

    def test_db_metadata_allowlist_and_unknown_operation(self) -> None:
        for operation in ("list_tables", "describe_table", "health_check"):
            with self.subTest(operation=operation):
                self.assertEqual(
                    "allow",
                    self.evaluate(
                        f"mcp__corp-db-read__{operation}",
                        {"schema": "dbo", "table": "T"},
                    ),
                )
        self.assertEqual(
            "deny",
            self.evaluate("mcp__corp-db-read__download_backup", {}),
        )
        self.assertEqual(
            "deny",
            self.evaluate("mcp__corp-db-read__list_tables", {"sql": "SELECT 1"}),
        )

    def test_db_operation_name_cannot_mix_query_with_a_write_verb(self) -> None:
        self.assertEqual(
            "deny",
            self.evaluate(
                "mcp__corp-db-read__delete_query",
                {"sql": "SELECT * FROM T"},
            ),
        )

    def test_managed_server_matching_is_anchored_and_malformed_names_fail_closed(
        self,
    ) -> None:
        self.assertEqual(
            "allow",
            self.evaluate("mcp__evil-corp-db-read__query", {"sql": "DROP TABLE T"}),
        )
        self.assertEqual(
            "allow",
            self.evaluate(
                "mcp__evil-corp-outlook-self__send_mail",
                {"from": "other@example.corp"},
            ),
        )
        self.assertEqual("deny", self.evaluate("mcp__corp-db-read__", {}))
        self.assertEqual("deny", self.evaluate("mcp__corp-outlook-self__", {}))

    def test_outlook_accepts_nested_own_sender_and_camel_case_send(self) -> None:
        for tool_name in (
            "mcp__corp-outlook-self__send_mail",
            "mcp__corp-outlook-self__sendMail",
            "mcp__corp-outlook-self__reply_all",
            "mcp__corp-outlook-self__forward_message",
        ):
            with self.subTest(tool_name=tool_name):
                self.assertEqual(
                    "allow",
                    self.evaluate(
                        tool_name,
                        {
                            "message": {
                                "from": {
                                    "emailAddress": {
                                        "address": "Me <me@example.corp>"
                                    }
                                }
                            }
                        },
                    ),
                )

    def test_outlook_send_reply_forward_reject_missing_or_mismatched_identity(
        self,
    ) -> None:
        cases = [
            ("mcp__corp-outlook-self__send_mail", {"subject": "hello"}),
            ("mcp__corp-outlook-self__reply", {"message_id": "1"}),
            (
                "mcp__corp-outlook-self__forward_mail",
                {"sender": "shared@example.corp"},
            ),
            (
                "mcp__corp-outlook-self__send_mail",
                {"from": {"emailAddress": {"address": "not-an-email"}}},
            ),
        ]
        for tool_name, tool_input in cases:
            with self.subTest(tool_name=tool_name, tool_input=tool_input):
                self.assertEqual("deny", self.evaluate(tool_name, tool_input))

    def test_outlook_accepts_explicit_immutable_authenticated_account(self) -> None:
        self.assertEqual(
            "allow",
            self.evaluate(
                "mcp__corp-outlook-self__send_mail",
                {
                    "authenticatedAccount": {
                        "emailAddress": {"address": "me@example.corp"}
                    },
                    "subject": "hello",
                },
            ),
        )
        self.assertEqual(
            "deny",
            self.evaluate(
                "mcp__corp-outlook-self__reply",
                {"authenticatedAccountEmail": "shared@example.corp"},
            ),
        )

    def test_outlook_non_send_changes_and_unknown_operations_are_not_autoapproved(
        self,
    ) -> None:
        for operation in ("delete_mail", "move_message", "custom_action"):
            with self.subTest(operation=operation):
                self.assertEqual(
                    "ask",
                    self.evaluate(f"mcp__corp-outlook-self__{operation}", {}),
                )
        self.assertEqual(
            "allow",
            self.evaluate(
                "mcp__corp-outlook-self__search_mail",
                {"query": "status report"},
            ),
        )

    def test_policy_hook_parse_and_runtime_errors_fail_closed(self) -> None:
        parse_failure = run_hook("policy_guard_hook.py", "not-json")
        self.assertEqual(0, parse_failure.returncode)
        self.assertEqual("deny", decision(json.loads(parse_failure.stdout)))
        self.assertEqual("", parse_failure.stderr)

        missing_name = run_hook("policy_guard_hook.py", json.dumps({"tool_input": {}}))
        self.assertEqual(0, missing_name.returncode)
        self.assertEqual("deny", decision(json.loads(missing_name.stdout)))

        (self.state / "config" / "user.json").write_text(
            "{broken-json",
            encoding="utf-8",
        )
        marker = "DO-NOT-ECHO-PAYLOAD"
        env = os.environ.copy()
        env["COMPANY_AGENT_USER_STATE"] = str(self.state)
        runtime_failure = run_hook(
            "policy_guard_hook.py",
            json.dumps(
                {
                    "tool_name": "mcp__corp-outlook-self__send_mail",
                    "tool_input": {
                        "from": "me@example.corp",
                        "subject": marker,
                    },
                }
            ),
            env,
        )
        self.assertEqual(0, runtime_failure.returncode)
        self.assertEqual("deny", decision(json.loads(runtime_failure.stdout)))
        self.assertNotIn(marker, runtime_failure.stdout)
        self.assertEqual("", runtime_failure.stderr)


class FeedbackStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mutation_requires_verification_then_allows_stop(self) -> None:
        marker = "DO-NOT-STORE-CONTENT"
        begin_turn("session-1", "MEDIUM", True, ["FILE_WRITE_INTENT"], self.state)
        record_activity(
            {
                "session_id": "session-1",
                "tool_name": "Write",
                "tool_input": {"file_path": "secret.txt", "content": marker},
                "tool_response": marker,
            },
            self.state,
        )
        first = stop_decision({"session_id": "session-1"}, self.state)
        self.assertEqual("block", first["decision"])
        state_text = (
            self.state / "sessions" / "session-1.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn(marker, state_text)
        self.assertNotIn("secret.txt", state_text)
        mark_verified("session-1", "pass", "unit tests passed", self.state)
        self.assertEqual({}, stop_decision({"session_id": "session-1"}, self.state))

    def test_read_only_context_audit_preserves_verification_but_compounds_do_not(self) -> None:
        from company_agent.native_runtime import cli_command
        session = "context-audit"
        begin_turn(session, "SMALL", False, (), self.state)
        mark_verified(session, "pass", "previous check", self.state)
        command = cli_command(SCRIPTS.parent) + f' context audit --project "{self.state}"'
        record_activity({"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}}, self.state)
        current = load_session(session, self.state)
        self.assertEqual(0, current["mutationCount"])
        self.assertEqual("pass", current["verification"]["status"])
        record_activity({"session_id": session, "tool_name": "Bash", "tool_input": {"command": command + " > result.txt"}}, self.state)
        self.assertEqual(1, load_session(session, self.state)["mutationCount"])

    def test_failed_verification_requests_fresh_worker_without_claiming_rewind(self) -> None:
        session = "fresh-retry"
        begin_turn(session, "LARGE", True, (), self.state)
        record_activity({"session_id": session, "tool_name": "Write"}, self.state)
        mark_verified(session, "fail", "one failing test", self.state)
        result = stop_decision({"session_id": session}, self.state)
        self.assertEqual("block", result["decision"])
        self.assertIn("새 worker", result["reason"])
        self.assertIn("2,000자", result["reason"])
        self.assertIn("rollback이 아닙니다", result["reason"])
        self.assertEqual(1, load_session(session, self.state)["stopRetryCount"])

    def test_stop_allows_two_corrective_continuations_even_when_active(self) -> None:
        begin_turn("session-loop", "MEDIUM", True, ["FILE_WRITE_INTENT"], self.state)
        record_activity(
            {"session_id": "session-loop", "tool_name": "Write", "tool_input": {}},
            self.state,
        )
        first = stop_decision(
            {"session_id": "session-loop", "stop_hook_active": False},
            self.state,
        )
        second = stop_decision(
            {"session_id": "session-loop", "stop_hook_active": True},
            self.state,
        )
        exhausted = stop_decision(
            {"session_id": "session-loop", "stop_hook_active": True},
            self.state,
        )
        self.assertEqual("block", first.get("decision"))
        self.assertEqual("block", second.get("decision"))
        self.assertNotEqual("block", exhausted.get("decision"))
        self.assertIn("did not pass", exhausted["systemMessage"])
        self.assertIn("do not treat this run as successful", exhausted["systemMessage"])
        self.assertEqual(2, load_session("session-loop", self.state)["stopRetryCount"])

    def test_equivalent_failure_stops_after_bounded_retries(self) -> None:
        begin_turn("session-fail", "MEDIUM", True, ["FILE_WRITE_INTENT"], self.state)
        record_activity(
            {"session_id": "session-fail", "tool_name": "Write", "tool_input": {}},
            self.state,
        )
        mark_verified("session-fail", "fail", "same failing assertion", self.state)
        record_activity(
            {"session_id": "session-fail", "tool_name": "Edit", "tool_input": {}},
            self.state,
        )
        mark_verified("session-fail", "fail", "same failing assertion", self.state)
        result = stop_decision({"session_id": "session-fail"}, self.state)
        self.assertNotEqual("block", result.get("decision"))
        self.assertIn("same verification failure repeated", result["systemMessage"])
        self.assertIn("did not pass", result["systemMessage"])

    def test_read_only_tool_does_not_create_verification_gate(self) -> None:
        record_activity(
            {
                "session_id": "session-2",
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            },
            self.state,
        )
        record_activity(
            {
                "session_id": "session-2",
                "tool_name": "mcp__personal-search__list_items",
                "tool_input": {},
            },
            self.state,
        )
        self.assertEqual({}, stop_decision({"session_id": "session-2"}, self.state))

    def test_conservative_mutation_detection_covers_shell_and_personal_mcp(self) -> None:
        commands = [
            "echo x>out.txt",
            "Get-Content a.txt | Out-File b.txt",
            "python script.py",
            "git restore file.txt",
            "git apply update.patch",
        ]
        for command in commands:
            record_activity(
                {
                    "session_id": "session-mutations",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
                self.state,
            )
        record_activity(
            {
                "session_id": "session-mutations",
                "tool_name": "mcp__personal-tools__do_work",
                "tool_input": {},
            },
            self.state,
        )
        stored = load_session("session-mutations", self.state)
        self.assertEqual(len(commands) + 1, stored["mutationCount"])
        self.assertEqual(
            "block",
            stop_decision({"session_id": "session-mutations"}, self.state)[
                "decision"
            ],
        )

    def test_native_verification_command_keeps_its_own_pass_marker(self) -> None:
        session = "session-native-verify"
        suffix = f'session verify --session "{session}" --status pass --summary "검증 성공"'
        entrypoint = SCRIPTS / "Invoke-CompanyAgent.ps1"
        commands = [
            f'company-agent {suffix}',
            f'& "{SCRIPTS.parent / "bin" / "company-agent.cmd"}" {suffix}',
            f'"{sys.executable}" "{SCRIPTS / "harness_cli.py"}" {suffix}',
            f'python -I -B "{SCRIPTS / "harness_cli.py"}" {suffix}',
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{entrypoint}" -Mode Cli {suffix}',
            f'& powershell.exe -NoProfile -File "{entrypoint}" -Mode Cli {suffix}',
        ]
        for command in commands:
            with self.subTest(command=command):
                begin_turn(session, "MEDIUM", True, [], self.state)
                record_activity({"session_id": session, "tool_name": "Write", "tool_input": {}}, self.state)
                mark_verified(session, "pass", "검증 성공", self.state)
                updated = record_activity(
                    {"session_id": session, "tool_name": "PowerShell", "tool_input": {"command": command}},
                    self.state,
                )
                self.assertEqual(1, updated["mutationCount"])
                self.assertEqual("pass", updated["verification"]["status"])
                self.assertEqual({}, stop_decision({"session_id": session}, self.state))

    def test_verification_exception_rejects_compounds_fake_paths_and_other_actions(self) -> None:
        session = "session-verify-reject"
        suffix = f'session verify --session {session} --status pass --summary "check passed"'
        entrypoint = SCRIPTS / "Invoke-CompanyAgent.ps1"
        valid = f'powershell.exe -NoProfile -File "{entrypoint}" -Mode Cli {suffix}'
        commands = [
            valid + '; Set-Content result.txt changed',
            valid + ' && python another.py',
            valid + ' | Out-File result.txt',
            valid + '\nSet-Content result.txt changed',
            valid.replace('check passed', '$(Set-Content result.txt changed)'),
            valid.replace(str(entrypoint), str(Path(self.temp.name) / "Invoke-CompanyAgent.ps1")),
            valid.replace('powershell.exe', f'"{Path(self.temp.name) / "powershell.exe"}"', 1),
            valid.replace(f'--session {session}', '--session another-session'),
            valid + ' --state-root another-state',
            valid.replace('session verify', 'memory upsert'),
            f'python "{Path(self.temp.name) / "harness_cli.py"}" {suffix}',
            f'python -c "print(1)" "{SCRIPTS / "harness_cli.py"}" {suffix}',
            f'company-agent {suffix}; echo x>result.txt',
        ]
        for command in commands:
            with self.subTest(command=command):
                begin_turn(session, "MEDIUM", True, [], self.state)
                mark_verified(session, "pass", "earlier check", self.state)
                updated = record_activity(
                    {"session_id": session, "tool_name": "PowerShell", "tool_input": {"command": command}},
                    self.state,
                )
                self.assertEqual(1, updated["mutationCount"])
                self.assertIsNone(updated["verification"])
                self.assertEqual("block", stop_decision({"session_id": session}, self.state)["decision"])

    def test_native_failed_verification_preserves_equivalent_failure_count(self) -> None:
        session = "session-native-fail"
        begin_turn(session, "MEDIUM", True, [], self.state)
        record_activity({"session_id": session, "tool_name": "Write", "tool_input": {}}, self.state)
        command = (
            f'python "{SCRIPTS / "harness_cli.py"}" session verify '
            f'--session {session} --status fail --summary "same failing assertion"'
        )
        for _ in range(2):
            mark_verified(session, "fail", "same failing assertion", self.state)
            record_activity(
                {"hook_event_name": "PostToolUseFailure", "session_id": session,
                 "tool_name": "Bash", "tool_input": {"command": command}, "error": "exit code 1"},
                self.state,
            )
        stored = load_session(session, self.state)
        self.assertEqual("fail", stored["verification"]["status"])
        self.assertEqual(2, stored["sameFailureCount"])
        self.assertIn("same verification failure", stop_decision({"session_id": session}, self.state)["systemMessage"])

    def test_failed_tool_that_may_have_mutated_still_requires_verification(self) -> None:
        record_activity(
            {
                "hook_event_name": "PostToolUseFailure",
                "session_id": "session-failed-tool",
                "tool_name": "PowerShell",
                "tool_input": {"command": "python script.py"},
                "error": "command failed after partial work",
            },
            self.state,
        )
        stored = load_session("session-failed-tool", self.state)
        self.assertEqual(1, stored["mutationCount"])
        self.assertFalse(stored["recentTools"][-1]["success"])
        self.assertEqual(
            "block",
            stop_decision({"session_id": "session-failed-tool"}, self.state)[
                "decision"
            ],
        )
        state_text = (
            self.state / "sessions" / "session-failed-tool.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("command failed", state_text)
        self.assertNotIn("script.py", state_text)

    def test_outlook_send_reply_and_forward_require_receipt_verification(self) -> None:
        for index, operation in enumerate(
            ("send_mail", "reply", "forward_message", "delete_message")
        ):
            session_id = f"session-mail-{index}"
            record_activity(
                {
                    "session_id": session_id,
                    "tool_name": f"mcp__corp-outlook-self__{operation}",
                    "tool_input": {"subject": "not stored"},
                },
                self.state,
            )
            self.assertEqual(
                "block",
                stop_decision({"session_id": session_id}, self.state)["decision"],
            )

    def test_parallel_activity_updates_do_not_lose_counts(self) -> None:
        calls = 30
        begin_turn("session-parallel", "MEDIUM", True, [], self.state)

        def record(index: int) -> None:
            record_activity(
                {
                    "session_id": "session-parallel",
                    "tool_name": "Write",
                    "tool_input": {"content": f"payload-{index}"},
                },
                self.state,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(record, range(calls)))

        stored = load_session("session-parallel", self.state)
        self.assertEqual(calls, stored["mutationCount"])
        self.assertEqual(20, len(stored["recentTools"]))
        state_text = (
            self.state / "sessions" / "session-parallel.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("payload-", state_text)

    def test_stop_hook_parse_error_ends_with_honest_failure(self) -> None:
        result = run_hook("stop_feedback_hook.py", "not-json")
        self.assertEqual(0, result.returncode)
        output = json.loads(result.stdout)
        self.assertNotIn("decision", output)
        self.assertIn("not verified", output["systemMessage"])
        self.assertEqual("", result.stderr)


if __name__ == "__main__":
    unittest.main()
