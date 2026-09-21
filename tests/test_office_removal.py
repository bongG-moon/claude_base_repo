"""The removed built-in reader must not disable shared business workflows."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "company-agent-plugin"
sys.path.insert(0, str(PLUGIN / "scripts"))

from company_agent import business_artifacts, business_files, business_mail, business_safety
from company_agent.cli import build_parser
from company_agent.skill_registry import inventory_skills
from company_agent.state import load_session


class OfficeRemovalTests(unittest.TestCase):
    def test_office_read_is_no_longer_a_business_command(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as failure:
            build_parser().parse_args(["business", "office-read", "--file", "example.xlsx"])
        self.assertEqual(2, failure.exception.code)
        self.assertIn("invalid choice", error.getvalue())

    def test_reader_skill_and_runtime_are_not_shipped(self):
        skill = PLUGIN / "skills" / "office-reader"
        self.assertFalse(skill.exists())
        for relative in (
            "Read-CompanyExcel.py", "Read-CompanyOffice.py",
            "company_agent/office_reader.py", "company_agent/office_consent.py",
            "company_agent/office_progress.py", "company_agent/office_structure.py",
            "company_agent/office_pywin32.py", "company_agent/excel_xlwings.py",
        ):
            with self.subTest(path=relative):
                self.assertFalse((PLUGIN / "scripts" / relative).exists())

    def test_shared_mail_file_and_presentation_entrypoints_survive(self):
        parser = build_parser()
        for action, options, implementation in (
            ("files-plan", ["--folder", "example"], business_files.create_plan),
            ("mail-read", ["--spec", "mail.json"], business_mail.read_mail),
            ("ppt", ["--spec", "slides.json", "--output", "slides.html"], business_artifacts.create_ppt),
        ):
            with self.subTest(action=action):
                self.assertEqual(action, parser.parse_args(["business", action, *options]).business_action)
                self.assertTrue(callable(implementation))

    @unittest.skipUnless(sys.platform == "win32", "Local confirmation is Windows-only.")
    def test_shared_confirmation_still_requires_explicit_approval(self):
        for response, expected in (("true", True), ("false", False), ('"true"', False)):
            completed = subprocess.CompletedProcess([], 0, '{"approved":' + response + '}')
            with self.subTest(response=response), \
                    patch.object(business_safety, "windows_powershell", return_value=Path("powershell.exe")), \
                    patch.object(business_safety.subprocess, "run", return_value=completed):
                self.assertEqual(expected, business_safety.confirm_action("Confirm", "Selected action"))
        self.assertEqual("protection_blocked", business_safety.blocked_input({"protection": "protected"})["code"])


class OfficeRemovalWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "state"
        self.project = self.root / "project"
        self.claude = self.root / "claude"
        self.project.mkdir()
        (self.project / "CLAUDE.md").write_text("Isolated removal regression fixture.\n", encoding="utf-8")
        environment = patch.dict(os.environ, {
            "COMPANY_AGENT_USER_STATE": str(self.state),
            "COMPANY_AGENT_KNOWLEDGE_BASE": str(self.root / "knowledge"),
            "COMPANY_AGENT_MANAGED_CONFIG": str(self.root / "managed.json"),
            "COMPANY_AGENT_PYTHON": sys.executable,
            "COMPANY_AGENT_SCOPE": "User",
            "CLAUDE_CONFIG_DIR": str(self.claude),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "LOCALAPPDATA": str(self.root / "local"),
            "APPDATA": str(self.root / "roaming"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.session = "office-removal-workflow"
        self.prompt_number = 0

    def hook(self, event, **fields):
        import native_entry

        payload = {"hook_event_name": event, "session_id": self.session,
                   "cwd": str(self.project), **fields}
        output = io.StringIO()
        # The registration gate is isolated; the real event handlers, registry,
        # routing, preparation and load receipts run against temporary state.
        with patch.object(native_entry, "configure_runtime", return_value=True), \
                patch.object(sys, "argv", ["native_entry.py", "--event", event]), \
                patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, native_entry.main())
        result = json.loads(output.getvalue())
        self.assertNotIn("systemMessage", result, result)
        return result

    def prompt(self, text):
        self.prompt_number += 1
        result = self.hook("UserPromptSubmit", prompt=text, prompt_id=f"prompt-{self.prompt_number}")
        lines = result["hookSpecificOutput"]["additionalContext"].splitlines()
        runtime = next(json.loads(line)["company_agent_runtime"] for line in lines
                       if line.startswith('{"company_agent_runtime":'))
        return runtime, result

    def add_reader(self, source):
        name = "personal-document-reader" if source == "user" else "project-document-reader"
        base = self.claude if source == "user" else self.project / ".claude"
        file = base / "skills" / name / "SKILL.md"
        file.parent.mkdir(parents=True)
        file.write_text(f"---\nname: {name}\ndescription: PPT PowerPoint XLSX Excel 문서를 읽고 요약합니다.\n"
                        "---\nRead only the user-selected document using the team's approved integration.\n",
                        encoding="utf-8")
        return name, file

    def candidate_names(self, result):
        return [json.loads(line)["name"]
                for line in result["hookSpecificOutput"]["additionalContext"].splitlines()
                if line.startswith('{"name":')]

    def load_skill(self, file):
        self.hook("PostToolUse", tool_name="Read", tool_input={"file_path": str(file)},
                  tool_response={"file": {"content": file.read_text(encoding="utf-8"), "startLine": 1}})
        route = load_session(self.session, self.state)["skillWorkflow"]
        self.assertEqual("loaded", route["loadObservation"]["status"])
        self.assertEqual(file, Path(route["selected"]["path"]))
        return route

    def test_shipped_inventory_and_document_requests_do_not_require_removed_reader(self):
        inventory = inventory_skills(self.state, project_root=self.project,
                                     plugin_root=PLUGIN, claude_root=self.claude)
        self.assertTrue(inventory["complete"], inventory.get("warnings"))
        company_names = {item["name"] for item in inventory["skills"] if item["source"] == "company"}
        self.assertIn("html-report", company_names)
        self.assertNotIn("office-reader", company_names)
        for filename in ("report.pptx", "table.xlsx"):
            with self.subTest(filename=filename):
                runtime, result = self.prompt(f"@{filename} 원본은 변경하지 말고 내용 읽어줘")
                self.assertEqual([], self.candidate_names(result))
                self.assertNotIn(runtime["skillExecution"]["mode"], {"load", "reuse"})
                responses = [result]
                for session in (self.session, ""):
                    for tool, inputs in (
                        ("Read", {"file_path": str(self.project / filename)}),
                        ("Bash", {"command": f'python approved_reader.py --file "{filename}"'}),
                    ):
                        response = self.hook("PreToolUse", session_id=session, tool_name=tool, tool_input=inputs)
                        self.assertNotIn("permissionDecision", response.get("hookSpecificOutput", {}))
                        responses.append(response)
                serialized = json.dumps(responses, ensure_ascii=False)
                for removed in ("office-reader", "office-read", "officeReadCommand",
                                "office_read_consent", "conversation_session_required",
                                "승인 답변을 연결할 대화 정보", "후크 JSON의 현재 대화 ID"):
                    self.assertNotIn(removed, serialized)

    def assert_custom_reader_loads(self, source):
        name, file = self.add_reader(source)
        runtime, result = self.prompt("PPT와 XLSX 문서를 읽고 요약해줘")
        self.assertEqual([name], self.candidate_names(result))
        execution = runtime["skillExecution"]
        self.assertEqual(("load", name, source), (execution["mode"], execution["name"], execution["source"]))
        self.assertEqual(file, Path(execution["path"]))
        self.assertEqual(name, self.load_skill(file)["selected"]["name"])
        response = self.hook("PreToolUse", tool_name="Bash",
                             tool_input={"command": 'python approved_reader.py --file "report.pptx"'})
        self.assertNotIn("permissionDecision", response.get("hookSpecificOutput", {}))

    def test_user_document_reader_can_be_discovered_and_loaded(self):
        self.assert_custom_reader_loads("user")

    def test_project_document_reader_can_be_discovered_and_loaded(self):
        self.assert_custom_reader_loads("project")

    def test_document_read_followed_by_html_creation_selects_real_report_skill(self):
        name, reader = self.add_reader("user")
        first, _ = self.prompt("PPT 내용을 읽어줘")
        self.assertEqual(name, first["skillExecution"]["name"])
        self.load_skill(reader)
        followup, _ = self.prompt("읽은 내용을 HTML 보고서로 만들어줘")
        execution = followup["skillExecution"]
        self.assertEqual(("load", "html-report", "company"),
                         (execution["mode"], execution["name"], execution["source"]))
        report = PLUGIN / "skills" / "html-report" / "SKILL.md"
        self.assertEqual(report, Path(execution["path"]))
        self.assertEqual("html-report", self.load_skill(report)["selected"]["name"])


if __name__ == "__main__":
    unittest.main()
