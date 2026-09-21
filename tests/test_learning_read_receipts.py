"""Learning must use the same actual body evidence as Skill preparation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"))
from company_agent.paths import atomic_write_text
from company_agent.state import begin_turn, load_session, record_activity


class LearningReadReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "한글 상태"
        self.sid = "learning-body"
        self.file = self.root / "personal-root/.claude/skills/report/SKILL.md"
        self.body = "---\nname: report\ndescription: Private report workflow\n---\n# Workflow\nPRIVATE-BODY\n"
        atomic_write_text(self.file, self.body)
        begin_turn(self.sid, "MEDIUM", False, [], self.root)

    def read(self, start=1, end=None, **overrides):
        lines = self.file.read_text(encoding="utf-8").splitlines()
        content = "\n".join(lines[start - 1:end])
        payload = {"session_id": self.sid, "hook_event_name": "PostToolUse", "tool_name": "Read",
                   "tool_input": {"file_path": str(self.file), "offset": start, "limit": len(content.splitlines())},
                   "tool_response": {"file": {"content": content, "startLine": start}}}
        payload.update(overrides)
        return record_activity(payload, self.root)

    def test_first_line_and_disk_hash_do_not_claim_full_exposure(self):
        state = self.read(end=1)
        self.assertEqual([], state["usedSkills"])
        self.assertEqual([], state["work"]["usedSkills"])
        self.assertNotIn("PRIVATE-BODY", json.dumps(state))

    def test_pages_require_every_matching_line_and_keep_only_hashes_ranges(self):
        self.read(end=2)
        self.assertEqual([], self.read(start=4)["usedSkills"])
        state = self.read(start=3, end=3)
        self.assertEqual([{"name": "report", "path": str(self.file),
                           "sha256": hashlib.sha256(self.body.encode()).hexdigest()}], state["usedSkills"])
        self.assertEqual(state["usedSkills"], state["work"]["usedSkills"])
        self.assertNotIn("PRIVATE-BODY", json.dumps(state))

    def test_missing_wrong_failed_and_worker_responses_are_not_evidence(self):
        for overrides in ({"tool_response": None},
                          {"tool_response": "Successfully read"},
                          {"tool_response": {"file": {"content": "invented", "startLine": 1}}},
                          {"tool_response": {"isError": True, "file": {"content": self.body, "startLine": 1}}},
                          {"hook_event_name": "PostToolUseFailure"},
                          {"agent_id": "another-worker"}):
            with self.subTest(overrides=overrides):
                self.assertEqual([], self.read(**overrides)["usedSkills"])

    def test_changed_body_cannot_reuse_old_partial_ranges(self):
        self.read(end=2)
        atomic_write_text(self.file, self.body.replace("name: report", "name: report-updated"))
        self.assertEqual([], self.read(start=3)["usedSkills"])
        self.assertEqual(1, len(self.read(end=2)["usedSkills"]))

    def test_new_turn_resets_partial_ranges_without_discarding_full_work_evidence(self):
        self.read(end=2)
        begin_turn(self.sid, "MEDIUM", False, [], self.root)
        self.assertEqual([], self.read(start=3)["usedSkills"])
        self.read(end=2)
        begin_turn(self.sid, "MEDIUM", False, [], self.root)
        state = load_session(self.sid, self.root)
        self.assertEqual({}, state["learningReadReceipts"])
        self.assertEqual(1, len(state["work"]["usedSkills"]))

    def test_partial_load_cannot_authorize_personal_skill_learning(self):
        from company_agent.learning import submit_review
        from company_agent.work import checkpoint
        state = self.read(end=1)
        checkpoint(self.root, self.sid, state["turnId"], "complete", learn=True)
        result = submit_review(self.root, self.sid, state["turnId"], {
            "schemaVersion": 1, "taskType": "report", "outcome": "success", "summary": "보고 절차의 수정 요청을 확인함",
            "observations": [{"kind": "skill", "key": "format", "signal": "explicit_correction",
                              "skillName": "report", "title": "보고 형식", "body": "결론을 먼저 정리한다."}],
            "evaluations": []})
        self.assertEqual("deferred", result["changes"][0]["status"])
        self.assertEqual(self.body, self.file.read_text(encoding="utf-8"))

    def test_actual_full_reads_support_a_b_a_skill_correction_in_one_work(self):
        from company_agent.learning import submit_review
        from company_agent.work import checkpoint
        work_ids = set()
        for instruction in ("Use Korean headings.", "Use English headings.", "Use Korean headings."):
            begin_turn(self.sid, "MEDIUM", False, [], self.root)
            state = self.read()
            work_ids.add(state["work"]["id"])
            checkpoint(self.root, self.sid, state["turnId"], "complete", learn=True)
            result = submit_review(self.root, self.sid, state["turnId"], {
                "schemaVersion": 1, "taskType": "report", "outcome": "success", "summary": "보고서 제목 언어를 교정함",
                "observations": [{"kind": "skill", "key": "language", "signal": "explicit_correction",
                                  "skillName": "report", "title": "제목 언어", "body": instruction}],
                "evaluations": []})
            self.assertEqual("active", result["changes"][0]["status"])
            text = self.file.read_text(encoding="utf-8")
            self.assertIn(instruction, text)
            self.assertEqual(1, text.count("- 제목 언어:"))
        self.assertEqual(1, len(work_ids))


if __name__ == "__main__":
    unittest.main()
