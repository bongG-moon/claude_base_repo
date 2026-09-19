"""A deterministic local child process for transport tests. No network or LLM."""
import json
import os
from pathlib import Path
import sys
import uuid

if "--version" in sys.argv:
    print("test-cli 1.0")
    sys.exit(0)
if "--help" in sys.argv:
    print('--input-format --output-format --setting-sources --permission-prompt-tool "manual"')
    sys.exit(0)
if "--print" in sys.argv and "--verbose" not in sys.argv:
    print("Missing --verbose: shell wrapper consumed a CLI argument", file=sys.stderr)
    sys.exit(2)

session = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--resume=")), str(uuid.uuid4()))
turn = 0


def emit(data):
    sys.stdout.buffer.write((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


for raw in sys.stdin.buffer:
    value = json.loads(raw)
    if value["type"] == "control_request":
        subtype = value["request"]["subtype"]
        emit({"type": "control_response", "response": {"subtype": "success", "request_id": value["request_id"], "response": {}}})
        if subtype == "interrupt":
            break
    elif value["type"] == "user":
        turn += 1
        emit({"type": "system", "subtype": "init", "session_id": session, "model": "fake-only",
              "skills": ["company-agent:office-reader"], "plugins": [{"name": "company-agent"}], "mcp_servers": []})
        text = value["message"]["content"]
        if text == "AUTH_PARITY_CHECK" and os.environ.get("WORKSPACE_FAKE_AUTH") == "1":
            valid = (Path(os.environ["CLAUDE_CONFIG_DIR"]) / "fake-auth.txt").read_text(encoding="utf-8") == "valid"
            emit({"type": "result", "session_id": session, "is_error": not valid,
                  "result": "기존 CLI 인증 사용" if valid else "Failed to authenticate: OAuth session expired and could not be refreshed"})
            continue
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "요청 확인: " + text}]}})
        emit({"type": "control_request", "request_id": "q" + str(turn), "request": {
            "subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": {"questions": [{
                "question": "정리 방식?", "multiSelect": False, "options": [{"label": "간단히"}, {"label": "자세히"}]}]}}})
    elif value["type"] == "control_response":
        response = value["response"]
        detail = response["response"]
        if response["request_id"].startswith("q") and detail["behavior"] == "allow":
            emit({"type": "control_request", "request_id": "p" + str(turn), "request": {
                "subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "FAKE_ONLY", "description": "테스트"}}})
        else:
            emit({"type": "result", "subtype": "success", "session_id": session, "is_error": False,
                  "result": "처리 완료: " + detail["behavior"], "duration_ms": 3, "usage": {"input_tokens": 0, "output_tokens": 0}})
