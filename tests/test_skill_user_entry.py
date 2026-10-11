"""Plain Korean execution uses existing skills, not another setup workflow."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent.skill_task_context import named_choices


class SkillUserEntryTests(unittest.TestCase):
    def test_execute_with_natural_language_or_existing_command(self):
        for prompt in ('mumu-pocket-launch 스킬 실행해줘',
                       'mumu-pocket-launch를 실행해줘',
                       '/company-agent:skills mumu-pocket-launch 실행'):
            with self.subTest(prompt=prompt):
                self.assertEqual(['mumu-pocket-launch'], named_choices(prompt))

    def test_edit_list_negation_and_explanation_do_not_run_the_skill(self):
        for prompt in ('mumu-pocket-launch 스킬 수정해줘',
                       'mumu-pocket-launch 스킬의 실행 순서를 바꿔줘',
                       'mumu-pocket-launch 실행하지 마',
                       'mumu-pocket-launch 실행 방법 설명해줘',
                       '/company-agent:skills 목록',
                       'mumu-pocket-launch를 설치해줘'):
            with self.subTest(prompt=prompt):
                self.assertEqual([], named_choices(prompt))

    def test_existing_command_uses_native_load_and_preserves_private_entry(self):
        command = (ROOT / 'company-agent-plugin/commands/skills.md').read_text(encoding='utf-8')
        for term in ('스킬이름 실행', '기존 이름·위치', '파일 복사나 AssetSpec 재생성',
                     '정확한 `Skill` 호출', '자동 이동·복제하지 않습니다',
                     '현재 세션 발견·실제 실행 성공을 주장하지 않습니다', '과거의 승인'):
            self.assertIn(term, command)
        self.assertIn('follow the returned load', command)
        self.assertNotIn('then use Read to read the complete selected', command)

    def test_guides_explain_native_single_source_and_sharing_boundary(self):
        for file in ('USER_GUIDE.md', 'COMPANY_AGENT_HANDBOOK.md', 'ONBOARDING_COURSE.md'):
            text = (ROOT / 'docs' / file).read_text(encoding='utf-8')
            with self.subTest(file=file):
                for term in ('/reload-skills', '.claude/skills', '실제 원본', '공유'):
                    self.assertIn(term, text)
        commands = (ROOT / 'docs/CLAUDE_CODE_COMMANDS.md').read_text(encoding='utf-8')
        self.assertIn('`/스킬이름`', commands)
        self.assertIn('`/reload-skills`', commands)


class InstallPreservationTests(unittest.TestCase):
    def test_other_plugin_repair_is_explicit_opt_in_without_new_prompt(self):
        source = (ROOT / 'deploy/Install-ScopedCompanyAgent.ps1').read_text(encoding='utf-8')
        self.assertIn('[switch] $RepairOtherPluginPython', source)
        guard = source.index('if ($RepairOtherPluginPython) {')
        call = source.index('$pluginRepairs = @(Repair-CompanyAgentPluginPython')
        self.assertLess(guard, call)
        self.assertIn("'RepairOtherPluginPython'", source.split('. (Join-Path $PSScriptRoot')[0])
        self.assertNotIn('Read-Host', source[guard:call])


if __name__ == '__main__':
    unittest.main()
