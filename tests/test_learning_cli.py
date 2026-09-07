from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent.paths import atomic_write_json, atomic_write_text
from company_agent.state import begin_turn, load_session, record_activity, stop_decision


class LearningCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "개인 학습 — 저장소"
        self.env = {**os.environ, "COMPANY_AGENT_USER_STATE": str(self.state),
                    "PYTHONIOENCODING": "cp949:strict", "PYTHONUTF8": "0"}
        self.session = "learning-cli-user"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *arguments):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "harness_cli.py"), *arguments],
                                env=self.env, cwd=ROOT, capture_output=True, timeout=30)
        stdout = result.stdout.decode("ascii")
        stderr = result.stderr.decode("ascii")
        return result.returncode, json.loads(stdout or stderr), stderr

    def submit(self, turn, spec):
        file = self.state / "tmp" / f"learning-review-{turn}.json"
        atomic_write_json(file, spec)
        record_activity({"session_id": self.session, "tool_name": "Write",
                         "tool_input": {"file_path": str(file), "content": "PRIVATE-STAGING-NOT-PERSISTED"}}, self.state)
        return self.cli("learning", "review", "--session", self.session, "--turn", turn, "--spec", str(file))

    @staticmethod
    def spec():
        return {"schemaVersion": 1, "taskType": "weekly-report", "outcome": "unknown", "summary": "보고 형식의 사용자 선택을 관찰함",
                "observations": [{"kind": "preference", "key": "team-report-order", "signal": "repeated_choice",
                                  "title": "팀 보고의 순서", "body": "팀 보고는 결정할 내용을 먼저 설명한다."}], "evaluations": []}

    def test_two_real_cli_turns_activate_and_next_route_retrieves_without_remember(self):
        for number in range(2):
            state = begin_turn(self.session, "SMALL", False, [], self.state)
            self.assertEqual("block", stop_decision({"session_id": self.session}, self.state)["decision"])
            code, result, stderr = self.submit(state["turnId"], self.spec())
            self.assertEqual(0, code, stderr)
            self.assertEqual("accepted", result["status"])
            self.assertEqual("removed", result["stagingCleanup"])
            self.assertFalse((self.state / "tmp" / f"learning-review-{state['turnId']}.json").exists())
            self.assertEqual("complete", load_session(self.session, self.state)["learningStatus"])
            self.assertEqual({}, stop_decision({"session_id": self.session}, self.state))
            if number == 0:
                self.assertEqual([], list((self.state / "memory" / "items").glob("learning.*.md")))
        files = list((self.state / "memory" / "items").glob("learning.*.md"))
        self.assertEqual(1, len(files))
        env = {**self.env, "PYTHONIOENCODING": "utf-8"}
        route = subprocess.run([sys.executable, "-B", str(SCRIPTS / "model_route_hook.py")], env=env,
                               input=json.dumps({"session_id": self.session, "prompt": "팀 보고를 정리해줘 RAW-USER-SENTINEL"}, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, timeout=30, cwd=ROOT)
        self.assertEqual(0, route.returncode, route.stderr)
        text = route.stdout.decode("utf-8")
        envelope = json.loads(json.loads(text)["hookSpecificOutput"]["additionalContext"])
        self.assertIn("결정할 내용을 먼저", envelope["company_agent_personal_memory_context"])
        self.assertNotIn("RAW-USER-SENTINEL", text)
        self.assertNotIn("RAW-USER-SENTINEL", (self.state / "learning" / "state.json").read_text(encoding="utf-8"))

    def test_status_read_only_and_pause_resume_preserve_memory(self):
        code, result, stderr = self.cli("learning", "status")
        self.assertEqual(0, code, stderr)
        self.assertTrue(result["learning"]["enabled"])
        self.assertFalse(self.state.exists())
        for operation, expected in (("pause", False), ("resume", True)):
            code, result, stderr = self.cli("learning", operation)
            self.assertEqual(0, code, stderr)
            self.assertEqual(expected, result["enabled"])
            self.assertEqual(expected, self.cli("learning", "status")[1]["learning"]["enabled"])

    def test_cli_rejects_foreign_spec_and_stale_turn_without_learning_writes(self):
        state = begin_turn(self.session, "SMALL", False, [], self.state)
        foreign = Path(self.temp.name) / "foreign.json"
        atomic_write_json(foreign, self.spec())
        result = self.cli("learning", "review", "--session", self.session, "--turn", state["turnId"], "--spec", str(foreign))
        self.assertEqual(1, result[0])
        self.assertFalse((self.state / "learning" / "state.json").exists())
        self.assertTrue(foreign.exists())
        begin_turn(self.session, "SMALL", False, [], self.state)
        self.assertEqual(1, self.submit(state["turnId"], self.spec())[0])
        self.assertFalse((self.state / "learning" / "state.json").exists())

    def test_cli_rejects_raw_review_and_keeps_review_pending(self):
        state = begin_turn(self.session, "SMALL", False, [], self.state)
        spec = self.spec()
        spec["transcript"] = "do not persist"
        code, _, _ = self.submit(state["turnId"], spec)
        self.assertEqual(1, code)
        self.assertEqual("pending", load_session(self.session, self.state)["learningStatus"])
        self.assertFalse((self.state / "learning" / "state.json").exists())
        self.assertFalse((self.state / "tmp" / f"learning-review-{state['turnId']}.json").exists())

    def test_cleanup_preserves_file_edited_during_review(self):
        from company_agent.cli import cmd_learning
        from argparse import Namespace
        state = begin_turn(self.session, "SMALL", False, [], self.state)
        file = self.state / "tmp" / f"learning-review-{state['turnId']}.json"
        atomic_write_json(file, self.spec())
        changed = {"userEdit": "Keep the user's newer staging content."}

        def review(*_):
            atomic_write_json(file, changed)
            return {"status": "accepted"}

        args = Namespace(learning_command="review", state_root=str(self.state), session=self.session,
                         turn=state["turnId"], spec=str(file))
        with patch("company_agent.learning.submit_review", side_effect=review), patch("company_agent.cli._print_json") as output:
            self.assertEqual(0, cmd_learning(args))
            self.assertEqual("retained_changed", output.call_args.args[0]["stagingCleanup"])
        self.assertEqual(changed, json.loads(file.read_text(encoding="utf-8")))

    def test_real_cli_skill_learning_next_use_assessment_and_targeted_rollback(self):
        skill = self.state / "personal-root" / ".claude" / "skills" / "weekly-report" / "SKILL.md"
        original = "---\nname: weekly-report\ndescription: Weekly report workflow\n---\n\n# Work\nORIGINAL-PERSONAL-CONTENT-MUST-STAY.\n"
        atomic_write_text(skill, original)
        untouched = self.state / "personal-root" / ".claude" / "skills" / "other-work" / "SKILL.md"
        atomic_write_text(untouched, "OTHER-PERSONAL-CONTENT-MUST-STAY\n")
        original_bytes, untouched_bytes = skill.read_bytes(), untouched.read_bytes()

        def observe(tool, inputs, *, failed=False):
            # Exercise the actual hook entry point, including its legacy-Windows
            # byte boundary. The payload simulates Claude's documented tool event.
            payload = {"session_id": self.session, "tool_name": tool, "tool_input": inputs,
                       "hook_event_name": "PostToolUseFailure" if failed else "PostToolUse",
                       "tool_response": "RAW-TOOL-OUTPUT-MUST-NOT-PERSIST"}
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "activity_hook.py")],
                                    input=json.dumps(payload).encode("ascii"), env=self.env,
                                    capture_output=True, timeout=30, cwd=ROOT)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual({}, json.loads(result.stdout))

        def verify(status):
            code, result, stderr = self.cli("session", "verify", "--session", self.session,
                                            "--status", status, "--summary", "actual-check-result")
            self.assertEqual(0 if status == "pass" else 1, code, stderr)
            self.assertEqual(status, result["verification"]["status"])
            command = (f'"{sys.executable}" -B "{SCRIPTS / "harness_cli.py"}" session verify '
                       f'--session "{self.session}" --status {status} --summary "actual-check-result"')
            observe("Bash", {"command": command}, failed=status == "fail")
            self.assertEqual(status, load_session(self.session, self.state)["verification"]["status"])

        first = begin_turn(self.session, "MEDIUM", True, [], self.state)
        observe("Read", {"file_path": str(skill)})
        observe("Write", {"file_path": str(self.state.parent / "business-report.md"),
                          "content": "RAW-BUSINESS-CONTENT-MUST-NOT-PERSIST"}, failed=True)
        verify("pass")
        self.assertEqual("block", stop_decision({"session_id": self.session}, self.state)["decision"])
        spec = self.spec()
        spec.update({"outcome": "success", "summary": "보고서 집계 기준 오류를 수정하고 결과를 검증함"})
        preference = dict(spec["observations"][0], signal="explicit_correction")
        spec["observations"] = [
            {"kind": "skill", "key": "check-report-grain", "signal": "verified_fix",
             "title": "집계 기준 확인", "body": "집계 전에 기간과 기준 단위를 확인한다.",
             "skillName": "weekly-report"}, preference,
        ]
        code, learned, stderr = self.submit(first["turnId"], spec)
        self.assertEqual(0, code, stderr)
        self.assertEqual("accepted", learned["status"])
        skill_change = next(item for item in learned["changes"] if item["kind"] == "skill")
        preference_change = next(item for item in learned["changes"] if item["kind"] == "preference")
        self.assertEqual("active", skill_change["status"])
        self.assertEqual("active", preference_change["status"])
        improved = skill.read_bytes()
        improved_hash = hashlib.sha256(improved).hexdigest()
        self.assertNotEqual(original_bytes, improved)
        self.assertTrue(improved.startswith(original_bytes))
        self.assertIn("집계 전에 기간과 기준 단위를 확인한다.", improved.decode("utf-8"))
        self.assertEqual({}, stop_decision({"session_id": self.session}, self.state))

        for verdict in ("helpful", "harmful"):
            current = begin_turn(self.session, "MEDIUM", False, [], self.state)
            self.assertNotEqual(first["turnId"], current["turnId"])
            observe("Read", {"file_path": str(skill)})
            code, status, stderr = self.cli("learning", "status", "--session", self.session)
            self.assertEqual(0, code, stderr)
            captured = status["session"]["usedSkills"]
            self.assertEqual([{"name": "weekly-report", "path": str(skill), "sha256": improved_hash}], captured)
            match = next(item for item in status["learning"]["relevantChanges"] if item["id"] == skill_change["id"])
            self.assertEqual("weekly-report", match["skillName"])
            self.assertEqual(improved_hash, match["sha256"])
            self.assertEqual("active", match["status"])
            if verdict == "harmful":
                observe("mcp__corp-db-read__select", {"query": "RAW-QUERY-MUST-NOT-PERSIST"}, failed=True)
            verify("pass" if verdict == "helpful" else "fail")
            evaluation = self.spec()
            evaluation.update({"outcome": "success" if verdict == "helpful" else "failure",
                               "summary": "개선된 보고 절차를 적용한 결과와 검증 근거를 검토함",
                               "observations": [],
                               "evaluations": [{"skillName": "weekly-report", "sha256": improved_hash,
                                                "verdict": verdict}]})
            code, assessed, stderr = self.submit(current["turnId"], evaluation)
            self.assertEqual(0, code, stderr)
            self.assertEqual("accepted", assessed["status"])
            assessment, = assessed["assessments"]
            self.assertEqual(skill_change["id"], assessment["changeId"])
            self.assertEqual(verdict, assessment["verdict"])
            self.assertEqual(1, assessment["baselineSamples"])
            self.assertEqual(1 if verdict == "helpful" else 2, assessment["afterSamples"])
            self.assertEqual("insufficient_data", assessment["confidence"])
            self.assertFalse(assessment["causalClaim"])
            self.assertEqual("complete", load_session(self.session, self.state)["learningStatus"])
            if verdict == "helpful":
                self.assertEqual(improved, skill.read_bytes())
                self.assertEqual(1, assessment["baselineAverageFailures"])
                self.assertEqual(0, assessment["afterAverageFailures"])
            else:
                self.assertEqual(skill_change["id"], assessment["rollback"]["id"])
                self.assertEqual("rolled_back", assessment["rollback"]["status"])
                self.assertTrue(assessment["rollback"]["changed"])

        self.assertEqual(original_bytes, skill.read_bytes())
        self.assertEqual(untouched_bytes, untouched.read_bytes())
        status = self.cli("learning", "status")[1]["learning"]
        changes = {item["id"]: item for item in status["recentChanges"]}
        self.assertEqual("rolled_back", changes[skill_change["id"]]["status"])
        self.assertEqual("active", changes[preference_change["id"]]["status"])
        ledger = (self.state / "learning" / "state.json").read_text(encoding="utf-8")
        self.assertNotIn("RAW-", ledger)
        self.assertNotIn("ORIGINAL-PERSONAL-CONTENT-MUST-STAY", ledger)


if __name__ == "__main__":
    unittest.main()
