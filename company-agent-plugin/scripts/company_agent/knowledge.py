from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .frontmatter import MarkdownDocument, dump_frontmatter, load_markdown, parse_frontmatter_text
from .paths import atomic_write_json, atomic_write_text, ensure_user_layout, load_json


KNOWLEDGE_KINDS = {
    "term",
    "table",
    "join",
    "metric",
    "business_rule",
    "knowledge_overlay",
}
ALLOWED_STATUS = {"active", "draft", "deprecated", "example"}
ALLOWED_OVERLAY_MODES = {"extend", "fork", "personal-new"}
COMMON_REQUIRED = {"kind", "id", "title", "owner", "status"}
KIND_REQUIRED = {
    "term": set(),
    "table": {"system", "schema", "table", "grain"},
    "join": {"left", "right", "cardinality", "preserves_left_grain"},
    "metric": {"domain"},
    "business_rule": {"domain"},
    "knowledge_overlay": {"mode", "scope"},
}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(server|data source)\s*=.+;(?:.*)(password|pwd)\s*="),
)
FORBIDDEN_SQL = re.compile(
    r"(?i)\b(insert|update|delete|merge|upsert|create|alter|drop|truncate|grant|revoke|execute|exec|call)\b"
)
MAX_CATALOG_SEARCH_TEXT_CHARS = 50_000
MAX_CATALOG_QUERY_CHARS = 10_000
MAX_CATALOG_QUERY_TOKENS = 32
MAX_CATALOG_RESULTS = 20

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
WINDOWS_USER_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\r\n\s]+")
POSIX_USER_PATH_PATTERN = re.compile(r"(?i)(?<![\w/])/(?:home|Users)/[^/\r\n\s]+")
SESSION_VALUE_PATTERN = re.compile(
    r"(?i)\b(session(?:[_ -]?id)?|conversation[_ -]?id|thread[_ -]?id)\s*[:=]\s*[\"']?[A-Za-z0-9._:-]{4,}[\"']?"
)
SESSION_METADATA_KEYS = {
    "session",
    "sessionid",
    "sourcesession",
    "sourcesessionid",
    "createdfromsession",
    "conversationid",
    "threadid",
}


@dataclass(frozen=True)
class KnowledgeIssue:
    level: str
    code: str
    message: str
    path: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def text_sha256(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = {part.lower() for part in relative.parts[:-1]}
    return bool(parts & {"templates", "generated", "generated-index", ".claude", ".git", "versions", "exports"})


def discover_documents(root: Path | None) -> tuple[list[MarkdownDocument], list[KnowledgeIssue]]:
    documents: list[MarkdownDocument] = []
    issues: list[KnowledgeIssue] = []
    if root is None or not root.exists():
        return documents, issues
    for path in sorted(root.rglob("*.md")):
        if _ignored(path, root):
            continue
        try:
            head = path.read_text(encoding="utf-8-sig")[:4]
            if not head.startswith("---"):
                continue
            documents.append(load_markdown(path))
        except (OSError, UnicodeError, ValueError) as exc:
            issues.append(KnowledgeIssue("error", "invalid_markdown", str(exc), str(path)))
    return documents, issues


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _is_active(document: MarkdownDocument) -> bool:
    return str(document.metadata.get("status", "")) == "active"


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _flatten_search_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _flatten_search_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten_search_values(item)
    elif value not in (None, ""):
        yield str(value)


def _document_search_text(document: MarkdownDocument) -> str:
    searchable_fields = (
        "id",
        "kind",
        "title",
        "aliases",
        "tags",
        "domain",
        "system",
        "schema",
        "table",
        "grain",
        "columns",
        "column",
        "left",
        "right",
        "cardinality",
    )
    values: list[str] = []
    for field in searchable_fields:
        values.extend(_flatten_search_values(document.metadata.get(field)))
    values.append(document.body)
    return re.sub(r"\s+", " ", " ".join(values)).strip()[:MAX_CATALOG_SEARCH_TEXT_CHARS]


def _base_contract_hash(document: MarkdownDocument) -> str:
    """Hash semantic metadata and body used by a personal extension.

    Automatic rebase is intentionally conservative: only operational metadata
    may change without review. A body, column, rule, alias, or relationship
    change can alter the meaning of an existing personal extension.
    """

    operational_fields = {
        "owner",
        "updated_at",
        "updatedAt",
        "reviewed_at",
        "reviewedAt",
        "pack_version",
        "revision",
    }
    contract: dict[str, Any] = {
        "metadata": {
            str(key): value
            for key, value in document.metadata.items()
            if str(key) not in operational_fields
        },
        "body": document.body.replace("\r\n", "\n").strip(),
    }
    rendered = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text_sha256(rendered)


def _redact_export_text(value: str) -> str:
    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    redacted = WINDOWS_USER_PATH_PATTERN.sub("[REDACTED_LOCAL_PATH]", redacted)
    redacted = POSIX_USER_PATH_PATTERN.sub("[REDACTED_LOCAL_PATH]", redacted)
    redacted = SESSION_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED_SESSION_ID]", redacted)
    return redacted


