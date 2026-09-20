"""Regression checks for the deliberately small, fail-closed schema subset."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import asset_factory as assets, platform_assets


class AssetSchemaTests(unittest.TestCase):
    def test_constraints_are_enforced_including_boolean_number_distinction(self):
        invalid = [
            (-1, {'type': 'integer', 'minimum': 0}),
            (4, {'maximum': 3}),
            ('unsafe', {'enum': ['safe']}),
            (True, {'enum': [1]}),
            ({'nested': [True]}, {'enum': [{'nested': [1]}]}),
            ({'ok': True, 'secret': 'extra'}, {'properties': {'ok': {}}, 'additionalProperties': False}),
            (True, {'type': 'integer'}),
            ({'value': float('nan')}, {}),
            ([float('inf')], {}),
        ]
        for value, schema in invalid:
            with self.subTest(value=value, schema=schema), self.assertRaises(ValueError):
                assets._validate_json_value(value, schema)
        for value, schema in [(2, {'minimum': 1, 'maximum': 2}), (1.0, {'enum': [1]}),
                              ({'ok': True}, {'properties': {'ok': {'type': 'boolean'}}, 'additionalProperties': False}),
                              (None, {'type': ['string', 'null']}), (3, {'type': 'number'}),
                              (1.0, {'type': 'integer'}), (True, {'enum': [True, 1]})]:
            assets._validate_json_value(value, schema)

    def test_malformed_or_unsupported_schema_is_rejected_before_values(self):
        malformed = [None, {'pattern': '^safe$'}, {'type': 'imaginary'}, {'type': []},
                     {'type': ['string', 'string']}, {'minimum': True}, {'maximum': float('nan')},
                     {'minimum': 3, 'maximum': 2}, {'enum': []}, {'enum': [1, 1.0]},
                     {'enum': [float('nan')]}, {'required': [1]}, {'required': ['a', 'a']},
                     {'properties': {'unused': {'pattern': 'ignored'}}}, {'items': {'unknown': True}},
                     {'additionalProperties': {}}, {'properties': {'unused': None}}]
        for schema in malformed:
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                assets._validate_schema_definition(schema, 'fixture')
        with self.assertRaises(ValueError):
            assets._validate_json_value({}, {'properties': {'absent': {'pattern': 'ignored'}}})

    def test_invalid_schema_does_not_create_or_overwrite_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state'
            spec = {'type': 'script-tool', 'name': 'safe-tool', 'description': '합성 시험',
                    'code': 'print(1)\n', 'output_schema': {'type': 'integer'}}
            path = assets.create_asset(spec, state)
            before = (path / 'tool.json').read_bytes()
            with self.assertRaises(ValueError):
                assets.create_asset({**spec, 'output_schema': {'pattern': 'unsupported'}}, state)
            self.assertEqual(before, (path / 'tool.json').read_bytes())
            with self.assertRaises(ValueError):
                assets.create_asset({**spec, 'name': 'new-tool', 'input_schema': {'items': {'unknown': 1}}}, state)
            self.assertFalse((state / 'tools/new-tool').exists())

    def test_legacy_script_receipt_requires_retest_before_activation_or_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state'
            path = assets.create_asset({'type': 'script-tool', 'name': 'script-evidence', 'description': '합성 검증',
                'code': 'print(1)\n', 'input_schema': {'type': 'integer', 'minimum': 0},
                'output_schema': {'type': 'integer', 'minimum': 0}}, state)
            layout = assets.ensure_user_layout(state)
            legacy = assets._write_receipt(layout, path, 'script-runtime', 'script-tool', 'script-evidence',
                assets._asset_content_hash(path, 'tool.json'), {'outputType': 'integer'})
            input_file = Path(temp) / 'input.json'
            input_file.write_text('1', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 're-test script tool'):
                assets.activate_script_tool(state, 'script-evidence', legacy)
            manifest = assets.load_json(path / 'tool.json')
            self.assertEqual('candidate', manifest['status'])
            # Simulate a previously activated installation, not a new activation.
            assets.atomic_write_json(path / 'tool.json', {**manifest, 'status': 'active', 'validationReceipt': legacy.name})
            with patch.object(assets, '_execute_json_tool') as run:
                with self.assertRaisesRegex(ValueError, 're-test script tool'):
                    assets.run_script_tool(state, 'script-evidence', input_file)
                run.assert_not_called()
            current = assets.validate_script_tool_runtime(state, 'script-evidence', input_file)
            self.assertEqual(1, assets.load_json(current)['details']['schemaValidationVersion'])
            assets.activate_script_tool(state, 'script-evidence', current)
            self.assertEqual(1, assets.run_script_tool(state, 'script-evidence', input_file)['result'])

    def test_invalid_input_never_runs_and_invalid_output_never_gets_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state'
            path = assets.create_asset({'type': 'script-tool', 'name': 'bounded-tool', 'description': '합성 시험',
                'code': 'print(-1)\n', 'input_schema': {'type': 'integer', 'minimum': 0},
                'output_schema': {'type': 'integer', 'minimum': 0}}, state)
            input_file = Path(temp) / 'input.json'
            input_file.write_text('-1', encoding='utf-8')
            with patch.object(assets, '_execute_json_tool') as run:
                with self.assertRaises(ValueError):
                    assets.validate_script_tool_runtime(state, 'bounded-tool', input_file)
                run.assert_not_called()
            input_file.write_text('1', encoding='utf-8')
            with self.assertRaises(ValueError):
                assets.validate_script_tool_runtime(state, 'bounded-tool', input_file)
            self.assertEqual([], list(path.glob('.receipts/*.json')))
            self.assertEqual('candidate', json.loads((path / 'tool.json').read_text())['status'])

    def test_business_schema_failure_cannot_produce_success_evidence(self):
        class Session:
            async def call_tool(self, name, arguments):
                return SimpleNamespace(isError=False, content=[SimpleNamespace(type='text', text='-1')])
        listed = SimpleNamespace(tools=[SimpleNamespace(name='example', inputSchema={})])
        cases = [{'tool': 'example', 'arguments': {}, 'expect': {'json_schema': {'type': 'integer', 'minimum': 0}}}]
        platform_assets.validate_cases(cases)
        with self.assertRaises(ValueError):
            asyncio.run(platform_assets.test_business_tools(Session(), listed, cases))

    def test_legacy_json_evidence_requires_retest_without_invalidating_text_tests(self):
        text = [{'tool': 'example', 'arguments': {}, 'expect': {'text': 'synthetic'}}]
        exact = [{'tool': 'example', 'arguments': {}, 'expect': {'json': 1}}]
        schema = [{'tool': 'example', 'arguments': {}, 'expect': {'json_schema': {'minimum': 0}}}]
        receipt = {'details': {'businessTestCount': 1, 'businessTools': ['example'], 'toolSchemas': {'example': {}}}}
        with patch.object(platform_assets, 'platform_cases', return_value=text):
            platform_assets.verify_business_receipt(Path('.'), {'format': platform_assets.FORMAT}, receipt)
        for cases in (exact, schema):
            with patch.object(platform_assets, 'platform_cases', return_value=cases):
                with self.assertRaisesRegex(ValueError, 're-test MCP'):
                    platform_assets.verify_business_receipt(Path('.'), {'format': platform_assets.FORMAT}, receipt)
                current = {'details': {**receipt['details'], 'schemaValidationVersion': 1}}
                platform_assets.verify_business_receipt(Path('.'), {'format': platform_assets.FORMAT}, current)

    def test_exact_business_json_keeps_booleans_distinct_from_numbers(self):
        class Session:
            async def call_tool(self, name, arguments):
                return SimpleNamespace(isError=False, content=[SimpleNamespace(type='text', text='true')])
        listed = SimpleNamespace(tools=[SimpleNamespace(name='example', inputSchema={})])
        with self.assertRaises(ValueError):
            asyncio.run(platform_assets.test_business_tools(Session(), listed,
                [{'tool': 'example', 'arguments': {}, 'expect': {'json': 1}}]))
        with self.assertRaises(ValueError):
            platform_assets.validate_cases([{'tool': 'example', 'arguments': {}, 'expect': {'json': float('nan')}}])

    def test_old_python_equal_json_success_is_not_reusable_evidence(self):
        # The old comparator issued success when actual True matched expected
        # numeric 1. That old receipt cannot substantiate the corrected test.
        self.assertEqual(True, 1)
        cases = [{'tool': 'example', 'arguments': {}, 'expect': {'json': 1}}]
        legacy = {'details': {'businessTestCount': 1, 'businessTools': ['example'],
                              'toolSchemas': {'example': {}}}}
        with patch.object(platform_assets, 'platform_cases', return_value=cases):
            with self.assertRaisesRegex(ValueError, 're-test MCP'):
                platform_assets.verify_business_receipt(Path('.'), {'format': platform_assets.FORMAT}, legacy)


if __name__ == '__main__':
    unittest.main()
