"""Installed skill/CLI/routing checks, without real Office or model calls."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))
import test_skill_discovery as discovery
from company_agent import business, excel_pipeline_command
from company_agent.cli import build_parser
from company_agent.execution_contract import classify_command, safe_permission
from company_agent.skill_decision import decide_preparation
from company_agent.skill_registry import inventory_skills
from company_agent.skill_task_context import task_candidates

HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


class ExcelRoutingTests(unittest.TestCase):
    def setUp(self):
        fixture = discovery.SkillDiscoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.inventory = inventory_skills(fixture.state, project_root=fixture.project,
                                         plugin_root=PLUGIN, claude_root=fixture.claude)
        self.excel = next(row for row in self.inventory['skills'] if row['name'] == 'excel-to-pipeline')

    def test_structural_work_routes_to_actual_shipped_skill(self):
        for prompt in (
            '@업무.xlsm 수식과 내장 VBA를 분석해서 Python 전처리 코드로 만들어줘',
            '엑셀 여러 표를 분리하고 수식 구조를 분석해줘',
            '이 xlsx 파일의 시트 구조와 수식을 확인해줘',
            '엑셀 함수 구조를 분석해줘',
            '엑셀 수식을 분석해서 Python 전처리 스크립트를 만들어줘',
            'Create a Python preprocessing script from the XLSM VBA formulas',
            'Analyze Excel formulas and multiple tables',
            'Convert XLSM VBA to a Python pipeline',
        ):
            with self.subTest(prompt=prompt):
                hints = task_candidates(self.inventory, prompt)
                decision = decide_preparation(hints, self.inventory['skills'], [])
                self.assertEqual(('load', self.excel['id']), (decision.mode, decision.candidate_id), hints)

    def test_plain_reads_and_unrelated_work_do_not_load_analysis(self):
        for prompt in ('@table.xlsx 내용 읽어줘', '엑셀 열어줘', '이 파일의 이름을 확인해줘',
                       'Chrome에서 페이지를 읽고 표를 확인해줘',
                       'PPT 수식 내용을 읽어줘', 'HTML 보고서 만들어줘',
                       '엑셀 분석 스킬을 만들어줘'):
            with self.subTest(prompt=prompt):
                hints = task_candidates(self.inventory, prompt)
                decision = decide_preparation(hints, self.inventory['skills'], [])
                self.assertNotEqual(self.excel['id'], decision.candidate_id)
                self.assertNotIn(self.excel['id'], hints.get('strongIds', []))

    def test_personal_alternative_keeps_choice(self):
        inventory = copy.deepcopy(self.inventory)
        alternative = dict(self.excel, id='user:excel-alternative', name='custom-excel-workflow',
                           source='user', invocation='custom-excel-workflow')
        inventory['skills'].append(alternative)
        hints = task_candidates(inventory, '엑셀 수식 구조를 분석해줘')
        decision = decide_preparation(hints, inventory['skills'], [])
        self.assertEqual('choose', decision.mode)
        self.assertEqual({self.excel['id'], alternative['id']}, set(hints['competingIds']))

    def test_general_personal_reader_keeps_plain_and_formula_capabilities(self):
        inventory = copy.deepcopy(self.inventory)
        alternative = dict(self.excel, id='user:general-reader', name='my-excel-reader',
                           source='user', invocation='my-excel-reader',
                           description='엑셀 파일 읽기 및 수식 분석을 지원합니다.')
        inventory['skills'].append(alternative)
        hints = task_candidates(inventory, '@file.xlsx 내용을 읽어줘')
        decision = decide_preparation(hints, inventory['skills'], [])
        self.assertEqual(('load', alternative['id']), (decision.mode, decision.candidate_id))
        hints = task_candidates(inventory, '엑셀 수식을 분석해줘')
        self.assertEqual('choose', decide_preparation(hints, inventory['skills'], []).mode)

    def test_hints_do_not_open_inputs_or_launch_work(self):
        with patch('pathlib.Path.open', side_effect=AssertionError('no input reads')), \
                patch('subprocess.run', side_effect=AssertionError('no execution')):
            hints = task_candidates(self.inventory, '@업무.xlsm VBA와 수식 구조를 분석해줘')
        self.assertIn(self.excel['id'], hints['strongIds'])


class ExcelCliContractTests(unittest.TestCase):
    def args(self, *suffix):
        return build_parser().parse_args(['business', 'excel-analyze', '--file', 'sample.xlsx', *suffix])

    def test_defaults_are_bounded_and_reader_is_auto(self):
        args = self.args('--context-only')
        self.assertEqual(('auto', 5, 12000, 90),
                         (args.reader, args.sample_rows, args.context_chars, args.excel_timeout))
        self.assertEqual('compact', args.layout)
        self.assertEqual([], args.target)

    def test_invalid_limit_never_starts_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'sample.xlsx'
            source.write_bytes(b'not-opened')
            args = self.args('--context-only', '--sample-rows', '1001')
            args.file = str(source)
            with patch.object(excel_pipeline_command.subprocess, 'run', side_effect=AssertionError('no launch')):
                result = excel_pipeline_command.analyze(args)
            self.assertEqual('invalid_excel_limits', result['code'])

    def test_missing_package_is_actionable_not_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'sample.xlsx'
            source.write_bytes(b'not-opened')
            args = self.args('--inspect')
            args.file = str(source)
            failure = subprocess.CompletedProcess([], 1, '', "ModuleNotFoundError: No module named 'openpyxl'")
            with patch.object(excel_pipeline_command.subprocess, 'run', return_value=failure) as run:
                result = business.dispatch(args)
            self.assertEqual(('input_required', 'openpyxl'), (result['status'], result['dependency']))
            command = run.call_args.args[0]
            self.assertEqual(sys.executable, command[0])
            self.assertNotIn('pip', command)
            self.assertNotIn('--session', command)
            self.assertEqual(1, run.call_count)

    def test_failures_do_not_fall_back_or_return_raw_tracebacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'sample.xlsx'
            source.write_bytes(b'not-opened')
            args = self.args('--inspect')
            args.file = str(source)
            failure = subprocess.CompletedProcess([], 2, '', '{"status":"not_processed","message":"permission denied"}')
            with patch.object(excel_pipeline_command.subprocess, 'run', return_value=failure) as run:
                result = excel_pipeline_command.analyze(args)
            self.assertFalse(result['ok'])
            self.assertFalse(result['retryAllowed'])
            self.assertEqual(1, run.call_count)

    def test_missing_source_does_not_launch_or_claim_drm(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args('--context-only')
            args.file = str(Path(temporary) / '없는 파일.xlsx')
            with patch.object(excel_pipeline_command.subprocess, 'run', side_effect=AssertionError('no execution')):
                result = business.dispatch(args)
            self.assertEqual('excel_input_not_found', result['code'])
            self.assertFalse(result['retryAllowed'])

    def test_read_only_contract_accepts_only_bounded_nonoutput_forms(self):
        prefix = ['business', 'excel-analyze', '--file', '한글 workbook.xlsm']
        for suffix in (['--inspect'], ['--context-only', '--reader', 'auto', '--sample-rows', '1000'],
                       ['--context-only', '--context-chars', '1024', '--excel-timeout', '300', '--reader', 'xlwings'],
                       ['--context-only', '--target', '집계!D8', '--target', 's01_t01', '--layout', 'compact']):
            self.assertTrue(excel_pipeline_command.read_only_arguments(prefix + suffix))
        for suffix in ([], ['--output', 'results'], ['--inspect', '--context-only'],
                       ['--inspect', '--inspect'], ['--inspect', '--sample-rows', '1001'],
                       ['--inspect', '--sample-rows', '-1'], ['--inspect', '--reader', 'unknown'],
                       ['--inspect', '--unknown', 'x'], ['--inspect', '--file', 'other.xlsm']):
            self.assertFalse(excel_pipeline_command.read_only_arguments(prefix + suffix), suffix)
        self.assertFalse(excel_pipeline_command.read_only_arguments(
            ['business', 'excel-analyze', '--file', 'x.html', '--inspect']))
        self.assertTrue(excel_pipeline_command.read_only_arguments(['business', 'excel-analyze', '--help']))

    def test_trusted_classification_is_not_permission(self):
        command = '"' + sys.executable + '" "' + str(PLUGIN / 'scripts/harness_cli.py') + '" business excel-analyze'
        for tail in (' --file "example.xlsx" --inspect', ' --file "example.xlsm" --context-only', ' --help'):
            self.assertEqual('read_only', classify_command(command + tail))
        self.assertEqual('unknown', classify_command(command + ' --file "example.xlsx" --output "result"'))
        payload = {'hook_event_name': 'PermissionRequest', 'tool_name': 'Bash',
                   'tool_input': {'command': command + ' --file "example.xlsx" --inspect'}}
        self.assertIsNone(safe_permission(payload, ROOT / 'tmp'))

    def test_generated_runtime_matches_authoritative_sources(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/sync-excel-pipeline-skill.py'), '--check'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        skill = PLUGIN / 'skills/excel-to-pipeline'
        for name in ('tests', 'examples', 'fixtures', '.venv'):
            self.assertFalse((skill / name).exists())
        self.assertFalse((PLUGIN / 'skills/office-reader').exists())

    def test_target_flags_forwarded_without_new_model_or_preflight_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'sample.xlsx'
            source.write_bytes(b'not-opened')
            args = self.args('--output', str(Path(temporary) / 'output'), '--target', '집계!D8',
                             '--target', 's01_t01', '--diagnostics')
            args.file = str(source)
            success = subprocess.CompletedProcess([], 0, '{"status": "extracted"}', '')
            with patch.object(excel_pipeline_command.subprocess, 'run', return_value=success) as run:
                result = excel_pipeline_command.analyze(args)
            self.assertTrue(result['ok'])
            command = run.call_args.args[0]
            self.assertEqual(2, command.count('--target'))
            self.assertIn('--diagnostics', command)
            self.assertEqual(1, run.call_count)
            self.assertTrue(result['modelContext'].endswith(str(Path('_details/model_context.json'))))
            self.assertNotIn('transform', result)


@unittest.skipUnless(HAS_OPENPYXL, 'openpyxl required for installed analysis smoke')
class InstalledExcelWorkflowTests(unittest.TestCase):
    def test_installed_copy_generates_case_preserving_reusable_pipeline(self):
        import openpyxl
        from openpyxl.styles import Font
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / '배포 폴더' / 'plugin'
            shutil.copytree(PLUGIN / 'scripts', install / 'scripts', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copytree(PLUGIN / 'skills/excel-to-pipeline', install / 'skills/excel-to-pipeline',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            source = root / '혼합대소문자.xlsx'
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = '입력'
            sheet.append(['ID', '수량', '결과'])
            sheet.append(['aB009', 3, '=B2*2'])
            sheet.append(['Ab009', 4, '=B3*2'])
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            workbook.save(source)
            workbook.close()
            before = source.read_bytes()
            output = root / '결과'
            completed = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(install / 'scripts/harness_cli.py'),
                                        'business', 'excel-analyze', '--file', str(source), '--output', str(output)],
                                       capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result['ok'], result)
            self.assertEqual(str(output / 'main.py'), result['entryPoint'])
            self.assertTrue((output / 'DATA/load.py').is_file())
            self.assertTrue((output / 'PROCESS/pipeline.py').is_file())
            self.assertEqual('openpyxl', result['summary']['reader'])
            self.assertEqual({'computed': 2}, result['summary']['formula_status'])
            self.assertEqual(before, source.read_bytes())
            cells = [json.loads(p.read_text(encoding='utf-8')) for p in (output / 'tables').glob('*.json')]
            serialized = json.dumps(cells, ensure_ascii=False)
            self.assertIn('aB009', serialized)
            self.assertIn('Ab009', serialized)
            context = (output / '_details/model_context.json').read_text(encoding='utf-8')
            self.assertLessEqual(len(context), 12000)
            next_output = root / '다음결과'
            rerun = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(output / 'main.py'),
                                    '--output', str(next_output)], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(0, rerun.returncode, rerun.stdout + rerun.stderr)
            self.assertEqual([t['rows'] for t in cells],
                             [json.loads(p.read_text(encoding='utf-8'))['rows'] for p in (next_output / 'tables').glob('*.json')])
            project_run = subprocess.run([sys.executable, '-X', 'utf8', '-B', result['entryPoint'],
                                          '--output', str(root / '분리 실행')],
                                         capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(0, project_run.returncode, project_run.stdout + project_run.stderr)
            self.assertEqual({'computed': 2}, json.loads(project_run.stdout)['summary']['formula_status'])


if __name__ == '__main__':
    unittest.main()
