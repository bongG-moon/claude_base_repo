"""Offline instruction contracts, not a substitute for real model behavior tests."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
SKILLS = PLUGIN / "skills"


class LeanSkillContractTests(unittest.TestCase):
    def read(self, relative):
        return (SKILLS / relative).read_text(encoding="utf-8")

    def test_only_expected_skill_names_and_no_upstream_wrappers(self):
        names = []
        for file in SKILLS.glob("*/SKILL.md"):
            names.append(re.search(r"^name: (.+)$", file.read_text(encoding="utf-8"), re.M).group(1))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), {
            "company-agent", "asset-factory", "file-organizer", "html-report",
            "karpathy-guidelines", "outlook-assistant", "personal-knowledge",
            "personal-memory", "presentation", "project-harness", "self-learning", "office-reader",
            "platform-mcp-builder",
        })

    def test_conditional_reference_links_exist_inside_plugin(self):
        links = {
            "asset-factory/SKILL.md": ["references/authoring.md", "references/windows-setup.md",
                                       "references/platform-tools.md", "references/legacy-assets.md",
                                       "../platform-mcp-builder/references/platform-contract.md"],
            "platform-mcp-builder/SKILL.md": ["../asset-factory/SKILL.md", "references/platform-contract.md"],
            "project-harness/SKILL.md": ["../asset-factory/references/authoring.md"],
            "personal-knowledge/SKILL.md": ["references/term-quality.md"],
            "karpathy-guidelines/SKILL.md": ["references/evidence-diagnosis.md"],
        }
        for parent, references in links.items():
            source = self.read(parent)
            for reference in references:
                with self.subTest(parent=parent, reference=reference):
                    self.assertIn(f"`{reference}`", source)
                    target = (SKILLS / parent).parent.joinpath(reference).resolve()
                    self.assertTrue(target.is_relative_to(PLUGIN.resolve()))
                    self.assertTrue(target.is_file())
                    self.assertNotIn(f"@{reference}", source)
        self.assertIn("other tasks do not load them", self.read("asset-factory/SKILL.md"))
        self.assertIn("Ordinary lookup does not load", self.read("personal-knowledge/SKILL.md"))
        self.assertIn("do not load it for ordinary feature work", self.read("karpathy-guidelines/SKILL.md"))

    def test_context_budget_and_no_blanket_import(self):
        main = self.read("company-agent/SKILL.md")
        self.assertLessEqual(len(main.splitlines()), 180)
        for name in ("authoring.md", "windows-setup.md", "term-quality.md", "evidence-diagnosis.md"):
            self.assertNotIn(name, main)
        for relative in (
            "asset-factory/references/authoring.md", "asset-factory/references/windows-setup.md",
            "personal-knowledge/references/term-quality.md", "karpathy-guidelines/references/evidence-diagnosis.md",
        ):
            self.assertLessEqual(len(self.read(relative).splitlines()), 40)
        self.assertNotIn("ponytail", (PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))
        self.assertNotIn("i-have-adhd", (PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))

    def test_result_style_keeps_completeness_and_uncertainty(self):
        main = self.read("company-agent/SKILL.md")
        for text in ("preserve all requested items and exact counts", "Give full detail when requested",
                     "never guess an error's cause", "without inventing a next task",
                     "do not repeat a plan every turn", "not invented precision",
                     "explicit durable-memory requests still use personal-memory",
                     "Routine learning success/no-change stays silent"):
            self.assertIn(text, main)

    def test_authoring_uses_existing_factory_and_windows_security(self):
        guide = self.read("asset-factory/references/authoring.md")
        for text in ("one primary job", "observable completion criteria", "No second Stop gate",
                     "references/reference-1.md", "not invent frontmatter or JSON fields"):
            self.assertIn(text, guide)
        wizard = self.read("asset-factory/references/windows-setup.md")
        for text in ("explicitly requested", "Bash, WSL, public downloads", "hidden",
                     "rejected by the personal asset factory", "isolated fixture"):
            self.assertIn(text, wizard)

    def test_knowledge_and_diagnosis_do_not_bypass_ownership_or_learning(self):
        knowledge = self.read("personal-knowledge/references/term-quality.md")
        for text in ("No direct edits", "corporate base", "not silently save",
                     "hypothetical", "preference feedback remains staged"):
            self.assertIn(text, knowledge)
        self.assertIn("company_agent_runtime.cliCommand", self.read("personal-knowledge/SKILL.md"))
        diagnosis = self.read("karpathy-guidelines/references/evidence-diagnosis.md")
        for text in ("diagnosis-only request remains read-only", "current retry budget",
                     "without workaround", "smallest missing evidence", "meaningful-milestone"):
            self.assertIn(text, diagnosis)

    def test_provenance_is_shipped_not_active_guidance(self):
        notice = (PLUGIN / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for text in ("Matt Pocock", "DietrichGebert", "Ayoub Ghriss", "MIT License",
                     "3cca18b368ae95cdbdebbff572ccafa662551015",
                     "356918eba965ee1eac64bd3a7f0dd02108350de5",
                     "6f1f982d0a47c65899af3c5a7450b7098bc65325"):
            self.assertIn(text, notice)

    def test_current_evidence_adaptation_does_not_add_another_workflow(self):
        adapter = self.read('karpathy-guidelines/SKILL.md')
        completion = self.read('company-agent/references/completion.md')
        self.assertIn('check detects the original defect', adapter)
        self.assertIn('Do not weaken the expected behavior', adapter)
        self.assertIn('after the latest relevant change', completion)
        self.assertIn('failures and skipped checks', completion)
        self.assertIn('requirements it never tests', completion)
        notice = (PLUGIN / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
        self.assertIn('5bf4e78011075bcfc0dc295f0724994cd123ee71', notice)
        self.assertIn('Copyright (c) 2025 Jesse Vincent', notice)
        hooks = (PLUGIN / 'hooks/hooks.json').read_text(encoding='utf-8')
        self.assertNotIn('superpowers', hooks)
        self.assertNotIn('UditAkhourii', hooks)


if __name__ == "__main__":
    unittest.main()
