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
DEFAULT_TOTAL_BODY_CHARS = 12_000
MAX_TOTAL_BODY_CHARS = 24_000
DEFAULT_RESULT_CHARS = 32_000
MAX_RESULT_CHARS = 64_000
_REF_PATTERN = re.compile(r"[A-Fa-f0-9]{8,4096}\Z")
_MESSAGES = {
    "connection_required": "실행 중인 Classic Outlook과 본인 계정 연결을 확인해 주세요. 메일은 변경하지 않았습니다.",
    "invalid_request": "조회 요청의 입력 형식을 확인해 주세요. 오류 코드에 표시된 항목만 수정하고 계정이나 검색 범위를 임의로 바꾸지 마세요.",
    "permission_denied": "메일 접근 권한을 확인할 수 없거나 허용되지 않아 해당 작업을 건너뛰었습니다.",
    "blocked": "보호된 메일이거나 보안 정책에서 허용하지 않아 해당 내용을 읽지 않았습니다.",
    "unknown": "접근 상태를 확인할 수 없어 해당 내용을 읽지 않았습니다.",
    "partial": "조회 범위 또는 시간 제한으로 일부 결과만 표시합니다. 기간이나 폴더를 좁혀 주세요.",
    "ok": "선택한 범위에서 읽기 전용 조회를 완료했습니다.",
}
_DRM_NOTICE = "Outlook IRM 상태만 확인합니다. 외부 문서 DRM의 허용 여부를 증명하지 않으며, 첨부는 내려받지 않습니다."

_VALIDATION_REASONS = {
    "invalid account": "account_format_invalid",
    "invalid references": "references_required_or_invalid",
    "invalid reference": "reference_format_invalid",
    "invalid date": "date_format_invalid",
    "invalid date range": "date_range_invalid",
    "invalid limit": "limit_invalid",
    "unknown request fields": "unsupported_request_fields",
    "PST selection must be in requested stores": "pst_outside_selected_stores",
    "message outside selected stores": "message_outside_selected_stores",
    "invalid message references": "message_references_required",
    "invalid message reference": "message_reference_invalid",
    "invalid query": "query_format_invalid",
    "invalid recursion option": "recursion_option_invalid",
    "invalid body option": "body_option_invalid",
}


def _validation_error(error: Exception) -> dict:
    # Only fixed identifiers escape this boundary, never raw input/exception text.
    code = _VALIDATION_REASONS.get(str(error), "request_format_invalid")
    result = _result("invalid_request", reason=code, stage="request_validation", bridge_called=False)
    if code == "date_format_invalid":
        result["message"] = "날짜는 2026-09-08T00:00:00+09:00처럼 시각을 포함해 주세요. 시간대 생략 시 PC의 해당 날짜 기준 현지 시간대를 사용합니다."
    elif code == "date_range_invalid":
        result["message"] = "검색 시작 시각은 종료 시각보다 빨라야 합니다. 종료 시각 자체는 검색 범위에서 제외됩니다."
    return result


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


