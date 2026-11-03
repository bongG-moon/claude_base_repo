"""Compatibility entry for old Read-hook launchers, using the selected Python.

Valid Read requests leave native permissions unchanged and do no state lookup.
Malformed input and unsupported Python use the existing launcher only once.
The current core payload no longer installs or runs this compatibility entry.
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
    # All Read requests use Claude's normal model and permission behavior. This
    # empty response is not an allow grant. PostToolUse still observes skill reads.
    print('{}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
