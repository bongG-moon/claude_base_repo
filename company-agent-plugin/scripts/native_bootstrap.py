"""Validate an interpreter and enter the harness in the same process.

Keep this file compatible with old Python syntax: an unsupported interpreter
must reject the candidate before importing any Company Agent implementation.
"""
import os
import sys


def main():
    if sys.version_info[0] != 3 or sys.version_info[:2] < (3, 11):
        return 78
    marker = sys.argv[1]
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native_entry.py")
    # Automatic installation is disabled while selecting/starting a runtime.
    # Restore the caller's process environment before application code, matching
    # the old wrapper's separation between its probe and actual invocation.
    import json
    environment = json.loads(os.environ.pop("COMPANY_AGENT_BOOTSTRAP_ENV", "{}"))
    for name in ("PYLAUNCHER_ALLOW_INSTALL", "PYLAUNCHER_ALWAYS_INSTALL",
                 "PYTHON_MANAGER_AUTOMATIC_INSTALL", "COMPANY_AGENT_BOOTSTRAP_ENV"):
        if name in environment:
            value = environment[name]
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    os.environ["COMPANY_AGENT_PYTHON"] = sys.executable
    sys.argv = [entry] + sys.argv[2:]
    # The wrapper removes this one invocation-specific line. Once emitted,
    # application errors must be returned unchanged, never trigger a fallback.
    print(marker)
    sys.stdout.flush()
    import runpy
    runpy.run_path(entry, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
