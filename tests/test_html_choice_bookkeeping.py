"""Choice preparation is not a report change; existing obligations remain."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "company-agent-plugin/scripts"))
from company_agent.state import begin_turn, load_session, record_activity, stop_decision


class HtmlChoiceBookkeepingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tmp").mkdir()
        self.path = self.root / "tmp/html-choices-report.json"
        begin_turn("choices", "MEDIUM", False, [], self.root)

    def write(self, content, path=None):
        return record_activity({"session_id": "choices", "hook_event_name": "PostToolUse",
                                "tool_name": "Write", "tool_input": {
                                    "file_path": str(path or self.path), "content": content}}, self.root)

    def test_selection_steps_are_silent_and_keep_no_business_content(self):
        for spec in ({}, {"designMenu": "additional"},
                     {"designMenu": "additional", "style": "neumorphism", "length": "detailed", "mode": "scroll"},
                     {"designMenu": "template", "htmlTemplate": {"path": str(self.root / "form.html"), "sha256": "a" * 64}}):
            state = self.write(json.dumps(spec))
            self.assertEqual(0, state["mutationCount"])
            self.assertEqual([], state["work"]["pending"])
            self.assertIsNone(state["verification"])
            self.assertEqual({}, stop_decision({"session_id": "choices"}, self.root))

    def test_report_content_invalid_values_and_other_paths_are_not_exempt(self):
        cases = [('{"sections": []}', self.path), ('{"title":"Report"}', self.path),
                 ('{"mode":"arbitrary"}', self.path), ('{"style":[]}', self.path),
                 ('[]', self.path), ('not json', self.path),
                 ('{"htmlTemplate":{"path":"relative.html","sha256":"abc"}}', self.path),
                 ('{}', self.root / "tmp/job.json"), ('{}', self.root / "html-choices-report.json"),
                 ('{}', self.root / "tmp/html-choices-report.html")]
        count = 0
        for content, path in cases:
            with self.subTest(content=content, path=path):
                count += 1
                self.assertEqual(count, self.write(content, path)["mutationCount"])
        self.assertEqual("block", stop_decision({"session_id": "choices"}, self.root)["decision"])

    def test_new_choices_do_not_clear_previous_unverified_report(self):
        self.write("<html>actual report</html>", self.root / "report.html")
        begin_turn("choices", "MEDIUM", False, [], self.root)
        self.write('{"style":"minimalism"}')
        self.assertEqual(1, load_session("choices", self.root)["mutationCount"])
        self.assertEqual("block", stop_decision({"session_id": "choices"}, self.root)["decision"])


if __name__ == "__main__":
    unittest.main()
