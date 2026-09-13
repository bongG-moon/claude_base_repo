"""Bounded local EML plain-text reader, not Outlook access or a DRM detector.

Never writes extracted files or contacts external services. Returned content may
be retained in the caller's conversation; source AI-processing approval remains
the caller's responsibility. Recognized protection is a stop signal, not a cue
to decrypt or try another parser.
"""
from __future__ import annotations

from email import policy
from email.errors import MessageError
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
import re

from .business_safety import safe_path

MAX_BYTES = 2 * 1024 * 1024
MAX_PARTS = 100
MAX_BODY = 12_000
MAX_ATTACHMENT = 4_000
MAX_TEXT = 20_000
_PROTECTED_TYPES = {"application/x-microsoft-rpmsg-message", "application/vnd.ms-outlook-rpmsg",
                    "application/pkcs7-mime", "application/x-pkcs7-mime", "multipart/encrypted"}


def _label(value: object, limit: int = 200) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))[:limit]


def _base() -> dict:
    return {"ok": False, "status": "failed", "source_kind": "local_eml", "read_only": True,
            "outlook_connected": False, "rawContentStored": False,
            "transcript_retention": "tool_output_may_be_retained", "body_read": False,
            "body": "", "attachments": [], "warnings": [], "partial_reasons": []}


def _failed(code: str) -> dict:
    return {**_base(), "code": code, "message": "선택한 로컬 메일 파일을 읽지 못했습니다. 오류 항목만 확인해 주세요."}


def _protected(part: Message) -> bool:
    name = str(part.get_filename() or "").casefold()
    return (part.get_content_type().lower() in _PROTECTED_TYPES or
            name.endswith((".rpmsg", ".p7m", ".p7e")))


def _text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        raise ValueError("invalid payload")
    # Unknown/invalid charsets fail rather than launching converters or emitting
    # undecoded bytes. email parsing never invokes Office or opens attachment URLs.
    return payload.decode(part.get_content_charset() or "ascii", errors="strict")


def read_eml(file: Path) -> dict:
    """Return bounded, explicitly qualified body/attachment evidence; no writes."""
    try:
        given = Path(file)
        if not given.is_absolute() or ".." in given.parts or given.suffix.casefold() != ".eml":
            return _failed("invalid_local_eml_path")
        source = safe_path(given, exists=True)
        if not source.is_file():
            return _failed("invalid_local_eml_path")
        before = source.stat()
        if before.st_size > MAX_BYTES:
            return _failed("eml_size_limit")
        with source.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return _failed("eml_size_limit")
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            return _failed("source_changed_during_read")
        message = BytesParser(policy=policy.default).parsebytes(raw)
        top_protected = _protected(message)
        metadata = {"subject": _label(message.get("subject")), "sender": _label(message.get("from")),
                    "date": _label(message.get("date"))} if not top_protected else {}
    except PermissionError:
        return _failed("permission_denied")
    except (OSError, ValueError, TypeError, LookupError, MessageError, RecursionError):
        return _failed("eml_read_failed")

    if top_protected:
        return {**_base(), "status": "blocked", "code": "protection_blocked",
                "warnings": [{"code": "protection_blocked"}], "partial_reasons": ["protection_blocked"],
                "message": "보호된 메일 유형이어서 본문을 읽지 않았습니다. 보호 해제나 대체 추출은 시도하지 않았습니다."}
    result = _base()
    result.update(ok=True, status="ok", source_name=_label(source.name), **metadata,
                  message="로컬 메일 파일에서 지원하는 일반 텍스트를 확인했습니다. 읽은 범위는 body_read와 첨부 상태를 확인하세요. Outlook에는 연결하지 않았습니다.")
    pending, count, remaining = [message], 0, MAX_TEXT
    reasons: list[str] = result["partial_reasons"]

    def reason(code: str) -> None:
        if code not in reasons:
            reasons.append(code)

    while pending:
        part = pending.pop()
        count += 1
        if count > MAX_PARTS:
            reason("mime_part_limit")
            break
        attached = False
        record = {"name": "unnamed", "content_type": "unknown", "status": "excluded"}
        try:
            kind = part.get_content_type().lower()
            filename = part.get_filename()
            attached = bool(filename) or part.get_content_disposition() == "attachment"
            record = {"name": _label(filename or "unnamed"), "content_type": kind, "status": "excluded"}
            if _protected(part):
                reason("protection_blocked")
                if attached:
                    result["attachments"].append({**record, "code": "protection_blocked"})
                continue
            if kind == "message/rfc822":
                reason("embedded_mail_not_read")
                result["attachments"].append({**record, "code": "embedded_mail_not_read"})
                continue
            if part.is_multipart() and not attached:
                children = part.get_payload()
                if isinstance(children, list):
                    pending.extend(reversed(children[:MAX_PARTS]))
                    if len(children) > MAX_PARTS:
                        reason("mime_part_limit")
                continue
            if attached:
                if kind != "text/plain" or not filename or not filename.casefold().endswith(".txt"):
                    reason("unsupported_attachment")
                    result["attachments"].append({**record, "code": "unsupported_attachment"})
                    continue
                text = _text(part)
                limit = min(MAX_ATTACHMENT, remaining)
                content = text[:limit]
                remaining -= len(content)
                result["attachments"].append({**record, "status": "read" if len(text) <= limit else "partial",
                                              "content": content, "truncated": len(text) > limit})
                if len(text) > limit:
                    reason("text_limit")
            elif kind == "text/plain":
                text = _text(part)
                separator = "\n" if result["body"] else ""
                limit = max(0, min(MAX_BODY - len(result["body"]) - len(separator), remaining - len(separator)))
                if limit or not text:
                    result["body"] += separator + text[:limit]
                    remaining -= len(separator) + min(len(text), limit)
                    result["body_read"] = True
                if len(text) > limit:
                    reason("text_limit")
            elif kind == "text/html":
                reason("html_not_rendered")
            else:
                reason("unsupported_body_part")
            if part.defects:
                reason("malformed_mime")
        except (ValueError, TypeError, LookupError, UnicodeError, MessageError, RecursionError):
            reason("part_decode_failed")
            if attached:
                result["attachments"].append({**record, "code": "part_decode_failed"})
    if not result["body_read"]:
        reason("plain_body_not_read")
    if reasons:
        result["status"] = "partial"
    if "protection_blocked" in reasons:
        result["warnings"].append({"code": "protection_blocked"})
    return result