def _redact_export_metadata(value: Any, key: str = "") -> Any:
    normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
    if normalized_key in SESSION_METADATA_KEYS:
        return "[REDACTED_SESSION_ID]"
    if isinstance(value, dict):
        return {str(item_key): _redact_export_metadata(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_export_metadata(item, key) for item in value]
    if isinstance(value, tuple):
        return [_redact_export_metadata(item, key) for item in value]
    if isinstance(value, str):
        return _redact_export_text(value)
    return value


def _sql_blocks(body: str) -> Iterable[str]:
    for match in re.finditer(r"```(?:sql)?\s*\n(.*?)```", body, flags=re.IGNORECASE | re.DOTALL):
        yield match.group(1)


def validate_documents(documents: list[MarkdownDocument], parse_issues: list[KnowledgeIssue] | None = None) -> list[KnowledgeIssue]:
    issues = list(parse_issues or [])
    by_id: dict[str, MarkdownDocument] = {}
    aliases: dict[str, str] = {}

    for document in documents:
        metadata = document.metadata
        path = str(document.path)
        missing = sorted(key for key in COMMON_REQUIRED if metadata.get(key) in (None, "", []))
        kind = str(metadata.get("kind", ""))
        if kind not in KNOWLEDGE_KINDS:
            issues.append(KnowledgeIssue("error", "unknown_kind", f"지원하지 않는 kind: {kind or '<empty>'}", path))
        else:
            missing.extend(sorted(key for key in KIND_REQUIRED[kind] if metadata.get(key) in (None, "", [])))
        for key in sorted(set(missing)):
            issues.append(KnowledgeIssue("error", "missing_field", f"필수 필드가 없습니다: {key}", path))

        identifier = str(metadata.get("id", ""))
        if identifier and not ID_PATTERN.fullmatch(identifier):
            issues.append(KnowledgeIssue("error", "invalid_id", f"ID 형식이 올바르지 않습니다: {identifier}", path))
        if identifier in by_id:
            issues.append(KnowledgeIssue("error", "duplicate_id", f"중복 ID: {identifier}", path))
        elif identifier:
            by_id[identifier] = document

        status = str(metadata.get("status", ""))
        if status and status not in ALLOWED_STATUS:
            issues.append(KnowledgeIssue("error", "invalid_status", f"지원하지 않는 status: {status}", path))

        if kind == "knowledge_overlay":
            mode = str(metadata.get("mode", ""))
            if mode not in ALLOWED_OVERLAY_MODES:
                issues.append(KnowledgeIssue("error", "invalid_overlay_mode", f"지원하지 않는 mode: {mode}", path))
            if mode in {"extend", "fork"} and not metadata.get("extends"):
                issues.append(KnowledgeIssue("error", "missing_target", "extend/fork에는 extends가 필요합니다.", path))

        for alias in _as_list(metadata.get("aliases")):
            key = alias.casefold().strip()
            if key and key in aliases and aliases[key] != identifier:
                issues.append(
                    KnowledgeIssue(
                        "warning",
                        "alias_conflict",
                        f"별칭 {alias!r}이 {aliases[key]} 및 {identifier}에서 사용됩니다.",
                        path,
                    )
                )
            elif key:
                aliases[key] = identifier

        searchable = document.raw
        for pattern in SECRET_PATTERNS:
            if pattern.search(searchable):
                issues.append(KnowledgeIssue("error", "possible_secret", "자격 증명 또는 연결 문자열로 보이는 값이 있습니다.", path))
                break
        for sql in _sql_blocks(document.body):
            if FORBIDDEN_SQL.search(sql):
                issues.append(KnowledgeIssue("error", "non_select_sql", "SQL 예시에는 SELECT 계열만 사용할 수 있습니다.", path))

    known_ids = set(by_id)
    for document in documents:
        metadata = document.metadata
        path = str(document.path)
        for field in ("related", "left", "right", "extends", "fork_of", "supersedes"):
            for reference in _as_list(metadata.get(field)):
                if not reference or reference in known_ids:
                    continue
                if metadata.get("kind") == "knowledge_overlay" and field == "extends":
                    # A valid personal overlay can outlive a corporate item
                    # removed by a later pack. It is reported and excluded
                    # from the effective catalog, but does not break startup.
                    issues.append(
                        KnowledgeIssue(
                            "warning",
                            "detached_overlay",
                            f"회사 원본이 제거되어 분리된 Personal Overlay: {reference}",
                            path,
                        )
                    )
                else:
                    issues.append(
                        KnowledgeIssue(
                            "error",
                            "broken_reference",
                            f"존재하지 않는 Knowledge ID 참조: {reference}",
                            path,
                        )
                    )

    return issues


def validate_pack(*roots: Path) -> tuple[list[MarkdownDocument], list[KnowledgeIssue]]:
    documents: list[MarkdownDocument] = []
    parse_issues: list[KnowledgeIssue] = []
    for root in roots:
        found, problems = discover_documents(root)
        documents.extend(found)
        parse_issues.extend(problems)
    return documents, validate_documents(documents, parse_issues)


def read_pack_version(root: Path | None) -> str:
    if root is None:
        return "unknown"
    metadata = load_json(root / "pack.json", {}) or {}
    return str(metadata.get("version", root.name))


def compose_catalog(base_root: Path | None, personal_root: Path | None) -> tuple[dict[str, Any], list[KnowledgeIssue]]:
    roots = [root for root in (base_root, personal_root) if root is not None]
    discovered: list[MarkdownDocument] = []
    parse_issues: list[KnowledgeIssue] = []
    for root in roots:
        found, problems = discover_documents(root)
        discovered.extend(found)
        parse_issues.extend(problems)

    # Draft/example/deprecated documents are authoring artifacts, not runtime
    # knowledge. They remain visible to the explicit validate command, but do
    # not block or leak into the effective startup catalog. Missing/unknown
    # status is still an error because it cannot be classified safely.
    classification_issues: list[KnowledgeIssue] = []
    for document in discovered:
        status = str(document.metadata.get("status", ""))
        if not status:
            classification_issues.append(
                KnowledgeIssue("error", "missing_field", "필수 필드가 없습니다: status", str(document.path))
            )
        elif status not in ALLOWED_STATUS:
            classification_issues.append(
                KnowledgeIssue("error", "invalid_status", f"지원하지 않는 status: {status}", str(document.path))
            )
    documents = [document for document in discovered if _is_active(document)]
    issues = validate_documents(documents, parse_issues + classification_issues)
    base_docs: dict[str, MarkdownDocument] = {}
    personal_docs: dict[str, MarkdownDocument] = {}
    overlays: dict[str, list[MarkdownDocument]] = {}

    for document in documents:
        metadata = document.metadata
        identifier = str(metadata.get("id", ""))
        if metadata.get("kind") == "knowledge_overlay" and metadata.get("extends"):
            overlays.setdefault(str(metadata["extends"]), []).append(document)
        elif personal_root is not None and personal_root in document.path.parents:
            personal_docs[identifier] = document
        else:
            base_docs[identifier] = document

    entries: list[dict[str, Any]] = []
    all_ids = sorted(set(base_docs) | set(personal_docs))
    for identifier in all_ids:
        document = personal_docs.get(identifier) or base_docs[identifier]
        metadata = document.metadata
        active_overlays = sorted(overlays.get(identifier, []), key=lambda item: str(item.metadata.get("id", "")))
        aliases = _ordered_unique(
            [*_as_list(metadata.get("aliases")), *(alias for item in active_overlays for alias in _as_list(item.metadata.get("aliases")))]
        )
        tags = _ordered_unique(
            [*_as_list(metadata.get("tags")), *(tag for item in active_overlays for tag in _as_list(item.metadata.get("tags")))]
        )
        search_text = " ".join([_document_search_text(document), *(_document_search_text(item) for item in active_overlays)])
        search_text = re.sub(r"\s+", " ", search_text).strip()[:MAX_CATALOG_SEARCH_TEXT_CHARS]
        entry = {
            "id": identifier,
            "kind": metadata.get("kind"),
            "title": metadata.get("title"),
            "aliases": aliases,
            "tags": tags,
            "domain": metadata.get("domain", ""),
            "status": metadata.get("status"),
            "source": "personal" if identifier in personal_docs else "corporate",
            "path": str(document.path.resolve()),
            "content_hash": text_sha256(document.raw),
            "searchText": search_text,
            "overlays": [
                {
                    "id": item.metadata.get("id"),
                    "title": item.metadata.get("title"),
                    "mode": item.metadata.get("mode"),
                    "path": str(item.path.resolve()),
                    "revision": item.metadata.get("personal_revision", 1),
                    "content_hash": text_sha256(item.raw),
                }
                for item in active_overlays
            ],
        }
        entries.append(entry)

    detached = []
    for target, items in overlays.items():
        if target not in base_docs and target not in personal_docs:
            detached.extend(str(item.metadata.get("id", item.path.name)) for item in items)

    catalog = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "corporatePackVersion": read_pack_version(base_root),
        "entries": entries,
        "detachedOverlays": sorted(detached),
    }
    return catalog, issues


