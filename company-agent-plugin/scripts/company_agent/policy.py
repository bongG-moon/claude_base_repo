from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
import re
from pathlib import Path
from typing import Any, Final, Iterator

from .paths import load_json, user_state_root


DB_MARKER: Final = "corp-db-read"
OUTLOOK_MARKER: Final = "corp-outlook-self"

# Server names are deliberately anchored. A tool such as
# `mcp__attacker-corp-db-read__query` is outside this guard's namespace rather
# than accidentally receiving an allow decision intended for the managed MCP.
_DB_TOOL_RE: Final = re.compile(
    r"^mcp__corp-db-read__(?P<operation>[a-z0-9][a-z0-9_.:-]*)$",
    re.IGNORECASE,
)
_OUTLOOK_TOOL_RE: Final = re.compile(
    r"^mcp__corp-outlook-self__(?P<operation>[a-z0-9][a-z0-9_.:-]*)$",
    re.IGNORECASE,
)

_SQL_KEYS: Final = {
    "command",
    "query",
    "querystring",
    "querytext",
    "sql",
    "sqltext",
    "statement",
}
_QUERY_OPERATION_WORDS: Final = {
    "exec",
    "execute",
    "query",
    "run",
    "select",
    "sql",
    "statement",
}
_FORBIDDEN_DB_OPERATION_WORDS: Final = {
    "alter",
    "call",
    "create",
    "delete",
    "drop",
    "insert",
    "merge",
    "truncate",
    "update",
    "write",
}

# These methods are safe without a free-form SQL payload. Keep this explicit;
# generic substring checks such as `"get" in operation` also allow names like
# `get_and_delete`.
_SAFE_DB_METADATA_OPERATIONS: Final = {
    "describe_database",
    "describe_schema",
    "describe_table",
    "describe_view",
    "get_columns",
    "get_database_metadata",
    "get_metadata",
    "get_schema",
    "get_table_schema",
    "get_view_schema",
    "health",
    "health_check",
    "list_columns",
    "list_databases",
    "list_schemas",
    "list_tables",
    "list_views",
    "metadata",
    "ping",
    "show_columns",
    "show_databases",
    "show_schemas",
    "show_tables",
}

FORBIDDEN_SQL_TOKENS: Final = {
    "ALTER",
    "ANALYZE",
    "ATTACH",
    "BEGIN",
    "CALL",
    "COMMIT",
    "COPY",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "EXEC",
    "EXECUTE",
    "GO",
    "GRANT",
    "INSERT",
    "LOCK",
    "MERGE",
    "REPLACE",
    "REVOKE",
    "ROLLBACK",
    "SET",
    "TRUNCATE",
    "UPDATE",
    "UPSERT",
    "USE",
    "VACUUM",
}

_SQL_LEADER_RE: Final = re.compile(
    r"^\s*(?:\(\s*)*(?:SELECT|WITH|EXPLAIN|INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|EXEC(?:UTE)?|CALL|GRANT|REVOKE|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE | re.DOTALL,
)
_SELECT_FROM_RE: Final = re.compile(
    r"\bSELECT\b.+\bFROM\b",
    re.IGNORECASE | re.DOTALL,
)
_SQL_MUTATION_SHAPE_RE: Final = re.compile(
    r"\b(?:DELETE\s+FROM|UPDATE\s+\S+\s+SET|INSERT\s+INTO|MERGE\s+INTO|"
    r"CREATE\s+(?:TABLE|VIEW|INDEX)|ALTER\s+(?:TABLE|VIEW)|"
    r"DROP\s+(?:TABLE|VIEW|INDEX)|EXEC(?:UTE)?\s+\S+)\b",
    re.IGNORECASE | re.DOTALL,
)

