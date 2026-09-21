"""Verify the portable UI bundle matches current source and contains no state."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[2]
version = json.loads((root / "company-agent-plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
parser = argparse.ArgumentParser()
parser.add_argument("bundle", type=Path)
args = parser.parse_args()
count = 0
expected = {"Company-Workspace.vbs", "deploy/Start-CompanyWorkspace.ps1", "docs/LOCAL_WORKSPACE.md",
            "docs/SKILL_PRIORITY.md", "docs/AUDIT_HARNESS_2026-09-20.md",
            "docs/README.md", "docs/CLAUDE_CODE_BASICS.md",
            "docs/COMPANY_AGENT_HANDBOOK.md", "docs/ONBOARDING_COURSE.md",
            "docs/Company-Agent-Handbook.html", "docs/Company-Agent-Onboarding.html",
            "docs/Company-Agent-Guide.html", "docs/Company-Agent-사용자-안내서.html", "docs/Claude-Code-필수-사용법.html",
            "docs/USER_GUIDE.md", "docs/CLAUDE_CODE_COMMANDS.md", f"docs/UPDATE_{version}.md", "docs/VALIDATION_UNIFIED_GUIDE_2026-09-19.md",
            "docs/VALIDATION_OFFICE_PATH_ERRORS_2026-09-21.md",
            "docs/VALIDATION_EXECUTION_FLOW_2026-09-21.md",
            "docs/VALIDATION_BEGINNER_WORKSPACE_2026-09-19.md",
            "docs/VALIDATION_AUDIT_FIXES_2026-09-19.md",
            "docs/UPDATE_1.4.16.md", "docs/VALIDATION_RESOURCE_SCOPES_2026-09-19.md",
            "docs/VALIDATION_HARNESS_MAP_2026-09-19.md",
            "local_app/__init__.py", "local_app/bridge.py", "local_app/server.py", "local_app/demo.py",
            "local_app/companion.py", "local_app/harness_client.py", "local_app/history.py", "local_app/html_preview.py", "company-agent-plugin/resources/onboarding-course.json",
            "local_app/Pick-Path.ps1", "local_app/Invoke-TerminalClaude.ps1",
            "local_app/web/index.html", "local_app/web/app.css", "local_app/web/app.js", "local_app/web/companion.js"}
seen = set()
with zipfile.ZipFile(args.bundle) as bundle:
    for entry in bundle.infolist():
        if entry.is_dir():
            continue
        name = entry.filename.replace("\\", "/")
        assert name.startswith("Company-Workspace/"), name
        relative = name.removeprefix("Company-Workspace/")
        assert relative in expected and relative not in seen, name
        seen.add(relative)
        assert ".." not in Path(relative).parts and not relative.startswith("/"), name
        assert not any(part in {"__pycache__", "history.json", "runtime.json", ".env", ".claude"} for part in Path(relative).parts), name
        source = root / relative
        assert source.is_file(), name
        assert bundle.read(entry) == source.read_bytes(), "Stale bundle content: " + name
        count += 1
    assert seen == expected, expected - seen
print(f"Verified {count} source-identical files; no runtime state or credentials bundled.")
print("SHA256: " + hashlib.sha256(args.bundle.read_bytes()).hexdigest())
