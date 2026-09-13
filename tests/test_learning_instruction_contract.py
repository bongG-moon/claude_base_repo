"""Keep memory instructions aligned with milestone learning and real CLI syntax."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent.cli import build_parser


class LearningInstructionContractTests(unittest.TestCase):
    def text(self, name):
        return (ROOT / "company-agent-plugin" / "skills" / name).read_text(encoding="utf-8")

    def test_memory_and_learning_agree_on_milestone_boundary(self):
        memory = self.text("personal-memory/SKILL.md")
        learning = self.text("self-learning/SKILL.md")
        self.assertIn("ordinary correction during unfinished work", memory.lower())
        self.assertIn("not an immediate-memory request", memory)
        self.assertIn("Ordinary\ncorrections during unfinished work use staging", learning)
        self.assertIn("explicit durable-memory request", memory.lower())
        self.assertNotIn("or corrects an interaction preference", memory)

    def test_repeated_choice_requires_independent_work_not_turns(self):
        schema = self.text("self-learning/references/review-schema.md")
        self.assertIn("independent completed work units", schema)
        self.assertIn("unit are not independent evidence", schema)
        self.assertNotIn("need evidence on separate user turns", schema)

    def test_search_example_matches_actual_parser(self):
        args = build_parser().parse_args(["memory", "search", "sample", "--state-root", "state"])
        self.assertEqual("sample", args.query)
        self.assertEqual("state", args.state_root)
        self.assertIn('memory search "<query>" --state-root "<stateRoot>"', self.text("personal-memory/SKILL.md"))

    def test_permission_failure_report_is_operation_specific(self):
        memory = self.text("personal-memory/SKILL.md")
        self.assertIn("If search is denied", memory)
        self.assertIn("If upsert is denied", memory)
        self.assertIn("editing the memory files directly", memory)

    def test_memory_spec_has_a_scoped_write_path_not_shell_fallback(self):
        memory = self.text("personal-memory/SKILL.md")
        self.assertIn("<stateRoot>/tmp/memory-<unique-id>.json", memory)
        self.assertIn("Use Write", memory)
        self.assertIn("shell redirection", memory)

    def test_real_work_feedback_guards_and_checkpoint_order(self):
        learning = self.text("self-learning/SKILL.md")
        self.assertIn("BEFORE writing/submitting the review spec", learning)
        html = self.text("html-report/SKILL.md")
        self.assertIn("Read", html)
        main = self.text("company-agent/SKILL.md")
        self.assertIn("file exists is not a content check", main)
        self.assertIn("Approval", (ROOT / "company-agent-plugin" / "scripts" / "company_agent" / "native_runtime.py").read_text(encoding="utf-8"))
        self.assertIn("Do not mark an unexecuted check `fail`", main)


if __name__ == "__main__":
    unittest.main()
