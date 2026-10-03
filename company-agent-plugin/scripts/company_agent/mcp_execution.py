"""Freeze receipt-verified MCP sources at explicit activation, never on startup.

This is a local source-integrity boundary, not an OS sandbox. Only Python source
and known generated metadata are packaged; separate credential files, receipts,
caches and arbitrary runtime data are not copied. Reviewed source/config.py and
test fixtures must themselves contain no secrets. Source edits cannot alter an
active bundle.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import zipfile


_METADATA = {"asset.json", "tool-tests.json", "requirements-local.txt", "pyproject.toml"}
_MAIN = b'import runpy\nrunpy.run_module("server", run_name="__main__")\n'
_MAX_BUNDLE_BYTES = 9 * 1024 * 1024


def bundle_evidence(content: bytes) -> dict:
    return {"executionFormat": "python-zipapp-v1", "executionBundleHash": hashlib.sha256(content).hexdigest()}


def verify_bundle_evidence(receipt: dict, content: bytes) -> None:
    expected = bundle_evidence(content)
    details = receipt.get("details", {})
    if not isinstance(details, dict) or any(details.get(key) != value for key, value in expected.items()):
        raise ValueError("MCP execution bundle needs a matching protocol receipt; run asset test-mcp again")


def read_execution_bundle(definition: dict) -> bytes:
    path = Path(definition["args"][0])
    _no_links(path)
    with path.open("rb") as stream:
        content = stream.read(_MAX_BUNDLE_BYTES + 1)
    if len(content) > _MAX_BUNDLE_BYTES:
        raise ValueError("MCP execution bundle exceeds its size limit")
    return content


def _no_links(path: Path) -> None:
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("MCP execution bundles cannot use symlink/junction paths")


def execution_definition(state_root: Path, name: str, manifest: dict) -> dict:
    from .asset_factory import _confined_child
    path = _confined_child(state_root / "mcp/active", name) / "server.pyz"
    return {"type": "stdio", "command": manifest["command"], "args": [str(path)]}


def prepare_execution_bundle(state_root: Path, server_root: Path, name: str, manifest: dict, receipt: dict) -> tuple[dict, bytes]:
    """Hash the exact captured bytes, then prepare one executable ZIP in memory.

    The caller verifies the signed receipt first. Recomputing its source hash
    from captured bytes prevents a check-then-copy race from publishing edits.
    No registered execution bytes are changed during preparation.
    """
    from .asset_factory import _canonical_manifest_value
    _no_links(state_root)
    _no_links(server_root)
    captured = {}
    total = 0
    for path in sorted(server_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(server_root)
        if ".receipts" in relative.parts or "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        _no_links(path)
        if not path.is_file():
            continue
        filename = relative.as_posix()
        if filename == "__main__.py" or (path.suffix != ".py" and filename not in _METADATA):
            raise ValueError("MCP bundle supports Python source and generated metadata only; review runtime data separately")
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("MCP execution bundle exceeds its source size limit")
        content = path.read_bytes()
        total += len(content)
        if len(captured) >= 256 or total > 8 * 1024 * 1024:
            raise ValueError("MCP execution bundle exceeds its source size limit")
        captured[filename] = content
    digest = hashlib.sha256()
    for filename, content in captured.items():
        canonical = _canonical_manifest_value(json.loads(content)) if filename == "asset.json" else content
        digest.update(filename.encode("utf-8") + b"\0" + len(canonical).to_bytes(8, "big") + canonical)
    if "sha256:" + digest.hexdigest() != receipt["assetHash"]:
        raise ValueError("MCP source changed while capturing activation; validate it again")
    if "server.py" not in captured:
        raise ValueError("MCP execution bundle requires server.py")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for filename, content in {**captured, "__main__.py": _MAIN}.items():
            if filename != "asset.json":  # Mutable activation metadata is control-plane state, not runtime code.
                bundle.writestr(zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0)), content)
    definition = execution_definition(state_root, name, manifest)
    content = archive.getvalue()
    if len(content) > _MAX_BUNDLE_BYTES:
        raise ValueError("MCP execution bundle exceeds its size limit")
    return definition, content


def publish_execution_bundle(state_root: Path, name: str, definition: dict, content: bytes) -> None:
    """The final activation commit: one atomic replacement of the fixed bundle."""
    target = Path(definition["args"][0])
    _no_links(state_root / "mcp/active" / name)
    target.parent.mkdir(parents=True, exist_ok=True)
    _no_links(target.parent)
    if target.exists():
        _no_links(target)
    fd, temporary = tempfile.mkstemp(prefix=".server-", suffix=".pyz", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