_SENDER_ROOT_KEYS: Final = {
    "account",
    "from",
    "fromaddress",
    "fromemail",
    "fromemailaddress",
    "mailbox",
    "sender",
    "senderaddress",
    "senderemail",
}
_EMAIL_LEAF_KEYS: Final = {
    "address",
    "email",
    "emailaddress",
    "fromaddress",
    "fromemail",
    "smtpaddress",
    "upn",
    "useremail",
}
# An internal MCP can expose one of these top-level fields as a schema-managed,
# immutable account identity. An arbitrary nested `account` is treated as a
# normal sender claim, not as authenticated evidence.
_IMMUTABLE_AUTH_ACCOUNT_KEYS: Final = {
    "authenticatedaccount",
    "authenticatedaccountemail",
    "immutableauthenticatedaccount",
}
_SEND_LIKE_WORDS: Final = {"forward", "reply", "resend", "send"}
_SAFE_OUTLOOK_READ_OPERATIONS: Final = {
    "get_attachment",
    "get_mail",
    "get_message",
    "health",
    "health_check",
    "list_folders",
    "list_mail",
    "list_messages",
    "ping",
    "read_mail",
    "read_message",
    "search_mail",
    "search_messages",
}
_OTHER_OUTLOOK_MUTATION_WORDS: Final = {
    "archive",
    "create",
    "delete",
    "draft",
    "mark",
    "move",
    "remove",
    "update",
}


@dataclass(frozen=True)
class _ScalarField:
    key: str
    value: str
    path: tuple[str, ...]


def _canonical_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _normalize_operation(value: str) -> str:
    # MCP tools usually use snake_case, but camelCase names such as sendMail
    # and replyAll are also legal and must not bypass operation checks.
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", words.casefold()).strip("_")


def _operation_words(operation: str) -> set[str]:
    return {part for part in operation.split("_") if part}


def db_operation(tool_name: str) -> str | None:
    match = _DB_TOOL_RE.fullmatch(tool_name.strip())
    return _normalize_operation(match.group("operation")) if match else None


def outlook_operation(tool_name: str) -> str | None:
    match = _OUTLOOK_TOOL_RE.fullmatch(tool_name.strip())
    return _normalize_operation(match.group("operation")) if match else None


def is_outlook_send_like_tool(tool_name: str) -> bool:
    operation = outlook_operation(tool_name)
    return bool(operation and _operation_words(operation).intersection(_SEND_LIKE_WORDS))