def build_index(base_root: Path | None, personal_root: Path | None, output_root: Path) -> tuple[dict[str, Any], list[KnowledgeIssue]]:
    catalog, issues = compose_catalog(base_root, personal_root)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        return catalog, issues

    output_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_root / "catalog.json", catalog)
    tsv_lines = ["id\tkind\ttitle\taliases\tsource\tpath\toverlay_count"]
    index_lines = ["# Effective Knowledge Index", "", f"Generated: {catalog['generatedAt']}", ""]
    for entry in catalog["entries"]:
        aliases = "|".join(entry["aliases"])
        tsv_lines.append(
            "\t".join(
                str(value).replace("\t", " ").replace("\n", " ")
                for value in (
                    entry["id"],
                    entry["kind"],
                    entry["title"],
                    aliases,
                    entry["source"],
                    entry["path"],
                    len(entry["overlays"]),
                )
            )
        )
        index_lines.append(f"- `{entry['id']}` — {entry['title']} ({entry['source']}, overlays={len(entry['overlays'])})")
    atomic_write_text(output_root / "catalog.tsv", "\n".join(tsv_lines) + "\n")
    atomic_write_text(output_root / "INDEX.md", "\n".join(index_lines) + "\n")

    files = []
    for name in ("catalog.json", "catalog.tsv", "INDEX.md"):
        path = output_root / name
        files.append({"path": name, "sha256": file_sha256(path).split(":", 1)[1], "size": path.stat().st_size})
    atomic_write_json(output_root / "manifest.json", {"schemaVersion": 1, "files": files})
    return catalog, issues


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.casefold()).strip("-.")
    return normalized or "knowledge"


