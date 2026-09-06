"""Read-only instruction-size diagnostics; never compact user files in place."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any


RECOMMENDED_LINES = 200
RECOMMENDED_CHARS = 12_000
MAX_INSPECT_BYTES = 512_000


def audit_context(project: Path, *, config_root: Path | None = None) -> dict[str, Any]:
    project = project.absolute()
    if not project.is_dir():
        raise ValueError("project must be an existing directory")
    config = config_root or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    candidates: list[Path] = [config / "CLAUDE.md"]
    for directory in [project, *project.parents]:
        candidates.extend([directory / "CLAUDE.md", directory / "CLAUDE.local.md", directory / ".claude" / "CLAUDE.md"])
    # A bounded audit of rules in the selected project/user root, not a whole-PC
    # crawler. Native Claude decides which path-scoped rules actually load.
    for rules in (config / "rules", project / ".claude" / "rules"):
        if rules.is_dir() and not rules.is_symlink() and not getattr(rules, "is_junction", lambda: False)():
            candidates.extend(sorted(rules.glob("*.md"))[:100])
    records = []
    seen = set()
    for path in candidates:
        key = os.path.normcase(str(path.absolute()))
        if key in seen:
            continue
        seen.add(key)
        try:
            unsafe = False
            for part in [path, *path.parents]:
                attributes = part.lstat()
                if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    unsafe = True
                    break
            if unsafe or not path.is_file():
                continue
            size = path.stat().st_size
            record: dict[str, Any] = {"path": str(path), "bytes": size}
            if size > MAX_INSPECT_BYTES:
                record.update({"status": "too-large-to-inspect", "overBudget": True})
            else:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_INSPECT_BYTES + 1)
                if len(raw) > MAX_INSPECT_BYTES:
                    record.update({"status": "too-large-to-inspect", "overBudget": True})
                else:
                    body = raw.decode("utf-8-sig")
                    record.update({"status": "inspected", "lines": len(body.splitlines()), "characters": len(body),
                                   "overBudget": len(body.splitlines()) > RECOMMENDED_LINES or len(body) > RECOMMENDED_CHARS})
            records.append(record)
        except (OSError, UnicodeError):
            continue
    return {"ok": True, "recommendedLines": RECOMMENDED_LINES, "recommendedCharacters": RECOMMENDED_CHARS,
            "files": records, "overBudgetCount": sum(item["overBudget"] for item in records),
            "note": "Read-only size hints, not a token count or complete loaded-context inventory. Imports, nested rules and native auto-memory are not expanded. No files changed."}
