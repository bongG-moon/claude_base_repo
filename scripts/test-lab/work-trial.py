"""Independent real-work Claude sessions, with native history/resume.

No fixed test prompts or expected answers. Operators own their task inputs and
approve only bounded commands after inspecting them. This is not an OS sandbox.
Normal Claude authentication is reused, never copied. No native plugin install.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
TRIALS = Path("C:/Users/qkekt/Desktop/Company-Agent-Work-Trials-20260912")
CLAUDE = Path("C:/nvm4w/nodejs/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
PYTHON = Path("C:/Python313/python.exe")
PS = "C:/Windows/system32/WindowsPowerShell/v1.0/powershell.exe"


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def boundary(root: Path) -> Path:
    root = root.absolute()
    if root.parent != TRIALS or root.name not in {"worker-one", "worker-two", "worker-three", "controller-smoke"}:
        raise ValueError("Use one explicit independent trial directory")
    for path in [root, *root.parents]:
        if path.exists() and (path.is_symlink() or path.is_junction()):
            raise ValueError("Redirected trial directory")
    return root


def plugin_copy(target: Path):
    shutil.copytree(REPO / "company-agent-plugin", target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "company-agent-install.json"))


def initialize(root: Path):
    # Operators may have already prepared workspace inputs. Never replace them.
    if any((root / name).exists() for name in ("trial.json", "plugin", "state")):
        raise ValueError("Trial is already initialized; use run or refresh")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("workspace", "operator", "state", "evidence"):
        (root / name).mkdir(exist_ok=True)
    (root / "state" / "tmp").mkdir()
    plugin_copy(root / "plugin")
    shutil.copytree(REPO / "corporate-knowledge", root / "knowledge")
    save(root / "empty-mcp.json", {"mcpServers": {}})
    save(root / "trial.json", {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
                              "plugin": "plugin", "conversations": {}, "nativeInstall": False})


def refresh(root: Path):
    meta = read(root / "trial.json")
    target = "plugin-" + uuid.uuid4().hex[:8]
    plugin_copy(root / target)
    meta["plugin"] = target
    save(root / "trial.json", meta)
    print(json.dumps({"plugin": target, "workspaceAndStatePreserved": True}))


def selected_plugin(root: Path, meta: dict) -> Path:
    name = meta.get("plugin", "")
    if not isinstance(name, str) or not re.fullmatch(r"plugin(?:-[a-f0-9]{8})?", name):
        raise ValueError("Invalid trial plugin selection")
    target = root / name
    if not target.is_dir() or target.is_symlink() or target.is_junction() or target.resolve().parent != root.resolve():
        raise ValueError("Trial plugin must be one owned snapshot")
    return target


def quoted(value: str):
    return [value, '"' + value + '"', "'" + value + "'"]


def path_rule(path: Path) -> str:
    value = path.as_posix()
    return "//" + value[0].lower() + value[2:] if value[1:3] == ":/" else "/" + value


def rules(root: Path, plugin: Path) -> list[str]:
    allow = [*(f"Read({path_rule(directory)}/**)" for directory in (root / "workspace", root / "state", plugin, root / "knowledge")), f"Edit({path_rule(root / 'workspace')}/**)",
             f"Edit({path_rule(root / 'state' / 'tmp')}/**)", "Glob", "Grep", "Skill",
             *(f"Agent(company-agent:{tier}-worker)" for tier in ("small", "medium", "large"))]
    # Internal bookkeeping only, not arbitrary Python, shell, corporate tools,
    # asset execution or external writes. Approvals for business artifacts are
    # exact commands supplied by the operator after inspection, below.
    operations = ["memory search", "memory upsert", "session status", "session verify",
                  "learning status", "learning stage", "learning review", "work checkpoint", "work resolve",
                  "skill list", "skill search", "skill inventory", "skill conflicts", "skill resolve", "context audit"]
    prefixes = []
    for program, script in itertools.product(quoted(PS), quoted((plugin / "scripts" / "Invoke-CompanyAgent.ps1").as_posix())):
        prefixes.append(f"{program} -NoLogo -NoProfile -ExecutionPolicy Bypass -File {script} -Mode Cli")
    for program, script in itertools.product(quoted(PYTHON.as_posix()), quoted((plugin / "scripts" / "harness_cli.py").as_posix())):
        prefixes.append(f"{program} -B {script}")
    for prefix, operation in itertools.product(prefixes, operations):
        allow.append(f"Bash({prefix} {operation} *)")
    approvals = root / "operator" / "approved-commands.json"
    if approvals.exists():
        extra = read(approvals)
        if not isinstance(extra, list) or not all(isinstance(x, str) and 0 < len(x) < 8192 for x in extra):
            raise ValueError("approved-commands must be a list of inspected exact commands")
        for command in extra:
            if any(c in command for c in "\r\n\0*?`$"):
                raise ValueError("No wildcard/expansion/multiline command approvals")
            allow.append("Bash(" + command + ")")
    return allow


def hashes(config: Path):
    return {name: hashlib.sha256((config / name).read_bytes()).hexdigest()
            for name in ("settings.json", "plugins/installed_plugins.json") if (config / name).is_file()}


def run(root: Path, prompt_path: Path, conversation: str, timeout: int):
    prompt_path = prompt_path.resolve()
    if not prompt_path.is_relative_to(root / "operator"):
        raise ValueError("Operator prompts must be inside this trial's operator directory")
    prompt = prompt_path.read_text(encoding="utf-8-sig")
    if not prompt.strip() or len(prompt) > 32768:
        raise ValueError("Provide a nonempty operator request of at most 32768 characters")
    meta = read(root / "trial.json")
    plugin, state, workspace = selected_plugin(root, meta), root / "state", root / "workspace"
    existing = meta["conversations"].get(conversation)
    sid = existing["sessionId"] if existing else str(uuid.uuid4())
    turn = existing["turns"] + 1 if existing else 1
    out = root / "evidence" / (conversation + "-" + str(turn).zfill(2) + "-" + uuid.uuid4().hex[:6])
    out.mkdir()
    settings = {"permissions": {"allow": rules(root, plugin), "deny": [f"Read({path_rule(root / 'operator')}/**)", f"Read({path_rule(root / 'evidence')}/**)"]}, "enabledPlugins": {}, "autoMemoryEnabled": False}
    settings_path = out / "settings.json"
    save(settings_path, settings)
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    before = hashes(config)
    current = read(config / "settings.json") if (config / "settings.json").exists() else {}
    env = os.environ.copy()
    env.update({"COMPANY_AGENT_USER_STATE": str(state), "COMPANY_AGENT_KNOWLEDGE_BASE": str(root / "knowledge"),
                "COMPANY_AGENT_PYTHON": str(PYTHON), "COMPANY_AGENT_SCOPE": "IndependentWorkTrial",
                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "DISABLE_AUTOUPDATER": "1"})
    args = [str(CLAUDE), "-p", "--output-format", "stream-json", "--verbose", "--include-hook-events",
            "--setting-sources", "", "--settings", str(settings_path), "--plugin-dir", str(plugin),
            "--strict-mcp-config", "--mcp-config", str(root / "empty-mcp.json"), "--no-chrome",
            "--add-dir", str(state), "--permission-mode", "manual", "--permission-prompts", "none",
            "--max-budget-usd", "3", "--tools", "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent",
            "--append-system-prompt", f"Authorized independent work trial. Use only synthetic work material under {workspace.as_posix()} and the active harness state {state.as_posix()}. Do not read operator/evidence folders or other users' tasks. Do not use real mail/DB, send messages, weaken permissions/security, install plugins globally or modify actual user configuration. Tool approvals are limited; if denied explain the exact blocked operation and await the operator, without a substitute bypass. Existing harness instructions apply normally. No task answers or success records are preloaded.",
            "--resume" if existing else "--session-id", sid]
    if isinstance(current.get("model"), str):
        args.extend(["--model", current["model"]])
    save(out / "request.json", {"prompt": prompt, "sessionId": sid, "nativeResume": bool(existing),
                               "conversation": conversation, "turn": turn, "plugin": str(plugin)})
    started = time.monotonic()
    with (out / "events.jsonl").open("wb") as stdout, (out / "stderr.txt").open("wb") as stderr:
        process = subprocess.Popen(args, cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            process.communicate(prompt.encode("utf-8"), timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            process.wait(timeout=15)
            timed_out = True
    events = []
    for line in (out / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    init = next((x for x in events if x.get("type") == "system" and x.get("subtype") == "init"), {})
    result = next((x for x in reversed(events) if x.get("type") == "result"), {})
    if init:
        meta["conversations"][conversation] = {"sessionId": init.get("session_id", sid), "turns": turn}
        save(root / "trial.json", meta)
    summary = {"conversation": conversation, "turn": turn, "sessionId": init.get("session_id"),
               "nativeResume": bool(existing), "elapsedSeconds": round(time.monotonic() - started, 2),
               "exitCode": process.returncode, "timeout": timed_out, "resultType": result.get("subtype"),
               "result": result.get("result"), "permissionDenials": result.get("permission_denials", []),
               "model": init.get("model"), "costUsd": result.get("total_cost_usd"),
               "originalConfigHashesUnchanged": before == hashes(config), "evidence": str(out)}
    save(out / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "run", "refresh"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--conversation", default="main")
    parser.add_argument("--timeout", type=int, default=180)
    options = parser.parse_args()
    root = boundary(options.root)
    if not options.conversation.replace("-", "").isalnum() or len(options.conversation) > 60:
        parser.error("Use a short alphanumeric conversation name")
    if options.action == "init":
        initialize(root)
    elif options.action == "refresh":
        refresh(root)
    elif not options.prompt_file:
        parser.error("--prompt-file is required for run")
    else:
        run(root, options.prompt_file, options.conversation, min(300, max(30, options.timeout)))