def _find_by_id(root: Path | None, identifier: str) -> MarkdownDocument | None:
    documents, _ = discover_documents(root)
    return next((item for item in documents if _is_active(item) and item.metadata.get("id") == identifier), None)


def upsert_personal(spec: dict[str, Any], state_root: Path, base_root: Path | None) -> Path:
    layout = ensure_user_layout(state_root)
    mode = str(spec.get("mode", "personal-new"))
    target = str(spec.get("extends", ""))
    kind = str(spec.get("kind", "knowledge_overlay" if target else "term"))
    title = str(spec.get("title", "")).strip()
    if not title:
        raise ValueError("title is required")
    if mode not in ALLOWED_OVERLAY_MODES:
        raise ValueError(f"unsupported mode: {mode}")
    if mode in {"extend", "fork"} and not target:
        raise ValueError("extends is required for extend/fork")

    user_config = load_json(layout["config"] / "user.json", {}) or {}
    owner = str(spec.get("owner") or user_config.get("display_name") or os.environ.get("USERNAME") or "local-user")
    identifier = str(spec.get("id") or f"personal.{_slug(target or kind)}.{_slug(title)}")
    destination_dir = layout["overlays"] if target else layout["entries"]
    path = destination_dir / f"{_slug(identifier)}.md"

    revision = 1
    if path.exists():
        existing = load_markdown(path)
        revision = int(existing.metadata.get("personal_revision", 0)) + 1
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        snapshot = layout["versions"] / timestamp / path.name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, snapshot)

    metadata = dict(spec.get("metadata") or {})
    for field in ("aliases", "tags", "domain", "system", "schema", "table", "grain", "columns", "column"):
        if field in spec:
            metadata[field] = spec[field]
    metadata.update(
        {
            "kind": "knowledge_overlay" if target else kind,
            "id": identifier,
            "title": title,
            "owner": owner,
            "status": str(spec.get("status", "active")),
            "scope": "personal",
            "personal_revision": revision,
            "updated_at": utc_now(),
            "source": str(spec.get("source", "explicit_user_feedback")),
        }
    )
    if target:
        base_document = _find_by_id(base_root, target)
        if base_document is None:
            raise ValueError(f"corporate knowledge target not found: {target}")
        metadata.update(
            {
                "mode": mode,
                "extends": target,
                "base_pack_version": read_pack_version(base_root),
                "base_content_hash": text_sha256(base_document.raw),
                "base_contract_hash": _base_contract_hash(base_document),
            }
        )
    body = str(spec.get("body", "")).strip()
    if not body:
        raise ValueError("body is required")
    rendered = dump_frontmatter(metadata, body)
    candidate_meta, candidate_body = parse_frontmatter_text(rendered, str(path))
    candidate = MarkdownDocument(path=path, metadata=candidate_meta, body=candidate_body, raw=rendered)

    other_documents, parse_issues = validate_pack(base_root, layout["knowledge"]) if base_root else validate_pack(layout["knowledge"])
    other_documents = [item for item in other_documents if item.path.resolve() != path.resolve()]
    validation = validate_documents(other_documents + [candidate], parse_issues)
    errors = [issue for issue in validation if issue.level == "error" and issue.path == str(path)]
    if errors:
        raise ValueError("; ".join(issue.message for issue in errors))

    atomic_write_text(path, rendered)
    ledger_record = {
        "at": utc_now(),
        "action": "create" if revision == 1 else "update",
        "knowledgeId": identifier,
        "revision": revision,
        "source": metadata["source"],
        "reason": str(spec.get("reason", "사용자가 확정한 재사용 지식"))[:500],
    }
    ledger_path = layout["ledger"] / "knowledge.jsonl"
    with ledger_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(ledger_record, ensure_ascii=False, sort_keys=True) + "\n")
    build_index(base_root, layout["knowledge"], layout["index"])
    return path