def _walk_scalar_fields(value: Any, path: tuple[str, ...] = ()) -> Iterator[_ScalarField]:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = (*path, key)
            if isinstance(child, str):
                yield _ScalarField(key=key, value=child, path=child_path)
            else:
                yield from _walk_scalar_fields(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_scalar_fields(child, (*path, str(index)))


def _strip_sql_literals_and_comments(sql: str) -> str:
    output: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        current = sql[index]
        following = sql[index + 1] if index + 1 < length else ""
        if current == "-" and following == "-":
            index += 2
            while index < length and sql[index] not in "\r\n":
                index += 1
            output.append(" ")
            continue
        if current == "/" and following == "*":
            end = sql.find("*/", index + 2)
            if end < 0:
                raise ValueError("SQL 블록 주석이 닫히지 않았습니다.")
            index = end + 2
            output.append(" ")
            continue
        if current in {"'", '"', "`"}:
            quote = current
            index += 1
            closed = False
            while index < length:
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    closed = True
                    break
                if sql[index] == "\\" and index + 1 < length:
                    index += 2
                else:
                    index += 1
            if not closed:
                raise ValueError("SQL 따옴표가 닫히지 않았습니다.")
            output.append(" ")
            continue
        if current == "[":
            end = sql.find("]", index + 1)
            if end < 0:
                raise ValueError("SQL 식별자 괄호가 닫히지 않았습니다.")
            index = end + 1
            output.append(" IDENT ")
            continue
        output.append(current)
        index += 1
    return "".join(output)


def _looks_like_sql(value: str) -> bool:
    try:
        cleaned = _strip_sql_literals_and_comments(value)
    except ValueError:
        # SQL-looking but malformed text is suspicious in a DB payload.
        return bool(
            re.search(
                r"\b(?:SELECT|WITH|INSERT|UPDATE|DELETE|DROP|EXEC)\b",
                value,
                re.IGNORECASE,
            )
        )
    return bool(
        _SQL_LEADER_RE.search(cleaned)
        or _SELECT_FROM_RE.search(cleaned)
        or _SQL_MUTATION_SHAPE_RE.search(cleaned)
    )


def validate_select_only(sql: str) -> tuple[bool, str]:
    if not isinstance(sql, str):
        return False, "SQL은 문자열이어야 합니다."
    try:
        cleaned = _strip_sql_literals_and_comments(sql).strip()
    except ValueError as exc:
        return False, str(exc)
    if not cleaned:
        return False, "빈 SQL은 실행할 수 없습니다."
    trimmed = cleaned.rstrip().rstrip(";").rstrip()
    if ";" in trimmed:
        return False, "한 번에 하나의 SELECT 문만 실행할 수 있습니다."
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", trimmed.upper())
    if not tokens:
        return False, "SQL 문을 판별할 수 없습니다."
    if any(token in FORBIDDEN_SQL_TOKENS for token in tokens):
        found = next(token for token in tokens if token in FORBIDDEN_SQL_TOKENS)
        return False, f"읽기 전용 정책에서 금지된 SQL 키워드입니다: {found}"
    if tokens[0] not in {"SELECT", "WITH", "EXPLAIN"}:
        return False, "SELECT, WITH ... SELECT 또는 EXPLAIN SELECT만 허용됩니다."
    if "SELECT" not in tokens:
        return False, "SELECT가 포함된 읽기 전용 쿼리만 허용됩니다."
    # SQL Server's SELECT ... INTO creates a table even though the statement
    # begins with SELECT. It must therefore be rejected explicitly.
    if "INTO" in tokens:
        return False, "SQL Server SELECT INTO는 쓰기 작업이므로 허용되지 않습니다."
    return True, "SELECT-only validation passed"


def _extract_email_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _extract_email_values(item)
        return
    if not isinstance(value, dict):
        return
    for raw_key, child in value.items():
        if _canonical_key(raw_key) in _EMAIL_LEAF_KEYS:
            yield from _extract_email_values(child)


def _sender_identities(tool_input: dict[str, Any]) -> list[str]:
    identities: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                if _canonical_key(raw_key) in _SENDER_ROOT_KEYS:
                    identities.extend(_extract_email_values(child))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(tool_input)
    return identities


def _immutable_authenticated_identities(tool_input: dict[str, Any]) -> list[str]:
    identities: list[str] = []
    for raw_key, child in tool_input.items():
        if _canonical_key(raw_key) in _IMMUTABLE_AUTH_ACCOUNT_KEYS:
            identities.extend(_extract_email_values(child))
    return identities


def _normalize_email(value: str) -> str:
    _, parsed = parseaddr(value.strip())
    candidate = (parsed or value).strip().casefold()
    return candidate if re.fullmatch(r"[^\s@]+@[^\s@]+", candidate) else ""


def deny_tool_call(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Company Agent managed policy passed.",
        }
    }


def _ask(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }


def _evaluate_db_call(operation: str, tool_input: Any) -> dict[str, Any]:
    if not isinstance(tool_input, dict):
        return deny_tool_call("corp-db-read 입력 형식을 확인할 수 없어 차단했습니다.")

    operation_words = _operation_words(operation)
    forbidden_operation_words = operation_words.intersection(
        _FORBIDDEN_DB_OPERATION_WORDS
    )
    if forbidden_operation_words:
        return deny_tool_call(
            "corp-db-read 도구 이름에 쓰기 작업이 포함되어 차단했습니다: "
            + ", ".join(sorted(forbidden_operation_words))
        )

    sql_values: list[str] = []
    for field in _walk_scalar_fields(tool_input):
        if _canonical_key(field.key) in _SQL_KEYS:
            sql_values.append(field.value)
        elif _looks_like_sql(field.value):
            return deny_tool_call(
                "등록되지 않은 입력 필드에서 SQL로 보이는 문자열이 발견되어 차단했습니다."
            )

    is_query_operation = bool(
        operation_words.intersection(_QUERY_OPERATION_WORDS)
    )
    if is_query_operation:
        if not sql_values:
            return deny_tool_call(
                "corp-db-read 조회/실행 도구에는 확인 가능한 sql, query, statement 또는 query_text 문자열이 필요합니다."
            )
        for sql in sql_values:
            allowed, reason = validate_select_only(sql)
            if not allowed:
                return deny_tool_call(reason)
        return _allow()

    if sql_values:
        # A metadata or unknown operation should not smuggle executable SQL in
        # a recognized field. Call the explicit query tool instead.
        return deny_tool_call(
            "SQL 문자열은 corp-db-read의 명시적인 조회 도구에서만 사용할 수 있습니다."
        )
    if operation in _SAFE_DB_METADATA_OPERATIONS:
        return _allow()
    return deny_tool_call(
        "corp-db-read에서 명시적으로 허용된 조회 또는 메타데이터 작업이 아닙니다."
    )


def _evaluate_outlook_call(
    operation: str,
    tool_input: Any,
    state_root: Path | None,
) -> dict[str, Any]:
    operation_words = _operation_words(operation)
    if not operation_words.intersection(_SEND_LIKE_WORDS):
        if operation in _SAFE_OUTLOOK_READ_OPERATIONS:
            return _allow()
        if operation_words.intersection(_OTHER_OUTLOOK_MUTATION_WORDS):
            return _ask(
                "메일 발송 이외의 Outlook 변경 작업은 사용자 확인이 필요합니다."
            )
        return _ask(
            "등록되지 않은 Outlook 작업은 자동 승인하지 않습니다. 내용을 확인해 주세요."
        )
    if not isinstance(tool_input, dict):
        return deny_tool_call("Outlook 발신 입력 형식을 확인할 수 없어 차단했습니다.")

    config_root = state_root or user_state_root()
    user_config = load_json(config_root / "config" / "user.json", {}) or {}
    user_email = _normalize_email(str(user_config.get("user_email", "")))
    if not user_email:
        return deny_tool_call(
            "본인 Outlook 계정이 설정되지 않았습니다. Company Agent 사용자 초기화를 먼저 실행하세요."
        )

    claimed = [_normalize_email(item) for item in _sender_identities(tool_input)]
    authenticated = [
        _normalize_email(item)
        for item in _immutable_authenticated_identities(tool_input)
    ]
    identities = claimed + authenticated
    if not identities or any(not identity for identity in identities):
        return deny_tool_call(
            "메일 send/reply/forward에는 확인 가능한 본인 발신 계정 또는 immutable authenticated-account가 필요합니다."
        )
    if any(identity != user_email for identity in identities):
        return deny_tool_call(
            "메일은 등록된 본인 Outlook 계정으로만 발송할 수 있습니다."
        )
    return _allow()


def evaluate_tool_call(
    payload: dict[str, Any],
    state_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return deny_tool_call("관리 MCP 정책 입력을 판별할 수 없어 차단했습니다.")

    tool_name = str(payload.get("tool_name") or "").strip()
    operation = db_operation(tool_name)
    if operation is not None:
        return _evaluate_db_call(operation, payload.get("tool_input"))
    if tool_name.casefold().startswith("mcp__corp-db-read__"):
        return deny_tool_call(
            "corp-db-read 도구 이름 또는 작업을 안전하게 판별할 수 없어 차단했습니다."
        )

    operation = outlook_operation(tool_name)
    if operation is not None:
        return _evaluate_outlook_call(operation, payload.get("tool_input"), state_root)
    if tool_name.casefold().startswith("mcp__corp-outlook-self__"):
        return deny_tool_call(
            "corp-outlook-self 도구 이름 또는 작업을 안전하게 판별할 수 없어 차단했습니다."
        )

    return _allow()