def _date(value, *, field: str = "date", assumptions: list | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40 or not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
        raise ValueError("invalid date")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid date") from None
    if parsed.tzinfo is None:
        # astimezone() applies the PC's local rules at this date, not today's
        # fixed offset. Do not silently treat a Korean wall-clock time as UTC.
        parsed = parsed.astimezone()
        if assumptions is not None:
            assumptions.append({"field": field, "basis": "pc_local_timezone_at_requested_date",
                                "normalized_local": parsed.isoformat()})
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_spec(operation: str, spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("invalid request")
    common = {"account_smtp", "store_ids", "pst_store_ids", "result_char_limit"}
    keys = (common | {"query", "folder_ids", "include_subfolders", "limit", "scan_limit", "folder_limit",
                       "received_after", "received_before"} if operation == "search" else
            common | {"message_refs", "include_body", "body_access_approved", "body_char_limit", "total_body_char_limit"})
    if set(spec) - keys:
        raise ValueError("unknown request fields")
    smtp = spec.get("account_smtp")
    if not isinstance(smtp, str) or not 3 <= len(smtp) <= 320 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", smtp):
        raise ValueError("invalid account")
    normalized = {"account_smtp": smtp.casefold(), "store_ids": _refs(spec.get("store_ids")),
                  "pst_store_ids": _refs(spec.get("pst_store_ids", []), allow_empty=True),
                  "result_char_limit": _bounded_int(spec.get("result_char_limit"), DEFAULT_RESULT_CHARS, MAX_RESULT_CHARS)}
    if normalized["result_char_limit"] < 4096:
        raise ValueError("invalid limit")
    if not set(normalized["pst_store_ids"]).issubset(normalized["store_ids"]):
        raise ValueError("PST selection must be in requested stores")
    if operation == "search":
        assumptions = []
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
                          received_after=_date(spec.get("received_after"), field="received_after", assumptions=assumptions),
                          received_before=_date(spec.get("received_before"), field="received_before", assumptions=assumptions))
        if normalized["received_after"] and normalized["received_before"]:
            if normalized["received_after"] >= normalized["received_before"]:
                raise ValueError("invalid date range")
        normalized["_date_assumptions"] = assumptions
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
                          body_char_limit=_bounded_int(spec.get("body_char_limit"), 4000, 12000),
                          total_body_char_limit=_bounded_int(spec.get("total_body_char_limit"), DEFAULT_TOTAL_BODY_CHARS, MAX_TOTAL_BODY_CHARS))
    return normalized