def reconcile_overlays(state_root: Path, base_root: Path, apply_safe: bool = False) -> dict[str, Any]:
    layout = ensure_user_layout(state_root)
    base_documents, _ = discover_documents(base_root)
    bases = {str(item.metadata.get("id")): item for item in base_documents if _is_active(item)}
    overlay_documents, _ = discover_documents(layout["overlays"])
    overlay_documents = [item for item in overlay_documents if _is_active(item)]
    report: dict[str, Any] = {"baseVersion": read_pack_version(base_root), "compatible": [], "rebased": [], "conflicts": [], "detached": []}

    for overlay in overlay_documents:
        metadata = dict(overlay.metadata)
        target = str(metadata.get("extends", ""))
        current = bases.get(target)
        if current is None:
            report["detached"].append(str(metadata.get("id", overlay.path.name)))
            continue
        current_hash = text_sha256(current.raw)
        if metadata.get("base_content_hash") == current_hash:
            report["compatible"].append(str(metadata.get("id")))
            continue
        current_contract_hash = _base_contract_hash(current)
        previous_contract_hash = metadata.get("base_contract_hash")
        if metadata.get("mode") == "extend" and previous_contract_hash == current_contract_hash:
            if apply_safe:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                snapshot = layout["versions"] / timestamp / overlay.path.name
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(overlay.path, snapshot)
                metadata["base_content_hash"] = current_hash
                metadata["base_contract_hash"] = current_contract_hash
                metadata["base_pack_version"] = read_pack_version(base_root)
                metadata["updated_at"] = utc_now()
                atomic_write_text(overlay.path, dump_frontmatter(metadata, overlay.body))
                report["rebased"].append(str(metadata.get("id")))
            else:
                report["compatible"].append(str(metadata.get("id")))
        else:
            if metadata.get("mode") == "extend":
                reason = (
                    "회사 원본의 kind 또는 필수 구조/의미 frontmatter가 변경되었거나 이전 계약 정보가 없어 "
                    "자동 rebase할 수 없습니다."
                )
            else:
                reason = "회사 원본과 개인 fork가 모두 변경되었습니다."
            conflict = {
                "overlayId": metadata.get("id"),
                "target": target,
                "previousBaseHash": metadata.get("base_content_hash"),
                "currentBaseHash": current_hash,
                "previousBaseContractHash": previous_contract_hash,
                "currentBaseContractHash": current_contract_hash,
                "reason": reason,
            }
            report["conflicts"].append(conflict)
            atomic_write_json(layout["conflicts"] / f"{_slug(str(metadata.get('id')))}.json", conflict)
    atomic_write_json(layout["conflicts"] / "report.json", report)
    if apply_safe:
        build_index(base_root, layout["knowledge"], layout["index"])
    return report


