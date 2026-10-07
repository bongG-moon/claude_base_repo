"""Installed Read-only fast path, using the interpreter selected by setup.

No document, settings, catalogue or session is read on the ordinary path.
Routing interventions and malformed input go through the existing launcher,
including its current runtime-selection and installed-scope checks. Never
retry after that launcher has run. Keep this entry compatible with old Python
syntax so an interpreter replaced in place can reach the normal recovery path.
"""
import json
import os
import subprocess
import sys


def fallback(payload):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Invoke-CompanyAgent.ps1")
    # Use Windows' existing launcher, not a shell command assembled from input.
    executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        result = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script, "-Mode", "Hook", "-Event", "PreToolUse"],
            input=payload.encode("utf-8"), check=False,
        )
        return result.returncode
    except OSError:
        # No raw payload, file path or credentials in a launcher diagnostic.
        print("Company Harness 읽기 준비를 실행하지 못했습니다. 설치를 다시 적용해 주세요.", file=sys.stderr)
        return 2


def main():
    payload = sys.stdin.read()
    if sys.version_info[0] != 3 or sys.version_info[:2] < (3, 11):
        return fallback(payload)
    try:
        value = json.loads(payload)
        valid = (isinstance(value, dict) and value.get("tool_name") == "Read"
                 and isinstance(value.get("tool_input"), dict)
                 and isinstance(value["tool_input"].get("file_path"), str)
                 and bool(value["tool_input"]["file_path"].strip()))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        return fallback(payload)
    try:
        # Also works with an embeddable interpreter's isolated ._pth.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from company_agent.vision_routing import preflight
        result = preflight(value)
    except Exception:
        return fallback(payload)
    if result == {}:
        # An empty result leaves native permissions intact. This is NOT allow.
        print("{}")
        return 0
    return fallback(payload)


if __name__ == "__main__":
    sys.exit(main())
