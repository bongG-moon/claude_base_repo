"""Read-only preparation must not manufacture a verification continuation."""
from pathlib import Path
import sys
import shlex
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.execution_contract import classify_command, safe_permission
from company_agent.state import begin_turn, load_session, mark_verified, record_activity, stop_decision


class CompletionEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        begin_turn("efficiency", "SMALL", False, [], self.root)

    def activity(self, command):
        return record_activity({"session_id": "efficiency", "tool_name": "Bash",
                                "hook_event_name": "PostToolUse",
                                "tool_input": {"command": command}}, self.root)

    def test_literal_python_version_does_not_create_completion_gate(self):
        for command in ("python --version", "python3 -V", "py --version",
                        "python -X utf8 --version", "python -I -B -Xutf8 -u -V",
                        "py -3 --version", "py -3.13 -X utf8 -V",
                        f'"{sys.executable}" --version'):
            with self.subTest(command=command):
                state = self.activity(command)
                self.assertEqual(0, state["mutationCount"])
                self.assertEqual({}, stop_decision({"session_id": "efficiency"}, self.root))

    def test_utf8_cli_metadata_keeps_read_only_contract_and_existing_pass(self):
        mark_verified("efficiency", "pass", "existing actual check", self.root)
        for flags in ("-X utf8 -B", "-B -X utf8", "-Xutf8 -I -B"):
            command = f'"{sys.executable}" {flags} "{SCRIPTS / "harness_cli.py"}" session status --session efficiency'
            with self.subTest(flags=flags):
                self.assertEqual("read_only", classify_command(command))
                state = self.activity(command)
                self.assertEqual(0, state["mutationCount"])
                self.assertEqual("pass", state["verification"]["status"])
                self.assertIsNone(safe_permission({"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                                                   "tool_input": {"command": command}}, self.root))

    def test_version_chain_or_script_still_requires_actual_verification(self):
        for command in ("python --version > version.txt", "python --version && python task.py",
                        "python --version; Remove-Item output.txt", "python --version task.py",
                        "python -c 'print(1)'", "py task.py", "python --version | tee version.txt",
                        "python --version $(python task.py)", "python --version %EXTRA%",
                        "python -X utf8 --version > version.txt", "python -X utf8 -c 'print(1)'",
                        "py -3 --version && python task.py", "py -3 -X utf8 task.py",
                        "python -X arbitrary --version", "python -X utf8 --version task.py",
                        f'"{self.root / "python.exe"}" --version'):
            with self.subTest(command=command):
                before = load_session("efficiency", self.root)["mutationCount"]
                self.assertEqual(before + 1, self.activity(command)["mutationCount"])

    def test_utf8_internal_verification_does_not_invalidate_its_own_receipt(self):
        self.activity("python task.py")
        mark_verified("efficiency", "pass", "actual result inspected", self.root)
        command = (f'"{sys.executable}" -X utf8 -B "{SCRIPTS / "harness_cli.py"}" '
                   'session verify --session efficiency --status pass --summary "actual result inspected"')
        state = self.activity(command)
        self.assertEqual(1, state["mutationCount"])
        self.assertEqual("pass", state["verification"]["status"])
        self.assertEqual({}, stop_decision({"session_id": "efficiency"}, self.root))

    def test_utf8_does_not_exempt_unknown_script_or_business_write(self):
        for tail in (f'"{SCRIPTS / "harness_cli.py"}" memory upsert --spec "{self.root / "spec.json"}" --storage-scope personal',
                     f'"{self.root / "harness_cli.py"}" session status --session efficiency',
                     f'"{SCRIPTS / "harness_cli.py"}" session status --session efficiency > "{self.root / "out.txt"}"'):
            command = f'"{sys.executable}" -X utf8 -B {tail}'
            with self.subTest(tail=tail):
                self.assertNotEqual("read_only", classify_command(command))
                before = load_session("efficiency", self.root)["mutationCount"]
                self.assertEqual(before + 1, self.activity(command)["mutationCount"])

    def test_read_only_preparation_does_not_clear_prior_obligation(self):
        self.activity("python task.py")
        self.activity("python --version")
        state = load_session("efficiency", self.root)
        self.assertEqual(1, state["mutationCount"])
        self.assertIsNone(state["verification"])
        self.assertEqual("block", stop_decision({"session_id": "efficiency"}, self.root)["decision"])

    def test_settings_and_hook_lookup_do_not_count_as_corrective_progress(self):
        self.activity("python task.py")
        self.assertEqual("block", stop_decision({"session_id": "efficiency"}, self.root)["decision"])
        record_activity({"session_id": "efficiency", "tool_name": "Read",
                         "tool_input": {"file_path": ".claude/settings.local.json"}}, self.root)
        record_activity({"session_id": "efficiency", "tool_name": "Glob",
                         "tool_input": {"pattern": "**/hooks/*"}}, self.root)
        self.activity(r'ls ~/.claude/hooks 2>/dev/null; cat ~/.claude/settings.json 2>/dev/null; cat "C:\Users\2069026\Desktop\하네스_테스트.claude\hooks"/* 2>/dev/null | head -80')
        state = load_session("efficiency", self.root)
        self.assertEqual(1, state["mutationCount"])
        self.assertGreater(state["activityCount"], 1)
        for payload in ({"session_id": "efficiency", "stop_hook_active": True},
                        {"session_id": "efficiency"}):
            self.assertNotIn("decision", stop_decision(payload, self.root))
        state = load_session("efficiency", self.root)
        self.assertEqual(1, state["stopRetryCount"])
        self.assertIsNone(state["verification"])

    def test_reading_with_null_stderr_never_grants_permission_or_hides_writes(self):
        readonly = ('cat file.txt 2>/dev/null', 'cat *.md 2>/dev/null | head -80',
                    'pwd; ls -la 2>/dev/null; cat file.txt | head -n 20')
        for command in readonly:
            with self.subTest(command=command):
                self.assertEqual(0, self.activity(command)["mutationCount"])
                self.assertIsNone(safe_permission({"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                    "tool_input": {"command": command}}, self.root))
        for command in ('cat file.txt > output.txt', 'cat file.txt 2>errors.txt',
                        'cat file.txt 2>>/dev/null', 'cat file.txt 2>/dev/null; rm file.txt',
                        'cat $(python task.py) 2>/dev/null', 'cat `python task.py` 2>/dev/null',
                        'cat file.txt 2>/dev/null | python task.py', 'cat file.txt 2>/dev/null | tee output.txt'):
            with self.subTest(command=command):
                before = load_session("efficiency", self.root)["mutationCount"]
                self.assertEqual(before + 1, self.activity(command)["mutationCount"])
        state = record_activity({"session_id": "efficiency", "tool_name": "PowerShell",
            "tool_input": {"command": "cat file.txt 2>/dev/null"}}, self.root)
        self.assertEqual(before + 2, state["mutationCount"])

    def test_real_result_changes_allow_remaining_bounded_correction(self):
        self.activity("python task.py")
        self.assertEqual("block", stop_decision({"session_id": "efficiency"}, self.root)["decision"])
        record_activity({"session_id": "efficiency", "tool_name": "Edit"}, self.root)
        self.assertEqual("block", stop_decision({"session_id": "efficiency", "stop_hook_active": True}, self.root)["decision"])
        record_activity({"session_id": "efficiency", "tool_name": "Edit"}, self.root)
        self.assertNotIn("decision", stop_decision({"session_id": "efficiency", "stop_hook_active": True}, self.root))
        self.assertEqual(2, load_session("efficiency", self.root)["stopRetryCount"])

    def test_completion_instruction_is_self_contained_and_distinguishes_missing_receipt(self):
        from company_agent.native_runtime import cli_command
        self.activity("python task.py")
        first = stop_decision({"session_id": "efficiency"}, self.root)["reason"]
        prefix = cli_command(SCRIPTS.parent)
        self.assertIn(prefix + " session verify", first)
        self.assertIn("--state-root " + shlex.quote(str(self.root)), first)
        self.assertIn('--session "efficiency"', first)
        self.assertIn("기록이 아직 없습니다", first)
        self.assertIn("이미 수행한 검사 근거는 재사용", first)
        self.assertIn("최신 변경 뒤 실제 검사에 성공했을 때만", first)
        self.assertIn("설정·후크·환경변수·세션을 재탐색하지", first)
        for status in ("pass", "fail", "partial", "unavailable"):
            self.assertIn("--status " + status, first)
        self.assertLess(len(first), len(prefix) + len(str(self.root)) + 900)
        mark_verified("efficiency", "fail", "actual failed check", self.root)
        second = stop_decision({"session_id": "efficiency", "stop_hook_active": True}, self.root)["reason"]
        self.assertIn("실제 결과 검사 실패", second)
        self.assertNotIn("기록이 아직 없습니다", second)


if __name__ == "__main__":
    unittest.main()
