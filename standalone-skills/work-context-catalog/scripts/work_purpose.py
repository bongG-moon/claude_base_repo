"""Bounded purpose summaries from call metadata and static inline code.

This never executes a command, follows a source path, reads a result or calls a
model. Only a short declared purpose or fixed Korean action labels leave here.
"""
from __future__ import annotations

import ast
import json
import re
import shlex

MAX_TEXT = 240
MAX_INPUT = 32768
MAX_NODES = 3000
BASES = {'invocation_description', 'code_structure', 'target_metadata'}
SHELL_TOOLS = {'bash', 'powershell', 'exec_command', 'shell_command', 'shell'}
SENSITIVE = re.compile(
    r'(?i)(?:token|secret|password|authorization|api[_ -]?key|credentials|private[_ -]?key|'
    r'sk-ant-|ghp_|github_pat_|glpat-|bearer\s)|비밀번호|인증키|접근키|주민등록|'
    r'@|https?://|[A-Za-z]:[\\/]|\\\\|(?:^|\s)[/~][A-Za-z0-9_.-]+/|'
    r'\b\d{9,}\b|[A-Za-z0-9+/=_-]{48,}'
)
GENERIC_DESCRIPTION = re.compile(
    r'(?i)^(?:run|execute|running|check|checking|read|write|python|bash|powershell|'
    r'command|script|code|file|test|tests|실행|파이썬|코드|명령|파일|확인|읽기|쓰기|테스트|\s|[.·:-])+$'
)


def safe_purpose_text(value, clean):
    """Free-text metadata is optional: omit questionable payloads, never crop code."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        return ''
    if SENSITIVE.search(value) or any(c in value for c in '\r\n\x00`{}<>|;='):
        return ''
    if re.search(r'\b(?:import|SELECT|INSERT|UPDATE|DELETE|def|class|function)\s', value):
        return ''
    if re.search(r'[A-Za-z_]\w*\s*\([^)]*\)', value):
        return ''
    if re.match(r'(?i)^\s*(?:python(?:3)?|bash|powershell|node|git|curl|wget)\s+(?:-\S|\w+\.py\b|push\b|pull\b|commit\b)', value):
        return ''
    normalized = ' '.join(value.split())
    if clean(normalized, MAX_TEXT) != normalized or len(normalized) < 5:
        return ''
    return normalized


def normalize_purpose(value, clean):
    """Validate optional imported evidence; legacy records have no such field."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'text', 'basis'} or value.get('basis') not in BASES:
        raise ValueError('invalid execution purpose')
    text = safe_purpose_text(value.get('text'), clean)
    if not text:
        raise ValueError('invalid execution purpose text')
    return {'text': text, 'basis': value['basis']}


def _args(value):
    if isinstance(value, str):
        if len(value) > MAX_INPUT:
            return {}
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return {}
    return value if isinstance(value, dict) else {}


def _shell_parts(command):
    if not isinstance(command, str) or len(command) > MAX_INPUT:
        return []
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return []
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'") else p for p in parts]


def _python_index(parts):
    if not parts:
        return None
    name = parts[0].replace('\\', '/').rsplit('/', 1)[-1].lower()
    if not re.fullmatch(r'(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?', name):
        return None
    i = 1
    while i < len(parts):
        if parts[i] in ('-X', '-W'):
            i += 2
        elif parts[i] in ('-I', '-B', '-u', '-S', '-E', '-s', '-O', '-OO', '-q') or re.fullmatch(r'-3(?:\.\d+)?', parts[i]):
            i += 1
        else:
            break
    return i


def _inline_python(command):
    """Recognize one Python -c or a complete, quoted heredoc; no shell expansion."""
    parts = _shell_parts(command)
    index = _python_index(parts)
    if index is not None and parts[index:index + 1] == ['-c'] and len(parts) == index + 2:
        return parts[index + 1]
    if not isinstance(command, str) or len(command) > MAX_INPUT:
        return ''
    match = re.fullmatch(r'([^\r\n]+)\s+<<\s*([\'\"])([A-Za-z_][A-Za-z0-9_]*)\2\s*\r?\n([\s\S]*?)\r?\n\3\s*', command.strip())
    if match:
        prefix = _shell_parts(match[1])
        index = _python_index(prefix)
        if index is not None and prefix[index:] in ([], ['-']):
            return match[4]
    return ''


