"""Synthetic H2 reproduction; shell strings are classified, never executed."""
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.completion_readonly import is_read_only_observation
from company_agent.execution_contract import safe_permission
from company_agent.state import begin_turn, load_session, mark_verified, record_activity, stop_decision


QUERIES = (
    'cd "/c/work/프로젝트" && sed -n \'1,80p\' scripts/review.py 2>/dev/null | tr -d \'\\r\' | grep -n "scope" | head -20',
    'cd -- "C:/work/프로젝트" && grep -En "memory|scope" review.py 2>/dev/null | head -n 30',
    'sed -n "10p" tests/review.py 2>/dev/null',
    'cat review.py 2>/dev/null | tr "a-z" "A-Z" | grep -F -e "SCOPE"',
    'ls -la "C:/work/자료" 2>/dev/null; pwd',
    'cat -- "-review.py" | grep -- "-flag"',
    'grep -m 20 -A2 -n "python" review.py',
    'grep -n ";" review.py',
    'cat review.py | tr -s "[:space:]"',
    'cat *.md 2>/dev/null | head -80',
    'cat "C:/work/자료/hooks"/* 2>/dev/null | head -80',
    'cat *.py 2>/dev/null | grep -n "scope"',
)

UNKNOWN = (
    # Commands with effects mixed into an otherwise ordinary query.
    'cd project && sed -n "1,80p" review.py; python change.py',
    'grep -n "scope" review.py | tee output.txt',
    'cat review.py 2>/dev/null && rm output.txt',
    'cat review.py > output.txt',
    'cat review.py 2>errors.txt',
    'cat review.py 2>>/dev/null',
    'cat review.py 1>/dev/null',
    'cat review.py 2 > /dev/null',
    'cat review.py > /dev/null "2>/dev/null"',
    'cat review.py 2>&1',
    'cat review.py &',
    # sed allows code execution and writes: only numeric print programs qualify.
    'sed -i "s/a/b/" review.py',
    'sed -n "1,20w output.txt" review.py',
    'sed -n "1,20p;w output.txt" review.py',
    'sed -n "1,20p;e touch output.txt" review.py',
    'sed -n -f commands.sed review.py',
    'sed -n "s/a/touch output/e" review.py',
    'sed -n "1,20p" --file=commands.sed review.py',
    # Expansions, other shells, external executables and unsupported grammar.
    'cat $(python change.py)',
    'cat `python change.py`',
    'cat <(python change.py)',
    'cat "$FILE"',
    'cat ${FILE}',
    'cat review.py\npython change.py',
    '/tmp/grep "scope" review.py',
    'bash -c "cat review.py"',
    'python review.py',
    'PATH=/tmp grep "scope" review.py',
    'grep --pre=worker "scope" review.py',
    'grep -f patterns.txt review.py',
    'sed -n "1,20p" review.py ||',
    'grep -e',
    'grep -m abc "scope" review.py',
    'ls\u00a0review.py',  # Bash does not tokenize NBSP as a shell separator.
    'cat "unterminated',
    '2>/dev/null cat review.py',
    # Expansion can turn filenames such as -i/--expression=... into options.
    'sed -n "1p" *',
    'sed -n "1p" ?',
    'sed -n "1p" [-a]*',
    's"e"d -n "1p" *',
    'cat *.md | s"e"d -n "1p" ? | head -20',
    'sed -n "1p" "prefix"*',
    'sed -n "1p" \\[*',
)


class ReadOnlyObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def event(self, command, session="inspect", tool="Bash", failure=False):
        return {"session_id": session, "tool_name": tool,
                "hook_event_name": "PostToolUseFailure" if failure else "PostToolUse",
                "tool_input": {"command": command}}

    def test_synthetic_inspection_paths_do_not_manufacture_completion_gate(self):
        for index, command in enumerate(QUERIES):
            with self.subTest(command=command):
                session = f"query-{index}"
                begin_turn(session, "SMALL", False, [], self.root)
                self.assertTrue(is_read_only_observation(command, "Bash"))
                state = record_activity(self.event(command, session), self.root)
                self.assertEqual(0, state["mutationCount"])
                self.assertIsNone(state["verification"])
                self.assertEqual({}, stop_decision({"session_id": session}, self.root))

    def test_failed_query_does_not_become_business_write(self):
        begin_turn("inspect", "SMALL", False, [], self.root)
        state = record_activity(self.event(QUERIES[0], failure=True), self.root)
        self.assertEqual(0, state["mutationCount"])
        self.assertEqual({}, stop_decision({"session_id": "inspect"}, self.root))

    def test_queries_preserve_prior_change_and_verification_obligation(self):
        begin_turn("inspect", "SMALL", False, [], self.root)
        record_activity({"session_id": "inspect", "tool_name": "Write",
                         "tool_input": {"file_path": "report.html"}}, self.root)
        for command in QUERIES:
            state = record_activity(self.event(command), self.root)
            self.assertEqual(1, state["mutationCount"])
            self.assertIsNone(state["verification"])
        self.assertEqual("block", stop_decision({"session_id": "inspect"}, self.root)["decision"])

    def test_queries_preserve_already_verified_work(self):
        begin_turn("inspect", "SMALL", False, [], self.root)
        record_activity({"session_id": "inspect", "tool_name": "Write"}, self.root)
        mark_verified("inspect", "pass", "test-only verified result", self.root)
        before = load_session("inspect", self.root)
        for command in QUERIES:
            after = record_activity(self.event(command), self.root)
            self.assertEqual(before["verification"], after["verification"])
            self.assertEqual(before["verificationRevision"], after["verificationRevision"])
        self.assertEqual({}, stop_decision({"session_id": "inspect"}, self.root))

    def test_unsupported_and_effectful_syntax_has_no_exemption(self):
        for command in UNKNOWN:
            with self.subTest(command=command):
                self.assertFalse(is_read_only_observation(command, "Bash"))

    def test_script_writes_and_redirections_still_create_completion_gate(self):
        for index, command in enumerate((UNKNOWN[0], UNKNOWN[2], UNKNOWN[3], UNKNOWN[4], UNKNOWN[10], UNKNOWN[13])):
            with self.subTest(command=command):
                session = f"mutation-{index}"
                begin_turn(session, "SMALL", False, [], self.root)
                state = record_activity(self.event(command, session), self.root)
                self.assertEqual(1, state["mutationCount"])
                self.assertEqual("block", stop_decision({"session_id": session}, self.root)["decision"])

    def test_non_bash_and_bounded_input(self):
        for tool in ("PowerShell", "cmd", "unknown"):
            self.assertFalse(is_read_only_observation(QUERIES[0], tool))
        for command in ("", "cat " + "a" * 4096, "pwd;" * 17 + "pwd", "cat " + "a " * 130,
                        "cat review.py\0", "cat review.py\x01"):
            self.assertFalse(is_read_only_observation(command, "Bash"))

    def test_quoted_or_escaped_glob_characters_stay_literal(self):
        for word in ("'*'", '"*"', r'\*', "'?'", r'\?', "'[a-z]'", r'\[a-z]',
                     '"prefix"\\*'):
            with self.subTest(word=word):
                self.assertTrue(is_read_only_observation(f'sed -n "1p" {word}', "Bash"))
        self.assertTrue(is_read_only_observation("cat review.py | tr -s '[:space:]'", "Bash"))

    def test_no_native_permission_autoapproval(self):
        for command in QUERIES + UNKNOWN:
            with self.subTest(command=command):
                for event in ("PermissionRequest", "PreToolUse"):
                    payload = self.event(command)
                    payload["hook_event_name"] = event
                    self.assertIsNone(safe_permission(payload, self.root))


if __name__ == "__main__":
    unittest.main()
