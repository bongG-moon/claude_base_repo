import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from work_catalog import clean
from work_execution import ExecutionTrace, merge_executions, sanitize_execution
from work_purpose import explain_purpose, normalize_purpose


def shell(code):
    return {'command': "python -I -X utf8 - <<'PY'\n" + code + '\nPY'}


def call(args, call_id='c1'):
    return {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'name': 'Bash', 'id': call_id, 'input': args}]}}


class PurposeTests(unittest.TestCase):
    def test_declared_business_purpose_is_preserved_but_not_success(self):
        text = '교육 신청자의 중복을 제거하고 부서별 신청 인원을 집계'
        purpose = explain_purpose('Bash', {'command': 'python summary.py', 'description': text}, clean)
        self.assertEqual({'text': text, 'basis': 'invocation_description'}, purpose)

    def test_inline_python_describes_processing_order_without_literals(self):
        code = "import pandas as pd\ndf = pd.read_csv('PRIVATE.csv')\ndf = df.drop_duplicates()\nout = df.groupby('PRIVATE_COLUMN').sum()\nout.to_csv('PRIVATE_OUTPUT.csv')"
        purpose = explain_purpose('Bash', shell(code), clean)
        self.assertEqual('code_structure', purpose['basis'])
        text = purpose['text']
        for phrase in ('CSV 표를 읽고', '중복 행을 제거하고', '같은 기준의 행을 묶고', '합계를 계산하고', 'CSV 결과를 저장하도록'):
            self.assertIn(phrase, text)
        self.assertLess(text.index('CSV 표를 읽고'), text.index('중복 행을 제거하고'))
        self.assertLess(text.index('합계를 계산하고'), text.index('CSV 결과를 저장하도록'))
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('import', text)
        self.assertIn('실제 처리 여부는 별도 확인', text)
        self.assertLessEqual(len(text), 240)

    def test_c_argument_and_json_encoded_arguments(self):
        args = {'cmd': 'python -c "import pandas as pd; df = pd.read_excel(\'a.xlsx\'); df.to_html()"'}
        purpose = explain_purpose('functions.exec_command', json.dumps(args), clean)
        self.assertIn('Excel 표를 읽고', purpose['text'])
        self.assertIn('HTML 표를 작성하도록', purpose['text'])

    def test_strings_comments_and_dormant_functions_are_not_steps(self):
        for code in ('print("df.drop_duplicates()")', '# df.drop_duplicates()\npass',
                     'def not_called():\n    return pd.read_csv("private.csv")',
                     'class Dormant:\n    result = pd.read_csv("private.csv")',
                     'f = lambda: pd.read_csv("private.csv")'):
            with self.subTest(code=code):
                self.assertIsNone(explain_purpose('Bash', shell(code), clean))

    def test_malformed_overlarge_and_unrecognized_commands_remain_unknown(self):
        for args in ({'command': 'python -c "broken('},
                     shell('pass\n' * 9000), shell('x=' + '[' * 5000),
                     {'command': 'echo "python -c pd.read_csv(x)"'},
                     {'command': 'python -c "pd.read_csv(x)" && upload secret'},
                     {'command': 'python private_script.py'},
                     {'command': 'python - <<PY\npd.read_csv(x)\nPY'}):
            self.assertIsNone(explain_purpose('Bash', args, clean))
        self.assertIsNone(explain_purpose('functions.exec', 'text(await tools.exec_command({cmd: "python private.py"}));', clean))

    def test_generic_descriptions_do_not_mask_more_specific_code_evidence(self):
        args = shell('import pandas as pd\npd.read_csv("private.csv").drop_duplicates().to_csv("out.csv")')
        args['description'] = 'Run Python code'
        self.assertEqual('code_structure', explain_purpose('Bash', args, clean)['basis'])
        args['description'] = '자료를 모두 정상 처리 완료'
        self.assertEqual('code_structure', explain_purpose('Bash', args, clean)['basis'])

    def test_sensitive_descriptions_are_omitted_not_cropped(self):
        values = ['Check token=PRIVATE_SECRET', 'Query user@example.com',
                  'Read C:\\Users\\someone\\source.csv', 'Download https://internal.example/data',
                  'x' * 241, 'Run\nPRIVATE CODE', 'SELECT customer FROM secret',
                  'Check value 12345678901', 'python process.py; cat credentials',
                  'Inspect ' + 'a' * 70, 'Call fn(PRIVATE)', '<img src=x>',
                  'Read /data/private.csv', '비밀번호 ABCDEF 확인', 'git push origin main']
        for text in values:
            with self.subTest(text=text):
                self.assertIsNone(explain_purpose('Bash', {'description': text}, clean))

    def test_result_and_prompt_fields_are_not_purpose_inputs(self):
        self.assertIsNone(explain_purpose('Agent', {'prompt': 'PRIVATE PURPOSE'}, clean))
        self.assertIsNone(explain_purpose('Write', {'content': 'PRIVATE PURPOSE'}, clean))
        self.assertIsNone(explain_purpose('Bash', {'output': 'PRIVATE PURPOSE', 'thinking': 'PRIVATE PURPOSE'}, clean))

    def test_metadata_uses_only_already_safe_target(self):
        purpose = explain_purpose('Read', {}, clean, '교육신청.csv')
        self.assertEqual('target_metadata', purpose['basis'])
        self.assertIn('교육신청.csv', purpose['text'])
        self.assertIsNone(explain_purpose('Read', {}, clean, '[민감 대상 가림]'))

    def test_python_test_command_gets_specific_validation_intent(self):
        purpose = explain_purpose('Bash', {'command': 'python -X utf8 -B -m unittest discover'}, clean)
        self.assertIn('기대한 결과와 일치', purpose['text'])
        self.assertIsNone(explain_purpose('Bash', {'command': 'echo "python -m unittest"'}, clean))

    def test_string_and_custom_methods_are_not_pandas_actions(self):
        for code in ("';'.join(['a', 'b'])", "obj.query('x').count()", 'custom.merge(other)',
                     'df.drop_duplicates().to_csv("out.csv")', 'thing.write_text("hello")',
                     'pd.read_csv("data.csv")'):
            self.assertIsNone(explain_purpose('Bash', shell(code), clean), code)

    def test_aliases_chains_and_pathlib_are_bound_to_imports(self):
        code = "from pandas import read_csv as load\nfrom pathlib import Path as LocalPath\ndf=load('input.csv')\ncleaned=df.drop_duplicates()\ncleaned.groupby('team').sum().to_csv('out.csv')\nLocalPath('done.txt').write_text('PRIVATE')"
        purpose = explain_purpose('Bash', shell(code), clean)
        self.assertIn('중복 행을 제거하고', purpose['text'])
        self.assertIn('합계를 계산하고', purpose['text'])
        self.assertIn('텍스트 결과 파일을 쓰도록', purpose['text'])
        self.assertNotIn('PRIVATE', purpose['text'])

    def test_reassigned_imports_and_receivers_do_not_keep_provenance(self):
        for code in ('import pandas as pd\npd=custom\npd.read_csv("private.csv")',
                     'from pathlib import Path\nPath=custom\nPath("a").write_text("x")',
                     'import pandas as pd\npd.read_csv=custom\npd.read_csv("private.csv")'):
            self.assertIsNone(explain_purpose('Bash', shell(code), clean), code)
        code = 'import pandas as pd\ndf=pd.DataFrame()\ndf=custom\ndf.query("x").count()'
        self.assertIsNone(explain_purpose('Bash', shell(code), clean))

    def test_conditional_binding_does_not_leak_as_a_certain_receiver(self):
        code = 'import pandas as pd\nif condition:\n    df=pd.DataFrame()\nelse:\n    df=custom\ndf.query("x").count()'
        self.assertIsNone(explain_purpose('Bash', shell(code), clean))

    def test_import_and_legacy_optional_purpose(self):
        trace = ExecutionTrace(clean)
        trace.observe(call({'description': '교육 신청자의 중복을 제거하기', 'command': 'python a.py'}), 'row')
        event = next(iter(trace.events.values()))
        imported = sanitize_execution(event, clean, set())
        self.assertEqual(event['purpose'], imported['purpose'])
        legacy = dict(event); legacy.pop('purpose')
        self.assertNotIn('purpose', sanitize_execution(legacy, clean, set()))
        self.assertEqual(event['purpose'], merge_executions([legacy], [event])[0]['purpose'])
        self.assertEqual(event['purpose'], merge_executions([event], [legacy])[0]['purpose'])

    def test_purpose_conflict_keeps_call_and_outcome_but_exposes_unknown(self):
        trace = ExecutionTrace(clean)
        trace.observe(call({'description': '교육 신청자의 중복을 제거하기'}), 'row')
        trace.observe(call({'description': '교재 주문의 중복을 제거하기'}), 'copy')
        event = next(iter(trace.events.values()))
        self.assertTrue(event['purpose_conflict'])
        self.assertNotIn('purpose', event)
        self.assertTrue(trace.partial)
        self.assertEqual('unconfirmed', event['status'])
        # A later matching copy cannot silently clear earlier conflicting evidence.
        other = dict(event, purpose={'text': '교육 신청자의 중복을 제거하기', 'basis': 'invocation_description'})
        other.pop('purpose_conflict')
        merged = merge_executions([event], [other])[0]
        self.assertTrue(merged['purpose_conflict'])
        self.assertNotIn('purpose', merged)

    def test_import_purpose_validates_shape_and_sensitive_text(self):
        for value in ({'text': 'token=PRIVATE', 'basis': 'invocation_description'},
                      {'text': '요청한 모든 업무 완료', 'basis': 'success'},
                      {'text': '교육 신청 집계', 'basis': 'code_structure', 'raw': 'PRIVATE'},
                      {'text': '<script>alert(1)</script>', 'basis': 'code_structure'}):
            with self.assertRaises(ValueError):
                normalize_purpose(value, clean)


if __name__ == '__main__':
    unittest.main()