def search_catalog(index_root: Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        catalog = load_json(index_root / "catalog.json", {}) or {}
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return []
    if not isinstance(catalog, dict):
        return []
    try:
        bounded_limit = max(0, min(int(limit), MAX_CATALOG_RESULTS))
    except (TypeError, ValueError):
        bounded_limit = 10
    if bounded_limit == 0:
        return []
    query_text = str(query or "")[:MAX_CATALOG_QUERY_CHARS]
    tokens = list(dict.fromkeys(token.casefold() for token in re.findall(r"[\w.-]{2,}", query_text)))[:MAX_CATALOG_QUERY_TOKENS]
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in catalog.get("entries", []):
        if not isinstance(entry, dict) or entry.get("status") != "active":
            continue
        title = str(entry.get("title", "")).casefold()
        aliases = " ".join(_as_list(entry.get("aliases"))).casefold()
        haystack = " ".join(
            [
                str(entry.get("id", "")),
                title,
                aliases,
                " ".join(_as_list(entry.get("tags"))),
                str(entry.get("domain", "")),
                str(entry.get("searchText", "")),
            ]
        ).casefold()
        score = sum(4 for token in tokens if token in title)
        score += sum(3 for token in tokens if token in aliases)
        score += sum(1 for token in tokens if token in haystack)
        if score:
            result = dict(entry)
            # searchText can contain whole document bodies. It is an internal
            # index field and must not expand CLI/model responses.
            result.pop("searchText", None)
            scored.append((score, result))
    return [entry for _, entry in sorted(scored, key=lambda pair: (-pair[0], str(pair[1].get("id"))))[:bounded_limit]]


def export_knowledge(state_root: Path, identifiers: list[str], output: Path) -> Path:
    layout = ensure_user_layout(state_root)
    documents, _ = discover_documents(layout["knowledge"])
    selected = [item for item in documents if str(item.metadata.get("id")) in set(identifiers)]
    missing = sorted(set(identifiers) - {str(item.metadata.get("id")) for item in selected})
    if missing:
        raise ValueError(f"knowledge IDs not found: {', '.join(missing)}")
    validation = validate_documents(selected)
    unsafe = [item for item in validation if item.level == "error" and item.code == "possible_secret"]
    if unsafe:
        raise ValueError("export blocked because a selected document may contain credentials")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="company-agent-export-") as temp_dir:
        root = Path(temp_dir)
        manifest = {
            "schemaVersion": 1,
            "createdAt": utc_now(),
            "knowledgeIds": identifiers,
            "redaction": "local paths, email addresses, and session identifiers removed",
            "files": [],
        }
        for document in selected:
            destination = root / document.path.name
            metadata = _redact_export_metadata(
                {
                    key: value
                    for key, value in document.metadata.items()
                    if key not in {"created_from_session", "session_id", "user_email", "source_note"}
                }
            )
            if metadata.get("scope") == "personal":
                metadata["owner"] = "shared-user"
            body = _redact_export_text(document.body)
            atomic_write_text(destination, dump_frontmatter(metadata, body))
            manifest["files"].append({"path": destination.name, "sha256": file_sha256(destination).split(":", 1)[1]})
        summary = (
            "# Knowledge Share\n\n"
            f"Exported {len(selected)} personal knowledge item(s).\n\n"
            "Review the Markdown before sharing. Automated redaction cannot identify every kind of sensitive business row.\n"
        )
        atomic_write_text(root / "change-summary.md", summary)
        manifest["files"].append(
            {"path": "change-summary.md", "sha256": file_sha256(root / "change-summary.md").split(":", 1)[1]}
        )
        atomic_write_json(root / "manifest.json", manifest)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.iterdir()):
                archive.write(path, arcname=path.name)
    return output