class _Actions(ast.NodeVisitor):
    """Track explicit pandas/Path imports and simple assignments, never execute."""
    READERS = {'read_csv': 'CSV 표를 읽고', 'read_excel': 'Excel 표를 읽고',
               'read_json': 'JSON 표를 읽고'}
    METHODS = {
        'drop_duplicates': '중복 행을 제거하고', 'dropna': '빈 값이 있는 행·열을 제외하고',
        'fillna': '빈 값을 보완하고', 'groupby': '같은 기준의 행을 묶고',
        'agg': '묶음별 값을 집계하고', 'aggregate': '값을 집계하고',
        'sum': '합계를 계산하고', 'mean': '평균을 계산하고',
        'count': '값의 개수를 세고', 'size': '행의 개수를 세고',
        'merge': '기준이 같은 표를 연결하고', 'join': '표를 연결하고',
        'sort_values': '값을 기준으로 순서를 정렬하고', 'sort_index': '행·열 기준을 정렬하고',
        'rename': '열·행 이름을 바꾸고', 'astype': '값의 자료형을 바꾸고',
        'query': '조건에 맞는 행을 선택하고', 'filter': '조건에 맞는 항목을 선택하고',
        'pivot_table': '분류별 요약표를 구성하고', 'pivot': '행·열 구조를 재배치하고',
    }
    EXPORTS = {'to_csv': 'CSV 결과를 저장하고', 'to_excel': 'Excel 결과를 저장하고',
               'to_json': 'JSON 결과를 저장하고', 'to_html': 'HTML 표를 작성하고'}
    FUNCTIONS = {'concat': '표를 이어 붙이고', 'merge': METHODS['merge'],
                 'to_numeric': '숫자 형식으로 바꾸고', 'to_datetime': '날짜 형식으로 바꾸고',
                 'pivot_table': METHODS['pivot_table']}
    PATH_METHODS = {'read_text': '텍스트 파일의 내용을 읽고', 'read_bytes': '파일 바이트를 읽고',
                    'write_text': '텍스트 결과 파일을 쓰고', 'write_bytes': '결과 파일을 쓰고',
                    'mkdir': '결과 폴더를 준비하고'}

    def __init__(self):
        self.labels = []
        self.bindings = {}

    def add(self, label):
        if label not in self.labels and len(self.labels) < 7:
            self.labels.append(label)

    def visit_FunctionDef(self, node):
        # A definition is dormant; defining it can shadow an imported name.
        if hasattr(node, 'name'):
            self.bindings.pop(node.name, None)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_Import(self, node):
        for item in node.names:
            binding = item.asname or item.name.split('.')[0]
            self.bindings.pop(binding, None)
            if item.name in ('pandas', 'pathlib'):
                self.bindings[binding] = item.name

    def visit_ImportFrom(self, node):
        for item in node.names:
            binding = item.asname or item.name
            self.bindings.pop(binding, None)
            if node.level == 0 and node.module == 'pandas' and item.name in {*self.READERS, *self.FUNCTIONS, 'DataFrame', 'Series'}:
                self.bindings[binding] = 'pandas:' + item.name
            elif node.level == 0 and node.module == 'pathlib' and item.name == 'Path':
                self.bindings[binding] = 'Path'

    def _bind(self, target, kind):
        if isinstance(target, ast.Name):
            self.bindings.pop(target.id, None)
            if kind:
                self.bindings[target.id] = kind
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind(item, '')
        elif isinstance(target, ast.Attribute):
            # Monkey-patching an imported module or instance invalidates its type.
            self._bind(target.value, '')

    def visit_Assign(self, node):
        self.visit(node.value)
        kind = self._kind(node.value)
        for target in node.targets:
            self._bind(target, kind)

    def visit_AnnAssign(self, node):
        if node.value:
            self.visit(node.value)
        self._bind(node.target, self._kind(node.value))

    def visit_AugAssign(self, node):
        self.visit(node.value)
        self._bind(node.target, '')

    def visit_NamedExpr(self, node):
        self.visit(node.value)
        self._bind(node.target, self._kind(node.value))

    def visit_Delete(self, node):
        for target in node.targets:
            self._bind(target, '')

    def visit_If(self, node):
        self.visit(node.test)
        original = dict(self.bindings)
        states = []
        for branch in (node.body, node.orelse):
            self.bindings = dict(original)
            for statement in branch:
                self.visit(statement)
            states.append(dict(self.bindings))
        self.bindings = {name: kind for name, kind in states[0].items() if states[1].get(name) == kind}

    def visit_For(self, node):
        self.visit(node.iter)
        original = dict(self.bindings)
        self._bind(node.target, '')
        for statement in (*node.body, *node.orelse):
            self.visit(statement)
        self.bindings = {name: kind for name, kind in original.items() if self.bindings.get(name) == kind}

    def visit_While(self, node):
        self.visit(node.test)
        original = dict(self.bindings)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)
        self.bindings = {name: kind for name, kind in original.items() if self.bindings.get(name) == kind}

    def _kind(self, node):
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id, '')
        if isinstance(node, ast.Call):
            return self._call(node)[0]
        if isinstance(node, ast.Subscript) and self._kind(node.value) == 'frame':
            return 'frame'
        if isinstance(node, ast.Attribute):
            receiver = self._kind(node.value)
            if receiver == 'frame' and node.attr in ('loc', 'iloc'):
                return 'frame'
            if receiver == 'path' and node.attr in ('parent',):
                return 'path'
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and self._kind(node.left) == 'path':
            return 'path'
        return ''

    def _call(self, node):
        if isinstance(node.func, ast.Name):
            binding = self.bindings.get(node.func.id, '')
            if binding == 'Path':
                return 'path', ''
            receiver, _, name = binding.partition(':')
        elif isinstance(node.func, ast.Attribute):
            receiver, name = self._kind(node.func.value), node.func.attr
        else:
            return '', ''
        if receiver == 'pandas':
            if name in ('DataFrame', 'Series'):
                return 'frame', ''
            if name in self.READERS:
                return 'frame', self.READERS[name]
            if name in self.FUNCTIONS:
                return 'frame', self.FUNCTIONS[name]
        elif receiver == 'frame':
            if name in self.METHODS:
                return 'frame', self.METHODS[name]
            if name in self.EXPORTS:
                return '', self.EXPORTS[name]
            if name in ('copy', 'reset_index', 'set_index', 'head', 'tail'):
                return 'frame', ''
        elif receiver == 'pathlib' and name == 'Path':
            return 'path', ''
        elif receiver == 'path':
            if name in self.PATH_METHODS:
                return '', self.PATH_METHODS[name]
            if name in ('joinpath', 'resolve', 'absolute', 'with_name', 'with_suffix'):
                return 'path', ''
        return '', ''

    def visit_Call(self, node):
        # A chained receiver is evaluated before the outer call.
        self.generic_visit(node)
        _, label = self._call(node)
        if label:
            self.add(label)


