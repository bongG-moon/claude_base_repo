"""Keep learning instructions aligned with unified submission and real CLI syntax."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin" / "scripts"))
from company_agent.cli import build_parser


class LearningInstructionContractTests(unittest.TestCase):
    def text(self, name):
        return (ROOT / "company-agent-plugin" / "skills" / name).read_text(encoding="utf-8")

    def test_memory_and_learning_agree_on_durable_preference_boundary(self):
        memory = self.text("personal-memory/SKILL.md")
        learning = self.text("self-learning/SKILL.md")
        self.assertIn('Choose by the affected resource', memory)
        self.assertIn('An existing saved fact: keep its exact ID and storageScope', memory)
        self.assertIn('A new project-only durable fact', memory)
        self.assertIn('A one-time or unclear correction', memory)
        self.assertIn('follow it for this task only. Do not save it.', memory)
        self.assertIn("learning submit", memory)
        self.assertIn('same ID and scope, not `learning rollback`', memory)
        self.assertIn("may be submitted while work is active", learning)
        self.assertIn("unclear directions apply only to the current task", learning)
        self.assertIn("explicit durable-memory request", memory.lower())
        self.assertNotIn("or corrects an interaction preference", memory)

    def test_memory_receipt_and_revision_restore_do_not_require_a_stop_ritual(self):
        memory = self.text('personal-memory/SKILL.md')
        for marker in ('persisted-content-verified', 'storageScope', '--expected-revision',
                       '--expected-sha256', 'memory history --id', 'memory restore --id',
                       'never verifies an unfinished report', 'Missing snapshots mean not restored'):
            self.assertIn(marker, memory)
        self.assertNotIn('Read back the generated Markdown', memory)

    def test_unified_submit_is_short_and_not_a_discovery_ritual(self):
        learning = self.text("self-learning/SKILL.md")
        self.assertLessEqual(len(learning.splitlines()), 90)
        for marker in ("learning submit --session", "company_agent_learning.turnId",
                       "<stateRoot>/tmp/learning-review-<turnId>.json",
                       "No status/stage/checkpoint prerequisite", "learning-only Stop continuation",
                       "No submission is not", "provided-to-model"):
            self.assertIn(marker, learning)
        for obsolete in ("learning stage --session", "learning review --session",
                         "work checkpoint --session", "learning status --session"):
            self.assertNotIn(obsolete, learning)

    def test_condensed_runtime_keeps_evidence_trigger_and_no_stop_restart(self):
        source = (ROOT / "company-agent-plugin" / "scripts" / "company_agent" / "native_runtime.py").read_text(encoding="utf-8")
        self.assertIn("검증된 절차 근거가 있을 때만 self-learning의 learning submit 한 번", source)
        self.assertIn("검증된 재사용 근거가 있을 때만 learning submit 한 번", source)
        self.assertEqual(2, source.count("선행 조회·빈 회고·학습용 Stop 재개"))
        self.assertNotIn("학습은 업무 이정표에서만", source)

    def test_schema_keeps_observation_separate_from_application(self):
        schema = self.text("self-learning/references/review-schema.md")
        for marker in ("actually fully", "actual verification pass", "observed failure",
                       "never fabricate", "no_candidates", "never submitting",
                       "only an active change", "not-observable"):
            self.assertIn(marker, schema)

    def test_repeated_choice_requires_independent_work_not_turns(self):
        schema = self.text("self-learning/references/review-schema.md")
        self.assertIn("two independent work units", schema)
        self.assertIn("actual current-turn verification", schema)
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

    def test_real_work_feedback_guards_do_not_require_checkpoint_ritual(self):
        learning = self.text("self-learning/SKILL.md")
        self.assertIn("submitting never declares the business work complete", learning)
        self.assertIn("actual relevant verification", learning)
        html = self.text("html-report/SKILL.md")
        self.assertIn("Read", html)
        main = self.text("company-agent/SKILL.md")
        self.assertIn("file exists is not a content check", main)
        self.assertIn("durable corrections may be submitted during work", main)
        self.assertIn("learning submit, not status/stage/checkpoint", main)
        self.assertNotIn("self-learning staging", main)
        self.assertIn("Approval", (ROOT / "company-agent-plugin" / "scripts" / "company_agent" / "native_runtime.py").read_text(encoding="utf-8"))
        self.assertIn("Do not mark an unexecuted check `fail`", main)


if __name__ == "__main__":
    unittest.main()
