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
            "personal-memory", "presentation", "project-harness", "self-learning",
            "platform-mcp-builder",
            "excel-to-pipeline", "web-interface", "website-rebuild", "work-context-catalog",
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
                    self.assertIn(reference, source)
                    target = (SKILLS / parent).parent.joinpath(reference).resolve()
                    self.assertTrue(target.is_relative_to(PLUGIN.resolve()))
                    self.assertTrue(target.is_file())
                    self.assertNotIn(f"@{reference}", source)
        self.assertRegex(self.read("asset-factory/SKILL.md"), r"해당 흐름 하나|필요한 자료")
        self.assertRegex(self.read("personal-knowledge/SKILL.md"), r"조회만.*(?:읽지|불필요)")
        self.assertRegex(self.read("karpathy-guidelines/SKILL.md"), r"일반 기능.*불필요")

    def test_context_budget_and_no_blanket_import(self):
        main = self.read("company-agent/SKILL.md")
        self.assertLessEqual(len(main.splitlines()), 180)
        for name in ("authoring.md", "windows-setup.md", "term-quality.md", "evidence-diagnosis.md"):
            self.assertNotIn(name, main)
        for relative in (
            "asset-factory/references/authoring.md", "asset-factory/references/windows-setup.md",
            "personal-knowledge/references/term-quality.md", "karpathy-guidelines/references/evidence-diagnosis.md",
        ):
            limit = 80 if relative.endswith('/authoring.md') else 40
            self.assertLessEqual(len(self.read(relative).splitlines()), limit)
            self.assertLessEqual(len(self.read(relative)), 4000)
        self.assertNotIn("ponytail", (PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))
        self.assertNotIn("i-have-adhd", (PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))

    def test_core_workflows_limit_loaded_text_not_only_line_count(self):
        # Long paragraphs formerly met 180 lines while repeating startup work.
        for name, limit in (("company-agent", 6500), ("presentation", 4500), ("html-report", 4500)):
            with self.subTest(name=name):
                text = self.read(f"{name}/SKILL.md")
                self.assertLessEqual(len(text), limit)
                self.assertNotIn('Read `../company-agent/references/business-protection.md` first', text)
                self.assertIn('cliCommand', text)
        for path in SKILLS.glob('*/SKILL.md'):
            self.assertLessEqual(len(path.read_text(encoding='utf-8').splitlines()), 180, path)
            self.assertLessEqual(len(path.read_text(encoding='utf-8')), 6500, path)

    def test_drafting_references_do_not_restart_choice_or_discovery(self):
        ppt = self.read('presentation/references/design-and-quality.md')
        html = self.read('html-report/references/design-and-numbers.md')
        self.assertNotIn('현재 Skill 목록의 출처 우선순위를 확인', ppt)
        self.assertNotIn('질문 전 `business html-choices', html)
        self.assertIn('질문·Skill 선택·런타임 탐색을 다시 시작', ppt)
        self.assertIn('질문/런타임/스킬 탐색을', html)
        self.assertNotIn('현재 목록에서 관련 디자인 스킬', self.read('presentation/references/native-layout.md'))

    def test_conditional_ppt_choices_reference_matches_live_schema(self):
        import json
        import sys
        sys.path.insert(0, str(PLUGIN / 'scripts'))
        from company_agent.ppt_workflow import choices
        text = self.read('presentation/references/choices.md')
        sample = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
        result = choices(sample)
        self.assertEqual('design_preview', result['stage'])
        self.assertEqual('prepare_full_job', result['nextAction'])
        self.assertFalse(result['waitForUser'])
        self.assertEqual(sample['slideCount'], result['contentRequirement']['requiredCount'])
        for field in ('htmlSource', 'designReview', 'workFile/jobPath', 'allowedValues/expected'):
            self.assertIn(field, text)

    def test_result_style_keeps_completeness_and_uncertainty(self):
        main = self.read("company-agent/SKILL.md")
        # These are explicit authoring contracts, not evidence that a model
        # follows them. Runtime selection and execution use scenario tests.
        for pattern in (r"요청한 항목과 수량.*보존", r"상세 설명 요청.*답",
                        r"실패 원인.*임의로.*않", r"매번 계획.*반복하지",
                        r"명시적 기억 저장.*personal-memory",
                        r"기록 성공/변경 없음.*조용히"):
            self.assertRegex(main, pattern)

    def test_authoring_uses_existing_factory_and_windows_security(self):
        import json
        guide = self.read("asset-factory/references/authoring.md")
        spec = json.loads(re.search(r'```json\n(.*?)\n```', guide, re.S).group(1))
        self.assertEqual('skill', spec['type'])
        self.assertEqual({'type', 'name', 'description', 'instructions'}, set(spec))
        self.assertTrue(spec['instructions'])
        self.assertIn('references/reference-1.md', guide)
        self.assertRegex(guide, r'새 Stop 후크.*붙이지')
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
        self.assertRegex(adapter, r'원래 결함.*재현/검사')
        self.assertRegex(adapter, r'기대 동작.*약하게.*않')
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