def _code_purpose(code):
    if not code or len(code) > MAX_INPUT:
        return None
    try:
        tree = ast.parse(code)
        for index, _ in enumerate(ast.walk(tree), 1):
            if index > MAX_NODES:
                return None
        actions = _Actions()
        actions.visit(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    if not actions.labels:
        return None
    # A statically recognized branch may not have been reached at run time.
    text = '코드는 ' + ', '.join(actions.labels[:-1] + [actions.labels[-1][:-1] + '도록 작성돼 있습니다.'])
    text += ' 실제 처리 여부는 별도 확인이 필요합니다.'
    return {'text': text[:MAX_TEXT], 'basis': 'code_structure'}


def explain_purpose(tool, payload, clean, target=''):
    """Return purpose evidence only; never infer the business task succeeded."""
    args = _args(payload)
    name = tool.rsplit('.', 1)[-1].lower()
    # Prefer observed code structure to a potentially optimistic call label.
    if name in SHELL_TOOLS:
        command = args.get('command', args.get('cmd', ''))
        evidence = _code_purpose(_inline_python(command))
        if evidence:
            return evidence
    # A declared purpose supplies business intent when code is not available.
    for key in ('description', 'title'):
        text = safe_purpose_text(args.get(key), clean)
        if text and not GENERIC_DESCRIPTION.fullmatch(text):
            return {'text': text, 'basis': 'invocation_description'}
    if name in SHELL_TOOLS:
        command = args.get('command', args.get('cmd', ''))
        parts = _shell_parts(command)
        index = _python_index(parts)
        if index is not None and parts[index:index + 2] in (['-m', 'unittest'], ['-m', 'pytest']):
            if not any(re.search(r'[;&|\r\n]', p) for p in parts[index + 2:]):
                return {'text': '자동 테스트를 실행해 코드의 동작이 기대한 결과와 일치하는지 확인하려는 요청입니다.', 'basis': 'code_structure'}
        return None
    if target and not target.startswith('['):
        suffix = {
            'read': '의 내용을 확인하려는 요청입니다.',
            'read_file': '의 내용을 확인하려는 요청입니다.',
            'view_image': ' 이미지의 내용을 확인하려는 요청입니다.',
            'write': ' 파일에 결과를 작성하려는 요청입니다.',
            'write_file': ' 파일에 결과를 작성하려는 요청입니다.',
            'edit': ' 파일의 일부 내용을 수정하려는 요청입니다.',
            'multiedit': ' 파일의 일부 내용을 수정하려는 요청입니다.',
            'skill': '에 정의된 절차를 불러와 이번 작업에 참고하려는 요청입니다.',
        }.get(name)
        if suffix:
            text = safe_purpose_text(target + suffix, clean)
            if text:
                return {'text': text, 'basis': 'target_metadata'}
    return None
