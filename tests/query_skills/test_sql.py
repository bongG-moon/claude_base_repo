from __future__ import annotations

from contextlib import redirect_stderr
from datetime import date, datetime
from decimal import Decimal
import io
import logging
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/query_skills'))
from query_core.sql import analyze_sql, bind_params, bounded_sql, compile_for_engine, parameter_names, validate_sql, _definitions


class SQLTests(unittest.TestCase):
    def test_simple_select_and_dual(self):
        self.assertEqual(validate_sql('SELECT 1;', 'oracle'), 'SELECT 1')
        self.assertEqual(analyze_sql('SELECT 1 FROM DUAL', 'oracle')['riskReasons'], [])
        self.assertEqual(analyze_sql('SELECT 1', 'datalake')['riskReasons'], [])

    def test_common_engines_and_named_binds(self):
        for engine in ('oracle', 'datalake', 'ehub', 'starrocks', 'sqlite', 'demo'):
            self.assertEqual(parameter_names('SELECT * FROM t WHERE code=:key', engine), ['key'])

    def test_strings_and_quoted_identifiers_are_not_parameters(self):
        sql = 'SELECT ":column", \'a:b\' FROM t WHERE x=:actual -- :fake\n'
        self.assertEqual(parameter_names(sql, 'oracle'), ['actual'])

    def test_q_string_and_embedded_quote_value_are_preserved(self):
        sql = "SELECT q'[don't:bind]' AS text FROM dual WHERE a=:wanted"
        value = validate_sql(sql, 'oracle')
        self.assertIn("'don''t:bind'", value)
        self.assertEqual(parameter_names(sql, 'oracle'), ['wanted'])

    def test_parameter_case_preserved_and_case_collisions_rejected(self):
        self.assertEqual(parameter_names('SELECT :Target FROM dual', 'oracle'), ['Target'])
        with self.assertRaises(ValueError):
            validate_sql('SELECT :Target, :target FROM dual', 'oracle')

    def test_reserved_generated_positional_and_invalid_parameters_rejected(self):
        for sql in ('SELECT :select FROM dual', 'SELECT :qsbind_key_0 FROM dual',
                    'SELECT :1 FROM dual', 'SELECT ? FROM dual', 'SELECT %s FROM dual',
                    'SELECT %(key)s FROM dual', 'SELECT {key} FROM dual'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_sql(sql, 'oracle')

    def test_table_binding_and_table_functions_rejected(self):
        for sql in ('SELECT * FROM :table_name', 'SELECT * FROM TABLE(my_function())'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_sql(sql, 'oracle')

    def test_dml_multiple_statements_and_admin_commands_rejected(self):
        for sql in ('DELETE FROM t', 'UPDATE t SET x=1', 'CREATE TABLE t(x INT)',
                    'SELECT 1; DROP TABLE t', 'BEGIN NULL; END;', 'COMMIT',
                    'SELECT a INTO b FROM t', 'WITH t AS (DELETE FROM x) SELECT * FROM t'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_sql(sql, 'oracle')

    def test_locks_file_output_hints_and_sequence_rejected(self):
        for sql, engine in [('SELECT * FROM t FOR UPDATE', 'oracle'),
                            ('SELECT * FROM t FOR SHARE', 'datalake'),
                            ("SELECT * FROM t INTO OUTFILE 'x'", 'datalake'),
                            ('SELECT /*+ FULL(t) */ * FROM t', 'oracle'),
                            ('SELECT /*!50000 x */ 1', 'datalake'),
                            ('SELECT seq.NEXTVAL FROM dual', 'oracle')]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_sql(sql, engine)

    def test_known_external_and_delay_functions_rejected(self):
        for sql in ("SELECT UTL_HTTP.REQUEST('url') FROM dual", 'SELECT DBMS_LOCK.SLEEP(1) FROM dual',
                    'SELECT SLEEP(30)', 'SELECT LOAD_FILE(:path)', 'SELECT NEXTVAL(:seq)'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_sql(sql, 'oracle')

    def test_unknown_function_is_review_candidate_not_claim_of_sandbox(self):
        risks = analyze_sql('SELECT business_fn(:item) FROM dual', 'oracle')['riskReasons']
        self.assertTrue(any('함수' in reason for reason in risks))

    def test_errors_and_parser_warnings_do_not_leak_sql(self):
        marker = 'PRIVATE_QUERY_CONTENT'
        stream = io.StringIO()
        logger = logging.getLogger('sqlglot')
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        try:
            for sql in ('EXECUTE ' + marker, 'SELECT FROM ) ' + marker):
                with redirect_stderr(stream), self.assertRaises(ValueError) as failure:
                    validate_sql(sql, 'oracle')
                self.assertNotIn(marker, str(failure.exception))
            self.assertNotIn(marker, stream.getvalue())
        finally:
            logger.removeHandler(handler)

    def test_broad_where_constant_and_union_branch_are_candidates(self):
        for sql in ('SELECT * FROM t', 'SELECT * FROM t WHERE 1=1',
                    'SELECT * FROM t WHERE a=a', 'SELECT * FROM t WHERE a=:key OR 1=1',
                    "SELECT * FROM t WHERE a LIKE '%'",
                    'SELECT x FROM t WHERE day=:day_value UNION ALL SELECT x FROM u'):
            with self.subTest(sql=sql):
                self.assertTrue(any('조건이 없는' in reason for reason in analyze_sql(sql, 'oracle')['riskReasons']))

    def test_cross_join_and_large_offset_candidates(self):
        cases = [('SELECT * FROM t CROSS JOIN u', '조인'),
                 ('SELECT * FROM t, u', '조인'),
                 ('SELECT * FROM t LIMIT 10 OFFSET 20000', '건너뛰')]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertTrue(any(expected in reason for reason in analyze_sql(sql, 'datalake')['riskReasons']))

    def test_filtered_ordinary_order_and_aggregation_do_not_require_large_approval(self):
        for sql, expected in [('SELECT * FROM t WHERE day=:day_value ORDER BY day', '정렬'),
                              ('SELECT process, SUM(qty) total FROM t WHERE day=:day_value GROUP BY process', '집계'),
                              ('SELECT * FROM t WHERE 1=1 AND day=:day_value ORDER BY day', '정렬')]:
            report = analyze_sql(sql, 'oracle')
            self.assertEqual(report['riskReasons'], [])
            self.assertTrue(any(expected in reason for reason in report['advisories']))

    def test_unfiltered_aggregation_retains_broad_risk_and_advisory(self):
        report = analyze_sql('SELECT COUNT(*) AS total FROM t', 'oracle')
        self.assertTrue(any('조건이 없는' in reason for reason in report['riskReasons']))
        self.assertTrue(any('집계' in reason for reason in report['advisories']))

    def test_filtered_cte_and_subquery_wrappers_do_not_repeat_broad_warning(self):
        for sql in ('WITH filtered AS (SELECT * FROM t WHERE x=:key) SELECT * FROM filtered ORDER BY x',
                    'SELECT * FROM (SELECT * FROM t WHERE x=:key) filtered'):
            with self.subTest(sql=sql):
                self.assertEqual(analyze_sql(sql, 'oracle')['riskReasons'], [])
        report = analyze_sql('WITH unfiltered AS (SELECT * FROM t) SELECT * FROM unfiltered', 'oracle')
        self.assertTrue(any('조건이 없는' in reason for reason in report['riskReasons']))

    def test_recursive_cte_requires_cost_confirmation(self):
        sql = 'WITH RECURSIVE nums(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM nums WHERE n<100) SELECT * FROM nums'
        self.assertTrue(any('재귀' in reason for reason in analyze_sql(sql, 'datalake')['riskReasons']))

    def test_condition_candidates_exclude_literal_content(self):
        report = analyze_sql("SELECT x FROM t WHERE process='PRIVATE_VALUE' AND day=:day_value", 'oracle')
        self.assertEqual(report['parameters'], ['day_value'])
        self.assertNotIn('PRIVATE_VALUE', str(report))
        self.assertEqual({c['column'] for c in report['conditionCandidates']}, {'process', 'day'})

    def test_bind_all_scalar_types_without_changing_text(self):
        sql = 'SELECT * FROM t WHERE a=:a AND b=:b AND c=:c AND d=:d AND e=:e'
        values = {'a': ' aBc ', 'b': '0012', 'c': '0.10', 'd': '2026-10-31', 'e': '2026-10-31T12:10:05'}
        definitions = {name: {'type': kind} for name, kind in zip(values, ['text', 'int', 'decimal', 'date', 'datetime'])}
        result = bind_params(sql, definitions, values, 'oracle')
        self.assertEqual(result, {'a': ' aBc ', 'b': 12, 'c': Decimal('0.10'), 'd': date(2026, 10, 31), 'e': datetime(2026, 10, 31, 12, 10, 5)})

    def test_required_unknown_and_undeclared_conditions_fail(self):
        sql = 'SELECT * FROM t WHERE a=:a'
        for definitions, values in [({'a': 'text'}, {}), ({}, {'a': 'x'}),
                                    ({'a': 'text'}, {'a': 'x', 'b': 'y'}),
                                    ({'a': 'text', 'b': 'text'}, {'a': 'x'})]:
            with self.subTest(definitions=definitions, values=values), self.assertRaises(ValueError):
                bind_params(sql, definitions, values, 'oracle')

    def test_defaults_nullable_and_choices_are_explicit(self):
        sql = 'SELECT :a, :b FROM dual'
        defs = {'a': {'type': 'text', 'default': 'WB', 'choices': ['WB', 'DA']},
                'b': {'type': 'text', 'required': False, 'nullable': True}}
        self.assertEqual(bind_params(sql, defs, {}, 'oracle'), {'a': 'WB', 'b': None})
        with self.assertRaises(ValueError):
            bind_params(sql, defs, {'a': 'UNLISTED'}, 'oracle')

    def test_invalid_types_and_values_do_not_leak(self):
        for kind, value in [('int', 1.2), ('int', True), ('int', 10**40), ('decimal', 'NaN'),
                            ('decimal', 'Infinity'), ('decimal', '1e999999'), ('date', '2026-02-31'),
                            ('datetime', '2026-01-01T00:00:00+09:00'), ('text', ''),
                            ('text', 'x' * 8001), ('text', {'secret': 'PRIVATE_VALUE'})]:
            with self.subTest(kind=kind), self.assertRaises(ValueError) as failure:
                bind_params('SELECT :a FROM dual', {'a': {'type': kind}}, {'a': value}, 'oracle')
            self.assertNotIn('PRIVATE_VALUE', str(failure.exception))

    def test_list_definitions_and_bounded_lists(self):
        sql = 'SELECT * FROM t WHERE a IN (:names)'
        defs = [{'name': 'names', 'type': 'list', 'item_type': 'text'}]
        self.assertEqual(bind_params(sql, defs, {'names': ['A', 'B']}, 'oracle'), {'names': ['A', 'B']})
        for value in ([], ['x'] * 501, [['x']], ['A', None]):
            with self.subTest(value_type=type(value)), self.assertRaises(ValueError):
                bind_params(sql, defs, {'names': value}, 'oracle')

    def test_registration_rejects_unsupported_definition_types(self):
        for definition in ({'type': 'object'}, {'type': 'list[object]'},
                           {'type': 'list', 'item_type': 'list'}, {'type': 1},
                           {'type': 'text', 'required': 'false'},
                           {'type': 'text', 'choices': 'A'}):
            with self.subTest(definition=definition), self.assertRaises(ValueError):
                _definitions({'key': definition})
        self.assertEqual(_definitions({'key': {'type': 'LIST', 'item_type': 'INT'}})['key']['item_type'], 'int')
        with self.assertRaises(ValueError):
            _definitions([{'name': ['invalid'], 'type': 'text'}])

    def test_mysql_binding_never_substitutes_string_literal_or_value(self):
        sql = "SELECT ':key' x FROM t WHERE a=:key"
        payload = "x' OR 1=1 --"
        rendered, binds = compile_for_engine(sql, {'key': payload}, 'datalake')
        self.assertIn("':key'", rendered)
        self.assertIn('%(key)s', rendered)
        self.assertNotIn(payload, rendered)
        self.assertEqual(binds, {'key': payload})

    def test_list_expands_to_safe_bind_parameters(self):
        rendered, binds = compile_for_engine('SELECT * FROM t WHERE a IN (:names) OR b IN (:names)', {'names': ['x', 'y']}, 'oracle')
        self.assertIn(':qsbind_names_0', rendered)
        self.assertEqual(binds, {'qsbind_names_0': 'x', 'qsbind_names_1': 'y'})
        self.assertEqual(rendered.count(':qsbind_names_0'), 2)

    def test_mysql_literal_percent_and_modulo_survive_driver_binding(self):
        rendered, binds = compile_for_engine("SELECT qty % 2 FROM t WHERE code LIKE 'A%' AND key_id=:key", {'key': 7}, 'datalake')
        self.assertIn("LIKE 'A%'", rendered)
        self.assertIn('qty % 2', rendered)
        self.assertIn('key_id = %(key)s', rendered)
        self.assertNotIn('%%', rendered)
        rendered, binds = compile_for_engine("SELECT '100%'", {}, 'ehub')
        self.assertEqual(rendered, "SELECT '100%'")

    def test_mysql_mapping_like_literal_is_not_accidentally_bound(self):
        with self.assertRaises(ValueError):
            compile_for_engine("SELECT '%(key)s' FROM t WHERE a=:key", {'key': 'A'}, 'datalake')
        rendered, binds = compile_for_engine('SELECT :key', {'key': '%(other)s'}, 'datalake')
        self.assertEqual(rendered, 'SELECT %(key)s')
        self.assertEqual(binds, {'key': '%(other)s'})

    def test_list_wrong_position_and_bind_mismatch_fail(self):
        for sql in ('SELECT :names FROM dual', 'SELECT * FROM t WHERE a IN (:names, 1)'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                compile_for_engine(sql, {'names': ['A']}, 'oracle')
        with self.assertRaises(ValueError):
            compile_for_engine('SELECT :a FROM dual', {'other': 1}, 'oracle')

    def test_bounded_sql_preserves_original_small_limit(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE t (x INTEGER)')
        connection.executemany('INSERT INTO t VALUES (?)', [(i,) for i in range(20)])
        for input_limit, outer_limit, expected in [(2, 10, 2), (10, 2, 2), (0, 10, 0)]:
            sql = bounded_sql(f'SELECT x FROM t ORDER BY x LIMIT {input_limit}', 'sqlite', outer_limit)
            self.assertEqual(len(connection.execute(sql).fetchall()), expected)

    def test_bounded_oracle_uses_rownum_wrapper_preserving_fetch(self):
        sql = bounded_sql('SELECT x FROM t FETCH FIRST 2 ROWS ONLY', 'oracle', 11)
        self.assertIn('FETCH FIRST 2 ROWS ONLY', sql)
        self.assertIn('ROWNUM <= 11', sql)
        self.assertEqual(parameter_names(sql, 'oracle'), [])

    def test_dynamic_or_negative_limit_rejected(self):
        for sql in ('SELECT * FROM t LIMIT -1', 'SELECT * FROM t LIMIT :amount', 'SELECT * FROM t OFFSET -2 ROWS'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_sql(sql, 'datalake')
        for limit in (-1, True, 10_000_002):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                bounded_sql('SELECT 1', 'oracle', limit)

    def test_sqlite_demo_applies_parameters_to_real_rows(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE t (day TEXT, process TEXT, qty INT)')
        connection.executemany('INSERT INTO t VALUES (?,?,?)', [('2026-10-30', 'WB', 10), ('2026-10-31', 'WB', 20), ('2026-10-31', 'DA', 30)])
        source = 'SELECT qty FROM t WHERE day=:day_value AND process IN (:processes)'
        sql = bounded_sql(source, 'sqlite', 10, source_engine='oracle')
        compiled, params = compile_for_engine(sql, {'day_value': '2026-10-31', 'processes': ['WB']}, 'sqlite')
        self.assertEqual(connection.execute(compiled, params).fetchall(), [(20,)])
        compiled, params = compile_for_engine(sql, {'day_value': '2026-10-30', 'processes': ['WB']}, 'sqlite')
        self.assertEqual(connection.execute(compiled, params).fetchall(), [(10,)])


if __name__ == '__main__':
    unittest.main()
