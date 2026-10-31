"""조회 SQL과 조건을 검사한다. 실제 읽기 전용 권한은 DB에서도 제한해야 한다."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
import logging
import re
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel
from sqlglot.optimizer.scope import traverse_scope

MAX_SQL_CHARS = 40_000
MAX_PARAMS = 100
MAX_LIST = 500
MAX_TEXT = 8_000
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_BIND = re.compile(r"(?<!:):([A-Za-z][A-Za-z0-9_]*)\b")
_MYSQL_MAPPING = re.compile(r'%\([^)]+\)[diouxXeEfFgGcrs%]')
_SCALAR_TYPES = {'text', 'str', 'string', 'int', 'integer', 'decimal', 'number', 'float',
                 'date', 'datetime', 'timestamp'}
_RESERVED = {'select', 'from', 'where', 'order', 'group', 'having', 'union', 'limit',
             'offset', 'join', 'table', 'user', 'date', 'null', 'true', 'false'}
_DANGEROUS_FUNCTIONS = {'load_file', 'sleep', 'benchmark', 'sys_eval', 'sys_exec',
                        'nextval', 'setval', 'next_value_for', 'pg_read_file',
                        'pg_read_binary_file', 'pg_ls_dir', 'readfile', 'writefile'}


@contextmanager
def _quiet_parser():
    # 파서의 지원 불가 경고에는 원문 SQL이 포함될 수 있다. 외부에는 정해진 오류만 보낸다.
    logger = logging.getLogger('sqlglot')
    suppress = lambda record: False
    logger.addFilter(suppress)
    try:
        yield
    finally:
        logger.removeFilter(suppress)


def dialect(engine: str) -> str:
    """사용자에게 보이는 서비스 이름을 SQL 문법 이름으로 바꾼다."""
    names = {'oracle': 'oracle', 'datalake': 'starrocks', 'ehub': 'starrocks',
             'lakehouse': 'starrocks', 'starrocks': 'starrocks', 'mysql': 'starrocks',
             'sqlite': 'sqlite', 'demo': 'sqlite'}
    if engine not in names:
        raise ValueError('지원하는 조회 연결 종류를 선택해 주세요.')
    return names[engine]


def _parts(sql: str):
    """문자열 안의 :기호와 주석을 실제 바인드 조건으로 오인하지 않는다."""
    index = start = 0
    while index < len(sql):
        end = index
        kind = ''
        if sql.startswith('--', index):
            kind = 'comment'
            end = sql.find('\n', index)
            end = len(sql) if end < 0 else end + 1
        elif sql.startswith('/*', index):
            kind = 'comment'
            if sql[index:index + 3] in {'/*!', '/*+'}:
                raise ValueError('실행 주석과 힌트를 제외한 조회 SQL을 등록해 주세요.')
            end = sql.find('*/', index + 2)
            if end < 0:
                raise ValueError('SQL 주석이 닫히지 않았습니다.')
            end += 2
        elif sql[index:index + 2].lower() == "q'" and index + 2 < len(sql):
            kind = 'qstring'
            closer = {'[': ']', '(': ')', '{': '}', '<': '>'}.get(sql[index + 2], sql[index + 2])
            end = sql.find(closer + "'", index + 3)
            if end < 0:
                raise ValueError('SQL 문자열이 닫히지 않았습니다.')
            end += 2
        elif sql[index] in "'\"`":
            quote = sql[index]
            kind = 'string' if quote == "'" else 'identifier'
            end = index + 1
            while end < len(sql):
                if sql[end] == quote:
                    if end + 1 < len(sql) and sql[end + 1] == quote:
                        end += 2
                        continue
                    end += 1
                    break
                if sql[end] == '\\':
                    # Oracle/MySQL 간 해석 차이가 있는 SQL 리터럴은 추측하지 않는다.
                    raise ValueError('SQL 문자열의 역슬래시는 바인드 조건으로 옮겨 주세요.')
                end += 1
            else:
                raise ValueError('SQL 문자열 또는 식별자가 닫히지 않았습니다.')
        if kind:
            if start < index:
                yield 'code', sql[start:index]
            yield kind, sql[index:end]
            index = start = end
        else:
            index += 1
    if start < len(sql):
        yield 'code', sql[start:]


def _name(value: Any) -> str:
    if (not isinstance(value, str) or not _NAME.fullmatch(value)
            or value.casefold() in _RESERVED or value.casefold().startswith('qsbind_')):
        raise ValueError('조건 이름은 영문자로 시작하는 1~64자 이름을 사용해 주세요. SQL 예약어는 사용할 수 없습니다.')
    return value


def _tree(sql: str, engine: str) -> exp.Expression:
    engine = dialect(engine)
    if not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL_CHARS or '\x00' in sql:
        raise ValueError('조회 SQL은 비어 있지 않은 40,000자 이하 텍스트여야 합니다.')
    parts = list(_parts(sql))
    # q 문자열을 같은 내용의 일반 SQL 리터럴로 바꾸어 파서에 전달한다.
    parse_sql = ''.join(' ' if kind == 'comment' else
                        "'" + text[3:-2].replace("'", "''") + "'" if kind == 'qstring'
                        else text for kind, text in parts)
    code = ' '.join(text for kind, text in parts if kind == 'code')
    if re.search(r'%\([^)]+\)s|%s|\?|(?<!:)\:[0-9]|\$[0-9]|\{\{?', code):
        raise ValueError('조회 조건은 :start_date처럼 이름을 가진 바인드 형식으로 등록해 주세요.')
    if re.search(r'\bINTO\s+(?:OUTFILE|DUMPFILE)\b|\bFOR\s+(?:UPDATE|SHARE)\b|\bLOCK\s+IN\b', code, re.I):
        raise ValueError('행 잠금과 파일 출력 SQL은 조회 스킬에서 실행하지 않습니다.')
    lexical_names = [match.group(1) for kind, text in _parts(parse_sql) if kind == 'code' for match in _BIND.finditer(text)]
    for name in lexical_names:
        _name(name)
    parse_names = {name: f'qsparse_{i}' for i, name in enumerate(dict.fromkeys(lexical_names))}
    reverse_names = {replacement: name for name, replacement in parse_names.items()}
    parser_sql = ''.join(_BIND.sub(lambda match: ':' + parse_names[match.group(1)], text) if kind == 'code' else text
                         for kind, text in _parts(parse_sql))
    try:
        with _quiet_parser():
            trees = [tree for tree in sqlglot.parse(parser_sql, read=engine, error_level=ErrorLevel.RAISE) if tree is not None]
    except Exception:
        raise ValueError('SQL 문법을 확인해 주세요. 해당 연결의 단일 SELECT 또는 WITH 조회가 필요합니다.') from None
    if len(trees) != 1 or not isinstance(trees[0], (exp.Select, exp.SetOperation)):
        raise ValueError('데이터 변경 없이 단일 SELECT 또는 WITH 조회만 실행할 수 있습니다.')
    tree = trees[0]
    for node in tree.find_all(exp.Placeholder):
        if node.name in reverse_names:
            node.set('this', reverse_names[node.name])
    denied_types = tuple(getattr(exp, name) for name in
                         ('DDL', 'DML', 'Command', 'Into', 'Lock', 'Set', 'Use', 'Transaction', 'Copy', 'Execute', 'Hint')
                         if hasattr(exp, name))
    names = []
    for node in tree.walk():
        if isinstance(node, denied_types):
            raise ValueError('데이터 변경, 행 잠금, 파일 출력과 실행 명령은 허용하지 않습니다.')
        if isinstance(node, exp.Column) and node.name.upper() in {'NEXTVAL', 'CURRVAL'}:
            raise ValueError('시퀀스 상태에 의존하는 조회는 이 스킬에서 지원하지 않습니다.')
        if isinstance(node, exp.Identifier) and node.name.upper().startswith(('DBMS_', 'UTL_')):
            raise ValueError('관리 또는 외부 통신 패키지는 조회 스킬에서 호출하지 않습니다.')
        if isinstance(node, exp.Func):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            if str(name).casefold() in _DANGEROUS_FUNCTIONS:
                raise ValueError('외부 접근, 대기 또는 상태를 바꾸는 함수는 실행하지 않습니다.')
        if isinstance(node, exp.Table) and not isinstance(node.this, exp.Identifier):
            raise ValueError('테이블은 고정된 이름으로 지정해 주세요. 테이블 함수나 동적 테이블은 지원하지 않습니다.')
        if isinstance(node, exp.Placeholder):
            name = _name(node.name)
            if isinstance(node.parent, (exp.Table, exp.Column)):
                raise ValueError('테이블과 컬럼 이름은 바인드 조건으로 바꾸지 않습니다.')
            names.append(name)
        if isinstance(node, (exp.Limit, exp.Fetch, exp.Offset)):
            value = node.expression if not isinstance(node, exp.Fetch) else node.args.get('count')
            if value is None and isinstance(node, exp.Fetch):
                continue
            if not isinstance(value, exp.Literal) or not value.is_int or int(value.this) < 0:
                raise ValueError('행 제한과 OFFSET은 0 이상의 고정 정수로 등록해 주세요.')
    if len(set(names)) > MAX_PARAMS:
        raise ValueError('조회 조건은 최대 100개까지 등록할 수 있습니다.')
    if len({name.casefold() for name in names}) != len(set(names)):
        raise ValueError('대소문자만 다른 조회 조건 이름은 함께 사용할 수 없습니다.')
    # 정적 문장 분리가 누락된 숫자/빈 이름 바인드를 감추지 않도록 파서와 비교한다.
    if set(lexical_names) != set(names):
        raise ValueError('조회 조건 위치를 확인해 주세요. 값 위치에 :조건이름을 사용하세요.')
    return tree


def _render(tree: exp.Expression, engine: str) -> str:
    try:
        with _quiet_parser():
            return tree.sql(dialect=dialect(engine), comments=False, unsupported_level=ErrorLevel.RAISE)
    except Exception:
        raise ValueError('이 조회 구문은 선택한 연결에서 지원하지 않습니다.') from None


def validate_sql(sql: str, engine: str) -> str:
    """실행 가능한 단일 읽기 SQL만 정규화한다. 값의 의미는 바꾸지 않는다."""
    return _render(_tree(sql, engine), engine)


def parameter_names(sql: str, engine: str) -> list[str]:
    tree = _tree(sql, engine)
    return list(dict.fromkeys(node.name for node in tree.walk() if isinstance(node, exp.Placeholder)))


def _restrictive_predicate(node: exp.Expression | None) -> bool:
    if node is None:
        return False
    if isinstance(node, (exp.Where, exp.Paren)):
        return _restrictive_predicate(node.this)
    if isinstance(node, exp.And):
        return _restrictive_predicate(node.this) or _restrictive_predicate(node.expression)
    if isinstance(node, exp.Or):
        return _restrictive_predicate(node.this) and _restrictive_predicate(node.expression)
    if isinstance(node, exp.EQ) and node.this == node.expression:
        return False
    if isinstance(node, exp.Like) and isinstance(node.expression, exp.Literal) and set(node.expression.this) == {'%'}:
        return False
    return any(isinstance(part, exp.Column) for part in node.walk())


def analyze_sql(sql: str, engine: str) -> dict:
    """넓은 조회는 거절 대신 사용자 확인 대상으로 분류한다."""
    tree = _tree(sql, engine)
    risks = []
    advisories = []
    candidates = []
    try:
        scopes = [(scope.expression, [source for _, source in scope.selected_sources.values()])
                  for scope in traverse_scope(tree) if isinstance(scope.expression, exp.Select)]
    except Exception:
        raise ValueError('조회에 같은 이름의 테이블 별칭이 겹치지 않는지 확인해 주세요.') from None
    for select, sources in scopes:
        # 조건이 있는 CTE/하위 조회를 읽는 외부 SELECT에 조건을 다시 요구하지 않는다.
        # 실제 원본 테이블을 읽는 각 내부 범위는 별도로 검사한다.
        has_real_source = any(isinstance(source, exp.Table) and source.name.casefold() != 'dual'
                              for source in sources)
        has_any_source = bool(sources)
        where = select.args.get('where')
        # WHERE 1=1이나 조건 없는 UNION 분기도 넓은 조회로 표시한다.
        has_column_condition = _restrictive_predicate(where)
        if has_real_source and not has_column_condition:
            risks.append('조회 조건이 없는 데이터 범위가 있습니다.')
        for join in select.args.get('joins') or []:
            if str(join.args.get('kind', '')).upper() == 'CROSS' or not (join.args.get('on') or join.args.get('using')):
                risks.append('결합 조건이 없는 조인이 있습니다.')
        if has_any_source and (select.args.get('group') or any(isinstance(n, exp.AggFunc) for n in select.walk())):
            advisories.append('집계는 반환 건수가 적어도 많은 원본을 읽을 수 있습니다.')
        if has_any_source and select.args.get('order'):
            advisories.append('정렬에 필요한 전체 범위를 확인해야 합니다.')
        if where:
            for node in where.walk():
                if isinstance(node, exp.Column):
                    entry = {'column': node.name, 'kind': '조건 컬럼'}
                    if entry not in candidates:
                        candidates.append(entry)
    for node in tree.find_all(exp.Offset):
        if isinstance(node.expression, exp.Literal) and int(node.expression.this) > 10_000:
            risks.append('건너뛰는 행이 많아 조회 비용이 커질 수 있습니다.')
    if any(isinstance(n, exp.Anonymous) for n in tree.walk()):
        risks.append('사용자 함수의 동작은 DB의 조회 전용 권한으로도 확인해야 합니다.')
    if any(node.args.get('recursive') for node in tree.find_all(exp.With)):
        risks.append('재귀 조회의 반복 범위와 종료 조건을 확인해야 합니다.')
    return {'parameters': parameter_names(sql, engine), 'riskReasons': list(dict.fromkeys(risks)),
            'conditionCandidates': candidates[:50], 'advisories': list(dict.fromkeys(advisories))}


def _definitions(definitions) -> dict:
    if isinstance(definitions, list):
        output = {}
        for item in definitions:
            if not isinstance(item, dict) or 'name' not in item:
                raise ValueError('조건 정의의 이름이 없거나 중복되었습니다.')
            name = _name(item['name'])
            if name in output:
                raise ValueError('조건 정의의 이름이 없거나 중복되었습니다.')
            output[name] = {key: value for key, value in item.items() if key != 'name'}
        definitions = output
    if not isinstance(definitions, dict):
        raise ValueError('조회 조건 정의는 이름별 객체여야 합니다.')
    if len(definitions) > MAX_PARAMS:
        raise ValueError('조회 조건 정의가 너무 많습니다.')
    output = {}
    for name, definition in definitions.items():
        _name(name)
        if isinstance(definition, str):
            definition = {'type': definition}
        if not isinstance(definition, dict):
            raise ValueError('조회 조건마다 자료형을 지정해 주세요.')
        kind = definition.get('type', 'text')
        if not isinstance(kind, str):
            raise ValueError('조회 조건의 자료형을 text, int, decimal, date, datetime 또는 list로 지정해 주세요.')
        kind = kind.lower()
        is_list = kind == 'list' or kind.startswith('list[') and kind.endswith(']')
        if is_list:
            item_kind = kind[5:-1] if kind != 'list' else definition.get('item_type', 'text')
            if not isinstance(item_kind, str) or item_kind.lower() not in _SCALAR_TYPES:
                raise ValueError('목록 안의 자료형은 text, int, decimal, date 또는 datetime으로 지정해 주세요.')
        elif kind not in _SCALAR_TYPES:
            raise ValueError('조회 조건의 자료형을 text, int, decimal, date, datetime 또는 list로 지정해 주세요.')
        for flag in ('required', 'nullable'):
            if flag in definition and type(definition[flag]) is not bool:
                raise ValueError('필수 여부와 빈 값 허용 여부는 true 또는 false로 지정해 주세요.')
        if 'choices' in definition and (not isinstance(definition['choices'], list)
                                        or not 1 <= len(definition['choices']) <= MAX_LIST):
            raise ValueError('허용 값은 1~500개 값의 목록으로 지정해 주세요.')
        output[name] = dict(definition, type=kind)
        if is_list and kind == 'list':
            output[name]['item_type'] = item_kind.lower()
    return output


def _scalar(value, kind: str, definition: dict):
    if value is None:
        if definition.get('nullable') is True:
            return None
        raise ValueError('빈 조회 조건은 사용할 수 없습니다.')
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)):
        raise ValueError('조회 조건의 자료형을 확인해 주세요.')
    try:
        if kind in {'text', 'str', 'string'}:
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT or '\x00' in value:
                raise ValueError()
            result = value  # 코드와 식별자의 대소문자 및 공백은 임의 수정하지 않는다.
        elif kind in {'int', 'integer'}:
            if not (type(value) is int or isinstance(value, str) and re.fullmatch(r'[+-]?\d{1,38}', value)):
                raise ValueError()
            result = int(value)
            if len(str(abs(result))) > 38:
                raise ValueError()
        elif kind in {'decimal', 'number', 'float'}:
            if not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 100:
                raise ValueError()
            result = Decimal(str(value))
            if not result.is_finite() or abs(result.adjusted()) > 300:
                raise ValueError()
        elif kind == 'date':
            if isinstance(value, datetime):
                raise ValueError()
            result = value if isinstance(value, date) else date.fromisoformat(value)
        elif kind in {'datetime', 'timestamp'}:
            result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
            if result.tzinfo is not None:
                raise ValueError()  # DB 시간대가 확정되지 않았으므로 자동 변환하지 않는다.
        else:
            raise ValueError()
        if 'choices' in definition and result not in [_scalar(item, kind, {}) for item in definition['choices']]:
            raise ValueError()
        return result
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise ValueError('조회 조건을 등록한 자료형과 허용 값에 맞게 입력해 주세요.') from None


def bind_params(sql: str, definitions, values: dict, engine: str) -> dict:
    """필수 조건을 검증하고 DB 드라이버가 받을 자료형으로 바꾼다."""
    names = parameter_names(sql, engine)
    specs = _definitions(definitions)
    if not isinstance(values, dict) or set(values) - set(names) or set(specs) != set(names):
        raise ValueError('SQL의 조건 이름과 등록한 조건 및 입력값을 확인해 주세요.')
    result = {}
    for name in names:
        spec = specs[name]
        if name in values:
            value = values[name]
        elif 'default' in spec:
            value = spec['default']
        elif spec.get('required') is False and spec.get('nullable') is True:
            value = None
        else:
            raise ValueError('필수 조회 조건을 입력해 주세요.')
        kind = str(spec.get('type', 'text')).lower()
        if kind == 'list' or kind.startswith('list[') and kind.endswith(']'):
            if not isinstance(value, list) or not 1 <= len(value) <= MAX_LIST:
                raise ValueError('목록 조건은 1~500개 값으로 입력해 주세요.')
            item_kind = kind[5:-1] if kind != 'list' else str(spec.get('item_type', 'text'))
            item_spec = {'nullable': False}
            result[name] = [_scalar(item, item_kind, item_spec) for item in value]
        else:
            result[name] = _scalar(value, kind, spec)
    return result


def compile_for_engine(sql: str, params: dict, engine: str, *, source_engine: str | None = None) -> tuple[str, dict]:
    """SQL 값은 쿼리 문자열에 넣지 않고 드라이버 바인드로만 전달한다."""
    tree = _tree(sql, source_engine or engine)
    names = {node.name for node in tree.walk() if isinstance(node, exp.Placeholder)}
    if not isinstance(params, dict) or set(params) != names:
        raise ValueError('실행 SQL의 조건과 입력값이 일치하지 않습니다.')
    expanded = dict(params)
    for name, values in params.items():
        if not isinstance(values, (list, tuple)):
            continue
        if not 1 <= len(values) <= MAX_LIST:
            raise ValueError('목록 조건은 1~500개 값으로 입력해 주세요.')
        placeholders = [node for node in tree.walk() if isinstance(node, exp.Placeholder) and node.name == name]
        for node in placeholders:
            parent = node.parent
            if not isinstance(parent, exp.In) or len(parent.expressions) != 1 or parent.expressions[0] is not node:
                raise ValueError('목록 조건은 IN (:조건이름) 안에서 단독으로 사용해 주세요.')
            parent.set('expressions', [exp.Placeholder(this=f'qsbind_{name}_{i}') for i in range(len(values))])
        del expanded[name]
        expanded.update({f'qsbind_{name}_{i}': value for i, value in enumerate(values)})
    rendered = _render(tree, engine)
    if dialect(engine) == 'starrocks':
        # mysql.connector의 사전 바인딩은 %(name)s만 치환한다. 일반 %를 늘리면 안 된다.
        # 드라이버가 문자열 안의 매핑 표기까지 치환하므로 애매한 상수는 값 바인드로 받는다.
        if params and _MYSQL_MAPPING.search(rendered):
            raise ValueError('SQL 상수 안의 %(...) 표기는 별도 바인드 조건 값으로 전달해 주세요.')
        rendered = ''.join(_BIND.sub(lambda match: '%(' + match.group(1) + ')s', text) if kind == 'code' else text
                           for kind, text in _parts(rendered))
    return rendered, expanded


def bounded_sql(sql: str, engine: str, limit: int, *, source_engine: str | None = None) -> str:
    """외부 제한을 붙여 기존의 더 작은 LIMIT과 쿼리 의미를 보존한다."""
    if type(limit) is not int or not 0 <= limit <= 10_000_001:
        raise ValueError('조회 행 제한은 0~10,000,001 사이의 정수여야 합니다.')
    rendered = _render(_tree(sql, source_engine or engine), engine)
    if dialect(engine) == 'oracle':
        return f'SELECT * FROM ({rendered}) qs_rows WHERE ROWNUM <= {limit}'
    return f'SELECT * FROM ({rendered}) AS qs_rows LIMIT {limit}'
