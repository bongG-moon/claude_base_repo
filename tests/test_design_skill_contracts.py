"""Ensure progressive skill guidance points to real files and executable CLI syntax."""
import argparse
from pathlib import Path
import re
import shlex
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business


class DesignSkillContracts(unittest.TestCase):
    def test_ppt_reference_inputs_do_not_compete_with_html_output(self):
        from company_agent.skill_task_context import task_candidates
        for base in ('company-agent-plugin/skills', 'standalone-skills'):
            items = []
            for name in ('html-report', 'presentation'):
                entry = ROOT / base / name / 'SKILL.md'
                description = re.search(r'^description: (.+)$', entry.read_text(encoding='utf-8'), re.M).group(1)
                items.append({'id': name, 'name': name, 'description': description,
                              'source': 'company', 'path': str(entry), 'invocation': 'company-agent:' + name})
            for prompt, expected in (('HTML 보고서 만들어줘', 'html-report'), ('PPT 발표자료 만들어줘', 'presentation'),
                                     ('현재 작업 흐름을 그림으로 설명해줘', 'html-report'),
                                     ('업무 흐름을 다이어그램으로 정리해줘', 'html-report')):
                with self.subTest(base=base, prompt=prompt):
                    result = task_candidates({'complete': True, 'skills': items}, prompt)
                    names = [row['name'] for group in result['groups'] for row in group['candidates']]
                    self.assertEqual([expected], names)

    def test_entry_reference_paths_exist(self):
        for base in ('company-agent-plugin/skills', 'standalone-skills'):
            for name in ('html-report', 'presentation', 'web-interface', 'website-rebuild'):
                entry = ROOT / base / name / 'SKILL.md'
                source = entry.read_text(encoding='utf-8')
                references = re.findall(r'`((?:\.\./[^`/]+/references/|references/)[^`]+\.md)`', source)
                # Workflow references resolve in source. Package-wide license
                # paths are checked after export by the package contract tests.
                for relative in references:
                    with self.subTest(entry=str(entry), reference=relative):
                        target = (entry.parent / relative).resolve()
                        self.assertTrue(target.is_relative_to(ROOT.resolve()))
                        self.assertTrue(target.is_file(),str(target))

    def test_documented_business_commands_parse_without_runtime_execution(self):
        parser = argparse.ArgumentParser()
        business.register(parser.add_subparsers(dest='command', required=True))
        paths = [ROOT / 'company-agent-plugin/skills' / name / 'SKILL.md'
                 for name in ('html-report', 'presentation')]
        paths.append(ROOT / 'company-agent-plugin/skills/html-report/references/choices.md')
        checked = set()
        for path in paths:
            source = path.read_text(encoding='utf-8')
            for command in re.findall(r'`(business [^`\n]+)`', source):
                # Square brackets document optional arguments, not shell syntax.
                variants = (re.sub(r'\[[^\]]+\]', '', command), command.replace('[', '').replace(']', ''))
                for variant in variants:
                    with self.subTest(path=str(path), command=variant):
                        args = parser.parse_args(shlex.split(variant))
                        checked.add(args.business_action)
        self.assertTrue({'artifact-start', 'artifact-publish', 'html', 'html-choices',
                         'html-template', 'ppt', 'ppt-choices', 'ppt-design-preview'} <= checked)


if __name__ == '__main__':
    unittest.main()
