from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FrontmatterError(ValueError):
    pass


@dataclass(frozen=True)
class MarkdownDocument:
    path: Path
    metadata: dict[str, Any]
    body: str
    raw: str


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value[0:1] in {'"', "'"} or value[0:1] in {"[", "{"}:
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1].replace("''", "'")
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(f"Invalid JSON-style scalar: {value}") from exc
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def parse_frontmatter_text(text: str, source: str = "<memory>") -> tuple[dict[str, Any], str]:
    normalized = text.lstrip("\ufeff")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError(f"{source}: missing opening frontmatter delimiter")
    try:
        closing = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise FrontmatterError(f"{source}: missing closing frontmatter delimiter") from exc

    metadata: dict[str, Any] = {}
    current_list_key: str | None = None
    for line_number, raw_line in enumerate(lines[1:closing], start=2):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if stripped.startswith("-"):
            if current_list_key is None:
                raise FrontmatterError(f"{source}:{line_number}: list item has no parent key")
            item = stripped[1:].strip()
            metadata[current_list_key].append(_parse_scalar(item))
            continue
        if raw_line[:1].isspace():
            raise FrontmatterError(
                f"{source}:{line_number}: nested mappings are not supported; use an inline JSON object"
            )
        if ":" not in raw_line:
            raise FrontmatterError(f"{source}:{line_number}: expected 'key: value'")
        key, value = raw_line.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            raise FrontmatterError(f"{source}:{line_number}: invalid key {key!r}")
        if key in metadata:
            raise FrontmatterError(f"{source}:{line_number}: duplicate key {key!r}")
        if value.strip():
            metadata[key] = _parse_scalar(value)
            current_list_key = None
        else:
            metadata[key] = []
            current_list_key = key

    body = "\n".join(lines[closing + 1 :]).strip() + "\n"
    return metadata, body


def load_markdown(path: Path) -> MarkdownDocument:
    raw = path.read_text(encoding="utf-8-sig")
    metadata, body = parse_frontmatter_text(raw, str(path))
    return MarkdownDocument(path=path, metadata=metadata, body=body, raw=raw)


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, str):
            rendered = json.dumps(value, ensure_ascii=False)
        elif value is None or isinstance(value, (bool, int, float, list, dict)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            raise TypeError(f"Unsupported frontmatter value for {key}: {type(value).__name__}")
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", body.strip(), ""])
    return "\n".join(lines)
