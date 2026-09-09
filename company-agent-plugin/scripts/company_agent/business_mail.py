"""Optional, read-only Classic Outlook bridge; never registers/replaces an MCP.

The corporate Outlook MCP remains responsible for identity-attested sending and
mailbox mutations. This bridge only reads an already running Outlook instance.
The caller must obtain its own trusted policy approval before enabling body reads;
``body_access_approved`` is an internal guard assertion, not user authorization.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

from .business_safety import windows_powershell

HELPER = Path(__file__).resolve().parents[1] / "Invoke-BusinessOutlook.ps1"
_MAX_INPUT = 32_768
_MAX_OUTPUT = 2_000_000
_READ_TIMEOUT = 45
_REF_PATTERN = re.compile(r"[A-Fa-f0-9]{8,4096}\Z")
_MESSAGES = {
    "connection_required": "실행 중인 Classic Outlook과 본인 계정 연결을 확인해 주세요. 메일은 변경하지 않았습니다.",
    "invalid_request": "조회할 본인 계정과 선택한 메일함/PST 범위를 확인해 주세요.",
    "permission_denied": "메일 접근 권한을 확인할 수 없거나 허용되지 않아 해당 작업을 건너뛰었습니다.",
    "blocked": "보호된 메일이거나 보안 정책에서 허용하지 않아 해당 내용을 읽지 않았습니다.",
    "unknown": "접근 상태를 확인할 수 없어 해당 내용을 읽지 않았습니다.",
    "partial": "조회 범위 또는 시간 제한으로 일부 결과만 표시합니다. 기간이나 폴더를 좁혀 주세요.",
    "ok": "선택한 범위에서 읽기 전용 조회를 완료했습니다.",
}
_DRM_NOTICE = "Outlook IRM 상태만 확인합니다. 외부 문서 DRM의 허용 여부를 증명하지 않으며, 첨부는 내려받지 않습니다."


def _result(status: str, **details) -> dict:
    return {
        "ok": status in {"ok", "partial"}, "status": status,
        "message": _MESSAGES.get(status, _MESSAGES["unknown"]),
        "read_only": True, "sending_supported": False,
        "identity_assurance": "profile_account_mapping_only",
        "external_drm": "not_detectable", "drm_notice": _DRM_NOTICE,
        **details,
    }


def _bounded_int(value, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError("invalid limit")
    return value


def _refs(value, *, maximum: int = 20, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > maximum:
        raise ValueError("invalid references")
    if any(not isinstance(item, str) or not _REF_PATTERN.fullmatch(item) for item in value):
        raise ValueError("invalid reference")
    return list(dict.fromkeys(item.upper() for item in value))


def _date(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid date")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("date requires timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_spec(operation: str, spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("invalid request")
    common = {"account_smtp", "store_ids", "pst_store_ids"}
    keys = (common | {"query", "folder_ids", "include_subfolders", "limit", "scan_limit", "folder_limit",
                       "received_after", "received_before"} if operation == "search" else
            common | {"message_refs", "include_body", "body_access_approved", "body_char_limit"})
    if set(spec) - keys:
        raise ValueError("unknown request fields")
    smtp = spec.get("account_smtp")
    if not isinstance(smtp, str) or not 3 <= len(smtp) <= 320 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", smtp):
        raise ValueError("invalid account")
    normalized = {"account_smtp": smtp.casefold(), "store_ids": _refs(spec.get("store_ids")),
                  "pst_store_ids": _refs(spec.get("pst_store_ids", []), allow_empty=True)}
    if not set(normalized["pst_store_ids"]).issubset(normalized["store_ids"]):
        raise ValueError("PST selection must be in requested stores")
    if operation == "search":
        query = spec.get("query", "")
        if not isinstance(query, str) or len(query) > 200 or any(ord(char) < 32 for char in query):
            raise ValueError("invalid query")
        descend = spec.get("include_subfolders", True)
        if not isinstance(descend, bool):
            raise ValueError("invalid recursion option")
        normalized.update(query=query, folder_ids=_refs(spec.get("folder_ids", []), maximum=50, allow_empty=True),
                          include_subfolders=descend, limit=_bounded_int(spec.get("limit"), 20, 50),
                          scan_limit=_bounded_int(spec.get("scan_limit"), 500, 2000),
                          folder_limit=_bounded_int(spec.get("folder_limit"), 30, 100),
                          received_after=_date(spec.get("received_after")),
                          received_before=_date(spec.get("received_before")))
        if normalized["received_after"] and normalized["received_before"]:
            if normalized["received_after"] >= normalized["received_before"]:
                raise ValueError("invalid date range")
    else:
        refs = spec.get("message_refs")
        if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
            raise ValueError("invalid message references")
        normalized["message_refs"] = []
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"store_id", "entry_id"}:
                raise ValueError("invalid message reference")
            store_id = _refs([ref["store_id"]])[0]
            entry_id = _refs([ref["entry_id"]])[0]
            if store_id not in normalized["store_ids"]:
                raise ValueError("message outside selected stores")
            normalized["message_refs"].append({"store_id": store_id, "entry_id": entry_id})
        include = spec.get("include_body", False)
        approved = spec.get("body_access_approved", False)
        if not isinstance(include, bool) or not isinstance(approved, bool):
            raise ValueError("invalid body option")
        if include and not approved:
            raise PermissionError("body approval required")
        normalized.update(include_body=include, body_access_approved=approved,
                          body_char_limit=_bounded_int(spec.get("body_char_limit"), 4000, 12000))
    return normalized


def _invoke(operation: str, spec: dict) -> dict:
    if os.name != "nt" or not HELPER.is_file():
        return _result("connection_required", reason="classic_outlook_bridge_unavailable")
    try:
        powershell = windows_powershell()
    except (OSError, ValueError):
        return _result("connection_required", reason="windows_powershell_unavailable")
    payload = json.dumps(spec, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(payload) > _MAX_INPUT:
        return _result("invalid_request", reason="request_limit")
    try:
        process = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(HELPER),
             "-Operation", operation], input=payload, capture_output=True, timeout=_READ_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
        if process.returncode or len(process.stdout) > _MAX_OUTPUT:
            return _result("connection_required", reason="bridge_unavailable_or_policy_blocked")
        response = json.loads(process.stdout.decode("utf-8-sig"))
        if not isinstance(response, dict) or response.get("status") not in _MESSAGES:
            return _result("unknown", reason="invalid_bridge_response")
        status = response.pop("status")
        # Helper-owned data cannot override this adapter's safety/identity claims.
        for key in ("ok", "message", "read_only", "sending_supported", "identity_assurance", "external_drm", "drm_notice"):
            response.pop(key, None)
        items = response.get("items", [])
        if not isinstance(items, list) or len(items) > 50 or any(not isinstance(item, dict) for item in items):
            return _result("unknown", reason="invalid_bridge_response")
        for item in items:
            if isinstance(item, dict):
                # The learning hook consumes fixed structured restriction codes,
                # not Outlook exception text. A generic connection/read failure
                # is not proof of protection; only the helper's item-level
                # permission-uncertainty marker warrants protection_unknown.
                if item.get("status") == "blocked":
                    item["code"] = "protection_blocked"
                elif item.get("status") == "permission_denied":
                    item["code"] = "permission_denied"
                elif item.get("status") == "unknown" and item.get("protection_status") == "unknown":
                    item["code"] = "protection_unknown"
                item["message"] = _MESSAGES.get(item.get("status", "unknown"), _MESSAGES["unknown"])
        # Search omits protected subjects entirely, so its restriction signals
        # are bounded aggregate counts rather than returned mail item records.
        warnings = []
        for field, code in (("blocked_count", "protection_blocked"),
                            ("protection_unknown_count", "protection_unknown")):
            count = response.get(field, 0)
            if isinstance(count, int) and not isinstance(count, bool) and 0 < count <= 2000:
                warnings.append({"code": code, "count": count})
        if warnings:
            response["restriction_warnings"] = warnings
        return _result(status, **response)
    except subprocess.TimeoutExpired:
        return _result("unknown", reason="outlook_timeout_no_automatic_retry")
    except (OSError, UnicodeError, ValueError, TypeError):
        # Exception text may contain mailbox names, subjects, or local paths.
        return _result("unknown", reason="bridge_read_failed")


def capabilities() -> dict:
    """List running Classic Outlook account/store metadata; no message reads."""
    return _invoke("capabilities", {})


def search_mail(spec: dict) -> dict:
    """Bounded subject/sender/date search, never body or attachment extraction."""
    try:
        request = _normalize_spec("search", spec)
    except (ValueError, TypeError):
        return _result("invalid_request")
    return _invoke("search", request)


def read_mail(spec: dict) -> dict:
    """Read selected refs; body requires explicit request AND caller guard grant."""
    try:
        request = _normalize_spec("read", spec)
    except PermissionError:
        return _result("permission_denied", reason="body_policy_approval_required")
    except (ValueError, TypeError):
        return _result("invalid_request")
    return _invoke("read", request)
