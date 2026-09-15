"""Actual Windows wrapper -> hooks -> scoped state, without model/Office access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import unittest

import test_native_runtime as native
from company_agent.paths import atomic_write_json
from company_agent.state import load_session


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
class SkillWorkflowNativeTests(native.NativeRuntimeTestBase):
    run_wrapper = native.NativePowerShellTests.run_wrapper

    def setUp(self):
        super().setUp()
        self.plugin = self.root / "plugin copy"
        shutil.copytree(native.PLUGIN, self.plugin, ignore=shutil.ignore_patterns("__pycache__", "runtime"))
        self.record = self.register("project", "Project", self.project)
        atomic_write_json(self.plugin / "company-agent-install.json", {
            "registrationsRoot": str(self.registrations), "knowledgeBaseRoot": str(self.base)})
        self.payload = {"session_id": "native-selection", "cwd": str(self.project)}

    def hook(self, event, **values):
        result = self.run_wrapper(["-Mode", "Hook", "-Event", event], {**self.payload, **values})
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def read(self, file):
        raw = file.read_text(encoding="utf-8-sig")
        self.hook("PostToolUse", tool_name="Read", tool_input={"file_path": str(file)},
                  tool_response={"type": "text", "file": {"filePath": str(file), "content": raw,
                      "startLine": 1, "totalLines": len(raw.splitlines()), "numLines": len(raw.splitlines())}})

    def test_first_prompt_selection_execution_and_silent_list_flow(self):
        self.hook("SessionStart", source="startup")
        result = self.hook("UserPromptSubmit", prompt="기존 PPT 내용을 분석해줘")
        runtime = json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[-1])["company_agent_runtime"]
        self.assertEqual("ready", runtime["skillWorkflow"]["status"])
        self.assertFalse(runtime["skillWorkflow"]["indexRead"])
        self.assertTrue(runtime["skillWorkflow"]["turn"])
        execution = {"tool_name": "Bash", "tool_input": {"command": "python invented_reader.py"}}
        self.assertEqual("deny", self.hook("PreToolUse", **execution)["hookSpecificOutput"]["permissionDecision"])
        self.read(Path(runtime["skillSelection"]["catalog"]["path"]))
        # A plain list lookup is already complete; Stop must not request pass/fail.
        self.assertNotIn("decision", self.hook("Stop"))
        self.read(self.plugin / "skills/office-reader/SKILL.md")
        self.assertEqual({}, self.hook("PreToolUse", **execution))
        state = load_session(self.payload["session_id"], Path(self.record["userStateRoot"]))
        self.assertEqual("office-reader", state["skillWorkflow"]["selected"]["name"])
        self.assertEqual(0, state["mutationCount"])
        # Corporate policy must still run after preparation; never emit allow.
        denied = self.hook("PreToolUse", tool_name="mcp__corp-db-read__query", tool_input={"query": "DELETE FROM employees"})
        self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])
        next_result = self.hook("UserPromptSubmit", prompt="이제 발표 자료를 만들어줘")
        next_runtime = json.loads(next_result["hookSpecificOutput"]["additionalContext"].split("\n")[-1])["company_agent_runtime"]
        self.assertTrue(next_runtime["skillWorkflow"]["indexRead"])
        self.assertIsNone(next_runtime["skillWorkflow"]["selected"])
        self.read(self.plugin / "skills/presentation/SKILL.md")
        self.assertEqual({}, self.hook("PreToolUse", **execution))


if __name__ == "__main__":
    unittest.main()
