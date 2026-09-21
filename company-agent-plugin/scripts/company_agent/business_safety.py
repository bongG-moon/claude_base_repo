"""Shared, conservative business-tool boundaries. Not a DRM bypass or OS sandbox."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any


def _protection_denial(message: str) -> bool:
    """A DRM label, path or troubleshooting advice is not an access decision."""
    return bool(re.search(
        r'\b(?:protection_blocked|drm_blocked)\b|'
        r'\b(?:drm|irm|rights management)(?:[: ]+(?:access|protection|is|was|has been)){0,4}[: ]+(?:blocked|denied|restricted)\b|'
        r'\b(?:blocked|denied|restricted) (?:by|due to) (?:drm|irm|rights management)\b|'
        r'(?:DRM|IRM|보호 설정|권한 관리)[^\r\n]{0,40}(?:차단|거부|제한)(?:되었|됐|됨)',
        message, re.I))


def windows_powershell() -> Path:
    if os.name != "nt":
        raise OSError("Windows is required.")
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError("Windows system directory is unavailable.")
    executable = Path(buffer.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not executable.is_absolute() or not executable.is_file():
        raise OSError("Windows PowerShell is unavailable.")
    return executable


def safe_path(value: str | Path, *, exists: bool = False) -> Path:
    """Reject links/reparse ancestors before resolving, including output parents."""
    path = Path(os.path.abspath(os.fspath(value)))
    if os.name == "nt" and (str(path).startswith("\\\\") or ":" in str(path)[2:]):
        raise ValueError("Network/device paths and alternate data streams are not supported.")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked folders and reparse points are not supported.")
    if exists and not path.exists():
        raise ValueError("The selected path no longer exists.")
    return path


def failure_result(exc: BaseException, *, item: str = "선택한 항목") -> dict[str, Any]:
    # Inspect error text locally; never return Office error text/body/addresses.
    message = str(exc).lower()
    protected = _protection_denial(message)
    denied = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 5 or any(
        word in message for word in ("access denied", "access is denied", "permission denied", "접근이 거부", "액세스가 거부"))
    code = "protection_blocked" if protected else "permission_denied" if denied else "operation_failed"
    reason = "보호 설정" if protected else "접근 권한" if denied else "작업 오류"
    return {"ok": False, "status": "blocked" if protected or denied else "failed", "code": code,
            "message": f"{item}은(는) {reason} 때문에 처리하지 못했습니다.",
            "retryAllowed": not (protected or denied), "rawContentStored": False}


def protection_notice(payload: Any) -> str:
    """Bounded hint for hook error/results; no document content echoed."""
    if not isinstance(payload, dict):
        return ""
    codes = {"protection_blocked", "permission_denied", "drm_blocked", "protected_or_unsupported", "protection_unknown", "protected_input"}
    def decode_result(value: str):
        # Bash errors can contain exit/progress lines before the CLI's final
        # JSON. Parse only a complete terminal object, never arbitrary document
        # fragments. Typed results take precedence over words in their message.
        text = value.strip()
        try:
            return json.loads(text)
        except (ValueError, TypeError, RecursionError):
            start = text.rfind('\n{')
            if start < 0:
                return None
            try:
                result = json.loads(text[start + 1:])
            except (ValueError, TypeError, RecursionError):
                return None
            if (isinstance(result, dict) and type(result.get('ok')) is bool
                    and isinstance(result.get('code'), str)):
                return result
        return None

    def restricted(value: Any, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(value, dict):
            if isinstance(value.get("code"), str) and value["code"] in codes:
                return True
            # MCP error blocks are operational errors, unlike ordinary result
            # content. Read text only when the envelope explicitly says error.
            content = value.get('content')
            if value.get('isError') is True and isinstance(content, list):
                if any(restricted_error(block.get('text'), depth + 1)
                       for block in content[:100] if isinstance(block, dict) and block.get('type') == 'text'):
                    return True
            return any(restricted(v, depth + 1) for k, v in list(value.items())[:100]
                       if k not in {"body", "subject", "contentHtml", "text", "content", "structure",
                                    "tool_input", "message", "instruction"})
        if isinstance(value, list):
            return any(restricted(v, depth + 1) for v in value[:500])
        if isinstance(value, str) and len(value) <= 2 * 1024 * 1024:
            parsed = decode_result(value)
            if parsed is not None:
                return restricted(parsed, depth + 1)
        return False
    def restricted_error(value: Any, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(value, dict):
            if restricted(value, depth):
                return True
            # Only typed business results own the meaning of their code.
            # Their recovery advice is not an access decision. Generic JSON
            # errors may carry the actual denial in an error/message field.
            if type(value.get('ok')) is bool and isinstance(value.get('code'), str):
                return False
            return any(restricted_error(v, depth + 1) for k, v in list(value.items())[:100]
                       if k in {'error', 'tool_error', 'message', 'stderr', 'exception', 'cause', 'detail'})
        if isinstance(value, list):
            return any(restricted_error(v, depth + 1) for v in value[:500])
        if isinstance(value, str) and len(value) <= 2 * 1024 * 1024:
            parsed = decode_result(value)
            if parsed is not None:
                return restricted_error(parsed, depth + 1)
            error = value[:10000].lower()
            return _protection_denial(error) or any(token in error for token in (
                'access is denied', 'access denied', 'permission denied',
                'permission_denied', '액세스가 거부', '접근이 거부'))
        return False

    raw_error = payload.get("error") or payload.get("tool_error") or ""
    error_restricted = restricted_error(raw_error)
    if restricted(payload.get("tool_response")) or error_restricted:
        return ("보호 설정 또는 접근 제한 신호가 있습니다. 실패한 항목만 중단하고, 허용된 항목은 계속 처리하세요. "
                "본문 조회 성공은 첨부 조회 성공이 아닙니다. 첨부가 차단되면 '메일 본문은 확인했지만 첨부파일은 보호 설정 때문에 "
                "분석하지 못했습니다. 첨부 내용은 제외하고 요약했습니다.'처럼 실제 확인 범위에 맞게 설명하세요. "
                "필요하면 담당자의 승인된 접근·AI 처리 절차만 안내하세요. 접근 권한은 추출·저장 허가를 뜻하지 않습니다. "
                "보호된 원문을 Memory/Knowledge에 저장하지 마세요.")
    return ""


def confirm_action(title: str, details: str, *, progress=None) -> bool:
    """A real local user click, never an LLM-supplied approved:true flag."""
    if os.name != "nt" or len(details) > 512 * 1024:
        return False
    helper = Path(__file__).resolve().parents[1] / "Confirm-BusinessAction.ps1"
    # Never approve operations omitted from a silently truncated preview.
    request = json.dumps({"title": title[:160], "details": details}, ensure_ascii=True)
    if progress is not None:
        from .office_progress import HelperTimeout, run_helper
        try:
            result = run_helper([str(windows_powershell()), '-NoLogo', '-NoProfile', '-STA', '-File', str(helper)],
                                request.encode('ascii'), timeout=300, startup_timeout=30, progress=progress)
            # An approved JSON without an actual Shown receipt is not approval.
            if not result.ready or result.returncode != 0:
                progress.failure_code = 'confirmation_unavailable'
                return False
            answer = json.loads(result.stdout.decode('utf-8-sig'))
            if not isinstance(answer, dict):
                raise ValueError('invalid confirmation response')
            return answer.get('approved') is True
        except HelperTimeout as exc:
            progress.failure_code = 'confirmation_wait_timeout' if exc.ready else 'confirmation_start_timeout'
        except (OSError, ValueError):
            progress.failure_code = 'confirmation_unavailable'
        return False
    try:
        result = subprocess.run([str(windows_powershell()), "-NoLogo", "-NoProfile", "-STA", "-File", str(helper)],
                                input=request, encoding="utf-8", capture_output=True, timeout=300,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode == 0 and json.loads(result.stdout.lstrip("\ufeff")).get("approved") is True
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def cancelled() -> dict[str, Any]:
    return {"ok": False, "status": "cancelled", "code": "confirmation_required_or_cancelled",
            "message": "사용자 확인이 완료되지 않아 실행하지 않았습니다. 확인 창이 지원되는 현재 Windows 세션에서 다시 요청하세요."}


def blocked_input(spec: dict[str, Any]) -> dict[str, Any] | None:
    """A supplied restriction may tighten policy, never grant extraction rights."""
    if spec.get("protection") in ("protected", "blocked", "unknown"):
        return {"ok": False, "status": "blocked", "code": "protection_blocked",
                "message": "자료의 AI 처리·출력 권한이 확인되지 않아 이 자료의 처리를 중단했습니다. 필요하면 담당자의 승인된 접근·AI 처리 절차를 확인해 주세요.",
                "retryAllowed": False}
    return None