def _bounded_result(result: dict, request: dict, operation: str) -> dict:
    """Bound the final CLI JSON, including escaping/metadata, without broken IDs.

    The COM reader stops subsequent body access at its cumulative budget. This
    final boundary also handles large metadata and keeps the displayed coverage
    honest; a transport byte ceiling alone is not a model-context budget.
    """
    items = result.get("items", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        return _result("unknown", reason="invalid_bridge_response", stage="outlook_bridge", bridge_called=True)
    original_count = len(items)
    limit = request["result_char_limit"]
    known_reasons = {"folder_limit", "scan_limit", "time_limit", "result_limit", "folder_access_failed",
                     "protected_items_excluded", "items_access_unverified", "body_char_limit",
                     "total_body_char_limit", "attachment_metadata_limit", "result_char_limit",
                     "unrequested_body_excluded", "restricted_content_excluded"}
    supplied_reasons = result.get("partial_reasons", [])
    reasons = list(dict.fromkeys(reason for reason in supplied_reasons
                               if isinstance(reason, str) and reason in known_reasons)) if isinstance(supplied_reasons, list) else []
    # Bound the original envelope as well as the fallback. Even known reason
    # codes must not expand it by repeating thousands of times.
    if "partial_reasons" in result:
        result["partial_reasons"] = reasons
    budget = {"result_char_limit": limit, "serialization": "ascii_json_indent_2_including_newline",
              "returned_count": original_count, "omitted_count": 0, "body_chars_returned": 0,
              "truncated": False}
    if operation == "read":
        budget.update(body_char_limit=request["body_char_limit"], total_body_char_limit=request["total_body_char_limit"])
    result["output_budget"] = budget

    def partial(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
        result["partial_reasons"] = reasons
        result["complete"] = False
        if result.get("status", "ok") in {"ok", "partial"}:
            result.update(ok=True, status="partial", message=_MESSAGES["partial"])
        budget["truncated"] = True

    # Preserve protection evidence even when the corresponding long-ID row must
    # be omitted. Do not downgrade a protection restriction to mere truncation.
    counts = {}
    for item in items:
        code = item.get("code")
        if code not in {"protection_blocked", "protection_unknown", "permission_denied"}:
            if item.get("status") == "blocked" or item.get("protection_status") in {"restricted", "blocked"} or item.get("body_status") == "blocked":
                code = "protection_blocked"
            elif item.get("status") == "permission_denied" or item.get("body_status") == "permission_denied":
                code = "permission_denied"
            elif item.get("protection_status") == "unknown":
                code = "protection_unknown"
        if code in {"protection_blocked", "protection_unknown", "permission_denied"}:
            item["code"] = code
            counts[code] = counts.get(code, 0) + 1
        if (code in {"protection_blocked", "protection_unknown", "permission_denied"}
                or item.get("status") in {"blocked", "permission_denied", "unknown"}
                or item.get("body_status") in {"blocked", "permission_denied", "unknown"}):
            # A malformed/mismatched helper response must not carry protected
            # content under Body, HTML, attachment or any unexpected field.
            # Keep only identity and fixed restriction evidence, never metadata
            # that the normal helper already refuses to read for this item.
            safe_fields = {"store_id", "entry_id", "status", "protection_status", "code", "message", "body_status"}
            omitted = any(key not in safe_fields for key in item)
            for key in list(item):
                if key not in safe_fields:
                    item.pop(key)
            if omitted:
                partial("restricted_content_excluded")
    for warning in result.get("restriction_warnings", []):
        if isinstance(warning, dict) and warning.get("code") in {"protection_blocked", "protection_unknown", "permission_denied"}:
            count = warning.get("count", 0)
            if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 2000:
                counts[warning["code"]] = max(counts.get(warning["code"], 0), count)
    if counts:
        result["restriction_warnings"] = [{"code": code, "count": count} for code, count in sorted(counts.items())]

    remaining = request.get("total_body_char_limit", 0)
    for item in items:
        body = item.get("body")
        if body is not None:
            if operation != "read" or not request.get("include_body") or not isinstance(body, str):
                item.pop("body", None)
                item["body_status"] = "not_requested"
                partial("unrequested_body_excluded")
                continue
            take = min(len(body), request["body_char_limit"], remaining)
            if take < len(body):
                item["body"] = body[:take]
                item["body_truncated"] = True
                if take == 0:
                    item["body_status"] = "omitted_body_budget"
                partial("total_body_char_limit" if remaining < min(len(body), request["body_char_limit"]) else "body_char_limit")
            remaining -= take
        if item.get("body_truncated"):
            partial("total_body_char_limit" if item.get("body_status") == "omitted_total_body_limit" else "body_char_limit")
        if item.get("attachments_truncated"):
            partial("attachment_metadata_limit")

    def size() -> int:
        budget.update(returned_count=len(items), omitted_count=original_count - len(items),
                      body_chars_returned=sum(len(item.get("body", "")) for item in items if isinstance(item.get("body", ""), str)))
        if "body_chars_returned" in result:
            result["body_chars_returned"] = budget["body_chars_returned"]
        return len(json.dumps(result, ensure_ascii=True, indent=2)) + 1

    if size() > limit:
        partial("result_char_limit")
        # Attachment count remains useful; filenames are not needed to select
        # the relevant message and never justify dropping its body first.
        for item in reversed(items):
            if size() <= limit:
                break
            if item.pop("attachments", None):
                item["attachments_truncated"] = True
                partial("attachment_metadata_limit")
        for item in reversed(items):
            if size() <= limit:
                break
            body = item.get("body", "")
            if not body:
                continue
            item["body_truncated"] = True
            item["body_status"] = "partial_output_limit"
            # Largest prefix fitting the complete final envelope, not a guessed
            # bytes-per-character ratio (Korean/emoji JSON escapes differ).
            low, high = 0, len(body)
            while low < high:
                middle = (low + high + 1) // 2
                item["body"] = body[:middle]
                if size() <= limit:
                    low = middle
                else:
                    high = middle - 1
            item["body"] = body[:low]
        while items and size() > limit:
            items.pop()
        if size() > limit:
            # Unusually large envelope metadata is not echoed or partially
            # serialized. Preserve fixed restriction and coverage information.
            result = _result("partial", reason="result_char_limit", items=[], complete=False,
                             coverage="response_omitted_by_output_budget", partial_reasons=reasons,
                             restriction_warnings=[{"code": code, "count": count} for code, count in sorted(counts.items())],
                             output_budget=budget, stage="outlook_bridge", bridge_called=True)
        size()
    return result


def _invoke(operation: str, spec: dict) -> dict:
    if os.name != "nt" or not HELPER.is_file():
        return _result("connection_required", reason="classic_outlook_bridge_unavailable", stage="bridge_preflight", bridge_called=False)
    try:
        powershell = windows_powershell()
    except (OSError, ValueError):
        return _result("connection_required", reason="windows_powershell_unavailable", stage="bridge_preflight", bridge_called=False)
    payload = json.dumps(spec, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(payload) > _MAX_INPUT:
        return _result("invalid_request", reason="request_limit", stage="request_validation", bridge_called=False)
    try:
        process = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(HELPER),
             "-Operation", operation], input=payload, capture_output=True, timeout=_READ_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
        if process.returncode or len(process.stdout) > _MAX_OUTPUT:
            return _result("connection_required", reason="bridge_unavailable_or_policy_blocked", stage="outlook_bridge", bridge_called=True)
        response = json.loads(process.stdout.decode("utf-8-sig"))
        if not isinstance(response, dict) or response.get("status") not in _MESSAGES:
            return _result("unknown", reason="invalid_bridge_response", stage="outlook_bridge", bridge_called=True)
        status = response.pop("status")
        # Helper-owned data cannot override this adapter's safety/identity claims.
        for key in ("ok", "message", "read_only", "sending_supported", "identity_assurance", "external_drm", "drm_notice"):
            response.pop(key, None)
        items = response.get("items", [])
        if not isinstance(items, list) or len(items) > 50 or any(not isinstance(item, dict) for item in items):
            return _result("unknown", reason="invalid_bridge_response", stage="outlook_bridge", bridge_called=True)
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
        response["stage"] = "outlook_bridge"
        response["bridge_called"] = True
        return _result(status, **response)
    except subprocess.TimeoutExpired:
        return _result("unknown", reason="outlook_timeout_no_automatic_retry", stage="outlook_bridge", bridge_called=True)
    except OSError:
        return _result("connection_required", reason="bridge_launch_failed", stage="bridge_preflight", bridge_called=False)
    except (UnicodeError, ValueError, TypeError):
        # Exception text may contain mailbox names, subjects, or local paths.
        return _result("unknown", reason="bridge_read_failed", stage="outlook_bridge", bridge_called=True)


def capabilities() -> dict:
    """List running Classic Outlook account/store metadata; no message reads."""
    return _invoke("capabilities", {})


def search_mail(spec: dict) -> dict:
    """Bounded subject/sender/date search, never body or attachment extraction."""
    try:
        request = _normalize_spec("search", spec)
    except (ValueError, TypeError, OverflowError, OSError) as error:
        return _validation_error(error)
    assumptions = request.pop("_date_assumptions", [])
    result = _invoke("search", request)
    result["search_scope"] = {
        "received_after_inclusive": request["received_after"],
        "received_before_exclusive": request["received_before"],
        "query_fields": ["subject", "sender_name", "sender_address"],
        "body_searched": False, "query_matching": "literal_substring_case_insensitive",
        "selected_store_count": len(request["store_ids"]),
        "limit": request["limit"], "scan_limit": request["scan_limit"],
        "folder_limit": request["folder_limit"], "timezone_assumptions": assumptions,
    }
    return _bounded_result(result, request, "search")


def read_mail(spec: dict) -> dict:
    """Read selected refs; body requires explicit request AND caller guard grant."""
    try:
        request = _normalize_spec("read", spec)
    except PermissionError:
        return _result("permission_denied", reason="body_policy_approval_required", stage="request_validation", bridge_called=False)
    except (ValueError, TypeError) as error:
        return _validation_error(error)
    result = _invoke("read", request)
    result["read_scope"] = {"requested_count": len(request["message_refs"]),
                            "body_requested": request["include_body"], "attachments": "metadata_only",
                            "coverage": "selected_message_refs_only"}
    return _bounded_result(result, request, "read")
